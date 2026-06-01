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
