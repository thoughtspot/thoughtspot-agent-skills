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
# OUTPUT. Provenance is split deliberately, because a wrong guess here is SAFE (an
# unrecognised decoration is not stripped, so the column is kept and any dangling reference
# is rejected loudly at import) while a wrong ENTRY is not:
#
#   OBSERVED in the 2026-07-30 census — the only four with evidence:
#     SUM -> "Total" (Total LINEAMOUNT) · AVERAGE -> "Average" (Average num_rows)
#     COUNT -> "Number of" (Number of URL) · growth -> "Growth of" (Growth of Total sales)
#
#   INFERRED — plausible display forms of the remaining aggregations in the
#     `view_columns[].properties.aggregation` enum. NOTE the schema documents the ENUM
#     VALUES (`COUNT_DISTINCT`, `STD_DEVIATION`, `MOVING_SUM`, `RANK`, …), NOT their
#     display spellings, so every prefix below is our guess at the label ThoughtSpot
#     renders and none is verified. `SQL_INT_AGGREGATE_OP` is in the enum but has no
#     prefix form at all — its label is the user's own SQL, so it is unmodelled here.
#
# Each entry is a SINGLE label. Composite prefixes are deliberately absent: adding
# "Growth of Total" would strip two levels and make `sales` match the real census value
# `Growth of Total sales`, whose column is `Total sales` — reopening the over-removal class
# this matcher exists to close. One level only.
_AGG_PREFIXES: tuple = (
    # observed
    "Growth of",
    "Number of",
    "Average",
    "Total",
    # inferred (unverified — see above)
    "Unique count of",
    "Std deviation of",
    "Variance of",
    "Moving average",
    "Unique count",
    "Cumulative",
    "Moving sum",
    "Count",
    "Min",
    "Max",
    "Rank",
)

# Date-bucket function names ThoughtSpot wraps a date column in for the search output.
# OBSERVED: `Month(...)`, `Day(...)`. The rest are INFERRED from ThoughtSpot's date-bucket
# vocabulary and unverified — same safety asymmetry as the prefixes above.
_DATE_BUCKETS: frozenset = frozenset({
    "Second", "Minute", "Hour", "Day", "Week", "Month", "Quarter", "Year",
    "Hour of day", "Day of week", "Day of month", "Week of year",
    "Month of year", "Quarter of year",
})

# A parenthesised decoration: `Month(YM)`, `Day(time)`. The bucket name is ASCII English
# (it is a ThoughtSpot keyword); the INNER column name may be anything, including
# non-ASCII, so it is `.+` — GREEDY, so it runs to the LAST `)` and a column whose own name
# contains parens (`sales(today)`, a real census column) survives the unwrap intact.
_BUCKET_RE = re.compile(r"^([A-Za-z][A-Za-z ]*)\((.+)\)$")


def _undecorated_forms(value: str) -> Iterable[str]:
    """Every column name `value` could be the (possibly decorated) label OF.

    Yields the value itself plus, where `value` matches a recognised decoration, one or
    more candidate column names from inside it — more than one when several prefixes match
    the same value. Single-level only, so `Growth of Total sales` yields `Total sales`
    (a real column name in the corpus) and NOT `sales`.
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

    Full rationale and the corpus measurement: BL-191 in `docs/backlog.md`. The 9 divergent
    `name`/`search_output_column` pairs are recorded in
    `test_accepts_every_decoration_form_observed_in_the_census` — that test is their durable
    home, since the census REPORT tabulates paths and counts rather than the pairs
    themselves, and the export corpus it was computed from is not committed.

    Residuals, both directions:

    - UNDER-removal (safe, loud): a decoration outside the vocabulary — an unseen bucket, a
      trailing suffix like `Total Revenue (USD)`, or a composed label whose base column is
      being removed — will not match, so the column stays and the dangling reference is
      rejected at import.
    - OVER-removal (unsafe, silent): a column legitimately NAMED like a decorated form of
      another, `Total sales` alongside `sales`. `_view_column_targeted` is what prevents
      this, by only stripping decoration when `name != search_output_column`; that gate is
      the reason this function is never the right thing to call directly on a
      `view_columns[]` entry.
    """
    if not value:
        return False
    cols = cols_to_remove if isinstance(cols_to_remove, (set, frozenset)) else set(cols_to_remove)
    return any(form in cols for form in _undecorated_forms(value))


def _view_column_targeted(c: TmlSection, cols_to_remove: Iterable[str]) -> bool:
    """True when a `view_columns[]` entry refers to one of `cols_to_remove`.

    Exact match on `name` or on `_view_column_ref` always counts. Beyond that, decoration
    is stripped — but ONLY when `name != search_output_column`, which is the gate that
    makes the vocabulary safe to apply at all.

    **Why the gate.** Decoration-stripping is a guess that a label was BUILT from a
    shorter column name, and it is wrong whenever a column is simply NAMED that way.
    `Total sales` is a real census column (`tml-census.md` §3.1.1) with
    `name == search_output_column`; without the gate, removing a coexisting `sales` column
    would silently delete it. Divergence is the platform's own signal that the label was
    generated rather than authored: all 9 real decorated entries diverge by definition,
    and an undecorated entry has nothing to strip.

    The gate does not weaken the formula-surfacing path's normal binding,
    `search_output_column == formulas[].name` — that is the EXACT branch, ungated.

    **What the gate costs, measured.** One real case in the 42-View corpus: `Sales with
    MONTH 2` has a column whose `name` and `search_output_column` are BOTH
    `Month(YearMonth)` — the user renamed it to match its own decorated label — surfacing
    formula `YearMonth`. Removing `年月日` drops that formula and the gate now keeps its
    column, leaving one dangling reference where the ungated matcher left none. That is
    accepted deliberately: a dangling reference is rejected LOUDLY at import (`tml_lint`
    I13 / error_code 14516), whereas the `Total sales` over-removal the gate prevents emits
    valid TML and is silent. Trading one loud failure for a class of silent ones is the
    whole design principle of BL-191. Recovering the case needs the formula-surfacing path
    to unwrap decoration on its own terms, which is BL-198's scope (it already has to
    rebuild this closure for transitive chains).

    The pre-BL-191 matcher was `any(col in c.get("column_id", "") ...)` — on a real View
    always `col in ""`, so dead. Only the `name` fallback worked, leaving an aliased
    column (`name: row_count` / `search_output_column: Average num_rows`) behind.
    """
    cols = cols_to_remove if isinstance(cols_to_remove, (set, frozenset)) else set(cols_to_remove)
    ref = _view_column_ref(c)
    name = c.get("name")
    if ref in cols or name in cols:
        return True
    if name is not None and ref == name:
        return False          # authored, not generated — nothing to strip
    return _decorated_ref_matches(ref, cols)
