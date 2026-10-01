# ts-object-set-manager — design (v1: report only)

**Date:** 2026-10-01
**Status:** approved; implemented
**Branch:** `feat/ts-object-set-manager`
**Backlog:** BL-324 (Model dependents omit Sets), BL-325 (`scan-sets` discovery), BL-326 (Set
MODIFY without Model access — parked), BL-327 (v2 actions), BL-328 (connection scope — parked),
BL-302 (H5 orphan sets — closed by this work)

---

## 1. Intent

A simple, repeatable process to manage reusable **Sets** (cohorts) on ThoughtSpot Models: see
what exists, decide what to clean up, and — in v2 — act on it safely.

**v1 is report only.** It changes nothing on the cluster. The fast follow (v2, BL-327) adds the
actions.

### Requirements (from the user)

1. Count the reusable Sets on each Model.
2. For each Set, report whether it has zero, one or many dependents.
3. Zero dependents → a **review list** for deletion, never an automatic delete. A Set used only
   in unsaved ad-hoc searches has no recorded dependent and may still have value.
4. One dependent → a candidate to become answer-level. A Liveboard visualization is a **copy**
   inside the Liveboard TML (ThoughtSpot does not pin by reference), so a Liveboard dependent
   means finding the visualization that uses the Set. **A Set used as a Liveboard filter must
   remain reusable.**
5. For reusable Sets, report the current sharing.
6. Changing sharing — deferred. Granting **edit** on a Set is **parked** by the user (known
   cause; BL-326).

### Success

For a chosen scope, one report showing per Model: each reusable Set, its dependents, its class
(§4) and the provenance of every grant on it (§5) — with every degraded or skipped object named
rather than dropped.

---

## 2. What live probing established (se-thoughtspot, 2026-09-30)

These findings shape the design. Several contradict what existing repo code assumes.

| # | Finding | Consequence |
|---|---|---|
| F1 | A Model's v2 dependents **do not list its Sets** — no `COHORT` bucket returned for a Model owning three | Discovery cannot use Model dependents. `ts-audit`'s Set discovery (and so H5) finds nothing → BL-324 |
| F2 | A Set is a `LOGICAL_COLUMN` owned by its Model; `metadata_header.type` was **blank on 2 of 3 Sets** (only the newest read `COHORT_ADVANCED`) | Never classify by `type`. `sets_scan.is_cohort_row` misses these → BL-325 |
| F3 | One cluster-wide `LOGICAL_COLUMN` search **timed out** (60s × 3) | Discovery must page, per Org, with a bounded fallback → BL-325 |
| F4 | `metadata/search` rejects `subtypes: [COHORT_*]` (not in `SearchMetadataSubtype`) | No server-side Set filter; filter by `owner` client-side, confirm by TML export (root `cohort:`) |
| F5 | A Set's dependents require `--type LOGICAL_COLUMN`; the default `LOGICAL_TABLE` returns 0 | Always pass the type |
| F6 | Grants on a Set read back from `security/metadata/fetch-permissions` as `metadata_type: COLUMN` | Read grants per Set as `LOGICAL_COLUMN` |
| F7 | Sharing an Answer (view **or** edit) writes an explicit **view-only** DEFINED grant on each reusable Set it uses — to the same principal. Never edit. No cascade to the Model | Copied grants are indistinguishable from direct ones in the API; provenance must be reconstructed (§5) |
| F8 | Unsharing the Answer **does not** remove the copied Set grant (a Set serves many Answers) | Set grants only accumulate → stale grants are a real class (§5 `UNEXPLAINED`) |
| F9 | To use a Set in an Answer you must already own it with edit, or hold view on it (user, product knowledge) | An Answer owner's grant on the Set is a **precondition**, not a copy (§5 `REQUIRED`) |
| F10 | Several principals can hold edit on a Set (one share call, read back) — but a non-admin with Set edit and no Model access gets a generic error on save | Edit is not usable on its own; parked (BL-326). v1 reports edit grants as-is and does not judge them |
| F12 | (2026-10-02) A cluster-wide paged `LOGICAL_COLUMN` search did not finish in 2h45m on se-thoughtspot (>144k rows; page latency linear in offset — Appendix A). The internal per-Model listing `GET /callosum/v1/metadata/detail/{model}?type=LOGICAL_TABLE&fetchcohortcolumnsonly=true` (Confluence SAGE/4309319694) returns every Set on a Model in 0.3–1.7s with the v2 bearer token; blank-`type` Sets still carry `cohortConfig` | **Discovery uses the per-Model listing.** Membership = presence of `cohortConfig`. Private/undocumented endpoint: a 404 means the build moved it |
| F11 | `EFFECTIVE` permissions on se-thoughtspot list ~115 users with MODIFY on everything | Provenance uses `DEFINED` grants only; `EFFECTIVE` is useless on admin-heavy clusters |

