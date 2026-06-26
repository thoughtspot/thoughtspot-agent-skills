"""Unit tests for the HTML report generator."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from report import generate_html_report, ReportMeta, _worst_severity, _model_stats, _disambiguate_model_names, CHECK_DESCRIPTIONS


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

    def test_check_descriptions_present(self):
        """Each check section in the detail view has a description paragraph."""
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'class="check-desc"' in html
        assert "Spotter" in html  # A1 description mentions Spotter

    def test_disambiguate_same_name_models(self):
        """Same-name models with different GUIDs get numbered suffixes."""
        findings = [
            {"angle": "D", "check_id": "D3", "check_name": "OUTER_JOIN",
             "severity": "HIGH", "title": "FULL OUTER join: A → B",
             "detail": "Performance risk", "model_name": "GTM", "model_guid": "g1"},
            {"angle": "D", "check_id": "D3", "check_name": "OUTER_JOIN",
             "severity": "HIGH", "title": "FULL OUTER join: A → B",
             "detail": "Performance risk", "model_name": "GTM", "model_guid": "g2"},
            {"angle": "D", "check_id": "D3", "check_name": "OUTER_JOIN",
             "severity": "HIGH", "title": "FULL OUTER join: C → D",
             "detail": "Performance risk", "model_name": "Sales", "model_guid": "s1"},
        ]
        result = _disambiguate_model_names(findings)
        gtm_names = sorted(set(r["model_name"] for r in result if "GTM" in r["model_name"]))
        assert gtm_names == ["GTM #1", "GTM #2"]
        sales = [r for r in result if r["model_name"] == "Sales"]
        assert len(sales) == 1

    def test_disambiguate_no_collision(self):
        """Unique model names are unchanged."""
        findings = [
            {"angle": "A", "check_id": "A1", "check_name": "DESC",
             "severity": "HIGH", "title": "Low", "detail": "",
             "model_name": "GTM", "model_guid": "g1"},
            {"angle": "A", "check_id": "A1", "check_name": "DESC",
             "severity": "HIGH", "title": "Low", "detail": "",
             "model_name": "Sales", "model_guid": "s1"},
        ]
        result = _disambiguate_model_names(findings)
        names = sorted(r["model_name"] for r in result)
        assert names == ["GTM", "Sales"]

    def test_disambiguate_separate_model_cards(self):
        """Disambiguated models produce separate model cards and distinct rows."""
        findings = [
            {"angle": "A", "check_id": "A1", "check_name": "DESC",
             "severity": "HIGH", "title": "Low coverage",
             "detail": "12%", "model_name": "GTM", "model_guid": "g1"},
            {"angle": "A", "check_id": "A1", "check_name": "DESC",
             "severity": "HIGH", "title": "Low coverage",
             "detail": "12%", "model_name": "GTM", "model_guid": "g2"},
        ]
        html = generate_html_report(findings)
        assert "GTM #1" in html
        assert "GTM #2" in html
        assert html.count('<tr data-sev="HIGH"') == 2
        assert 'data-model="GTM #1"' in html
        assert 'data-model="GTM #2"' in html

    def test_summary_shows_all_checks(self):
        """Summary table includes rows for every check in CHECK_DESCRIPTIONS, not just those with findings."""
        html = generate_html_report(SAMPLE_FINDINGS)
        for cid in CHECK_DESCRIPTIONS:
            assert f'>{cid}</td>' in html, f"Missing summary row for {cid}"

    def test_summary_zero_findings_row(self):
        """Checks with zero findings show GREEN severity and 0 count."""
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'data-sev="GREEN" data-count="0"' in html

    def test_summary_has_descriptions(self):
        """Summary table contains the description column."""
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'class="summary-desc"' in html
        assert "Spotter" in html

    def test_summary_filter_controls(self):
        """Summary has angle, severity, and issues-only filter controls."""
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'id="summary-angle-filter"' in html
        assert 'id="summary-sev-filter"' in html
        assert 'id="summary-issues-only"' in html

    def test_sidebar_summary_link(self):
        """Sidebar contains a link to the checks summary."""
        html = generate_html_report(SAMPLE_FINDINGS)
        assert 'id="nav-summary"' in html
        assert "Checks Summary" in html

    def test_summary_filter_js(self):
        """JS functions for summary filtering are embedded."""
        html = generate_html_report(SAMPLE_FINDINGS)
        assert "function filterSummaryTable" in html
        assert "function scrollToSummary" in html
