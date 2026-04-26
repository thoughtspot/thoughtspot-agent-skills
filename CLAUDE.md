# thoughtspot-agent-skills

A collection of skills and tools for creating semantic models in ThoughtSpot and Snowflake,
packaged for two runtimes: **Claude Code** (via `~/.claude/` symlinks) and **Snowflake Cortex /
CoCo** (via Snowflake internal stage). Both runtimes consume the same shared reference library.

## Directory map

```
agents/claude/    — Claude Code skills; symlinked into ~/.claude/skills/
agents/coco/      — Snowflake Cortex skills; deployed via snow stage copy to @SKILLS.PUBLIC.SHARED
agents/cursor/    — Cursor AI rules; installed via agents/cursor/scripts/install.sh into .cursor/rules/
agents/shared/    — Reference files consumed by ALL runtimes (schemas, mappings, worked examples)
tools/ts-cli/     — Python CLI used by Claude and Cursor skills at runtime for ThoughtSpot API calls
scripts/          — Deployment helpers (deploy.sh, stage-sync.sh)
```

## Symlink contract

`~/.claude/skills/`, `~/.claude/shared/`, and `~/.claude/mappings/` are symlinks into this repo.
Editing repo files takes effect in Claude Code immediately — never copy files to the symlink target
or patch files there directly.

## Change impact map — when you change X, also update Y

| Changed area | Also update |
|---|---|
| Any SKILL.md (new command or step) | README.md skills table; agents/claude/SETUP.md if install/symlink step changed; corresponding agents/cursor/rules/*.mdc; bump version in SKILL.md ## Changelog |
| agents/shared/* | snow stage copy for that file (see agents/coco/SETUP.md); worked example if output changes |
| tools/ts-cli command interface | tools/ts-cli/README.md; any SKILL.md and .mdc that uses that command; CHANGELOG.md entry if version bumped |
| agents/claude/ skill logic | Corresponding agents/coco/ skill AND agents/cursor/rules/*.mdc if logic applies |
| agents/coco/ skill logic | Corresponding agents/claude/ skill if logic applies to both runtimes |
| agents/cursor/rules/*.mdc | Corresponding agents/claude/ SKILL.md (keep in sync) |
| Credential storage steps | agents/claude/ts-profile-{thoughtspot,snowflake}/SKILL.md; agents/cursor/rules/ts-profile-{thoughtspot,snowflake}.mdc; .claude/rules/security.md |
| Add a new skill | README.md; agents/claude/SETUP.md (symlink step); agents/coco/SETUP.md (stage copy list); agents/cursor/rules/ (.mdc file); add ## Changelog starting at 1.0.0; CHANGELOG.md entry |
| Add a new shared schema/mapping | agents/coco/SETUP.md stage copy list; all SKILL.md and .mdc files that reference it |
| `.mcp.json` (MCP server wiring) or `.claude/rules/api-research.md` | Update the other if precedence/usage rules change; check that `agents/claude/CLAUDE.md` "open-items.md pattern" and `.claude/rules/ts-cli.md` (v1 migration trigger, "When a skill needs an API call") still reference the rule correctly |

If this map is getting outdated, update the table — do not prompt the author to check manually.

## Commit + deploy protocol

**Never push directly to `main`.** All changes — including hotfixes and docs-only edits —
must go through a pull request. `main` has branch protection; direct pushes bypass it and
skip review.

Workflow for every change:
1. Work on a feature or wip branch (`feat/<slug>` or `wip/<skill>`)
2. `git push -u origin <branch>` and open a PR against `main`
3. After the PR merges:
   - For any changed `agents/coco/` or `agents/shared/` file: `./scripts/stage-sync.sh`
   - For `tools/ts-cli/` changes: `pip install -e tools/ts-cli` in the affected environment

Claude Code changes (via symlinks) take effect immediately — no step needed for `agents/claude/` only.

## Branching conventions

In-progress skills that require live-instance testing before shipping live on `wip/*` branches.
These branches are pushed to remote for backup but never merged to main until verified.

| Branch | Contents |
|---|---|
| `main` | Clean, published — what users clone |
| `wip/databricks` | Databricks profile + conversion skills; Databricks shared content |
| `wip/model-builder` | `ts-object-model-builder` (pending Snowflake + ThoughtSpot live testing) |

**Working on a wip branch:**
- Pre-commit hook runs on every commit (same as main)
- `deploy.sh` is blocked on non-main branches — use `stage-sync.sh` to test CoCo content
- Validators can be run manually before a stage sync: `python3 tools/validate/check_*.py --root .`
- Merge criteria: all `references/open-items.md` items are VERIFIED, smoke tests pass, all validators clean

**Starting a new wip skill:**
1. `git checkout -b wip/<skill-name>` from current main
2. Remove the skill's `.gitignore` entry on that branch only
3. Update README.md, SETUP.md, and coco/SETUP.md to include the skill (consistency checker enforces this)
4. `git push -u origin wip/<skill-name>`

**Session-start protocol:** see `.claude/rules/branching.md` — check your branch before making any edits.

## Auth and secrets

Credentials are never stored in files, env files, or git. Pattern used throughout:

- Credential → OS credential store via `keyring` (macOS Keychain, Windows Credential Manager, Linux Secret Service)
  - macOS: `security add-generic-password -s "thoughtspot-{slug}" -a "{username}"` (also readable via `keyring`)
  - Windows/Linux: `python -c "import keyring; keyring.set_password('thoughtspot-{slug}', username, value)"`
- Env var → `~/.zshenv` export line (macOS/Linux) or permanent user env var (Windows — optional)
- Profile JSON → `~/.claude/thoughtspot-profiles.json` (not in repo) stores `{token_env: "THOUGHTSPOT_TOKEN_{SLUG}"}`

Canonical source for full auth flow: `agents/claude/ts-profile-thoughtspot/SKILL.md` (Technical Reference section).
Platform policy: `.claude/rules/security.md`.

## Critical TML invariants

Read `agents/shared/schemas/thoughtspot-table-tml.md` and `thoughtspot-model-tml.md` before generating any TML.
These rules come from real import failures — violating them causes silent errors or rejected imports:

- `db_column_name`: always include on every table column, even when it equals `name`
- Connection in table TML: `name:` only — never `fqn:` inside a connection block
- `guid:` goes at the document root — NOT nested inside `table:` or `model:`; omit on first import
- All formula columns (ATTRIBUTE and MEASURE) need a `columns[]` entry with `formula_id:` that matches the `formulas[]` `id:`
- `aggregation:` belongs in `columns[]` entries only — never in a `formulas[]` entry
- Model `id:` is optional; when absent, `name:` is the join reference target in `joins_with`

## Formula classification

Before declaring any formula untranslatable between ThoughtSpot and Snowflake, read:
`agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`

Many window and LOD functions have direct SQL equivalents. Declaring something untranslatable
without checking the reference is an error.
