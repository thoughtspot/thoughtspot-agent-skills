"""The report's formula dependency tree (audit v2 roadmap PR 3.2): the data
(ts_cli/audit/formula_tree.py) and the Formulas view (report/views/formulas.js)."""
from __future__ import annotations

import re

import pytest

import report_browser
from ts_cli.audit import run_audit
from ts_cli.audit.context import make_context
from ts_cli.audit.formula_tree import formula_tree
from ts_cli.audit.report import render_report

needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")


def _f(fid, name, expr):
    return {"id": fid, "name": name, "expr": expr}


def _col(name, fid, kind="MEASURE", hidden=False):
    props = {"column_type": kind}
    if hidden:
        props["is_hidden"] = True
    return {"name": name, "formula_id": fid, "properties": props}


MODEL = {
    "name": "Sales",
    "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
    "formulas": [
        _f("formula_GMP", "Gross Margin %", "[formula_GM] / [formula_Rev]"),
        _f("formula_GM", "Gross Margin", "[formula_Rev] - [Cost]"),   # display-name ref
        _f("formula_Rev", "Revenue", "sum ( [ORDERS::AMOUNT] )"),
        _f("formula_Cost", "Cost", "sum ( [ORDERS::COST] )"),
        _f("formula_Cnt", "Order Count", "count ( [ORDERS::ORDER_ID] ) + [formula_Cnt]"),
        _f("formula_A", "Loop A", "[formula_B] + 1"),
        _f("formula_B", "Loop B", "[formula_A] + 1"),
    ],
    "columns": [
        _col("Gross Margin %", "formula_GMP"),
        _col("Gross Margin", "formula_GM", hidden=True),
        _col("Revenue", "formula_Rev"),
        _col("Order Count", "formula_Cnt"),
        _col("Loop A", "formula_A", kind="ATTRIBUTE"),
    ],
}


def _node(tree, name):
    return next(n for n in tree["nodes"] if n["name"] == name)


def test_nodes_carry_kind_hidden_uses_and_used_by():
    tree = formula_tree(MODEL)
    gm = _node(tree, "Gross Margin")
    assert (gm["kind"], gm["hidden"], gm["used_by"]) == ("MEASURE", True, 1)
    assert gm["uses"] == [{"formula": "Revenue"}, {"formula": "Cost"}]
    assert _node(tree, "Revenue")["used_by"] == 2
    assert _node(tree, "Revenue")["uses"] == [{"column": "ORDERS::AMOUNT"}]
    cost = _node(tree, "Cost")  # surfaced by no column: a hidden helper, kind unknown
    assert (cost["kind"], cost["hidden"]) == (None, True)
    assert _node(tree, "Loop A")["kind"] == "ATTRIBUTE"


def test_roots_are_what_nothing_uses_and_a_self_reference_is_not_a_use():
    tree = formula_tree(MODEL)
    assert _node(tree, "Order Count")["uses"] == [{"column": "ORDERS::ORDER_ID"}]
    assert tree["roots"][:2] == ["Gross Margin %", "Order Count"]


def test_a_cycle_reachable_from_no_root_is_rooted_once():
    tree = formula_tree(MODEL)
    assert tree["roots"] == ["Gross Margin %", "Order Count", "Loop A"]
    assert _node(tree, "Loop A")["used_by"] == 1


def test_no_formulas_is_an_empty_tree_and_malformed_entries_are_skipped():
    assert formula_tree({}) == {"nodes": [], "roots": []}
    tree = formula_tree({"formulas": [None, {"expr": "x"}, _f("f1", "Only", 5)]})
    assert [n["name"] for n in tree["nodes"]] == ["Only"]


# References by display name and to parameters, quoted literals, labels, duplicates.
EDGES = {
    "name": "Edges",
    "parameters": [{"name": "Rate", "data_type": "DOUBLE"}],
    "formulas": [
        _f("formula_Margin", "margin_f",
           "[Net Sales] * [Rate] + strlen ( 'x[ORDERS::FAKE]' ) + strlen ( \"[Old Calc]\" )"),
        _f("formula_Net", "net_sales_f", "sum ( [ORDERS::AMOUNT] )"),
        _f("formula_Old", "Old Calc", "sum ( [ORDERS::AMOUNT] )"),
        _f("formula_Dup", "Dup",
           "[formula_Net] + [net_sales_f] + [Net Sales] + [ORDERS::X] + [ORDERS::X]"),
    ],
    "columns": [
        _col("Margin", "formula_Margin"),
        _col("Net Sales", "formula_Net"),
        _col("Old Calc", "formula_Old", hidden=True),
        _col("Dup", "formula_Dup"),
    ],
}


