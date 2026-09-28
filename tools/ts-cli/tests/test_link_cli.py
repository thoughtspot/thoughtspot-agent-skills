"""Orchestration tests for `ts link build` (commands/link.py) with a fake ThoughtSpot client.

No live connection: the fake records every POST and answers from a scripted table, so
these tests pin the import order, the Table-GUID injection into the Model, and — the part
the adversarial review found broken — that no failure after the Table exists can exit
without reporting table_guid on stdout.
"""
import json

import pytest
import yaml
from typer.testing import CliRunner

from ts_cli.cli import app as ts_app
from ts_cli.commands import link as link_cmd

runner = CliRunner()

TABLE_GUID = "11111111-1111-1111-1111-111111111111"
MODEL_GUID = "22222222-2222-2222-2222-222222222222"

SPEC = {
    "connection": "TS-DBX", "db": "cat", "schema": "sch", "db_table": "sales_mv",
    "instructions": "Use geo dims for sessions.",
    "columns": [
        {"name": "region", "data_type": "string", "kind": "attribute"},
        {"name": "revenue", "data_type": "double", "kind": "measure", "expr": "SUM(x)"},
    ],
}


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _ok_import(guid):
    return FakeResp(200, [{"response": {"status": {"status_code": "OK"},
                                        "header": {"id_guid": guid}}}])


class FakeClient:
    """Scripted responses per call; a callable entry is invoked (to raise)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def post(self, path, json=None, **kwargs):
        self.calls.append((path, json, kwargs))
        item = self.script.pop(0)
        if callable(item):
            return item()
        return item


def _run(tmp_path, monkeypatch, script, extra=()):
    fake = FakeClient(script)
    monkeypatch.setattr(link_cmd, "ThoughtSpotClient", lambda *a, **k: fake)
    monkeypatch.setattr(link_cmd, "resolve_profile", lambda p: "p")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(SPEC))
    res = runner.invoke(ts_app, ["link", "build", "--spec", str(spec), "--aggregation", "aggregate",
                                       "--model-name", "M", "--output-dir", str(tmp_path), *extra])
    out = json.loads(res.stdout) if res.stdout.strip() else None
    return res, out, fake


def _exported(model_doc_path):
    doc = yaml.safe_load(model_doc_path.read_text())
    return FakeResp(200, [{"edoc": yaml.safe_dump(doc)}])


def test_happy_path_order_fqn_and_summary(tmp_path, monkeypatch):
    # export answers with exactly what was sent → no coercion
    def export():
        return _exported(tmp_path / "model.tml")
    res, out, fake = _run(tmp_path, monkeypatch, [
        _ok_import(TABLE_GUID), _ok_import(MODEL_GUID), FakeResp(200, {"success": True}), export])
    assert res.exit_code == 0, res.stderr
    paths = [c[0] for c in fake.calls]
    assert paths == [link_cmd._IMPORT_PATH, link_cmd._IMPORT_PATH,
                     link_cmd._INSTRUCTIONS_SET_PATH, link_cmd._EXPORT_PATH]
    model_tml = yaml.safe_load(fake.calls[1][1]["metadata_tmls"][0])
    assert model_tml["model"]["model_tables"] == [{"name": "sales_mv", "fqn": TABLE_GUID}]
    assert fake.calls[2][1]["nl_instructions_info"] == [
        {"instructions": ["Use geo dims for sessions."], "scope": "GLOBAL"}]
    assert out["table_guid"] == TABLE_GUID and out["model_guid"] == MODEL_GUID
    assert out["instructions_result"] == {"set": True}
    assert out["coerced"] == []
    assert all(c[2].get("raise_for_status") is False for c in fake.calls)


def test_dry_run_makes_no_calls(tmp_path, monkeypatch):
    res, out, fake = _run(tmp_path, monkeypatch, [], extra=["--dry-run"])
    assert res.exit_code == 0 and fake.calls == [] and out["dry_run"] is True
    assert (tmp_path / "table.tml").exists() and (tmp_path / "model.tml").exists()


def test_model_http_error_still_reports_table_guid(tmp_path, monkeypatch):
    res, out, _ = _run(tmp_path, monkeypatch, [_ok_import(TABLE_GUID), FakeResp(403, {"error": "no"})])
    assert res.exit_code == 1
    assert out["table_guid"] == TABLE_GUID and "model import failed" in out["error"]
    assert TABLE_GUID in res.stderr


def test_model_client_exit_still_reports_table_guid(tmp_path, monkeypatch):
    def boom():
        raise SystemExit(1)  # what ThoughtSpotClient does on exhausted retries
    res, out, _ = _run(tmp_path, monkeypatch, [_ok_import(TABLE_GUID), boom])
    assert res.exit_code == 1 and out["table_guid"] == TABLE_GUID


def test_instructions_and_verify_failures_do_not_undo_link(tmp_path, monkeypatch):
    def boom():
        raise SystemExit(1)
    res, out, _ = _run(tmp_path, monkeypatch, [
        _ok_import(TABLE_GUID), _ok_import(MODEL_GUID), boom, FakeResp(500, None)])
    assert res.exit_code == 0
    assert out["model_guid"] == MODEL_GUID
    assert out["instructions_result"]["set"] is False
    assert out["coerced"] is None and "500" in out["verify_error"]


def test_already_linked_reports_existing_guid(tmp_path, monkeypatch):
    refusal = FakeResp(200, [{"response": {"status": {
        "status_code": "ERROR",
        "error_message": "Cannot create a new table as the table in the TML file already exists. "
                         "Existing Table GUID: 39570acf-7364-4860-a1c4-599c4a9d75b3. "
                         "Switch to Update existing to continue. <br/>"}}}])
    res, out, fake = _run(tmp_path, monkeypatch, [refusal])
    assert res.exit_code == 1 and len(fake.calls) == 1
    assert out["existing_table_guid"] == "39570acf-7364-4860-a1c4-599c4a9d75b3"


def test_non_json_import_body_is_a_reported_failure(tmp_path, monkeypatch):
    res, out, _ = _run(tmp_path, monkeypatch, [FakeResp(502, None)])
    assert res.exit_code == 1 and "table import failed" in out["error"]


def test_coercion_is_reported(tmp_path, monkeypatch):
    def export():
        doc = yaml.safe_load((tmp_path / "model.tml").read_text())
        for c in doc["model"]["columns"]:
            if c["column_id"].endswith("::revenue"):
                c["properties"] = {"column_type": "ATTRIBUTE"}
        return FakeResp(200, [{"edoc": yaml.safe_dump(doc)}])
    res, out, _ = _run(tmp_path, monkeypatch, [
        _ok_import(TABLE_GUID), _ok_import(MODEL_GUID), FakeResp(200, {"success": True}), export])
    assert {"column_id": "sales_mv::revenue", "field": "column_type",
            "expected": "MEASURE", "actual": "ATTRIBUTE"} in out["coerced"]
    assert "WARNING" in res.stderr
