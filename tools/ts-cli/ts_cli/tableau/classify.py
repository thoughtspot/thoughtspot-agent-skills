"""Formula tier classification for audit mode.

The translatable/skipped verdict is delegated to translate_formulas() so audit
and migrate CANNOT diverge. This module only *labels* each formula with a tier.
"""
from __future__ import annotations
import re
from ts_cli.tableau_translate import translate_formulas

TRANSLATABLE_TIERS = {
    "native", "lod", "cumulative", "moving",
    "pass_through", "row_offset_native", "parameter_ref",
}
UNTRANSLATABLE_TIERS = {
    "untranslatable", "row_offset_ambiguous", "geospatial",
    "circular", "orphan", "parameter_query",
}

_GEO_RE = re.compile(
    r"\b(MAKEPOINT|MAKELINE|BUFFER|OUTLINE|DISTANCE|AREA|LENGTH|INTERSECTS|"
    r"SHAPETYPE|DIFFERENCE|INTERSECTION|SYMDIFFERENCE|VALIDATE)\s*\(", re.I)
_LOD_RE = re.compile(r"\{\s*(FIXED|INCLUDE|EXCLUDE)\b", re.I)
_RUNNING_RE = re.compile(r"\bRUNNING_(SUM|AVG|MAX|MIN|COUNT)\s*\(", re.I)
_WINDOW_RE = re.compile(r"\bWINDOW_(SUM|AVG|MAX|MIN|COUNT|STDEV|VAR|MEDIAN|PERCENTILE)\s*\(", re.I)
_RANK_RE = re.compile(r"\b(RANK(_UNIQUE|_MODIFIED|_DENSE|_PERCENTILE)?|TOTAL)\s*\(", re.I)
_ROWOFFSET_RE = re.compile(r"\b(INDEX|LOOKUP|FIRST|LAST|SIZE)\s*\(", re.I)
_PARAM_RE = re.compile(r"\[Parameters\]\.\[", re.I)


def _translatable_tier(expr: str) -> str:
    if _LOD_RE.search(expr):
        return "lod"
    if _RUNNING_RE.search(expr):
        return "cumulative"
    if _WINDOW_RE.search(expr):
        return "moving"
    if _ROWOFFSET_RE.search(expr):
        return "row_offset_native"
    if _RANK_RE.search(expr):
        return "pass_through"
    if _PARAM_RE.search(expr):
        return "parameter_ref"
    return "native"


def _untranslatable_tier(expr: str, reason: str) -> str:
    if _GEO_RE.search(expr):
        return "geospatial"
    low = (reason or "").lower()
    if "circular" in low or "unresolvable" in low:
        return "circular"
    if "parameter" in low:
        return "parameter_query"
    if _ROWOFFSET_RE.search(expr):
        return "row_offset_ambiguous"
    return "untranslatable"


def _complexity(expr: str) -> int:
    nesting = expr.count("(")
    cross_refs = len(re.findall(r"\[Calculation_\d+\]", expr))
    funcs = len(re.findall(r"[A-Za-z_]+\s*\(", expr))
    return nesting + cross_refs + funcs


def classify_formulas(formulas: list[dict], orphan_calcs=None, **translate_kwargs) -> dict:
    orphan_calcs = set(orphan_calcs or ())
    result = translate_formulas(formulas, **translate_kwargs)
    translated = {t["name"]: t for t in result["translated"]}
    skipped = {s["name"]: s for s in result["skipped"]}

    classified = []
    counts: dict = {}
    for f in formulas:
        name = f.get("caption") or f.get("name")
        expr = f.get("formula", "")
        if name in orphan_calcs:
            tier, reason, level = "orphan", "references table not in datasource", -1
        elif name in translated:
            tier = _translatable_tier(expr)
            reason = ""
            level = translated[name].get("level", 0)
        else:
            sk = skipped.get(name, {})
            reason = sk.get("reason", "unknown")
            level = sk.get("level", -1)
            tier = _untranslatable_tier(expr, reason)
        classified.append({"name": name, "tier": tier, "reason": reason,
                           "level": level, "complexity": _complexity(expr)})
        counts[tier] = counts.get(tier, 0) + 1

    return {"formulas": classified, "tier_counts": counts,
            "translate_stats": result["stats"]}
