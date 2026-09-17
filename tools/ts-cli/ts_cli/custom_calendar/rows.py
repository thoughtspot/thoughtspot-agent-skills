"""Expand the grid into calendar rows matching the ThoughtSpot column contract.

Column names and order are taken from live `generate-csv` output and corroborated
across the 42-table CUSTOM_CALENDAR corpus. `end_of_*_epoch` is EXCLUSIVE.

Pure — no I/O.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Tuple

from ts_cli.custom_calendar.anchors import sunday_index
from ts_cli.custom_calendar.grid import build_years
from ts_cli.custom_calendar.labels import render
from ts_cli.custom_calendar.spec import CalendarSpec, LabelSpec, validate_labels, periods_per_year

COLUMNS_10: Tuple[str, ...] = (
    "date", "day_of_week", "month", "quarter", "year",
    "day_number_of_week", "week_number_of_month", "week_number_of_quarter",
    "week_number_of_year", "is_weekend",
)

COLUMNS_30: Tuple[str, ...] = COLUMNS_10 + (
    "monthly", "quarterly",
    "day_number_of_month", "day_number_of_quarter", "day_number_of_year",
    "month_number_of_quarter", "month_number_of_year", "quarter_number_of_year",
    "absolute_week_number", "start_of_week_epoch", "end_of_week_epoch",
    "absolute_month_number", "start_of_month_epoch", "end_of_month_epoch",
    "absolute_quarter_number", "start_of_quarter_epoch", "end_of_quarter_epoch",
    "absolute_year_number", "start_of_year_epoch", "end_of_year_epoch",
)


def columns_for(n: int) -> Tuple[str, ...]:
    if n == 10:
        return COLUMNS_10
    if n == 30:
        return COLUMNS_30
    raise ValueError(f"columns must be 10 or 30, got {n}")


def build_rows(spec: CalendarSpec, labels: LabelSpec, *, columns: int = 30) -> List[Dict[str, object]]:
    """Every day in [first_year, last_year] as a contract-shaped row."""
    cols = columns_for(columns)
    validate_labels(labels, periods_per_year(spec))
    years = build_years(spec)

    out: List[Dict[str, object]] = []
    abs_week = abs_month = abs_quarter = 0
    for y_ix, fy in enumerate(years, start=1):
        quarter_starts: Dict[int, date] = {}
        quarter_ends: Dict[int, date] = {}
        for p in fy.periods:
            quarter_starts.setdefault(p.quarter, p.start)
            quarter_ends[p.quarter] = p.end_exclusive

        year_week_base = abs_week
        for p in fy.periods:
            abs_month += 1
            if p.index_in_quarter == 1:
                abs_quarter += 1
            q_start, q_end = quarter_starts[p.quarter], quarter_ends[p.quarter]

            d = p.start
            while d < p.end_exclusive:
                since_period = (d - p.start).days
                since_quarter = (d - q_start).days
                since_year = (d - fy.start).days
                week_of_year = since_year // 7 + 1
                week_start = fy.start + timedelta(days=(week_of_year - 1) * 7)

                lab = render(labels, fy, p, d)
                row: Dict[str, object] = {
                    "date": d,
                    "day_of_week": lab["day_of_week"],
                    "month": lab["month"],
                    "quarter": lab["quarter"],
                    "year": lab["year"],
                    "day_number_of_week": since_year % 7 + 1,
                    "week_number_of_month": since_period // 7 + 1,
                    "week_number_of_quarter": since_quarter // 7 + 1,
                    "week_number_of_year": week_of_year,
                    "is_weekend": sunday_index(d) in (0, 6),
                    "monthly": lab["monthly"],
                    "quarterly": lab["quarterly"],
                    "day_number_of_month": since_period + 1,
                    "day_number_of_quarter": since_quarter + 1,
                    "day_number_of_year": since_year + 1,
                    "month_number_of_quarter": p.index_in_quarter,
                    "month_number_of_year": p.index,
                    "quarter_number_of_year": p.quarter,
                    "absolute_week_number": year_week_base + week_of_year,
                    "start_of_week_epoch": week_start,
                    "end_of_week_epoch": week_start + timedelta(days=7),
                    "absolute_month_number": abs_month,
                    "start_of_month_epoch": p.start,
                    "end_of_month_epoch": p.end_exclusive,
                    "absolute_quarter_number": abs_quarter,
                    "start_of_quarter_epoch": q_start,
                    "end_of_quarter_epoch": q_end,
                    "absolute_year_number": y_ix,
                    "start_of_year_epoch": fy.start,
                    "end_of_year_epoch": fy.end_exclusive,
                }
                out.append({k: row[k] for k in cols})
                d += timedelta(days=1)
        abs_week += fy.weeks
    return out
