"""Unit tests for the Data Objects Health Audit report generator."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from efficiency_report import (
    generate_efficiency_report,
    build_corpus_stats,
    EfficiencyMeta,
    CorpusStats,
    _obj_cell,
)


SAMPLE_MODELS = [
    {
        "model": {
            "name": "GTM Analytics",
            "model_tables": [
                {"fqn": "db.schema.CUSTOMER", "name": "CUSTOMER"},
                {"fqn": "db.schema.ORDERS", "name": "ORDERS"},
                {"fqn": "db.schema.PRODUCT", "name": "PRODUCT"},
            ],
        }
    },
    {
        "model": {
            "name": "Sales Model",
            "model_tables": [
                {"fqn": "db.schema.CUSTOMER", "name": "CUSTOMER"},
                {"fqn": "db.schema.REVENUE", "name": "REVENUE"},
            ],
        }
    },
    {
        "model": {
            "name": "Copy of GTM Analytics",
            "model_tables": [
                {"fqn": "db.schema.CUSTOMER", "name": "CUSTOMER"},
                {"fqn": "db.schema.ORDERS", "name": "ORDERS"},
                {"fqn": "db.schema.PRODUCT", "name": "PRODUCT"},
            ],
        }
    },
]

SAMPLE_FINDINGS = [
    {
        "check_id": "D7", "check_name": "IDENTICAL_MODELS",
        "severity": "HIGH", "title": "Identical models",
        "detail": "GTM Analytics and Copy of GTM Analytics: 100% overlap",
        "score": 1.0,
        "objects": [{"name": "GTM Analytics", "guid": "aaa"}, {"name": "Copy of GTM Analytics", "guid": "bbb"}],
    },
    {
        "check_id": "D7", "check_name": "MODEL_SUBSET",
        "severity": "INFO", "title": "Subset model",
        "detail": "Sales Model is a subset of GTM Analytics",
        "score": 0.67,
        "objects": [{"name": "Sales Model", "guid": "ccc"}, {"name": "GTM Analytics", "guid": "aaa"}],
    },
    {
        "check_id": "D8", "check_name": "DUPLICATE_TABLE",
        "severity": "HIGH", "title": "2 TS objects -> CUSTOMER",
        "detail": "db.schema.CUSTOMER",
        "objects": [{"name": "CUSTOMER", "guid": "t1"}, {"name": "CUSTOMER_v2", "guid": "t2"}],
    },
    {
        "check_id": "D12", "check_name": "CONFORMED_DIM_DIVERGENCE",
        "severity": "MEDIUM", "title": "Divergent classification: Revenue",
        "detail": "ATTRIBUTE in GTM; MEASURE in Sales",
    },
    {
        "check_id": "H10", "check_name": "STALE_OBJECT",
        "severity": "LOW", "title": "Stale LOGICAL_TABLE: Copy of GTM Analytics",
        "detail": "Pattern: copy_of",
        "model_name": "",
        "model_guid": "bbb",
    },
    {
        "check_id": "H10", "check_name": "STALE_COLUMNS",
        "severity": "LOW", "title": "62 zDEL-pattern columns",
        "detail": "zDEL_ prefix: deprecated markers",
        "model_name": "GTM Analytics",
        "model_guid": "aaa",
    },
    {
        "check_id": "H8", "check_name": "FORMULA_PROMOTION",
        "severity": "MEDIUM", "title": "Promote formula: Revenue_YoY",
        "detail": "Used in 3 answers, not in model",
    },
]


class TestBuildCorpusStats:
    def test_table_reuse_shared(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        customer = next(t for t in stats.table_reuse if "CUSTOMER" in t["fqn"])
        assert customer["is_shared"]
        assert customer["count"] == 3

    def test_table_reuse_unique(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        revenue = next(t for t in stats.table_reuse if "REVENUE" in t["fqn"])
        assert not revenue["is_shared"]
        assert revenue["count"] == 1

    def test_duplicate_groups(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert len(stats.duplicate_groups) == 1
        assert stats.duplicate_groups[0]["detail"] == "db.schema.CUSTOMER"

    def test_model_overlaps(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert len(stats.model_overlaps) == 2
        identical = [o for o in stats.model_overlaps if o["check_name"] == "IDENTICAL_MODELS"]
        assert len(identical) == 1

    def test_stale_objects_split(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert len(stats.stale_objects) == 2
        stale_models = [s for s in stats.stale_objects if s["check_name"] == "STALE_OBJECT"]
        stale_cols = [s for s in stats.stale_objects if s["check_name"] == "STALE_COLUMNS"]
        assert len(stale_models) == 1
        assert len(stale_cols) == 1

    def test_dimension_divergence(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert len(stats.dimension_divergence) == 1
        assert "Revenue" in stats.dimension_divergence[0]["title"]

    def test_formula_candidates(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert len(stats.formula_candidates) == 1

    def test_empty_findings(self):
        stats = build_corpus_stats([], SAMPLE_MODELS)
        assert len(stats.duplicate_groups) == 0
        assert len(stats.model_overlaps) == 0
        assert len(stats.table_reuse) == 4

    def test_empty_models(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, [])
        assert len(stats.table_reuse) == 0
        assert len(stats.duplicate_groups) == 1


class TestGenerateReport:
    def test_basic_generation(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "<!DOCTYPE html>" in html
        assert "Data Objects Health Audit" in html

    def test_meta_included(self):
        meta = EfficiencyMeta(
            cluster_url="https://champ-staging.thoughtspot.cloud",
            date="2026-06-18",
            scope="Connection: Snowflake_GTM",
            model_count=3,
        )
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS, meta)
        assert "champ-staging.thoughtspot.cloud" in html
        assert "2026-06-18" in html
        assert "Snowflake_GTM" in html

    def test_tabs_present(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert 'id="tab-overview"' in html
        assert 'id="tab-overlaps"' in html
        assert 'id="tab-duplicates"' in html
        assert 'id="tab-reuse"' in html
        assert 'id="tab-divergence"' in html
        assert 'id="tab-stale"' in html

    def test_stat_cards(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "stat-card" in html
        assert "Identical Model Pairs" in html

    def test_recommendations(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "Consolidate" in html
        assert "Deduplicate" in html

    def test_overlap_shows_models_with_guids(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "GTM Analytics" in html
        assert "Copy of GTM Analytics" in html

    def test_ts_links_when_meta_has_url(self):
        meta = EfficiencyMeta(cluster_url="https://example.thoughtspot.cloud")
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS, meta)
        assert "example.thoughtspot.cloud/#/data/tables/" in html

    def test_stale_split_models_and_columns(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "Stale Models" in html
        assert "Stale Columns" in html

    def test_divergence_shows_type_badges(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "type-badge" in html
        assert "ATTRIBUTE" in html
        assert "MEASURE" in html

    def test_duplicate_cards(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "dup-card" in html
        assert "db.schema.CUSTOMER" in html

    def test_no_external_deps(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert '<link' not in html
        assert 'src="http' not in html

    def test_escaping(self):
        xss_findings = [{
            "check_id": "D7", "check_name": "IDENTICAL_MODELS",
            "severity": "HIGH", "title": "Identical models",
            "detail": '<script>alert("xss")</script>',
            "objects": [{"name": '<img onerror="alert(1)">'}, {"name": "B"}],
        }]
        html = generate_efficiency_report(xss_findings, SAMPLE_MODELS)
        assert '<script>alert("xss")</script>' not in html
        assert "&lt;script&gt;" in html

    def test_empty_findings_renders(self):
        html = generate_efficiency_report([], SAMPLE_MODELS)
        assert "<!DOCTYPE html>" in html
        assert "None found" in html or "No efficiency issues" in html

    def test_js_embedded(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "function showTab" in html
        assert "function filterTable" in html

    def test_css_embedded(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert ".stat-card" in html
        assert ".data-table" in html

    def test_dependencies_tab_present(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert 'id="tab-dependencies"' in html
        assert 'data-tab="dependencies"' in html

    def test_dependencies_bar_charts(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "Tables per Model" in html
        assert "<svg" in html
        assert "<rect" in html

    def test_dependencies_model_detail_table(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "dep-model-table" in html
        assert "GTM Analytics" in html
        assert "Sales Model" in html

    def test_dependencies_model_deps_computed(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert len(stats.model_deps) == 3
        gtm = next(d for d in stats.model_deps if d["name"] == "GTM Analytics")
        assert gtm["table_count"] == 3
        sales = next(d for d in stats.model_deps if d["name"] == "Sales Model")
        assert sales["table_count"] == 2

    def test_dependencies_table_deps_computed(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        customer = next(d for d in stats.table_deps if "CUSTOMER" in d["fqn"])
        assert customer["model_count"] == 3

    def test_dependencies_shared_table_detail(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "dep-table-table" in html
        assert "Shared Table Detail" in html

    def test_sub_tabs_present(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert "sub-tab-bar" in html
        assert "showSubTab" in html

    def test_dependencies_sub_tabs(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert 'data-subtab="dep-model-chart"' in html
        assert 'data-subtab="dep-table-chart"' in html
        assert 'data-subtab="dep-model-detail"' in html
        assert 'data-subtab="dep-table-detail"' in html

    def test_sankey_present(self):
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS)
        assert 'data-subtab="reuse-sankey"' in html
        assert "sankey-flow" in html
        assert "TABLES" in html

    def test_sankey_labels_have_guids(self):
        meta = EfficiencyMeta(cluster_url="https://example.thoughtspot.cloud")
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS, meta)
        assert "sankey-label" in html

    def test_obj_cell_with_guid_and_url(self):
        cell = _obj_cell("MyModel", "abcd1234-5678", "https://ts.cloud", "model")
        assert "MyModel" in cell
        assert "abcd1234" in cell
        assert "ts.cloud/#/data/tables/abcd1234-5678" in cell

    def test_obj_cell_no_guid(self):
        cell = _obj_cell("MyModel", "", "https://ts.cloud", "model")
        assert "MyModel" in cell
        assert "guid" not in cell

    def test_obj_cell_no_base_url(self):
        cell = _obj_cell("MyModel", "abcd1234-5678", "", "model")
        assert "MyModel" in cell
        assert "<a " not in cell

    def test_reuse_rows_have_guids_and_links(self):
        meta = EfficiencyMeta(cluster_url="https://example.thoughtspot.cloud")
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS, meta)
        assert "example.thoughtspot.cloud/#/data/tables/" in html

    def test_table_reuse_has_table_guid(self):
        stats = build_corpus_stats(SAMPLE_FINDINGS, SAMPLE_MODELS)
        customer = next(t for t in stats.table_reuse if "CUSTOMER" in t["fqn"])
        assert "table_guid" in customer
        assert "model_guids" in customer

    def test_duplicate_tables_show_model_links(self):
        meta = EfficiencyMeta(cluster_url="https://example.thoughtspot.cloud")
        html = generate_efficiency_report(SAMPLE_FINDINGS, SAMPLE_MODELS, meta)
        assert "dup-card" in html
