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

    # TML probes (RLS, alerts, aliases, joins, AI surface).
    rls_hits: list = []
    csr_hits: list = []
    alias_hits: list = []
    alert_hits: list = []
    join_hits: list = []
    ai_hits: list = []
    alias_supported = True

    # Deep probes filter by column name; for table/model sources there is no
    # single target column, so all probe functions return zero hits.  Track
    # whether deep probes were truly active so coverage rows can be honest.
    deep_active = with_deep and source.type == "LOGICAL_COLUMN"

    if with_deep:
        from . import tml_probes
        import yaml

        # Determine target columns for probe filtering.
        target_cols = {source.name} if source.type == "LOGICAL_COLUMN" else set()

        # Export source TML with the column-alias beta flag (10.13.0+).
        # The response contains model, table, and column_alias docs in one call.
        # RLS, joins, and AI-surface uses are parsed from those same docs.
        try:
            resp = client.post("/api/rest/2.0/metadata/tml/export", json={
                "metadata": [{"identifier": source.guid, "type": source.type}],
                "export_associated": True,
                "export_fqn": True,
                "edoc_format": "YAML",
                "export_options": {"export_with_column_aliases": True},
            })
            for doc in (resp.json() or []):
                edoc_str = doc.get("edoc") or ""
                if not edoc_str:
                    continue
                parsed = yaml.safe_load(edoc_str) or {}
                info_type = ((doc.get("info") or {}).get("type") or "").upper()
                filename = ((doc.get("info") or {}).get("filename") or "").lower()
                if "COLUMN_ALIAS" in info_type or "alias" in filename:
                    alias_hits.extend(tml_probes.find_alias_column_uses(parsed, target_cols))
                if info_type in ("TABLE", "LOGICAL_TABLE"):
                    rls_hits.extend(tml_probes.find_rls_column_uses(parsed, target_cols))
                if info_type in ("MODEL", "LOGICAL_MODEL", "WORKSHEET"):
                    join_hits.extend(tml_probes.find_join_column_uses(parsed, target_cols))
                    ai_hits.extend(tml_probes.find_ai_surface_uses(parsed, target_cols))
        except Exception:
            alias_supported = False

        # Monitor alerts: export TML for each Liveboard dependent.
        for dep in dependents:
            if dep.type != "LIVEBOARD":
                continue
            try:
                a_resp = client.post("/api/rest/2.0/metadata/tml/export", json={
                    "metadata": [{"identifier": dep.guid, "type": "LIVEBOARD"}],
                    "export_associated": True,
                    "edoc_format": "YAML",
                })
                for doc in (a_resp.json() or []):
                    parsed = yaml.safe_load((doc.get("edoc") or "")) or {}
                    if "monitor_alert" in parsed:
                        alert_hits.extend(tml_probes.find_alert_column_uses(parsed, target_cols))
            except Exception:
                pass

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
        CoverageEntry(type="RLS rules", checked=deep_active, found=len(rls_hits),
                      reason=(None if deep_active
                              else "deep probes only populate for column sources in v1")),
        CoverageEntry(type="Monitor alerts", checked=deep_active, found=len(alert_hits),
                      reason=(None if deep_active
                              else "deep probes only populate for column sources in v1")),
        CoverageEntry(
            type="Column alias TML",
            checked=deep_active and alias_supported,
            found=len(alias_hits),
            reason=(None if (deep_active and alias_supported)
                    else ("requires --with-deep + cluster build 10.13.0+" if deep_active
                          else "deep probes only populate for column sources in v1")),
        ),
        CoverageEntry(type="Joins", checked=deep_active, found=len(join_hits),
                      reason=(None if deep_active
                              else "deep probes only populate for column sources in v1")),
        CoverageEntry(type="Spotter AI surface area", checked=deep_active, found=len(ai_hits),
                      reason=(None if deep_active
                              else "deep probes only populate for column sources in v1")),
        CoverageEntry(type="Column-level sharing (ACLs)", checked=False, found=0,
                      informational=True, reason="not implemented in v1"),
        CoverageEntry(type="CSR (column_security_rules)", checked=False, found=0,
                      reason="deferred — cluster feature gate (open-item #9)"),
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
