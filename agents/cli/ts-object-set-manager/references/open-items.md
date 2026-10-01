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

## #2 — Liveboard visualization detection — VERIFIED 2026-10-02

Detection matches `[Set Name]` (literal, case-insensitive) in each visualization's
`search_query`, its `formulas[].expr`, and `answer_columns[].name`.

**Original fixture is gone.** Liveboard *Formula LB - SC* `da4f1be1-b6cd-47a2-84bd-f8cffe1d0696`
no longer exists on se-thoughtspot: `metadata/search` by GUID returns nothing, a name search
for `%Formula LB%` returns nothing, and TML export answers 400 / 10002 "Specified identifier
doesn't exist". Set *Top Brands* `69f6aed0-…` is still there (Model *Retail Sales - RP*
`e2806e7c-87d3-44b7-b230-69efb6183045`), and its raw v2 dependents are now empty
(`dependents: {<set>: {}}`, `hasInaccessibleDependents: false`). `ts sets inventory` reads it
as `REVIEW_DELETE`, which is consistent with what the API now returns.

Verified on two other fixtures instead, one per match path:

| Path | Set (Model) | Liveboard | Result |
|---|---|---|---|
| `search_query` + `answer_columns` | *Promotion Id set* `223a23fc-f5af-4460-908f-e72a9257000e` (Model *Just Eat v3* `8b07b2bc-…`) | *Just Eat v3* `73df2a30-e378-44c3-a113-00f269717d19`, plus *Luke Copy of Just Eat v3* `ee7f0be1-…` and *Food Supy Liveboard* `de54cbe2-…` | All three listed, each with `Viz_7` *Promotion Impact on AOV* (`average [Order Revenue] [Promotion Id set]`), `filter: false` |
| `formulas[].expr` | *mytop5* `3fbe9ac6-…`, *mytop10* `8c1cbe6e-…` (Model *Paul - Snowflake Retapp* `5bb6feec-…`) | *Dynamic Set Selection* `eb3871ab-c026-4459-ad2e-aad002cc7f3b` | Both Sets list it with `Viz_1` *Total Sales by fx*, `filter: false` |

**Divergence (class, not detection) — resolved by #6.** All four Sets above classified
`REVIEW_MANUAL`, because their dependents response carries `hasInaccessibleDependents: true`.
After the #6 fix (2026-10-02) *mytop5* / *mytop10* classify `CANDIDATE_VIZ` (one
visualization), as the dependents imply.

## #3 — Liveboard / Answer author as owner (REQUIRED) — VERIFIED 2026-10-02

Dependents report `author`; provenance treats the author as the owner, so the author's view
grant on the Set reads `REQUIRED`.

Checked on *Advanced Basket Analysis* `b8b5788b-986f-4999-9408-224d88082e3f` and *Basket
Analysis* `4ab96c01-87e9-46ba-994a-3689eb85ffef` (dependents of *Product Basket 2* / *PC*).
The dependents item's `author` (`1401d07c-…`, pinelopi.chamalelli) **equals** the Answer's own
`metadata/search` header `author` / `authorName`. The header `owner` field is **not a user**:
on an Answer it is the Answer's own GUID (`owner == metadata_id` on both). So `author` is
the only user-valued owner field ThoughtSpot exposes, and reading it as owner is correct.

Not exercised live: (a) an object whose ownership was transferred (*Advanced Basket
Analysis* has a different `modifiedBy`, but that is an edit, not a transfer); (b) a
`REQUIRED` label itself — every consumer author on the fixtures holds `MODIFY` on the Set,
so `DIRECT` wins first. `REQUIRED` stays covered by unit tests.

## #4 — Liveboard-filter detection (KEEP_FILTER) — OPEN

Detection matches the Set name in `liveboard.filters[].column[]`. No live fixture exists:
none of the six Set-using Liveboards exported on se-thoughtspot (spec Appendix A) has a
Liveboard-level filter on a Set, and none of the four checked on 2026-10-02 (#2) does either
(`filter: false` on all; *Just Eat v3* `filters: []`). `KEEP_FILTER` is covered by unit tests
only. Deferred to v2 / a built fixture.

## #5 — Dependents response with no item for the Set — VERIFIED 2026-10-02

Raw v2 dependents (`_build_dependents_payload([guid], "LOGICAL_COLUMN")`) for *Product
Basket 1* `cf2d7861-9417-4b1d-845a-8f70eb0f0270`, which has no dependents, returns **one item
for the Set, with an empty bucket map**, not a missing item:

```json
[{"metadata_id": "cf2d7861-…", "metadata_type": "LOGICAL_COLUMN",
  "dependent_objects": {"dependents": {"cf2d7861-…": {}},
                        "hasInaccessibleDependents": false,
                        "areInaccessibleDependentsReturned": false}}]
```

Same shape for *Top Brands* (#2). So "no dependents" is an explicit empty result, and reading
it as `REVIEW_DELETE` is what the API means. A response with **no** item for the Set was not
observed; the engine still reads that as no dependents, which remains unverified.

## #6 — `hasInaccessibleDependents` with `areInaccessibleDependentsReturned` — VERIFIED 2026-10-02 (fixed)

Found 2026-10-02. The engine (`ts_cli/sets/consumers.py`) treats
`hasInaccessibleDependents: true` as "some dependents hidden", so the Set reads
`REVIEW_MANUAL` and its grants `UNKNOWN`/uncertain. For an admin caller the response also
carries `areInaccessibleDependentsReturned: true`, meaning the hidden dependents **were**
returned. Raw evidence: *Product Basket 2* `4f39eea6-…` and *PC* `cad1b0d6-…` both carry
`hasInaccessibleDependents: true, areInaccessibleDependentsReturned: true` with their full
Answer lists (1 and 2). Effect on se-thoughtspot (admin profile): the smoke fails (PB2 and PC
read `REVIEW_MANUAL`, expected `CANDIDATE_ANSWER` / `KEEP_SHARED`); every Set with a dependent
on the fixtures checked reads `REVIEW_MANUAL`; `ts audit` H5 skips those Sets with a warning.
A scratch counterfactual that clears the flag in that case restores every expected class.
Routed to the controller; not fixed in Task 12.

**Fixed 2026-10-02 (ruling R17, commit `3e6518a`).** `fetch_consumers` now treats dependents
as hidden only when some item has `hasInaccessibleDependents: true` **and**
`areInaccessibleDependentsReturned` is not `true` (missing counts as not true). Unit tests in
`tests/test_sets_consumers.py` cover both-true (no error, dependents listed), returned=false
(error) and returned missing (error); `tests/test_audit_context.py` runs the real
`fetch_consumers` through `build_context` to show H5 now records such Sets.

Live re-verification, same admin profile, read-only:
- Smoke on Dunder Mifflin: **PASS** — PB1 `REVIEW_DELETE`, PB2 `CANDIDATE_ANSWER`, PC `KEEP_SHARED`.
- TEST_SV_DMSI_AI_CONTEXT: *Static Top 10* and *Customer State set* `CANDIDATE_ANSWER`,
  *Product Category set* `KEEP_SHARED`, all `dependents_complete` true.
- *Paul - Snowflake Retapp*: *mytop5* / *mytop10* `CANDIDATE_VIZ`.
- `ts audit run --angles H` on Dunder Mifflin: no `hasInaccessibleDependents` warnings; Sets
  with dependents are recorded and not flagged.

Still unobserved: a non-admin caller, for whom `returned` should be false and the error should
fire. The unit test pins that branch; no live non-admin run was made.
