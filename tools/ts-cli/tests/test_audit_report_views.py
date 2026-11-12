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
    "formulas": ("formulas", "No formulas in the audited Models"),  # JSON from before 3.2
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


#: Browser and language globals the report scripts may call without defining.
_JS_GLOBALS = {
    "Array", "Boolean", "Date", "Error", "Event", "JSON", "KeyboardEvent", "Math", "Number",
    "Object", "RegExp", "Set", "Map", "CustomEvent", "String", "Promise", "Blob", "URL", "isNaN", "isFinite",
    "parseInt", "parseFloat", "encodeURIComponent", "decodeURIComponent", "setTimeout",
    "clearTimeout", "setInterval", "clearInterval", "requestAnimationFrame", "alert",
    "confirm", "getComputedStyle", "matchMedia", "fetch", "atob", "btoa", "escape",
}
_JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof",
                "new", "in", "of", "do", "else", "with", "void", "delete", "throw"}


def _strip_js_strings_and_comments(src: str) -> str:
    """Blank out comments, string literals and regex literals (a `/` after an operator,
    an opening bracket or a keyword starts one), so only code is left to read."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("/*", i):
            j = src.find("*/", i + 2); i = n if j < 0 else j + 2; out.append(" "); continue
        if src.startswith("//", i):
            j = src.find("\n", i); i = n if j < 0 else j; continue
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append('""'); i = j + 1; continue
        if c == "/":
            prev = "".join(out).rstrip()
            if not prev or prev[-1] in "(,=:[!&|?{};+-*%<>~^" or re.search(r"\b(return|typeof|in|of)$", prev):
                j, in_class = i + 1, False
                while j < n and (in_class or src[j] != "/"):
                    if src[j] == "\\":
                        j += 1
                    elif src[j] == "[":
                        in_class = True
                    elif src[j] == "]":
                        in_class = False
                    j += 1
                j += 1
                while j < n and src[j].isalpha():
                    j += 1
                out.append('""'); i = j; continue
        out.append(c); i += 1
    return "".join(out)


def test_every_function_a_report_script_calls_is_defined_somewhere():
    """A helper deleted while a caller remains is a ReferenceError only when that path
    runs (a column link in the Formulas view's panel, e031fba6's review): no linter reads
    these scripts, so check the whole page's calls against its definitions."""
    srcs = {p.relative_to(REPORT_DIR).as_posix(): _strip_js_strings_and_comments(p.read_text(encoding="utf-8"))
            for p in sorted(REPORT_DIR.rglob("*.js"))}
    every = "\n".join(srcs.values())
    functions = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", every))

    def local(src):  # vars and parameters: callable only in the script declaring them
        names = set(re.findall(r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)", src))
        for params in re.findall(r"\bfunction\s*[\w$]*\s*\(([^)]*)\)", src):
            names |= {p.strip() for p in params.split(",") if p.strip()}
        names |= set(re.findall(r"\b(?:var|let|const)\s+[\w$]+\s*=\s*[^;]*?,\s*([A-Za-z_$][\w$]*)\s*=", src))
        return names
    missing = {}
    for name, src in srcs.items():
        defined = functions | local(src)
        for m in re.finditer(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", src):
            fn = m.group(1)
            if fn not in defined and fn not in _JS_GLOBALS and fn not in _JS_KEYWORDS:
                missing.setdefault(fn, name)
    assert missing == {}, f"called but defined nowhere in the report: {missing}"
