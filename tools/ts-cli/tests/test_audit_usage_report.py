"""Usage in the audit JSON and the report: the header's Org line, the scorecard numbers,
the Dashboard's Last used column and the Cleanup view's lists.

Usage that was fetched but not read reads "Not read" wherever it would show, never
"unused"; usage no selected rule fetched shows nowhere. Synthetic names and GUIDs only.
"""
from __future__ import annotations

import pytest

import audit_rule_fixtures as fx
import report_browser
from ts_cli.audit import data_needs, run_audit
from ts_cli.audit.context import ALWAYS_FETCHED, make_context
from ts_cli.audit.report import compact_payload, render_report

needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")

IDLE, NEVER, BUSY = ("aaaaaaaa-0000-4000-8000-000000000001",
                     "aaaaaaaa-0000-4000-8000-000000000002",
                     "aaaaaaaa-0000-4000-8000-000000000003")
GONE_A, GONE_B = ("dddddddd-0000-4000-8000-00000000000a",
                  "dddddddd-0000-4000-8000-00000000000b")
H_NEEDS = data_needs(["H"]) | ALWAYS_FETCHED


def _usage(org=None, not_visible=(GONE_A, GONE_B), **kw):
    return fx.build_usage({IDLE: 120, BUSY: 10,
                           GONE_A: {"last_used": fx.USAGE_READ_AT - 5 * 86400,
                                    "queries_180d": 40, "users_180d": 6},
                           GONE_B: {"last_used": fx.USAGE_READ_AT - 200 * 86400,
                                    "queries_180d": 0, "users_180d": 0}},
                          org=org, not_visible=not_visible, **kw)


def _ctx(usage):
    models = [fx.build_human_model(name, guid) for name, guid in
              (("Idle Sales", IDLE), ("Never Sales", NEVER), ("Busy Sales", BUSY))]
    return make_context(models=models, model_guids=[IDLE, NEVER, BUSY], usage=usage)


def _data(usage, needs=H_NEEDS, angles=("H",)):
    return run_audit(None, [], list(angles), ctx=_ctx(usage), fetched_needs=set(needs))


# ── the audit JSON and the payload ──────────────────────────────────────────

def test_the_corpus_carries_each_models_usage_and_the_reading():
    corpus = _data(_usage())["corpus"]
    by_guid = {m["guid"]: m["usage"] for m in corpus["models"]}
    assert by_guid[IDLE] == {"last_used": fx.USAGE_READ_AT - 120 * 86400, "days": 120,
                             "queries_180d": 12, "users_180d": 3, "never": False}
    assert by_guid[BUSY]["days"] == 10 and by_guid[BUSY]["queries_180d"] == 12
    assert by_guid[NEVER] == {"last_used": None, "days": None, "queries_180d": 0,
                              "users_180d": 0, "never": True}
    usage = corpus["usage"]
    assert usage["org"] == {"id": 0, "name": "Primary"} and usage["primary"] is True
    assert usage["window_days"] == 180 and usage["fetched_at"] == fx.USAGE_READ_AT
    # most queried first; GUIDs and counts only
    assert [g["guid"] for g in usage["gone"]] == [GONE_A, GONE_B]
    # a reading from before 0.224.0 records no Org: each ID's `orgs` is empty
    assert usage["gone"][0] == {"guid": GONE_A, "last_used": fx.USAGE_READ_AT - 5 * 86400,
                                "days": 5, "queries_180d": 40, "users_180d": 6, "orgs": []}
    assert usage["org_read"] is None and usage["orgs"] == []


def test_an_audited_model_is_never_listed_as_gone():
    corpus = _data(_usage(not_visible=(GONE_A, IDLE)))["corpus"]
    assert [g["guid"] for g in corpus["usage"]["gone"]] == [GONE_A]


def test_unread_usage_is_none_in_the_corpus_with_no_model_entries():
    corpus = _data(None)["corpus"]
    assert corpus["usage"] is None and "usage" in corpus["fetched_needs"]
    assert all("usage" not in m for m in corpus["models"])


