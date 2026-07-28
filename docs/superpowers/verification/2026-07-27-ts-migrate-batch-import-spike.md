# Phase D gating spike — batch import into a clean Org

**Date:** 2026-07-27
**Cluster:** `nebula-damian-alias` (test cluster, authorised by the repo owner)
**Spec:** [`2026-07-15-ts-org-migrate-design.md`](../specs/2026-07-15-ts-org-migrate-design.md)
§ *Remaining spike (implementation task #1)*
**Baseline:** captured, restored, diff proven (§6).

> **§1 and §3 have since been resolved — read
> [`2026-07-27-ts-migrate-binding-resolution.md`](2026-07-27-ts-migrate-binding-resolution.md)
> before acting on them.** Both were framed against an assumed topology (one shared clean
> Org) that the repo owner corrected to **one fresh Org per tenant, each with its own
> connection**. Under the real topology: connection names are per-Org, so a same-named
> connection makes §1's rewrite unnecessary; and the dedupe key includes the connection, so
> §3 is a fact but not a blocker. §2 stands and is now an explicit provisioning step.

## The question, and the answer

> Confirm that a **batch import into a fresh Org remaps intra-batch references cleanly** —
> importing scaffolding Tables + Models + content together binds content to the
> newly-created scaffolding Models without manual GUID surgery.

**Not proven, and it cannot be until three prerequisites the design does not mention are
solved.** That is the useful outcome: the spike was meant to gate the import
batching/ordering, and what it actually gates is earlier than that. None of the three is a
reason to abandon lift-and-shift; all three change what `apply` must do before it can
batch anything.

The design's core mechanism did show itself working (§4), so the architecture is not in
question — the preconditions are.

---

## 1. Connections are per-Org, never shared, and differently named

The finding that blocks everything else.

| Org | Connections visible |
|---|---|
| Primary | `SnowflakeConnection`, `APJ` |
| ORG1 | `APJ_ORG1` |
| ORG2 | `APJ_ORG2` |
| ORG3 | `APJ_ORG3` |
| A freshly created Org | **none** |

A tenant's Table TML therefore carries its own Org's connection:

```json
"connection": {"name": "APJ_ORG1", "fqn": "9f65f69c-9bd3-40f9-b50e-dd2b5ec458ff"}
```

Importing that anywhere else fails with `Please ensure that connection name specified in
TML file exists on this cluster`.

**This is an EXTERNAL reference.** The design's "zero per-object reference rewriting"
claim is about references *inside* the batch — Table ↔ Model ↔ Answer — and holds for
them. The connection points *out* of the batch, so nothing in the batch can remap it.

**Consequence for `apply`:** every lifted scaffolding Table needs its `connection` block
rewritten to the target Org's connection. That is one field per Table — O(tables), not
O(objects), and nothing like the per-object GUID surgery the architecture exists to avoid
— but it is not zero and it must be designed in.

**A simplification worth taking.** Step 4 of the migration *deletes* the scaffolding
anyway, and nothing is ever queried through it — only its reference structure matters. So
the rewrite does not need to find a *matching* connection, only a valid one in the target
Org. "Any connection the clean Org has" is a sufficient rule.

---

## 2. Publishing a Table into an Org does NOT give that Org a usable connection

Tested directly, because it was the obvious way to satisfy §1 with existing tooling.

`T1_PUBLISH` was parameterized and published from Primary into a fresh Org (`MIGSPIKE`).
The publish succeeded. The Org's connection list was then still **empty**, and a Table
import into it failed with the same connection error.

So the connection grant that publishing performs makes the *published object* work; it
does not make the connection available to create new Tables against. `ts publish`'s
rollback note ("retracting the Connection grant too") describes a grant on the published
object's behalf, not Org-level availability.

**Consequence:** a clean Org must be given its **own** connection before any lift-and-shift
can run. That is a provisioning step, and it belongs alongside the Org/user/group topology
in `ts tenancy` / `/ts-setup-tenancy` rather than inside `ts migrate`.

---

## 3. Tables are deduplicated by PHYSICAL binding, not logical name

With the connection rewritten to a valid one, the next import failed differently:

```
Cannot create a new table as the table in the TML file already exists.
Existing Table GUID: 383e0507-0023-4783-9aec-5c9478853765
```

The logical object had been renamed (`T4_PER_ORG` → `SPIKE_T4`) and its `guid` stripped.
The importer still matched it to an existing Table, so the identity it dedupes on is the
**physical binding** (connection + db + schema + db_table), not the TML name.

**Consequence:** lift-and-shift can only import a tenant's scaffolding Table if the target
Org does not already model that same physical table.

**This is the common case in production, not a fixture artefact.** My first reading of it
was wrong and the repo owner corrected it: tenants do **not** have to be segmented by
database or schema. A perfectly normal deployment has every tenant referencing the **same**
physical table with **RLS** ensuring each sees only its own rows. In that topology every
tenant's scaffolding Table shares one physical binding — with each other, and with the
published Model's Tables in the clean Org.

So this is not an edge case to check for; for an RLS-segmented fleet it blocks
lift-and-shift for **every** tenant, and it is the most likely of the three findings to
stop `apply` outright.

That the test cluster reproduces it (ORG1/ORG2/ORG3 all point at one physical table) is
therefore a *feature* of the fixture, not a flaw in it — it models the harder and more
common shape.

**What this forces.** Lift-and-shift assumes the scaffolding Table can be created in the
target Org. Where the binding already exists there, it cannot. Options, none yet chosen:

| Option | Note |
|---|---|
| Reuse the existing Table rather than creating one | The scaffolding exists only to carry references and is deleted at step 4, so binding the lifted Models to the target's *existing* Table may be sufficient — and removes the import entirely |
| Import with `create_new: false` and an explicit guid | Updates the existing Table rather than duplicating it. Risks mutating an object the clean Org depends on |
| Give the scaffolding a throwaway distinct binding | A view or alias per migration. Extra warehouse objects, but keeps the scaffolding genuinely disposable |

The first looks strongest and would *simplify* the design — but it changes step 1 from
"lift Tables + Models + content" to "lift Models + content, binding to Tables already
there", which needs its own verification. `ts migrate audit` must detect the collision
either way.

---

## 4. Reference resolution is fqn-then-name — the mechanism the design relies on

Visible in the failure text itself:

```
Error: Tables do not exist. - SPIKE_T4
Warning: No table with fqn d3a688f2-2543-4dcc-9907-b4cdb130c36b found for table_id SPIKE_T4
```

The importer tried the `fqn` (a source-Org GUID, dead in the target), failed, and fell
back to matching by `table_id` — the name. Two things follow:

- **The intra-batch remap mechanism exists and behaves as the design assumes.** A dead fqn
  degrades to a name match rather than aborting on the reference itself.
- **Names must be unique within the target Org**, since the fallback is by name. Worth
  stating as a precondition on `apply`.

This is why the architecture is not in question. §1–3 are preconditions in front of a
mechanism that appears to work.

---

## 5. Throughput

Small, but the shape is useful:

| Step | Calls | Wall clock |
|---|---|---|
| Export 3 objects (1 batched call) | 1 | 0.90s |
| Import 3 objects (1 batched call) | 1 | 1.00–1.73s |
| **Total** | **2** | **~2.0–2.6s** (≈0.6–0.9s/object) |

The important number is **2 API calls for 3 objects** — export and import both batch, so
calls scale with *batches*, not objects. That is the round-trip budget the design's
Efficiency & Scale section is built on, and it holds.

Per-object wall clock will not extrapolate from three objects; re-measure at realistic
batch sizes once §1–3 are solved.

---

## 6. Baseline restored

| Dimension | Baseline | Final |
|---|---|---|
| Orgs | Primary, ORG1, ORG2, ORG3 | identical (MIGSPIKE deleted) |
| Variable `apj_schema` | absent | absent |
| `T1_PUBLISH` publication | `[]` | `[]` |
| ORG1 owned Answers | none | none |
| ORG3 objects | no `SPIKE_*` | no `SPIKE_*` (ALL_OR_NONE created nothing) |
| `scan-sets` result | 1 of 80 blocked | unchanged |

`MIGSPIKE` was removed with `ts tenancy teardown --org MIGSPIKE --yes`, which was its first
end-to-end run against a real Org: the marker gate accepted it because `ts orgs create` had
stamped `[ts-tenancy-fixture]` into the description.

---

## 7. What this changes

**For the spec.** The four-step model (lift-and-shift → rename → repoint → delete) starts
one step too late. Add a step 0: *the clean Org must have its own connection*, and a rule
that every lifted Table's connection block is rewritten to it.

**For `ts migrate audit`.** It should report two new blockers, both cheap to detect and
both fatal at `apply` time if missed:

1. the target Org has no connection;
2. a tenant scaffolding Table shares a physical binding with something already in the
   target Org.

**For the build order.** The gating question is answered enough to proceed: the mechanism
works, so `apply` is worth building. It should be built against these three preconditions
rather than discovering them mid-implementation.

**Still unproven, and worth re-running once §1–3 are handled:** that a full batch binds
content to the newly-created Models. §4 makes it likely; it is not yet demonstrated.
