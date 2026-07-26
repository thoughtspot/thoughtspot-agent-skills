# `ts security column-rules` CLI design

**Date:** 2026-07-26
**Status:** DESIGN, approved. API surface confirmed against the SpotterCode MCP spec; behaviour still to be live-verified on `nebula-damian-alias`.
**Branch:** `feat/ts-security-column-rules`

Step 2 of the build order in
[`2026-07-26-ts-security-sharing-design.md`](2026-07-26-ts-security-sharing-design.md) §7.
Step 1 (`ts share`) shipped in PR #346, ts-cli v0.108.0.

This document covers the Column Security Rules (CSR) CLI only. It does not cover the
`ts-security-columns` skill (parent spec §4) or the migration additions (parent spec §5).

Programme context: [`docs/multi-tenancy-platform-plan.md`](../../multi-tenancy-platform-plan.md) §4.3.

---

## 1. What the MCP spec corrected

The parent spec's §2.4 recorded CSR from live probing. Reading the canonical spec
(`get-rest-api-reference`, operations `fetchColumnSecurityRules` and
`updateColumnSecurityRules`) surfaced four things that change the design, and explained one
of the live gotchas.

### 1.1 `group_access` has three operations, not one

The parent spec assumed CSR was purely declarative. It is not. Each column rule carries a
`group_access` array whose entries name an `operation`:

| Operation | Effect |
|---|---|
| `ADD` | Add the named groups to the column's access list |
| `REMOVE` | Remove the named groups from the column's access list |
| `REPLACE` | Replace the entire access list with the named groups |

So the endpoint supports both incremental and declarative use. This is the single most
consequential difference: it is what makes an idempotent `set` possible, and it means the
CLI has to choose which semantics it presents rather than inheriting one.

### 1.2 `update` takes one table per call

`identifier` is a scalar, not an array. Securing three tables is three calls, and the
"all or none" rollback the spec promises is per call, not per run. Multi-table work is
therefore a loop the CLI owns, with a failure mid-loop leaving earlier tables applied.
`fetch`, by contrast, takes `tables[]` and reads many in one call.

### 1.3 `column_security_rules` is a required field, which explains the `clear_csr` gotcha

The parent spec §2.4 recorded that `clear_csr: true` alone is rejected and that
`column_security_rules: []` must accompany it, noting the docs imply the flag suffices.
The request schema resolves it: `required: ["column_security_rules"]`. The rejection is
schema validation, not a bug, so it will not be "fixed" and the builder should always emit
both fields.

### 1.4 Per-column `is_unsecured`, distinct from whole-table `clear_csr`

`is_unsecured: true` on a single column rule marks that one column unprotected and drops
its group associations. `clear_csr: true` does it for every column on the table. The parent
spec only knew about the second, which would have made "unsecure one column" a
read-modify-write of the whole table.

### 1.5 Other spec facts worth recording

- Success on `update` is documented as **204 No Content**. Live probing saw 200. Treat any
  2xx as success and do not parse a body.
- The `fetch` response is documented inconsistently: the prose example shows a `data`
  envelope with camelCase keys (`columnSecurityRules`, `objId`, `sourceTableDetails`),
  while the response schema shows a bare array with snake_case keys
  (`column_security_rules`, `obj_id`, `source_table_details`). Parse both defensively, the
  way `_normalise_response` does elsewhere in the repo.
- Required permissions: `ADMINISTRATION`, or `DATAMANAGEMENT` (RBAC disabled), or
  `CAN_MANAGE_WORKSHEET_VIEWS_TABLES` (RBAC enabled).
- Both endpoints are Beta, 10.12.0.cl or later, and feature-flagged off by default
  (parent spec §2.6: `403 code 10023`).

---

## 2. Surface

Two chains over one plan. The plan JSON is the pivot, so each route has exactly one
executor and no command needs a `--route` flag.

