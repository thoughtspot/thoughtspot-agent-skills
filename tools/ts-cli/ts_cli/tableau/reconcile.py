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


def validate_name_map(name_map: dict[str, str]) -> str | None:
    """Validate a --column-name-map for a rename chain or convergent targets.
    Returns an error message if invalid, None if OK.

    apply_reconciliation rewrites renamed-column formula refs by applying
    name_map pairs sequentially on a mutating expression string:
    - A chain (A -> B, B -> C) would corrupt that rewrite (A ends up
      rewritten to C via B, or vice versa depending on dict order), since
      the first substitution's output becomes the second's input.
    - A convergent map (A -> X, B -> X) would collide two source columns
      into one column_id in the emitted model TML ("column_id values are
      incorrect" on import). apply_reconciliation's post-condition dedupe
      is defense-in-depth for this; failing fast here is a clearer error.

    suggest_column_mappings never produces either shape by construction, but
    this file is user-supplied, so validate it explicitly rather than trust it.
    """
    chained = set(name_map.keys()) & set(name_map.values())
    if chained:
        return (
            "reconcile: --column-name-map contains a rename chain — "
            f"{sorted(chained)} appear as both a source and a target. "
            "Chained renames would corrupt formula rewriting; split them "
            "into independent mappings."
        )
    targets = list(name_map.values())
    convergent = {t for t in targets if targets.count(t) > 1}
    if convergent:
        return (
            "reconcile: --column-name-map maps multiple columns to the same "
            f"target: {sorted(convergent)} — map at most one source column "
            "to each target."
        )
    return None


def drop_junk_formulas(formulas: list[dict]) -> tuple[list[dict], list[str]]:
    """Drop any formula whose expr references a __tableau_internal_object_id__
    junk column (Tier-1 companion to clean_columns, which drops the junk
    COLUMNS but leaves formulas referencing them dangling)."""
    kept: list[dict] = []
    dropped: list[str] = []
    for f in formulas:
        if _JUNK in f.get("expr", ""):
            dropped.append(f["name"])
        else:
            kept.append(f)
    return kept, dropped


def apply_reconciliation(columns: list[dict], formulas: list[dict],
                         target_cols: set[str], name_map: dict[str, str]) -> tuple[list[dict], list[dict], dict]:
    kept_cols: list[dict] = []
    kept_origs: list[str] = []  # pre-mapping db_column_name, parallel to kept_cols
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
            kept_origs.append(orig)
            if mapped != orig:
                renamed[orig] = mapped
        else:
            dropped_cols.append(orig)
            dropped_col_names.add(orig)

    # Post-condition dedupe: two different source columns can converge on the
    # same final db_column_name — either via name_map (two renames landing on
    # one target) or because a renamed column collides with an already-present
    # unmapped column. Either way, two kept columns sharing a db_column_name
    # would emit two columns with the same column_id, which ThoughtSpot's
    # import rejects. Keep the first occurrence; move later duplicates to the
    # dropped report (by their pre-mapping name, matching the convention used
    # for ordinary reconcile-drops above) and cascade-drop any formula that
    # referenced them via that pre-mapping name — formulas at this point still
    # reference original names; the `renamed` rewrite happens below.
    seen_final: set[str] = set()
    deduped_cols: list[dict] = []
    for nc, orig in zip(kept_cols, kept_origs):
        final = nc["db_column_name"]
        if final in seen_final:
            dropped_cols.append(orig)
            dropped_col_names.add(orig)
        else:
            seen_final.add(final)
            deduped_cols.append(nc)
    kept_cols = deduped_cols

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
