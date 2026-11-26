"""The Usage view (ts-audit 3.28.0): each audited Model's status, dependents, owner and
creation date in the audit JSON, and the view itself — its quadrant, triage table,
filters and the candidates export.

Synthetic names and GUIDs only.
"""
from __future__ import annotations

import json

import pytest

import audit_rule_fixtures as fx
import report_browser
from ts_cli.audit import data_needs, run_audit
from ts_cli.audit.context import ALWAYS_FETCHED, make_context
from ts_cli.audit.report import compact_payload, render_report
from ts_cli.audit.usage_triage import (dependent_counts, model_status, owner_of,
                                       status_idle_days)

needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")

DAY = 86400
READ = fx.USAGE_READ_AT
ACTIVE, IDLE, NEVER, YOUNG, NOTIME, USED_IDLE = (
    f"aaaaaaaa-0000-4000-8000-00000000000{i}" for i in range(1, 7))
MARKUP = "<img src=x onerror=alert(1)>"
H_NEEDS = data_needs(["H"]) | ALWAYS_FETCHED


def _meta(guid, created_days=400, author="Ann Owner", author_name="ann"):
    header = {"id": guid, "authorName": author_name}
    if author is not None:
        header["authorDisplayName"] = author
    if created_days is not None:
        header["created"] = (READ - created_days * DAY) * 1000
    return {"metadata_id": guid, "metadata_type": "LOGICAL_TABLE", "metadata_header": header}


def _dep(src, i, kind):
    return {"source_guid": src, "guid": f"eeeeeeee-0000-4000-8000-{i:012d}",
            "name": f"Dependent {i}", "type": kind}


NAMES = {ACTIVE: "Active Sales", IDLE: "Idle Sales", NEVER: "Never Sales",
         YOUNG: "Young Sales", NOTIME: "No Time Sales", USED_IDLE: MARKUP}


def _ctx(usage, names=None):
    names = names or NAMES
    models = [fx.build_human_model(n, g) for g, n in names.items()]
    metadata = [_meta(ACTIVE), _meta(IDLE, author=None), _meta(NEVER, author=None,
                                                                author_name=None),
                _meta(YOUNG, created_days=30), _meta(NOTIME), _meta(USED_IDLE, author=MARKUP)]
    dependents = {
        IDLE: [],
        USED_IDLE: [_dep(USED_IDLE, 1, "LIVEBOARD"), _dep(USED_IDLE, 2, "LIVEBOARD"),
                    _dep(USED_IDLE, 3, "ANSWER"), _dep(USED_IDLE, 4, "SET"),
                    _dep(USED_IDLE, 5, "LOGICAL_TABLE"), _dep(USED_IDLE, 6, "FEEDBACK")],
        ACTIVE: [_dep(ACTIVE, 7, "ANSWER")],
    }
    return make_context(models=models, model_guids=list(names), usage=usage,
                        metadata=metadata, dependents=dependents)


def _usage(**kw):
    return fx.build_usage({ACTIVE: 10, IDLE: 120, USED_IDLE: 200, NOTIME: None}, **kw)


def _data(usage, needs=H_NEEDS, angles=("H",), names=None):
    return run_audit(None, [], list(angles), ctx=_ctx(usage, names),
                     fetched_needs=set(needs))


def _by_guid(data):
    return {m["guid"]: m.get("usage") for m in data["corpus"]["models"]}


# ── the pure helpers ────────────────────────────────────────────────────────

def test_dependents_split_by_type_and_sets_null_when_not_read():
    rows = [{"type": t} for t in ("LIVEBOARD", "LIVEBOARD", "ANSWER", "SET",
                                  "LOGICAL_TABLE", "FEEDBACK")]
    assert dependent_counts(rows, True) == {"total": 6, "liveboards": 2, "answers": 1,
                                            "sets": 1, "other": 2}
    # Sets not read: the dependents are not known, so there is no total
    assert dependent_counts(rows, False) == {"total": None, "liveboards": 2, "answers": 1,
                                             "sets": None, "other": 2}
    assert dependent_counts(None, True)["total"] == 0


