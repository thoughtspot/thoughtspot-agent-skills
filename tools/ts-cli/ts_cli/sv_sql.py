"""Snowflake SQL expression -> ThoughtSpot formula text.

Pure functions: SQL text + a column resolver in, TS formula text out. No
I/O, no network calls — trivially unit-testable.

The function map below IS agents/shared/mappings/ts-snowflake/
ts-snowflake-formula-translation.md encoded as data. Extend the doc and this
module together; an unmapped construct raises UntranslatableError (the
caller records a skipped[] entry — fail loud, never silent).

Output style: tokens joined with single spaces (`sum ( [T::a] * [T::b] )`),
byte-matching the verified worked examples in
agents/shared/worked-examples/snowflake/.
"""
from __future__ import annotations

import re
from typing import Callable

from ts_cli.formula_common import (
    CAST_MAP_FULL,
    UntranslatableError,
    sql_digits_to_ts_increment,
    sql_int_digits,
    ts_round_from_sql_digits,
    ts_weekday_number,
)
from ts_cli.sv_sql_exact import EXACT_FORM_CALLS as _EXACT_FORM_CALLS
from ts_cli.sv_sql_exact import CAST_NUMBER, cast_number, cast_params, datediff_to_ts
from ts_cli.sv_sql_exact import is_aggregated as _is_aggregated
from ts_cli.sql_forms import (
    sqlf_fold_concat,
    sqlf_fold_multiplicative,
    sqlf_group,
    sqlf_guard_adjacent,
    sqlf_like,
    sqlf_null_default_call,
)


_TOKEN_RE = re.compile(
    r"(?P<string>'(?:[^']|'')*')"
    r"|(?P<number>\d+(?:\.\d+)?)"
    # A segment is a bare identifier OR a double-quoted one. Snowflake requires
    # the quoted form for reserved words and for names needing exact case
    # (`dm_date_dim."DATE"`); without this alternative the tokenizer stopped at
    # the dot and raised "unrecognized character '.'", silently costing the
    # construct (BL-212).
    r"|(?P<ident>(?:[A-Za-z_][\w$]*|\"[^\"]+\")"
    r"(?:\.(?:[A-Za-z_][\w$]*|\"[^\"]+\"))*)"
    r"|(?P<op><=|>=|!=|<>|\|\||[+\-*/%(),<>=])"
    r"|(?P<ws>\s+)")

_KEYWORDS = {"AND", "OR", "NOT", "CASE", "WHEN", "THEN", "ELSE", "END",
             "IS", "NULL", "IN", "BETWEEN", "TRUE", "FALSE", "DISTINCT",
             "AS", "CAST", "FROM", "LIKE", "OVER", "FILTER", "WHERE",
             "PARTITION", "BY", "ORDER", "ASC", "DESC", "ROWS", "RANGE",
             "UNBOUNDED", "PRECEDING", "FOLLOWING", "CURRENT", "ROW",
             "EXCLUDING", "ILIKE", "RLIKE", "REGEXP"}
#: Keyword operators translated as a sql_bool_op pass-through (BL-362).
_LIKE_OPS = frozenset({"LIKE", "ILIKE", "RLIKE", "REGEXP"})

_DATE_LITERAL_RE = re.compile(r"^'\d{4}-\d{2}-\d{2}'$")
_BARE_NOW_FNS = {"CURRENT_DATE": "today", "CURRENT_TIMESTAMP": "now"}


def tokenize(sql: str) -> list[tuple[str, str]]:
    """Tokenize into (kind, text): string|number|ident|kw|op."""
    toks: list[tuple[str, str]] = []
    i, n = 0, len(sql)
    while i < n:
        m = _TOKEN_RE.match(sql, i)
        if not m:
            raise UntranslatableError(
                f"unrecognized character {sql[i]!r} at position {i}")
        if m.lastgroup == "number" and re.match(r"[A-Za-z_]", sql[m.end():m.end() + 1]):
            # `1e1` would otherwise split into the number 1 and an identifier
            # `e1` resolved as a column — garbage, silently (BL-331).
            raise UntranslatableError(
                f"numeric literal at position {i} runs into "
                f"{sql[m.end()]!r} — scientific notation is not supported")
        i = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        text = m.group()
        if kind == "ident" and text.upper() in _KEYWORDS:
            toks.append(("kw", text.upper()))
        else:
            toks.append((kind, text))
    return toks


class _Cursor:
    def __init__(self, toks: list[tuple[str, str]]):
        self.toks = toks
        self.i = 0

    def peek(self, ahead: int = 0) -> tuple[str | None, str | None]:
        j = self.i + ahead
        return self.toks[j] if j < len(self.toks) else (None, None)

    def advance(self) -> tuple[str, str]:
        if self.i >= len(self.toks):
            raise UntranslatableError("unexpected end of expression")
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expect_op(self, text: str) -> None:
        kind, t = self.peek()
        if kind != "op" or t != text:
            raise UntranslatableError(f"expected {text!r}, got {t!r}")
        self.advance()


