"""Week-start notes for emitted ThoughtSpot formulas (BL-334 item 2).

One detector and one wording per note, imported by every translator's reporting path
and by ``ts formula translate``'s traps. Split out of ``formula_common`` under the
file-size gate; same contract — pure functions, stdlib only, Genie-vendorable (listed
in ``agents/databricks/build_mv_lib.py``). Never fork these into a platform module.
"""
from __future__ import annotations

import re

from ts_cli.formula_common import WEEKDAY_FIRST_DAY_INDEX


# ---------------------------------------------------------------------------
# Week-start notes for emitted ThoughtSpot formulas (BL-334 item 2)
# ---------------------------------------------------------------------------
#
# ThoughtSpot's week functions are built around a Monday week start. What each one
# rests on differs, and the note says exactly that, per function found:
#   * `start_of_week` compiles to DATE_TRUNC(week, d), which follows the warehouse's
#     week-start setting (Snowflake WEEK_START) — Monday only while that is 0 or 1;
#     whether ThoughtSpot sets it on its session is unverified (BL-334 item 3).
#   * `day_number_of_week` compiles to a fixed 1 = Monday expression, independent of
#     WEEK_START (live-probed 2026-10-06); whether a non-default Model calendar
#     changes it is unverified (BL-334 item 4).
#   * `week_number_of_*` assume the default calendar's Monday week; same item 4 caveat.
#   * `diff_weeks` counts week boundaries from a FIXED Monday (epoch-day arithmetic in
#     its compiled SQL, 2026-10-06).
#
# Decision (2026-10-07): translators do NOT emit a calendar argument
# (`start_of_week ( d , 'Calendar' )`); the Model's calendar is the default. Three
# notes, one home (BL-217 — re-implementing them per converter is an angle-9 finding):
#   * week_start_note — ADVISORY. The status is unchanged.
#   * week_start_mismatch_note — the converter KNOWS the source week starts on another
#     day and emitted a Monday-based function anyway: a known wrong answer, so a
#     REVIEW-class note (each converter downgrades in its own vocabulary).
#   * week_diff_days_note — `diff_days ( … ) / 7` is fractional 7-day spans, not
#     week boundaries: REVIEW-class.
# Deliberately NOT week-dependent: `day_of_week` (the day NAME), `is_weekend`
# (Saturday/Sunday either way) and `add_weeks` (seven days).

WEEK_DEPENDENT_FUNCTIONS = (
    "start_of_week", "day_number_of_week", "week_number_of_year",
    "week_number_of_month", "week_number_of_quarter", "diff_weeks",
)

#: Every advisory week-start note begins with this — a stable prefix to test on.
WEEK_START_NOTE_PREFIX = "assumes a Monday week start"
#: Review-class notes: a converter carrying one must not report a clean translation.
WEEK_START_MISMATCH_PREFIX = "week start mismatch"
WEEK_DIFF_DAYS_PREFIX = "week difference emitted as diff_days / 7"
WEEK_REVIEW_PREFIXES = (WEEK_START_MISMATCH_PREFIX, WEEK_DIFF_DAYS_PREFIX)

_WEEK_DEPENDENT_RE = re.compile(
    r"\b(" + "|".join(WEEK_DEPENDENT_FUNCTIONS) + r")\s*\(", re.I)
_WEEK_DIFF_DAYS_RE = re.compile(
    r"\bdiff_days\s*\([^()]*(?:\([^()]*\)[^()]*)*\)\s*/\s*7\b", re.I)
# String literals ('…' with '' doubling, "…") and [column] references, blanked
# before matching so a literal or a column name never reads as a call.
_LITERAL_OR_REF_RE = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"|\[[^\[\]]*\]")

_WEEK_NUMBER_FUNCTIONS = ("week_number_of_year", "week_number_of_month",
                          "week_number_of_quarter")


def _week_code(ts_expr: str) -> str:
    return _LITERAL_OR_REF_RE.sub("''", ts_expr)


