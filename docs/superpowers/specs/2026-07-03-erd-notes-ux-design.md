# ERD notes UX — design

**Date:** 2026-07-03
**Branch:** `feat/erd-notes-ux` (based on `main` @ 9d24626, i.e. after #155)
**Skill:** `ts-object-model-erd` (shared library `agents/shared/erd/`)
**Status:** Approach agreed in chat (4 gaps in the object-notes feature). Ready for implementation by Sonnet after Fable spec review.

---

## 1. Context & problem

The ERD lets a user attach a free-text **note** to a table or a join (edge). Notes persist to `localStorage` (`NOTES_KEY = "ts-erd-notes:"+model.name`, keyed by table `id` or join `name`) and are baked into Share-HTML. Four gaps were reported and **empirically confirmed** by driving the built HTML headless:

1. **"Not sure if save is working."** Save *does* work — after clicking **Save note**, `localStorage["ts-erd-notes:GTM"]` = `{"SFDC_OPPORTUNITY":"REVIEW: …"}` and it survives reload. **But there is no feedback:** `note-save.onclick` (renderer.js:61) calls `persistNotes();renderAll();` and does **not** re-render the inspector, so the panel looks unchanged and the save feels like a no-op.
2. **"No way to delete."** A Delete button exists (`notesSection`, renderer.js:53–57: `${val?'<button id="note-del">…':''}`), but it only renders when `notes[id]` is already set. Because the inspector isn't refreshed after a save (see #1), the Delete button doesn't appear until the user reloads or re-selects the object. Mid-session it's effectively unreachable.
3. **"No quick way to highlight all objects with notes."** No filter/overlay for noted objects. Worse: at overview/LOD zoom (`view.k < 0.5`, from #155) the `✎` note badge (node rect at :351, amber `#D97706`) isn't drawn at all, so on a large model there is **no** visual indication of which tables carry notes.
4. **"No quick way to view all notes."** No way to read every note at once for review — the user must click each noted object individually.

Root cause of #1 + #2 is the same one-liner: **the inspector isn't re-rendered after save/delete.**

Existing patterns to reuse:

| Pattern | Location | Reuse for |
|---|---|---|
| `wireNotes(id)` save/del handlers | renderer.js:59–62 | Feature A |
| `notesSection(id)` (textarea + Save + conditional Delete) | :53–57 | Feature A |
| Filter chips (`#filter-chips`, `data-f=…`, `tableMatchesFilter`, `syncChips`, chip click handler, chip enable/disable in `loadModel`) | render.py:61–68; renderer.js:188–194, 681–688, 758–763 | Feature B |
| List-panel-in-inspector (`showRlsSubgraph` :657, `showOverview` :553, back-button pattern) | renderer.js | Feature C |
| Controls buttons (`share-btn`, `clear-notes-btn`, `help-btn`) | render.py:73–75 | Feature C trigger |
| `✎` node badge / amber annotated edge | renderer.js:351 / :275 | Feature B styling reference |

---

## 2. Goals / non-goals

**Goals:**
- **A.** Save/delete give immediate feedback and the Delete button is reachable in-session (fixes #1 + #2).
- **B.** A one-click way to **highlight every object carrying a note** — works at overview/LOD zoom too, since the badge is hidden there.
- **C.** A **review panel listing all notes** (tables + edges), each click-to-jump, with inline delete.

**Non-goals:**
- Changing where/how notes are stored (localStorage keying, Share-HTML baking) — unchanged.
- Rich text / multiple notes per object — still one free-text note per object.
- Any parser/data change.

**Success:** save shows a confirmation and immediately exposes Delete; the "Notes" chip highlights all noted tables at any zoom; a "Review notes" panel lists every note and jumps to the object on click; existing behavior (filters, focus, minimap, Share-HTML, clear-notes) intact.

---

## 3. Shared note-mutation exit + Feature A (save/delete feedback)

### 3.0 Shared helpers (used by A, B, C, and clearAllNotes)
All note writes must go through ONE exit so no site is missed:

```
function syncNotesChip(){
  const chip=document.querySelector('#filter-chips .fchip[data-f="notes"]');
  const any=Object.keys(notes).length>0;
  if(chip)chip.disabled=!any;
  // B3: never leave the diagram ghosted behind a disabled chip
  if(!any && activeFilters.has("notes")){activeFilters.delete("notes");if(!activeFilters.size)activeFilters.add("all");}
  syncChips();
}
function commitNotes(){ persistNotes(); syncNotesChip(); renderAll(); }
```

`commitNotes()` is the single mutation exit (persist → chip/filter re-sync → redraw). `clearAllNotes` (renderer.js:52) must call it too (replace its inline `persistNotes();renderAll();`).

### 3.1 wireNotes — pass the object type; refresh + confirm
Change the signature to **`wireNotes(id, isEdge)`** and pass `isEdge` from the two call sites (`showTable`→`wireNotes(id,false)` :622, `showEdge`→`wireNotes(name,true)` :654). Do **not** read `selected` inside the handlers — `selected.id` can diverge from the displayed object (shift-click compare leaves `selected` on a different id), and `selected` can be null. Use the closure `id` + `isEdge`.

- **On save** (`note-save`): `const v=inp.value.trim(); if(v)notes[id]=v; else delete notes[id]; commitNotes();` then **re-render THIS inspector** — `isEdge?showEdge(id):showTable(id)` — so Delete appears and state reflects the save, then show a transient **"Saved ✓"**.
- **On delete** (`note-del`): `delete notes[id]; commitNotes();` then re-render (`isEdge?showEdge(id):showTable(id)`) and show a transient **"Note deleted"**.

**Preserve scroll (nit 1):** the notes section is at the *bottom* of the table inspector and both `showTable`/`showEdge` end with `inspector.scrollTop=0` (:622/:654), which would scroll the confirmation off-screen. Capture `inspector.scrollTop` before the re-render and restore it after (or `scrollIntoView` the notes section), so "Saved ✓" is visible.

**Confirmation UI:** append a self-dismissing `.note-saved` span into the `.notes-btns` row (`display:flex;gap:6px`, renderer.css:170 — no layout thrash) AFTER the re-render (a re-render replaces `inspector.innerHTML`, so appending before would be wiped); remove it via `setTimeout(~1500ms)` (harmless if the node is already detached by a later render). Add the fade to `renderer.css` and honor the existing reduced-motion pattern (css :103 / JS `reduce` const :20). No external deps.

**Key-collision caveat (document):** `notes` is a single map keyed by table id OR join name; if a table id equals a join name, both light up. Pre-existing limitation; `wireNotes(id,isEdge)` and the `tableById`-first resolution in §5 keep behavior deterministic — note it, don't fix here.

**Guard:** handlers use `.onclick=` assignment and each re-render fully replaces `inspector.innerHTML`, so re-running `wireNotes` re-binds cleanly (no duplicate listeners).

---

## 4. Feature B — highlight objects with notes

Add a **"Notes" filter chip** to the filter row, consistent with the existing chips.

- **render.py:** add `<button class="fchip" data-f="notes">Notes</button>` to `#filter-chips` (after RLS/alias).
- **renderer.js `tableMatchesFilter`:** add `if(activeFilters.has("notes")&&notes[t.id])return true;` so noted tables are the highlighted subgraph (non-matches dim, exactly like the other chips — and this works at LOD because filtering dims/ghosts by node, independent of badges).
- **Edges:** edge notes (`notes[join.name]`) already render amber when present; additionally, when the "notes" filter is active, **keep noted edges emphasized** (don't dim them). Reuse the existing annotated-edge amber; ensure edges connected to the highlight aren't hidden. (If wiring edge-note highlighting is more than a couple of lines, scope the chip to tables and note the edge limitation — tables are the primary case.)
- **Chip enable/disable (corrected — B1):** do **not** extend the chip loop at renderer.js:760–763 — it runs **before** `notes=loadNotes()` (:766) and before the `ERD_INITIAL_STATE` baked-notes merge (:770–774), so it would compute against the previous model's notes (model switcher) or the module-init `{}` and wrongly disable the chip despite persisted/baked notes. Instead call **`syncNotesChip()` at the END of `loadModel`** (after :774). Runtime changes already route through `commitNotes()`→`syncNotesChip()`.
- **syncChips / chip-click**: no special-casing needed — the generic handler at :682 already toggles any `data-f`.
- **B3 (last-note-while-active):** handled by `syncNotesChip()` dropping `"notes"` from `activeFilters` when no notes remain (see §3.0) — prevents the whole diagram ghosting behind a disabled-but-active chip. `clearAllNotes` inherits this via `commitNotes()`.

At overview/LOD this is now the *only* way to see which tables have notes (badge is hidden there), so it directly answers #3.

---

## 5. Feature C — review all notes

A panel listing every note, rendered in the inspector like `showRlsSubgraph`.

- **Trigger:** add a **"Review notes" button** (`id="notes-review-btn"`) next to `clear-notes-btn` in render.py:73–75. Clicking it calls `showNotesReview()`.
- **`showNotesReview()`** (new, modeled on `showRlsSubgraph` :657): build a list from `notes`. For each key, resolve: table (`tableById[key]`) → join (`MODEL.joins.find(j=>j.name===key)`) → **neither = stale key**. Show object name + a small tag (Table / Join / **"not in model"**) and the escaped, wrapped note text. Rows:
  - **Table/Join rows are click-to-jump.** `selectTable(id,false)` (or `selectEdge(name)`) opens the inspector itself (no extra call needed), **and move the canvas** like the finder (:801): for a table `view.k=Math.max(view.k,0.9); centerOn(nodeById[id])`; for an edge center on/near its endpoints (or skip the pan). §7.4 asserts the jump moves the view, so this is required, not optional.
  - **Stale-key rows (B2)** — a note whose object was renamed/removed (keys persist per model *name* in localStorage) — render as **delete-only, NOT clickable** (no jump). This prevents `selectTable(staleId)`→`showTable` crashing (`showTable` has no missing-id guard: `t.cols` on undefined, :591–592).
  - **Per-row delete** routes through the shared exit: `delete notes[key]; commitNotes();` then re-render the panel (`showNotesReview()`).
- **Defensive (B2, recommended):** add a missing-id guard to `showTable` mirroring `showEdge`'s (:634) — `const t=tableById[id]; if(!t){showOverview();return;}` — so no future caller can crash on a stale id.
- **Back button → `showOverview()`** using `showTable`'s back pattern (:621: clear `focusSet`/`selected` → `showOverview`). Do **not** copy `showRlsSubgraph`'s back (:667) — it resets `activeFilters` to `["all"]`, which would wipe an active filter the user set.
- **Empty state:** "No notes yet — add one from any table or join's inspector." Keep it a read-only view over `notes` (no new persistence).

Optional nicety (only if trivial): a note **count** on the button (e.g. "Review notes (3)").

---

## 6. Files touched

| File | Change |
|---|---|
| `agents/shared/erd/renderer.js` | Shared: `syncNotesChip()`+`commitNotes()`; `clearAllNotes` routes through `commitNotes`. A: `wireNotes(id,isEdge)` re-renders inspector (scroll-preserving) + transient confirmation. B: `tableMatchesFilter` notes case; `syncNotesChip()` at end of `loadModel` (not the :760 loop). C: `showNotesReview()` (stale-key rows, canvas-move on jump, `showOverview` back), `showTable` missing-id guard, wire `notes-review-btn`. |
| `agents/shared/erd/renderer.css` | `.note-saved` confirmation fade (reduced-motion aware); `.notes-review` list/row styling. |
| `agents/shared/erd/render.py` | B: `Notes` filter chip. C: `Review notes` button in controls. Help drawer (:120,:145–146) — add the Notes chip + Review-notes lines. |
| `agents/cli/ts-object-model-erd/SKILL.md` | `## Changelog` MINOR entry (1.6.0 at PR time) + note the notes highlight/review in the ERD-features list. |

**Complexity:** keep `showNotesReview` and any helper under cc<15; extract a row-builder if needed. Don't inflate `renderNodes`/`renderEdges`.

---

## 7. Verification (headless Chrome; module-scoped state — read DOM)

Build GTM (`/private/tmp/claude-501/-Users-damianwaldron-Dev/45ed40f8-ed5a-4cd3-ae51-f5f2769524fd/scratchpad/export.json`) + mini control. Assert:

1. **Save feedback + Delete appears same-session** — open a table, type + Save: a "Saved ✓" confirmation shows, and the Delete button is present **without** reload. Delete removes it and the textarea clears, still without reload.
2. **Persistence unchanged** — after Save + `page.reload()`, the note text is still in the textarea and `localStorage` (regression guard on the working save path).
3. **Notes chip highlights** — with ≥1 note, clicking the "Notes" chip highlights (does not dim) the noted table(s) and dims the rest; works at fit/LOD zoom (0.12×) too. Chip is **disabled** when no notes exist and **enables** after the first save (and disables again after the last delete/clear) without reload. **Baked-notes load (B1):** build a Share-HTML/reload with an existing note and confirm the chip is **enabled on load** (regression for the :760-loop bug).
   **B3:** activate the Notes chip, then delete the last note — the diagram must **not** stay fully ghosted; `activeFilters` drops `"notes"` (reverts to "all") and the chip disables. Same via `clearAllNotes`.
4. **Review panel** — "Review notes" lists every note (correct object name + Table/Join tag + text); clicking a table/join row opens that object **and moves the canvas** (view centered, k≥0.9); inline delete removes the note and updates the panel; empty state shows when no notes. **Stale key (B2):** seed `localStorage` with a note under a key absent from the model, reload, open the panel — the row shows a "not in model" tag, is **not** clickable (no crash), and its delete works.
5. **Edge notes** — a note on a join round-trips (add/save/reload) and appears in the review panel; (edge highlight per §4 if implemented, else documented).
6. **No regressions** — existing filters/focus/minimap/Share-HTML/`clear-notes` unchanged; `clearAllNotes` also re-syncs the Notes chip; 24 pytest green; full pre-commit green.

---

## 8. Rollout
- `feat/erd-notes-ux` off `main`; **no push to main** — PR after Fable CI review.
- Skill MINOR bump 1.6.0 at PR time + root `CHANGELOG.md` entry (repo gate requires it for MINOR); CLI-only skill, no CoCo stage-sync (`agents/shared/erd/` consumed only by `build_erd.py`).
