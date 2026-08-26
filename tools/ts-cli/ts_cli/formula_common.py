"""Platform-neutral formula/name transforms shared by the Tableau and Databricks
model builders.

Relocated from ts_cli/model_builder.py + ts_cli/tableau/naming.py (BL-063 PR 5) —
these encode ThoughtSpot TML semantics (formula_ cross-reference prefix,
double-aggregation collapse, column/formula/parameter collision rules), not any
source platform's. Pure functions, stdlib only — part of the Genie-vendorable
closure. Never fork these into a platform module; import them.
"""
from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# SQL CAST target type -> ThoughtSpot conversion function
# ---------------------------------------------------------------------------
#
# Shared so a fix in one engine cannot silently miss the other — the divergence
# BL-161 item 1 predicted and audit 4.1 found had already happened: the Databricks
# clone discarded the target type outright while Snowflake mapped it.
#
# The two engines legitimately differ on WIDENING casts, and that is deliberate:
#
#   * Snowflake emits the conversion (CAST(x AS DOUBLE) -> to_double([x])), which
#     ts-snowflake-formula-translation.md documents and `to_double` is a valid
#     ThoughtSpot formula function (thoughtspot-formula-patterns.md).
#   * Databricks unwraps it, which ts-from-databricks.md documents. Justified by
#     live test on se-thoughtspot 2026-08-26:
#         SELECT SUM("UNITS_SOLD") / COUNT("ORDER_ID")  ->  type DOUBLE, 5128.71
#     Both operands are INT64, so ThoughtSpot promotes integer division itself and
#     a CAST(... AS DOUBLE) around a numerator is genuinely redundant.
#
# What is NOT optional is a NARROWING cast. Dropping one changes the answer, and
# that was the real 4.1 bug on the Databricks side:
#     CAST(4.7 AS INT)  must truncate to 4
#     CAST(ts AS DATE)  must drop the time component
#
#: Casts whose target type changes the VALUE. Every engine MUST emit these;
#: dropping one is a silent wrong-numbers bug.
CAST_MAP_LOAD_BEARING = {
    "INTEGER": "to_integer", "INT": "to_integer", "BIGINT": "to_integer",
    "SMALLINT": "to_integer", "TINYINT": "to_integer",
    "DATE": "to_date", "TIMESTAMP": "to_date",
    "BOOLEAN": "to_bool",
}

#: Widening / no-op casts. Enumerated rather than defaulted so a genuinely
#: UNKNOWN target type still fails loudly instead of silently unwrapping.
CAST_TYPES_WIDENING = frozenset({
    "NUMBER", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL",
    "VARCHAR", "TEXT", "STRING", "CHAR",
})

#: Load-bearing + widening, for engines that emit a conversion for every
#: recognised target (Snowflake). Keeps sv_sql's behaviour unchanged.
CAST_MAP_FULL = {
    **CAST_MAP_LOAD_BEARING,
    "NUMBER": "to_double", "FLOAT": "to_double", "DOUBLE": "to_double",
    "DECIMAL": "to_double", "NUMERIC": "to_double", "REAL": "to_double",
    "VARCHAR": "to_string", "TEXT": "to_string", "STRING": "to_string",
    "CHAR": "to_string",
}

#: Back-compat alias.
CAST_MAP = CAST_MAP_FULL


# ---------------------------------------------------------------------------
# Shared translation-failure exception
# ---------------------------------------------------------------------------

class UntranslatableError(Exception):
    """A formula/expression construct has no deterministic translation to the
    other platform's syntax.

    Canonical home (BL-063 PR 14 — Genie vendor wiring): both the reverse
    (Databricks-SQL -> ThoughtSpot formula, `mv_sql.py`) and forward
    (ThoughtSpot formula -> Databricks-SQL, `mv_emit_expr.py`) directions
    raise this SAME exception type for the same concept — "no documented
    deterministic mapping exists" — so a single `except UntranslatableError`
    catches either direction's failures. Concatenating both modules into one
    vendored Genie notebook namespace (`agents/databricks/build_mv_lib.py`)
    would otherwise define the class twice under one name, which
    `assert_no_duplicate_top_level_names` rejects. `mv_sql.py` and
    `mv_emit_expr.py` both re-export this name (`from ts_cli.formula_common
    import UntranslatableError`) so existing `from
    ts_cli.databricks.mv_sql import UntranslatableError` / `from
    ts_cli.databricks.mv_emit_expr import UntranslatableError` call sites are
    unaffected.
    """


