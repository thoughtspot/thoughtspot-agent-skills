# `ts migrate` — Org-to-Org Content Migration & Column Remap Design

**Date:** 2026-07-15
**Status:** Design approved, pending implementation plan
**Branch:** `feat/ts-org-migrate`

---

## Goal

Provide a deterministic routine to migrate tenant-authored ThoughtSpot content
from a source Org into a fresh "clean" Org that already holds centrally-published
Tables and Models, remapping the content onto those published objects and
reconciling any differing column names. The routine runs as a two-phase
`ts migrate` CLI command group (`audit` then `apply`), orchestrated by a
`ts-org-migrate` skill. It must be safe (backup + rollback), reviewable (a
human-approved column mapping gates every write), and — the primary constraint —
**efficient and resumable per tenant**: one `(source Org → clean Org)` run must be
fast and API-frugal even for a tenant with thousands of objects, and trivially
repeatable across ~2000 Orgs on a few clusters, migrated per-tenant on demand.

## Context & Terminology

The organisation is moving to **ThoughtSpot Publishing**: today each tenant Org
holds its own copies of Tables, Models, and standard Liveboards; in the target
state a single governed copy of Tables + Models is authored in a **Primary Org**
and *published* into fresh, empty **clean Orgs** (`cleanTenant1`, `cleanTenant2`,
…). Tenants have also built their own content — **Sets, (Search-based) Views,
Answers, Liveboards** — on top of their local copies. That bespoke content is
what this routine migrates.

| Term | Meaning |
|------|---------|
| **Source Org** | The old tenant Org (`Tenant1`) holding the tenant's original Tables, Models, and bespoke content. |
| **Clean Org** | The fresh target Org (`cleanTenant1`) that already received the governed **published Tables + Models** via Publishing. Starts with no bespoke content. |
| **Published Model/Table** | The governed object in the clean Org (its own GUID/fqn in that Org). Migration destination. |
| **Tenant scaffolding** | Copies of the source Org's Tables + Models lifted into the clean Org purely as an intermediate; deleted at the end. |
| **Bespoke content** | Tenant-authored Sets, Views, Answers, Liveboards — the objects actually being migrated. |
| **Column mapping** | Per-Model `tenant-column-name → published-column-name` exception list (majority match 1:1; only renames are listed). |

Each migration run processes exactly one **(source Org → clean Org)** pair.
Cross-cluster and same-cluster-different-Org are both supported: each side is a
`ts` profile plus an optional org identifier (see *Auth & Org Scoping*).

## Why this architecture

The naive approach — rewrite every bespoke object's references from source GUIDs
to clean-Org published GUIDs — is O(objects) of fragile per-object rewriting and
does not scale. Instead we reframe migration as **lift-and-shift + local
transform**, which plays to the existing in-cluster dependency engine's
strengths:

1. **Lift-and-shift** the tenant scaffolding (Tables + Models) and bespoke content
   into the clean Org *as batches*. Because tables, models, and content move
   together, their references stay internally consistent — ThoughtSpot rewires
   intra-batch references on import. **Zero per-object reference rewriting.**
2. **Rename** the tenant scaffolding Model/Table columns to the published names,
   *once per column*. This cascades to every dependent object automatically —
   O(columns) work instead of O(objects).
3. **Repoint** the bespoke content from the tenant scaffolding Models onto the
   governed published Models. Because column names now match after step 2, this
   is a clean 1:1-by-name repoint using the proven in-cluster
   `ts dependency apply-change` engine.
4. **Delete** the tenant scaffolding, leaving only published Models + repointed
   content in the clean Org.

### Verified assumption (2026-07-15, live on se-thoughtspot)

