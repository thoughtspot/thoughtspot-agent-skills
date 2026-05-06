# Agent Parity — Cross-Agent Skill Mapping

This document tracks which skills exist in which agent runtime and what must be
kept in sync when making changes.

## Agent Runtimes

| Directory | Runtime | API Access | Credential Storage | Deployment |
|---|---|---|---|---|
| `agents/claude/` | Claude Code (local terminal) | `ts` CLI | OS Keychain + `~/.claude/` profiles | Symlinks from `~/.claude/skills/` |
| `agents/cli/` | Cortex Code CLI (local terminal) | `ts` CLI | OS Keychain + `~/.claude/` profiles | Symlinks from `~/.snowflake/cortex/skills/` |
| `agents/coco-snowsight/` | Snowsight Workspace (no shell) | Stored procedures | Snowflake Secrets | Stage → Workspace copy |

## Skill Matrix

| Skill | claude | cli | coco-snowsight | Notes |
|---|---|---|---|---|
| ts-profile-thoughtspot | Y | Y | Y | CLI versions use OS keychain; Snowsight uses Snowflake Secrets |
| ts-convert-to-snowflake-sv | Y | Y | Y | Core mapping logic identical; API call mechanism differs |
| ts-convert-from-snowflake-sv | Y | Y | Y | Core mapping logic identical; API call mechanism differs |
| ts-dependency-manager | Y | Y | — | CLI versions use ts CLI; Snowsight can't support graph walks |
| ts-object-answer-promote | Y | Y | — | CLI versions use ts CLI; Snowsight can't support complex manipulation |
| ts-object-model-coach | Y | Y | — | CLI versions use ts CLI; Snowsight can't support interactive coaching |
| ts-setup-sv | — | — | Y | Snowsight-only: installs stored procedures |
| ts-profile-snowflake | Y | — | — | Claude Code only: Cortex Code manages connections natively |

## What to Sync

### Always sync (core logic changes)

Changes to these areas must be propagated to ALL agent versions of the skill:

- Mapping rules (column classification, formula translation, DDL generation)
- TML schema interpretations
- Concept mappings (ThoughtSpot ↔ Snowflake)
- Validation logic
- Error messages and user-facing text
- New steps or removed steps
- Bug fixes to conversion logic

### Never sync (runtime-specific)

These are inherently different per runtime:

- API call mechanism (stored procedure vs `ts` CLI)
- Authentication flow (Snowflake Secrets vs OS Keychain)
- File paths (relative shared refs vs `~/.claude/` vs Cortex Code connections)
- SQL execution method (`sql_execute` tool vs `snow sql` vs Python connector)
- Deployment instructions

## Shared References

All agents reference the same `agents/shared/` directory for mapping rules,
schemas, and worked examples. Path convention differs by agent:

| Agent | Shared path convention |
|---|---|
| `claude` | `~/.claude/mappings/...`, `~/.claude/shared/schemas/...` |
| `cli` | `../../shared/mappings/...`, `../../shared/schemas/...` |
| `coco-snowsight` | `../../shared/mappings/...`, `../../shared/schemas/...` |

## Publishing Checklist

When making a change to a skill:

1. Identify which agents have this skill (see matrix above)
2. Make the core logic change in all applicable agents
3. Adapt runtime-specific sections for each agent
4. Update changelogs in each SKILL.md
5. For coco-snowsight: run `./scripts/stage-sync.sh` after push
6. For cli: symlinks update automatically on `git pull`
7. For claude: symlinks update automatically on `git pull`
