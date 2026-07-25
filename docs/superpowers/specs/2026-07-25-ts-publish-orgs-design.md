# ts-publish-orgs — design

**Status:** IN PROGRESS — API surface live-verified; CLI steps 1-7 shipped (ts-cli v0.100.0), skill not yet authored
**Branch:** `wip/ts-publish-orgs`
**Date:** 2026-07-25
**Verification instance:** `nebula-damian-alias` (SW/DEV build, Orgs enabled: Primary + ORG1/ORG2/ORG3, Snowflake connections `APJ` and `SnowflakeConnection`). All endpoints below confirmed present and exercised live on 2026-07-25.

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

Publishing suits multi-tenant instances wanting standardised, reusable content.
Where a tenant needs customisation variables cannot express, TML deployment
remains correct. The two coexist.

**The corollary that shapes this skill:** variable definition is not a
preliminary to publishing. It *is* the work. Verified live: an object with no
variable in its dependency tree **cannot be published at all** with validation
on (§2.5).

---

## 2. API surface

### 2.1 Variables

| Operation | Endpoint | Notes |
|---|---|---|
| Create | `POST /api/rest/2.0/template/variables/create` | Returns the variable object with `id` |
| Search | `POST /api/rest/2.0/template/variables/search` | `response_content: METADATA_AND_VALUES` for values |
| Assign values | `POST /api/rest/2.0/template/variables/{identifier}/update-values` | 204 on success |
| Delete | `POST /api/rest/2.0/template/variables/delete` | **Batch.** Takes `identifiers: [String!]!`. Use this, not the deprecated per-identifier path |

Create request: `{type, name, is_sensitive?, data_type?}`.

| Type | Use | Value shape (verified) |
|---|---|---|
| `TABLE_MAPPING` | `databaseName`, `schemaName`, `tableName` | Scalar `value`. **Rejects multiple values** |
| `CONNECTION_PROPERTY` | `accountName`, `warehouse`, `user`, `password`, `role` | Scalar `value` |
| `CONNECTION_PROPERTY_PER_PRINCIPAL` | Per user/group connection properties | Support-gated, off by default. Cannot cover `accountName`, `host`, `port` |
| `FORMULA_VARIABLE` | Formula and rule logic via `ts_var()` | `value_list` (array). Multi-value permitted |

Names must be **unique across all Orgs**. `data_type` applies to
`FORMULA_VARIABLE` only.

Value assignment: `{operation, variable_assignment[]}` where each assignment is
`{assigned_values[], org_identifier?, principal_type?, principal_identifier?,
model_identifier?, priority?}`. Operations `ADD` / `REPLACE` / `REMOVE` / `RESET`.

Note the asymmetry: the request field is always the array `assigned_values`, but
for `TABLE_MAPPING` it must contain exactly one element. Passing more returns
`code 10002`, `"This variable type can only take a single value"`.

### 2.2 Parameterization

| Operation | Endpoint |
|---|---|
| Parameterize | `POST /api/rest/2.0/metadata/parameterize-fields` |
| Unparameterize | `POST /api/rest/2.0/metadata/unparameterize` |

`parameterize-fields`:
`{metadata_type?, metadata_identifier, field_type, field_names[], variable_identifier}`

- `metadata_type`: `LOGICAL_TABLE` | `CONNECTION` | `CONNECTION_CONFIG`
- `field_type`: `ATTRIBUTE` (Logical Tables) | `CONNECTION_PROPERTY` (Connections)
- Logical Table field names: `databaseName`, `schemaName`, `tableName`
- Connection Config field names: `impersonate_user`

The singular `POST /metadata/parameterize` is deprecated. Use the plural form.

`unparameterize` is singular-field and **requires a `value`** to restore. This is
why the plan must record every original static value: without it, rollback is
impossible.

Resulting TML form:

```yaml
table:
  name: T1_PUBLISH
  db: "${zz_pubtest_db}"
  schema: "${zz_pubtest_schema}"
  db_table: T1_PUBLISH
```

Parameterizing default system tables is not supported.

### 2.3 Publish

| Operation | Endpoint |
|---|---|
| Publish | `POST /api/rest/2.0/security/metadata/publish` |
| Unpublish | `POST /api/rest/2.0/security/metadata/unpublish` |

Publish: `{metadata[{identifier, type}], org_identifiers[], skip_validation?}`
Unpublish: `{metadata[], org_identifiers[], include_dependencies, force?}`

