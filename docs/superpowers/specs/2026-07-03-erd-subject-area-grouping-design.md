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
Group id = the leading name token, **skipping known modifier prefixes** so warehouse/view naming doesn't mis-split: if the first `_`-token is in `{W, DIM, VW, VIEW, STG, TMP, FACT, AGG}`, use the next token (e.g. `W_SFDC_PERSON` → `SFDC`, `DIM_CALENDAR` → `CALENDAR`… — actually treat `DIM` as a real prefix only if no better token; see nit-tolerance below). Fold any group with **< 2 members** into **"Other"**. Label = the prefix, title-cased. Deterministic. Best for disciplined naming (GTM). Limitation to document: garbage-in if names aren't prefixed.

### 3b. Graph cluster (`groupByCluster`)
Community detection on the **undirected join graph** (`undir`). Use **label propagation** (no deps, ~linear, deterministic): init each node's label = its own id; iterate a fixed number of passes (e.g. 8) over nodes **in sorted id order**, setting each node's label to the most frequent label among its neighbours (tie-break: lowest label id) — **no `Math.random`** (reproducible across reloads). Collapse final labels to group ids; label each group after its highest-degree member (or most-common name prefix within it). Isolated nodes (no joins) → **"Ungrouped"**. Rationale for label-prop over connected-components: GTM is one connected component (everything joins to `SFDC_ACCOUNT`/`OPPORTUNITY`), so components would yield a single blob — label-prop finds sub-communities. Limitation: communities are structural, may not map 1:1 to business domains; results can shift if joins change.

### 3c. Fact neighbourhood (`groupByFact`)
Each **fact** anchors a group. BFS over `undir` from all facts simultaneously (multi-source), assigning each non-fact node to the **nearest fact** (tie-break: fewest hops, then lowest fact id — deterministic). Group label = the fact's id. Facts with no reachable dims are their own singleton group; nodes unreachable from any fact → **"Other"**. Limitation to document: **over-fragments when there are many facts** (GTM has 41) and shared dims are force-assigned to one fact — best for clean star/snowflake schemas, noisy on wide models. Surface this in the legend/hint (e.g. show group count) so the user can judge.

All three functions must be **cc < 15** — extract helpers (e.g. `_leadingToken`, `_labelPropPass`, `_multiSourceBFS`).

---

## 4. Selector + wiring

- **render.py:** add `<select id="group-mode">` (options: `none`/`prefix`/`cluster`/`fact`, default `none`) next to `col-mode` in the controls, labeled "Group by". Add a **legend container** `<div class="grp-legend" id="grp-legend" hidden></div>` (near `.hint`, bottom area). Update the help drawer with the Group-by control.
- **renderer.js:** `let GROUP_MODE="none";` `const groupSel=$("group-mode");` `groupSel.onchange=()=>{GROUP_MODE=groupSel.value; renderAll(); renderLegend();}`. On `loadModel`, reset `GROUP_MODE="none"`, clear `groupCache`, `renderLegend()`.

---

## 5. Display layer (shared across strategies)

When `GROUP_MODE!=="none"`, resolve `const grp=computeGroups(GROUP_MODE)` and per node `const gc=grp.byId[t.id]` → its group's `color`.

- **Color palette (§ dataviz):** assign a **categorical palette** to `grp.groups` — N visually distinct hues, **contrast-checked**, that read as accents and don't read as the semantic RLS-red / focus-blue *borders* (grouping never touches borders). Cap at **~10 groups + "Other"/grey**; if a strategy yields more, keep the top-N by count and fold the tail into "Other" (log/annotate that folding in the legend). **Load the `dataviz` skill** to pick the palette and verify separation/CVD.
- **Detail node:** draw a **group accent stripe** — a thin (~5px) rounded rect in the group color along the node's **left edge** (full height) — *added* to the current node drawing; header `hbg` (fact/dim) and all borders stay as-is. Grouping thus composes with, not replaces, the fact/dim + state encoding.
- **LOD block:** at overview the block fill *is* the signal, so when grouping is active `drawNodeBlock` fills with the **group color** instead of `LOD_FILL[lodKind]`; border stays state-aware. (When `GROUP_MODE==="none"`, unchanged.)
- **Legend (`renderLegend`)**: populate `#grp-legend` with a row per group — swatch + label + count — plus a header naming the active mode and total group count (so fact-mode fragmentation is visible). **Click a legend row → highlight that group** (reuse the ghost/dim mechanism: dim non-group nodes; a second click clears). Hidden when mode is None. Keep it collapsible/scrollable if many groups.