def translate_sql_expr(sql: str, resolver: Callable[[str], str]) -> str:
    """Translate one Snowflake SQL expression to ThoughtSpot formula text."""
    cur = _Cursor(tokenize(sql.strip()))
    out = _expr(cur, resolver)
    kind, text = cur.peek()
    if kind is not None:
        raise UntranslatableError(f"unexpected trailing token {text!r}")
    return out


_STOP_OPS = {")", ","}


def _expr(cur: _Cursor, resolver, stop_kws: frozenset = frozenset()) -> str:
    return " ".join(_expr_units(cur, resolver, stop_kws))


def _expr_units(cur: _Cursor, resolver,
                stop_kws: frozenset = frozenset(), finish: bool = True) -> list[str]:
    """``finish=False`` returns the units before ``_finish_units`` (BL-357)."""
    units: list[str] = []
    while True:
        kind, text = cur.peek()
        if kind is None:
            break
        if kind == "op" and text in _STOP_OPS:
            break
        if kind == "kw" and text in stop_kws:
            break
        cur.advance()
        if kind == "string":
            units.append(_string_literal(text))
        elif kind == "number":
            units.append(text)
        elif kind == "op":
            _op_unit(text, cur, resolver, units)
        elif kind == "ident":
            _ident_unit(text, cur, resolver, units)
        else:  # kw
            _keyword_unit(text, cur, resolver, units)
    if not units:
        raise UntranslatableError("empty expression")
    return _finish_units(units) if finish else units


def _finish_units(units: list[str]) -> list[str]:
    """Collapse NULLIF markers, then fold ``%`` and ``||`` at their precedence."""
    _collapse_nullif_markers(units)
    sqlf_fold_multiplicative(units)
    sqlf_fold_concat(units)
    return units


def _string_literal(text: str) -> str:
    if _DATE_LITERAL_RE.match(text):
        return f"to_date ( {text} , 'yyyy-MM-dd' )"
    return text


def _op_unit(text: str, cur: _Cursor, resolver, units: list[str]) -> None:
    if text == "(":
        inner = _expr(cur, resolver)
        cur.expect_op(")")
        units.append(f"( {inner} )")
    elif text == "<>":
        units.append("!=")
    else:  # `%` and `||` are folded by _finish_units (BL-362)
        units.append(text)


def _unquote_ident(text: str) -> str:
    """Strip Snowflake double-quoting from each dotted segment.

    ``dm_date_dim."DATE"`` -> ``dm_date_dim.DATE``. The quotes carry no meaning
    once the token is parsed — they exist in the DDL only so a reserved word or
    an exact-case name is legal SQL — and downstream resolution is
    case-insensitive.
    """
    if '"' not in text:
        return text
    return ".".join(seg[1:-1] if seg.startswith('"') and seg.endswith('"')
                    else seg
                    for seg in _split_dotted(text))


def _split_dotted(text: str) -> list[str]:
    """Split a dotted identifier on the dots that separate segments, ignoring
    any dot inside a double-quoted segment."""
    segs, buf, in_q = [], [], False
    for ch in text:
        if ch == '"':
            in_q = not in_q
            buf.append(ch)
        elif ch == "." and not in_q:
            segs.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    segs.append("".join(buf))
    return segs


def _ident_unit(text: str, cur: _Cursor, resolver, units: list[str]) -> None:
    text = _unquote_ident(text)
    upper = text.upper()
    nk, nt = cur.peek()
    if upper in _BARE_NOW_FNS:
        if nk == "op" and nt == "(":
            cur.advance()
            cur.expect_op(")")
        units.append(f"{_BARE_NOW_FNS[upper]} ( )")
        return
    if nk == "op" and nt == "(":
        cur.advance()
        units.append(_call(upper, cur, resolver))
        return
    if upper == "DIV" and units:
        raise UntranslatableError(
            "Snowflake has no DIV operator — integer division is TRUNC(a / b) (BL-360)")
    sqlf_guard_adjacent(units, text)
    units.append(resolver(text))


def _keyword_unit(text: str, cur: _Cursor, resolver,
                  units: list[str]) -> None:
    if text == "AND":
        units.append("and")
    elif text == "OR":
        units.append("or")
    elif text == "TRUE":
        units.append("true")
    elif text == "FALSE":
        units.append("false")
    elif text == "NULL":
        units.append("null")
    elif text == "NOT":
        _construct_not(cur, resolver, units)
    elif text == "CASE":
        units.append(_construct_case(cur, resolver))
    elif text == "CAST":
        units.append(_construct_cast(cur, resolver))
    elif text == "IS":
        _construct_is(cur, units)
    elif text == "IN":
        _construct_in(cur, resolver, units)
    elif text == "BETWEEN":
        _construct_between(cur, resolver, units)
    elif text in _LIKE_OPS:
        _construct_like(text, cur, units)
    elif text == "OVER":
        raise UntranslatableError(
            "OVER clause in expression — pre-split window expressions "
            "before calling translate_sql_expr")
    else:
        raise UntranslatableError(
            f"'{text}' has no documented ThoughtSpot mapping in this "
            f"position (ts-snowflake-formula-translation.md)")


# --- function map: ts-snowflake-formula-translation.md as data ---------------

