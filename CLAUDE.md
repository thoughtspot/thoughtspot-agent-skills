# thoughtspot-skills

A collection of skills and tools for creating semantic models in ThoughtSpot and Snowflake,
packaged for two runtimes: **Claude Code** (via `~/.claude/` symlinks) and **Snowflake Cortex /
CoCo** (via Snowflake internal stage). Both runtimes consume the same shared reference library.

## Directory map

```
agents/claude/    — Claude Code skills; symlinked into ~/.claude/skills/
agents/coco/      — Snowflake Cortex skills; deployed via snow stage copy to @SKILLS.PUBLIC.SHARED
agents/shared/    — Reference files consumed by BOTH runtimes (schemas, mappings, worked examples)
tools/ts-cli/     — Python CLI used by Claude skills at runtime for ThoughtSpot API calls
scripts/          — Deployment helpers (deploy.sh, stage-sync.sh)
```

## Symlink contract

`~/.claude/skills/`, `~/.claude/shared/`, and `~/.claude/mappings/` are symlinks into this repo.
Editing repo files takes effect in Claude Code immediately — never copy files to the symlink target
or patch files there directly.

## Change impact map — when you change X, also update Y

| Changed area | Also update |
|---|---|
| Any SKILL.md (new command or step) | README.md skills table; agents/claude/SETUP.md if install/symlink step changed |
| agents/shared/* | snow stage copy for that file (see agents/coco/SETUP.md); worked example if output changes |
| tools/ts-cli command interface | tools/ts-cli/README.md; any SKILL.md that uses that command |
| agents/claude/ skill logic | Corresponding agents/coco/ skill if logic applies to both runtimes |
| agents/coco/ skill logic | Corresponding agents/claude/ skill if logic applies to both runtimes |
| Add a new skill | README.md; agents/claude/SETUP.md (symlink step); agents/coco/SETUP.md (stage copy list) |
| Add a new shared schema/mapping | agents/coco/SETUP.md stage copy list; both SKILL.md files that reference it |

If this map is getting outdated, update the table — do not prompt the author to check manually.

## Commit + deploy protocol

Three steps, always together:

1. `git commit` + `git push origin main`
2. For any changed `agents/coco/` or `agents/shared/` file: `./scripts/stage-sync.sh`
   (exact commands in agents/coco/SETUP.md if running manually)
3. For `tools/ts-cli/` changes: `pip install -e tools/ts-cli` in the affected environment

Claude Code changes (via symlinks) take effect immediately — no step 2 needed for `agents/claude/` only.

## Auth and secrets

Credentials are never stored in files, env files, or git. Pattern used throughout:

- Credential → macOS Keychain (`security add-generic-password -s "thoughtspot-{slug}" -a "{username}"`)
- Env var → `~/.zshenv` export line: `export THOUGHTSPOT_TOKEN_{SLUG}=$(security find-generic-password ...)`
- Profile JSON → `~/.claude/thoughtspot-profiles.json` (not in repo) stores `{token_env: "THOUGHTSPOT_TOKEN_{SLUG}"}`

Canonical source for full auth flow: `agents/claude/ts-setup-profile/SKILL.md` (Technical Reference section).

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
