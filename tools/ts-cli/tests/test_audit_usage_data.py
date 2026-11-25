"""The `usage` conditional data: each Model's queries, read from the system Model.

Fetched once per audit, only when a selected rule declares `usage` (H17), from the
system Model "TS: AI and BI Stats" with `searchdata` (audit/usage.py; the live probe is
ts-audit open-items #9). `ctx.usage` is None when not fetched and when any of it could
not be read, so a rule requiring it judges no Model and the report says "Not read",
never "unused". A final 401, a 429 or a `requests` exception aborts the run once;
anything else is a warning naming the status and path, never a response body.
Synthetic GUIDs only.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests
import yaml

from ts_cli.audit.context import build_context, make_context
from ts_cli.audit.engine import scopes
from ts_cli.audit.snapshot import read_snapshot, read_snapshot_needs, write_snapshot
from ts_cli.audit.usage import (HISTORY_QUERY, LAST_USED_QUERY, SYSTEM_MODEL_NAME,
                                WINDOW_QUERY, idle_reading, merge_rows, model_usage)

SEARCHDATA = "/api/rest/2.0/searchdata"
SESSION = "/api/rest/2.0/auth/session/user"
SYS = "00000000-0000-4000-8000-00000000a1b1"
M1, M2, GONE = ("11111111-1111-4111-8111-111111111111",
                "22222222-2222-4222-8222-222222222222",
                "99999999-9999-4999-8999-999999999999")
MODEL = {"guid": M1, "model": {"name": "Sales", "model_tables": [], "columns": [],
                               "formulas": []}}
BODY_MARKER = "body-text-marker-x1"


def _response(status, body, path=SEARCHDATA):
    r = MagicMock()
    r.status_code, r.ok = status, 200 <= status < 400
    r.url = "https://example.thoughtspot.cloud" + path
    if isinstance(body, Exception):
        r.json.side_effect = body
        r.text = "<html>"
    else:
        r.json.return_value = body
        r.text = json.dumps(body)
    return r


def _table(names, rows, available=None):
    t = {"column_names": names, "data_rows": rows,
         "returned_data_row_count": len(rows)}
    t["available_data_row_count"] = len(rows) if available is None else available
    return {"contents": [t]}


#: Each query answered with its columns in an order of its own, as searchdata does.
ANSWERS = {
    HISTORY_QUERY[0]: _table(["Maximum TS Query Start Time", "Minimum TS Query Start Time"],
                             [[1_764_000_000, 1_696_118_400]]),
    LAST_USED_QUERY[0]: _table(["Maximum TS Query Start Time", "Model ID"],
                               [[1_763_900_000, M1], [1_700_000_000, M2],
                                [1_760_000_000, GONE], [1_762_000_000, ""]]),
    WINDOW_QUERY[0]: _table(["Model ID", "Unique Number of User ID", "Queries"],
                            [[M1, 4, 120], [GONE, 1, 7], ["", 9, 50], [None, 1, 1]]),
}


class Client:
    """Model M1 exports; the system Model is found by name; each searchdata query is
    answered from `answers`; `session` answers auth/session/user; `visible` lists the
    LOGICAL_TABLEs the user can see. `override(path, body)` may answer any call first."""

    def __init__(self, answers=None, session=None, visible=(M1, M2), override=None,
                 system=((SYS, SYSTEM_MODEL_NAME),)):
        self.answers = dict(ANSWERS if answers is None else answers)
        self.session = {"current_org": {"id": 0, "name": "Primary"}} if session is None \
            else session
        self.visible = list(visible)
        self.override = override
        self.system = system
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url, None, kw))
        if self.override:
            hit = self.override(url, None)
            if hit is not None:
                return hit
        if url.endswith(SESSION):
            return _response(200, self.session, SESSION)
        return _response(404, {}, url)

    def post(self, url, json=None, **kw):
        self.calls.append(("POST", url, json, kw))
        if self.override:
            hit = self.override(url, json)
            if hit is not None:
                return hit
        if url.endswith("/metadata/tml/export"):
            return _response(200, [{"edoc": yaml.safe_dump(MODEL)}], url)
        if url.endswith(SEARCHDATA):
            return _response(200, self.answers[json["query_string"]])
        if url.endswith("/metadata/search"):
            meta = (json or {}).get("metadata") or [{}]
            if meta[0].get("name_pattern") == SYSTEM_MODEL_NAME:
                return _response(200, [{"metadata_id": g, "metadata_name": n}
                                       for g, n in self.system], url)
            if meta[0] == {"type": "LOGICAL_TABLE"} and "record_offset" in json:
                off, size = json["record_offset"], json["record_size"]
                return _response(200, [{"metadata_id": g} for g in
                                       self.visible[off:off + size]], url)
        return _response(200, [], url)

    def usage_calls(self):
        return [c for c in self.calls if c[1].endswith(SEARCHDATA) or c[1].endswith(SESSION)]


def _read(client):
    return build_context(client, [M1], {"usage"})


# ── when it is fetched, and what it keeps ───────────────────────────────────

def test_usage_is_fetched_only_when_needed():
    client = Client()
    ctx = build_context(client, [M1], set())
    assert client.usage_calls() == [] and ctx.usage is None


def test_values_are_read_by_column_name_not_position():
    ctx = _read(Client())
    usage = ctx.usage
    assert usage["models"][M1] == {"last_used": 1_763_900_000, "queries_180d": 120,
                                   "users_180d": 4}
    assert usage["models"][M2] == {"last_used": 1_700_000_000, "queries_180d": 0,
                                   "users_180d": 0}
    assert usage["history"] == {"start": 1_696_118_400, "end": 1_764_000_000}
    assert usage["window_days"] == 180 and isinstance(usage["fetched_at"], int)
    assert ctx.warnings == []


def test_rows_with_a_blank_model_id_are_dropped_and_counted():
    usage = _read(Client()).usage
    assert "" not in usage["models"] and None not in usage["models"]
    assert usage["blank_rows"] == 1      # counted once, from the all-history rows
    assert set(usage["models"]) == {M1, M2, GONE}


def test_every_call_names_the_system_model_and_asks_for_every_row():
    client = Client()
    _read(client)
    bodies = [b for m, u, b, _ in client.calls if u.endswith(SEARCHDATA)]
    assert [b["query_string"] for b in bodies] == [HISTORY_QUERY[0], LAST_USED_QUERY[0],
                                                   WINDOW_QUERY[0]]
    assert all(b["logical_table_identifier"] == SYS and b["record_size"] == -1
               and b["data_format"] == "COMPACT" for b in bodies)
    assert all(kw.get("raise_for_status") is False for _, _, _, kw in client.usage_calls())


def test_the_window_is_the_keyword_filter_the_probe_settled():
    assert WINDOW_QUERY[0] == ("[Model ID] [Queries] unique count [User ID] "
                               "[TS Query Start Time].'last 180 days'")


def test_models_no_visible_object_matches_are_listed():
    assert _read(Client()).usage["not_visible"] == [GONE]


def test_usage_keeps_guids_and_counts_only():
    usage = _read(Client()).usage
    assert set(usage) == {"org", "window_days", "fetched_at", "history", "blank_rows",
                          "models", "not_visible"}
    assert "Sales" not in json.dumps(usage)


# ── the Org ─────────────────────────────────────────────────────────────────

def test_the_primary_org_is_recorded():
    assert _read(Client()).usage["org"] == {"id": 0, "name": "Primary"}


def test_a_non_primary_org_is_recorded():
    client = Client(session={"current_org": {"id": 7, "name": "Tenant B"}, "id": "u"})
    assert _read(client).usage["org"] == {"id": 7, "name": "Tenant B"}


def test_an_unread_session_leaves_the_org_unnamed_and_the_usage_read(capsys):
    client = Client(override=lambda url, body: _response(403, {"x": BODY_MARKER}, SESSION)
                    if url.endswith(SESSION) else None)
    ctx = _read(client)
    assert ctx.usage["org"] == {"id": None, "name": None}
    assert ctx.usage["models"][M1]["queries_180d"] == 120
    [warning] = ctx.warnings
    assert "ThoughtSpot API 403 on GET " + SESSION in warning and BODY_MARKER not in warning


# ── not read: usage is None, with a warning naming status and path only ──────

def _not_read(client, capsys):
    ctx = _read(client)
    assert ctx.usage is None
    [warning] = [w for w in ctx.warnings if w.startswith("Usage was not read")]
    assert BODY_MARKER not in warning and BODY_MARKER not in capsys.readouterr().err
    assert [m["guid"] for m in ctx.models] == [M1]   # the audit goes on
    return warning


def test_the_system_model_missing_is_not_read(capsys):
    warning = _not_read(Client(system=()), capsys)
    assert SYSTEM_MODEL_NAME in warning and "was not found" in warning


def test_two_objects_with_the_system_models_name_are_not_read(capsys):
    other = "00000000-0000-4000-8000-00000000a1b2"
    warning = _not_read(Client(system=((SYS, SYSTEM_MODEL_NAME), (other, SYSTEM_MODEL_NAME))),
                        capsys)
    assert "2 objects" in warning


def test_a_partial_name_match_is_not_the_system_model(capsys):
    _not_read(Client(system=((SYS, SYSTEM_MODEL_NAME + " (copy)"),)), capsys)


@pytest.mark.parametrize("status", [403, 400, 500])
def test_a_refused_searchdata_is_not_read(status, capsys):
    client = Client(override=lambda url, body: _response(status, {"debug": BODY_MARKER})
                    if url.endswith(SEARCHDATA) else None)
    warning = _not_read(client, capsys)
    assert f"ThoughtSpot API {status} on POST {SEARCHDATA}" in warning


def test_a_refused_system_model_search_is_not_read(capsys):
    def refuse(url, body):
        if url.endswith("/metadata/search") and \
                ((body or {}).get("metadata") or [{}])[0].get("name_pattern"):
            return _response(403, {"debug": BODY_MARKER}, url)
    warning = _not_read(Client(override=refuse), capsys)
    assert "ThoughtSpot API 403 on POST /api/rest/2.0/metadata/search" in warning


@pytest.mark.parametrize("answer, reason", [
    (_table(["Model ID", "Queries"], [[M1, 3]]), "no column Unique Number of User ID"),
    (_table(["Model ID", "Queries", "Unique Number of User ID"], [[M1, 3, 1]], available=2),
     "holds 1 of 2 rows"),
    ({"contents": []}, "not one table"),
    (_table(["Model ID", "Queries", "Unique Number of User ID"], [[M1, 3]]),
     "does not match"),
])
def test_an_answer_that_cannot_be_read_whole_is_not_read(answer, reason, capsys):
    answers = dict(ANSWERS)
    answers[WINDOW_QUERY[0]] = answer
    warning = _not_read(Client(answers=answers), capsys)
    assert reason in warning


def test_a_non_json_answer_is_not_read(capsys):
    client = Client(override=lambda url, body: _response(200, ValueError("Expecting value"))
                    if url.endswith(SEARCHDATA) else None)
    assert "Expecting value" in _not_read(client, capsys)


def test_a_failed_visible_object_search_leaves_the_rest_read(capsys):
    def refuse(url, body):
        if url.endswith("/metadata/search") and \
                ((body or {}).get("metadata") or [{}])[0] == {"type": "LOGICAL_TABLE"}:
            return _response(500, {"debug": BODY_MARKER}, url)
    ctx = _read(Client(override=refuse))
    assert ctx.usage["not_visible"] is None and ctx.usage["models"][M1]
    [warning] = ctx.warnings
    assert "used Models not found in this Org were not checked" in warning
    assert BODY_MARKER not in warning


# ── abort paths ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status, why", [(401, "the credential was refused"),
                                         (429, "rate limited")])
def test_a_final_401_or_429_aborts_the_run(status, why, capsys):
    client = Client(override=lambda url, body: _response(status, {"error": BODY_MARKER})
                    if url.endswith(SEARCHDATA) else None)
    with pytest.raises(SystemExit) as exc:
        _read(client)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert f"ThoughtSpot API {status} on POST {SEARCHDATA}" in err and why in err
    assert BODY_MARKER not in err


def test_a_requests_exception_aborts_once_naming_the_type_only(capsys):
    def boom(url, body):
        if url.endswith(SEARCHDATA):
            raise requests.ConnectionError("https://secret-host.example/x reset")
    with pytest.raises(SystemExit):
        _read(Client(override=boom))
    err = capsys.readouterr().err
    [line] = [ln for ln in err.splitlines() if "aborting" in ln]
    assert "Usage read (POST " + SEARCHDATA + ") failed in the request itself" in line
    assert "ConnectionError" in line and "secret-host" not in err


def test_another_exception_is_a_bug_and_propagates():
    def bug(url, body):
        if url.endswith(SEARCHDATA):
            raise KeyError("oops")
    with pytest.raises(KeyError):
        _read(Client(override=bug))


# ── the pure helpers ────────────────────────────────────────────────────────

def test_merge_rows_keys_by_model_id_and_counts_blanks():
    models, blank = merge_rows([{"Model ID": M1, "Maximum TS Query Start Time": 5},
                                {"Model ID": "  ", "Maximum TS Query Start Time": 6}],
                               [{"Model ID": M1, "Queries": 2, "Unique Number of User ID": 1}])
    assert models == {M1: {"last_used": 5, "queries_180d": 2, "users_180d": 1}}
    assert blank == 1


def test_model_usage_and_idle_reading():
    usage = {"fetched_at": 100 * 86400, "history": {"start": 0},
             "models": {M1: {"last_used": 5 * 86400, "queries_180d": 0, "users_180d": 0},
                        M2: {"last_used": None, "queries_180d": 3, "users_180d": 1}}}
    assert model_usage(usage, M1)["days"] == 95
    assert model_usage(usage, GONE)["never"] is True
    assert idle_reading(usage, M1, 90) == (95, "No query in 95 days; last queried on "
                                               "1970-01-06")
    assert idle_reading(usage, M2, 90) == (None, None)     # no time recorded: says nothing
    assert idle_reading(usage, GONE, 90) == (
        None, "No query in the usage history ThoughtSpot holds, which starts on 1970-01-01")


# ── availability: a rule requiring usage judges no Model when it was not read ─

def test_usage_is_available_only_when_read():
    ctx = make_context(models=[MODEL])
    item = next(scopes.iterate(ctx, "model"))
    assert not scopes.has_data(item, ctx, "usage")
    assert scopes.has_data(item, make_context(models=[MODEL], usage={"models": {}}), "usage")


# ── snapshots ───────────────────────────────────────────────────────────────

def test_a_snapshot_round_trips_usage_and_its_absence(tmp_path):
    read = _read(Client()).usage
    for i, value in enumerate((read, None)):
        snap = tmp_path / f"s{i}"
        write_snapshot(make_context(models=[MODEL], usage=value), snap, ["H"])
        assert read_snapshot(snap)[0].usage == value


def test_a_snapshot_written_before_usage_reads_it_as_not_fetched(tmp_path):
    snap = tmp_path / "old"
    write_snapshot(make_context(models=[MODEL]), snap, ["D"], needs=set())
    manifest = json.loads((snap / "manifest.json").read_text())
    manifest["files"].remove("usage.json")
    (snap / "usage.json").unlink()
    (snap / "manifest.json").write_text(json.dumps(manifest))
    ctx, _, needs = read_snapshot_needs(snap)
    assert ctx.usage is None and "usage" not in needs


def test_an_h_replay_of_a_snapshot_without_usage_is_refused_naming_h17(tmp_path):
    from typer.testing import CliRunner

    from ts_cli.audit import data_needs
    from ts_cli.cli import app
    import audit_rule_fixtures as fx
    old = tmp_path / "old"
    write_snapshot(fx.human_model_recently_used(), old, ["H"],
                   needs=data_needs(["H"]) - {"usage"})
    res = CliRunner().invoke(app, ["audit", "run", "--snapshot-in", str(old), "--angles", "H"])
    assert res.exit_code != 0
    out = " ".join(res.output.split())
    assert "usage" in out and "H17" in out
    # D reads none of it, so it still replays; a capture with usage replays H
    assert CliRunner().invoke(app, ["audit", "run", "--snapshot-in", str(old), "--angles", "D",
                                    "-o", str(tmp_path / "d.json")]).exit_code == 0
    new = tmp_path / "new"
    write_snapshot(fx.human_model_idle(), new, ["H"], needs=data_needs(["H"]))
    res = CliRunner().invoke(app, ["audit", "run", "--snapshot-in", str(new), "--angles", "H",
                                   "-o", str(tmp_path / "h.json")])
    assert res.exit_code == 0, res.output
    found = json.loads((tmp_path / "h.json").read_text())["findings"]
    assert [f["severity"] for f in found if f["check_id"] == "H17"] == ["LOW"]
