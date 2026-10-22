"""A failed `ai/instructions/get` lookup is "could not be read", and the audit goes on.

Driven through the REAL `ThoughtSpotClient.request` over a fake transport (its
`requests.Session`), because that is where an HTTP failure takes its real shape: with
the default `raise_for_status=True` a 4xx/5xx becomes one stderr line and
`SystemExit(1)`, which `except Exception` does not catch — so until 12b fix round 3
one Model's failed lookup aborted the whole `ts audit run` (re-review N6). A fake
whose `post` raises a plain exception (the earlier tests) cannot show that.

What must hold for a 403 and a 500 on one Model of two:
- the run completes and audits both Models;
- that Model is recorded as not read (`instructions_read: false`) and A3 skips it
  (A3 requires ai_instructions), while the other Model is judged as usual;
- the warning names the Model and carries the secret-free reason
  (`client.format_http_error`, never the request headers or the bearer token);
- the report says "Could not be read" for it.
A non-HTTP failure (a 200 whose body is not JSON) is still caught the same way.
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
from ts_cli.audit.report import compact_payload, render_report
from ts_cli.client import ThoughtSpotClient

TOKEN = "fake-bearer-SECRET-XYZ"  # a fake bearer, checked never to be echoed
AI_PATH = "/api/rest/2.0/ai/instructions/get"
MODELS = {
    "m-ok": {"guid": "m-ok", "model": {"name": "Readable", "model_tables": [
        {"name": "ORDERS", "fqn": "t1"}], "columns": []}},
    "m-bad": {"guid": "m-bad", "model": {"name": "Unreadable", "model_tables": [
        {"name": "ORDERS", "fqn": "t1"}], "columns": []}},
}


def _response(url: str, status: int, body) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = url
    r._content = (body if isinstance(body, bytes) else _json.dumps(body).encode())
    r.headers["Content-Type"] = "application/json"
    return r


def _client(tmp_path: Path, ai_failure) -> ThoughtSpotClient:
    """A real client whose transport answers: Model TML export, empty searches, and
    `ai/instructions/get` — empty for m-ok, `ai_failure` for m-bad."""
    profile = {"name": "Fake", "base_url": "https://example.thoughtspot.cloud",
               "username": "u@example.com", "token_env": "THOUGHTSPOT_TOKEN_FAKE"}
    with patch("ts_cli.client.load_profiles", return_value={"Fake": profile}):
        client = ThoughtSpotClient("Fake")
    client._token_path = lambda: tmp_path / "token.txt"
    client._expiry_path = lambda: tmp_path / "expiry.txt"
    client._token = TOKEN

    def transport(method, url, headers=None, timeout=None, **kw):
        body = kw.get("json") or {}
        if url.endswith("/metadata/tml/export"):
            ids = [m["identifier"] for m in body.get("metadata", [])]
            return _response(url, 200, [{"edoc": yaml.safe_dump(MODELS[g])}
                                        for g in ids if g in MODELS])
        if url.endswith(AI_PATH):
            if body.get("data_source_identifier") == "m-bad":
                return ai_failure(url)
            return _response(url, 200, {"nl_instructions_info": []})
        return _response(url, 200, [])
    client._session = MagicMock()
    client._session.request.side_effect = transport
    return client


FAILURES = {
    "403": (lambda url: _response(url, 403, {"error": "Access denied to this object"}),
            "ThoughtSpot API 403 on POST " + AI_PATH + " — Access denied to this object"),
    "500": (lambda url: _response(url, 500, {"debug": "internal failure 42"}),
            "ThoughtSpot API 500 on POST " + AI_PATH + " — internal failure 42"),
    "non-JSON 200": (lambda url: _response(url, 200, b"<html>not json</html>"),
                     "Expecting value"),
}


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("ts_cli.client.time.sleep"):
        yield


@pytest.mark.parametrize("kind", list(FAILURES))
def test_a_failed_lookup_is_recorded_and_the_audit_completes(kind, tmp_path, capsys):
    failure, reason = FAILURES[kind]
    out = run_audit(_client(tmp_path, failure), ["m-ok", "m-bad"], ["A"], "spotter")
    err = capsys.readouterr().err

    models = {m["guid"]: m for m in out["corpus"]["models"]}
    assert set(models) == {"m-ok", "m-bad"}                      # the run completed
    assert models["m-bad"]["ai_analysis"]["instructions_read"] is False
    assert models["m-ok"]["ai_analysis"]["instructions_read"] is True
    a3 = [f["object_guid"] for f in out["findings"] if f["check_id"] == "A3"]
    assert a3 == ["m-ok"]                                       # A3 skips the unread Model
    assert f"AI instructions fetch failed for model m-bad: {reason}" in err
    assert TOKEN not in err and "Authorization" not in err
    order = [m["guid"] for m in out["corpus"]["models"]]
    compact = compact_payload(out)["C"]["m"]
    assert compact[order.index("m-bad")]["ai"]["rd"] is False
    assert compact[order.index("m-ok")]["ai"]["rd"] is True


@pytest.mark.parametrize("kind", ["403", "500"])
def test_without_the_fix_the_real_client_would_have_aborted(kind, tmp_path):
    """The failure shape the fix exists for: the real client, asked to raise, exits."""
    failure, _ = FAILURES[kind]
    client = _client(tmp_path, failure)
    with pytest.raises(SystemExit):
        client.post(AI_PATH, json={"data_source_identifier": "m-bad"})


@pytest.mark.skipif(report_browser.CHROME is None, reason="headless Chrome not installed")
@pytest.mark.parametrize("kind", ["403", "500"])
def test_the_report_says_could_not_be_read(kind, tmp_path):
    failure, _ = FAILURES[kind]
    out = run_audit(_client(tmp_path, failure), ["m-ok", "m-bad"], ["A"], "spotter")
    html = render_report(out)
    bad = report_browser.render(html, _dir(tmp_path, "bad"), "model/m-bad")
    ok = report_browser.render(html, _dir(tmp_path, "ok"), "model/m-ok")
    assert bad["errors"] == [] and ok["errors"] == []
    assert "Could not be read" in bad["text"]
    assert "None — no AI instructions on this Model." in ok["text"]
    assert "Could not be read" not in ok["text"]


def _dir(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    return d
