<!-- currency: claude-harness — 2026-08 (Claude 5 family: Fable 5 / Opus 5 / Sonnet 5; Haiku 4.5; 2026-08-28: assignments table dropped in favour of frontmatter-with-reason — see docs/backlog.md and the check_harness_routing.py docstring for the history) -->

# Model and Effort Routing

Which model tier and reasoning effort each kind of work gets. The goal: spend the
expensive model where judgment changes the outcome (planning, review verification,
semantic auditing, synthesis) and the cheap tiers where the work is mechanical
(running validators, grep/diff-shaped scans, scripted git operations).

**Scope.** The governing policy is `~/.claude/CLAUDE.md` ("Models and effort"). The
dated inventory of effort surfaces — which settings, flags and frontmatter keys
actually read the dial, and which silently do not — is
`~/.claude/setup-review-backlog.md`. Neither is restated here: this file restated
harness machinery twice and both copies rotted within a day of a correction landing
elsewhere (finding 18.5, 2026-08-26; the "rejects the effort parameter" claim,
corrected 2026-08-27). Requirements below; machinery in the dated inventory.

## Requirements

- **Assignments live in the agent file, nowhere else.** `model:` and `effort:` in
  `.claude/agents/*.md` frontmatter are the single source of truth. The former
  "Current assignments" table here was a second hand-maintained copy of the
  frontmatter plus a validator rule to keep the copies equal — double bookkeeping,
  and a merge-conflict funnel for concurrent sessions. Dropped 2026-08-28.
- **Classify by work shape, then reach for the effort dial — not a model name**
  (finding 18.5: rules that name models go stale on every lineup change; rules that
  name work shapes do not). *Mechanical* (prescribed steps, verifiable output:
  validators, greps, scripted git) → inherit the model at `effort: low`.
  *Judgment* (weighs evidence, synthesises, verifies — and **every review gate**) →
  inherit at `effort: high`→`max`. Never downgrade a gate; an independent reviewer
  that reasons less than the author is worse than no reviewer.
- **A `model:` pin needs a reason the effort dial cannot serve, written beside it**
  as a `# reason:` comment inside the frontmatter block — its own line or inline on
  the pin (enforced by `tools/validate/check_harness_routing.py`). `repo-publisher`'s
  pin is the worked example: its risk is a *partial publish* from a long prescribed
  sequence, not shallow reasoning — capability headroom buys nothing there.
- **No Haiku pin for delegated work** (enforced by the same validator). The
  subagent-driven-development policy rejects it outright; the governing policy in
  `~/.claude/CLAUDE.md` and the dated inventory record why the cheap tier cannot be
  reached through the effort dial instead.
- **A read-only agent declares `tools:`.** A description that says "read-only"
  without a grant is a comment, not a control (finding 18.6: two pure reporters
  declared no grant, so nothing but the prompt stopped them editing the repo they
  audit). `Bash` can mutate, so a grant that keeps Bash narrows the surface without
  closing it — state that honestly in the agent file, as
  `conversion-consistency-auditor` does.

## Repo-specific assignments outside frontmatter

Workflow stages pass `effort` per `agent()` call in `.claude/workflows/*.js`:
repo-audit uses `low` for the mechanical finders (dead-files, pr-validation,
dependencies) and `max` for the angle-17 code-review backstop. The interactive
session inherits the user's default model — planning and QA happen interactively,
so the session default should be the strong tier; `.claude/settings.json` pins
nothing.