_RENAME = {
    "CONCAT": "concat", "LENGTH": "strlen",
    # SUBSTR / SUBSTRING deliberately do NOT live here (BL-340): Snowflake's start
    # is 1-based, ThoughtSpot substr's zero-based — see _EXACT_FORM_CALLS.
    # BL-171: TRIM/LTRIM/RTRIM/REPLACE/STARTSWITH/ENDSWITH deliberately do NOT
    # live here — none of those ThoughtSpot names exists (live-verified
    # 2026-07-29/30, se-thoughtspot; error_code 14516). They are handled by
    # _PASS_THROUGH_HINT and _STRING_COMPOSED below.
    "CONTAINS": "contains",
    "LEFT": "left", "RIGHT": "right", "LPAD": "lpad", "RPAD": "rpad",
    "REVERSE": "reverse", "REPEAT": "repeat",
    # CEIL / CEILING / FLOOR deliberately not here (BL-361): the optional scale argument
    # needs the scaled form — see sv_sql_exact.call_floor_ceil.
    "ABS": "abs",
    # ROUND / TRUNC deliberately do NOT live here (BL-331): ThoughtSpot round()'s
    # 2nd arg is a rounding INCREMENT, not a digit count — see _call_round /
    # _call_trunc and formula_common.ts_round_from_sql_digits.
    "MOD": "mod", "POWER": "pow", "SQRT": "sqrt", "LN": "ln",
    "LOG2": "log2", "LOG10": "log10",
    "GREATEST": "greatest", "LEAST": "least",
    "YEAR": "year", "MONTH": "month_number", "DAY": "day",
    "QUARTER": "quarter_number", "HOUR": "hour_of_day",
    # DAYOFWEEK / DAYOFWEEKISO deliberately do NOT live here (BL-334): a rename
    # to day_number_of_week is a silent wrong number — see _WEEKDAY below.
    "DAYOFYEAR": "day_number_of_year",
    "WEEKOFYEAR": "week_number_of_year",
    # MONTHS_BETWEEN deliberately does NOT live here (BL-342): it is fractional
    # (31-day months, integral only on the same day or both month ends), while
    # diff_months counts boundaries crossed — see _call_months_between.
    "DATE": "date",
    "SUM": "sum", "AVG": "average", "MIN": "min", "MAX": "max",
    "MEDIAN": "median", "STDDEV": "stddev", "VARIANCE": "variance",
    # IFNULL / NVL / ZEROIFNULL / COALESCE: _call_null_default (BL-357). ZEROIFNULL was a
    # rename to `zeroifnull`, which is not a ThoughtSpot function in the catalog (BL-226).
}
_PASS_THROUGH_HINT = {
    "LOWER": "sql_string_op", "UPPER": "sql_string_op",
    "MINUTE": "sql_int_op", "SECOND": "sql_int_op",
    "DATE_FORMAT": "sql_string_op",
    "INITCAP": "sql_string_op",
    # BL-171 — no native `trim`/`ltrim`/`rtrim` in ThoughtSpot (live-verified
    # 2026-07-29 + 2026-07-30, se-thoughtspot). Same treatment as UPPER/LOWER.
    "TRIM": "sql_string_op", "LTRIM": "sql_string_op",
    "RTRIM": "sql_string_op",
}
_DATE_TRUNC = {"day": "date", "week": "start_of_week",
               "month": "start_of_month", "quarter": "start_of_quarter",
               "year": "start_of_year"}
_EXTRACT = {"YEAR": "year", "MONTH": "month_number", "DAY": "day",
            "HOUR": "hour_of_day", "QUARTER": "quarter_number"}
# Weekday NUMBER sources -> (first day numbered `base`, base), rendered through
# formula_common.ts_weekday_number (BL-334). ThoughtSpot day_number_of_week is
# fixed 1 = Monday ... 7 = Sunday (live-probed 2026-10-06).
#   DAYOFWEEK    — "Returns 0 (Sunday) to 6 (Saturday)" under WEEK_START = 0,
#                  which is the documented default ("0 (legacy Snowflake
#                  behavior)") — docs.snowflake.com/en/sql-reference/parameters
#                  (WEEK_START) and .../functions-date-time (week-related parts).
#                  A session/account with a NON-default WEEK_START (1-7) changes
#                  the source meaning to 1-7 from that day; the translator cannot
#                  see session parameters and assumes the default.
#   DAYOFWEEKISO — 1 (Monday) to 7 (Sunday) regardless of WEEK_START — a clean
#                  rename.
# The EXTRACT/DATE_PART spellings are Snowflake's documented part aliases
# (functions-date-time: "weekday, dow, dw" / "weekday_iso, dow_iso, dw_iso").
_WEEKDAY = {"DAYOFWEEK": ("sunday", 0), "DAYOFWEEKISO": ("monday", 1)}
_EXTRACT_WEEKDAY = {
    "DAYOFWEEK": "DAYOFWEEK", "WEEKDAY": "DAYOFWEEK", "DOW": "DAYOFWEEK",
    "DW": "DAYOFWEEK",
    "DAYOFWEEKISO": "DAYOFWEEKISO", "WEEKDAY_ISO": "DAYOFWEEKISO",
    "DOW_ISO": "DAYOFWEEKISO", "DW_ISO": "DAYOFWEEKISO",
}


