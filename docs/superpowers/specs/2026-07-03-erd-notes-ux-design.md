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

## 3. Feature A — save/delete feedback + inspector refresh

In `wireNotes(id)` (renderer.js:59–62):
- **On save** (`note-save`): after `persistNotes();renderAll();`, **re-render the inspector for the current object** (`selected.type==="edge" ? showEdge(id) : showTable(id)`) so the Delete button appears and the panel reflects saved state, then show a **transient "Saved ✓" confirmation** (see below). Empty input still deletes (keep `else delete notes[id]`).
- **On delete** (`note-del`): after `persistNotes();renderAll();`, re-render the inspector the same way (textarea returns to empty, Delete button disappears) and show a transient **"Note deleted"** confirmation.
- **Re-sync the "Notes" chip enabled state** (Feature B) after any note change — a note may have just become the first/last one.

Confirmation UI: a small, self-dismissing inline element (e.g. a `.note-saved` span appended next to the Save button, or a lightweight toast) that fades after ~1.5s — no external deps, no layout shift. Prefer appending into the notes button row so it needs no new DOM in `render.py`.

Also: make the Delete button render whenever `notes[id]` is set (already the case) — after Feature A it becomes reachable because the panel refreshes. No change to `notesSection` markup required beyond what's above; if a class is needed for the confirmation span, add it to `renderer.css`.

**Guard:** re-rendering the inspector re-runs `wireNotes`, which re-binds handlers — fine (idempotent). Ensure we don't double-fire: replace the handler bodies rather than adding listeners.

---

## 4. Feature B — highlight objects with notes

Add a **"Notes" filter chip** to the filter row, consistent with the existing chips.

- **render.py:** add `<button class="fchip" data-f="notes">Notes</button>` to `#filter-chips` (after RLS/alias).
- **renderer.js `tableMatchesFilter`:** add `if(activeFilters.has("notes")&&notes[t.id])return true;` so noted tables are the highlighted subgraph (non-matches dim, exactly like the other chips — and this works at LOD because filtering dims/ghosts by node, independent of badges).
- **Edges:** edge notes (`notes[join.name]`) already render amber when present; additionally, when the "notes" filter is active, **keep noted edges emphasized** (don't dim them). Reuse the existing annotated-edge amber; ensure edges connected to the highlight aren't hidden. (If wiring edge-note highlighting is more than a couple of lines, scope the chip to tables and note the edge limitation — tables are the primary case.)
- **Chip enable/disable:** in `loadModel` (renderer.js:758–763) add the `notes` chip → enabled iff `Object.keys(notes).length>0`. Because notes change at runtime, **re-evaluate the notes chip's `disabled` after every save/delete/clear** (call from Feature A's re-sync and from `clearAllNotes`).
- **syncChips / chip-click**: no special-casing needed — the generic handler at :682 already toggles any `data-f`.

At overview/LOD this is now the *only* way to see which tables have notes (badge is hidden there), so it directly answers #3.

---

## 5. Feature C — review all notes

A panel listing every note, rendered in the inspector like `showRlsSubgraph`.

- **Trigger:** repurpose/extend the controls. Add a **"Notes" button** (`id="notes-review-btn"`) next to `clear-notes-btn` in render.py:73–75 (label e.g. "Review notes"). Clicking it calls `showNotesReview()`.
- **`showNotesReview()`** (new, modeled on `showRlsSubgraph` :657): build a list from `notes` — for each key, resolve whether it's a table (`tableById[key]`) or a join (`MODEL.joins.find(j=>j.name===key)`), show the object name (+ a small Table/Join tag) and the note text (escaped, wrapped). Each row is **click-to-jump**: `selectTable(id,false)` / `selectEdge(name)` then re-open its inspector (which now shows the editable note). Include a small **delete** control per row (reuse the delete path, then re-render the panel). Empty state: "No notes yet." with a one-line hint on how to add one. Back button → `showOverview()` (match the RLS panel's back pattern).
- Keep it read-lightweight: no new persistence, just a view over `notes`.

Optional nicety (only if trivial): a note **count badge** on the Review-notes button (e.g. "Review notes (3)").

---

## 6. Files touched

| File | Change |
|---|---|
| `agents/shared/erd/renderer.js` | A: `wireNotes` re-renders inspector + transient confirmation, chip re-sync. B: `tableMatchesFilter` notes case, chip enable/disable + runtime re-sync. C: `showNotesReview()`, wire `notes-review-btn`. |
| `agents/shared/erd/renderer.css` | Confirmation span style; any `.notes-review` list styling. |
| `agents/shared/erd/render.py` | B: `Notes` filter chip. C: `Review notes` button in controls. |
| `agents/cli/ts-object-model-erd/SKILL.md` | `## Changelog` MINOR entry (1.6.0 at PR time) + note the notes highlight/review in the ERD-features list. |

**Complexity:** keep `showNotesReview` and any helper under cc<15; extract a row-builder if needed. Don't inflate `renderNodes`/`renderEdges`.

---

## 7. Verification (headless Chrome; module-scoped state — read DOM)

Build GTM (`/private/tmp/claude-501/-Users-damianwaldron-Dev/45ed40f8-ed5a-4cd3-ae51-f5f2769524fd/scratchpad/export.json`) + mini control. Assert:

1. **Save feedback + Delete appears same-session** — open a table, type + Save: a "Saved ✓" confirmation shows, and the Delete button is present **without** reload. Delete removes it and the textarea clears, still without reload.
2. **Persistence unchanged** — after Save + `page.reload()`, the note text is still in the textarea and `localStorage` (regression guard on the working save path).
3. **Notes chip highlights** — with ≥1 note, clicking the "Notes" chip highlights (does not dim) the noted table(s) and dims the rest; works at fit/LOD zoom (0.12×) too. Chip is **disabled** when no notes exist and **enables** after the first save (and disables again after the last delete/clear) without reload.
4. **Review panel** — "Review notes" lists every note (correct object name + Table/Join tag + text); clicking a row jumps to and opens that object; inline delete removes the note and updates the panel; empty state shows when no notes.
5. **Edge notes** — a note on a join round-trips (add/save/reload) and appears in the review panel; (edge highlight per §4 if implemented, else documented).
6. **No regressions** — existing filters/focus/minimap/Share-HTML/`clear-notes` unchanged; `clearAllNotes` also re-syncs the Notes chip; 24 pytest green; full pre-commit green.

---

## 8. Rollout
- `feat/erd-notes-ux` off `main`; **no push to main** — PR after Fable CI review.
- Skill MINOR bump 1.6.0 at PR time + root `CHANGELOG.md` entry (repo gate requires it for MINOR); CLI-only skill, no CoCo stage-sync (`agents/shared/erd/` consumed only by `build_erd.py`).
