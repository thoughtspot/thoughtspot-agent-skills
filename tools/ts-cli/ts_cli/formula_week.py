"""Week-start notes for emitted ThoughtSpot formulas (BL-334 item 2).

One detector and one wording per note, imported by every translator's reporting path
and by ``ts formula translate``'s traps. Split out of ``formula_common`` under the
file-size gate; same contract — pure functions, stdlib only, Genie-vendorable (listed
in ``agents/databricks/build_mv_lib.py``). Never fork these into a platform module.
"""
from __future__ import annotations

import re

from ts_cli.formula_common import WEEKDAY_FIRST_DAY_INDEX, ts_weekday_number


# ---------------------------------------------------------------------------
# Exact week forms for a KNOWN source week start (BL-373, BL-380)
# ---------------------------------------------------------------------------
#
# Live-probed 2026-10-07 on se-thoughtspot (120 dates, Dec 25 - Jan 13 around six
# year boundaries, every weekday; docs/reviews/2026-10-06-formula-semantics-probes.md
# section 8):
#   * The week start is rebuilt from day_number_of_week, NOT by shifting
#     start_of_week. `add_days ( start_of_week ( add_days ( d , k ) ) , -k )` was
#     exact on the cluster, but start_of_week compiles to DATE_TRUNC(week, d) and the
#     shift breaks under a Snowflake WEEK_START of 7 (Saturday for every Sunday-start
#     week, reproduced in a Snowflake session). day_number_of_week is fixed
#     arithmetic, so `add_days ( date ( d ) , 0 - <days since the week start> )` is
#     exact under any WEEK_START.
#   * week_number_of_year is the ISO-8601 week (Thursday rule), so it disagrees with
#     a "week 1 contains January 1" numbering (Tableau DATEPART('week')) for WHOLE
#     years, not only boundary days: every date of 2021, 2022, 2023 and 2027 was one
#     lower under a Monday start. The Jan-1 form is rebuilt from day_number_of_year
#     and the weekday of start_of_year.


def _first_day_index(first_day: int | str) -> int:
    if isinstance(first_day, str):
        return WEEKDAY_FIRST_DAY_INDEX[first_day.strip().lower()]
    return int(first_day)


def ts_week_start(date_expr: str, first_day: int | str, *, compact: bool = False) -> str:
    """ThoughtSpot formula for the first day of ``date_expr``'s week, the week starting
    on ``first_day`` (a name, or a Monday-based index as in ``ts_weekday_number``).

    Monday stays ``start_of_week``. Any other day is rebuilt from the fixed
    ``day_number_of_week`` so it does not depend on the warehouse's WEEK_START.

    >>> ts_week_start("[d]", "sunday")
    'add_days ( date ( [d] ) , 0 - mod ( day_number_of_week ( [d] ) , 7 ) )'
    >>> ts_week_start("[d]", 0)
    'start_of_week ( [d] )'
    """
    idx = _first_day_index(first_day)
    if idx == 0:
        return f"start_of_week({date_expr})" if compact else f"start_of_week ( {date_expr} )"
    since = ts_weekday_number(date_expr, first_day=idx, base=0, compact=compact)
    if compact:
        return f"add_days(date({date_expr}), 0 - {since})"
    return f"add_days ( date ( {date_expr} ) , 0 - {since} )"


def ts_week_of_year_jan1(date_expr: str, first_day: int | str) -> str:
    """ThoughtSpot formula numbering weeks within the calendar year so that week 1
    is the week containing January 1 and weeks start on ``first_day`` — Tableau's
    DATEPART('week') (1-54). Not ISO: see ``week_number_of_year``.

    >>> ts_week_of_year_jan1("[d]", "monday")
    '( floor ( ( day_number_of_year ( [d] ) - 1 + ( day_number_of_week ( start_of_year ( [d] ) ) - 1 ) ) / 7 ) + 1 )'
    """
    jan1 = f"start_of_year ( {date_expr} )"
    offset = ts_weekday_number(jan1, first_day=_first_day_index(first_day), base=0)
    return (f"( floor ( ( day_number_of_year ( {date_expr} ) - 1 + {offset} ) / 7 ) + 1 )")


