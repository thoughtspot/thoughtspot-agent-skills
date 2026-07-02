# ERD subject-area grouping — design

**Date:** 2026-07-03
**Branch:** `feat/erd-subject-area-grouping` (based on `main` @ cbb4ba4)
**Skill:** `ts-object-model-erd` (shared library `agents/shared/erd/`)
**Status:** Approach agreed in chat — three selectable grouping strategies + a shared tint/legend display. Ready for implementation by Sonnet after Fable spec review.

---

## 1. Context & goal

On a large model (GTM, 79 tables) it's hard to see the *shape* of the domain. The user wants to group tables into subject areas — and, because different models favor different bases, wants **all three strategies selectable at runtime**, not one baked-in heuristic.

**Design principle: strategy is pluggable, display is shared.** Each strategy is a pure function `tables/joins → {tableId → groupId}`. A **"Group by"** selector swaps strategy. The coloring/legend rendering is identical regardless of which strategy produced the groups. Grouping is a **non-destructive coloring overlay** — no layout/position change, orthogonal to filters/focus/RLS.

Existing hooks (main @ cbb4ba4):

| Hook | Location | Reuse for |
|---|---|---|
| `<select id="col-mode">` + `colSel`/`colSel.onchange` | render.py:46; renderer.js:16, 768 | The new `Group by` `<select id="group-mode">` + `groupSel` |
| `renderNodes()` (header fill `hbg` :375) | renderer.js:347 | detail-node group accent stripe |
| `drawNodeBlock(g,n,t,stroke,sw)`, `LOD_FILL`, `lodKind` | renderer.js:339, 334–335 | LOD block group tint |
| `nodeHeight`/`HEAD_H`/`ROW_H` | :44, :21 | stripe geometry (no height change) |
| `MODEL.tables` / `MODEL.joins` / `tableById` / `adj`/`undir` | throughout | strategy inputs |
| filter-chips / `.hint` / `.ctrls` | render.py:61/101/92 | legend placement, help text |

---

## 2. Goals / non-goals

**Goals:**
- A **Group by** selector: **None** (default) / **Name prefix** / **Graph cluster** / **Fact neighbourhood**.
- Three pure strategy functions, each `→ {byId, groups}` where `groups=[{id,label,color,count}]`.
- Shared display: a group **accent stripe** on detail nodes + **group tint** on LOD blocks + a **legend** (label, swatch, count) with click-to-highlight.
- Sensible behavior + honest limits per strategy (see §3).

**Non-goals:**
- Manual/assigned groups (a heavier 4th mode — out of scope; can follow later).
- Changing layout to physically cluster grouped nodes (coloring only; the *Layered/Star/Organic* layouts are unchanged).
- Persisting the selected mode across reloads (default None each load; note it).
- Parser/data changes.

**Success:** on GTM, Name-prefix yields ~8–10 legible groups (SFDC/JIRA/MIXPANEL/GAINSIGHT/PENDO/VIVUN/TS/NPS/…/Other); Graph-cluster yields several non-trivial communities (not one blob); Fact-neighbourhood yields per-fact groups; the legend matches the canvas; None fully restores today's rendering; filters/focus/RLS/minimap/Share-HTML all still work.

---

## 3. Strategy layer

`computeGroups(mode)` returns `{byId:{tableId:groupId}, groups:[{id,label,color,count}]}`, memoized per `(model, mode)` in a `groupCache` (cleared on model switch). Colors are assigned **after** grouping (see §5) so each strategy only produces group membership + labels.