def test_owner_is_the_author_display_name_then_the_author_name():
    assert owner_of({"authorDisplayName": "Ann", "authorName": "ann"}) == "Ann"
    assert owner_of({"authorDisplayName": "", "authorName": "ann"}) == "ann"
    assert owner_of({"owner": "a-user-id"}) is None
    assert owner_of(None) is None


@pytest.mark.parametrize("guid,created_days,status", [
    (ACTIVE, 400, "active"),
    (IDLE, 400, "idle"),
    (NEVER, 400, "never"),
    (NEVER, 30, "too_new"),      # the #757 rule: younger than the idle window
    (NEVER, None, "never"),      # no creation time: judged as before
    (NOTIME, 400, "not_judged"),  # a row with no query time
])
def test_each_status(guid, created_days, status):
    created = None if created_days is None else (READ - created_days * DAY) * 1000
    assert model_status(_usage(), guid, 90, created) == status


def test_a_short_history_judges_a_never_queried_model_not_judged():
    short = _usage(start=READ - 30 * DAY)
    assert model_status(short, NEVER, 90, (READ - 400 * DAY) * 1000) == "not_judged"
    # a Model the history holds is judged by its last query alone
    assert model_status(short, IDLE, 90, None) == "idle"


def test_status_idle_days_is_h17s_and_falls_back_to_the_catalogs():
    assert status_idle_days({}) == 90


# ── the audit JSON ──────────────────────────────────────────────────────────

def test_the_corpus_carries_status_dependents_owner_and_created():
    by = _by_guid(_data(_usage()))
    assert by[USED_IDLE]["status"] == "idle"
    assert by[USED_IDLE]["dependents"] == {"total": 6, "liveboards": 2, "answers": 1,
                                           "sets": 1, "other": 2}
    assert by[USED_IDLE]["owner"] == MARKUP
    assert by[ACTIVE]["owner"] == "Ann Owner" and by[IDLE]["owner"] == "ann"
    assert by[NEVER]["owner"] is None
    assert by[ACTIVE]["created"] == "2025-10-21"
    assert by[YOUNG]["status"] == "too_new" and by[NEVER]["status"] == "never"
    assert by[NOTIME]["status"] == "not_judged" and by[ACTIVE]["status"] == "active"
    assert by[IDLE]["dependents"]["total"] == 0
    # the usage keys from 3.26 are unchanged
    assert by[IDLE]["days"] == 120 and by[IDLE]["never"] is False
    assert _data(_usage())["corpus"]["usage"]["status_idle_days"] == 90


def test_a_model_with_no_header_has_no_owner_or_created():
    data = _data(_usage(), names={**NAMES, "aaaaaaaa-0000-4000-8000-000000000009": "Bare"})
    bare = _by_guid(data)["aaaaaaaa-0000-4000-8000-000000000009"]
    assert bare["owner"] is None and bare["created"] is None and bare["status"] == "never"


def test_sets_are_null_when_the_run_did_not_fetch_them():
    by = _by_guid(_data(_usage(), needs=H_NEEDS - {"sets"}))
    assert by[USED_IDLE]["dependents"]["sets"] is None
    assert by[USED_IDLE]["dependents"]["total"] is None      # not known, never 5
    assert by[USED_IDLE]["dependents"]["liveboards"] == 2


def test_unread_usage_adds_no_status():
    assert all(u is None for u in _by_guid(_data(None)).values())


def test_the_payload_compacts_the_triage():
    payload = compact_payload(_data(_usage()))
    by = {payload["L"][cm["mi"]]["g"]: cm["us"] for cm in payload["C"]["m"]}
    assert by[USED_IDLE]["s"] == "idle" and by[USED_IDLE]["dp"] == [6, 2, 1, 1, 2]
    assert by[USED_IDLE]["ow"] == MARKUP and by[ACTIVE]["cr"] == "2025-10-21"
    assert by[NEVER]["ow"] is None
    assert payload["C"]["us"]["si"] == 90


