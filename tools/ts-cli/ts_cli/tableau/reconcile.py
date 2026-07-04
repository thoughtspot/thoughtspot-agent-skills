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


def _tokens(s: str) -> set[str]:
    return {t for t in s.upper().replace("-", "_").split("_") if t}


def suggest_column_mappings(absent: list[str], target: set[str]) -> list[dict]:
    targets = sorted(target)
    out: list[dict] = []
    for a in absent:
        au = a.upper()
        best, best_score = None, 0.0
        for t in targets:
            tu = t.upper()
            if au == tu:
                score = 1.0
            elif tu == "DM_" + au or au == "DM_" + tu or tu.endswith("_" + au) or au.endswith("_" + tu):
                score = 0.9
            else:
                ta, tt = _tokens(a), _tokens(t)
                score = len(ta & tt) / len(ta | tt) if (ta | tt) else 0.0
            if score > best_score:
                best, best_score = t, score
        if best is not None and best_score > 0.5:
            out.append({"from": a, "to": best, "confidence": round(best_score, 2)})
    return out


def apply_reconciliation(columns: list[dict], formulas: list[dict],
                         target_cols: set[str], name_map: dict[str, str]) -> tuple[list[dict], list[dict], dict]:
    kept_cols: list[dict] = []
    dropped_cols: list[str] = []
    dropped_col_names: set[str] = set()
    renamed: dict[str, str] = {}
    for c in columns:
        orig = c.get("db_column_name")
        mapped = name_map.get(orig, orig)
        if mapped in target_cols:
            nc = dict(c)
            nc["db_column_name"] = mapped
            nc["name"] = mapped if c.get("name") == orig else c.get("name")
            kept_cols.append(nc)
            if mapped != orig:
                renamed[orig] = mapped
        else:
            dropped_cols.append(orig)
            dropped_col_names.add(orig)

    kept_formulas: list[dict] = []
    dropped_formulas: list[str] = []
    for f in formulas:
        expr = f.get("expr", "")
        if any(re.search(r"::" + re.escape(dc) + r"\b", expr) or ("[" + dc + "]") in expr
               for dc in dropped_col_names):
            dropped_formulas.append(f["name"])
        else:
            if renamed:
                for old, new in renamed.items():
                    expr = re.sub(r"::" + re.escape(old) + r"\b", lambda _m, new=new: "::" + new, expr)
                    expr = expr.replace("[" + old + "]", "[" + new + "]")
                nf = dict(f)
                nf["expr"] = expr
                kept_formulas.append(nf)
            else:
                kept_formulas.append(f)

    return kept_cols, kept_formulas, {"columns": dropped_cols, "formulas": dropped_formulas}
