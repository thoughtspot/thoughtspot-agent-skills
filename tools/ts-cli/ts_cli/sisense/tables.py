"""Sisense -> ThoughtSpot Table TML + naming/type/cardinality helpers.

Ported from the standalone converter (map/model.py). Pure functions, no I/O.
Repo invariant: a table TML connection block carries the connection display NAME
only, never a GUID (.claude/rules/ts-cli.md, the "connection_name" convention).

Physical-name conventions (from the standalone converter):
  db_table       = SourceTable.id with a trailing ".csv" stripped (optionally lowered)
  db_column_name = column display name with spaces -> underscores
  logical name   = the Sisense display name (kept, may contain spaces)
"""
from __future__ import annotations

import re

# Normalized type token (from parsing._to_datatype) -> TML data_type enum.
_TML_TYPE = {
    "int64": "INT64",
    "double": "DOUBLE",
    "bool": "BOOL",
    "string": "VARCHAR",
    "date": "DATE",
    "datetime": "DATE_TIME",
    "unknown": "VARCHAR",
}

# Sisense v2 `relations` does NOT export cardinality (defaults to UNKNOWN), so this
# maps a known value through and defaults the rest to MANY_TO_ONE (fact -> dimension).
_CARD = {
    "many_to_one": "MANY_TO_ONE", "one_to_one": "ONE_TO_ONE",
    "one_to_many": "ONE_TO_MANY", "many_to_many": "MANY_TO_MANY",
}


def _slug(name) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(name)).strip("-").lower() or "obj"


def _clean(table_id) -> str:
    """Table id -> logical table name: strip a trailing '.csv' (Sisense CSV datasets)."""
    s = str(table_id)
    return s[:-4] if s.lower().endswith(".csv") else s


def _dbname(name) -> str:
    """Display name -> a warehouse-safe physical column name (spaces -> underscores)."""
    return str(name).replace(" ", "_")


# A numeric column whose name looks dimensional is an ATTRIBUTE, not a SUM measure.
# Suffixes are matched on the whole (lowercased) name; terms are matched as whole
# tokens (camelCase- and separator-split) so "Info" is not mistaken for a "...no" key.
_DIM_SUFFIXES = ("id", "key", "code", "number", "zip", "postal")
_DIM_TERMS = frozenset({
    "year", "quarter", "month", "week", "day", "date", "datetime",
    "age", "rank", "rating", "status", "flag",
    "id", "key", "code", "no", "number", "zip", "postal",
})


def _dim_tokens(name) -> list:
    """Split a name into lowercase tokens on separators AND camelCase boundaries."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(name))
    return re.findall(r"[a-z0-9]+", spaced.lower())


def _is_dimensional_name(name) -> bool:
    """True when a numeric column's name reads as a key/date/category rather than a metric."""
    lower = str(name).strip().lower()
    if lower.endswith(_DIM_SUFFIXES):
        return True
    return any(tok in _DIM_TERMS for tok in _dim_tokens(name))


def _tml_type(data_type) -> str:
    return _TML_TYPE.get((data_type or "").strip().lower(), "VARCHAR")


def _col_role(col: dict) -> tuple:
    """Infer (column_type, aggregation, review_note) for a parsed Sisense column.

    An explicit `role` wins. Otherwise a numeric column whose name looks dimensional
    (ends id/key/code/number/zip/postal, or is a year/date/age/status/flag/… term) is an
    ATTRIBUTE; any other numeric column defaults to a SUM measure but carries a review_note
    (flag, don't downgrade) so a Year-like column is verified rather than silently summed;
    everything else is an attribute. review_note is None unless the measure was defaulted."""
    role = (col.get("role") or "").strip().upper() if col.get("role") else None
    if role in ("ATTRIBUTE", "MEASURE"):
        return role, ("SUM" if role == "MEASURE" else None), None
    numeric = (col.get("data_type") or "").strip().lower() in ("int64", "double")
    if numeric and not _is_dimensional_name(col.get("name", "")):
        return "MEASURE", "SUM", (
            "auto-classified as a SUM measure (numeric column, source gave no role) — "
            "verify it is a metric and not a dimensional attribute (e.g. a code/year)")
    return "ATTRIBUTE", None, None


def _cardinality(rel: dict) -> tuple:
    """Relation cardinality -> (TML cardinality, defaulted?).

    Sisense v2 exports carry no cardinality, so an absent/unknown value defaults to
    MANY_TO_ONE with defaulted=True — the caller flags the relation NEEDS REVIEW because a
    true many-to-many bridge silently defaulted to MANY_TO_ONE will fan out / double-count."""
    card = _CARD.get((rel.get("cardinality") or "").strip().lower())
    if card is None:
        return "MANY_TO_ONE", True
    return card, False


def build_table_tml(table: dict, connection_name: str, db: str, schema: str,
                    warnings: list, lower_db_table: bool = False) -> tuple:
    """Build a Table TML. Returns (tml_dict, dropped_column_display_names).

    Logical column/table names stay the Sisense display names (the model references
    those); db_table / db_column_name are the warehouse-safe physical names. The
    connection block carries name only (never fqn) per the repo invariant.
    """
    cols = []
    for c in table.get("columns", []):
        ctype, agg, _note = _col_role(c)
        props = {"column_type": ctype}
        if agg:
            props["aggregation"] = agg
        cols.append({
            "name": c["name"],
            "db_column_name": _dbname(c["name"]),
            "properties": props,
            "db_column_properties": {"data_type": _tml_type(c.get("data_type"))},
        })
    name = _clean(table.get("id") or table.get("name"))
    db_table = name.lower() if lower_db_table else name
    tbl = {
        "name": name,
        "db": db,
        "schema": schema,
        "db_table": db_table,
        "connection": {"name": connection_name},
        "columns": cols,
    }
    obj = {"obj_id": f"{_slug(name)}-sisense", "table": tbl}
    return obj, []
