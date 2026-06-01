# tools/ts-cli/tests/test_report_classifier.py
"""Tests for report.classifier — risk tags and aggregate recommendation."""
from __future__ import annotations

from ts_cli.report.classifier import (
    classify_dependent,
    DependentSignals,
)
from ts_cli.report.schema import DependentEntry, Owner, RiskTag


def _dep(guid="g", type_="LOGICAL_TABLE", hops=1):
    return DependentEntry(
        guid=guid, name="x", type=type_, subtype=None,
        via="v2_dependents", hops=hops,
        owner=Owner(id="u", display_name="U"),
        modified_at="2026-01-01T00:00:00Z",
        risk=RiskTag(tag="LOW", reason="placeholder"),
    )


class TestClassifyDependent:
    def test_chart_on_x_axis_is_high(self):
        sig = DependentSignals(chart_axis_use=["y"])
        tag = classify_dependent(_dep(), sig)
        assert tag.tag == "HIGH"
        assert "axis" in tag.reason.lower()

    def test_chart_on_color_is_medium(self):
        sig = DependentSignals(chart_axis_use=["color"])
        tag = classify_dependent(_dep(), sig)
        assert tag.tag == "MEDIUM"

    def test_join_reference_is_high(self):
        sig = DependentSignals(referenced_in_joins=True)
        tag = classify_dependent(_dep(), sig)
        assert tag.tag == "HIGH"

    def test_dormant_only_is_low(self):
        sig = DependentSignals(is_dormant=True)
        tag = classify_dependent(_dep(), sig)
        assert tag.tag == "LOW"

    def test_no_signals_default_is_low(self):
        tag = classify_dependent(_dep(), DependentSignals())
        assert tag.tag == "LOW"


from ts_cli.report.classifier import aggregate_classification, AggregateInputs


class TestAggregateClassification:
    def test_all_safe(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[],
            rls_hits=[],
            csr_hits=[],
        ))
        assert agg.aggregate.tag == "SAFE"
        assert agg.recommendation == "SAFE_TO_DROP"

    def test_any_low(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[RiskTag(tag="LOW", reason="x")],
            rls_hits=[], csr_hits=[],
        ))
        assert agg.aggregate.tag == "LOW"
        assert agg.recommendation == "REVIEW_RECOMMENDED"

    def test_medium_promotes(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[RiskTag(tag="LOW", reason="x"), RiskTag(tag="MEDIUM", reason="y")],
            rls_hits=[], csr_hits=[],
        ))
        assert agg.aggregate.tag == "MEDIUM"
        assert agg.recommendation == "PLAN_REQUIRED"

    def test_high_promotes(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[RiskTag(tag="HIGH", reason="x")],
            rls_hits=[], csr_hits=[],
        ))
        assert agg.aggregate.tag == "HIGH"
        assert agg.recommendation == "PLAN_REQUIRED_WITH_PER_VIZ_DECISIONS"

    def test_rls_makes_stop(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[RiskTag(tag="LOW", reason="x")],
            rls_hits=[{"rule_name": "geo"}],
            csr_hits=[],
        ))
        assert agg.aggregate.tag == "STOP"
        assert agg.recommendation == "BLOCKED_RESOLVE_RLS_FIRST"

    def test_csr_makes_stop(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[],
            rls_hits=[],
            csr_hits=[{"column": "X"}],
        ))
        assert agg.aggregate.tag == "STOP"
        assert agg.recommendation == "BLOCKED_RESOLVE_RLS_FIRST"