Step 2 is load-bearing and was verified before committing this design.
Renaming a Model column's display alias by editing only `columns[].name` and
importing with `--no-create-new` is treated by ThoughtSpot as an **in-place
column update** (`diff: {columns_updated: 1}`, status `OK`), not a drop+add. A
dependent Answer's stored formula auto-updated from `[Product Category]` to
`[Product Category ZZZ]` with the Answer never being touched, and reverted
symmetrically on rename-back. Dependents reference the column by its logical
identity (anchored to the unchanged `column_id` physical binding), not the name
string. Recorded in memory `feedback_ts_column_alias_rename_propagates`.

### Remaining spike (implementation task #1) — RUN 2026-07-27, see below

**Result: the mechanism works; three preconditions in front of it do not.** Full account:
[`2026-07-27-ts-migrate-batch-import-spike.md`](../verification/2026-07-27-ts-migrate-batch-import-spike.md).

1. **Connections are per-Org, never shared, and differently named** (`APJ` in Primary,
   `APJ_ORG1` in ORG1). A tenant Table's TML carries its own Org's connection, which is an
   **external** reference — nothing in the batch can remap it. The "zero per-object
   reference rewriting" claim holds for intra-batch references and not for this one. Every
   lifted Table needs its `connection` block rewritten: one field per Table, O(tables).
   Since step 4 deletes the scaffolding and nothing is queried through it, *any* valid
   connection in the target will do.
2. **Publishing a Table into an Org does not give that Org a usable connection.** Verified
   directly: a fresh Org with a published Table still lists zero connections and still
   refuses a Table import. So the clean Org needs its OWN connection provisioned first —
   a `ts tenancy` concern, not a `ts migrate` one.
3. **Tables dedupe by PHYSICAL binding, not logical name.** A renamed, guid-stripped Table
   still matched an existing one (`Cannot create a new table ... Existing Table GUID: …`).
   Lift-and-shift needs the tenant's binding to be distinct from anything already modelled
   in the target.

**The mechanism itself showed up working:** `Warning: No table with fqn <dead-guid> found
for table_id <name>` proves the importer tries the fqn, then falls back to the NAME — which
is exactly what intra-batch remapping relies on. Names must therefore be unique in the
target Org.

**Throughput:** 2 API calls for 3 objects (export and import both batch), ≈0.6–0.9s/object.
Calls scale with batches, not objects, as the Efficiency & Scale section assumes. Re-measure
at realistic batch sizes.