---

## 3. Architecture

A new **`ts sets`** CLI command group holds all deterministic logic; the skill is a thin
interactive layer over it. Chosen over (B) a Sets angle inside `ts audit` — an inventory with
per-Set detail does not fit the audit's findings model, and v2 actions do not belong in a
read-only skill — and over (C) a skill-only composition of existing commands, which would leave
the Set × dependent × visualization × grant joins to the LLM (the angle-11 "agentic →
deterministic" anti-pattern).

### 3.1 Commands

| Command | Does | Output |
|---|---|---|
| `ts sets inventory` | Resolve scope → Models; discover reusable Sets; fetch dependents; inspect Liveboard dependents; read grants; classify | `sets-inventory.json` (stdout, or `-o <path>`) |
| `ts sets report <inventory.json>` | Render the inventory | `report.html` (self-contained) + `report.md` (`-o <dir>`) |

`inventory` scope flags — combinable, de-duplicated by Model GUID:

| Flag | Meaning |
|---|---|
| `--model <guid\|exact name>` | Repeatable |
| `--model-contains <text>` | Repeatable; case-insensitive substring (e.g. `DUNDER`) |
| `--org <name\|id>` | Repeatable; every Model in that Org |
| `--all-orgs` | Cluster scope: every Org in turn |
| `--dry-run` | Resolve scope only; print Models matched per Org and a run-time estimate; no Set scan |

Plus the standard `--profile`. JSON on stdout, diagnostics on stderr, per `.claude/rules/ts-cli.md`.

**Connection scope is parked** (BL-328). When it returns it resolves connection → tables →
Models (Models carry no connection field; see `ts-audit` Step 3).

### 3.2 Engine — `tools/ts-cli/ts_cli/sets/`

Pure functions, unit-testable with no live cluster. `commands/sets.py` is the only I/O layer.

| Module | One job | Depends on |
|---|---|---|
| `scope.py` | Selectors → de-duplicated `[{org, model_guid, model_name}]` | — |
| `discover.py` | Model → reusable Sets: one per-Model cohort listing call (F12); membership by `cohortConfig`, never by `type` (F2) | — |
| `consumers.py` | Set → dependents (`LOGICAL_COLUMN`, F5). For each Liveboard dependent: the visualizations whose `search_query`, `answer_columns[].name` or `formulas[].expr` reference `[Set Name]` (literal, case-insensitive), and whether any `liveboard.filters[].column[]` names it. Only the response item whose `metadata_id` is the Set, with a dict under that GUID in `dependent_objects.dependents`, is read; anything else (`[]`, no map, another GUID) sets `error`. Dependents are hidden — `error`, visible dependents still listed — only when `hasInaccessibleDependents` is true and `areInaccessibleDependentsReturned` is not true (R17); a Liveboard export that fails or is not Liveboard TML goes to `unreadable` | — |
| `classify.py` | Set + consumers → class (§4) | `consumers` output |
| `grants.py` | DEFINED grants on the Set + grants and owners of its consumers → provenance per grant (§5) | `consumers` output |
| `render.py` | Inventory JSON → HTML + Markdown | — |

### 3.3 Shared-code consolidation

- `migrate/sets_scan.py` switches its discovery to `sets/discover.py`. This fixes F2/F3 for the
  Org-migration gate too (BL-325), where a missed Set means a lift-and-shift silently drops it.
- `ts-audit`'s `check_h5` consumes Set dependents produced the same way, closing BL-302.

### 3.4 Skill — `agents/cli/ts-object-set-manager/`

Family `ts-object-*` (type `set`). Precedent for a skill spanning many instances of one type:
`ts-object-model-coach`. CLI-only (§7).

---

## 4. Set classification

First matching rule wins. The order is deliberate: uncertainty is resolved before any
"candidate" verdict, so a Set is never marked convertible on incomplete evidence.

| # | Class | Rule | Report says |
|---|---|---|---|
| 1 | `KEEP_FILTER` | Used in any Liveboard filter | Must stay reusable |
| 2 | `REVIEW_MANUAL` | Any dependent could not be inspected (export FORBIDDEN/failed), or is a type other than Answer/Liveboard | Cannot classify — reason given |
| 3 | `KEEP_SHARED` | 2+ dependent objects, or one Liveboard with 2+ visualizations using it | Reusable is correct |
| 4 | `CANDIDATE_ANSWER` | Exactly one dependent, an Answer | Could become answer-level (v2) |
| 5 | `CANDIDATE_VIZ` | Exactly one dependent, a Liveboard, exactly one visualization using it, no filter use | Could move into that visualization (v2) — named by viz id and title |
| 6 | `REVIEW_DELETE` | Zero dependents | Delete candidate — check ad-hoc use first |

---

## 5. Grant provenance

For each principal with a DEFINED grant on a reusable Set. Matching is by **same principal**
(F7 copies group → group); group membership is not expanded. First matching rule wins —
`REQUIRED` is tested before `EXPLAINED` so a principal who owns any consumer is always
protected.

| Provenance | Rule | v2 revocation |
|---|---|---|
| `DIRECT` | Edit (MODIFY) — includes the Set's author | Never offered |
| `REQUIRED` | View, and the principal **owns** an Answer or Liveboard that uses the Set (F9) | Never offered — revoking breaks their content |
| `EXPLAINED` | View, and the principal holds a grant on a consuming Answer or Liveboard (F7) | Not recommended |
| `UNEXPLAINED` | View, and the principal neither owns nor was granted any consumer | Review candidate — caveat: possible ad-hoc use |
| `UNKNOWN` | Grants could not be read for this Set | — (scan note) |

A user whose access is explained only via a group they belong to reads as `UNEXPLAINED`. This
is deliberately conservative: it puts a grant in front of a reviewer rather than hiding it.

---

## 6. Report and skill flow

### 6.1 Report

| View | Content |
|---|---|
| Summary | Per scope: Models scanned, reusable Sets, count per class, `UNEXPLAINED` grants |
| Per Model | One row per Set: name, column vs query Set, anchor column, author, dependent count, class, v2 next action |
| Set detail (expandable) | Dependents — Answers; Liveboards with the visualizations and filters using the Set — and the grant table with provenance |
| Review lists | `REVIEW_DELETE` Sets and `UNEXPLAINED` grants; clipboard copy. Never contains a `REQUIRED` grant |
| Scan notes | Every skipped or degraded object by name, from the top-level and per-Org `notes[]`: `discovery_failed`, `unrecognised_row`, `dependents_failed`, `export_unreadable`, `unrecognised_dependent`, `grants_unreadable`, `org_skipped` |

### 6.2 Skill steps

| Step | Action | Mode |
|---|---|---|
| 0 | Overview; state that v1 changes nothing | confirm |
| 1 | Authenticate (`ts auth whoami`) | auto |
| 2 | Scope: Models (guid / name / contains) · Org · Cluster | user |
| 3 | `ts sets inventory --dry-run` → Models matched + estimate. Contains-matches always listed; Org/Cluster always confirmed | confirm |
| 4 | `ts sets inventory -o ~/Dev/audit-runs/{profile}-sets-{date}/sets-inventory.json` | auto |
| 5 | `ts sets report … -o ~/Dev/audit-runs/{profile}-sets-{date}/`; open the HTML | auto |
| 6 | Walk-through: headline numbers, review lists, scan notes. Point each class to what exists today (`/ts-dependency-manager` for deletes, `ts share` for grants) and say v2 will act | review |

---

## 7. Error handling

**Rule: a failure makes the report less certain, never more favourable.**

| Situation | Behaviour |
|---|---|
| A Model's cohort listing fails or returns a non-list | That Model is `INCOMPLETE` with `set_count: null` and a scan note. Never report "0 Sets" for a failed lookup |
| A dependent's TML unreadable | Set → `REVIEW_MANUAL` with reason |
| Grants unreadable | Provenance `UNKNOWN` for that Set; scan note; classification unaffected |
| A selector matches nothing | Error before any scan |

---

## 8. Testing

- **Unit** — `tools/ts-cli/tests/test_sets_*.py`, recorded fixtures: blank-`type` Sets (F2);
  every class and the precedence between them; filter use overriding single use; the five
  provenance labels with `REQUIRED` beating `EXPLAINED`; scope de-duplication across
  overlapping selectors.
- **Gate tests** — `REVIEW_MANUAL` fires when a dependent export fails; the `UNEXPLAINED` review
  list never contains a `REQUIRED` grant; a timed-out page never yields "0 Sets".
- **Smoke** — `tools/smoke-tests/smoke_ts_object_set_manager.py` against se-thoughtspot,
  Model **Dunder Mifflin** (`829a3344-657c-4d34-918d-84a7438afb59`). Expected:

  Dunder Mifflin owns **9** Sets (Appendix A, 2026-10-02); the three below have known classes:

  | Set | Dependents | Class |
  |---|---|---|
  | Product Basket 1 | 0 | `REVIEW_DELETE` |
  | Product Basket 2 | 1 Answer (Advanced Basket Analysis) | `CANDIDATE_ANSWER` |
  | Product Basket PC | 2 Answers | `KEEP_SHARED` |

  Each Set's only grant (its author, MODIFY) reads `DIRECT`. These are the post-cleanup
  baseline; the smoke must re-derive rather than hard-code if the fixture drifts.

- **First live checks in the plan** — done 2026-10-01/02, Appendix A: paged discovery infeasible
  (→ F12); Liveboard fixture *Formula LB - SC* `da4f1be1-b6cd-47a2-84bd-f8cffe1d0696` (`Viz_2`, Set
  *Top Brands*); Sets are also referenced inside viz formulas; no Liveboard-filter fixture found.
  > **Note (2026-10-02):** *Formula LB - SC* has since been deleted from se-thoughtspot (search
  > by GUID and by name returns nothing; TML export 400/10002). Open item #2 was verified on
  > *Just Eat v3* (`search_query`, `Viz_7`) and *Dynamic Set Selection* (formula, `Viz_1`)
  > instead — see Appendix B. The citation above is left as the historic record.

---

## 9. Repo obligations

Per the root `CLAUDE.md` change-impact map:

- `README.md` skills table; `agents/cli/SETUP.md` symlink step; skill `## Changelog` at 1.0.0
- `CHANGELOG.md` — new skill; ts-cli version bump
- `tools/validate/check_runtime_coverage.py` `EXPECTED_DIVERGENCES` — CLI-only: Set management
  is not part of the Snowflake conversion pipeline
- `tools/ts-cli/README.md` for `ts sets`; bump `__init__.py` + `pyproject.toml`
- `agents/cli/ts-audit/references/check-catalog.md` (H5); `agents/cli/ts-dependency-manager/references/dependency-types.md`
  (Set discovery note)
- `docs/backlog.md` — BL-324…BL-328 filed with this spec

---

## 10. Out of scope (v1)

| Item | Where |
|---|---|
| Delete `REVIEW_DELETE` Sets; convert `CANDIDATE_*` to answer-/viz-level; revoke `UNEXPLAINED` grants | BL-327 (v2). Conversion depends on ts-dependency-manager open items #14 (`pass_thru_filter` lost on round-trip) and #16 (Set + Answer import ordering); delete depends on #11 |
| Granting edit on Sets | BL-326 — parked by the user |
| Connection scope | BL-328 — parked |
| Answer-level Set inventory (`answer.cohorts[]`) | Not requested; v1 covers reusable Sets only |

---

## Appendix A — live checks (2026-10-01)

Read-only probes on se-thoughtspot (Primary Org). The probe scripts were throwaway and are not committed.

| Check | Result |
|---|---|
| Paged `LOGICAL_COLUMN` search, page size 500 | **Did not finish.** At least **144,000 rows** (offsets 0–143,500, every page full) seen across **2h45m** of page time (0–76,000: 2,659s; 76,000–144,000: 7,198s) before the 2h background cap stopped it. No HTTP errors and no client timeouts at 120s. **Page latency grows linearly with offset:** ~4.7s at offset 0, ~17s at 50k, ~30s at 75k, ~55s at 110k, 71–86s at 140k+. The slowest page took 85.8s, so the 120s timeout would trip soon after. In the first 76,000 rows: 4,580 distinct `owner` values. 63 rows read `metadata_header.type` `COHORT_*` (44 ADVANCED, 19 SIMPLE), a lower bound because of F2 |
| Where Dunder Mifflin's columns sit | All 34 rows owned by `829a3344-…` were at offset > 76,000. None were in the first 76,000. Default ordering is therefore no shortcut |
| Dunder Mifflin Sets (full GUIDs) | `cf2d7861-9417-4b1d-845a-8f70eb0f0270` *Product Basket 1* (`COHORT_ADVANCED`); `4f39eea6-c51e-498a-8acc-fad2f5f58249` *Product Basket 2* (type **blank**); `cad1b0d6-3db6-4076-8595-b939e9b13b00` *Product Basket PC* (type **blank**). Re-confirms F2. The same Model also owns `COHORT_ADVANCED` rows *QS - Maximum tableDate*, *QS - Minimum tableDate*, *QS - Min Quantity*, *Ranked Products* and *Basket Analysis Set For Insights Hour*. Blank-type candidates such as *Ranked Products By Region* need a TML check |
| Per-Model route (`metadata/search` of the Model, `LOGICAL_TABLE`, `include_details`) | 200, 109,778 bytes, 2.0s. **None of the three Set GUIDs appear.** `metadata_detail.columns` has 25 entries, all physical/formula columns. No key mentions `cohort`. The route is **ruled out**, alongside v2 Model dependents and v1 `dependency/logicaltable` |
| `sort_options` `CREATED`/`MODIFIED` `DESC` on `LOGICAL_COLUMN` search | Honoured, and fast at low offsets (~2–3s per 500 page). It finds only *recent* Sets: none of Dunder Mifflin's were created after 2026-09-28. Not a discovery route |
| Set → dependents (`--type LOGICAL_COLUMN`) | `cf2d7861` none; `4f39eea6` ANSWER×1; `cad1b0d6` ANSWER×2; `60a9794b` *Static Top 10* ANSWER×1 (*Testing Share by Edit*); `b929a421` *QS - Minimum tableDate* ANSWER×1 **+ SET×1** (a Set depending on a Set). None of these has a LIVEBOARD dependent |
| Liveboard using a Set | **Found, no build needed.** Fixture: **`da4f1be1-b6cd-47a2-84bd-f8cffe1d0696` *Formula LB - SC*** (3 vizzes). `Viz_2` (viz_guid `a3c94a83-e5b5-4e55-a27a-936652429b25`) uses Set `69f6aed0-503f-4ded-87b2-bac3ffe391af` *Top Brands* in `search_query` (`… top [Top Brands]`). Liveboard filter on the Set: **no**. Alternate with two Sets: `eb3871ab-c026-4459-ad2e-aad002cc7f3b` *Dynamic Set Selection*, `Viz_1` (viz_guid `a79d5565-…`), which references Sets *mytop5* `3fbe9ac6-…` and *mytop10* `8c1cbe6e-…` inside a viz formula and not in `search_query`. Filter: no. Other Set-using Liveboards: *Just Eat v3* `73df2a30-…` (`Viz_7`, *Promotion Id set*) plus 3 copies; *Aditi D's Demo Retail Liveboard* `2d3898fb-…` (`Viz_33`); *Demo fis lib* `9d0f02cf-…` (`Viz_18`, `Viz_22`); *PM Condor* / *easyJet InFlight Retail Analysis* (*Promotion Type set*). **None of the 6 exported had a Liveboard-level filter on a Set**, and none carried `answer.cohorts` for a reusable Set: reuse shows only as `[Set Name]` in `search_query`/columns or inside a formula |
| Per-Model cohort listing (2026-10-02) | `GET /callosum/v1/metadata/detail/{model}?type=LOGICAL_TABLE&showhidden=false&dropquestiondetails=false&fetchcohortcolumnsonly=true` (no `doUpdate`), v2 bearer token: **200**. Dunder Mifflin 1.7s → 9 Sets (QS - Min Quantity, QS - Minimum tableDate, QS - Maximum tableDate, Ranked Products, Ranked Products By Region, Basket Analysis Set For Insights Hour, Product Basket 1/2/PC; 3 with blank `type`, all with `cohortConfig`). TEST_SV_DMSI_AI_CONTEXT 0.3s → 3 (Static Top 10, Customer State set, Product Category set `SIMPLE/GROUP_BASED`). Source: Confluence SAGE/4309319694 |

> **Note (2026-10-02):** the *Formula LB - SC* fixture in the "Liveboard using a Set" row above has since been deleted
> from se-thoughtspot. Open item #2 was verified on *Just Eat v3* (`search_query`, `Viz_7`) and
> *Dynamic Set Selection* (formula, `Viz_1`) — see Appendix B. The row is kept as the historic record.

**Consequences for Task 2.** A cluster-wide paged scan is not viable on se-thoughtspot. It runs for hours, and late pages approach the 120s timeout. The `INCOMPLETE` fallback is therefore the *normal* path on this cluster, not an edge case. Discovery needs a narrower scope: per Org, as F3 already says, or per Model owner. There is no confirmed server-side way to filter `LOGICAL_COLUMN` by owner yet (not probed here).

---

## Appendix B — live verification (2026-10-02)

Read-only, se-thoughtspot Primary Org, admin profile, worktree code via a PATH shim.

| Check | Result |
|---|---|
| Smoke (`smoke_ts_object_set_manager.py`, Dunder Mifflin) | **FAIL.** auth, inventory PASS; 9 Sets. *Product Basket 1* `REVIEW_DELETE` as expected; *Product Basket 2* and *PC* `REVIEW_MANUAL` (expected `CANDIDATE_ANSWER` / `KEEP_SHARED`) because their dependents carry `hasInaccessibleDependents: true` alongside `areInaccessibleDependentsReturned: true` (open item #6) |
| `--model-contains DUNDER` | 5 Models matched (dry run and full); 14 Sets, `REVIEW_DELETE` 11 / `REVIEW_MANUAL` 3, 0 incomplete, 0 unexplained, 0 unknown grants; ~15s. `report.html` and `report.md` written. *Static Top 10* not in scope |
| Provenance, TEST_SV_DMSI_AI_CONTEXT | *Static Top 10*: michelle `DIRECT`, damian `DIRECT`, ashok `DIRECT` (all MODIFY). The other two Sets: damian `DIRECT`. All three Sets `REVIEW_MANUAL` (#6) |
| Liveboard viz detection (#2) | Fixture *Formula LB - SC* no longer exists; *Top Brands* now has 0 dependents → `REVIEW_DELETE`. Verified instead on *Just Eat v3* (`search_query`, `Viz_7`, 3 Liveboards) and *Dynamic Set Selection* (formula, `Viz_1`, *mytop5* / *mytop10*) |
| Empty dependents (#5) | One item for the Set with an empty bucket map `{}`, not a missing item |
| Author as owner (#3) | Dependents `author` = Answer header `author`; header `owner` is the Answer's own GUID |
| `ts audit run --angles H`, Dunder Mifflin | H5 flags exactly the 6 `REVIEW_DELETE` Sets incl. *Product Basket 1*; no Set with dependents flagged; 3 Sets skipped with a warning (#6). **But 18 findings for 6 Sets**: each Set is emitted once per source that lists it (the Model plus each underlying Table's `COHORT` bucket). No H4 finding |
| **After fix** — smoke, Dunder Mifflin (R17/R18, commit `3e6518a`) | **PASS.** 9 Sets. *Product Basket 1* `REVIEW_DELETE`, *Product Basket 2* `CANDIDATE_ANSWER`, *PC* `KEEP_SHARED`. *QS - Minimum tableDate* stays `REVIEW_MANUAL`: its only dependent is another Set (*QS - Min Quantity*), which is the intended R5 outcome, not #6 |
| **After fix** — `--model-contains DUNDER` | 5 Models, 14 Sets: `REVIEW_DELETE` 11 / `CANDIDATE_ANSWER` 1 / `KEEP_SHARED` 1 / `REVIEW_MANUAL` 1 (the Set-on-Set case above); 0 incomplete, 0 unexplained, 0 unknown grants. Report written |
| **After fix** — TEST_SV_DMSI_AI_CONTEXT `889a704f-…` | 3 Sets, all `dependents_complete` true: *Static Top 10* `CANDIDATE_ANSWER` (1 Answer), *Customer State set* `CANDIDATE_ANSWER` (1 Answer), *Product Category set* `KEEP_SHARED` (2 Answers) |
| **After fix** — *Paul - Snowflake Retapp* | *mytop5*, *mytop10* `CANDIDATE_VIZ` (one viz each on *Dynamic Set Selection*), matching the #2 counterfactual |
| **After fix** — `ts audit run --angles H`, Dunder Mifflin | **6 findings, all H5, one per Set**: the 6 `REVIEW_DELETE` Sets incl. *Product Basket 1*. No Set with dependents flagged. One warning only: *QS - Minimum tableDate* (Set-on-Set dependent, R14). No H4 |
| Migrate gate — cohort listing for unresolvable / cross-Org / hidden (open item #7) | Bogus GUID → **404** (13003); Answer GUID → **403** (10003); Dunder Mifflin from Org *DamianTest* → **404**. No unresolvable GUID returns 200 `[]`, so a failed lookup is always `INCOMPLETE` and `apply` refuses; no resolvability pre-check added. A Primary-owned Model shared into DamianTest lists only DamianTest's Sets (*TS: BI Server*: 0 there, 4 in Primary, the 4 invisible from DamianTest). `showhidden` true vs false: identical across all 1,908 Primary Models (418 Sets), no hidden Set exists, so kept `false`. `scan-sets --source-org DamianTest --all-models`: 0 Models (DamianTest owns none), all-zero summary |
