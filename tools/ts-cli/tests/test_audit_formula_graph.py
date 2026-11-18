"""The Formulas view's graph mode (report/formula_graph.js) and its vendored libraries
(ts_cli/audit/vendor/), carried in the data only when some Model has a formula chain."""
from __future__ import annotations

import hashlib
import json
import re

import pytest

import report_browser
from ts_cli.audit import run_audit
from ts_cli.audit.context import make_context
from ts_cli.audit.report import (GRAPH_VENDOR, VENDOR_DIR, compact_payload, has_formula_chains,
                                 render_report)

needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")


def _f(fid, name, expr):
    return {"id": fid, "name": name, "expr": expr}


def _col(name, fid, kind="MEASURE", hidden=False):
    props = {"column_type": kind}
    if hidden:
        props["is_hidden"] = True
    return {"name": name, "formula_id": fid, "properties": props}


CHAIN = {
    "name": "Sales",
    "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
    "parameters": [{"name": "Rate", "data_type": "DOUBLE"}],
    "formulas": [
        _f("formula_Rev", "Revenue", "sum ( [ORDERS::AMOUNT] )"),
        _f("formula_Cost", "Cost", "sum ( [ORDERS::COST] )"),
        _f("formula_GM", "Gross Margin", "[formula_Rev] - [formula_Cost]"),
        _f("formula_GMP", "Gross Margin %", "[formula_GM] / [formula_Rev] * [Rate]"),
        _f("formula_Cnt", "Order Count", "count ( [ORDERS::ORDER_ID] )"),
    ],
    "columns": [_col("Revenue", "formula_Rev"), _col("Cost", "formula_Cost", hidden=True),
                _col("Gross Margin", "formula_GM"), _col("Gross Margin %", "formula_GMP"),
                _col("Order Count", "formula_Cnt")],
}
#: Formulas, but none built on another: no graph, no libraries.
FLAT = {
    "name": "Flat",
    "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
    "formulas": [_f("formula_A", "A", "sum ( [ORDERS::A] )"), _f("formula_B", "B", "max ( [ORDERS::B] )")],
    "columns": [_col("A", "formula_A"), _col("B", "formula_B")],
}


def _data(*models):
    ctx = make_context(models=[{"guid": g, "model": m} for g, m in models],
                       model_guids=[g for g, _ in models])
    return run_audit(None, [g for g, _ in models], ctx=ctx)


def _report(*models):
    return render_report(_data(*models))


def _big(n):
    """A Model of n formulas in chains of five, each link one column: past the cap."""
    formulas, columns = [], []
    for i in range(n):
        expr = f"sum ( [ORDERS::C{i}] )" if i % 5 == 0 else f"[formula_F{i - 1}] + [ORDERS::C{i}]"
        formulas.append(_f(f"formula_F{i}", f"F{i}", expr))
        columns.append(_col(f"F{i}", f"formula_F{i}"))
    return {"name": "Big", "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
            "formulas": formulas, "columns": columns}


# ── data ────────────────────────────────────────────────────────────────────

def test_the_libraries_travel_only_with_a_formula_chain():
    assert has_formula_chains(compact_payload(_data(("m-1", CHAIN))))
    assert not has_formula_chains(compact_payload(_data(("m-2", FLAT))))
    assert not has_formula_chains({})
    chained, flat = _report(("m-1", CHAIN)), _report(("m-2", FLAT))
    data = {}
    for name, page in (("chained", chained), ("flat", flat)):
        data[name] = json.loads(re.search(r'<script id="audit-data" type="application/json">(.*?)</script>', page, re.S).group(1))
    # the libraries, in load order, beside the catalog meta (key G), not in place of it
    v = data["chained"]["V"]
    assert v.startswith("/*") and v.count("Permission is hereby granted") >= 3   # the licences, first
    code = v[v.index("*/") + 2:]
    marks = [code.index(m) for m in ("g.dagre=f()", "The Cytoscape Consortium", "cytoscapeDagre")]
    assert marks == sorted(marks)
    assert "V" not in data["flat"]
    assert data["chained"]["G"] == data["flat"]["G"] and "categories" in data["chained"]["G"]
    assert "<script src=" not in chained and "<script src=" not in flat
    assert len(chained) - len(flat) > 400_000


def test_every_vendored_file_matches_its_pinned_hash_and_has_a_licence():
    lines = (VENDOR_DIR / "MANIFEST").read_text(encoding="utf-8").split("\n")
    pinned = {name: digest for digest, name in (l.split(None, 1) for l in lines if l.strip())}
    assert sorted(pinned) == sorted(GRAPH_VENDOR)
    for name, digest in pinned.items():
        assert hashlib.sha256((VENDOR_DIR / name).read_bytes()).hexdigest() == digest, name
    on_disk = {p.name for p in VENDOR_DIR.iterdir()}
    assert on_disk - set(pinned) == {"MANIFEST", "README.md", "LICENSE-cytoscape", "LICENSE-dagre",
                                     "LICENSE-cytoscape-dagre"}
    for lic in ("LICENSE-cytoscape", "LICENSE-dagre", "LICENSE-cytoscape-dagre"):
        assert "Permission is hereby granted" in (VENDOR_DIR / lic).read_text(encoding="utf-8")


