"""Text handlers (Excel map, Text). ThoughtSpot's native string functions are ``concat``,
``substr`` (0-based), ``left``, ``right``, ``strlen``, ``strpos`` and ``contains``; the rest are
``sql_string_op`` / ``sql_int_op`` / ``sql_bool_op`` pass-throughs, Snowflake syntax assumed."""
from __future__ import annotations

import re

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.helpers import is_range, need, template

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
        count = tr.int_arg(n.args[1]) if len(n.args) == 2 else T.lit_number("1")
        return T.call(fn, tr.text(n.args[0]), count)
    return handler


def _mid(tr, n):
    """``MID(s, start, n)`` → ``substr ( s , start - 1 , n )`` (zero-based start). A DOUBLE
    start or count is truncated with ``floor`` (BL-355: the slots take an integer)."""
    need(tr, n, 3, 3)
    start = tr.int_arg(n.args[1])
    value = T.number_value(start)
    begin = (T.lit_number(str(int(value) - 1)) if value is not None
             else T.binop("-", start, T.lit_number("1")))
    return T.call("substr", tr.text(n.args[0]), begin, tr.int_arg(n.args[2]))


def _len(tr, n):
    need(tr, n, 1, 1)
    return T.call("strlen", tr.text(n.args[0]))


def search_call(tr, n) -> dict:
    """``SEARCH(find, within)`` → ``strpos ( within , find )`` (both case-insensitive)."""
    need(tr, n, 2, 2)
    find = n.args[0]
    if isinstance(find, X.Str) and re.search(r"[*?~]", find.value):
        tr.review("SEARCH with wildcards (* ? ~) has no native form — Excel map SEARCH row")
    return T.call("strpos", tr.text(n.args[1]), tr.text(find))


def _start(tr, n) -> dict:
    """A FIND / SEARCH ``start_num``: below 1 is #VALUE! in Excel."""
    start = tr.int_arg(n.args[2])
    value = T.number_value(start)
    if value is not None and value < 1:
        tr.review(f"{n.name} with start_num below 1 is #VALUE! in Excel")
    tr.note(f"{n.name} with start_num past the end of the text: Excel returns #VALUE!, "
            "POSITION returns 0")
    return start


def _search(tr, n):
    tr.trap("SEARCH not found: Excel returns #VALUE!, strpos returns 0")
    if len(n.args) == 3:
        # strpos has no start position; Snowflake's three-argument POSITION over LOWER is
        # strpos's own compiled form (POSITION(lower(find) IN LOWER(within)), probe record §4)
        find = n.args[0]
        if isinstance(find, X.Str) and re.search(r"[*?~]", find.value):
            tr.review("SEARCH with wildcards (* ? ~) has no native form — Excel map SEARCH row")
        return T.call("sql_int_op", template("POSITION(LOWER({0}), LOWER({1}), {2})"),
                      tr.text(find), tr.text(n.args[1]), _start(tr, n))
    return search_call(tr, n)


def find_call(tr, n) -> dict:
    need(tr, n, 2, 2)
    tr.note(CASE_NOTE.format(name="FIND"))
    return T.call("sql_int_op", template("POSITION({0} IN {1})"),
                  tr.text(n.args[0]), tr.text(n.args[1]))


def _find(tr, n):
    tr.trap("FIND not found: Excel returns #VALUE!, POSITION returns 0")
    if len(n.args) == 3:
        tr.note(CASE_NOTE.format(name="FIND"))
        return T.call("sql_int_op", template("POSITION({0}, {1}, {2})"),
                      tr.text(n.args[0]), tr.text(n.args[1]), _start(tr, n))
    return find_call(tr, n)


def _exact(tr, n):
    need(tr, n, 2, 2)
    tr.note(CASE_NOTE.format(name="EXACT"))
    return T.call("sql_bool_op", template("{0} = {1}"), tr.text(n.args[0]), tr.text(n.args[1]))


def _string_op(sql: str, why: str = ""):
    def handler(tr, n):
        need(tr, n, 1, 1)
        if why:
            tr.note(why)
        return T.call("sql_string_op", template(sql), tr.text(n.args[0]))
    return handler


def _substitute(tr, n):
    need(tr, n, 3, 3)
    return T.call("sql_string_op", template("REPLACE({0}, {1}, {2})"),
                  *[tr.text(a) for a in n.args])


def _value(tr, n):
    """VALUE of text → ``to_double``; of a number → the number (``to_double`` rejects a
    DOUBLE); of a date → its serial (BL-353)."""
    need(tr, n, 1, 1)
    x = tr.expr(n.args[0])
    t = tr.fine_type(x)
    if t in ("int", "double", "number"):
        return x
    if t == "date":
        from ts_cli.excel.coerce import serial
        return serial(tr, x)
    if t in ("bool", "datetime"):
        tr.review(f"VALUE of a {'boolean' if t == 'bool' else 'date-time'}: Excel returns "
                  "#VALUE! for a boolean and a fractional serial for a date-time — no rule")
    from ts_cli.excel.coerce import TEXT_NUMBER_TRAP, TRY_DOUBLE, as_number, string_value
    if string_value(x) is not None:
        return as_number(tr, x)          # a literal: folded, or NEEDS_REVIEW (#VALUE!)
    if tr.try_conversion:
        # inside IFERROR: TRY_TO_DOUBLE gives NULL for non-numeric text, so the fallback
        # applies; to_double would fail the whole query (probe record §7)
        tr.note("VALUE inside IFERROR → TRY_TO_DOUBLE (NULL for text that is not a number)")
        return T.call("sql_double_op", template(TRY_DOUBLE), x)
    tr.trap(TEXT_NUMBER_TRAP, downgrade=True)
    return T.call("to_double", x)


