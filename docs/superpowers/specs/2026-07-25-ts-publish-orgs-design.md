# ts-publish-orgs — design

**Status:** DRAFT — blocked on live verification (see Open Items)
**Branch:** `wip/ts-publish-orgs`
**Date:** 2026-07-25

Publish Tables and Models from the Primary Org to target Orgs using ThoughtSpot's
Orgs Publishing feature, automating the variable definition and metadata
parameterization that publishing depends on.

---

## 1. What publishing is (and is not)

Publishing keeps **one** object in the Primary Org and makes it visible in target
Orgs. There is no copy, no new GUID, no GUID mapping file. Per-tenant variation
comes entirely from **variables** substituted at runtime.

| | Publishing | TML import / Git deployment |
|---|---|---|
| Object count | One master object | One copy per Org |
| GUIDs | Unchanged, no mapping needed | Requires GUID mapping |
| Per-tenant variation | Variables only | Arbitrary (full TML edit) |
| Target scope | Orgs within one instance | Any Org, any instance |
| Editability in target | Read-only | Fully editable |
| Git integration | Not supported | Supported |

Publishing is right for multi-tenant instances wanting standardised, reusable
content. Where a tenant needs customisation that variables cannot express, TML
deployment remains the correct tool. The two coexist; this skill does not
replace `ts-dependency-manager` or any conversion skill.

**The corollary that shapes this whole skill:** without variables, publishing
only works when every tenant reads the identical database, schema and table.
Variable definition is not a preliminary to publishing. It *is* the work.

---

## 2. API surface

All verified against `get-rest-api-reference` / `get-developer-docs-reference`
on 2026-07-25. Endpoint paths and request shapes below are from the spec, not
from a live call.

### 2.1 Variables

