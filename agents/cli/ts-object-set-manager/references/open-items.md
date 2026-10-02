# Open Items — ts-object-set-manager

Items that need verification against a live ThoughtSpot instance before the skill is
considered fully verified. Update each item with findings after testing.

Status legend: **VERIFIED** (tested live) | **OPEN** (not yet verified) | **DEFERRED** (decided later, tracked in the backlog)

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

## #4 — Liveboard-filter detection (KEEP_FILTER) — VERIFIED 2026-10-02 for a Liveboard that uses the Set as a filter AND in a viz

Detection matches the Set name in `liveboard.filters[].column[]` (literal, case-insensitive).
No existing Liveboard on se-thoughtspot had a Liveboard-level filter on a Set (spec
Appendix A; #2), so a probe was built, with the user's explicit authorisation, and deleted afterwards.

**Probe.** Liveboard `ZZ Set Filter Probe (delete me)`, created with `ts tml import
--create-new --policy ALL_OR_NONE`, returned GUID `5955975e-…`
(status OK). It has one TABLE_MODE viz modelled on Answer *Testing Share by Edit*
`b7de443c-…` (`tables[].fqn` = Model TEST_SV_DMSI_AI_CONTEXT `889a704f-…`, `search_query:
"[Static Top 10] [Amount]"`), plus a Liveboard filter with `column: [Static Top 10]`. A Set
**can** be a Liveboard filter via TML. The import was accepted on the first attempt.

**Stored form** (TML export of the probe): the plain Set name, with no `Model::` prefix and no column id:

```yaml
filters:
- column:
  - Static Top 10
  is_mandatory: false
  is_single_value: false
  display_name: ''
ordered_chips:
- name: Static Top 10
  type: FILTER
```

`consumers.liveboard_usage` already matches this form, so no code change was needed.
`tests/test_sets_consumers.py::test_filter_block_as_exported_live_is_detected` pins the
exported block verbatim.

| | *Static Top 10* `60a9794b-…` class | Dependents | `liveboards` |
|---|---|---|---|
| BEFORE | `CANDIDATE_ANSWER` ("one Answer") | *Testing Share by Edit* | `{}` |
| AFTER (probe present) | **`KEEP_FILTER`** ("used as a Liveboard filter") | + the probe (`LIVEBOARD`), `dependents_complete: true` | `{5955975e-…: {vizzes: [Viz_1 "Static Top 10 probe"], filter: true}}` |
| After cleanup | `CANDIDATE_ANSWER` ("one Answer") | *Testing Share by Edit* | `{}` |

The other two Sets on the Model kept their classes throughout (*Customer State set*
`CANDIDATE_ANSWER`, *Product Category set* `KEEP_SHARED`).

**Cleanup.** The GUID was re-confirmed (name, type `LIVEBOARD`, author = profile user, created
by this run; a name search before the import returned `[]`). It was then deleted with
`POST /api/rest/2.0/metadata/delete` `{"metadata":[{"identifier":"5955975e-…","type":"LIVEBOARD"}]}`,
which returned **204**. Afterwards, search by GUID and by name returned `[]`.

**Scope of this item.** The probe also used the Set in its viz, so #4 proves detection only
once the Liveboard is fetched as a dependent. Whether a Liveboard that uses the Set *only* as a
filter is listed as a dependent is a separate question — see **#8**.

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

## #7 — Migrate gate — cohort listing for unresolvable / cross-Org / hidden — VERIFIED 2026-10-02

Read-only, se-thoughtspot, admin profile, worktree code via the PATH shim. Only `GET` on the
cohort listing, `POST metadata/search` and `GET auth/session/user`; no `doUpdate`. The question:
does the listing ever answer **200 `[]`** for a GUID that is not a Model visible in the caller's
Org? If it did, `discover_sets` would read "not found" as "0 Sets" and `migrate apply` would pass
a Model it never inspected.

| Probe | Org | Result |
|---|---|---|
| (a) bogus GUID `00000000-0000-0000-0000-000000000000` | Primary | **HTTP 404**, `code 13003`, "Object with Id … of type: LOGICAL_TABLE not found" |
| (b) Answer GUID `b8b5788b-986f-4999-9408-224d88082e3f` | Primary | **HTTP 403**, `code 10003`, `debug: [null]` |
| (c) Dunder Mifflin `829a3344-…` (Primary-owned) | DamianTest `1859868966` (session read back as DamianTest) | **HTTP 404**, `code 13003`, not found; `metadata/search` of the GUID from DamianTest: `[]` |
| (c′) the 17 Models visible in DamianTest (all Primary-owned system/sample Models; DamianTest owns none) | DamianTest | 200 for each. 16 return `[]` from both Orgs. *TS: BI Server* `eaab6de7-…` returns `[]` from DamianTest but **4 Sets from Primary** (*Monthly User Logins*, *First Use*, *uc users set*, *Org Name セット*). `metadata/search` of each of those four Set GUIDs: 1 hit from Primary, **0 from DamianTest** — they are Primary-Org objects, so the per-Org listing is consistent with what that Org can see |
| (d) `showhidden=true` vs `false` | Primary | Dunder Mifflin: 9 Sets either way. **Sweep of all 1,908 Primary Models**: 418 Sets across 108 Models with `false`, 418 with `true`, no Model differs, and no row carries `header.isHidden: true` |
| (e) `ts migrate scan-sets --source-profile se-thoughtspot --source-org DamianTest --all-models` (docstring: read-only) | DamianTest | exit 0; `DamianTest: no Models in scope`; `scanned {orgs: 1, models: 0}`, `summary` all zero, `models_incomplete: 0`, no notes. `--all-models` keeps Models the Org **owns**, and DamianTest owns none |

**Decision rule — not triggered.** Every unresolvable GUID (a, b, c) is an HTTP error. The client
exits on it, `discover_sets` records `discovery_failed`, and the Model is `INCOMPLETE`, so
`migrate apply` refuses it. No resolvability check was added: a `metadata/search` pre-check would
cost a call per Model and guard a case that does not occur on this build.

**`showhidden` — unchanged (`false`).** No difference across 418 Sets, but no hidden Set exists on
the cluster, so this shows only that `false` drops nothing *here*. It does not prove a hidden Set
would be listed. Re-probe if a hidden Set is ever created; switching to `true` is the safe
direction if it turns out to matter.

**Cross-Org reading (c′).** A Model shared into a tenant Org lists only the Sets that Org can see.
That is right for a tenant migration (`apply` and `scan-sets --all-models` only take Models the
Org owns), but a `ts sets inventory --org <tenant>` over a Primary-owned Model reports the
tenant's Sets on it, not Primary's.

## #8 — Filter-only Liveboard listed as a Set dependent — VERIFIED 2026-10-02 (admin profile; cross-Model filter untested)

Split out of #4. The question: when a Liveboard uses a Set **only** as a Liveboard filter, and
no visualization's `search_query`, `answer_columns` or `formulas` reference the Set, does
ThoughtSpot list that Liveboard as a dependent of the Set? If not, the engine would never fetch
it and the Set would read `CANDIDATE_*` or `REVIEW_DELETE` — the unsafe direction.

**Probe** (write probe, user-authorised; se-thoughtspot Primary Org, admin profile, worktree code
via the PATH shim). Liveboard `ZZ Set Filter-Only Probe (delete me)`, created with `ts tml import
--create-new --policy ALL_OR_NONE`, returned GUID `aff4a8a6-…` (status OK, accepted first try).
One TABLE_MODE viz on Model TEST_SV_DMSI_AI_CONTEXT `889a704f-…` whose search does **not**
mention the Set, plus a Liveboard filter on *Static Top 10* `60a9794b-…`:

```yaml
visualizations:
- id: Viz_1
  answer:
    name: "Amount probe"
    tables: [{id: TEST_SV_DMSI_AI_CONTEXT, name: TEST_SV_DMSI_AI_CONTEXT, fqn: 889a704f-…}]
    search_query: "[Amount]"
    answer_columns: [{name: Total Amount}]
filters:
- column: [Static Top 10]
  display_name: ''
  is_mandatory: false
  is_single_value: false
```

The TML export stored the filter exactly as in #4 (`filters: [{column: ["Static Top 10"], …}]`,
`ordered_chips: [{name: Static Top 10, type: FILTER}]`), and the viz's `search_query` stayed
`[Amount]`. So a filter on a Set that no visualization uses **can** be created via TML.

