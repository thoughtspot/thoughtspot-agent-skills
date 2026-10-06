"""Known translator defects — downgrade instead of reporting a wrong result as TRANSLATED.

Each entry names a construct a wrapped translator is KNOWN to get wrong today, with the
backlog item or branch fixing it in the translator itself (BL-217: the fix goes there, not
here). Until it lands, a formula using the construct comes back ``NEEDS_REVIEW`` (wrong
answer) or ``APPROXIMATED`` with a trap (unverified or lossy), so a tester never sees it as
a clean translation.

Remove an entry in the same PR that fixes its translator; the test for the entry then fails
and says so.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

NEEDS_REVIEW = "NEEDS_REVIEW"
APPROXIMATED = "APPROXIMATED"


@dataclass(frozen=True)
class Defect:
    dialects: frozenset
    pattern: "re.Pattern[str]"
    action: str          # NEEDS_REVIEW | APPROXIMATED
    cite: str
    message: str
    allow_functions: frozenset = frozenset()   # output names the guard should not reject
    applies: Optional[Callable[[str], bool]] = None  # extra test on the translated output


KNOWN_DEFECTS: tuple[Defect, ...] = (
    Defect(frozenset({"databricks"}), re.compile(r"\bdatediff\s*\(", re.I), NEEDS_REVIEW,
           "fix/databricks-datediff-order",
           "known defect: the Databricks translator reverses DATEDIFF's argument order "
           "(datediff(end, start) came back as diff_days(start, end)); fix in progress on "
           "fix/databricks-datediff-order"),
    Defect(frozenset({"snowflake"}), re.compile(r"\bDAYOFWEEK\s*\(", re.I), NEEDS_REVIEW,
           "BL-334",
           "known defect (BL-334): DAYOFWEEK is renamed to day_number_of_week, which is "
           "1 = Monday … 7 = Sunday; Snowflake DAYOFWEEK is 0 = Sunday by default "
           "(WEEK_START-dependent). Fix in progress on fix/dayofweek-numbering"),
    Defect(frozenset({"databricks"}), re.compile(r"\bdayofweek\s*\(", re.I), NEEDS_REVIEW,
           "BL-334",
           "known defect (BL-334): dayofweek is renamed to day_number_of_week (1 = Monday); "
           "Databricks dayofweek is 1 = Sunday. Fix in progress on fix/dayofweek-numbering"),
    Defect(frozenset({"tableau"}),
           re.compile(r"\bDATEPART\s*\(\s*['\"]weekday['\"]", re.I), NEEDS_REVIEW, "BL-334",
           "known defect (BL-334): DATEPART('weekday') becomes day_of_week, which returns the "
           "day NAME; Tableau returns a number (1 = Sunday by default). Fix in progress on "
           "fix/dayofweek-numbering"),
    Defect(frozenset({"snowflake", "databricks"}), re.compile(r"\bZEROIFNULL\s*\(", re.I),
           APPROXIMATED, "BL-226",
           "ZEROIFNULL → zeroifnull: the translator emits it, but it is not in the ThoughtSpot "
           "formula catalog and has never been probed (BL-226) — validate before use, or "
           "write ifnull ( x , 0 )",
           allow_functions=frozenset({"zeroifnull"})),
    Defect(frozenset({"tableau"}), re.compile(r"\bZN\s*\(", re.I), APPROXIMATED, "tableau",
           "ZN() was dropped: a NULL now stays NULL where Tableau returned 0 — inside "
           "arithmetic (ZN(SUM([a])) / SUM([b])) the whole result becomes NULL for that row; "
           "wrap the operand in ifnull ( … , 0 ) if the 0 matters",
           applies=lambda out: "ifnull" not in out),
)


def find_defects(dialect: str, source: str, output: str) -> list[Defect]:
    return [d for d in KNOWN_DEFECTS
            if dialect in d.dialects and d.pattern.search(source)
            and (d.applies is None or d.applies(output))]