def _weekday_number(name: str, date_expr: str) -> str:
    first_day, base = _WEEKDAY[name]
    return ts_weekday_number(date_expr, first_day=first_day, base=base)


# DATEDIFF units and the non-rename forms (SUBSTR, MONTHS_BETWEEN, TO_CHAR) live in
# sv_sql_exact.py (BL-340..343).
_DATEADD_UNIT = {"DAY": "add_days", "WEEK": "add_days",
                 "MONTH": "add_months", "YEAR": "add_months"}
# Canonical map now lives in formula_common so both engines share one copy
# (audit 4.1). Alias kept so existing references need no change.
_CAST_MAP = CAST_MAP_FULL
_NULLIF0 = "\x00NULLIF0\x00"


def _emit(name: str, args: list[str]) -> str:
    inner = " , ".join(args)
    return f"{name} ( {inner} )" if args else f"{name} ( )"


_SPECIAL_DISPATCH: dict[str, str] = {
    "EXTRACT": "_extract", "COUNT": "_count", "COUNT_IF": "_count_if",
    "DATEDIFF": "_datediff", "DATEADD": "_dateadd", "POSITION": "_position",
    "TO_DATE": "_to_date",
}
_IFF_NAMES = frozenset({"IFF", "IF"})
_NULL_DEFAULT_NAMES = frozenset({"COALESCE", "IFNULL", "NVL", "ZEROIFNULL"})
_CAST_NAMES = frozenset({"CAST", "TRY_CAST"})
_ARG_SWAP = {"LOCATE": ("strpos", 2)}


def _call(name: str, cur: _Cursor, resolver) -> str:
    """Translate NAME ( ... ) — '(' already consumed."""
    dispatch_key = _SPECIAL_DISPATCH.get(name)
    if dispatch_key == "_extract":
        return _call_extract(cur, resolver)
    if dispatch_key == "_count":
        return _call_count(cur, resolver)
    if dispatch_key == "_count_if":
        return _call_count_if(cur, resolver)
    if dispatch_key == "_datediff":
        return _call_datediff(cur, resolver)
    if dispatch_key == "_dateadd":
        return _call_dateadd(cur, resolver)
    if dispatch_key == "_position":
        return _call_position(cur, resolver)
    if dispatch_key == "_to_date":
        return _emit("to_date", _call_raw_string_args(cur))
    if name in _PASS_THROUGH_HINT:
        return _call_pass_through(name, cur, resolver)
    if name in _IFF_NAMES:
        return _call_iff(cur, resolver)
    if name in _NULL_DEFAULT_NAMES:
        return _call_null_default(name, cur, resolver)
    if name in _CAST_NAMES:
        return _construct_cast(cur, resolver)
    return _call_with_args(name, cur, resolver)


def _call_with_args(name: str, cur: _Cursor, resolver) -> str:
    """Handle functions that parse args first, then dispatch."""
    args = _call_args(cur, resolver, agg=name)
    if name in _EXACT_FORM_CALLS:  # BL-340 / BL-342 / BL-343
        return _EXACT_FORM_CALLS[name](name, args, resolver)
    if name == "NULLIF":
        return _call_nullif(args)
    if name == "NVL2":
        _need(args, 3, name)
        return f"if ( {args[0]} != null ) then {args[1]} else {args[2]}"
    if name == "LOG":
        return _call_log(args)
    if name == "ROUND":
        return _call_round(args, resolver)
    if name in ("TRUNC", "TRUNCATE"):
        return _call_trunc(args, resolver)
    if name == "DATE_TRUNC":
        return _call_date_trunc(args)
    if name in _ARG_SWAP:
        fn, n = _ARG_SWAP[name]
        _need(args, n, name)
        return _emit(fn, [args[1], args[0]])
    if name in _STRING_COMPOSED:
        return _STRING_COMPOSED[name](args)
    if name in _WEEKDAY:
        _need(args, 1, name)
        return _weekday_number(name, args[0])
    if name in _RENAME:
        return _emit(_RENAME[name], args)
    raise UntranslatableError(
        f"function '{name}' is not in "
        f"ts-snowflake-formula-translation.md — extend the mapping doc and "
        f"sv_sql._RENAME together")


def _round_args(args: list[str], name: str) -> tuple[str, str | None]:
    if len(args) not in (1, 2):
        raise UntranslatableError(
            f"{name} expects 1 or 2 arguments, got {len(args)}")
    return args[0], (args[1] if len(args) == 2 else None)


def _call_round(args: list[str], resolver=None) -> str:
    """ROUND(x[, d]) — d is a digit count, ThoughtSpot round()'s 2nd arg an
    increment (BL-331); the conversion lives in formula_common."""
    x, d = _round_args(args, "ROUND")
    return ts_round_from_sql_digits(x, d, aggregated=_is_aggregated(x, resolver))


# Snap x/inc to the nearest 1e-6 before floor/ceil: 0.29 / 0.01 is
# 28.999999999999996 in floating point, so a bare floor() truncates 0.29 to 0.28.
_TRUNC_GUARD = "0.000001"


