# The report assembled from parts (roadmap PR 3.1)

**Status:** built to the roadmap's PR 3.1 row (`2026-10-23-audit-v2-roadmap.md`, wave 3,
principle 3). No visible change.

## What changes

`ts_cli/audit/report_template.html` (2,951 lines: CSS, layout and every view's script in
one file) becomes `ts_cli/audit/report/`:

| Part | Holds |
|---|---|
| `shell.html` | The layout, with four slots: `{{STYLES}}`, `{{VIEW_CONTAINERS}}`, `{{SCRIPT}}`, `{{AUDIT_DATA}}` |
| `styles.css` | Every style, unchanged |
| `core.js` | The data, constants and shared helpers (including the severity pill, the cluster link and the readiness constants, which several views use), the sidebar, the filter pills, the view registry and the router |
| `views/<view>.js` | One per view: dashboard, scorecard, crossmodel, objectmap, cleanup, each holding its own state. Each ends with `registerView({id, routes, show, nav, pills, fallback})`: the route handling the router's `switch` used to hold for it, its breadcrumb, and its sidebar link (`nav`), which `core.js` builds the sidebar from and highlights while the view is shown |
| `boot.js` | Init, last, so every view has registered before the first route |

`report.REPORT_VIEWS` is the registry: (view id, script) per view, in container order.
`assemble_page` builds the containers from it and concatenates the scripts inside the
one function scope the template had, so the output is still a single self-contained HTML
file. A new view is a new file and a registry line; the router is never edited.

## How "no visible change" was checked

0. **What the claim covers.** After the router change the page no longer holds the
   template's lines exactly (the `switch` became `registerView` blocks); it renders and
   behaves the same, which is what was checked.
1. **A pure move first.** The template was sliced by line range into the parts, and the
   assembled page holds exactly the template's lines (a line-multiset comparison: none
   missing, none added).
2. **Rendered, before and after.** The old template and the assembled page were rendered
   in headless Chrome at every route (the dashboard; cross-model unfiltered, by severity
   and by category; every Object Map tab; cleanup; two Models' scorecards and one
   category tab) for three audit JSONs: the committed pre-cut-over fixture, the
   generated test data, and a local run over the 148-Model SE demo sample (not
   committed). Visible text (`innerText`, so a hidden filter bar counts) and JS errors
   were identical on all 42 renders, after the move and again after the router change.
3. **Driven, before and after.** The review's harness drove both pages through every
   control on every route (pills carried across views, back and forward, tabs, sorting,
   the hamburger, ERD documents, copy-selected), comparing the DOM, the visible text, the
   active view, the breadcrumb, the sidebar, listener counts and clipboard writes: 0
   differences, re-run after the sidebar moved into the registry (3,960 steps over five
   audit JSONs).

## Choices

- **Function scope kept.** The views share helpers and state through one scope; turning
  them into modules would be a rewrite, not a split. Concatenating inside the original
  IIFE keeps every name and its hoisting as it was.
- **The registry is a Python list, the routes are in each view.** The containers are
  built server-side (no DOM change), and each view owns its routes, breadcrumb, sidebar
  link, filter-bar flag and state, so nothing about a view is spread across files.
- **One shared scope has a cost.** A part that re-declares another's top-level name (say,
  a helper like `esc`) replaces it everywhere with no error; a test fails on any such
  clash. And exactly one view may be the `fallback`, or an unknown route shows nothing
  (none) or the wrong view (two); a test guards that too.
- **The scripts are not size-gated** (the file-size and module-health gates scan Python
  only): BL-503.

## Tests

`tests/test_audit_report_views.py`: every registry entry is a file that registers exactly
that view, and every view file is registered; the page has every slot filled and loads
nothing external; every registered view renders from the fixed fixture with no JS error,
shows its own container, and renders content; and a synthetic view added as one file and
one registry line renders at its route with its own sidebar link; exactly one view is the
fallback and an unknown route shows it; no part redeclares another's top-level name.
`tests/report_browser.py` now also reports the active view.
