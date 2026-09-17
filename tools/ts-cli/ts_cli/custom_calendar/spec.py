"""Calendar specification dataclasses and validation.

Pure — no I/O — so every function here is unit-testable without a live instance.

Weekday indices are SUNDAY-BASED (0=Sunday .. 6=Saturday) to match the
ThoughtSpot `start_day_of_week` enum. Python's `date.weekday()` is Monday-based;
the single conversion point is `sunday_index()` in anchors.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple, Union

MONTHS_EN: Tuple[str, ...] = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
DAYS_EN: Tuple[str, ...] = (
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
)

# Weeks held by each period, in order. Every pattern totals 52 weeks.
# 12-period patterns repeat a 3-period trio across four quarters;
# 13x4 is a flat 13 periods of 4 weeks (FISCAL_CALENDAR_13_PERIOD).
PATTERNS = {
    "4-4-5": (4, 4, 5) * 4,
    "4-5-4": (4, 5, 4) * 4,
    "5-4-4": (5, 4, 4) * 4,
    "13x4": (4,) * 13,
}

# Periods per quarter, derived from the period count — never configured.
# 13x4 is 3/3/3/4: verified from FISCAL_CALENDAR_13_PERIOD FY2020, where Q4
# holds Period 10..13.
QUARTER_LAYOUT = {12: (3, 3, 3, 3), 13: (3, 3, 3, 4)}

ANCHOR_RULES = ("nearest", "first", "fixed52")
BASES = ("fiscal", "gregorian")


def parse_day_of_week(name: str) -> int:
    """Map a ThoughtSpot day name to a Sunday-based index (0=Sunday)."""
    try:
        return DAYS_EN.index(name.strip().capitalize())
    except ValueError:
        raise ValueError(
            f"Unknown day of week '{name}'. Expected one of: {', '.join(DAYS_EN)}"
        ) from None


@dataclass(frozen=True)
class LabelSpec:
    """Display labels. Attaches to a CalendarSet, shared by every variant.

    `month_names` is the single mechanism for localization, abbreviations
    (FEB) and period labelling (Period 1..13) — there is no separate style option.
    """
    month_names: Tuple[str, ...] = MONTHS_EN
    day_names: Tuple[str, ...] = DAYS_EN
    year_prefix: str = ""
    quarter_prefix: str = ""
    year_basis: str = "fiscal"
    monthly_basis: str = "fiscal"
    quarterly_basis: str = "fiscal"
    fiscal_year_number: str = "start"
    monthly_format: str = "{month} {year}"
    quarterly_format: str = "{quarter} {year}"


@dataclass(frozen=True)
class CalendarSpec:
    """The date grid. Labels live separately, on LabelSpec."""
    start_month: int
    start_day_of_week: int
    pattern: str
    anchor_rule: str
    first_year: int
    last_year: int
    leap_week_period: Union[str, int] = "last"


@dataclass(frozen=True)
class CalendarSet:
    """N calendars unioned with a discriminator column, for RLS."""
    labels: LabelSpec = field(default_factory=LabelSpec)
    variants: Tuple[Tuple[str, CalendarSpec], ...] = ()
    discriminator_column: str = "TS_CALENDAR_GROUP"
    materialisation: str = "view"


def periods_per_year(spec: CalendarSpec) -> int:
    return len(PATTERNS[spec.pattern])


def leap_index(spec: CalendarSpec) -> int:
    """Zero-based index of the period that absorbs a 53rd week."""
    n = periods_per_year(spec)
    if spec.leap_week_period == "last":
        return n - 1
    return int(spec.leap_week_period) - 1


def validate_spec(spec: CalendarSpec) -> None:
    if spec.pattern not in PATTERNS:
        raise ValueError(
            f"Unknown pattern '{spec.pattern}'. Expected one of: {', '.join(PATTERNS)}"
        )
    if spec.anchor_rule not in ANCHOR_RULES:
        raise ValueError(
            f"Unknown anchor_rule '{spec.anchor_rule}'. "
            f"Expected one of: {', '.join(ANCHOR_RULES)}"
        )
    if not 1 <= spec.start_month <= 12:
        raise ValueError(f"start_month must be 1-12, got {spec.start_month}")
    if not 0 <= spec.start_day_of_week <= 6:
        raise ValueError(
            f"start_day_of_week must be 0-6 (Sunday-based), got {spec.start_day_of_week}"
        )
    if spec.last_year < spec.first_year:
        raise ValueError(
            f"last_year ({spec.last_year}) is before first_year ({spec.first_year})"
        )
    n = periods_per_year(spec)
    if spec.leap_week_period != "last":
        try:
            idx = int(spec.leap_week_period)
        except (TypeError, ValueError):
            raise ValueError(
                f"leap_week_period must be 'last' or an integer, got {spec.leap_week_period!r}"
            ) from None
        if not 1 <= idx <= n:
            raise ValueError(
                f"leap_week_period {idx} is out of range for pattern "
                f"'{spec.pattern}' ({n} periods)"
            )


def validate_labels(labels: LabelSpec, periods_per_year: int) -> None:
    if len(labels.month_names) != periods_per_year:
        raise ValueError(
            f"month_names has {len(labels.month_names)} entries but the pattern has "
            f"{periods_per_year} periods"
        )
    if len(labels.day_names) != 7:
        raise ValueError(f"day_names must have 7 entries, got {len(labels.day_names)}")
    for attr in ("year_basis", "monthly_basis", "quarterly_basis"):
        val = getattr(labels, attr)
        if val not in BASES:
            raise ValueError(f"{attr} must be one of {BASES}, got {val!r}")
    if labels.fiscal_year_number not in ("start", "end"):
        raise ValueError(
            f"fiscal_year_number must be 'start' or 'end', got {labels.fiscal_year_number!r}"
        )
