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
    assert "get" in result.output
