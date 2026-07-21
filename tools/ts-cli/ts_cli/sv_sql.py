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

from ts_cli.formula_common import UntranslatableError


_TOKEN_RE = re.compile(
    r"(?P<string>'(?:[^']|'')*')"
    r"|(?P<number>\d+(?:\.\d+)?)"
    r"|(?P<ident>[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*)"
    r"|(?P<op><=|>=|!=|<>|\|\||[+\-*/%(),<>=])"
    r"|(?P<ws>\s+)")

_KEYWORDS = {"AND", "OR", "NOT", "CASE", "WHEN", "THEN", "ELSE", "END",
             "IS", "NULL", "IN", "BETWEEN", "TRUE", "FALSE", "DISTINCT",
             "AS", "CAST", "FROM", "LIKE", "OVER", "FILTER", "WHERE",
             "PARTITION", "BY", "ORDER", "ASC", "DESC", "ROWS", "RANGE",
             "UNBOUNDED", "PRECEDING", "FOLLOWING", "CURRENT", "ROW",
             "EXCLUDING"}

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
        return f"to_date ( {text} , 'yyyy-MM-dd' )"
    return text


def _op_unit(text: str, cur: _Cursor, resolver, units: list[str]) -> None:
    if text == "(":
        inner = _expr(cur, resolver)
        cur.expect_op(")")
        units.append(f"( {inner} )")
    elif text == "<>":
        units.append("!=")
    elif text == "||":
        raise UntranslatableError(
            "operator '||' — use CONCAT() instead "
            "(ts-snowflake-formula-translation.md)")
    else:
        units.append(text)


def _ident_unit(text: str, cur: _Cursor, resolver, units: list[str]) -> None:
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
    "CONCAT": "concat", "LENGTH": "strlen", "SUBSTR": "substr",
    "SUBSTRING": "substr",
    "TRIM": "trim", "LTRIM": "ltrim", "RTRIM": "rtrim", "REPLACE": "replace",
    "CONTAINS": "contains", "STARTSWITH": "starts_with",
    "ENDSWITH": "ends_with",
    "LEFT": "left", "RIGHT": "right", "LPAD": "lpad", "RPAD": "rpad",
    "REVERSE": "reverse", "REPEAT": "repeat",
    "ABS": "abs", "CEIL": "ceil", "CEILING": "ceil",
    "FLOOR": "floor", "ROUND": "round",
    "MOD": "mod", "POWER": "pow", "SQRT": "sqrt", "LN": "ln",
    "LOG2": "log2", "LOG10": "log10",
    "GREATEST": "greatest", "LEAST": "least",
    "YEAR": "year", "MONTH": "month_number", "DAY": "day",
    "QUARTER": "quarter_number", "HOUR": "hour_of_day",
    "DAYOFWEEK": "day_number_of_week", "DAYOFYEAR": "day_number_of_year",
    "WEEKOFYEAR": "week_number_of_year",
    "DATE": "date",
    "SUM": "sum", "AVG": "average", "MIN": "min", "MAX": "max",
    "MEDIAN": "median", "STDDEV": "stddev", "VARIANCE": "variance",
    "IFNULL": "ifnull", "NVL": "ifnull",
    "ZEROIFNULL": "zeroifnull",
}
_PASS_THROUGH_HINT = {
    "LOWER": "sql_string_op", "UPPER": "sql_string_op",
    "MINUTE": "sql_int_op", "SECOND": "sql_int_op",
    "DATE_FORMAT": "sql_string_op",
    "INITCAP": "sql_string_op",
}
_DATE_TRUNC = {"day": "date", "week": "start_of_week",
               "month": "start_of_month", "quarter": "start_of_quarter",
               "year": "start_of_year"}
_EXTRACT = {"YEAR": "year", "MONTH": "month_number", "DAY": "day",
            "HOUR": "hour_of_day", "QUARTER": "quarter_number"}
_DATEDIFF_UNIT = {"DAY": "diff_days", "MONTH": "diff_months",
                  "YEAR": "diff_days", "SECOND": "diff_time"}
_DATEADD_UNIT = {"DAY": "add_days", "WEEK": "add_days",
                 "MONTH": "add_months", "YEAR": "add_months"}
_CAST_MAP = {
    "INTEGER": "to_integer", "INT": "to_integer", "BIGINT": "to_integer",
    "SMALLINT": "to_integer", "TINYINT": "to_integer",
    "NUMBER": "to_double", "FLOAT": "to_double", "DOUBLE": "to_double",
    "DECIMAL": "to_double", "NUMERIC": "to_double", "REAL": "to_double",
    "VARCHAR": "to_string", "TEXT": "to_string", "STRING": "to_string",
    "CHAR": "to_string",
    "DATE": "to_date", "TIMESTAMP": "to_date",
    "BOOLEAN": "to_bool",
}
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
_DIV0_NAMES = frozenset({"DIV0", "DIV0NULL"})
_TO_STRING_NAMES = frozenset({"TO_CHAR", "TO_VARCHAR"})
_TO_DOUBLE_NAMES = frozenset({"TO_NUMBER", "TO_DECIMAL", "TO_NUMERIC"})
_CAST_NAMES = frozenset({"CAST", "TRY_CAST"})
_ARG_SWAP = {"MONTHS_BETWEEN": ("diff_months", 2),
             "LOCATE": ("strpos", 2)}


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
    if name in _DIV0_NAMES:
        return _call_div0(cur, resolver)
    if name in _CAST_NAMES:
        return _construct_cast(cur, resolver)
    return _call_with_args(name, cur, resolver)


