# tools/ts-cli/tests/test_report_impact_probes.py
"""Tests for report.impact_probes — the network-calling dependency-impact probes.

Ported from a live-tested prototype (api_work/column_impact.py) per
agents/cli/ts-convert-from-dbt/references/open-items.md #8. All ThoughtSpotClient
calls are mocked — these are unit tests, not live-instance tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from ts_cli.report import impact_probes


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    return r


class TestFetchColumnSecurityRules:
    def test_matches_column_by_name(self):
        client = MagicMock()
        client.post.return_value = _resp([{
            "table_guid": "t-1",
            "column_security_rules": [
                {"column": {"name": "franchiseID", "id": "col-1"},
                 "groups": [{"name": "Sales"}, {"name": "Ops"}]},
                {"column": {"name": "other", "id": "col-2"}, "groups": []},
            ],
        }])
        hits = impact_probes.fetch_column_security_rules(client, "t-1", "franchiseID")
        assert len(hits) == 1
        assert hits[0]["groups"] == ["Sales", "Ops"]

    def test_no_matching_rules(self):
        client = MagicMock()
        client.post.return_value = _resp([{"table_guid": "t-1", "column_security_rules": []}])
        assert impact_probes.fetch_column_security_rules(client, "t-1", "franchiseID") == []


class TestFetchFormulaVariables:
    def test_matches_variable_by_value(self):
        client = MagicMock()
        client.post.return_value = _resp([
            {"name": "region_var", "id": "v-1", "values": [{"value": "[franchiseID] = 1"}]},
            {"name": "other_var", "id": "v-2", "values": [{"value": "[other] = 2"}]},
        ])
        hits = impact_probes.fetch_formula_variables(client, "m-1", {"franchiseID"})
        assert len(hits) == 1
        assert hits[0]["name"] == "region_var"

    def test_matches_variable_by_own_name(self):
        client = MagicMock()
        client.post.return_value = _resp([{"name": "franchiseID_filter", "id": "v-1", "values": []}])
        hits = impact_probes.fetch_formula_variables(client, "m-1", {"franchiseID"})
        assert len(hits) == 1

    def test_no_matches(self):
        client = MagicMock()
        client.post.return_value = _resp([{"name": "other", "id": "v-1", "values": []}])
        assert impact_probes.fetch_formula_variables(client, "m-1", {"franchiseID"}) == []


class TestFetchBusinessTermsAndAiMemory:
    def test_matches_business_term(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp([{"edoc": (
                "nls_feedback:\n"
                "  feedback:\n"
                "    - type: BUSINESS_TERM\n"
                "      feedback_phrase: franchise count\n"
                "      search_tokens: '[Franchise id]'\n"
            )}]),
            _resp({"content": "memories: []\n"}),
        ]
        hits = impact_probes.fetch_business_terms_and_ai_memory(client, "m-1", ["Franchise id"])
        assert len(hits) == 1
        assert hits[0]["source"] == "business_term"

    def test_matches_ai_memory_recipe(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp([{"edoc": "nls_feedback:\n  feedback: []\n"}]),
            _resp({"content": (
                "memories:\n"
                "  - type: RULE\n"
                "    content:\n"
                "      rule_definition: 'always group by Franchise id'\n"
            )}),
        ]
        hits = impact_probes.fetch_business_terms_and_ai_memory(client, "m-1", ["Franchise id"])
        assert len(hits) == 1
        assert hits[0]["source"] == "ai_memory"

    def test_no_matches(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp([{"edoc": "nls_feedback:\n  feedback: []\n"}]),
            _resp({"content": "memories: []\n"}),
        ]
        assert impact_probes.fetch_business_terms_and_ai_memory(client, "m-1", ["Franchise id"]) == []

    def test_empty_feedback_response_does_not_crash(self):
        client = MagicMock()
        client.post.side_effect = [_resp([]), _resp({})]
        assert impact_probes.fetch_business_terms_and_ai_memory(client, "m-1", ["X"]) == []


class TestFetchSqlViewHits:
    def test_finds_matching_sql_view(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp([{"metadata_id": "sv-1", "metadata_header": {"subType": "SQL_VIEW"}}]),
            _resp([{"edoc": '{"guid": "sv-1", "sql_view": {"name": "V", "sql_query": "SELECT franchiseID FROM t"}}'}]),
        ]
        hits = impact_probes.fetch_sql_view_hits(client, "franchiseID")
        assert len(hits) == 1
        assert hits[0]["guid"] == "sv-1"

    def test_no_sql_views_short_circuits_without_export_call(self):
        client = MagicMock()
        client.post.return_value = _resp([])
        hits = impact_probes.fetch_sql_view_hits(client, "franchiseID")
        assert hits == []
        assert client.post.call_count == 1  # only the search page — no TML export batch


class TestFetchCustomActionsForGuids:
    def test_global_action_always_matches(self):
        client = MagicMock()
        client.post.return_value = _resp([
            {"id": "a-1", "name": "Global Action",
             "default_action_config": {"visibility": True}, "metadata_association": []},
        ])
        hits = impact_probes.fetch_custom_actions_for_guids(client, {"g-1"})
        assert len(hits) == 1
        assert hits[0]["is_global"] is True

    def test_scoped_action_matches_by_guid(self):
        client = MagicMock()
        client.post.return_value = _resp([
            {"id": "a-1", "name": "Scoped Action",
             "default_action_config": {"visibility": False},
             "metadata_association": [{"identifier": "g-1"}]},
        ])
        hits = impact_probes.fetch_custom_actions_for_guids(client, {"g-1"})
        assert len(hits) == 1
        assert hits[0]["matched_guids"] == ["g-1"]

    def test_unrelated_action_does_not_match(self):
        client = MagicMock()
        client.post.return_value = _resp([
            {"id": "a-1", "name": "Other",
             "default_action_config": {"visibility": False},
             "metadata_association": [{"identifier": "g-99"}]},
        ])
        assert impact_probes.fetch_custom_actions_for_guids(client, {"g-1"}) == []


class TestFetchScheduledReports:
    def test_returns_schedules_for_liveboards(self):
        client = MagicMock()
        client.post.return_value = _resp([
            {"id": "s-1", "name": "Weekly", "status": "ACTIVE", "metadata": {"name": "LB"}},
        ])
        hits = impact_probes.fetch_scheduled_reports(client, ["lb-1"])
        assert len(hits) == 1
        assert hits[0]["liveboard"] == "LB"

    def test_empty_guids_short_circuits(self):
        client = MagicMock()
        hits = impact_probes.fetch_scheduled_reports(client, [])
        assert hits == []
        client.post.assert_not_called()


class TestFindColumnGuidByName:
    def test_matches_by_owner(self):
        client = MagicMock()
        client.post.return_value = _resp([
            {"metadata_id": "col-1", "metadata_header": {"owner": "m-1"}},
            {"metadata_id": "col-2", "metadata_header": {"owner": "m-2"}},
        ])
        assert impact_probes.find_column_guid_by_name(client, "X", "m-1") == "col-1"

    def test_no_match_returns_none(self):
        client = MagicMock()
        client.post.return_value = _resp([{"metadata_id": "col-1", "metadata_header": {"owner": "m-2"}}])
        assert impact_probes.find_column_guid_by_name(client, "X", "m-1") is None


class TestWalkOneHop:
    def test_tags_hops_on_each_row(self):
        client = MagicMock()
        client.post.return_value = _resp([{
            "metadata_id": "g-1",
            "dependent_objects": {"dependents": {"g-1": {
                "QUESTION_ANSWER_BOOK": [{"id": "ans-1", "name": "A"}],
            }}},
        }])
        rows = impact_probes.walk_one_hop(client, "g-1", "LOGICAL_COLUMN", 2)
        assert len(rows) == 1
        assert rows[0]["hops"] == 2
        assert rows[0]["guid"] == "ans-1"