def test_display_names_parameters_and_quoted_literals():
    tree = formula_tree(EDGES)
    margin = _node(tree, "margin_f")
    # [Net Sales] is the display name of net_sales_f's column; [Rate] a parameter; the
    # bracket text inside both quoted literals is not a reference at all
    assert margin["uses"] == [{"formula": "net_sales_f"}, {"parameter": "Rate"}]
    assert margin["label"] == "Margin"
    assert _node(tree, "net_sales_f")["label"] == "Net Sales"
    assert _node(tree, "Old Calc")["used_by"] == 0


@pytest.mark.parametrize("expr, uses", [
    # a quote inside a reference opens no literal (BL-369, BL-379)
    ("if ( [ORDERS::Men's Sales] > 0 ) then [formula_Net] else [ORDERS::Women's Sales]",
     [{"column": "ORDERS::Men's Sales"}, {"formula": "net_sales_f"},
      {"column": "ORDERS::Women's Sales"}]),
    ("[Customer's Count] + [Net Sales]",
     [{"column": "Customer's Count"}, {"formula": "net_sales_f"}]),
    ("if ( [T::Men's] = 'x' ) then [formula_Net] else 0",
     [{"column": "T::Men's"}, {"formula": "net_sales_f"}]),
    ('[T::a "b"] + [formula_Net] + strlen ( "[T::lit]" )',
     [{"column": 'T::a "b"'}, {"formula": "net_sales_f"}]),
])
def test_a_quote_inside_a_reference_is_part_of_its_name(expr, uses):
    model = {"formulas": [_f("formula_Top", "Top", expr),
                          _f("formula_Net", "net_sales_f", "sum ( [T::X] )")],
             "columns": [_col("Net Sales", "formula_Net", hidden=True)]}
    tree = formula_tree(model)
    assert _node(tree, "Top")["uses"] == uses
    assert _node(tree, "net_sales_f")["used_by"] == 1 and tree["roots"] == ["Top"]


def test_malformed_ids_and_names_are_ignored_not_fatal():
    model = {"formulas": [{"id": {"x": 1}, "name": "A", "expr": "[T::X]"},
                          {"id": "formula_B", "name": ["B"], "expr": "[T::Y]"},
                          _f("formula_C", "C", "[A]")],
             "columns": [{"name": "Col", "formula_id": ["formula_C"]}, _col("C", "formula_C")]}
    tree = formula_tree(model)
    assert [n["name"] for n in tree["nodes"]] == ["A", "C"]
    assert _node(tree, "C")["uses"] == [{"formula": "A"}]


def test_each_node_carries_its_expression_as_written_with_references_resolved():
    tree = formula_tree(EDGES)
    # references resolve exactly as `uses` does, each keeping how it was written; quoted
    # literals stay text even when they hold bracket text (adjacent text is one
    # segment); every occurrence is kept
    assert _node(tree, "margin_f")["expr"] == [
        {"formula": "net_sales_f", "ref": "[Net Sales]"}, " * ",
        {"parameter": "Rate", "ref": "[Rate]"},
        " + strlen ( 'x[ORDERS::FAKE]' ) + strlen ( \"[Old Calc]\" )"]
    assert [s["ref"] for s in _node(tree, "Dup")["expr"] if isinstance(s, dict)] == [
        "[formula_Net]", "[net_sales_f]", "[Net Sales]", "[ORDERS::X]", "[ORDERS::X]"]
    # a self-reference is not a use, but the text still shows it
    cnt = _node(formula_tree(MODEL), "Order Count")
    assert cnt["expr"][-1] == {"formula": "Order Count", "ref": "[formula_Cnt]"}
    # rejoined, the segments are the expression as written
    assert "".join(s if isinstance(s, str) else s["ref"] for s in cnt["expr"]) == \
        "count ( [ORDERS::ORDER_ID] ) + [formula_Cnt]"


@pytest.mark.parametrize("expr, segments", [
    ("[T::Men's] + 1", [{"column": "T::Men's", "ref": "[T::Men's]"}, " + 1"]),  # BL-369
    (5, ["5"]),                                                 # YAML read a number
    (None, []), ({"x": 1}, []), (["[A]"], []),
])
def test_an_expression_that_is_not_plain_text_is_still_shown_safely(expr, segments):
    node = formula_tree({"formulas": [_f("formula_A", "A", expr)]})["nodes"][0]
    assert node["expr"] == segments
    assert node["uses"] == [{k: v for k, v in s.items() if k != "ref"}
                            for s in segments if isinstance(s, dict)]


