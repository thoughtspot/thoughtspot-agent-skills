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
from .classifier import (
    aggregate_classification, AggregateInputs, build_matched_columns_map,
    classify_dependent, DependentSignals,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tag_hits(hits: List[dict], object_guid: Optional[str]) -> List[dict]:
    """Attach the owning TML document's GUID to each probe hit.

    The per-identifier `putVariableValues`-style doc-header GUID (confirmed by the
    exportMetadataTML spec: "including the GUID of each object within the headers")
    lets `build_matched_columns_map` attribute a hit back to the specific dependent
    that referenced the column, instead of only an aggregate count. Mutates and
    returns `hits` in place — safe because each hit list is freshly built by the
    tml_probes call immediately before this is applied.
    """
    for hit in hits:
        hit["object_guid"] = object_guid
    return hits


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

    return coverage, warnings


def build_extended_coverage(*, deep_active: bool, probes: dict) -> Tuple[List[CoverageEntry], List[str]]:
    """Coverage rows + warnings for the impact_probes.py probe family.

    `probes` maps a coverage-row type name to a dict with keys `hits` (list),
    `ok` (bool, default True), `error` (str, optional), and `informational`
    (bool, default False). Pure function — no I/O.

    Kept separate from build_coverage() (rather than growing that function's
    signature further) so the original probe family's tests are untouched.
    """
    coverage: List[CoverageEntry] = []
    warnings: List[str] = []
    for type_name, result in probes.items():
        hits = result.get("hits", [])
        ok = result.get("ok", True)
        error = result.get("error")
        checked = deep_active and ok
        reason = None
        if not checked:
            reason = "deep probes only populate for column sources in v1" if not deep_active else \
                "probe failed — see warnings"
        coverage.append(CoverageEntry(
            type=type_name, checked=checked, found=len(hits),
            informational=result.get("informational", False), reason=reason,
        ))
        # skip_warning: this row shares its ok/error flag with a probe family
        # that already emits its own warning elsewhere (e.g. "Model-level
        # filters" and "Formula references" ride the same primary-TML-export
        # probe as the RLS/Joins/AI-surface rows in build_coverage) — without
        # this, one underlying failure would be reported twice.
        if deep_active and not ok and not result.get("skip_warning", False):
            detail = f": {error}" if error else ""
            warnings.append(
                f"{type_name} probe failed{detail}. This coverage row is UNVERIFIED "
                f"(checked=False) — found=0 does NOT mean nothing was found, it means "
                f"the probe could not run."
            )
    return coverage, warnings


class _ProbeState:
    """Mutable accumulator for every probe family's hits + success flags.

    Threaded through the build_report phase functions below rather than
    passed/returned as a growing tuple. Internal to this module — not part of
    the public Report schema.
    """
    def __init__(self):
        self.rls_hits: list = []
        self.csr_hits: list = []
        self.alias_hits: list = []
        self.alert_hits: list = []
        self.join_hits: list = []
        self.ai_hits: list = []
        self.formula_hits: list = []
        self.model_filter_hits: list = []
        self.variable_hits: list = []
        self.memory_hits: list = []
        self.sql_view_hits: list = []
        self.action_hits: list = []
        self.schedule_hits: list = []
        # Cascade hops discovered mid-report (formula columns, SQL views) —
        # merged into `dependents` once all cascade sources have run.
        self.extra_dependent_rows: list = []
        # (doc_guid, parsed_model_dict) for every MODEL-type doc seen in the
        # primary export — consumed by the per-model impact_probes phase.
        self.model_docs: list = []

        # Per-probe success — a failed probe must not read as "verified: no
        # usage found" (2026-07 audit finding this module's docstrings cite).
        self.primary_probe_ok = True
        self.primary_probe_error: Optional[str] = None
        self.monitor_probe_ok = True
        self.monitor_probe_error: Optional[str] = None
        self.csr_probe_ok = True
        self.csr_probe_error: Optional[str] = None
        self.variables_probe_ok = True
        self.variables_probe_error: Optional[str] = None
        self.memory_probe_ok = True
        self.memory_probe_error: Optional[str] = None
        self.sql_view_probe_ok = True
        self.sql_view_probe_error: Optional[str] = None
        self.actions_probe_ok = True
        self.actions_probe_error: Optional[str] = None
        self.schedules_probe_ok = True
        self.schedules_probe_error: Optional[str] = None


def _run_primary_probes(state, client, source, target_cols, physical_column) -> None:
    """Primary TML export: RLS, alias, join, AI-surface, formula, model-filter.

    One export call covers all six — export_associated=True pulls in every
    associated Table/Model/column-alias doc alongside the source itself.
    """
    from . import tml_probes
    import yaml

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
            info = doc.get("info") or {}
            info_type = (info.get("type") or "").upper()
            filename = (info.get("filename") or "").lower()
            doc_guid = info.get("id")
            if "COLUMN_ALIAS" in info_type or "alias" in filename:
                state.alias_hits.extend(_tag_hits(
                    tml_probes.find_alias_column_uses(parsed, target_cols), doc_guid))
            if info_type in ("TABLE", "LOGICAL_TABLE"):
                state.rls_hits.extend(_tag_hits(
                    tml_probes.find_rls_column_uses(parsed, target_cols), doc_guid))
            if info_type in ("MODEL", "LOGICAL_MODEL", "WORKSHEET"):
                state.join_hits.extend(_tag_hits(
                    tml_probes.find_join_column_uses(parsed, target_cols), doc_guid))
                state.ai_hits.extend(_tag_hits(
                    tml_probes.find_ai_surface_uses(parsed, target_cols), doc_guid))
                if physical_column:
                    state.formula_hits.extend(_tag_hits(
                        tml_probes.find_formula_column_uses(parsed, physical_column), doc_guid))
                    state.model_filter_hits.extend(_tag_hits(
                        tml_probes.find_model_filter_column_uses(parsed, target_cols), doc_guid))
                    state.model_docs.append((doc_guid, parsed))
    except Exception as exc:
        state.primary_probe_ok = False
        state.primary_probe_error = str(exc)


def _run_monitor_alert_probe(state, client, dependents, target_cols) -> None:
    """Monitor alerts: batch-export TML for all Liveboard dependents."""
    from . import tml_probes
    import yaml

    lb_guids = [dep.guid for dep in dependents if dep.type == "LIVEBOARD"]
    if not lb_guids:
        return
    try:
        a_resp = client.post("/api/rest/2.0/metadata/tml/export", json={
            "metadata": [{"identifier": g, "type": "LIVEBOARD"} for g in lb_guids],
            "export_associated": True,
            "edoc_format": "YAML",
        })
        for doc in (a_resp.json() or []):
            parsed = yaml.safe_load((doc.get("edoc") or "")) or {}
            if "monitor_alert" in parsed:
                doc_guid = (doc.get("info") or {}).get("id")
                state.alert_hits.extend(_tag_hits(
                    tml_probes.find_alert_column_uses(parsed, target_cols), doc_guid))
    except Exception as exc:
        state.monitor_probe_ok = False
        state.monitor_probe_error = str(exc)


def _run_per_model_probes(state, client, target_cols, physical_column) -> None:
    """Formula/template variables + business terms/AI memory + formula cascade.

    One model at a time, in the same order model_docs was populated — deferred
    to its own phase (after the monitor-alerts export) so call ordering stays
    predictable regardless of how many associated models a source has.
    """
    from . import tml_probes, impact_probes

    for doc_guid, parsed_model in state.model_docs:
        if not doc_guid:
            continue
        try:
            state.variable_hits.extend(
                impact_probes.fetch_formula_variables(client, doc_guid, target_cols))
        except Exception as exc:
            state.variables_probe_ok = False
            state.variables_probe_error = str(exc)
        try:
            state.memory_hits.extend(
                impact_probes.fetch_business_terms_and_ai_memory(client, doc_guid, target_cols))
        except Exception as exc:
            state.memory_probe_ok = False
            state.memory_probe_error = str(exc)
        # Cascade (column_impact.py Pass 3): a formula referencing the dropped
        # physical column is itself a column other Answers/Liveboards may
        # query directly — walk its own dependents too.
        for f in tml_probes.find_formula_column_uses(parsed_model, physical_column):
            try:
                fguid = impact_probes.find_column_guid_by_name(client, f["name"], doc_guid)
                if fguid:
                    state.extra_dependent_rows.extend(
                        impact_probes.walk_one_hop(client, fguid, "LOGICAL_COLUMN", 2))
            except Exception:
                pass  # best-effort cascade; failures don't own a coverage row


def _run_csr_probe(state, client, source, deep_active, physical_column) -> None:
    """Column security rules — needs the owning table's GUID, only available
    when the source resolved with a parent (e.g. a DB.SCH.TBL.COL input)."""
    if not (deep_active and source.parent):
        return
    from . import impact_probes
    try:
        state.csr_hits = impact_probes.fetch_column_security_rules(
            client, source.parent["guid"], physical_column)
    except Exception as exc:
        state.csr_probe_ok = False
        state.csr_probe_error = str(exc)


def _run_sql_view_probe(state, client, deep_active, physical_column) -> None:
    """SQL views — org-wide text scan (most expensive probe here, see
    impact_probes.fetch_sql_view_hits docstring) + their downstream dependents."""
    if not deep_active:
        return
    from . import impact_probes
    try:
        state.sql_view_hits = impact_probes.fetch_sql_view_hits(client, physical_column)
        for v in state.sql_view_hits:
            if not v.get("guid"):
                continue
            try:
                state.extra_dependent_rows.extend(
                    impact_probes.walk_one_hop(client, v["guid"], "LOGICAL_TABLE", 1))
            except Exception:
                pass  # downstream-of-SQL-view walk is best-effort
    except Exception as exc:
        state.sql_view_probe_ok = False
        state.sql_view_probe_error = str(exc)


def _merge_cascade_rows(dependents: list, state, with_deep: bool, physical_column) -> None:
    """Merge formula-column + SQL-view downstream dependents into `dependents`,
    deduped by GUID, before anything counts or classifies dependents."""
    seen_guids = {d.guid for d in dependents}
    for row in state.extra_dependent_rows:
        if row.get("guid") in seen_guids:
            continue
        seen_guids.add(row["guid"])
        entry = row_to_entry(row)
        entry.matched_columns = [physical_column] if with_deep and physical_column else []
        dependents.append(entry)


def _run_custom_actions_and_schedules(state, client, dependents) -> None:
    """Custom actions + scheduled reports — computed from the final dependents list."""
    from . import impact_probes
    try:
        state.action_hits = impact_probes.fetch_custom_actions_for_guids(
            client, [d.guid for d in dependents])
    except Exception as exc:
        state.actions_probe_ok = False
        state.actions_probe_error = str(exc)
    try:
        state.schedule_hits = impact_probes.fetch_scheduled_reports(
            client, [d.guid for d in dependents if d.type == "LIVEBOARD"])
    except Exception as exc:
        state.schedules_probe_ok = False
        state.schedules_probe_error = str(exc)


def _extended_probe_map(state) -> dict:
    """Assemble the `probes` dict build_extended_coverage() expects from a _ProbeState."""
    return {
        "Column security rules (CSR)": {
            "hits": state.csr_hits, "ok": state.csr_probe_ok, "error": state.csr_probe_error},
        "Model-level filters": {
            "hits": state.model_filter_hits, "ok": state.primary_probe_ok,
            "error": state.primary_probe_error, "skip_warning": True},
        "Formula references": {
            "hits": state.formula_hits, "ok": state.primary_probe_ok,
            "error": state.primary_probe_error, "skip_warning": True},
        "Formula / template variables": {
            "hits": state.variable_hits, "ok": state.variables_probe_ok,
            "error": state.variables_probe_error},
        "Business terms / AI memory": {
            "hits": state.memory_hits, "ok": state.memory_probe_ok,
            "error": state.memory_probe_error},
        "SQL views": {
            "hits": state.sql_view_hits, "ok": state.sql_view_probe_ok,
            "error": state.sql_view_probe_error},
        "Custom actions": {
            "hits": state.action_hits, "ok": state.actions_probe_ok,
            "error": state.actions_probe_error},
        "Scheduled reports": {
            "hits": state.schedule_hits, "ok": state.schedules_probe_ok,
            "error": state.schedules_probe_error, "informational": True},
    }


def _classify_all_dependents(dependents: list, state) -> None:
    """Real per-dependent risk classification.

    Previously dead code: every dependent got a hardcoded LOW placeholder from
    walker.row_to_entry, and classify_dependent (despite being fully
    implemented) was never called — see
    agents/cli/ts-convert-from-dbt/references/open-items.md #8. Signals still
    without any backing probe (chart axis use, dormancy, informational-only)
    stay unset; that's a smaller, separately-scoped remaining gap, not
    silently claimed fixed here.
    """
    join_guids = {h["object_guid"] for h in state.join_hits if h.get("object_guid")}
    model_filter_guids = {h["object_guid"] for h in state.model_filter_hits if h.get("object_guid")}
    alert_guids = {h["object_guid"] for h in state.alert_hits if h.get("object_guid")}
    ai_guids = {h["object_guid"] for h in state.ai_hits if h.get("object_guid")}
    for dep in dependents:
        sig = DependentSignals(
            referenced_in_joins=dep.guid in join_guids,
            referenced_in_model_filter=dep.guid in model_filter_guids,
            referenced_in_alerts=dep.guid in alert_guids,
            referenced_in_feedback=(dep.type == "FEEDBACK"),
            referenced_in_ai_surface=dep.guid in ai_guids,
        )
        dep.risk = classify_dependent(dep, sig)


def build_report(source_ref: str, *, profile: str, with_deep: bool = True, max_depth: int = 3) -> dict:
    """Resolve source → walk dependents → (optionally) probe TML → classify → return dict.

    Returns the to_dict() result of a Report. Raises SourceUnresolvedError /
    SourceAmbiguousError if the source ref can't be uniquely resolved.

    The deep-probe phases (RLS/alias/join/AI-surface/formula/model-filter,
    monitor alerts, formula/template variables, business terms/AI memory,
    column security rules, SQL views, custom actions, scheduled reports) were
    ported from a live-tested prototype (api_work/column_impact.py) that found
    this module covered only ~4 of 13 real impact-analysis passes — see
    agents/cli/ts-convert-from-dbt/references/open-items.md #8.
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    source = resolve_source(source_ref, client)

    raw_rows = walk_dependents_recursive(source, client, max_depth=max_depth)
    dependents = [row_to_entry(r) for r in raw_rows]

    # Deep probes filter by column name; for table/model sources there is no
    # single target column, so all probe functions return zero hits. Track
    # whether deep probes were truly active so coverage rows can be honest.
    deep_active = with_deep and source.type == "LOGICAL_COLUMN"
    target_cols = {source.name} if source.type == "LOGICAL_COLUMN" else set()
    physical_column = source.name if target_cols else None

    state = _ProbeState()
    if with_deep:
        _run_primary_probes(state, client, source, target_cols, physical_column)
        _run_monitor_alert_probe(state, client, dependents, target_cols)
        _run_per_model_probes(state, client, target_cols, physical_column)
        _run_csr_probe(state, client, source, deep_active, physical_column)
        _run_sql_view_probe(state, client, deep_active, physical_column)

    _merge_cascade_rows(dependents, state, with_deep, physical_column)

    if deep_active:
        _run_custom_actions_and_schedules(state, client, dependents)

    coverage, probe_warnings = build_coverage(
        dependents,
        rls_hits=state.rls_hits,
        alert_hits=state.alert_hits,
        alias_hits=state.alias_hits,
        join_hits=state.join_hits,
        ai_hits=state.ai_hits,
        deep_active=deep_active,
        primary_probe_ok=state.primary_probe_ok,
        monitor_probe_ok=state.monitor_probe_ok,
        primary_probe_error=state.primary_probe_error,
        monitor_probe_error=state.monitor_probe_error,
    )
    extended_coverage, extended_warnings = build_extended_coverage(
        deep_active=deep_active, probes=_extended_probe_map(state))
    coverage.extend(extended_coverage)
    probe_warnings.extend(extended_warnings)

    # Attribute deep-probe hits back to the specific dependent that referenced the
    # column (see build_matched_columns_map docstring) — fixes the scope-filter bug
    # where ts-dependency-manager's Step 4 tried to match on risk.reason text.
    matched_columns_map = build_matched_columns_map(
        state.rls_hits, state.alert_hits, state.join_hits, state.ai_hits, state.alias_hits,
    )
    for dep in dependents:
        if dep.guid in matched_columns_map:
            dep.matched_columns = matched_columns_map[dep.guid]

    _classify_all_dependents(dependents, state)

    agg = aggregate_classification(AggregateInputs(
        per_dependent_tags=[d.risk for d in dependents],
        rls_hits=state.rls_hits,
        csr_hits=state.csr_hits,
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