# ── the rendered view ───────────────────────────────────────────────────────

def _render(data, tmp_path, actions, route="usage", settle_ms=50):
    shown = report_browser.render(render_report(data), tmp_path, route, actions=actions,
                                  settle_ms=settle_ms)
    assert shown["errors"] == [], shown["errors"]
    return shown


_NAV = ('window.__extra = Array.prototype.map.call(document.querySelectorAll('
        '"#sidebar-nav > a"), function(a){ return a.querySelectorAll("span")[1].textContent; });')


@needs_chrome
def test_the_nav_entry_shows_only_when_usage_was_fetched(tmp_path):
    read = _render(_data(_usage()), tmp_path, _NAV, route="dashboard")["extra"]
    assert "Usage" in read and read.index("Usage") == read.index("Cleanup") + 1
    unread = _render(_data(None), tmp_path, _NAV, route="dashboard")["extra"]
    assert "Usage" in unread
    data = _data(None, needs=data_needs(["D"]) | ALWAYS_FETCHED, angles=("D",))
    assert "Usage" not in _render(data, tmp_path, _NAV, route="dashboard")["extra"]


@needs_chrome
def test_unread_usage_says_not_read_and_draws_no_table(tmp_path):
    shown = _render(_data(None), tmp_path, "")
    assert shown["active"] == "v-usage"
    assert "Not read" in shown["visible"]
    assert "could not read usage" in shown["visible"]
    assert "Retire candidates" not in shown["visible"]
    page = render_report(_data(None))
    assert "usage-table" in page   # the class exists, so its absence below is real
    probe = _render(_data(None), tmp_path,
                    'window.__extra = document.querySelectorAll("#v-usage table, '
                    '#v-usage svg circle").length;')
    assert probe["extra"] == 0


@needs_chrome
def test_no_usage_fetched_says_not_collected(tmp_path):
    data = _data(None, needs=data_needs(["D"]) | ALWAYS_FETCHED, angles=("D",))
    shown = _render(data, tmp_path, "")
    assert shown["active"] == "v-usage" and "Not collected" in shown["visible"]


_ROWS = ('function rows(){ return Array.prototype.filter.call(document.querySelectorAll('
         '"#v-usage .usage-table tbody tr"), function(tr){ return tr.style.display !== "none"; })'
         '.map(function(tr){ return tr.getAttribute("data-guid"); }); }')


@needs_chrome
def test_the_quadrant_has_one_dot_per_model_in_its_quadrant(tmp_path):
    shown = _render(_data(_usage()), tmp_path,
                    'var out = {}; Array.prototype.forEach.call(document.querySelectorAll('
                    '"#v-usage svg circle.usage-dot"), function(c){ out[c.getAttribute("data-guid")]'
                    ' = [c.getAttribute("data-quadrant"), c.querySelector("title").textContent]; });'
                    'window.__extra = {dots: out, imgs: document.querySelectorAll('
                    '"#v-usage img").length, line: !!document.querySelector('
                    '"#v-usage .usage-idle-line")};')
    dots = shown["extra"]["dots"]
    assert {g: d[0] for g, d in dots.items()} == {
        ACTIVE: "active", IDLE: "retire", NEVER: "retire", YOUNG: "unjudged",
        NOTIME: "unjudged", USED_IDLE: "check"}
    assert dots[USED_IDLE][1].startswith(MARKUP)        # text, not markup
    assert "6 dependents" in dots[USED_IDLE][1] and "200 days ago" in dots[USED_IDLE][1]
    assert shown["extra"]["imgs"] == 0 and shown["extra"]["line"]
    for label in ("Idle, no dependents — retire candidates",
                  "Idle, has dependents — check first", "Active"):
        assert label in shown["visible"]


