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
    _pop_operand,
)
# UntranslatableError's canonical home is ts_cli/formula_common.py (BL-063
# PR 14) — mv_emit_expr.py (the reverse direction) raises the same exception
# for the same concept, and vendoring both into one Genie-notebook namespace
# would otherwise define the class twice under one name. Re-exported here so
# existing `from ts_cli.databricks.mv_sql import UntranslatableError` call
# sites are unaffected.
from ts_cli.formula_common import (
    UntranslatableError,
    expr_is_aggregated,
    sql_passthrough_call,
    sql_substr_to_ts,
    ts_round_from_sql_digits,
    ts_weekday_number,
)
from ts_cli.formula_text import (
    SQL_STRING_TOKEN_DATABRICKS,
    sql_literal_text,
    sql_std_literal,
    ts_finalize_formula,
    sql_trig_to_ts,
)
from ts_cli.databricks.mv_sql_calls import (
    mvc_bround,
    mvc_concat_ws,
    mvc_floor_ceil,
    mvc_instr,
    mvc_last_day,
    mvc_mod,
    mvc_nvl2,
    mvc_to_date_expr,
    mvc_trunc,
    mvc_try_divide,
)
from ts_cli.sql_forms import (
    SQLF_BINARY_OPS,
    SQLF_DIV_MARK,
    sqlf_fold_concat,
    sqlf_fold_multiplicative,
    sqlf_group,
    sqlf_guard_adjacent,
    sqlf_like,
    sqlf_null_default_call,
    sqlf_safe_divide_form,
)


_TOKEN_RE = re.compile(
    r"(?P<string>" + SQL_STRING_TOKEN_DATABRICKS + ")"
    r"|(?P<number>\d+(?:\.\d+)?)"
    r"|(?P<ident>(?:`[^`]+`|[A-Za-z_][\w$]*)(?:\.(?:`[^`]+`|[A-Za-z_][\w$]*))*)"
    r"|(?P<op><=|>=|!=|<>|\|\||[+\-*/%(),<>=])"
    r"|(?P<ws>\s+)")

_KEYWORDS = {"AND", "OR", "NOT", "CASE", "WHEN", "THEN", "ELSE", "END",
             "IS", "NULL", "IN", "BETWEEN", "TRUE", "FALSE", "DISTINCT",
             "AS", "CAST", "FROM", "LIKE", "ILIKE", "RLIKE", "OVER", "FILTER",
             "WHERE"}
#: Keyword operators translated as a sql_bool_op pass-through (BL-362).
_LIKE_OPS = frozenset({"LIKE", "ILIKE", "RLIKE"})
#: ILIKE / RLIKE are not reserved in Databricks: a bare column of that name (not followed by a
#: pattern) is still a column (upper-cased by the tokenizer; resolution is case-insensitive).
_COLUMN_OK_OPS = frozenset({"ILIKE", "RLIKE"})

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
        if kind == "string":
            # decoded (\' is a quote) and carried SQL-standard (BL-365); adjacent
            # literals are one literal, as Databricks reads them ('it''s' = its, live)
            text = sql_std_literal(sql_literal_text(text, "databricks"))
            if toks and toks[-1][0] == "string":
                text = sql_std_literal(toks.pop()[1][1:-1].replace("''", "'")
                                       + text[1:-1].replace("''", "'"))
        if kind == "ident" and text.upper() in _KEYWORDS:
            toks.append(("kw", text.upper()))
        else:
            toks.append((kind, text))
    return toks


class _Cursor:
    def __init__(self, toks: list[tuple[str, str]], agg_hook=None):
        self.toks = toks
        self.i = 0
        # BL-316 item 7 — windowed measures: when set, every aggregate call is
        # handed to agg_hook(AGG_NAME, inner_ts) instead of being emitted, so a
        # window wraps EACH aggregate (a ratio's numerator and denominator
        # alike). None for ordinary expressions.
        self.agg_hook = agg_hook
        # emitted aggregate text -> its label, so OVER () can prove its argument
        # is exactly one aggregate call (not a ratio of two)
        self.emitted_aggs: dict[str, str] = {}

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


