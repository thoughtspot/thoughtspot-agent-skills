"""The `connections` conditional data: each connection's derived settings, for P24.

`connection/search` with `include_details` answers each connection with
`details.configuration`, a JSON string of its settings, credentials included (live probe,
the SE demo cluster, 2026-11-18; ts-audit open-items #17). The audit parses it in the
fetch and keeps only `{id, name, type, oauth, oauth_m2m, privatelink, parameterized,
parameterized_connection}` (the last from each connection's metadata header): no
configuration value may reach the context, a snapshot, the audit JSON, a warning or a
log line. Fetched once per audit, paged, only when a selected rule declares it; None when
not fetched or the search failed, as for `calendars`.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import requests
import yaml

from ts_cli.audit import run_audit
from ts_cli.audit.connection_facts import CONNECTION_KEYS, connection_facts
from ts_cli.audit.context import build_context, make_context
from ts_cli.audit.engine import scopes
from ts_cli.audit.report import render_report
from ts_cli.audit.snapshot import read_snapshot, read_snapshot_needs, write_snapshot

SEARCH = "/api/rest/2.0/connection/search"
SECRETS = ("S3cret-PW-41d", "S3cret-OAUTH-9f2", "S3cret-KEY-77a",
           "example-account.privatelink.snowflakecomputing.com", "S3cret-DBX-c11")
MODEL = {"guid": "m1", "model": {"name": "Sales", "model_tables": [
    {"name": "ORDERS", "fqn": "t1"}, {"name": "V_SALES", "fqn": "v1"}],
    "columns": [], "formulas": []}}
TABLE = {"guid": "t1", "table": {"name": "ORDERS", "connection": {"name": "Warehouse A"},
                                 "db": "DB", "schema": "S", "db_table": "ORDERS",
                                 "columns": []}}


def _config(**settings):
    return json.dumps(settings)


def _connection(i, name="Warehouse A", **settings):
    return {"id": f"conn-{i}", "name": name, "data_warehouse_type": "SNOWFLAKE",
            "details": {"type": "RDBMS_SNOWFLAKE",
                        "configuration": _config(**settings) if settings else _config(
                            accountName="acme", user="svc", password=SECRETS[0])}}


SECRET_CONNECTIONS = [
    _connection(0, "Warehouse A", accountName=SECRETS[3], user="svc", password=SECRETS[0],
                OAuth2ClientId="cid", OAuth2Secret=SECRETS[1]),
    _connection(1, "Warehouse B", host="dbc.example", client_id="sp",
                client_secret=SECRETS[4], oauth_pvt_key=SECRETS[2]),
    {"id": "conn-2", "name": "Broken", "data_warehouse_type": "REDSHIFT",
     "details": {"configuration": "{not json " + SECRETS[0]}},
]


# ── the facts ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("settings, oauth", [
    ({"OAuth2ClientId": "x"}, True), ({"oauth_pvt_key": "x"}, True),
    ({"OAUTH": "x"}, True), ({"client_id": "x", "client_secret": "y"}, True),
    ({"Client_ID": "x", "CLIENT_SECRET": "y"}, True),
    ({"client_id": "x"}, False), ({"user": "u", "password": "p", "host": "h"}, False),
    ({"auth": {"oauth_scope": "x"}}, True), ({"note": "uses oauth", "host": "h"}, False),
])
def test_oauth_is_read_from_key_names_at_any_depth(settings, oauth):
    assert connection_facts(_connection(0, **settings))["oauth"] is oauth


@pytest.mark.parametrize("settings, privatelink", [
    ({"accountName": "acme.privatelink"}, True),
    ({"host": "acme.PRIVATELINK.snowflakecomputing.com"}, True),
    ({"ACCOUNTNAME": "x.privatelink.y"}, True),
    ({"host": "acme.snowflakecomputing.com"}, False),
    # no host or account name to read it from: unknown, not "no"
    ({"note": "privatelink", "client_id": "x"}, None), ({"host": 12, "user": "u"}, None),
])
def test_privatelink_is_read_from_the_host_or_account_value(settings, privatelink):
    assert connection_facts(_connection(0, **settings))["privatelink"] is privatelink


@pytest.mark.parametrize("settings, parameterized", [
    ({"accountName": "${ACCOUNT}"}, True), ({"db": {"name": " ${DB_NAME} "}}, True),
    ({"roles": ["${ROLE}"]}, True), ({"accountName": "pre_${ACCOUNT}"}, False),
    ({"accountName": "acme"}, False),
])
def test_a_whole_template_token_is_a_parameterized_connection(settings, parameterized):
    assert connection_facts(_connection(0, **settings))["parameterized"] is parameterized


@pytest.mark.parametrize("settings, oauth", [
    ({"OAuth2ClientId": ""}, False), ({"oauth_enabled": False}, False),
    ({"oauth_enabled": "false"}, False), ({"oauth_enabled": " FALSE "}, False),
    ({"OAUTH": None}, False), ({"oauth": "null"}, False), ({"oauth": {}}, False),
    ({"oauth": []}, False), ({"client_id": "x", "client_secret": ""}, False),
    ({"client_id": None, "client_secret": "y"}, False),
    ({"oauth_enabled": True}, True), ({"oauth": {"client": "x"}}, True),
    ({"OAuth2Secret": "******"}, True),
])
def test_an_oauth_setting_counts_only_when_it_is_set(settings, oauth):
    assert connection_facts(_connection(0, **settings))["oauth"] is oauth


@pytest.mark.parametrize("settings, privatelink", [
    ({"host": ["x.privatelink.example"]}, True),
    ({"accountName": [["acme.privatelink.example"]]}, True),
    ({"host": ["acme.example"]}, False),
    # no host key, or a host that holds no text: unknown
    ({"hosts": ["x.privatelink.example"]}, None),
    ({"host": [{"name": "x.privatelink.example"}]}, None),
])
def test_a_lists_items_come_with_the_lists_key(settings, privatelink):
    assert connection_facts(_connection(0, **settings))["privatelink"] is privatelink


@pytest.mark.parametrize("configuration", [
    "{}", '{"user": "u", "password": "p"}', '{"note": "x", "warehouse": "w"}'])
def test_a_configuration_without_the_keys_the_readings_use_is_unknown(configuration):
    """A parsed `{}`, or settings naming no host, account name, OAuth or client key, say
    nothing about OAuth or PrivateLink: unknown, never "no"."""
    facts = connection_facts({"id": "c", "name": "N", "details": {"configuration": configuration}})
    assert (facts["oauth"], facts["oauth_m2m"], facts["privatelink"],
            facts["parameterized"]) == (None, None, None, None)


def test_facts_keep_ids_names_and_type_only():
    facts = connection_facts(SECRET_CONNECTIONS[0])
    assert facts == {"id": "conn-0", "name": "Warehouse A", "type": "SNOWFLAKE",
                     "oauth": True, "oauth_m2m": False, "privatelink": True,
                     "parameterized": False, "parameterized_connection": None}
    assert tuple(facts) == CONNECTION_KEYS


def test_oauth_from_a_client_id_and_secret_alone_is_marked_m2m():
    m2m = connection_facts({"id": "c", "name": "N", "details": {
        "configuration": '{"client_id": "x", "client_secret": "******", "host": "h"}'}})
    named = connection_facts({"id": "c", "name": "N", "details": {
        "configuration": '{"OAuth2ClientId": "x", "client_id": "x", "client_secret": "y"}'}})
    assert (m2m["oauth"], m2m["oauth_m2m"]) == (True, True)
    assert (named["oauth"], named["oauth_m2m"]) == (True, False)


@pytest.mark.parametrize("details", [{}, {"configuration": None},
                                     {"configuration": "not json"},
                                     {"configuration": "[1, 2]"}, "a string"])
def test_an_unreadable_configuration_is_unknown_not_no(details):
    facts = connection_facts({"id": "c", "name": "N", "details": details})
    assert (facts["oauth"], facts["privatelink"], facts["parameterized"]) == (None, None, None)


def test_a_configuration_already_a_mapping_and_the_type_fallback():
    facts = connection_facts({"id": "c", "name": "N", "details": {
        "type": "RDBMS_DATABRICKS", "configuration": {"host": "x.privatelink.y"}}})
    assert facts["type"] == "RDBMS_DATABRICKS" and facts["privatelink"] is True
    assert connection_facts("not a connection") is None


# ── the fetch ───────────────────────────────────────────────────────────────

def _response(status, body):
    r = MagicMock()
    r.status_code, r.ok = status, 200 <= status < 400
    r.url = "https://example.thoughtspot.cloud" + SEARCH
    if isinstance(body, Exception):
        r.json.side_effect = body
    else:
        r.json.return_value = body
    r.text = "<body>"
    return r


def _is_connection_header_search(json):
    return [m.get("type") for m in (json or {}).get("metadata") or []] == ["CONNECTION"]


class Client:
    """Model `m1` (on Table t1 and a SQL View v1) exports; `connection/search` answers
    `search(body)`; the CONNECTION header search answers `headers(body)` (none by
    default); the metadata search answers headers for what it is asked."""

    def __init__(self, search, headers=None):
        self.search = search
        self.headers = headers or (lambda body: _response(200, []))
        self.calls = []

    def post(self, url, json=None, **kw):
        self.calls.append((url, json, kw))
        if url.endswith("/metadata/search") and _is_connection_header_search(json):
            return self.headers(json)
        if url.endswith("/metadata/tml/export"):
            return _response(200, [{"edoc": yaml.safe_dump(MODEL)}, {"edoc": yaml.safe_dump(TABLE)},
                                   {"edoc": yaml.safe_dump({"guid": "v1", "sql_view": {
                                       "name": "V_SALES", "sql_query": "select 1"}})}])
        if url.endswith(SEARCH):
            return self.search(json)
        if url.endswith("/metadata/search") and (json or {}).get("include_headers"):
            ids = [m["identifier"] for m in json["metadata"]]
            return _response(200, [{"metadata_header": {"id": g}} for g in ids])
        return _response(200, [])

    def searches(self):
        return [j for u, j, _ in self.calls if u.endswith(SEARCH)]


def _paged(connections):
    def search(body):
        off, size = body["record_offset"], body["record_size"]
        return _response(200, connections[off:off + size])
    return search


def _connection_header(i, configs=None, **flags):
    """A CONNECTION metadata/search row; `configs` stands for whatever else a header
    carries, which the audit must not keep."""
    header = {"id": f"conn-{i}", "name": f"C{i}", "configs": configs or {"pw": SECRETS[0]}}
    header.update(flags)
    return {"metadata_id": f"conn-{i}", "metadata_header": header}


def test_the_parameterized_flag_is_read_from_each_connections_header():
    """connection/search returns a parameterized connection's settings without its
    `${var}` tokens (open-items #17), so the flag comes from the connection's metadata
    header: `parameterizedConnection`, or `isParameterized`, true. A header without
    either key, or no header at all, leaves it unknown, never "no"."""
    conns = [_connection(i, f"C{i}") for i in range(5)]
    headers = [_connection_header(0, parameterizedConnection=True, isParameterized=False),
               _connection_header(1, parameterizedConnection=False, isParameterized=True),
               _connection_header(2, parameterizedConnection=False, isParameterized=False),
               _connection_header(3)]
    client = Client(_paged(conns), _paged(headers))
    ctx = build_context(client, ["m1"], {"connections"})
    assert [c["parameterized_connection"] for c in ctx.connections] == [
        True, True, False, None, None]
    [ask] = [j for u, j, _ in client.calls
             if u.endswith("/metadata/search") and _is_connection_header_search(j)]
    assert ask["include_headers"] is True and ask["record_offset"] == 0
    assert SECRETS[0] not in json.dumps(ctx.connections)


def test_the_header_search_pages_like_the_connection_search():
    conns = [_connection(i, f"C{i}") for i in range(130)]
    headers = [_connection_header(i, parameterizedConnection=(i == 120)) for i in range(130)]
    client = Client(_paged(conns), _paged(headers))
    ctx = build_context(client, ["m1"], {"connections"})
    flagged = [c["name"] for c in ctx.connections if c["parameterized_connection"]]
    assert flagged == ["C120"]
    assert all(c["parameterized_connection"] is False for c in ctx.connections
               if c["name"] != "C120")


def test_a_failed_header_search_leaves_the_flag_unknown_and_warns_without_a_body(capsys):
    refused = _response(403, {"error": SECRETS[0]})
    refused.text = f'{{"error": "{SECRETS[0]}"}}'
    ctx = build_context(Client(_paged(SECRET_CONNECTIONS), lambda body: refused), ["m1"],
                        {"connections"})
    assert len(ctx.connections) == 3
    assert all(c["parameterized_connection"] is None for c in ctx.connections)
    [warning] = [w for w in ctx.warnings if "header search" in w]
    assert warning == ("Connection header search failed, so the connections' parameterized "
                       "flags were not checked: ThoughtSpot API 403 on POST "
                       "/api/rest/2.0/metadata/search")
    assert SECRETS[0] not in "".join(capsys.readouterr())


def test_connections_are_fetched_only_when_needed():
    client = Client(_paged(SECRET_CONNECTIONS))
    assert build_context(client, ["m1"], set()).connections is None
    assert client.searches() == []


def test_every_page_is_fetched_with_details_and_reduced_to_facts():
    many = [_connection(i, f"C{i}") for i in range(130)]
    client = Client(_paged(many))
    ctx = build_context(client, ["m1"], {"connections"})
    assert len(ctx.connections) == 130
    assert all(tuple(c) == CONNECTION_KEYS for c in ctx.connections)
    assert [(b["record_offset"], b["record_size"], b["include_details"])
            for b in client.searches()] == [(0, 100, True), (100, 100, True)]


def test_the_metadata_search_asks_for_every_model_source_sql_views_included():
    client = Client(_paged([]))
    build_context(client, ["m1"], set())
    asked = {m["identifier"] for u, j, _ in client.calls
             if u.endswith("/metadata/search") and (j or {}).get("include_headers")
             for m in j["metadata"]}
    assert asked == {"m1", "t1", "v1"}


@pytest.mark.parametrize("answer, reason", [
    (_response(403, {"error": "denied"}), "ThoughtSpot API 403 on POST " + SEARCH),
    (_response(200, ValueError("Expecting value")), "Expecting value"),
    (_response(200, {"connections": []}), "not a list of connections"),
])
def test_a_failed_search_is_a_warning_and_reads_as_not_fetched(answer, reason):
    ctx = build_context(Client(lambda body: answer), ["m1"], {"connections"})
    assert ctx.connections is None
    [warning] = [w for w in ctx.warnings if "Connection search" in w]
    assert warning.startswith("Connection search failed, so connection settings were not "
                              "checked") and reason in warning


def test_a_refused_search_warns_with_its_status_and_path_never_its_body(capsys):
    """An error body can quote anything, a configuration value included."""
    refused = _response(403, {"error": f"denied: {SECRETS[0]}"})
    refused.text = f'{{"error": "denied: {SECRETS[0]}"}}'
    ctx = build_context(Client(lambda body: refused), ["m1"], {"connections"})
    [warning] = [w for w in ctx.warnings if "Connection search" in w]
    assert warning == ("Connection search failed, so connection settings were not checked: "
                       f"ThoughtSpot API 403 on POST {SEARCH}")
    assert SECRETS[0] not in "".join(capsys.readouterr())


def test_a_page_with_an_entry_that_is_not_a_connection_fails_the_search():
    """Dropping the odd entry left a full page one short, which read as the last page:
    150 connections paged as 99, silently. The search fails instead, so no rule reads a
    partial list as complete."""
    many = [_connection(i, f"C{i}") for i in range(150)]
    many[5] = "not a connection"
    ctx = build_context(Client(_paged(many)), ["m1"], {"connections"})
    assert ctx.connections is None
    [warning] = [w for w in ctx.warnings if "Connection search" in w]
    assert warning.startswith("Connection search failed") and "not a list of connections" in warning


@pytest.mark.parametrize("status", [401, 429])
def test_a_final_401_or_429_aborts_the_run(status, capsys):
    refused = _response(status, {"error": SECRETS[0]})
    refused.text = f'{{"error": "{SECRETS[0]}"}}'
    with pytest.raises(SystemExit):
        build_context(Client(lambda body: refused), ["m1"], {"connections"})
    err = capsys.readouterr().err
    assert f"ThoughtSpot API {status} on POST {SEARCH}" in err and SECRETS[0] not in err


def test_a_requests_exception_aborts_once_naming_the_type_only(capsys):
    def boom(body):
        raise requests.ConnectionError("https://secret-host.example reset")
    with pytest.raises(SystemExit):
        build_context(Client(boom), ["m1"], {"connections"})
    err = capsys.readouterr().err
    assert "Connection search failed in the request itself" in err
    assert "ConnectionError" in err and "secret-host" not in err


def test_connections_are_available_only_when_fetched():
    item = next(scopes.iterate(make_context(models=[MODEL]), "model"))
    assert not scopes.has_data(item, make_context(models=[MODEL]), "connections")
    assert scopes.has_data(item, make_context(models=[MODEL], connections=[]), "connections")


def test_a_snapshot_written_before_connections_reads_them_as_not_fetched(tmp_path):
    snap = tmp_path / "old"
    write_snapshot(make_context(models=[MODEL], connections=[]), snap, ["D"], needs=set())
    manifest = json.loads((snap / "manifest.json").read_text())
    manifest["files"].remove("connections.json")
    (snap / "connections.json").unlink()
    (snap / "manifest.json").write_text(json.dumps(manifest))
    ctx, _, needs = read_snapshot_needs(snap)
    assert ctx.connections is None and "connections" not in needs


# ── no configuration value leaks ────────────────────────────────────────────

def test_no_configuration_value_reaches_the_context_snapshot_json_report_or_logs(
        tmp_path, capsys):
    client = Client(_paged(SECRET_CONNECTIONS))
    ctx = build_context(client, ["m1"], {"connections", "calendars"})
    snap = tmp_path / "snap"
    write_snapshot(ctx, snap, ["P"], needs={"connections", "calendars"})
    replayed = read_snapshot(snap)[0]
    data = run_audit(None, [], ["A", "D", "H", "P", "S"], ctx=replayed)
    page = render_report(data)
    texts = {"context": json.dumps(ctx.connections) + json.dumps(ctx.warnings),
             "snapshot": "".join(p.read_text() for p in snap.iterdir()),
             "audit JSON": json.dumps(data, default=str), "report": page,
             "logs": "".join(capsys.readouterr())}
    for where, text in texts.items():
        for secret in SECRETS:
            assert secret not in text, f"a configuration value reached the {where}"
    assert {c["name"] for c in ctx.connections} == {"Warehouse A", "Warehouse B", "Broken"}
    assert next(c for c in ctx.connections if c["name"] == "Broken")["oauth"] is None
