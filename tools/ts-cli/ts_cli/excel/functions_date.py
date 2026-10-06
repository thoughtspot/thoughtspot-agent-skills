"""Date handlers (Excel map, Date and time). Traps the rows carry: ``month`` returns a name
(use ``month_number``); ``diff_*`` takes the END date first; ``diff_months`` counts boundaries
(probe record §3); ``day_number_of_week`` is fixed 1 = Monday (§2) — weekday numbering goes
through ``formula_common.ts_weekday_number``, and NETWORKDAYS uses the live-verified per-weekday
counting form (§6)."""
from __future__ import annotations

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.excel.helpers import from_text, graft, literal_int, need
from ts_cli.formula_common import ts_weekday_number

def _nullary(fn: str):
    def handler(tr, n):
        need(tr, n, 0, 0)
        return T.call(fn)
    return handler


def _part(fn: str):
    def handler(tr, n):
        need(tr, n, 1, 1)
        return T.call(fn, tr.date(n.args[0]))
    return handler


def _months_complete(end: dict, start: dict) -> dict:
    """DATEDIF "M": boundaries crossed, minus one when the end day is before the start day."""
    correction = T.ifelse(T.binop("<", T.call("day", end), T.call("day", start)),
                          T.lit_number("1"), T.lit_number("0"))
    return T.binop("-", T.call("diff_months", end, start), correction)


def _datedif(tr, n):
    need(tr, n, 3, 3)
    unit = n.args[2]
    if not isinstance(unit, X.Str):
        tr.review("DATEDIF with a non-literal unit has no rule")
    start, end = tr.date(n.args[0]), tr.date(n.args[1])
    u = unit.value.upper()
    if u == "D":
        return T.call("diff_days", end, start)
    if u == "M":
        return _months_complete(end, start)
    if u == "Y":
        return T.call("floor", T.binop("/", _months_complete(end, start), T.lit_number("12")))
    tr.review(f'DATEDIF unit "{unit.value}" (MD / YM / YD) has no rule in the Excel map row')


def _eomonth(tr, n):
    need(tr, n, 2, 2)
    offset = tr.int_arg(n.args[1], signed=True)
    months = T.number_value(offset)
    ahead = (T.lit_number(str(int(months) + 1)) if months is not None
             else T.binop("+", offset, T.lit_number("1")))
    som = T.call("start_of_month", tr.date(n.args[0]))
    return T.call("add_days", T.call("add_months", som, ahead), T.unop("-", T.lit_number("1")))


def _edate(tr, n):
    need(tr, n, 2, 2)
    return T.call("add_months", tr.date(n.args[0]), tr.int_arg(n.args[1], signed=True))


def _days(tr, n):
    need(tr, n, 2, 2)
    return T.call("diff_days", tr.date(n.args[0]), tr.date(n.args[1]))


# WEEKDAY return_type -> (first day, base), per the Excel map's WEEKDAY row.
_WEEKDAY_TYPES = {1: ("sunday", 1), 2: ("monday", 1), 3: ("monday", 0),
                  **{t: (t - 11, 1) for t in range(11, 18)}}


def _weekday(tr, n):
    need(tr, n, 1, 2)
    rtype = 1 if len(n.args) == 1 else literal_int(n.args[1])
    if rtype not in _WEEKDAY_TYPES:
        tr.review("WEEKDAY with this return_type has no rule (types 1, 2, 3, 11–17 are covered)")
    first, base = _WEEKDAY_TYPES[rtype]  # week-start trap: formula_translate.traps (OI-2)
    date_node = tr.date(n.args[0])
    date = T.to_text(date_node)
    return graft(from_text(ts_weekday_number(date, first_day=first, base=base)), date_node)


# NETWORKDAYS.INTL weekend codes -> non-working day_number_of_week values (1 = Monday).
_WEEKEND_CODES = {1: (6, 7), 2: (7, 1), 3: (1, 2), 4: (2, 3), 5: (3, 4), 6: (4, 5), 7: (5, 6),
                  **{c: ((c - 11 + 6) % 7 + 1,) for c in range(11, 18)}}


def _weekend_days(tr, node) -> tuple:
    if node is None or isinstance(node, X.Missing):
        return _WEEKEND_CODES[1]
    code = literal_int(node)
    if code in _WEEKEND_CODES:
        return _WEEKEND_CODES[code]
    if isinstance(node, X.Str) and len(node.value) == 7 and set(node.value) <= {"0", "1"}:
        if node.value == "1111111":
            tr.review('weekend "1111111" (every day off) is #VALUE! in Excel')
        return tuple(i + 1 for i, ch in enumerate(node.value) if ch == "1")
    tr.review("NETWORKDAYS.INTL weekend argument is not a literal code or 7-character string")


def counting_form(start: str, end: str, weekend: tuple) -> str:
    """The per-weekday counting form, live-verified (probe record §6), as text."""
    n = f"( diff_days ( {end} , {start} ) + 1 )"
    w = f"day_number_of_week ( {start} )"
    out = n
    for k in weekend:
        out += (f" - ( floor ( {n} / 7 ) + if ( mod ( {k} + 7 - {w} , 7 ) < mod ( {n} , 7 ) ) "
                "then 1 else 0 )")
    return out


