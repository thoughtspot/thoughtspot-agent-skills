"""Each Model's Data Cache readiness (`corpus.models[].data_cache`, audit/data_cache.py)
and the report's Data Cache view (report/views/datacache.js).

The readiness is decided by the rules that report it (P19-P22): a rule's own `requires`
and `where` over the same derived field, for the rules the run ran. So the view and the
findings cannot disagree, which the parity test below checks over every Data Cache
fixture. The view lists every audited Model with its readiness, reasons and calendars,
filters by readiness and by text, and links each Model to its scorecard.
"""
from __future__ import annotations

import pytest

import audit_rule_fixtures as fx
import report_browser
from ts_cli.audit import run_audit
from ts_cli.audit.context import make_context
from ts_cli.audit.report import compact_payload, render_report

needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")
col, cal = fx.build_cache_column, fx.build_cache_calendar
CACHE_RULES = ("P19", "P20", "P21", "P22", "P23", "P24", "P25", "P26", "P27", "P28")


def _model(guid, name, columns=(), formulas=(), fqn=fx.CACHE_TABLE):
    return {"guid": guid, "model": {"name": name,
                                    "model_tables": [{"name": "ORDERS", "fqn": fqn}],
                                    "columns": list(columns), "formulas": list(formulas)}}


def _estate(calendars=(cal("Retail 445", connection="Warehouse B", connection_id="k-b"),),
            connections=()):
    """Four Models: one on a custom calendar (blocked), one on a connection that
    defines custom calendars (warning), one ready, one with a pass-through formula. Its
    connections were searched (none with a blocking setting) unless `connections` is
    None."""
    a = {"guid": "t-a", "table": {"name": "ORDERS", "connection": {"name": "Warehouse A"},
                                  "columns": [{"name": "SHIP", "properties": {
                                      "calendar": "Retail 445"}}]}}
    b = {"guid": "t-b", "table": {"name": "ORDERS", "connection": {"name": "Warehouse B"},
                                  "columns": []}}
    c = {"guid": "t-c", "table": {"name": "ORDERS", "connection": {"name": "Warehouse C"},
                                  "columns": []}}
    models = [
        _model("m-blocked", "Blocked Sales", [col("Ship Date", "ORDERS::SHIP"),
                                              col("Day", "ORDERS::DAY", calendar="fiscal")],
               fqn="t-a"),
        _model("m-warn", "Warned Sales", [col("Day", "ORDERS::DAY")], fqn="t-b"),
        _model("m-ready", "Ready Sales", [col("Day", "ORDERS::DAY", calendar="calendar")],
               fqn="t-c"),
        _model("m-sql", "Passthrough Sales", [], [
            {"id": "formula_U", "name": "Upper", "expr": "sql_string_op ( \"upper({0})\" , [ORDERS::N] )"}],
               fqn="t-c"),
    ]
    return make_context(models=models, tables={"t-a": a, "t-b": b, "t-c": c},
                        model_guids=[m["guid"] for m in models],
                        calendars=None if calendars is None else list(calendars),
                        connections=None if connections is None else list(connections))


def _dc(data):
    return {m["guid"]: m["data_cache"] for m in data["corpus"]["models"]}


# ── readiness ───────────────────────────────────────────────────────────────

def test_each_model_reads_ready_blocked_or_warning_with_its_reasons():
    dc = _dc(run_audit(None, [], ["P"], ctx=_estate()))
    assert {g: d["readiness"] for g, d in dc.items()} == {
        "m-blocked": "blocked", "m-warn": "warning", "m-ready": "ready", "m-sql": "blocked"}
    assert dc["m-blocked"]["reasons"] == [{"rule": "P19", "effect": "blocks",
                                           "label": "Custom calendar",
                                           "items": ["Ship Date (Retail 445)"]}]
    assert dc["m-blocked"]["calendars_in_use"] == [
        {"column": "Ship Date", "calendar": "Retail 445", "kind": "custom", "set_on": "table"},
        {"column": "Day", "calendar": "fiscal", "kind": "code-based", "set_on": "model"}]
    assert dc["m-warn"]["reasons"] == [{"rule": "P22", "effect": "warns",
                                        "label": "Connection defines custom calendars",
                                        "items": ["Warehouse B (1 custom calendar)"]}]
    assert dc["m-warn"]["connection_calendars"] == [{"connection": "Warehouse B",
                                                     "calendars": ["Retail 445"]}]
    assert dc["m-ready"]["reasons"] == [] and dc["m-ready"]["not_assessed"] == []
    assert dc["m-ready"]["connection_calendars"] == []
    assert dc["m-sql"]["reasons"][0]["items"] == ["Upper"]


