# Skill Naming Convention

Every skill directory under `agents/cli/` and `agents/coco-snowsight/` must match one
of the documented family patterns below. The pattern is enforced by
`tools/validate/check_skill_naming.py` and runs in the pre-commit hook on every
commit that adds or renames a skill directory.

## Why this exists

Skill names are the user's primary discovery surface — the `/<skill-name>`
slash command in Claude Code, the directory name in the repo, the entry in
the skills table. When skills are named with consistent shapes, users build
correct expectations from the prefix alone (`ts-profile-*` is credential
setup, `ts-object-*` is a single-object operation, etc.). When the shape
drifts, every skill becomes a one-off the user has to memorise.

The rule below was lifted from observed patterns in shipped skills and
formalised so that future skills land in a known family or — explicitly —
extend the rule with a new one.

---

## The eleven families

| # | Family | Pattern | Semantic | Members |
|---|---|---|---|---|
| 1 | `ts-object-*` | `ts-object-{type}-{verb}` | Single-object scoped operation. Third token is the **object type** (model, answer, liveboard, etc.); fourth is the **verb** (promote, builder, coach, etc.). | `ts-object-answer-promote`, `ts-object-model-coach`, `ts-object-model-builder` *(planned)* |
| 2 | `ts-profile-*` | `ts-profile-{platform}` | Credential setup for a specific platform. Second token is the platform name. | `ts-profile-thoughtspot`, `ts-profile-snowflake` |
| 3 | `ts-convert-*` | `ts-convert-{direction}-{format}` | Cross-platform schema conversion. Third token is `to` or `from`; fourth is the target/source format. | `ts-convert-to-snowflake-sv`, `ts-convert-from-snowflake-sv`, `ts-convert-from-tableau` |
| 4 | `ts-dependency-*` | `ts-dependency-{verb}` | Cross-object dependency-graph operation (walk, rewrite, cleanup). | `ts-dependency-manager` |
| 5 | `ts-variable-*` | `ts-variable-{specifier}` | Manage a specific platform variable across all its operations (search, set, remove). Second token is the variable's short name. | `ts-variable-timezone` *(planned)* |
| 6 | `ts-setup-*` | `ts-setup-{specifier}` | Install or upgrade a toolset / stored procedures / shared infrastructure — or stand up a reproducible environment — used by other skills. | `ts-setup-sv`, `ts-setup-tenancy` |
| 7 | `ts-recipe-*` | `ts-recipe-{ts-artifact-type}-{concept}[-{platform}]` | Build a specific analytical capability in ThoughtSpot. Second token is the primary ThoughtSpot artifact produced (`formula`, `answer`, `liveboard`, `model`). Third+ tokens describe the concept (`business-days`, `hms-display`, `abc-analysis`). Optional platform suffix (`-snowflake`, `-databricks`) present only when the recipe deploys to an external platform; omitted for pure-ThoughtSpot recipes. | `ts-recipe-formula-business-days-snowflake` |
| 8 | `ts-audit` | `ts-audit` | Read-only health assessment of a ThoughtSpot environment or individual objects. Scans across multiple angles (AI readiness, data modeling, performance, security) and produces a prioritised report with actionable recommendations. Distinct from `ts-dependency-*` which actively modifies the dependency graph. | `ts-audit` |
| 9 | `ts-load-*` | `ts-load-{specifier}` | Load source data into a warehouse. Specifier describes the data domain or purpose. | `ts-load-source-data` |
| 10 | `ts-publish-*` | `ts-publish-{target}` | Distribute a master object to a set of destinations **without copying it**, including the variable definition and metadata parameterization that distribution requires. Second token is the destination class. | `ts-publish-orgs` |
| 11 | `ts-security-*` | `ts-security-{aspect}` | Cross-object, cross-Org security configuration that **chooses between mechanisms** rather than driving one. Second token names the aspect secured (`columns`, `rls`). | `ts-security-columns`, `ts-security-rls` *(planned)* |
| 12 | `ts-migrate-*` | `ts-migrate-{destination-class}` | Move an **existing estate** onto a new platform pattern and **retire the old one**. Second token is the destination class. Spans many object types across two Orgs and is destructive at the source. | `ts-migrate-orgs` |

---

## How to choose a family for a new skill

Work top-down through these questions. Stop at the first match.

### 1. Is the operation scoped to ONE object instance (model / answer / liveboard / table / view / set)?

→ **`ts-object-*`**. Pattern: `ts-object-{type}-{verb}`.

The verb describes the operation; the type is the object kind. If the
"verb" you want to use is actually a noun (`builder`, `coach`), that's
acceptable when the noun reads naturally as an action — `builder` = "the
builder skill", `coach` = "coach this Model". The shipped `ts-object-model-coach`
and the planned `ts-object-model-builder` both use noun-shaped verbs.

