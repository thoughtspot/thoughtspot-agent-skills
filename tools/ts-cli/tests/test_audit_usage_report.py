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


def _usage(org=None, not_visible=(GONE_A, GONE_B)):
    return fx.build_usage({IDLE: 120, BUSY: 10,
                           GONE_A: {"last_used": fx.USAGE_READ_AT - 5 * 86400,
                                    "queries_180d": 40, "users_180d": 6},
                           GONE_B: {"last_used": fx.USAGE_READ_AT - 200 * 86400,
                                    "queries_180d": 0, "users_180d": 0}},
                          org=org, not_visible=not_visible)


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
    assert usage["gone"][0] == {"guid": GONE_A, "last_used": fx.USAGE_READ_AT - 5 * 86400,
                                "days": 5, "queries_180d": 40, "users_180d": 6}


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
    assert us["g"][0] == [GONE_A, 40, 6, fx.USAGE_READ_AT - 5 * 86400]
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
    assert seen["meta"] == "Usage of the Org ‘Primary’, read on 2026-11-25"
    assert seen["note"] is None          # the Primary Org's usage needs no note
    assert "Last used" in seen["th"]
    assert seen["rows"]["Idle Sales"][0] == "120 days ago"
    assert seen["rows"]["Idle Sales"][1] == ("Last queried on 2026-07-28; 12 queries by 3 "
                                             "users in the last 180 days (the Org ‘Primary’)")
    assert seen["rows"]["Never Sales"] == [
        "No query", "No query in the usage history, which starts on 2023-10-01 "
                    "(the Org ‘Primary’)"]


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
    shown = report_browser.render(render_report(_data(_usage())), tmp_path, "cleanup",
                                  actions=_CLEANUP)
    assert shown["errors"] == []
    seen = shown["extra"]
    assert seen["head"] == "Used, but not found in this Org — usage of the Org ‘Primary’ (2)"
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
                              "30 days the history holds (the Org ‘Primary’)")


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
    assert title["extra"].endswith("12 queries by 3 users in the last 180 days (the Org ‘Primary’)")