| Check (probe present) | Result |
|---|---|
| Raw v2 dependents of the Set, `LOGICAL_COLUMN` (`_build_dependents_payload`) | 200. `PINBOARD_ANSWER_BOOK`: **the probe** `aff4a8a6-…`; `QUESTION_ANSWER_BOOK`: *Testing Share by Edit* `b7de443c-…`. `hasInaccessibleDependents: true`, `areInaccessibleDependentsReturned: true` (admin; #6) |
| Raw v2 dependents of the Model, `LOGICAL_TABLE` | 200. `PINBOARD_ANSWER_BOOK`: the probe; plus 5 Answers and 5 `FEEDBACK` rows |
| `ts sets inventory --model 889a704f-…` | *Static Top 10* **`KEEP_FILTER`** ("used as a Liveboard filter"), `target: null`, dependents *Testing Share by Edit* (ANSWER) + the probe (LIVEBOARD), `dependents_complete: true`, `liveboards: {aff4a8a6-…: {vizzes: [], filter: true}}` |

| | *Static Top 10* class | Dependents | `liveboards` |
|---|---|---|---|
| BEFORE | `CANDIDATE_ANSWER` ("one Answer") | *Testing Share by Edit* | `{}` |
| AFTER (probe present) | **`KEEP_FILTER`** | + the probe (`LIVEBOARD`) | `{aff4a8a6-…: {vizzes: [], filter: true}}` |
| After cleanup | `CANDIDATE_ANSWER` ("one Answer") | *Testing Share by Edit* | `{}` |

The other two Sets kept their classes throughout. Summary BEFORE and after cleanup identical
(`CANDIDATE_ANSWER` 2, `KEEP_SHARED` 1).

**Cleanup.** A name search before the import returned `[]`. Before deleting, `metadata/search`
by GUID and type `LIVEBOARD` returned exactly one row: the probe's name, type `LIVEBOARD`, author
the profile user, created 2026-10-02 03:11 UTC (this run). Deleted with `POST
/api/rest/2.0/metadata/delete` `{"metadata":[{"identifier":"aff4a8a6-…","type":"LIVEBOARD"}]}`
→ **204**. Afterwards `ts metadata search --guid … --type LIVEBOARD` and a name search both
returned `[]`. No callosum delete and no `doUpdate` were used.

**Result.** A filter-only Liveboard **is** listed as a dependent of the Set, and the engine
classifies the Set `KEEP_FILTER`. Both Liveboard shapes (filter + viz, #4; filter only, #8) are
verified, so the report needs no hand-check for filter-only Liveboards.

Not covered: a non-admin caller (see #6 — BL-327 gate (b)); a Liveboard filter on a Set from a
*different* Model than the Liveboard's vizzes.
