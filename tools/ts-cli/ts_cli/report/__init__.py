"""ts_cli.report — public entry points.

build_report(source_ref) → single-source report dict (schema_version 1.0)
build_reports([refs])    → multi-source wrapper {"reports": [...]}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from ts_cli.client import ThoughtSpotClient, resolve_profile
from .schema import (
    Report, CoverageEntry, Classification, RiskTag, SCHEMA_VERSION,
)
from .resolver import resolve_source, SourceUnresolvedError, SourceAmbiguousError
from .walker import walk_dependents_recursive, row_to_entry
from .classifier import aggregate_classification, AggregateInputs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _probe_reason(checked: bool, deep_active: bool) -> Optional[str]:
    """Reason string for a deep-probe-derived coverage row that isn't checked.

    Two distinct causes collapse into one row-level flag (`checked=False`) but need
    different explanations: the probe never ran at all for non-column sources
    (`deep_active=False`), vs. the probe ran but raised (`deep_active=True` — the
    detail then lives in the report's `warnings` list, not repeated per-row).
    """
    if checked:
        return None
    if not deep_active:
        return "deep probes only populate for column sources in v1"
    return "TML probe failed — see warnings"


def _dependent_type_counts(dependents: list) -> dict:
    """Count dependents by type once, for the static (always-checked) coverage rows."""
    counts: dict = {}
    for d in dependents:
        counts[d.type] = counts.get(d.type, 0) + 1
    return counts


def _static_coverage_rows(dependents: list) -> List[CoverageEntry]:
    """Coverage rows with no probe dependency — always checked=True."""
    counts = _dependent_type_counts(dependents)
    return [
        CoverageEntry(type="Models / Views / Tables", checked=True, found=counts.get("LOGICAL_TABLE", 0)),
        CoverageEntry(type="Answers", checked=True, found=counts.get("ANSWER", 0)),
        CoverageEntry(type="Liveboards", checked=True, found=counts.get("LIVEBOARD", 0)),
        CoverageEntry(type="Sets / Cohorts", checked=True, found=counts.get("SET", 0)),
        CoverageEntry(type="Spotter feedback", checked=True, found=counts.get("FEEDBACK", 0)),
    ]


def _deep_probe_coverage_rows(
    *,
    rls_hits: list,
    alert_hits: list,
    alias_hits: list,
    join_hits: list,
    ai_hits: list,
    deep_active: bool,
    primary_probe_ok: bool,
    monitor_probe_ok: bool,
) -> List[CoverageEntry]:
    """Coverage rows fed by the two deep-probe families.

    RLS rules / Joins / Spotter AI surface area / Column alias TML all come from the
    "primary" TML export/parse; Monitor alerts comes from the separate Liveboard TML
    export. A row is only checked=True when BOTH deep_active (the probe applies to
    this source type) AND its backing probe's success flag are true.
    """
    primary_checked = deep_active and primary_probe_ok
    alerts_checked = deep_active and monitor_probe_ok
    return [
        CoverageEntry(type="RLS rules", checked=primary_checked, found=len(rls_hits),
                      reason=_probe_reason(primary_checked, deep_active)),
        CoverageEntry(type="Monitor alerts", checked=alerts_checked, found=len(alert_hits),
                      reason=_probe_reason(alerts_checked, deep_active)),
        CoverageEntry(type="Column alias TML", checked=primary_checked, found=len(alias_hits),
                      reason=_probe_reason(primary_checked, deep_active)),
        CoverageEntry(type="Joins", checked=primary_checked, found=len(join_hits),
                      reason=_probe_reason(primary_checked, deep_active)),
        CoverageEntry(type="Spotter AI surface area", checked=primary_checked, found=len(ai_hits),
                      reason=_probe_reason(primary_checked, deep_active)),
    ]


def _probe_failure_warnings(
    *,
    deep_active: bool,
    primary_probe_ok: bool,
    monitor_probe_ok: bool,
    primary_probe_error: Optional[str],
    monitor_probe_error: Optional[str],
) -> List[str]:
    """Human-readable warnings for each deep-probe family that raised.

    This is the fix for the "probe failure reads as verified absence" defect: a deep
    probe exception must not leave its coverage row(s) silently reporting
    `checked=True, found=0` (which ts-dependency-manager reads as "verified: no
    RLS/alert usage" and uses to green-light destructive removals).
    """
    warnings: List[str] = []
    if deep_active and not primary_probe_ok:
        detail = f": {primary_probe_error}" if primary_probe_error else ""
        warnings.append(
            f"TML probe failed{detail}. Coverage rows for RLS rules, Joins, "
            "Spotter AI surface area, and Column alias TML are UNVERIFIED "
            "(checked=False) — found=0 does NOT mean no usage was found, it means "
            "the probe could not run."
        )
    if deep_active and not monitor_probe_ok:
        detail = f": {monitor_probe_error}" if monitor_probe_error else ""
        warnings.append(
            f"Monitor-alert TML probe failed{detail}. The 'Monitor alerts' coverage "
            "row is UNVERIFIED (checked=False) — found=0 does NOT mean no alerts "
            "were found, it means the probe could not run."
        )
    return warnings


def build_coverage(
    dependents: list,
    *,
    rls_hits: list,
    alert_hits: list,
    alias_hits: list,
    join_hits: list,
    ai_hits: list,
    deep_active: bool,
    primary_probe_ok: bool,
    monitor_probe_ok: bool,
    primary_probe_error: Optional[str] = None,
    monitor_probe_error: Optional[str] = None,
) -> Tuple[List[CoverageEntry], List[str]]:
    """Build coverage rows + warnings from probe results and per-probe success flags.

    Pure function — no I/O, no network. See _deep_probe_coverage_rows and
    _probe_failure_warnings for the two probe families (primary TML export vs. the
    separate Monitor-alerts Liveboard export) and how a failure of either propagates.
    """
    warnings = _probe_failure_warnings(
        deep_active=deep_active,
        primary_probe_ok=primary_probe_ok,
        monitor_probe_ok=monitor_probe_ok,
        primary_probe_error=primary_probe_error,
        monitor_probe_error=monitor_probe_error,
    )

    coverage = _static_coverage_rows(dependents)
    coverage.extend(_deep_probe_coverage_rows(
        rls_hits=rls_hits,
        alert_hits=alert_hits,
        alias_hits=alias_hits,
        join_hits=join_hits,
        ai_hits=ai_hits,
        deep_active=deep_active,
        primary_probe_ok=primary_probe_ok,
        monitor_probe_ok=monitor_probe_ok,
    ))
    coverage.append(CoverageEntry(type="Column-level sharing (ACLs)", checked=False, found=0,
                                   informational=True, reason="not implemented in v1"))
    coverage.append(CoverageEntry(type="CSR (column_security_rules)", checked=False, found=0,
                                   reason="deferred — cluster feature gate (open-item #9)"))

    return coverage, warnings


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

    # Per-probe success — a failed probe must not read as "verified: no usage found".
    primary_probe_ok = True
    primary_probe_error: Optional[str] = None
    monitor_probe_ok = True
    monitor_probe_error: Optional[str] = None

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
        except Exception as exc:
            primary_probe_ok = False
            primary_probe_error = str(exc)

        # Monitor alerts: batch-export TML for all Liveboard dependents.
        lb_guids = [dep.guid for dep in dependents if dep.type == "LIVEBOARD"]
        if lb_guids:
            try:
                a_resp = client.post("/api/rest/2.0/metadata/tml/export", json={
                    "metadata": [{"identifier": g, "type": "LIVEBOARD"} for g in lb_guids],
                    "export_associated": True,
                    "edoc_format": "YAML",
                })
                for doc in (a_resp.json() or []):
                    parsed = yaml.safe_load((doc.get("edoc") or "")) or {}
                    if "monitor_alert" in parsed:
                        alert_hits.extend(tml_probes.find_alert_column_uses(parsed, target_cols))
            except Exception as exc:
                monitor_probe_ok = False
                monitor_probe_error = str(exc)

    coverage, probe_warnings = build_coverage(
        dependents,
        rls_hits=rls_hits,
        alert_hits=alert_hits,
        alias_hits=alias_hits,
        join_hits=join_hits,
        ai_hits=ai_hits,
        deep_active=deep_active,
        primary_probe_ok=primary_probe_ok,
        monitor_probe_ok=monitor_probe_ok,
        primary_probe_error=primary_probe_error,
        monitor_probe_error=monitor_probe_error,
    )

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
        warnings=probe_warnings,
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
