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
    # A final 1xx or 3xx is not an answer even with a JSON body (`resp.ok` is true for
    # both: it is false only for 4xx/5xx) — skipped like any other non-2xx.
    "302 with JSON": (lambda url: _response(url, 302, {"nl_instructions_info": [
        {"instructions": ["Use net revenue"], "scope": "GLOBAL"}]}),
                      "ThoughtSpot API 302 on POST " + AI_PATH),
    "101 with JSON": (lambda url: _response(url, 101, {"nl_instructions_info": []}),
                      "ThoughtSpot API 101 on POST " + AI_PATH),
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


# --- A final 401 stays fatal; a transient 5xx is retried, then skipped per Model ------
#
# Only the per-Model failures (403/404/5xx, after the client's own retries) are a
# "could not be read". A 401 that survives the client's single re-authentication means
# the credential itself is bad: every later call would fail the same way, so the run
# aborts as it did before the fix — once, not one re-auth and one warning per Model.

def _counting_client(tmp_path: Path, ai_status: int):
    """`_client` whose `ai/instructions/get` answers `ai_status` for EVERY Model, and
    which counts the lookups per Model and the re-authentications."""
    calls: dict = {}
    client = _client(tmp_path, lambda url: _response(url, ai_status, {"error": "nope"}))
    transport = client._session.request.side_effect

    def counting(method, url, headers=None, timeout=None, **kw):
        if url.endswith(AI_PATH):
            guid = (kw.get("json") or {}).get("data_source_identifier")
            calls[guid] = calls.get(guid, 0) + 1
            return _response(url, ai_status, {"error": "nope"})
        return transport(method, url, headers=headers, timeout=timeout, **kw)
    client._session.request.side_effect = counting
    reauth = MagicMock(return_value=(TOKEN, None))
    client._authenticate = reauth
    return client, calls, reauth


def test_a_final_401_aborts_the_run_after_one_reauth(tmp_path, capsys):
    client, calls, reauth = _counting_client(tmp_path, 401)
    with pytest.raises(SystemExit) as exc:
        run_audit(client, ["m-ok", "m-bad"], ["A"], "spotter")
    assert exc.value.code not in (0, None)
    assert reauth.call_count == 1                 # one re-auth, not one per Model
    assert calls == {"m-ok": 2}                   # first Model: initial + post-re-auth try
    err = capsys.readouterr().err
    assert "ThoughtSpot API 401 on POST " + AI_PATH in err
    assert "AI instructions fetch failed for model" not in err   # not a per-Model skip
    assert TOKEN not in err and "Authorization" not in err


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_transient_5xx_is_retried_then_skipped_per_model(status, tmp_path, capsys):
    client, calls, reauth = _counting_client(tmp_path, status)
    out = run_audit(client, ["m-ok", "m-bad"], ["A"], "spotter")
    err = capsys.readouterr().err

    assert calls == {"m-ok": 4, "m-bad": 4}       # the client's 3 retries, per Model
    assert reauth.call_count == 0
    assert f"ThoughtSpot API {status} on POST " in err and "(transient) — retry 3/3" in err
    models = {m["guid"]: m for m in out["corpus"]["models"]}
    assert set(models) == {"m-ok", "m-bad"}                      # the run completed
    assert all(m["ai_analysis"]["instructions_read"] is False for m in models.values())
    assert [f for f in out["findings"] if f["check_id"] == "A3"] == []
    for guid in ("m-ok", "m-bad"):
        assert f"AI instructions fetch failed for model {guid}: ThoughtSpot API {status}" in err
    assert TOKEN not in err and "Authorization" not in err


