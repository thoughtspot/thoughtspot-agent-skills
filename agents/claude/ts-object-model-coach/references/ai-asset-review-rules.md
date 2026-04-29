# AI Asset Review Rules — `ts-coach-model`

How to critique existing AI assets on a Model and propose deltas. Used in
[SKILL.md Step 4](../SKILL.md). The principle: existing assets are author-curated
content and are **never silently overwritten** — every change is proposed as an
explicit `ADD` / `REFINE` / `REWRITE` / `KEEP` action that the user accepts in Step 7.

The four asset types reviewed:

1. **`model.description`** — model-level free-text overview
2. **`columns[].properties.ai_context`** — per-column free-text business meaning
3. **`columns[].synonyms[]`** — per-column array of alternative names
4. **Existing `nls_feedback.feedback[]` entries** — Reference Questions and Business Terms

---

## Action vocabulary

| Action | Semantics |
|---|---|
| `KEEP` | Asset is good; no change proposed |
| `ADD` | Asset is empty; we propose a new value |
| `ADD_PHRASES` | Synonyms array exists but is missing high-value phrases; we propose appending |
| `REFINE` | Asset has a value but is incomplete or imprecise; we propose minor edits preserving the original intent |
| `REWRITE` | Asset has a value but is wrong, generic, or contradicts mined evidence; we propose a full replacement |
| `REMOVE_REDUNDANT` | A synonym is redundant with the column display name — propose removal |
| `FLAG_FOR_HUMAN` | Critique heuristic was uncertain; surface to the user without an automatic proposal |

The user can override any proposed action — including downgrading a `REWRITE` to a
`KEEP` if they disagree.

---

## 1. Reviewing `model.description`

### Critique signals

| Signal | Threshold | Implies |
|---|---|---|
| Length | < 100 chars | `EXPAND` — too thin to give Spotter useful context |
| Length | 100 – 600 chars | Likely `KEEP` — within typical sweet spot |
| Length | > 1000 chars | Possible `REFINE` — likely too verbose for Spotter |
| Coverage | Mentions ≥ 60% of measures by name (or stem) | Strong — `KEEP` |
| Coverage | Mentions < 30% of measures | Weak — `EXPAND` |
| Generic boilerplate | Phrases like "comprehensive overview", "data warehouse", "single source of truth" with no specifics | Lean toward `REWRITE` |
| `(AI generated)` suffix | Present | Medium quality — refine with mined evidence |
| Contradicts mined prose | Description says "sales fact only" but mined Liveboards heavily reference inventory | `REWRITE` |

### Output template

For `EXPAND`:

```
{original description}

The model includes {measures[:3]} for tracking {primary_business_outcome}, broken down
by {top_dims[:3]}. {grain_note} {join_note}.
```

For `REWRITE` (only when boilerplate or contradicts evidence):

```
{Model name} consolidates {primary_facts} for analyzing {top_outcomes_from_mined_seeds}.
Core measures include {measures[:5]}. Common dimensions: {top_dims[:5]}.
{date_grain_note}. Joined to {dim_tables} for {what_the_joins_enable}.
```

Do not exceed 600 characters.

---

## 2. Reviewing per-column `ai_context`

`ai_context` is **structured-only** — closed enums and refs, never prose. The
authoritative spec is [ai-context-schema.md](ai-context-schema.md). This section
covers the critique signals used in Step 4 and 7 review passes.

### Critique signals (per column)

| Signal | Implies |
|---|---|
| Empty on a measure | `ADD` — bootstrap mandatory tier (additivity, time_basis, source, grain_keys) |
| Empty on a self-explanatory key/ID | `KEEP` — empty is fine |
| Contains free-form prose / sentences | `REWRITE` — move prose to `column.description`; rebuild structured `ai_context` |
| Contains a `formula:` axis with TS DSL text | `REWRITE` — drop the formula axis; populate `additivity` + `time_basis` + `source` instead |
| Uses keys outside the closed allowed-key list | `REWRITE` — strip unknown keys |
| Missing mandatory axis on a measure (e.g. no `additivity`) | `REFINE` — add the missing axis |
| `additivity: semi_additive` without `additive_dimensions` + `non_additive_dimension` | `REFINE` — populate the sub-fields |
| `source:` doesn't resolve to a real physical column | `REWRITE` — fix the path or drop |
| `time_basis:` doesn't reference a real date dim in the Model | `REWRITE` — re-anchor |
| Total payload > 400 chars | `REFINE` — drop optional tier (`null_semantics` → `unit`); never drop mandatory |
| Mandatory tier present, all values lex-clean as enums/refs, ≤ 400 chars | `KEEP` |

### Where prose goes

