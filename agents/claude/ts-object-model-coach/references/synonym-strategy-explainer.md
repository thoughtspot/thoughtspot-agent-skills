# Coaching Method Explainer — `ts-coach-model`

Inline reference shown to the user during [SKILL.md](../SKILL.md). The explainer
must be displayed **verbatim** at three points:

| When to show it | Where in SKILL.md |
|---|---|
| Before Step 6 generation, whenever Methods A / B / C are involved | Step 5 (after the surface selection menu) |
| Before each per-surface review file is opened | Step 7 (one Method label per surface) |
| When the user is uncertain which Method a phrase should use | On demand, in response to user questions |

The premise: **users will not absorb technical vocabulary** ("search_tokens",
"BUSINESS_TERM", "nls_feedback") on first read. Every decision point must show plain
English with examples drawn from the user's own Model.

The explainer is also valuable for re-runs — when the user runs the skill again in
six months, they will have forgotten the distinctions. Showing it again with their
specific phrases lets them confirm their previous choices still apply.

---

## Variable substitution

Before display, substitute these variables with values from the user's Model. The
table below lists every variable used in the explainer text.

| Variable | Source |
|---|---|
| `{Model name}` | `model.name` |
| `{Method A example column}` | A high-confidence Synonym proposal — usually the column with the most synonym candidates |
| `{Method A example phrase}` | The top-scored synonym phrase for that column |
| `{Method A example query 1..5}` | Five concrete queries the synonym would catch — generated from common search shapes (`by month`, `top 10 ___`, `for ___`, etc.) |
| `{Method B example phrase}` | A phrase from prose mining that targets an existing Model formula |
| `{Method B existing formula}` | The Model formula being targeted (must already exist on the Model) |
| `{Method B example chart_type}` | Default chart_type for that BT entry (typically `KPI`) |
| `{Method C example phrase}` | A conversational paraphrase from the proposed Reference Question variants |
| `{Method C example tokens}` | The `search_tokens` we'd map it to |
| `{Method C example chart_type}` | The chart type for that question |
| `{N_method_a}` | Total synonym proposals (column-targeted phrases) |
| `{N_method_b}` | Total Business Term proposals (formula-targeted phrases) |
| `{N_method_c}` | Total Reference Question proposals (canonical + variants) |
| `{Method A first 5 proposals}` | Five concrete `phrase → [Column]` rows |
| `{Method B all proposals}` | List of phrase → formula mappings |
| `{Method C representative canonical + variants}` | One canonical question with its variants, then a second one |

---

## The user-facing explainer (verbatim)

