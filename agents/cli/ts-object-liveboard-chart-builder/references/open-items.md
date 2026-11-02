# Open Items — ts-object-liveboard-chart-builder

Tracks behaviour not yet verified on a live cluster, deferred work, and known gaps.
Status: OPEN | VERIFIED | DEFERRED | WONT-FIX

Everything here is covered offline by the mock-`ts` scenarios in thoughtspot-agent-skills
(`tools/smoke-tests/_liveboard_patch_mock.mjs`); "live" means a real import on a cluster.

---

## #1 — The write path as shipped, committed on a live Liveboard — OPEN

**What changed since the last live run (2026-10-01, `pipeline.md`):** lean tiles, the backup required for any
Liveboard with visualizations and matched by content fingerprints, a marked tile taken only at its spec position
(`--relayout`), `--adopt` limited to core tiles at their own slug's position, the Liveboard's style kept, and the
pre-commit re-check comparing the whole document.

**Action:** On a scratch Liveboard holding a native chart, a note, a user's copy of a skill tile and a changed
border style: `--validate`, `--commit` with a fresh backup, `--check`, then a second `--commit --all` run of
several blocks. Expect `roundTripAllOk: true` each time and the user's content unchanged. Record the cluster
version and date.

---

## #2 — Subresource integrity inside a tile — OPEN

**Question:** Does a ThoughtSpot custom-chart tile load a `<script src>` that carries `integrity` and
`crossorigin="anonymous"` from cdn.jsdelivr.net? The preview (headless Chromium) does; a tile's sandboxed iframe
has not been checked with SRI set.

**Action:** Screenshot one MayaCharts tile from `library/` on a cluster (`cluster-shot.mjs`) and read the PNG.

---

## #3 — The backup's fingerprints match the sandbox's export — OPEN

**Question:** A backup is `ts tml export <guid> --format JSON`; the sandbox exports with `edoc_format: 'JSON'`
through the MCP. The fingerprint (name, search, chart type, decoded chart code, note) should be the same for
both, but they have not been compared on a cluster (the CLI sends `formattype`, the sandbox `edoc_format`).

**Action:** Export one Liveboard both ways and compare `fingerprint()` from `helpers/backup-check.mjs` for every
visualization. A mismatch shows as a refused commit ("the backup ... is not of this Liveboard as it is now"),
never as a silent write.

---

## #4 — 48 MayaCharts library tiles seen on a cluster — OPEN

The library tiles moved to MayaCharts 0.18.1 render in the preview in every data mode, but carry
`.preview-only` until they have been on a Liveboard and screenshotted (`library.md`).

**Action:** Rebuild the worked example on a cluster and screenshot every tab.

---

## #5 — Default date filter `LAST_N_PERIOD` with `oper: '='` excludes the current month — OPEN

Seen on a cluster that `>=` runs up to today and does not exclude the current month (changelog 4.8.0); that `=`
does is the intent and has not been confirmed on a screenshot.

**Action:** Screenshot a monthly tile with the filter applied in the last days of a month.
