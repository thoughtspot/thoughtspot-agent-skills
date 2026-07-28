<!-- status: ACTIVE -->

# Coding with Claude: a quickstart that grows

This is the **portable layer** of the quality framework this repo runs on, extracted
for anyone setting up their own Claude Code environment. It is deliberately *not*
"copy our setup": this repo's 39 validators, TML invariants, and skill families are
the **end state** of months of iteration, and almost every gate exists because an
incident happened first. Adopting the end state hands you ceremony without conviction.

What transfers is the **mechanism** — a small set of practices that turn incidents
into permanent protections. Adopt them in stages; grow your own gates.

**Domain-specific vs generic:** everything below works for any codebase. What does
NOT transfer from this repo: the individual validators (`check_tml.py`,
`check_skill_naming.py`, …), the `.claude/rules/` content about ThoughtSpot/Snowflake,
and the skill/runtime architecture. Treat those as worked examples of the patterns,
not as templates.

---

## Stage 0 — Day one: orientation

1. **Write a short `CLAUDE.md`** (`/init` drafts one). What the project is, how to
   build and test, the two or three conventions that actually matter. Under a page.
   Claude reads it every session — every line is a recurring token cost, so earn it.
2. **Branch protection from the start**: never commit to the default branch; every
   change is a PR. Add this rule to CLAUDE.md so Claude enforces it on itself.
3. **Permission allowlist** for the commands you run constantly (`git`, your test
   runner, your package manager) in `.claude/settings.json` — fewer prompts, and the
   allowlist doubles as documentation of what's routine.

## Stage 1 — Week one: the habits

4. **Plan before implementing.** For non-trivial work, use plan mode (or ask for a
   plan) and review it before any code is written. Reviewing a plan costs minutes;
   reviewing a wrong implementation costs the implementation.
5. **Review the diff before every PR.** Run `/code-review` on the working diff —
   scale the effort to the risk of the change. This is the *primary* bug net;
   everything later in this guide is backstop.
6. **Demand verification before completion.** "Done" means the tests ran and the
   output is shown, not that the code was written. Put this expectation in CLAUDE.md.
7. **Split CLAUDE.md into `.claude/rules/*.md`** when it outgrows a page — one file
   per concern (branching, security, testing). Focused files stay current; monoliths rot.
8. **Start a change-impact map** in CLAUDE.md: a table of "when you change X, also
   update Y". Every time a PR misses a companion change, add a row. This single
   table prevents the most common class of agent mistake — locally correct,
   globally incomplete edits.

## Stage 2 — Month one: the ratchet

9. **The two-bucket rule** — the single highest-value idea here. Every incident,
   review finding, or "we should remember this" moment exits to exactly one of:
   - **a permanent automated check** (preferred — the issue can never recur), or
   - **a dated backlog item** (real work, tracked, with an owner-date).

   Nothing stays as "we noticed this, we'll be careful next time." A finding that is
   neither codified nor backlogged is not done. Start with zero validators; add one
   per incident. Ten incidents in, you have ten gates each of which earned its place —
   and a one-line "why it exists" comment at the top of each one.
10. **Pre-commit + CI run the same checks.** Pre-commit gives the fast local loop;
    CI is the **hard gate** (enable `enforce_admins` so nobody — including you —
    merges red). Local hooks are bypassable (`--no-verify`) and machines differ;
    the server-side check is the one that counts.
11. **First three validators** worth having in any repo: a secrets scan on staged
    files, a broken-internal-reference check (paths mentioned in docs exist), and
    your unit tests. All three are generic; write them once.
12. **Auto-generate a gates catalog** (ours: `docs/quality-gates.md`) from the
    hook + CI config: name, what it checks, *why it exists*, last modified. The
    "why" column is what keeps gates honest when someone asks "can we delete this?"

## Stage 3 — Quarter one: the flywheel

13. **A periodic audit rubric** with two kinds of angles:
    - **Internal/static** — is the repo good against its own rules? (Mostly your
      validators already; the audit hunts for what should *become* one.)
    - **External/dynamic** — are our assumptions still true as the world moves?
      Products deprecate APIs, libraries EOL, best practices shift. No validator
      can catch these; a periodic specialist sweep can.
14. **Currency anchors**: any file encoding knowledge about a moving external
    product gets a header — `<!-- currency: <platform> — <YYYY-MM> -->` — recording
    when it was last validated. Sweeps then check only the delta since the anchor,
    which is what keeps periodic review tractable.
15. **Nudge, don't cron.** A freshness check that runs on every commit and prints
    "an audit is due" (by age or by accumulated work — e.g. 40+ commits) beats a
    scheduled job: audits produce findings a human must route, so run them when
    attention is available, silently skip when nothing changed.
16. **Codification: agentic → deterministic.** When the model performs the same
    mechanical transformation repeatedly (parsing, format emission, renaming),
    move it into a script or CLI the model *calls*. Deterministic code is faster,
    cheaper, testable, and doesn't vary between runs. The model's job is judgment;
    scripts do mechanics. This is the biggest token-efficiency lever available.
17. **Model/effort routing.** Spend the strong model where judgment changes the
    outcome (planning, review verification, synthesis); route mechanical agent work
    (validator running, scripted operations) to cheaper tiers or lower effort.
    Encode it in agent definitions (`model:` frontmatter) — not habit. (Ours:
    `.claude/rules/model-routing.md`.)
18. **Gate the context cost of your instruction files.** CLAUDE.md, rules, and
    skill files are loaded into context repeatedly; their size is a recurring tax.
    A size gate with warn/fail thresholds (ours: `check_skill_context_cost.py`)
    stops silent growth the same way a complexity ratchet stops god-functions.
19. **Audit the framework itself.** One audit angle should point inward: is the
    harness config current (model lineup, new Claude Code capabilities), are the
    rules files stale, do the gates still catch anything? The practices in this
    guide go stale exactly the way product mappings do.

---

## What NOT to copy

- **Don't adopt someone else's validator suite.** Gates earn their place through
  incidents. A gate nobody remembers the reason for gets bypassed, then deleted —
  usually right before it would have fired.
- **Don't build shared tooling for a second repo you don't have yet.** Extract
  the framework when the second consumer actually appears (this guide exists
  because one did).
- **Don't write rules for things the model already does well.** Rules are for
  *your* conventions and *your* incident history, not general good practice the
  model already knows.
- **Don't let the docs describe the aspiration.** Every claim in CLAUDE.md and the
  rules must match reality — an agent follows instructions literally, and a doc
  that says "CI can be bypassed" when it can't (or vice versa) causes real,
  confusing failures. When behaviour changes, the doc changes in the same PR.

## The one-sentence version

Keep instructions short and true, plan with the expensive model, review every diff,
and route every lesson into either a permanent automated check or a dated backlog
item — then periodically audit both the repo *and* the framework against a moving
world.
