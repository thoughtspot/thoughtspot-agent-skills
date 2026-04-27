# Token Mapping Rules — `ts-coach-model`

How to translate a verified natural-language question into the four `nls_feedback`
fields: `search_tokens`, `formula_info[]`, `chart_type`/`display_mode`/`axis_config`,
and `feedback_phrase`/`parent_question`. Used in
[SKILL.md Step 6](../SKILL.md). Also covers the SQL → NL reverse-translation used
when mining Snowflake query history in Step 3b.

The structural fields and their allowed values are defined in
[thoughtspot-feedback-tml.md](~/.claude/shared/schemas/thoughtspot-feedback-tml.md).

---

## 1. `search_tokens` — column reference syntax

`search_tokens` uses **bare display-name brackets**, the same convention as Spotter's
search bar:

```
"[Region] [Revenue]"
"[Customer Name] [Revenue] top 10"
"[Order Date] [Revenue] monthly"
```

Rules:
- One column per `[...]` token. Multiple columns are space-separated.
- Use the **Model column display name** (the `columns[].name` value from the Model TML),
  not the physical warehouse column name.
- For formulas referenced in tokens, use the **formula's display name** in brackets:
  `[Margin pct]` (not `[formula_Margin pct]` — that ID convention is for formula-internal
  references, not for `search_tokens`).
- Search keywords (`top`, `bottom`, `monthly`, `last 30 days`, `this quarter`, etc.) go
  outside brackets, lowercase, in their natural search-bar position.

The example structure is verified in
[thoughtspot-feedback-tml.md](~/.claude/shared/schemas/thoughtspot-feedback-tml.md):
`search_tokens: "[Customer Name] [Revenue] top 10"`.

### Keyword vocabulary (search-bar tokens that are not column references)

