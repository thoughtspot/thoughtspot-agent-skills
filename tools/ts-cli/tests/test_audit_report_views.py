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

#: A route each registered view answers, and text that view renders for it on the fixture.
ROUTES = {
    "dashboard": ("dashboard", "Example Sales"),
    "scorecard": ("model/00000000-0000-4000-8000-000000000001", "Example Sales"),
    "crossmodel": ("crossmodel", "Example Sales"),
    "objectmap": ("objectmap/dependencies", "Example Sales"),
    "cleanup": ("cleanup", "Orphan model with no dependents"),
}
_PARTS = ["core.js"] + [script for _, script in REPORT_VIEWS] + ["boot.js"]


def _registrations(script: str) -> list:
    return re.findall(r"registerView\(\s*\{\s*id\s*:\s*[\"']([^\"']+)[\"']", script)


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
    route, marker = ROUTES[view]
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    shown = report_browser.render(render_report(data), tmp_path, route)
    assert shown["errors"] == [], shown["errors"]
    assert shown["active"] == f"v-{view}", "the route shows its own view"
    assert marker in shown["active_text"], "the view rendered its content"


def test_exactly_one_view_is_the_fallback():
    """The router sends an unknown route to the one `fallback` view; none leaves an
    unknown route (a typo, a stale bookmark) with no view, two make the last one win."""
    flagged = [script for script in _PARTS[1:-1]
               if re.search(r"\bfallback\s*:\s*true", (REPORT_DIR / script).read_text())]
    assert flagged == ["views/dashboard.js"]


def test_no_part_redeclares_another_parts_top_level_name():
    """All parts share one function scope, so a later part declaring a name an earlier
    one declared (a helper such as `esc`) replaces it everywhere, silently."""
    seen: dict = {}
    clashes = []
    for part in _PARTS:
        text = (REPORT_DIR / part).read_text(encoding="utf-8")
        for name in re.findall(r"^(?:function\s+([A-Za-z_$][\w$]*)|var\s+([A-Za-z_$][\w$]*))",
                               text, re.M):
            name = name[0] or name[1]
            if name in seen and seen[name] != part:
                clashes.append((name, seen[name], part))
            seen.setdefault(name, part)
    assert clashes == []


@needs_chrome
def test_an_unknown_route_shows_the_fallback_view(tmp_path):
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    shown = report_browser.render(render_report(data), tmp_path, "no-such-view")
    assert shown["errors"] == []
    assert shown["active"] == "v-dashboard"


@needs_chrome
def test_a_new_view_is_a_new_file_and_a_registry_line(tmp_path, monkeypatch):
    parts = tmp_path / "report"
    shutil.copytree(REPORT_DIR, parts)
    (parts / "views" / "probe.js").write_text(
        'function buildProbe(){ document.getElementById("v-probe").textContent = '
        '"Probe view rendered"; }\n'
        'registerView({id: "probe", routes: ["probe"],\n'
        '  nav: {hash: "#probe", icon: "*", label: "Probe Link"},\n'
        '  show: function(route){\n'
        '  buildProbe();\n  return {crumbs: ["Probe"], links: []};\n}});\n', encoding="utf-8")
    monkeypatch.setattr(report, "REPORT_DIR", parts)
    monkeypatch.setattr(report, "REPORT_VIEWS", REPORT_VIEWS + [("probe", "views/probe.js")])
    data = json.loads((FIXTURES / "pre_cutover_audit.json").read_text())
    shown = report_browser.render(render_report(data), tmp_path, "probe")
    assert shown["errors"] == []
    assert shown["active"] == "v-probe"
    assert shown["active_text"] == "Probe view rendered"
    assert "Probe Link" in shown["text"], "its sidebar link comes from its own registration"
