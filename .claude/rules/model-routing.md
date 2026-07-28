<!-- currency: claude-harness — 2026-07 (Claude 5 family: Fable 5 / Opus 5 / Sonnet 5; Haiku 4.5) -->

# Model and Effort Routing

Which model tier and reasoning effort each kind of work gets. The goal: spend the
expensive model where judgment changes the outcome (planning, review verification,
semantic auditing, synthesis) and the cheap tiers where the work is mechanical
(running validators, grep/diff-shaped scans, scripted git operations).

## Where routing is encoded

| Surface | Mechanism | Current assignments |
|---|---|---|
| `.claude/agents/*.md` | `model:` frontmatter | `consistency-checker: haiku` (runs validators, greps); `repo-publisher: sonnet` (scripted git/stage ops); `conversion-consistency-auditor:` unset — inherits the session model (semantic judgment) |
| `.claude/workflows/*.js` | `effort:` (and rarely `model:`) per `agent()` call | repo-audit: `low` for mechanical finders (dead-files, pr-validation, dependencies); `max` for the angle-17 code-review backstop; default for everything else |
| `.claude/settings.json` | No `model` pin | The interactive session inherits the user's default. Planning and QA happen interactively, so the session default should be the strong tier |

## Rules of thumb

- **Default to inheriting.** Only set a tier when you are confident the task shape
  justifies it — a wrong cheap-tier assignment costs more in rework than it saves.
- **Haiku**: deterministic checklists — run these commands, report pass/fail, grep
  and collate. No synthesis, no judgment calls.
- **Sonnet**: mechanical multi-step work where mistakes have consequences but the
  steps are prescribed (repo-publisher's commit → push → stage sequence).
- **Session default (strong tier)**: anything that weighs evidence — planning,
  code review verification, semantic consistency auditing, audit synthesis.
- **Effort over model** in workflows: prefer `effort: 'low'` on a strong model for
  mechanical stages rather than downgrading the model — same savings profile,
  less capability risk. Reserve `effort: 'max'` for adversarial verification.

## When adding a new agent or workflow stage

Classify it: *mechanical* (prescribed steps, verifiable output) → haiku/sonnet or
`effort: 'low'`; *judgment* (weighs evidence, synthesises, verifies) → inherit.
Record the assignment in the table above so the audit (harness-currency angle)
can review it against the current model lineup.
