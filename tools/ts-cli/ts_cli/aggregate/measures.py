"""Measure decomposition engine — rewrite plans for aggregate models.

Pure functions, no I/O. Classes and rules mirror
agents/cli/ts-object-model-aggregates/references/measure-decomposition-rules.md.
"""
from __future__ import annotations

import re
from typing import Optional

_DIRECT = {"SUM": "SUM", "MIN": "MIN", "MAX": "MAX"}
_SIMPLE_FN = re.compile(
    r"^\s*(sum|min|max|count|average|avg)\s*\(\s*\[([^\]]+)\]\s*\)\s*$", re.I
)
_UNIQUE = re.compile(r"^\s*unique\s+count\s*\(\s*\[([^\]]+)\]\s*\)\s*$", re.I)
_RATIO = re.compile(
    r"^\s*(sum|count)\s*\(\s*\[([^\]]+)\]\s*\)\s*/\s*(sum|count)\s*\(\s*\[([^\]]+)\]\s*\)\s*$",
    re.I,
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _plan(name, klass, decomposable, components=None, model_expr=None, requires=None):
    return {
        "name": name,
        "class": klass,
        "decomposable": decomposable,
        "components": components or [],
        "model_expr": model_expr,
        "requires_grain_column": requires,
    }


def classify_measure(name: str, aggregation: Optional[str] = None,
                     expr: Optional[str] = None) -> dict:
    """Return the rewrite plan for one measure (column aggregation or formula expr)."""
    slug = _slug(name)
    if expr is None and aggregation:
        agg = aggregation.upper()
        if agg in _DIRECT:
            comp = {"alias": f"{slug}_{agg.lower()}", "source_column": name,
                    "func": agg, "reagg": agg}
            return _plan(name, agg, True, [comp])
        if agg == "COUNT":
            comp = {"alias": f"{slug}_cnt", "source_column": name,
                    "func": "COUNT", "reagg": "SUM"}
            return _plan(name, "COUNT", True, [comp],
                         model_expr=f"sum ( [{slug}_cnt] )")
        if agg in ("AVERAGE", "AVG"):
            expr = f"average ( [{name}] )"  # fall through to formula path
        elif agg in ("COUNT_DISTINCT", "UNIQUE_COUNT"):
            return _plan(name, "NONADDITIVE", False, requires=name)
        else:
            return _plan(name, "UNKNOWN", False)

    if expr is None:
        return _plan(name, "UNKNOWN", False)

    m = _UNIQUE.match(expr)
    if m:
        return _plan(name, "NONADDITIVE", False, requires=m.group(1))

    m = _SIMPLE_FN.match(expr)
    if m:
        fn, col = m.group(1).lower(), m.group(2)
        if fn in ("sum", "min", "max"):
            f = fn.upper()
            comp = {"alias": f"{slug}_{fn}", "source_column": col,
                    "func": f, "reagg": f}
            return _plan(name, f, True, [comp])
        if fn == "count":
            comp = {"alias": f"{slug}_cnt", "source_column": col,
                    "func": "COUNT", "reagg": "SUM"}
            return _plan(name, "COUNT", True, [comp],
                         model_expr=f"sum ( [{slug}_cnt] )")
        # average / avg
        comps = [
            {"alias": f"{slug}_sum", "source_column": col, "func": "SUM", "reagg": "SUM"},
            {"alias": f"{slug}_cnt", "source_column": col, "func": "COUNT", "reagg": "SUM"},
        ]
        return _plan(name, "AVG", True, comps,
                     model_expr=f"sum ( [{slug}_sum] ) / sum ( [{slug}_cnt] )")

    m = _RATIO.match(expr)
    if m:
        nfn, ncol, dfn, dcol = m.group(1).upper(), m.group(2), m.group(3).upper(), m.group(4)
        comps = [
            {"alias": f"{slug}_num", "source_column": ncol, "func": nfn, "reagg": "SUM"},
            {"alias": f"{slug}_den", "source_column": dcol, "func": dfn, "reagg": "SUM"},
        ]
        return _plan(name, "RATIO", True, comps,
                     model_expr=f"sum ( [{slug}_num] ) / sum ( [{slug}_den] )")

    return _plan(name, "UNKNOWN", False)


def build_rewrite_plans(model_tml: dict) -> dict:
    """Map every MEASURE column and formula in a Model TML to its rewrite plan."""
    model = model_tml.get("model", {})
    plans: dict = {}
    formula_names = set()
    for f in model.get("formulas", []) or []:
        plans[f["name"]] = classify_measure(f["name"], expr=f.get("expr"))
        formula_names.add(f["name"])
    for c in model.get("columns", []) or []:
        props = c.get("properties", {}) or {}
        if props.get("column_type") == "MEASURE" and c["name"] not in formula_names:
            plans[c["name"]] = classify_measure(
                c["name"], aggregation=props.get("aggregation", "SUM"))
    return plans
