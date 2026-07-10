"""Databricks SQL expression -> ThoughtSpot formula text.

Pure functions: SQL text + a column resolver in, TS formula text out. No
I/O, no network calls — trivially unit-testable. stdlib only
(Genie-vendorable — see package docstring).

The function map below IS agents/shared/mappings/ts-databricks/
ts-databricks-formula-translation.md encoded as data — the same relationship
ts_cli/tableau/functions.py has to its source doc. Extend the doc and this
module together; an unmapped construct raises UntranslatableError (the
caller records a skipped[] entry — fail loud, never silent).

Output style: tokens joined with single spaces (`sum ( [T::a] * [T::b] )`),
byte-matching the verified worked examples in
agents/shared/worked-examples/databricks/.

CASE/CAST/NOT/IS/IN/BETWEEN keyword-construct handlers live in the sibling
mv_sql_constructs.py (split out under the file-size warn line, BL-063 PR3);
this module re-exports them so translate_sql_expr/UntranslatableError/tokenize
remain the public API.
"""
from __future__ import annotations

import re
from typing import Callable

from ts_cli.databricks.mv_expr import strip_sql_comments
from ts_cli.databricks.mv_sql_constructs import (
    _construct_between,
    _construct_case,
    _construct_cast,
    _construct_in,
    _construct_is,
    _construct_not,
)


class UntranslatableError(Exception):
    """Expression has no documented deterministic translation."""


_TOKEN_RE = re.compile(
    r"(?P<string>'(?:[^']|'')*')"
    r"|(?P<number>\d+(?:\.\d+)?)"
    r"|(?P<ident>(?:`[^`]+`|[A-Za-z_][\w$]*)(?:\.(?:`[^`]+`|[A-Za-z_][\w$]*))*)"
    r"|(?P<op><=|>=|!=|<>|\|\||[+\-*/%(),<>=])"
    r"|(?P<ws>\s+)")

_KEYWORDS = {"AND", "OR", "NOT", "CASE", "WHEN", "THEN", "ELSE", "END",
             "IS", "NULL", "IN", "BETWEEN", "TRUE", "FALSE", "DISTINCT",
             "AS", "CAST", "FROM", "LIKE", "OVER", "FILTER", "WHERE"}

_REF_PLACEHOLDER_RE = re.compile(r"^__MVREF_\d+__$")
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
    """Translate one Databricks SQL expression to ThoughtSpot formula text."""
    cleaned = strip_sql_comments(sql)
    cur = _Cursor(tokenize(cleaned))
    out = _expr(cur, resolver)
    kind, text = cur.peek()
    if kind is not None:
        raise UntranslatableError(f"unexpected trailing token {text!r}")
    return out


_STOP_OPS = {")", ","}


def _expr(cur: _Cursor, resolver, stop_kws: frozenset = frozenset()) -> str:
    return " ".join(_expr_units(cur, resolver, stop_kws))


def _expr_units(cur: _Cursor, resolver,
                stop_kws: frozenset = frozenset()) -> list[str]:
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
    _collapse_nullif_markers(units)
    if not units:
        raise UntranslatableError("empty expression")
    return units


def _string_literal(text: str) -> str:
    if _DATE_LITERAL_RE.match(text):
        # A bare 'YYYY-MM-DD' parses as subtraction in TS — wrap in to_date
        # (implementation note, ts-databricks-formula-translation.md).
        return f"to_date ( {text} , 'yyyy-MM-dd' )"
    return text


def _op_unit(text: str, cur: _Cursor, resolver, units: list[str]) -> None:
    if text == "(":
        inner = _expr(cur, resolver)
        cur.expect_op(")")
        units.append(f"( {inner} )")
    elif text == "<>":
        units.append("!=")
    elif text in ("||", "%"):
        raise UntranslatableError(
            f"operator '{text}' has no documented ThoughtSpot mapping "
            f"(ts-databricks-formula-translation.md)")
    else:
        units.append(text)


def _ident_unit(text: str, cur: _Cursor, resolver, units: list[str]) -> None:
    if _REF_PLACEHOLDER_RE.match(text):
        units.append(text)
        return
    upper = text.upper()
    nk, nt = cur.peek()
    if upper in _BARE_NOW_FNS:
        if nk == "op" and nt == "(":
            cur.advance()
            cur.expect_op(")")
        units.append(f"{_BARE_NOW_FNS[upper]} ( )")
        return
    if nk == "op" and nt == "(":
        cur.advance()  # consume '('
        units.append(_call(upper, cur, resolver))
        return
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
    else:
        _keyword_construct(text, cur, resolver, units)  # Task 5


