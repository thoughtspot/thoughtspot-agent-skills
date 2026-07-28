# End-to-end migration fixture — live verification

**Date:** 2026-07-27, rewritten 2026-07-28 after the architecture change
**Cluster:** `nebula-damian-alias` (test cluster, authorised by the repo owner)
**Status:** fixture is **live and left in place**. The migration **completes successfully**.

> **This is the verification record.** For instructions on running a migration, use
> [`running-a-migration.md`](../../../agents/cli/ts-migrate-orgs/references/running-a-migration.md)
> — the sequence, what a human must decide, every check, and the Python API.

The original version of this document described the lift-and-shift architecture and
recorded that the run failed at `lift_scaffolding` (**BL-148**). That architecture was
replaced by export/rewrite/import, and the run now completes.

---

## The fixture

| Org | Object | Owner | GUID |
|---|---|---|---|
| **ORG1** (source) | `T2_PUBLISH` Table on `APJ_ORG1` | ORG1 | `a9f276dd-5055-4b15-895b-18f080e37ccf` |
| **ORG1** | `T2_PUBLISH_MODEL` | ORG1 | `9917a017-443c-4cf7-be81-2958d83997c8` |
| **ORG1** | Answer `ORG1 Revenue by Segment` | ORG1 | `3c708712-12ab-45d5-abb6-15a6305b917d` |
| **ORG2** (target) | `T2_PUBLISH` Table | Primary — **published** | `d2c12c11-6560-4810-96b8-4b902bbb82dc` |
| **ORG2** | `T2_PUBLISH_MODEL` | Primary — **published** | `2a743be3-b26e-43b7-9abc-47aa6486dc57` |

ORG1's Model shares the published Model's **name** (that is how `audit` pairs them) while
naming two columns the tenant's way:

| Tenant name | Physical column | Published name |
|---|---|---|
| `Segment` | `T2_PUBLISH::STRING_1` | `STRING_1` |
| `Order Date` | `T2_PUBLISH::DATE_1` | `DATE_1` |

Four other columns already match, which is the normal case.

ORG1's Table sits on `APJ_ORG1` against the **same physical warehouse table** as the
published one on Primary's `APJ`. No collision, because the Table dedupe key includes the
connection — so this fixture doubles as a standing regression test of that finding.

---

## What was verified

### `ts migrate scan-sets`

Scanned 80 Models across Primary and found exactly one blocked: `T1_PUBLISH_MODEL`,
carrying `RSET_QTY_ON_HAND_BINS`. That prediction was then **confirmed independently** — an
attempt to publish that Model failed on precisely that cohort column.

### `ts migrate audit`

Paired ORG1's Model to the published one, classified 4 `MATCHED` and 2 `GAP_BLOCKER` (both
tenant-named columns, correctly promoted to blockers once the Answer used one), and
reported the effort:

```
**1 dependent object(s)**, of which **1 need rewriting**.
No View shielding available: every dependent reads its source directly,
so the rewrite count is the object count.
```

### `ts migrate apply` — the tenant-isolation check fired first

The published table has no RLS, so the first run **correctly refused**:

```
  backup: done
  rewrite_views: done
FAILED at 'rewrite_content':
refused: the published Model 'T2_PUBLISH_MODEL' has NO row-level security on:
T2_PUBLISH. Binding this tenant's content to it would leave every tenant able to
see every other tenant's rows.
```

That is the check working. The run then **resumed cleanly from the ledger** with
`--allow-unfiltered-target`, skipping the completed `backup` and `rewrite_views`.

### The migrated Answer works

```
name          : ORG1 Revenue by Segment
tables        : fqn = 2a743be3…        <- the PUBLISHED Model
search_query  : [STRING_1] [AMOUNT]    <- was [Segment]
answer_columns: ['STRING_1', 'Total AMOUNT']

data HTTP 200
columns: ['STRING_1', 'Total AMOUNT']
rows   : [["Closed Lost", 3949.3], ["Closed Won", 22387], ["Demo", 22218.4],
          ["Negotiation", 17578.8]]
```

Repointed, renamed, and **returning real data**. Structural survival is not functional
survival, so the data check is the one that matters.

---

## Reproducing it

Org ids: Primary `0`, ORG1 `12750490`, ORG2 `535312919`, ORG3 `443705360`. Names work too
(BL-147 fixed).

```bash
ts migrate audit --source-org ORG1 --target-org ORG2 \
  --model 9917a017-443c-4cf7-be81-2958d83997c8 -o ./plan/ \
  --source-profile nebula-damian-alias --target-profile nebula-damian-alias

# fill the two GAP_BLOCKER rows: Segment -> STRING_1, Order Date -> DATE_1

ts migrate apply --source-org ORG1 --target-org ORG2 -d ./plan --dry-run \
  --source-profile nebula-damian-alias --target-profile nebula-damian-alias

# the published table has no RLS, so this run is EXPECTED to refuse
ts migrate apply --source-org ORG1 --target-org ORG2 -d ./plan \
  --source-profile nebula-damian-alias --target-profile nebula-damian-alias

ts migrate apply --source-org ORG1 --target-org ORG2 -d ./plan --resume \
  --allow-unfiltered-target \
  --source-profile nebula-damian-alias --target-profile nebula-damian-alias
```

The migrated Answer was deleted from ORG2 after verification, so the fixture reproduces
from a clean state.

### What this fixture does NOT exercise

- **View shielding.** ORG1 has no Views, so `rewrite_views` runs empty. The shield is
  proven separately, end to end and functionally, in this directory's View test.
- **Same-Org and cross-cluster topologies.** Only new-Org-same-cluster is exercised.
- **A published Model WITH RLS.** Every run needs `--allow-unfiltered-target`, so the happy
  path through the isolation check is unverified against real data.

---

## Teardown, when finished

```bash
# ORG1 fixture -- Answer, then Model, then Table
ts metadata delete 3c708712-12ab-45d5-abb6-15a6305b917d --type ANSWER --org 12750490
ts metadata delete 9917a017-443c-4cf7-be81-2958d83997c8 --type LOGICAL_TABLE --org 12750490
ts metadata delete a9f276dd-5055-4b15-895b-18f080e37ccf --type LOGICAL_TABLE --org 12750490

# ORG2 publication
ts publish rollback -i t2_rollback.json -p nebula-damian-alias
```

Pre-existing objects (`T4/T5/T6_PER_ORG` in ORG1, ORG2's own content) were not touched.

---

## Two `ts publish` defects found while staging this — both FIXED (v0.113.1)

**BL-146** — `ts publish apply` created the template variable and parameterized the field
*before* checking the cohort gate, so a Set-blocked publish left both behind and the re-run
failed with `HTTP 409 Duplicate template variable name`, pointing at the wrong problem
entirely. The gate now runs before any client is constructed.

**BL-147** — `ts migrate audit` read the **wrong Org** when given an Org name rather than a
numeric id. Now resolved and asserted the way `apply` does.
