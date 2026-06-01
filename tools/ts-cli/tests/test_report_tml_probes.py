# tools/ts-cli/tests/test_report_tml_probes.py
"""Tests for report.tml_probes — TML inspection helpers."""
from __future__ import annotations

import pytest

from ts_cli.report.tml_probes import find_rls_column_uses


class TestFindRlsColumnUses:
    def test_finds_column_in_rule_expr(self):
        table_tml = {
            "table": {
                "rls_rules": {
                    "table_paths": [{"id": "T_1", "table": "T", "column": ["ZIPCODE"]}],
                    "rules": [{"name": "geo", "expr": "[T_1::ZIPCODE] = ts_groups_int"}],
                }
            }
        }
        hits = find_rls_column_uses(table_tml, {"ZIPCODE"})
        assert len(hits) == 1
        assert hits[0]["rule_name"] == "geo"
        assert hits[0]["column"] == "ZIPCODE"

    def test_no_rls_block_returns_empty(self):
        table_tml = {"table": {"name": "T"}}
        hits = find_rls_column_uses(table_tml, {"ZIPCODE"})
        assert hits == []

    def test_column_not_referenced_returns_empty(self):
        table_tml = {
            "table": {
                "rls_rules": {
                    "table_paths": [{"id": "T_1", "table": "T", "column": ["NAME"]}],
                    "rules": [{"name": "x", "expr": "[T_1::NAME] != ''"}],
                }
            }
        }
        hits = find_rls_column_uses(table_tml, {"ZIPCODE"})
        assert hits == []


from ts_cli.report.tml_probes import find_alert_column_uses


class TestFindAlertColumnUses:
    def test_finds_alert_filtering_on_column(self):
        alert_tml = {
            "monitor_alert": [{
                "guid": "a-1", "name": "Alert 1",
                "metric_id": {"pinboard_viz_id": {"viz_id": "v-1"}},
                "personalised_view_info": {
                    "filters": [
                        {"column": ["TEST_MODEL::Customer Zipcode"]},
                        {"column": ["TEST_MODEL::Other Column"]},
                    ]
                }
            }]
        }
        hits = find_alert_column_uses(alert_tml, {"Customer Zipcode"}, source_model_name="TEST_MODEL")
        assert len(hits) == 1
        assert hits[0]["alert_guid"] == "a-1"
        assert hits[0]["column"] == "Customer Zipcode"

    def test_ignores_alerts_on_other_models(self):
        alert_tml = {
            "monitor_alert": [{
                "guid": "a-1", "name": "Alert 1",
                "metric_id": {"pinboard_viz_id": {"viz_id": "v-1"}},
                "personalised_view_info": {
                    "filters": [{"column": ["OTHER_MODEL::Customer Zipcode"]}]
                }
            }]
        }
        hits = find_alert_column_uses(alert_tml, {"Customer Zipcode"}, source_model_name="TEST_MODEL")
        assert hits == []

    def test_empty_alert_tml(self):
        hits = find_alert_column_uses({}, {"X"}, source_model_name=None)
        assert hits == []