# --- function map: ts-databricks-formula-translation.md as data ------------

_RENAME = {
    "CONCAT": "concat", "LENGTH": "strlen", "SUBSTRING": "substr",
    "TRIM": "trim", "LTRIM": "ltrim", "RTRIM": "rtrim", "REPLACE": "replace",
    "CONTAINS": "contains", "STARTSWITH": "starts_with", "LEFT": "left",
    "RIGHT": "right", "LPAD": "lpad", "RPAD": "rpad", "REVERSE": "reverse",
    "REPEAT": "repeat",
    "ABS": "abs", "CEIL": "ceil", "FLOOR": "floor", "ROUND": "round",
    "MOD": "mod", "POWER": "pow", "SQRT": "sqrt", "LN": "ln",
    "LOG2": "log2", "LOG10": "log10",
    "GREATEST": "greatest", "LEAST": "least", "IF": "if",
    "YEAR": "year", "MONTH": "month_number", "DAY": "day",
    "HOUR": "hour_of_day", "QUARTER": "quarter_number",
    "WEEKOFYEAR": "week_number_of_year", "DAYOFWEEK": "day_number_of_week",
    "DAYOFYEAR": "day_number_of_year", "DATE": "date",
    "DATE_ADD": "add_days", "ADD_MONTHS": "add_months",
    "SUM": "sum", "AVG": "average", "MIN": "min", "MAX": "max",
    "COUNT": "count", "STDDEV": "stddev", "VARIANCE": "variance",
}
_PASS_THROUGH_HINT = {"LOWER": "sql_string_op", "UPPER": "sql_string_op",
                      "MINUTE": "sql_int_op", "SECOND": "sql_int_op",
                      "DATE_FORMAT": "sql_string_op"}
_DATE_TRUNC = {"day": "date", "week": "start_of_week",
               "month": "start_of_month", "quarter": "start_of_quarter",
               "year": "start_of_year"}
_EXTRACT = {"YEAR": "year", "MONTH": "month_number", "DAY": "day",
            "HOUR": "hour_of_day"}
_DATEDIFF_UNIT = {"DAY": "diff_days", "MONTH": "diff_months"}
_NULLIF0 = "\x00NULLIF0\x00"  # marker prefix; collapsed before joining


def _emit(name: str, args: list[str]) -> str:
    inner = " , ".join(args)
    return f"{name} ( {inner} )" if args else f"{name} ( )"


def _call(name: str, cur: _Cursor, resolver) -> str:
    """Translate NAME ( … ) — '(' already consumed."""
    if name == "EXTRACT":
        return _call_extract(cur, resolver)
    if name == "COUNT":
        return _call_count(cur, resolver)
    if name in _PASS_THROUGH_HINT:
        raise UntranslatableError(
            f"'{name}' has no native ThoughtSpot function — needs a "
            f"{_PASS_THROUGH_HINT[name]} pass-through (manual review, PT1)")
    if name == "TO_DATE":
        # TO_DATE's arguments are raw strings — the date-literal wrap must
        # not fire inside it (would double-wrap 'yyyy-MM-dd'-style args).
        return _emit("to_date", _call_raw_string_args(cur))
    if name == "DATEDIFF":
        return _call_datediff(cur, resolver)
    args = _call_args(cur, resolver, agg=name)
    if name == "DATE_TRUNC":
        return _call_date_trunc(args)
    if name == "MONTHS_BETWEEN":
        _need(args, 2, name)
        return _emit("diff_months", [args[1], args[0]])
    if name == "LOCATE":
        _need(args, 2, name)
        return _emit("strpos", [args[1], args[0]])
    if name == "NULLIF":
        return _call_nullif(args)
    if name == "COALESCE":
        return _call_coalesce(args)
    if name in _RENAME:
        return _emit(_RENAME[name], args)
    raise UntranslatableError(
        f"function '{name}' is not in "
        f"ts-databricks-formula-translation.md — extend the mapping doc and "
        f"mv_sql._RENAME together")


def _need(args: list[str], n: int, name: str) -> None:
    if len(args) != n:
        raise UntranslatableError(f"{name} expects {n} arguments, got {len(args)}")


def _call_args(cur: _Cursor, resolver, agg: str | None = None) -> list[str]:
    """Parse a comma-separated argument list up to the closing ')'.

    Rejects DISTINCT here (only COUNT handles it, in _call_count)."""
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
        _need(args, 1, "COUNT(DISTINCT …)")
        return f"unique count ( {args[0]} )"
    args = _call_args(cur, resolver)
    _need(args, 1, "COUNT")
    return _emit("count", args)


