"""Command-level tests for `ts tables create` (Bug B, Task 25; BL-073 batching).

Tests cover:
- Two-pass RLS registration: pass 1 creates without rls_rules; pass 2 attaches
  them with the GUID + --no-create-new.
- Batched import: pass 1 sends all table TMLs in a single API call (up to 50);
  JDBC failures in the batch are retried individually.
- Fail-closed (Task 26): a pass-2 failure exits non-zero.
"""
from __future__ import annotations

import json

import yaml
from typer.testing import CliRunner

import ts_cli.commands.tables as tables_mod
from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # Click >= 8.2 removed mix_stderr (stderr separated by default)
    runner = CliRunner()

_RLS_SPEC = {
    "name": "SALES_AGG",
    "db": "MY_DB",
    "schema": "MY_SCHEMA",
    "db_table": "SALES_AGG",
    "connection_name": "My Connection",
    "columns": [
        {"name": "CATEGORY", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
        {"name": "SALES", "data_type": "DOUBLE", "column_type": "MEASURE"},
    ],
    "rls_rules": {
        "tables": [{"name": "SALES_AGG"}],
        "table_paths": [{"id": "SALES_AGG_1", "table": "SALES_AGG", "column": ["CATEGORY"]}],
        "rules": [{"name": "cat_rule", "expr": "[SALES_AGG_1::CATEGORY] = ts_groups"}],
    },
}

_PLAIN_SPEC = {
    "name": "PLAIN_TABLE",
    "db": "MY_DB",
    "schema": "MY_SCHEMA",
    "db_table": "PLAIN_TABLE",
    "connection_name": "My Connection",
    "columns": [{"name": "ID", "data_type": "INT64", "column_type": "ATTRIBUTE"}],
}


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _ok_item(guid: str) -> dict:
    return {"response": {"status": {"status_code": "OK"},
                         "object": [{"header": {"id_guid": guid}}]}}


def _ok_response(guid: str) -> list:
    return [_ok_item(guid)]


def _make_batch_client(calls: list, guids: dict[str, str] | None = None,
                       default_guid: str = "default-guid"):
    """Client that returns OK for each TML in a batch, assigning GUIDs.

    `guids` maps table name to GUID. Absent names get `default_guid`.
    Inspects TML YAML to find the table name.
    """
    if guids is None:
        guids = {}

    class FakeClient:
        def __init__(self, profile_name):
            pass

        def post(self, path, json=None, **kwargs):
            calls.append(json)
            tmls = json.get("metadata_tmls", [])
            items = []
            for tml_str in tmls:
                tml = yaml.safe_load(tml_str)
                name = tml.get("table", {}).get("name", "")
                guid = guids.get(name, default_guid)
                items.append(_ok_item(guid))
            return _FakeResp(items)

    return FakeClient


class TestBatchedImport:
    def test_single_plain_table_uses_one_batch_call(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, default_guid="plain-guid-1"))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_PLAIN_SPEC]))
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert len(calls[0]["metadata_tmls"]) == 1
        assert calls[0]["create_new"] is True
        assert json.loads(result.stdout) == {"PLAIN_TABLE": "plain-guid-1"}

    def test_multiple_plain_tables_batched_in_one_call(self, monkeypatch):
        specs = [
            {**_PLAIN_SPEC, "name": f"TABLE_{i}", "db_table": f"TABLE_{i}"}
            for i in range(5)
        ]
        guids = {f"TABLE_{i}": f"guid-{i}" for i in range(5)}
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, guids=guids))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps(specs))
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert len(calls[0]["metadata_tmls"]) == 5
        out = json.loads(result.stdout)
        for i in range(5):
            assert out[f"TABLE_{i}"] == f"guid-{i}"

    def test_jdbc_error_in_batch_retries_individually(self, monkeypatch):
        calls = []

        class JdbcBatchClient:
            def __init__(self, profile_name):
                self.call_count = 0

            def post(self, path, json=None, **kwargs):
                calls.append(json)
                self.call_count += 1
                tmls = json.get("metadata_tmls", [])
                if self.call_count == 1:
                    items = []
                    for tml_str in tmls:
                        tml = yaml.safe_load(tml_str)
                        name = tml.get("table", {}).get("name", "")
                        if name == "TABLE_1":
                            items.append({"response": {"status": {
                                "status_code": "ERROR",
                                "error_message": "CONNECTION_METADATA_FETCH_ERROR"}}})
                        else:
                            items.append(_ok_item(f"guid-{name}"))
                    return _FakeResp(items)
                # Individual retry for TABLE_1
                return _FakeResp([_ok_item("guid-TABLE_1")])

        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", JdbcBatchClient)
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        specs = [
            {**_PLAIN_SPEC, "name": "TABLE_0", "db_table": "TABLE_0"},
            {**_PLAIN_SPEC, "name": "TABLE_1", "db_table": "TABLE_1"},
        ]
        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile",
                                     "--retries", "1"],
                               input=json.dumps(specs))
        assert result.exit_code == 0, result.output
        assert len(calls) == 2  # 1 batch + 1 individual retry
        assert len(calls[0]["metadata_tmls"]) == 2  # batch
        assert len(calls[1]["metadata_tmls"]) == 1  # individual retry
        out = json.loads(result.stdout)
        assert out["TABLE_0"] == "guid-TABLE_0"
        assert out["TABLE_1"] == "guid-TABLE_1"


