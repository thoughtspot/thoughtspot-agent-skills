"""Contract and invariant checks for generated or externally-built calendars.

Pure — no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Sequence

from ts_cli.custom_calendar.rows import COLUMNS_10
from ts_cli.custom_calendar.spec import MONTHS_EN

# Closed vocabularies: a fixed set of values, so drift across variants breaks
# ThoughtSpot's search suggestions (AUGUST vs AUG both offered, only one valid).
CLOSED_VOCABULARY_COLUMNS = ("day_of_week", "month", "quarter")
# Derived columns: values legitimately differ across variants with different
# date ranges, so only the FORMAT is comparable.
DERIVED_LABEL_COLUMNS = ("year", "monthly", "quarterly")

# Values ThoughtSpot's filter widget recognises as a month: the English month
# names and their three-letter abbreviations (the corpus ships both `April` and
# `FEB`). Anything else — `Period 01`, and see the caveat below — is a label the
# widget cannot offer as a typed choice.
_MONTH_NAME_TOKENS = frozenset(
    [m.lower() for m in MONTHS_EN] + [m[:3].lower() for m in MONTHS_EN]
)
_YEAR_LABEL_RE = re.compile(r"^\d{4}$")
_SAMPLE = 5


@dataclass(frozen=True)
class Finding:
    severity: str   # "error" | "warning"
    code: str
    message: str


def _sample(values: List[str]) -> str:
    shown = ", ".join(repr(v) for v in values[:_SAMPLE])
    return shown + (f" (+{len(values) - _SAMPLE} more)" if len(values) > _SAMPLE else "")


def _filter_widget_findings(rows: Sequence[Dict[str, object]]) -> List[Finding]:
    """Label values ThoughtSpot's filter widget cannot take as TYPED input.

    Both are product limitations of the typed-value filter components only. The
    calendar stays fully usable: date-range filters and dynamic/relative filters
    ("this year") work, and query generation, grouping, aggregation and display
    are unaffected — the numeric columns carry the ordering. So both are
    WARNINGS, not errors: these calendars are legitimate, just constrained.

    Provenance: ThoughtSpot product knowledge confirmed at PR review on
    2026-09-16 — NOT an automated probe, and there is no REST surface that could
    be one. See the skill's references/open-items.md item 6.

    `quarter` is deliberately NOT checked: a prefixed quarter label (`Q1`) IS
    selectable. The YYYY-only rule is specific to the year filter.

    Caveat on the month check: a real month name in another language is warned
    about here too, because whether the widget reads one as a month name was not
    established. Such a calendar registers fine (open item 1, live-verified).
    """
    findings: List[Finding] = []

    months = sorted({str(r["month"]) for r in rows if "month" in r})
    non_month = [m for m in months if m.strip().lower() not in _MONTH_NAME_TOKENS]
    if non_month:
        findings.append(Finding(
            "warning", "month-label-not-filter-selectable",
            f"month labels that are not month names cannot be SELECTED in a "
            f"ThoughtSpot filter widget: {_sample(non_month)}. The calendar is "
            "otherwise unaffected — querying, grouping, aggregation and display "
            "all work, and it stays filterable by a date range, by a dynamic "
            "filter (\"this year\"), or on month_number_of_year. Drop "
            "--month-names only if typed month filtering matters more than the "
            "label text."))

    years = sorted({str(r["year"]) for r in rows if "year" in r})
    non_numeric = [y for y in years if not _YEAR_LABEL_RE.match(y.strip())]
    if non_numeric:
        findings.append(Finding(
            "warning", "year-label-not-filter-typeable",
            f"ThoughtSpot's year filter accepts a four-digit YYYY only, so these "
            f"year labels cannot be typed into it: {_sample(non_numeric)} "
            "(--year-prefix is the usual cause). Date-range and dynamic filters "
            "(\"this year\") work normally, and querying, grouping and display "
            "are unaffected. --quarter-prefix is NOT subject to this."))

    return findings


def validate_rows(rows: Sequence[Dict[str, object]], *, columns: Sequence[str]) -> List[Finding]:
    """Contract shape plus the structural invariants of a single calendar."""
    findings: List[Finding] = []
    if not rows:
        return [Finding("error", "empty", "Calendar has no rows")]

    expected = list(columns)
    if expected == list(COLUMNS_10):
        findings.append(Finding(
            "warning", "ten-column-not-registrable",
            "This calendar uses the 10-column contract. ThoughtSpot's createCalendar "
            "REJECTS a 10-column table (HTTP 400, INVALID_EXTERNAL_CALENDAR) even when "
            "every column and type is correct — verified live 2026-09-16 against a "
            "10.12+ build, against both a pre-existing and a freshly created table. "
            "Regenerate with --columns 30 before loading and registering; the "
            "10-column file is usable only as an intermediate artifact."))
    for i, row in enumerate(rows):
        if list(row.keys()) != expected:
            findings.append(Finding(
                "error", "column-contract",
                f"Row {i} columns do not match the contract. "
                f"Expected {expected}, got {list(row.keys())}"))
            break

    dates = [r["date"] for r in rows]
    seen = set()
    for d in dates:
        if d in seen:
            findings.append(Finding("error", "duplicate-date", f"Date {d} appears more than once"))
            break
        seen.add(d)

    ordered = sorted(seen)
    for a, b in zip(ordered, ordered[1:]):
        if (b - a) != timedelta(days=1):
            findings.append(Finding(
                "error", "date-gap",
                f"Gap between {a} and {b} — calendars must cover every day in range"))
            break

    for r in rows:
        wn = r.get("week_number_of_year")
        if isinstance(wn, int) and not 1 <= wn <= 53:
            findings.append(Finding(
                "error", "week-number-range",
                f"week_number_of_year {wn} on {r['date']} is outside 1..53"))
            break

    findings.extend(_filter_widget_findings(rows))
    return findings


def _format_signature(value: str) -> str:
    """Reduce a derived label to its shape: digits become '#'."""
    return re.sub(r"\d+", "#", str(value))


def _closed_vocabulary_drift(variant_rows: Dict[str, List[Dict[str, object]]],
                              names: List[str], severity: str) -> List[Finding]:
    """Exact value-set equality per closed-vocabulary column, across variants.

    A fixed set of values (day_of_week, month, quarter) must match exactly —
    any difference is real drift (e.g. AUGUST vs AUG), not a range artifact.
    """
    findings: List[Finding] = []
    for column in CLOSED_VOCABULARY_COLUMNS:
        vocab = {n: {str(r[column]) for r in rows if column in r}
                 for n, rows in variant_rows.items()}
        reference = vocab[names[0]]
        for other in names[1:]:
            if vocab[other] != reference:
                only_a = sorted(reference - vocab[other])
                only_b = sorted(vocab[other] - reference)
                findings.append(Finding(
                    severity, "label-drift",
                    f"Column '{column}' differs between variants '{names[0]}' and "
                    f"'{other}': only in '{names[0]}': {only_a or '-'}; "
                    f"only in '{other}': {only_b or '-'}"))
    return findings


def _derived_label_format_drift(variant_rows: Dict[str, List[Dict[str, object]]],
                                 names: List[str]) -> List[Finding]:
    """Format-signature equality per derived-label column, across variants.

    Values legitimately differ across variants spanning different date ranges
    (year, monthly, quarterly), so only the format shape is comparable, and
    always as a warning.
    """
    findings: List[Finding] = []
    for column in DERIVED_LABEL_COLUMNS:
        sigs = {n: {_format_signature(r[column]) for r in rows if column in r}
                for n, rows in variant_rows.items()}
        reference = sigs[names[0]]
        for other in names[1:]:
            if sigs[other] != reference:
                findings.append(Finding(
                    "warning", "label-format-drift",
                    f"Column '{column}' format differs between variants "
                    f"'{names[0]}' ({sorted(reference)}) and '{other}' ({sorted(sigs[other])})"))
    return findings


def validate_set_labels(variant_rows: Dict[str, List[Dict[str, object]]], *,
                        allow_label_drift: bool = False) -> List[Finding]:
    """Cross-variant label consistency for an RLS calendar set.

    ThoughtSpot indexes a column's values across every row of the registered
    object, but RLS resolves a user to one variant. A set where one variant says
    AUGUST and another says AUG offers both as suggestions while only one can
    ever return rows.

    Two tiers, compared separately (see the helpers): closed vocabularies must
    match exactly (severity depends on ``allow_label_drift``); derived columns
    only need matching formats, and always at warning severity.
    """
    if len(variant_rows) < 2:
        return []

    names = list(variant_rows)
    severity = "warning" if allow_label_drift else "error"

    return (_closed_vocabulary_drift(variant_rows, names, severity)
            + _derived_label_format_drift(variant_rows, names))
