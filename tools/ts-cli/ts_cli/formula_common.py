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
# round(): SQL digit count <-> ThoughtSpot rounding increment (BL-331)
# ---------------------------------------------------------------------------
#
# ThoughtSpot `round(x, n)` takes a rounding INCREMENT, not a decimal-place count.
# It compiles to `n * round(x / NULLIF(n, 0))` (seen via `ts agentql generate-sql`,
# live-probed on se-thoughtspot 2026-10-06). On 1234.5678:
#     round(x) = 1235     round(x, 1) = 1235      round(x, 0.01) = 1234.57
#     round(x, 2) = 1234  round(x, 10) = 1230     round(x, 0.5)  = 1234.5
#     round(x, 0) = NULL  round(x, -2) = 1234
# SQL `ROUND(x, d)` (Snowflake, Databricks, Tableau, DAX) takes a digit count, so
# every translator must convert: d -> 10^-d one way, a power-of-ten increment -> d
# the other. Copying the argument verbatim is a silent wrong-numbers bug (it shipped
# in four translators). One copy of the conversion, here; never re-implement it.

# An integer literal, optionally signed/parenthesised, optionally written `2.0`.
_SQL_INT_LITERAL_RE = re.compile(r"^\(?\s*([+-])?\s*(\d+)(?:\.0*)?\s*\)?$")

#: Largest |digit count| accepted. Snowflake NUMBER scale tops out at 37 and its
#: ROUND scale range is about +-38; past that a "digit count" is an authoring error.
MAX_ROUND_DIGITS = 37


def sql_int_digits(digits: str) -> int | None:
    """An integer-literal digit count (``"2"``, ``"- 2"``, ``"2.0"``) as int, else None."""
    m = _SQL_INT_LITERAL_RE.match((digits or "").strip())
    if not m:
        return None
    return int(m.group(2)) * (-1 if m.group(1) == "-" else 1)


def sql_digits_to_ts_increment(digits: str) -> str | None:
    """SQL ROUND digit count -> ThoughtSpot round() increment, as literal text.

    ``"2"`` / ``"2.0"`` -> ``"0.01"``, ``"0"`` -> ``"1"``, ``"-2"`` / ``"- 2"`` ->
    ``"100"``. Returns None when ``digits`` is not an integer literal (a column,
    an expression, a fraction) or exceeds MAX_ROUND_DIGITS in magnitude — the
    caller must pass it through, refuse it, or flag it.
    """
    from decimal import Decimal
    d = sql_int_digits(digits)
    if d is None or abs(d) > MAX_ROUND_DIGITS:
        return None
    return format(Decimal(1).scaleb(-d), "f")


def ts_round_from_sql_digits(x: str, digits: str | None = None, *,
                             aggregated: bool = False) -> str:
    """SQL ``ROUND(x[, d])`` -> ThoughtSpot formula text (spaced token style).

    Literal d -> ``round ( x , 10^-d )``; absent d -> ``round ( x )``; a
    non-literal d has no native increment form, so it passes through to the
    warehouse unchanged: ``sql_double_op ( "ROUND({0}, {1})" , x , d )``.

    That pass-through is row-level, so a non-literal d over an aggregated x
    raises UntranslatableError rather than emit it. ``aggregated=True`` tells it x is aggregated when the text cannot
    show it (a ``[formula_X]`` reference to a metric). A literal d beyond
    +-MAX_ROUND_DIGITS always raises.
    """
    if digits is None:
        return f"round ( {x} )"
    inc = sql_digits_to_ts_increment(digits)
    if inc is not None:
        return f"round ( {x} , {inc} )"
    if sql_int_digits(digits) is not None:
        raise UntranslatableError(
            f"ROUND digit count {digits.strip()} is outside "
            f"+-{MAX_ROUND_DIGITS} — BL-331")
    if aggregated or expr_is_aggregated(x):
        raise UntranslatableError(
            "ROUND with a non-literal digit count over an aggregate has no "
            "ThoughtSpot form (round() takes an increment; the sql_double_op "
            "pass-through is row-level) — BL-331")
    return f'sql_double_op ( "ROUND({{0}}, {{1}})" , {x} , {digits} )'


def ts_increment_to_sql_digits(increment: str) -> int | None:
    """ThoughtSpot round() increment literal -> SQL ROUND digit count.

    ``"0.01"`` -> 2, ``"1"`` -> 0, ``"100"`` -> -2. Returns None when the
    increment is not a positive power of ten (``"0.5"``, ``"25"``, a non-number)
    — the caller emits ``inc * ROUND(x / inc)`` instead, which is the form
    ThoughtSpot itself compiles round() to, so it agrees for any increment. Raises ValueError for a zero increment: ThoughtSpot evaluates
    ``round(x, 0)`` to NULL, so there is no faithful ``ROUND(x, d)`` for it.
    """
    from decimal import Decimal, InvalidOperation
    try:
        value = Decimal((increment or "").strip())
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    if value == 0:
        raise ValueError("round(x, 0) evaluates to NULL in ThoughtSpot "
                         "(the increment divides by NULLIF(0, 0))")
    if value < 0:
        return None
    _sign, digit_tuple, exponent = value.normalize().as_tuple()
    if digit_tuple != (1,):
        return None
    return -exponent