def test_the_payload_compacts_the_reading():
    payload = compact_payload(_data(_usage(org={"id": 7, "name": "Tenant B"})))
    us = payload["C"]["us"]
    assert (us["o"], us["oi"], us["pr"], us["w"], us["at"]) == (
        "Tenant B", 7, 0, 180, fx.USAGE_READ_AT)
    assert us["g"][0] == [GONE_A, 40, 6, fx.USAGE_READ_AT - 5 * 86400, []]
    by_mi = {payload["L"][cm["mi"]]["g"]: cm["us"] for cm in payload["C"]["m"]}
    assert by_mi[NEVER] == {"l": None, "d": None, "q": 0, "u": 0, "n": 1}
    assert by_mi[BUSY]["d"] == 10


def test_json_from_before_usage_compacts_without_it():
    data = _data(_usage())
    del data["corpus"]["usage"]
    for m in data["corpus"]["models"]:
        del m["usage"]
    payload = compact_payload(data)
    assert "us" not in payload["C"] and all("us" not in cm for cm in payload["C"]["m"])


def test_unread_usage_compacts_to_null():
    assert compact_payload(_data(None))["C"]["us"] is None


# ── the rendered report ─────────────────────────────────────────────────────

_DASH = ('var th = Array.prototype.map.call(document.querySelectorAll(".heatmap thead th"),'
         ' function(t){ return t.textContent; });'
         'var rows = {}; Array.prototype.forEach.call(document.querySelectorAll('
         '".heatmap tbody tr"), function(tr){ var c = tr.querySelector(".usage-cell");'
         ' rows[tr.querySelector(".model-name a").textContent] = c ? [c.textContent,'
         ' c.getAttribute("title")] : null; });'
         'var meta = document.querySelector("#v-dashboard .usage-meta");'
         'var note = document.querySelector("#v-dashboard .usage-note");'
         'window.__extra = {th: th, rows: rows, meta: meta && meta.textContent,'
         ' note: note && note.textContent, imgs: document.querySelectorAll("#v-dashboard img").length};')


def _dash(data, tmp_path):
    shown = report_browser.render(render_report(data), tmp_path, "dashboard", actions=_DASH)
    assert shown["errors"] == [], shown["errors"]
    return shown["extra"]


@needs_chrome
def test_the_dashboard_names_the_org_and_shows_last_used(tmp_path):
    seen = _dash(_data(_usage()), tmp_path)
    # a reading with no Orgs (as 0.223.0 took it) from the Primary Org: not known whose
    assert seen["meta"] == ("Usage read from the Primary Org on 2026-11-25; which Orgs it "
                            "covers was not read")
    assert seen["note"] is None          # the Primary Org's usage needs no note
    assert "Last used" in seen["th"]
    assert seen["rows"]["Idle Sales"][0] == "120 days ago"
    assert seen["rows"]["Idle Sales"][1] == ("Last queried on 2026-07-28; 12 queries by 3 "
                                             "users in the last 180 days (usage read from the Primary Org; which Orgs it covers was not read)")
    assert seen["rows"]["Never Sales"] == [
        "No query", "No query in the usage history, which starts on 2023-10-01 "
                    "(usage read from the Primary Org; which Orgs it covers was not read)"]


@needs_chrome
def test_a_run_outside_the_primary_org_says_the_usage_is_that_orgs_only(tmp_path):
    seen = _dash(_data(_usage(org={"id": 7, "name": "Tenant B"})), tmp_path)
    assert seen["meta"] == "Usage of the Org ‘Tenant B’, read on 2026-11-25"
    assert seen["note"] == ("Usage counts the queries in the Org ‘Tenant B’ only: this audit "
                            "ran outside the Primary Org, so queries made in other Orgs are "
                            "not counted.")


@needs_chrome
def test_an_unnamed_org_gets_a_note_too(tmp_path):
    seen = _dash(_data(_usage(org={"id": None, "name": None})), tmp_path)
    assert seen["meta"].startswith("Usage of an Org whose name could not be read")
    assert seen["note"].startswith("The Org this usage belongs to could not be read")


@needs_chrome
def test_unread_usage_reads_not_read_on_the_dashboard(tmp_path):
    seen = _dash(_data(None), tmp_path)
    assert seen["meta"] == "Usage: Not read" and "Last used" in seen["th"]
    # with no usage H17 judged nothing, so only Models with other findings are listed;
    # whichever are, each cell says Not read
    assert seen["rows"] and all(r[0] == "Not read" for r in seen["rows"].values())


