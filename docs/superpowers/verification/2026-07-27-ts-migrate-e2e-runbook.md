# End-to-end migration fixture and runbook

**Date:** 2026-07-27
**Cluster:** `nebula-damian-alias` (test cluster, authorised by the repo owner)
**Status:** fixture is **live and left in place** for validation. Nothing here is torn down.

A working `ORG1 → ORG2` migration, staged up to the point where the destructive steps
begin. `audit` and `apply --dry-run` have been run against it successfully; the live
`apply` is deliberately left for a human.

---

## What is staged

| Org | Object | Owner | GUID |
|---|---|---|---|
| **ORG1** (source tenant) | `T2_PUBLISH` Table on `APJ_ORG1` | ORG1 | `a9f276dd-5055-4b15-895b-18f080e37ccf` |
| **ORG1** | `T2_PUBLISH_MODEL` | ORG1 | `9917a017-443c-4cf7-be81-2958d83997c8` |
| **ORG2** (target) | `T2_PUBLISH` Table | Primary — **published** | `d2c12c11-6560-4810-96b8-4b902bbb82dc` |
| **ORG2** | `T2_PUBLISH_MODEL` | Primary — **published** | `2a743be3-b26e-43b7-9abc-47aa6486dc57` |

ORG1's Model deliberately shares the published Model's **name** — that is how
`ts migrate audit` pairs them — while naming two columns the tenant's way:

| Tenant name | Physical column | Published name |
|---|---|---|
| `Segment` | `T2_PUBLISH::STRING_1` | `STRING_1` |
| `Order Date` | `T2_PUBLISH::DATE_1` | `DATE_1` |

Four other columns (`PROD_ID`, `CUSTOMER`, `REGION`, `AMOUNT`) already match, which is the
normal case — the rename step is O(renames), not O(columns).

ORG1's Table sits on `APJ_ORG1` against the **same physical warehouse table** as the
published one on Primary's `APJ`. No collision, because the dedupe key includes the
connection — this fixture is therefore also a standing regression test of that finding.

**ORG2 is a real tenant Org with its own content, not a fresh Org.** It was chosen because
it already has a connection (`APJ_ORG2`) and provisioning one needs warehouse credentials.
The consequence is that this fixture exercises the **connection-rewrite fallback**
(`APJ_ORG1` → `APJ_ORG2`) rather than the same-name path. Both are supported; the
same-name path is the one production will use.

---

## What has been validated

**`ts migrate scan-sets --all-models`** — scanned 80 Models across Primary and found
exactly one blocked: `T1_PUBLISH_MODEL`, carrying `RSET_QTY_ON_HAND_BINS`, with no
dependents. That prediction was then **confirmed independently**: an attempt to publish
that Model failed with precisely that cohort column. Phase 0 works against real data.

**`ts migrate audit`** — paired ORG1's Model to the published one, classified 4 `MATCHED`
and 2 `GAP`, and emitted `column-mapping.csv` with the two tenant columns left blank for a
human.

**`ts migrate apply --dry-run`** — produced the correct ordered plan, including detecting
the connection mismatch and selecting the rewrite path:

```
2. lift_scaffolding
   - 1 Table(s), 1 Model(s)
   - connection: rewrite — the target Org has no connection named 'APJ_ORG1', so each
     lifted Table's connection block is rewritten to 'APJ_ORG2'
4. rename
   - T2_PUBLISH_MODEL: `Order Date` → `DATE_1`
   - T2_PUBLISH_MODEL: `Segment` → `STRING_1`
```

---

## Running it

The plan directory with the **filled** mapping is at
`<scratchpad>/plan/column-mapping.csv`; regenerate it with the audit command below if it
has been cleaned up.

```bash
# 1. Audit  (numeric Org ids -- see the caveat below)
ts migrate audit --source-org 12750490 --target-org 535312919 \
  --model 9917a017-443c-4cf7-be81-2958d83997c8 -o ./plan/ \
  --source-profile nebula-damian-alias --target-profile nebula-damian-alias

# 2. Fill the two GAP rows in ./plan/column-mapping.csv:
#      Segment    -> STRING_1
#      Order Date -> DATE_1

# 3. Read the plan
ts migrate apply --source-org 12750490 --target-org 535312919 -d ./plan --dry-run \
  --source-profile nebula-damian-alias --target-profile nebula-damian-alias

# 4. Run it
ts migrate apply --source-org 12750490 --target-org 535312919 -d ./plan \
  --source-profile nebula-damian-alias --target-profile nebula-damian-alias

# 5. Undo
ts migrate rollback --target-org 535312919 -d ./plan --dry-run
ts migrate rollback --target-org 535312919 -d ./plan
```

### One gap in the fixture

**There is no bespoke Answer on ORG1's Model.** Hand-authoring a valid Answer TML kept
failing on table-path aliases (`Table path alias: t2 not found in metadata`) and was not
worth more budget — building one in the UI takes seconds and produces more realistic
content anyway.

Until one exists, `lift_content` and `repoint` are **no-ops**, so the run does not exercise
the two most interesting steps. **Create an Answer in ORG1 on `T2_PUBLISH_MODEL` that uses
the `Segment` column before running step 4.** That column choice matters: `Segment` is
renamed during the migration, so the Answer is what proves the rename cascades to
dependents rather than breaking them.

### Caveat: pass Org ids numerically

`--source-org ORG1` **fails** (`Specified identifier doesn't exist`); `--source-org
12750490` works. `auth/token/full` silently ignores a non-numeric `org_identifier` and
falls back to the caller's default Org — the known trap — and `audit`'s inline comment
claiming `_org_auth_fields` resolves a name is **wrong**. Worth fixing: `audit` should
resolve the name the way `apply` does, or refuse a non-numeric value rather than reading
the wrong Org.

Org ids on this cluster: Primary `0`, ORG1 `12750490`, ORG2 `535312919`, ORG3 `443705360`.

---

## Two `ts publish` defects found while staging this

Neither blocks the fixture; both are real.

**`ts publish apply` is not idempotent, and its gates run in the wrong order.** It creates
the template variable and parameterizes the field *before* checking the cohort-column gate.
A Set-blocked publish therefore leaves the variable and the parameterization behind, and
the re-run fails with `HTTP 409 Duplicate template variable name` — pointing at the wrong
problem entirely. Recovering takes a manual `unparameterize` (the variable cannot be
deleted while bound) then a variable delete. **The cohort gate should run first**, before
anything is created.

**The failure was also silent at the surface I was watching**: `created variable` and
`parameterized` were printed, and the cohort refusal went to a different stream, so the
run looked like it had partially succeeded rather than been refused.

---

## Teardown, when finished

```bash
# ORG1 fixture -- Model before Table
ts metadata delete 9917a017-443c-4cf7-be81-2958d83997c8 --type LOGICAL_TABLE --org 12750490
ts metadata delete a9f276dd-5055-4b15-895b-18f080e37ccf --type LOGICAL_TABLE --org 12750490

# ORG2 publication
ts publish rollback -i t2_rollback.json -p nebula-damian-alias
```

Pre-existing objects (`T4/T5/T6_PER_ORG` in ORG1, ORG2's own content) were not touched.
