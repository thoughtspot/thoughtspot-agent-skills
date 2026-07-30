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
    arity)`, e.g. ``{"trim": ("sql_string_op", "TRIM({0})", 1)}``. Markers are
    matched case-SENSITIVELY, and templates are conventionally UPPERCASE, so a
    rewritten call is never re-matched (no unbounded rescan) while nested
    occurrences still resolve on the following pass.

    Returns ``(rewritten_text, unresolved)``. `unresolved` holds marker names
    whose call had the wrong argument count or unbalanced parens: those are
    left untouched so the caller can flag them for review, because emitting a
    bare `trim ( )` would fail at import (flag, don't downgrade).
    """
    if not templates:
        return text, set()
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])(" + "|".join(
            sorted((re.escape(k) for k in templates), key=len, reverse=True))
        + r")\s*\(")
    unresolved: set[str] = set()
    search_from = 0
    guard = 0
    while guard < 200:
        guard += 1
        m = pattern.search(text, search_from)
        if not m:
            break
        name = m.group(1)
        op, template, arity = templates[name]
        open_idx = m.end() - 1
        close_idx = _close_paren(text, open_idx)
        if close_idx < 0:
            unresolved.add(name)
            break
        args = _split_top_level_args(text[open_idx + 1:close_idx])
        if len(args) != arity:
            unresolved.add(name)
            search_from = m.end()
            continue
        replacement = (f"{op}({quote}{template}{quote}, "
                       + ", ".join(args) + ")")
        text = text[:m.start()] + replacement + text[close_idx + 1:]
        search_from = m.start()
    return text, unresolved


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
