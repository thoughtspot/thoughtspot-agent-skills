# Cursor Rules — Conventions

Loaded when working in `agents/cursor/`. Covers rule anatomy, path conventions,
and how Cursor rules differ from Claude Code skills.

## How Cursor rules work vs. Claude Code skills

| Concept | Claude Code | Cursor |
|---|---|---|
| Invocation | `/skill-name` slash command | User describes intent; AI matches rule by `description` field |
| Entry point | `SKILL.md` with `name:` frontmatter | `.mdc` file with `description:` frontmatter |
| Install location | `~/.claude/skills/<name>/` (global) | `.cursor/rules/<name>.mdc` (per-project) |
| Shared references | `~/.claude/shared/` | `~/.cursor/shared/` |
| Profile references | `~/.claude/skills/<skill>/SKILL.md` | `~/.cursor/rules/<skill>.mdc` |
| Runtime tools | `ts` CLI + Bash | `ts` CLI + Bash (same Python env) |

## Rule anatomy

Each skill is a single `.mdc` file in `agents/cursor/rules/`:

```
agents/cursor/rules/
  {skill-name}.mdc     — Cursor frontmatter + full rule instructions
```

`.mdc` frontmatter format:

```yaml
---
description: Invoked when the user wants to [action] — [what it does]. [Trigger phrases.]
alwaysApply: false
---
```

- `description` — shown in the Cursor UI; the AI uses this to decide when to attach the rule
- `alwaysApply: false` — rules are on-demand, not always injected into context
- No `globs:` for profile/conversion skills — they are task-driven, not file-driven

## Reference paths (Cursor convention)

Cursor rules reference shared files via:

- `~/.cursor/shared/...` — schemas, worked examples
- `~/.cursor/shared/mappings/...` — formula and property mapping lookup tables
- `~/.cursor/rules/<other-skill>.mdc` — cross-skill references

Do NOT use `~/.claude/shared/...` — that is the Claude Code convention.

The `install.sh` / `install.ps1` scripts create the `~/.cursor/shared/` symlink when
setting up for the first time.

## Change impact map — when you change X, also update Y

| Changed area | Also update |
|---|---|
| `agents/claude/<skill>/SKILL.md` logic | `agents/cursor/rules/<skill>.mdc` (keep in sync) |
| Credential storage or verification steps | Both SKILL.md files, both .mdc files, and `.claude/rules/security.md` |
| `agents/shared/*` | `agents/coco/` stage copy AND `agents/cursor/` (shared via `~/.cursor/shared/` symlink — no copy needed if symlink is in place) |
| Add a new Claude skill | Add matching `agents/cursor/rules/<skill>.mdc` |
| Path convention changes | Update `agents/cursor/SETUP.md` install steps |

## Installing rules

Rules are per-project in Cursor. The install scripts create symlinks from
`.cursor/rules/*.mdc` in a target project directory into this repo's `rules/` folder:

```bash
# macOS / Linux
cd /path/to/your/project
~/Dev/thoughtspot-agent-skills/agents/cursor/scripts/install.sh

# Windows (PowerShell, run as Administrator if needed for symlinks)
cd C:\path\to\your\project
& "$env:USERPROFILE\Dev\thoughtspot-agent-skills\agents\cursor\scripts\install.ps1"
```

## Commit protocol

Rules take effect immediately via symlinks — no deploy step. For changes to shared
reference content (`agents/shared/`), also run `./scripts/stage-sync.sh` to keep
CoCo in sync (see root CLAUDE.md).