No layout/position change; grouping recolors only.

---

## 6. Files touched

| File | Change |
|---|---|
| `agents/shared/erd/renderer.js` | `GROUP_MODE`+`groupSel`+`groupCache`; `computeGroups` + `groupByPrefix`/`groupByCluster`/`groupByFact` (+ small helpers, all cc<15); group color assignment; accent stripe in `renderNodes`; group tint in `drawNodeBlock`; `renderLegend` + click-to-highlight; reset in `loadModel`. |
| `agents/shared/erd/renderer.css` | `.grp-stripe` (n/a if drawn in SVG), `.grp-legend` panel + rows + swatches. |
| `agents/shared/erd/render.py` | `Group by` select; `#grp-legend` container; help-drawer line. |
| `agents/cli/ts-object-model-erd/SKILL.md` | `## Changelog` MINOR (1.7.0 at PR time) + ERD-features bullet. |
| `CHANGELOG.md` | matching `feat: update ts-object-model-erd to v1.7.0 — …` entry (repo gate). |

**Bundled nits (from the prior CI review, cheap, include here):** (a) `esc()` also escape `"`→`&quot;` / `'`→`&#39;` (attribute-injection hardening); (b) `clearAllNotes` refreshes the review panel if it's the open view. **Not** bundling the arrowhead-marker scaling (fiddly, accepted trade-off) — leave for a separate look.

---

## 7. Verification (headless Chrome; module-scoped state — read DOM)

Build GTM (`/private/tmp/claude-501/-Users-damianwaldron-Dev/45ed40f8-ed5a-4cd3-ae51-f5f2769524fd/scratchpad/export.json`) + mini control. Assert:

1. **Selector present**, default None → node rendering byte-equivalent to today (no stripe, `LOD_FILL` unchanged), legend hidden.
2. **Name-prefix:** switching to it groups GTM into a sane set (assert SFDC/JIRA/MIXPANEL/GAINSIGHT among labels; `W_SFDC_*` lands in SFDC, not "W"; singleton→Other); legend rows match `grp.groups`; stripe color per node matches its group; count in legend sums to 79.
3. **Graph-cluster:** yields **>1** group and **not** one blob (assert 2 ≤ groups ≤ ~15 on GTM); deterministic across two reloads (same assignment).
4. **Fact-neighbourhood:** every fact anchors a group; each dim assigned to exactly one group; legend shows the (large) group count so fragmentation is visible; no crash with 41 facts.
5. **LOD tint:** at fit (0.12×) with a mode active, blocks fill with group colors (not `LOD_FILL[kind]`); borders still state-aware; None reverts to kind fills.
6. **Legend click-to-highlight:** clicking a group row dims non-group nodes; second click clears; composes with (doesn't corrupt) the filter chips.
7. **Palette:** ≤ ~10 groups + Other; colors distinct (spot-check contrast/CVD via dataviz); overflow folds into Other with a legend note.
8. **No regressions:** filters/focus/compare/minimap/Share-HTML/notes(+chip+review) all work; mode resets to None on model switch/reload; nits (a)/(b) verified; 24 pytest green; full pre-commit green.

---

## 8. Rollout
- `feat/erd-subject-area-grouping` off `main`; **no push to main** — PR after Fable CI review.
- Skill MINOR 1.7.0 + root CHANGELOG entry (repo gate); CLI-only skill, no CoCo stage-sync (`agents/shared/erd/` consumed only by `build_erd.py`).
