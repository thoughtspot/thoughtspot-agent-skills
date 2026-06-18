"""Unit tests for the HTML report generator."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from report import generate_html_report, ReportMeta, _worst_severity, _model_stats


SAMPLE_FINDINGS = [
    {
        "angle": "A", "check_id": "A1", "check_name": "DESC_COVERAGE",
        "severity": "HIGH", "title": "Low description coverage",
        "detail": "12% coverage", "model_name": "GTM", "score": 0.12,
    },
    {
        "angle": "D", "check_id": "D1", "check_name": "COMPLEXITY_TABLES",
        "severity": "HIGH", "title": "79 tables",
        "detail": "Exceeds threshold", "model_name": "GTM", "score": 79,
    },
    {
        "angle": "S", "check_id": "S1", "check_name": "PII_DETECTED",
        "severity": "INFO", "title": "PII: email",
        "detail": "Heuristic", "model_name": "Sales",
    },
    {
        "angle": "A", "check_id": "A4", "check_name": "MODEL_DESCRIPTION",
        "severity": "MEDIUM", "title": "No model description",
        "detail": "", "model_name": "Sales",
    },
]


class TestHelpers:
    def test_worst_severity_mixed(self):
        assert _worst_severity(["INFO", "HIGH", "LOW"]) == "HIGH"

    def test_worst_severity_critical(self):
        assert _worst_severity(["MEDIUM", "CRITICAL"]) == "CRITICAL"

    def test_worst_severity_empty(self):
        assert _worst_severity([]) == "GREEN"

    def test_model_stats(self):
        stats = _model_stats(SAMPLE_FINDINGS, "GTM")
        assert stats["count"] == 2
        assert stats["by_angle"]["A"] == "HIGH"
        assert stats["by_angle"]["D"] == "HIGH"
        assert stats["worst"] == "HIGH"

    def test_model_stats_not_found(self):
        stats = _model_stats(SAMPLE_FINDINGS, "Nonexistent")
        assert stats["count"] == 0
        assert stats["worst"] == "GREEN"


class TestGenerateReport:
    def test_basic_generation(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert "<!DOCTYPE html>" in html
        assert "GTM" in html
        assert "Sales" in html
        assert "Semantic Layer Health Audit" in html

    def test_with_meta(self):
        meta = ReportMeta(
            profile_name="champ-staging",
            cluster_url="https://champ-staging.thoughtspot.cloud",
            date="2026-06-18",
            audit_profile="Spotter-ready",
            scope="Connection: Snowflake_Prod",
            model_count=2,
        )
        html = generate_html_report(SAMPLE_FINDINGS, meta)
        assert "champ-staging.thoughtspot.cloud" in html
        assert "2026-06-18" in html
        assert "Spotter-ready" in html
        assert "Snowflake_Prod" in html

    def test_views_present(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'id="view-heatmap"' in html
        assert 'id="view-model"' in html
        assert 'id="view-checks"' in html

    def test_sidebar_present(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'id="sidebar"' in html
        assert "sidebar-model" in html

    def test_severity_badges(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert "sev-badge" in html

    def test_model_cards(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'data-model="GTM"' in html
        assert 'data-model="Sales"' in html

    def test_check_summary(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert "Checks Overview" in html
        assert "summary-table" in html
        assert "summary-bar" in html

    def test_check_tables(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'id="check-A1"' in html
        assert 'id="check-D1"' in html

    def test_js_embedded(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert "function showView" in html
        assert "function showModel" in html
        assert "function filterHeatmap" in html

    def test_css_embedded(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert ".heatmap-table" in html
        assert ".model-card" in html

    def test_empty_findings(self):
        html = generate_html_report([])
        assert "<!DOCTYPE html>" in html
        assert "Findings:</span> 0" in html

    def test_no_external_deps(self):
        html = generate_html_report(SAMPLE_FINDINGS)
        assert '<link' not in html
        assert 'src="http' not in html

    def test_escaping(self):
        xss_findings = [{
            "angle": "A", "check_id": "A1", "check_name": "TEST",
            "severity": "HIGH", "title": '<script>alert("xss")</script>',
            "detail": "", "model_name": "Model<br>",
        }]
        html = generate_html_report(xss_findings)
        assert '<script>alert("xss")</script>' not in html
        assert "&lt;script&gt;" in html
