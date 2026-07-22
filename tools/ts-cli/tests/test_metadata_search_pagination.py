"""Unit tests for `ts metadata search` auto-pagination (2026-07 audit finding 14.2).

Before this fix, the command was single-page unless --all was passed — the
same truncation class that caused the ts-audit 2.4.0 false-orphan bug. Now the
full result set is the default; --limit opts back into the legacy single-page
behavior, and --all is a no-op kept only for backward compatibility.

No live ThoughtSpot connection — ThoughtSpotClient is mocked.
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


class TestDefaultIsFullAutoPagination:
    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_short_page_stops_after_one_call(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [{"id": "t1"}, {"id": "t2"}]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search"])

        assert result.exit_code == 0, _all_output(result)
        assert mock_client.post.call_count == 1

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_full_page_triggers_a_second_call(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        full_page = [{"id": f"t{i}"} for i in range(500)]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: full_page),
            MagicMock(json=lambda: []),
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search"])

        assert result.exit_code == 0, _all_output(result)
        assert mock_client.post.call_count == 2

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_results_from_all_pages_are_concatenated(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        page1 = [{"id": f"t{i}"} for i in range(500)]
        page2 = [{"id": "t500"}, {"id": "t501"}]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: page1),
            MagicMock(json=lambda: page2),
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search"])

        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert len(out) == 502

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_offset_advances_by_page_size(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        full_page = [{"id": f"t{i}"} for i in range(500)]
        mock_client.post.side_effect = [
            MagicMock(json=lambda: full_page),
            MagicMock(json=lambda: []),
        ]
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["metadata", "search"])

        offsets = [c.kwargs["json"]["record_offset"] for c in mock_client.post.call_args_list]
        assert offsets == [0, 500]

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_all_flag_is_still_accepted_and_still_returns_full_set(self, mock_resolve, mock_client_cls):
        """--all is now a documented no-op — passing it must not error or change
        the (already-full) result set."""
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [{"id": "t1"}]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search", "--all"])

        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert out == [{"id": "t1"}]


class TestExplicitLimitPreservesLegacySinglePage:
    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_explicit_limit_makes_exactly_one_call(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        full_page = [{"id": f"t{i}"} for i in range(10)]
        mock_client.post.return_value.json.return_value = full_page
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search", "--limit", "10"])

        assert result.exit_code == 0, _all_output(result)
        assert mock_client.post.call_count == 1

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_explicit_limit_sends_the_given_record_size(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = []
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["metadata", "search", "--limit", "5", "--offset", "20"])

        body = mock_client.post.call_args.kwargs["json"]
        assert body["record_size"] == 5
        assert body["record_offset"] == 20

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_explicit_limit_returns_raw_response_not_a_list_wrapper(self, mock_resolve, mock_client_cls):
        """Legacy single-page mode prints resp.json() verbatim (whatever shape
        the API returns), unlike the auto-paginate branch which always emits a
        flat list."""
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = {"metadata": [{"id": "t1"}]}
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search", "--limit", "50"])

        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert out == {"metadata": [{"id": "t1"}]}

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_limit_wins_even_with_all_flag(self, mock_resolve, mock_client_cls):
        """An explicit --limit always means single-page, regardless of --all."""
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [{"id": "t1"}]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search", "--limit", "1", "--all"])

        assert result.exit_code == 0, _all_output(result)
        assert mock_client.post.call_count == 1