def _call_trunc(args: list[str], resolver=None) -> str:
    """TRUNC(x[, d]) — numeric truncation toward zero, or TRUNC(date, 'unit').

    It was emitted as round(x, d) — wrong twice: round() rounds rather than
    truncates, and its 2nd arg is an increment, not a digit count (BL-331).

    Numeric form: ThoughtSpot has no truncate function, so a row-level x passes
    through to Snowflake's own TRUNC, which runs in the warehouse's own numeric
    type. An aggregated x (including a metric reference) cannot go through the
    row-level pass-through, so it uses the sign-split floor/ceil identity, which
    ThoughtSpot evaluates natively over aggregates — in DOUBLE. The scaled value
    is first snapped to the nearest 1e-6 (_TRUNC_GUARD) so float error cannot
    drop an exact boundary (0.29 -> 0.28). Residual: a value within 5e-7 of an
    increment *below* a boundary is snapped up to it (TRUNC(0.28999999, 2) ->
    0.29, not 0.28) — an accepted trade for exact boundaries.
    """
    if len(args) == 2 and args[1].startswith("'"):
        return _call_date_trunc([args[1], args[0]])  # TRUNC(date, 'month')
    x, d = _round_args(args, "TRUNC")
    d = d if d is not None else "0"
    inc = sql_digits_to_ts_increment(d)
    if inc is None and sql_int_digits(d) is not None:
        raise UntranslatableError(f"TRUNC digit count {d.strip()} is out of range — BL-331")
    if not _is_aggregated(x, resolver):
        if inc is not None:  # literal digit count: inline it in the template
            digits = str(sql_int_digits(d))
            return f'sql_double_op ( "TRUNC({{0}}, {digits})" , {x} )'
        return f'sql_double_op ( "TRUNC({{0}}, {{1}})" , {x} , {d} )'
    if inc is None:
        raise UntranslatableError(
            "TRUNC with a non-literal digit count over an aggregate has no "
            "ThoughtSpot form — BL-331")
    if inc == "1":
        return f"( if ( {x} >= 0 ) then floor ( {x} ) else ceil ( {x} ) )"
    n = sql_int_digits(d)
    if n > 0:  # scale up by 10^d, divide back: 115 / 100 is 1.15, 115 * 0.01 is not
        factor = sql_digits_to_ts_increment(str(-n))
        scaled, back = f"{x} * {factor}", f"/ {factor}"
    else:
        scaled, back = f"{x} / {inc}", f"* {inc}"
    g = _TRUNC_GUARD
    return (f"( if ( {x} >= 0 ) then floor ( round ( {scaled} , {g} ) ) {back} "
            f"else ceil ( round ( {scaled} , {g} ) ) {back} )")


def _need(args: list[str], n: int, name: str) -> None:
    if len(args) != n:
        raise UntranslatableError(
            f"{name} expects {n} arguments, got {len(args)}")


# --- BL-171: string functions with no ThoughtSpot equivalent ----------------
# `replace`, `starts_with` and `ends_with` are absent from the ThoughtSpot
# formula parser (live-verified 2026-07-29 + 2026-07-30, se-thoughtspot —
# each rejected with `Search did not find "<fn> ("`, error_code 14516). The
# forms below are the String Functions rows of
# ts-snowflake-formula-translation.md, all three verified to import.

def _call_replace(args: list[str]) -> str:
    _need(args, 3, "REPLACE")
    return ('sql_string_op ( "REPLACE({0}, {1}, {2})" , '
            f"{args[0]} , {args[1]} , {args[2]} )")


def _call_starts_with(args: list[str]) -> str:
    """STARTSWITH(s, p) -> ( strpos ( s , p ) = 1 ) — strpos is 1-indexed."""
    _need(args, 2, "STARTSWITH")
    return f"( strpos ( {args[0]} , {args[1]} ) = 1 )"


def _call_ends_with(args: list[str]) -> str:
    """ENDSWITH(s, x) -> a substr/strlen tail comparison."""
    _need(args, 2, "ENDSWITH")
    s, suffix = args[0], args[1]
    return (f"( substr ( {s} , strlen ( {s} ) - strlen ( {suffix} ) , "
            f"strlen ( {suffix} ) ) = {suffix} )")


_STRING_COMPOSED = {
    "REPLACE": _call_replace,
    "STARTSWITH": _call_starts_with,
    "ENDSWITH": _call_ends_with,
}


def _call_args(cur: _Cursor, resolver, agg: str | None = None) -> list[str]:
    kind, text = cur.peek()
    if kind == "kw" and text == "DISTINCT":
        raise UntranslatableError(
            f"DISTINCT under {agg or 'a function'} has no ThoughtSpot "
            f"mapping (only COUNT(DISTINCT col) -> unique count)")
    args: list[str] = []
    if kind == "op" and text == ")":
        cur.advance()
        return args
    while True:
        args.append(_expr(cur, resolver))
        kind, text = cur.peek()
        if kind == "op" and text == ",":
            cur.advance()
            continue
        cur.expect_op(")")
        return args