Prose context that used to live in `ai_context` (business meaning, gotchas, edge
cases, grain-in-words) now lives in `column.description`. Step 6.1 generates both
surfaces; this section's critique applies only to `ai_context`. Critique for
`column.description` follows the standard "specific and grounded vs. generic" test.

### Sourcing the content

Pull from `mined_prose_extract.ai_context_evidence_per_column` (Step 3c) and combine
with structural facts from the schema. The mapping is deterministic for most axes:

| Source | Axis it populates |
|---|---|
| `column_type` (MEASURE / ATTRIBUTE) | Whether mandatory tier applies |
| `aggregation` (SUM / AVG / MIN / MAX / COUNT_DISTINCT) | First-pass `additivity` guess |
| Mined evidence flagging "snapshot" / "balance" / "closing" | Override SUM-implies-additive → `semi_additive` candidate |
| Underlying `db_column_name` + table | `source:` (deterministic — no LLM needed) |
| `formulas[]` block (formula columns) | Infer `time_basis:` from `query_groups({DATE_DIM.DATE})` refs — **never copy formula text** |
| Model join graph | Prefer the conformed shared date dim for `time_basis` if one exists |
| Existing `description` field on the underlying physical column | Seed `column.description` (prose), not `ai_context` |

See [ai-context-schema.md § Worked example](ai-context-schema.md#worked-example---inventory-balance)
for a full populated example.

---

## 3. Reviewing per-column `synonyms`

### Critique signals (per column)

| Signal | Treatment |
|---|---|
| Empty list | `ADD_PHRASES` — propose from mined synonym candidates |
| Contains the display name (case-insensitive) | `REMOVE_REDUNDANT` — that's not a synonym |
| Contains an existing column's display name from this Model | `REMOVE_REDUNDANT` — likely a misclassification |
| `synonym_type: AUTO_GENERATED` | Treat as low-confidence — propose `REFINE` if mined evidence suggests better phrases |
| `synonym_type: USER_DEFINED` | Treat as authoritative — only propose `ADD_PHRASES` (never remove) |
| Mined evidence contains high-score phrases not in the array | `ADD_PHRASES` — propose specific additions |
| Total synonyms > 8 after additions | `FLAG_FOR_HUMAN` — synonym sprawl, ask user to prune |

### Synonym proposal rules

- Only propose phrases with a Jaccard score ≥ 0.5 against the column display name
  (per [prose-mining-rules.md](prose-mining-rules.md))
- Reject synonyms that are exact substrings or supersets of other columns' display
  names — these create parser ambiguity
- Reject single-character or all-numeric phrases
- Lowercase all proposed synonyms; remove duplicate and case variants
- Cap proposed additions at 4 per column per run — large additions overwhelm review

### Coverage considerations

A column with 0 mined synonym candidates should not get `ADD_PHRASES` — empty by
default is fine. Don't synthesize synonyms without evidence.

---

## 4. Reviewing existing `nls_feedback.feedback[]` entries

Existing feedback is **the highest-quality signal available** — these entries have
already been curated by an analyst and (for `access: GLOBAL`) shared with end users.
Treat them as primary input, not just de-dup material.

### 4a. Split by access level FIRST

```python
existing_global = [e for e in existing_feedback if e.get("access") == "GLOBAL"]
existing_user   = [e for e in existing_feedback if e.get("access") == "USER"]
```

`access: GLOBAL` entries:
- Visible to all Model consumers
- Have been deliberately promoted by an analyst
- Reflect curated, validated coaching that's actively serving real queries
- **Treat as authoritative input** — preserve, learn from, and use to seed new content

`access: USER` entries:
- Private to the creator only
- May be experimental, abandoned drafts, or personal preferences
- Quality is unverified
- **Default to ignoring** — the user can opt in via the Step 5 scope menu if they want to include them

The user-facing prompt in Step 5 reads:

```
Existing feedback entries on this Model:
  Global  (shared with all users):  {N_global} entries
  User    (private to creator):     {N_user} entries

Include the USER entries as input signal for paraphrase variants and ranking? (y/N)
   Default = N. USER entries are private and may be unreviewed; safer to skip them
   unless you know the creator and trust their drafts.
```

### 4b. Critique each entry

| Existing entry has... | Action |
|---|---|
| Search tokens referencing a column that no longer exists | `FLAG_FOR_HUMAN` (entry is stale; will silently drop on next import) |
| Search tokens referencing a formula that no longer exists | `FLAG_FOR_HUMAN` |
| Identical `feedback_phrase` to a newly proposed entry | `KEEP` existing, drop the new proposal as duplicate |
| Same `search_tokens` as a new proposal but different `feedback_phrase` | Both kept — they are paraphrase variants |
| `rating: DOWNVOTE` | `KEEP` — preserve negative signal (it's anti-coaching, equally important) |
| `access: USER` and the user opted to skip USER entries (Step 5 default) | `KEEP_OUT_OF_SCOPE` — leave untouched, don't use as signal |
| `access: USER` and the user opted to include USER entries | Treat same as GLOBAL but propagate access through; never silently promote to GLOBAL |
| `access: GLOBAL` REFERENCE_QUESTION matching one of our generated patterns | `KEEP` — drop the generated proposal, mark the pattern "already covered" in scoring |
| `access: GLOBAL` BUSINESS_TERM matching one of our proposed phrase mappings | `KEEP` — drop the proposed phrase, the existing entry is authoritative |

**Never propose deleting an existing entry.** The user can manually remove via the UI
if needed. Never propose changing `access: USER` → `access: GLOBAL` automatically — if
the user wants to promote, they do it explicitly.

### 4c. Use existing GLOBAL entries as input signal

Existing `feedback_phrase` strings from GLOBAL entries are pre-validated business
language — exactly what we need for paraphrase variants. Inject them into:

| Surface | How GLOBAL feedback feeds it |
|---|---|
| Reference Question paraphrases (Step 6.3) | Existing `feedback_phrase` strings become natural variants of any new question with matching `search_tokens` |
| Synonym candidates (Step 6.2) | Existing BUSINESS_TERM `feedback_phrase` strings show how analysts have already mapped phrases — use them to validate or extend |
| Question taxonomy ranking | Add `matches_existing_global_feedback: +4` — see [question-taxonomy.md](question-taxonomy.md). |

Lower than mined search match (`+5`) because GLOBAL feedback is *already there* — we
don't need to re-add it, just confirm it remains in scope and use it to inform new
candidates.

### 4d. Output structure

Add to `existing_review.json`:

```json
{
  "existing_feedback": {
    "global_count": 17,
    "user_count": 4,
    "user_included_in_signal": false,
    "stale_references": [
      {"id": "12", "feedback_phrase": "old metric by region", "reason": "search_tokens reference [Old Metric] which no longer exists"}
    ],
    "global_entries_summary": [
      {"id": "1", "type": "REFERENCE_QUESTION", "feedback_phrase": "...", "search_tokens": "...", "rating": "UPVOTE"},
      ...
    ],
    "user_entries_summary": [
      {"id": "20", "type": "REFERENCE_QUESTION", "creator": "alice@...", "feedback_phrase": "...", "in_scope": false}
    ]
  }
}
```

`global_entries_summary` is full content (it's the input signal). `user_entries_summary`
omits content unless the user opted in — keep them privacy-respecting by default.

---

## Confidence scoring

Each proposed delta carries a confidence score (0–100). Flag low-confidence deltas
explicitly so the user spends review time where it matters:

| Confidence | Conditions |
|---|---|
| 90–100 (HIGH) | Backed by ≥ 3 distinct mined sources and structural evidence (e.g. column type) aligns |
| 60–89 (MED) | 1–2 mined sources OR strong structural evidence alone |
| 30–59 (LOW) | Inferred from heuristic / template only — minimal mined evidence |
| 0–29 (FLAG) | Below threshold — emit as `FLAG_FOR_HUMAN`, not `ADD`/`REFINE`/`REWRITE` |

The Step 7 review files show confidence as a column. The user can sort by confidence
and accept high-confidence proposals in bulk.

---

## Output format

Save the critique to `{run_dir}/existing_review.json`:

```json
{
  "model_description": {
    "current": "...",
    "proposed": "...",
    "action": "EXPAND",
    "confidence": 75,
    "reasons": ["mentions <30% of measures", "AI-generated"]
  },
  "column_ai_context": {
    "Inventory Balance": {
      "current": "",
      "proposed": "Current quantity of product on hand at the end of each period. ...",
      "action": "ADD",
      "confidence": 85,
      "reasons": ["empty", "3 prose sources reference inventory levels"]
    }
  },
  "column_synonyms": {
    "Inventory Balance": {
      "current": [],
      "proposed_additions": ["inventory levels", "stock", "on hand"],
      "action": "ADD_PHRASES",
      "confidence": 80,
      "reasons": ["empty", "model.description mentions 'inventory levels'"]
    }
  },
  "existing_feedback": []
}
```

Step 7 reads this file plus the surface-specific candidates from Step 6 and produces
the per-surface markdown review files (`ai_context.md`, `synonyms.md`, etc.).

---

## What this review never does

- **Never deletes existing content** without explicit user accept
- **Never modifies physical table TML** (`columns[].description` on tables) — out of scope; handled by `/ts-object-model-builder`
- **Never proposes ai_context for hidden columns** (`is_hidden: true`) — Spotter doesn't index them
- **Never proposes synonyms for hidden columns** — same reason
- **Never combines multiple existing entries** into one — keeps merges explicit
