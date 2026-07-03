"""Unit tests for `ts orgs search` (2026-07 audit finding 14.2).

Previously hard-capped at --limit 200 with no pagination loop. Full-result
auto-pagination is now the default; --limit opts back into the legacy
single-page behavior. No live ThoughtSpot connection — the client is mocked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()


def _all_output(result):
    try:
        return (result.stdout or "") + (result.stderr or "")
    except ValueError:
        return result.output or ""


class TestOrgsSearchAutoPagination:
    @patch("ts_cli.commands.orgs.ThoughtSpotClient")
    @patch("ts_cli.commands.orgs.resolve_profile", return_value="test")
    def test_short_page_stops_after_one_call(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [{"orgId": 1}]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["orgs", "search"])

        assert result.exit_code == 0, _all_output(result)
        assert mock_client.post.call_count == 1

    @patch("ts_cli.commands.orgs.ThoughtSpotClient")
    @patch("ts_cli.commands.orgs.resolve_profile", return_value="test")
    def test_full_page_of_50_triggers_a_second_call(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        full_page = [{"orgId": i} for i in range(50)]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: full_page),
            MagicMock(json=lambda: []),
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["orgs", "search"])

        assert result.exit_code == 0, _all_output(result)
        assert mock_client.post.call_count == 2

    @patch("ts_cli.commands.orgs.ThoughtSpotClient")
    @patch("ts_cli.commands.orgs.resolve_profile", return_value="test")
    def test_results_concatenated_across_pages(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        page1 = [{"orgId": i} for i in range(50)]
        page2 = [{"orgId": 50}]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: page1),
            MagicMock(json=lambda: page2),
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["orgs", "search"])
        out = json.loads(result.stdout)
        assert len(out) == 51

    @patch("ts_cli.commands.orgs.ThoughtSpotClient")
    @patch("ts_cli.commands.orgs.resolve_profile", return_value="test")
    def test_offset_advances_by_page_size(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        full_page = [{"orgId": i} for i in range(50)]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: full_page),
            MagicMock(json=lambda: []),
        ]
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["orgs", "search"])

        offsets = [c.kwargs["json"]["record_offset"] for c in mock_client.post.call_args_list]
        assert offsets == [0, 50]

    @patch("ts_cli.commands.orgs.ThoughtSpotClient")
    @patch("ts_cli.commands.orgs.resolve_profile", return_value="test")
    def test_explicit_limit_makes_one_call(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = []
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["orgs", "search", "--limit", "5"])

        assert mock_client.post.call_count == 1
        body = mock_client.post.call_args.kwargs["json"]
        assert body["record_size"] == 5

    @patch("ts_cli.commands.orgs.ThoughtSpotClient")
    @patch("ts_cli.commands.orgs.resolve_profile", return_value="test")
    def test_status_and_name_filters_in_payload(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = []
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["orgs", "search", "--status", "ACTIVE", "--name", "%sales%"])

        body = mock_client.post.call_args.kwargs["json"]
        assert body["status"] == "ACTIVE"
        assert body["name_pattern"] == "%sales%"