# Databricks colon-path JSON access, e.g. `col:a.b`, `parse_json(col):a.b`,
# `col:a.b::string`. ThoughtSpot's sql_*_op parser rejects the colon syntax and
# bracket notation fails on Databricks VARIANT, so the colon-free form is
# get_json_object (ts-databricks-formula-translation.md, verified 2026-07-15).
_JSON_IDENT = r"(?:`[^`]+`|[A-Za-z_][\w$]*)"
_JSON_PATH_RE = re.compile(
    r"^\s*(?:parse_json\s*\(\s*(?P<pj>.+?)\s*\)"
    rf"|(?P<bare>{_JSON_IDENT}(?:\.{_JSON_IDENT})*))"
    r"\s*:\s*(?P<path>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)"
    r"(?:\s*::\s*(?P<cast>[A-Za-z_]\w*))?\s*$",
    re.IGNORECASE)
_JSON_STRING_CASTS = frozenset({"string", "varchar", "text", "char"})


def _try_json_path(sql: str, resolver: Callable[[str], str]) -> str | None:
    """Whole-expression Databricks JSON colon-path -> get_json_object.

    Returns a `sql_string_op` pass-through, or None if `sql` is not a JSON
    path access (caller falls through to the normal tokenizer). A non-string
    cast raises UntranslatableError; an array index in the path does not match
    (falls through, then the ':' fails to tokenize -> skipped)."""
    m = _JSON_PATH_RE.match(sql)
    if m is None:
        return None
    cast = m.group("cast")
    if cast is not None and cast.lower() not in _JSON_STRING_CASTS:
        raise UntranslatableError(
            f"JSON path cast '::{cast}' is not codified — only string casts map "
            f"to get_json_object (ts-databricks-formula-translation.md)")
    ref = (m.group("pj") or m.group("bare")).strip()
    path = m.group("path")
    return (f"sql_string_op ( \"get_json_object({{0}}, '$.{path}')\" , "
            f"{resolver(ref)} )")


def translate_sql_expr(sql: str, resolver: Callable[[str], str],
                       agg_hook: Callable[[str, str], str] | None = None) -> str:
    """Translate one Databricks SQL expression to ThoughtSpot formula text.

    agg_hook (windowed measures only): called as agg_hook(AGG, inner_ts) for
    every aggregate call; its return value replaces that call."""
    cleaned = strip_sql_comments(sql)
    json_out = _try_json_path(cleaned, resolver)
    if json_out is not None:
        return json_out
    cur = _Cursor(tokenize(cleaned), agg_hook)
    out = _expr(cur, resolver)
    kind, text = cur.peek()
    if kind is not None:
        raise UntranslatableError(f"unexpected trailing token {text!r}")
    # string literals into their exact ThoughtSpot form; `a * b / c` bracketed (BL-365)
    return ts_finalize_formula(out)


_STOP_OPS = {")", ","}


def _expr(cur: _Cursor, resolver, stop_kws: frozenset = frozenset()) -> str:
    return " ".join(_expr_units(cur, resolver, stop_kws))


def _expr_units(cur: _Cursor, resolver,
                stop_kws: frozenset = frozenset(), finish: bool = True) -> list[str]:
    """Translate up to a stop token into units. ``finish=False`` returns them before the
    NULLIF markers are collapsed and the operators folded (``_finish_units``), so a caller
    can see an ``x / NULLIF(y, 0)`` argument (BL-357)."""
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
    return _finish_units(units, resolver) if finish else units


def _finish_units(units: list[str], resolver=None) -> list[str]:
    """Collapse NULLIF markers, then fold ``%`` / ``DIV`` and ``||`` at their precedence."""
    _collapse_nullif_markers(units)
    sqlf_fold_multiplicative(units, resolver)
    sqlf_fold_concat(units)
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
    else:  # `%` and `||` are folded by _finish_units (BL-362)
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
    if upper == "DIV" and units and units[-1] not in SQLF_BINARY_OPS:
        units.append(SQLF_DIV_MARK)  # `a DIV b`, folded by _finish_units (BL-360)
        return
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
    else:
        _keyword_construct(text, cur, resolver, units)  # Task 5


# --- function map: ts-databricks-formula-translation.md as data ------------