### 3a. Name prefix (`groupByPrefix`)
For each table: **uppercase** the id, split on `_`. Take the leading token; if it's in the modifier set `{W, DIM, VW, VIEW, STG, TMP, FACT, AGG}` **and a next token exists**, use the next token instead. A single-token name (no `_`) uses the whole name. Group id/label = that token, title-cased. Fold any group with **< 2 members** into **"Other"**. Deterministic.
- **Degenerate-case guard (C1):** if the modifier-skip causes **> 50% of tables to land in "Other"** (e.g. an all-`DIM_*` model), recompute **without** the modifier-skip and keep whichever result has fewer Other members. This prevents `DIM_CALENDAR`→`CALENDAR`→Other-style folding from swallowing a whole model.
- Best for disciplined naming (GTM → SFDC/JIRA/MIXPANEL/…). Limitation: names without prefixes group poorly (mostly "Other").

### 3b. Graph cluster (`groupByCluster`)
Community detection on the **undirected join graph** (`undir`) via **stabilized label propagation** — no deps, deterministic, no `Math.random`:
- **Dedupe neighbours first:** `undir` contains **duplicate entries** when two joins connect the same pair (loadModel pushes per-join, renderer.js:846). Build a **de-duplicated** neighbour set per node so the vote isn't silently weighted by join multiplicity.
- Init each node's label = its own id. Run a fixed number of passes (e.g. 8) over nodes in **sorted id order**. For each node, tally labels among its de-duped neighbours **including the node's own current label**, and **relabel only on a strict majority improvement** over the current label (the standard LPA stabilizer that prevents the lexicographically-smallest label from flooding a hub-connected component). Tie-break = **lexicographically smallest label string** (labels are table ids).
- Collapse final labels → group ids; label each group after its **highest-degree member**. Isolated nodes (no joins) → **"Ungrouped"**.
- **Honest 1-group behavior (B1):** label-prop on a hub-dominated graph (GTM: everything joins `SFDC_ACCOUNT`/`OPPORTUNITY`) *may* still yield one large community. That is acceptable and must degrade gracefully — the legend reports whatever it finds; **do not** promise N communities. **Before finalizing, run this against the real GTM export** and record the actual community count in the PR; the §7 test asserts **determinism across reloads + ≥1 group + no crash**, NOT a specific count. If GTM collapses to ~1, note it as a real property of that model (its joins are hub-centric), not a bug.

### 3c. Fact neighbourhood (`groupByFact`)
Each **fact** anchors a group. Assign every non-fact node to the fact that is nearest by **hop distance**, with a deterministic tie-break, via a level-by-level relaxation over the de-duped `undir` (a plain FIFO multi-source BFS does **not** honor a fact-id tie-break — the winner would follow join-declaration order). Per node track `(dist, factId)`; when reaching a node via a fact at `newDist`, **accept if `newDist < dist || (newDist === dist && newFactId < factId)`** (lexicographic fact-id compare). Group label = the fact id. Facts with no reachable dims are singleton groups; nodes unreachable from any fact → **"Other"**.
- Limitation to document: **over-fragments with many facts** (GTM has 41) and shared dims are force-assigned to one fact — best for clean star/snowflake schemas. The legend header shows the group count so this is visible, not surprising.

All strategy functions should stay small/readable — extract helpers (`_leadingToken`, `_dedupNeighbours`, `_labelPropPass`, `_multiSourceRelax`). Note: the module-health cc<15 gate is **Python-only** (`check_module_health.py` scans `.py`), so for renderer.js this is self-discipline; the realistic pressure is on `renderNodes` (add the stripe via a helper, see §5/C4) and `renderLegend` (extract a row-builder per the `noteReviewRow` precedent), not the strategies.

---

## 4. Selector + wiring

- **render.py:** add `<select id="group-mode">` (options: `none`/`prefix`/`cluster`/`fact`, default `none`) next to `col-mode` in the controls, labeled "Group by". Add a **legend container** `<div class="grp-legend" id="grp-legend" hidden></div>` (near `.hint`, bottom area). Update the help drawer with the Group-by control.
- **renderer.js:** `let GROUP_MODE="none";` `const groupSel=$("group-mode");` `groupSel.onchange=()=>{GROUP_MODE=groupSel.value; clearGroupHighlight(); renderAll(); renderLegend();}`. On `loadModel`, reset `GROUP_MODE="none"` **and `groupSel.value="none"`** (C2 — the model-switcher path at renderer.js:911 would otherwise show a stale select value; the Share-HTML path self-heals via the baked `selected` attribute), clear `groupCache`, `clearGroupHighlight()`, `renderLegend()` (which must **clear + hide** `#grp-legend` when mode is none).

