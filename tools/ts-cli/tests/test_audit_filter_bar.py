"""One filter bar across the report (report/filter_bar.js: the Formulas and Data Cache
views) and the ERD (agents/shared/erd, drawn standalone and in the report's ERD frame).

The ERD runs in its own page, so it cannot call the report's script: the two keep one
spec. Their CSS between the filter-bar markers is byte-identical, and every bar has the
same shape: "Show", an All chip, the toggle chips, the search box, the shown count."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import report_browser
from ts_cli.audit import run_audit
from ts_cli.audit.context import make_context
from ts_cli.audit.report import REPORT_DIR, render_report

needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")
ERD_CSS = Path(__file__).resolve().parents[3] / "agents" / "shared" / "erd" / "renderer.css"


def _block(text):
    m = re.search(r"/\* filter-bar:begin.*?/\* filter-bar:end \*/", text, re.S)
    assert m, "no filter-bar block"
    return m.group(0)


def test_the_filter_bar_css_is_one_spec_in_the_report_and_the_erd():
    report = _block((REPORT_DIR / "styles.css").read_text(encoding="utf-8"))
    erd = _block(ERD_CSS.read_text(encoding="utf-8"))
    assert report == erd, "edit the filter-bar block in both files together"
    for cls in (".fbar{", ".fbar-label{", ".fbar-chip{", ".fbar-count{", ".fbar-search{", ".fbar-total{"):
        assert cls in report


def _f(fid, name, expr):
    return {"id": fid, "name": name, "expr": expr}


SALES = {
    "name": "Sales", "model_tables": [{"name": "ORDERS", "fqn": "t-1"}],
    "formulas": [_f("formula_Rev", "Revenue", "sum ( [ORDERS::AMOUNT] )"),
                 _f("formula_Dbl", "Double Revenue", "[formula_Rev] * 2")],
    "columns": [{"name": "Revenue", "formula_id": "formula_Rev", "properties": {"column_type": "MEASURE"}}],
}

#: Each bar as [its children's class names, with the chips run together, the label text,
#: role, the All chip first, every chip a button with aria-pressed].
_SHAPE = ('function shape(bar){ if(!bar) return null; var kids = Array.prototype.map.call(bar.children,'
          ' function(c){ return c.classList.contains("fbar-chip") && !c.classList.contains("fbar-all") ? "fbar-chip"'
          '  : c.className.split(" ")[0] + (c.classList.contains("fbar-all") ? " fbar-all" : ""); })'
          '  .filter(function(k, i, a){ return k !== "fbar-chip" || a[i - 1] !== "fbar-chip"; });'
          ' var chips = bar.querySelectorAll(".fbar-chip");'
          ' return {kids: kids, label: bar.querySelector(".fbar-label").textContent, role: bar.getAttribute("role"),'
          '  buttons: Array.prototype.every.call(chips, function(b){ return b.tagName === "BUTTON" &&'
          '   b.getAttribute("type") === "button" && b.hasAttribute("aria-pressed") && !!b.querySelector(".fbar-count"); }),'
          '  search: bar.querySelector(".fbar-search").getAttribute("type")}; }')
SHAPE = {"kids": ["fbar-label", "fbar-chip fbar-all", "fbar-chip", "fbar-search", "fbar-total"],
         "label": "Show", "role": "group", "buttons": True, "search": "search"}


@needs_chrome
@pytest.mark.parametrize("route, selector", [
    ("formulas/m-1", "#v-formulas .fbar"),
    ("formulas/m-1/graph", "#v-formulas .fbar"),
    ("datacache", "#v-datacache .fbar"),
])
def test_every_report_bar_has_the_shared_shape(tmp_path, route, selector):
    page = render_report(run_audit(None, ["m-1"], ctx=make_context(
        models=[{"guid": "m-1", "model": SALES}], model_guids=["m-1"])))
    shown = report_browser.render(page, tmp_path, route, actions=_SHAPE + (
        'window.__extra = shape(document.querySelector("' + selector + '"));'))
    assert shown["errors"] == [] and shown["extra"] == SHAPE


@needs_chrome
def test_the_erd_in_the_report_has_the_same_bar(tmp_path):
    page = render_report(run_audit(None, ["m-1"], ctx=make_context(
        models=[{"guid": "m-1", "model": SALES}], model_guids=["m-1"])))
    shown = report_browser.render(page, tmp_path, "model/m-1/erd", actions=_SHAPE + (
        'setTimeout(function(){ var f = document.querySelector("#v-scorecard iframe.erd-frame");'
        ' window.__extra = shape(f.contentDocument.getElementById("filter-chips")); }, 300);'),
        settle_ms=600)
    assert shown["errors"] == [] and shown["extra"] == SHAPE
