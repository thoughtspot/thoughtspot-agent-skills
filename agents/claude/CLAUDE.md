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

## Skill intro

Every skill with 4 or more steps, or any confirmation gate, must begin with a
**Step 0** that displays the session plan before doing any work. Read any prerequisite
reference files in the background first, but output nothing to the user until Step 0 is
shown.

### Step 0 format

Display:
1. **Skill name** — the one-sentence `description` from the frontmatter
2. A numbered list of the major steps, each annotated as `auto`, `you choose`, or `you confirm`
3. A one-line summary of which steps require confirmation and which are auto-executed
4. `Ready to start? [Y / N]`

Do not begin Step 1 until the user confirms. If the user declines, offer to explain the
skill in more detail or exit.

### Template

```markdown
## Step 0 — Overview

On skill invocation, display:

---
**{skill-name}** — {description from frontmatter}

Steps:
  1. {step name} ........... auto
  2. {step name} ........... you choose
  ...
  N. {step name} ........... you confirm

Confirmation required: Steps M, N
Auto-executed: all others

Ready to start? [Y / N]
---

Do not begin Step 1 until the user confirms.
```

### Profile skills and other menu-driven skills

Profile management skills (`ts-profile-*`) display an interactive menu on invocation.
Add a one-sentence context line before the menu — no confirmation gate needed.
These skills are exempt from Step 0 because the menu IS the entry point.

### Research-only skills

Skills that perform only read operations (no API writes, no file modifications) should
show the plan but may proceed without waiting for explicit confirmation.

---

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

Before filing an open-item, query the SpotterCode MCP first — `get-rest-api-reference`
for endpoint shape, `get-developer-docs-reference` as fallback for broader concepts.
Most "what does this endpoint do?" questions are answerable from the spec without
a live instance. See `.claude/rules/api-research.md` for precedence and finding format.

If the MCP doesn't answer the question — or the question is build/version-specific
behaviour that needs live verification — document it in `references/open-items.md`
with the question, a self-contained test script, and space to record the finding.
Do not ship skills with unresolved high-risk open items.

## Temp file hygiene

Any `/tmp/ts_token_*.txt` written during a skill session must be cleaned up at skill end.
The `ts` CLI manages its own token cache — skills should not create additional token files.

## Personal references

Internal URLs, environment-specific GUIDs, and other personal context that should not
be committed to this repo belong in the Claude Code memory system
(`~/.claude/projects/.../memory/`), not in skill files or shared references. Use the
`reference` memory type for pointers to internal resources (e.g. internal source control
URLs, private API playgrounds). This keeps the repo clean and public-safe.

## Adding a skill

1. Create `agents/claude/<skill-name>/SKILL.md` with frontmatter
2. Add symlink step to agents/claude/SETUP.md (Developer Install section)
3. Add row to skills table in README.md and agents/claude/SETUP.md
4. Create matching `agents/coco/<skill-name>/SKILL.md` if the logic applies to both runtimes
5. Add the new skill's shared file to agents/coco/SETUP.md stage copy list if applicable
