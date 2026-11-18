"""One unreadable object must not end the audit's metadata header search.

`build_context` asks `metadata/search` for the header of every scoped object, Model
sources included, 50 to a request. A source whose TML export failed is asked for too, so
one refused id is more likely than before. With the client's default
`raise_for_status=True`, a refused batch was `SystemExit(1)`: the whole audit ended.
Now, as the TML export does (`_export_items`): a batch refused as a bad request (400 or
404) is retried one id at a time, and an id that still fails is skipped; any other
refusal would recur for every id, so its batch (or the rest of a retry) is skipped
whole. Each warning carries the status and the path, never the response body. A final
401 or a 429 still aborts the run once.

Driven through the REAL `ThoughtSpotClient.request` over a fake transport, as
test_audit_model_export_batches.py is, because a 4xx takes its real shape there.
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
_SEARCH = "/api/rest/2.0/metadata/search"
_NO_SETS = {"sets": {}, "incomplete": [], "notes": []}
#: A response body the warning must never carry.
_BODY_SECRET = "S3cret-in-the-error-body-5e1"


def _response(url: str, status: int, body) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r.url = url
    r._content = _json.dumps(body).encode()
    r.headers["Content-Type"] = "application/json"
    return r


#: A Model over three sources: t1 and t2 export, `gone` does not (and is refused by the
#: header search too).
MODEL = {"guid": "m1", "model": {"name": "Sales", "columns": [], "model_tables": [
    {"name": "A", "fqn": "t1"}, {"name": "B", "fqn": "t2"}, {"name": "C", "fqn": "gone"}]}}


class Transport:
    """Exports Model m1 with Tables t1 and t2. The header search refuses any request
    naming `gone` with `bad`; `all_fail` refuses every one; `single_failure`, when set,
    is the status every one-id request gets instead."""

    def __init__(self, bad: int = 400, all_fail: bool = False, single_failure: int = 0):
        self.bad, self.all_fail, self.single_failure = bad, all_fail, single_failure
        self.searches: list = []

    def __call__(self, method, url, headers=None, timeout=None, **kw):
        body = kw.get("json") or {}
        if url.endswith(_EXPORT):
            tables = [{"guid": g, "table": {"name": g, "columns": []}} for g in ("t1", "t2")]
            return _response(url, 200, [{"edoc": yaml.safe_dump(d)}
                                        for d in [MODEL] + tables])
        if url.endswith(_SEARCH) and body.get("include_headers"):
            ids = [m["identifier"] for m in body.get("metadata", [])]
            self.searches.append(ids)
            if len(ids) == 1 and self.single_failure:
                return _response(url, self.single_failure, {"debug": _BODY_SECRET})
            if self.all_fail or "gone" in ids:
                return _response(url, self.bad, {"debug": f"no such object {_BODY_SECRET}"})
            return _response(url, 200, [{"metadata_header": {"id": g, "type": "ONE_TO_ONE_LOGICAL"}}
                                        for g in ids])
        return _response(url, 200, [])


def _run(tmp_path: Path, transport: Transport):
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
        return build_context(client, ["m1"], {"model_tml"})


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch("ts_cli.client.time.sleep"):
        yield


@pytest.mark.parametrize("status", [400, 404])
def test_a_refused_id_costs_only_its_own_header(tmp_path, capsys, status):
    transport = Transport(bad=status)
    ctx = _run(tmp_path, transport)
    assert sorted(h["metadata_header"]["id"] for h in ctx.metadata) == ["m1", "t1", "t2"]
    [warning] = [w for w in ctx.warnings if "Metadata search" in w]
    assert warning == (f"Metadata search returned {status} on POST {_SEARCH} for gone, "
                       "so its header was not read")
    # the batch, then each id alone
    assert len(transport.searches) == 1 + 4
    assert all(len(ids) == 1 for ids in transport.searches[1:])
    logs = "".join(capsys.readouterr())
    assert _BODY_SECRET not in logs and _BODY_SECRET not in "".join(ctx.warnings)


def test_every_id_refused_still_finishes_the_audit(tmp_path):
    ctx = _run(tmp_path, Transport(all_fail=True))
    assert ctx.metadata == [] and len(ctx.models) == 1
    assert len([w for w in ctx.warnings if "Metadata search" in w]) == 4


@pytest.mark.parametrize("status", [403, 500])
def test_any_other_refusal_skips_its_batch_without_a_retry(tmp_path, capsys, status):
    """Not a bad id: one request per id would fail the same way."""
    transport = Transport(bad=status)
    ctx = _run(tmp_path, transport)
    assert ctx.metadata == [] and len(ctx.models) == 1
    assert len(transport.searches) == 1
    [warning] = [w for w in ctx.warnings if "Metadata search" in w]
    assert warning == (f"Metadata search batch 1 returned {status} on POST {_SEARCH}, so "
                       "the headers of its 4 object(s) were not read")
    assert _BODY_SECRET not in "".join(capsys.readouterr())


def test_a_retry_that_meets_another_refusal_stops_and_skips_the_rest(tmp_path):
    transport = Transport(bad=400, single_failure=500)
    ctx = _run(tmp_path, transport)
    assert ctx.metadata == []
    assert len(transport.searches) == 2          # the batch, then the first id alone
    [warning] = [w for w in ctx.warnings if "Metadata search" in w]
    assert warning.startswith("Metadata search returned 500 on POST " + _SEARCH + " for ")
    assert warning.endswith("; the retry stopped there, skipping 3 more object(s)")


def test_a_429_still_aborts_once(tmp_path, capsys):
    """Rate limited: every later request would get the same, so the run stops once, as
    the other fetches do (context._FATAL_STATUSES; a final 401 is the same path)."""
    transport = Transport(bad=429, all_fail=True)
    with pytest.raises(SystemExit):
        _run(tmp_path, transport)
    assert len(transport.searches) == 1
    err = capsys.readouterr().err
    assert f"ThoughtSpot API 429 on POST {_SEARCH}" in err
    assert _BODY_SECRET not in err
