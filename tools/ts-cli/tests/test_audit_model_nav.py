"""The pages about one Model share one tab bar and one breadcrumb (report/model_nav.js):
Scorecard (#model/<guid>), ERD (#model/<guid>/erd, the scorecard with its ERD open),
Formulas (#formulas/<guid> and its graph) and Data Cache (#datacache/<guid>, the Data
Cache view filtered to the Model). The older routes keep working."""
from __future__ import annotations

import pytest

import report_browser
from ts_cli.audit import run_audit
from ts_cli.audit.context import make_context
from ts_cli.audit.report import render_report

needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")


def _f(fid, name, expr):
    return {"id": fid, "name": name, "expr": expr}


def _col(name, fid, kind="MEASURE"):
    return {"name": name, "formula_id": fid, "properties": {"column_type": kind}}


SALES = {
    "name": "Sales",
    "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
    "formulas": [_f("formula_Rev", "Revenue", "sum ( [ORDERS::AMOUNT] )"),
                 _f("formula_Dbl", "Double Revenue", "[formula_Rev] * 2")],
    "columns": [_col("Revenue", "formula_Rev"), _col("Double Revenue", "formula_Dbl")],
}
PLAIN = {"name": "Plain", "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
         "columns": [{"name": "A", "column_id": "ORDERS::A"}]}


def _data(*models):
    models = models or (("m-1", SALES), ("m-9", PLAIN))
    ctx = make_context(models=[{"guid": g, "model": m} for g, m in models],
                       model_guids=[g for g, _ in models])
    return run_audit(None, [g for g, _ in models], ctx=ctx)


def _page(*models):
    return render_report(_data(*models))


#: The tabs ([tab, href or None when disabled, current]) and the breadcrumb, as text.
_NAV = ('var tabs = document.querySelector(".view.active .model-tabs");'
        'var bc = document.getElementById("breadcrumb");'
        'window.__extra = {tabs: tabs && Array.prototype.map.call(tabs.children, function(t){'
        '  return [t.getAttribute("data-tab"), t.getAttribute("href"), t.getAttribute("aria-current"),'
        '          t.tabIndex]; }),'
        ' crumb: bc.textContent.replace(/\\s+/g, " ").trim(),'
        ' model: (bc.querySelectorAll("a")[1] || {}).getAttribute ? bc.querySelectorAll("a")[1].getAttribute("href") : null};')

ALL_TABS = [["scorecard", "#model/m-1"], ["erd", "#model/m-1/erd"], ["formulas", "#formulas/m-1"],
            ["datacache", "#datacache/m-1"]]


@needs_chrome
@pytest.mark.parametrize("route, view, current, crumb", [
    ("model/m-1", "v-scorecard", "scorecard", "Audit / Sales / Scorecard"),
    ("model/m-1/erd", "v-scorecard", "erd", "Audit / Sales / ERD"),
    ("formulas/m-1", "v-formulas", "formulas", "Audit / Sales / Formulas"),
    ("formulas/m-1/graph", "v-formulas", "formulas", "Audit / Sales / Formula graph"),
    ("datacache/m-1", "v-datacache", "datacache", "Audit / Sales / Data Cache"),
    # a heatmap cell's route: the scorecard, one category open
    ("model/m-1/data_modeling", "v-scorecard", "scorecard", "Audit / Sales / Scorecard / Data Modeling"),
])
def test_every_model_page_has_the_tabs_its_own_current_and_one_breadcrumb(tmp_path, route, view,
                                                                           current, crumb):
    shown = report_browser.render(_page(), tmp_path, route, actions=_NAV)
    assert shown["errors"] == []
    assert shown["active"] == view
    x = shown["extra"]
    assert [t[:2] for t in x["tabs"]] == ALL_TABS
    assert [t[0] for t in x["tabs"] if t[2] == "page"] == [current]
    assert all(t[3] == 0 for t in x["tabs"]), "every tab is a link the keyboard reaches"
    assert x["crumb"] == crumb
    assert x["model"] == "#model/m-1", "the Model in the breadcrumb links to its scorecard"


@needs_chrome
def test_a_model_without_formulas_has_the_formulas_tab_disabled_with_the_reason(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "model/m-9", actions=_NAV + (
        'var off = document.querySelector("#v-scorecard .model-tab-off");'
        'window.__extra.off = [off.getAttribute("data-tab"), off.getAttribute("aria-disabled"),'
        ' off.title, off.textContent];'))
    assert shown["errors"] == []
    tabs = shown["extra"]["tabs"]
    assert [t[0] for t in tabs] == ["scorecard", "erd", "formulas", "datacache"]
    assert tabs[2][1] is None and tabs[2][3] == -1     # no link, not in the tab order
    assert shown["extra"]["off"][:3] == ["formulas", "true", "This Model has no formulas."]
    assert "unavailable: This Model has no formulas." in shown["extra"]["off"][3]


