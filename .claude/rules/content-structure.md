# Content Structure Rules

Two decisions come up repeatedly: where to put new content, and when to split a file.
These rules give a consistent answer to both.

---

## Where does new content belong?

Work through these questions in order. Stop at the first match.

### 1. Is it used by both the Claude skill AND the CoCo skill?
**→ agents/shared/**

Examples: formula translation tables, TML schema references, property mapping rules,
worked examples. Both runtimes read these files; putting the content in either
`agents/claude/` or `agents/coco/` means the other runtime gets a stale copy.

### 2. Is it a lookup table, schema reference, or worked example used by 2+ skills?
**→ agents/shared/**

Even if only one runtime currently uses it, if more than one skill references it the
content belongs in shared/ so there is one source of truth. Duplicating content across
SKILL.md files means rule changes require touching multiple files — and they will drift.

### 3. Is it procedural step logic specific to one skill, but too large for SKILL.md?
**→ agents/claude/<skill>/references/ or agents/coco/<skill>/references/**

Skill-local reference files: lookup tables, test scripts, open-items tracking. Used only
by one skill, not shared across skills or runtimes. SKILL.md references them with a link.
The `references/open-items.md` pattern is the canonical example.

### 4. Everything else
**→ inline in SKILL.md**

Step-by-step procedural logic, decision trees, runtime-specific instructions, anything
used only in this one skill and small enough to read in context. If it is a sequence of
steps a contributor must follow, keep it in SKILL.md — forcing them to jump to another
file to read a procedure breaks the flow.

---

## When to split a single MD file into smaller parts

Split when **any** of these are true:

| Signal | Why it matters |
|---|---|
| Another file already links to a section inside this file | The section has its own identity — give it its own file |
| The section is a lookup table (rows + columns) in a file that is otherwise prose | Tables and prose change for different reasons and have different readers |
| The section will change at a different cadence than the rest of the file | Splitting avoids unnecessary diffs and makes review easier |
| The file exceeds ~250 lines and has clearly separable concerns | Long files with mixed purposes are hard to navigate and cause context bloat when loaded |
| A rule or example in this file would also belong in another skill | Move it to shared/ rather than duplicating |

Keep together when **all** of these are true:

- The content is a single coherent procedure (steps that must be read as a sequence)
- The file is under 200 lines
- No other file needs to link to a specific section of it
- Splitting would require readers to jump files to follow one logical flow

---

## Specific cases

### "Should this formula go in SKILL.md or in ts-snowflake-formula-translation.md?"

If the formula is a ThoughtSpot↔Snowflake translation pattern:
→ **ts-snowflake-formula-translation.md** (the authoritative mapping reference).
Never add inline formula logic to SKILL.md — the skill reads the reference file.

If the formula is a worked example showing how a specific model was translated:
→ **agents/shared/worked-examples/snowflake/** if verified against a live instance,
or **agents/claude/<skill>/references/** if it is a skill-local test case.

### "Should this go in the CoCo SKILL.md or the Claude SKILL.md or both?"

If the logic is the same in both runtimes (same rules, same mapping, same output):
→ Put the **rules and reference** in agents/shared/ and link from both SKILL.md files.
The SKILL.md files then contain only the runtime-specific *invocation* (how to call an
API vs. how to call a stored procedure).

If the logic is runtime-specific (e.g., stored procedure name, interactive prompt wording):
→ Keep it in the individual SKILL.md. Do not put CoCo stored procedure names in shared/.

### "This SKILL.md is getting long — should I split it?"

Check the nature of the long sections:
- If they are **lookup tables or reference data** → move to references/ or shared/
- If they are **sequential procedure steps** → keep together; a long procedure is still
  one file's job. Consider whether some steps can be shortened by linking to shared/ references
  instead of repeating rules inline.

### "Should I add a new file to agents/shared/schemas/ or agents/shared/mappings/?"

**schemas/** — structural reference for a platform's object format (TML, Semantic View YAML,
connection object). One file per object type, per platform.

**mappings/ts-snowflake/** — translation rules between ThoughtSpot and Snowflake concepts.
New platforms get a new subdirectory (e.g., mappings/ts-databricks/), not new files
in the Snowflake mapping directory.

When you add to either: update agents/coco/SETUP.md stage copy list and run
`./scripts/stage-sync.sh` — shared/ files must be deployed to the stage to reach CoCo.
