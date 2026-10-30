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
| `views/<view>.js` | One per view: dashboard, scorecard, crossmodel, objectmap, cleanup. Each ends with `registerView({id, routes, show, pills, fallback})`, which carries the route handling the router's `switch` used to hold for it |
| `boot.js` | Init, last, so every view has registered before the first route |

`report.REPORT_VIEWS` is the registry: (view id, script) per view, in container order.
`assemble_page` builds the containers from it and concatenates the scripts inside the
one function scope the template had, so the output is still a single self-contained HTML
file. A new view is a new file and a registry line; the router is never edited.

## How "no visible change" was checked

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

## Choices

- **Function scope kept.** The views share helpers and state through one scope; turning
  them into modules would be a rewrite, not a split. Concatenating inside the original
  IIFE keeps every name and its hoisting as it was.
- **The registry is a Python list, the routes are in each view.** The containers are
  built server-side (no DOM change), and each view owns its routes, breadcrumb and
  filter-bar flag, so nothing about a view is spread across files.

## Tests

`tests/test_audit_report_views.py`: every registry entry is a file that registers exactly
that view, and every view file is registered; the page has every slot filled and loads
nothing external; every registered view renders from the fixed fixture with no JS error,
shows its own container, and renders content; and a synthetic view added as one file and
one registry line renders at its route. `tests/report_browser.py` now also reports the
active view.
