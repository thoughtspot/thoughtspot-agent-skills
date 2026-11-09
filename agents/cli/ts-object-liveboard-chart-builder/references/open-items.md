# Open Items — ts-object-liveboard-chart-builder

Tracks behaviour not yet verified on a live cluster, deferred work, and known gaps.
Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

Everything here is covered offline by the mock-`ts` scenarios in thoughtspot-agent-skills
(`tools/smoke-tests/_liveboard_patch_mock.mjs`); "live" means a real import on a cluster.

The 2026-11-05 live run used ps-internal (ThoughtSpot 26.11.0.cl, Primary org) and a scratch Liveboard
built for it: two spec tabs holding four library charts, to which a native column chart, a note, a copy of a
skill tile on a spec tab and a changed border style (`CURVED` to `SHARP`) were added through TML, as a user's
edits. Every block was printed by `liveboard-pack.mjs` and run through the ThoughtSpot MCP. Backups were
exported with `ts tml export`'s exact request (`formattype: JSON`, `export_fqn: false`) from a signed-in
browser session, as no CLI profile was set up on the machine; `backup-check.mjs` checked each file on disk.

---

## #1 — The write path as shipped, committed on a live Liveboard — VERIFIED 2026-11-05

**What changed since the last live run (2026-10-01, `pipeline.md`):** lean tiles, the backup required for any
Liveboard with visualizations and matched by content fingerprints, a marked tile taken only at its spec position
(`--relayout`), `--adopt` limited to core tiles at their own slug's position, the Liveboard's style kept, and the
pre-commit re-check comparing the whole document.

**Result (ps-internal 26.11.0.cl, 2026-11-05):**
- `--commit --all` on the new, empty Liveboard: `roundTripAllOk: true`.
- With the user's content added, `--validate where-hex-cartogram`: `problems: []` (the slug was marked twice;
  the tile at the spec position was taken, the user's copy kept), `kept: 3`, and `commitWouldRefuse` asking for
  a backup.
- `--commit --backup <file> where-hex-cartogram`: `recheck: unchanged`, `roundTripAllOk: true`. Read back
  afterwards: the border still `SHARP`, the native chart (with its description), the note and the user's copy
  (at its own position) unchanged.
- `--check --all`: `ok: 4`, nothing stale, missing or in conflict.
- A second `--commit --all` run of two blocks with one backup taken before it: both `roundTripAllOk: true`; the
  second block accepted the backup after the first block's import.
- Two exports of the unchanged 50-tile "Amuzing chart samples" Liveboard were byte-identical, so the
  pre-commit re-check does not refuse an untouched Liveboard.

**Which code each result ran on.** Two fixes landed during this run (below, and the fingerprint in #3). The
first commit to the empty Liveboard ran before the `export_fqn` fix (`searches: 3`). Every backup-gated result
above, the one-tile commit (14:35 UTC) and both blocks of the two-block run (14:40 and 14:42 UTC), ran on blocks
that carried both fixes: `export_fqn: true` and the whole-visualization fingerprint without `id`, `viz_guid` and
`fqn`, as committed.

**Found and fixed by this run:** `patch.js` exported without `export_fqn`, so an export carried no table fqn
and a kept tile never matched "the same answer": every block rebuilt every skill tile from a new search,
resetting what a user had set on it (the mock's export always held the fqn). The export now asks for fqns
(`searches: 1` for a one-chart block, where it was 3), and the mock drops them unless asked, as the cluster does.

---

## #2 — Subresource integrity inside a tile — VERIFIED 2026-11-05

**Question:** Does a ThoughtSpot custom-chart tile load a `<script src>` that carries `integrity` and
`crossorigin="anonymous"` from cdn.jsdelivr.net?

**Result (ps-internal 26.11.0.cl, 2026-11-05):** yes. `cluster-shot.mjs` on the scratch Liveboard: five
MayaCharts tiles (`maya.core.global.js` and `maya.global.js`, both with SRI) rendered in their tile frames,
`rendered=2 of 2` and `3 of 3`, `problems=0`, and the PNGs show the charts drawn.

**Found and fixed by this run:** `cluster-shot.mjs` read every MayaCharts tile as blank (`rendered=0`), because
the chart draws inside `<maya-chart>`'s shadow root, which `body.querySelectorAll` and `innerText` do not see.
It now walks shadow roots for marks, nodes and failure texts.

---

## #3 — The backup's fingerprints match the sandbox's export — VERIFIED 2026-11-05

**Question:** A backup is `ts tml export <guid> --format JSON`; the sandbox exports with `edoc_format: 'JSON'`
through the MCP. Is a visualization's fingerprint the same from both?

**Result (ps-internal 26.11.0.cl, 2026-11-05):** on "Amuzing chart samples" (50 visualizations) the CLI's
request body (sent from the sandbox, as no CLI profile existed) and the sandbox's request returned the same
bytes, and every sandbox fingerprint was in the CLI backup. That comparison ran before `patch.js` asked for
fqns: the sandbox's request was then `edoc_format: 'JSON'` without `export_fqn`. With `export_fqn: true` the
two exports differ in the fqns only, so they are no longer the same bytes, and the fingerprint leaves the fqns
out so they still match; the commits in #1 checked that on the final code. The
fingerprint is now the whole visualization (keys sorted) without `id`, `viz_guid` and any `fqn`: `viz_guid` is
a top-level key on 26.11, ThoughtSpot renumbers ids on import, and `patch.js` now exports with fqns while a CLI
backup has none. Every commit in #1 accepted its CLI-format backup.

---

## #4 — 44 MayaCharts library tiles seen on a cluster — DEFERRED 2026-11-05 (BL-552)

The library tiles moved to MayaCharts 0.18.1 render in the preview in every data mode, but carry
`.preview-only` until they have been on a Liveboard and screenshotted (`library.md`). The 2026-11-05 live run
put four of them on a cluster (`pulse-kpi-sales`, `kpi-ring`, `where-state-bubbles`, `where-hex-cartogram`;
all rendered), and those four no longer carry `.preview-only`; 44 still do.

**Action (BL-552, target 2027-01-31):** Rebuild the worked example on a cluster and screenshot every tab.

---

## #5 — Default date filter `LAST_N_PERIOD` with `oper: '='` excludes the current month — DEFERRED 2026-11-05 (BL-552)

Seen on a cluster that `>=` runs up to today and does not exclude the current month; that `=`
does is the intent and has not been confirmed on a screenshot.

**Action (BL-552, target 2027-01-31):** Screenshot a monthly tile with the filter applied in the last days of a
month.