# ── browser ─────────────────────────────────────────────────────────────────

_CY = 'var cy = document.getElementById("v-formulas")._cy;'
_LABELS = 'function labels(s){ return cy.$(s).map(function(n){ return n.data("label"); }).sort(); }'


@needs_chrome
def test_the_graph_draws_every_formula_column_and_parameter(tmp_path):
    shown = report_browser.render(_report(("m-1", CHAIN)), tmp_path, "formulas/m-1/graph",
                                  actions=_CY + _LABELS + (
        'window.__extra = {nodes: labels("node"), edges: cy.edges().length,'
        ' gm: cy.edges("[target = \\"f2\\"]").map(function(e){ return e.source().data("label"); }).sort(),'
        ' hidden: labels("node.hidden"), single: labels("node.single"),'
        ' columns: labels("node.column"), params: labels("node.parameter")};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["nodes"] == sorted(["Revenue", "Cost", "Gross Margin", "Gross Margin %", "Order Count",
                                 "ORDERS::AMOUNT", "ORDERS::COST", "ORDERS::ORDER_ID", "Rate"])
    assert x["edges"] == 8           # 3 columns + GM's 2 + GMP's 3 (GM, Revenue, Rate)
    assert x["gm"] == ["Cost", "Revenue"]   # an edge runs from what is used to its user
    assert x["hidden"] == ["Cost"] and x["single"] == ["Cost"]
    assert x["columns"] == ["ORDERS::AMOUNT", "ORDERS::COST", "ORDERS::ORDER_ID"]
    assert x["params"] == ["Rate"]
    assert "9 formulas, columns and parameters" in shown["visible"]