# ---------------------------------------------------------------------------
# Name collision resolution
# ---------------------------------------------------------------------------

def resolve_name_collisions(
    columns: list[dict],
    formulas: list[dict],
    parameters: list[dict],
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Detect and resolve name collisions between columns, formulas, parameters.

    Rules:
      - If a formula name matches a parameter name, rename the formula
        (append " Selection" suffix)
      - If a column name matches a formula name, drop the column (keep formula)
      - Returns (cleaned_columns, renamed_formulas, rename_map)

    rename_map: {old_name: new_name} for formulas that were renamed.
    """
    param_names = {p["name"] for p in parameters}
    formula_names = {f["name"] for f in formulas}

    rename_map: dict[str, str] = {}
    for f in formulas:
        if f["name"] in param_names:
            new_name = f["name"] + " Selection"
            rename_map[f["name"]] = new_name
            f["name"] = new_name

    new_formula_names = {f["name"] for f in formulas}
    cleaned_columns = [
        c for c in columns
        if c["name"] not in new_formula_names
    ]
    dropped = len(columns) - len(cleaned_columns)

    return cleaned_columns, formulas, rename_map


# ---------------------------------------------------------------------------
# Duplicate column_id → formula promotion (TML invariant I8/I5)
# ---------------------------------------------------------------------------

# Column-aggregation enum (columns[].properties.aggregation) → ThoughtSpot
# formula aggregation function. Covers the enum values BOTH the from-Snowflake
# (sv_translate._SIMPLE_AGG_MAP — STDDEV/MEDIAN) and from-Databricks
# (mv_translate._COLUMN_AGG — STD_DEVIATION) builders emit, plus COUNT_DISTINCT
# for the related I5 rule (a COUNT_DISTINCT column silently flips MEASURE →
# ATTRIBUTE; `unique count(...)` is the correct form).
_AGG_TO_FORMULA_FN = {
    "SUM": "sum",
    "AVERAGE": "average",
    "MIN": "min",
    "MAX": "max",
    "COUNT": "count",
    "MEDIAN": "median",
    "STDDEV": "stddev",
    "STD_DEVIATION": "stddev",
    "VARIANCE": "variance",
    "COUNT_DISTINCT": "unique count",
}


def promote_duplicate_column_ids(
    physical: list[dict],
    formula_entries: list[dict],
) -> tuple[list[dict], list[dict], list[str]]:
    """Keep every column_id unique (TML invariant I8) by re-expressing duplicate
    physical columns as formulas.

    When a source references one physical column both as a raw measure and as
    an aggregate metric (e.g. ``F_TIME_TO_RESOLVE`` + ``AVG(TIMETORESOLVE__C)``),
    the translate step emits two physical ``columns[]`` candidates with an
    identical ``TABLE::col`` column_id. ThoughtSpot rejects that on import
    ("columns should have unique column_id values"). This helper keeps the
    first occurrence of each column_id as a physical column and promotes every
    later occurrence to a formula:

    - MEASURE with a mapped aggregation → ``fn ( [TABLE::col] )`` (I5's
      COUNT_DISTINCT → ``unique count(...)`` is one row of the same map).
    - Anything else (MEASURE with an unmapped aggregation, or two ATTRIBUTE
      columns on one physical column) → left in place, so ``ts tml lint`` I8
      still surfaces it rather than the builder either emitting a wrong formula
      or silently masking a modelling mistake. Only an aggregate expressible as
      a formula is promoted; a bare duplicate dimension is a lint finding for
      the author to resolve.

    Both builders call this AFTER ``resolve_name_collisions`` (so display-name
    clashes are already settled) and BEFORE the formula-text pipeline (so a
    promoted expr is prefixed/double-agg-checked like any other formula).

    Each candidate is a builder dict carrying at least ``name`` (display title)
    and ``entry`` (the translated column dict with ``table`` / ``column`` /
    ``aggregation`` / ``column_type``), plus the builder's own source-name key
    used to re-locate it during emission. A promoted candidate keeps that
    source-name key and gains an ``expr`` key, so the builder's emit walk finds
    it in ``formula_entries`` instead of ``physical``. Neither input list is
    mutated; returns ``(kept_physical, formula_entries_with_promotions,
    promoted_titles)``.
    """
    seen: set[str] = set()
    kept: list[dict] = []
    out_formulas = list(formula_entries)
    promoted_titles: list[str] = []
    for cand in physical:
        entry = cand["entry"]
        col_id = f"{entry['table']}::{entry['column']}"
        fn = None
        if col_id not in seen:
            seen.add(col_id)
            kept.append(cand)
            continue
        if entry.get("column_type") == "MEASURE":
            fn = _AGG_TO_FORMULA_FN.get((entry.get("aggregation") or "SUM").upper())
        if fn is None:
            # Not an aggregate we can re-express as a formula (unmapped measure
            # aggregation, or a bare duplicate dimension) — leave it in place so
            # `ts tml lint` I8 surfaces it for the author to resolve.
            kept.append(cand)
            continue
        # A formula-measure column's aggregation is ignored by ThoughtSpot (the
        # expr carries the aggregation); SUM matches the convention used for
        # every other formula measure.
        promoted_entry = dict(entry, aggregation="SUM")
        out_formulas.append(
            dict(cand, entry=promoted_entry, expr=f"{fn} ( [{col_id}] )"))
        promoted_titles.append(cand["name"])
    return kept, out_formulas, promoted_titles


# ---------------------------------------------------------------------------
# Formula cross-reference prefix
# ---------------------------------------------------------------------------

def add_formula_prefix(
    expr: str,
    formula_names: set[str],
    parameter_names: set[str],
) -> str:
    """Rewrite [Name] → [formula_Name] for formula cross-references.

    Skips table-qualified refs ([TABLE::COL]), parameter refs, and refs
    that already have the formula_ prefix.
    """
    def _replace(m: re.Match) -> str:
        ref = m.group(1)
        if "::" in ref:
            return m.group(0)
        if ref in parameter_names:
            return m.group(0)
        if ref.startswith("formula_"):
            return m.group(0)
        if ref in formula_names:
            return f"[formula_{ref}]"
        return m.group(0)

    return re.sub(r"\[([^\]]+)\]", _replace, expr)


# ---------------------------------------------------------------------------
# sql_*_op pass-through rewriting (BL-171)
# ---------------------------------------------------------------------------

def _split_top_level_args(inner: str) -> list[str]:
    """Split a call's argument text on top-level commas (quote/paren aware)."""
    args: list[str] = []
    depth, quote, cur = 0, None, []
    for ch in inner:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        args.append("".join(cur).strip())
    return [a for a in args if a != ""]


def _close_paren(text: str, open_idx: int) -> int:
    """Index of the ')' matching the '(' at open_idx, or -1 (quote aware)."""
    depth, quote = 0, None
    for i in range(open_idx, len(text)):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    """[(start, end)) index ranges covered by string literals.

    Both quote styles matter: a ThoughtSpot literal is `'...'` and an
    `sql_*_op` template is `"..."`, and a marker name can legitimately appear
    inside either as *data* (`Replace(Name, 'upper(x)', 'y')`). Doubled quotes
    (`'it''s'`, the escape ThoughtSpot uses) read as adjacent literals, which
    keeps the inner text quoted — conservative in the safe direction.
    """
    spans: list[tuple[int, int]] = []
    quote: str | None = None
    start = 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                spans.append((start, i + 1))
                quote = None
        elif ch in "'\"":
            quote = ch
            start = i
    if quote:                      # unterminated literal — treat to end of text
        spans.append((start, len(text)))
    return spans


def _in_quotes(idx: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= idx < b for a, b in spans)


def rewrite_marker_calls(
    text: str,
    handlers: dict[str, Any],
) -> tuple[str, set[str]]:
    """Rewrite `marker(args...)` calls via `handlers[marker](args) -> str|None`.

    The single call-rewriting scanner shared by the regex-pipeline converters
    (qlik, powerbi). `handlers` is keyed on a LOWERCASE marker name — the
    intermediate name a converter's function map produces for something that
    needs an argument-aware rewrite rather than a rename.

    Two properties make it safe to run over its own output:

    * **Quote-aware.** A marker inside a string literal is data, not a call —
      `Replace(Name, 'upper(x)', 'y')` must not have its literal rewritten, and
      an emitted `sql_string_op('TRIM({0})', …)` template must not be re-read as
      a `trim` call. Both the marker search and the paren walk skip literals.
    * **Terminating.** A handler's output must not itself contain the marker as
      a callable token (pass-through templates are UPPERCASE inside quotes;
      compositions emit a different function name), so each rewrite strictly
      reduces the marker count while nested occurrences still resolve on the
      following pass.

    Returns ``(rewritten_text, unresolved)``. A handler returning None (wrong
    arity, or a shape it cannot express) leaves the call untouched, and **any
    marker still callable in the final text is reported in `unresolved`** —
    including after an unbalanced-paren bail-out or guard exhaustion. Callers
    must surface `unresolved` as NEEDS REVIEW: the surviving text is a bare
    call to a function ThoughtSpot does not have, so shipping it silently would
    trade a loud import failure for a wrong formula (flag, don't downgrade).
    """
    if not handlers:
        return text, set()
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])(" + "|".join(
            sorted((re.escape(k) for k in handlers), key=len, reverse=True))
        + r")\s*\(")
    search_from = 0
    guard = 0
    while guard < 200:
        guard += 1
        spans = _quoted_spans(text)
        m = None
        for candidate in pattern.finditer(text, search_from):
            if not _in_quotes(candidate.start(), spans):
                m = candidate
                break
        if not m:
            break
        name = m.group(1)
        open_idx = m.end() - 1
        close_idx = _close_paren(text, open_idx)
        if close_idx < 0:
            break                          # unbalanced — final sweep flags it
        args = _split_top_level_args(text[open_idx + 1:close_idx])
        replacement = handlers[name](args)
        if replacement is None:
            search_from = m.end()          # final sweep flags it
            continue
        text = text[:m.start()] + replacement + text[close_idx + 1:]
        search_from = m.start()
    # Final sweep: whatever is still a callable marker outside a literal was
    # not translated, whether through wrong arity, unbalanced parens or guard
    # exhaustion. Reporting it is what keeps the failure loud.
    spans = _quoted_spans(text)
    unresolved = {m.group(1) for m in pattern.finditer(text)
                  if not _in_quotes(m.start(), spans)}
    return text, unresolved


