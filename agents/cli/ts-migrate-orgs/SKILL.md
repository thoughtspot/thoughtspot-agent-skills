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

## Step 2 — Provision the target Org and its connection

The clean Org needs **its own connection, named exactly as the source Org's**.

Connection names are per-Org (verified live), so `ACME NEW` may hold an `APJ_ACME` while
`ACME` still does — and then every lifted Table's TML resolves **unchanged**. A different
name still works; `apply` rewrites one field per Table. **No connection at all is fatal**,
because publishing a Table into an Org does *not* give that Org a usable connection.

Use `/ts-setup-tenancy` or `ts tenancy apply`. Provision the connection yourself — it needs
warehouse credentials, which must never pass through this conversation.

Then publish the governed Model into the new Org with `/ts-publish-orgs`.

## Step 3 — Audit, and read the mapping

```bash
ts migrate audit --source-org <TENANT> --target-org <TENANT_NEW> --all-models -o ./plan/ -p <profile>
```

Produces `plan/column-mapping.csv`, one row per tenant column, and `audit-report.md`.

**This is the step a human must actually read.** Every `GAP_BLOCKER` row has a blank
`published_column` for you to fill: a column the tenant's content uses that the published
Model does not have. Ask the tenant what it should map to; do not guess. `MATCHED` rows are
already resolved and need nothing.

Check the three target-side findings in the report: no connection in the target (fatal), a
connection name that differs from the source's (a warning — it triggers the rewrite path),
and a scaffolding Table colliding on the same connection (fatal, but unreachable in the
per-tenant-Org topology).

## Step 4 — Read the plan before running it

```bash
ts migrate apply --source-org <TENANT> --target-org <TENANT_NEW> \
  -d ./plan --sets-scan ./scan/sets-scan.json --dry-run
```

Every step is destructive in someone's Org. `--dry-run` prints the ordered plan and writes
nothing. Read it, then drop `--dry-run`.

`apply` refuses the run outright — listing **every** problem, not the first — if a
`GAP_BLOCKER` is unmapped, a Model carries a Set, or the rename map is unusable.

## Step 5 — Apply

```bash
ts migrate apply --source-org <TENANT> --target-org <TENANT_NEW> -d ./plan --sets-scan ./scan/sets-scan.json
```

| Step | What it does |
|---|---|
| `backup` | Exports everything in scope before anything is written. All-or-nothing |
| `lift_scaffolding` | Tenant Tables + Models into the target as **one batch**, so intra-batch references remap |
| `lift_content` | Views → Answers → Liveboards, in that order |
| `rename` | Tenant column names → published names, **once per column** |
| `repoint` | Content moved off the scaffolding onto the published Model |
| `cleanup_*` | Scaffolding deleted: Models, then Tables, then the connection |

Progress is recorded in `plan/state.json`, so an interrupted run resumes with `--resume`
instead of redoing work.

**The rename is the clever part and worth understanding.** Editing only `columns[].name`
(keeping `column_id`) is an in-place update, so it cascades to every dependent Answer and
Liveboard automatically. That is what makes the whole approach O(columns) instead of
O(objects) — and it is also why a *wrong* mapping is dangerous: it silently repoints real
content at the wrong column rather than erroring. Which is why step 3 is a human read.

## Step 6 — Two outcomes that look like errors and are not

**A scaffolding Model refuses to delete.** This is the **missed-repoint check working**. By
cleanup, the repoint has run and nothing should reference the scaffolding; dependents mean
content was left behind. Find it. Deleting past this orphans that content — and it is
precisely why cleanup is surgical rather than a wholesale Org drop, which would take the
un-repointed content silently.

**An RLS assertion fails after a rename.** A malformed `rls_rules` block imports with
`status_code: OK`, is discarded, *and destroys the rule already on the table* (**BL-144**).
`apply` re-reads and asserts, so this failure means the table is genuinely **unfiltered
right now**. Restore it from `plan/backup/` before doing anything else.

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

Deletes what the ledger records this run as creating. **The source Org is never touched.**

Abandoning the attempt entirely? Delete the whole Org (`ts tenancy teardown`) — before
cutover it holds nothing but this migration's output.

## Reference

- [Decisions and gotchas](references/migration-notes.md) — the findings behind the step order
- Design spec: `docs/superpowers/specs/2026-07-15-ts-org-migrate-design.md`
- Verifications: `docs/superpowers/verification/2026-07-27-ts-migrate-binding-resolution.md`,
  `2026-07-27-ts-migrate-rls-on-published.md`

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-07-27 | Initial release |