`type` is `LIVEBOARD` | `ANSWER` | `LOGICAL_TABLE`. **`LOGICAL_TABLE` covers both
Tables and Models.** Both endpoints return 204 with no body.

`org_identifiers` accepts the Org **name** (`"ORG1"`), the numeric **id as a
string** (`"535312919"`), and `"Primary"`. An unknown value returns
`INVALID_ORG`.

### 2.4 Feature constraints

- Requires Orgs enabled. Only cluster admins with all-Orgs access can publish.
- Primary Org to target Orgs only.
- Published objects are read-only in targets and initially visible **only to
  that Org's admins**, who must share them onward.
- Connections cannot be published directly.
- No Git integration on published objects. No cohort publishing. No per-Org
  custom calendars.

### 2.5 Verified behaviour

Everything in this section was exercised live on `nebula-damian-alias` against
the `T1/T2/T3_PUBLISH` tables (APJ connection, `AGENT_SKILLS.ALIAS_TESTS`). All
test artefacts were removed afterwards; the cluster is back to its prior state.

**One variable holds one value per scope.** `field_names[]` is a batch
convenience only: binding one variable to `["databaseName","schemaName"]` writes
the *same* token into both fields, which is almost never intended. The correct
model is **one variable per distinct value**, shared by every table needing that
value. Twenty tables in one schema need one schema variable, not twenty. The
published `TABLE_MAPPING` doc example (three values to one variable) is wrong and
the API rejects it.

**Variable type binding is enforced.** Binding a `CONNECTION_PROPERTY` variable
to a `LOGICAL_TABLE` `ATTRIBUTE` field returns `code 10002`,
`"Parameterization of given Object cannot be done with Variable of type:
CONNECTION_PROPERTY"`.

**Publish fails closed on incomplete variable coverage.** Publishing an object
to an Org where one of its variables has no value returns `code 13151`:

```
Variable dcc65c68-7b37-4d25-b8ad-5b6f806c6964 not defined for orgs [443705360]
in which object d2c12c11-6560-4810-96b8-4b902bbb82dc is to be published
```

This is the strongest safety net in the feature. Note it names the variable and
Org by **GUID and numeric id**, so the skill must resolve those back to names
before showing the user. Assigning the missing value and re-publishing succeeds.

**An unparameterized object cannot be published.** With validation on it returns
`code 13151`, `"No template variable node found in the dependency tree for
object {guid}"`. `skip_validation: true` publishes it regardless, leaving the
target Org reading the Primary Org's hardcoded database and schema. See §5 for
why the skill should not use that flag.

**The Connection is granted to the target Org automatically.** After publishing
a table, the APJ connection's `orgIds` gained the target Org, despite connections
being unpublishable. No pre-existing connection is needed in the target.

**`metadata_header.orgIds` is the publication registry.** A published object's
`orgIds` lists Primary plus every Org it is published to (`[0, 12750490]`).
Readable from the Primary Org with an ordinary `metadata/search`, so
publication status needs **no per-Org authentication**.

**Unpublish does not retract the Connection unless asked.** With
`include_dependencies: false` the object is retracted but the Connection stays
granted to the target Orgs. `include_dependencies: true` retracts both. Rollback
must therefore use `true`.

**Parameterizing breaks the SOURCE object unless the owner Org also has a value.**
Found by publishing `T1_PUBLISH` to ORG3 with values assigned for ORG3 only. The
publish succeeded, but a `searchdata` query in the Primary Org then failed with
`SQL compilation error: Object 'T1_PUBLISH' does not exist or not authorized`:
`${apj_db}.${apj_schema}` resolved to nothing, collapsing the FQN to a bare table
name. Assigning Primary values restored it immediately. ThoughtSpot's publish
validation checks only the TARGET orgs, so nothing on the platform side catches
this. `ts publish resolve` therefore always includes the owner Org and always
gives it the field's current value, never a pattern expansion.

**`obj_id` is auto-populated** (e.g. `T1_PUBLISH-4be2cc25`) on all tables
regardless of publish state. Nothing for the skill to assign.

---

## 3. Gap analysis against ts-cli

Current version 0.97.0.

**Present:** `ts orgs search`, `ts variables search` (already requests
`METADATA_AND_VALUES`, auto-paginates), `ts variables set` (`REPLACE`),
`ts variables remove`.

**Missing primitives:**

