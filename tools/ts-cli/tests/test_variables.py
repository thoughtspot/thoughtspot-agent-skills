"""Unit tests for `ts variables` (2026-07 audit findings 13.1, 14.2, 6.4).

Covers:
  - _build_variable_assignments / _build_variable_update_payload — the pure
    scope-expansion + request-body logic previously duplicated verbatim between
    set_value and remove_value (finding 6.4), now migrated to the per-identifier
    update-values endpoint (finding 13.1).
  - CLI-level wiring: `ts variables set` / `remove` post to the per-identifier
    URL with the new body shape; `ts variables search` auto-paginates to
    exhaustion instead of hard-capping at one 50-row page (finding 14.2).

No live ThoughtSpot connection anywhere — ThoughtSpotClient is mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.commands.variables import (
    _build_variable_assignments,
    _build_variable_update_payload,
)

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()


def _all_output(result):
    try:
        return (result.stdout or "") + (result.stderr or "")
    except ValueError:
        return result.output or ""


# ---------------------------------------------------------------------------
# _build_variable_assignments — org x user scope expansion
# ---------------------------------------------------------------------------

class TestBuildVariableAssignments:
    def test_single_org_no_user_is_org_level(self):
        assignments = _build_variable_assignments("UTC", ["Primary"], [])
        assert assignments == [{"assigned_values": ["UTC"], "org_identifier": "Primary"}]

    def test_multiple_orgs_no_user_one_entry_per_org(self):
        assignments = _build_variable_assignments("UTC", ["Primary", "Sales"], [])
        assert len(assignments) == 2
        assert {a["org_identifier"] for a in assignments} == {"Primary", "Sales"}
        assert all(a["assigned_values"] == ["UTC"] for a in assignments)
        assert all("principal_type" not in a for a in assignments)

    def test_single_org_single_user_is_user_level(self):
        assignments = _build_variable_assignments("America/New_York", ["Primary"], ["alice@x.com"])
        assert assignments == [{
            "assigned_values": ["America/New_York"],
            "org_identifier": "Primary",
            "principal_type": "USER",
            "principal_identifier": "alice@x.com",
        }]

    def test_one_org_two_users_yields_two_entries(self):
        assignments = _build_variable_assignments("UTC", ["Primary"], ["a@x.com", "b@x.com"])
        assert len(assignments) == 2
        assert {a["principal_identifier"] for a in assignments} == {"a@x.com", "b@x.com"}
        assert all(a["org_identifier"] == "Primary" for a in assignments)
        assert all(a["principal_type"] == "USER" for a in assignments)

    def test_two_orgs_two_users_is_cross_product(self):
        assignments = _build_variable_assignments("UTC", ["Primary", "Sales"], ["a@x.com", "b@x.com"])
        assert len(assignments) == 4  # 2 orgs x 2 users
        pairs = {(a["org_identifier"], a["principal_identifier"]) for a in assignments}
        assert pairs == {
            ("Primary", "a@x.com"), ("Primary", "b@x.com"),
            ("Sales", "a@x.com"), ("Sales", "b@x.com"),
        }

    def test_every_entry_carries_the_same_value(self):
        assignments = _build_variable_assignments("Asia/Kolkata", ["A", "B"], ["u1", "u2"])
        assert all(a["assigned_values"] == ["Asia/Kolkata"] for a in assignments)


# ---------------------------------------------------------------------------
# _build_variable_update_payload — REPLACE/REMOVE body shape
# ---------------------------------------------------------------------------

class TestBuildVariableUpdatePayload:
    def test_replace_operation_top_level(self):
        payload = _build_variable_update_payload("UTC", ["Primary"], [], operation="REPLACE")
        assert payload["operation"] == "REPLACE"
        assert payload["variable_assignment"] == [
            {"assigned_values": ["UTC"], "org_identifier": "Primary"}
        ]

    def test_remove_operation_top_level(self):
        payload = _build_variable_update_payload("UTC", ["Primary"], [], operation="REMOVE")
        assert payload["operation"] == "REMOVE"

    def test_payload_has_no_legacy_batch_fields(self):
        """The deprecated batch endpoint's body used variable_identifier /
        variable_values / a separate variable_value_scope list — none of that
        shape should survive the migration to the per-identifier endpoint."""
        payload = _build_variable_update_payload("UTC", ["Primary"], ["alice"], operation="REPLACE")
        assert "variable_identifier" not in payload
        assert "variable_values" not in payload
        assert "variable_value_scope" not in payload
        assert set(payload.keys()) == {"operation", "variable_assignment"}

    def test_only_two_top_level_keys(self):
        payload = _build_variable_update_payload("UTC", ["Primary"], [], operation="RESET")
        assert set(payload.keys()) == {"operation", "variable_assignment"}


# ---------------------------------------------------------------------------
# CLI wiring — `ts variables set` / `remove` hit the per-identifier URL
# ---------------------------------------------------------------------------

class TestSetRemoveCliWiring:
    @patch("ts_cli.commands.variables.ThoughtSpotClient")
    @patch("ts_cli.commands.variables.resolve_profile", return_value="test")
    def test_set_posts_to_per_identifier_url(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            app, ["variables", "set", "ts_user_timezone", "Pacific/Honolulu", "--org", "Primary"],
        )

        assert result.exit_code == 0, _all_output(result)
        path = mock_client.post.call_args[0][0]
        assert path == "/api/rest/2.0/template/variables/ts_user_timezone/update-values"
        body = mock_client.post.call_args.kwargs["json"]
        assert body["operation"] == "REPLACE"
        assert body["variable_assignment"] == [
            {"assigned_values": ["Pacific/Honolulu"], "org_identifier": "Primary"}
        ]

    @patch("ts_cli.commands.variables.ThoughtSpotClient")
    @patch("ts_cli.commands.variables.resolve_profile", return_value="test")
    def test_remove_posts_to_per_identifier_url(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            app, ["variables", "remove", "ts_user_timezone", "Pacific/Honolulu", "--org", "Primary"],
        )

        assert result.exit_code == 0, _all_output(result)
        path = mock_client.post.call_args[0][0]
        assert path == "/api/rest/2.0/template/variables/ts_user_timezone/update-values"
        body = mock_client.post.call_args.kwargs["json"]
        assert body["operation"] == "REMOVE"

    @patch("ts_cli.commands.variables.ThoughtSpotClient")
    @patch("ts_cli.commands.variables.resolve_profile", return_value="test")
    def test_identifier_with_special_chars_is_url_quoted(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            app, ["variables", "set", "my timezone", "UTC", "--org", "Primary"],
        )

        assert result.exit_code == 0, _all_output(result)
        path = mock_client.post.call_args[0][0]
        assert path == "/api/rest/2.0/template/variables/my%20timezone/update-values"


# ---------------------------------------------------------------------------
# `ts variables search` — auto-pagination to exhaustion (finding 14.2)
# ---------------------------------------------------------------------------

class TestSearchAutoPagination:
    @patch("ts_cli.commands.variables.ThoughtSpotClient")
    @patch("ts_cli.commands.variables.resolve_profile", return_value="test")
    def test_single_short_page_stops_after_one_call(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [{"id": "v1"}, {"id": "v2"}]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["variables", "search"])

        assert result.exit_code == 0, _all_output(result)
        assert mock_client.post.call_count == 1

    @patch("ts_cli.commands.variables.ThoughtSpotClient")
    @patch("ts_cli.commands.variables.resolve_profile", return_value="test")
    def test_full_page_triggers_a_second_call(self, mock_resolve, mock_client_cls):
        """A page exactly at the internal page_size (50) must trigger one more
        request to confirm there isn't a 51st row — the exact truncation bug
        class the ts-audit 2.4.0 false-orphan incident hit."""
        mock_client = MagicMock()
        full_page = [{"id": f"v{i}"} for i in range(50)]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: full_page),
            MagicMock(json=lambda: []),
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["variables", "search"])

        assert result.exit_code == 0, _all_output(result)
        assert mock_client.post.call_count == 2

    @patch("ts_cli.commands.variables.ThoughtSpotClient")
    @patch("ts_cli.commands.variables.resolve_profile", return_value="test")
    def test_results_across_pages_are_concatenated(self, mock_resolve, mock_client_cls):
        import json as _json

        mock_client = MagicMock()
        page1 = [{"id": f"v{i}"} for i in range(50)]
        page2 = [{"id": "v50"}]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: page1),
            MagicMock(json=lambda: page2),
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["variables", "search"])

        assert result.exit_code == 0, _all_output(result)
        out = _json.loads(result.stdout)
        assert len(out) == 51

    @patch("ts_cli.commands.variables.ThoughtSpotClient")
    @patch("ts_cli.commands.variables.resolve_profile", return_value="test")
    def test_offset_advances_by_page_size_each_call(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        full_page = [{"id": f"v{i}"} for i in range(50)]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: full_page),
            MagicMock(json=lambda: []),
        ]
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["variables", "search"])

        offsets = [c.kwargs["json"]["record_offset"] for c in mock_client.post.call_args_list]
        assert offsets == [0, 50]

    @patch("ts_cli.commands.variables.ThoughtSpotClient")
    @patch("ts_cli.commands.variables.resolve_profile", return_value="test")
    def test_identifier_argument_included_in_payload(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = []
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["variables", "search", "ts_user_timezone"])

        body = mock_client.post.call_args.kwargs["json"]
        assert body["variable_details"] == [{"identifier": "ts_user_timezone"}]