def test_without_the_performance_rules_readiness_is_unknown():
    dc = _dc(run_audit(None, [], ["D"], ctx=_estate()))
    assert {d["readiness"] for d in dc.values()} == {"unknown"}
    assert dc["m-ready"]["not_assessed"] == list(CACHE_RULES)
    # what the columns use is still listed: it is read off the TML, not a rule
    assert dc["m-blocked"]["calendars_in_use"][0]["calendar"] == "Retail 445"


def test_a_failed_calendar_search_leaves_the_warning_unchecked_not_the_model_unknown():
    dc = _dc(run_audit(None, [], ["P"], ctx=_estate(calendars=None)))
    assert dc["m-ready"]["readiness"] == "ready" and dc["m-ready"]["not_assessed"] == ["P22"]
    assert dc["m-warn"]["readiness"] == "ready"         # its warning could not be checked
    assert dc["m-warn"]["connection_calendars"] is None
    assert dc["m-blocked"]["readiness"] == "blocked"


def test_a_failed_connection_search_leaves_an_unblocked_model_unknown():
    """P24 blocks, so a Model it could not judge is not "ready": the connection search
    failed, and nothing else stops it."""
    dc = _dc(run_audit(None, [], ["P"], ctx=_estate(connections=None)))
    assert dc["m-ready"]["readiness"] == "unknown" and dc["m-ready"]["not_assessed"] == ["P24"]
    assert dc["m-warn"]["readiness"] == "unknown"
    assert dc["m-blocked"]["readiness"] == "blocked"


def test_the_new_limitations_block_with_their_reasons():
    ctx = _estate(connections=[fx.build_cache_connection("Warehouse C", oauth=True)])
    ctx.metadata = [{"metadata_header": fx.build_cache_header("t-c", source="RDBMS_REDSHIFT",
                                                              connection="Warehouse C")}]
    dc = _dc(run_audit(None, [], ["P"], ctx=ctx))["m-ready"]
    assert dc["readiness"] == "blocked"
    assert [(r["rule"], r["label"], r["items"]) for r in dc["reasons"]] == [
        ("P23", "Source not Snowflake or Databricks", ["ORDERS (RDBMS_REDSHIFT)"]),
        ("P24", "Connection uses OAuth, PrivateLink or a variable", ["Warehouse C (OAuth)"])]


def test_a_blocked_model_also_lists_its_warning():
    ctx = _estate(calendars=[cal("Retail 445")])
    dc = _dc(run_audit(None, [], ["P"], ctx=ctx))["m-blocked"]
    assert [(r["rule"], r["effect"]) for r in dc["reasons"]] == [("P19", "blocks"),
                                                                 ("P22", "warns")]
    assert dc["readiness"] == "blocked"


