"""Unit tests for the `ts metadata search --connection` client-side filter (BL-111).

The metadata/search API has no server-side connection filter, so connection
scoping is done client-side on `metadata_header.dataSourceName` (the verified
field — see .claude/rules/ts-cli.md). `filter_by_connection` is a pure function
covering the match logic; the CLI tests confirm it is wired into both the
auto-paginate and legacy `--limit` output branches.

No live ThoughtSpot connection — ThoughtSpotClient is mocked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.commands.metadata import filter_by_connection

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()


def _all_output(result):
    try:
        return (result.stdout or "") + (result.stderr or "")
    except ValueError:
        return result.output or ""


def _item(name, ds=None):
    """A search result with an optional dataSourceName in its header."""
    header = {"name": name}
    if ds is not None:
        header["dataSourceName"] = ds
    return {"metadata_id": name, "metadata_name": name, "metadata_header": header}


class TestFilterByConnectionPure:
    def test_none_connection_returns_input_unchanged(self):
        items = [_item("a", "Conn1"), _item("b", "Conn2")]
        assert filter_by_connection(items, None) is items

    def test_empty_connection_returns_input_unchanged(self):
        items = [_item("a", "Conn1")]
        assert filter_by_connection(items, "") is items

    def test_exact_match_keeps_only_that_connection(self):
        items = [_item("a", "Snowflake Prod"), _item("b", "Databricks"), _item("c", "Snowflake Prod")]
        out = filter_by_connection(items, "Snowflake Prod")
        assert [r["metadata_id"] for r in out] == ["a", "c"]

    def test_match_is_case_insensitive(self):
        items = [_item("a", "Snowflake Prod")]
        assert len(filter_by_connection(items, "snowflake prod")) == 1
        assert len(filter_by_connection(items, "SNOWFLAKE PROD")) == 1

    def test_surrounding_whitespace_on_query_is_ignored(self):
        items = [_item("a", "Snowflake Prod")]
        assert len(filter_by_connection(items, "  Snowflake Prod  ")) == 1

    def test_objects_without_datasource_are_excluded(self):
        # Worksheets/models carry no dataSourceName — never match a connection filter.
        items = [_item("ws", None), _item("tbl", "Conn1")]
        out = filter_by_connection(items, "Conn1")
        assert [r["metadata_id"] for r in out] == ["tbl"]

    def test_falls_back_to_top_level_datasource_when_no_header(self):
        # Mirrors tables.py: header = r.get("metadata_header") or r.
        flat = {"metadata_id": "x", "dataSourceName": "Conn1"}
        assert filter_by_connection([flat], "Conn1") == [flat]

    def test_no_match_returns_empty_list(self):
        items = [_item("a", "Conn1")]
        assert filter_by_connection(items, "Nonexistent") == []


class TestSearchCliWiring:
    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_connection_filter_applied_to_autopaginated_results(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        page = [_item("a", "Snowflake Prod"), _item("b", "Databricks")]
        mock_client.post.return_value.json.return_value = page
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search", "--connection", "Snowflake Prod"])

        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert [r["metadata_id"] for r in out] == ["a"]

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_connection_filter_applied_to_legacy_limit_branch(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        page = [_item("a", "Snowflake Prod"), _item("b", "Databricks")]
        mock_client.post.return_value.json.return_value = page
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            app, ["metadata", "search", "--limit", "10", "--connection", "Databricks"]
        )

        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert [r["metadata_id"] for r in out] == ["b"]

    @patch("ts_cli.commands.metadata.ThoughtSpotClient")
    @patch("ts_cli.commands.metadata.resolve_profile", return_value="test")
    def test_no_connection_flag_returns_all_results(self, mock_resolve, mock_client_cls):
        mock_client = MagicMock()
        page = [_item("a", "Snowflake Prod"), _item("b", "Databricks")]
        mock_client.post.return_value.json.return_value = page
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["metadata", "search"])

        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert len(out) == 2