---

## 5. Display layer (shared across strategies)

When `GROUP_MODE!=="none"`, resolve `const grp=computeGroups(GROUP_MODE)` and per node `const gc=grp.byId[t.id]` → its group's `color`.

- **Color palette (§ dataviz):** assign a **categorical palette** to `grp.groups`, ordered **count desc, then label** (C6 — deterministic so fold membership + legend order are reproducible). Cap at **~10 groups + "Other"/grey**; overflow (beyond top-N by that order) folds into "Other", annotated in the legend. Colors are accents/tints and never touch borders (RLS-red / focus-blue borders stay authoritative). **Two palette needs (C3):** the stripe color (on the light node body) and a **dark LOD variant** of the same hue for the LOD block behind the **white** `.node-block-title` (calibrated ≥4.5:1 AA, matching the existing dark `LOD_FILL` comment at renderer.js:329–333). Either provide a dark variant per group **or** luminance-switch the title color (white/ink) per group fill. **Load the `dataviz` skill** to pick both and verify separation/CVD/contrast.
- **Detail node (C4 — z-order + inset):** draw a **group accent stripe** — a thin rounded rect in the group color along the node's left edge — inserted **after** the header rects (`hbg` at renderer.js:376–377) so it isn't covered, and **inset** from the body-rect border (`x≈1.5, y≈3, width≈5, height≈n.h−6, rx≈2.5`) so it never overpaints the state-aware border (:364–367) or clash with the `rx:10` corner. Header `hbg` (fact/dim) and all borders stay as-is → grouping composes with, not replaces, the fact/dim + state encoding. Draw via a small helper so `renderNodes` doesn't grow.
- **LOD block:** at overview the block fill *is* the signal, so when grouping is active `drawNodeBlock` fills with the group's **dark LOD variant** (not `LOD_FILL[lodKind]`) and the title uses the matching AA-safe text color (C3); border stays state-aware. (When `GROUP_MODE==="none"`, unchanged.)
- **Legend (`renderLegend`)**: populate `#grp-legend` with a row per group — swatch + label + count — plus a header naming the active mode + total group count (so fact-mode fragmentation is visible) + any "N folded into Other" note. Extract a row-builder helper. When mode is None: **clear innerHTML + hide**.
- **Legend click-to-highlight (B3 — defined precedence):** use a **separate** `groupHighlight` overlay var (the highlighted group id, or null), **not** `focusGroup()`/`activeFilters`. When set, apply **ghost-only, never `gone`** to out-of-group nodes/edges — i.e. intersect it into the keep computation such that it can only *dim*, so it can't hide nodes even during tree/compare focus. Clear `groupHighlight` on: second click of the same row, mode change, `loadModel`, filter-chip click (:775–782), and empty-canvas click (:465–467). Sync the active legend row's "on" state like `syncChips()`. Highlight and an active filter/focus compose (both can dim); neither hides via the highlight.

No layout/position change; grouping recolors only. **Non-goal (C5):** the minimap keeps its kind-based fills (`mmFill`, renderer.js:490–493) — groups are not reflected there.

---

## 6. Files touched

