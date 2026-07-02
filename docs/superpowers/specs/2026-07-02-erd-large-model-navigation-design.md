# ERD large-model navigation — design

**Date:** 2026-07-02
**Branch:** `feat/erd-large-model-nav` (based on `fix/erd-table-aliases`)
**Skill:** `ts-object-model-erd` (shared library `agents/shared/erd/`)
**Status:** Design approved in chat; revised per Fable spec-review (2026-07-02) —
see review-correction notes inline. Ready for implementation by Sonnet.

> **Review corrections applied (Fable, HEAD e69ae5d):** minimap moved to
> bottom-**right** (`.ctrls` is top-right, `.hint` is bottom-left — bottom-right
> is the free corner); a shared `MIN_K` constant replaces the hardcoded 0.25
> zoom-out floor so the readable fit floor doesn't cause a zoom snap; minimap
> rects reuse the existing node fill mapping (no invented "bridge" color);
> minimap must be Share-HTML-safe (clear before draw, sync collapsed state from
> localStorage at init); and the §7 probes note the module-scoped `focusSet` and
> the `ctrlKey` WheelEvent dispatch. `svg{cursor:grab}` (A2) already exists —
> verify only.

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
  existing cursor-anchored zoom math (zoom toward the pointer) and clamp to
  `[MIN_K, 2.4]` — see C1 for `MIN_K` (a shared constant that replaces today's
  hardcoded `0.25` floor here **and** in `#zoom-out`, so a fresh fit doesn't
  snap-zoom on the first wheel/button press).
- **Pan** otherwise — `view.x -= e.deltaX; view.y -= e.deltaY; applyView();`.
  Respect `deltaMode` loosely: treat line-mode (`deltaMode === 1`) by
  multiplying deltas by ~16 so a mouse-wheel notch pans a sensible distance.
- Keep `e.preventDefault()` and `{passive:false}` so the page never scrolls.

### A2. Discoverable drag cursor

**Already implemented** — `#svg { cursor: grab }` and `#svg.panning { cursor:
grabbing }` exist at renderer.css 69–70, and the `.panning` class is toggled on
`#svg` (renderer.js 358/360). **Verify only; do not add duplicate rules.**

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

A small always-on map, **bottom-right** of the canvas, showing the whole model
with a viewport rectangle. (Corner audit: `.ctrls` is top-right, `.hint` is
bottom-left — bottom-right is the free corner. Do **not** use bottom-left; it
would sit on the hint bar.)

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