@needs_chrome
def test_no_last_used_column_when_no_rule_fetched_usage(tmp_path):
    needs = data_needs(["D"]) | ALWAYS_FETCHED
    data = _data(_usage(), needs=needs, angles=("D", "H"))
    data["corpus"]["usage"] = None
    for m in data["corpus"]["models"]:
        m.pop("usage", None)
    seen = _dash(data, tmp_path)
    assert "Last used" not in seen["th"] and seen["meta"] is None
    assert all(r is None for r in seen["rows"].values())


@needs_chrome
def test_data_built_strings_are_escaped(tmp_path):
    seen = _dash(_data(_usage(org={"id": 7, "name": "<img src=x onerror=alert(1)>"})),
                 tmp_path)
    assert seen["imgs"] == 0
    assert seen["meta"] == "Usage of the Org ‘<img src=x onerror=alert(1)>’, read on 2026-11-25"


_STATS = ('window.__extra = Array.prototype.map.call(document.querySelectorAll('
          '".scorecard-header .usage-stat"), function(s){ return [s.querySelector(".stat-lbl")'
          '.textContent, s.querySelector(".stat-val").textContent]; });')


@needs_chrome
def test_the_scorecard_header_shows_last_used_queries_and_users(tmp_path):
    shown = report_browser.render(render_report(_data(_usage())), tmp_path,
                                  f"model/{BUSY}", actions=_STATS)
    assert shown["errors"] == []
    assert shown["extra"] == [["Last used", "10 days ago"], ["Queries (180 days)", "12"],
                              ["Users (180 days)", "3"]]
    never = report_browser.render(render_report(_data(_usage())), tmp_path,
                                  f"model/{NEVER}", actions=_STATS)
    assert never["extra"] == [["Last used", "No query"], ["Queries (180 days)", "0"],
                              ["Users (180 days)", "0"]]


@needs_chrome
def test_the_scorecard_header_reads_not_read(tmp_path):
    shown = report_browser.render(render_report(_data(None)), tmp_path, f"model/{BUSY}",
                                  actions=_STATS)
    assert shown["errors"] == []
    assert shown["extra"] == [["Last used", "Not read"], ["Queries (180 days)", "Not read"],
                              ["Users (180 days)", "Not read"]]


_CLEANUP = ('var gone = document.querySelector("#v-cleanup .usage-gone");'
            'window.__extra = {head: gone && gone.querySelector("h3").textContent,'
            ' rows: gone ? Array.prototype.map.call(gone.querySelectorAll("tbody tr"),'
            ' function(tr){ return Array.prototype.map.call(tr.cells, function(c){'
            ' return c.textContent; }); }) : null,'
            ' text: gone && gone.textContent,'
            ' h17_text: (function(){ var s = document.querySelector('
            '"#v-cleanup .usage-unjudged .empty-state"); return s && s.textContent; })(),'
            ' sections: Array.prototype.map.call(document.querySelectorAll('
            '"#v-cleanup .cleanup-section h3"), function(h){ return h.textContent; }),'
            ' idle: Array.prototype.map.call(document.querySelectorAll('
            '"#v-cleanup .cleanup-section"), function(s){ return s; }).filter(function(s){'
            ' return s.querySelector("h3").textContent.indexOf("H17") !== -1; }).map('
            'function(s){ return Array.prototype.map.call(s.querySelectorAll("tbody tr"),'
            ' function(tr){ return tr.cells[2].textContent; }); })[0] || null};')


@needs_chrome
def test_the_cleanup_view_lists_idle_models_and_models_that_no_longer_exist(tmp_path):
    shown = report_browser.render(render_report(_data(_usage(model_orgs={}))), tmp_path,
                                  "cleanup", actions=_CLEANUP)
    assert shown["errors"] == []
    seen = shown["extra"]
    # Orgs read, none recorded for either ID: this Org's list is first, and empty
    assert seen["head"] == "Used in this Org, but not found (0)"
    assert [s for s in seen["sections"] if s.startswith("Org not recorded")] == [
        "Org not recorded (2)"]
    seen = report_browser.render(render_report(_data(_usage(model_orgs={
        GONE_A: [{"id": "0", "name": "Primary", "last_used": fx.USAGE_READ_AT - 5 * 86400}],
        GONE_B: [{"id": "0", "name": "Primary", "last_used": fx.USAGE_READ_AT - 200 * 86400}],
    }))), tmp_path, "cleanup", actions=_CLEANUP)["extra"]
    assert seen["head"] == "Used in this Org, but not found (2)"
    assert seen["rows"] == [[GONE_A, "40", "6", "2026-11-20"], [GONE_B, "0", "0", "2026-05-09"]]
    assert "keeps no names" in seen["text"]
    assert sorted(seen["idle"]) == ["Idle Sales", "Never Sales"]