def _call_count(cur: _Cursor, resolver) -> str:
    kind, text = cur.peek()
    if kind == "op" and text == "*":
        cur.advance()
        cur.expect_op(")")
        return _emit("count", ["1"])
    if kind == "kw" and text == "DISTINCT":
        cur.advance()
        args = _call_args(cur, resolver)
        _need(args, 1, "COUNT(DISTINCT ...)")
        return f"unique count ( {args[0]} )"
    args = _call_args(cur, resolver)
    _need(args, 1, "COUNT")
    return _emit("count", args)


def _call_count_if(cur: _Cursor, resolver) -> str:
    args = _call_args(cur, resolver)
    _need(args, 1, "COUNT_IF")
    return f"sum ( if ( {args[0]} ) then 1 else 0 )"


def _call_extract(cur: _Cursor, resolver) -> str:
    kind, unit = cur.advance()
    unit_u = unit.upper() if kind == "ident" else ""
    if unit_u not in _EXTRACT and unit_u not in _EXTRACT_WEEKDAY:
        raise UntranslatableError(
            f"EXTRACT unit {unit!r} not mapped "
            f"(YEAR|MONTH|DAY|HOUR|QUARTER|DAYOFWEEK|DAYOFWEEKISO)")
    kw_kind, kw = cur.advance()
    if kw_kind != "kw" or kw != "FROM":
        raise UntranslatableError("EXTRACT expects '<unit> FROM <expr>'")
    inner = _expr(cur, resolver)
    cur.expect_op(")")
    if unit_u in _EXTRACT_WEEKDAY:
        return _weekday_number(_EXTRACT_WEEKDAY[unit_u], inner)
    return _emit(_EXTRACT[unit_u], [inner])


def _call_iff(cur: _Cursor, resolver) -> str:
    args = _call_args(cur, resolver)
    _need(args, 3, "IFF")
    return f"if ( {args[0]} ) then {args[1]} else {args[2]}"


def _call_null_default(name: str, cur: _Cursor, resolver) -> str:
    """COALESCE / IFNULL / NVL / ZEROIFNULL over raw argument units, so an
    ``x / NULLIF(y, 0)`` first argument is visible (BL-357, ``sql_forms``)."""
    raw: list[list[str]] = []
    if cur.peek() == ("op", ")"):
        cur.advance()
    else:
        while True:
            raw.append(_expr_units(cur, resolver, finish=False))
            if cur.peek() == ("op", ","):
                cur.advance()
                continue
            cur.expect_op(")")
            break
    return sqlf_null_default_call(name, raw, _finish_units, _NULLIF0)


def _call_position(cur: _Cursor, resolver) -> str:
    """POSITION(substr IN str) -> strpos ( str , substr )."""
    substr = _expr(cur, resolver, frozenset({"IN"}))
    kind, text = cur.advance()
    if text != "IN":
        raise UntranslatableError("POSITION expects 'substr IN str'")
    str_expr = _expr(cur, resolver)
    cur.expect_op(")")
    return _emit("strpos", [str_expr, substr])


def _call_pass_through(name: str, cur: _Cursor, resolver) -> str:
    op_type = _PASS_THROUGH_HINT[name]
    args = _call_args(cur, resolver)
    if name == "DATE_FORMAT":
        _need(args, 2, name)
        return (f'{op_type} ( "DATE_FORMAT({{0}}, {args[1]})" , {args[0]} )')
    _need(args, 1, name)
    return f'{op_type} ( "{name}({{0}})" , {args[0]} )'


_DATE_TRUNC_PASSTHROUGH = frozenset({"hour", "minute", "second"})


def _call_date_trunc(args: list[str]) -> str:
    _need(args, 2, "DATE_TRUNC")
    unit = args[0].strip("'").lower()
    fn = _DATE_TRUNC.get(unit)
    if fn is not None:
        return _emit(fn, [args[1]])
    if unit in _DATE_TRUNC_PASSTHROUGH:
        return (f"sql_date_time_op ( \"DATE_TRUNC('{unit.upper()}', "
                f"{{0}})\" , {args[1]} )")
    raise UntranslatableError(
        f"DATE_TRUNC unit '{unit}' not mapped "
        f"(day|week|month|quarter|year|hour|minute|second)")


def _unit_arg(cur: _Cursor, fn_name: str) -> str:
    """Read the leading date-part argument of DATEDIFF / DATEADD.

    Snowflake accepts the unit either bare (``DATEDIFF(day, a, b)``) or as a
    string literal (``DATEDIFF('day', a, b)``) and both are idiomatic in a
    hand-written Semantic View. Only the bare form was accepted, so the quoted
    form raised "expects a unit identifier as first argument" and the whole
    metric was dropped into ``skipped[]`` (BL-212).
    """
    kind, text = cur.peek()
    if kind == "string":
        unit = text[1:-1].strip().upper()
    elif kind == "ident":
        unit = text.upper()
    else:
        raise UntranslatableError(
            f"{fn_name} expects a unit identifier or quoted unit as first "
            f"argument")
    cur.advance()
    return unit


