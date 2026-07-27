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
# safe_divide(sum([a]), sum([b])) — ThoughtSpot's null-safe division; decomposes
# exactly like the `a/b` ratio above (store both component sums, re-divide at the
# aggregate grain), but the model_expr keeps safe_divide so the aggregate matches
# the primary's own null-handling.
_SAFE_DIVIDE = re.compile(
    r"^\s*safe_divide\s*\(\s*(sum|count)\s*\(\s*\[([^\]]+)\]\s*\)\s*,"
    r"\s*(sum|count)\s*\(\s*\[([^\]]+)\]\s*\)\s*\)\s*$",
    re.I,
)
# Semi-additive snapshot: last_value/first_value(sum([col]), query_groups(),
# {[date]}) — the classic period-end stock/balance form. Sums across
# non-date dims but takes the period-end (last/first) value across the date
# dimension, so it can NEVER be flat-summed across periods. Decomposes to a
# single stored period-end-snapshot component; the aggregate model re-applies
# last_value/first_value over the aggregate's own (bucketed) date column,
# which is candidate-specific — so model_expr carries the `__AGG_DATE__`
# placeholder that generate.build_aggregate_model_tml substitutes.
_SEMIADD = re.compile(
    r"^\s*(last_value|first_value)\s*\(\s*sum\s*\(\s*\[([^\]]+)\]\s*\)\s*,"
    r"\s*query_groups\s*\(\s*\)\s*,\s*\{\s*\[([^\]]+)\]\s*\}\s*\)\s*$",
    re.I,
)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "measure"  # fully non-ASCII/symbol names must not slug to ""


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
            fn = agg.lower()
            alias = f"{slug}_{fn}"
            comp = {"alias": alias, "source_column": name,
                    "func": agg, "reagg": agg}
            # Live-verified (aggregate-aware cluster, 2026-07-13): aggregate
            # routing fires ONLY for FORMULA measures, never a plain measure
            # column (default-aggregation switching on columns isn't coded).
            # So even a direct SUM/MIN/MAX must surface as a formula over its
            # hidden stored component — see skill Open Item #0.
            return _plan(name, agg, True, [comp], model_expr=f"{fn} ( [{alias}] )")
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
            alias = f"{slug}_{fn}"
            comp = {"alias": alias, "source_column": col,
                    "func": f, "reagg": f}
            # See the aggregation-path comment above: routing needs a
            # formula, so a direct sum()/min()/max() expr also gets a
            # model_expr over its hidden stored component.
            return _plan(name, f, True, [comp], model_expr=f"{fn} ( [{alias}] )")
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

    m = _SAFE_DIVIDE.match(expr)
    if m:
        nfn, ncol, dfn, dcol = m.group(1).upper(), m.group(2), m.group(3).upper(), m.group(4)
        comps = [
            {"alias": f"{slug}_num", "source_column": ncol, "func": nfn, "reagg": "SUM"},
            {"alias": f"{slug}_den", "source_column": dcol, "func": dfn, "reagg": "SUM"},
        ]
        return _plan(name, "RATIO", True, comps,
                     model_expr=f"safe_divide ( sum ( [{slug}_num] ) , sum ( [{slug}_den] ) )")

    m = _SEMIADD.match(expr)
    if m:
        # Recognized but NOT auto-decomposed (decomposable=False): a correct
        # period-end snapshot aggregate needs a windowed `last_value OVER
        # (PARTITION BY grain ORDER BY date)` DDL that the flat-SUM/positional
        # generators can't emit, so auto-generation is deliberately out of
        # scope (would risk wrong snapshot numbers). Classifying it as
        # SEMIADDITIVE (vs UNKNOWN) lets `recommend` surface it and point the
        # user at the hand-build recipe; `requires_grain_column` records the
        # date column the snapshot is taken over. Same coverage behaviour as
        # before (a date-column requirement in dims is never met, so
        # semi-additive signatures stay excluded from candidates).
        datecol = m.group(3)
        return _plan(name, "SEMIADDITIVE", False, requires=datecol)

    return _plan(name, "UNKNOWN", False)


def _uniquify_aliases(plans: dict) -> None:
    """Make component aliases unique across all plans, in stable iteration order.

    Aliases are the binding contract downstream tasks (SQL/TML generation) key on;
    colliding slugs ("Avg Sale" vs "Avg-Sale") would silently merge components.
    First occurrence keeps its base alias; later collisions get _2, _3, ... and any
    renamed alias is rewritten inside that plan's model_expr as well.
    """
    seen: set = set()
    for plan in plans.values():
        renames = {}
        for comp in plan["components"]:
            alias = comp["alias"]
            if alias in seen:
                n = 2
                while f"{alias}_{n}" in seen:
                    n += 1
                new_alias = f"{alias}_{n}"
                renames[alias] = new_alias
                comp["alias"] = new_alias
                alias = new_alias
            seen.add(alias)
        if renames and plan["model_expr"]:
            for old, new in renames.items():
                plan["model_expr"] = plan["model_expr"].replace(f"[{old}]", f"[{new}]")


def build_rewrite_plans(model_tml: dict) -> dict:
    """Map every MEASURE column and formula in a Model TML to its rewrite plan."""
    model = model_tml.get("model", {})
    plans: dict = {}
    for f in model.get("formulas", []) or []:
        plans[f["name"]] = classify_measure(f["name"], expr=f.get("expr"))
    for c in model.get("columns", []) or []:
        if c.get("formula_id"):
            # Formula-backed column: its plan comes from the formulas[] entry
            # (resolved by formula_id, same as spotql_ops.classify_model_columns).
            # The column name is NOT a physical warehouse column — planning it as
            # a raw measure would emit a spurious SUM over a nonexistent column.
            continue
        props = c.get("properties", {}) or {}
        if props.get("column_type") == "MEASURE":
            plans[c["name"]] = classify_measure(
                c["name"], aggregation=props.get("aggregation", "SUM"))
    _uniquify_aliases(plans)
    return plans
