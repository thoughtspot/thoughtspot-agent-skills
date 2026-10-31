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
    closed = report_browser.render(page, tmp_path, "formulas/m-1", actions=_EXPAND + _COLLAPSE)
    assert "Gross Margin %" in closed["visible"]
    assert "Revenue" not in closed["visible"] and "ORDERS::AMOUNT" not in closed["visible"]


@needs_chrome
def test_parameters_labels_and_hidden_unused_formulas_are_shown(tmp_path):
    page = _report(tmp_path, ("m-2", EDGES))
    shown = report_browser.render(page, tmp_path, "formulas/m-2", actions=_EXPAND + (
        'window.__extra = Array.prototype.map.call(document.querySelectorAll('
        '"#v-formulas .ftree-name[title]"), function(e){ return [e.textContent, e.title]; });'))
    assert shown["errors"] == []
    seen = shown["visible"]
    assert "parameter" in seen and "Rate" in seen
    assert "FAKE" not in seen
    assert "hidden, unused" in seen and "hidden helper" not in seen
    assert ["Margin", "Formula: margin_f"] in shown["extra"]
    assert ["Net Sales", "Formula: net_sales_f"] in shown["extra"]


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
    assert "Stopped after 2000 more rows" in x["note"]
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
def test_a_formula_opens_from_the_keyboard(tmp_path):
    page = _report(tmp_path)
    shown = report_browser.render(page, tmp_path, "formulas/m-1", actions=(
        'var row = Array.prototype.find.call(document.querySelectorAll("#v-formulas .ftree-row"),'
        ' function(r){ return r.querySelector(".ftree-name") && '
        'r.querySelector(".ftree-name").textContent === "Gross Margin"; });'
        'row.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter", bubbles: true}));'
        'window.__extra = row.getAttribute("aria-expanded");'))
    assert shown["errors"] == [] and shown["extra"] == "true"
    assert "Cost" in shown["visible"]


@needs_chrome
def test_names_are_escaped(tmp_path):
    evil = {"name": "Evil <i>m</i>", "formulas": [
        _f("formula_X", "x\" data-pwned=\"1", "[formula_Y]"), _f("formula_Y", "y", "[T::<b>c</b>]")],
        "columns": [_col('<b>bold</b> "q" \'s\'', "formula_X"), _col("<b>y</b>", "formula_Y")]}
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
    picker = report_browser.render(page, tmp_path, "formulas")
    assert picker["errors"] == [] and "Sales" in picker["visible"]
    assert "7 formulas" in picker["visible"] and "Plain" not in picker["visible"]
    nav = ('var nav = document.querySelector(\'#sidebar-nav a[href="#formulas"]\');'
           'var link = document.querySelector(\'#v-scorecard a[href^="#formulas/"]\');'
           'window.__extra = {nav: nav && nav.textContent, link: link && link.getAttribute("href")};')
    card = report_browser.render(page, tmp_path, "model/m-1", actions=nav)
    assert "Formula tree" in card["visible"]
    assert card["extra"]["link"] == "#formulas/m-1"
    assert "Formulas" in card["extra"]["nav"]
    other = report_browser.render(page, tmp_path, "model/m-9", actions=nav)
    assert other["errors"] == [] and other["extra"]["link"] is None


@needs_chrome
def test_a_report_without_trees_and_an_unknown_model_say_why(tmp_path):
    page = _report(tmp_path, strip_trees=True)
    picker = report_browser.render(page, tmp_path, "formulas")
    assert "predates the Formulas view" in picker["visible"]
    tree = report_browser.render(page, tmp_path, "formulas/m-1")
    assert "predates the Formulas view" in tree["visible"]
    fresh = _report(tmp_path)
    missing = report_browser.render(fresh, tmp_path, "formulas/nope")
    assert missing["errors"] == [] and "This report has no such Model." in missing["visible"]
