# Review-File Explainers — `ts-coach-model`

Every review file generated in [SKILL.md Step 7](../SKILL.md) is prepended with a
3-section explainer block so the user can pick decisions confidently without
re-reading the whole skill.

The premise: a markdown table of proposals is opaque on its own. Before showing
rows, the file must answer three questions:

1. **WHAT THIS IS FOR** — the purpose of this Spotter coaching surface and
   how it changes Spotter's behaviour
2. **WHAT WE CHECKED** — the signals and heuristics the skill used to produce
   the proposals (so the user can tell which rows are well-grounded vs. inferred)
3. **RULES FOR THE OUTCOMES YOU CAN PICK** — every allowed `RouteAction` value,
   when to use it, and what happens when the skill applies it

The blocks below are the canonical text. Each generator in
[SKILL.md Step 6](../SKILL.md) prepends its block verbatim to the corresponding
review file.

> **Show vs. collapse.** Always show the full explainer block. Re-runs are
> infrequent enough that the cost is small, and showing the rules every time
> means the user notices when the skill itself has changed.

---

## Variable substitution

Each block contains placeholder counts (`{N_columns}`, `{N_models_scanned}`,
etc.). Substitute from the run before writing the file.

| Placeholder | Source |
|---|---|
| `{N_columns}` | Total columns on this Model |
| `{N_filled}` | Columns with existing populated values for this surface |
| `{N_models_scanned}` | Models enumerated in the cross-Model consistency scan (Step 4.5) |
| `{N_proposals}` | Proposals being shown in this file |
| `{Model name}` | This Model's display name |

---

## Block 1 — `ai_context.md`

```
─── ai_context.md ──────────────────────────────────────────────────────────────
WHAT THIS IS FOR
  AI Context is per-column free text that Spotter's coaching index reads to
  understand what each column MEANS. It's the most direct way to answer the
  "same name, different meaning" problem — Spotter learns "[Amount] on this
  Model is dollar value of one order line, NOT net of discounts" from this
  field. Humans see the column's `description` (a separate, prose field);
  Spotter primarily uses `ai_context`.

WHAT WE CHECKED
  - Existing ai_context: {N_filled} of {N_columns} columns populated
  - For each unfilled column we mined evidence from:
      • dependent Answer/Liveboard prose
      • the column's table grain (e.g. DM_ORDER_DETAIL = order-line grain)
      • the formula expression (for formula columns)
      • the warehouse column it points at (db_column_name)
  - We then filled the structured ai_context schema (9 axes — meaning, unit,
    includes, excludes, source, time_basis, null_zero, watch_out, formula).
    Where evidence was insufficient, the slot is left as `# REVIEW_REQUIRED`
    so the question is asked, not guessed.
  - For columns with EXISTING ai_context: we critiqued for length (<30 chars
    triggers REFINE), missing semantic axes, and conflicts with mined prose.

RULES FOR THE OUTCOMES YOU CAN PICK
  | RouteAction | Use when | Effect |
  |---|---|---|
  | KEEP | Proposed YAML is correct; you've reviewed every # REVIEW_REQUIRED | Imported as-is |
  | EDIT | You filled in or changed any line | Whatever you wrote becomes authoritative |
  | DROP | This column shouldn't have AI Context (e.g., internal ID columns) | No ai_context written |
  | DEFER | You need to confirm a # REVIEW_REQUIRED slot but can't right now | Column is skipped this run; flagged on next run |

  The "Slots filled" column shows how many of the 9 axes were auto-populated.
  Anything below 9 means at least one axis is # REVIEW_REQUIRED. Importing
  with REVIEW_REQUIRED slots is allowed but not recommended — they're visible
  to anyone reading the Model.
────────────────────────────────────────────────────────────────────────────────
```

---

## Block 2 — `synonyms.md`

```
─── synonyms.md ────────────────────────────────────────────────────────────────
WHAT THIS IS FOR
  Column synonyms are alternative names attached to a column at the schema
  level. When Spotter's parser sees a synonym in a query, it substitutes the
  column wherever the synonym appears — ONE entry covers MANY query shapes.
  This is Method A in the three-method model. Use this for phrases that are
  truly another name for an existing column (e.g. "revenue" → [Amount]); use
  Method B (Business Terms) for phrases that target a Model formula; use
  Method C (Reference Questions) for whole-sentence phrasings.