```
ts security column-rules get      <table>... [--org O ...] [--profile P]
ts security column-rules export   <table>... [--org O] [--out DIR] [--profile P]
ts security column-rules resolve  --org O [--org O] --source uniform|file|db
                                  [--rule "COL=G1,G2" | --csv F | --table T]
                                  [--init-table] [--prune] [--profile P]
ts security column-rules apply    --input plan.json [--dry-run] [--allow-published] [--profile P]
ts security column-rules build    --input plan.json [--out DIR]
ts security column-rules import   --file F [--dry-run] [--profile P]
ts security column-rules set      --table T --rule "COL=G1,G2" [--add|--remove]
                                  [--org O] [--dry-run] [--profile P]
ts security column-rules clear    --table T [--column COL] [--org O] [--dry-run] [--profile P]
```

```
                       ┌─► apply                          POST /security/column/rules/update
resolve ──plan.json────┤
                       └─► build ──*_CSR.tml──► import    POST /metadata/tml/import
```

`get` and `export` are the two read shapes: current state as JSON, and the TML document
that parent spec §5.3 wants preserved into a migration plan directory. `set` and `clear`
are one-shot imperatives over a single table for interactive use, bypassing the manifest.

The shape mirrors the two shipped pipelines deliberately. `resolve` / `apply` and the
`--source uniform|file|db` conventions come from `ts share` and `ts publish`;
`export` / `build` / `import` comes from `ts alias`, which CSR resembles structurally
because both are sibling TML documents exported behind a flag.

### Group naming

`ts security` is a new top-level group. `column-rules` names the CSR mechanism explicitly
rather than the goal, because the goal ("column security") is equally true of `ts share`'s
column grants, which are the other mechanism. Parent spec §1 exists precisely to keep the
two apart, so the command names should not blur them. `security` leaves room for a sibling
`ts security rls` later.

---

## 3. Safety rules the tool enforces

Four decisions where the parent spec was silent. Two of them are the difference between
securing data and exposing it.

### 3.1 Named columns only; pruning is opt-in

A manifest is a set of instructions about the columns it names. It is **not** a full
desired state for the table. A column that is currently secured but absent from the
manifest is left alone.

`--prune` opts into `is_unsecured: true` for those columns. It is a flag on `resolve`, not
on `apply`, because pruning is a planning decision that has to be recorded in the plan for
`apply --dry-run` to display it and for the plan to stay the reviewable artefact.

`--prune` is therefore the one case where `resolve` must read current state: it calls
`/rules/fetch` per table to learn which columns are secured today, and diffs that against
the manifest. Without the flag, `resolve` needs no state read at all.

The reasoning is asymmetric risk. Under full-desired-state semantics an incomplete
manifest silently unsecures columns, which exposes data. Under named-columns semantics an
incomplete manifest leaves stale protection in place, which is visible and recoverable.
Only one of those two failure modes leaks, so the default guards against that one.

### 3.2 `set` is REPLACE per named column

What you pass is what the column ends up with, so `get` then `set` then `get` converges and
a `--dry-run` diffs cleanly against `get`. `--add` and `--remove` expose the incremental
operations for when that is genuinely what is wanted.

This is a deliberate narrowing of §1.1: all three operations are reachable, but the default
is the idempotent one, because the skill (parent spec §4) needs a converging "make it look
like this" call rather than a sequence whose result depends on prior state.

### 3.3 Published tables are refused, not attempted

CSR cannot be defined on published objects (parent spec §2, plan §4.3). `resolve` already
reads each table's `metadata_header` to turn a name into a GUID, so it records `orgIds` from
the same response and marks affected rows `CSR_BLOCKED`. `apply` refuses those rows unless
`--allow-published` is passed.

This is parent spec §5.1's `CSR_BLOCKER` at CLI level, and it costs one field off a call
already being made. It fails at plan time rather than mid-apply, matching the house style
that `apply` refuses before touching anything if the plan is incomplete.

### 3.4 Org scoping is asserted, not assumed

Reuses `_resolve_org_id` and `assert_org_context` from `ts_cli/commands/share.py` rather
than reimplementing them. `auth/token/full` silently ignores an Org name and falls back to
the caller's default Org, so a name is resolved to a numeric `org_id` and the session's
actual Org is read back before any mutating call. A mismatch stops the run. Applying a
tenant's column rules in the wrong Org while reporting success is the failure this prevents.

