"""Qlik week handlers: Weekday(), WeekStart(), FirstWeekDay (BL-334, BL-373).

Split out of ``qlik/functions.py`` under the file-size gate and re-exported from it,
so callers keep importing from ``functions``. It imports nothing from ``functions``.
Pure functions, no I/O.
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.formula_common import ts_weekday_number
from ts_cli.formula_week import ts_week_start


def _weekday(args: list[str], first_week_day: Optional[int] = None) -> Optional[str]:
    """Qlik Weekday(date[, first_week_day]) -> ThoughtSpot day_number_of_week,
    origin shifted.

    Qlik `Weekday()` returns "an integer between 0-6" counted from the week's
    first day; `first_week_day` is 0 = Monday ... 6 = Sunday and, when omitted,
    comes from the app's `FirstWeekDay` variable (help.qlik.com, WeekDay — script
    and chart function: `weekday('10/12/1971')` = 1 for a Tuesday under
    FirstWeekDay 0, `weekday('10/12/1971', 6)` = 2). `FirstWeekDay` is set by the
    app's regional settings in the load script — US apps typically carry
    `SET FirstWeekDay=6;` (Sunday), European ones `0` — so there is NO safe
    default. ThoughtSpot `day_number_of_week()` is fixed 1 = Monday (live-probed
    2026-10-06); the shift is formula_common.ts_weekday_number (BL-217/BL-334),
    whose Monday-based index is exactly Qlik's encoding.

    Origin, in order: a literal second argument; else ``first_week_day`` (from
    `SET FirstWeekDay=n;` in the recovered load script — see
    ``parse_first_week_day``); else None, which flags the call for review rather
    than guessing (BL-334). A non-literal second argument is also flagged.
    """
    if len(args) == 2 and args[1].strip() in {str(i) for i in range(7)}:
        first: Optional[int] = int(args[1].strip())
    elif len(args) == 1:
        first = first_week_day
    else:
        return None
    if first is None:
        return None
    return ts_weekday_number(args[0], first_day=first, base=0, compact=True)


def _weekstart(args: list[str], first_week_day: Optional[int] = None) -> Optional[str]:
    """Qlik WeekStart(date[, period_no[, first_week_day]]) -> the first day of the week.

    The week start comes from a literal third argument, else the app's `FirstWeekDay`
    (0 = Mon ... 6 = Sun). A known start gets the exact form, formula_week.ts_week_start:
    Monday is `start_of_week`; any other day is rebuilt from the fixed
    `day_number_of_week` (BL-373, live-verified 2026-10-07). An unknown start is
    emitted as `start_of_week` with the advisory week note. A literal integer
    period_no shifts by 7 * n days. A non-literal offset or first week day returns
    None and is flagged NEEDS REVIEW (a bare rename once emitted the invalid
    `start_of_week(D,0,6)` and reported OK).
    """
    if not 1 <= len(args) <= 3:
        return None
    offset = 0
    if len(args) >= 2:
        if not re.fullmatch(r"\s*-?\d+\s*", args[1]):
            return None
        offset = int(args[1])
    first = first_week_day
    if len(args) == 3:
        if args[2].strip() not in {str(i) for i in range(7)}:
            return None
        first = int(args[2].strip())
    out = ts_week_start(args[0], first or 0, compact=True)
    return f"add_days({out}, {7 * offset})" if offset else out


_WEEK_CALL = re.compile(r"(?i)\b(weekday|weekstart)\s*\(")
_DAY_ARG = {str(i) for i in range(7)}


# Qlik string literals ('…', '' doubling), double-quoted and [bracketed] field names.
_OPAQUE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\[(?:[^\]]|\]\])*\]")


def _blank_opaque(expr: str) -> str:
    """``expr`` with the inside of every literal / field name blanked, length kept, so
    ``[Weekday(x)]`` or ``'weekday(z)'`` never reads as a call (#589 re-review)."""
    return _OPAQUE.sub(lambda m: m.group(0)[0] + "_" * (len(m.group(0)) - 2)
                       + m.group(0)[-1], expr)


def _week_calls(expr: str):
    """(lower-cased name, top-level args) of each Weekday() / WeekStart() call, found
    outside literals and field names. The structure is read from the blanked text
    (same length), and each arg is sliced from the original at the same span."""
    original = expr or ""
    blanked = _blank_opaque(original)
    for m in _WEEK_CALL.finditer(blanked):
        depth, i = 0, m.end() - 1
        for i in range(m.end() - 1, len(blanked)):
            depth += {"(": 1, ")": -1}.get(blanked[i], 0)
            if depth == 0:
                break
        # Top-level commas of the blanked inner text — a comma inside a literal or a
        # field name was blanked away — then the same spans of the original.
        args, start, level = [], m.end(), 0
        for j in range(m.end(), i):
            c = blanked[j]
            level += 1 if c in "([{" else -1 if c in ")]}" else 0
            if c == "," and level == 0:
                args.append(original[start:j])
                start = j + 1
        if original[start:i].strip() or args:
            args.append(original[start:i])
        yield m.group(1).lower(), args


def known_week_starts(expr: str, first_week_day: Optional[int] = None) -> list[int]:
    """Week start days (0 = Mon … 6 = Sun) for which ``translate`` emitted an exact
    ``day_number_of_week`` form — a ``Weekday()`` with a known first day, a
    ``WeekStart()`` with a known non-Monday one — read from the SOURCE, so the week
    note can say what was emitted (#589 review). Monday ``WeekStart`` is
    ``start_of_week`` and keeps the Monday wording."""
    found: list[int] = []
    for name, args in _week_calls(expr):
        if name == "weekday":
            day = (int(args[1]) if len(args) == 2 and args[1].strip() in _DAY_ARG
                   else first_week_day if len(args) == 1 else None)
        else:
            day = (int(args[2]) if len(args) == 3 and args[2].strip() in _DAY_ARG
                   else first_week_day if len(args) <= 2 else None)
            if day == 0:
                day = None
        if day is not None and day not in found:
            found.append(day)
    return found


def _weekstart_arg_problem(expr: str) -> str:
    """'unsupported literal' (1.5, +1, 7) or 'non-literal' — the first bad WeekStart arg."""
    for name, args in _week_calls(expr):
        if name != "weekstart":
            continue
        for k, a in enumerate(args[1:3], start=1):
            ok = (re.fullmatch(r"\s*-?\d+\s*", a) if k == 1 else a.strip() in _DAY_ARG)
            if not ok:
                kind = ("an unsupported literal" if re.fullmatch(r"\s*[-+]?[\d.]+\s*", a)
                        else "a non-literal")
                what = "period offset" if k == 1 else "first week day"
                return f"{kind} {what} {a.strip()!r}"
    return "a non-literal period offset or first week day"


_FIRST_WEEK_DAY_RE = re.compile(
    r"(?im)^\s*(?:SET|LET)\s+FirstWeekDay\s*=\s*'?\s*([0-6])\s*'?\s*;")


def parse_first_week_day(load_script: Optional[str]) -> Optional[int]:
    """`SET FirstWeekDay=n;` from a Qlik load script -> n (0 = Mon ... 6 = Sun).

    The last assignment wins, as it would when the script runs. None when there
    is no script or no assignment — callers must then flag, not assume."""
    if not load_script:
        return None
    found = _FIRST_WEEK_DAY_RE.findall(load_script)
    return int(found[-1]) if found else None
