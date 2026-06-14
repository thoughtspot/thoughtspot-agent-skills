# thoughtspot-agent-skills

A collection of skills and tools for creating semantic models in ThoughtSpot and Snowflake,
packaged for multiple runtimes: **CLI** (Claude Code + Cortex Code CLI, via symlinks) and
**Snowsight** (via Snowflake internal stage). All runtimes consume the same shared reference library.

## Directory map

```
agents/cli/            — Canonical CLI skills (Claude Code + Cortex Code CLI); symlinked into both ~/.claude/skills/ and ~/.snowflake/cortex/skills/
agents/claude/         — Claude Code-only skills (ts-profile-snowflake); symlinked into ~/.claude/skills/
agents/coco-snowsight/ — Snowflake Cortex skills (Snowsight); deployed via snow stage copy
agents/shared/         — Reference files consumed by ALL runtimes (schemas, mappings, worked examples)
tools/ts-cli/          — Python CLI used by CLI skills at runtime for ThoughtSpot API calls
scripts/               — Deployment helpers (deploy.sh, stage-sync.sh)
```

## Symlink contract

`~/.claude/skills/`, `~/.claude/shared/`, and `~/.claude/mappings/` are symlinks into this repo.
Editing repo files takes effect in Claude Code immediately — never copy files to the symlink target
or patch files there directly.

## Change impact map — when you change X, also update Y

| Changed area | Also update |
|---|---|
| Any SKILL.md (new command or step) | README.md skills table; agents/cli/SETUP.md if install/symlink step changed; bump version in SKILL.md ## Changelog |
| agents/shared/* | snow stage copy for that file (see agents/coco-snowsight/SETUP.md); worked example if output changes |
| tools/ts-cli command interface | tools/ts-cli/README.md; any SKILL.md that uses that command; CHANGELOG.md entry if version bumped |
| agents/claude/ skill logic | Corresponding agents/cli/ and agents/coco-snowsight/ skill if logic applies |
| agents/cli/ skill logic | Corresponding agents/claude/ skill and agents/coco-snowsight/ skill if logic applies |
| agents/coco-snowsight/ skill logic | Corresponding agents/claude/ and agents/cli/ skill if logic applies to those runtimes |
| Credential storage steps | agents/cli/ts-profile-thoughtspot/SKILL.md; agents/claude/ts-profile-snowflake/SKILL.md; .claude/rules/security.md |
| Add a new skill | README.md; agents/cli/SETUP.md (symlink step); agents/coco-snowsight/SETUP.md (stage copy list); **tools/smoke-tests/smoke_<skill>.py** (or add to ALLOWLIST in tools/validate/check_smoke_tests.py with justification); add ## Changelog starting at 1.0.0; CHANGELOG.md entry; **skill name must match a family in `.claude/rules/skill-naming.md`** (or extend the rule with a new family in the same PR); **runtime coverage**: CoCo Snowsight divergence requires an entry in `EXPECTED_DIVERGENCES` in `tools/validate/check_runtime_coverage.py` with a one-line justification |
| Add a new shared schema/mapping | agents/coco-snowsight/SETUP.md stage copy list; all SKILL.md files that reference it |
| `.mcp.json` (MCP server wiring) or `.claude/rules/api-research.md` | Update the other if precedence/usage rules change; check that `CLAUDE.md` "open-items.md pattern" and `.claude/rules/ts-cli.md` (v1 migration trigger, "When a skill needs an API call") still reference the rule correctly |
| ts-dependency-manager: changes to Step 4 walking, Step 5 impact-report, or any open-items.md status | Also update agents/cli/ts-dependency-manager/references/dependency-types.md (status table, hierarchy, or sample output as relevant) — these must stay in sync; pre-commit prompts soft when one changes without the other |

If this map is getting outdated, update the table — do not prompt the author to check manually.

## Commit + deploy protocol

**Never push directly to `main`.** All changes — including hotfixes and docs-only edits —
must go through a pull request. `main` has branch protection; direct pushes bypass it and
skip review.

Workflow for every change:
1. Work on a feature or wip branch (`feat/<slug>` or `wip/<skill>`)
2. `git push -u origin <branch>` and open a PR against `main`
3. After the PR merges:
   - For any changed `agents/coco-snowsight/` or `agents/shared/` file: `./scripts/stage-sync.sh`
   - For `tools/ts-cli/` changes: `pip install -e tools/ts-cli` in the affected environment

Claude Code changes (via symlinks) take effect immediately — no step needed for `agents/claude/` only.

## Branching conventions

In-progress skills that require live-instance testing before shipping live on `wip/*` branches.
These branches are pushed to remote for backup but never merged to main until verified.

| Branch | Contents |
|---|---|
| `main` | Clean, published — what users clone |

**Working on a wip branch:**
- Pre-commit hook runs on every commit (same as main)
- `deploy.sh` is blocked on non-main branches — use `stage-sync.sh` to test CoCo content
- Validators can be run manually before a stage sync: `python3 tools/validate/check_*.py --root .`
- Merge criteria: all `references/open-items.md` items are VERIFIED, smoke tests pass, all validators clean

**Starting a new wip skill:**
1. `git checkout -b wip/<skill-name>` from current main
2. Remove the skill's `.gitignore` entry on that branch only
3. Update README.md, SETUP.md, and coco-snowsight/SETUP.md to include the skill (consistency checker enforces this)
4. `git push -u origin wip/<skill-name>`

**Session-start protocol:** see `.claude/rules/branching.md` — check your branch before making any edits.

## Auth and secrets

Credentials are never stored in files, env files, or git. Pattern used throughout:

- Credential → OS credential store via `keyring` (macOS Keychain, Windows Credential Manager, Linux Secret Service)
  - macOS: `security add-generic-password -s "thoughtspot-{slug}" -a "{username}"` (also readable via `keyring`)
  - Windows/Linux: `python -c "import keyring; keyring.set_password('thoughtspot-{slug}', username, value)"`
- Env var → `~/.zshenv` export line (macOS/Linux) or permanent user env var (Windows — optional)
- Profile JSON → `~/.claude/thoughtspot-profiles.json` (not in repo) stores `{token_env: "THOUGHTSPOT_TOKEN_{SLUG}"}`

Canonical source for full auth flow: `agents/cli/ts-profile-thoughtspot/SKILL.md` (Technical Reference section).
Platform policy: `.claude/rules/security.md`.

## Critical TML invariants

Read `agents/shared/schemas/thoughtspot-table-tml.md` and `agents/shared/schemas/thoughtspot-model-tml.md` before generating any TML.
These rules come from real import failures — violating them causes silent errors or rejected imports:

- `db_column_name`: always include on every table column, even when it equals `name`
- Connection in table TML: `name:` only — never `fqn:` inside a connection block
- `guid:` goes at the document root — NOT nested inside `table:` or `model:`; omit on first import
- All formula columns (ATTRIBUTE and MEASURE) need a `columns[]` entry with `formula_id:` that matches the `formulas[]` `id:`
- `aggregation:` belongs in `columns[]` entries only — never in a `formulas[]` entry
- Model `id:` is optional; when absent, `name:` is the join reference target in `model_tables[].joins[].with`

## Formula classification

Before declaring any formula untranslatable between ThoughtSpot and Snowflake, read:
`agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md`

Many window and LOD functions have direct SQL equivalents. Declaring something untranslatable
without checking the reference is an error.
