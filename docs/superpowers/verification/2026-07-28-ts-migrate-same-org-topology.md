# Same-Org topology — live verification, and the Tier 1 bug it found

**Cluster:** `nebula-damian-alias` · **Date:** 2026-07-28 · **ts-cli:** v0.121.0

The third and last of the three supported topologies to be exercised: source Org ==
target Org, content updated in place. It failed on the first run, silently.

---

## 1. The bug (BL-152)

`ts migrate audit --source-org ORG1 --target-org ORG1` reported:

```
source_guid  : 9917a017-443c-4cf7-be81-2958d83997c8
target_guid  : 9917a017-443c-4cf7-be81-2958d83997c8      <- the SAME object
readiness    : READY
column_counts: {'MATCHED': 6, 'GAP': 0, 'GAP_BLOCKER': 0, 'BINDING_MISMATCH': 0}
```

`discover.find_model_by_name` returned the **first** name match. Same-Org is precisely the
topology where an Org holds **two** Models of one name — its own, and the master published
in from Primary — and it returned the tenant's own. The audit compared the source with
itself: every column matched itself, the rename map was empty, nothing to validate, `READY`.

**Why it is Tier 1: it is a no-op that passes every gate.** `apply` runs green and moves
nothing. Verification does not catch it either — the content still works, because it is
still on the Model it always used. It breaks at teardown, when the "old" Model is retired
and every Answer and Liveboard in the Org fails at once.

**The precondition worth naming.** Same-Org requires the master to be **published into the
source Org first**. That is easy to skip, because the Org already contains a same-named
Model and there appears to be nothing to publish. Before the fix, skipping it produced
`READY`. After the fix it produces `NO_TARGET`.

---

## 2. The same audit after the fix

Master `2a743be3` published into ORG1, same command:

```
source_guid  : 9917a017-443c-4cf7-be81-2958d83997c8
target_guid  : 2a743be3-b26e-43b7-9abc-47aa6486dc57      <- the published master
SAME OBJECT? : False
readiness    : NEEDS_MAPPING
column_counts: {'MATCHED': 4, 'GAP': 1, 'GAP_BLOCKER': 1, 'BINDING_MISMATCH': 0}
blockers     : ['Segment']
```

```
model,tenant_column,tenant_column_id,published_column,status
T2_PUBLISH_MODEL,PROD_ID,T2_PUBLISH::PROD_ID,PROD_ID,MATCHED
T2_PUBLISH_MODEL,CUSTOMER,T2_PUBLISH::CUSTOMER,CUSTOMER,MATCHED
T2_PUBLISH_MODEL,REGION,T2_PUBLISH::REGION,REGION,MATCHED
T2_PUBLISH_MODEL,AMOUNT,T2_PUBLISH::AMOUNT,AMOUNT,MATCHED
T2_PUBLISH_MODEL,Segment,T2_PUBLISH::STRING_1,,GAP_BLOCKER
T2_PUBLISH_MODEL,Order Date,T2_PUBLISH::DATE_1,,GAP
```

This is the correct comparison and it is **not** `READY`: ORG1's own Model renamed
`STRING_1` to `Segment` and `DATE_1` to `Order Date`, while the master exposes the physical
names. A human has to map them — which is exactly the decision the audit exists to surface,
and exactly what the self-pairing hid.

---

## 3. The plan, with the mapping filled in

`Segment → STRING_1`, `Order Date → DATE_1`, then `apply --dry-run`:

```
# Migration plan

**ORG1 → ORG1**

1. **backup**          — 4 object(s) exported before anything is written
2. **rewrite_views**   — 1 object(s), updated in place
3. **rewrite_content** — 2 object(s), updated in place
                           `Order Date` → `DATE_1`
                           `Segment`    → `STRING_1`
4. **move_shielded**   — none (same-Org run: shielded content stays where it is)
5. **share_grants**    — none (same-Org run: existing grants are untouched)

Mode: updating content in place; the backup is the only rollback.
```

Both same-Org derivations are right: nothing to move, and grants left alone because the
content never changed hands. **The rename map is itself the proof the apply path resolved
the master and not the source** — self-paired, that map is empty, which is what the original
run produced.

---

## 4. What was NOT run, and why

**The destructive same-Org `apply` was not executed.** It mutates ORG1's live content in
place, and ORG1 is the source side of the only live fixture — the one that has now caught
four real bugs. Repointing its content onto the master consumes that, and the backup is the
only way back. It is one command when wanted:

```bash
ts migrate audit --source-profile nebula-damian-alias --target-profile nebula-damian-alias \
  --source-org ORG1 --target-org ORG1 \
  --model 9917a017-443c-4cf7-be81-2958d83997c8 --out-dir ./sameorg
# then set published_column: Segment -> STRING_1, Order Date -> DATE_1
ts migrate apply --source-profile nebula-damian-alias --target-profile nebula-damian-alias \
  --source-org ORG1 --target-org ORG1 --plan-dir ./sameorg
```

Everything up to the write is verified. What an actual run would add is evidence that an
in-place `--no-create-new` import of rewritten content behaves like the create-fresh path —
worth having, but not worth the fixture without the owner's say-so.

---

## 5. Cluster state left behind

**The master `2a743be3` is published into ORG1 as well as ORG2, deliberately.** It is the
precondition for the remaining step above, so it has been left in place rather than
reverted. `apj_schema` has values for Primary/ORG1/ORG2 (all `ALIAS_TESTS`).

Nothing was written to any object: the run stopped at `--dry-run`. To return ORG1 to its
pre-test state:

```bash
ts publish unpush 2a743be3-b26e-43b7-9abc-47aa6486dc57 --org ORG1 \
  -t LOGICAL_TABLE -p nebula-damian-alias
```

---

## 6. Still untested

| Gap | What it needs |
|---|---|
| Same-Org `apply` (the write) | The owner's go-ahead — see §4 |
| Cross-cluster topology | A second cluster with the master published there |
| `client_state_v2` rewriting | A chart customised in the UI; TML-created charts carry no such blob |
| Published Model **with** RLS | The happy path through the tenant-isolation check |
| The per-wave alias step | Not built. Its count assertion is known insufficient — it also needs the scope-overlap check (PR #391) |