WHAT WE CHECKED
  - Existing synonyms: {N_filled} of {N_columns} columns populated
  - Critique of existing synonyms — flagged AUTO_GENERATED entries on FK ID
    columns as low-value (FK IDs are rarely searched by name)
  - For each column we compiled candidate phrases from:
      • prose mining: noun phrases that match the column name with stem
        overlap ≥ 0.6 in dependent Answer/Liveboard text
      • common business shorthands inferred from the column's apparent role
      • mined search_query strings where the phrase appears alongside this
        column
  - Rejected phrases that are exact substrings/supersets of the display name

RULES FOR THE OUTCOMES YOU CAN PICK
  | RouteAction | Use when | Effect |
  |---|---|---|
  | KEEP | Proposed phrases are right | All phrases added to column.synonyms[] |
  | DROP | Don't add any synonyms to this column | No change to this column |
  | EDIT | You changed the proposed phrase list | Your list becomes authoritative |
  | MOVE_TO_B | The phrase actually targets a Model formula, not a column | Re-routed to business_terms.md |
  | MOVE_TO_C | The phrase is really a whole-sentence question | Re-routed to candidates.md / mappings.md |
────────────────────────────────────────────────────────────────────────────────
```

---

## Block 3 — `candidates.md` (Reference Questions, Stage 1)

```
─── candidates.md ──────────────────────────────────────────────────────────────
WHAT THIS IS FOR
  Reference Questions are whole-sentence anchors that tell Spotter "when
  someone asks THIS, return THAT answer." They cover queries that don't
  decompose into the column-by-column shape Spotter parses naturally. This
  file is STAGE 1 of the Method C review — confirm WHICH questions to coach.
  Stage 2 (mappings.md) confirms how each gets translated to search_tokens.

WHAT WE CHECKED
  - Generated {N_proposals} candidate questions across 4 tiers (T1
    foundational, T2 time-based, T3 filters/ratios, T4 complex)
  - Scored each candidate on additive signals:
      • +5 if its tokens overlap a real search_query mined from a dependent
        Answer/Liveboard
      • +4 if its tokens match an existing GLOBAL feedback entry's shape
      • +3 if its primary measure is in mined searches (partial match)
      • +2 if its dimension is a join key for ≥ 2 tables (D_join)
      • +2 if the measure appears in any dependent Liveboard tile
      • +1 if it's a T1/T2 pattern (foundation coverage bonus)
      • +1 if it requires a formula not already on the Model
  - Selected the top 15 (or 10 for sparse Models) with tier minimums:
    ≥ 3 T1, ≥ 2 T2, ≥ 2 T3, ≥ 1 T4

RULES FOR THE OUTCOMES YOU CAN PICK
  | RouteAction | Use when | Effect |
  |---|---|---|
  | KEEP | Question reads natural, scope is right | Carried into Stage 2 |
  | DROP | Doesn't reflect how analysts here actually ask | Removed entirely |
  | EDIT | You rewrote the question text | Your text replaces the proposed |
  | MOVE_TO_A | The phrase is really a column synonym, not a sentence | Re-routed to synonyms.md |
  | MOVE_TO_B | The phrase targets an existing Model formula | Re-routed to business_terms.md |
────────────────────────────────────────────────────────────────────────────────
```

---

## Block 4 — `mappings.md` (Reference Questions, Stage 2)

```
─── mappings.md ────────────────────────────────────────────────────────────────
WHAT THIS IS FOR
  Stage 2 of Method C review. Each kept Reference Question is shown with its
  full specification — search_tokens (the column-bracket form Spotter's
  parser maps the question to), 2–3 paraphrase variants (more anchor
  phrasings → wider match), chart_type, and any required answer-level
  formula. Editing rules are the same as Stage 1; this stage exists because
  reviewing tokens and formulas is a different mental task from confirming
  questions.

