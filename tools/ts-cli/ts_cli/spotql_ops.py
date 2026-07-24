"""Pure helpers behind `ts spotql classify-columns` (no I/O).

Codifies aggregate-function detection that two skills previously duplicated with
DIFFERENT, drifted keyword lists (BL-087, 2026-07-03 codification review row 24):

- `ts-object-model-agentql-query` SKILL.md (~:137-146) — a prose table classifying each
  `model.columns[]` entry as an attribute, a raw measure, or an "aggregate-formula
  measure" (whose backing formula must be wrapped in AgentQL `AGG(...)`, never `SUM`,
  or ThoughtSpot rejects the query with `NESTED_AGGREGATE_NOT_SUPPORTED`).
- `ts-object-answer-promote` SKILL.md (~:700-722) — an inline `AGGREGATE_FUNCS` regex
  plus `infer_column_type`/`infer_aggregation`, applied to Answer formula expressions
  that are not yet attached to any Model column (promotion candidates).

`AGGREGATE_FUNCS` here is the answer-promote regex verbatim (the fuller of the two
lists) — every function the spotql-query prose named ("sum, count, group_aggregate,
last_value, first_value, ...") is already covered by it, so nothing needed folding in
beyond it. This module is now the single canonical source; both skills call through
`ts spotql classify-columns` instead of carrying their own copy.

**Semi-additive sub-case (live-verified 2026-07-13, nebula-aggregate-aware).** Most
aggregate-formula measures must be referenced in AgentQL as `AGG(...)` (a real
`SUM(...)` errors `NESTED_AGGREGATE_NOT_SUPPORTED`). The exception is a *semi-additive*
measure whose **outermost** function is `last_value`/`first_value` — the classic
`last_value(sum(col), query_groups(), {date})` snapshot form. There `AGG(...)` fails
with `NON_CONVERTIBLE_FUNCTION` ("Non standard sql function QueryGroups") because the
serializer can't emit `query_groups()` natively; the query must instead wrap the
column in `SUM(...)`, which forces a per-group materialisation that resolves
`query_groups()` and passes the already-collapsed per-group value through unchanged.
Crucially the trigger is the OUTERMOST op, not the mere presence of `query_groups()`:
`sum(last_value(...))` (an additive aggregate *wrapping* the window) is a normal
`AGG(...)` measure — an extra `SUM(...)` there double-aggregates / errors NESTED. So
classification keys off the parsed outer function, and only `last_value`/`first_value`
as that outer op yield the `semiadditive_measure` kind (wrapper `SUM`).
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Canonical aggregate-function detector — matches a call to any ThoughtSpot aggregate
# formula function. Case-insensitive; requires an opening paren immediately (with
# optional whitespace) after the function name so a column merely named "Sum" or
# "Count" doesn't false-positive.
AGGREGATE_FUNCS = re.compile(
    r'\b(sum|count|count_distinct|unique\s+count|average|min|max|median|stddev|'
    r'variance|sum_if|unique_count_if|cumulative_\w+|moving_\w+|group_aggregate|'
    r'group_\w+|rank|rank_percentile|last_value|first_value)\s*\(',
    re.IGNORECASE,
)

# Semi-additive window functions that, when they are the OUTERMOST call in a formula,
# must be referenced in AgentQL via SUM(...) not AGG(...). See the module docstring.
SEMIADDITIVE_OUTER_FUNCS = {"last_value", "first_value"}

_LEADING_FUNC = re.compile(r"([A-Za-z_]\w*)\s*\(")


def is_aggregate_expr(expr: Optional[str]) -> bool:
    """True if `expr` contains a call to any function in AGGREGATE_FUNCS."""
    if not expr:
        return False
    return bool(AGGREGATE_FUNCS.search(expr))


def outermost_func(expr: Optional[str]) -> Optional[str]:
    """Return the lowercased name of the function call that wraps the ENTIRE expr.

    Returns the leading identifier only when its matching close-paren is the last
    non-whitespace character — i.e. the whole expression is one `f( ... )` call.
    Returns `None` for a bare column, a non-call expression, or a compound
    expression where the outer operator is not a single wrapping call (e.g.
    `last_value(...) + 1`, whose outer op is `+`, not `last_value`). This is what
    lets `last_value(sum(...))` be distinguished from `sum(last_value(...))`.
    """
    if not expr:
        return None
    s = expr.strip()
    m = _LEADING_FUNC.match(s)
    if not m:
        return None
    depth = 0
    for i in range(m.end() - 1, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return m.group(1).lower() if s[i + 1:].strip() == "" else None
    return None


def classify_expr(expr: Optional[str]) -> dict[str, Any]:
    """Classify a single formula expression not yet attached to a Model column.

    Matches answer-promote's `infer_column_type`/`infer_aggregation` semantics
    exactly: MEASURE iff the expression contains an aggregate function call;
    `aggregation` is `SUM` for a MEASURE (ThoughtSpot ignores the `aggregation`
    property on formula columns at query time — the expr is self-contained; `SUM`
    is the repo's documented convention), `None` for an ATTRIBUTE.

    Returns: {"column_type": "MEASURE"|"ATTRIBUTE", "aggregation": "SUM"|None,
    "is_aggregate": bool}.
    """
    is_agg = is_aggregate_expr(expr)
    column_type = "MEASURE" if is_agg else "ATTRIBUTE"
    aggregation = "SUM" if column_type == "MEASURE" else None
    return {"column_type": column_type, "aggregation": aggregation, "is_aggregate": is_agg}


def classify_model_columns(model_tml: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify every `model.columns[]` entry in a parsed Model TML.

    `model_tml` is the full parsed TML dict rooted at `model:` (the shape
    `ts tml export --parse` / `parse_edoc` produces) — e.g. `{"model": {...},
    "guid": "..."}`. A bare `{"columns": [...], "formulas": [...]}` dict (no
    `model` wrapper) is also accepted for convenience.

    For each column, reads `properties.column_type` (nested under `properties`,
    never a direct child — see thoughtspot-model-tml.md). A MEASURE column is
    either:

    - **raw** — a plain warehouse column (no `formula_id`), or a `formula_id`
      whose `formulas[].expr` contains no aggregate call. Query-time aggregation
      (`SUM`/`AVG`/...) is applied on top — read from `properties.aggregation`
      if present, else default `SUM`.
    - **aggregate-formula** — a `formula_id` whose `formulas[].expr` DOES contain
      an aggregate call (e.g. `sum(...)`, `group_aggregate(...)`). AgentQL must
      wrap a reference to this column in `AGG(...)`, never a real aggregate —
      stacking a second aggregate on top errors `NESTED_AGGREGATE_NOT_SUPPORTED`.
    - **semi-additive** — an aggregate-formula whose OUTERMOST call is
      `last_value`/`first_value` (the `last_value(sum(col), query_groups(),
      {date})` snapshot form). This one inverts the rule above: AgentQL must wrap
      it in `SUM(...)`, and `AGG(...)` errors `NON_CONVERTIBLE_FUNCTION`. See the
      module docstring for why, and why `sum(last_value(...))` is NOT this case.

    A `formula_id` that doesn't resolve to any `formulas[]` entry (a malformed or
    partially-exported TML) is treated as a raw measure with an empty expression
    — conservative, since we have no expression text to detect an aggregate in.

    Returns one dict per column: `{"name", "column_type", "kind":
    "attribute"|"raw_measure"|"aggregate_measure"|"semiadditive_measure",
    "needs_agg": bool, "aggregation": "SUM"|None, "wrapper": "AGG"|"SUM"|None}`.
    The `wrapper` field is the directly-actionable output — the AgentQL function to
    wrap a reference to this column in (`None` for attributes, which go in
    `GROUP BY`). `kind == "aggregate_measure"` (equivalently `needs_agg is True`)
    means `AGG(...)`; `"semiadditive_measure"` means `SUM(...)` (NOT `AGG` —
    NON_CONVERTIBLE); `"raw_measure"` means a real aggregate (`SUM`/`AVG`/...);
    `"attribute"` means group by it.
    """
    model = model_tml.get("model", model_tml) if isinstance(model_tml, dict) else {}
    columns = model.get("columns") or []
    formulas = model.get("formulas") or []
    formulas_by_id = {f.get("id"): f for f in formulas if f.get("id")}

    results: list[dict[str, Any]] = []
    for col in columns:
        name = col.get("name", "")
        props = col.get("properties") or {}
        column_type = props.get("column_type", "ATTRIBUTE")

        if column_type != "MEASURE":
            results.append({
                "name": name,
                "column_type": column_type,
                "kind": "attribute",
                "needs_agg": False,
                "aggregation": None,
                "wrapper": None,
            })
            continue

        formula_id = col.get("formula_id")
        formula = formulas_by_id.get(formula_id) if formula_id else None
        expr = formula.get("expr", "") if formula else ""

        if formula_id and is_aggregate_expr(expr):
            if outermost_func(expr) in SEMIADDITIVE_OUTER_FUNCS:
                results.append({
                    "name": name,
                    "column_type": column_type,
                    "kind": "semiadditive_measure",
                    "needs_agg": False,
                    "aggregation": "SUM",
                    "wrapper": "SUM",
                })
            else:
                results.append({
                    "name": name,
                    "column_type": column_type,
                    "kind": "aggregate_measure",
                    "needs_agg": True,
                    "aggregation": None,
                    "wrapper": "AGG",
                })
        else:
            results.append({
                "name": name,
                "column_type": column_type,
                "kind": "raw_measure",
                "needs_agg": False,
                "aggregation": props.get("aggregation") or "SUM",
                "wrapper": "SUM",
            })

    return results