def _call_datediff(cur: _Cursor, resolver) -> str:
    """DATEDIFF(unit, start, end) -> diff_days/diff_months(end, start).

    Snowflake DATEDIFF always takes 3 args: unit, start_date, end_date.
    ThoughtSpot diff_* functions take (later, earlier) — same order as
    Snowflake's (start, end) becomes (end, start) — args reversed.
    """
    unit = _unit_arg(cur, "DATEDIFF")
    cur.expect_op(",")
    args = _call_args(cur, resolver)
    _need(args, 2, "DATEDIFF(unit, ...)")
    return datediff_to_ts(unit, args, resolver)


def _call_dateadd(cur: _Cursor, resolver) -> str:
    """DATEADD(unit, amount, date) -> add_days/add_months(date, amount)."""
    unit = _unit_arg(cur, "DATEADD")
    cur.expect_op(",")
    args = _call_args(cur, resolver)
    _need(args, 2, "DATEADD(unit, ...)")
    fn = _DATEADD_UNIT.get(unit)
    if fn is None:
        raise UntranslatableError(
            f"DATEADD unit '{unit}' not mapped (DAY|WEEK|MONTH|YEAR)")
    amount = args[0]
    date_expr = args[1]
    if unit == "WEEK":
        amount = f"( {amount} * 7 )"
    if unit == "YEAR":
        amount = f"( {amount} * 12 )"
    return _emit(fn, [date_expr, amount])


def _call_nullif(args: list[str]) -> str:
    """``NULLIF(a, b)``. ThoughtSpot has no ``nullif`` (rejected at import, probe record
    §7, BL-339), so a non-zero ``b`` becomes ``if ( a = b ) then null else a`` — ``then
    null`` is accepted. ``NULLIF(x, 0)`` keeps its marker (the divisor idiom)."""
    _need(args, 2, "NULLIF")
    if args[1] != "0":
        return f"( if ( {args[0]} = {args[1]} ) then null else {args[0]} )"
    return _NULLIF0 + args[0]


def _call_log(args: list[str]) -> str:
    if len(args) == 2:
        if args[0] == "2":
            return _emit("log2", [args[1]])
        if args[0] == "10":
            return _emit("log10", [args[1]])
        raise UntranslatableError(
            f"LOG base {args[0]} not mapped (only LOG(2,x) and LOG(10,x))")
    _need(args, 1, "LOG")
    return _emit("ln", args)


def _call_raw_string_args(cur: _Cursor) -> list[str]:
    args: list[str] = []
    while True:
        kind, text = cur.advance()
        if kind != "string":
            raise UntranslatableError(
                "TO_DATE arguments must be string literals")
        args.append(text)
        kind, text = cur.advance()
        if kind == "op" and text == ",":
            continue
        if kind == "op" and text == ")":
            return args
        raise UntranslatableError("malformed TO_DATE argument list")


# --- keyword constructs: CASE/CAST/NOT/IS/IN/BETWEEN -----------------------

_NOT_OPERAND_STOP_KWS = frozenset(
    {"AND", "OR", "THEN", "WHEN", "ELSE", "END"})
_COMPOUND_GUARD_OPS = {"+", "-", "*", "/", "%", "||", "=", "!=", "<", ">", "<=", ">="}


def _pop_operand(units: list[str], construct: str) -> str:
    if not units:
        raise UntranslatableError(f"'{construct}' without a left operand")
    if len(units) >= 2 and units[-2] in _COMPOUND_GUARD_OPS:
        raise UntranslatableError(
            f"compound left operand of {construct} — parenthesize it "
            f"(e.g. (a * b) {construct} ...)")
    unit = units.pop()
    if unit.startswith(_NULLIF0):
        return f"( if ( {unit[len(_NULLIF0):]} = 0 ) then null else {unit[len(_NULLIF0):]} )"
    return unit


def _terminates_operand(nk, nt) -> bool:
    if nk is None:
        return True
    if nk == "kw" and nt in _NOT_OPERAND_STOP_KWS:
        return True
    return nk == "op" and nt in (")", ",")


def _one_operand(cur, resolver) -> list[str]:
    kind, text = cur.peek()
    if kind is None:
        raise UntranslatableError("expected an operand")
    units: list[str] = []
    cur.advance()
    if kind == "string":
        units.append(_string_literal(text))
    elif kind == "number":
        units.append(text)
    elif kind == "op" and text == "(":
        inner = _expr(cur, resolver)
        cur.expect_op(")")
        units.append(f"( {inner} )")
    elif kind == "ident":
        _ident_unit(text, cur, resolver, units)
    elif kind == "kw":
        _keyword_unit(text, cur, resolver, units)
    else:
        raise UntranslatableError(f"unexpected operand {text!r}")
    _collapse_nullif_markers(units)
    return units


def _construct_not(cur, resolver, units: list[str]) -> None:
    kind, text = cur.peek()
    if kind == "kw" and text in _LIKE_OPS:
        cur.advance()
        _construct_like(text, cur, units, negate=True)  # BL-362
        return
    if kind == "kw" and text in ("IN", "BETWEEN"):
        raise UntranslatableError(
            f"NOT {text} has no documented ThoughtSpot mapping")
    if kind == "ident":
        nk, nt = cur.peek(1)
        if _terminates_operand(nk, nt):
            cur.advance()
            units.append(f"{resolver(text)} = false")
            return
        if not (nk == "op" and nt == "("):
            inner = _expr(cur, resolver, _NOT_OPERAND_STOP_KWS)
            units.append(f"not ( {inner} )")
            return
    operand_units = _one_operand(cur, resolver)
    units.append(f"not ( {' '.join(operand_units)} )")