---

## 4. Manifest

```sql
TS_COLUMN_SECURITY_RULES (
    org_name     VARCHAR NOT NULL,
    table_name   VARCHAR NOT NULL,
    column_name  VARCHAR NOT NULL,
    group_name   VARCHAR NOT NULL,   -- empty string: secured, no group can see it
    PRIMARY KEY (org_name, table_name, column_name, group_name)
)
```

A row means: in Org `org_name`, on table `table_name`, column `column_name` is restricted,
and group `group_name` can see it.

`group_name` is `NOT NULL` with the empty string as the sentinel, rather than nullable.
A nullable column cannot sit in a primary key, and `TS_SHARE_GRANTS` sets the same
precedent of an all-`NOT NULL` key.

Only restricted columns appear. That is CSR's declaration model and the inverse of CLS,
which enumerates every visible column per group (parent spec §1). The two must not be
modelled the same way, and the manifest schemas should not be interchangeable.

A blank `group_name` is how a column is declared secured with no group able to see it.
Without the sentinel, that state is indistinguishable from a missing row.

`--source uniform` applies the same rules to every `--org`, which is the common case: the
pattern is the same restricted columns and the same group names in every tenant Org.
`file` and `db` express per-Org variation without enumerating identical rows per tenant.
`--init-table` emits the DDL, matching `ts share` and `ts publish`.

Per parent spec §4.1 the real producer of this manifest is `ts migrate audit`'s column-usage
map: used columns get granted, unused ones are withheld. That transform is the skill's
concern, not this CLI's. The CLI only has to consume the manifest shape.

---

## 5. Module layout

| File | Contents |
|---|---|
| `ts_cli/csr_plan.py` | Pure engine, no I/O. `parse_rule_flags`, `parse_rule_rows`, `build_csr_steps`, `build_update_payload`, `normalise_fetch_response`, `build_csr_tml`, `parse_csr_tml_export`, `diff_csr`, `explain_csr_error` |
| `ts_cli/commands/security.py` | The `security` Typer app plus the nested `column-rules` app; `get`, `export`, `set`, `clear`, and the shared substrate |
| `ts_cli/commands/security_planning.py` | `resolve`, `build`, `apply`, `import`, attached to the `column-rules` app |

The two-command-module split mirrors `share.py` and `share_planning.py`, which exists to
stay under the file-size gate (warn 500 lines, fail 1000). `security_planning.py` imports
the substrate from `security.py`, the way `share_planning.py` imports from `share.py`.

Registration in `cli.py`: `app.add_typer(security.app, name="security")`, with
`security_planning` added to the module import line so its commands attach at import time.

Everything decision-shaped lives in `csr_plan.py` and is unit-testable without a live
instance, per `.claude/rules/ts-cli.md`.

### Reuse rather than reimplementation

From `ts_cli/commands/share.py`: `_resolve_org_id`, `assert_org_context`, `_client_for_org`,
`_read_json_envelope`, `_search`, `_resolve_object`, `_table_columns`, `_profile_option`.

The TML export call follows `ts alias export`, which issues its own scoped
`metadata/tml/export` rather than routing through `ts tml export`:

```json
{"metadata": [{"identifier": "<table>", "type": "LOGICAL_TABLE"}],
 "export_associated": true,
 "export_fqn": true,
 "edoc_format": "YAML",
 "export_options": {"export_column_security_rules": true}}
```

Both `export_associated: true` and the export option are required (parent spec §2.4).
Import uses `create_new: false`, and the emitted document must carry its `table:`
reference or the import fails with code 14502.

---

## 6. Error translation

`explain_csr_error` covers the failures whose raw form points nowhere useful, returning
`None` when nothing matches so the caller surfaces the raw error rather than a misleading
paraphrase. Same contract as `explain_share_error`.