def test_a_formula_and_a_column_used_twice_are_listed_once():
    dup = _node(formula_tree(EDGES), "Dup")
    assert dup["uses"] == [{"formula": "net_sales_f"}, {"column": "ORDERS::X"}]
    assert _node(formula_tree(EDGES), "net_sales_f")["used_by"] == 2


def test_a_cycle_is_rooted_where_nothing_outside_it_uses_it():
    # C is used only by B, inside the A <-> B cycle: rooting C first would leave the
    # cycle hanging under it, so the root is A, the first formula no outsider uses
    model = {"formulas": [_f("formula_C", "C", "[ORDERS::X]"),
                          _f("formula_A", "A", "[formula_B]"),
                          _f("formula_B", "B", "[formula_A] + [formula_C]")]}
    assert formula_tree(model)["roots"] == ["A"]


def test_a_cycle_beneath_another_cycle_is_not_a_root():
    # C <-> D is used by A, inside the A <-> B cycle: one root, A
    model = {"formulas": [_f("formula_C", "C", "[formula_D]"),
                          _f("formula_D", "D", "[formula_C]"),
                          _f("formula_A", "A", "[formula_B] + [formula_C]"),
                          _f("formula_B", "B", "[formula_A]")]}
    assert formula_tree(model)["roots"] == ["A"]


def test_the_report_compacts_labels_names_and_use_kinds():
    data = run_audit(None, ["m-2"], ctx=make_context(
        models=[{"guid": "m-2", "model": EDGES}], model_guids=["m-2"]))
    from ts_cli.audit.report import compact_payload
    ft = compact_payload(data)["C"]["m"][0]["ft"]
    names = [n["f"] for n in ft["n"]]
    margin = ft["n"][names.index("margin_f")]
    assert (margin["n"], margin["f"]) == ("Margin", "margin_f")
    assert margin["u"] == [[0, names.index("net_sales_f")], [2, "Rate"]]
    assert ft["n"][names.index("Dup")]["u"][1] == [1, "ORDERS::X"]


def test_the_report_compacts_each_expression_with_the_use_encoding():
    data = run_audit(None, ["m-2"], ctx=make_context(
        models=[{"guid": "m-2", "model": EDGES}], model_guids=["m-2"]))
    from ts_cli.audit.report import compact_payload
    ft = compact_payload(data)["C"]["m"][0]["ft"]
    names = [n["f"] for n in ft["n"]]
    margin = ft["n"][names.index("margin_f")]
    assert margin["x"][:3] == [[0, names.index("net_sales_f"), "[Net Sales]"], " * ",
                               [2, "Rate", "[Rate]"]]
    assert ft["n"][names.index("Dup")]["x"][-1] == [1, "ORDERS::X", "[ORDERS::X]"]


def test_a_tree_written_before_expressions_compacts_without_them():
    from ts_cli.audit.report import _compact_tree
    old = {"nodes": [{"name": "A", "label": "A", "kind": None, "hidden": True,
                      "uses": [], "used_by": 0}], "roots": ["A"]}
    assert "x" not in _compact_tree(old)["n"][0]


def _report(tmp_path, *models, strip_trees=False):
    models = models or (("m-1", MODEL),)
    ctx = make_context(models=[{"guid": g, "model": m} for g, m in models],
                       model_guids=[g for g, _ in models])
    data = run_audit(None, [g for g, _ in models], ctx=ctx)
    if strip_trees:  # a report built before the Formulas view existed
        for m in data["corpus"]["models"]:
            m.pop("formula_tree", None)
    return render_report(data)


_EXPAND = 'document.querySelector(".ftree-expand").click();'
_COLLAPSE = 'document.querySelector(".ftree-collapse").click();'