**Consequences.** Add a step 0 to the architecture below (the clean Org must have its own
connection, and every lifted Table's connection block is rewritten to it), and have
`audit` report two new blockers: no connection in the target, and a scaffolding Table
whose physical binding collides with something already there.

### Original spike definition

Confirm that a **batch import into a fresh Org remaps intra-batch references
cleanly** — i.e. importing scaffolding Tables + Models + content together binds
content to the newly-created scaffolding Models without manual GUID surgery. This
cannot be fully exercised without a clean target Org, so it is the first
implementation task and gates the exact import batching/ordering. Fallback if it
misbehaves: import in dependency tiers with an explicit source→target GUID map
threaded through references (still no name-level rewriting). The spike also
**measures throughput** — API calls and wall-clock per object — so a large tenant's
run time can be predicted and the batching validated against the round-trip budget
(see *Efficiency & Scale*).

## CLI Surface

New command group `ts migrate` in `tools/ts-cli`.

```
ts migrate scan-sets --source-profile P1 [--source-org O1 ...] \
                     [--model <name|guid> ...] [--all-models] \
                     [--models-file F] [--models-table T] [--out-dir ./scan/]

ts migrate audit  --source-profile P1 [--source-org O1] \
                  --target-profile P2 [--target-org O2] \
                  [--model <name|guid> ...] [--all-models] \
                  --out-dir ./migrate_run/

ts migrate apply  --source-profile P1 [--source-org O1] \
                  --target-profile P2 [--target-org O2] \
                  --plan ./migrate_run/ \
                  --mapping ./migrate_run/column-mapping.csv \
                  [--model <name|guid> ...] [--dry-run] [--resume]

ts migrate rollback --target-profile P2 [--target-org O2] --plan ./migrate_run/
```

- `audit` is read-only. It writes the audit report and a pre-filled column-mapping
  file into `--out-dir`.
- `apply` refuses to run while any *used* tenant column is still unmapped in the
  approved mapping file. `--dry-run` runs every import as `VALIDATE_ONLY`.
  `--resume` continues from the state ledger.
- `rollback` deletes objects created in the clean Org using the state ledger.

Migration is scoped **per Model** by default (the natural unit — bespoke content
attaches to Models); `--all-models` enumerates every published Model in the clean
Org and processes each in turn.

## Phase 0 — `ts migrate scan-sets` (read-only, source-side only)

**Added 2026-07-26 after live testing established that Sets block migration.**

### Why this is a separate command

Sets are a hard blocker (see *Sets are a migration blocker* below). Before planning any
wave — or committing to build Phase 2 at all — the programme needs one number: **how many
tenants actually use Sets.** That answer decides whether Sets support gates the whole
programme or just a tail of stragglers.

This is deliberately **not** a mode of `audit`:

- It needs **no target Org**, so it runs before any clean Org exists.
- It is far cheaper: a metadata scan, no TML export and no column matching.
- Its output is a fleet roll-up, not a per-tenant mapping file.

### Surface

```
ts migrate scan-sets --source-profile P1 [--source-org O1 ...] \
                     [--model <name|guid> ...] [--all-models] \
                     [--models-file objects.csv] [--models-table DB.SCH.T] \
                     [--out-dir ./scan/]
```

Scoping mirrors `audit` (`--model` repeatable, `--all-models`) and adds the manifest forms
used elsewhere in the CLI, so a targeted list of migration-candidate Models can be scanned
without sweeping every Model on the cluster. `--source-org` is repeatable for a fleet pass.

### What it does

1. For each in-scope Model, find `LOGICAL_COLUMN`s of subtype `COHORT_*` owned by it.
   **Query metadata, never TML** — see the detection note below.
2. For each cohort column found, walk dependents with `--type LOGICAL_COLUMN` to list the
   Answers and Liveboards that actually use it.
3. Emit `sets-scan.json` + `sets-scan.md`.

```json
{
  "scanned":  {"orgs": 12, "models": 340},
  "summary":  {"orgs_blocked": 3, "models_blocked": 4, "objects_affected": 17},
  "blocked":  [
    {"org": "Tenant1", "model": "Sales", "model_guid": "...",
     "cohort_columns": [{"name": "RSET_QTY_BINS", "guid": "..."}],
     "dependents": [{"type": "ANSWER", "name": "Q4 cohort view", "guid": "..."}]}
  ]
}
```

The per-object detail is the point. "Blocked" alone is a dead end; "blocked by these four
Answers" is a decision the tenant can act on — some Set-based content is stale or rebuilds
trivially as a filter, and retiring it converts a blocked tenant into a migratable one
without waiting for the platform.

---

## Sets are a migration blocker

**Verified live 2026-07-26** (nebula, Orgs-enabled). Three facts:

1. A Set creates a `LOGICAL_COLUMN` of subtype `COHORT_SIMPLE` **owned by the Model**.
2. That column **does not appear in the Model's TML at all** — the Model exported 10
   columns and the cohort column was not among them. It is visible only via
   `metadata/search`.
3. A cohort column **blocks publishing** the Model and every Answer and Liveboard on it,
   used or not. Published objects are also read-only in target Orgs, so a Set cannot be
   added to a published Model afterwards either.

**Therefore Sets cannot live on a published Model.** Not "should not" — cannot.

Fact 2 is the dangerous one: because the cohort column is invisible in TML, a
lift-and-shift would **silently drop Sets** rather than fail. Nobody would notice until a
tenant asked where theirs went.

### Handling

`ts migrate apply` **refuses** when any in-scope Model has a cohort column. There is no
override flag. The alternatives were considered and rejected:

| Option | Why not |
|---|---|
| Migrate, leave Set-dependent content in the source Org | Splits the tenant across two Orgs for months. Worse for users than waiting |
| Retain the tenant scaffolding Model for Set content | Two Models in one Org with identical column names after the rename step. Search and Spotter see both; users get duplicates. A hybrid state to unwind later |
| A `--force` style flag | Silently leaving content behind is precisely the failure mode fact 2 already makes likely |

A blocked tenant either retires or rebuilds the dependent content (use `scan-sets` to see
what that is), or waits for Sets support on published objects — expected in roughly 3 to 6
months from 2026-07.

Set-usage is therefore a **risk class in the existing batching strategy**, not a hard stop
on the programme: low-risk tenants migrate now, Sets-using tenants form a later batch.

### Detection note

Cohort columns must be found through `metadata/search` for `COHORT_*` subtypes. Inspecting
TML is not sufficient and will report a clean Model that is in fact blocked.
`ts publish export` already implements this correctly and is the reference.

---

## Phase 1 — `ts migrate audit` (read-only)

1. Open source and target sessions (two `ThoughtSpotClient` instances; see auth).
2. For each in-scope Model, enumerate the source-Org bespoke content depending on
   it (Sets, Views, Answers, Liveboards) via `ts metadata report` / `dependents`,
   applying the alias-propagation rule (match dependents against the Model's
   aliases, per memory `feedback_dep_manager_alias_propagation`).
3. Match the tenant Model + its underlying Tables to the clean Org's **published**
   counterparts **by name** (case-insensitive). Compare columns by name.
4. Classify each column: **matched** (name present in both), **gap** (in tenant,
   absent in published), **gap-blocker** (a gap column actually referenced by
   bespoke content — the only class that blocks migration), **gap-unused**
   (informational). Also flag **binding-mismatch** (same display name, different
   `column_id`) as review items.
5. Emit `column-mapping.csv` — one row per tenant column per Model, pre-filled.
   The `status` column takes one of `MATCHED`, `GAP` (unused gap), `GAP_BLOCKER`
   (used gap), `SET_BLOCKER` (the Model carries a cohort column — see *Sets are a
   migration blocker*), `BINDING_MISMATCH`. Matched rows are resolved; `GAP`/`GAP_BLOCKER`
   rows have a blank `published_column` field for the user to fill
   (`Department → String1`).
6. Emit `audit-report.md` + `audit-report.json`: object inventory to migrate,
   per-Model column diffs, blockers, physical-binding warnings, and a readiness
   verdict per Model.

The audit changes nothing and can be re-run freely.

### `column-mapping.csv` shape

```
model,tenant_column,tenant_column_id,published_column,status
Sales,Department,DM_CUST::DEPT,,GAP_BLOCKER      # user fills published_column
Sales,Amount,DM_ORD::LINE_TOTAL,Amount,MATCHED
Sales,Region,DM_CUST::REGION,Region,MATCHED
```

## Phase 2 — `ts migrate apply`

Per (source Org → clean Org) pair, per Model, driven by the approved mapping and a
state ledger:

0. **Load & validate mapping** — abort if any `GAP_BLOCKER` row has an empty
   `published_column`, or if any Model carries a `SET_BLOCKER`. The Set case has no
   override: see *Sets are a migration blocker*.
1. **Backup** — export every source object in scope (reuse the `ts dependency
   backup` all-or-nothing pattern) to `--plan/backup/`. Nothing is written if any
   export fails.
2. **Lift-and-shift scaffolding** — export tenant Tables + Model(s) from the
   source Org and import them into the clean Org as a batch (create-new; GUIDs
   recorded in the ledger). Tables bind to the clean Org's connection (same
   physical warehouse).
