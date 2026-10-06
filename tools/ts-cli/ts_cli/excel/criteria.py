"""``*IF`` / ``*IFS`` criteria → a ThoughtSpot condition (Excel map E11, "Criteria strings").

Covered (each row of the criteria table): a number or a bare value (``5``, ``"West"``); a
comparison prefix (``">5"``, ``"<=10"``, ``"=x"``); ``"<>x"`` — which also matches blanks, so
``( col != x or isnull ( col ) )``; blank (``""``, ``"="``) and non-blank (``"<>"`` →
``not ( isnull ( col ) )`` — there is no ``isnotnull``); a prefix
wildcard (``"We*"`` → ``strpos ( col , 'We' ) = 1``); a contains wildcard (``"*es*"``); other
wildcards → ``sql_bool_op`` ILIKE; and a prefix joined to a cell (``">"&C1``). Text criteria are
case-insensitive on both sides (ThoughtSpot lowercases ``=``, ``contains`` and ``strpos`` —
probe record §4). Anything else is NEEDS_REVIEW.
"""
from __future__ import annotations

import re

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.helpers import template

_PREFIX = re.compile(r"^(<=|>=|<>|<|>|=)?(.*)$", re.S)
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")


def _value(text: str) -> dict:
    if _NUMBER.match(text.strip()):
        num = text.strip()
        if num.startswith("-"):
            return T.unop("-", T.lit_number(num[1:]))
        return T.lit_number(num.lstrip("+"))
    return T.lit_string(text)


def _not_equal(col: dict, value: dict) -> dict:
    return T.binop("or", T.binop("!=", col, value), T.call("isnull", col))


def _wildcard(tr, col: dict, text: str) -> dict:
    inner = text[1:-1] if text.startswith("*") and text.endswith("*") and len(text) > 1 else None
    if inner is not None and not re.search(r"[*?~]", inner):
        return T.call("contains", col, T.lit_string(inner))
    if text.endswith("*") and not re.search(r"[*?~]", text[:-1]):
        return T.binop("=", T.call("strpos", col, T.lit_string(text[:-1])), T.lit_number("1"))
    if re.search(r"[%_~]", text):
        tr.review(f"criteria wildcard {text!r} contains %, _ or ~, which a LIKE pattern would "
                  "read differently")
    pattern = text.replace("'", "''").replace("*", "%").replace("?", "_")
    tr.note("a criteria wildcard with no native form passes through as ILIKE (Snowflake "
            "syntax assumed)")
    return T.call("sql_bool_op", template("{0} ILIKE '" + pattern + "'"), col)


def _from_string(tr, col: dict, raw: str) -> dict:
    op, rest = _PREFIX.match(raw).groups()
    op = op or "="
    if rest == "":
        if op == "=":
            return T.call("isnull", col)
        if op == "<>":  # no isnotnull in ThoughtSpot (probe record §7, BL-339)
            return T.unop("not", T.call("isnull", col))
        tr.review(f"criterion {raw!r} has no condition")
    if op in ("=", "<>") and re.search(r"[*?]", rest):
        cond = _wildcard(tr, col, rest)
        return T.unop("not", cond) if op == "<>" else cond
    value = _value(rest)
    if op == "<>":
        return _not_equal(col, value)
    return T.binop(op, col, value)


def criteria_condition(tr, col: dict, crit) -> dict:
    """The condition ``crit`` (an Excel AST node) applies to column ``col``."""
    if isinstance(crit, X.Str):
        return _from_string(tr, col, crit.value)
    if isinstance(crit, X.Num):
        return T.binop("=", col, T.lit_number(crit.text))
    if isinstance(crit, X.Binary) and crit.op == "&" and isinstance(crit.left, X.Str):
        op, rest = _PREFIX.match(crit.left.value).groups()
        if rest:
            tr.review("a criteria string that joins text before a cell value is not covered")
        right = tr.expr(crit.right)
        op = op or "="
        return _not_equal(col, right) if op == "<>" else T.binop(op, col, right)
    if isinstance(crit, (X.Array, X.Err, X.Missing)):
        tr.review("an array or empty criterion is not covered (the SUM(SUMIFS(…, {…})) "
                  "OR-idiom is a hand-written `in { }`)")
    return T.binop("=", col, tr.expr(crit))