@needs_chrome
def test_the_tree_opens_roots_one_level_and_expands_on_demand(tmp_path):
    page = _report(tmp_path)
    shown = report_browser.render(page, tmp_path, "formulas/m-1")
    assert shown["errors"] == []
    assert shown["active"] == "v-formulas"
    seen = shown["visible"]
    # roots, and the formulas each root directly uses
    for name in ("Gross Margin %", "Order Count", "Gross Margin", "Revenue"):
        assert name in seen
    assert "hidden helper" in seen and "used by 2 formulas" in seen
    assert re.search(r"used by 1 formula(?!s)", seen)
    # Gross Margin is built but collapsed: Cost, beneath it, is not shown
    assert "Cost" not in seen
    # deeper levels are not built until opened
    assert "ORDERS::AMOUNT" not in shown["active_text"]
    opened = report_browser.render(page, tmp_path, "formulas/m-1", actions=_EXPAND)
    assert opened["errors"] == []
    for text in ("ORDERS::AMOUNT", "ORDERS::COST", "Cost", "circular reference to Loop A"):
        assert text in opened["visible"]
    assert "Stopped after" not in opened["visible"]
    closed = report_browser.render(page, tmp_path, "formulas/m-1", actions=_EXPAND + _COLLAPSE + (
        'window.__extra = document.querySelectorAll('
        '"#v-formulas [aria-expanded=true]").length;'))
    assert closed["errors"] == [] and closed["extra"] == 0
    assert "Gross Margin %" in closed["visible"]
    assert "Revenue" not in closed["visible"] and "ORDERS::AMOUNT" not in closed["visible"]


@needs_chrome
def test_parameters_labels_and_hidden_unused_formulas_are_shown(tmp_path):
    page = _report(tmp_path, ("m-2", EDGES))
    shown = report_browser.render(page, tmp_path, "formulas/m-2", actions=_EXPAND + (
        'window.__extra = {titles: Array.prototype.map.call(document.querySelectorAll('
        '"#v-formulas .ftree-name[title]"), function(e){ return [e.textContent, e.title]; }),'
        ' cols: Array.prototype.map.call(document.querySelectorAll('
        '"#v-formulas .ftree-col"), function(e){ return e.textContent; })};'))
    assert shown["errors"] == []
    seen = shown["visible"]
    assert "parameter" in seen and "Rate" in seen
    # bracket text inside a quoted literal is no column: it shows only in the definition
    assert not any("FAKE" in c for c in shown["extra"]["cols"])
    assert "'x[ORDERS::FAKE]'" in seen
    assert "hidden, unused" in seen and "hidden helper" not in seen
    assert ["Margin", "Formula: margin_f"] in shown["extra"]["titles"]
    assert ["Net Sales", "Formula: net_sales_f"] in shown["extra"]["titles"]


