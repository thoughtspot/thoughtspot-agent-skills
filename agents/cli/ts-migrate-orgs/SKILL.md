---
name: ts-migrate-orgs
description: Move a tenant Org's bespoke content off its own Table/Model copies onto a governed published Model, then retire the old Org. Use when migrating tenants to the single-model publishing pattern, when a tenant's Answers and Liveboards must be repointed at published objects, or when sizing how many tenants a Sets dependency blocks.
---

# Migrate a tenant Org onto the published model

The counterpart to `ts-publish-orgs`. Publishing distributes a governed master **outward**
and changes nothing that already exists. This runs the other direction: it takes the
copies a tenant already has, moves their content onto the published master, and deletes
the originals.

That direction is why the whole skill is shaped around one question — **what is the state
if this stops halfway?** Every step below has an answer.

## Before you start: the one thing that makes this safe

**The tenant's source Org is never touched until the very end.** Not backed up and
modified — *not touched*. It is the rollback, for the entire migration, and it stays
authoritative until users are cut over.

Everything happens in a **fresh Org per tenant** (`ACME` → `ACME NEW`) that has no users
until the final step. So for the whole run the target is disposable: any failure is
abandoned by deleting the Org, and the tenant carries on in `ACME` having noticed nothing.

If you take one thing from this skill, take that. It is what makes each individual step
recoverable, and it is why there is no "restore from backup into production" path.

## Step 1 — Size the problem before planning anything

```bash
ts migrate scan-sets --all-models --source-org <TENANT> -o ./scan/ -p <profile>
```

Sets are a hard blocker: a Set creates a `COHORT_*` column that **does not appear in the
Model's TML at all**, and it blocks publishing the Model and every Answer and Liveboard on
it. Because it is invisible in TML, a lift-and-shift would **silently drop it** rather than
fail — nobody notices until a tenant asks where theirs went.

Read `scan/sets-scan.md`. It names the specific Answers and Liveboards, because "blocked"
alone is a dead end while "blocked by these four Answers" is something a tenant can act on.

A blocked tenant has three routes: retire the stale dependent content, rebuild it as a
filter, or wait for Sets support on published objects. `apply` refuses a Set-carrying
Model with **no override** — do not go looking for the flag.

**Do not batch a Sets-using tenant with clean ones.** Set usage is a risk class in the
wave plan, not a stop on the programme.

## Step 2 — Make sure the published Model exists in the target

Publish the governed Model into the target Org with `/ts-publish-orgs`, and use
`/ts-setup-tenancy` if the Org itself needs creating.

**No connection provisioning is needed.** Nothing is lifted, so nothing carries a
`connection` block. That was a precondition of the old architecture and is simply gone.

## Step 3 — Audit, and read the mapping

```bash
ts migrate audit --source-org <TENANT> --target-org <TARGET> --all-models -o ./plan/ -p <profile>
```

Produces `plan/column-mapping.csv`, one row per tenant column, and `audit-report.md`.

**Read the effort section first.** It tells you the size of the job, and it is *not* the
object count:

```
**47 dependent object(s)**, of which **16 need rewriting**.
31 are shielded by 3 View(s) and cost nothing.
```

Content built on a View is free: repointing the View preserves the names its dependents
see, so everything above it migrates for nothing. A View-heavy tenant is far cheaper than
its object count suggests, and this is the only place that shows it.

Two warnings in that section matter:

- **Content sitting directly on a Table.** It still needs rewriting, and a Model-level
  change never reaches it, so anything assuming Model-level coverage misses it.
- **Unresolved dependents.** Counted as chargeable, because an unresolved dependency is
  not a safe one to skip.

**Then fill the mapping.** Every `GAP_BLOCKER` row has a blank `published_column`: a
column the tenant's content uses that the published Model does not have. Ask the tenant;
do not guess. `MATCHED` rows need nothing.

## Step 4 — Read the plan before running it

