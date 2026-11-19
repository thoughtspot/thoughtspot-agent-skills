"""The Formulas view's type chips and legend (report/formula_types.js): Columns,
Parameters, Measure formulas and Attribute formulas (a formula of no stated kind counts
as an attribute), shared by the tree and the graph for the session. The graph hides a
switched-off type's nodes and edges; the tree hides its rows, keeping a switched-off
formula, faded, when something shown is under it."""
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


#: Two measures, two attributes and a helper no column surfaces (no stated kind).
TYPES = {
    "name": "Typed",
    "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
    "parameters": [{"name": "Sep", "data_type": "VARCHAR"}],
    "formulas": [
        _f("formula_Rev", "Revenue", "sum ( [ORDERS::AMOUNT] )"),
        _f("formula_Helper", "Helper", "sum ( [ORDERS::COST] ) * 2"),
        _f("formula_Top", "Top", "[formula_Rev] + [formula_Helper]"),
        _f("formula_Region", "Region Label", "concat ( [ORDERS::REGION] , [Sep] )"),
        _f("formula_Label2", "Label Two", "concat ( [formula_Region] , 'x' )"),
    ],
    "columns": [_col("Revenue", "formula_Rev"), _col("Top", "formula_Top"),
                _col("Region Label", "formula_Region", "ATTRIBUTE"),
                _col("Label Two", "formula_Label2", "ATTRIBUTE")],
}


def _page(*models):
    models = models or (("m-1", TYPES),)
    ctx = make_context(models=[{"guid": g, "model": m} for g, m in models],
                       model_guids=[g for g, _ in models])
    return render_report(run_audit(None, [g for g, _ in models], ctx=ctx))


def _chip(t):
    return 'document.querySelector(\'#v-formulas .ftype-chip[data-ftype="' + t + '"]\')'


_CY = 'function cy(){ return document.getElementById("v-formulas")._cy; }'
_LABELS = 'function labels(){ return cy().nodes().map(function(n){ return n.data("label"); }).sort(); }'
_CHIPS = ('function chips(){ return Array.prototype.map.call(document.querySelectorAll('
          '"#v-formulas .ftype-chip"), function(b){ return [b.getAttribute("data-ftype"),'
          ' b.getAttribute("aria-pressed"), b.querySelector(".ftype-count").textContent]; }); }')
ALL = sorted(["Revenue", "Helper", "Top", "Region Label", "Label Two",
              "ORDERS::AMOUNT", "ORDERS::COST", "ORDERS::REGION", "Sep"])


@needs_chrome
def test_the_graph_hides_a_switched_off_type_and_its_edges_and_restores_it(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "formulas/m-1/graph", actions=_CY + _LABELS + _CHIPS + (
        'var first = {chips: chips(), nodes: labels(), edges: cy().edges().length};'
        + _chip("column") + '.click();'
        'var noCols = {nodes: labels(), edges: cy().edges().length, pressed: chips()[0][1],'
        ' sub: document.querySelector("#v-formulas .fgraph-sub").textContent};'
        + _chip("attribute") + '.click();'
        'var noAttr = labels();'
        + _chip("column") + '.click();' + _chip("attribute") + '.click();'
        'window.__extra = {first: first, noCols: noCols, noAttr: noAttr, back: labels(),'
        ' edges: cy().edges().length, chips: chips()};'))
    assert shown["errors"] == []
    x = shown["extra"]
    # Helper has no column: it is counted with the attributes
    assert x["first"]["chips"] == [["column", "true", "3"], ["parameter", "true", "1"],
                                   ["measure", "true", "2"], ["attribute", "true", "3"]]
    assert x["first"]["nodes"] == ALL and x["first"]["edges"] == 7
    assert x["noCols"]["nodes"] == sorted(["Revenue", "Helper", "Top", "Region Label", "Label Two", "Sep"])
    assert x["noCols"]["edges"] == 4      # Top's two, Region Label's parameter, Label Two's
    assert x["noCols"]["pressed"] == "false"
    assert "6 formulas, columns and parameters (3 more switched off by the type chips)" in x["noCols"]["sub"]
    assert x["noAttr"] == sorted(["Revenue", "Top", "Sep"])
    assert x["back"] == ALL and x["edges"] == 7
    assert all(c[1] == "true" for c in x["chips"])