def _reauth_failure(kind: str) -> Exception:
    """What `_authenticate` raises when the token exchange itself fails other than by a
    401/403 SystemExit: `resp.raise_for_status()` on a 500 (an OIDC account's bad
    password answers 500/10000), or the network dropping during the exchange."""
    if kind == "HTTPError":
        resp = _response("https://example.thoughtspot.cloud/api/rest/2.0/auth/token/full",
                         500, {"debug": "10000"})
        return requests.HTTPError("500 Server Error", response=resp)
    if kind == "JSONDecodeError":   # an SSO/proxy HTML page from the token exchange:
        # requests' JSONDecodeError is BOTH a ValueError and a RequestException
        return requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0)
    if kind == "KeyError":          # a JSON body without `token`
        return KeyError("token")
    if kind == "RuntimeError":      # a bug, not a transport failure
        return RuntimeError("oops: a bug in the request path")
    return requests.ConnectionError("connection reset")


@pytest.mark.parametrize("kind", ["HTTPError", "ConnectionError", "JSONDecodeError"])
def test_a_401_whose_reauthentication_raises_aborts_once(kind, tmp_path, capsys):
    """The re-authentication after a 401 can itself raise a `requests` exception (not
    exit). That is a credential/transport failure every later call would repeat: abort
    the run after ONE token exchange, never swallow it as one Model's failure and re-try
    per Model. The line names the type only — a requests message can carry a URL."""
    client, calls, reauth = _counting_client(tmp_path, 401)
    reauth.side_effect = _reauth_failure(kind)
    with pytest.raises(SystemExit) as exc:
        run_audit(client, ["m-ok", "m-bad"], ["A"], "spotter")
    assert exc.value.code not in (0, None)
    assert reauth.call_count == 1
    assert calls == {"m-ok": 1}
    err = capsys.readouterr().err
    assert "AI instructions fetch failed for model" not in err
    abort = [ln for ln in err.splitlines() if "aborting" in ln]
    assert len(abort) == 1 and kind in abort[0]
    assert "example.thoughtspot.cloud" not in abort[0] and TOKEN not in err


@pytest.mark.parametrize("kind", ["KeyError", "RuntimeError"])
def test_a_non_requests_exception_in_the_request_path_reraises_unchanged(kind, tmp_path, capsys):
    """Anything that is not a `requests` exception is not a transport failure: it is
    re-raised as it is (type, message, traceback intact), never disguised as one, and
    never swallowed per Model. It still happens once — the run stops at the first."""
    client, calls, reauth = _counting_client(tmp_path, 401)
    failure = _reauth_failure(kind)
    reauth.side_effect = failure
    with pytest.raises(type(failure)) as exc:
        run_audit(client, ["m-ok", "m-bad"], ["A"], "spotter")
    assert exc.value is failure
    assert reauth.call_count == 1 and calls == {"m-ok": 1}
    err = capsys.readouterr().err
    assert "AI instructions fetch failed for model" not in err and "aborting" not in err


def test_a_429_aborts_the_run_once(tmp_path, capsys):
    """Rate limited: every later lookup would be refused too, and the client does not
    retry 429 — so stop once with a clear message, never mark Model after Model as
    "could not be read"."""
    client, calls, reauth = _counting_client(tmp_path, 429)
    with pytest.raises(SystemExit) as exc:
        run_audit(client, ["m-ok", "m-bad"], ["A"], "spotter")
    assert exc.value.code not in (0, None)
    assert calls == {"m-ok": 1} and reauth.call_count == 0
    err = capsys.readouterr().err
    assert "ThoughtSpot API 429 on POST " + AI_PATH in err
    assert "rate limited — retry later" in err
    assert "AI instructions fetch failed for model" not in err
    assert TOKEN not in err and "Authorization" not in err


def test_a_404_skips_only_that_model(tmp_path, capsys):
    """404 takes the 403 path (a per-Model skip), pinned on its own."""
    out = run_audit(_client(tmp_path, lambda url: _response(url, 404, {"error": "No such object"})),
                    ["m-ok", "m-bad"], ["A"], "spotter")
    models = {m["guid"]: m for m in out["corpus"]["models"]}
    assert models["m-bad"]["ai_analysis"]["instructions_read"] is False
    assert models["m-ok"]["ai_analysis"]["instructions_read"] is True
    assert ("AI instructions fetch failed for model m-bad: ThoughtSpot API 404 on POST "
            + AI_PATH + " — No such object") in capsys.readouterr().err