```bash
ts migrate apply --source-org <TENANT> --target-org <TARGET> \
  -d ./plan --sets-scan ./scan/sets-scan.json --dry-run
```

Check the **mode** line. `updated in place` and `created fresh` have very different
rollbacks, and the plan says which you are about to run.

`apply` refuses the whole run — listing **every** problem, not the first — if a
`GAP_BLOCKER` is unmapped, a Model carries a Set, or the rename map is unusable.

## Step 5 — Apply

```bash
ts migrate apply --source-org <TENANT> --target-org <TARGET> -d ./plan --sets-scan ./scan/sets-scan.json
```

Three steps:

| Step | What it does |
|---|---|
| `backup` | Exports everything in scope before anything is written. All-or-nothing |
| `rewrite_views` | Repoints Views, **preserving what they expose**, so their content needs nothing |
| `rewrite_content` | Rewrites the chargeable Answers and Liveboards onto the published Model |
| `move_shielded` | Copies View-shielded content **without rewriting its columns** — new-Org runs only |
| `share_grants` | Re-establishes **group-level** sharing — new-Org runs only |

Each object's rewrite changes exactly two things: the data-source reference and the column
names. Progress is recorded in `plan/state.json`, so an interrupted run resumes with
`--resume`.

**Why `share_grants` exists.** **TML carries no sharing information at all** — no `share`,
`permission`, `principal`, `group` or `acl` key. So migrated content is authored by whoever
ran the migration and visible to **nobody else**. The migration completes, every check
passes, and not one tenant user can see anything.

That failure survives verification, because an admin sees objects regardless of sharing.
It surfaces only when a real tenant user logs in to an empty Org — possibly after the
source Org has been retired.

> **Not yet verified live.** The step runs and reports success, but on some Orgs the
> grants do not register for Answers and Liveboards -- `HTTP 204` with no grant applied
> (**BL-150**, cause not yet established). **Check the grants yourself after any new-Org
> migration**, and treat an admin-only check as not verified: an admin sees objects
> regardless of sharing.

Grants cover the **whole stack**, not just the content: the **published Model needs
explicit grants too**, because publishing it makes it *present*, not *visible*.

Grants are re-applied at **group** level. Groups are **per-Org principals**, so the target
Org needs a group of each name; a missing one is reported rather than skipped, because a
dropped grant is invisible until someone complains. Per-user grants are deliberately not
attempted: the users may not be in the target Org until cutover.

**Why `move_shielded` exists.** A View shields its content from the *column rewrite*, not
from the migration. In a **new-Org** run that content still has to exist over there, and
its `fqn` still points at the source View, which is dead in the target. Omitting it was
silent data loss — the tenant's Answer simply did not appear. In a **same-Org** run the
step is empty: the content stays put and the repointed View keeps working underneath it.

### The three topologies

The same command covers all three; only the write mode differs, and it is derived rather
than configured:

| | Content | Rollback |
|---|---|---|
| Same Org, same cluster | updated in place | **the backup only** — weakest |
| New Org, same cluster | created fresh | delete the Org |
| New Org, different cluster | created fresh | delete the Org |

Cross-cluster needs nothing extra. Tags, schedules and sharing are per-cluster though, so
they need re-establishing over there.

## Step 6 — Two refusals that are the system working

**"rewrite incomplete: N source column reference(s) survive."** The coverage gate caught a
field the rewrite does not know about. **Do not work around it.** Importing anyway
produces an object that loads and renders wrong, which is the failure this gate exists to
prevent. The message names the paths; they need adding to the transform.

**"resolves every Org to the SAME physical data and has NO row-level security."** The
tenant-isolation check.

**It only fires when the Orgs actually share rows.** Publishing binds a variable to the
db/schema/table fields, and that variable may hold a **different value per Org** — pointing
each tenant at its own database or schema. Where it does, the tenants are already
physically separated and the check stays quiet: RLS is not the mechanism keeping them
apart. Same for a per-principal variable (`USER_PROPERTY`), which resolves per user.