_RENAME = {
    "CONCAT": "concat", "LENGTH": "strlen",
    # SUBSTRING / SUBSTR deliberately do NOT live here (BL-340): Databricks' pos
    # is 1-based (negative counts from the end), ThoughtSpot substr's zero-based
    # — see formula_common.sql_substr_to_ts.
    # BL-171: TRIM/LTRIM/RTRIM/REPLACE/STARTSWITH/ENDSWITH deliberately do NOT
    # live here — none of those ThoughtSpot names exists (live-verified
    # 2026-07-29/30, se-thoughtspot; error_code 14516). They are handled by
    # _PASS_THROUGH_HINT and _STRING_COMPOSED below.
    "CONTAINS": "contains", "LEFT": "left",
    "RIGHT": "right", "LPAD": "lpad", "RPAD": "rpad", "REVERSE": "reverse",
    "REPEAT": "repeat",
    # CEIL / FLOOR deliberately not here (BL-361): their optional scale argument needs
    # the scaled form — see mv_sql_calls.mvc_floor_ceil.
    "ABS": "abs",
    # ROUND deliberately not here (BL-331): ThoughtSpot round()'s 2nd arg is a
    # rounding INCREMENT, not a digit count — see _call_round.
    "POWER": "pow", "SQRT": "sqrt", "LN": "ln",
    "LOG2": "log2", "LOG10": "log10",
    "GREATEST": "greatest", "LEAST": "least",
    "YEAR": "year", "MONTH": "month_number", "DAY": "day",
    "HOUR": "hour_of_day", "QUARTER": "quarter_number",
    # DAYOFWEEK / WEEKDAY deliberately do NOT live here (BL-334): a rename to
    # day_number_of_week is a silent wrong number — see _DBX_WEEKDAY below.
    "WEEKOFYEAR": "week_number_of_year",
    "DAYOFYEAR": "day_number_of_year", "DATE": "date",
    "DATE_ADD": "add_days", "ADD_MONTHS": "add_months",
    "SUM": "sum", "AVG": "average", "MIN": "min", "MAX": "max",
    "COUNT": "count", "STDDEV": "stddev", "VARIANCE": "variance",
    "MEDIAN": "median",
}
_PASS_THROUGH_HINT = {"LOWER": "sql_string_op", "UPPER": "sql_string_op",
                      "MINUTE": "sql_int_op", "SECOND": "sql_int_op",
                      "DATE_FORMAT": "sql_string_op",
                      # BL-171 — no native `trim`/`ltrim`/`rtrim` in
                      # ThoughtSpot (live-verified 2026-07-29 + 2026-07-30,
                      # se-thoughtspot). Same treatment as UPPER/LOWER.
                      "TRIM": "sql_string_op", "LTRIM": "sql_string_op",
                      "RTRIM": "sql_string_op"}
_DATE_TRUNC = {"day": "date", "week": "start_of_week",
               "month": "start_of_month", "quarter": "start_of_quarter",
               "year": "start_of_year"}
_EXTRACT = {"YEAR": "year", "MONTH": "month_number", "DAY": "day",
            "HOUR": "hour_of_day"}
# Weekday NUMBER sources -> (first day numbered `base`, base), rendered through
# formula_common.ts_weekday_number (BL-334). ThoughtSpot day_number_of_week is
# fixed 1 = Monday ... 7 = Sunday (live-probed 2026-10-06). Databricks docs:
#   dayofweek(expr)  — "1 = Sunday, and 7 = Saturday"
#                      (docs.databricks.com/aws/en/sql/language-manual/functions/dayofweek)
#   weekday(expr)    — "0 = Monday and 6 = Sunday" (.../functions/weekday)
#   EXTRACT(DAYOFWEEK | DOW ...)         — "Sunday(1) to Saturday(7)"
#   EXTRACT(DAYOFWEEK_ISO | DOW_ISO ...) — "Monday(1) to Sunday(7)" (.../functions/extract)
# No session parameter changes these.
_DBX_WEEKDAY = {"DAYOFWEEK": ("sunday", 1), "WEEKDAY": ("monday", 0),
                "DAYOFWEEK_ISO": ("monday", 1)}
_DBX_EXTRACT_WEEKDAY = {"DAYOFWEEK": "DAYOFWEEK", "DOW": "DAYOFWEEK",
                        "DAYOFWEEK_ISO": "DAYOFWEEK_ISO",
                        "DOW_ISO": "DAYOFWEEK_ISO"}


def _dbx_weekday_number(name: str, date_expr: str) -> str:
    first_day, base = _DBX_WEEKDAY[name]
    return ts_weekday_number(date_expr, first_day=first_day, base=base)


def _call_dbx_dayofweek(args: list[str]) -> str:
    _need(args, 1, "DAYOFWEEK")
    return _dbx_weekday_number("DAYOFWEEK", args[0])


