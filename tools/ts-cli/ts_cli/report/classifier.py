"""ts_cli.report.classifier — risk tag + recommendation rules.

Pure functions; consume walker/tml_probes outputs and produce RiskTag values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

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