# Windows-1252 and Unicode agree on 1–127 and 160–255; 128–159 differ (live: CHR(150) is
# U+0096, Windows-1252 150 is an en dash). Snowflake ASCII returns the first UTF-8 BYTE
# (ASCII('é') = 195, live 2026-10-07), so CODE uses UNICODE, which returns 233.
CODE_PAGE_TRAP = ("{name}: Excel uses the platform code page (Windows-1252 on Windows) and "
                  "the warehouse Unicode; they agree for codes 1–127 and 160–255 and differ "
                  "for 128–159 (and Excel's CODE is 63, '?', for a character outside the "
                  "code page)")


def _same_page(code) -> bool:
    return 1 <= code <= 127 or 160 <= code <= 255


def _char(unicode: bool):
    def handler(tr, n):
        need(tr, n, 1, 1)
        code = tr.int_arg(n.args[0])
        value = T.number_value(code)
        top = 1114111 if unicode else 255
        if value is not None and not 1 <= value <= top:
            tr.review(f"{n.name}({value}) is #VALUE! in Excel")
        if unicode:
            if value is None:
                tr.trap("UNICHAR of 0 (or of a surrogate code point) is an error in Excel; "
                        "CHR returns a character")
        elif value is None or not _same_page(int(value)):
            tr.trap(CODE_PAGE_TRAP.format(name="CHAR"), downgrade=True)
        return T.call("sql_string_op", template("CHR({0})"), code)
    return handler


def _code(unicode: bool):
    def handler(tr, n):
        need(tr, n, 1, 1)
        from ts_cli.excel.coerce import string_value
        s = tr.text(n.args[0])
        text = string_value(s)
        if text == "":
            tr.review(f"{n.name} of empty text is #VALUE! in Excel")
        if text is None:
            tr.note(f"{n.name} of empty text: Excel returns #VALUE!, UNICODE returns 0")
        if not unicode and (text is None or not _same_page(ord(text[0]))):
            tr.trap(CODE_PAGE_TRAP.format(name="CODE"), downgrade=True)
        return T.call("sql_int_op", template("UNICODE({0})"), s)
    return handler


def _minus_one(node: dict) -> dict:
    value = T.number_value(node)
    if value is not None:
        from ts_cli.excel.coerce import number_literal
        return number_literal(value - 1)
    return T.binop("-", node, T.lit_number("1"))


def _replace(tr, n):
    """``REPLACE(s, start, n, new)`` is positional: ``n`` characters from ``start`` become
    ``new`` (``SUBSTITUTE`` is the substring one). Native composition, map row:
    ``concat ( left ( s , start - 1 ) , new , substr ( s , start - 1 + n , strlen ( s ) ) )``."""
    need(tr, n, 4, 4)
    s, new = tr.text(n.args[0]), tr.text(n.args[3])
    start, count = tr.int_arg(n.args[1]), tr.int_arg(n.args[2])
    for node, low in ((start, 1), (count, 0)):
        value = T.number_value(node)
        if value is not None and value < low:
            tr.review(f"REPLACE with a {'start below 1' if low else 'negative count'} is "
                      "#VALUE! in Excel")
    head = _minus_one(start)
    sv, cv = T.number_value(start), T.number_value(count)
    tail_at = (T.lit_number(str(int(sv) - 1 + int(cv))) if sv is not None and cv is not None
               else T.binop("+", head, count))
    parts = [] if T.is_lit(head, "number", "0") else [T.call("left", s, head)]
    parts += [new, T.call("substr", s, tail_at, T.call("strlen", s))]
    return T.call("concat", *parts)


DBCS_TRAP = ("{name} counts a double-byte character as 2 only when a DBCS language (Chinese, "
             "Japanese, Korean) is Excel's default editing language; otherwise it is {plain}, "
             "which this is (Excel map {name} row)")


def _bytes(name: str, plain: str):
    def handler(tr, n):
        tr.trap(DBCS_TRAP.format(name=name, plain=plain), downgrade=True)
        return TEXT_HANDLERS[plain](tr, n)
    return handler


TEXT_HANDLERS = {
    "CONCAT": _concat, "CONCATENATE": _concat, "TEXTJOIN": _textjoin,
    "LEFT": _left_right("left"), "RIGHT": _left_right("right"), "MID": _mid, "LEN": _len,
    "SEARCH": _search, "FIND": _find, "EXACT": _exact,
    "UPPER": _string_op("UPPER({0})"), "LOWER": _string_op("LOWER({0})"),
    "TRIM": _string_op("TRIM(REGEXP_REPLACE({0}, ' +', ' '))",
                       "Excel TRIM also collapses inner runs of spaces; the template does too"),
    "SUBSTITUTE": _substitute, "VALUE": _value,
    "CHAR": _char(False), "UNICHAR": _char(True), "CODE": _code(False), "UNICODE": _code(True),
    "REPLACE": _replace,
}
TEXT_HANDLERS.update({f"{name}B": _bytes(f"{name}B", name)
                      for name in ("LEFT", "RIGHT", "MID", "LEN", "FIND", "SEARCH", "REPLACE")})
