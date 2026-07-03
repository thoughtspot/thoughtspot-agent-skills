"""Unit tests for `ts auth whoami/token/logout` (2026-07 audit finding 6.4).

Zero prior coverage despite backing every skill's credential-verification step.
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


class TestWhoami:
    @patch("ts_cli.commands.auth.ThoughtSpotClient")
    @patch("ts_cli.commands.auth.resolve_profile", return_value="test")
    def test_calls_session_user_endpoint(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.get.return_value.json.return_value = {"name": "alice"}
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["auth", "whoami"])

        assert result.exit_code == 0, _all_output(result)
        mock_client.get.assert_called_once_with("/api/rest/2.0/auth/session/user")

    @patch("ts_cli.commands.auth.ThoughtSpotClient")
    @patch("ts_cli.commands.auth.resolve_profile", return_value="test")
    def test_prints_the_response_json(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.get.return_value.json.return_value = {"name": "alice", "id": "u-1"}
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["auth", "whoami"])

        out = json.loads(result.stdout)
        assert out == {"name": "alice", "id": "u-1"}

    @patch("ts_cli.commands.auth.ThoughtSpotClient")
    @patch("ts_cli.commands.auth.resolve_profile")
    def test_resolves_the_given_profile(self, mock_resolve, mock_client_cls):
        mock_resolve.return_value = "My Staging"
        mock_client = MagicMock()
        mock_client.get.return_value.json.return_value = {}
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["auth", "whoami", "--profile", "My Staging"])

        mock_resolve.assert_called_once_with("My Staging")
        mock_client_cls.assert_called_once_with("My Staging")


class TestToken:
    @patch("ts_cli.commands.auth.ThoughtSpotClient")
    @patch("ts_cli.commands.auth.resolve_profile", return_value="test")
    def test_prints_the_raw_token(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.get_token.return_value = "abc-token-123"
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["auth", "token"])

        assert result.exit_code == 0, _all_output(result)
        assert result.stdout.strip() == "abc-token-123"


class TestLogout:
    @patch("ts_cli.commands.auth.ThoughtSpotClient")
    @patch("ts_cli.commands.auth.resolve_profile", return_value="Production")
    def test_reports_cleared_when_cache_existed(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.clear_token_cache.return_value = True
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["auth", "logout"])

        assert result.exit_code == 0, _all_output(result)
        assert "cleared" in _all_output(result).lower()
        assert "Production" in _all_output(result)

    @patch("ts_cli.commands.auth.ThoughtSpotClient")
    @patch("ts_cli.commands.auth.resolve_profile", return_value="Production")
    def test_reports_nothing_to_clear_when_no_cache(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.clear_token_cache.return_value = False
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["auth", "logout"])

        assert result.exit_code == 0, _all_output(result)
        assert "no cached token" in _all_output(result).lower()

    @patch("ts_cli.commands.auth.ThoughtSpotClient")
    @patch("ts_cli.commands.auth.resolve_profile", return_value="Production")
    def test_calls_clear_token_cache_exactly_once(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        mock_client.clear_token_cache.return_value = True
        mock_client_cls.return_value = mock_client

        runner.invoke(app, ["auth", "logout"])

        mock_client.clear_token_cache.assert_called_once_with()