3. **Lift-and-shift content** — export bespoke content (Views + Sets → Answers →
   Liveboards) and import into the clean Org as batches in dependency order.
   References resolve to the just-imported scaffolding Models.
4. **Rename** — for every mapping row where `tenant_column != published_column`,
   edit `columns[].name` on the scaffolding Model/Table TML (keeping `column_id`)
   and import with `--no-create-new`. Verify `diff.columns_updated`. Cascades to
   all content automatically.
5. **Repoint** — repoint bespoke content from scaffolding Models onto the
   published Models via `ts dependency apply-change` (now a 1:1 name match).
   `search_query` sanitisation and dangling-join handling are already enforced by
   that engine (per memory `feedback_ts_tml_import_constraints`).
6. **Cleanup** — delete the tenant scaffolding Tables + Models from the clean Org.

Every step records progress in the **state ledger** so a re-run with `--resume`
skips completed work; imports of already-created objects use `--no-create-new`
with the ledger's target GUID (avoids duplicate-creation per memory
`feedback_ts_tml_import_gotchas`). `--dry-run` runs all imports `VALIDATE_ONLY`.

### State ledger (`--plan/state.json`)

```json
{
  "pair": {"source": "Tenant1", "target": "cleanTenant1"},
  "models": {
    "<published_model_guid>": {
      "scaffold_model": {"source_guid": "...", "target_guid": "...", "step": "renamed"},
      "objects": [
        {"type": "ANSWER", "source_guid": "...", "target_guid": "...", "step": "repointed"}
      ]
    }
  }
}
```