def _call_extract(cur: _Cursor, resolver) -> str:
    kind, unit = cur.advance()
    if kind != "ident" or unit.upper() not in _EXTRACT:
        raise UntranslatableError(
            f"EXTRACT unit {unit!r} not mapped (YEAR|MONTH|DAY|HOUR — "
            f"ts-databricks-formula-translation.md)")
    kw_kind, kw = cur.advance()
    if kw_kind != "kw" or kw != "FROM":
        raise UntranslatableError("EXTRACT expects '<unit> FROM <expr>'")
    inner = _expr(cur, resolver)
    cur.expect_op(")")
    return _emit(_EXTRACT[unit.upper()], [inner])


def _call_date_trunc(args: list[str]) -> str:
    _need(args, 2, "DATE_TRUNC")
    unit = args[0].strip("'").lower()
    fn = _DATE_TRUNC.get(unit)
    if fn is None:
        raise UntranslatableError(
            f"DATE_TRUNC unit '{unit}' not mapped "
            f"(day|week|month|quarter|year)")
    return _emit(fn, [args[1]])


def _call_datediff(cur: _Cursor, resolver) -> str:
    """DATEDIFF(end, start) -> diff_days(start, end); DATEDIFF(unit, s, e).

    The 3-arg unit arrives as a bare ident (e.g. MONTH) that must NOT be
    resolved as a column — peek for '<unit-ident> ,' before parsing args.
    """
    kind, text = cur.peek()
    nk, nt = cur.peek(1)
    if (kind == "ident" and text.upper() in _DATEDIFF_UNIT
            and nk == "op" and nt == ","):
        cur.advance()
        cur.advance()
        rest = _call_args(cur, resolver)
        _need(rest, 2, "DATEDIFF(unit, …)")
        return _emit(_DATEDIFF_UNIT[text.upper()], [rest[0], rest[1]])
    rest = _call_args(cur, resolver)
    _need(rest, 2, "DATEDIFF")
    return _emit("diff_days", [rest[1], rest[0]])


def _call_nullif(args: list[str]) -> str:
    _need(args, 2, "NULLIF")
    if args[1] != "0":
        raise UntranslatableError(
            "NULLIF with a non-zero second argument has no documented "
            "mapping (only NULLIF(x, 0) — ts-databricks-formula-translation.md)")
    return _NULLIF0 + args[0]


def _call_coalesce(args: list[str]) -> str:
    if len(args) == 2 and args[0].startswith("safe_divide (") and args[1] == "0":
        return args[0]  # COALESCE(x / NULLIF(y,0), 0) -> safe_divide(x, y)
    if len(args) == 2:
        return f"if ( {args[0]} != null ) then {args[0]} else {args[1]}"
    raise UntranslatableError(
        "COALESCE with more than two arguments has no documented mapping")


def _call_raw_string_args(cur: _Cursor) -> list[str]:
    args: list[str] = []
    while True:
        kind, text = cur.advance()
        if kind != "string":
            raise UntranslatableError(
                "TO_DATE arguments must be string literals")
        args.append(text)  # verbatim — no date-literal wrapping
        kind, text = cur.advance()
        if kind == "op" and text == ",":
            continue
        if kind == "op" and text == ")":
            return args
        raise UntranslatableError("malformed TO_DATE argument list")


# --- keyword constructs: CASE/CAST/NOT/IS/IN/BETWEEN -----------------------

def _keyword_construct(text: str, cur: _Cursor, resolver,
                       units: list[str]) -> None:
    if text == "NOT":
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
    else:
        # LIKE / OVER / FILTER / WHERE / stray THEN/ELSE/END/FROM/AS/WHEN
        raise UntranslatableError(
            f"'{text}' has no documented ThoughtSpot mapping in this "
            f"position (ts-databricks-formula-translation.md)")


def _collapse_nullif_markers(units: list[str]) -> None:
    """x / NULLIF(y, 0) -> safe_divide ( x , y ); stray marker -> null_if_zero."""
    i = 0
    while i < len(units):
        if units[i].startswith(_NULLIF0):
            y = units[i][len(_NULLIF0):]
            if i >= 2 and units[i - 1] == "/":
                x = units[i - 2]
                units[i - 2:i + 1] = [f"safe_divide ( {x} , {y} )"]
                i -= 2
            else:
                units[i] = f"null_if_zero ( {y} )"
        i += 1
