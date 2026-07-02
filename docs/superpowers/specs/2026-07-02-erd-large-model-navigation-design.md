# ERD large-model navigation — design

**Date:** 2026-07-02
**Branch:** `feat/erd-large-model-nav` (based on `fix/erd-table-aliases`)
**Skill:** `ts-object-model-erd` (shared library `agents/shared/erd/`)
**Status:** Design approved in chat — ready for implementation by Fable.

---

## 1. Context & problem

The ERD renders every table of a ThoughtSpot Model as a draggable node in a
pan/zoom SVG canvas. On a large model — the motivating case is **GTM, 79 tables
/ 98 joins** — the view is hard to navigate. Three concrete problems were
confirmed empirically by driving the generated HTML in headless Chrome:

1. **No scroll/trackpad panning.** `renderer.js` line 363's `wheel` handler
   zooms on *every* wheel event. A trackpad two-finger scroll (the natural pan
   gesture) therefore zooms instead of panning. Click-drag panning *does* work
   (verified: dragging on empty canvas moves `#viewport`'s transform), but it is
   undiscoverable and easy to start on top of a node (drags the node) or a
   control chip (does nothing).

2. **"Fit" is microscopic.** `fit()` (lines 351–353) computed **scale ≈ 0.047×**
   for GTM — the organic force layout spreads 79 nodes across a canvas ~20× the
   viewport, so "fit everything" is unreadable.

3. **No overview / wayfinding.** With everything tiny there is no way to see
   where you are or jump to a region.

The renderer is browser JavaScript in `agents/shared/erd/renderer.js`, wrapped
into a self-contained HTML file by `agents/shared/erd/render.py` (which inlines
`renderer.css` and `renderer.js`, and injects the model as
`window.__ERD_DATA__`). There is **no external network dependency** and there
is **no JS unit-test harness** today — verification is done by driving the
output in headless Chrome (see §7).

Relevant existing code (post `fix/erd-table-aliases`):

| Symbol | Location | Note |
|---|---|---|
| `view = {x,y,k}` | renderer.js ~348 | module-scoped pan/zoom state |
| `applyView()` | ~349 | writes `translate(x,y) scale(k)` to `#viewport` |
| `screenToWorld(cx,cy)` | ~350 | screen→world coords |
| `fit()` | ~351–353 | fits all nodes; clamps k to **max** 1.35, **no floor** |
| `centerOn(n)` | ~354 | centers a node at current `view.k` |
| pan pointer handlers | ~356–361 | click-drag pan on empty canvas |
| empty-canvas `click` reset | ~362 | clears focus/selection on stray click |
| `wheel` handler | ~363–365 | **always zooms** |
| zoom buttons | ~366–368 | `#zoom-in` / `#zoom-out` / `#zoom-fit` |
| `enableDrag(g,n)` | ~370–374 | node drag |
| `focusSet` / `focusMode` | 24–25 | current focus selection |
| `selectTable(id,additive)` | ~378 | single/compare focus |
| finder `change` handler | ~658 | already `selectTable` + `centerOn` — but at current k |
| global `keydown` | ~580–584 | guards INPUT/TEXTAREA/SELECT; handles `?` `/` `Esc` |
| `loadModel(m)` | ~594 | rebuilds all model-derived state; calls layout + `fit()` |
| SVG skeleton, `.ctrls`, `.hint` | render.py ~81–95 | where new DOM/hint text live |

---

## 2. Goals / non-goals

**Goals** (the three approved items):

- **A. Pan gestures + affordance** — make panning work the way hands expect.
- **B. Minimap overview** — always-available wayfinding for large graphs.
- **C. Readable "fit" + focus-aware zoom** — never land microscopic.

**Non-goals** (explicitly cut):

- Subject-area grouping / coloring by domain (needs a grouping heuristic; deferred).
- Re-tuning the force-layout algorithm itself.
- Any change to the parser / data model (that shipped in `fix/erd-table-aliases`).
- A JS unit-test framework (out of scope; verify via headless probes).

**Success criteria:** on the GTM model, a user can (1) two-finger-scroll to pan
and pinch/⌘-scroll to zoom, (2) glance at a minimap and click to jump, (3) hit
"fit" and land on a legible, centered view. All existing behaviors (node drag,
focus/compare, search, findings/RLS overlays, layout switch, localStorage
positions, Share HTML) keep working.

---

## 3. Feature A — Pan gestures + affordance

### A1. Scroll-to-pan, modifier-to-zoom (`wheel` handler rewrite)

Replace the always-zoom `wheel` handler with:

- **Zoom** when `e.ctrlKey || e.metaKey` — a Mac trackpad pinch reports
  `ctrlKey: true`; ⌘+scroll is the explicit keyboard-modified zoom. Keep the
  existing cursor-anchored zoom math (zoom toward the pointer) and the
  `[0.25, 2.4]` clamp.
- **Pan** otherwise — `view.x -= e.deltaX; view.y -= e.deltaY; applyView();`.
  Respect `deltaMode` loosely: treat line-mode (`deltaMode === 1`) by
  multiplying deltas by ~16 so a mouse-wheel notch pans a sensible distance.
- Keep `e.preventDefault()` and `{passive:false}` so the page never scrolls.

### A2. Discoverable drag cursor

Ensure the canvas shows `cursor: grab`, and `grabbing` while panning. The
`.panning` class is already toggled on `#svg` (renderer.js 358/360); add/verify
the CSS in `renderer.css`:

```css
#svg { cursor: grab; }
#svg.panning { cursor: grabbing; }
```

(Node hit-areas keep their own `grab`/`grabbing` from `enableDrag`; unaffected.)

### A3. Drag never triggers the reset-click

Today an empty-canvas `click` (renderer.js 362) clears focus/selection. A
pan-drag ends with a synthetic `click`, which can wipe the user's focus. Add a
movement threshold: in the pan pointer handlers track total movement; if it
exceeds ~4px, set a `suppressNextClick` flag and have the `click` handler
early-return once (then clear the flag). This mirrors the `moved` guard already
used in `enableDrag` (373).

### A4. Keyboard navigation

Extend the existing global `keydown` handler (renderer.js ~580, which already
returns early for INPUT/TEXTAREA/SELECT):

- Arrow keys → pan by a fixed step (~60px, `view.x/ y ±= step; applyView()`).
- `+` / `=` → zoom in; `-` → zoom out (reuse the zoom-button logic / clamp).
- `0` → fit (same as `#zoom-fit`).

Update the help drawer's shortcut list and the `.hint` text (render.py ~95) to
read: `drag or scroll to pan · pinch / ⌘-scroll to zoom · arrows / 0 to move`.

---

## 4. Feature B — Minimap overview

A small always-on map, bottom-left of the canvas (bottom-right is occupied by
`.ctrls`), showing the whole model with a viewport rectangle.

### B1. DOM (render.py)

Add, as a sibling of `.ctrls` inside the canvas wrapper:

```html
<div class="minimap" id="minimap" aria-hidden="true">
  <button class="minimap-toggle" id="minimap-toggle" title="Hide overview">–</button>
  <svg id="minimap-svg"><g id="minimap-nodes"></g><rect id="minimap-view"></rect></svg>
</div>
```

Fixed size ~180×130. `aria-hidden` because it is a redundant navigation aid.

### B2. Rendering (renderer.js, new `renderMinimap()` / `updateMinimapViewport()`)

- **Node rects** (`renderMinimap`): compute the world bounding box over all
  `nodes` (reuse the same min/max sweep as `fit()`), derive a single
  `scale = min(mmW/worldW, mmH/worldH)` with a few px padding, and draw one tiny
  `<rect>` per node into `#minimap-nodes`, colored by `t.kind` (fact / dim /
  bridge / sql_view) reusing existing palette values. Rebuild only when the set
  of nodes or their positions change: call from `loadModel`, after a layout
  change, after `fit`, and at the end of a node drag (`enableDrag` pointerup).
- **Viewport rect** (`updateMinimapViewport`): map the current visible
  world-rect (derived from `view` and `svg.getBoundingClientRect()`) through the
  same minimap transform and position `#minimap-view`. Call from `applyView()`
  so it tracks every pan/zoom (cheap — one rect update).

Store the minimap transform (`scale`, offset, world origin) in a module var so
both functions and the click/drag handler share it.

### B3. Click / drag to navigate

Pointer events on `#minimap-svg`: convert the clicked minimap point back to
world coords, then set `view.x/ y` so that world point is centered in the main
canvas (reuse `centerOn` math with a synthetic node, or inline). Support drag
(pointerdown + move) to scrub. `stopPropagation` so it never reaches the canvas
pan handler.

### B4. Toggle

`#minimap-toggle` collapses the minimap to just the toggle button
(`.minimap.collapsed` CSS). Persist the collapsed state in `localStorage`
(key e.g. `ts-erd-minimap`) so it survives reloads. Default **expanded**.

### B5. CSS (renderer.css)

`.minimap` absolutely positioned bottom-left, translucent panel matching the
existing `.ctrls` styling (border, radius, subtle shadow, `background` with
slight transparency). `#minimap-view` a 1.5px accent-colored stroke, no fill (or
faint fill). `.minimap.collapsed svg { display:none }`.

---

## 5. Feature C — Readable fit + focus-aware zoom

### C1. Fit floor

In `fit()`, after computing the fit scale, clamp with a **floor** as well as the
existing max: `view.k = clamp(fitScale, FIT_FLOOR, 1.35)` with
`FIT_FLOOR = 0.12`. Keep centering on the layout's bounding-box center. Result:
"fit" on GTM lands ≈0.12× (legible-ish, centered) instead of 0.047×; the minimap
+ pan cover the overflow. Small models are unaffected (their fit scale is well
above the floor).

### C2. Fit-to-focus

`#zoom-fit` currently clears focus then fits everything (renderer.js 368).
Change: **if `focusSet` is non-empty, fit to just the focused neighbourhood**
(the same node set `focusGroup()`/`hideOutOfFocus()` uses) instead of clearing
it. Only clear-and-fit-all when nothing is focused. Extract a
`fitNodes(subset)` helper so `fit()` (all) and fit-to-focus share the bounding
-box + clamp logic. The `0` keyboard shortcut follows the same rule.

### C3. Search zooms to a readable level

The finder `change` handler (renderer.js 658) already does
`selectTable(id,false); centerOn(nodeById[id])` — but at whatever `view.k` you
were on (microscopic after a fit). Change it to set a **readable zoom**
(e.g. `view.k = max(view.k, 0.9)`) before `centerOn`, so searching a table
always brings it up legibly. Keep clearing the input after.

---

## 6. Files touched

| File | Change |
|---|---|
| `agents/shared/erd/renderer.js` | A1 wheel rewrite; A3 suppress-click; A4 keyboard; B2–B4 minimap render/viewport/click/toggle; C1 fit floor; C2 `fitNodes` + fit-to-focus; C3 search zoom. Wire minimap into `loadModel` + layout/drag/fit callsites. |
| `agents/shared/erd/renderer.css` | A2 grab cursors; B5 minimap styles. |
| `agents/shared/erd/render.py` | B1 minimap DOM; A4 updated `.hint` text + help-drawer shortcuts. |
| `agents/cli/ts-object-model-erd/SKILL.md` | `## Changelog` entry (MINOR bump at PR time) + note new gestures/minimap in the "ERD features" list in Step 6. |
| `tools/smoke-tests/smoke_ts_object_model_erd.py` | Extend if it asserts on rendered structure (check first; keep green). |

**Module-health note:** keep any new functions under CAP=15 cyclomatic
complexity (the pre-commit gate blocks regressions — this is why `parse_model`
was already refactored in the base branch). Prefer small helpers
(`renderMinimap`, `updateMinimapViewport`, `minimapToWorld`, `fitNodes`) over
growing existing functions.

---

## 7. Verification (no unit harness — drive the real output)

For each change, rebuild an ERD and drive it in headless Chrome via puppeteer
(global install; run with `NODE_PATH=$(npm root -g)`), reading `#viewport`'s
`transform` attribute and DOM state. Use the **GTM export** as the large-model
fixture and the repo's `mini.model.tml` fixture as the small-model control.

Concrete assertions (all must pass):

1. **Renders** — GTM: `#nodes > g.node` count == table count (79), zero
   `pageerror` events (guards against a regression of the alias crash).
2. **Scroll pans** — dispatch `wheel` with `deltaY` and **no** ctrl/meta →
   `#viewport` translate changes, scale unchanged.
3. **Modifier zooms** — dispatch `wheel` with `ctrlKey:true` → scale changes.
4. **Drag pans without reset** — pointer drag on empty canvas moves the view
   **and** a pre-existing `focusSet` survives (no reset-click).
5. **Keyboard** — ArrowRight moves translate; `0` fits.
6. **Fit floor** — after `#zoom-fit` on GTM, parsed scale ≥ 0.12.
7. **Fit-to-focus** — with a table focused, `#zoom-fit` increases scale (zooms
   into the neighbourhood) and does **not** clear `focusSet`.
8. **Search** — set finder value to a table id + dispatch `change` → view
   centers on it and scale ≥ 0.9.
9. **Minimap** — `#minimap-nodes rect` count == table count; `#minimap-view`
   moves after a pan; a click on the minimap recenters the main view; toggle
   hides/shows and the state persists across reload.
10. **Small model unaffected** — mini fixture still fits above the floor and all
    prior interactions work.

Keep the existing test suite green: `python3 -m pytest
agents/cli/ts-object-model-erd/tests/` (24 tests) and the pre-commit validators
(`module health`, `consistency`, `version sync`, etc.).

---

## 8. Rollout

- Work on `feat/erd-large-model-nav`; **no direct push to `main`** — open a PR.
- Bump `ts-object-model-erd` `## Changelog` (MINOR) with the PR, dated PR day.
- `agents/shared/erd/*` changes reach Claude Code immediately via symlink; no
  CoCo stage-sync needed (this skill is CLI-only per runtime-coverage).
- The base branch `fix/erd-table-aliases` should land first (or this PR targets
  it / is rebased onto `main` once the fix merges) — they touch different files
  (`parser.py` vs `renderer.*`) so no conflict is expected.