The ledger is the single source of truth for resumability **and** rollback.

## Auth & Org Scoping

Reuse `ts_cli/client.py` (profile resolution, keyring credentials, token cache,
401/5xx retry). Two clients are instantiated — one per `--source-profile` /
`--target-profile`.

- **Cross-cluster:** the two profiles carry different `base_url`s. No new auth
  work.
- **Same-cluster, different Org:** both sides may share a profile but differ by
  `--source-org` / `--target-org`. `client.py` today binds one session with no
  org switch. Add org-scoped token acquisition (pass `org_identifier` to the
  `auth/token/full` exchange, or set the org on the session) — a small, isolated
  extension, verified during implementation. Cross-cluster does not need it, so
  it does not block the cross-cluster path.

## Reuse Map

| Concern | Reused component |
|---------|------------------|
| Auth, retry, token cache | `ts_cli/client.py` |
| TML export/import/lint | `ts tml export/import/lint` |
| Repoint transforms (fqn/obj_id swap, `column_id` prefix, formula `expr`, joins, descriptions) | `ts_cli/dependency/mutate.py` (`repoint_*`) |
| `search_query` sanitisation, dangling-join removal | `ts_cli/dependency/mutate.py` |
| Dependent discovery + alias propagation | `ts metadata report` / `dependents` |
| Backup / apply-change / rollback engine | `ts dependency backup|apply-change|rollback` |
| Object-type identifiers, subtypes | existing metadata type maps |

New code is the `ts_cli/migrate/` package: orchestration, name-based matching,
column-mapping IO, the state ledger, batch lift-and-shift, and the rename step.

## Efficiency & Scale

Efficiency is the primary non-functional requirement. Execution is **per-tenant on
demand** across ~2000 Orgs on a few clusters, so the strategy is *not* a distributed
fleet engine — it is a tight, API-frugal single-tenant run plus a thin wrapper for
running a wave. Deliberately **not** building a queue/worker system.

### The real lever — minimise API round-trips within one run

Deterministic Python transforms (matching, TML rewriting, mapping) are CPU-cheap; the
cost that scales is **ThoughtSpot API calls**. Every step is designed to batch:

- **Export in bulk** — one `ts tml export` call with many GUIDs and `--associated`,
  not one call per object. One dependents walk per Model (cached), not per object.
- **Import in bulk** — array/`--dir` import grouped by dependency tier (tables+models,
  then views+sets, then answers, then liveboards), so each tier is a few calls, not one
  per object.
- **Repoint in bulk** — a single `ts dependency apply-change` plan per Model covers all
  its dependents in one pass.
- **No obj_id read-back per object** — avoid the known anti-pattern (repo-audit angle
  14); resolve target references once into an in-memory map and reuse it.
- **Reuse the token cache** — one authenticated session per side per run.