def _call_dbx_weekday(args: list[str]) -> str:
    _need(args, 1, "WEEKDAY")
    return _dbx_weekday_number("WEEKDAY", args[0])
# Units of the 3-argument datediff(unit, start, end) (datediff3 docs) — all emitted as
# an exact pass-through except DAY over DATE columns; see _call_datediff (BL-345).
_DATEDIFF_UNITS = frozenset({"MICROSECOND", "MILLISECOND", "SECOND", "MINUTE", "HOUR",
                             "DAY", "WEEK", "MONTH", "QUARTER", "YEAR"})
_NULLIF0 = "\x00NULLIF0\x00"  # marker prefix; collapsed before joining


def _emit(name: str, args: list[str]) -> str:
    inner = " , ".join(args)
    return f"{name} ( {inner} )" if args else f"{name} ( )"


def _call(name: str, cur: _Cursor, resolver) -> str:
    """Translate NAME ( … ) — '(' already consumed."""
    pre = _PRE_ARGS.get(name)
    if pre is not None:
        return pre(name, cur, resolver)
    if name in _PASS_THROUGH_HINT:
        return _call_pass_through(name, cur, resolver)
    if name == "TO_DATE" and cur.peek()[0] == "string":
        # TO_DATE's arguments are raw strings — the date-literal wrap must
        # not fire inside it (would double-wrap 'yyyy-MM-dd'-style args).
        return _emit("to_date", _call_raw_string_args(cur))
    args = _call_args(cur, resolver, agg=name)
    if name in _AGGREGATES:
        _need(args, 1, name)
        return _finish_aggregate(name, args[0], cur, resolver)
    if name == "DATE_TRUNC":
        return _call_date_trunc(args)
    if name in _EXACT_FORM_CALLS:  # BL-340 / BL-342
        return _EXACT_FORM_CALLS[name](name, args, resolver)
    if name == "LOCATE":
        _need(args, 2, name)
        return _emit("strpos", [args[1], args[0]])
    if name in ("NULLIF", "NULLIFZERO"):
        return _call_nullif(name, args)
    if name in _ARG_COMPOSED:
        return _ARG_COMPOSED[name](args)
    if name in _RENAME:
        return _emit(_RENAME[name], args)
    raise UntranslatableError(
        f"function '{name}' is not in "
        f"ts-databricks-formula-translation.md — extend the mapping doc and "
        f"mv_sql._RENAME together")


def _row_level_only(name: str, args: list[str]) -> None:
    """A row-level sql_*_op pass-through cannot wrap an aggregate."""
    if any(expr_is_aggregated(a) for a in args):
        raise UntranslatableError(
            f"{name} over an aggregate has no exact ThoughtSpot form (its exact form is a "
            "row-level pass-through)")


def _call_dbx_substr(name: str, args: list[str], resolver=None) -> str:
    """1-based SUBSTRING -> zero-based substr, or an exact pass-through (BL-340)."""
    out = sql_substr_to_ts(name, args)
    if out.startswith("sql_"):
        _row_level_only(name, args)
    return out


def _call_months_between(name: str, args: list[str], resolver=None) -> str:
    """months_between(expr1, expr2[, roundOff]) -> exact pass-through (BL-342).

    Databricks returns FRACTIONAL months — 31-day months; integral (time of day
    ignored) when both are the same day of the month or both month ends; "rounded to
    8 digits unless roundOff = false" (docs.databricks.com/aws/en/sql/language-manual/
    functions/months_between). ``diff_months`` counts boundaries crossed, so the old
    rename was a silent wrong number. The source's own argument order is kept.
    """
    if len(args) not in (2, 3):
        raise UntranslatableError(
            f"MONTHS_BETWEEN expects 2 or 3 arguments, got {len(args)}")
    if len(args) == 3 and args[2].strip().lower() not in ("true", "false"):
        raise UntranslatableError("MONTHS_BETWEEN roundOff must be a literal true/false")
    _row_level_only("MONTHS_BETWEEN", args)
    return sql_passthrough_call("sql_double_op", "months_between", args)


def _call_trig(name: str, args: list[str], resolver=None) -> str:
    """SIN … ATAN, COT, DEGREES, RADIANS, PI, ATAN2 (BL-364); ATAN2 is row-level."""
    if name == "ATAN2":
        _row_level_only(name, args)
    return sql_trig_to_ts(name, args)


