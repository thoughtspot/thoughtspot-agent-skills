"""BL-510: one deleted Model must not drop its whole export batch.

Driven through the REAL `ThoughtSpotClient.request` over a fake transport, as
`test_audit_ai_lookup_failures.py` is, because that is where a 4xx takes its real shape:
without `raise_for_status=False` the first refused batch becomes `SystemExit(1)`, which
ends the run with no Models at all. A fake whose `post` ignores its keyword arguments
cannot see that.

The API refuses a whole `metadata/tml/export` request when one identifier in it no longer
exists. The audit retries such a batch (400 or 404) one Model at a time and reports only
the Models that still fail; any other failure — a server error, auth — would fail again
for every Model, so the rest of the batch is reported whole, at batch level or mid-retry.
"""
from __future__ import annotations

import copy
import json as _json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from ts_cli.audit.context import build_context
from ts_cli.client import ThoughtSpotClient

_EXPORT = "/metadata/tml/export"
_NO_SETS = {"sets": {}, "incomplete": [], "notes": []}


def _response(url: str, status: int, body) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = url
    r._content = _json.dumps(body).encode()
    r.headers["Content-Type"] = "application/json"
    return r


def _model(guid: str) -> dict:
    return {"guid": guid, "model": {"name": guid, "model_tables": [], "columns": []}}


class Transport:
    """Answers Model export requests: `gone` in a request makes it fail with `bad`
    (default 400); `single_failure`, when set, is the status every one-GUID request for a
    healthy Model gets instead of 200. Records every export request body."""

    def __init__(self, bad: int = 400, single_failure: int = 0):
        self.bad, self.single_failure = bad, single_failure
        self.exports: list = []

    def __call__(self, method, url, headers=None, timeout=None, **kw):
        body = kw.get("json") or {}
        if not url.endswith(_EXPORT):
            return _response(url, 200, [])
        self.exports.append(body)
        ids = [m["identifier"] for m in body.get("metadata", [])]
        if "gone" in ids:
            return _response(url, self.bad, {"debug": "object not found"})
        if len(ids) == 1 and self.single_failure:
            return _response(url, self.single_failure, {"debug": "service unavailable"})
        return _response(url, 200, [{"edoc": yaml.safe_dump(_model(g))} for g in ids])


def _run(tmp_path: Path, guids: list, transport: Transport):
    profile = {"name": "Fake", "base_url": "https://example.thoughtspot.cloud",
               "username": "u@example.com", "token_env": "THOUGHTSPOT_TOKEN_FAKE"}
    with patch("ts_cli.client.load_profiles", return_value={"Fake": profile}):
        client = ThoughtSpotClient("Fake")
    client._token_path = lambda: tmp_path / "token.txt"
    client._expiry_path = lambda: tmp_path / "expiry.txt"
    client._token = "fake-token"
    client._session = MagicMock()
    client._session.request.side_effect = transport
    with patch("ts_cli.audit.context.discover_sets", return_value=copy.deepcopy(_NO_SETS)):
        return build_context(client, guids, {"model_tml"})


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("ts_cli.client.time.sleep"):
        yield


@pytest.mark.parametrize("status", [400, 404])
def test_a_deleted_model_costs_only_itself(tmp_path, status):
    transport = Transport(bad=status)
    ctx = _run(tmp_path, ["m1", "gone", "m2"], transport)
    assert [m["guid"] for m in ctx.models] == ["m1", "m2"]          # order kept
    assert [w for w in ctx.warnings if "gone" in w] == [
        f"Model gone could not be exported (HTTP {status}), so not checked"]
    assert all(b["export_associated"] and b["export_fqn"] for b in transport.exports)


def test_a_two_model_batch_is_retried(tmp_path):
    ctx = _run(tmp_path, ["m1", "gone"], Transport())
    assert [m["guid"] for m in ctx.models] == ["m1"]


def test_a_failure_mid_retry_stops_the_retry(tmp_path):
    """The batch 400s, then the first single request 503s: the remaining Models would
    fail the same way, so they are reported together instead of one call each."""
    transport = Transport(single_failure=503)
    guids = ["gone"] + [f"m{i}" for i in range(30)]
    ctx = _run(tmp_path, guids, transport)
    assert ctx.models == []
    assert len(transport.exports) <= 6                   # batch + gone + one 503 (with retries)
    assert any("503" in w and "29 more model(s)" in w for w in ctx.warnings)


def test_a_lone_model_is_not_retried(tmp_path):
    transport = Transport()
    ctx = _run(tmp_path, ["gone"], transport)
    assert ctx.models == [] and len(transport.exports) == 1
    assert any("gone" in w for w in ctx.warnings)