def week_dependent_functions(ts_expr: str | None) -> list[str]:
    """The week-dependent ThoughtSpot functions ``ts_expr`` calls, lower-cased, in
    first-seen order (empty when none, or when ``ts_expr`` is empty).

    >>> week_dependent_functions("start_of_week ( [T::d] )")
    ['start_of_week']
    >>> week_dependent_functions("start_of_month ( [T::d] )")
    []
    """
    if not ts_expr:
        return []
    seen: list[str] = []
    for m in _WEEK_DEPENDENT_RE.finditer(_week_code(ts_expr)):
        name = m.group(1).lower()
        if name not in seen:
            seen.append(name)
    return seen


def _week_clauses(fns: list[str]) -> list[str]:
    out: list[str] = []
    if "start_of_week" in fns:
        out.append("start_of_week truncates to Monday under the default calendar, but it "
                   "compiles to DATE_TRUNC(week, d), which follows the warehouse's week-start "
                   "setting (Snowflake WEEK_START) — Monday only while that is 0 or 1, and "
                   "whether ThoughtSpot sets it on its session is unverified (BL-334 item 3)")
    if "day_number_of_week" in fns:
        out.append("day_number_of_week compiles to a fixed 1 = Monday … 7 = Sunday "
                   "expression, independent of WEEK_START (live-probed 2026-10-06); whether "
                   "a non-default Model calendar changes it is unverified (BL-334 item 4)")
    numbers = [f for f in _WEEK_NUMBER_FUNCTIONS if f in fns]
    if numbers:
        out.append(f"{' / '.join(numbers)} number weeks under the default calendar's Monday "
                   "week; whether a non-default Model calendar changes them is unverified "
                   "(BL-334 item 4)")
    if "diff_weeks" in fns:
        out.append("diff_weeks counts week boundaries crossed from a FIXED Monday (epoch-day "
                   "arithmetic in its compiled SQL, 2026-10-06); a source counting from another "
                   "start day (SQL DATEDIFF(week) under a non-Monday WEEK_START, a Sunday-start "
                   "BI tool) counts differently")
    return out


def week_start_note(ts_expr: str | None) -> str | None:
    """The standard Monday-week-start advisory for an emitted ThoughtSpot formula,
    tailored to the week-dependent functions it calls, or None when it calls none.

    Every translator surfaces this same string (Tableau / Qlik ``review_notes``,
    Snowflake SV ``annotations``, Databricks MV ``annotations`` kind
    ``week_start_assumption``, ``ts formula translate`` traps). Advisory — never
    a status downgrade.
    """
    fns = week_dependent_functions(ts_expr)
    if not fns:
        return None
    return (f"{WEEK_START_NOTE_PREFIX} ({', '.join(fns)}): "
            + "; ".join(_week_clauses(fns))
            + ". No calendar argument is emitted, so the Model's calendar applies — "
              "check it (BL-334)")


def week_start_mismatch_note(source: str, first_day: int | str) -> str:
    """REVIEW-class note: ``source`` is known to start its week on ``first_day`` (a
    name, or a Monday-based index as in ``ts_weekday_number``), not Monday, yet the
    emitted formula is Monday-based. A known wrong answer — the caller downgrades."""
    if isinstance(first_day, int):
        first_day = next(k for k, v in WEEKDAY_FIRST_DAY_INDEX.items() if v == first_day)
    return (f"{WEEK_START_MISMATCH_PREFIX}: {source} starts the week on "
            f"{first_day.capitalize()}, but ThoughtSpot's start_of_week / week numbering "
            "is Monday-based, so the translation returns a different week for every date. "
            "Rewrite it by hand; no shifted form is emitted yet (BL-334)")


def week_diff_days_note(ts_expr: str | None) -> str | None:
    """REVIEW-class note for ``diff_days ( … ) / 7`` in ``ts_expr``, or None."""
    if not ts_expr or not _WEEK_DIFF_DAYS_RE.search(_week_code(ts_expr)):
        return None
    return (f"{WEEK_DIFF_DAYS_PREFIX} — a fractional count of 7-day spans, not the "
            "number of week boundaries crossed that a DATEDIFF('week') source returns; "
            "wrap in floor() or rewrite if it matters")


def is_week_review_note(note: str) -> bool:
    """True for a review-class week note (mismatch, diff_days / 7)."""
    return note.startswith(WEEK_REVIEW_PREFIXES)