def _passthrough_handler(op: str, template: str, arity: int, quote: str) -> Any:
    def handler(args: list[str]) -> str | None:
        if len(args) != arity:
            return None
        return f"{op}({quote}{template}{quote}, " + ", ".join(args) + ")"
    return handler


def wrap_passthrough_calls(
    text: str,
    templates: dict[str, tuple[str, str, int]],
    quote: str = "'",
) -> tuple[str, set[str]]:
    """Rewrite `fn(args...)` into a ThoughtSpot `sql_*_op` pass-through.

    BL-171: a converter that renames a source function to a ThoughtSpot name
    which does not exist produces a formula rejected at import (error_code
    14516). For the functions with no ThoughtSpot equivalent — `upper`,
    `lower`, `trim`, `ltrim`, `rtrim`, `replace` (all live-disproved on
    se-thoughtspot: 2026-06-13 for the first two, 2026-07-29/30 for the rest)
    — the translation is a `sql_*_op` pass-through instead.

    `templates` maps a LOWERCASE marker name to `(sql_op, sql_template,
    arity)`, e.g. ``{"trim": ("sql_string_op", "TRIM({0})", 1)}``. A thin
    wrapper over :func:`rewrite_marker_calls` — see there for the quoting and
    termination guarantees, and for what `unresolved` obliges the caller to do.
    """
    return rewrite_marker_calls(
        text,
        {name: _passthrough_handler(op, template, arity, quote)
         for name, (op, template, arity) in templates.items()},
    )