It fires only when every Org resolves to the *same* data, because then RLS is the **only**
separator and its absence means every tenant sees every other tenant's rows.

Three ways out, and the right one depends on the deployment: add RLS, point the Orgs at
different data via the publication variable, or `--allow-unfiltered-target` for a
deliberately single-tenant target. An **unreadable** check refuses too: not knowing how a
shared Model separates tenants is not the same as knowing it is safe.

## Step 7 — Aliases, once per WAVE

Per-Org column aliases live on the **Primary** Org's Model, and until delta load ships
there is no partial update: every append re-imports the whole document.

**So do this once per wave, never once per tenant.** Per-tenant, tenant *k* pays the cost
of all *k* before it — O(N²) across the fleet, and past 5 MB each import goes async at
10–15 minutes. At 50 columns that threshold lands around tenant 500.

It must also be serialised: two concurrent full-document writes clobber each other.

Use `/ts-object-model-alias` with `build --merge`. **Before merging, confirm the export
returned the aliases of every already-cut-over tenant.** A partial export silently drops
them, and those tenants' users see `String_1` where they saw `Region` — no error anywhere.
This is the one catastrophic step in the routine.

**Scope Org-wide with `group: TS_WILDCARD_ALL`.** And never leave a second pathway on the
same column: a user matching both a wildcard entry and a group entry sees the **base column
name**, not either alias — verified live, and true even when both aliases are identical. A
group scope does *not* override a wildcard. Mixed strategies across *different* columns are
fine. An empty group is rejected, so do not substitute a real group to get past that error.

**Verify in Search Data, an Answer, a Liveboard or Spotter.** Aliases are not rendered in the
Data Management app, so checking there shows base names for everything.

## Step 8 — Verify, then cut over

Cutover is deliberately **not** part of `apply`. Verify the target Org in its final state
first — as a **real non-admin user in that Org**, never as an admin. An admin session
bypasses RLS and sees objects a tenant user cannot, so an admin check proves nothing about
what the tenant will see.

Confirm: content opens, columns show the tenant's own names, and row counts are scoped.
Then move users and retire the source Org.

## If it goes wrong

```bash
ts migrate rollback --target-org <TENANT_NEW> -d ./plan --dry-run
ts migrate rollback --target-org <TENANT_NEW> -d ./plan
```

Deletes what the ledger records this run as creating. **In a new-Org run the source Org is
never touched**, so it remains authoritative until you cut over.

In a **same-Org** run there is nothing to delete: content was updated in place, and
`plan/backup/` is the rollback. That is why that topology is the weakest of the three.

Abandoning a new-Org attempt entirely? Delete the Org (`ts tenancy teardown`) — before
cutover it holds nothing but this migration's output.

## Reference

- **[Running a migration](references/running-a-migration.md)** — the complete operator
  reference: the sequence, what a human must decide, every check the tooling makes, the
  **Python API**, and every design decision with its rejected alternative
- [Decisions and gotchas](references/migration-notes.md) — the live findings behind each rule
- Design spec: `docs/superpowers/specs/2026-07-15-ts-org-migrate-design.md`
- Verifications: `docs/superpowers/verification/2026-07-27-ts-migrate-binding-resolution.md`,
  `2026-07-27-ts-migrate-rls-on-published.md`

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 2.2.0 | 2026-07-28 | `share_grants` grants the whole object stack bottom-up — Strict Object Mode drops a grant whose source is ungranted |
| 2.1.0 | 2026-07-28 | Add `share_grants` — TML carries no sharing, so migrated content was invisible to tenant users |
| 2.0.0 | 2026-07-28 | Rebuild around export/rewrite/import: three steps, no scaffolding, no connection provisioning |
| 1.1.0 | 2026-07-28 | Replace the dead BL-144 guard with the tenant-isolation check at the repoint |
| 1.0.0 | 2026-07-27 | Initial release |