_EXACT_FORM_CALLS = {"MONTHS_BETWEEN": _call_months_between,
                     "SUBSTRING": _call_dbx_substr, "SUBSTR": _call_dbx_substr,
                     # BL-361 / BL-362 — mv_sql_calls.py
                     "FLOOR": mvc_floor_ceil, "CEIL": mvc_floor_ceil,
                     "CEILING": mvc_floor_ceil, "TRY_DIVIDE": mvc_try_divide,
                     "NVL2": mvc_nvl2, "TRUNC": mvc_trunc, "LAST_DAY": mvc_last_day,
                     "BROUND": mvc_bround, "INSTR": mvc_instr, "CONCAT_WS": mvc_concat_ws,
                     "TO_DATE": mvc_to_date_expr, "MOD": mvc_mod,
                     # BL-364 — radians on both sides (formula_text.sql_trig_to_ts)
                     "SIN": _call_trig, "COS": _call_trig, "TAN": _call_trig,
                     "ASIN": _call_trig, "ACOS": _call_trig, "ATAN": _call_trig,
                     "COT": _call_trig, "ATAN2": _call_trig, "DEGREES": _call_trig,
                     "RADIANS": _call_trig, "PI": _call_trig}
# Every ThoughtSpot name each handler above can emit — read by check_mapping_code_sync.py
# (requirement D), which cannot see through function-valued dispatch maps.
EXACT_FORM_EMITS = {"MONTHS_BETWEEN": ("sql_double_op",),
                    "SUBSTRING": ("substr", "strlen", "sql_string_op"),
                    "SUBSTR": ("substr", "strlen", "sql_string_op"),
                    "FLOOR": ("floor", "round"), "CEIL": ("ceil", "round"),
                    "CEILING": ("ceil", "round"), "TRY_DIVIDE": (), "NVL2": (),
                    "TRUNC": ("start_of_year", "start_of_quarter", "start_of_month",
                              "sql_date_op"),
                    "LAST_DAY": ("add_days", "add_months", "start_of_month"),
                    "BROUND": ("sql_double_op",), "INSTR": ("sql_int_op",),
                    "CONCAT_WS": ("sql_string_op",), "TO_DATE": ("sql_date_op",),
                    "MOD": ("mod", "sql_double_op"),
                    "SIN": ("sin",), "COS": ("cos",), "TAN": ("tan",), "ASIN": ("asin",),
                    "ACOS": ("acos",), "ATAN": ("atan",), "COT": ("tan",),
                    "ATAN2": ("sql_double_op",), "DEGREES": ("sql_double_op",),
                    "RADIANS": ("sql_double_op",), "PI": ("sql_double_op",)}


def _call_round(args: list[str]) -> str:
    """ROUND(x[, d]) — d is a digit count, ThoughtSpot round()'s 2nd arg an
    increment (BL-331); the conversion lives in formula_common."""
    if len(args) not in (1, 2):
        raise UntranslatableError(
            f"ROUND expects 1 or 2 arguments, got {len(args)}")
    return ts_round_from_sql_digits(args[0], args[1] if len(args) == 2 else None)


def _need(args: list[str], n: int, name: str) -> None:
    if len(args) != n:
        raise UntranslatableError(f"{name} expects {n} arguments, got {len(args)}")


# --- BL-171: string functions with no ThoughtSpot equivalent ----------------
# `replace`, `starts_with` and `ends_with` are absent from the ThoughtSpot
# formula parser (live-verified 2026-07-29 + 2026-07-30, se-thoughtspot —
# rejected with `Search did not find "<fn> ("`, error_code 14516). The forms
# below are ts-databricks-formula-translation.md's corrected rows and
# ts-convert-from-databricks-mv coverage-matrix #75/#76; each was verified to
# import in the same probe pass.

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

# Functions whose translation is built from already-translated args, dispatched
# by name (keeps _call under the module-health complexity CAP).
# DAYOFWEEK_ISO is an EXTRACT field only, not a Databricks function.
_ARG_COMPOSED: dict = {**_STRING_COMPOSED, "ROUND": _call_round,
                       "DAYOFWEEK": _call_dbx_dayofweek,
                       "WEEKDAY": _call_dbx_weekday}


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


