# tools/ts-cli/ts_cli/tableau/reconcile.py
"""Reconcile Tableau-parsed columns/formulas against a real target schema.

Pure functions, no I/O. Tier 1 (clean_*) is always-safe and needs no schema;
Tier 2 (suggest_column_mappings / apply_reconciliation, Task 2) needs the target
table's real column names.
"""
from __future__ import annotations
import re

_SUFFIX = re.compile(r"\s*\(Custom SQL Query\d+\)")
_JUNK = "__tableau_internal_object_id__"


def clean_column_name(name: str | None) -> str | None:
    if not name or _JUNK in name:
        return None
    cleaned = _SUFFIX.sub("", name).strip()
    return cleaned or None


def strip_suffix_in_expr(expr: str) -> str:
    return _SUFFIX.sub("", expr)


def clean_columns(columns: list[dict], table_name: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for c in columns:
        db = clean_column_name(c.get("db_column_name") or c.get("name"))
        if db is None:
            continue
        if db in seen:
            continue
        seen.add(db)
        nc = dict(c)
        nc["db_column_name"] = db
        nc["name"] = clean_column_name(c.get("name")) or db
        nc["table"] = table_name
        out.append(nc)
    return out
