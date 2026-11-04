"""BL-516: a requested Model the audit could not export is shown, not only warned.
BL-517: the Answer export keeps the healthy Answers of a refused batch.

A Model that is requested (`ctx.model_guids`) but has no exported TML (`ctx.models`) was
named only on stderr and in a snapshot's warnings.json. It is now in the run's JSON
(`corpus.not_exported`), the report's "Not exported" box and the closing line. Derived
from the context rather than recorded in it, so a snapshot captured before this replays
the same way.

The Answer export reuses the Model export's retry (BL-510): a batch refused as a bad
request (400 or 404) is retried one Answer at a time, any other failure stops it, and
every skip lands in `ctx.warnings`. Driven through the REAL client over a fake transport,
as test_audit_model_export_batches.py is.
"""
from __future__ import annotations

import json as _json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

import report_browser
from ts_cli.audit import run_audit
from ts_cli.audit.context import _export_answers, make_context
from ts_cli.audit.report import compact_payload, render_report
from ts_cli.client import ThoughtSpotClient
from ts_cli.commands.audit import closing_line


def _model(guid):
    return {"guid": guid, "model": {"name": guid.upper(), "columns": [],
                                    "model_tables": []}}


def _run(guids, exported, warnings):
    ctx = make_context(models=[_model(g) for g in exported], model_guids=guids,
                       warnings=list(warnings))
    return run_audit(None, guids, ctx=ctx)


def test_a_model_refused_on_its_own_is_listed_with_its_reason():
    warning = "Model gone could not be exported (HTTP 404), so not checked"
    out = _run(["m-1", "gone"], ["m-1"], [warning])
    assert out["corpus"]["not_exported"] == [warning]
    assert compact_payload(out)["C"]["ne"] == [warning]


def test_a_model_in_a_skipped_batch_is_listed_by_guid():
    """The batch warning counts Models but names none: each GUID is listed."""
    out = _run(["m-1", "x-1", "x-2"], ["m-1"],
               ["Model export batch 1 returned 503, skipping 2 model(s)"])
    assert out["corpus"]["not_exported"] == [
        "Model x-1: no TML was exported for it, so not checked",
        "Model x-2: no TML was exported for it, so not checked"]


def test_a_warning_for_a_longer_guid_is_not_borrowed():
    out = _run(["a"], [], ["Model ab could not be exported (HTTP 404), so not checked"])
    assert out["corpus"]["not_exported"] == ["Model a: no TML was exported for it, so not checked"]


def test_a_model_doc_whose_guid_is_not_a_string_does_not_end_the_listing():
    """`_not_exported` itself; the rest of the engine on a non-string guid is the scalar
    class (BL-518)."""
    from ts_cli.audit import _not_exported
    odd = _model("m-1")
    odd["guid"] = ["m-1"]
    assert _not_exported(make_context(models=[odd], model_guids=["m-1"])) == [
        "Model m-1: no TML was exported for it, so not checked"]


def test_a_model_requested_twice_is_listed_once():
    out = _run(["gone", "gone"], [], [])
    assert len(out["corpus"]["not_exported"]) == 1


def test_nothing_is_listed_when_every_model_was_exported():
    out = _run(["m-1"], ["m-1"], [])
    assert "not_exported" not in out["corpus"]
    assert "ne" not in compact_payload(out)["C"]


@pytest.mark.skipif(report_browser.CHROME is None, reason="headless Chrome not installed")
def test_the_dashboard_shows_both_boxes_and_neither_when_clean(tmp_path):
    warning = "Model gone could not be exported (HTTP 404), so not checked"
    bad = _model("m-2")
    bad["model"]["properties"] = ["x"]
    ctx = make_context(models=[_model("m-1"), bad], model_guids=["m-1", "m-2", "gone"],
                       warnings=[warning])
    (tmp_path / "x").mkdir()
    shown = report_browser.render(render_report(run_audit(None, [], ctx=ctx)), tmp_path / "x")
    assert shown["errors"] == []
    assert "Not exported — 1 Model not checked." in shown["visible"]
    assert warning in shown["visible"]
    assert "Could not be read — 1 item not judged." in shown["visible"]
    (tmp_path / "y").mkdir()
    clean = report_browser.render(render_report(_run(["m-1"], ["m-1"], [])), tmp_path / "y")
    assert clean["errors"] == []
    assert "Not exported" not in clean["visible"] and "Could not be read" not in clean["visible"]