@pytest.mark.parametrize("build", [
    _estate, lambda: _estate(calendars=None), lambda: _estate(calendars=[cal("R")]),
    fx.perf_custom_calendar_columns, fx.perf_code_based_calendars,
    fx.perf_sql_passthrough_formulas, fx.perf_sql_passthrough_named_only,
    fx.perf_semantic_query_measures, fx.perf_summed_measures,
    fx.perf_connection_custom_calendars, fx.perf_connection_without_custom_calendars,
    fx.perf_non_cloud_sources, fx.perf_cloud_sources, fx.perf_connection_oauth_privatelink,
    fx.perf_connection_service_account, fx.perf_parameterized_table,
    fx.perf_fixed_table_names, fx.perf_parameter_formula,
    fx.perf_parameter_named_in_a_literal, fx.perf_sql_view_source, fx.perf_tables_only,
    fx.perf_rls_beyond_own_columns, fx.perf_rls_own_columns_only,
])
@pytest.mark.parametrize("profile", ["general", "spotter"])
def test_the_view_and_the_findings_agree(build, profile):
    data = run_audit(None, [], ["P"], profile, ctx=build())
    fired = {(f["object_guid"], f["check_id"]) for f in data["findings"]
             if f["check_id"] in CACHE_RULES}
    listed = {(g, r["rule"]) for g, d in _dc(data).items() for r in d["reasons"]}
    assert fired == listed


# ── the report payload ──────────────────────────────────────────────────────

def test_the_payload_compacts_readiness_reasons_and_calendars():
    payload = compact_payload(run_audit(None, [], ["P"], ctx=_estate()))
    by_guid = {payload["L"][cm["mi"]]["g"]: cm["dc"] for cm in payload["C"]["m"]}
    assert by_guid["m-blocked"] == {
        "s": "blocked",
        "r": [{"c": "P19", "b": 1, "l": "Custom calendar", "i": ["Ship Date (Retail 445)"]}],
        "k": [{"n": "Ship Date", "c": "Retail 445", "u": 1, "t": 1},
              {"n": "Day", "c": "fiscal", "u": 0, "t": 0}],
        "cc": [], "na": []}
    assert by_guid["m-warn"]["r"][0]["b"] == 0
    unknown = compact_payload(run_audit(None, [], ["P"], ctx=_estate(calendars=None)))
    assert all(cm["dc"]["cc"] is None for cm in unknown["C"]["m"])


def test_json_from_before_the_view_compacts_without_it():
    data = run_audit(None, [], ["P"], ctx=_estate())
    for m in data["corpus"]["models"]:
        m.pop("data_cache")
    assert all("dc" not in cm for cm in compact_payload(data)["C"]["m"])


# ── the view ────────────────────────────────────────────────────────────────

def _page(**kw):
    return render_report(run_audit(None, [], kw.pop("angles", ["P"]), ctx=_estate(**kw)))


_ROWS = ('window.__extra = Array.prototype.map.call(document.querySelectorAll('
         '"#v-datacache tbody tr[data-state]"), function(tr){ return '
         '[tr.querySelector("a").textContent, tr.getAttribute("data-state")]; });')


@needs_chrome
def test_the_view_lists_every_model_with_its_readiness(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "datacache", actions=_ROWS)
    assert shown["errors"] == [] and shown["active"] == "v-datacache"
    assert sorted(shown["extra"]) == [["Blocked Sales", "blocked"],
                                      ["Passthrough Sales", "blocked"],
                                      ["Ready Sales", "ready"], ["Warned Sales", "warning"]]
    seen = shown["visible"]
    for text in ("Can’t use", "Can use", "Warning", "Custom calendar: Ship Date (Retail 445)",
                 "SQL pass-through: Upper", "Retail 445 (custom): Ship Date (from its Table)",
                 "fiscal (code-based): Day", "4 of 4 Models",
                 "Connection defines custom calendars: Warehouse B (1 custom calendar)"):
        assert text in seen, text
    nav = report_browser.render(_page(), tmp_path, "dashboard", actions=(
        'var a = document.querySelector(\'#sidebar-nav a[href="#datacache"]\');'
        'window.__extra = a && a.textContent;'))
    assert "Data Cache" in nav["extra"]


@needs_chrome
@pytest.mark.parametrize("pill, expected", [
    ("blocked", ["Blocked Sales", "Passthrough Sales"]), ("ready", ["Ready Sales"]),
    ("warning", ["Warned Sales"]),
    ("all", ["Blocked Sales", "Passthrough Sales", "Ready Sales", "Warned Sales"])])