```
═══════════════════════════════════════════════════════════════════════════════
HOW TO COACH "{Model name}" — WHICH METHOD TO USE
═══════════════════════════════════════════════════════════════════════════════

You have three coaching methods. Each catches different kinds of user queries.
The right answer for any one phrase depends on what query SHAPES you want it to
support.

────────────────────────────────────────────────────────────────────────────────
METHOD A — Add a SYNONYM on a column
────────────────────────────────────────────────────────────────────────────────
What it does
  Tells Spotter: "when you see this phrase, treat it as if the user typed THAT
  column name." Spotter then parses the rest of the query normally.

Example using YOUR data
  Add "{Method A example phrase}" as a synonym of [{Method A example column}].
  Now ALL of these work — without any further coaching:
    ✓ "{Method A example query 1}"
    ✓ "{Method A example query 2}"
    ✓ "{Method A example query 3}"
    ✓ "{Method A example query 4}"
    ✓ "{Method A example query 5}"

Why it's powerful
  ONE entry covers MANY query shapes. The user doesn't have to type
  "{Method A example column}" exactly — Spotter substitutes "{Method A example
  phrase}" wherever it sees the word.

When to use it
  ✓ The phrase is essentially another name for a column that already exists
  ✓ You want it to work across many sentence structures

When NOT to use it
  ✗ The phrase represents a CALCULATION (margin, growth, ratio) — there's no
    column to point at. Use Method B instead.
  ✗ The phrase is a full conversational sentence — Method C is better.

────────────────────────────────────────────────────────────────────────────────
METHOD B — Add a BUSINESS TERM (phrase → existing Model formula)
────────────────────────────────────────────────────────────────────────────────
What it does
  Tells Spotter: "when you see this phrase, treat it as if the user typed THAT
  Model formula." Same substitution idea as Method A, but the target is an
  EXISTING Model-level formula instead of a plain column.

Example using YOUR data
  Your Model already has the formula [{Method B existing formula}].
  I noticed analysts also call it: "{Method B example phrase}"

  I'll add:    BUSINESS_TERM mapping "{Method B example phrase}" → [{Method B existing formula}]

  Now ALL of these work — same as Method A:
    ✓ "{Method B example phrase}"
    ✓ "{Method B example phrase} by region"
    ✓ "{Method B example phrase} for electronics"

Why we can't use Method A here
  Column synonyms (Method A) only attach to PLAIN COLUMNS — they cannot point
  at Model-level formulas. [{Method B existing formula}] is a formula, not a
  column, so we need a BUSINESS_TERM instead.

⚠ Important constraint
  BUSINESS_TERMs cannot CREATE new formulas. They can only point at things that
  already exist on the Model. If a phrase you'd like to coach maps to a NEW
  calculation:
    1. First, create the formula as a Model formula (use /ts-object-answer-promote)
    2. Then re-run this skill — it will offer the BT mapping to the new formula

When to use it
  ✓ The phrase targets an existing Model formula
  ✓ You want sentence-flexible substitution (like Method A, but for formulas)

When NOT to use it
  ✗ The phrase targets a regular column — use Method A instead, lighter weight
  ✗ The phrase needs a NEW calculation — create the Model formula first, then
    re-run this skill
  ✗ The phrase is a full sentence — Method C is better

────────────────────────────────────────────────────────────────────────────────
METHOD C — Add a REFERENCE QUESTION (whole sentence)
────────────────────────────────────────────────────────────────────────────────
What it does
  Tells Spotter: "when someone types THIS phrasing, return THIS answer."
  The match is at the WHOLE-SENTENCE level. No substitution.

Example using YOUR data
  Add "{Method C example phrase}":
    feedback_phrase : "{Method C example phrase}"
    search_tokens   : "{Method C example tokens}"
    chart_type      : {Method C example chart_type}

  This exact query works:                ✓
  Close paraphrases MAY match (fuzzy):   ~  similar wording is best-effort
  Differently structured queries DON'T match:
                                         ✗  any query that doesn't read like the
                                            sentence above; needs a Synonym

Why we can't use Method A here
  "{Method C example phrase}" doesn't decompose into your columns word-by-word.
  There's no single phrase to substitute.

When to use it
  ✓ The phrasing is conversational or idiomatic
  ✓ It's the literal way users in your org actually type the question
  ✓ You want to coach 2–3 paraphrases of the same question

When NOT to use it
  ✗ The phrase has structure Spotter can already parse — use Method A instead
  ✗ You're adding 20 paraphrases of one question — past 4 it diminishes

────────────────────────────────────────────────────────────────────────────────
DECISION TREE — apply per phrase
────────────────────────────────────────────────────────────────────────────────
For each proposed phrase, ask in order:

  1. Does it target a SINGLE COLUMN that exists in the Model?
       → YES: use METHOD A (Synonym).

  2. Does it target a CALCULATION (growth, ratio, margin)?
       → YES: use METHOD B (Business Term + formula).

  3. Is it a WHOLE QUESTION users would type word-for-word?
       → YES: use METHOD C (Reference Question).

  4. Still unsure?
       → Default to METHOD C. Doesn't change the Model schema. Spotter uses it
         as one anchor among many; you can promote to A or B later.

────────────────────────────────────────────────────────────────────────────────
WHAT WE'RE PROPOSING FOR YOUR MODEL
────────────────────────────────────────────────────────────────────────────────
Method A (Synonyms on columns):           {N_method_a} phrases
{Method A first 5 proposals}

Method B (Business Terms + formulas):     {N_method_b} phrases
{Method B all proposals}

Method C (Reference Questions):           {N_method_c} questions, with paraphrases
{Method C representative canonical + variants}

You'll review each in the next step. Anything you don't like as Method A can be
moved to Method C, edited, or dropped.
═══════════════════════════════════════════════════════════════════════════════
```

---

## Per-surface review header (Step 7)

When opening each per-surface review file in Step 7, prepend a short label that
links back to this explainer. Each file shows ONE method only, so the label is
focused:

```
─── synonyms.md ────────────────────────────────────────────────────────────────
This file lists Method A proposals — one phrase per row, each becoming a synonym
on a Model column.

Reminder of how Method A behaves:
  Add "balances" as a synonym of [Inventory Balance]
    → Spotter substitutes "balances" → [Inventory Balance] in any query.
    → "balances by month", "top customers by balances", and "balances for X"
      all start working.

If a row's phrase doesn't fit Method A — for example, it's calculated or it's a
full-sentence question — change KEEP to MOVE_TO_B or MOVE_TO_C in the first
column. The skill will route it to the right surface.
────────────────────────────────────────────────────────────────────────────────
```

The same pattern applies to `business_terms.md` (Method B) and `mappings.md`
(Method C). Each header is plain language, with one concrete example drawn from
the file's own first row.

---

## What this explainer does NOT do

- **Doesn't replace the per-row review.** The user still reviews each proposal
  individually in the markdown files. The explainer sets context for the whole
  decision; the rows are the decisions.
- **Doesn't try to teach the full TML schema.** It's a Spotter user's mental model,
  not an engineer's. Internal names like `nls_feedback` and `search_tokens` only
  appear when concretely necessary (the formula example in Method B).
- **Doesn't ask "which strategy do you want?".** The skill auto-selects per phrase
  using the decision tree. The user's choice is per row, not global.

---

## Why this format

Earlier iterations of this skill showed terse summaries like:
```
Default split (Strategy C):
  - Phrase → column         : Column Synonyms     (35 entries)
  - Phrase → answer formula : BUSINESS_TERM coaching (~3-5 entries)
  - Conversational paraphrases : REFERENCE_QUESTION (~30 with variants)
```

Field-tested observation: users who don't already know ThoughtSpot's coaching
architecture treat that as opaque. They click through, accept the defaults, and
the run produces results they don't understand. The plain-English explainer above
takes ~30 seconds to read and gives the user enough mental model to make
intentional decisions per row.
