<!-- currency: claude-harness — 2026-08 (Claude 5 family: Fable 5 / Opus 5 / Sonnet 5; Haiku 4.5); 2026-08-26: anchor was stale at 2026-07 after the 96a9c59 rewrite (finding 18.7) -- this file is already in check_mapping_currency's ANCHORED_FILES (added earlier the same day, PR #447), so staleness is nudged rather than remembered -- only the anchor VALUE was stale; frontmatter inventory completed and `tools:` declared on the two read-only agents (finding 18.6) -->

# Model and Effort Routing

Which model tier and reasoning effort each kind of work gets. The goal: spend the
expensive model where judgment changes the outcome (planning, review verification,
semantic auditing, synthesis) and the cheap tiers where the work is mechanical
(running validators, grep/diff-shaped scans, scripted git operations).

## Where routing is encoded

| Surface | Mechanism | Current assignments |
|---|---|---|
| `.claude/agents/*.md` | `model:` frontmatter (`sonnet`/`opus`/`haiku`/`fable`, or `inherit`) and `effort:` (`low`/`medium`/`high`/`xhigh`/`max`) — plus **`tools:` / `disallowedTools:`**, `permissionMode`, `isolation`, `maxTurns`, `skills`, `memory`, `mcpServers`, `hooks` (subagent-scoped), `background`, `color`, `initialPrompt` (inventory completed 2026-08-26, finding 18.6 — the previous list omitted the two that matter most) | `consistency-checker:` session model at `effort: low` (runs validators, greps — mechanical, but see "effort over model" below); `repo-publisher: sonnet` (scripted commit → branch → PR → stage-sync flow); `conversion-consistency-auditor:` unset — inherits the session model (semantic judgment) |
| `.claude/workflows/*.js` | `effort:` (and rarely `model:`) per `agent()` call | repo-audit: `low` for mechanical finders (dead-files, pr-validation, dependencies); `max` for the angle-17 code-review backstop; default for everything else |
| `.claude/settings.json` | No `model` pin | The interactive session inherits the user's default. Planning and QA happen interactively, so the session default should be the strong tier |

## Tool grants — a contract is not an enforcement

`tools:` was absent from this file's inventory until 2026-08-26 (finding 18.6), and the
consequence was concrete: `conversion-consistency-auditor`'s description ended
**"Read-only."** and `consistency-checker` is a pure reporter, yet neither declared a
grant — so nothing but the prompt stopped either from editing the repo it was auditing.
An agent that *reports* on correctness is exactly the one whose write access should be
denied rather than requested.

Both now declare `tools: Bash, Read, Grep, Glob`. State the limit honestly: **Bash can
mutate**, and both agents genuinely need it (one runs validators, the other greps and
globs), so removing Edit/Write/NotebookEdit narrows the surface without closing it. The
guarantee is partial by design. Closing it fully would mean re-expressing every `ls`/
`grep` step as Glob/Grep tool calls and dropping Bash — worth doing for the auditor if
its instructions are ever rewritten, but not worth a rewrite on its own.

**When adding a read-only agent, declare `tools:`.** A description that says "read-only"
without a grant is a comment, not a control.

## Rules of thumb

- **Default to inheriting.** Only set a tier when you are confident the task shape
  justifies it — a wrong cheap-tier assignment costs more in rework than it saves.
- **Describe the WORK, not the model.** Rewritten 2026-08-26 (finding 18.5). These
  bullets used to lead with model names — "Haiku: deterministic checklists", "Sonnet:
  mechanical multi-step work" — which contradicted the corollary below and, worse, goes
  stale on every lineup change. A rule that names a model has to be re-audited each time
  the family moves; a rule that names a *work shape* does not.
- **But "effort over model" is not a complete policy**, and this file said so too
  absolutely on its first rewrite. Corrected 2026-08-26 against the portable policy in
  `~/.claude/CLAUDE.md`, which is the governing statement — this project rule is *more
  specific and therefore wins*, so an over-simplification here silently overrides the
  correct general rule. Two cases are genuinely **model**-shaped and cannot be expressed
  as effort:
  - the **cheapest tier does not support the effort parameter at all** - it forfeits the
    dial rather than rejecting a call, which is easy to miss - so choosing it is a model
    decision with no effort equivalent; and
  - **frontier reasoning or long-horizon agentic work** is what the top model is for, at a
    real price premium.

  **Why the old wording mattered.** This bullet read "the cheapest tier *rejects* the
  effort parameter outright" until 2026-08-27. "Rejects" tells a reader they would find
  out; they would not. The client gates on a `supportsEffort` property and drops the
  parameter, and the runtime describes the result in its own words as the active level
  "after any **silent downgrade** for the selected model" - the same trap class as an
  `effortLevel` settings key that quietly discards `max`. Ask for a level the model cannot
  do and you get less, with no error. Verified against the installed binary, not inferred
  from the schema.

  Recording it because the paragraph above predicted this exact failure: it says an
  over-simplification *here* silently overrides the correct general rule, since this file
  is more specific and therefore wins. It then contained one for a day, while
  `~/.claude/CLAUDE.md` - which it names as the governing statement - already carried the
  accurate version. A file that can describe its own failure mode can still live it.

  Where the requirement is model-shaped, name it — and **write the reason beside it**, so a
  later reader can tell a considered choice from a copied one. That is what
  `repo-publisher`'s pin does, and why it survives.
- **Mechanical work** — deterministic checklists, running commands and reporting
  pass/fail, grep-and-collate. No synthesis, no judgment calls. → **inherit the model,
  drop `effort` to `low`.**
- **Prescribed multi-step work** where mistakes have consequences but the steps are
  fixed (repo-publisher's commit → branch → PR → stage-sync sequence). → inherit, or pin
  *only* under the corollary below.
- **Judgment work** — anything that weighs evidence: planning, code-review verification,
  semantic consistency auditing, audit synthesis, and **every review gate**. → **inherit
  the model at `effort: high`→`max`.** Never downgrade a gate; an independent reviewer
  that reasons less than the author is worse than no reviewer.
- **Effort over model** — *read with the qualification three bullets above, which this
  bullet used to omit.* In workflows and in agent frontmatter, prefer `effort: low` on a
  strong model for mechanical stages rather than downgrading the model — same savings
  profile, less capability risk. Reserve `effort: 'max'` for adversarial verification.
  Note the dial is not available on every path: the `Agent` tool takes `model` but no
  `effort`, so there the model *is* the only lever (see `~/.claude/CLAUDE.md`). Say which
  dial you actually had when justifying a choice.
- **Corollary — a `model:` pin needs a reason the effort dial cannot serve.** The dial
  is the default lever; a pin is the exception. `repo-publisher: sonnet` keeps its pin
  because its risk is a *partial publish* from a long prescribed sequence, not shallow
  reasoning — capability headroom buys nothing there. `consistency-checker` had no such
  reason, so it moved to `effort: low` on the session model (audit finding 18.3,
  2026-07-29). This also settles a standing conflict: the user's subagent-driven-
  development policy rejects Haiku for delegated work outright, which a `haiku` pin
  contradicted and an effort dial does not.

## When adding a new agent or workflow stage

Classify it by **work shape**, then reach for the **effort dial** — not a model name
(finding 18.5): *mechanical* (prescribed steps, verifiable output) → inherit the model at
`effort: low`; *judgment* (weighs evidence, synthesises, verifies) → inherit at
`effort: high`→`max`. Pin a model only under the corollary above.
Record the assignment in the table above so the audit (harness-currency angle)
can review it against the current model lineup.