def _call_count(cur: _Cursor, resolver) -> tuple[str, str]:
    """-> (label, inner): label is COUNT or COUNT_DISTINCT."""
    kind, text = cur.peek()
    if kind == "op" and text == "*":
        cur.advance()
        cur.expect_op(")")
        return "COUNT", "1"
    if kind == "kw" and text == "DISTINCT":
        cur.advance()
        args = _call_args(cur, resolver)
        _need(args, 1, "COUNT(DISTINCT …)")
        return "COUNT_DISTINCT", args[0]
    args = _call_args(cur, resolver)
    _need(args, 1, "COUNT")
    return "COUNT", args[0]


# --- aggregates: FILTER (WHERE …), OVER (), window hook (BL-316) ------------

_AGGREGATES = frozenset({"SUM", "AVG", "MIN", "MAX", "STDDEV", "VARIANCE",
                         "MEDIAN"})
_AGG_FN = {"SUM": "sum", "AVG": "average", "MIN": "min", "MAX": "max",
           "COUNT": "count", "STDDEV": "stddev", "VARIANCE": "variance",
           "MEDIAN": "median"}
_AGG_IF_FN = {"SUM": "sum_if", "COUNT": "count_if", "AVG": "average_if",
              "MIN": "min_if", "MAX": "max_if", "STDDEV": "stddev_if",
              "VARIANCE": "variance_if", "COUNT_DISTINCT": "unique_count_if"}
# SUM(inner) OVER () is a grand total only when summing is the inner
# aggregate's own roll-up; MIN/MAX likewise. SUM(AVG(x)) OVER () is a sum of
# per-group averages, not an average — no group_aggregate equivalent.
_OVER_ROLLUP = {"SUM": {"SUM", "COUNT"}, "MIN": {"MIN"}, "MAX": {"MAX"}}


def _emit_aggregate(label: str, inner: str) -> str:
    if label == "COUNT_DISTINCT":
        return f"unique count ( {inner} )"
    return _emit(_AGG_FN[label], [inner])


def _maybe_filter(cur: _Cursor, resolver) -> str | None:
    """Consume `FILTER ( WHERE cond )` if present; return translated cond."""
    kind, text = cur.peek()
    if not (kind == "kw" and text == "FILTER"):
        return None
    cur.advance()
    cur.expect_op("(")
    k2, t2 = cur.advance()
    if not (k2 == "kw" and t2 == "WHERE"):
        raise UntranslatableError("FILTER expects '( WHERE <condition> )'")
    cond = _expr(cur, resolver)
    cur.expect_op(")")
    return cond


def _finish_aggregate(label: str, inner: str, cur: _Cursor, resolver) -> str:
    """An aggregate call's ')' has been consumed: apply FILTER/OVER/hook."""
    cond = _maybe_filter(cur, resolver)
    if cur.agg_hook is not None:
        if label == "COUNT_DISTINCT":
            raise UntranslatableError(
                "COUNT(DISTINCT …) inside a windowed measure has no "
                "moving_/cumulative_ equivalent")
        if cond is not None:
            # FILTER-equivalent: non-matching rows contribute NULL
            inner = f"if ( {cond} ) then {inner} else null"
        return cur.agg_hook(label, inner)
    if cond is not None:
        fn = _AGG_IF_FN.get(label)
        if fn is None:
            raise UntranslatableError(
                f"aggregate '{label}' under FILTER (WHERE …) has no native "
                f"*_if function mapping (ts-databricks-formula-translation.md)")
        return f"{fn} ( {cond} , {inner} )"
    out = _emit_aggregate(label, inner)
    kind, text = cur.peek()
    if kind == "kw" and text == "OVER":
        return _over_empty(label, inner, cur)
    cur.emitted_aggs[out] = label
    return out


def _over_empty(label: str, inner: str, cur: _Cursor) -> str:
    """AGG(AGG(x)) OVER () -> group_aggregate ( AGG(x) , { } , query_filters ( ) ).

    The empty window is the grand total of the query's result rows — every
    grouping column dropped, every filter kept (BL-316 item 5, live-verified
    2026-09-28). PARTITION BY / ORDER BY windows are not mapped here."""
    cur.advance()  # OVER
    cur.expect_op("(")
    kind, text = cur.peek()
    if not (kind == "op" and text == ")"):
        raise UntranslatableError(
            "only an empty OVER () window is mapped on a measure "
            "(PARTITION BY / ORDER BY need a per-MV judgment call)")
    cur.advance()
    # The argument must be exactly ONE aggregate call: SUM(SUM(a)/SUM(b)) OVER ()
    # is a sum of per-group ratios, which no group_aggregate reproduces.
    if cur.emitted_aggs.get(inner) not in _OVER_ROLLUP.get(label, set()):
        raise UntranslatableError(
            f"{label}(…) OVER () is mapped only as a grand-total roll-up of the "
            f"same aggregate (SUM of SUM/COUNT, MIN of MIN, MAX of MAX)")
    return f"group_aggregate ( {inner} , {{ }} , query_filters ( ) )"