@needs_chrome
def test_expand_all_stops_at_the_cap_and_continues_when_pressed_again(tmp_path):
    # each formula uses the two before it: the tree's paths grow like Fibonacci
    formulas = [_f("formula_F0", "F0", "[T::A]"), _f("formula_F1", "F1", "[T::B]")]
    formulas += [_f(f"formula_F{i}", f"F{i}", f"[formula_F{i-1}] + [formula_F{i-2}]")
                 for i in range(2, 24)]
    big = {"name": "Big", "formulas": formulas,
           "columns": [_col(f["name"], f["id"]) for f in formulas]}
    count = ('document.querySelectorAll("#v-formulas .ftree-row").length')
    page = _report(tmp_path, ("m-3", big))
    shown = report_browser.render(page, tmp_path, "formulas/m-3", actions=(
        'var b=document.querySelector(".ftree-expand"); var r0=' + count + ';'
        'b.click(); var r1=' + count + '; var n1=document.querySelector(".ftree-note").textContent;'
        'b.click(); var r2=' + count + ';'
        'window.__extra={r0:r0, r1:r1, r2:r2, note:n1};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert 2000 <= x["r1"] - x["r0"] <= 2010
    assert "Stopped after about 2000 more rows: press Expand all again" in x["note"]
    assert 2000 <= x["r2"] - x["r1"] <= 2010
    # column leaves count toward the cap too: 400 formulas of 10 columns each under one root
    leaves = [_f(f"formula_L{i}", f"L{i}", " + ".join(f"[T::C{i}_{j}]" for j in range(10)))
              for i in range(400)]
    top = _f("formula_Top", "Top", " + ".join(f"[formula_L{i}]" for i in range(400)))
    wide = {"name": "Wide", "formulas": [top] + leaves}
    page = _report(tmp_path, ("m-5", wide))
    shown = report_browser.render(page, tmp_path, "formulas/m-5", actions=(
        'var r0=' + count + '; document.querySelector(".ftree-expand").click();'
        'window.__extra=' + count + ' - r0;'))
    assert shown["errors"] == [] and 2000 <= shown["extra"] <= 2010


@needs_chrome
@pytest.mark.parametrize("key", ["Enter", " "])
def test_a_formula_opens_from_the_keyboard(tmp_path, key):
    page = _report(tmp_path)
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=(
        'var row = Array.prototype.find.call(document.querySelectorAll("#v-formulas .ftree-row"),'
        ' function(r){ return r.querySelector(".ftree-name") && '
        'r.querySelector(".ftree-name").textContent === "Gross Margin"; });'
        'row.dispatchEvent(new KeyboardEvent("keydown", {key: "' + key + '", bubbles: true}));'
        'window.__extra = row.getAttribute("aria-expanded");'))
    assert shown["errors"] == [] and shown["extra"] == "true"
    assert "Cost" in shown["visible"]


@needs_chrome
def test_names_are_escaped(tmp_path):
    evil = {"name": "Evil <i>m</i>", "formulas": [
        _f("formula_X", "x\" data-pwned=\"1", "[formula_Y]"), _f("formula_Y", "y", "[T::<b>c</b>]")],
        "columns": [_col('<b>bold</b> "q" \'s\'', "formula_X"),
                    _col("<b>y</b>", "formula_Y", kind='measure" data-pwned="1')]}
    page = _report(tmp_path, ("m-4", evil))
    shown = report_browser.render(page, tmp_path, "formulas/m-4", actions=_EXPAND + (
        'window.__extra = document.querySelectorAll('
        '"#v-formulas b, #v-formulas i, #v-formulas [data-pwned]").length;'))
    assert shown["errors"] == [] and shown["extra"] == 0
    assert '<b>bold</b> "q" \'s\'' in shown["visible"]
    assert "T::<b>c</b>" in shown["visible"]


@needs_chrome
def test_the_picker_the_sidebar_and_the_scorecard_link_reach_the_tree(tmp_path):
    plain = {"name": "Plain", "columns": [{"name": "A", "column_id": "T::A"}]}
    page = _report(tmp_path, ("m-1", MODEL), ("m-9", plain))
    picker = report_browser.render(page, tmp_path, "formulas", actions=(
        'window.__extra = Array.prototype.map.call(document.querySelectorAll('
        '"#v-formulas .ftree-models a"), function(a){ return a.getAttribute("href"); });'))
    assert picker["errors"] == [] and "Sales" in picker["visible"]
    assert picker["extra"] == ["#formulas/m-1"]
    head = report_browser.render(page, tmp_path, "formulas/m-1", actions=(
        'window.__extra = document.querySelector("#v-formulas .ftree-header a").getAttribute("href");'))
    assert head["errors"] == [] and head["extra"] == "#model/m-1"
    assert "7 formulas" in picker["visible"] and "Plain" not in picker["visible"]
    nav = ('var nav = document.querySelector(\'#sidebar-nav a[href="#formulas"]\');'
           'var link = document.querySelector(\'#v-scorecard a[href^="#formulas/"]\');'
           'window.__extra = {nav: nav && nav.textContent, link: link && link.getAttribute("href")};')
    card = report_browser.render(page, tmp_path, "model/m-1", actions=nav)
    assert card["errors"] == [] and "Formula tree" in card["visible"]
    assert card["extra"]["link"] == "#formulas/m-1"
    assert "Formulas" in card["extra"]["nav"]
    other = report_browser.render(page, tmp_path, "model/m-9", actions=nav)
    assert other["errors"] == [] and other["extra"]["link"] is None


@needs_chrome
def test_a_report_without_trees_and_an_unknown_model_say_why(tmp_path):
    page = _report(tmp_path, strip_trees=True)
    picker = report_browser.render(page, tmp_path, "formulas")
    assert picker["errors"] == [] and "predates the Formulas view" in picker["visible"]
    tree = report_browser.render(page, tmp_path, "formulas/m-1")
    assert tree["errors"] == [] and "predates the Formulas view" in tree["visible"]
    # a fresh report whose only formulas are unnamed has formula counts but no tree
    # nodes: that is "no formulas", not an old report
    unnamed = {"name": "Unnamed", "formulas": [{"id": "formula_X", "expr": "[T::X]"}]}
    page2 = _report(tmp_path, ("m-6", unnamed))
    empty = report_browser.render(page2, tmp_path, "formulas/m-6")
    assert empty["errors"] == [] and "This Model has no formulas." in empty["visible"]
    picker2 = report_browser.render(page2, tmp_path, "formulas")
    assert picker2["errors"] == [] and "predates" not in picker2["visible"]
    fresh = _report(tmp_path)
    missing = report_browser.render(fresh, tmp_path, "formulas/nope")
    assert missing["errors"] == [] and "This report has no such Model." in missing["visible"]


@needs_chrome
def test_links_carry_an_awkward_guid_verbatim(tmp_path):
    # the router reads the guid raw, as the sidebar writes it: escaped (an unescaped
    # "&amp;" would read back as "&"), never URL-encoded ("%" would become "%25")
    guid = "m%1&amp;2"
    page = _report(tmp_path, (guid, MODEL))
    links = ('window.__extra = Array.prototype.map.call(document.querySelectorAll('
             '\'a[href^="#formulas/"], a[href^="#model/"]\'), function(a){ return a.getAttribute("href"); });')
    picker = report_browser.render(page, tmp_path, "formulas", actions=links)
    assert picker["errors"] == [] and "#formulas/" + guid in picker["extra"]
    card = report_browser.render(page, tmp_path, "model/" + guid, actions=links)
    assert card["errors"] == [] and "#formulas/" + guid in card["extra"]
    tree = report_browser.render(page, tmp_path, "formulas/" + guid, actions=links)
    assert tree["errors"] == [] and "#model/" + guid in tree["extra"]


# ── The definition panel, links, search (the Formulas view, detail panel) ──
_ROW = ('function row(name){ return Array.prototype.find.call('
        'document.querySelectorAll("#v-formulas .ftree-row"), function(r){'
        ' var n = r.querySelector(".ftree-name, .ftree-col");'
        ' return n && n.textContent === name; }); }'
        'function panel(){ return document.querySelector("#v-formulas .fdetail"); }'
        'function link(scope, text){ return Array.prototype.find.call('
        'scope.querySelectorAll("a.fref"), function(a){ return a.textContent === text; }); }')


@needs_chrome
def test_clicking_a_formula_shows_its_definition_uses_and_used_by(tmp_path):
    page = _report(tmp_path)
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=_ROW + (
        'row("Revenue").click();'
        'var p = panel();'
        'window.__extra = {expr: p.querySelector(".fdetail-expr").textContent,'
        ' uses: Array.prototype.map.call(p.querySelectorAll(".fdetail-uses a.fref"), function(a){ return a.textContent; }),'
        ' usedBy: Array.prototype.map.call(p.querySelectorAll(".fdetail-usedby a.fref"), function(a){ return a.textContent; }),'
        ' selected: document.querySelectorAll("#v-formulas .ftree-selected").length};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["expr"] == "sum ( [ORDERS::AMOUNT] )"   # as written: it can be copied back
    assert x["uses"] == ["ORDERS::AMOUNT"]
    assert x["usedBy"] == ["Gross Margin %", "Gross Margin"]
    assert x["selected"] >= 1


@needs_chrome
def test_a_reference_link_opens_that_formula_and_reveals_it_in_the_tree(tmp_path):
    page = _report(tmp_path)
    # Cost sits under Gross Margin, collapsed: following the link must open the path to it
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=_ROW + (
        'row("Gross Margin %").click();'
        'var gm = link(panel().querySelector(".fdetail-expr"), "[formula_GM]"); var tip = gm.title; gm.click();'
        'var title1 = panel().querySelector(".fdetail-title").textContent;'
        'link(panel().querySelector(".fdetail-expr"), "[Cost]").click();'
        'var r = row("Cost");'
        'window.__extra = {tip: tip, title1: title1, title2: panel().querySelector(".fdetail-title").textContent,'
        ' shown: !!r && r.offsetParent !== null, selected: !!r && r.classList.contains("ftree-selected")};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["tip"] == "Formula: Gross Margin"
    assert x["title1"] == "Gross Margin" and x["title2"] == "Cost"
    assert x["shown"] and x["selected"]


@needs_chrome
def test_everything_that_depends_on_a_formula_is_listed(tmp_path):
    page = _report(tmp_path)
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=_ROW + (
        'row("Order Count").click();'   # a root: nothing uses it
        'var top = panel().querySelector(".fdetail-usedby").textContent;'
        'row("Gross Margin %").click(); link(panel(), "Gross Margin").click();'
        'link(panel().querySelector(".fdetail-expr"), "[Cost]").click();'
        'window.__extra = {top: top,'
        ' all: Array.prototype.map.call(panel().querySelectorAll(".fdetail-dependents a.fref"), function(a){ return a.textContent; })};'))
    assert shown["errors"] == []
    assert "Nothing uses it" in shown["extra"]["top"]
    # Cost is used by Gross Margin, which Gross Margin % uses
    assert shown["extra"]["all"] == ["Gross Margin", "Gross Margin %"]


@needs_chrome
def test_a_column_shows_the_formulas_that_use_it(tmp_path):
    page = _report(tmp_path)
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=_EXPAND + _ROW + (
        'row("ORDERS::AMOUNT").click();'
        'window.__extra = {title: panel().querySelector(".fdetail-title").textContent,'
        ' usedBy: Array.prototype.map.call(panel().querySelectorAll(".fdetail-usedby a.fref"), function(a){ return a.textContent; })};'))
    assert shown["errors"] == []
    assert shown["extra"]["title"] == "ORDERS::AMOUNT"
    assert shown["extra"]["usedBy"] == ["Revenue"]


@needs_chrome
def test_search_finds_formulas_by_name_and_definition_and_columns(tmp_path):
    page = _report(tmp_path)
    search = ('var s = document.querySelector("#v-formulas .ftree-search");'
              'function find(q){ s.value = q; s.dispatchEvent(new Event("input"));'
              ' return Array.prototype.map.call(document.querySelectorAll("#v-formulas .ftree-results a.fref"),'
              ' function(a){ return a.textContent; }); }')
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=search + _ROW + (
        'var byName = find("margin"); var byExpr = find("orders::cost"); var none = find("zzz");'
        'find("loop b"); document.querySelector("#v-formulas .ftree-results a.fref").click();'
        'var title = panel().querySelector(".fdetail-title").textContent;'
        'var cleared = find("");'
        'window.__extra = {byName: byName, byExpr: byExpr, none: none, title: title, cleared: cleared,'
        ' empty: document.querySelector("#v-formulas .ftree-results").textContent};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["byName"] == ["Gross Margin %", "Gross Margin"]
    assert "Cost" in x["byExpr"] and "ORDERS::COST" in x["byExpr"]
    assert x["none"] == [] and x["title"] == "Loop B" and x["cleared"] == [] and x["empty"] == ""


@needs_chrome
def test_an_open_formula_shows_its_expression_inline_without_counting_as_a_row(tmp_path):
    page = _report(tmp_path)
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=(
        'window.__extra = Array.prototype.map.call(document.querySelectorAll('
        '"#v-formulas .ftree > li > .ftree-children > .ftree-exprline"), function(e){ return e.textContent; });'))
    assert shown["errors"] == []
    assert "= Gross Margin / Revenue" in shown["extra"]
    assert "= count ( ORDERS::ORDER_ID ) + Order Count" in shown["extra"]


@needs_chrome
def test_definitions_and_search_results_are_escaped(tmp_path):
    evil = {"name": "Evil", "formulas": [
        _f("formula_X", "x", "[formula_Y] + '<i>lit</i>'"), _f("formula_Y", "y", "[T::<b>c</b>]")],
        "columns": [_col('<b>bold</b>', "formula_X"), _col("<b>y</b>", "formula_Y")]}
    page = _report(tmp_path, ("m-4", evil))
    shown = report_browser.render(page, tmp_path, "formulas/m-4", actions=_EXPAND + _ROW + (
        'row("<b>bold</b>").click();'
        'var s = document.querySelector("#v-formulas .ftree-search"); s.value = "<"; s.dispatchEvent(new Event("input"));'
        'window.__extra = {tags: document.querySelectorAll("#v-formulas b, #v-formulas i").length,'
        ' expr: panel().querySelector(".fdetail-expr").textContent};'))
    assert shown["errors"] == []
    assert shown["extra"]["tags"] == 0
    assert shown["extra"]["expr"] == "[formula_Y] + '<i>lit</i>'"


@needs_chrome
def test_a_report_written_before_definitions_says_to_rerun(tmp_path):
    ctx = make_context(models=[{"guid": "m-1", "model": MODEL}], model_guids=["m-1"])
    data = run_audit(None, ["m-1"], ctx=ctx)
    for m in data["corpus"]["models"]:
        for node in m["formula_tree"]["nodes"]:
            node.pop("expr")
    page = render_report(data)
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=_ROW + (
        'row("Revenue").click();'
        'window.__extra = {inline: document.querySelectorAll("#v-formulas .ftree-exprline").length,'
        ' uses: panel().querySelectorAll(".fdetail-uses a.fref").length};'))
    assert shown["errors"] == []
    assert "predates formula definitions" in shown["visible"]
    assert shown["extra"] == {"inline": 0, "uses": 1}


