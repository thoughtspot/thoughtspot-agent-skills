# Running a migration — the complete reference

Everything needed to migrate one tenant, in the order you need it. Three ways to drive it
(agent skill, CLI, Python), what a human has to decide, every check the tooling makes, and
why each design decision is what it is.

**Start here if you are running a migration.** `SKILL.md` is the guided path; this is the
detail behind it.

---

## 1. What a migration actually does

A tenant has its own Table and Model copies, and content built on them using its own
column names. The target state is that same content running on a single **governed
published Model**, whose columns have generic names.

For each content object, exactly **two things change**:

```
tables[].fqn        <tenant Model guid>  →  <published Model guid>
column references   "Segment"            →  "STRING_1"
```

That is the whole migration. Everything below is about doing it safely.

### Why it is a rewrite and not something cleverer

The original design lifted the tenant's Tables and Models into the target and renamed the
Model's columns once, letting the change cascade to dependents. That was O(columns) rather
than O(objects), and it does not work:

- **BL-148** — lifted scaffolding collides **by name** with the published objects, because
  `audit` pairs them by name and reference resolution is fqn-then-name.
- **BL-149** — the rename cascade is **asynchronous**: `answer_columns` updates
  immediately, `search_query` does not, so an export taken straight after a rename is
  internally inconsistent.

Underneath both: **content TML has no physical anchor.** A Liveboard references columns
purely by display name, including `table_columns[].column_id`, which is the display name
and not a `TBL::COL` binding. Only `tables[].fqn` is stable. There is no id-based path, so
the rewriting the old design existed to avoid was never avoidable.

---

## 2. Choose your topology

All three are the same command. Only the write mode differs, and it is **derived** rather
than configured, so there is no flag to set wrongly.

| | Content | Rollback | Cutover |
|---|---|---|---|
| **Same Org, same cluster** | updated in place (`guid` kept) | **the backup only** | none, users stay |
| **New Org, same cluster** | created fresh | delete the Org | move users |
| **New Org, different cluster** | created fresh | delete the Org | move users |

**Prefer a new Org.** The source Org then stays completely untouched and *is* your
rollback, for the whole migration, until you cut over. Same-Org is the weakest: you are
mutating live content and `plan/backup/` is the only way back.

> **Same-Org has one extra precondition: publish the master into the source Org first.**
> The Org will then hold **two** Models of the same name — its own and the master — which
> is correct and expected. It is easy to skip this step, because the Org already contains a
> same-named Model and there looks to be nothing to publish. `audit` reports `NO_TARGET`
> until you do. It no longer reports `READY` by comparing the Model with itself (BL-152).

**How the source and the target are told apart:** by **ownership**, not by name. The
tenant's Model is owned by the tenant Org; the master is owned by Primary. If two
same-named Models cannot be told apart, both `audit` and `apply` **refuse** rather than
guess — picking either wrong is silent, so there is no safe default.

**Cross-cluster needs nothing extra** — cluster is a property of the profile. But tags,
schedules and sharing are per-cluster and need re-establishing, and the per-Org aliases
live on the *target* cluster's Primary Model.

---

## 3. The sequence

### Step 1 — Size the Sets problem

```bash
ts migrate scan-sets --all-models --source-org <TENANT> -o ./scan/ -p <profile>
```

A Set creates a `COHORT_*` column that **does not appear in the Model's TML at all** and
blocks publishing the Model and everything on it. Because it is invisible in TML, a
migration would drop it **silently** rather than fail.

`apply` refuses a Set-carrying Model with **no override**. A blocked tenant retires the
dependent content, rebuilds it as a filter, or waits for Sets support.

### Step 2 — Make sure the published Model exists in the target

Publish it with `/ts-publish-orgs`; create the Org with `/ts-setup-tenancy` if needed.

**No connection provisioning is required.** Nothing is lifted, so nothing carries a
`connection` block.

### Step 3 — Audit  ← **a human must read this**

```bash
ts migrate audit --source-org <TENANT> --target-org <TARGET> --all-models -o ./plan/ -p <profile>
```

Produces `plan/column-mapping.csv`, `audit-report.md` and `audit-report.json`.

### Step 4 — Fill the column mapping  ← **the only step requiring human judgement**

Every `GAP_BLOCKER` row has a blank `published_column`:

```csv
model,tenant_column,tenant_column_id,published_column,status
Sales,PROD_ID,T2::PROD_ID,PROD_ID,MATCHED          ← resolved, leave alone
Sales,Segment,T2::STRING_1,,GAP_BLOCKER            ← YOU fill this in
Sales,Order Date,T2::DATE_1,,GAP_BLOCKER           ← YOU fill this in
```

**Ask the tenant what each gap column should map to. Do not guess.** A wrong mapping does
not error: the rewrite substitutes names across the whole document, so content silently
reads the wrong column and shows plausible but incorrect numbers.

### Step 5 — Read the plan

```bash
ts migrate apply --source-org <TENANT> --target-org <TARGET> \
  -d ./plan --sets-scan ./scan/sets-scan.json --dry-run
```

Check the **mode** line: `updated in place` and `created fresh` have very different
rollbacks.

### Step 6 — Apply

```bash
ts migrate apply --source-org <TENANT> --target-org <TARGET> \
  -d ./plan --sets-scan ./scan/sets-scan.json
```

| Step | What it does |
|---|---|
| `backup` | Exports everything in scope. All-or-nothing |
| `rewrite_views` | Repoints Views **preserving what they expose** |
| `rewrite_content` | Rewrites chargeable Answers and Liveboards |
| `move_shielded` | Copies View-shielded content, columns **unchanged** (new-Org runs only) |
| `share_grants` | Re-establishes **group-level** sharing — new-Org runs only |

Progress is in `plan/state.json`; resume with `--resume`.

**`HTTP 204` from a share call does not mean the grant landed.** Under Strict Object Mode a
grant on content whose source is ungranted is accepted and **silently dropped**, so grants
must be applied **bottom-up**: published Tables → published Model → Views → content. The
**published Model needs explicit grants** — publishing it makes it *present*, not *visible*,
and that half holds regardless of the mode.

Strict Object Mode is a **per-cluster setting**. Granting the stack is safe either way, so
nothing detects the mode — but if this symptom appears on a cluster with it **off**, look
for a different cause.

**Migrated content lands shared with nobody unless `share_grants` runs.** TML has no
sharing block, so the objects are authored by the migrating admin and invisible to the
tenant. An admin verifying the migration sees everything, which is why this failure
survives verification. Grants are re-applied at **group** level, against the target Org's
group of that name — so the target needs those groups (provision with `ts tenancy`).

**A View shields content from the column rewrite, not from the migration.** In a new-Org
run that content still has to be copied over and repointed at the newly-created View.
`move_shielded` runs last because it needs the View guids the previous step created. In a
same-Org run it is empty: the content stays where it is.

### Step 7 — Aliases, once per WAVE not per tenant

Per-Org aliases live on the **Primary** Org's Model with no partial update until delta load
(est. 26.10), so every append re-imports the whole document. Per-tenant that is O(N²)
across the fleet, and past 5 MB each import goes async at 10–15 minutes.

```bash
ts migrate aliases -m "{master_model}" --target-org ORG2 -d ./plan \
    --expect-org ORG1 -p "{profile}" \
  | ts alias build --merge \
  | ts alias import --model "{master_model_guid}" -p "{profile}"
```

Once per wave, serialised. `ts migrate aliases` derives the alias rows from the approved
`column-mapping.csv` — they are the inverse of the rename `apply` applied — and **refuses the
wave if the export is missing any Org named in `--expect-org`**. That is the check that used
to be prose telling you to confirm the export by eye; a partial export silently drops
already-cut-over tenants. `--first-wave` is the explicit alternative when none exists yet, and
one of the two is required, because a check that defaults to off is not a check.

Verified live 2026-07-28: with ORG2 already aliased, adding ORG1 preserved ORG2's entries and
added ORG1's, both `TS_WILDCARD_ALL`; the round-trip export confirmed all four entries; and
re-running produced a byte-identical document.

### Alias scoping — three things that will bite you

**Org-wide aliases use `group: TS_WILDCARD_ALL`.** That is what a tenant migration wants:
every user in the Org sees their own column names.

**An ambiguous alias resolves to the BASE column name.** Verified by live experiment,
four cases on four columns, checked as a real non-admin user:

| Column | Scopes | Rendered |
|---|---|---|
| `STRING_1` | wildcard only | `A_wildcard_only` |
| `STRING_2` | wildcard + group, **different** aliases | **`STRING_2`** — base name |
| `STRING_3` | wildcard + group, **identical** aliases | **`STRING_3`** — base name |
| `STRING_4` | group only | `D_group_only` |

So a group scope does **not** override a wildcard, and identical values do not save you.
Every entry stays individually valid, the import returns `OK`, and the export looks right —
the only symptom is tenants seeing generic names.

**Mixed strategies across *different* columns are fine.** Wildcard on some, group scopes on
others is legitimate; the rule bites only on one column carrying both.

> **Verify in Search Data, an Answer, a Liveboard or Spotter — nowhere else.** Aliases are
> **not** rendered in the Data Management app (an open development item as of 2026-07-28),
> and `metadata/answer/data` returns base names too. Checking either shows base names for
> *everything* and looks like total failure.

**An empty group is rejected** with `Group with name not found in org`. Do not substitute an
arbitrary real group to get past it — that is precisely how the overlap above gets created.

**`--merge` cannot remove an entry.** Correcting a wrong scope needs a full non-merge
rebuild, which **silently drops anything absent from your input**. Inventory what exists
before replacing.

### Step 8 — Verify, then cut over

Verify **as a real non-admin user in the target Org**. An admin bypasses RLS and sees
objects a tenant user cannot, so an admin check proves nothing.

---

## 4. Every check the tooling makes

### Refusals before anything is written

| Check | Why |
|---|---|
| `GAP_BLOCKER` with no mapping | The column is used by content and has nowhere to go |
| `SET_BLOCKER` | Cohort column blocks the Model. **No override** |
| Rename map not injective | Two columns onto one name |
| Target name already a column of that Model | Would produce two columns with one name |
| One tenant column mapped **differently in two Models** | The rewrite is document-wide and cannot honour both |
| No published Model of that name in the target | Nothing to migrate onto |

All problems are reported at once, not one per run.

### Refusals during the run

**Coverage gate — "rewrite incomplete: N source column reference(s) survive".**
Caught **before** the object is written. A partial rewrite imports cleanly and *renders
wrong*, so it must not be worked around. The message names the surviving paths; they need
adding to the transform.

**Tenant isolation — "resolves every Org to the SAME physical data and has NO row-level
security".**

RLS is only one way tenants are separated, and the check knows the difference:

| How the Orgs are separated | Detected from | RLS required? |
|---|---|---|
| **Physically** — the publication variable holds a different value per Org, so each reads its own db/schema/table | `TABLE_MAPPING` / `CONNECTION_PROPERTY` with >1 distinct value | **no** |
| **Per principal** — resolved per user or group | `USER_PROPERTY`, or any value scoped to a principal | **no** |
| **Shared** — every Org resolves to the same data | one distinct value across Orgs | **yes** — RLS is the only separator |
| **Unknown** — nothing readable | — | refuses; unreadable is not passed |

Demanding RLS where the platform already segments physically would be a false alarm, and
worse than no check: it teaches operators to pass `--allow-unfiltered-target` reflexively,
which destroys the check for the case where it genuinely matters.

Three ways out when it does fire: add RLS, point the Orgs at different data via the
publication variable, or `--allow-unfiltered-target` for a deliberately single-tenant
target.

### What the audit reports

- **Column classification** — `MATCHED`, `GAP`, `GAP_BLOCKER`, `BINDING_MISMATCH`
- **Effort** — the rewrite count, which is **not** the object count
- **Views to repoint** — named, because content on them is free
- **Table-based content** — warned separately: a Model-level change never reaches it
- **Unresolved dependents** — counted as chargeable, because an unresolved dependency is
  not safe to skip

---

## 5. Driving it from Python

The engine is pure functions with no I/O, so it can be embedded directly.