# ---------------------------------------------------------------------------
# Weekday numbering -> ThoughtSpot day_number_of_week (BL-334)
# ---------------------------------------------------------------------------
#
# ThoughtSpot `day_number_of_week ( d )` is FIXED at 1 = Monday ... 7 = Sunday:
# it compiles to `(MOD((DATEDIFF(day, DATE '1970-01-01', d) + 3), 7) + 1)`,
# independent of the warehouse's WEEK_START (live-probed, se-thoughtspot,
# 2026-10-06). Every source numbers its weekdays from some FIRST DAY with some
# BASE (0 or 1), and a bare rename to `day_number_of_week` is right only for
# (Monday, 1). Anything else imports cleanly and returns a silently wrong number
# — Snowflake DAYOFWEEK and Databricks DAYOFWEEK both shipped that way.
#
# One helper so the offset arithmetic lives once (BL-217): a source day number
# is  mod(dnw - 1 - first_idx, 7) + base  ==  mod(dnw + (6 - first_idx), 7) + base,
# where first_idx is the source's first day, Monday-based (Monday = 0 ... Sunday
# = 6). Exact under the Model's default calendar; a Model calendar with a
# non-Monday week start is unverified territory (BL-334 item 4).

WEEKDAY_FIRST_DAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def ts_weekday_number(date_expr: str, *, first_day: int | str, base: int,
                      compact: bool = False) -> str:
    """ThoughtSpot formula giving a source's weekday NUMBER for ``date_expr``.

    ``first_day`` is the day the source numbers ``base`` — a name
    (``"sunday"``) or a Monday-based index (Monday = 0 ... Sunday = 6, which is
    also Qlik's ``first_week_day`` encoding). ``base`` is 0 or 1. ``compact``
    selects the caller's spacing style (``fn(x)`` vs ``fn ( x )``); the value is
    identical. Any additive result is parenthesised so it composes safely inside
    a larger expression.

    >>> ts_weekday_number("[d]", first_day="sunday", base=0)
    'mod ( day_number_of_week ( [d] ) , 7 )'
    >>> ts_weekday_number("[d]", first_day="sunday", base=1)
    '( mod ( day_number_of_week ( [d] ) , 7 ) + 1 )'
    >>> ts_weekday_number("[d]", first_day="monday", base=1)
    'day_number_of_week ( [d] )'
    """
    if isinstance(first_day, str):
        try:
            idx = WEEKDAY_FIRST_DAY_INDEX[first_day.strip().lower()]
        except KeyError:
            raise ValueError(f"unknown weekday name {first_day!r}") from None
    else:
        idx = int(first_day)
    if not 0 <= idx <= 6:
        raise ValueError(f"first_day index must be 0-6 (Monday-based), got {idx}")
    if base not in (0, 1):
        raise ValueError(f"weekday base must be 0 or 1, got {base}")

    if compact:
        dnw = f"day_number_of_week({date_expr})"

        def _mod(x: str) -> str:
            return f"mod({x}, 7)"

        def _paren(x: str) -> str:
            return f"({x})"
    else:
        dnw = f"day_number_of_week ( {date_expr} )"

        def _mod(x: str) -> str:
            return f"mod ( {x} , 7 )"

        def _paren(x: str) -> str:
            return f"( {x} )"

    if idx == 0:  # Monday-first: a plain offset, no wrap-around
        return dnw if base == 1 else _paren(f"{dnw} - 1")
    shift = 6 - idx
    core = _mod(dnw if shift == 0 else f"{dnw} + {shift}")
    return core if base == 0 else _paren(f"{core} + {base}")


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
# SQL pass-through and 1-based SUBSTR (BL-340 / BL-342 / BL-343)
# ---------------------------------------------------------------------------
#
# Shared by sv_sql (Snowflake) and databricks/mv_sql so the two SQL engines
# cannot drift apart again (BL-217): both copied SUBSTR's 1-based start into
# ThoughtSpot's zero-based substr (BL-340).

_SQL_NUM_LITERAL_RE = re.compile(r"^-?\s*\d+(?:\.\d+)?$")
_SQL_STR_LITERAL_RE = re.compile(r"^'(?:[^']|'')*'$")
_SQL_BOOL_LITERALS = frozenset({"true", "false"})