@needs_chrome
def test_the_table_default_sort_puts_retire_candidates_first(tmp_path):
    shown = _render(_data(_usage()), tmp_path,
                    _ROWS + 'var tr = document.querySelector("#v-usage tr[data-guid=\\"'
                    + USED_IDLE + '\\"]");'
                    'window.__extra = {rows: rows(), cells: Array.prototype.map.call(tr.cells,'
                    ' function(c){ return c.textContent; }), dep_title: tr.cells[6]'
                    '.getAttribute("title"), imgs: document.querySelectorAll('
                    '"#v-usage img").length};')
    seen = shown["extra"]
    # never (no last query) counts as the most idle; IDLE has 0 dependents, USED_IDLE 6
    assert seen["rows"][:2] == [NEVER, IDLE]
    assert seen["rows"][2] == USED_IDLE
    assert seen["rows"][-1] == ACTIVE
    assert seen["cells"][1] == MARKUP and seen["cells"][2] == "Idle"
    assert seen["cells"][6] == "6" and seen["cells"][7] == MARKUP
    assert seen["dep_title"] == "2 Liveboards, 1 Answer, 1 Set, 2 other"
    assert seen["imgs"] == 0


@needs_chrome
def test_a_header_click_sorts_and_a_second_reverses(tmp_path):
    shown = _render(_data(_usage()), tmp_path,
                    _ROWS + 'function th(){ return document.querySelector('
                    '"#v-usage th[data-sort=\\"dependents\\"]"); }'
                    'th().click(); var a = rows(); var sa = th().getAttribute("aria-sort");'
                    'th().click(); window.__extra = {a: a, b: rows(), sa: sa,'
                    ' sb: th().getAttribute("aria-sort")};')
    seen = shown["extra"]
    assert seen["sa"] == "descending" and seen["sb"] == "ascending"
    assert seen["a"][:2] == [USED_IDLE, ACTIVE]        # 6, then 1
    assert seen["b"][-2:] == [ACTIVE, USED_IDLE]


_CHIP = ('function chip(f){ document.querySelector("#v-usage .fbar-chip[data-f=\\"" + f +'
         ' "\\"]").click(); }')


@needs_chrome
@pytest.mark.parametrize("chip,hidden", [
    ("active", {ACTIVE}), ("idle", {IDLE, USED_IDLE}), ("never", {NEVER}),
    ("too_new", {YOUNG}), ("not_judged", {NOTIME})])
def test_each_status_chip_hides_its_models(chip, hidden, tmp_path):
    shown = _render(_data(_usage()), tmp_path,
                    _ROWS + _CHIP + f'chip("{chip}"); window.__extra = {{rows: rows(),'
                    ' dots: document.querySelectorAll("#v-usage circle.usage-dot").length,'
                    ' counts: Array.prototype.map.call(document.querySelectorAll('
                    '"#v-usage .fbar-chip"), function(b){ return b.textContent; })};')
    assert set(shown["extra"]["rows"]) == set(NAMES) - hidden
    assert shown["extra"]["dots"] == len(NAMES) - len(hidden)   # the chart follows
    assert "Idle 2" in shown["extra"]["counts"] and "No dependents 4" in shown["extra"]["counts"]


@needs_chrome
def test_no_dependents_narrows_and_combines_with_status(tmp_path):
    shown = _render(_data(_usage()), tmp_path,
                    _ROWS + _CHIP + 'chip("nodeps"); var a = rows(); chip("never");'
                    'window.__extra = {a: a, b: rows(), pressed: document.querySelector('
                    '"#v-usage .fbar-chip[data-f=\\"nodeps\\"]").getAttribute("aria-pressed")};')
    seen = shown["extra"]
    assert set(seen["a"]) == {IDLE, NEVER, YOUNG, NOTIME} and seen["pressed"] == "true"
    assert set(seen["b"]) == {IDLE, YOUNG, NOTIME}


