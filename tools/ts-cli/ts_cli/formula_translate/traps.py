"""Traps: the semantic differences a translated formula carries (spec §6 item 3).

Each trap is derived from the source text and the translated output — only the ones that
fired are returned. The wording is the user-facing line. Live evidence is cited where a
trap rests on it:

- BL-331 (2026-10-06): ``round``'s 2nd argument is an increment, not a digit count.
- OI-2 (2026-10-06): ``day_number_of_week`` is fixed 1 = Monday; ``start_of_week`` compiles
  to ``DATE_TRUNC(week, d)``. Both assume a Monday week start (the Gregorian default).
- OI-3 (2026-10-06): ``diff_months`` / ``diff_years`` count calendar boundaries crossed.
- OI-4 (2026-10-06): ``=``, ``contains`` and ``strpos`` on strings are case-insensitive
  (BL-333). OI-2's week-start consequences are BL-334.

Also hosts the two output repairs that are about ThoughtSpot, not about any one source
language: ``COUNT(*)`` → count of a key column, and a guard against SQL keywords a
translator left behind (``count(DISTINCT x)`` mid-expression, which no ThoughtSpot
function accepts).
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.formula_translate.context import ColumnContext
from ts_cli.formula_translate.refs import split_literals

# Dialects whose string comparison is case-sensitive by default (OI-4 applies).
CASE_SENSITIVE_DIALECTS = {"tableau", "snowflake", "databricks"}

_ROUND_SRC = re.compile(r"\bround\s*\(", re.I)
_ROUND_OUT = re.compile(r"\bround\s*\(")
_DISTINCT_SRC = re.compile(r"\b(countd|distinctcount|count\s*\(\s*distinct|countdistinct)\b", re.I)
_UNIQUE_OUT = re.compile(r"\bunique count\s*\(")
_DIFF_OUT = re.compile(r"\bdiff_(days|months|years|weeks|quarters|hours|minutes|seconds|time)\s*\(")
_DAYS_OVER_7 = re.compile(r"\bdiff_days\s*\([^()]*(?:\([^()]*\)[^()]*)*\)\s*/\s*7\b")
_DIFF_MY_OUT = re.compile(r"\bdiff_(months|years|quarters)\s*\(")
_WEEK_OUT = re.compile(
    r"\b(start_of_week|day_number_of_week|week_number_of_year|day_of_week|"
    r"week_number_of_month|week_number_of_quarter)\s*\(")
_STRCMP_OUT = re.compile(
    r"(\bcontains\s*\(|\bstrpos\s*\(|\bbegins_with\s*\(|\bends_with\s*\(|"
    r"(?:=|!=|<>)\s*'|'\s*(?:=|!=|<>))")
_PASSTHROUGH_OUT = re.compile(r"\bsql_(\w+?)_op\s*\(")
_COUNT_STAR = re.compile(r"\bcount\s*\(\s*(?:\*|1)\s*\)", re.I)
_SQL_LEFTOVER = re.compile(r"\b(DISTINCT|OVER|PARTITION\s+BY|QUALIFY|WITHIN\s+GROUP)\b", re.I)


# Trap lines that mean the output does NOT compute what the source computes: a translation
# carrying one is downgraded to APPROXIMATED, never reported as a clean TRANSLATED.
DOWNGRADE_TRAP_PREFIXES = ("week difference emitted as diff_days / 7",)


def is_downgrade(trap: str) -> bool:
    return trap.startswith(DOWNGRADE_TRAP_PREFIXES)


def _code(expr: str) -> str:
    """``expr`` with every string literal blanked, so keyword checks skip literals."""
    return "".join("''" if lit else seg for lit, seg in split_literals(expr))


def repair_count_star(expr: str, ctx: ColumnContext) -> tuple[str, Optional[str]]:
    """``count ( 1 )`` / ``count(*)`` → ``count ( <key> )``. Returns (expr, trap)."""
    if not _COUNT_STAR.search(_code(expr)):
        return expr, None
    key = ctx.key_reference()
    out = "".join(seg if lit else _COUNT_STAR.sub(f"count ( {key} )", seg)
                  for lit, seg in split_literals(expr))
    return out, ("COUNT(*) has no ThoughtSpot form — counted a non-null key column "
                 f"instead ({key}); name the table's primary key if this is a placeholder")


def leftover_sql(expr: str) -> Optional[str]:
    """A SQL keyword no ThoughtSpot formula accepts, left by a translator, or None."""
    m = _SQL_LEFTOVER.search(_code(expr))
    if m:
        return (f"the translator left the SQL keyword {m.group(1).upper()!r} in its output; "
                "no ThoughtSpot formula accepts it, so this needs a manual rewrite")
    return None


def detect_traps(dialect: str, source: str, output: str) -> list[str]:
    """Trap lines that apply to this (source → output) pair."""
    traps: list[str] = []
    code = _code(output)
    if dialect != "thoughtspot" and _ROUND_SRC.search(source) and _ROUND_OUT.search(code):
        if dialect == "qlik":
            traps.append("round: Qlik's 2nd argument is already a step (increment), "
                         "so it is kept as-is — ThoughtSpot round(x, 0.01) is 2 decimals")
        else:
            traps.append("round: the source's decimal-place count became an increment "
                         "(2 places → 0.01, 0 → 1; round(x, 0) is NULL in ThoughtSpot) — BL-331")
    if _DISTINCT_SRC.search(source) and _UNIQUE_OUT.search(code):
        traps.append("distinct count → `unique count` (a space, not an underscore; "
                     "`unique_count` and `count_distinct` are rejected)")
    if _DIFF_OUT.search(code):
        traps.append("diff_*(end, start): ThoughtSpot takes the LATER date first")
    if _DAYS_OVER_7.search(code):
        traps.append("week difference emitted as diff_days / 7 — a fractional count of "
                     "7-day spans, not the number of week boundaries crossed that a "
                     "DATEDIFF('week') source returns; wrap in floor() or rewrite if it matters")
    if _DIFF_MY_OUT.search(code):
        traps.append("diff_months / diff_years count calendar boundaries crossed "
                     "(Jan 31 → Feb 1 = 1 month), not complete periods (OI-3)")
    if _WEEK_OUT.search(code):
        traps.append("assumes a Monday week start; diverges if the Model's calendar "
                     "starts on another day (day_number_of_week is fixed 1 = Monday; "
                     "start_of_week follows the warehouse's DATE_TRUNC(week)) — OI-2, BL-334")
    if dialect in CASE_SENSITIVE_DIALECTS and _STRCMP_OUT.search(output):
        traps.append("string comparison is case-INSENSITIVE in ThoughtSpot (=, contains, "
                     "strpos — OI-4, BL-333); if the source compared case-sensitively, use "
                     "sql_bool_op ( \"{0} = {1}\" , … ) instead")
    m = _PASSTHROUGH_OUT.search(code)
    if m:
        traps.append(f"passthrough (sql_{m.group(1)}_op): the SQL runs in the warehouse "
                     "(Snowflake syntax assumed), ThoughtSpot cannot plan around it, and the "
                     "variant fixes the column's type and role (Ossie map E7)")
    return traps
