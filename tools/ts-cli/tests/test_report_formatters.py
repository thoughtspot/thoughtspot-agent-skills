# tools/ts-cli/tests/test_report_formatters.py
"""Tests for report.formatters — JSON / text / markdown rendering."""
from __future__ import annotations

import json

from ts_cli.report.formatters import render_json, render_text, render_md
from ts_cli.report.schema import (
    Report, SourceDescriptor, CoverageEntry, Classification, RiskTag,
)


def _mk_report():
    src = SourceDescriptor(input="g-1", guid="g-1", type="LOGICAL_TABLE", name="X", parent=None)
    return Report(
        source=src,
        walked_at="2026-05-28T00:00:00Z",
        profile="test",
        dependents=[],
        coverage=[CoverageEntry(type="Models", checked=True, found=0)],
        classification=Classification(
            per_dependent=[],
            aggregate=RiskTag(tag="SAFE", reason="No dependents"),
            recommendation="SAFE_TO_DROP",
        ),
        warnings=[],
    )


class TestRenderJson:
    def test_valid_json(self):
        out = render_json(_mk_report())
        parsed = json.loads(out)
        assert parsed["schema_version"] == "1.0"
        assert parsed["source"]["guid"] == "g-1"
        assert parsed["classification"]["aggregate"]["tag"] == "SAFE"

    def test_multi_report_wrapper(self):
        out = render_json([_mk_report(), _mk_report()])
        parsed = json.loads(out)
        assert parsed["schema_version"] == "1.0"
        assert len(parsed["reports"]) == 2


class TestRenderText:
    def test_contains_source_name(self):
        out = render_text(_mk_report())
        assert "X" in out

    def test_contains_coverage_section(self):
        out = render_text(_mk_report())
        assert "Coverage" in out or "CHECKED" in out

    def test_contains_recommendation(self):
        out = render_text(_mk_report())
        assert "SAFE_TO_DROP" in out
