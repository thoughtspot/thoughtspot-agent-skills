"""Command-level tests for `ts tables create` (Bug B, Task 25).

LIVE FINDING: a single `create_new` import of an aggregate table's TML that
already carries a self-referencing `rls_rules` block (`[<agg>_1::COL]`
pointing at the table being created) fails — `OBJECT_NOT_FOUND ...
LOGICAL_TABLE` — because the self-reference can't resolve before the table
exists. The working sequence is two passes: (1) create the table WITHOUT
`rls_rules`, capture its GUID; (2) re-import the SAME table WITH `rls_rules`
+ that GUID at the document root + `--no-create-new`, which attaches the
rules to the now-existing table. `create_tables` does this automatically
whenever a spec carries `rls_rules` — the caller (the `ts-object-model-
aggregates` skill) doesn't need to orchestrate it by hand.

A spec with no `rls_rules` is completely unaffected — single pass, byte-for-
byte the pre-Task-25 behavior (see TestSinglePassUnaffected below).
"""
from __future__ import annotations

import json

import yaml
from typer.testing import CliRunner

import ts_cli.commands.tables as tables_mod
from ts_cli.cli import app

runner = CliRunner(mix_stderr=False)

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


def _ok_response(guid: str) -> list:
    return [{"response": {"status": {"status_code": "OK"},
                          "object": [{"header": {"id_guid": guid}}]}}]


def _make_fake_client(calls: list, guid: str = "agg-guid-1"):
    class FakeClient:
        def __init__(self, profile_name):
            pass

        def post(self, path, json=None, **kwargs):
            calls.append(json)
            return _FakeResp(_ok_response(guid))

    return FakeClient


class TestTwoPassRlsRegistration:
    def test_two_import_calls_made_for_an_rls_spec(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", _make_fake_client(calls))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_RLS_SPEC]))
        assert result.exit_code == 0, result.output
        assert len(calls) == 2

    def test_pass_one_creates_without_rls_rules(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", _make_fake_client(calls))
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
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", _make_fake_client(calls, "agg-guid-1"))
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
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", _make_fake_client(calls, "agg-guid-1"))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_RLS_SPEC]))
        assert json.loads(result.stdout) == {"SALES_AGG": "agg-guid-1"}

    def test_pass_two_failure_is_reported_but_table_guid_still_returned(self, monkeypatch):
        # Pass 1 (create) succeeds; pass 2 (attach RLS) fails outright (not a
        # retryable JDBC error) — the table exists (unsecured) and this must
        # be surfaced loudly on stderr, not silently swallowed. The SKILL's
        # own "confirm they attached (export + check)" step is the actual
        # safety net; this only checks the CLI doesn't hide the failure.
        calls = []

        class FlakyClient:
            def __init__(self, profile_name):
                self.n = 0

            def post(self, path, json=None, **kwargs):
                calls.append(json)
                self.n += 1
                if self.n == 1:
                    return _FakeResp(_ok_response("agg-guid-1"))
                return _FakeResp([{"response": {
                    "status": {"status_code": "ERROR", "error_message": "boom"}}}])

        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", FlakyClient)
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile",
                                     "--retries", "1"],
                               input=json.dumps([_RLS_SPEC]))
        assert len(calls) == 2
        assert "row-level security" in result.stderr
        assert json.loads(result.stdout) == {"SALES_AGG": "agg-guid-1"}


class TestSinglePassUnaffected:
    def test_no_rls_rules_spec_makes_exactly_one_call(self, monkeypatch):
        calls = []
        monkeypatch.setattr(tables_mod, "ThoughtSpotClient", _make_fake_client(calls, "plain-guid-1"))
        monkeypatch.setattr(tables_mod, "resolve_profile", lambda p: "test-profile")

        result = runner.invoke(app, ["tables", "create", "--profile", "test-profile"],
                               input=json.dumps([_PLAIN_SPEC]))
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert calls[0]["create_new"] is True
        assert json.loads(result.stdout) == {"PLAIN_TABLE": "plain-guid-1"}