| Command | Endpoint |
|---|---|
| `ts variables create` | `/template/variables/create` |
| `ts variables delete` | `/template/variables/delete` (batch `identifiers[]`) |
| `ts metadata parameterize` | `/metadata/parameterize-fields` |
| `ts metadata unparameterize` | `/metadata/unparameterize` |
| `ts publish push` | `/security/metadata/publish` |
| `ts publish unpush` | `/security/metadata/unpublish` |
| `ts publish status` | `metadata/search`, read `metadata_header.orgIds` |

**Adjacent work:** `feat/ts-org-migrate` adds optional `org_id` org-scoped token
auth to `client.py`. Now a **soft** dependency, not a hard one: `orgIds` makes
status work without it. It is still needed for Open Item #1 (verifying
substitution inside a target Org by TML export). Note `POST /auth/session/org`
does **not** exist on this build.

---

## 4. Skill shape

Named `ts-publish-orgs`, requiring a new `ts-publish-*` family in
`.claude/rules/skill-naming.md` (justified in §7).

Scope for the **skill's** 1.0.0 is the data layer: Tables and Models. The **CLI**
covers Liveboards and Answers as well, because it costs almost nothing to do so:
they carry no parameterizable fields of their own, so `export` simply walks down
to the Tables beneath them and `apply` publishes the root with its own type. A
Liveboard whose data layer is already wired needs only
`ts publish push --type LIVEBOARD`.

Pipeline mirrors `ts-object-model-alias`, with a rollback arm from
`ts-dependency-manager`:

```
ts publish export  →  ts publish resolve  →  ts publish build  →  ts publish apply  →  ts publish verify
   (discover)           (value matrix)        (plan + rollback)      (execute)          (round-trip)
                                                                          |
                                                                          v
                                                                   ts publish rollback
```

Each stage writes JSON to stdout and is pipeable, per `.claude/rules/ts-cli.md`.

### 4.1 `ts publish export {guid}`

Walks the dependency closure (Model → Tables → Connection), reads each table's
static `db` / `schema` / `db_table` and the connection properties, and emits a
**field variance report** clustering fields by distinct current value. Given
§2.5, a cluster maps one-to-one onto a variable.

```
{"model": {"guid","name","obj_id"},
 "tables": [{"guid","name","db","schema","db_table"}, ...],
 "connection": {"guid","name","type","properties":{...}},
 "clusters": [{"field":"schemaName","current_value":"ALIAS_TESTS",
               "tables":[guid,...],"suggested_variable":"apj_schema",
               "already_parameterized":false}, ...],
 "existing_variables": [...],
 "published_to": [0]}
```

`already_parameterized` and `published_to` (from `metadata_header.orgIds`) make
the command safe to re-run on a partially configured model, which is the
add-a-tenant path.

### 4.2 `ts publish resolve`

Builds the per-Org value matrix.

| Source | Behaviour |
|---|---|
| `--source pattern` | Convention expansion, e.g. `--pattern "db={ORG_UPPER}_DB"`. Placeholders `{ORG}`, `{ORG_UPPER}`, `{ORG_LOWER}`, `{ORG_ID}` |
| `--source uniform` | One value replicated to every target Org. The shared-table case (§5) |
| `--source warehouse` | Introspect Snowflake or Databricks for real per-tenant databases and schemas, fuzzy-match to Org names, confirm interactively. Reuses `ts-profile-*` and `sv_introspect` |
| `--source file` | CSV `org_name,variable_name,value` |
| `--source db` | A `TS_PUBLISH_VARIABLES` governance table. `--init-table` emits DDL, as `ts alias translate --init-table` does |
| `--source existing` | Reuse instance variables. The re-publish and add-a-tenant path |

Also auto-names variables and **collision-checks every proposed name** against
`ts variables search`, since names are instance-unique and `create` fails on a
duplicate.

Critically, it emits a **coverage matrix** of variable × target Org and refuses
to proceed on a gap. The platform enforces this anyway (§2.5), but catching it
here produces a readable error naming the variable and Org, rather than the
platform's GUID-and-numeric-id message.

No AI source. Tenant database names cannot be invented, exactly as the alias
skill refuses `--source ai` for tenant renaming.

### 4.3 `ts publish build`

Emits an ordered plan plus a **rollback record** capturing every original static
value (mandatory, since `unparameterize` demands a restore value).

```
{"variables_to_create": [{"name","type","is_sensitive"}, ...],
 "value_assignments":   [{"variable","org","value"}, ...],
 "parameterizations":   [{"metadata_identifier","field_names","variable"}, ...],
 "publish":             {"metadata":[...], "org_identifiers":[...]},
 "rollback":            [{"metadata_identifier","field_name","original_value"}, ...]}
```

### 4.4 `ts publish apply --input plan.json [--dry-run]`

