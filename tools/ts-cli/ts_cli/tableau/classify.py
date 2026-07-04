"""Formula tier classification for audit mode.

The translatable/skipped verdict is delegated to translate_formulas() so audit
and migrate CANNOT diverge. This module only *labels* each formula with a tier.

Orphan carve-out: formulas named in `orphan_calcs` are excluded from the
translate_formulas() call entirely — mirroring migrate's Step 3g exclusion — and
are always tiered "orphan", never consulted against the translate verdict. A
syntactically valid orphan calc (e.g. it references a table missing from this
datasource, not a translation-unsupported construct) would otherwise show up in
translate's `translated[]` and make classify disagree with what migrate actually
does with it.
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
    """Classify each formula into a tier.

    The translatable/skipped verdict for non-orphan formulas is delegated to
    translate_formulas() so audit and migrate cannot diverge. Formulas named in
    `orphan_calcs` are carved out: they are excluded from the translate_formulas()
    call (matching migrate's Step 3g exclusion of orphans from `translate-formulas`/
    `build-model`), so `translated`/`skipped`/`translate_stats` never include them,
    and they are always tiered "orphan" directly — never consulted against the
    translate verdict. With no `orphan_calcs`, behaviour is unchanged from before
    this carve-out.
    """
    orphan_calcs = set(orphan_calcs or ())

    def _name(f: dict) -> str:
        return f.get("caption") or f.get("name")

    non_orphan_formulas = [f for f in formulas if _name(f) not in orphan_calcs]
    result = translate_formulas(non_orphan_formulas, **translate_kwargs)
    translated = {t["name"]: t for t in result["translated"]}
    skipped = {s["name"]: s for s in result["skipped"]}

    classified = []
    counts: dict = {}
    for f in formulas:
        name = _name(f)
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


def classify_workbook(parsed: dict, datasource: str | None = None) -> dict:
    """Classify a parsed-workbook dict PER DATASOURCE.

    Migration builds one model per datasource, so a calc must be classified
    against its own datasource's expression — NOT flattened across the whole
    workbook. Flattening lets translate_formulas() dedupe by name, which (a)
    mis-tiers a shared calc name whose expression differs between datasources
    (e.g. SUM in one, COUNTD in another) and (b) makes workbook totals
    misreport coverage (translated+skipped no longer sums to total).

    Returns::

        {"datasources": [{"name", "formulas", "tier_counts", "translate_stats"}, ...],
         "tier_counts": <sum of per-datasource tier_counts>}

    The top-level `tier_counts` sums per-datasource instance counts — a name
    shared by two datasources is counted once per datasource, matching the two
    models migration produces. Pass `datasource` to limit to one datasource.
    """
    out_datasources = []
    summed: dict = {}
    for ds in parsed.get("datasources", []):
        if datasource and ds.get("name") != datasource:
            continue
        r = classify_formulas(
            ds.get("calculated_fields", []),
            orphan_calcs=set(ds.get("orphan_calcs", [])),
        )
        out_datasources.append({
            "name": ds.get("name"),
            "formulas": r["formulas"],
            "tier_counts": r["tier_counts"],
            "translate_stats": r["translate_stats"],
        })
        for tier, n in r["tier_counts"].items():
            summed[tier] = summed.get(tier, 0) + n
    return {"datasources": out_datasources, "tier_counts": summed}
