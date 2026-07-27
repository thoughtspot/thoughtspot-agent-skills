# Physical binding and connection scope — resolving spike findings §1 and §3

**Date:** 2026-07-27
**Cluster:** `nebula-damian-alias` (test cluster, authorised by the repo owner)
**Follows:** [`2026-07-27-ts-migrate-batch-import-spike.md`](2026-07-27-ts-migrate-batch-import-spike.md)
**Baseline:** captured, restored, diff proven (§6).

## Why this exists

The batch-import spike ended with three preconditions in front of lift-and-shift. Two of
them — the connection being an external reference (§1) and the physical-binding dedupe
(§3) — were framed against an assumed topology: one clean Org receiving tenants in
sequence, sharing whatever connection it had.

That assumption was wrong, and the repo owner corrected it. The real shape is **one fresh
Org per tenant** (`ACME` → `ACME NEW`), each **with its own connection**, named the same as
the tenant's existing one, and deleted once cutover completes.

Under that topology, two of the three findings dissolve. This document proves it.

---

## 1. Connection names are scoped PER-ORG, not cluster-unique

**The question.** `ACME NEW` needs a connection named `APJ_ACME` while `ACME` still has
one. If names were cluster-unique that is impossible, and every lifted Table's
`connection:` block would have to be rewritten — spike §1 stands.

**How it was tested.** Creating a connection needs warehouse credentials, and
`validate: false` does **not** skip warehouse validation despite the spec's wording — a
placeholder config fails at connectivity (`code 12119`, JDBC 404) before any name check.
So the test used a **rename** instead, which the `updateConnection` spec explicitly allows
without validation:

> "If you are updating a configuration attribute, connection name, or description, you can
> set `validate` to `false`."

`APJ_ORG2` was renamed to `APJ_ORG1` — a name ORG1 already holds — and restored in a
`finally` block. Table bindings are by connection GUID, so a rename is non-destructive.

```
RESULT : rename to 'APJ_ORG1' ACCEPTED while ORG1 holds that name
restored: 'APJ_ORG1' -> 'APJ_ORG2'
```

**Finding: connection names are per-Org.** Two Orgs may hold the same connection name
simultaneously.

**Consequence — spike §1 dissolves for this topology.** Give `ACME NEW` a connection named
exactly as `ACME`'s and the lifted Table TML resolves **unchanged**. No connection-block
rewriting, and the design's "zero per-object reference rewriting" claim holds for the
external reference too, not just intra-batch ones.

It is not a rewrite that was avoided so much as relocated: the naming is now
load-bearing, and `apply` must **verify** the target Org's connection name matches the
source's rather than assume it. A mismatch reverts to the §1 rewrite, which still works —
so this is an optimisation with a correct fallback, not a single point of failure.

---

## 2. The Table dedupe key INCLUDES the connection

**The question.** Spike §3 found Tables deduped on physical binding rather than logical
name. It did not establish whether the *connection* is part of that key — which decides
whether a tenant's scaffolding Table can coexist with a published Table on the same
warehouse table.

**How it was tested.** Two imports into ORG1, differing in exactly one variable.

`T1_PUBLISH` (Primary-owned, connection `APJ`, bound to
`AGENT_SKILLS.ALIAS_TESTS.T1_PUBLISH`) was first published into ORG1, so the Org held a
**published** Table on that binding.

| # | Import into ORG1 | Connection | Physical binding | Result |
|---|---|---|---|---|
| 1 | `SCAFFOLD_T1` | `APJ_ORG1` | `…ALIAS_TESTS.T1_PUBLISH` | **OK** — created |
| 2 | `SCAFFOLD_T4_CONTROL` | `APJ_ORG1` | `…ALIAS_TESTS.T4_PER_ORG` | **ERROR** — collided |

Import 2 is the control: ORG1 already owns `T4_PER_ORG` on that binding **via that same
connection**, and the importer refused it —