# ---------------------------------------------------------------------------
# Double-aggregation detection
# ---------------------------------------------------------------------------

_AGG_FUNCTIONS = re.compile(
    r"\b(sum|average|count|unique\s+count|max|min|sum_if|count_if|average_if|"
    r"unique_count_if|cumulative_sum|cumulative_average|cumulative_max|"
    r"cumulative_min|stddev|variance|moving_sum|moving_average|moving_max|"
    r"moving_min|group_aggregate)\s*\(",
    re.IGNORECASE,
)


def expr_is_aggregated(expr: str) -> bool:
    """Check if an expression contains aggregation functions."""
    return bool(_AGG_FUNCTIONS.search(expr))


def fix_double_aggregation(
    expr: str,
    formula_exprs: dict[str, str],
) -> str:
    """Replace sum([formula_X]) with [formula_X] when X is already aggregated.

    Handles sum, count, average, max, min and their _if variants.
    """
    _WRAPPED_REF = re.compile(
        r"\b(sum|average|count|max|min)\s*\(\s*\[formula_([^\]]+)\]\s*\)",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        ref_name = m.group(2)
        ref_expr = formula_exprs.get(ref_name, "")
        if expr_is_aggregated(ref_expr):
            return f"[formula_{ref_name}]"
        return m.group(0)

    return _WRAPPED_REF.sub(_replace, expr)
