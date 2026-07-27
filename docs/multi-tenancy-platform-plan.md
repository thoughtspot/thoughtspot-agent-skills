# Single-model multi-tenancy: end-to-end build plan

**Date:** 2026-07-26
**Scope:** the capabilities that make single-model multi-tenancy work for embedded
analytics, how they interact, and what remains to build.

This is the programme-level view. Per-component design specs live under
`docs/superpowers/specs/`; the two most relevant here are
`2026-07-25-ts-publish-orgs-design.md` and `2026-07-15-ts-org-migrate-design.md`, which
land with PR #343 and the `feat/ts-org-migrate` branch respectively. This document ties
them together and records the cross-component interactions that no single spec owns.

---

## 1. The pattern, and what each component owns

| # | Component | Owns | Skill | CLI |
|---|---|---|---|---|
| 1 | **Publication** | One governed Table + Model in the Primary Org, published to tenant Orgs with per-Org variables | `ts-publish-orgs` | `ts publish`, `ts variables`, `ts metadata parameterize` |
| 2 | **Aliasing** | Per-tenant display names for shared generic columns (`String1` → `Region`) | `ts-object-model-alias` | `ts alias` |
| 3 | **Column security** | Hiding custom columns a tenant does not use | *not built* | *not built* |
| 4 | **Sharing** | Making objects visible to end users; also the mechanism column security uses | *not built* | *not built* |
| 5 | **Migration** | Moving existing tenants from replicated content to the published model | *not built* | `ts migrate audit` only |

Sharing (4) is a lower-level capability that both publication and column security consume.
It is not part of either.

---

## 2. Current state

| Component | Status |
|---|---|
| Publication | **PR #343** (rebased, checks green). CLI + skill complete, live-verified. Two open items: connection-property variables, and substitution verified inside a target Org |
| Aliasing | **Shipped** on main (skill v1.1.0, `ts alias` v0.98.0) |
| Column security | **Not started.** APIs identified |
| Sharing | **Not started.** No `ts share` command exists |
| Migration | **Phase 1 built, unmerged** on `feat/ts-org-migrate`. `ts migrate audit` works; `apply` and `rollback` do not exist; no skill |
| Orchestration | **Nothing** |

---

## 3. Review of the migration work (`feat/ts-org-migrate`)

### The architecture is sound

The design reframes migration as **lift-and-shift plus local transform** rather than
per-object reference rewriting:

1. Lift the tenant's Tables + Models + bespoke content into the clean Org as batches, so
   intra-batch references stay consistent and ThoughtSpot rewires them on import.
2. Rename the scaffolding columns to the published names, **once per column**. This
   cascades to every dependent automatically.
3. Repoint content from the scaffolding onto the governed published Models, now a clean
   1:1 name match.
4. Delete the scaffolding.

That converts O(objects) of fragile rewriting into O(columns) of renaming. Step 2 rests on
a live-verified behaviour (renaming a Model column's display name with `--no-create-new` is
an in-place update that propagates to dependents), which was checked before the design was
committed. The reuse map leans on `ts dependency`, `ts tml` and `client.py` rather than
reinventing them.

### What is built

`ts migrate audit` and its supporting package: schema dataclasses, name matching, column
classification and readiness, `column-mapping.csv` IO, audit report builders (JSON +
Markdown), a dependent-discovery layer, and org-scoped token auth on `client.py`. Six test
modules.

### What is not

- `ts migrate apply` — every mutating step: backup, lift-and-shift, rename, repoint, cleanup
- `ts migrate rollback`
- The state ledger that makes runs resumable
- The `ts-org-migrate` skill
- All three spec open questions remain unanswered, and the first is a **gating spike**:
  confirm a batch import into a fresh Org remaps intra-batch references cleanly

### Risk assessment

| Risk | Assessment |
|---|---|
| Gating spike unproven | The whole architecture depends on batch-import reference remapping. Everything else is scaffolding around it. Do this first |
| Same-cluster org-scoped auth | Spec calls it "likely required, not deferrable" with ~2000 Orgs on a few clusters. Implemented on the branch but unverified |
| Scaffolding connection binding | Open question 3. My publishing work partly answers it: the Connection is **granted** to a target Org on publish, not copied, so the clean Org has the published connection available |
| Scope creep | v1 correctly excludes owner/permission preservation, schedules, alerts. Keep it there |