def sql_passthrough_call(op: str, fn: str, args: list[str]) -> str:
    """``op ( "FN(<args>)" , … )`` — a warehouse pass-through, exact by construction.

    Numeric, string and boolean literals are inlined into the template
    (``TO_CHAR({0}, 'YYYY-MM')``); every other argument becomes a ``{n}``
    placeholder. Refused when no argument is a column (a pass-through needs one), or
    when a string literal holds a brace (the template would read it as a
    placeholder), a backslash, or a double quote. The double quote is a real loss — a
    Snowflake format model's literal text, ``'YYYY"m"MM'`` — but the template has no
    escape for it: ``\\"`` was live-probed and rejected at import (*Search did not find
    "TO_CHAR ( { 0 } , 'YYYY"m"MM' ) "*, error_code 14516; formula fidelity M0
    ``sf-date-018``, se-thoughtspot 2026-10-06).
    """
    parts: list[str] = []
    bound: list[str] = []
    for a in args:
        a = a.strip()
        if _SQL_NUM_LITERAL_RE.match(a):
            parts.append(a.replace(" ", ""))
        elif a.lower() in _SQL_BOOL_LITERALS:
            parts.append(a.upper())
        elif _SQL_STR_LITERAL_RE.match(a):
            if any(ch in a for ch in '"{}\\'):
                raise UntranslatableError(
                    f"{fn}: literal {a} holds a double quote, a brace or a backslash, "
                    "which a sql_*_op template cannot carry (no escape exists — "
                    "live-probed 2026-10-06)")
            parts.append(a)
        else:
            parts.append("{%d}" % len(bound))
            bound.append(a)
    if not bound:
        raise UntranslatableError(f"{fn} with only literal arguments has no pass-through form")
    template = f"{fn}({', '.join(parts)})"
    return f'{op} ( "{template}" , ' + " , ".join(bound) + " )"


def sql_substr_to_ts(fn: str, args: list[str]) -> str:
    """1-based SQL ``SUBSTR(s, start[, len])`` → ThoughtSpot (BL-340).

    ThoughtSpot ``substr`` is ZERO-based — ``substr ( s , 2 , 3 )`` compiles to
    ``SUBSTRING(s, (2 + 1), 3)`` — and takes exactly three arguments.

    * literal ``start >= 1``: native, folded — ``SUBSTR(s, 2, 3)`` → ``substr ( s , 1 , 3 )``;
      the 2-argument form takes the rest of the string, ``strlen ( s )`` long.
    * literal ``start <= 0``, or a non-literal ``start``: a ``sql_string_op`` pass-through.
      Snowflake and Databricks both count a negative start from the END of the string
      (and Snowflake treats 0 as 1), which ``substr`` does not define; a non-literal
      start could be either at run time. The pass-through is exact by construction.
    """
    if len(args) not in (2, 3):
        raise UntranslatableError(f"{fn} expects 2 or 3 arguments, got {len(args)}")
    s, start = args[0], args[1]
    n = sql_int_digits(start)
    if n is None or n <= 0 or "." in start:
        return sql_passthrough_call("sql_string_op", fn, args)
    length = args[2] if len(args) == 3 else f"strlen ( {s} )"
    return f"substr ( {s} , {n - 1} , {length} )"


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
    quote: str = '"',
) -> tuple[str, set[str]]:
    """Rewrite `fn(args...)` into a ThoughtSpot `sql_*_op` pass-through.

    ``quote`` defaults to the DOUBLE-quoted outer template. It defaulted to a
    single quote — a form nothing in this repo emits and nothing has verified
    against the parser. Both live callers already override it, and
    ``qlik/functions.py`` records why: taking the default made Qlik alone emit
    the single-quoted form while its siblings and every example in the patterns
    schema use the double-quoted one. A default reachable by omitting one keyword
    argument, in the helper BL-171 created to stop emitting forms ThoughtSpot
    rejects, is a trap rather than a convenience (audit 9.7).

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


# A single column reference, optionally qualified and/or double-quoted:
#   COL   "COL"   tbl.COL   tbl."COL"   "tbl"."COL"
_QUALIFIED_BARE_COLUMN_RE = re.compile(
    r'^(?:(?P<tbl>"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*)\s*\.\s*)?'
    r'(?P<col>"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*)$')


def bare_column_name(expr: str | None, alias_table: str | None = None) -> str | None:
    """Return the column an expression names, if it names exactly one column.

    A rename is a COLUMN in ThoughtSpot, not a formula — and, as
    `_translate_dimension` documents, "a table needs at least one real column
    selected or it imports with a cross-join warning". The previous pattern
    only recognised the UNQUALIFIED, UNQUOTED form, so a rename written
    `DM_DATE_DIM.DATE_VALUE as dm_date_dim."DATE"` was classified as computed and
    emitted as a formula. On a date dimension whose only other references are join
    keys that left the table with **zero** `column_id` entries, and ThoughtSpot
    refuses the import outright:

        "One or more tables have been added to the model without selecting any of
         their columns ... DM_DATE_DIM"

    (live, converting TEST_SV_DUNDER_MIFFLIN_SALES_INVENTORY, 2026-09-02.) BL-212
    taught the expression *translator* to read quoted identifiers; this is the
    *classifier* catching up.

    When the expression is qualified, the qualifier must match `alias_table`
    (case-insensitively) — a reference to a different table is not a simple rename
    of this one's column, so it correctly falls through to the formula path.
    Returns the column name with quotes stripped, or None.
    """
    if not expr:
        return None
    m = _QUALIFIED_BARE_COLUMN_RE.match(expr.strip())
    if not m:
        return None
    tbl = m.group("tbl")
    if tbl is not None and alias_table is not None:
        if tbl.strip('"').lower() != alias_table.strip('"').lower():
            return None
    return m.group("col").strip('"')