@needs_chrome
def test_search_says_when_it_stops_and_ranks_columns_above_definitions(tmp_path):
    # 55 formulas all use one column: the column must not be lost behind them
    many = {"name": "Many", "formulas": [_f(f"formula_F{i}", f"F{i}", f"sum ( [ORDERS::AMOUNT] ) * {i}")
                                         for i in range(55)]}
    page = _report(tmp_path, ("m-7", many), ("m-1", MODEL))
    find = ('var s = document.querySelector("#v-formulas .ftree-search");'
            's.value = Q; s.dispatchEvent(new Event("input"));'
            'var r = document.querySelector("#v-formulas .ftree-results");'
            'window.__extra = {hits: Array.prototype.map.call(r.querySelectorAll("a.fref"), function(a){ return a.textContent; }),'
            ' more: (r.querySelector(".ftree-more") || {}).textContent || ""};')
    shown = report_browser.render(page, tmp_path, "formulas/m-7", actions='var Q = "orders::amount";' + find)
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["hits"][0] == "ORDERS::AMOUNT" and len(x["hits"]) == 50
    assert x["more"] == "and 6 more: type more to narrow the list"
    # the definition is searched as written too
    written = report_browser.render(page, tmp_path, "formulas/m-1", actions='var Q = "[formula_gm]";' + find)
    assert written["errors"] == [] and written["extra"]["hits"] == ["Gross Margin %"]
    assert written["extra"]["more"] == ""