| File | Change |
|---|---|
| `agents/shared/erd/renderer.js` | `GROUP_MODE`+`groupSel`+`groupCache`; `computeGroups` + `groupByPrefix`/`groupByCluster`/`groupByFact` (+ small helpers, all cc<15); group color assignment; accent stripe in `renderNodes`; group tint in `drawNodeBlock`; `renderLegend` + click-to-highlight; reset in `loadModel`. |
| `agents/shared/erd/renderer.css` | `.grp-stripe` (n/a if drawn in SVG), `.grp-legend` panel + rows + swatches. |
| `agents/shared/erd/render.py` | `Group by` select; `#grp-legend` container; help-drawer line. |
| `agents/cli/ts-object-model-erd/SKILL.md` | `## Changelog` MINOR (1.7.0 at PR time) + ERD-features bullet. |
| `CHANGELOG.md` | matching `feat: update ts-object-model-erd to v1.7.0 — …` entry (repo gate). |

**Bundled nits (from the prior CI review, cheap, include here):** (a) `esc()` also escape `"`→`&quot;` / `'`→`&#39;` (attribute-injection hardening) — verified safe since every embedment is read back via `dataset` (the parser decodes before access); **also fix `findingCard`'s `data-target="${x.target}"` which is currently embedded UNescaped** (renderer.js:565). (b) `clearAllNotes` refreshes the review panel if that's the open view (detect via `inspector.querySelector(".notes-review")` and call `showNotesReview()`, mirroring the per-row delete path :748) — currently it routes by `selected`, which the panel never sets, so it lands on a stale view. **Not** bundling the arrowhead-marker scaling (fiddly, accepted trade-off).

---

## 7. Verification (headless Chrome; module-scoped state — read DOM)

Build GTM (`/private/tmp/claude-501/-Users-damianwaldron-Dev/45ed40f8-ed5a-4cd3-ae51-f5f2769524fd/scratchpad/export.json`) + mini control. Assert:

1. **Selector present**, default None → node rendering byte-equivalent to today (no stripe, `LOD_FILL` unchanged), legend hidden.
2. **Name-prefix:** switching to it groups GTM into a sane set (assert SFDC/JIRA/MIXPANEL/GAINSIGHT among labels; `W_SFDC_*` lands in SFDC, not "W"; singleton→Other); legend rows match `grp.groups`; stripe color per node matches its group; count in legend sums to 79.
3. **Graph-cluster (B1 — assert determinism, not count):** produces **≥1** group, **no crash**, and the **identical** assignment across two reloads. Record GTM's actual community count in the PR; do NOT hard-assert a range (a hub-centric model may legitimately yield ~1). Confirm the stabilizer + neighbour-dedup are in effect.
4. **Fact-neighbourhood:** every fact anchors a group; each non-fact node assigned to exactly one group via the `(dist,factId)` relaxation (deterministic across reloads); legend shows the (large) group count; no crash with 41 facts.
5. **LOD tint + title contrast (C3):** at fit (0.12×) with a mode active, blocks fill with the group **dark variant** (not `LOD_FILL[kind]`) and the title stays legible (computed white/ink contrast ≥4.5:1 per group); borders still state-aware; None reverts to kind fills.
6. **Legend click-to-highlight (B3):** clicking a group row **dims** (never hides) non-group nodes — verify it only ghosts even during a tree/compare focus; second click clears; `groupHighlight` also clears on mode change, model load, filter-chip click, and empty-canvas click; active row shows an "on" state.
7. **Palette:** ≤ ~10 groups + Other, ordered count-desc/label; colors distinct (contrast/CVD via dataviz); overflow folds into Other with a legend note.
8. **No regressions:** filters/focus/compare/minimap/Share-HTML/notes(+chip+review) all work; `GROUP_MODE` **and** `group-mode` select reset to None on model switch/reload; legend cleared+hidden at None; nits (a)/(b) verified (incl. `findingCard` data-target); 24 pytest green; full pre-commit green.

---

## 8. Rollout
- `feat/erd-subject-area-grouping` off `main`; **no push to main** — PR after Fable CI review.
- Skill MINOR 1.7.0 + root CHANGELOG entry (repo gate); CLI-only skill, no CoCo stage-sync (`agents/shared/erd/` consumed only by `build_erd.py`).
