"""CliRunner tests for `ts security column-rules`. No live instance."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import pytest
from typer.testing import CliRunner

from ts_cli.cli import app

# `runner` for stdout-JSON assertions; `msg_runner` for anything a manual
# print(file=sys.stderr) emits, which the separated runner silently drops. See the
# Global Constraints section of the plan, and test_cli_alias.py / test_tml_commands.py
# for the same tradeoff documented elsewhere in this suite.
try:
    runner = CliRunner(mix_stderr=False)
except TypeError:            # Click >= 8.2 removed the parameter
    runner = CliRunner()
msg_runner = CliRunner()


class FakeResponse:
    def __init__(self, payload: Any = None, status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text or json.dumps(payload or {})

    def json(self) -> Any:
        return self._payload


class FakeClient:
    """Records every POST so a test can assert on the payload that would have gone out."""

    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        self.responses = responses or {}
        self.calls = []

    def post(self, path: str, json: Any = None, **kwargs: Any) -> FakeResponse:
        self.calls.append((path, json))
        result = self.responses.get(path, FakeResponse({}))
        return result(json) if callable(result) else result

    def get(self, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((path, None))
        result = self.responses.get(path, FakeResponse({}))
        return result(None) if callable(result) else result


FETCH = "/api/rest/2.0/security/column/rules/fetch"
UPDATE = "/api/rest/2.0/security/column/rules/update"

_FETCH_BODY = [{
    "table_guid": "tg-1", "obj_id": "oid",
    "column_security_rules": [
        {"column": {"id": "c1", "name": "SALARY"},
         "groups": [{"id": "g1", "name": "HR"}],
         "source_table_details": {"id": "st", "name": "EMP"}}]}]


@pytest.fixture
def patched(monkeypatch):
    """Patch the org-scoped client factory the whole command group goes through."""
    holder = {}

    def _install(client):
        holder["client"] = client
        monkeypatch.setattr("ts_cli.commands.security._client_for_org",
                            lambda profile, org=None: client)
        monkeypatch.setattr("ts_cli.commands.security.assert_org_context",
                            lambda *a, **k: None)
        return client

    return _install


def test_get_prints_normalised_rows_as_json(patched):
    patched(FakeClient({FETCH: FakeResponse(_FETCH_BODY)}))
    result = runner.invoke(app, ["security", "column-rules", "get", "T2", "-p", "x"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert rows == [{"org": "", "table_guid": "tg-1", "obj_id": "oid",
                     "column_id": "c1", "column_name": "SALARY",
                     "group_names": ["HR"], "source_table_name": "EMP"}]


def test_get_sends_all_tables_in_one_fetch_call(patched):
    client = patched(FakeClient({FETCH: FakeResponse([])}))
    runner.invoke(app, ["security", "column-rules", "get", "T1", "T2", "-p", "x"])
    body = next(b for p, b in client.calls if p == FETCH)
    assert body == {"tables": [{"identifier": "T1"}, {"identifier": "T2"}]}


def test_get_tags_each_row_with_the_org_it_came_from(patched):
    patched(FakeClient({FETCH: FakeResponse(_FETCH_BODY)}))
    result = runner.invoke(app, ["security", "column-rules", "get", "T2",
                                 "--org", "ORG1", "-p", "x"])
    assert json.loads(result.stdout)[0]["org"] == "ORG1"


def test_get_explains_the_feature_flag_instead_of_a_bare_403(patched):
    body = '{"error":{"code":10023,"message":"Column Security rule feature is disabled"}}'
    patched(FakeClient({FETCH: FakeResponse(None, 403, body)}))
    # msg_runner: the explanation is a manual stderr print, which the separated runner
    # drops.
    result = msg_runner.invoke(app, ["security", "column-rules", "get", "T2", "-p", "x"])
    assert result.exit_code == 1
    assert "feature-flagged" in result.output
    assert "10.12" in result.output


def test_the_group_is_registered_under_ts_security():
    result = runner.invoke(app, ["security", "column-rules", "--help"])
    assert result.exit_code == 0
    for command in ("get", "set", "clear", "export"):
        assert command in result.output


def test_set_defaults_to_replace(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                 "--rule", "PROD_NM=Analyst,Finance", "-p", "x"])
    assert result.exit_code == 0, result.output
    body = next(b for p, b in client.calls if p == UPDATE)
    assert body == {
        "identifier": "T2", "clear_csr": False,
        "column_security_rules": [
            {"column_identifier": "PROD_NM", "is_unsecured": False,
             "group_access": [{"operation": "REPLACE",
                               "group_identifiers": ["Analyst", "Finance"]}]}]}


def test_set_add_and_remove_change_the_operation(patched):
    for flag, operation in (("--add", "ADD"), ("--remove", "REMOVE")):
        client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
        runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                            "--rule", "COST=Finance", flag, "-p", "x"])
        body = next(b for p, b in client.calls if p == UPDATE)
        assert body["column_security_rules"][0]["group_access"][0]["operation"] \
            == operation


def test_set_refuses_add_and_remove_together(patched):
    patched(FakeClient())
    result = msg_runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                     "--rule", "COST=Finance", "--add", "--remove",
                                     "-p", "x"])
    assert result.exit_code != 0
    assert "--add" in result.output


def test_set_dry_run_prints_the_payload_and_posts_nothing(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                 "--rule", "COST=Finance", "--dry-run", "-p", "x"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["identifier"] == "T2"
    # --dry-run never constructs a client at all, so no call of any kind should be
    # recorded -- not just an absence of the UPDATE path specifically.
    assert client.calls == []


def test_set_rejects_a_malformed_rule_flag(patched):
    patched(FakeClient())
    result = msg_runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                                     "--rule", "PROD_NM", "-p", "x"])
    assert result.exit_code != 0
    assert "COL=GROUP" in result.output


def test_clear_sends_clear_csr_with_the_required_empty_array(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = runner.invoke(app, ["security", "column-rules", "clear", "--table", "T2",
                                 "-p", "x"])
    assert result.exit_code == 0, result.output
    body = next(b for p, b in client.calls if p == UPDATE)
    assert body == {"identifier": "T2", "clear_csr": True,
                    "column_security_rules": []}


def test_clear_one_column_unsecures_just_that_column(patched):
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    runner.invoke(app, ["security", "column-rules", "clear", "--table", "T2",
                        "--column", "COST", "-p", "x"])
    body = next(b for p, b in client.calls if p == UPDATE)
    assert body == {"identifier": "T2", "clear_csr": False,
                    "column_security_rules": [
                        {"column_identifier": "COST", "is_unsecured": True}]}


def test_clear_rejects_an_explicitly_empty_column(patched):
    # --column "" (e.g. an unset shell variable spliced into `--column "$COL"`) must NOT
    # silently fall through to the whole-table clear branch -- that would strip every
    # column's security on a routine scripting mistake, which is the one failure
    # direction this feature must never take silently. An explicit empty string is
    # distinct from an omitted flag (column is None) and must be refused.
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    result = msg_runner.invoke(app, ["security", "column-rules", "clear", "--table", "T2",
                                     "--column", "", "-p", "x"])
    assert result.exit_code != 0
    assert not [p for p, _ in client.calls if p == UPDATE]


def test_set_asserts_the_org_context_before_writing(monkeypatch, patched):
    # The assertion and the POST are recorded into the SAME ordered list (the fake
    # client's own `.calls`) so the test can prove the assertion ran BEFORE the write,
    # not merely that it ran. An implementation that posted first and asserted
    # afterwards -- exactly the bug this assertion exists to prevent -- would still
    # pass a test that only checked "did assert_org_context get called at all".
    client = patched(FakeClient({UPDATE: FakeResponse(None, 204)}))
    monkeypatch.setattr(
        "ts_cli.commands.security.assert_org_context",
        lambda c, org, profile=None: client.calls.append(("assert_org_context", org)))
    runner.invoke(app, ["security", "column-rules", "set", "--table", "T2",
                        "--rule", "COST=Finance", "--org", "ORG1", "-p", "x"])
    kinds = [p for p, _ in client.calls]
    assert "assert_org_context" in kinds and UPDATE in kinds
    assert kinds.index("assert_org_context") < kinds.index(UPDATE)


EXPORT = "/api/rest/2.0/metadata/tml/export"

_CSR_EDOC = ("column_security_rules:\n"
             "  table:\n    name: T2\n"
             "  rules:\n"
             "  - column_name: PROD_NM\n"
             "    accessible_groups:\n      group_name:\n      - Analyst\n")


def test_export_asks_for_both_flags_the_beta_option_needs(patched):
    client = patched(FakeClient({EXPORT: FakeResponse([])}))
    runner.invoke(app, ["security", "column-rules", "export", "T2", "-p", "x"])
    body = next(b for p, b in client.calls if p == EXPORT)
    assert body["export_associated"] is True
    assert body["export_options"] == {"export_column_security_rules": True}
    assert body["metadata"] == [{"identifier": "T2", "type": "LOGICAL_TABLE"}]


def test_export_prints_the_parsed_documents(patched):
    patched(FakeClient({EXPORT: FakeResponse(
        [{"info": {"type": "column_security_rules", "id": "g-9"}, "edoc": _CSR_EDOC}])}))
    result = runner.invoke(app, ["security", "column-rules", "export", "T2", "-p", "x"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["documents"][0]["table_name"] == "T2"
    assert payload["documents"][0]["rules"] == {"PROD_NM": ["Analyst"]}


def test_export_writes_files_named_the_way_the_platform_names_them(patched, tmp_path):
    patched(FakeClient({EXPORT: FakeResponse(
        [{"info": {"type": "column_security_rules", "id": "g-9"}, "edoc": _CSR_EDOC}])}))
    result = runner.invoke(app, ["security", "column-rules", "export", "T2",
                                 "--out", str(tmp_path), "-p", "x"])
    assert result.exit_code == 0, result.output
    written = tmp_path / "T2_CSR.column_security_rules.tml"
    assert written.exists()
    assert "column_security_rules" in written.read_text()


_NO_CSR = [{"info": {"type": "logical_table"}, "edoc": "table:\n  name: T2\n"}]


def test_export_returns_an_empty_document_list_when_nothing_is_secured(patched):
    patched(FakeClient({EXPORT: FakeResponse(_NO_CSR)}))
    result = runner.invoke(app, ["security", "column-rules", "export", "T2", "-p", "x"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["documents"] == []


def test_export_says_on_stderr_that_it_found_nothing(patched):
    # Split from the test above: the message is a manual stderr print, so it needs the
    # mixing runner, which in turn makes result.stdout unparseable.
    patched(FakeClient({EXPORT: FakeResponse(_NO_CSR)}))
    result = msg_runner.invoke(app, ["security", "column-rules", "export", "T2",
                                     "-p", "x"])
    assert result.exit_code == 0
    assert "no column security rules" in result.output.lower()
