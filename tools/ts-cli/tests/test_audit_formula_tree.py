"""The report's formula dependency tree (audit v2 roadmap PR 3.2): the data
(ts_cli/audit/formula_tree.py) and the Formulas view (report/views/formulas.js)."""
from __future__ import annotations

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


def _report(tmp_path):
    ctx = make_context(models=[{"guid": "m-1", "model": MODEL}], model_guids=["m-1"])
    return render_report(run_audit(None, ["m-1"], ctx=ctx))


@needs_chrome
def test_the_tree_opens_roots_one_level_and_expands_on_demand(tmp_path):
    page = _report(tmp_path)
    shown = report_browser.render(page, tmp_path, "formulas/m-1")
    assert shown["errors"] == []
    assert shown["active"] == "v-formulas"
    text = shown["active_text"]
    # roots, and the formulas each root directly uses
    for name in ("Gross Margin %", "Order Count", "Gross Margin", "Revenue"):
        assert name in text
    assert "hidden helper" in text and "used by 2" in text
    # deeper levels are not built until opened
    assert "ORDERS::AMOUNT" not in text and "ORDERS::COST" not in text
    opened = report_browser.render(
        page, tmp_path, "formulas/m-1",
        actions='document.querySelector(".ftree-expand").click();')
    assert opened["errors"] == []
    assert "ORDERS::AMOUNT" in opened["active_text"]
    assert "ORDERS::COST" in opened["active_text"]
    assert "circular reference to Loop A" in opened["active_text"]


@needs_chrome
def test_the_picker_and_the_scorecard_link_reach_the_tree(tmp_path):
    page = _report(tmp_path)
    picker = report_browser.render(page, tmp_path, "formulas")
    assert picker["errors"] == [] and "Sales" in picker["active_text"]
    assert "7 formulas" in picker["active_text"]
    card = report_browser.render(page, tmp_path, "model/m-1")
    assert "Formula tree" in card["active_text"]
    assert "Formulas" in card["text"]  # the sidebar link, from the view's registration
