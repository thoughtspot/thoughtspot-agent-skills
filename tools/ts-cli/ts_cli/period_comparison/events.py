"""Anchor dates for the built-in retail events a period comparison is centred on.

Pure date arithmetic, no I/O. Each event key resolves to one calendar date per
year; the comparison windows are built around that date by later modules.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

BUILTIN_EVENTS: dict[str, str] = {
    "black-friday": "Black Friday",
    "cyber-monday": "Cyber Monday",
    "christmas": "Christmas",
    "boxing-day": "Boxing Day",
    "easter": "Easter",
}


def easter_sunday(year: int) -> date:
    """Return Western (Gregorian) Easter Sunday for ``year``.

    Anonymous Gregorian algorithm (Meeus/Jones/Butcher).
    """
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - the algorithm's own name
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _thanksgiving_us(year: int) -> date:
    """Fourth Thursday of November (US Thanksgiving)."""
    first = date(year, 11, 1)
    # date.weekday(): Monday=0 ... Thursday=3
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    return first_thursday + timedelta(weeks=3)


def _black_friday(year: int) -> date:
    return _thanksgiving_us(year) + timedelta(days=1)


def _cyber_monday(year: int) -> date:
    return _black_friday(year) + timedelta(days=3)


_RESOLVERS: dict[str, Callable[[int], date]] = {
    "black-friday": _black_friday,
    "cyber-monday": _cyber_monday,
    "christmas": lambda year: date(year, 12, 25),
    "boxing-day": lambda year: date(year, 12, 26),
    "easter": easter_sunday,
}


def anchor_date(event: str, year: int) -> date:
    """Return the date ``event`` falls on in ``year``.

    Raises ``KeyError`` when ``event`` is not a key of ``BUILTIN_EVENTS``.
    """
    if event not in BUILTIN_EVENTS:
        raise KeyError(event)
    return _RESOLVERS[event](year)
