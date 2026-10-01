# Open Items — ts-object-set-manager

Items that need verification against a live ThoughtSpot instance before the skill is
considered fully verified. Update each item with findings after testing.

Status legend: **VERIFIED** (tested live) | **OPEN** (not yet verified)

Fixture cluster: se-thoughtspot. Model *Dunder Mifflin* `829a3344-657c-4d34-918d-84a7438afb59`.

---

## #1 — Per-Model cohort listing — VERIFIED 2026-10-02

Read-only, with the v2 bearer token:
`GET /callosum/v1/metadata/detail/{model}?type=LOGICAL_TABLE&showhidden=false&dropquestiondetails=false&fetchcohortcolumnsonly=true`
(no `doUpdate`). Source: Confluence SAGE/4309319694.

- Dunder Mifflin: **200, 1.7s, 9 Sets**, 3 with a blank header `type`, all carrying
  `cohortConfig` — so membership is decided by `cohortConfig`, never by `type`.
- TEST_SV_DMSI_AI_CONTEXT: 0.3s, 3 Sets.

The paged `LOGICAL_COLUMN` search is ruled out: it did not finish in 2h45m (>144k rows,
page latency linear in offset). See spec Appendix A.

The endpoint is private and undocumented: a 404 on a newer build means it moved, and every
Model then reads `INCOMPLETE` with a `discovery_failed` note.

## #2 — Liveboard visualization detection — OPEN

Detection matches `[Set Name]` (literal, case-insensitive) in each visualization's
`search_query`, its `formulas[].expr`, and `answer_columns[].name`.

Fixture: Liveboard *Formula LB - SC* `da4f1be1-b6cd-47a2-84bd-f8cffe1d0696`, whose `Viz_2`
(viz_guid `a3c94a83-e5b5-4e55-a27a-936652429b25`) uses Set *Top Brands*
`69f6aed0-503f-4ded-87b2-bac3ffe391af` in `search_query`. Expected: *Top Brands* lists the
Liveboard with `Viz_2` as its visualization. To verify live in Task 12.

## #3 — Liveboard / Answer author as owner (REQUIRED) — OPEN

Dependents report `author`; provenance treats the author as the owner, so the author's view
grant on the Set reads `REQUIRED`. Verify against an object whose owner changed after
creation.

## #4 — Liveboard-filter detection (KEEP_FILTER) — OPEN

Detection matches the Set name in `liveboard.filters[].column[]`. No live fixture exists:
none of the six Set-using Liveboards exported on se-thoughtspot (spec Appendix A) has a
Liveboard-level filter on a Set. `KEEP_FILTER` is covered by unit tests only. Verify once a
Liveboard with a Set filter is available.

## #5 — Dependents response with no item for the Set — OPEN

When the dependents response carries no item for the Set's GUID, the engine reads it as "no
dependents" (and so `REVIEW_DELETE`). Confirm that is what the API means rather than a
silent failure. Verify on *Product Basket 1* `cf2d7861-9417-4b1d-845a-8f70eb0f0270`, which
had no dependents in Appendix A, in Task 12.
