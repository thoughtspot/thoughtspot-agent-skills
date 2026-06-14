# Agent Parity — Cross-Agent Skill Mapping

This document tracks which skills exist in which agent runtime and what must be
kept in sync when making changes.

**This matrix is generated.** Run `python3 tools/validate/generate_parity.py` to
regenerate. Run with `--check` to validate the committed version matches the
filesystem.

## Agent Runtimes

| Directory | Runtime | API Access | Credential Storage | Shared path convention | Deployment |
|---|---|---|---|---|---|
| `agents/cli/` | Claude Code + Cortex Code CLI (local terminal) | `ts` CLI | OS Keychain + `~/.claude/` profiles | `../../shared/mappings/...`, `../../shared/schemas/...` | Symlinks from `~/.claude/skills/` and `~/.snowflake/cortex/skills/` |
| `agents/claude/` | Claude Code only (annex — `ts-profile-snowflake`) | `ts` CLI | OS Keychain + `~/.claude/` profiles | `../../shared/mappings/...`, `../../shared/schemas/...` | Symlinks from `~/.claude/skills/` |
| `agents/coco-snowsight/` | Snowsight Workspace (no shell) | Stored procedures | Snowflake Secrets | `../../shared/mappings/...`, `../../shared/schemas/...` | Stage → Workspace copy (`stage-sync.sh`) |

## Skill Matrix

| Skill | cli | claude | coco-snowsight |
|---|---|---|---|
| ts-convert-from-databricks-mv | Y | — | — |
| ts-convert-from-snowflake-sv | Y | — | Y |
| ts-convert-from-tableau | Y | — | — |
| ts-convert-to-databricks-mv | Y | — | — |
| ts-convert-to-snowflake-sv | Y | — | Y |
| ts-dependency-manager | Y | — | — |
| ts-object-answer-promote | Y | — | — |
| ts-object-model-coach | Y | — | — |
| ts-profile-databricks | Y | — | — |
| ts-profile-snowflake | — | Y | — |
| ts-profile-thoughtspot | Y | — | Y |
| ts-recipe-formula-business-days-snowflake | Y | — | Y |
| ts-recipe-formula-hms-display-snowflake | Y | — | Y |
| ts-setup-sv | — | — | Y |
| ts-variable-timezone | Y | — | — |

## What to Sync

### Always sync (core logic changes)

Changes to these areas must be propagated to ALL agent versions of the skill:

- Mapping rules (column classification, formula translation, DDL generation)
- TML schema interpretations
- Concept mappings (ThoughtSpot ↔ Snowflake/Databricks/Tableau)
- Validation logic
- Error messages and user-facing text
- New steps or removed steps
- Bug fixes to conversion logic

### Never sync (runtime-specific)

These are inherently different per runtime:

- API call mechanism (stored procedure vs `ts` CLI)
- Authentication flow (Snowflake Secrets vs OS Keychain)
- File paths (relative shared refs vs `~/.claude/`)
- SQL execution method (`snowflake_sql_execute` vs `snow sql` vs Python connector)
- Deployment instructions

## Publishing Checklist

When making a change to a skill:

1. Identify which agents have this skill (see matrix above)
2. Make the core logic change in all applicable agents
3. Adapt runtime-specific sections for each agent
4. Update changelogs in each SKILL.md
5. Update `synced-from` markers on mirrors to reflect the new CLI version
6. For coco-snowsight: run `./scripts/stage-sync.sh` after push
7. For cli/claude: symlinks update automatically on `git pull`