The design carries an explicit **round-trip budget**: API calls per run should scale
with *tiers × models*, not with *object count*. The spike (below) measures actual
calls-per-object and wall-clock-per-object on a real tenant so a large tenant's run
time can be predicted before the fleet rollout.

### Known cost — the scaffolding double-import

The lift-and-shift + rename + repoint path imports bespoke content **twice** (once on
lift-shift, once on repoint) plus the scaffolding create/delete lifecycle. This is the
price of robustness (it avoids fragile per-object formula/column-name rewriting). It is
mitigated by batching both imports, but if the spike shows imports dominate wall-clock
for large tenants, the fallback is to fold the column rename into the repoint so content
imports once — recorded as a tunable, not a v1 default.

### Resumability & re-runs

- Per-object idempotency via the state ledger: an interrupted run resumes exactly where
  it stopped; a completed run re-invoked is a near-no-op (delta only).
- `client.py` 5xx backoff is respected; a per-run summary (migrated / skipped / blocked
  / failed) plus a machine-readable manifest supports per-tenant reporting.
- Browser/bearer tokens are short-lived (memory `reference_ts_skills_smoke_profile`);
  a long single-tenant run must refresh mid-run.

### Running a wave

A thin batch wrapper (a loop over a tenant-pair list, sharded per cluster with bounded
concurrency and per-tenant `--plan` dirs) covers "migrate N tenants tonight" without a
bespoke orchestrator. Concurrency is a knob, tuned to each cluster's headroom.

## File Layout

```
tools/ts-cli/ts_cli/
+-- migrate/
|   +-- __init__.py        # run_audit(), run_apply(), run_rollback() entry points
|   +-- match.py           # name-based Model/Table/column matching + classification
|   +-- mapping.py         # column-mapping.csv read/write + validation
|   +-- ledger.py          # state ledger read/write, resume/idempotency helpers
|   +-- liftshift.py       # batch export→import of scaffolding + content
|   +-- rename.py          # column-alias rename step (verified pattern)
|   +-- report.py          # audit-report.md/.json emitters
tools/ts-cli/ts_cli/commands/migrate.py   # click command group wiring
agents/cli/ts-org-migrate/SKILL.md        # orchestration skill (+ references/)
```

## Error Handling

- Audit is read-only and total (never partial writes).
- Apply is transactional per step with the ledger; a failed step leaves the
  ledger at the last good state and `--resume` retries from there.
- `apply` refuses to start with unmapped blockers.
- `--dry-run` (`VALIDATE_ONLY`) available for every import.
- `rollback` deletes clean-Org objects by ledger GUID, in reverse dependency
  order.

## Testing

- **Unit:** pure functions — name matching/classification, mapping IO/validation,
  ledger transitions, rename-TML transform, report emission — against fixture
  TMLs. No network.
- **Live smoke:** one small source→target pair on `se-thoughtspot`; the rename
  step is already proven live (2026-07-15). The batch-import-into-clean-Org spike
  becomes a smoke test once a clean Org is available.

## Out of Scope (v1)

- Cleanup / exclusion-tagging of source content before migration (a separate
  pre-step).
- Preserving original owner, sharing, and permissions (v1 imports as the running
  user; noted in the report).
- Migrating the published Tables/Models themselves (they arrive via Publishing).
- Renaming migrated *objects*.
- Schedules and Alerts.

## Open Questions

1. **Batch-import reference remapping into a fresh Org** — the spike above;
   confirms exact import batching/ordering (§*Remaining spike*).
2. **Same-cluster org-scoped auth** — with ~2000 Orgs on a few clusters, source and
   clean Orgs are frequently on the *same* cluster, so org-scoped auth is **likely
   required, not deferrable**. Confirm the `org_identifier` mechanism on the token
   exchange early (candidate for the same spike).
3. **Connection binding of scaffolding Tables in the clean Org** — confirm tenant
   scaffolding Tables can bind to the clean Org's published connection (same
   physical warehouse) so the rename→repoint path holds.