def _call_extract(cur: _Cursor, resolver) -> str:
    kind, unit = cur.advance()
    unit_u = unit.upper() if kind == "ident" else ""
    if unit_u not in _EXTRACT and unit_u not in _DBX_EXTRACT_WEEKDAY:
        raise UntranslatableError(
            f"EXTRACT unit {unit!r} not mapped (YEAR|MONTH|DAY|HOUR|"
            f"DAYOFWEEK|DAYOFWEEK_ISO — ts-databricks-formula-translation.md)")
    kw_kind, kw = cur.advance()
    if kw_kind != "kw" or kw != "FROM":
        raise UntranslatableError("EXTRACT expects '<unit> FROM <expr>'")
    inner = _expr(cur, resolver)
    cur.expect_op(")")
    if unit_u in _DBX_EXTRACT_WEEKDAY:
        return _dbx_weekday_number(_DBX_EXTRACT_WEEKDAY[unit_u], inner)
    return _emit(_EXTRACT[unit_u], [inner])


def _call_if(cur: _Cursor, resolver) -> str:
    """IF / IFF (cond, then_val, else_val) → if ( cond ) then val else val."""
    args = _call_args(cur, resolver)
    _need(args, 3, "IF")
    # the compiled safe_divide form, read back as the idiom (BL-374)
    return (sqlf_safe_divide_form(*args)
            or f"if ( {args[0]} ) then {args[1]} else {args[2]}")


def _call_pass_through(name: str, cur: _Cursor, resolver) -> str:
    """Generate sql_*_op pass-through for functions with no native TS equivalent."""
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
    """DATEDIFF(end, start) -> diff_days(end, start); DATEDIFF(unit, s, e)
    -> diff_<unit>(e, s).

    ThoughtSpot diff_* takes the LATER date first (diff_days(end, start) =
    end - start; live on se-thoughtspot 2026-10-06). Databricks 2-arg
    datediff(endDate, startDate) already has that order, so it passes
    through; the 3-arg datediff(unit, start, end) is end - start, so its
    date args are swapped. Emitting earlier-first flips every sign (BL-336).

    The 3-arg form is a synonym of timestampdiff and counts WHOLE elapsed units
    in UTC, a DAY being 86400 s; "one month is considered elapsed when the
    calendar month has increased and the calendar day and time is equal or
    greater to the start" (docs.databricks.com/aws/en/sql/language-manual/
    functions/datediff3; returns BIGINT). Every native diff_* counts calendar
    BOUNDARIES instead (Jan 31 -> Feb 1: 0 months in Databricks, 1 in
    ThoughtSpot), so the 3-arg form is an exact sql_int_op pass-through (BL-345)
    — except DAY over two columns known to be DATE, where whole elapsed days and
    date boundaries agree and diff_days is exact. The resolver says which
    references are DATE through ``date_only_refs``; without it, DAY passes through.

    The 3-arg unit arrives as a bare ident (e.g. MONTH) that must NOT be
    resolved as a column — peek for '<unit-ident> ,' before parsing args.
    """
    kind, text = cur.peek()
    nk, nt = cur.peek(1)
    if (kind == "ident" and text.upper() in _DATEDIFF_UNITS
            and nk == "op" and nt == ","):
        cur.advance()
        cur.advance()
        rest = _call_args(cur, resolver)
        _need(rest, 2, "DATEDIFF(unit, …)")
        return _datediff3(text.upper(), rest, resolver)
    rest = _call_args(cur, resolver)
    _need(rest, 2, "DATEDIFF")
    return _emit("diff_days", [rest[0], rest[1]])


def _datediff3(unit: str, args: list[str], resolver) -> str:
    """``datediff(unit, start, end)`` with ``args = [start, end]`` (BL-345)."""
    date_only = getattr(resolver, "date_only_refs", ()) or ()
    if unit == "DAY" and all(a.strip() in date_only for a in args):
        return _emit("diff_days", [args[1], args[0]])
    _row_level_only("DATEDIFF", args)
    return f'sql_int_op ( "DATEDIFF({unit}, {{0}}, {{1}})" , {args[0]} , {args[1]} )'


