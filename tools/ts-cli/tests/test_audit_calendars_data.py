"""The `calendars` conditional data: every connection's registered custom calendars.

Fetched once per audit, paged (`custom_calendar/search.py`; the live probe in ts-audit
open-items #16 found the endpoint answers 10 by default and none for `record_size: -1`),
and only when a selected rule declares `calendars`. `ctx.calendars` is None when not
fetched and when the search failed, a list (perhaps empty) when it answered — so a rule
requiring it skips a Model after a failure rather than read "no calendars". The error
handling is the AI-instructions lookup's: a final 401, a 429 or a `requests` exception
aborts the run once; anything else is a warning.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests
import yaml

from ts_cli.audit.context import CALENDAR_KEYS, build_context, make_context
from ts_cli.audit.engine import scopes
from ts_cli.audit.snapshot import read_snapshot, read_snapshot_needs, write_snapshot

SEARCH = "/api/rest/2.0/calendars/search"
MODEL = {"guid": "m1", "model": {"name": "Sales", "model_tables": [
    {"name": "ORDERS", "fqn": "t1"}], "columns": [], "formulas": []}}


def _calendars(n):
    return [{"calendar_id": f"cal-{i}", "calendar_name": f"Calendar {i}",
             "connection_id": "conn-a", "connection_name": "Warehouse A",
             "data_warehouse_type": "SNOWFLAKE", "author_name": "an author",
             "modification_time_in_millis": "0"} for i in range(n)]


def _response(status, body):
    r = MagicMock()
    r.status_code, r.ok = status, 200 <= status < 400
    r.url = "https://example.thoughtspot.cloud" + SEARCH
    if isinstance(body, Exception):
        r.json.side_effect = body
    else:
        r.json.return_value = body
    r.text = json.dumps(body) if not isinstance(body, Exception) else "<html>"
    return r


class Client:
    """Model `m1` exports; `calendars/search` answers `search(body)`; calls recorded."""

    def __init__(self, search):
        self.search = search
        self.calls = []

    def post(self, url, json=None, **kw):
        self.calls.append((url, json, kw))
        if url.endswith("/metadata/tml/export"):
            return _response(200, [{"edoc": yaml.safe_dump(MODEL)}])
        if (json or {}).get("include_dependent_objects"):  # a clean "no dependents"
            return _response(200, [{"metadata_id": m["identifier"],
              "dependent_objects": {"dependents": {m["identifier"]: {}}}} for m in json["metadata"]])
        if url.endswith(SEARCH):
            return self.search(json)
        return _response(200, [])

    def searches(self):
        return [(j, kw) for u, j, kw in self.calls if u.endswith(SEARCH)]


def _paged(calendars):
    def search(body):
        off, size = body["record_offset"], body["record_size"]
        return _response(200, calendars[off:off + size])
    return search


def test_calendars_are_fetched_only_when_needed():
    client = Client(_paged(_calendars(3)))
    ctx = build_context(client, ["m1"], set())
    assert client.searches() == [] and ctx.calendars is None


def test_every_page_is_fetched_and_each_calendar_trimmed():
    client = Client(_paged(_calendars(130)))
    ctx = build_context(client, ["m1"], {"calendars"})
    assert len(ctx.calendars) == 130
    assert all(set(c) == set(CALENDAR_KEYS) for c in ctx.calendars)
    assert "author_name" not in json.dumps(ctx.calendars)
    bodies = [b for b, _ in client.searches()]
    assert [b["record_offset"] for b in bodies] == [0, 100]
    assert all(kw.get("raise_for_status") is False for _, kw in client.searches())
    assert ctx.warnings == []


def test_no_calendars_is_an_empty_list_not_none():
    ctx = build_context(Client(_paged([])), ["m1"], {"calendars"})
    assert ctx.calendars == []


@pytest.mark.parametrize("answer, reason", [
    (_response(403, {"error": "denied"}), "ThoughtSpot API 403 on POST " + SEARCH),
    (_response(500, {"debug": "boom"}), "ThoughtSpot API 500 on POST " + SEARCH),
    (_response(302, []), "ThoughtSpot API 302 on POST " + SEARCH),
    (_response(200, ValueError("Expecting value")), "Expecting value"),
    (_response(200, {"calendars": []}), "not a list of calendars"),
])
def test_a_failed_search_is_a_warning_and_reads_as_not_fetched(answer, reason, capsys):
    ctx = build_context(Client(lambda body: answer), ["m1"], {"calendars"})
    assert ctx.calendars is None
    [warning] = [w for w in ctx.warnings if "calendar" in w]
    assert warning.startswith("Custom calendar search failed, so connection calendars "
                              "were not checked") and reason in warning
    assert [m["guid"] for m in ctx.models] == ["m1"]   # the audit goes on


def test_a_failure_on_a_later_page_drops_the_partial_list():
    pages = iter([_response(200, _calendars(100)), _response(500, {"debug": "x"})])
    ctx = build_context(Client(lambda body: next(pages)), ["m1"], {"calendars"})
    assert ctx.calendars is None


@pytest.mark.parametrize("status, why", [(401, "the credential was refused"),
                                         (429, "rate limited")])
def test_a_final_401_or_429_aborts_the_run(status, why, capsys):
    with pytest.raises(SystemExit) as exc:
        build_context(Client(lambda body: _response(status, {"error": "no"})), ["m1"],
                      {"calendars"})
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert f"ThoughtSpot API {status} on POST {SEARCH}" in err and why in err


def test_a_requests_exception_aborts_once_naming_the_type_only(capsys):
    def boom(body):
        raise requests.ConnectionError("https://secret-host.example/x reset")
    with pytest.raises(SystemExit):
        build_context(Client(boom), ["m1"], {"calendars"})
    err = capsys.readouterr().err
    [line] = [ln for ln in err.splitlines() if "aborting" in ln]
    assert "Custom calendar search failed in the request itself" in line
    assert "ConnectionError" in line and "secret-host" not in err


def test_another_exception_is_a_bug_and_propagates():
    def bug(body):
        raise KeyError("oops")
    with pytest.raises(KeyError):
        build_context(Client(bug), ["m1"], {"calendars"})


# ── availability: a rule requiring calendars skips when they are unknown ────

def test_calendars_are_available_only_when_fetched():
    item = next(scopes.iterate(make_context(models=[MODEL]), "model"))
    assert not scopes.has_data(item, make_context(models=[MODEL]), "calendars")
    assert scopes.has_data(item, make_context(models=[MODEL], calendars=[]), "calendars")
    assert make_context().calendars is None and make_context(calendars=[]).calendars == []


# ── snapshots ───────────────────────────────────────────────────────────────

def test_a_snapshot_round_trips_calendars_and_their_absence(tmp_path):
    for i, value in enumerate(([], [{k: "x" for k in CALENDAR_KEYS}], None)):
        snap = tmp_path / f"s{i}"
        write_snapshot(make_context(models=[MODEL], calendars=value), snap, ["P"])
        assert read_snapshot(snap)[0].calendars == value


def test_a_snapshot_written_before_calendars_reads_them_as_not_fetched(tmp_path):
    snap = tmp_path / "old"
    write_snapshot(make_context(models=[MODEL], calendars=[]), snap, ["D"], needs=set())
    manifest = json.loads((snap / "manifest.json").read_text())
    manifest["files"].remove("calendars.json")
    (snap / "calendars.json").unlink()
    (snap / "manifest.json").write_text(json.dumps(manifest))
    ctx, _, needs = read_snapshot_needs(snap)
    assert ctx.calendars is None and "calendars" not in needs


# ── table_columns: what a Model column's column_id resolves to ──────────────

def test_table_columns_resolve_by_alias_else_name_and_column_types_read_them():
    ctx = make_context(tables={
        "t1": {"guid": "t1", "table": {"name": "ORDERS", "columns": [
            {"name": "DAY", "properties": {"calendar": "Retail"},
             "db_column_properties": {"data_type": "DATE"}},
            {"name": "", "db_column_properties": {"data_type": "INT64"}}]}}})
    model = {"model": {"model_tables": [{"name": "ORDERS", "fqn": "t1", "alias": "O"},
                                        {"name": "MISSING", "fqn": "t9"}]}}
    cols = ctx.table_columns(model)
    assert list(cols) == ["O::DAY"]
    assert cols["O::DAY"]["properties"]["calendar"] == "Retail"
    assert ctx.column_types(model) == {"O::DAY": "DATE"}
