"""Year / quarter / period / week skeleton.

All period boundaries are half-open [start, end_exclusive), matching the
`end_of_*_epoch` convention ThoughtSpot emits.

Pure — no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Tuple

from ts_cli.custom_calendar.anchors import resolve_anchor
from ts_cli.custom_calendar.spec import (
    PATTERNS, QUARTER_LAYOUT, CalendarSpec, leap_index, periods_per_year,
    validate_spec,
)


@dataclass(frozen=True)
class Period:
    index: int              # 1-based within the fiscal year
    quarter: int            # 1-4
    index_in_quarter: int   # 1-based
    start: date
    end_exclusive: date
    weeks: int


@dataclass(frozen=True)
class FiscalYear:
    number: int
    start: date
    end_exclusive: date
    weeks: int
    periods: Tuple[Period, ...]


def _quarter_of_period(n_periods: int) -> List[Tuple[int, int]]:
    """[(quarter, index_in_quarter)] for each period, from the derived layout."""
    out: List[Tuple[int, int]] = []
    for q, count in enumerate(QUARTER_LAYOUT[n_periods], start=1):
        out.extend((q, i) for i in range(1, count + 1))
    return out


def _period_weeks(spec: CalendarSpec, total_weeks: int) -> List[int]:
    weeks = list(PATTERNS[spec.pattern])
    extra = total_weeks - sum(weeks)
    if extra not in (0, 1):
        raise ValueError(
            f"Fiscal year has {total_weeks} weeks; expected 52 or 53 for pattern "
            f"'{spec.pattern}'"
        )
    if extra:
        weeks[leap_index(spec)] += extra
    return weeks


def build_years(spec: CalendarSpec) -> Tuple[FiscalYear, ...]:
    """Build every fiscal year in [first_year, last_year]."""
    validate_spec(spec)
    n_periods = periods_per_year(spec)
    layout = _quarter_of_period(n_periods)

    years: List[FiscalYear] = []
    for number in range(spec.first_year, spec.last_year + 1):
        start = resolve_anchor(spec, number)
        end_exclusive = resolve_anchor(spec, number + 1)
        span_days = (end_exclusive - start).days
        if span_days % 7:
            raise ValueError(
                f"Fiscal year {number} spans {span_days} days, not a whole number of "
                f"weeks — anchor rule '{spec.anchor_rule}' is inconsistent"
            )
        total_weeks = span_days // 7
        weeks = _period_weeks(spec, total_weeks)

        periods: List[Period] = []
        cursor = start
        for i, w in enumerate(weeks):
            nxt = cursor + timedelta(weeks=w)
            q, iq = layout[i]
            periods.append(Period(index=i + 1, quarter=q, index_in_quarter=iq,
                                  start=cursor, end_exclusive=nxt, weeks=w))
            cursor = nxt
        if cursor != end_exclusive:
            raise RuntimeError(
                f"Internal invariant violated: fiscal year {number}'s periods tile to "
                f"{cursor}, but the year's end_exclusive is {end_exclusive}"
            )

        years.append(FiscalYear(number=number, start=start, end_exclusive=end_exclusive,
                                weeks=total_weeks, periods=tuple(periods)))
    return tuple(years)