@needs_chrome
def test_a_report_without_data_cache_readiness_has_no_data_cache_tab(tmp_path):
    data = _data()
    for m in data["corpus"]["models"]:
        m.pop("data_cache", None)
    shown = report_browser.render(render_report(data), tmp_path, "model/m-1", actions=_NAV)
    assert shown["errors"] == []
    assert [t[0] for t in shown["extra"]["tabs"]] == ["scorecard", "erd", "formulas"]


@needs_chrome
def test_the_erd_route_opens_the_erd_inline_and_scrolls_to_it(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "model/m-1/erd", size="1400,700", actions=(
        'setTimeout(function(){'
        ' var sec = document.querySelector("#v-scorecard details.erd-panel");'
        ' var frame = sec.querySelector("iframe.erd-frame");'
        ' var h1 = frame && frame.contentDocument && frame.contentDocument.querySelector(".brand h1");'
        ' window.__extra = {open: sec.open, top: Math.round(sec.getBoundingClientRect().top),'
        '  title: frame && frame.title, h1: h1 && h1.textContent,'
        '  newtab: !!sec.querySelector(".erd-newtab"),'
        '  buttons: Array.prototype.map.call(document.querySelectorAll("#v-scorecard .header-actions .erd-btn,'
        ' #v-scorecard .header-actions a[href^=\\"#formulas\\"]"), function(b){ return b.textContent; })};'
        '}, 300);'), settle_ms=600)
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["open"] is True and x["title"] == "ERD of Sales"
    assert x["h1"] == "Sales", "the ERD rendered inside its frame"
    assert x["newtab"] is True
    assert 30 <= x["top"] <= 80, "scrolled to, just under the top bar"
    assert x["buttons"] == [], "the ERD and Formulas buttons gave way to the tabs"


@needs_chrome
def test_the_scorecard_keeps_its_erd_closed_and_draws_it_when_opened(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "model/m-1", actions=(
        'var sec = document.querySelector("#v-scorecard details.erd-panel");'
        'var before = {open: sec.open, frame: !!sec.querySelector("iframe")};'
        'sec.querySelector("summary").click();'
        'setTimeout(function(){ window.__extra = {before: before, open: sec.open,'
        ' frame: !!sec.querySelector("iframe.erd-frame")}; }, 50);'), settle_ms=300)
    assert shown["errors"] == []
    assert shown["extra"] == {"before": {"open": False, "frame": False}, "open": True, "frame": True}


@needs_chrome
def test_the_data_cache_model_page_shows_that_model_and_a_way_back_to_all(tmp_path):
    rows = ('Array.prototype.map.call(document.querySelectorAll("#v-datacache tbody tr[data-state]"),'
            ' function(tr){ return tr.querySelector("a").textContent; })')
    shown = report_browser.render(_page(), tmp_path, "datacache/m-1", actions=(
        'var one = ' + rows + ';'
        'var back = document.querySelector("#v-datacache a.dc-all");'
        'var pills = document.querySelectorAll("#v-datacache .fbar, #v-datacache .fbar-chip").length;'
        'back.click();'
        'setTimeout(function(){ window.__extra = {one: one, back: back.getAttribute("href"),'
        ' text: back.parentNode.textContent, pills: pills, all: ' + rows + ','
        ' tabs: !!document.querySelector("#v-datacache .model-tabs")}; }, 50);'), settle_ms=300)
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["one"] == ["Sales"]
    assert x["back"] == "#datacache" and "Showing 1 Model of 2" in x["text"]
    assert x["pills"] == 0, "the list's filters are not on a Model's page"
    assert sorted(x["all"]) == ["Plain", "Sales"] and x["tabs"] is False


@needs_chrome
def test_the_lists_filter_does_not_hide_the_model_on_its_own_page(tmp_path):
    # Sales reads Not assessed (its Table's TML was not read): switch Not assessed off
    # on the list, which hides it there, then open Sales's page
    shown = report_browser.render(_page(), tmp_path, "datacache", actions=(
        'document.querySelector(\'#v-datacache .fbar-chip[data-f="unknown"]\').click();'
        'if(document.querySelectorAll("#v-datacache tbody tr[data-state]").length) throw "not filtered";'
        'location.hash = "#datacache/m-1";'
        'setTimeout(function(){ window.__extra = Array.prototype.map.call('
        ' document.querySelectorAll("#v-datacache tbody tr[data-state]"),'
        ' function(tr){ return tr.querySelector("a").textContent; }); }, 50);'), settle_ms=300)
    assert shown["errors"] == [] and shown["extra"] == ["Sales"]


@needs_chrome
def test_an_unknown_model_on_the_data_cache_route_says_so(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "datacache/no-such", actions=_NAV)
    assert shown["errors"] == []
    assert "This report has no such Model." in shown["visible"]
    assert shown["extra"]["tabs"] is None and shown["extra"]["crumb"] == "Audit / Data Cache"


