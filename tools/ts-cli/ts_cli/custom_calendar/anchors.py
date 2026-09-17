"""Fiscal-year anchor rules.

A fiscal year runs anchor(y) .. anchor(y+1) - 1 day. Because every anchor falls
on the same weekday, that span is always a whole number of weeks — so 52-vs-53
weeks is DERIVED, never configured. Only the leap week's placement is an option.

Pure — no I/O.
"""
from __future__ import annotations

from datetime import date, timedelta

from ts_cli.custom_calendar.spec import CalendarSpec


def sunday_index(d: date) -> int:
    """Sunday-based weekday index (0=Sunday). The only Monday->Sunday conversion."""
    return (d.weekday() + 1) % 7


def _forward_delta(target: date, start_dow: int) -> int:
    """Days from `target` forward to the next occurrence of `start_dow` (0 if same day)."""
    return (start_dow - sunday_index(target)) % 7


def anchor_nearest(year: int, start_month: int, start_dow: int) -> date:
    """The `start_dow` nearest the 1st of `start_month`. NRF / retail standard.

    Reproduces CUSTOM_CALENDAR.PUBLIC.LULULEMON exactly, including its 371-day
    2018 and 2024 years.
    """
    target = date(year, start_month, 1)
    delta = _forward_delta(target, start_dow)
    if delta == 0:
        return target
    # delta days forward vs (7 - delta) days back. The two distances are never
    # equal for an integer delta in 1..6 (that would need delta == 3.5), so
    # there is no tie to break: delta <= 3 means forward is strictly closer.
    return target + timedelta(days=delta if delta <= 3 else delta - 7)


def anchor_first(year: int, start_month: int, start_dow: int) -> date:
    """The first `start_dow` on or after the 1st of `start_month`."""
    target = date(year, start_month, 1)
    return target + timedelta(days=_forward_delta(target, start_dow))


def anchor_fixed52(year: int, start_month: int, start_dow: int, *, first_year: int) -> date:
    """Anchor once, then +364 days forever. Identical to the native ThoughtSpot API.

    Drifts ~1.25 days/year against the Gregorian calendar and never inserts a
    leap week.
    """
    base = anchor_first(first_year, start_month, start_dow)
    return base + timedelta(days=364 * (year - first_year))


def resolve_anchor(spec: CalendarSpec, year: int) -> date:
    if spec.anchor_rule == "nearest":
        return anchor_nearest(year, spec.start_month, spec.start_day_of_week)
    if spec.anchor_rule == "first":
        return anchor_first(year, spec.start_month, spec.start_day_of_week)
    if spec.anchor_rule == "fixed52":
        return anchor_fixed52(year, spec.start_month, spec.start_day_of_week,
                              first_year=spec.first_year)
    raise ValueError(f"Unknown anchor_rule '{spec.anchor_rule}'")