| Operation | Endpoint | Since |
|---|---|---|
| Create | `POST /api/rest/2.0/template/variables/create` | 26.4.0.cl |
| Search | `POST /api/rest/2.0/template/variables/search` | 26.4.0.cl |
| Assign values | `POST /api/rest/2.0/template/variables/{identifier}/update-values` | 26.4.0.cl |
| Delete | `POST /api/rest/2.0/template/variables/{identifier}/delete` | 10.14.0.cl (marked deprecated in favour of `/template/variables/delete`, which has no published schema — Open Item #3) |

Create request: `{type, name, is_sensitive?, data_type?}`.

Variable types:

| Type | Use | Notes |
|---|---|---|
| `TABLE_MAPPING` | `databaseName`, `schemaName`, `tableName` | The main type for this skill |
| `CONNECTION_PROPERTY` | `accountName`, `warehouse`, `user`, `password`, `role`, … | Needed when tenants sit in different accounts or warehouses |
| `CONNECTION_PROPERTY_PER_PRINCIPAL` | Per user/group connection properties | Disabled by default; requires ThoughtSpot Support to enable. Cannot parameterize `accountName`, `host`, `port` |
| `FORMULA_VARIABLE` | Formula and RLS logic via `ts_var()` | Out of scope here; owned by the `ts-variable-*` family |

Names must be **unique across all Orgs on the instance**. `data_type` applies to
`FORMULA_VARIABLE` only.

Value assignment request: `{operation, variable_assignment[]}` where each
assignment is `{assigned_values[], org_identifier?, principal_type?,
principal_identifier?, model_identifier?, priority?}`. Operations are `ADD`,
`REPLACE`, `REMOVE`, `RESET`. Returns 204.

For `TABLE_MAPPING` and `CONNECTION_PROPERTY`, `org_identifier` is the scope
that matters. The Primary Org is addressed as `primaryOrg` or Org 0.

### 2.2 Parameterization

| Operation | Endpoint | Since |
|---|---|---|
| Parameterize | `POST /api/rest/2.0/metadata/parameterize-fields` | 26.5.0.cl |
| Unparameterize | `POST /api/rest/2.0/metadata/unparameterize` | 26.5.0.cl |

`parameterize-fields` request:
`{metadata_type?, metadata_identifier, field_type, field_names[], variable_identifier}`

- `metadata_type`: `LOGICAL_TABLE` | `CONNECTION` | `CONNECTION_CONFIG`
- `field_type`: `ATTRIBUTE` (Logical Tables) | `CONNECTION_PROPERTY` (Connections)
- `field_names` for a Logical Table: `databaseName`, `schemaName`, `tableName`
- `field_names` for a Connection Config: `impersonate_user`

The singular `POST /metadata/parameterize` (`field_name`, 10.9.0.cl) is
deprecated. Use the plural form.

`unparameterize` is singular-field and **requires a `value`** to restore in place
of the variable. This is why the plan must record every original static value:
without it, rollback is impossible.

Equivalent TML form, for reference:

```yaml
table:
  name: Sales
  db: "${DATABASE}"
  schema: "${SCHEMA_VAR}"
  db_table: "${TABLE_VAR}"
```

Parameterizing default system tables is not supported.

### 2.3 Publish

| Operation | Endpoint | Since |
|---|---|---|
| Publish | `POST /api/rest/2.0/security/metadata/publish` | 26.5.0.cl |
| Unpublish | `POST /api/rest/2.0/security/metadata/unpublish` | 26.5.0.cl |

Publish request: `{metadata[{identifier, type}], org_identifiers[], skip_validation?}`
Unpublish request: `{metadata[], org_identifiers[], include_dependencies, force?}`

`type` is one of `LIVEBOARD`, `ANSWER`, `LOGICAL_TABLE`. **`LOGICAL_TABLE` covers
both Tables and Models.** Connections cannot be published.

Both require ADMINISTRATION role and TENANT scope. Publish returns 204 with no
body, so there is no per-object result to inspect.

Unpublish semantics:
- `include_dependencies: true` unpublishes dependencies not used by another
  published object
- `force: true` breaks all dependent objects in the target Orgs

### 2.4 Feature constraints

- Early Access. Requires 26.5.0.cl or later with Orgs enabled.
- Only cluster admins with all-Orgs access can publish.
- Primary Org to target Orgs only. No Org-to-Org.
- Published objects are read-only in targets and initially visible **only to
  that Org's admins**, who must share them onward.
- Git integration is not supported for published objects.
- Cohort publishing is not supported.
- Custom calendars with differing metadata across Orgs are not supported.

---

## 3. Gap analysis against ts-cli

Current version 0.97.0.

**Present:**

| Command | Endpoint |
|---|---|
| `ts orgs search` | `/orgs/search` |
| `ts variables search` | `/template/variables/search` (already requests `METADATA_AND_VALUES`, auto-paginates) |
| `ts variables set` | `/template/variables/{id}/update-values` with `REPLACE` |
| `ts variables remove` | same endpoint with `REMOVE` |

**Missing primitives:**

| Command | Endpoint |
|---|---|
| `ts variables create` | `/template/variables/create` |
| `ts variables delete` | `/template/variables/{id}/delete` |
| `ts metadata parameterize` | `/metadata/parameterize-fields` |
| `ts metadata unparameterize` | `/metadata/unparameterize` |
| `ts publish push` | `/security/metadata/publish` |
| `ts publish unpush` | `/security/metadata/unpublish` |

**Adjacent work in flight:** `feat/ts-org-migrate` adds optional `org_id`
org-scoped token auth to `client.py`. The verify and status steps here depend on
authenticating into each target Org, so that commit is a hard prerequisite. Land
it first or cherry-pick it.

---

## 4. Skill shape

Named `ts-publish-orgs`. This requires a **new `ts-publish-*` family** in
`.claude/rules/skill-naming.md`, justified in §7.

Scope for 1.0.0 is the **data layer only**: Tables and Models. Liveboards and
Answers use the identical publish call and are a later minor version. They
depend on the data layer being published first regardless.

The pipeline mirrors `ts-object-model-alias` (`export` → `translate` → `build` →
`import`) with a rollback arm borrowed from `ts-dependency-manager`:

```
ts publish export   →  ts publish resolve  →  ts publish build  →  ts publish apply  →  ts publish verify
   (discover)            (value matrix)        (plan + rollback)      (execute)          (round-trip)
                                                                           |
                                                                           v
                                                                    ts publish rollback
```

Each stage writes JSON to stdout and is pipeable, per `.claude/rules/ts-cli.md`.

### 4.1 `ts publish export {model_guid|table_guid}`

Walks the dependency closure (Model → Tables → Connection) and reads each
table's current static `db` / `schema` / `db_table` plus the connection's
properties.

Emits a **field variance report**. This is where the real analysis lives: it
clusters the N tables × 3 fields into the *minimum* viable variable set. Twenty
tables sharing one database and schema need **two** variables, not sixty. Tables
in a shared reference schema fall out as their own cluster. `tableName` usually
needs no parameterization at all, since tenant tables normally share a name.

```
{"model": {"guid","name","obj_id"},
 "tables": [{"guid","name","db","schema","db_table"}, ...],
 "connection": {"guid","name","type","properties":{...}},
 "clusters": [{"field":"schemaName","current_value":"SALES","tables":[guid,...],
               "suggested_variable":"sales_conn_schema","already_parameterized":false}, ...],
 "existing_variables": [...] }
```

`already_parameterized` makes the command safe to re-run on a partially
configured model, which is the add-a-tenant path.

### 4.2 `ts publish resolve`

Builds the per-Org value matrix. Sources mirror the alias skill's
`--source ai|file|db`, adapted to this problem:

| Source | Behaviour |
|---|---|
| `--source pattern` | Convention expansion, e.g. `--pattern "db={ORG_UPPER}_DB" --pattern "schema=SALES"`. Placeholders: `{ORG}`, `{ORG_UPPER}`, `{ORG_LOWER}`, `{ORG_ID}`. Zero input for convention-driven tenants. |
| `--source warehouse` | Introspect Snowflake or Databricks for the real per-tenant databases and schemas, fuzzy-match to Org names, present for confirmation. Reuses `ts-profile-snowflake` / `ts-profile-databricks` and `sv_introspect`. |
| `--source file` | CSV `org_name,variable_name,value`. Same shape convention as the alias CSV. |
| `--source db` | A `TS_PUBLISH_VARIABLES` governance table. `--init-table` emits the DDL, exactly as `ts alias translate --init-table` does. |
| `--source existing` | Reuse variables already on the instance. The re-publish and add-a-tenant path. |

It also **auto-names** variables (`{connection_slug}_db`, `{table_slug}_schema`)
and **collision-checks** every proposed name against `ts variables search`,
because names are unique instance-wide and `create` fails on a duplicate.

No AI source. Tenant database names cannot be invented, exactly as the alias
skill refuses `--source ai` for tenant renaming.

### 4.3 `ts publish build`

Turns the resolved matrix into a concrete, ordered plan plus a **rollback
record** capturing every original static value (mandatory, since
`unparameterize` demands a restore value).

```
{"variables_to_create": [{"name","type","is_sensitive"}, ...],
 "value_assignments":   [{"variable","org","value"}, ...],
 "parameterizations":   [{"metadata_type","metadata_identifier","field_type","field_names","variable"}, ...],
 "publish":             {"metadata":[...], "org_identifiers":[...]},
 "rollback":            [{"metadata_identifier","field_name","original_value"}, ...]}
```

### 4.4 `ts publish apply --input plan.json [--dry-run]`

Executes idempotently in order: create variables → assign values → parameterize
→ publish. `--dry-run` validates and prints without mutating. Existing variables
are reused rather than re-created. A confirmation gate sits before the publish
call.

### 4.5 `ts publish verify`

Authenticates into each target Org (needs the org-scoped token auth from
`feat/ts-org-migrate`), exports the Table and Model TML, and diffs the
substituted values against intent. Produces the same
Expected / Actual / Status table the alias skill produces.

### 4.6 `ts publish rollback --input plan.json`

Unpublishes, then unparameterizes each field back to its recorded static value.

---

## 5. Skill steps (SKILL.md outline)

Follows the `ts-object-model-alias` Step 0 convention: display the plan, wait for
confirmation, then proceed.

| Step | Name | Mode |
|---|---|---|
| 1 | Authenticate | auto |
| 2 | Select Model / Table(s) | you choose |
| 3 | Export dependency closure + field variance | auto |
| 4 | Review suggested variable clusters | you confirm (may edit) |
| 5 | Select target Orgs | you choose |
| 6 | Choose value source | you choose |
| 7 | Resolve the per-Org value matrix | auto |
| 8 | Review the matrix | you confirm (may edit) |
| 9 | Build plan + rollback record | auto |
| 10 | Apply: variables, values, parameterization | auto (checkpoint before) |
| 11 | Publish to target Orgs | you confirm |
| 12 | Verify per Org | auto |

Confirmation required at 2, 4, 5, 6, 8, 11 and the Step 10 checkpoint.

Object pickers at Step 2 must show the Owner column alongside name, GUID and
modified date, per the established convention across the TS skills.

---

## 6. Security constraints

`CONNECTION_PROPERTY` variables cover `user`, `password` and `role`. Per
`.claude/rules/security.md`, the skill must **never** accept those values in
conversation. They are created with `is_sensitive: true` and the user assigns
values from their own terminal, the same pattern `ts-profile-thoughtspot` uses
for tokens. The skill may confirm presence, never echo a value.

`ts variables search` returns assigned values. Output for a variable marked
sensitive must be masked before display.

---

## 7. Naming: why a new family

`.claude/rules/skill-naming.md` requires every skill to match a documented
family, and asks reviewers to push back on new ones. The case for
`ts-publish-*`:

- **Not `ts-object-*`.** That family is a single-object-scoped operation. This
  operates on a dependency closure (Model + N Tables + 1 Connection) and on
  instance-wide variables, then fans out across a set of Orgs. Nothing about it
  is single-object.
- **Not `ts-dependency-*`.** That family is documented as graph-*rewrite*
  (audit, remove-and-cascade, repoint). Publishing walks the graph but rewrites
  nothing in it.
- **Not `ts-variable-*`.** That family is "one specific platform variable
  end-to-end" (e.g. `timezone`). Here variables are generated dynamically, not
  known in advance.
- **Room to grow.** `ts-publish-liveboard` and `ts-publish-status` slot in
  naturally as the feature leaves Early Access.

Proposed row for the family table:

| # | Family | Pattern | Semantic | Members |
|---|---|---|---|---|
| 10 | `ts-publish-*` | `ts-publish-{target}` | Distribute a master object to a set of destinations without copying it, including the variable definition and parameterization that distribution requires. Second token is the destination class. | `ts-publish-orgs` |

Requires three changes in the same PR: the row above, a `FAMILY_PATTERNS` entry
in `tools/validate/check_skill_naming.py`, and a CLAUDE.md change-impact map
mention.

---

## 8. Open Items

All are spec-read, not live-verified. Every one goes into
`agents/cli/ts-publish-orgs/references/open-items.md` as UNVERIFIED before any
merge to main.

| # | Item | Why it matters |
|---|---|---|
| 1 | **Variable-to-field cardinality.** The docs' `TABLE_MAPPING` example assigns three values (`SALES_SCHEMA_A`, `SALES_DB_A`, `SALES_TABLE_A`) to a single `table_var` in one Org with `ADD`. Either variables are list-typed and positional, or the example is wrong. | Decides one-variable-per-field vs one-per-table. The single most important unknown; §4.1 clustering depends on it. |
| 2 | Does `parameterize-fields` reject a `CONNECTION_PROPERTY` variable on a `LOGICAL_TABLE` `ATTRIBUTE` field? | Determines whether type binding needs client-side validation. |
| 3 | Correct delete endpoint: `/template/variables/{identifier}/delete` is flagged deprecated in favour of `/template/variables/delete`, which has no published schema. | Blocks `ts variables delete`. |
| 4 | How does the Connection reach a target Org, given connections are not publishable? Implicit dependency grant, or must it pre-exist per Org? | Changes the prerequisite checklist and possibly the whole flow. |
| 5 | No API found for "what is published where". | Status and drift detection likely needs per-Org token auth plus metadata search. Enabled by the `feat/ts-org-migrate` org-scoped auth work. |
| 6 | Publish returns bare 204. What does a validation failure look like with `skip_validation: false`? | Needed for the error-handling table. |
| 7 | Org identifier form: is `Primary` / `primaryOrg` / `Org 0` interchangeable? | Affects value-scope construction throughout. |
| 8 | Does the target Org's exported TML show substituted values or the `${var}` form? | Step 12 verify is built on the assumption that it shows substituted values. |
| 9 | Is `obj_id` required on Tables and Models before publishing, or only for the TML-import path? | The docs list `obj_id` under TML portability prerequisites, not publishing. Publishing keeps GUIDs, so it is probably not required. |

**Instance prerequisite:** verification needs 26.5.0.cl+, Orgs enabled,
publishing EA switched on, and an account with all-Orgs admin. None of the usual
test instances (champ-staging, se-thoughtspot, ashok-direct-query,
champagne-master) are confirmed to meet this. Damian is identifying one.

---

## 9. Build order

1. Land or cherry-pick org-scoped token auth from `feat/ts-org-migrate`
2. Extend `.claude/rules/skill-naming.md` + `check_skill_naming.py` with the
   `ts-publish-*` family
3. `ts variables create` / `delete`
4. `ts metadata parameterize` / `unparameterize`
5. `ts publish push` / `unpush`
6. Resolve Open Items #1–#9 against a live instance
7. `ts publish export` (field variance clustering) — shape depends on #1
8. `ts publish resolve` (value matrix, all five sources)
9. `ts publish build` / `apply` / `verify` / `rollback`
10. `agents/cli/ts-publish-orgs/SKILL.md`
11. `tools/smoke-tests/smoke_ts_publish_orgs.py`
12. README.md, `agents/cli/SETUP.md`, `EXPECTED_DIVERGENCES` in
    `check_runtime_coverage.py` (CLI-only; publishing has no Snowsight analogue),
    CHANGELOG.md

Steps 3 to 5 are useful standalone and can ship ahead of the skill.