class TestTwoPassRlsRegistration:
    def test_two_import_calls_made_for_an_rls_spec(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, guids={"SALES_AGG": "agg-guid-1"}))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_RLS_SPEC]))
        assert result.exit_code == 0, result.output
        assert len(calls) == 2  # pass 1 batch + pass 2 batch

    def test_pass_one_creates_without_rls_rules(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, guids={"SALES_AGG": "agg-guid-1"}))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                      input=json.dumps([_RLS_SPEC]))
        pass1 = calls[0]
        assert pass1["create_new"] is True
        tml = yaml.safe_load(pass1["metadata_tmls"][0])
        assert "rls_rules" not in tml["table"]
        assert "guid" not in tml

    def test_pass_two_attaches_rls_rules_with_guid_and_no_create_new(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, guids={"SALES_AGG": "agg-guid-1"}))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                      input=json.dumps([_RLS_SPEC]))
        pass2 = calls[1]
        assert pass2["create_new"] is False
        tml = yaml.safe_load(pass2["metadata_tmls"][0])
        assert tml["guid"] == "agg-guid-1"
        assert tml["table"]["rls_rules"] == _RLS_SPEC["rls_rules"]

    def test_output_maps_table_name_to_the_created_guid(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, guids={"SALES_AGG": "agg-guid-1"}))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_RLS_SPEC]))
        assert json.loads(result.stdout) == {"SALES_AGG": "agg-guid-1"}

    def test_pass_two_failure_is_reported_but_table_guid_still_returned(self, monkeypatch):
        calls = []

        class FlakyClient:
            def __init__(self, profile_name):
                self.n = 0

            def post(self, path, json=None, **kwargs):
                calls.append(json)
                self.n += 1
                tmls = json.get("metadata_tmls", [])
                if self.n == 1:
                    return _FakeResp([_ok_item("agg-guid-1") for _ in tmls])
                return _FakeResp([{"response": {
                    "status": {"status_code": "ERROR",
                               "error_message": "boom"}}} for _ in tmls])

        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", FlakyClient)
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile",
                                     "--retries", "1"],
                               input=json.dumps([_RLS_SPEC]))
        assert len(calls) == 2
        assert "row-level security" in result.stderr
        assert json.loads(result.stdout) == {"SALES_AGG": "agg-guid-1"}
        assert result.exit_code != 0
        assert "SALES_AGG" in result.stderr


class TestSinglePassUnaffected:
    def test_no_rls_rules_spec_makes_exactly_one_call(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, default_guid="plain-guid-1"))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_PLAIN_SPEC]))
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert calls[0]["create_new"] is True
        assert json.loads(result.stdout) == {"PLAIN_TABLE": "plain-guid-1"}


class TestPassTwoFailureFailsClosed:
    """Task 26: pass-2 (RLS attach) failure exits non-zero."""

    def _flaky_client(self, calls, guid="agg-guid-1"):
        class FlakyClient:
            def __init__(self, profile_name):
                self.n = 0

            def post(self, path, json=None, **kwargs):
                calls.append(json)
                self.n += 1
                tmls = json.get("metadata_tmls", [])
                if self.n == 1:
                    return _FakeResp([_ok_item(guid) for _ in tmls])
                return _FakeResp([{"response": {
                    "status": {"status_code": "ERROR",
                               "error_message": "boom"}}} for _ in tmls])

        return FlakyClient

    def test_pass_two_failure_exits_non_zero(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", self._flaky_client(calls))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile",
                                     "--retries", "1"],
                               input=json.dumps([_RLS_SPEC]))
        assert result.exit_code != 0

    def test_pass_two_failure_still_preserves_guid_in_stdout(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", self._flaky_client(calls, "agg-guid-2"))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile",
                                     "--retries", "1"],
                               input=json.dumps([_RLS_SPEC]))
        assert json.loads(result.stdout) == {"SALES_AGG": "agg-guid-2"}

    def test_pass_two_failure_error_names_the_table(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", self._flaky_client(calls))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile",
                                     "--retries", "1"],
                               input=json.dumps([_RLS_SPEC]))
        assert "SALES_AGG" in result.stderr
        assert "row-level security" in result.stderr
        assert "do not re-run" in result.stderr.lower()

    def test_one_table_rls_attach_fails_other_table_succeeds_still_reports_both_guids(
        self, monkeypatch,
    ):
        calls = []

        class MixedClient:
            def __init__(self, profile_name):
                self.n = 0

            def post(self, path, json=None, **kwargs):
                calls.append(json)
                self.n += 1
                tmls = json.get("metadata_tmls", [])
                if self.n == 1:
                    # Pass 1 batch: both tables succeed
                    items = []
                    for tml_str in tmls:
                        tml = yaml.safe_load(tml_str)
                        name = tml.get("table", {}).get("name", "")
                        if name == "PLAIN_TABLE":
                            items.append(_ok_item("plain-guid-1"))
                        else:
                            items.append(_ok_item("agg-guid-1"))
                    return _FakeResp(items)
                # Pass 2 batch: SALES_AGG RLS attach fails
                return _FakeResp([{"response": {
                    "status": {"status_code": "ERROR",
                               "error_message": "boom"}}} for _ in tmls])

        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", MixedClient)
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile",
                                     "--retries", "1"],
                               input=json.dumps([_PLAIN_SPEC, _RLS_SPEC]))
        assert result.exit_code != 0
        assert json.loads(result.stdout) == {
            "PLAIN_TABLE": "plain-guid-1",
            "SALES_AGG": "agg-guid-1",
        }

    def test_happy_path_no_rls_still_exits_zero(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, default_guid="plain-guid-1"))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_PLAIN_SPEC]))
        assert result.exit_code == 0

    def test_happy_path_successful_two_pass_rls_still_exits_zero(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient",
                            _make_batch_client(calls, guids={"SALES_AGG": "agg-guid-1"}))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_RLS_SPEC]))
        assert result.exit_code == 0