@needs_chrome
def test_each_type_has_one_mark_in_the_graph_and_the_legend(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "formulas/m-1/graph", actions=_CY + (
        'function shapes(cls){ return cy().$("node." + cls).map(function(n){'
        '  return [n.data("label"), n.style("shape")]; }).sort(); }'
        'var legend = document.querySelector("#v-formulas .ftype-legend");'
        'window.__extra = {measure: shapes("measure"), attribute: shapes("attribute"),'
        ' nokind: shapes("nokind"), column: shapes("column"), parameter: shapes("parameter"),'
        ' keys: Array.prototype.map.call(legend.querySelectorAll(".ftype-key"), function(k){'
        '  var s = k.querySelector("svg"); return [s ? s.getAttribute("class") : null, k.textContent]; })};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["measure"] == [["Revenue", "round-rectangle"], ["Top", "round-rectangle"]]
    assert x["attribute"] == [["Label Two", "cut-rectangle"], ["Region Label", "cut-rectangle"]]
    assert x["nokind"] == [["Helper", "barrel"]]
    assert {s for _, s in x["column"]} == {"rectangle"} and x["parameter"] == [["Sep", "tag"]]
    assert x["keys"] == [
        ["ftype-ico ftype-column", "Table column"], ["ftype-ico ftype-parameter", "Parameter"],
        ["ftype-ico ftype-measure", "Measure formula"], ["ftype-ico ftype-attribute", "Attribute formula"],
        ["ftype-ico ftype-nokind", "Formula of no stated kind (with Attribute formulas)"],
        [None, "Dashed: hidden"], [None, "Amber: hidden, used once (H16)"]]


_ROWS = ('function rows(){ return Array.prototype.filter.call(document.querySelectorAll('
         '"#v-formulas .ftree-row[role=button]"), function(r){ return r.offsetParent !== null; })'
         '.map(function(r){ var n = r.querySelector(".ftree-name, .ftree-col");'
         ' return [n.textContent, r.parentNode.classList.contains("ftree-dimmed")]; }); }')


@needs_chrome
def test_the_tree_hides_rows_and_keeps_a_switched_off_formula_with_shown_rows_under_it(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "formulas/m-1", actions=_ROWS + (
        'document.querySelector(".ftree-expand").click();'
        'var all = rows();'
        + _chip("column") + '.click();' + _chip("measure") + '.click();'
        'var off = rows();'
        + _chip("column") + '.click();' + _chip("measure") + '.click();'
        'window.__extra = {all: all, off: off, back: rows(),'
        ' marks: document.querySelectorAll("#v-formulas .ftype-off, #v-formulas .ftree-dimmed").length,'
        ' icons: Array.prototype.map.call(document.querySelectorAll("#v-formulas .ftree-row svg.ftype-ico"),'
        '  function(s){ return s.getAttribute("aria-label"); }).filter(function(v, i, a){ return a.indexOf(v) === i; }).sort()};'))
    assert shown["errors"] == []
    x = shown["extra"]
    names = [r[0] for r in x["all"]]
    assert names == ["Top", "Revenue", "ORDERS::AMOUNT", "Helper", "ORDERS::COST",
                     "Label Two", "Region Label", "ORDERS::REGION", "Sep"]
    # columns and measures off: Revenue (a measure over a column) goes; Top, a measure,
    # stays faded because Helper, of no stated kind (an attribute), is under it
    assert x["off"] == [["Top", True], ["Helper", False], ["Label Two", False],
                        ["Region Label", False], ["Sep", False]]
    assert x["back"] == x["all"] and x["marks"] == 0
    assert x["icons"] == sorted(["Attribute formula", "Formula of no stated kind (with Attribute formulas)",
                                 "Measure formula", "Parameter", "Table column"])


@needs_chrome
def test_search_leaves_out_switched_off_types_and_counts_them(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "formulas/m-1", actions=(
        'var s = document.querySelector("#v-formulas .ftree-search");'
        's.value = "re"; s.dispatchEvent(new Event("input"));'
        'function hits(){ var r = document.querySelector("#v-formulas .ftree-results");'
        ' return [Array.prototype.map.call(r.querySelectorAll("a.fref"), function(a){ return a.textContent; }),'
        '  (r.querySelector(".ftype-offcount") || {}).textContent || ""]; }'
        'var before = hits();' + _chip("column") + '.click();'
        'window.__extra = {before: before, after: hits()};'))
    assert shown["errors"] == []
    x = shown["extra"]
    # columns and parameters by name, then formulas by name, then by definition
    assert x["before"] == [["ORDERS::REGION", "Revenue", "Region Label", "Top", "Label Two"], ""]
    assert x["after"] == [["Revenue", "Region Label", "Top", "Label Two"], "1 more of a switched-off type"]


@needs_chrome
def test_a_link_to_a_switched_off_node_says_so_and_offers_to_show_it(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "formulas/m-1/graph", actions=_CY + (
        _chip("column") + '.click();'
        'cy().nodes().filter(function(n){ return n.data("label") === "Revenue"; }).emit("tap");'
        'var p = document.querySelector("#v-formulas .fdetail");'
        'Array.prototype.find.call(p.querySelectorAll("a.fref"), function(a){'
        '  return a.textContent === "ORDERS::AMOUNT"; }).click();'
        'var note = document.querySelector("#v-formulas .ftype-note");'
        'var said = {note: note.textContent, title: p.querySelector(".fdetail-title").textContent,'
        ' focus: cy().$(".focus").length};'
        'note.querySelector(".ftype-reveal").click();'
        'window.__extra = {said: said, after: note.textContent,'
        ' pressed: ' + _chip("column") + '.getAttribute("aria-pressed"),'
        ' focus: cy().$(".focus").map(function(n){ return n.data("label"); }),'
        ' active: document.activeElement.getAttribute("data-ftype")};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["said"]["title"] == "ORDERS::AMOUNT", "the definition still opens"
    assert x["said"]["focus"] == 0
    assert "ORDERS::AMOUNT is not shown: Columns are switched off." in x["said"]["note"]
    assert "Show columns" in x["said"]["note"]
    assert x["after"] == "" and x["pressed"] == "true"
    assert x["focus"] == ["ORDERS::AMOUNT"] and x["active"] == "column"


@needs_chrome
def test_the_chips_hold_across_the_tree_and_the_graph(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "formulas/m-1", actions=_CY + (
        _chip("parameter") + '.click();'
        'location.hash = "#formulas/m-1/graph";'
        'setTimeout(function(){ window.__extra = {pressed: ' + _chip("parameter") + '.getAttribute("aria-pressed"),'
        ' params: cy().$("node.parameter").length, legend: !!document.querySelector("#v-formulas .ftype-legend")}; }, 50);'),
        settle_ms=300)
    assert shown["errors"] == []
    assert shown["extra"] == {"pressed": "false", "params": 0, "legend": True}


def _big(n):
    """n formulas in chains of five, each link one column: past the graph's cap."""
    formulas, columns = [], []
    for i in range(n):
        expr = f"sum ( [ORDERS::C{i}] )" if i % 5 == 0 else f"[formula_F{i - 1}] + [ORDERS::C{i}]"
        formulas.append(_f(f"formula_F{i}", f"F{i}", expr))
        columns.append(_col(f"F{i}", f"formula_F{i}"))
    return {"name": "Big", "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
            "formulas": formulas, "columns": columns}


@needs_chrome
def test_past_the_cap_switching_columns_off_can_draw_the_model_whole(tmp_path):
    shown = report_browser.render(_page(("m-3", _big(200))), tmp_path, "formulas/m-3/graph", actions=_CY + (
        'var before = cy().nodes().length;' + _chip("column") + '.click();'
        'window.__extra = {before: before, after: cy().nodes().length,'
        ' sub: document.querySelector("#v-formulas .fgraph-sub").textContent};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["before"] == 10       # one chain of five formulas and their five columns
    assert x["after"] == 200
    assert x["sub"].startswith("200 formulas, columns and parameters (200 more switched off")


@needs_chrome
def test_the_tree_shows_the_legend_and_says_when_every_type_is_off(tmp_path):
    shown = report_browser.render(_page(), tmp_path, "formulas/m-1", actions=(
        'var legend = document.querySelector("#v-formulas .ftype-legend").textContent;'
        'Array.prototype.forEach.call(document.querySelectorAll("#v-formulas .ftype-chip"),'
        ' function(b){ b.click(); });'
        'window.__extra = {legend: legend, note: document.querySelector("#v-formulas .ftree-note").textContent,'
        ' rows: Array.prototype.filter.call(document.querySelectorAll("#v-formulas .ftree-row[role=button]"),'
        '  function(r){ return r.offsetParent !== null; }).length};'))
    assert shown["errors"] == []
    x = shown["extra"]
    for text in ("Table column", "Parameter", "Measure formula", "Attribute formula",
                 "Faded: switched off, kept for what is shown under it"):
        assert text in x["legend"]
    assert x["rows"] == 0 and "Every type is switched off" in x["note"]