def _call_with_args(name: str, cur: _Cursor, resolver) -> str:
    """Handle functions that parse args first, then dispatch."""
    args = _call_args(cur, resolver, agg=name)
    if name in _TO_STRING_NAMES:
        return _emit("to_string", args[:1])
    if name in _TO_DOUBLE_NAMES:
        return _emit("to_double", args[:1])
    if name == "NULLIF":
        return _call_nullif(args)
    if name == "COALESCE":
        return _call_coalesce(args)
    if name == "NVL2":
        _need(args, 3, name)
        return f"if ( {args[0]} != null ) then {args[1]} else {args[2]}"
    if name == "LOG":
        return _call_log(args)
    if name == "TRUNC":
        _need(args, 2, name)
        return _emit("round", args)
    if name == "DATE_TRUNC":
        return _call_date_trunc(args)
    if name in _ARG_SWAP:
        fn, n = _ARG_SWAP[name]
        _need(args, n, name)
        return _emit(fn, [args[1], args[0]])
    if name in _RENAME:
        return _emit(_RENAME[name], args)
    raise UntranslatableError(
        f"function '{name}' is not in "
        f"ts-snowflake-formula-translation.md — extend the mapping doc and "
        f"sv_sql._RENAME together")


def _need(args: list[str], n: int, name: str) -> None:
    if len(args) != n:
        raise UntranslatableError(
            f"{name} expects {n} arguments, got {len(args)}")


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
    if kind != "ident" or unit.upper() not in _EXTRACT:
        raise UntranslatableError(
            f"EXTRACT unit {unit!r} not mapped (YEAR|MONTH|DAY|HOUR|QUARTER)")
    kw_kind, kw = cur.advance()
    if kw_kind != "kw" or kw != "FROM":
        raise UntranslatableError("EXTRACT expects '<unit> FROM <expr>'")
    inner = _expr(cur, resolver)
    cur.expect_op(")")
    return _emit(_EXTRACT[unit.upper()], [inner])


def _call_iff(cur: _Cursor, resolver) -> str:
    args = _call_args(cur, resolver)
    _need(args, 3, "IFF")
    return f"if ( {args[0]} ) then {args[1]} else {args[2]}"


def _call_div0(cur: _Cursor, resolver) -> str:
    args = _call_args(cur, resolver)
    _need(args, 2, "DIV0")
    return f"safe_divide ( {args[0]} , {args[1]} )"


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


def _call_datediff(cur: _Cursor, resolver) -> str:
    """DATEDIFF(unit, start, end) -> diff_days/diff_months(end, start).

    Snowflake DATEDIFF always takes 3 args: unit, start_date, end_date.
    ThoughtSpot diff_* functions take (later, earlier) — same order as
    Snowflake's (start, end) becomes (end, start) — args reversed.
    """
    kind, text = cur.peek()
    if kind != "ident":
        raise UntranslatableError(
            "DATEDIFF expects a unit identifier as first argument")
    unit = text.upper()
    cur.advance()
    cur.expect_op(",")
    args = _call_args(cur, resolver)
    _need(args, 2, "DATEDIFF(unit, ...)")
    fn = _DATEDIFF_UNIT.get(unit)
    if fn is None:
        raise UntranslatableError(
            f"DATEDIFF unit '{unit}' not mapped (DAY|MONTH|YEAR|SECOND)")
    if unit == "YEAR":
        return f"( {_emit('diff_days', [args[1], args[0]])} / 365 )"
    return _emit(fn, [args[1], args[0]])


def _call_dateadd(cur: _Cursor, resolver) -> str:
    """DATEADD(unit, amount, date) -> add_days/add_months(date, amount)."""
    kind, text = cur.peek()
    if kind != "ident":
        raise UntranslatableError(
            "DATEADD expects a unit identifier as first argument")
    unit = text.upper()
    cur.advance()
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
    _need(args, 2, "NULLIF")
    if args[1] != "0":
        return _emit("nullif", args)
    return _NULLIF0 + args[0]


def _call_coalesce(args: list[str]) -> str:
    if len(args) == 2 and args[0].startswith("safe_divide (") and args[1] == "0":
        return args[0]
    if len(args) == 2:
        return f"if ( {args[0]} != null ) then {args[0]} else {args[1]}"
    if len(args) >= 2:
        inner = _call_coalesce(args[1:])
        return f"if ( {args[0]} != null ) then {args[0]} else {inner}"
    return args[0]


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
_COMPOUND_GUARD_OPS = {"+", "-", "*", "/", "=", "!=", "<", ">", "<=", ">="}


def _pop_operand(units: list[str], construct: str) -> str:
    if not units:
        raise UntranslatableError(f"'{construct}' without a left operand")
    if len(units) >= 2 and units[-2] in _COMPOUND_GUARD_OPS:
        raise UntranslatableError(
            f"compound left operand of {construct} — parenthesize it "
            f"(e.g. (a * b) {construct} ...)")
    unit = units.pop()
    if unit.startswith(_NULLIF0):
        return f"null_if_zero ( {unit[len(_NULLIF0):]} )"
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
    if kind == "kw" and text in ("IN", "BETWEEN", "LIKE"):
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
    nk, nt = cur.peek()
    if nk == "op" and nt == "(":
        cur.advance()
        depth = 1
        while depth:
            k2, t2 = cur.advance()
            if k2 == "op" and t2 == "(":
                depth += 1
            elif k2 == "op" and t2 == ")":
                depth -= 1
    cur.expect_op(")")
    inner = " ".join(inner_units) if len(inner_units) > 1 else inner_units[0]
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