---

## 4. The three cross-component interactions

These are not in any existing document and are the reason an end-to-end plan is needed.

### 4.1 Migration audit output is the input to aliasing AND column security

`ts migrate audit` already computes, per tenant Model, which tenant column maps to which
published column, and **which columns are actually referenced by bespoke content**. That is
precisely the input the other two components need.

```
column-mapping.csv                       (ts migrate audit)
  model, tenant_column, published_column, status

        ├─► alias CSV                    (ts alias --source file)
        │     column_name  = published_column      e.g. String1
        │     alias        = tenant_column         e.g. Region
        │     org_name     = the tenant Org
        │
        └─► column security input
              used columns    -> share / grant
              unused columns  -> withhold
```

The `status` field already distinguishes used gaps (`GAP_BLOCKER`) from unused ones
(`GAP`), which is exactly the used/unused split column security needs.

**Implication.** Do not build three separate discovery mechanisms. The migration audit is
the discovery layer for the whole pattern, and a transform step should emit the alias CSV
and the column-security manifest from it.

### 4.2 Cohort columns may block re-publication after migration

**Verified:** an unused cohort column (`COHORT_SIMPLE`) owned by a Model blocks publishing
that Model and every Answer and Liveboard on it. The Table beneath it publishes fine.

**Inferred, needs confirming:** ThoughtSpot Sets create exactly such a column on the Model.
The migration spec lists **Sets** as bespoke content it migrates.

If both hold, then migrating tenant Sets onto a shared published Model progressively makes
that Model unpublishable: the first migrated Set breaks publication for every subsequent
tenant and for any update to the Model.

This is the single most important thing to test before `ts migrate apply` is built, because
it could invalidate the "migrate Sets onto the published Model" step. Possible outcomes:

- Sets do not create Model-owned cohort columns, and there is no issue
- They do, and Sets must stay on tenant-local objects rather than the published Model
- They do, and Sets cannot be migrated at all in the published architecture

**Tested 2026-07-26. Result: worse than expected, and it changes the migration design.**

The cohort column is a `LOGICAL_COLUMN` of subtype `COHORT_SIMPLE` **owned by the Model**,
created when a Set is added. Three facts, all verified:

1. It **does not appear in the Model's TML at all.** The Model exports 10 columns; the
   cohort column is not among them. It is only visible through `metadata/search`.
2. It **blocks publishing** the Model and every Answer and Liveboard on it, used or not.
3. Published objects are **read-only in target Orgs**, so a tenant cannot add a Set to a
   published Model even if they wanted to.

Taken together: **Sets cannot live on a published Model.** Not "should not" — cannot. The
first Set added would make the Model unpublishable, and tenants cannot create them on a
published Model anyway.

**Consequences for the migration design:**

- The spec lists Sets as bespoke content to lift-and-shift. That step cannot land them on
  the published Model. Options are to drop Sets (tenant loses them), recreate them on a
  tenant-local object, or keep a tenant-local Model purely for Sets, which partly defeats
  the purpose. This is a **product decision, not an implementation detail**, and it should
  be settled before `ts migrate apply` is written.
- Because the cohort column is invisible in TML, a lift-and-shift would **silently drop
  Sets** rather than fail. Nobody would notice until a tenant asked where their Set went.
- Any pre-flight check must query `metadata/search` for `COHORT_*` subtypes. Inspecting TML
  is not sufficient. `ts publish export` already does this correctly.

### 4.3 Publication constrains the column-security mechanism

Column security rules **can** be defined on a published object -- the platform accepts the
write (`HTTP 204`) and enforces it in the Org where it was defined. The constraint is not an
API refusal; it is about *where the rule takes effect*: it does not travel with publication.
Live-verified with real non-admin user sessions on `nebula-damian-alias`: a rule restricting
a column stayed enforced in the owning Org but the same column remained fully visible in a
tenant Org the object was published to, with no error and no warning in either Org. See
`docs/superpowers/verification/2026-07-26-ts-security-column-rules-live-verification.md` §15.
So, in practice:

| | Org per tenant (published) | Shared org (not published) |
|---|---|---|
| Column security | column-level **sharing** | column security **rules** |
| Liveboards with secured filters | lock; must be replicated | stay interactive |

The column-security skill therefore cannot be a single implementation. It must detect
publication state and choose the mechanism, and the two have materially different
capabilities. This also means the migration path has a sequencing constraint: reduce object
count with column-level sharing first, then move to rules once each tenant Org's own CSR
configuration, against that Org's own groups, is set up and verified there -- there is no
single owning-Org rule that reaches every tenant automatically.

This also makes the per-Org shape of the column-security manifest load-bearing rather than
incidental: `TS_COLUMN_SECURITY_RULES` is keyed by `org_name` precisely because a rule has
to be configured in each Org against that Org's own groups, not written once from the
owning Org and expected to propagate.

---

## 5. Build plan

### Phase A — close the current PR (now)

Merge #343. Publication is complete for schema-level tenancy.

### Phase B — sharing (small, unblocks two things)

`ts share` CLI: object-level and column-level, over `security/metadata/share`.

**Verified 2026-07-26.** `LOGICAL_COLUMN` **is** accepted by `shareMetadata` and takes
effect, despite being absent from the documented supported-types list. Proven decisively:
a group with no prior access appeared as `READ_ONLY` on the column after the call, along
with its member users, and reverted cleanly with `share_mode: NO_ACCESS`.

**Also found: the docs put `message` in the wrong place.** Every published example nests it
inside `notification`; the API rejects that with
`Variable "$message" of required type "String!" was not provided`. It must be **top-level**,
alongside `notify_on_share`. This affects object sharing as much as column sharing, so it
would have blocked the first call either way.

So sharing is one command over one endpoint, covering both object and column granularity.

Unblocks: `ts-publish-orgs` Step 12, and column security.

### Phase C — column security

`ts-security-columns` over two mechanisms:

- `security/metadata/share` for published objects
- `security/column/rules/update` + `/fetch` for unpublished (Beta, 10.12+)

The skill's job is choosing correctly and explaining the trade-off, not just calling an API.

### Phase D — migration, resumed

1. **The gating spike:** batch-import reference remapping into a fresh Org, plus throughput
   measurement.
2. **The cohort test** from §4.2, before committing to the Sets step.
3. `ts migrate apply` with the state ledger, then `rollback`.
4. The `ts-org-migrate` skill.

### Phase E — orchestration

Only once B, C and D exist. Two shapes:

- **Onboard a new tenant:** publish → share → alias → secure
- **Migrate an existing tenant:** audit → apply → alias → secure, driven by one manifest

The `ts publish run` command is the model for the headless shape: manifest in, exit code
out, refuses before touching anything if the plan is incomplete.

### Sequencing

```
A  publication  ──────────────► (done)
                    │
B  sharing      ◄───┘  unblocks Step 12 and Phase C
        │
C  column security
        │
D  migration    ── spike ── cohort test ── apply ── skill
        │
E  orchestration
```

The one item on the critical path for **both** the publish verify step and migration Phase 2
is **org-scoped token auth**. It is implemented on `feat/ts-org-migrate` but unverified.
Landing and verifying it early unblocks two components.

---

## 6. Immediate next actions

| # | Action | Effort | Why now |
|---|---|---|---|
| 1 | Merge PR #343 | — | Publication is done; keep the branch from ageing |
| 2 | ~~Cohort + Sets test~~ | done | **Sets cannot live on a published Model.** Needs a product decision before `ts migrate apply` |
| 3 | ~~Verify `LOGICAL_COLUMN` sharing~~ | done | Works. One command covers object + column sharing |
| 4 | Decide the Sets question | discussion | Blocks the migration design, not just the code |
| 5 | Land + verify org-scoped token auth | small | On the critical path for two components |
| 6 | `ts share` CLI | small | Unblocks Step 12 and Phase C |

Both tests are done and both changed the plan. The sharing one simplified it: a single
command over a single endpoint. The Sets one is more serious — it invalidates a step in the
migration spec and needs a decision about what happens to tenant Sets, before any code is
written for that phase.
