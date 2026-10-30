"""The report is assembled from parts: `ts_cli/audit/report/` holds the shell, styles,
`core.js`, one script per view and `boot.js`; `report.REPORT_VIEWS` is the registry
(audit v2 roadmap, principle 3 and PR 3.1).

A fixed audit JSON renders every registered view in headless Chrome with no JS error;
each view file registers exactly the view the registry names; and a new view is a new
file and a registry line, with no edit to the router.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

import report_browser
from ts_cli.audit import report
from ts_cli.audit.report import REPORT_DIR, REPORT_VIEWS, assemble_page, render_report

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "audit"
needs_chrome = pytest.mark.skipif(report_browser.CHROME is None,
                                  reason="headless Chrome not installed")

#: A route each registered view answers.
ROUTES = {
    "dashboard": "dashboard",
    "scorecard": "model/00000000-0000-4000-8000-000000000001",
    "crossmodel": "crossmodel",
    "objectmap": "objectmap/dependencies",
    "cleanup": "cleanup",
}


def _registrations(script: str) -> list:
    return re.findall(r'registerView\(\{id: "([a-z-]+)"', script)


def test_every_registry_entry_is_a_file_that_registers_that_view():
    seen = []
    for view, script in REPORT_VIEWS:
        text = (REPORT_DIR / script).read_text(encoding="utf-8")
        assert _registrations(text) == [view], (script, _registrations(text))
        seen.append(view)
    assert len(seen) == len(set(seen))
    on_disk = {p.relative_to(REPORT_DIR).as_posix() for p in (REPORT_DIR / "views").glob("*.js")}
    assert on_disk == {script for _, script in REPORT_VIEWS}, "a view file the registry omits"
    assert set(ROUTES) == set(seen), "add the new view's route to ROUTES"


def test_the_page_is_one_self_contained_file_with_every_slot_filled():
    page = assemble_page()
    assert re.findall(r"\{\{[A-Z_]+\}\}", page) == ["{{AUDIT_DATA}}"]
    for view, _ in REPORT_VIEWS:
        assert page.count(f'id="v-{view}"') == 1
    assert "<script src=" not in page and '<link rel="stylesheet"' not in page


@needs_chrome
@pytest.mark.parametrize("view", list(ROUTES))
def test_every_registered_view_renders_from_a_fixed_audit_json(view, tmp_path):
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    shown = report_browser.render(render_report(data), tmp_path, ROUTES[view])
    assert shown["errors"] == [], shown["errors"]
    assert shown["active"] == f"v-{view}", "the route shows its own view"
    assert len(shown["active_text"].strip()) > 50, "the view rendered content"


@needs_chrome
def test_a_new_view_is_a_new_file_and_a_registry_line(tmp_path, monkeypatch):
    parts = tmp_path / "report"
    shutil.copytree(REPORT_DIR, parts)
    (parts / "views" / "probe.js").write_text(
        'function buildProbe(){ document.getElementById("v-probe").textContent = '
        '"Probe view rendered"; }\n'
        'registerView({id: "probe", routes: ["probe"], show: function(route){\n'
        '  buildProbe();\n  return {crumbs: ["Probe"], links: []};\n}});\n', encoding="utf-8")
    monkeypatch.setattr(report, "REPORT_DIR", parts)
    monkeypatch.setattr(report, "REPORT_VIEWS", REPORT_VIEWS + [("probe", "views/probe.js")])
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    shown = report_browser.render(render_report(data), tmp_path, "probe")
    assert shown["errors"] == []
    assert shown["active"] == "v-probe"
    assert shown["active_text"] == "Probe view rendered"