@needs_chrome
def test_a_formula_in_a_cycle_never_depends_on_itself(tmp_path):
    ring = {"name": "Ring", "formulas": [_f("formula_A", "A", "[formula_B]"),
                                         _f("formula_B", "B", "[formula_C]"),
                                         _f("formula_C", "C", "[formula_A] + [T::X]")]}
    page = _report(tmp_path, ("m-8", ring))
    shown = report_browser.render(page, tmp_path, "formulas/m-8", actions=_ROW + (
        'row("A").click();'
        'window.__extra = Array.prototype.map.call(panel().querySelectorAll(".fdetail-dependents a.fref"),'
        ' function(a){ return a.textContent; });'))
    assert shown["errors"] == []
    assert shown["extra"] == ["C", "B"]


@needs_chrome
def test_the_tree_is_one_tab_stop_moved_with_the_arrow_keys(tmp_path):
    page = _report(tmp_path)
    key = ('function key(t, k){ t.dispatchEvent(new KeyboardEvent("keydown", {key: k, bubbles: true})); }'
           'function stops(){ return Array.prototype.map.call(document.querySelectorAll('
           '\'#v-formulas .ftree [tabindex="0"]\'), function(e){ return e.textContent; }); }')
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=_ROW + key + (
        'var first = stops(); document.querySelector(".ftree-expand").click(); var expanded = stops();'
        'var r = row("Gross Margin %"); r.focus(); key(r, "ArrowDown");'
        'var next = document.activeElement.querySelector(".ftree-name").textContent;'
        'key(document.activeElement, "Enter");'
        'link(panel().querySelector(".fdetail-expr"), "[Cost]").focus();'
        'key(document.activeElement, "Enter");'
        'var inPanel = !!document.activeElement.closest(".fdetail");'
        'var title = panel().querySelector(".fdetail-title").textContent;'
        'document.querySelector(".ftree-collapse").click();'
        'var after = stops(); var visible = document.querySelector(\'#v-formulas .ftree [tabindex="0"]\').offsetParent !== null;'
        'window.__extra = {first: first.length, expanded: expanded.length, next: next, inPanel: inPanel, title: title,'
        ' after: after.length, visible: visible};'))
    assert shown["errors"] == []
    x = shown["extra"]
    assert x["first"] == 1 and x["expanded"] == 1   # rows built on opening are not tab stops
    assert x["next"] == "Gross Margin"
    assert x["inPanel"] and x["title"] == "Cost"
    assert x["after"] == 1 and x["visible"]


@needs_chrome
def test_a_formula_with_no_expression_says_so(tmp_path):
    blank = {"name": "Blank", "formulas": [_f("formula_E", "Empty", ""), _f("formula_T", "Top", "[formula_E]")]}
    page = _report(tmp_path, ("m-9", blank))
    shown = report_browser.render(page, tmp_path, "formulas/m-9", actions=_ROW + 'row("Empty").click();')
    assert shown["errors"] == []
    assert "The TML gives this formula no expression." in shown["visible"]