def _call_nullif(name: str, args: list[str]) -> str:
    """``NULLIF(x, 0)`` / ``nullifzero(x)`` -> the divisor marker, collapsed by
    ``_collapse_nullif_markers``."""
    if name == "NULLIFZERO":
        _need(args, 1, name)
        return _NULLIF0 + args[0]
    _need(args, 2, "NULLIF")
    if args[1] != "0":
        raise UntranslatableError(
            "NULLIF with a non-zero second argument has no documented "
            "mapping (only NULLIF(x, 0) — ts-databricks-formula-translation.md)")
    return _NULLIF0 + args[0]


def _call_null_default(name: str, cur: _Cursor, resolver) -> str:
    """COALESCE / IFNULL / NVL / ZEROIFNULL, over raw argument units so that an
    ``x / NULLIF(y, 0)`` first argument is visible (BL-357, ``sql_forms``)."""
    raw: list[list[str]] = []
    if cur.peek() != ("op", ")"):
        while True:
            raw.append(_expr_units(cur, resolver, finish=False))
            if cur.peek() == ("op", ","):
                cur.advance()
                continue
            cur.expect_op(")")
            break
    else:
        cur.advance()
    return sqlf_null_default_call(name, raw, lambda u: _finish_units(u, resolver), _NULLIF0)


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
    elif text in _COLUMN_OK_OPS and cur.peek()[0] != "string":
        _ident_unit(text, cur, resolver, units)
    elif text in _LIKE_OPS:
        _construct_like(text, cur, units)
    else:
        # OVER / FILTER / WHERE / stray THEN/ELSE/END/FROM/AS/WHEN
        raise UntranslatableError(
            f"'{text}' has no documented ThoughtSpot mapping in this "
            f"position (ts-databricks-formula-translation.md)")


def _construct_like(op: str, cur: _Cursor, units: list[str], negate: bool = False) -> None:
    """``x [NOT] LIKE | ILIKE | RLIKE 'p'`` -> sql_bool_op pass-through (BL-362)."""
    operand = _pop_operand(units, op)
    kind, pattern = cur.advance()
    if kind != "string":
        raise UntranslatableError(f"{op} expects a string-literal pattern")
    nk, nt = cur.peek()
    if nk == "ident" and nt.upper() == "ESCAPE":
        raise UntranslatableError(f"{op} … ESCAPE has no documented mapping")
    units.append(sqlf_like(f"NOT {op}" if negate else op, operand, pattern))


def _collapse_nullif_markers(units: list[str]) -> None:
    """x / NULLIF(y, 0) -> x / y — ThoughtSpot's `/` is already NULL on a zero divisor
    (it compiles to x / NULLIF(y, 0.0)); `safe_divide` was 0 there (BL-357). A stray marker
    -> ( if ( y = 0 ) then null else y ) — ThoughtSpot has no null_if_zero (rejected at
    import, probe record §7, BL-344)."""
    for i, unit in enumerate(units):
        if unit.startswith(_NULLIF0):
            y = unit[len(_NULLIF0):]
            if i >= 2 and units[i - 1] == "/":
                units[i] = sqlf_group(y)
            else:
                units[i] = f"( if ( {y} = 0 ) then null else {y} )"


def _call_extract_pre(name: str, cur: _Cursor, resolver) -> str:
    return _call_extract(cur, resolver)


def _call_count_pre(name: str, cur: _Cursor, resolver) -> str:
    label, inner = _call_count(cur, resolver)
    return _finish_aggregate(label, inner, cur, resolver)


# Calls handled from the cursor, before their argument list is parsed.
_PRE_ARGS = {
    "EXTRACT": _call_extract_pre, "COUNT": _call_count_pre,
    "DATEDIFF": lambda name, cur, resolver: _call_datediff(cur, resolver),
    "IF": lambda name, cur, resolver: _call_if(cur, resolver),
    # `iff` is Databricks' documented synonym for `if` (BL-374)
    "IFF": lambda name, cur, resolver: _call_if(cur, resolver),
    "COALESCE": _call_null_default, "IFNULL": _call_null_default,
    "NVL": _call_null_default, "ZEROIFNULL": _call_null_default,
}
