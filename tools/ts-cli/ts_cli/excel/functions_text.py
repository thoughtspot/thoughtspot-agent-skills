"""Text handlers (Excel map, Text). ThoughtSpot's native string functions are ``concat``,
``substr`` (0-based), ``left``, ``right``, ``strlen``, ``strpos`` and ``contains``; the rest are
``sql_string_op`` / ``sql_int_op`` / ``sql_bool_op`` pass-throughs, Snowflake syntax assumed."""
from __future__ import annotations

import re

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.helpers import is_range, literal_int, need, template

CASE_NOTE = ("{name} is case-sensitive and ThoughtSpot's = / strpos are not (probe record §4, "
             "BL-333), so it passes through to the warehouse")


def _concat(tr, n):
    if not n.args:
        tr.review(f"{n.name}() with no arguments")
    if any(is_range(a) for a in n.args):
        tr.review(f"{n.name} over a range is string aggregation — {_row('TEXTJOIN')}")
    return tr.concat(list(n.args))


def _row(name: str) -> str:
    from ts_cli.excel.map_index import cite
    return cite(name)


def _textjoin(tr, n):
    if len(n.args) < 3:
        tr.review("TEXTJOIN needs a delimiter, ignore_empty and at least one value")
    delim, ignore, values = n.args[0], n.args[1], n.args[2:]
    if any(is_range(a) for a in values) or not isinstance(delim, X.Str):
        tr.review(f"TEXTJOIN over a range (or a non-literal delimiter) is string aggregation "
                  f"— {_row('TEXTJOIN')}")
    if not (isinstance(ignore, X.Bool) and ignore.value is False):
        tr.note("TEXTJOIN ignore_empty=TRUE skips blanks; concat makes the result NULL if any "
                "value is NULL — wrap nullable values in ifnull ( x , '' )")
    parts: list = []
    for i, v in enumerate(values):
        if i:
            parts.append(X.Str(delim.value))
        parts.append(v)
    return tr.concat(parts)


def _left_right(fn: str):
    def handler(tr, n):
        need(tr, n, 1, 2)
        count = tr.expr(n.args[1]) if len(n.args) == 2 else T.lit_number("1")
        return T.call(fn, tr.expr(n.args[0]), count)
    return handler


def _mid(tr, n):
    need(tr, n, 3, 3)
    start = literal_int(n.args[1])
    begin = (T.lit_number(str(start - 1)) if start is not None
             else T.binop("-", tr.expr(n.args[1]), T.lit_number("1")))
    return T.call("substr", tr.expr(n.args[0]), begin, tr.expr(n.args[2]))


def _len(tr, n):
    need(tr, n, 1, 1)
    return T.call("strlen", tr.expr(n.args[0]))


def search_call(tr, n) -> dict:
    """``SEARCH(find, within)`` → ``strpos ( within , find )`` (both case-insensitive)."""
    need(tr, n, 2, 2)
    find = n.args[0]
    if isinstance(find, X.Str) and re.search(r"[*?~]", find.value):
        tr.review("SEARCH with wildcards (* ? ~) has no native form — Excel map SEARCH row")
    return T.call("strpos", tr.expr(n.args[1]), tr.expr(find))


def _search(tr, n):
    tr.trap("SEARCH not found: Excel returns #VALUE!, strpos returns 0")
    return search_call(tr, n)


def find_call(tr, n) -> dict:
    need(tr, n, 2, 2)
    tr.note(CASE_NOTE.format(name="FIND"))
    return T.call("sql_int_op", template("POSITION({0} IN {1})"),
                  tr.expr(n.args[0]), tr.expr(n.args[1]))


def _find(tr, n):
    tr.trap("FIND not found: Excel returns #VALUE!, POSITION returns 0")
    return find_call(tr, n)


def _exact(tr, n):
    need(tr, n, 2, 2)
    tr.note(CASE_NOTE.format(name="EXACT"))
    return T.call("sql_bool_op", template("{0} = {1}"), tr.expr(n.args[0]), tr.expr(n.args[1]))


def _string_op(sql: str, why: str = ""):
    def handler(tr, n):
        need(tr, n, 1, 1)
        if why:
            tr.note(why)
        return T.call("sql_string_op", template(sql), tr.expr(n.args[0]))
    return handler


def _substitute(tr, n):
    need(tr, n, 3, 3)
    return T.call("sql_string_op", template("REPLACE({0}, {1}, {2})"),
                  *[tr.expr(a) for a in n.args])


def _value(tr, n):
    need(tr, n, 1, 1)
    tr.note("VALUE → to_double: numeric strings only; a failed parse is NULL (Excel #VALUE!)")
    return T.call("to_double", tr.expr(n.args[0]))


TEXT_HANDLERS = {
    "CONCAT": _concat, "CONCATENATE": _concat, "TEXTJOIN": _textjoin,
    "LEFT": _left_right("left"), "RIGHT": _left_right("right"), "MID": _mid, "LEN": _len,
    "SEARCH": _search, "FIND": _find, "EXACT": _exact,
    "UPPER": _string_op("UPPER({0})"), "LOWER": _string_op("LOWER({0})"),
    "TRIM": _string_op("TRIM(REGEXP_REPLACE({0}, ' +', ' '))",
                       "Excel TRIM also collapses inner runs of spaces; the template does too"),
    "SUBSTITUTE": _substitute, "VALUE": _value,
}