# ---------------------------------------------------------------------------
# Week-start notes for emitted ThoughtSpot formulas (BL-334 item 2)
# ---------------------------------------------------------------------------
#
# ThoughtSpot's week functions are built around a Monday week start. What each one
# rests on differs, and the note says exactly that, per function found:
#   * `start_of_week` compiles to DATE_TRUNC(week, d), which follows the Snowflake
#     WEEK_START of ThoughtSpot's connection session. That was 0 (Monday weeks) on
#     se-thoughtspot / APJ_TAB, read from a ThoughtSpot-issued DAYOFWEEK, 2026-10-07;
#     a connection whose user or account sets 2-7 gets that day (BL-334 item 3).
#   * `day_number_of_week` compiles to fixed arithmetic, 1 = Monday ... 7 = Sunday,
#     independent of WEEK_START (2026-10-06) and of a custom calendar bound to the
#     column (2026-10-07, BL-334 item 4).
#   * `week_number_of_year` is the ISO-8601 week (Thursday rule, 2026-10-07, BL-380);
#     a column calendar does not change it either.
#   * `diff_weeks` counts week boundaries from a FIXED Monday (epoch-day arithmetic in
#     its compiled SQL, 2026-10-06).
# Only an explicit calendar argument (`start_of_week ( d , CalName )`, a bare
# calendar keyword) makes them read a custom calendar.
#
# Decision (2026-10-07): translators do NOT emit a calendar argument. Three
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
#: Advisory, for a formula whose only week logic is an exact form the converter built
#: for a week start it KNEW (BL-373). Not review-class.
WEEK_START_EXACT_PREFIX = "exact week start"
WEEK_ADVISORY_PREFIXES = (WEEK_START_NOTE_PREFIX, WEEK_START_EXACT_PREFIX)
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


def _start_of_week_clause(dialect: str | None) -> str:
    if dialect == "databricks":
        # Databricks date_trunc('WEEK', d) is always Monday — no session setting.
        return ("start_of_week compiles to date_trunc('WEEK', d), which Databricks fixes to "
                "Monday; a custom Model calendar bound to the column does not change it "
                "(probed 2026-10-07) — only an explicit calendar argument does "
                "(BL-334 item 4)")
    return ("start_of_week compiles to DATE_TRUNC(week, d), which follows the Snowflake "
            "WEEK_START of ThoughtSpot's connection session — 0 (Monday weeks) on "
            "se-thoughtspot, probed 2026-10-07; a connection whose user or account sets "
            "WEEK_START to 2-7 truncates to that day instead (BL-334 item 3)")


def _week_clauses(fns: list[str], dialect: str | None = None) -> list[str]:
    out: list[str] = []
    if "start_of_week" in fns:
        out.append(_start_of_week_clause(dialect))
    if "day_number_of_week" in fns:
        out.append("day_number_of_week compiles to fixed arithmetic, 1 = Monday … 7 = Sunday, "
                   "independent of WEEK_START and of a custom calendar bound to the column "
                   "(live-probed 2026-10-06 / 2026-10-07, BL-334 item 4)")
    numbers = [f for f in _WEEK_NUMBER_FUNCTIONS if f in fns]
    if numbers:
        clause = (f"{' / '.join(numbers)} number Monday-based Gregorian weeks, and a custom "
                  "calendar bound to the column does not change them (BL-334 item 4)")
        if "week_number_of_year" in numbers:
            clause += ("; week_number_of_year is the ISO-8601 week (Thursday rule), so "
                       "early-January days can be week 52 / 53 and late-December days "
                       "week 1 (live-probed 2026-10-07, BL-380)")
        out.append(clause)
    if "diff_weeks" in fns:
        out.append("diff_weeks counts week boundaries crossed from a FIXED Monday (epoch-day "
                   "arithmetic in its compiled SQL, 2026-10-06); a source counting from another "
                   "start day (SQL DATEDIFF(week) under a non-Monday WEEK_START, a Sunday-start "
                   "BI tool) counts differently")
    return out


def _day_names(starts) -> str:
    names: list[str] = []
    for s in starts:
        if isinstance(s, int):
            s = next(k for k, v in WEEKDAY_FIRST_DAY_INDEX.items() if v == s)
        s = s.strip().lower().capitalize()
        if s not in names:
            names.append(s)
    return " / ".join(names)


def _exact_clause(starts) -> str:
    return (f"exact for a {_day_names(starts)} week start — built on day_number_of_week, "
            "fixed arithmetic that does not depend on the warehouse's WEEK_START or on a "
            "calendar bound to the column (live-verified 2026-10-07, BL-373)")