@needs_chrome
def test_the_cleanup_view_reads_not_read(tmp_path):
    shown = report_browser.render(render_report(_data(None)), tmp_path, "cleanup",
                                  actions=_CLEANUP)
    assert shown["errors"] == []
    assert shown["extra"]["head"] == "Used, but not found in this Org"
    assert "Not read: the audit could not read usage" in shown["extra"]["text"]
    # H17's own section must not read as clean: no "(0)", no "No findings."
    [h17] = [h for h in shown["extra"]["sections"] if "H17" in h]
    assert h17.endswith("— H17 — Not read") and "(0)" not in h17
    assert shown["extra"]["h17_text"] == ("Not read: the audit could not read usage, so "
                                          "this rule judged no Model.")


@needs_chrome
def test_an_unlisted_visible_set_reads_not_read_in_cleanup(tmp_path):
    usage = _usage()
    usage["not_visible"] = None
    shown = report_browser.render(render_report(_data(usage)), tmp_path, "cleanup",
                                  actions=_CLEANUP)
    assert "the objects this user can see could not be listed" in shown["extra"]["text"]


@needs_chrome
def test_h17_says_not_collected_in_cleanup_when_no_rule_fetched_usage(tmp_path):
    """A D-only run never fetched usage: H17's Cleanup section says so, never "(0)"."""
    data = _data(None, needs=data_needs(["D"]) | ALWAYS_FETCHED, angles=("D",))
    shown = report_browser.render(render_report(data), tmp_path, "cleanup", actions=_CLEANUP)
    assert shown["errors"] == []
    [h17] = [h for h in shown["extra"]["sections"] if "H17" in h]
    assert h17.endswith("— H17 — Not collected") and "(0)" not in h17
    assert shown["extra"]["h17_text"].startswith("Not collected for this selection")
    assert shown["extra"]["head"] is None        # no usage list either


_GROUPS = ('document.getElementById("cm-group-by-check").click();'
           'document.getElementById("cm-show-all-checks").click();'
           'var out = {}; Array.prototype.forEach.call(document.querySelectorAll('
           '"#v-crossmodel tr.group-header"), function(tr){'
           ' var next = tr.nextElementSibling;'
           ' out[tr.querySelector(".gh-id").textContent] = [tr.querySelector(".gh-count")'
           '.textContent, next && next.className === "group-empty" ? next.textContent : null]; });'
           'window.__extra = out;')


@needs_chrome
def test_h17_says_not_read_in_the_cross_model_groups(tmp_path):
    shown = report_browser.render(render_report(_data(None)), tmp_path, "crossmodel",
                                  actions=_GROUPS)
    assert shown["errors"] == []
    assert shown["extra"]["H17"] == [
        "Not read", "Not read: the audit could not read usage, so this rule judged no Model."]
    # another rule with no findings still reads as before
    clean = [v for k, v in shown["extra"].items() if k != "H17" and v[0] == "0 findings"]
    assert clean and all(v[1] == "No findings — all checks passed" for v in clean)
    read = report_browser.render(render_report(_data(_usage())), tmp_path, "crossmodel",
                                 actions=_GROUPS)
    assert read["extra"]["H17"][0] == "2 findings"


# ── a history shorter than the window, or than H17's idle days ──────────────

def _short(history_days):
    usage = fx.build_usage({IDLE: 20, BUSY: 10,
                            GONE_A: {"last_used": fx.USAGE_READ_AT - 5 * 86400,
                                     "queries_180d": 40, "users_180d": 6}},
                           start=fx.USAGE_READ_AT - history_days * 86400,
                           not_visible=(GONE_A,))
    return render_report(_data(usage))