WHAT WE CHECKED
  - For each kept question, generated 2–3 paraphrase variants from the
    template table in token-mapping-rules.md §5
  - Mapped each question's intent to search_tokens using:
      • bare-bracket display-name references for columns and formulas
      • documented search-bar keywords (top N, monthly, last 30 days, etc.)
  - For questions needing a formula, generated the expression from
    token-mapping-rules.md §2 and verified the function exists in
    thoughtspot-formula-patterns.md (the t4.yoy/mom patterns are excluded
    until open-item #13 verifies a working growth-% formula)

RULES FOR THE OUTCOMES YOU CAN PICK
  | RouteAction | Use when | Effect |
  |---|---|---|
  | KEEP | Tokens, variants, formula all look right | Imported as REFERENCE_QUESTION entries (one per variant, all sharing tokens + formula) |
  | DROP | Question is wrong or unimportant | Dropped from this run |
  | EDIT | You modified tokens, variants, or formula expression | Your text becomes authoritative |
  | MOVE_TO_A | The phrase is really a column synonym | Re-routed to synonyms.md |
  | MOVE_TO_B | The phrase targets an existing Model formula | Re-routed to business_terms.md |
────────────────────────────────────────────────────────────────────────────────
```

---

## Block 5 — `business_terms.md`

```
─── business_terms.md ──────────────────────────────────────────────────────────
WHAT THIS IS FOR
  Business Terms are coaching-layer phrase → existing Model artifact mappings.
  They behave like column synonyms (Method A) but the target can be a Model
  formula, not just a column. Use this for phrases like "stock on hand" →
  [Inventory Balance] (a formula, not a column — synonyms can't reach it).
  Business Terms cannot define new formulas inline (verified in open-item
  #12) — if a phrase needs a calculation that doesn't yet exist on the Model,
  the proposal is marked MOVE_TO_NEW_FORMULA and you create the Model formula
  first via /ts-object-answer-promote, then re-run this skill.

WHAT WE CHECKED
  - For each prose-mined phrase, checked whether it could decompose
    word-by-word into existing Model columns (if yes → Method A) or
    targeted a single Model formula (if yes → Method B / this surface)
  - Excluded phrases targeting formulas not yet on the Model (emitted as
    MOVE_TO_NEW_FORMULA in this file, no default RouteAction)

RULES FOR THE OUTCOMES YOU CAN PICK
  | RouteAction | Use when | Effect |
  |---|---|---|
  | KEEP | Phrase → existing-formula mapping is right | BUSINESS_TERM entry created |
  | DROP | Phrase is wrong / not used in your org | No entry created |
  | EDIT | You changed the phrase or the target formula | Your text becomes authoritative |
  | MOVE_TO_A | Phrase actually targets a column, not a formula | Re-routed to synonyms.md |
  | MOVE_TO_C | Phrase is really a whole-sentence question | Re-routed to mappings.md |
  | MOVE_TO_NEW_FORMULA | The target formula doesn't exist yet on the Model | No entry created. You're directed to /ts-object-answer-promote to create the formula, then re-run this skill |
────────────────────────────────────────────────────────────────────────────────
```

---

## Block 6 — `cross_model_consistency.md`

```
─── cross_model_consistency.md ─────────────────────────────────────────────────
WHAT THIS IS FOR
  Spotter doesn't know that "[Amount]" in this Model means something different
  from "[Amount]" in your other Models — it just sees a column with the same
  name. When users ask "show me amount by region," Spotter's parser may pick
  the wrong Model's column, or the SAME query may return different numbers
  depending on which Model the user happens to be querying. This is the most
  common cause of "the dashboards disagree" complaints, and is the central
  failure mode the article-of-record on enterprise text-to-SQL flagged
  (see references/cross-model-consistency.md for the source).

WHAT WE CHECKED
  For each of the {N_columns} columns in this Model, we searched the
  {N_models_scanned} Models you can read in this org and compared:
    1. db_column_name        — does the column point at the SAME warehouse
                               column? (different source = almost always
                               different meaning)
    2. column_type            — measure vs attribute mismatch
    3. aggregation            — sum vs avg = different semantics
    4. formula expression     — for formula columns, does the math agree?
    5. ai_context text        — if both Models have AI Context, do the
                               descriptions contradict each other?

  We did NOT compare display-name spelling variants (e.g., "Amount" vs
  "Total Amount"). Exact-name matching only, to keep false-positive rate low.

RULES FOR THE OUTCOMES YOU CAN PICK
  | RouteAction | Use when | Effect |
  |---|---|---|
  | KEEP_AS_IS | Other Models are wrong or out of scope; this Model is canonical | No change. The clash continues to exist in the org |
  | ALIGN | Other Models should adopt this Model's definition | Skill emits a follow-up plan: which Models to update, which fields. No automated edits |
  | RENAME | Both definitions are legitimate; rename one to disambiguate | Skill suggests a name (e.g., "Order-line Amount" vs "Order Amount"). Rename applied to THIS Model only; you propagate elsewhere |
  | DOCUMENT_DIFFERENCE | Differences are intentional; record why in ai_context | Skill adds a `# CONFLICTS_WITH:` line to this column's ai_context with the other Models' GUIDs and your one-line rationale |
  | INTENTIONAL_DIFFERENCE | Same as above but no documentation needed (rare — separate audiences) | No change |
  | NEEDS_REVIEW | Can't tell yet; come back later | Surfaced again on the next run |
────────────────────────────────────────────────────────────────────────────────
```

---

## Block 7 — `description.md` (Model description)

```
─── description.md ─────────────────────────────────────────────────────────────
WHAT THIS IS FOR
  The Model description is the human-readable summary shown in the catalog,
  in hover tooltips, and on the Model preview. It tells someone unfamiliar
  with the Model what entities are in it, what grain each fact is at, what's
  in scope vs out of scope, and any known anomalies. Spotter does NOT
  primarily use this field — global rules for Spotter live in Data Model
  Instructions (see instructions.md).

WHAT WE CHECKED
  - Length: a description under ~100 chars is almost always too short to
    convey the Model's purpose
  - Coverage: does it mention the primary measures, primary dimensions, and
    fact-table grains?
  - Provenance: does it identify the source system or the spec / owner?
  - Scope: does it say what's in vs out (e.g. "active customers only")?

RULES FOR THE OUTCOMES YOU CAN PICK
  | RouteAction | Use when | Effect |
  |---|---|---|
  | KEEP | Existing description is good as-is | No change |
  | EXPAND | Existing has the right idea but is too thin | Proposed text replaces existing |
  | REWRITE | Existing is stale or off-topic | Proposed text replaces existing |
  | EDIT | You wrote your own description | Your text becomes authoritative |
  | DROP | Don't write any description | description field cleared (rare) |
────────────────────────────────────────────────────────────────────────────────
```

---

## Block 8 — `instructions.md` (Data Model Instructions)

```
─── instructions.md ────────────────────────────────────────────────────────────
WHAT THIS IS FOR
  Data Model Instructions are global rules Spotter applies when interpreting
  queries against this Model — e.g. "when users say 'last month', use the
  last 30 days" or "for revenue questions, use Amount unless explicitly
  asked about gross." They live in a Spotter-specific TML location (TBD —
  see open-item #4) and are pasted into the UI under
  Settings → Coach Spotter → Instructions until that location ships.

WHAT WE CHECKED
  - Mined patterns from search_query strings and Snowflake history that
    suggest a global rule (recurring relative-time phrases, recurring
    measure-disambiguation phrasings)
  - Generated rule candidates from those patterns

RULES FOR THE OUTCOMES YOU CAN PICK
  | RouteAction | Use when | Effect |
  |---|---|---|
  | KEEP | Rule is right and useful | Saved to instructions.md for manual paste |
  | DROP | Rule is wrong or never triggers | Removed |
  | EDIT | You rewrote the rule | Your text becomes authoritative |
────────────────────────────────────────────────────────────────────────────────
```

---

## Per-surface block lookup

When generating a review file in Step 6, prepend the matching block:

| Generator Step | Output file | Explainer block |
|---|---|---|
| 6.1 Column AI Context | `ai_context.md` | Block 1 |
| 6.2 Column Synonyms | `synonyms.md` | Block 2 |
| 6.3 Reference Questions, Stage 1 | `candidates.md` | Block 3 |
| 6.3 Reference Questions, Stage 2 | `mappings.md` | Block 4 |
| 6.4 Business Terms | `business_terms.md` | Block 5 |
| 6.7 Cross-Model Consistency *(new)* | `cross_model_consistency.md` | Block 6 |
| 6.6 Improved Model Description | `description.md` | Block 7 |
| 6.5 Data Model Instructions | `instructions.md` | Block 8 |

The lookup is stable; if the SKILL.md step numbers change, only this table updates.
