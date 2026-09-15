"""Display-label rendering.

The date grid and the labels are independent; almost all client-specific
variation lives here. `month_names` is the single mechanism for localization,
abbreviation and period labelling.

Pure — no I/O.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Tuple

from ts_cli.custom_calendar.anchors import sunday_index
from ts_cli.custom_calendar.grid import FiscalYear, Period
from ts_cli.custom_calendar.spec import MONTHS_EN, PATTERNS, LabelSpec


def default_month_names(pattern: str) -> Tuple[str, ...]:
    """Default period labels for a pattern.

    12-period patterns get English month names. `13x4` gets `Period 01`..`Period 13`,
    ZERO-PADDED deliberately: unpadded labels sort lexically as
    `Period 1, Period 10, Period 11, Period 12, Period 13, Period 2, ...`, so any
    consumer that orders by the label rather than by `month_number_of_year` lists
    periods wrongly. Confirmed 2026-09-15 against
    CUSTOM_CALENDAR.PUBLIC.FISCAL_CALENDAR_13_PERIOD. Padding makes lexical and
    numeric order coincide at no cost.
    """
    n = len(PATTERNS[pattern])
    if n == 12:
        return MONTHS_EN
    return tuple("Period {:02d}".format(i) for i in range(1, n + 1))


def fiscal_year_label(labels: LabelSpec, fy: FiscalYear) -> str:
    """The fiscal year number as a bare string, before any prefix.

    ThoughtSpot numbers a fiscal year by the calendar year it STARTS in —
    verified on semantic-sql for both July and December offsets. `end` is
    offered because some organisations number by the ending year instead.
    """
    number = fy.number if labels.fiscal_year_number == "start" else fy.number + 1
    return str(number)


def _year_value(labels: LabelSpec, fy: FiscalYear, d: date, basis: str) -> str:
    return str(d.year) if basis == "gregorian" else fiscal_year_label(labels, fy)


def render(labels: LabelSpec, fy: FiscalYear, period: Period, d: date) -> Dict[str, str]:
    """The six string label columns for one date."""
    month = labels.month_names[period.index - 1]
    quarter = f"{labels.quarter_prefix}{period.quarter}"

    year = f"{labels.year_prefix}{_year_value(labels, fy, d, labels.year_basis)}"
    monthly_year = f"{labels.year_prefix}{_year_value(labels, fy, d, labels.monthly_basis)}"
    quarterly_year = f"{labels.year_prefix}{_year_value(labels, fy, d, labels.quarterly_basis)}"

    return {
        "day_of_week": labels.day_names[sunday_index(d)],
        "month": month,
        "quarter": quarter,
        "year": year,
        "monthly": labels.monthly_format.format(month=month, year=monthly_year),
        "quarterly": labels.quarterly_format.format(quarter=quarter, year=quarterly_year),
    }
