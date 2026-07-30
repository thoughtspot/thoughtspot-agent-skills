"""ts_cli.dependency.view_refs — how a View's `view_columns[]` entry names its column.

Split out of `mutate.py` under the file-size gate (the pattern `publish_apply.py`,
`mv_emit_base.py` and `share_planning.py` follow) and re-exported from it, so callers and
tests keep importing from `mutate` unchanged.

One concern: given a `view_columns[]` entry, does it refer to one of the columns being
removed? That question has its own module because getting it wrong is silent in BOTH
directions — under-removal ships a dangling reference (BL-191's original defect) and
over-removal deletes an unrelated column while emitting perfectly valid TML, which no
import gate or linter catches. Full evidence, the census figures and the 0/0 corpus
measurement: BL-191 in `docs/backlog.md`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

TmlSection = Dict[str, Any]


def _view_column_ref(c: TmlSection) -> str:
    """The reference field of a `view_columns[]` entry.

    `search_output_column` is the field real View TML carries: the 2026-07-30 property
    census (`docs/reviews/2026-07-30-tml-census.md`) covered all 42 `AGGR_WORKSHEET`
    objects on se-thoughtspot and found it on 265 of 265 View columns, while `column_id`
    appeared ZERO times and no value contained `::`.

    `column_id` is read as a FALLBACK — deliberate defensive compatibility, since the
    census is one cluster and it may be a legacy or version-gated spelling elsewhere.
    `agents/shared/schemas/thoughtspot-view-tml.md` states the policy: prefer
    `search_output_column`, tolerate the old spelling on input. (Second-cluster
    re-run: BL-190.)
    """
    return c.get("search_output_column") or c.get("column_id") or ""


# Aggregation / growth prefixes ThoughtSpot puts before a column name in a View's search
# OUTPUT. Census-evidenced: SUM -> "Total" (Total LINEAMOUNT), AVERAGE -> "Average"
# (Average num_rows), COUNT -> "Number of" (Number of URL), growth -> "Growth of"
# (Growth of Total sales). The rest are the display forms of the aggregations
# `thoughtspot-view-tml.md` documents, so a real View using one is not under-cleaned.
#
# Each entry is a SINGLE label. Composite prefixes are deliberately absent: adding
# "Growth of Total" would strip two levels and make `sales` match the real census value
# `Growth of Total sales`, whose column is `Total sales` — reopening the over-removal class
# this matcher exists to close. One level only.
_AGG_PREFIXES: tuple = (
    "Unique count of",
    "Std deviation of",
    "Moving average",
    "Variance of",
    "Growth of",
    "Number of",
    "Unique count",
    "Cumulative",
    "Moving sum",
    "Average",
    "Total",
    "Count",
    "Min",
    "Max",
    "Rank",
)

# Date-bucket function names ThoughtSpot wraps a date column in for the search output.
# Census-evidenced: Month(...), Day(...).
_DATE_BUCKETS: frozenset = frozenset({
    "Second", "Minute", "Hour", "Day", "Week", "Month", "Quarter", "Year",
    "Hour of day", "Day of week", "Day of month", "Week of year",
    "Month of year", "Quarter of year",
})

# A parenthesised decoration: `Month(YM)`, `Day(time)`. The bucket name is ASCII English
# (it is a ThoughtSpot keyword); the INNER column name may be anything, including
# non-ASCII, so it is `.+` and matched non-greedily to the FINAL closing paren.
_BUCKET_RE = re.compile(r"^([A-Za-z][A-Za-z ]*)\((.+)\)$")


def _undecorated_forms(value: str) -> Iterable[str]:
    """Every column name `value` could be the (possibly decorated) label OF.

    Yields the value itself plus, where `value` matches a recognised decoration, the one
    column name inside it. Single-level only — `Growth of Total sales` yields
    `Total sales` (a real column name in the corpus) and NOT `sales`.
    """
    yield value
    if "::" in value:
        # Tolerated legacy `column_id` shape only (`Orders_1::Revenue`).
        # `search_output_column` never contains `::` — 0 of 265 census columns.
        yield value.rsplit("::", 1)[-1]
    for prefix in _AGG_PREFIXES:
        if value.startswith(prefix + " "):
            yield value[len(prefix) + 1:]
    m = _BUCKET_RE.match(value)
    if m and m.group(1) in _DATE_BUCKETS:
        yield m.group(2)


def _decorated_ref_matches(value: Optional[str], cols_to_remove: Iterable[str]) -> bool:
    """True when `value` IS one of `cols_to_remove`, or is that column DECORATED.

    The matcher for `search_output_column`: **whole-value equality against an enumerated
    set of decorations** — `value == col`, `f"{prefix} {col}"`, or `f"{bucket}({col})"`.
    Never a substring search of any kind.

    **Why equality, not containment.** The value is a human label *with spaces*, so any
    containment rule — even one anchored to the end of the string — matches a trailing
    word-SUBSEQUENCE of an unrelated column: `Date` matched `Ship Date` (an ordinary
    UNDECORATED column) and `Month(Order Date)`; `sales` matched the real census value
    `Growth of Total sales`. A View of `{Date, Ship Date, Order Date, Revenue}` lost three
    of four columns on remove-`Date`. Over-removal emits **valid TML**, so nothing
    downstream catches it — silent, the same failure mode BL-191 was filed for.

    **Why not rewrite.py's shape.** `substitute_decorated` is a *substitution* and can lean
    on a longest-match-first tiebreak, so `Order Date` beats `Order`. A boolean *deletion*
    predicate is asked about one column at a time with no view of the others and has no
    tiebreak available, so enumerated equality is the only safe shape. Blast radius differs
    too: an over-matched rename is visible and reversible, an over-matched delete is not.

    Full evidence and the 0/0 corpus measurement: BL-191 in `docs/backlog.md`. All 9
    divergent census values are asserted case-by-case in the tests.

    Residual: a decoration outside the vocabulary (an unseen bucket, or a trailing suffix
    like `Total Revenue (USD)`) will not match, so the column stays. That is the safe
    direction — a dangling reference is rejected loudly at import.
    """
    if not value:
        return False
    cols = cols_to_remove if isinstance(cols_to_remove, (set, frozenset)) else set(cols_to_remove)
    return any(form in cols for form in _undecorated_forms(value))


def _view_column_targeted(c: TmlSection, cols_to_remove: Iterable[str]) -> bool:
    """True when a `view_columns[]` entry refers to one of `cols_to_remove`.

    Matched on `_view_column_ref` allowing for decoration (`_decorated_ref_matches`), OR
    on an exact `name` match. Decoration tolerance is needed because
    `search_output_column` is the label in the View's `search_query` OUTPUT, so it can
    wrap the column in an aggregation or bucket prefix (`Total LINEAMOUNT`, `Month(YM)`).

    The pre-BL-191 matcher was `any(col in c.get("column_id", "") ...)` — on a real View
    always `col in ""`, so dead. Only the `name` fallback worked, leaving an aliased
    column (`name: row_count` / `search_output_column: Average num_rows`) behind.
    """
    return (_decorated_ref_matches(_view_column_ref(c), cols_to_remove)
            or c.get("name") in cols_to_remove)