# The Blob's parts and type are captured as it is made (synchronously: a probe that waited
# on Blob.text() raced the page read under load), and the download's click is swallowed.
_EXPORT = ('var RealBlob = window.Blob; window.__blobs = [];'
           'window.Blob = function(parts, opts){ window.__blobs.push({text: parts.join(""),'
           ' type: (opts || {}).type}); return new RealBlob(parts, opts); };'
           'URL.createObjectURL = function(){ return "blob:probe"; };'
           ' URL.revokeObjectURL = function(){};'
           'var names = []; HTMLAnchorElement.prototype.click = function(){'
           ' names.push(this.getAttribute("download")); };'
           'function q(s){ return document.querySelector("#v-usage " + s); }')


@needs_chrome
def test_selection_select_all_shown_and_clear(tmp_path):
    shown = _render(_data(_usage()), tmp_path,
                    _EXPORT + _CHIP + 'var dis = q(".usage-export-csv").disabled;'
                    'chip("active"); q(".usage-select-shown").click();'
                    'var n = q(".usage-selected-count").textContent;'
                    'var checked = Array.prototype.filter.call(document.querySelectorAll('
                    '"#v-usage .usage-check"), function(c){ return c.checked; }).length;'
                    'q(".usage-clear").click();'
                    'window.__extra = {dis: dis, n: n, checked: checked,'
                    ' after: q(".usage-selected-count").textContent,'
                    ' dis2: q(".usage-export-json").disabled};')
    seen = shown["extra"]
    assert seen["dis"] is True and seen["dis2"] is True
    assert seen["n"] == "5 selected" and seen["checked"] == 5
    assert seen["after"] == "0 selected"


@needs_chrome
def test_a_dot_click_selects_its_row(tmp_path):
    shown = _render(_data(_usage()), tmp_path,
                    'var dot = document.querySelector("#v-usage circle.usage-dot[data-guid=\\"'
                    + IDLE + '\\"]"); dot.dispatchEvent(new MouseEvent("click", {bubbles: true}));'
                    'var cb = document.querySelector("#v-usage tr[data-guid=\\"' + IDLE +
                    '\\"] .usage-check"); var one = cb.checked;'
                    'dot = document.querySelector("#v-usage circle.usage-dot[data-guid=\\"'
                    + IDLE + '\\"]"); var ring = dot.classList.contains("selected");'
                    'dot.dispatchEvent(new MouseEvent("click", {bubbles: true}));'
                    'window.__extra = {one: one, ring: ring, two: document.querySelector('
                    '"#v-usage tr[data-guid=\\"' + IDLE + '\\"] .usage-check").checked};')
    assert shown["extra"] == {"one": True, "ring": True, "two": False}


def _export(tmp_path, which, data=None):
    shown = _render(data or _data(_usage()), tmp_path,
                    _EXPORT + 'Array.prototype.forEach.call(document.querySelectorAll('
                    '"#v-usage .usage-check"), function(c){ if(["' + IDLE + '","' + USED_IDLE +
                    '"].indexOf(c.getAttribute("data-guid")) !== -1) c.click(); });'
                    'q(".usage-export-' + which + '").click();'
                    'window.__extra = {text: window.__blobs[0].text,'
                    ' type: window.__blobs[0].type, names: names};')
    return shown["extra"]


@needs_chrome
def test_the_csv_export_holds_the_selected_rows_escaped(tmp_path):
    seen = _export(tmp_path, "csv")
    assert seen["names"] == ["ts-audit-candidates.csv"] and seen["type"].startswith("text/csv")
    lines = seen["text"].strip().split("\r\n")
    assert lines[0] == ("guid,name,type,status,last_used,days_since_last_use,queries_180d,"
                        "users_180d,dependents_total,liveboards,answers,sets,other,owner,created,"
                        "usage_scope,dependents_scope,cluster_url,audit_read_date")
    assert len(lines) == 3
    by = {ln.split(",")[0]: ln for ln in lines[1:]}
    assert by[IDLE].startswith(IDLE + ",Idle Sales,MODEL,idle,2026-07-28,120,12,3,0,0,0,0,0,ann,"
                               "2025-10-21,")
    assert ",visible to the audit's user in this Org," in by[IDLE]
    assert by[IDLE].endswith(",2026-11-25")
    assert by[USED_IDLE].startswith(USED_IDLE + "," + MARKUP + ",MODEL,idle,")
    assert ",6,2,1,1,2," in by[USED_IDLE]