def test_the_corpus_records_how_many_days_the_history_covers():
    corpus = _data(fx.build_usage({BUSY: 10}, start=fx.USAGE_READ_AT - 30 * 86400))["corpus"]
    assert corpus["usage"]["history_days"] == 30 and corpus["usage"]["idle_days"] == 90
    payload = compact_payload(_data(fx.build_usage({BUSY: 10},
                                                   start=fx.USAGE_READ_AT - 30 * 86400)))
    assert (payload["C"]["us"]["hd"], payload["C"]["us"]["id"]) == (30, 90)


_PARTIAL = ("Partly judged: the usage history starts on 2026-10-26, 30 days before the "
            "read, under the 90 days H17 needs; Models with no query in it were not judged.")


@needs_chrome
def test_a_30_day_history_says_h17_judged_only_part(tmp_path):
    page = _short(30)
    cleanup = report_browser.render(page, tmp_path, "cleanup", actions=_CLEANUP)
    assert cleanup["errors"] == []
    [h17] = [h for h in cleanup["extra"]["sections"] if "H17" in h]
    assert h17.endswith("— H17 — Partly judged") and "(0)" not in h17
    assert cleanup["extra"]["h17_text"] == _PARTIAL
    assert "No findings" not in cleanup["visible"].split("H17")[1].split("Used, but")[0]
    groups = report_browser.render(page, tmp_path, "crossmodel", actions=_GROUPS)
    assert groups["extra"]["H17"] == ["Partly judged", _PARTIAL]


_HEADS = ('window.__extra = Array.prototype.map.call(document.querySelectorAll('
          '"#v-cleanup .usage-gone thead th"), function(th){ return th.textContent; });')


@needs_chrome
def test_a_30_day_history_labels_the_counts_with_its_span(tmp_path):
    page = _short(30)
    stats = report_browser.render(page, tmp_path, f"model/{BUSY}", actions=_STATS)
    assert stats["extra"] == [["Last used", "10 days ago"], ["Queries (since 2026-10-26)", "12"],
                              ["Users (since 2026-10-26)", "3"]]
    heads = report_browser.render(page, tmp_path, "cleanup", actions=_HEADS)
    assert heads["extra"] == ["Model ID", "Queries (since 2026-10-26)",
                              "Users (since 2026-10-26)", "Last queried"]


_TITLE = ('var s = document.querySelector(".scorecard-header .usage-stat");'
          'window.__extra = s && s.getAttribute("title");')


@needs_chrome
def test_a_30_day_history_words_the_last_used_tooltip_by_its_span(tmp_path):
    shown = report_browser.render(_short(30), tmp_path, f"model/{BUSY}", actions=_TITLE)
    assert shown["extra"] == ("Last queried on 2026-11-15; 12 queries by 3 users in the "
                              "30 days the history holds (usage read from the Primary Org; which Orgs it covers was not read)")


@needs_chrome
def test_a_400_day_history_keeps_the_usual_wording(tmp_path):
    page = _short(400)
    cleanup = report_browser.render(page, tmp_path, "cleanup", actions=_CLEANUP)
    [h17] = [h for h in cleanup["extra"]["sections"] if "H17" in h]
    # the history is long enough to judge "never queried": Never Sales is reported
    assert h17.endswith("— H17 (1)") and cleanup["extra"]["h17_text"] is None
    assert cleanup["extra"]["idle"] == ["Never Sales"]
    groups = report_browser.render(page, tmp_path, "crossmodel", actions=_GROUPS)
    assert groups["extra"]["H17"][0] == "1 finding"
    stats = report_browser.render(page, tmp_path, f"model/{BUSY}", actions=_STATS)
    assert stats["extra"][1] == ["Queries (180 days)", "12"]
    heads = report_browser.render(page, tmp_path, "cleanup", actions=_HEADS)
    assert heads["extra"][1] == "Queries (180 days)"
    title = report_browser.render(page, tmp_path, f"model/{BUSY}", actions=_TITLE)
    assert title["extra"].endswith("12 queries by 3 users in the last 180 days (usage read from the Primary Org; which Orgs it covers was not read)")


# ── the Org each used Model was queried in (since 0.224.0) ──────────────────

GONE_C, GONE_D = ("dddddddd-0000-4000-8000-00000000000c",
                  "dddddddd-0000-4000-8000-00000000000d")
_DAYS = 86400
MARKUP = "<img src=x onerror=alert(1)>"


