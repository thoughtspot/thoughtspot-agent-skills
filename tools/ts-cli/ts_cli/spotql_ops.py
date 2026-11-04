"""Pure helpers behind `ts agentql classify-columns` (no I/O).

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
beyond it. The remaining conditional aggregates (`count_if`, `average_if`, `min_if`,
`max_if`, `stddev_if`, `variance_if`) were added in PR #570 — only `sum_if` and
`unique_count_if` had been listed, so a COUNTIF translation came out as an ATTRIBUTE.
This module is now the single canonical source; both skills call through
`ts agentql classify-columns` instead of carrying their own copy.

The audit reads `AGGREGATE_FUNCS` too (P2's `@is_row_level_formula` and D14's
`@surfaces_row_level_formula`, in `ts_cli/audit/engine/fields.py`): an edit here moves
P2's and D14's findings, and because the audit
catalog gate imports it under Python 3.9 with only PyYAML, this module stays stdlib-only
(`GATE_SHARED_MODULES` in `tools/validate/tests/test_check_audit_catalog.py`).

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
as that outer op yield the `semiadditive_measure` kind (wrapper `SUM`). Their
`*_in_period` spellings take the same arguments, `query_groups ( )` included, and are
classified the same way (BL-509) — by that shared shape, not by a live AgentQL probe.

**Column aggregation (BL-509).** `formula_aggregation` is the one reading of what a
generator declares on a MEASURE formula column (product owner, 2026-11-02): applied to a
per-row formula and to a bare group_aggregate / group_* / last_value / first_value
(`is_bare_window`), ignored for any other aggregate formula. The Power BI, Sisense and
dbt builders, `ts aggregate generate`, the Tableau merge, `ts formula translate` and
`classify_expr` call it (`declare_formula_aggregations`); the Snowflake SV, Databricks
MV, Tableau and Qlik builders still declare their own value (BL-519).
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
    r'variance|sum_if|count_if|average_if|min_if|max_if|stddev_if|variance_if|'
    r'unique_count_if|cumulative_\w+|moving_\w+|group_aggregate|'
    r'group_\w+|rank|rank_percentile|last_value|first_value|'
    r'last_value_in_period|first_value_in_period)\s*\(',
    re.IGNORECASE,
)

# Semi-additive window functions that, when they are the OUTERMOST call in a formula,
# must be referenced in AgentQL via SUM(...) not AGG(...). See the module docstring.
# The *_in_period spellings take the same three arguments, `query_groups ( )` included
# (thoughtspot-formula-patterns.md: "treat same as last_value"; BL-509).
SEMIADDITIVE_OUTER_FUNCS = {"last_value", "first_value",
                            "last_value_in_period", "first_value_in_period"}

#: The aggregate formulas whose column `aggregation` ThoughtSpot applies to their result
#: when one is the whole expression (product owner, 2026-11-02; thoughtspot-model-tml.md):
#: group_aggregate, its group_* shorthands, and the semi-additive windows.
_BARE_WINDOW = re.compile(r"group_\w+|(last|first)_value(_in_period)?", re.IGNORECASE)

#: An inner aggregate -> the column aggregation that re-aggregates its per-group values
#: the same way (a count re-aggregates by SUM; the `_if` forms as their base).
_REAGGREGATE = {"sum": "SUM", "count": "SUM", "average": "AVERAGE", "min": "MIN", "max": "MAX",
                "sum_if": "SUM", "count_if": "SUM", "average_if": "AVERAGE",
                "min_if": "MIN", "max_if": "MAX"}

_SINGLE_REF = re.compile(r"^\s*\[([^\]]+)\]\s*$")

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


def is_bare_window(expr: Optional[str]) -> bool:
    """True when the whole of `expr` is one call to group_aggregate, a group_* shorthand,
    last_value, first_value or an *_in_period spelling — an aggregate formula whose
    column `aggregation` ThoughtSpot applies (`sum ( last_value ( ... ) )` is not one)."""
    func = outermost_func(expr)
    return bool(func and _BARE_WINDOW.fullmatch(func))


def _first_arg(expr: str) -> str:
    """The text of the first argument of the call that is the whole of `expr`."""
    s = expr.strip()
    start = s.index("(") + 1
    depth = 0
    for i in range(start, len(s)):
        if s[i] in "([{":
            depth += 1
        elif s[i] in ")]}":
            if depth == 0:
                return s[start:i]
            depth -= 1
        elif s[i] == "," and depth == 0:
            return s[start:i]
    return s[start:]


def formula_aggregation(expr: Optional[str], formulas: Optional[dict] = None) -> str:
    """The `aggregation` a generator declares on a MEASURE formula column whose source
    gave none (BL-509, under the product owner's ruling of 2026-11-02):

    - a **bare window** (`is_bare_window`): ThoughtSpot applies it to the per-group
      result, so it re-aggregates the way the inner aggregate does — AVERAGE for
      `group_aggregate ( average ( ... ) , ... )` or `group_average`, MIN, MAX, and SUM
      for a sum or count (a balance summed across accounts); `_REAGGREGATE` is the map.
      An inner aggregate with no faithful re-aggregation (a ratio of sums, a unique
      count, a stddev) is not additive, so AVERAGE: summing it is the failure D13
      reports. An inner `[formula_X]` (how Power BI and promote write it) is resolved
      through `formulas` (reference — id, or name — -> expr), following a chain of
      references; one that cannot be resolved, or no inner aggregate at all, keeps SUM;
    - any other aggregate formula: ignored, but declared — SUM, the repo convention;
    - a per-row formula: applied, and SUM is the convention a generator falls back to.
    """
    if not is_bare_window(expr):
        return "SUM"
    func = outermost_func(expr)
    if func.startswith("group_") and func != "group_aggregate":
        return _REAGGREGATE.get(func[len("group_"):], "AVERAGE")
    return _reaggregation(_first_arg(expr), formulas or {}, set())


def _reaggregation(inner: str, formulas: dict, seen: set) -> str:
    ref = _SINGLE_REF.match(inner)
    if ref:
        name = ref.group(1)
        if name in seen or not isinstance(formulas.get(name), str):
            return "SUM"            # opaque (a column, an unknown or cyclic reference)
        return _reaggregation(formulas[name], formulas, seen | {name})
    func = outermost_func(inner)
    if func in _REAGGREGATE:
        return _REAGGREGATE[func]
    return "AVERAGE" if is_aggregate_expr(inner) else "SUM"


def formula_ref_exprs(formulas: list) -> dict:
    """{id: expr, name: expr} over `formulas[]`, the index `formula_aggregation` resolves
    an inner `[formula_X]` (or `[Name]`) reference through."""
    out: dict = {}
    for f in formulas or []:
        if not isinstance(f, dict) or not isinstance(f.get("expr"), str):
            continue
        for key in (f.get("id"), f.get("name")):
            if isinstance(key, str) and key:
                out[key] = f["expr"]
    return out


def declare_formula_aggregations(columns: list, formulas: list) -> None:
    """In place: give every formula column in `columns` that is a MEASURE (an untyped one
    reads as MEASURE, as the builders default it) and declares no `aggregation` the one
    `formula_aggregation` names, resolving references through `formulas`. A declared
    aggregation, an ATTRIBUTE and a table column are left as they are (BL-509)."""
    exprs = formula_ref_exprs(formulas)
    by_id = {f.get("id"): f.get("expr") for f in formulas or [] if isinstance(f, dict)}
    for col in columns or []:
        if not isinstance(col, dict) or not col.get("formula_id"):
            continue
        props = col.setdefault("properties", {})
        if props.get("column_type", "MEASURE") != "MEASURE" or props.get("aggregation"):
            continue
        expr = by_id.get(col["formula_id"])
        props["aggregation"] = formula_aggregation(expr if isinstance(expr, str) else None, exprs)


def classify_expr(expr: Optional[str], formulas: Optional[dict] = None) -> dict[str, Any]:
    """Classify a single formula expression not yet attached to a Model column.

    Matches answer-promote's `infer_column_type` semantics: MEASURE iff the
    expression contains an aggregate function call, else ATTRIBUTE (`aggregation`
    None). A MEASURE's `aggregation` is `formula_aggregation(expr)`: ignored by
    ThoughtSpot for an aggregate formula (SUM, declared by convention) but applied to
    a bare group_aggregate / last_value / first_value, so a promoted per-group average
    is declared AVERAGE rather than summed (BL-509). `formulas` (`formula_ref_exprs`)
    resolves an inner `[formula_X]` reference.

    Returns: {"column_type": "MEASURE"|"ATTRIBUTE", "aggregation": str|None,
    "is_aggregate": bool}.
    """
    is_agg = is_aggregate_expr(expr)
    column_type = "MEASURE" if is_agg else "ATTRIBUTE"
    aggregation = formula_aggregation(expr, formulas) if column_type == "MEASURE" else None
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
