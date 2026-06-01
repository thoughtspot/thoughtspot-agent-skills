"""ts_cli.report — public entry points.

build_report(source_ref) → single-source report dict (schema_version 1.0)
build_reports([refs])    → multi-source wrapper {"reports": [...]}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from ts_cli.client import ThoughtSpotClient, resolve_profile
from .schema import (
    Report, CoverageEntry, Classification, RiskTag, SCHEMA_VERSION,
)
from .resolver import resolve_source, SourceUnresolvedError, SourceAmbiguousError
from .walker import walk_dependents_recursive, row_to_entry
from .classifier import aggregate_classification, AggregateInputs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_report(source_ref: str, *, profile: str, with_deep: bool = True, max_depth: int = 3) -> dict:
    """Resolve source → walk dependents → (optionally) probe TML → classify → return dict.

    Returns the to_dict() result of a Report. Raises SourceUnresolvedError /
    SourceAmbiguousError if the source ref can't be uniquely resolved.
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    source = resolve_source(source_ref, client)

    raw_rows = walk_dependents_recursive(source, client, max_depth=max_depth)
    dependents = [row_to_entry(r) for r in raw_rows]

    # TML probes (RLS, alerts, aliases, joins, AI surface) — added in Task G2.
    # For now, with_deep=True is identical to with_deep=False until G2 lands.
    rls_hits: list = []
    csr_hits: list = []

    coverage = [
        CoverageEntry(type="Models / Views / Tables", checked=True,
                      found=sum(1 for d in dependents if d.type == "LOGICAL_TABLE")),
        CoverageEntry(type="Answers", checked=True,
                      found=sum(1 for d in dependents if d.type == "ANSWER")),
        CoverageEntry(type="Liveboards", checked=True,
                      found=sum(1 for d in dependents if d.type == "LIVEBOARD")),
        CoverageEntry(type="Sets / Cohorts", checked=True,
                      found=sum(1 for d in dependents if d.type == "SET")),
        CoverageEntry(type="Spotter feedback", checked=True,
                      found=sum(1 for d in dependents if d.type == "FEEDBACK")),
    ]

    agg = aggregate_classification(AggregateInputs(
        per_dependent_tags=[d.risk for d in dependents],
        rls_hits=rls_hits,
        csr_hits=csr_hits,
    ))
    classification = Classification(
        per_dependent=dependents,
        aggregate=agg.aggregate,
        recommendation=agg.recommendation,
    )

    report = Report(
        source=source,
        walked_at=_now_iso(),
        profile=profile,
        dependents=dependents,
        coverage=coverage,
        classification=classification,
        warnings=[],
    )
    return report.to_dict()


def build_reports(source_refs: List[str], *, profile: str, with_deep: bool = True, max_depth: int = 3) -> dict:
    """Multi-source: returns the {"reports": [...]} wrapper."""
    reports = []
    for ref in source_refs:
        try:
            reports.append(build_report(ref, profile=profile, with_deep=with_deep, max_depth=max_depth))
        except (SourceUnresolvedError, SourceAmbiguousError) as e:
            reports.append({
                "schema_version": SCHEMA_VERSION,
                "source": {"input": ref, "guid": None, "type": None, "name": None, "parent": None},
                "error": str(e),
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "walked_at": _now_iso(),
        "reports": reports,
    }