def test_the_pills_filter_by_readiness(tmp_path, pill, expected):
    click = (f'document.querySelector(\'#v-datacache .dc-pill[data-filter="blocked"]\').click();'
             f'document.querySelector(\'#v-datacache .dc-pill[data-filter="{pill}"]\').click();')
    shown = report_browser.render(_page(), tmp_path, "datacache", actions=click + _ROWS)
    assert shown["errors"] == []
    assert sorted(name for name, _ in shown["extra"]) == expected
    assert f"{len(expected)} of 4 Models" in shown["visible"]


@needs_chrome
def test_the_search_filters_by_name_reason_or_calendar(tmp_path):
    def search(term):
        act = ('var s = document.querySelector("#v-datacache input[type=search]");'
               f's.value = {term!r}; s.dispatchEvent(new Event("input"));' + _ROWS)
        shown = report_browser.render(_page(), tmp_path, "datacache", actions=act)
        assert shown["errors"] == []
        return sorted(name for name, _ in shown["extra"])
    # Warned Sales matches on its connection's calendar, Blocked Sales on its column's
    assert search("retail") == ["Blocked Sales", "Warned Sales"]
    assert search("ship date") == ["Blocked Sales"]
    assert search("PASS-THROUGH") == ["Passthrough Sales"]
    assert search("warehouse b") == ["Warned Sales"]
    assert search("nothing like it") == []


@needs_chrome
def test_each_model_links_to_its_scorecard(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "datacache", actions=(
        'window.__extra = Array.prototype.map.call(document.querySelectorAll('
        '"#v-datacache tbody a"), function(a){ return a.getAttribute("href"); });'))
    assert sorted(shown["extra"]) == ["#model/m-blocked", "#model/m-ready",
                                      "#model/m-sql", "#model/m-warn"]


@needs_chrome
def test_a_run_without_p_and_a_failed_search_say_so(tmp_path):
    without = report_browser.render(_page(angles=["D"]), tmp_path, "datacache")
    assert without["errors"] == []
    assert without["visible"].count("Not assessed") >= 4
    assert "did not run" in without["visible"]
    failed = report_browser.render(_page(calendars=None), tmp_path, "datacache")
    assert failed["errors"] == [] and "Not checked: connection calendars" in failed["visible"]
    no_settings = report_browser.render(_page(connections=None), tmp_path, "datacache")
    assert no_settings["errors"] == []
    assert "Not checked: connection settings" in no_settings["visible"]
    assert "Not assessed" in no_settings["visible"]


@needs_chrome
def test_values_are_escaped(tmp_path):
    evil = '<img src=x onerror="window.__pwned=1"><b>x</b>'
    ctx = make_context(
        models=[_model("m-evil", evil, [col(evil, "ORDERS::D", calendar=evil)],
                       [{"id": "f", "name": evil, "expr": "sql_int_op ( \"1\" )"}])],
        tables={fx.CACHE_TABLE: {"guid": fx.CACHE_TABLE, "table": {
            "name": "ORDERS", "connection": {"name": evil}, "columns": []}}},
        calendars=[cal(evil, connection=evil)])
    page = render_report(run_audit(None, [], ["P"], ctx=ctx))
    shown = report_browser.render(page, tmp_path, "datacache", actions=(
        'window.__extra = [document.querySelectorAll("#v-datacache img, #v-datacache b")'
        '.length, window.__pwned || 0];'))
    assert shown["errors"] == [] and shown["extra"] == [0, 0]
    assert "<b>x</b>" in shown["visible"]


@needs_chrome
def test_a_model_link_carries_an_awkward_guid_verbatim(tmp_path):
    """As the sidebar writes it: escaped (an unescaped "&amp;" would read back as "&"),
    never URL-encoded ("%" would become "%25")."""
    guid = 'm%1&amp;2"x'
    ctx = make_context(models=[_model(guid, "Odd")], calendars=[])
    page = render_report(run_audit(None, [], ["P"], ctx=ctx))
    shown = report_browser.render(page, tmp_path, "datacache", actions=(
        'window.__extra = document.querySelector("#v-datacache tbody a").getAttribute("href");'))
    assert shown["errors"] == [] and shown["extra"] == "#model/" + guid
