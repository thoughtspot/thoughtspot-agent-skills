"""ts_cli.report.classifier — risk tag + recommendation rules.

Pure functions; consume walker/tml_probes outputs and produce RiskTag values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .schema import DependentEntry, RiskTag


@dataclass
class DependentSignals:
    """Signals collected per-dependent during walking and probing."""
    chart_axis_use: List[str] = field(default_factory=list)        # subset of {"x","y","color","size","shape"}
    referenced_in_joins: bool = False
    referenced_in_model_filter: bool = False
    referenced_in_alerts: bool = False
    referenced_in_feedback: bool = False
    referenced_in_ai_surface: bool = False                          # DMI, synonyms
    is_dormant: bool = False                                        # modified_at older than threshold
    is_informational_only: bool = False                             # alias, ACL — no behavioral impact


def classify_dependent(dep: DependentEntry, sig: DependentSignals) -> RiskTag:
    """Compute a RiskTag for one dependent from its signals.

    Note: STOP is handled at the aggregate level via separate RLS / CSR
    findings on the source, not per-dependent.
    """
    if "x" in sig.chart_axis_use or "y" in sig.chart_axis_use:
        return RiskTag(tag="HIGH", reason="chart uses source column on x/y axis")
    if sig.referenced_in_joins:
        return RiskTag(tag="HIGH", reason="referenced in a join condition")
    if sig.referenced_in_model_filter:
        return RiskTag(tag="HIGH", reason="referenced in a model-level filter")
    if any(a in sig.chart_axis_use for a in ("color", "size", "shape")):
        return RiskTag(tag="MEDIUM", reason="chart uses source column on color/size/shape")
    if sig.referenced_in_alerts:
        return RiskTag(tag="MEDIUM", reason="alert filter references source column")
    if sig.referenced_in_feedback:
        return RiskTag(tag="MEDIUM", reason="Spotter feedback references source column")
    if sig.referenced_in_ai_surface:
        return RiskTag(tag="MEDIUM", reason="referenced in Spotter AI surface area")
    if sig.is_dormant or sig.is_informational_only:
        return RiskTag(tag="LOW", reason="dormant or informational only")
    return RiskTag(tag="LOW", reason="no high-risk signals")


_TAG_ORDER = {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "STOP": 4}

_TAG_TO_RECOMMENDATION = {
    "SAFE":   "SAFE_TO_DROP",
    "LOW":    "REVIEW_RECOMMENDED",
    "MEDIUM": "PLAN_REQUIRED",
    "HIGH":   "PLAN_REQUIRED_WITH_PER_VIZ_DECISIONS",
    "STOP":   "BLOCKED_RESOLVE_RLS_FIRST",
}


@dataclass
class AggregateInputs:
    per_dependent_tags: List[RiskTag] = field(default_factory=list)
    rls_hits: List[dict] = field(default_factory=list)
    csr_hits: List[dict] = field(default_factory=list)


@dataclass
class AggregateResult:
    aggregate: RiskTag
    recommendation: str


def aggregate_classification(inp: AggregateInputs) -> AggregateResult:
    """Compute the top-level aggregate tag + recommendation."""
    # STOP wins outright if either RLS or CSR are present.
    if inp.rls_hits or inp.csr_hits:
        reasons = []
        if inp.rls_hits:
            reasons.append(f"{len(inp.rls_hits)} RLS rule(s) reference source column")
        if inp.csr_hits:
            reasons.append(f"{len(inp.csr_hits)} CSR rule(s) reference source column")
        return AggregateResult(
            aggregate=RiskTag(tag="STOP", reason="; ".join(reasons)),
            recommendation="BLOCKED_RESOLVE_RLS_FIRST",
        )
    if not inp.per_dependent_tags:
        return AggregateResult(
            aggregate=RiskTag(tag="SAFE", reason="No dependents found"),
            recommendation="SAFE_TO_DROP",
        )
    max_tag = max(inp.per_dependent_tags, key=lambda t: _TAG_ORDER.get(t.tag, 0))
    return AggregateResult(
        aggregate=RiskTag(tag=max_tag.tag, reason=max_tag.reason),
        recommendation=_TAG_TO_RECOMMENDATION[max_tag.tag],
    )


def build_matched_columns_map(*hit_lists: List[dict]) -> Dict[str, List[str]]:
    """Map an object's GUID to the sorted column names the deep TML probes matched for it.

    2026-07 audit fix (dependency-manager column-scope filter bug): every
    ``reason`` string produced by ``classify_dependent`` above is a fixed literal
    that never names a column, so a filter like "keep dependents whose
    ``risk.reason`` references the column name" (ts-dependency-manager SKILL.md
    Step 4) can never match. This function gives callers a field that actually
    carries the matched column name(s).

    Each hit list is one of the probe families from ``ts_cli.report.tml_probes``
    (rls/join/ai/alias hits) or the Monitor-alerts probe — all tagged by the
    caller (``ts_cli.report.build_report``) with an ``object_guid`` key holding
    the GUID of the TML document the hit was found in (the dependent that
    referenced the column), alongside the ``column`` key every probe function
    already returns. Hits missing either key are skipped defensively (e.g. an
    RLS hit against the source table itself, which is not a "dependent").

    Pure function — no I/O — so it is fully unit-testable without a live probe.
    """
    mapping: Dict[str, set] = {}
    for hits in hit_lists:
        for hit in hits:
            guid = hit.get("object_guid")
            column = hit.get("column")
            if not guid or not column:
                continue
            mapping.setdefault(guid, set()).add(column)
    return {guid: sorted(cols) for guid, cols in mapping.items()}
