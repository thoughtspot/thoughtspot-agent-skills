"""BL-373 / BL-380 — exact week forms for a KNOWN source week start.

`formula_week.ts_week_start` and `ts_week_of_year_jan1` are evaluated with a Python
model of the ThoughtSpot functions they use — each modelled on its compiled SQL
(se-thoughtspot, 2026-10-06 / 2026-10-07) — over Dec 20 - Jan 15 around ten year
boundaries (every Jan-1 weekday), for all seven week starts. Expectations are
derived independently from `datetime` (the week-start day on or before the date;
Tableau's "week 1 contains January 1" numbering).

The forms themselves were live-verified on 120 dates, 2026-10-07: see
docs/reviews/2026-10-06-formula-semantics-probes.md section 8.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

import pytest

from ts_cli.formula_common import WEEKDAY_FIRST_DAY_INDEX
from ts_cli.formula_week import ts_week_of_year_jan1, ts_week_start

DATES = [date(y, 12, 20) + timedelta(days=i)
         for y in range(2019, 2029) for i in range(27)]
STARTS = list(WEEKDAY_FIRST_DAY_INDEX)  # monday .. sunday


def _dnw(d: date) -> int:
    """ThoughtSpot day_number_of_week: (MOD(DATEDIFF(day, 1970-01-01, d) + 3, 7) + 1)."""
    return ((d - date(1970, 1, 1)).days + 3) % 7 + 1


def _ts_mod(a: int, b: int) -> int:
    """ThoughtSpot mod takes the dividend's sign (Snowflake MOD)."""
    return int(math.fmod(a, b))


_ENV = {
    "day_number_of_week": _dnw,
    "mod": _ts_mod,
    "add_days": lambda d, n: d + timedelta(days=n),
    "date": lambda d: d,
    # start_of_week compiled to DATE_TRUNC(week, d) — Monday under WEEK_START 0/1,
    # the value read from ThoughtSpot's own session on 2026-10-07.
    "start_of_week": lambda d: d - timedelta(days=d.weekday()),
    "start_of_year": lambda d: date(d.year, 1, 1),
    "day_number_of_year": lambda d: d.timetuple().tm_yday,
    "floor": math.floor,
}


def _evaluate(formula: str, d: date):
    body = re.sub(r"\b([a-z_]+)\s*\(", r"\1(", formula).replace("[d]", "D")
    assert re.fullmatch(r"[\w\s()+\-,/]*", body), body
    return eval(body, {"__builtins__": {}}, {**_ENV, "D": d})


def _week_start_expected(d: date, start: str) -> date:
    idx = WEEKDAY_FIRST_DAY_INDEX[start]  # Monday-based == datetime.weekday()
    return d - timedelta(days=(d.weekday() - idx) % 7)


def _tableau_week_expected(d: date, start: str) -> int:
    jan1 = date(d.year, 1, 1)
    return (d - _week_start_expected(jan1, start)).days // 7 + 1


@pytest.mark.parametrize("start", STARTS)
def test_week_start_is_exact_for_every_start_day(start):
    formula = ts_week_start("[d]", start)
    for d in DATES:
        assert _evaluate(formula, d) == _week_start_expected(d, start), (start, d)


@pytest.mark.parametrize("start", STARTS)
def test_week_of_year_jan1_is_exact_for_every_start_day(start):
    formula = ts_week_of_year_jan1("[d]", start)
    for d in DATES:
        assert _evaluate(formula, d) == _tableau_week_expected(d, start), (start, d)


def test_jan1_is_always_week_1_and_week_54_occurs():
    # Tableau's ww runs 1-54: 2000 starts on a Saturday and is a leap year, so a
    # Sunday-start Dec 31 2000 is week 54.
    f = ts_week_of_year_jan1("[d]", "sunday")
    assert _evaluate(f, date(2000, 12, 31)) == 54
    for y in range(2019, 2029):
        assert all(_evaluate(ts_week_of_year_jan1("[d]", s), date(y, 1, 1)) == 1
                   for s in STARTS)


def test_monday_week_start_stays_start_of_week():
    assert ts_week_start("[d]", "monday") == "start_of_week ( [d] )"
    assert ts_week_start("D", 0, compact=True) == "start_of_week(D)"


def test_non_monday_form_does_not_use_start_of_week():
    # start_of_week compiles to WEEK_START-dependent SQL; a shifted start_of_week was
    # wrong under WEEK_START = 7 (Snowflake session probe, 2026-10-07).
    for s in STARTS[1:]:
        assert "start_of_week" not in ts_week_start("[d]", s)


@pytest.mark.parametrize("d, expected", [
    # Live values, se-thoughtspot 2026-10-07 (Monday start) — week_number_of_year (ISO)
    # beside the Jan-1 form: they differ for the whole of 2021.
    (date(2021, 1, 1), 1), (date(2021, 1, 4), 2), (date(2019, 12, 30), 53),
    (date(2023, 1, 2), 2), (date(2026, 1, 5), 2),
])
def test_matches_live_monday_values(d, expected):
    assert _evaluate(ts_week_of_year_jan1("[d]", "monday"), d) == expected