def test_a_malformed_model_is_unreadable_not_unexported():
    """It was exported: item 10's box names it, this one does not."""
    bad = _model("m-1")
    bad["model"]["properties"] = ["not", "a", "mapping"]
    ctx = make_context(models=[bad], model_guids=["m-1"])
    out = run_audit(None, ["m-1"], ctx=ctx)
    assert out["corpus"]["unreadable"] and "not_exported" not in out["corpus"]


def test_the_closing_line_counts_what_was_not_checked():
    out = _run(["m-1", "gone"], ["m-1"], [])
    line = closing_line(out)
    assert line.startswith("Audit complete:")
    assert "1 Model(s) could not be exported, so were not checked" in line
    bad = _model("m-2")
    bad["model"]["properties"] = ["x"]
    out = run_audit(None, ["m-2"], ctx=make_context(models=[bad], model_guids=["m-2"]))
    assert "1 item(s) could not be read, so were not judged" in closing_line(out)
    assert "could not" not in closing_line(_run(["m-1"], ["m-1"], []))


# ── BL-517: the Answer export ────────────────────────────────────────────────

_EXPORT = "/metadata/tml/export"


def _response(url, status, body):
    r = requests.Response()
    r.status_code, r.url = status, url
    r._content = _json.dumps(body).encode()
    r.headers["Content-Type"] = "application/json"
    return r


class Transport:
    """Answers export requests: `gone` in a request fails it with `bad`;
    `single_failure` is what a one-GUID request for a healthy Answer gets instead."""

    def __init__(self, bad=400, single_failure=0):
        self.bad, self.single_failure = bad, single_failure
        self.exports: list = []

    def __call__(self, method, url, headers=None, timeout=None, **kw):
        body = kw.get("json") or {}
        self.exports.append(body)
        ids = [m["identifier"] for m in body.get("metadata", [])]
        if "gone" in ids:
            return _response(url, self.bad, {"debug": "object not found"})
        if len(ids) == 1 and self.single_failure:
            return _response(url, self.single_failure, {"debug": "unavailable"})
        return _response(url, 200, [
            {"edoc": yaml.safe_dump({"guid": g, "answer": {"name": g}})} for g in ids])


def _client(tmp_path: Path, transport):
    profile = {"name": "Fake", "base_url": "https://example.thoughtspot.cloud",
               "username": "u@example.com", "token_env": "THOUGHTSPOT_TOKEN_FAKE"}
    with patch("ts_cli.client.load_profiles", return_value={"Fake": profile}):
        client = ThoughtSpotClient("Fake")
    client._token_path = lambda: tmp_path / "token.txt"
    client._expiry_path = lambda: tmp_path / "expiry.txt"
    client._token = "fake-token"
    client._session = MagicMock()
    client._session.request.side_effect = transport
    return client


def _dependents(guids):
    return {"m-1": [{"guid": g, "type": "ANSWER", "name": g} for g in guids]}


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("ts_cli.client.time.sleep"):
        yield


@pytest.mark.parametrize("status", [400, 404])
def test_a_deleted_answer_costs_only_itself(tmp_path, status):
    warnings: list = []
    transport = Transport(bad=status)
    answers = _export_answers(_client(tmp_path, transport),
                              _dependents(["a-1", "gone", "a-2"]), warnings)
    assert sorted(a["guid"] for a in answers) == ["a-1", "a-2"]
    assert warnings == [f"Answer gone could not be exported (HTTP {status}), so not checked"]
    assert not any("export_associated" in b for b in transport.exports)


def test_an_answer_batch_failing_otherwise_is_skipped_into_the_warnings(tmp_path):
    warnings: list = []
    transport = Transport(single_failure=503)
    answers = _export_answers(_client(tmp_path, transport),
                              _dependents(["gone"] + [f"a{i}" for i in range(10)]), warnings)
    assert answers == []
    assert any("503" in w and "more answer(s)" in w for w in warnings)


def test_an_answer_the_export_refuses_inside_a_200_is_a_warning(tmp_path):
    class Forbidden(Transport):
        def __call__(self, method, url, headers=None, timeout=None, **kw):
            return _response(url, 200, [{"edoc": None, "info": {
                "status": {"status_code": "ERROR", "error_message": "FORBIDDEN"}}}])
    warnings: list = []
    assert _export_answers(_client(tmp_path, Forbidden()), _dependents(["a-1"]), warnings) == []
    assert len(warnings) == 1 and warnings[0].startswith("Answer not exported")
