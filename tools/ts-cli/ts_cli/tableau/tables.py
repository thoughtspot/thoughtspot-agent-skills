"""Tableau -> ThoughtSpot Table TML assembly. Pure functions, no I/O.

Mirrors ts_cli.powerbi.tables' shape and invariants (see CLAUDE.md "Critical TML
invariants" and agents/shared/schemas/thoughtspot-table-tml.md):
  - db_column_name is always present, even when it equals the display name.
  - the connection block carries the connection display NAME only — never fqn:/GUID.
  - Datetime/timestamp maps to the canonical DATE_TIME (not DATETIME).
"""

from __future__ import annotations

import re

from ts_cli.powerbi.tables import _is_key_col

# Tableau/parse type name -> ThoughtSpot db_column_properties.data_type.
# Canonical values per agents/shared/schemas/thoughtspot-table-tml.md — SQL type
# names (e.g. BIGINT) are rejected by the API and must never appear here.
_TML_TYPE = {
    "integer": "INT64", "int": "INT64",
    "real": "DOUBLE", "double": "DOUBLE", "float": "DOUBLE", "decimal": "DOUBLE",
    "string": "VARCHAR", "text": "VARCHAR",
    "boolean": "BOOL", "bool": "BOOL",
    "date": "DATE",
    "datetime": "DATE_TIME", "timestamp": "DATE_TIME",
}


def _slug(name):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(name)).strip("-").lower() or "obj"


def _dbname(name):
    """Display name -> a warehouse-safe physical name. Collapse any run of
    non-alphanumeric/underscore characters to a single underscore."""
    return re.sub(r"[^0-9A-Za-z_]+", "_", str(name).strip()).strip("_") or "col"


def _tml_type(data_type):
    """Map a data type to canonical ThoughtSpot db_column_properties.data_type.

    Handles both:
    1. Canonical TS types (INT64, DOUBLE, BOOL, DATE, DATE_TIME, VARCHAR) — pass through.
    2. Raw Tableau names (integer, datetime, etc.) — map via _TML_TYPE dict.
    """
    raw = (data_type or "").strip()
    normalized = raw.upper()

    # Canonical TS types: pass through (check upper-cased form)
    canonical_types = ("INT64", "DOUBLE", "BOOL", "DATE", "DATE_TIME", "VARCHAR")
    if normalized in canonical_types:
        return normalized

    # Raw Tableau names: lowercase and map
    return _TML_TYPE.get(raw.lower(), "VARCHAR")


def _col_role(col):
    """(column_type, aggregation) for a parsed Tableau column.

    The parser's own column_type (ATTRIBUTE/MEASURE) is authoritative when present.
    Otherwise mirror powerbi's inference: numeric non-key columns are SUM measures,
    everything else (keys included) is an attribute."""
    col_type = (col.get("column_type") or "").strip().upper()
    if col_type == "MEASURE":
        return "MEASURE", col.get("aggregation") or "SUM"
    if col_type == "ATTRIBUTE":
        return "ATTRIBUTE", None
    dt = (col.get("data_type") or "").strip().lower()
    if dt in ("integer", "int", "real", "double", "float", "decimal") and not _is_key_col(col.get("name", "")):
        return "MEASURE", "SUM"
    return "ATTRIBUTE", None


def _parsed_db_table(table: dict) -> str | None:
    """The physical warehouse table name from the parser's own ``db_table``
    field (Fix #C), when present — a dotted ``db.schema.table`` path (see
    ``ts_cli/tableau/twb.py::_extract_tables``), so only its LAST segment is
    the table name proper (``db``/``schema`` are already their own separate
    Table TML fields).

    This is the REAL underlying table, which can differ from the table's
    logical ``name`` when the same physical table is joined twice under a
    Tableau-assigned alias (``alias_of`, e.g. ``d_partner1`` aliasing
    ``d_partner``) — re-deriving db_table from ``name`` in that case slugs
    the ALIAS, not the real table, and ThoughtSpot rejects the import
    ("table not found") because that alias name was never a real warehouse
    table. Returns ``None`` when the parser didn't supply a ``db_table``
    (e.g. hand-built table dicts in tests/other converters), so the caller
    can fall back to the name-slug default.
    """
    raw = table.get("db_table")
    if not raw:
        return None
    physical = str(raw).split(".")[-1].strip("[]")
    return _dbname(physical) if physical else None


def _table_columns(table, cmap):
    cols = []
    for c in table.get("columns", []):
        ctype, agg = _col_role(c)
        props = {"column_type": ctype}
        if agg:
            props["aggregation"] = agg
        cols.append({
            "name": c["name"],
            "db_column_name": cmap.get(c["name"]) or _dbname(c["name"]),
            "properties": props,
            "db_column_properties": {"data_type": _tml_type(c.get("data_type"))},
        })
    return cols


def build_table_tml(table: dict, connection_name: str, db: str, schema: str, *,
                     table_map: dict | None = None, column_map: dict | None = None,
                     ) -> tuple[dict, list[str]]:
    """Build a Table TML from a parsed Tableau datasource table. Returns
    (tml_dict, dropped_column_display_names).

    A name-mapping override binds the logical table to an existing physical table:
      table_map[tableau_table]            -> physical db_table
      column_map[tableau_table][tableau_col] -> physical db_column_name
    Logical display names always stay the Tableau names; only the physical
    db_table / db_column_name are remapped. v1 has no drop_unmapped: a column
    absent from column_map falls back to its derived physical name rather than
    being dropped (YAGNI — no plan yet needs the model to drop columns for this
    converter; see ts_cli.powerbi.tables.build_table_tml for that contract)."""
    table_map = table_map or {}
    cmap = (column_map or {}).get(table["name"], {})
    cols = _table_columns(table, cmap)
    db_table = (
        table_map.get(table["name"])
        or _parsed_db_table(table)
        or _dbname(table["name"])
    )
    tbl = {
        "name": table["name"],
        "db": db,
        "schema": schema,
        "db_table": db_table,
        "connection": {"name": connection_name},
        "columns": cols,
    }
    obj = {"obj_id": f"{_slug(table['name'])}-tableau", "table": tbl}
    return obj, []