def _org(oid, name, days):
    return {"id": oid, "name": name, "last_used": fx.USAGE_READ_AT - days * _DAYS}


def _org_usage(org=None, model_orgs="all"):
    """GONE_A was queried in the Primary Org, GONE_B in Tenant B, GONE_C in Tenant B and
    an Org whose name is markup, GONE_D in no recorded Org."""
    if model_orgs == "all":
        model_orgs = {IDLE: [_org("0", "Primary", 120)], BUSY: [_org("0", "Primary", 10)],
                      GONE_A: [_org("0", "Primary", 5)], GONE_B: [_org("7", "Tenant B", 200)],
                      GONE_C: [_org("7", "Tenant B", 3), _org("9", MARKUP, 4)]}
    return fx.build_usage({IDLE: 120, BUSY: 10,
                           GONE_A: {"last_used": fx.USAGE_READ_AT - 5 * _DAYS,
                                    "queries_180d": 40, "users_180d": 6},
                           GONE_B: {"last_used": fx.USAGE_READ_AT - 200 * _DAYS,
                                    "queries_180d": 0, "users_180d": 0},
                           GONE_C: {"last_used": fx.USAGE_READ_AT - 3 * _DAYS,
                                    "queries_180d": 25, "users_180d": 2},
                           GONE_D: {"last_used": fx.USAGE_READ_AT - 8 * _DAYS,
                                    "queries_180d": 1, "users_180d": 1}},
                          org=org, not_visible=(GONE_A, GONE_B, GONE_C, GONE_D),
                          model_orgs=model_orgs)


def test_the_corpus_carries_each_not_found_ids_orgs_and_the_orgs_named():
    usage = _data(_org_usage())["corpus"]["usage"]
    assert usage["org_read"] is True
    assert usage["orgs"] == [{"id": "0", "name": "Primary", "models": 3},
                             {"id": "7", "name": "Tenant B", "models": 2},
                             {"id": "9", "name": MARKUP, "models": 1}]
    by_guid = {g["guid"]: g["orgs"] for g in usage["gone"]}
    assert by_guid[GONE_C] == [_org("7", "Tenant B", 3), _org("9", MARKUP, 4)]
    assert by_guid[GONE_D] == []
    # a Model ID in two Orgs keeps its own counts, not one per Org
    assert [g["queries_180d"] for g in usage["gone"] if g["guid"] == GONE_C] == [25]


def test_orgs_not_read_are_null_in_the_corpus_and_the_payload():
    data = _data(_org_usage(model_orgs=None))
    usage = data["corpus"]["usage"]
    assert usage["org_read"] is False and usage["orgs"] is None
    assert all(g["orgs"] is None for g in usage["gone"])
    us = compact_payload(data)["C"]["us"]
    assert us["or"] == 0 and us["os"] is None and all(g[4] is None for g in us["g"])


def test_the_payload_compacts_the_orgs():
    us = compact_payload(_data(_org_usage()))["C"]["us"]
    assert us["or"] == 1
    assert us["os"] == [["0", "Primary", 3], ["7", "Tenant B", 2], ["9", MARKUP, 1]]
    row = {g[0]: g for g in us["g"]}[GONE_C]
    assert row == [GONE_C, 25, 2, fx.USAGE_READ_AT - 3 * _DAYS,
                   [["7", "Tenant B", fx.USAGE_READ_AT - 3 * _DAYS],
                    ["9", MARKUP, fx.USAGE_READ_AT - 4 * _DAYS]]]


def test_json_from_0_223_compacts_with_no_org_fields():
    us = compact_payload(_data(_usage()))["C"]["us"]
    assert "or" not in us and "os" not in us
    assert all(g[4] == [] for g in us["g"])


@needs_chrome
def test_from_the_primary_org_with_several_orgs_the_header_says_all_orgs(tmp_path):
    seen = _dash(_data(_org_usage()), tmp_path)
    assert seen["meta"] == ("Usage of all Orgs (3 in the usage history), read from the "
                            "Primary Org on 2026-11-25")
    assert seen["note"] is None and seen["imgs"] == 0


@needs_chrome
def test_from_the_primary_org_with_one_org_the_header_names_it(tmp_path):
    only = {IDLE: [_org("0", "Primary", 120)]}
    seen = _dash(_data(_org_usage(model_orgs=only)), tmp_path)
    assert seen["meta"] == "Usage of the Org ‘Primary’, read on 2026-11-25"