@needs_chrome
def test_a_node_opens_its_definition_and_lights_its_lineage(tmp_path):
    shown = report_browser.render(_report(("m-1", CHAIN)), tmp_path, "formulas/m-1/graph",
                                  actions=_CY + _LABELS + (
        'cy.getElementById("f2").emit("tap");'
        'var p = document.querySelector("#v-formulas .fdetail");'
        'var title = p.querySelector(".fdetail-title").textContent;'
        'var lit = cy.nodes().filter(function(n){ return !n.hasClass("faded"); })'
        '  .map(function(n){ return n.data("label"); }).sort();'
        # a link in the panel moves the graph to that node
        'Array.prototype.find.call(p.querySelectorAll("a.fref"), function(a){'
        '  return a.textContent === "[formula_Rev]"; }).click();'
        'window.__extra = {title: title, lit: lit, focus: labels("node.focus"),'
        ' title2: p.querySelector(".fdetail-title").textContent};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["title"] == "Gross Margin"
    # upstream (Revenue, Cost and their columns) and downstream (Gross Margin %), not Order Count
    assert x["lit"] == sorted(["Gross Margin", "Revenue", "Cost", "ORDERS::AMOUNT", "ORDERS::COST",
                               "Gross Margin %"])
    assert x["focus"] == ["Revenue"] and x["title2"] == "Revenue"


@needs_chrome
def test_the_tree_and_the_graph_link_each_other_and_keep_the_selection(tmp_path):
    page = _report(("m-1", CHAIN))
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=(
        'var mode = document.querySelector("#v-formulas .fgraph-mode").getAttribute("href");'
        'var row = Array.prototype.find.call(document.querySelectorAll("#v-formulas .ftree-row"),'
        '  function(r){ var n = r.querySelector(".ftree-name"); return n && n.textContent === "Gross Margin %"; });'
        'row.click(); location.hash = "#formulas/m-1/graph";'
        'setTimeout(function(){ var cy = document.getElementById("v-formulas")._cy;'
        '  window.__extra = {mode: mode, focus: cy && cy.$(".focus").map(function(n){ return n.data("label"); }),'
        '   title: document.querySelector("#v-formulas .fdetail-title").textContent,'
        '   back: document.querySelector("#v-formulas .fgraph-mode").getAttribute("href")}; }, 20);'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["mode"] == "#formulas/m-1/graph" and x["back"] == "#formulas/m-1"
    assert x["focus"] == ["Gross Margin %"] and x["title"] == "Gross Margin %"


@needs_chrome
def test_a_model_with_no_chain_has_no_graph_and_the_graph_route_shows_the_tree(tmp_path):
    page = _report(("m-1", CHAIN), ("m-2", FLAT))
    shown = report_browser.render(page, tmp_path, "formulas/m-2/graph", actions=(
        'window.__extra = {link: !!document.querySelector("#v-formulas .fgraph-mode"),'
        ' tree: !!document.querySelector("#v-formulas ul.ftree"),'
        ' graph: !!document.querySelector("#v-formulas .fgraph")};'))
    assert shown["errors"] == []
    assert shown["extra"] == {"link": False, "tree": True, "graph": False}
    # a report with no chain anywhere: no libraries, no graph link either
    flat = report_browser.render(_report(("m-2", FLAT)), tmp_path, "formulas/m-2/graph", actions=(
        'window.__extra = !!document.querySelector("#v-formulas .fgraph-mode");'))
    assert flat["errors"] == [] and flat["extra"] is False


@needs_chrome
def test_a_model_past_the_cap_is_drawn_one_lineage_at_a_time(tmp_path):
    page = _report(("m-3", _big(200)))   # 200 formulas + 200 columns = 400 nodes
    shown = report_browser.render(page, tmp_path, "formulas/m-3/graph", actions=_CY + _LABELS + (
        'var first = labels("node.formula");'
        'Array.prototype.find.call(document.querySelectorAll("#v-formulas .ftree-search"), function(){ return true; });'
        'var s = document.querySelector("#v-formulas .ftree-search");'
        's.value = "F102"; s.dispatchEvent(new Event("input"));'
        'Array.prototype.find.call(document.querySelectorAll("#v-formulas .ftree-results a.fref"),'
        '  function(a){ return a.textContent === "F102"; }).click();'
        'cy = document.getElementById("v-formulas")._cy;'
        'window.__extra = {first: first, after: labels("node.formula"),'
        ' sub: document.querySelector("#v-formulas .fgraph-sub").textContent};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert len(x["first"]) == 5 and len(x["after"]) == 5        # one chain of five
    assert "F102" in x["after"] and x["first"] != x["after"]
    assert "400 formulas, columns and parameters, too many to draw at once" in x["sub"]
    assert "lineage of F102" in x["sub"]


_IN_VIEW = ('function inView(cy){ var n = cy.$(".focus"); if(!n.length) return null;'
            ' var b = n.renderedBoundingBox();'
            ' return b.x1 >= 0 && b.y1 >= 0 && b.x2 <= cy.width() && b.y2 <= cy.height(); }')


@needs_chrome
def test_a_selection_carried_from_the_tree_lands_in_view(tmp_path):
    shown = report_browser.render(_report(("m-1", CHAIN)), tmp_path, "formulas/m-1", actions=_IN_VIEW + (
        'var row = Array.prototype.find.call(document.querySelectorAll("#v-formulas .ftree-row"),'
        '  function(r){ var n = r.querySelector(".ftree-name"); return n && n.textContent === "Gross Margin %"; });'
        'row.click(); location.hash = "#formulas/m-1/graph";'
        'setTimeout(function(){'
        '  var cy = document.getElementById("v-formulas")._cy; window.__extra = inView(cy); }, 100);'),
        settle_ms=400)
    assert shown["errors"] == []
    assert shown["extra"] is True


@needs_chrome
def test_rebuilding_the_view_destroys_the_last_graph(tmp_path):
    shown = report_browser.render(_report(("m-1", CHAIN)), tmp_path, "formulas/m-1/graph", actions=(
        'var first = document.getElementById("v-formulas")._cy;'
        'location.hash = "#formulas/m-1";'
        'setTimeout(function(){ window.__extra = {destroyed: first.destroyed(),'
        ' left: document.getElementById("v-formulas")._cy || null}; }, 20);'))
    assert shown["errors"] == []
    assert shown["extra"] == {"destroyed": True, "left": None}


@needs_chrome
def test_a_model_past_the_cap_opens_on_a_lineage_under_it(tmp_path):
    hub = {"name": "Hub", "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
           "formulas": [_f(f"formula_H{i}", f"H{i}", f"sum ( [ORDERS::C{i}] )") for i in range(200)]
           + [_f("formula_Total", "Total", " + ".join(f"[formula_H{i}]" for i in range(200))),
              _f("formula_S0", "S0", "sum ( [ORDERS::S] )"), _f("formula_S1", "S1", "[formula_S0] * 2")],
           "columns": [_col("Total", "formula_Total"), _col("S1", "formula_S1")]}
    shown = report_browser.render(_report(("m-4", hub)), tmp_path, "formulas/m-4/graph", actions=(
        'window.__extra = document.getElementById("v-formulas")._cy.nodes().length;'))
    assert shown["errors"] == []
    assert 0 < shown["extra"] <= 300    # S1's lineage, not Total's 401 nodes


@needs_chrome
def test_a_selection_carried_to_the_tree_is_scrolled_into_view(tmp_path):
    shown = report_browser.render(_report(("m-3", _big(200))), tmp_path, "formulas/m-3/graph", actions=(
        'var s = document.querySelector("#v-formulas .ftree-search");'
        's.value = "F197"; s.dispatchEvent(new Event("input"));'
        'Array.prototype.find.call(document.querySelectorAll("#v-formulas .ftree-results a.fref"),'
        '  function(a){ return a.textContent === "F197"; }).click();'
        'location.hash = "#formulas/m-3";'
        'setTimeout(function(){'
        '  var r = document.querySelector("#v-formulas .ftree-selected");'
        '  var b = r && r.getBoundingClientRect();'
        '  window.__extra = !!b && b.top >= 0 && b.bottom <= window.innerHeight; }, 100);'),
        settle_ms=400)
    assert shown["errors"] == []
    assert shown["extra"] is True