@needs_chrome
def test_csv_cells_that_could_run_as_formulas_are_prefixed(tmp_path):
    names = dict(NAMES)
    names[IDLE] = '=HYPERLINK("x","y")'
    names[USED_IDLE] = "+1, -2 @3"
    seen = _export(tmp_path, "csv", _data(_usage(), names=names))
    assert "'=HYPERLINK(\"\"x\"\",\"\"y\"\")\"" in seen["text"]
    assert "\"'=HYPERLINK" in seen["text"]
    assert "\"'+1, -2 @3\"" in seen["text"]


@needs_chrome
def test_the_json_export_is_the_candidates_format(tmp_path):
    seen = _export(tmp_path, "json")
    assert seen["names"] == ["ts-audit-candidates.json"]
    doc = json.loads(seen["text"])
    assert doc["format"] == "ts-audit-candidates/1"
    assert doc["generated"].endswith("Z")
    assert doc["dependents_scope"] == "visible to the audit's user in this Org"
    assert doc["usage"] == {"scope": "usage read from the Primary Org; which Orgs it covers "
                                     "was not read",
                            "org": {"id": 0, "name": "Primary"},
                            "read_at": "2026-11-25T00:00:00Z", "idle_days": 90,
                            "window_days": 180}
    by = {o["guid"]: o for o in doc["objects"]}
    assert set(by) == {IDLE, USED_IDLE}
    assert by[IDLE] == {"guid": IDLE, "name": "Idle Sales", "type": "MODEL", "status": "idle",
                        "last_used": "2026-07-28", "days_since_last_use": 120,
                        "queries_180d": 12, "users_180d": 3, "dependents_total": 0,
                        "liveboards": 0, "answers": 0, "sets": 0, "other": 0, "owner": "ann",
                        "created": "2025-10-21"}
    assert by[USED_IDLE]["name"] == MARKUP and by[USED_IDLE]["sets"] == 1
    assert by[USED_IDLE]["other"] == 2 and by[USED_IDLE]["dependents_total"] == 6


@needs_chrome
def test_a_never_queried_row_exports_empty_last_used_and_null_days(tmp_path):
    shown = _render(_data(_usage()), tmp_path,
                    _EXPORT + 'document.querySelector("#v-usage tr[data-guid=\\"' + NEVER +
                    '\\"] .usage-check").click(); q(".usage-export-json").click();'
                    'window.__extra = JSON.parse(window.__blobs[0].text).objects[0];')
    assert shown["extra"]["last_used"] is None and shown["extra"]["days_since_last_use"] is None
    assert shown["extra"]["status"] == "never" and shown["extra"]["owner"] is None


def _before_3_28(data):
    for m in data["corpus"]["models"]:
        for k in ("status", "dependents", "owner", "created"):
            m["usage"].pop(k, None)
    data["corpus"]["usage"].pop("status_idle_days")
    return data


def test_json_from_before_3_28_compacts_without_the_triage():
    payload = compact_payload(_before_3_28(_data(_usage())))
    assert all("s" not in cm["us"] and "dp" not in cm["us"] for cm in payload["C"]["m"])
    assert payload["C"]["us"]["si"] is None


@needs_chrome
def test_json_from_before_3_28_says_to_re_run(tmp_path):
    shown = _render(_before_3_28(_data(_usage())), tmp_path, "")
    assert "predates the Usage view" in shown["visible"]



# ── a Set lookup that failed: the dependents are not known, never 0 ─────────

def _ctx_sets_unread(usage, unread=(IDLE,), recorded=True):
    ctx = _ctx(usage)
    if recorded:
        ctx.sets_incomplete = list(unread)
    else:   # a snapshot from before 0.225.0: only the run's warning names the Model
        ctx.sets_incomplete = None
        ctx.warnings = [f"Set discovery discovery_failed for {NAMES[g]} ({g}): cohort "
                        "listing failed: 500" for g in unread]
    return ctx