@needs_chrome
def test_from_the_primary_org_with_orgs_not_read_the_header_says_so(tmp_path):
    seen = _dash(_data(_org_usage(model_orgs=None)), tmp_path)
    assert seen["meta"] == ("Usage read from the Primary Org on 2026-11-25; which Orgs it "
                            "covers was not read")


@needs_chrome
def test_from_another_org_with_one_org_the_header_is_unchanged(tmp_path):
    only = {GONE_B: [_org("7", "Tenant B", 200)]}
    seen = _dash(_data(_org_usage(org={"id": 7, "name": "Tenant B"}, model_orgs=only)),
                 tmp_path)
    assert seen["meta"] == "Usage of the Org ‘Tenant B’, read on 2026-11-25"
    assert seen["note"].startswith("Usage counts the queries in the Org ‘Tenant B’ only")


@needs_chrome
def test_from_another_org_with_several_orgs_the_header_says_what_the_data_shows(tmp_path):
    seen = _dash(_data(_org_usage(org={"id": 7, "name": "Tenant B"})), tmp_path)
    assert seen["meta"] == "Usage of 3 Orgs, read from the Org ‘Tenant B’ on 2026-11-25"
    assert seen["note"] is None          # "that Org's only" would be false
    assert seen["imgs"] == 0


_SPLIT = ('function rows(root){ return Array.prototype.map.call(root.querySelectorAll('
          '"tbody tr"), function(tr){ return Array.prototype.map.call(tr.cells,'
          ' function(c){ return c.textContent; }); }); }'
          'var out = [];'
          'Array.prototype.forEach.call(document.querySelectorAll("#v-cleanup .usage-gone"),'
          ' function(s){ var groups = Array.prototype.map.call(s.querySelectorAll('
          '"details.usage-org-group"), function(d){ return [d.querySelector("summary")'
          '.textContent, d.open, rows(d)]; });'
          ' out.push({head: s.querySelector("h3").textContent, cls: s.className,'
          ' text: s.textContent, rows: groups.length ? null : rows(s), groups: groups}); });'
          'window.__extra = {sections: out,'
          ' imgs: document.querySelectorAll("#v-cleanup img").length};')


def _split(data, tmp_path):
    shown = report_browser.render(render_report(data), tmp_path, "cleanup", actions=_SPLIT)
    assert shown["errors"] == [], shown["errors"]
    return shown["extra"]


@needs_chrome
def test_cleanup_splits_this_orgs_ids_from_other_orgs_and_unrecorded(tmp_path):
    seen = _split(_data(_org_usage()), tmp_path)
    own, others, unrecorded = seen["sections"]
    assert own["head"] == "Used in this Org, but not found (1)"
    assert own["rows"] == [[GONE_A, "40", "6", "2026-11-20"]]
    assert "deleted, or not shared with that user" in own["text"]
    assert others["head"] == "Used in other Orgs (2 IDs in 2 Orgs)"   # GONE_C once
    assert "does not judge whether they still exist" in others["text"]
    assert "deleted" not in others["text"]
    # one collapsed group per Org, the most IDs first; an ID in two Orgs is in both,
    # each with that Org's last query
    assert others["groups"] == [
        ["the Org ‘Tenant B’ — 2 Model IDs", False,
         [[GONE_C + " · also queried in 1 other Org", "25", "2", "2026-11-22"],
          [GONE_B, "0", "0", "2026-05-09"]]],
        ["the Org ‘" + MARKUP + "’ — 1 Model ID", False,
         [[GONE_C + " · also queried in 1 other Org", "25", "2", "2026-11-21"]]]]
    assert unrecorded["head"] == "Org not recorded (1)"
    assert unrecorded["rows"] == [[GONE_D, "1", "1", "2026-11-17"]]
    assert seen["imgs"] == 0             # the Org name is text, never markup


