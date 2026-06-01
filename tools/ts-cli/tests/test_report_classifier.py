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