| Trigger | Translation |
|---|---|
| `403` with code `10023` | Column Security Rules are feature-flagged off on this cluster. Beta, 10.12.0.cl or later. The flag has to be enabled before any CSR call works, and this is not a permissions problem. |
| Code `14502`, `Referenced table with name  not found` | The CSR TML document is missing its mandatory `table:` reference. Note the doubled space in the platform message, which is the empty name interpolated. |
| `clear_csr` rejected without the array | `column_security_rules` is a required field, so `clear_csr: true` must ship with `[]`. Only reachable from a hand-rolled payload; the builder always emits both. |
| `403` without code `10023` | A genuine permissions problem: `ADMINISTRATION`, `DATAMANAGEMENT` (RBAC disabled), or `CAN_MANAGE_WORKSHEET_VIEWS_TABLES` (RBAC enabled). |

---

## 7. Testing

Unit tests in `tools/ts-cli/tests/`, no live instance required, covering every pure
function in `csr_plan.py`. The cases that matter most:

- `parse_rule_flags`: well-formed, multi-group, whitespace, missing `=`, empty column,
  empty group list, duplicate columns across flags.
- `build_update_payload`: `clear_csr: true` always accompanied by
  `column_security_rules: []`; REPLACE, ADD and REMOVE shapes; `is_unsecured` for a
  pruned or explicitly unsecured column; deterministic key and list ordering so a
  `--dry-run` plan is diffable.
- `normalise_fetch_response`: bare array and `data` envelope; snake_case and camelCase
  keys; a table with no rules; `groups: null`.
- `build_csr_tml`: the mandatory `table:` reference present; `info.type`;
  restricted-columns-only; filename derivation.
- `build_csr_steps`: one step per (org, table); `CSR_BLOCKED` marking; `--prune`
  producing `is_unsecured` entries only for columns absent from the manifest; stable sort.
- `explain_csr_error`: each row of §6, plus an unmatched body returning `None`.

---

## 8. Live verification plan

Cluster: profile `nebula-damian-alias`, Orgs Primary / ORG1 / ORG2 / ORG3, tables
T1 / T2 / T3_PUBLISH. CSR is enabled there.

Baseline `get` captured across all three tables before any change, restored afterwards,
and the before-and-after diff shown. Six things the spec cannot answer:

| # | Question | Why it matters |
|---|---|---|
| 1 | Does a per-column `REPLACE` leave other columns' rules untouched, or is `update` a whole-table replace? | Decides whether `set` must read-modify-write. The single most important unknown. |
| 2 | 204 with no body, or the 200 seen live? | Response handling |
| 3 | `fetch` response casing and envelope in practice | Which branch of `normalise_fetch_response` is real |
| 4 | `is_unsecured: true` on a column that was never secured | No-op or error; affects `--prune` safety |
| 5 | Does the CSR TML import into a different Org, given `table:` is by name? | Parent spec open item #3; blocks §5.3 preservation being useful |
| 6 | The refusal shape for CSR on a published object | Confirms §3.3 and gives §6 its fourth row |

Item 6 needs T2_PUBLISH actually published first, which also settles the `ts share`
verification record's open item about an end-to-end grant on a published object in a
tenant Org.

Folded in from that same record: whether a table-level `NO_ACCESS` clears existing column
grants. It is untested, it is why `ts share` refuses revoke-and-grant in one manifest, and
it is cheap to settle while on the cluster.

Findings land in `docs/superpowers/verification/2026-07-26-ts-security-column-rules-live-verification.md`.

---

## 9. Out of scope

- The `ts-security-columns` skill (parent spec §4). It is the decision layer over CLS and
  CSR both, and it needs this CLI to exist first.
- Migration additions (parent spec §5): `CSR_BLOCKER` as an audit status, `--csr
  map-to-cls`, CSR TML preservation into the plan directory. §3.3 implements the CLI-level
  refusal; the audit status is `ts migrate`'s work.
- The `ts migrate audit` transform that produces `TS_COLUMN_SECURITY_RULES` (parent spec
  §4.1). This CLI consumes the manifest; it does not generate it.
