# ERD overview legibility (semantic zoom) — design

**Date:** 2026-07-02
**Branch:** `feat/erd-overview-legibility` (based on `fix/erd-drop-unresolvable-joins` / #154)
**Skill:** `ts-object-model-erd` (shared library `agents/shared/erd/`)
**Status:** Approach approved in chat (non-scaling strokes + level-of-detail). Ready for implementation by Sonnet after Fable spec review.

---

## 1. Context & problem

On a large model (GTM: 79 tables) the fit view is ~0.12× zoom, and at that scale the diagram is hard to read:

- **Borders vanish.** Node body strokes are `stroke-width` in user units (`sw` = 1.2–2.8, renderer.js:305–308). SVG scales strokes with the viewport transform, so at 0.12× a 1.6px border renders ~0.19px — effectively invisible. Edges (renderer.js:280) have the same problem.
- **Fills don't separate from the ground.** Detailed nodes fill white/pale, with a pale header (`hbg`: fact `#EAF2F8`, dim `#EEF0F3`, renderer.js:312) that is nearly identical to the canvas ground (`--ground:#F6F7F9`). With borders gone and fills near-ground, a zoomed-out box has neither outline nor distinct fill.
- **Detail is wasted.** Column rows and text are unreadable below ~0.4× anyway, but they're still drawn.

Zoomed in, borders are full-size and cards read fine — this is purely an **overview-scale** problem. The fix is *semantic zoom*: the drawing should change with scale, not just shrink.

Key existing code (post #154, on the base branch):

| Symbol | Location | Note |
|---|---|---|
| `view = {x,y,k}`, `applyView()` | ~348–349 | pan/zoom state; `applyView` writes the `#viewport` transform and calls `updateMinimapViewport()` |
| `renderAll()` = `renderEdges()` + `renderNodes()` | 345 | full redraw |
| `renderNodes()` | ~298–340 | per node: computes `stroke`/`sw`/`fill` (state-aware), draws body rect (311), header rect + separator (312–315), title text (317), badges (321–329), column rows (333+), `enableDrag` |
| `renderEdges()` | ~270–285 | edge path with `stroke`/`stroke-width` sw (280) |
| `MIN_K`, `fit()`/`fitNodes()` | ~351–375 | fit lands at `MIN_K = 0.12` on GTM |
| `nodeHeight(t)`, `HEAD_H=30`, `ROW_H=20` | 21,44 | node box height from visible columns |
| wheel/zoom buttons/keyboard | ~360–395 | all zoom paths funnel through `applyView` |

---

## 2. Goals / non-goals

**Goals:**
- **A. Non-scaling strokes** — node borders and edges stay crisp (~their nominal px) at any zoom.
- **B. Level-of-detail (semantic zoom)** — below a zoom threshold, draw each node as a bold, color-by-kind **overview block** (solid saturated fill + crisp border + table name only, no columns); above the threshold, the current detailed card.
- **C. Overview palette** — saturated, contrast-checked fills per kind so 79 tables read as color-coded regions.

**Non-goals:**
- Changing layout, positions, or node bounding boxes (LOD is a *rendering* change within the existing `n.w × n.h` box — keeps fit/minimap/drag/localStorage positions intact).
- Minimap changes (its rects already use a fixed tiny stroke and are fine).
- Any parser / data change.

**Success:** at fit (0.12×) on GTM, every table is a clearly-visible, color-coded block with a crisp outline and visible edges; zooming past the threshold smoothly restores full cards; small models (mini) are unaffected because they fit well above the threshold.

---

## 3. Feature A — non-scaling strokes

Add `vector-effect: non-scaling-stroke` to:
- the node **body** rect (renderer.js:311), and
- the **edge** visible path stroke (renderer.js:280), **and** the transparent
  16px **hit-path** (renderer.js:281). The hit-path gets it too so edges stay
  clickable at overview zoom (at 0.12× a 16-world-unit hit target is ~2px
  without it — barely hittable); this upholds the §B3 interaction-parity claim.

Effect: a 1.6px border / edge stays ~1.6px on screen at 0.12× and at 2.4×. This is the single highest-leverage change and benefits both LOD blocks and detailed cards. Pure attribute addition; no JS logic.

Do **not** add it to the header separator line (:315) or column-internal strokes — those live inside a card that only shows above the LOD threshold, where normal scaling is fine.

**Known limitations (accept; don't report as bugs):**
- **Arrowheads/crow's-feet still shrink.** SVG `marker-end` markers (renderer.js:280) and the drawn crow's-foot/arrow ticks (~:255–257) are *not* affected by `vector-effect`, so at 0.12× the edge lines are crisp but the arrowheads are tiny. Acceptable — LOD is about block/line legibility, and direction is secondary at overview.
- **Focus/secured/RLS borders no longer thicken with zoom-in.** The focus border (`sw=2.8`) currently renders ~6.7px at 2.4×; with non-scaling stroke it stays 2.8px at all zooms. This is a minor, intentional consistency change on the detail side, not a regression.

---

## 4. Feature B — level-of-detail rendering

### B1. Threshold + re-render hook
Add a module constant `LOD_T = 0.5` (tunable). Define `lodActive()` → `view.k < LOD_T`.

`renderNodes()` branches per node on `lodActive()`:
- **LOD block** when `lodActive()` is true.
- **Detailed card** (current code) otherwise.

Re-render only when the threshold is **crossed** (not on every zoom step, and never on pan — `view.k` doesn't change on pan; the per-`pointermove` `lastLod` compare is one boolean and no-ops). In `applyView()`, after writing the transform, compare `lodActive()` to a stored `lastLod`; if it changed, set `lastLod` and call `renderNodes()`. `renderEdges()` doesn't need re-rendering (edges look the same both sides of the threshold; only their stroke crispness matters, handled by A). `renderNodes()` sets `lastLod` itself each time it runs, so the state is always consistent with what's drawn.

**On a large model there IS one legitimate double-render at load, and that's correct:** `loadModel` runs `renderAll()` at the initial `view.k=1` (detail cards, `lastLod=false`), then `fit()` drops k to 0.12, `applyView()` sees the crossing, and re-renders once as LOD blocks. This is unavoidable given the load order and happens exactly once. (Optional optimization — reorder `loadModel`/`tweenTo` to call `fit()` *before* `renderAll()`; `nodesBBox` computes `n.h` itself so fit doesn't need a prior render. Not required.) Small models that fit above `LOD_T` never cross, so they render once. No recursion: `renderNodes` never mutates `view`/calls `applyView`/`fit`, so `applyView`→`renderNodes` is terminal.

Cost: one `renderNodes()` per threshold crossing (rare) — negligible.

### B2. LOD block appearance
**Both branches must still set `n.h = nodeHeight(t)`** (currently at the top of
the per-node loop, ~renderer.js:293) — `renderEdges` (:269), `nodesBBox` (:359),
and the minimap all read `n.h`, so it can't be folded into the detail branch
only. Keep it computed before the LOD/detail fork.

Within the node `<g>` (same `transform`, same `n.w × n.h` box), draw:
- **One body rect** `n.w × n.h`, `rx:10`, **solid saturated kind fill** (see §5), `vector-effect:non-scaling-stroke`, border = the **state-aware `stroke`/`sw`** already computed (so secured=red, in-RLS-path=amber, severity, and focus=thick-blue borders still communicate state at overview). Keep the existing drop-shadow.
- **Title text only** — the table id, in white (or the palette's on-fill text color), centered horizontally, vertically centered in the box, with a **larger font** than the card title so it's legible as you approach the threshold. Truncate with an ellipsis to `n.w` (reuse the existing truncation approach used for the card title if there is one; otherwise clip).
- **No** header rect/separator, badges, or column rows.

Everything else about the node (`class="node"`, ghost/gone focus classes at :303, `enableDrag`, click/dblclick handlers at :341–342) stays identical, so focus/compare/drag/inspector all keep working at overview zoom.

### B3. Interaction parity
Because the `<g>`, classes, transform, and handlers are unchanged, all existing behavior holds at LOD: click-to-focus, shift-click compare, double-click component, drag, minimap, filters (ghosting via `.ghost`/`.gone`), search-centering. Only the *contents* of the `<g>` differ.

---

## 5. Feature C — overview palette

At overview, fill carries the signal, so use saturated fills with white text. The fills **must meet WCAG AA for white text (≥4.5:1)** — the obvious mid-tones fail (white on `#8A93A0` slate ≈ 3.0:1, on `#0D9488` teal ≈ 3.5:1, and `#1E6FA8` is borderline ≈ 4.4:1), so darken them. **Consult the `dataviz` skill** to lock the final values and verify contrast. AA-targeted starting point (Sonnet to confirm/adjust via dataviz — these are chosen to pass, unlike the first-draft mid-tones):

| kind | LOD fill | white-text contrast |
|---|---|---|
| fact | `#1B5E8C` (deep blue) | ~5.2:1 ✓ |
| dim | `#5B6472` (dark slate) | ~6.6:1 ✓ |
| sql_view | `#0B5A54` (deep teal) | ~8.1:1 ✓ (darkened post-CI so its lightness sits clearly below `dim`, not hue-only — helps deuteranopia) |

Keep the family coherent with the detailed view (same hues, darker/saturated). State (secured/RLS/severity/focus) continues to show through the **border** color/width (unchanged logic), not the fill. `alias_of` isn't a distinct fill (it's a badge only in the card) — an alias node takes its kind's fill at LOD.

**Accepted UX trade-off:** at LOD there are no badges, so an annotated table's ✎ marker isn't shown at overview (secured state still shows via the red border; notes have no border signal). Consistent with "title only."

---

## 6. Files touched

| File | Change |
|---|---|
| `agents/shared/erd/renderer.js` | A: `vector-effect` on body rect (311) + edge path (280). B: `LOD_T`/`lodActive()`, threshold-crossing re-render in `applyView`, LOD branch in `renderNodes`. C: kind→LOD-fill mapping + white title. |
| `agents/shared/erd/renderer.css` | Only if a class-based rule is cleaner than an attribute (e.g. a `.node-block-title` font size); otherwise no change. |
| `agents/cli/ts-object-model-erd/SKILL.md` | `## Changelog` MINOR entry (1.5.0 at PR time) + note semantic-zoom/overview-legibility in the "ERD features" list. |

**Complexity:** keep new helpers small (cc < 15 gate). `renderNodes` already branches a lot — extract the LOD block into a helper (`drawNodeBlock(g,n,t,stroke,sw)`) rather than inflating `renderNodes`.

---

## 7. Verification (headless Chrome; `view`/`focusSet` are module-scoped, read the DOM)

Build the GTM export (`/private/tmp/claude-501/-Users-damianwaldron-Dev/45ed40f8-ed5a-4cd3-ae51-f5f2769524fd/scratchpad/export.json`) and the mini control. Assert:

1. **Renders** — GTM 79 `g.node`, zero `pageerror`.
2. **Non-scaling stroke present** — node body rect and edge path carry `vector-effect="non-scaling-stroke"`.
3. **LOD active at fit** — after `#zoom-fit` (k=0.12 < 0.5), a node `<g>` contains **no** column rows / header separator (LOD block: ≤ ~2 shapes + 1 title text). Capture a screenshot for eyeball.
4. **Detail restored on zoom-in** — zoom to k ≥ 0.5 (dispatch ctrl-wheels or set via buttons), a node `<g>` again contains column rows + header. Confirms threshold re-render fires.
5. **One re-render per crossing** — **start counting only after initial load settles** (the load sequence legitimately renders nodes twice on a large model: once detailed at k=1, then once as LOD blocks after `fit()` — see §4 B1). After that: crossing the threshold triggers exactly one `renderNodes`; panning at fixed zoom does **not** re-render.
6. **State borders survive at LOD** — a focused node (click) still shows the thick focus border; if the model has RLS/severity, those border colors persist in the block.
7. **Interaction parity at LOD** — at fit zoom, click-to-focus updates the inspector; drag moves the node; minimap still tracks.
8. **Contrast** — spot-check (or compute) that each LOD fill vs ground and white-text vs fill meet WCAG AA (via dataviz guidance).
9. **Small model** — mini fits at ~1.35× (> 0.5), so it renders detailed cards as before; no LOD, no regression; 24 pytest still green.

Keep `pytest agents/cli/ts-object-model-erd/tests/` (24) and the full pre-commit gate green.

---

## 8. Rollout
- `feat/erd-overview-legibility` (stacked on #154); **no push to main** — PR after Fable CI review.
- Skill MINOR bump 1.5.0 at PR time; CLI-only skill, no CoCo stage-sync.
- Base #154 should merge first (or rebase once it does); both touch `renderer.js` but this branch already contains #154's changes so there's no conflict with main beyond what #154 introduces.