```python
from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.migrate import apply_exec, classify, discover
from ts_cli.migrate.apply_plan import (build_apply_plan, column_map, import_mode,
                                       new_ledger, pending_steps, record_completed,
                                       validate_apply)
from ts_cli.migrate.mapping import read_mapping
from pathlib import Path

source = ThoughtSpotClient(resolve_profile("prod"), org="12750490")
target = ThoughtSpotClient(resolve_profile("prod"), org="535312919")

rows = read_mapping(Path("./plan/column-mapping.csv"))
problems = validate_apply(rows)
if problems:
    raise SystemExit("\n".join(problems))

plan = build_apply_plan(
    {"source": "ACME", "target": "ACME NEW"},
    views=[], content=[{"guid": "ans-1", "name": "Revenue"}],
    columns=column_map(rows),
    target={"guid": "published-model-guid", "name": "Sales"},
    mode=import_mode("ACME", "ACME NEW", "prod", "prod"))

ledger = new_ledger({"source": "ACME", "target": "ACME NEW"})
ctx = apply_exec.Ctx(source, target, Path("./plan"), ledger)
for step in pending_steps(plan, ledger):
    record_completed(ledger, step["step"], apply_exec.RUNNERS[step["step"]](ctx, step))
```

### Just the transform, no orchestration

```python
from ts_cli.migrate.rewrite import rewrite_content, residual_references

out = rewrite_content(doc, {"Segment": "STRING_1"}, "published-guid", "Sales")

# ALWAYS check coverage before importing. A partial rewrite imports cleanly
# and renders wrong.
assert not residual_references(out, {"Segment": "STRING_1"})
```

### Just the classification

```python
deps = discover.dependents_through_views(source, model_guid)
docs = discover.export_dependents(source, deps)
refs = [classify.source_refs(d) for d in docs]
kinds = {g: classify.kind_of(st) for g, st in
         discover.subtypes_by_guid(source, {r for rs in refs for r in rs}).items()}
effort = classify.build_effort([
    classify.classify_dependent(d["guid"], d["name"], d["type"], r, kinds)
    for d, r in zip(deps, refs)])
print(effort["needs_rewrite"], "of", effort["dependents"])
```

**Two rules if you embed this:** always run `residual_references` before importing, and
never bypass `unfiltered_target_problem`. They are the two checks that prevent silent
damage.

---

## 6. Decisions, and why

| Decision | Why | Alternative rejected |
|---|---|---|
| Rewrite content, don't lift scaffolding | Content has no physical anchor, so rewriting is unavoidable (BL-148/149) | Lift + Model rename: collides by name, cascade is async |
| Views repointed, `name` preserved | Content on a View then needs nothing at all | Rewriting View dependents too: pointless work, only adds risk |
| Denylist for label paths, not an allowlist | A new *reference* field is handled automatically | Allowlist: silently misses whatever the platform adds |
| Coverage gate before writing | A partial rewrite imports cleanly and renders wrong | Checking after: the user finds it |
| Isolation check is **segmentation-aware** | RLS only separates tenants when they share physical data; publication variables may already segment them | Always requiring RLS: a false alarm that trains operators to pass the override reflexively |
| `client_state_v2` parsed, not string-replaced | Its column names sit in named fields beside a stable GUID | Substring pass: corrupts unrelated chart state |
| Write mode derived, not a flag | Three topologies, one code path | A flag an operator can set wrongly |
| Flat column map across Models | The rewrite is document-wide | Per-Model: does not match how the transform works |
| Prefer a new Org | Source stays untouched and is the rollback | Same-Org: only the backup |
| Aliases per wave | Per-tenant is O(N²) with async imports past 5 MB | Per-tenant: ~100 hours for a 1000-tenant fleet |
| No override on `SET_BLOCKER` | Silently dropping a Set is the failure Phase 0 exists to prevent | A force flag |

### The one thing needing human review when the platform changes

`LABEL_PATHS` in `rewrite.py`. Because the denylist rewrites everything else, a **new label
field** would be wrongly rewritten, and the coverage gate **cannot** catch that — it looks
like success. A new *reference* field is fine. Keep the list small and deliberate.

---

## 7. If it goes wrong

```bash
ts migrate rollback --target-org <TARGET> -d ./plan --dry-run
ts migrate rollback --target-org <TARGET> -d ./plan
```

Deletes what the ledger records this run as creating. In a **new-Org** run the source Org
was never touched. In a **same-Org** run there is nothing to delete: `plan/backup/` is the
rollback.

Abandoning a new-Org attempt entirely? Delete the Org — before cutover it holds nothing
but this migration's output.

---

## Related

- [`SKILL.md`](../SKILL.md) — the guided agent path
- [`migration-notes.md`](migration-notes.md) — the live findings behind each rule
- `docs/superpowers/specs/2026-07-28-ts-migrate-orgs-rewrite-design.md` — the design
- `tools/ts-cli/README.md` — CLI flag reference