def _data_ctx(ctx, needs=H_NEEDS):
    return run_audit(None, [], ["H"], ctx=ctx, fetched_needs=set(needs))


@pytest.mark.parametrize("recorded", [True, False])
def test_a_model_whose_set_lookup_failed_has_unknown_dependents(recorded):
    by = _by_guid(_data_ctx(_ctx_sets_unread(_usage(), recorded=recorded)))
    assert by[IDLE]["dependents"] == {"total": None, "liveboards": 0, "answers": 0,
                                      "sets": None, "other": 0}
    assert by[NEVER]["dependents"]["total"] == 0      # its lookup was clean


def test_dependents_are_unknown_when_what_was_fetched_is_not_known():
    data = run_audit(None, [], ["H"], ctx=_ctx(_usage()), fetched_needs=None)
    assert _by_guid(data)[IDLE]["dependents"]["total"] is None


def _set_client(get):
    client = fx.build_client_with_one_model("m1")
    client.get.side_effect = get
    return client


def _raise(*_a, **_kw):
    raise RuntimeError("cohort listing refused")


@pytest.mark.parametrize("get", [_raise, lambda *a, **kw: fx.build_response({"error": "x"})])
def test_build_context_records_a_failed_set_lookup(get):
    from ts_cli.audit.context import build_context
    ctx = build_context(_set_client(get), ["m1"], data_needs(["H"]))
    assert ctx.sets_incomplete == ["m1"]


def test_build_context_records_no_failure_when_sets_are_not_fetched():
    from ts_cli.audit.context import build_context
    ctx = build_context(_set_client(_raise), ["m1"], data_needs(["D"]))
    assert ctx.sets_incomplete is None


def test_a_snapshot_keeps_the_failed_set_lookups(tmp_path):
    from ts_cli.audit.snapshot import read_snapshot, write_snapshot
    ctx = _ctx_sets_unread(_usage())
    write_snapshot(ctx, tmp_path / "snap", ["H"], needs=H_NEEDS)
    assert read_snapshot(tmp_path / "snap")[0].sets_incomplete == [IDLE]


@needs_chrome
def test_unknown_dependents_are_never_a_retire_candidate(tmp_path):
    data = _data_ctx(_ctx_sets_unread(_usage()))
    shown = _render(data, tmp_path,
                    _ROWS + _CHIP + 'var dot = document.querySelector("#v-usage circle.usage-dot'
                    '[data-guid=\\"' + IDLE + '\\"]"); var tr = document.querySelector('
                    '"#v-usage tr[data-guid=\\"' + IDLE + '\\"]");'
                    'var out = {quadrant: dot.getAttribute("data-quadrant"),'
                    ' title: dot.querySelector("title").textContent, cell: tr.cells[6].textContent,'
                    ' cell_title: tr.cells[6].getAttribute("title"), first: rows()[0],'
                    ' chip: document.querySelector("#v-usage .fbar-chip[data-f=\\"nodeps\\"]")'
                    '.textContent}; chip("nodeps"); out.nodeps = rows(); window.__extra = out;')
    seen = shown["extra"]
    assert seen["quadrant"] == "unjudged" and "dependents not read" in seen["title"]
    assert seen["cell"] == "Not read" and "Sets not read" in seen["cell_title"]
    assert seen["first"] != IDLE                       # not sorted as a retire candidate
    assert seen["chip"] == "No dependents 3" and IDLE not in seen["nodeps"]
    exported = _export(tmp_path, "json", data)
    obj = {o["guid"]: o for o in json.loads(exported["text"])["objects"]}[IDLE]
    assert obj["sets"] is None and obj["dependents_total"] is None


@needs_chrome
def test_the_view_says_whose_dependents_it_counts(tmp_path):
    shown = _render(_data(_usage()), tmp_path, "")
    assert "Dependents are those the audit's user can see in this Org" in shown["visible"]