def week_start_note(ts_expr: str | None, dialect: str | None = None,
                    exact_starts=None) -> str | None:
    """The week-start advisory for an emitted ThoughtSpot formula, tailored to the
    week-dependent functions it calls, or None when it calls none.

    Every translator surfaces this same string (Tableau / Qlik ``review_notes``,
    Snowflake SV ``annotations``, Databricks MV ``annotations`` kind
    ``week_start_assumption``, ``ts formula translate`` traps). Advisory — never
    a status downgrade. ``dialect`` ("databricks") selects the warehouse-specific
    ``start_of_week`` clause; anything else gets the WEEK_START-dependent wording.

    ``exact_starts``: the week start day(s) the CONVERTER knew and built an exact
    ``day_number_of_week`` form for (``ts_week_start`` / ``ts_week_of_year_jan1`` /
    ``ts_weekday_number``) — passed by the converter, never inferred from the text.
    Its ``day_number_of_week`` is then reported as exact for that day, under
    ``WEEK_START_EXACT_PREFIX`` when nothing Monday-based remains; any remaining
    Monday-based function keeps the Monday wording.
    """
    fns = week_dependent_functions(ts_expr)
    if not fns:
        return None
    if exact_starts:
        monday = [f for f in fns if f != "day_number_of_week"]
        if not monday:
            return (f"{WEEK_START_EXACT_PREFIX} ({_day_names(exact_starts)}): "
                    + _exact_clause(exact_starts)
                    + ". No calendar argument is emitted (BL-334)")
        return (f"{WEEK_START_NOTE_PREFIX} ({', '.join(monday)}): "
                + "; ".join(_week_clauses(monday, dialect) + [
                    "day_number_of_week is " + _exact_clause(exact_starts)])
                + ". No calendar argument is emitted, so the Monday-based part is "
                  "Gregorian with a Monday week even on a column bound to another "
                  "calendar (BL-334)")
    return (f"{WEEK_START_NOTE_PREFIX} ({', '.join(fns)}): "
            + "; ".join(_week_clauses(fns, dialect))
            + ". No calendar argument is emitted, so the result is Gregorian with a "
              "Monday week even on a column bound to another calendar (BL-334)")


def week_start_mismatch_note(source: str, first_day: int | str) -> str:
    """REVIEW-class note: ``source`` is known to start its week on ``first_day`` (a
    name, or a Monday-based index as in ``ts_weekday_number``), not Monday, yet the
    emitted formula is Monday-based. A known wrong answer — the caller downgrades."""
    if isinstance(first_day, int):
        first_day = next(k for k, v in WEEKDAY_FIRST_DAY_INDEX.items() if v == first_day)
    return (f"{WEEK_START_MISMATCH_PREFIX}: {source} starts the week on "
            f"{first_day.capitalize()}, but ThoughtSpot's start_of_week / week numbering "
            "is Monday-based, so the translation returns a different week for every date. "
            "Rewrite it by hand from day_number_of_week, which is fixed arithmetic "
            "(BL-334, BL-373)")


WEEK_DIFF_DAYS_NOTE = (
    f"{WEEK_DIFF_DAYS_PREFIX} — a fractional count of 7-day spans, not the "
    "number of week boundaries crossed that a DATEDIFF('week') source returns; "
    "wrap in floor() or rewrite if it matters")


def week_diff_days_note(ts_expr: str | None) -> str | None:
    """REVIEW-class note for ``diff_days ( … ) / 7`` in ``ts_expr``, or None.

    Text-driven, for ``ts formula translate``'s traps. A converter that KNOWS it
    converted a DATEDIFF('week') reports ``WEEK_DIFF_DAYS_NOTE`` from its own
    counter instead — an exact ``DATEDIFF('day', a, b) / 7`` source must not be
    flagged (Tableau, PR #582 re-review)."""
    if not ts_expr or not _WEEK_DIFF_DAYS_RE.search(_week_code(ts_expr)):
        return None
    return WEEK_DIFF_DAYS_NOTE


def is_week_review_note(note: str) -> bool:
    """True for a review-class week note (mismatch, diff_days / 7)."""
    return note.startswith(WEEK_REVIEW_PREFIXES)
