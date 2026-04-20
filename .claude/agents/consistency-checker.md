---
name: consistency-checker
description: Verify cross-file consistency after edits — checks broken references, stage copy completeness, skills table, symlink instructions, anti-patterns, and version sync. Run after any batch of changes before committing.
---

# Consistency Checker

Run after any batch of edits to catch integration problems that individual file edits can miss.
Report pass/fail for each check. On failure, give the exact file and line to fix.

## Checks to perform

### 1. Broken file references in SKILL.md files

Scan every `SKILL.md` in `agents/claude/` and `agents/coco/` for markdown links `[text](path)`.

- For Claude skills (`agents/claude/`): resolve `~/.claude/shared/` → `agents/shared/`, `~/.claude/mappings/` → `agents/shared/mappings/`, `~/.claude/skills/` → `agents/claude/`
- For CoCo skills (`agents/coco/`): resolve relative `../../shared/` → `agents/shared/`
- Check each resolved path exists in the repo
- Report: file, line number, broken path

### 2. Stage copy list completeness

Read `agents/coco/SETUP.md`. Extract every filename mentioned in `snow stage copy` commands.
For each, verify the source file exists in the repo at the stated path.

Also check: every `SKILL.md` in `agents/coco/` is listed in a `snow stage copy` command.
Every file in `agents/shared/` is listed (or note any that are missing and should be added).

### 3. Skills table in README.md

Read `README.md`. Extract skill names from the Claude Code and CoCo skills tables.

Compare against:
- Every directory in `agents/claude/` that contains a `SKILL.md`
- Every directory in `agents/coco/` that contains a `SKILL.md`

Report: any skill directory not in README, or any README row with no matching directory.

### 4. Symlink steps in SETUP.md

Read `agents/claude/SETUP.md`. Extract skill names from the `ln -s` symlink commands in the
Developer Install section.

Compare against every directory in `agents/claude/` that contains a `SKILL.md`.
Report: any skill missing a symlink step.

### 5. Anti-pattern detection

Scan all `.md` and `.py` files in the repo for known bad patterns:

| Pattern | What to check | Bad signal |
|---|---|---|
| `fqn:` adjacent to `connection:` | TML examples in .md files | Should be `name:` only |
| `aggregation:` under `formulas[]:` | TML examples | `aggregation:` belongs in `columns[]`, never in `formulas[]` |
| `connection_fqn` | Python files | Should be `connection_name` |
| `%%` in help strings | `.py` files | Should be `%` (Typer doubles `%`) |

Report: file, line number, matched pattern.

### 6. Version sync

Read `tools/ts-cli/ts_cli/__init__.py` and extract `__version__`.
Read `tools/ts-cli/pyproject.toml` and extract `version`.

Report pass if they match; report both values if they differ.

## Output format

```
consistency-checker results
===========================

[PASS] Broken references: all paths resolved
[FAIL] Stage copy completeness: agents/coco/setup-ts-sv/SKILL.md not listed in SETUP.md (line 24)
[PASS] README skills table: all skills present
[PASS] SETUP.md symlink steps: all skills covered
[FAIL] Anti-patterns: tools/ts-cli/ts_cli/commands/metadata.py:44 — "%%" in help string
[PASS] Version sync: 0.2.0 matches

1 check(s) failed.
```

Fix each failure before committing. Re-run after fixing to confirm clean.
