# Claude Code Skills — Conventions

Loaded when working in agents/claude/. Covers skill anatomy, path conventions,
and runtime tooling specific to the Claude Code runtime.

## Skill anatomy

Each skill lives in its own directory:

```
skill-name/
  SKILL.md           — YAML frontmatter + full skill instructions (entry point)
  references/        — optional supporting docs
    open-items.md    — unverified API behaviors with test scripts
    *.md             — lookup tables, worked examples
```

`SKILL.md` must start with YAML frontmatter:

```yaml
---
name: skill-name
description: One sentence shown in the skill picker — be specific about inputs and outputs.
---
```

## Reference paths (Claude Code convention)

Claude skills reference shared files via symlink-resolved paths:

- `~/.claude/shared/...` — schemas, worked examples
- `~/.claude/mappings/...` — formula and property mapping lookup tables
- `~/.claude/skills/<other-skill>/SKILL.md` — cross-skill references

Do NOT use `../../shared/...` — that is the CoCo convention and will not resolve from Claude Code.

## Runtime: ts CLI

All ThoughtSpot API calls go through the `ts` command (`pip install -e tools/ts-cli`).
Use `ts` subcommands rather than raw REST calls when a subcommand covers the operation.
The CLI handles token caching, Keychain access, and expiry automatically.

Common calls:

```bash
ts auth whoami --profile {name}
ts metadata search --profile {name} --subtype WORKSHEET --name "%keyword%"
ts tml export {guid} --profile {name} --fqn --associated
ts connections list --profile {name}
ts tables create --profile {name}   # reads JSON spec from stdin
```

## open-items.md pattern

If a skill depends on API behaviour that hasn't been verified against a live instance,
document it in `references/open-items.md` with the question, a self-contained test
script, and space to record the finding. Do not ship skills with unresolved high-risk
open items.

## Temp file hygiene

Any `/tmp/ts_token_*.txt` written during a skill session must be cleaned up at skill end.
The `ts` CLI manages its own token cache — skills should not create additional token files.

## Adding a skill

1. Create `agents/claude/<skill-name>/SKILL.md` with frontmatter
2. Add symlink step to agents/claude/SETUP.md (Developer Install section)
3. Add row to skills table in README.md and agents/claude/SETUP.md
4. Create matching `agents/coco/<skill-name>/SKILL.md` if the logic applies to both runtimes
5. Add the new skill's shared file to agents/coco/SETUP.md stage copy list if applicable
