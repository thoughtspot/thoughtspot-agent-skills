"""``TEXT(value, format_text)`` (Excel map, Text, and its *TEXT format codes* table).

Only the subset with an exact Snowflake ``TO_CHAR`` form is translated; every other format
code is NEEDS_REVIEW, never an approximation. Live facts (probe record §7, se-thoughtspot,
2026-10-07): ``TO_CHAR(x, 'FM…0.00')`` rounds half away from zero on a DOUBLE as Excel does
(2.675 → ``2.68``, 0.125 → ``0.13``, −2.5 with ``'FM…0'`` → ``-3``), groups with
``'FM999,…,990'``, and formats a DATE with ``YYYY`` / ``YY`` / ``MM`` / ``MON`` (``Mar``) /
``MMMM`` (``March``) / ``DD`` / ``DY`` (``Fri``) / ``HH24`` / ``MI`` / ``SS``.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.helpers import need, template

POSITIONS = 30          # digit positions in a number format: beyond, TO_CHAR prints '#'
_NUMBER = re.compile(r"(?P<int>[#,]*0[0,]*)(?:\.(?P<frac>0+))?(?P<pct>%?)")
NEG_ZERO_TRAP = ("TEXT of a negative number that rounds to zero at the format's precision: "
                 "the warehouse prints a minus sign (-0.00, live); Excel's output for that "
                 "case was not verified")
MONTH_NAME_NOTE = ("month and day names are English in the warehouse; Excel's follow the "
                   "workbook's locale")
_DATE_TOKENS = {"yyyy": "YYYY", "yy": "YY", "mmmm": "MMMM", "mmm": "MON", "mm": "MM",
                "dd": "DD", "ddd": "DY", "hh": "HH24", "ss": "SS"}
_SEPARATORS = set("-/ :.,")


def _number_format(fmt: str):
    """``(Snowflake format, decimals, percent)`` for the plain number subset, else None."""
    m = _NUMBER.fullmatch(fmt)
    if not m or ",," in m["int"] or m["int"].endswith(","):
        return None
    digits = m["int"].replace(",", "")
    if "#" in digits.lstrip("#"):
        return None                       # '#' after a '0' is not a plain integer part
    zeros = digits.count("0")
    pattern = ["0"] * zeros + ["9"] * (POSITIONS - zeros)   # right to left
    if "," in m["int"]:
        out = []
        for i, ch in enumerate(pattern):
            if i and i % 3 == 0:
                out.append(",")
            out.append(ch)
        pattern = out
    sf = "FM" + "".join(reversed(pattern))
    decimals = len(m["frac"] or "")
    if decimals:
        sf += "." + "0" * decimals
    return sf, decimals, bool(m["pct"])


def _date_format(fmt: str):
    """The Snowflake format for a format of date / time tokens and separators, else None."""
    runs = re.findall(r"y+|m+|d+|h+|s+|.", fmt.lower())
    out, kinds = [], []
    for i, run in enumerate(runs):
        if run in _SEPARATORS:
            out.append(run)
            kinds.append("sep")
            continue
        if run not in _DATE_TOKENS:
            return None
        tok = _DATE_TOKENS[run]
        if run == "mm":
            prev = next((k for k in reversed(kinds) if k != "sep"), None)
            nxt = next((r for r in runs[i + 1:] if r not in _SEPARATORS), None)
            if prev == "hh" or nxt == "ss":
                tok = "MI"                # Excel reads mm after hh / before ss as minutes
        out.append(tok)
        kinds.append(run)
    if not any(k != "sep" for k in kinds):
        return None
    return "".join(out), any(k in ("hh", "ss") or t == "MI" for k, t in zip(kinds, out))


def _number(tr, x: dict, fmt: str, spec) -> dict:
    sf, decimals, pct = spec
    value = T.number_value(x)
    if value is not None:
        shown = (value * (100 if pct else 1)).quantize(Decimal(1).scaleb(-decimals),
                                                       rounding=ROUND_HALF_UP)
        if value < 0 and shown == 0:
            tr.review(NEG_ZERO_TRAP)
        if abs(shown) >= Decimal(10) ** POSITIONS:
            tr.review(f"TEXT of a number with more than {POSITIONS} integer digits")
    else:
        tr.trap(NEG_ZERO_TRAP, downgrade=True)
    sql = f"TO_CHAR({{0}}{' * 100' if pct else ''}, '{sf}'){' || ' + repr('%') if pct else ''}"
    return T.call("sql_string_op", template(sql), x)


def _text(tr, n):
    need(tr, n, 2, 2)
    fmt_node = n.args[1]
    if not isinstance(fmt_node, X.Str):
        tr.review("TEXT with a non-literal format has no rule: the format decides the form")
    fmt = fmt_node.value
    spec = _number_format(fmt)
    if spec is not None:
        x = tr.expr(n.args[0])
        t = tr.fine_type(x)
        from ts_cli.excel.coerce import as_number, string_value
        text = string_value(x)
        if text is not None:
            try:
                Decimal(text.strip())
            except ArithmeticError:
                tr.note("TEXT of text that is not a number returns the text unchanged")
                return x
            x = as_number(tr, x)
        elif t not in ("int", "double", "number"):
            tr.review(f"TEXT with a number format over {'a value of unknown type' if t is None else 'a ' + t}: "
                      "Excel formats a number (a date as its serial, text that is a number as "
                      "that number) — pass data_type in --columns")
        return _number(tr, x, fmt, spec)
    if fmt.lower() == "dddd":
        # day_of_week returns the name in lower case ('friday', live 2026-10-07); Snowflake's
        # TO_CHAR has no full day-name element, so INITCAP restores Excel's 'Friday'
        tr.note(MONTH_NAME_NOTE)
        return T.call("sql_string_op", template("INITCAP({0})"),
                      T.call("day_of_week", tr.date(n.args[0])))
    dated = _date_format(fmt)
    if dated is None:
        tr.review(f'TEXT format "{fmt}" is outside the translated subset (plain numbers, '
                  "percentages, and date / time codes yyyy yy mmmm mmm mm dd ddd hh ss) — "
                  "Excel map TEXT format codes")
    sf, _timed = dated
    if re.search(r"MON|MMMM|DY", sf):
        tr.note(MONTH_NAME_NOTE)
    return T.call("sql_string_op", template(f"TO_CHAR({{0}}, '{sf}')"), tr.date(n.args[0]))


FORMAT_HANDLERS = {"TEXT": _text}