Executes in order: create variables → assign values → parameterize → publish.
Idempotent; existing variables are reused rather than re-created. Confirmation
gate before the publish call. Never sets `skip_validation` (§5).

### 4.5 `ts publish verify`

Two levels. **Status** reads `metadata_header.orgIds` from the Primary Org and
confirms every target is present, needing no extra auth. **Substitution** (Open
Item #1) exports the TML inside each target Org and diffs against intent; this
needs the org-scoped token auth from `feat/ts-org-migrate`.

### 4.6 `ts publish rollback --input plan.json`

Unpublishes with `include_dependencies: true` (required to retract the
Connection grant, §2.5), then unparameterizes each field back to its recorded
static value.

---

## 5. Shared-table pattern and `skip_validation`

When every Org reads the identical physical table, there is no per-Org
variation to express. Two routes exist; only one is acceptable.

**Use a variable with the same value for every Org** (`--source uniform`).
Verified: publishes cleanly with validation on.

**Do not use `skip_validation: true`.** It publishes an unparameterized object,
but:

1. It is all-or-nothing. It disables every validation in the call, so a batch
   containing one shared table and one genuinely per-tenant table loses the
   coverage check on the second one too.
2. It disables the single best safety net in the feature (§2.5).
3. It makes future divergence structural. With a variable in place, moving one
   tenant to its own schema is one `update-values` call. Without one, the table
   must be parameterized after it is already published.

The cost of the uniform variable is one variable and N identical assignments,
which `resolve --source uniform` generates.

The skill therefore never sets `skip_validation`. If a user asks for it, it
explains the above and offers `--source uniform` instead.

**Assumption, out of scope:** in the shared-table pattern, per-tenant data
separation is provided by row-level security configured independently of this
skill. This skill neither creates nor validates RLS rules.

Setting RLS via variables belongs in a **separate skill**. It shares the
variables API but nothing else: it uses `FORMULA_VARIABLE` rather than
`TABLE_MAPPING`, targets RLS rules on a Table rather than table-mapping fields,
and has no publish step. Two facts verified here are useful groundwork for it:
`FORMULA_VARIABLE` scopes to an Org (not only to a user or Model), and it
returns `value_list` rather than a scalar, so a multi-value assignment becomes an
`IN` clause in the generated predicate. Both are recorded in §2.1.

---

## 6. Skill steps (SKILL.md outline)

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
| 8 | Review the matrix + coverage check | you confirm (may edit) |
| 9 | Build plan + rollback record | auto |
| 10 | Apply: variables, values, parameterization | auto (checkpoint before) |
| 11 | Publish to target Orgs | you confirm |
| 12 | Verify status (and substitution where available) | auto |

Confirmation required at 2, 4, 5, 6, 8, 11 and the Step 10 checkpoint.

Object pickers at Step 2 must show the Owner column alongside name, GUID and
modified date, per the established convention across the TS skills.

---

## 7. Security constraints

`CONNECTION_PROPERTY` variables cover `user`, `password` and `role`. Per
`.claude/rules/security.md`, the skill must **never** accept those in
conversation. They are created with `is_sensitive: true` and the user assigns
values from their own terminal, the pattern `ts-profile-thoughtspot` uses for
tokens. The skill may confirm presence, never echo a value.

`ts variables search` returns assigned values, so output for a variable marked
sensitive must be masked before display.

---

## 8. Naming: why a new family

`.claude/rules/skill-naming.md` requires a family match and asks reviewers to
push back on new ones. The case for `ts-publish-*`:

- **Not `ts-object-*`.** That family is single-object-scoped. This operates on a
  dependency closure (Model + N Tables + 1 Connection) plus instance-wide
  variables, then fans out across a set of Orgs.
- **Not `ts-dependency-*`.** That family is documented as graph-*rewrite*.
  Publishing walks the graph but rewrites nothing in it.
- **Not `ts-variable-*`.** That family is one known platform variable
  end-to-end. Here variables are generated dynamically.
- **Room to grow.** `ts-publish-liveboard` and `ts-publish-status` slot in
  naturally.

Proposed family row:

| # | Family | Pattern | Semantic | Members |
|---|---|---|---|---|
| 10 | `ts-publish-*` | `ts-publish-{target}` | Distribute a master object to a set of destinations without copying it, including the variable definition and parameterization distribution requires. Second token is the destination class. | `ts-publish-orgs` |

Requires three changes in one PR: the row above, a `FAMILY_PATTERNS` entry in
`tools/validate/check_skill_naming.py`, and a CLAUDE.md change-impact mention.

---

## 9. Open Items

Nine items were opened on spec-read. **Eight are resolved** by the 2026-07-25
live verification (§2.5). One remains.

| # | Item | Status |
|---|---|---|
| 1 | Does a target Org's TML export show substituted values or the `${var}` form? | **OPEN.** Needs org-scoped token auth from `feat/ts-org-migrate`; `POST /auth/session/org` returns 404 on this build. Step 12 substitution checking depends on it. Status checking does not. |
| — | Variable-to-field cardinality | RESOLVED: one variable, one value per scope; `field_names[]` is batch-only |
| — | Is variable type binding enforced? | RESOLVED: yes, `code 10002` |
| — | Correct delete endpoint | RESOLVED: `/template/variables/delete`, batch `identifiers[]` |
| — | How does the Connection reach a target Org? | RESOLVED: auto-granted on publish; retracted only with `include_dependencies: true` |
| — | How to tell what is published where | RESOLVED: `metadata_header.orgIds`, no per-Org auth needed |
| — | Publish validation failure shape | RESOLVED: `code 13151`, GUID/numeric-id message; `INVALID_ORG` for a bad Org |
| — | Org identifier forms | RESOLVED: name, numeric id as string, and `Primary` all accepted |
| — | Is `obj_id` required before publishing? | RESOLVED: auto-populated, nothing to assign |

---

## 10. Build order and status

| # | Step | Status |
|---|---|---|
| 1 | `ts-publish-*` family in `skill-naming.md` + `check_skill_naming.py` | **DONE** (`bf41b3b`) |
| 2 | `ts variables create` / `delete` | **DONE** (`8c58d9c`, v0.98.0) |
| 3 | `ts metadata parameterize` / `unparameterize` | **DONE** (`8c58d9c`) |
| 4 | `ts publish push` / `unpush` / `status` | **DONE** (`8c58d9c`) |
| 5 | `ts publish export` (field-variance clustering) | **DONE** (`61ea50a`) |
| 6 | `ts publish resolve` (value matrix + coverage check) | **DONE** (`bc60b37`, v0.99.0) |
| 7 | `ts publish apply` / `rollback` | **DONE** (`21c73a7`, v0.100.0) |
| 8 | Org-scoped token auth from `feat/ts-org-migrate`, then close Open Item #1 and add substitution checking to `verify` | TODO (blocked) |
| 9 | `agents/cli/ts-publish-orgs/SKILL.md` | TODO |
| 10 | `tools/smoke-tests/smoke_ts_publish_orgs.py` | TODO |
| 11 | README.md, `agents/cli/SETUP.md`, `agents/PARITY.md`, `EXPECTED_DIVERGENCES` in `check_runtime_coverage.py` (CLI-only; no Snowsight analogue) | TODO |

Steps 2 to 7 are shipped, unit-tested (82 new tests) and live-verified end to end
on `nebula-damian-alias`: `export` → `resolve` → `apply --publish-to ORG1` →
`rollback` returns the cluster to its exact prior state. The whole workflow is
drivable from the CLI today; what remains is the interactive skill on top.

### Two design changes made during the build

**`build` merged into `apply`.** The original five-stage pipeline had `build`
emit a plan for review before `apply` executed it. In practice `resolve` already
produces the reviewable artefact (the value matrix), so a separate `build` would
only re-emit it in a different shape. `apply --dry-run` prints the ordered plan
instead, which gives the same review step with one command fewer.

**`--source warehouse` and `--source db` deferred.** `resolve` ships with four
sources (`uniform`, `pattern`, `file`, `existing`). Warehouse introspection and
a governance table both need a Snowflake or Databricks profile and are worth
building once the skill is exercised against a real tenant layout; `pattern`
plus `file` covers the same ground meanwhile. Not dropped, just not speculative.

### Corrections from live testing

**Root publish type.** `apply` originally published the closure root using the
same type it used to parameterize the Tables (`LOGICAL_TABLE`), so a Liveboard or
Answer closure would have been published with the wrong type. The publish type is
now derived from `root.type` via `publish_type_for_root`.

**Falcon-backed tables.** Tables with no connection block cannot be parameterized: they are the
"default system tables" the docs exclude. The first cut of `export` happily
proposed variables for them. Clusters now carry `parameterizable`, `recommended`
is gated on it, `selectable_clusters` never returns one, and `export` warns
naming the tables. Worth remembering when the skill picks a Model: a Falcon-backed
Model cannot be published at all.