@needs_chrome
@pytest.mark.parametrize("route, view, marker", [
    ("dashboard", "v-dashboard", "Sales"),
    ("datacache", "v-datacache", "2 of 2 Models shown"),
    ("formulas", "v-formulas", "Pick a Model"),
    ("model/m-1", "v-scorecard", "Sales"),
    ("formulas/m-1", "v-formulas", "Double Revenue"),
    ("formulas/m-1/graph", "v-formulas", "formulas, columns and parameters"),
])
def test_the_routes_reports_already_link_to_still_work(tmp_path, route, view, marker):
    shown = report_browser.render(_page(), tmp_path, route)
    assert shown["errors"] == [] and shown["active"] == view
    assert marker in shown["visible"]


@needs_chrome
def test_the_list_pages_carry_no_model_tabs(tmp_path):
    for route in ("datacache", "formulas", "dashboard"):
        shown = report_browser.render(_page(), tmp_path, route, actions=_NAV)
        assert shown["errors"] == [] and shown["extra"]["tabs"] is None, route


@needs_chrome
def test_tab_links_carry_an_awkward_guid_verbatim(tmp_path):
    # escaped, as the sidebar writes it ("&amp;" would read back as "&" unescaped); a
    # guid the browser percent-encodes in a hash ('"', '%') cannot round-trip any route
    guid = "m&amp;1'x"
    shown = report_browser.render(_page((guid, SALES)), tmp_path, "datacache", actions=(
        'location.hash = document.querySelector("#v-datacache tbody a").getAttribute("href");'
        'setTimeout(function(){ var tabs = document.querySelectorAll("#v-scorecard .model-tabs a");'
        ' window.__extra = Array.prototype.map.call(tabs, function(a){ return a.getAttribute("href"); });'
        '}, 50);'), settle_ms=300)
    assert shown["errors"] == []
    assert shown["extra"] == ["#model/" + guid, "#model/" + guid + "/erd", "#formulas/" + guid,
                              "#datacache/" + guid]


@needs_chrome
def test_no_data_cache_tab_when_the_performance_angle_did_not_run(tmp_path):
    """The same check as the Dashboard's Data Cache column: without P, every Model
    would read Not assessed."""
    ctx = make_context(models=[{"guid": "m-1", "model": SALES}], model_guids=["m-1"])
    page = render_report(run_audit(None, ["m-1"], ["D"], ctx=ctx))
    shown = report_browser.render(page, tmp_path, "model/m-1", actions=_NAV)
    assert shown["errors"] == []
    assert [t[0] for t in shown["extra"]["tabs"]] == ["scorecard", "erd", "formulas"]


@needs_chrome
@pytest.mark.parametrize("route, tabs", [
    ("formulas/m-9", ["scorecard", "erd", "formulas", "datacache"]),   # known, no formulas
    ("model/no-such", None), ("formulas/no-such", None), ("datacache/no-such", None),
])
def test_tabs_show_for_a_known_model_and_never_for_an_unknown_one(tmp_path, route, tabs):
    shown = report_browser.render(_page(), tmp_path, route, actions=_NAV)
    assert shown["errors"] == []
    got = shown["extra"]["tabs"]
    assert (None if got is None else [t[0] for t in got]) == tabs


_FRAME = ('function frame(){ return document.querySelector("#v-scorecard iframe.erd-frame"); }')


@needs_chrome
def test_the_inline_erd_survives_a_name_holding_script_markup(tmp_path):
    evil = dict(SALES, name="Sales </script><!--<script> x")
    shown = report_browser.render(_page(("m-1", evil)), tmp_path, "model/m-1/erd", actions=_FRAME + (
        'setTimeout(function(){ var h = frame().contentDocument.querySelector(".brand h1");'
        ' window.__extra = h && h.textContent; }, 300);'), settle_ms=600)
    assert shown["errors"] == []
    assert shown["extra"] == "Sales </script><!--<script> x"


@needs_chrome
def test_the_inline_erds_share_html_works(tmp_path):
    """It reads the data script by id="erd-data"; without the id it did nothing."""
    shown = report_browser.render(_page(), tmp_path, "model/m-1/erd", actions=_FRAME + (
        'setTimeout(function(){ var w = frame().contentWindow, html = null, RB = w.Blob;'
        ' w.Blob = function(parts, o){ html = parts.join(""); return new RB(parts, o); };'
        ' w.URL.createObjectURL = function(){ return "blob:x"; };'
        ' w.HTMLAnchorElement.prototype.click = function(){};'
        ' w.document.getElementById("share-btn").click();'
        ' window.__extra = !!html && html.indexOf("window.ERD_INITIAL_STATE") !== -1'
        '  && html.indexOf("Sales") !== -1; }, 300);'), settle_ms=600)
    assert shown["errors"] == [] and shown["extra"] is True


@needs_chrome
def test_the_erd_tab_reopens_a_closed_erd_on_its_own_route(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "model/m-1/erd", actions=(
        'var sec = document.querySelector("#v-scorecard details.erd-panel"); sec.open = false;'
        'document.querySelector(\'#v-scorecard .model-tabs a[data-tab="erd"]\').click();'
        'window.__extra = {open: sec.open, hash: location.hash};'))
    assert shown["errors"] == []
    assert shown["extra"] == {"open": True, "hash": "#model/m-1/erd"}