def _networkdays(intl: bool):
    def handler(tr, n):
        need(tr, n, 2, 4 if intl else 3)
        holidays = n.args[3 if intl else 2] if len(n.args) > (3 if intl else 2) else None
        if holidays is not None and not isinstance(holidays, X.Missing):
            tr.review("NETWORKDAYS with holidays: only the inline-holiday term with weekend "
                      "code 1 is live-verified (probe record §6); compose it from the Excel "
                      "map's NETWORKDAYS.INTL row")
        weekend = _weekend_days(tr, n.args[2] if intl and len(n.args) > 2 else None)
        start_node, end_node = tr.date(n.args[0]), tr.date(n.args[1])
        start, end = T.to_text(start_node), T.to_text(end_node)
        tr.trap("NETWORKDAYS counting form assumes end >= start (Excel returns a negative "
                "count for a reversed range)")
        return graft(from_text(counting_form(start, end, weekend)), start_node, end_node)
    return handler


def _part_arg(tr, node, signed: bool = True) -> dict:
    """A DATE year / month / day: an omitted one is 0; Excel truncates toward zero (a year is
    never negative in a valid DATE, so ``floor`` is its truncation)."""
    if isinstance(node, X.Missing):
        return T.lit_number("0")
    return tr.int_arg(node, signed=signed)


def _fold_date(tr, y: int, m: int, d: int) -> dict:
    """Literal parts: Excel's own arithmetic, done here (a year below 1900 gains 1900;
    months and days overflow into the next unit)."""
    import datetime as _dt
    from ts_cli.excel.coerce import ISO

    if 0 <= y < 1900:
        y += 1900
    if not 1900 <= y <= 9999:
        tr.review(f"DATE with year {y} is #NUM! in Excel")
    months = y * 12 + (m - 1)
    try:
        when = _dt.date(months // 12, months % 12 + 1, 1) + _dt.timedelta(days=d - 1)
    except (ValueError, OverflowError):
        tr.review("DATE outside 1900–9999 is #NUM! in Excel")
    if when < _dt.date(1900, 3, 1):
        tr.review("a DATE before 1900-03-01 is a date in Excel's own 1900 calendar, which "
                  "counts a fictitious 29 February 1900 — no real date to translate it to")
    if when.year > 9999:
        tr.review("DATE after 9999-12-31 is #NUM! in Excel")
    return T.call("to_date", T.lit_string(when.isoformat()), T.lit_string(ISO))


def _plus(node: dict, k: int) -> dict:
    value = T.number_value(node)
    if value is not None:
        from ts_cli.excel.coerce import number_literal
        return number_literal(int(value) + k)
    return T.binop("+" if k > 0 else "-", node, T.lit_number(str(abs(k))))


def _date(tr, n):
    """``DATE(y, m, d)``: built from 1 January with ``add_months`` / ``add_days``, so
    out-of-range months and days overflow as Excel's do (map row). Literal parts fold."""
    from ts_cli.excel.coerce import ISO

    need(tr, n, 3, 3)
    y, m, d = _part_arg(tr, n.args[0], signed=False), *(_part_arg(tr, a) for a in n.args[1:])
    vals = [T.number_value(p) for p in (y, m, d)]
    if None not in vals:
        return _fold_date(tr, *(int(v) for v in vals))
    if vals[0] is not None:
        year = int(vals[0]) + (1900 if 0 <= vals[0] < 1900 else 0)
        if not 1900 <= year <= 9999:
            tr.review(f"DATE with year {year} is #NUM! in Excel")
        start = T.call("to_date", T.lit_string(f"{year:04d}-01-01"), T.lit_string(ISO))
    else:
        tr.trap("DATE with a year from a column: a year below 0 or above 9999 is #NUM! in "
                "Excel; here it does not parse as a date")
        year = T.ifelse(T.binop("<", y, T.lit_number("1900")), T.binop("+", y, T.lit_number(
            "1900")), y)
        start = T.call("to_date", T.call("concat", T.call("to_string", year),
                                         T.lit_string("-01-01")), T.lit_string(ISO))
    months, days = _plus(m, -1), _plus(d, -1)
    out = start
    if not T.is_lit(months, "number", "0"):
        out = T.call("add_months", out, months)
    if not T.is_lit(days, "number", "0"):
        out = T.call("add_days", out, days)
    return out


DATE_HANDLERS = {
    "TODAY": _nullary("today"), "NOW": _nullary("now"), "YEAR": _part("year"),
    "MONTH": _part("month_number"), "DAY": _part("day"), "DATEDIF": _datedif,
    "EOMONTH": _eomonth, "EDATE": _edate, "DAYS": _days, "WEEKDAY": _weekday,
    "NETWORKDAYS": _networkdays(False), "NETWORKDAYS.INTL": _networkdays(True),
    "DATE": _date,
}