```
Cannot create a new table as the table in the TML file already exists.
Existing Table GUID: d3a688f2-2543-4dcc-9907-b4cdb130c36b.
```

— reproducing spike §3 exactly. The only difference in import 1 is the connection.

**Finding: the dedupe key is (connection + db + schema + db_table).** Same connection and
binding collides; a different connection on the same binding does not.

After import 1, both Tables coexisted in ORG1 on the same warehouse table:

```
TABLE                  OWNER-ORG   CONNECTION
SCAFFOLD_T1            ORG1        9f65f69c…  (APJ_ORG1)
T1_PUBLISH             PRIMARY     5e7e34e2…  (APJ)
```

---

## 3. Whether a PUBLISHED Table participates in the dedupe is moot

Worth stating explicitly, because it was on the question list and the answer is that the
question cannot arise.

A tenant Org can never hold Primary's connection — connections are per-Org and publishing
does **not** grant one (spike §2). So any Table a tenant Org creates is necessarily on a
*different* connection from a published Table's. By §2 above, it therefore cannot collide.

**Publication is irrelevant to the binding collision, by construction.** No test can
distinguish the two cases because the colliding case is unreachable.

---

## 4. Deleting a connection does NOT cascade to its Tables

The teardown step in the proposed routine ("delete `APJ_ACME`, the scaffolding goes with
it") assumed a cascade. The `deleteConnection` spec states the opposite:

> "**Note**: If a connection has dependent objects, make sure you remove its associations
> before the delete operation."

**Not live-verified**, and deliberately so: the only connections on the cluster carry real
fixture Tables, and testing a cascade that might succeed would destroy an Org's contents to
learn something the spec already states. It is recorded as spec-sourced.

**Consequence.** Teardown is two ordered steps, not one: delete the scaffolding Tables and
Models first, then the connection. The conservative order is correct whichever way the
platform actually behaves, so `apply` should implement it regardless.

---

## 5. Net effect on the spike's three preconditions

| Spike finding | Status under per-tenant-Org topology |
|---|---|
| §1 — connection is an external reference needing rewrite | **Dissolved**, if the target Org's connection is named as the source's. `apply` verifies the name and falls back to rewriting when it differs. |
| §2 — publishing does not grant a usable connection | **Stands**, and is now by design: each fresh Org is provisioned its own connection as an explicit step. |
| §3 — Tables dedupe by physical binding | **Stands as a fact, dissolved as a blocker.** The key includes the connection, so a tenant's scaffolding on its own connection never collides with the published Tables on Primary's. |

The RLS-segmented fleet case that made §3 look fatal — every tenant on one physical table
— is exactly the case the connection component resolves, because each tenant reaches that
table through its own connection.

**What `ts migrate audit` should report** (revising the spike's §7):

1. the target Org has no connection — **fatal**;
2. the target Org's connection name differs from the source's — **warning**, triggers the
   §1 rewrite path rather than blocking;
3. a scaffolding Table would collide **on the same connection** — fatal, but only reachable
   when source and target Orgs share a connection, which the per-tenant-Org topology
   precludes.

---

## 6. Baseline restored

| Dimension | Baseline | Final |
|---|---|---|
| `T1_PUBLISH` publication | `[]` | `[]` |
| ORG1 owned Tables | 7, no `SCAFFOLD_*` | identical |
| Variable `apj_schema` | absent | absent (deleted by rollback) |
| ORG1 / ORG2 / ORG3 connections | `APJ_ORG1` / `APJ_ORG2` / `APJ_ORG3` | identical |

`SCAFFOLD_T1` was deleted directly; the publication, the parameterized `schemaName` field
and the `apj_schema` variable were undone with `ts publish rollback -i`. The `APJ_ORG2`
rename was restored in the test's own `finally` block.

`SCAFFOLD_T4_CONTROL` never existed — the import that would have created it is the one
that failed, which is the finding.