### 2. Does the skill set up credentials for a platform?

→ **`ts-profile-*`**. Pattern: `ts-profile-{platform}`.

Platform name is the lower-case canonical name (`thoughtspot`, `snowflake`,
`databricks`, `bigquery`).

### 3. Does the skill convert a schema between two platforms?

→ **`ts-convert-*`**. Pattern: `ts-convert-{to|from}-{format}`.

The direction (`to` / `from`) is mandatory — the symmetric pair
(`ts-convert-to-snowflake-sv` and `ts-convert-from-snowflake-sv`) makes the
direction explicit at the slash-command level. Don't drop it.

### 4. Does the skill operate across the dependency graph (multiple object types)?

→ **`ts-dependency-*`**. Pattern: `ts-dependency-{verb}`.

This family is for graph-walking operations (audit, remove-and-cascade,
repoint, cleanup). The verb describes what the skill does to the graph;
not what it does to one object.

### 5. Does the skill manage one specific platform variable end-to-end?

→ **`ts-variable-*`**. Pattern: `ts-variable-{specifier}`.

The specifier is the variable's short name (`timezone`, `currency`,
`language`). The skill bundles all CRUD-like operations on that one
variable. If a future skill is a generic variable manager (handles all
variables, user picks which), use `ts-object-variable-{verb}` instead — but
that hasn't been written yet.

### 6. Does the skill install or upgrade infrastructure (procs, packages, deployment artefacts) — or stand up a reproducible environment other skills run against?

→ **`ts-setup-*`**. Pattern: `ts-setup-{specifier}`.

Specifier identifies what's being installed or stood up (`sv` = the
semantic-view toolset, `tenancy` = the multi-tenancy test environment,
`databricks` = the Databricks toolset, etc.). This is distinct
from `ts-profile-*` — profile is about credentials, setup is about
deploying executable code, shared schema files, or disposable test
environments that **other skills use** (`ts-setup-tenancy` builds the
Orgs/groups/tables scaffolding that the publishing, aliasing, column-security
and migration skills are exercised against).
If the deployment serves end-users directly (not other skills), prefer
`ts-recipe-*` — a recipe's output is a durable analytical artifact the user
keeps, not disposable scaffolding with a teardown.

### 7. Does the skill build a specific analytical capability — a formula, answer, or liveboard pattern?

→ **`ts-recipe-*`**. Pattern: `ts-recipe-{ts-artifact-type}-{concept}[-{platform}]`.

The second token is the primary ThoughtSpot artifact the user receives
(`formula`, `answer`, `liveboard`, `model`). The concept follows in
kebab-case (`business-days`, `hms-display`, `abc-analysis`). The platform
suffix (`-snowflake`, `-databricks`) is only included when the recipe
deploys something to that external platform — omit it for pure-ThoughtSpot
recipes. This family is distinct from `ts-setup-*` (which deploys
infrastructure for other skills) and `ts-object-*` (which operates on an
existing object the user already has).

### 8. Is the skill a read-only health assessment or audit of ThoughtSpot objects?

→ **`ts-audit`**. Pattern: `ts-audit`.

This family is for skills that scan a ThoughtSpot environment (or individual
objects within it) across multiple quality angles and produce a report with
prioritised findings. Distinct from `ts-dependency-*` which actively modifies
objects via the dependency graph, and from `ts-object-*` which operates on a
single object instance.

### 9. Does the skill load or provision data in an external warehouse?

→ **`ts-load-*`**. Pattern: `ts-load-{specifier}`.

This family is for skills that take source data (CSV, manifest, schema definitions)
and load it into a warehouse (Snowflake, Databricks, etc.) so that ThoughtSpot can
connect to it. Distinct from `ts-setup-*` (which installs procedures/infrastructure)
and `ts-convert-*` (which converts between platform schemas).

### 10. Does the skill distribute one master object to many destinations without copying it?

→ **`ts-publish-*`**. Pattern: `ts-publish-{target}`.

The destination class is the second token (`orgs` today; a future
`ts-publish-instances` would slot in the same way). This family owns the whole
distribution job, not just the final call: defining the template variables,
parameterizing the Table and Connection fields against them, publishing, and
verifying what landed where.

Distinct from `ts-object-*` (which operates on one object instance — publishing
spans a dependency closure plus instance-wide variables, then fans out across a
set of Orgs), from `ts-dependency-*` (which *rewrites* the graph — publishing
walks it but changes nothing in it), and from `ts-convert-*` (no format change:
the same object is made visible elsewhere).

