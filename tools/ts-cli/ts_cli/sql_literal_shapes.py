"""Shape checks for DATE and TIMESTAMP literal text, in one place.

Shared by `ts load databricks` (``commands/load_databricks.py``), which refuses a value that
would fail at execution time before it creates anything, and by the formula-fidelity
harness (``tools/formula-fidelity/fidelity/builders.py``), which validates the literals it
sends. Moved here from builders.py so the two cannot drift (BL-550 review).

ASCII digits only: ``[0-9]``, never ``\\d``, which also matches other scripts' digits.
Pure functions, stdlib only.
"""
from __future__ import annotations

import datetime
import re

DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# The harness's strict form: 'YYYY-MM-DD HH:MM:SS[.fff]' plus, for TIMESTAMP_TZ, an offset
# (' +05:30'). It is what the harness generates, so it accepts nothing looser.
TIMESTAMP_STRICT_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?: [+-][0-9]{2}:[0-9]{2})?")

# The ISO forms a Databricks TIMESTAMP literal accepts, live-verified on DBSQL 2026.35
# (2026-11-08): 'T' or space between date and time, seconds and fraction optional, then
# optionally 'Z' or an offset written +HH:MM, +HHMM or ' +HH:MM'.
TIMESTAMP_ISO_RE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})[T ]([0-9]{2}):([0-9]{2})"
    r"(?::([0-9]{2})(?:\.[0-9]+)?)?(?:Z| ?[+-][0-9]{2}:?[0-9]{2})?")


def is_calendar_date(text: str) -> bool:
    """'YYYY-MM-DD' naming a real day. Databricks refuses '2024-02-30' (INVALID_TYPED_LITERAL)
    only when the statement runs, so the shape alone is not enough."""
    if not DATE_RE.fullmatch(text):
        return False
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def is_iso_timestamp(text: str) -> bool:
    """One of the `TIMESTAMP_ISO_RE` forms with a real day and an in-range time of day."""
    m = TIMESTAMP_ISO_RE.fullmatch(text)
    if not m:
        return False
    year, month, day, hour, minute, second = (int(g) if g else 0 for g in m.groups())
    try:
        datetime.date(year, month, day)
    except ValueError:
        return False
    return hour < 24 and minute < 60 and second < 60