def _construct_case(cur, resolver) -> str:
    branches: list[tuple[str, str]] = []
    else_val = "null"
    stop = frozenset({"WHEN", "THEN", "ELSE", "END"})
    while True:
        kind, text = cur.advance() if cur.peek()[0] is not None else (None, None)
        if kind is None:
            raise UntranslatableError("CASE without END")
        if text == "WHEN":
            cond = _expr(cur, resolver, stop)
            k2, t2 = cur.advance()
            if t2 != "THEN":
                raise UntranslatableError("CASE WHEN without THEN")
            val = _expr(cur, resolver, stop)
            branches.append((cond, val))
        elif text == "ELSE":
            else_val = _expr(cur, resolver, stop)
        elif text == "END":
            break
        else:
            raise UntranslatableError(f"unexpected {text!r} inside CASE")
    if not branches:
        raise UntranslatableError("CASE with no WHEN branch")
    out = else_val
    for cond, val in reversed(branches):
        out = f"if ( {cond} ) then {val} else {out}"
    return out


def _construct_cast(cur, resolver) -> str:
    """CAST(expr AS type) or TRY_CAST(expr AS type).

    Called both as a keyword construct (CAST ...) and as a function
    (when _call dispatches CAST/TRY_CAST here after consuming '(').
    When called as keyword, consumes the leading '('.
    """
    kind, text = cur.peek()
    if kind == "op" and text == "(":
        cur.advance()
    inner_units = _expr_units(cur, resolver, frozenset({"AS"}))
    kind, text = cur.advance()
    if text != "AS":
        raise UntranslatableError("CAST without AS")
    tk, ttext = cur.advance()
    if tk != "ident":
        raise UntranslatableError("CAST with a non-identifier target type")
    type_name = ttext.upper()
    params = cast_params(cur)
    cur.expect_op(")")
    inner = " ".join(inner_units) if len(inner_units) > 1 else inner_units[0]
    if type_name in CAST_NUMBER:
        return cast_number(type_name, params, inner, resolver)
    fn = _CAST_MAP.get(type_name)
    if fn:
        return _emit(fn, [inner])
    raise UntranslatableError(
        f"CAST target type '{type_name}' not mapped — extend _CAST_MAP")


def _construct_is(cur, units: list[str]) -> None:
    operand = _pop_operand(units, "IS")
    kind, text = cur.advance()
    if text == "NULL":
        units.append(f"isnull ( {operand} )")
        return
    if text == "NOT":
        k2, t2 = cur.advance()
        if t2 == "NULL":
            units.append(f"not ( isnull ( {operand} ) )")
            return
    raise UntranslatableError("IS supports only IS NULL / IS NOT NULL")


def _construct_in(cur, resolver, units: list[str]) -> None:
    operand = _pop_operand(units, "IN")
    cur.expect_op("(")
    values: list[str] = []
    while True:
        values.append(_expr(cur, resolver))
        kind, text = cur.peek()
        if kind == "op" and text == ",":
            cur.advance()
            continue
        cur.expect_op(")")
        break
    ors = " or ".join(f"{operand} = {v}" for v in values)
    units.append(f"( {ors} )")


def _construct_between(cur, resolver, units: list[str]) -> None:
    operand = _pop_operand(units, "BETWEEN")
    lo = _expr(cur, resolver, frozenset({"AND"}))
    kind, text = cur.advance()
    if text != "AND":
        raise UntranslatableError("BETWEEN without AND")
    hi = " ".join(_one_operand(cur, resolver))
    units.append(f"{operand} >= {lo} and {operand} <= {hi}")


def _construct_like(op: str, cur, units: list[str], negate: bool = False) -> None:
    """``x [NOT] LIKE | ILIKE | RLIKE | REGEXP 'p'`` -> sql_bool_op pass-through (BL-362)."""
    operand = _pop_operand(units, op)
    kind, pattern = cur.advance()
    if kind != "string":
        raise UntranslatableError(f"{op} expects a string-literal pattern")
    nk, nt = cur.peek()
    if nk == "ident" and nt.upper() == "ESCAPE":
        raise UntranslatableError(f"{op} … ESCAPE has no documented mapping")
    units.append(sqlf_like(f"NOT {op}" if negate else op, operand, pattern))


def _collapse_nullif_markers(units: list[str]) -> None:
    """x / NULLIF(y, 0) -> x / y — ThoughtSpot's `/` is already NULL on a zero divisor;
    `safe_divide` was 0 there (BL-357). Stray marker -> ( if ( y = 0 ) then null else y ) —
    ThoughtSpot has no null_if_zero (rejected at import, probe record §7, BL-344)."""
    for i, unit in enumerate(units):
        if unit.startswith(_NULLIF0):
            y = unit[len(_NULLIF0):]
            if i >= 2 and units[i - 1] == "/":
                units[i] = sqlf_group(y)
            else:
                units[i] = f"( if ( {y} = 0 ) then null else {y} )"
