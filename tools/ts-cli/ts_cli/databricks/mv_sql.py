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
"""
from __future__ import annotations

import re
from typing import Callable

from ts_cli.databricks.mv_expr import strip_sql_comments


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


def _keyword_construct(text, cur, resolver, units):  # pragma: no cover
    raise UntranslatableError(f"'{text}' construct not yet implemented")


def _call(name, cur, resolver):  # pragma: no cover — replaced in Task 5
    raise UntranslatableError(f"function '{name}' not yet implemented")


def _collapse_nullif_markers(units: list[str]) -> None:  # Task 5
    return None