- **Node rects** (`renderMinimap`): **clear `#minimap-nodes` (`innerHTML=""`)
  first** (same pattern as `renderNodes`; keeps Share-HTML copies from
  double-rendering — see B4), compute the world bounding box over all `nodes`
  (reuse the same min/max sweep as `fit()`), derive a single
  `scale = min(mmW/worldW, mmH/worldH)` with a few px padding, and draw one tiny
  `<rect>` per node into `#minimap-nodes`. **Color each rect to match the fill
  the main node gets** — reuse the *same* `kind`→fill mapping `renderNodes` uses
  (today that's fact vs. dim, with `is_sql_view` styled distinctly); do **not**
  invent a "bridge" color (`t.kind` in the renderer is effectively fact/dim —
  treat anything non-fact as the dim fill). Rebuild only when the set of nodes or
  their positions change: call from `loadModel`, after a layout change, after
  `fit`, and at the end of a node drag (`enableDrag` pointerup).
- **Viewport rect** (`updateMinimapViewport`): map the current visible
  world-rect (derived from `view` and `svg.getBoundingClientRect()`) through the
  same minimap transform and position `#minimap-view`. Call from `applyView()`
  so it tracks every pan/zoom (cheap — one rect update). **Init-order guard:**
  `applyView()` runs during the initial `loadModel()`→`fit()` *before* the
  minimap transform exists, so `updateMinimapViewport()` must no-op when the
  shared transform is unset.

Store the minimap transform (`scale`, offset, world origin) in a module var so
both functions and the click/drag handler share it (unset until `renderMinimap`
runs — hence the guard above).

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
**Share-HTML safety:** `shareHTML()` (renderer.js ~557) serializes
`document.documentElement.outerHTML`, so a shared copy bakes in whatever
`.collapsed` class is on the DOM at save time. On init, **sync the collapsed
state from `localStorage`** (apply/remove the class) regardless of the baked
class, so shared copies open in the viewer's own preferred state rather than a
stale one.

### B5. CSS (renderer.css)

`.minimap` absolutely positioned **bottom-right**, translucent panel matching
the existing `.ctrls` styling (border, radius, subtle shadow, `background` with
slight transparency). `#minimap-view` a 1.5px accent-colored stroke, no fill (or
faint fill). `.minimap.collapsed svg { display:none }`.

---

## 5. Feature C — Readable fit + focus-aware zoom

### C1. Fit floor

Introduce a single module constant **`MIN_K = 0.12`** and use it as the shared
zoom floor everywhere: in `fit()` clamp `view.k = clamp(fitScale, MIN_K, 1.35)`,
and **replace the hardcoded `0.25` floor** in the `wheel` handler (renderer.js
365) and `#zoom-out` (367) with `MIN_K`. This is the fix for the snap Fable
flagged: without it, a fresh fit at 0.12 jumps to 0.25 on the first
wheel/zoom-out because those paths still clamp at 0.25. Keep centering on the
layout's bounding-box center. Result: "fit" on GTM lands ≈0.12× (legible-ish,
centered) instead of 0.047×, and zooming out from there is smooth; the minimap +
pan cover the overflow. Small models are unaffected (their fit scale is well
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
| `tools/smoke-tests/smoke_ts_object_model_erd.py` | No change expected — it only asserts `col-group` markup exists (verified). Confirm it stays green; extend only if you change that markup. |

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

> **Fixtures.** `view` and `focusSet` are module-scoped — NOT on `window`; read
> state via the DOM, not globals. The GTM export is **not in the repo**; it is a
> local ThoughtSpot export the orchestrator will hand you the path to (a
> `ts tml export --associated` JSON dump). Build with the symlinked CLI
> (`python3 ~/.claude/skills/ts-object-model-erd/build_erd.py <export.json>
> --out gtm.html`), which picks up your edits live. The small-model control
> builds from `agents/cli/ts-object-model-erd/tests/fixtures/mini*.tml`.

Concrete assertions (all must pass):

1. **Renders** — GTM: `#nodes > g.node` count == table count (79), zero
   `pageerror` events (guards against a regression of the alias crash).
2. **Scroll pans** — dispatch `wheel` with `deltaY` and **no** ctrl/meta →
   `#viewport` translate changes, scale unchanged.
3. **Modifier zooms** — `page.mouse.wheel` **cannot** set `ctrlKey`; dispatch
   via `page.evaluate` — `svg.dispatchEvent(new WheelEvent('wheel',{ctrlKey:true,
   deltaY:-120,clientX,clientY,bubbles:true,cancelable:true}))` (or hold
   `keyboard.down('Control')`) → scale changes.
4. **Drag pans without reset** — pointer drag on empty canvas moves the view
   **and** a pre-existing focus survives. `focusSet` isn't readable directly;
   assert via the DOM proxy — non-focused nodes still carry the `.ghost`/`.gone`
   class (renderer.js 279/303), i.e. focus wasn't reset.
5. **Keyboard** — ArrowRight moves translate; `0` fits.
6. **Fit floor** — after `#zoom-fit` on GTM, parsed scale ≥ 0.12 (== `MIN_K`).
7. **Fit-to-focus** — with a table focused (click a node), `#zoom-fit` increases
   scale (zooms into the neighbourhood) and focus is **not** cleared (assert via
   the same `.ghost`/`.gone` DOM proxy as step 4).
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
