"""Power BI -> ThoughtSpot Table TML + naming/type/cardinality helpers.

Ported from the standalone converter (generate_tml.py). Pure functions, no I/O.
Repo invariant: a table TML connection block carries the connection display NAME
only, never a GUID (see .claude/rules/ts-cli.md, the "connection_name" convention).
"""

from __future__ import annotations

import re


_TML_TYPE = {
    "int64": "INT64", "int": "INT64", "integer": "INT64",
    "double": "DOUBLE", "decimal": "DOUBLE", "currency": "DOUBLE",
    "single": "DOUBLE", "float": "DOUBLE",
    "string": "VARCHAR", "text": "VARCHAR",
    "boolean": "BOOL", "bool": "BOOL",
    "datetime": "DATE_TIME", "date": "DATE", "time": "DATE_TIME",
}

# Power BI summarizeBy -> TML aggregation.
_AGG = {
    "sum": "SUM", "average": "AVERAGE", "avg": "AVERAGE",
    "min": "MIN", "max": "MAX", "count": "COUNT",
    "distinctcount": "COUNT_DISTINCT",
}

# Power BI auto-generated date tables (the implicit date hierarchy behind every
# date column). They are internal artifacts, not real source tables, so they and
# any relationship touching them are dropped (and recorded as Skipped).
_AUTO_TABLE = re.compile(r"^(LocalDateTable_|DateTableTemplate_)", re.I)


def _slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(name)).strip("-").lower() or "obj"


def _dbname(name):
    """Display name -> a warehouse-safe physical name. Databricks Delta (and most
    warehouses) reject spaces and ` ,;{}()=\\t\\n` in identifiers, so collapse any
    run of non-alphanumeric/underscore characters to a single underscore."""
    return re.sub(r"[^0-9A-Za-z_]+", "_", str(name).strip()).strip("_") or "col"


def _is_key_col(name):
    n = str(name).strip().lower()
    return n.endswith("id") or n.endswith("key") or n.endswith("sk")


def _tml_type(data_type):
    return _TML_TYPE.get((data_type or "").strip().lower(), "VARCHAR")


def _col_role(col):
    """Infer (column_type, aggregation) for a parsed Power BI column.

    summarizeBy drives it when present; otherwise numeric non-keys are SUM
    measures and everything else is an attribute (keys included)."""
    summ = (col.get("summarizeBy") or "").strip().lower()
    dt = (col.get("dataType") or "").strip().lower()
    if summ in ("none", "default", ""):
        if summ in ("none", "default"):
            return "ATTRIBUTE", None
        # unset: infer from type
        if dt in ("int64", "int", "integer", "double", "decimal", "currency",
                  "single", "float") and not _is_key_col(col.get("name", "")):
            return "MEASURE", "SUM"
        return "ATTRIBUTE", None
    if summ in _AGG:
        return "MEASURE", _AGG[summ]
    return "ATTRIBUTE", None


def _table_columns(table, cmap, drop_unmapped, force_physical):
    """Physical columns for a table's TML. Returns (columns, dropped_display_names).
    Calc columns become model formulas (skipped) unless materialized as a join key;
    with drop_unmapped, a column absent from the column-map is dropped and reported."""
    cols, dropped = [], []
    for c in table.get("columns", []):
        colid = f"{table['name']}::{c['name']}"
        is_calc = c.get("calculated")
        if is_calc and colid not in force_physical:
            continue  # calculated columns become model formulas, not physical columns
        if cmap and drop_unmapped and not is_calc and c["name"] not in cmap:
            dropped.append(c["name"])
            continue
        if is_calc:                       # materialized join-key calc column
            ctype, agg, dtype = "ATTRIBUTE", None, _tml_type(force_physical[colid])
        else:
            ctype, agg = _col_role(c)
            dtype = _tml_type(c.get("dataType"))
        props = {"column_type": ctype}
        if agg:
            props["aggregation"] = agg
        cols.append({
            "name": c["name"],
            "db_column_name": cmap.get(c["name"]) or _dbname(c.get("sourceColumn") or c["name"]),
            "properties": props,
            "db_column_properties": {"data_type": dtype},
        })
    return cols, dropped


def build_table_tml(table, connection_name, db, schema, warnings,
                    table_map=None, column_map=None, drop_unmapped=False, lower_db_table=False,
                    force_physical=None):
    """Build a Table TML. Returns (tml_dict, [dropped_column_display_names]).

    A name-mapping override binds the logical model to existing physical tables:
      table_map[pbi_table]            -> physical db_table
      column_map[pbi_table][pbi_col]  -> physical db_column_name
    Logical display names stay the Power BI names (the model/answers reference
    those); only the physical db_table / db_column_name are remapped. With
    drop_unmapped, a column absent from the table's column_map is dropped (it has
    no physical backing) and returned so the model can drop it too.

    force_physical maps "Table::Col" -> data_type for calculated columns that are
    used as join keys: joins are physical, so such a column must be emitted as a
    real column (and materialized in the warehouse) instead of becoming a formula."""
    table_map = table_map or {}
    force_physical = force_physical or {}
    cmap = (column_map or {}).get(table["name"], {})
    cols, dropped = _table_columns(table, cmap, drop_unmapped, force_physical)
    db_table = table_map.get(table["name"])
    if not db_table:
        db_table = _dbname(table["name"])
        if lower_db_table:        # Databricks folds unquoted table names to lowercase
            db_table = db_table.lower()
    tbl = {
        "name": table["name"],
        "db": db,
        "schema": schema,
        "db_table": db_table,
        "connection": {"name": connection_name},
        "columns": cols,
    }
    obj = {"obj_id": f"{_slug(table['name'])}-pbi", "table": tbl}
    return obj, dropped


def _cardinality(rel):
    # TMDL omits default-valued cardinality: the default relationship is many-to-one, so
    # `fromCardinality` defaults to 'many' and `toCardinality` to 'one'. Read with those
    # defaults so a partially-serialized non-default relationship (e.g. only
    # `fromCardinality: one`, `toCardinality` omitted) is NOT silently downgraded to
    # MANY_TO_ONE and made to fan out / double-count.
    f = (rel.get("fromCardinality") or "many").lower()
    t = (rel.get("toCardinality") or "one").lower()
    if f == "one" and t == "one":
        return "ONE_TO_ONE"
    if f == "one" and t == "many":
        return "ONE_TO_MANY"
    if f == "many" and t == "many":
        return "MANY_TO_MANY"
    return "MANY_TO_ONE"  # many -> one: the common fact -> dimension default