If a skill copies the object rather than sharing it, that is TML deployment, not
publishing, and it does not belong in this family.

### 11. Does the skill configure security across objects and Orgs, choosing between mechanisms?

→ **`ts-security-*`**. Pattern: `ts-security-{aspect}`.

The aspect is what is being secured (`columns`, and a future `rls`). This family is for
skills whose job is **selecting a mechanism and explaining the trade-off**, not driving
one — where two or more platform mechanisms exist for the same goal with materially
different capabilities, and picking wrong exposes data.

It mirrors the `ts security` CLI group, which was named the same way and for the same
reason: `ts security column-rules` names the *mechanism* explicitly, leaving
`ts security rls` as the reserved sibling. The skill layer should mirror that boundary
rather than blur it.

Distinct from `ts-object-*` (single-object scoped — these skills produce a verdict per
(Org, object) across a set of both), from `ts-dependency-*` (which *rewrites* the graph —
these change no object definition at all), from `ts-audit` (read-only), and from
`ts-publish-*` (which distributes an object — these restrict one).

### 12. Does the skill move an existing estate onto a new pattern and retire the old one?

→ **`ts-migrate-*`**. Pattern: `ts-migrate-{destination-class}`.

The destination class is the second token (`orgs` today; a future
`ts-migrate-instances` would slot in the same way). This family mirrors the
`ts migrate` CLI group, the same way `ts-security-*` mirrors `ts security`.

It is the **counterpart** to `ts-publish-*`, and the pair is the clearest way to
see the boundary. Publishing *distributes a master object outward* and changes
nothing that already exists. Migration runs the other direction: it takes the
copies a tenant already has, moves their content onto the published master, and
**deletes the originals**. One is additive and reversible by retraction; the
other is a destructive cutover with a state ledger and a rollback.

Distinct from `ts-dependency-*`, which rewrites the graph *within one Org* as an
operation — a migration spans two Orgs, several object types, a backup, a
rename, a repoint and a teardown, and *uses* the dependency engine as one step.
Distinct from `ts-convert-*` (no format change — the same TML lands in a
different Org) and from `ts-object-*` (a migration's unit is a tenant, not an
object).

### 13. None of the above match

→ **Extend the rule**. See "Adding a new family" below. The validator
will fail until either (a) a new family is added or (b) the skill is
allowlisted with explicit justification.

---

## Adding a new family

A new family needs THREE updates in the same PR:

1. **Add a row to the family table** above with pattern, semantic, and at
   least one example.
2. **Add the family to `tools/validate/check_skill_naming.py`** in the
   `FAMILY_PATTERNS` dict, with a regex that matches valid names and a
   one-line description.
3. **Update the root `CLAUDE.md`** change-impact map row "Adding a new
   skill" to mention the new family.

The PR description must explain **why** the new family is needed and
**why an existing family doesn't fit**. Reviewers should push back on new
families — most "new" patterns can be expressed as a verb in an existing
family.

---

## Allowlist (legitimate exceptions)

The validator has an `ALLOWLIST` set in `check_skill_naming.py` for skills
that legitimately don't fit any family — this should be empty under normal
circumstances. An entry requires a justification comment explaining why the
skill can't be renamed. Mass-allowlisting is a smell.

---

## Cross-runtime coverage

The same family rule applies to **every runtime** the repo serves:

| Runtime | Layout | Validator check |
|---|---|---|
| `agents/cli/` | `<skill>/SKILL.md` | Directory name |
| `agents/coco-snowsight/` | `<skill>/SKILL.md` | Directory name |

Where a skill exists in multiple runtimes, all copies must share the same
name — `agents/cli/ts-convert-to-snowflake-sv` and
`agents/coco-snowsight/ts-convert-to-snowflake-sv` are the same skill.
The validator catches new skills added to ANY of these locations.

---

## What this rule does NOT cover

- **Inside-skill file naming** — names of files under `references/`,
  output directories, etc. Those are skill-author choices documented in
  the skill's own SKILL.md.
- **ts-cli command names** — `ts metadata search`, `ts tml export`, etc.
  Those follow the `ts <noun> <verb>` convention documented in
  [tools/ts-cli/CLAUDE.md](../../tools/ts-cli/CLAUDE.md).
- **Slash commands** — they always match the skill directory name 1:1, so
  the rule above is the same rule.

---

## Related rules

- [content-structure.md](content-structure.md) — where new content belongs
  (shared/, references/, inline)
- [versioning.md](versioning.md) — when to bump a skill's version on rename
  (renames are MAJOR — see "Semver rules" in versioning.md)
- [branching.md](branching.md) — merge-criteria checklist