> **Authoritative source for verified-working keyword positions and syntax:**
> [feedback-tml-verified-patterns.md](feedback-tml-verified-patterns.md). The
> initial v1 finding (every non-bracket keyword REJECTED) was over-broad —
> the rejections were caused by **wrong syntax positions / missing quotes**,
> not by keyword banning. See [open-items.md #16](open-items.md) for the
> recategorisation.

| Intent | Verified-working form | Common mistake (v1 emitted, REJECTED) |
|---|---|---|
| Top / Bottom N | `top N [Col]` *(keyword BEFORE the column refs)* | `[Col] [Col] top N` *(after — REJECTED)* |
| Time grain (date bucket) | `[Date Col].monthly` *(dot-suffix, attached to col)* | `[Date Col] monthly` *(standalone — REJECTED)* |
| Multi-word date bucket | `[Date Col].'month of year'` *(quoted)* | `month of year [Date Col]` *(REJECTED)* |
| Relative time | `[Date Col] = 'this year' vs [Date Col] = 'last year'` *(quoted period as filter value)* | `[Col] this year` *(bare keyword — REJECTED)* |
| Year filter | `[Date Col] = '2025'` *(quoted)* | `[Date Col] = 2025` *(unquoted — REJECTED)* |
| Filter equality | `[Col] = 'value'` *(single-quoted literal)* | bare equals — REJECTED |
| Multiple filters | `[Col] = 'a' [Col] = 'b'` *(implicit OR-set)* | — |
| Aggregation prefix | `sum [Col]`, `sum [Col] [Group]` *(verified)* | — |
| Sort | `[Col] sort by [Col]` *(verified)* | — |
| Compare clauses | `<filter clause> vs <filter clause>` *(verified)* | — |
| Bracketed column references | `[Customer Name] [Amount]` *(any number 1+)* | — |

**Practical rule for v1 generators:** match the verified-working forms above
exactly. When an intent isn't in the table, treat it as untested — drop the
question or route via `DEFER` rather than emit a guess.

---

## 2. `formula_info[]` — when to generate, expression syntax

> **Verified 2026-04-27 ([open-items.md #17](open-items.md)):** `formula_info[]`
> on `REFERENCE_QUESTION` is REJECTED by the same parser bug that affects
> `BUSINESS_TERM` (per [#12](open-items.md)). The parser tries to evaluate the
> formula expression as a search query and fails. Until #17 lands a verified
> syntax, generators must NOT emit `formula_info` on either entry type — instead
> emit a `MOVE_TO_NEW_FORMULA` proposal that routes the user to define the
> formula on the Model first (via `/ts-object-answer-promote`), then reference
> the formula's display name in `search_tokens`.
>
> The mapping below documents the eventual target syntax for when #17 is
> verified — but the current import path is to drop these questions and
> use the Model-formula workaround.

Generate `formula_info[]` when the question's mathematical intent cannot be expressed by
existing Model columns alone. Mapping by tier (from
[question-taxonomy.md](question-taxonomy.md)):

| Tier | Pattern IDs that need formulas |
|---|---|
| T1 | none |
| T2 | `t2.cumulative` |
| T3 | `t3.avg_per`, `t3.ratio`, `t3.share_of_total` |
| T4 | `t4.conditional_agg`, `t4.window_rank`, `t4.cross_join_metric` (`t4.yoy_compare` and `t4.mom_compare` use search-bar `this period`/`last period` keywords — no formula) |

### Expression syntax

**Answer-level formulas use bare display-name references**, not `TABLE::column`. This is
the same convention as `answer.formulas[].expr` and is verified in
[thoughtspot-answer-tml.md](~/.claude/shared/schemas/thoughtspot-answer-tml.md):

```
expr: "[Revenue] - [Cost]"                                  # ✓ bare names
expr: "( [Revenue] - [Prior Year Revenue] ) / [Revenue]"    # ✓ bare names
expr: "[FACT_ORDERS::AMOUNT]"                               # ✗ TABLE:: form is for Model formulas
```

This distinction matters: the `formula_info[]` block in `nls_feedback` follows the
**Answer formula** convention because Spotter resolves these at search time against the
Answer it produces, not against the Model schema directly.

### Formula function reference

Authoritative function syntax is in
[thoughtspot-formula-patterns.md](~/.claude/shared/schemas/thoughtspot-formula-patterns.md).
The functions used by the taxonomy patterns:

| Pattern | Formula template |
|---|---|
| `t2.cumulative` | `cumulative_sum ( [M] , [T] )` |
| `t3.avg_per` | `[M_total] / unique count ( [D] )` |
| `t3.ratio` (margin) | `( [M1] - [M2] ) / [M1]` |
| `t3.share_of_total` | `[M] / group_aggregate ( sum , [M] , { } )` |
| `t4.conditional_agg` | `sum_if ( [M] , [D_status] = 'new' )` |
| `t4.window_rank` | `rank ( [M] , { [D2] } )` |
| `t4.cross_join_metric` | `[M1] / [M2]` (model joins resolve the cross-fact) |

> **YoY/MoM growth-% formulas removed.** The previous templates relied on
> `group_aggregate ( sum , [M] , { [T] - 1 } )`. The `[T] - 1` operator on a date column
> inside a grouping argument is not valid TS formula syntax —
> `group_aggregate`'s third argument is a `query_filters()` expression, not a date offset.
> Use the keyword-based `t4.yoy_compare` and `t4.mom_compare` patterns from
> [question-taxonomy.md](question-taxonomy.md) instead, which produce two side-by-side
> KPIs (this period and last period) with no formula required. A verified TS
> period-over-period growth-% formula is tracked as an open item in
> [open-items.md](open-items.md).

### Formula `name` field

Formula display names should describe what the user asked, not the formula's internals.
Naming convention:

| Pattern | Name template | Example |
|---|---|---|
| `t3.avg_per` | `Avg {M} per {D}` | "Avg Revenue per Customer" |
| `t3.ratio` (margin) | `{M1} margin %` (or domain-specific term) | "Margin pct" |
| `t3.share_of_total` | `{D} share of {M}` | "Region share of Revenue" |
| `t4.yoy` | `{M} YoY %` | "Revenue YoY pct" |
| `t4.mom` | `{M} MoM %` | "Revenue MoM pct" |
| `t4.conditional_agg` | `{M} from {D=condition}` | "Revenue from new customers" |
| `t4.window_rank` | `{D} rank by {M}` | "Customer rank by Revenue" |
| `t4.cross_join_metric` | `{M1} per {M2}` | "Conversion rate" |

Avoid `%` and `/` in formula names — both are valid in the TML but make the formula
harder to reference in `search_tokens`. Prefer `pct` and `per`.

### YAML encoding

Per [thoughtspot-formula-patterns.md](~/.claude/shared/schemas/thoughtspot-formula-patterns.md):
expressions containing `{ }` (window/group_aggregate scopes) **must use `>-` folded block
scalar**, not inline strings:

```yaml
- id: 5
  type: REFERENCE_QUESTION
  feedback_phrase: "Revenue YoY growth by region"
  search_tokens: "[Region] [Revenue YoY pct]"
  formula_info:
  - name: "Revenue YoY pct"
    expression: >-
      ( [Revenue] - group_aggregate ( sum , [Revenue] , { [Order Date] - 1 } ) )
      / group_aggregate ( sum , [Revenue] , { [Order Date] - 1 } )
```

Inline `expression: "( [Revenue] - group_aggregate(... { [Order Date] - 1 } ) ...)"` will
break PyYAML serialization — the `{` is interpreted as a flow-style mapping marker.

---

## 3. `chart_type`, `display_mode`, `axis_config` — inference rules

The valid values for `chart_type` and `display_mode` are defined in
[thoughtspot-feedback-tml.md](~/.claude/shared/schemas/thoughtspot-feedback-tml.md).

### Decision table

| Question shape | `chart_type` | `display_mode` | `axis_config` |
|---|---|---|---|
| Single measure aggregate (`t1.total`, `t1.distinct_count`) | `KPI` | `UNDEFINED` | omit |
| `M` by `D` (`t1.by_dim`) | `COLUMN` | `CHART_MODE` | `[{x: [D]}, {y: [M]}]` |
| Top-N or bottom-N (`t1.top_n`, `t1.bottom_n`) | `TABLE` | `TABLE_MODE` | omit |
| Time series (`t2.by_time`, `t2.cumulative`) | `LINE` | `CHART_MODE` | `[{x: [T]}, {y: [M]}]` |
| Time comparison (`t2.this_vs_last`) | `KPI` | `UNDEFINED` | omit |
| Trend by dim (`t2.trend_by_dim`) | `LINE_STACKED_COLUMN` or `LINE` | `CHART_MODE` | `[{x: [T]}, {y: [M]}, {color: [D]}]` |
| Filtered aggregate (`t3.dim_filter`, `t3.year_filter`, `t3.recent_period`) | `KPI` | `UNDEFINED` | omit |
| Average per (`t3.avg_per`) | `COLUMN` | `CHART_MODE` | `[{x: [D]}, {y: [formula_name]}]` |
| Ratio / margin (`t3.ratio`) | `KPI` | `UNDEFINED` | omit |
| Share of total (`t3.share_of_total`) | `PIE` or `COLUMN` | `CHART_MODE` | `[{x: [D]}, {y: [formula_name]}]` |
| YoY/MoM growth (`t4.yoy`, `t4.mom`) | `COLUMN` | `CHART_MODE` | `[{x: [D]}, {y: [formula_name]}]` |
| Conditional aggregation (`t4.conditional_agg`) | `KPI` | `UNDEFINED` | omit |
| Window rank (`t4.window_rank`) | `TABLE` | `TABLE_MODE` | omit |
| Cross-join metric (`t4.cross_join_metric`) | `KPI` | `UNDEFINED` | omit |

### `axis_config` shape

Matches the structure shown in the feedback TML schema:

```yaml
axis_config:
- "y":
  - "Revenue"
- "x":
  - "Order Date"
```

Use display names (column or formula display name) — not IDs.

---

## 4. Common per-entry fields

Every `REFERENCE_QUESTION` entry sets:

```yaml
- id: "{auto-incrementing}"
  type: REFERENCE_QUESTION
  access: GLOBAL
  feedback_phrase: "{the question text — same as parent_question for our purposes}"
  parent_question: "{the question text}"
  search_tokens: "{generated per Section 1}"
  rating: UPVOTE
  display_mode: "{per Section 3}"
  chart_type: "{per Section 3}"
  # formula_info: only if needed (per Section 2)
  # axis_config: only if not omitted (per Section 3)
```

For `BUSINESS_TERM` entries (Method B — verified working shape from
[open-items.md #12](open-items.md), tested 2026-04-26 against champ-staging):

```yaml
- id: "{auto-incrementing}"
  type: BUSINESS_TERM
  access: GLOBAL
  feedback_phrase: "{the phrase — e.g. 'stock'}"
  parent_question: "{same as feedback_phrase, or a representative full question}"
  search_tokens: "[{Existing Column or Formula Name}]"
  rating: UPVOTE
  display_mode: UNDEFINED      # REQUIRED
  chart_type: KPI               # REQUIRED — KPI is universally safe; see open-items.md #11 for full whitelist
```

**Critical constraint: BUSINESS_TERMs reference EXISTING Model artifacts only.** They
cannot create new formulas inline. Every BT must point at:
- A column that exists on the Model (`[Customer Name]`, `[Amount]`, etc.), OR
- A Model-level formula that already exists in `model.formulas[]` (`[Inventory Balance]`,
  `[# Employees]`, etc.)

**Do NOT include `formula_info` on a BUSINESS_TERM.** The schema documents this field
but the API rejects every formula-expression syntax variant tested (verified
[open-items.md #12](open-items.md)). The error is consistent: "Search did not find
<expression> in your data or metadata" — the parser is looking up the expression as
a search bar query, not interpreting it as a formula.

**When a phrase needs a calculation that doesn't exist on the Model**, the workflow
is two-step:

1. Add the formula as a Model formula first — via `/ts-object-answer-promote` (most
   common path) or by editing the Model TML directly
2. THEN create the BUSINESS_TERM with `search_tokens` pointing at the new formula

The skill emits a `MOVE_TO_NEW_FORMULA` action in `business_terms.md` for these cases
rather than attempting auto-import.

### Method A vs Method B decision

The two mechanisms overlap when the target is a column. The decision (presented to
the user via [synonym-strategy-explainer.md](synonym-strategy-explainer.md)):

| Phrase target | Recommended Method |
|---|---|
| Phrase → existing Model **column** | Method A (column synonyms) — schema-level, lighter |
| Phrase → existing Model **formula** | Method B (BUSINESS_TERM) — column synonyms can't reach formulas |
| Phrase → calculation that doesn't yet exist on the Model | Out of scope — emit `MOVE_TO_NEW_FORMULA`, user runs `/ts-object-answer-promote` first |
| Whole-question conversational phrasing | Method C (REFERENCE_QUESTION) |

---

## 5. Paraphrase variant generation (Step 6.3)

For each kept Reference Question, generate 2–3 conversational paraphrases. All variants
share the same `search_tokens` and `formula_info` — only `feedback_phrase` differs.
Spotter's coaching index does similarity matching against `feedback_phrase`, so multiple
phrasings of the same intent give it more anchor points without changing the answer it
returns.

### Why paraphrases are needed for Spotter (vs Cortex Analyst)

Snowflake's published guidance says *"avoid synonyms unless industry-specific"* —
correct for Cortex Analyst (frontier-LLM-backed). Spotter's coaching index is more
keyword/similarity-based, so it benefits from more anchor phrasings. The two product
positions diverge here; the skill follows Spotter's empirical behaviour.

### Variant templates per question pattern

| Pattern | Canonical | Example variants |
|---|---|---|
| `t1.total` | `What is total {M}?` | `Show me total {M}.` / `How much {M} did we have?` / `Total {M}.` |
| `t1.by_dim` | `{M} by {D}` | `{M} broken down by {D}` / `Show {M} for each {D}` / `{D}-level {M}` |
| `t1.top_n` | `Top 10 {entity}s by {M}` | `Which are our biggest {entity}s by {M}?` / `Top {entity}s ranked by {M}` |
| `t1.distinct_count` | `How many distinct {D}?` | `How many unique {D}?` / `Distinct {D} count` |
| `t2.by_time` | `{M} by month` | `Monthly {M}` / `How is {M} trending each month?` / `{M} per month` |
| `t2.recent_period` | `{M} in the last 30 days` | `{M} for the past month` / `Recent {M}` / `{M} over the last 30 days` |
| `t2.this_vs_last` | `{M} this Q vs last Q` | `How does {M} compare to last quarter?` / `{M} growth quarter on quarter` |
| `t2.cumulative` | `Cumulative {M} by month` | `Running total of {M} by month` / `{M} year-to-date` |
| `t3.dim_filter` | `{M} for {D} = {value}` | `{M} where {D} is {value}` / `{value}'s {M}` |
| `t3.avg_per` | `Average {M} per {D}` | `Mean {M} for each {D}` / `What is {M} per {D}` |
| `t3.ratio` (margin) | `Margin %` | `Profit margin` / `What is our margin?` |
| `t3.share_of_total` | `{D} share of total {M}` | `{D} contribution to {M}` / `What proportion of {M} comes from each {D}` |
| `t4.yoy` | `{M} YoY growth` | `Year over year change in {M}` / `How is {M} growing year on year` |
| `t4.mom` | `{M} MoM change` | `Month over month change in {M}` / `Monthly trend in {M}` |
| `t4.conditional_agg` | `{M} from {filter}` | `{M} for only {filter}` / `{filter}-only {M}` |
| `t4.window_rank` | `{D} rank by {M}` | `Where does each {D} rank in {M}?` / `{D} ranked by {M}` |
| `t4.cross_join_metric` | `Conversion rate` | `Hit rate` / `{M1} per {M2}` |

### Domain-aware paraphrases

Augment the templates with domain phrases from the **prose mining output** for this
specific Model. Example for Dunder Mifflin Sales & Inventory:

| Mined phrase | Implies variant |
|---|---|
| "inventory levels" (in model.description) | Variant of `t1.total Inventory Balance`: *"What are our current inventory levels?"* |
| "growth in sales amounts" (in model.description) | Variant of `t4.yoy Amount`: *"What is the growth in sales amounts?"* |
| "Total Amount by Order Id" (Answer name) | Already a canonical phrasing — emit as a variant of `t1.by_dim` for Amount + Order Id |

Always include the literal mined phrase as a variant when it reads like a question —
it's the analyst's own wording. Cap variants per intent at 4 to avoid sprawl.

---

## 6. Worked example explainer (Step 7)

Before showing the user `mappings.md`, display this in-conversation explainer using
THEIR data. Substitute `{COL}`, `{Mined Phrase}`, etc. with values from their Model.
Show only the surfaces that were selected in Step 5 — don't lecture about all five.

```
═══════════════════════════════════════════════════════════════════════════════
HOW EACH COACHING TYPE BEHAVES — using YOUR data

Below is a worked example for each coaching surface I'm about to generate. This is
to make sure you understand what each row in the review files will mean.

────────────────────────────────────────────────────────────────────────────────
1. COLUMN SYNONYMS — schema-level, used at parse time

   Your Model has the column [{COL}].
   I noticed analysts also call it: "{Mined Phrase}"

   I'll add:    synonyms: ["{Mined Phrase}"]   on column [{COL}]

   This single entry catches:
       "{Mined Phrase} by {Other Col}"
       "show {Mined Phrase} for {Filter}"
       "top customers by {Mined Phrase}"
       "{Mined Phrase} this year"
   …and any other shape Spotter can already parse.

────────────────────────────────────────────────────────────────────────────────
2. COLUMN AI CONTEXT — per-column free text, used by Spotter to disambiguate

   Your Model column [{COL}] currently has no business description.
   I'll add 2-3 sentences explaining what it represents and how it's measured.

   Example proposed AI Context for [{COL}]:
     "{2-3 sentence description, drawn from mined evidence}"

   Spotter uses this when a query is ambiguous or when explaining its answer.

────────────────────────────────────────────────────────────────────────────────
3. REFERENCE QUESTIONS — per-question, used for whole-question matches

   Some queries are conversational and can't decompose word-by-word into your
   columns:
       "{Mined Conversational Phrasing}"
   I'll add a Reference Question entry that maps the entire phrasing to a known
   answer:
       feedback_phrase: "{Mined Conversational Phrasing}"
       search_tokens:   "{Generated tokens}"
       chart_type:      {Chart}

   Use sparingly — for genuine paraphrases, not for queries already covered by
   synonyms.

────────────────────────────────────────────────────────────────────────────────
4. BUSINESS TERMS — coaching-layer phrase mappings

   Some phrases map to FORMULAS, not columns. Synonyms can't reference formulas,
   so we use BUSINESS_TERM coaching:
       feedback_phrase: "margin"
       search_tokens:   "[Margin pct]"        # this is a formula, not a column

   These also live separately from the Model schema, so they're easier to add/
   remove without re-importing the Model.

────────────────────────────────────────────────────────────────────────────────
HOW TO CHOOSE WHEN REVIEWING

When you see a proposed entry in the review files:

   • Phrase maps to a column?  →  Synonym (cleanest)
   • Phrase maps to a formula? →  Business Term (synonyms can't reach formulas)
   • Multi-word conversational phrasing of a question? →  Reference Question
                                                          (whole-sentence match)
   • Domain-wide rule? ("when last month, use last 30 days") → Data Model
                                                                Instructions

═══════════════════════════════════════════════════════════════════════════════
```

The explainer is gated on which surfaces were selected in Step 5. If only Reference
Questions were selected, show only sections 1 (briefly, as context) and 3 in detail.

---

## 5. SQL → NL reverse translation (Step 3b)

When mining Snowflake `QUERY_HISTORY`, classify each top SQL pattern and emit a
candidate question. Return `None` (skip the candidate) if the SQL doesn't map cleanly.

| SQL shape | NL candidate |
|---|---|
| `SELECT SUM(col) FROM t` | "What is total {col_display}?" |
| `SELECT d, SUM(m) FROM t GROUP BY d` | "{m_display} by {d_display}" |
| `SELECT d, SUM(m) FROM t GROUP BY d ORDER BY SUM(m) DESC LIMIT N` | "Top N {d_display} by {m_display}" |
| `SELECT DATE_TRUNC('month', t), SUM(m) FROM t GROUP BY 1 ORDER BY 1` | "{m_display} by month" |
| `SELECT SUM(m) FROM t WHERE t >= DATEADD('day', -30, CURRENT_DATE)` | "{m_display} in the last 30 days" |
| `SELECT SUM(m1)/SUM(m2) FROM t` | "{m1_display} per {m2_display}" + formula `[m1]/[m2]` |
| `SELECT SUM(CASE WHEN cond THEN m END) FROM t` | "{m_display} from {cond_display}" + `sum_if` formula |
| `SELECT d, SUM(m), SUM(m) / SUM(SUM(m)) OVER () FROM t GROUP BY d` | "{d_display} share of {m_display}" + share-of-total formula |
| `WITH cte AS (...)` / window functions / multi-CTE | Skip — too complex to reverse cleanly |
| `SELECT * FROM t LIMIT 10` | Skip — not a business question |

**Column-name resolution.** SQL column names are warehouse-physical (`AMOUNT`,
`CUSTOMER_ID`); display names are ThoughtSpot-style (`Revenue`, `Customer ID`). Resolve
via `table_tmls[].table.columns[].db_column_name` → `name` lookup. If a SQL column
doesn't resolve to any Model column, skip the SQL pattern.

**Formula translation for SQL-derived candidates** must check
[ts-snowflake-formula-translation.md](~/.claude/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
before declaring a SQL expression untranslatable. This is mandatory per project memory
(`feedback_formula_translation`) — many window/LOD functions have direct TS equivalents.

---

## 6. Worked end-to-end example

**Input candidate** (from Step 4):

```python
{
    "tier": "T3",
    "pattern": "t3.ratio",
    "question": "Margin %",
    "score": 8,
    "score_breakdown": ["mined_search_match:+5", "complex_formula_unique:+1", "T3_implicit:0"],
    "selected_default": True,
    # extras populated during build:
    "measures": ["Revenue", "Cost"],
    "dimensions": [],
}
```

**Output entry** (built in Step 6):

```yaml
- id: "12"
  type: REFERENCE_QUESTION
  access: GLOBAL
  feedback_phrase: "Margin %"
  parent_question: "Margin %"
  search_tokens: "[Margin pct]"
  rating: UPVOTE
  display_mode: UNDEFINED
  chart_type: KPI
  formula_info:
  - name: "Margin pct"
    expression: "( [Revenue] - [Cost] ) / [Revenue]"
```

User reviews in `mappings.md` (Step 7) and either accepts or edits the formula
expression. After acceptance, this entry is appended to `nls_feedback.feedback[]` and
imported in Step 8.