@needs_chrome
def test_cleanup_from_another_org_puts_that_orgs_ids_first(tmp_path):
    seen = _split(_data(_org_usage(org={"id": 7, "name": "Tenant B"})), tmp_path)
    own, others, _ = seen["sections"]
    assert own["head"] == "Used in this Org, but not found (2)"
    assert [r[0].split(" ")[0] for r in own["rows"]] == [GONE_C, GONE_B]
    assert [g[0] for g in others["groups"]] == ["the Org ‘Primary’ — 1 Model ID",
                                                "the Org ‘" + MARKUP + "’ — 1 Model ID"]
    # GONE_C was queried here (Tenant B) and in the markup Org: the audit's own Org is
    # "this Org", never one of the "other" Orgs
    assert own["rows"][0][0] == GONE_C + " · also queried in 1 other Org"
    assert others["groups"][1][2][0][0] == GONE_C + " · also queried in this Org"


@needs_chrome
def test_cleanup_with_the_audits_org_not_read_lists_every_id_by_org(tmp_path):
    seen = _split(_data(_org_usage(org={"id": None, "name": None})), tmp_path)
    own, others, _ = seen["sections"]
    assert own["head"] == "Used in this Org, but not found"
    assert own["text"].endswith("every ID is listed by its Org below.")
    assert others["head"] == "Not found, by the Org queried in (3 IDs in 3 Orgs)"


@needs_chrome
def test_cleanup_with_orgs_not_read_keeps_one_list_and_says_so(tmp_path):
    seen = _split(_data(_org_usage(model_orgs=None)), tmp_path)
    [only] = seen["sections"]
    assert only["head"] == "Used, but not found in this Org — usage of the Org ‘Primary’ (4)"
    assert "Org not read: the Org each ID was queried in could not be read" in only["text"]
    assert [r[0] for r in only["rows"]] == [GONE_A, GONE_C, GONE_D, GONE_B]


@needs_chrome
def test_cleanup_of_a_reading_from_0_223_says_org_not_recorded(tmp_path):
    seen = _split(_data(_usage()), tmp_path)
    [only] = seen["sections"]
    assert only["head"] == "Org not recorded (2)"
    assert "read before the audit read each Model's Org" in only["text"]
    assert [r[0] for r in only["rows"]] == [GONE_A, GONE_B]


@needs_chrome
def test_one_id_in_two_other_orgs_counts_once(tmp_path):
    orgs = {GONE_C: [_org("7", "Tenant B", 3), _org("9", "Tenant C", 4)]}
    usage = _org_usage(model_orgs=orgs)
    usage["not_visible"] = [GONE_C]
    seen = _split(_data(usage), tmp_path)
    own, others = seen["sections"]
    assert own["head"] == "Used in this Org, but not found (0)"
    assert others["head"] == "Used in other Orgs (1 ID in 2 Orgs)"
    assert [g[2][0][0] for g in others["groups"]] == [
        GONE_C + " · also queried in 1 other Org"] * 2


_TITLES = ('window.__extra = Array.prototype.map.call(document.querySelectorAll('
           '".scorecard-header .usage-stat"), function(s){ return s.getAttribute("title"); });')


@needs_chrome
def test_titles_say_all_orgs_from_the_primary_org_with_several(tmp_path):
    data = _data(_org_usage())
    seen = _dash(data, tmp_path)
    assert seen["rows"]["Idle Sales"][1].endswith(
        "(usage of all Orgs, read from the Primary Org)")
    stats = report_browser.render(render_report(data), tmp_path, f"model/{BUSY}",
                                  actions=_TITLES)
    assert stats["errors"] == []
    assert all(t.endswith("(usage of all Orgs, read from the Primary Org)")
               for t in stats["extra"]) and len(stats["extra"]) == 3
    # H17's finding says the same
    [h17] = [f for f in data["findings"] if f["check_id"] == "H17"
             and f["object_guid"] == IDLE]
    assert h17["detail"].endswith("(usage of all Orgs, read from the Primary Org)")


@needs_chrome
def test_titles_from_another_org_keep_its_wording(tmp_path):
    only = {GONE_B: [_org("7", "Tenant B", 200)]}
    data = _data(_org_usage(org={"id": 7, "name": "Tenant B"}, model_orgs=only))
    seen = _dash(data, tmp_path)
    assert seen["rows"]["Idle Sales"][1].endswith("(usage of the Org ‘Tenant B’)")
    stats = report_browser.render(render_report(data), tmp_path, f"model/{BUSY}",
                                  actions=_TITLES)
    assert all(t.endswith("(usage of the Org ‘Tenant B’)") for t in stats["extra"])
