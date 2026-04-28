# Skill Naming Convention

Every skill directory under `agents/claude/` and `agents/coco/` must match one
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

## The six families

| # | Family | Pattern | Semantic | Members |
|---|---|---|---|---|
| 1 | `ts-object-*` | `ts-object-{type}-{verb}` | Single-object scoped operation. Third token is the **object type** (model, answer, liveboard, etc.); fourth is the **verb** (promote, builder, coach, etc.). | `ts-object-answer-promote`, `ts-object-model-builder`, `ts-object-model-coach` |
| 2 | `ts-profile-*` | `ts-profile-{platform}` | Credential setup for a specific platform. Second token is the platform name. | `ts-profile-thoughtspot`, `ts-profile-snowflake` |
| 3 | `ts-convert-*` | `ts-convert-{direction}-{format}` | Cross-platform schema conversion. Third token is `to` or `from`; fourth is the target/source format. | `ts-convert-to-snowflake-sv`, `ts-convert-from-snowflake-sv` |
| 4 | `ts-dependency-*` | `ts-dependency-{verb}` | Cross-object dependency-graph operation (audit, walk, rewrite, cleanup). | `ts-dependency-manager` |
| 5 | `ts-variable-*` | `ts-variable-{specifier}` | Manage a specific platform variable across all its operations (search, set, remove). Second token is the variable's short name. | `ts-variable-timezone` *(planned)* |
| 6 | `ts-setup-*` | `ts-setup-{specifier}` | Install or upgrade a toolset / stored procedures / shared infrastructure used by other skills. | `ts-setup-sv` |

---

## How to choose a family for a new skill

Work top-down through these questions. Stop at the first match.

### 1. Is the operation scoped to ONE object instance (model / answer / liveboard / table / view / set)?

→ **`ts-object-*`**. Pattern: `ts-object-{type}-{verb}`.

The verb describes the operation; the type is the object kind. If the
"verb" you want to use is actually a noun (`builder`, `coach`), that's
acceptable when the noun reads naturally as an action — `builder` = "the
builder skill", `coach` = "coach this Model". Both shipped examples
(`ts-object-model-builder`, `ts-object-model-coach`) use noun-shaped verbs.

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

### 6. Does the skill install or upgrade infrastructure (procs, packages, deployment artefacts)?

→ **`ts-setup-*`**. Pattern: `ts-setup-{specifier}`.

Specifier identifies what's being installed (`sv` = the semantic-view
toolset, `databricks` = the Databricks toolset, etc.). This is distinct
from `ts-profile-*` — profile is about credentials, setup is about
deploying executable code or shared schema files.

### 7. None of the above match

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
3. **Update `agents/claude/CLAUDE.md`** change-impact map row "Adding a new
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

## Cross-runtime note

The same family rule applies to `agents/coco/` skills. Where a skill exists
in both `agents/claude/` AND `agents/coco/`, both copies must share the
same name (so `agents/claude/ts-convert-to-snowflake-sv` and
`agents/coco/ts-convert-to-snowflake-sv` are both present and both pass).

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
