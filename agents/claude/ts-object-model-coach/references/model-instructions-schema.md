# `model_instructions` Schema — Declarative-Only Spec

`model_instructions` is the structured, machine-parsable channel for **global,
untriggered guidance** about a Model. It carries rules the LLM should apply on
every query — exclusions, defaults, formatting — plus meta-level facts about how
the schema is laid out.

It is the **Model-level counterpart to per-column `ai_context`**: same
declarative-only discipline, same structured form, same closed allowed-key list,
just one level up (about the Model rather than about a single column).

This file is the authoritative spec. Generators in `ts-object-model-coach`
(Step 6.5) and validators in Step 8b read these rules.

---

## Boundary — what does NOT belong here

`model_instructions` carries **untriggered global rules**. Anything that fires
on a specific NL phrase belongs elsewhere:

| Pattern | Goes in |
|---|---|
| "When the user says *last month*, interpret as last 30 days" | `nls_feedback` BUSINESS_TERM (Spotter's phrase-trigger channel) |
| "When the user says *sales*, prefer Total Sales over Net Sales" | `nls_feedback` BUSINESS_TERM |
| "Top 10 customers by sales: example NL → search_tokens" | `nls_feedback` REFERENCE_QUESTION |
| "Always exclude refund line items from sales totals" | `model_instructions.exclusion_rules` |
| "Default time period is last 90 days when none specified" | `model_instructions.time_defaults` |
| "Don't infer separate dim tables for denormalized columns" | `model_instructions.schema_assumptions` |

The boundary: **does the rule fire on a phrase, or always?** Phrase-triggered
goes to feedback; always-applied goes here.

(Note: feedback lives in a separate TML document, exported via
`tml/export type=FEEDBACK`. External agents that consume only the Model TML do
not see feedback by default. Bundling decisions for external-agent export are
deferred — see [open-items.md #4](open-items.md).)

---

## The hard rule: structured only, no prose

`model_instructions` contains **only enums, refs, and lists of refs/predicates**.
Free-form rule descriptions are rejected at deploy validation.

| Surface | What goes here | LLM treatment |
|---|---|---|
| `model_instructions` | Closed enums, column refs, structured rule shapes. | Authoritative — primary signal channel for global rules. |
| `model.description` | Prose. Business meaning, history, narrative. | Supplementary narrative — read alongside `model_instructions`. |

Each rule may include a short **`reason`** or **`note`** prose field (≤ 80 chars)
where the *why* is irreducible. Otherwise structured.

---

## Allowed-key list (closed)

Top-level keys must come from this set. Anything else is rejected at deploy.

```
exclusion_rules
aggregation_defaults
time_defaults
output_formatting
schema_assumptions
```

Five categories. All untriggered. Within each category, every rule has a known
shape with typed fields (refs, enums, predicates).

---

## Categories

### 1. `exclusion_rules` — always-applied filters

Filters that apply automatically whenever a measure is queried, regardless of NL
phrasing. Used when a measure has business semantics that excludes certain rows
(refunds, internal accounts, test data).

```yaml
exclusion_rules:
  - applies_to: <measure_ref>           # required — column ref to a measure
    exclude_when: <SQL predicate>       # required — SQL-like predicate on the same table
    reason: <≤ 80 chars prose>          # optional — short why
```

**Predicate form** — single-table SQL predicate using physical column names. The
LLM resolves any `<col_ref>` references via `column_id` before emitting SQL.

**Example:**

```yaml
exclusion_rules:
  - applies_to: Total Sales
    exclude_when: line_total < 0
    reason: refund line items
  - applies_to: Customer Count
    exclude_when: account_type = 'INTERNAL'
    reason: exclude internal test accounts
```

### 2. `aggregation_defaults` — default agg for ambiguous columns

When the LLM aggregates a column without an explicit aggregation in the user's
question, this rule sets the default.

```yaml
aggregation_defaults:
  - column: <col_ref>                   # required
    default_agg: <enum>                 # required — closed: sum/avg/min/max/count/count_distinct
```

**Example:**

```yaml
aggregation_defaults:
  - column: Customer Name
    default_agg: count_distinct
  - column: Order ID
    default_agg: count_distinct
```

### 3. `time_defaults` — global time interpretation

Defaults that apply when the user's question omits a time qualifier.

```yaml
time_defaults:
  default_period: <text>                # optional — e.g. "last 90 days"
  default_grain: <enum>                 # optional — closed: day/week/month/quarter/year
  fiscal_year_start: <date>             # optional — ISO 8601 date for fiscal calendar
```

**Example:**

```yaml
time_defaults:
  default_period: last 90 days
  default_grain: day
  fiscal_year_start: 2026-02-01
```

### 4. `output_formatting` — display rules

How to format output for specific units or column types. Keyed by the
`ai_context.unit` enum so it composes with per-column metadata.

```yaml
output_formatting:
  - apply_to_unit: <enum>               # required — closed: currency/count/ratio/percentage/duration
    format: <text>                      # required — short directive, ≤ 80 chars
```

**Example:**

```yaml
output_formatting:
  - apply_to_unit: currency
    format: USD, no decimals, thousands separator
  - apply_to_unit: percentage
    format: one decimal place, % symbol
```

### 5. `schema_assumptions` — meta-level facts about the schema

Reinforces structural patterns the LLM should follow. Each assumption has a
known type and is keyed by an enum.

```yaml
schema_assumptions:
  - assumption: <enum>                  # required — closed: see below
    columns: [<col_ref>, ...]           # for column-targeted assumptions
    dim: <col_ref>                      # for date-dim assumptions
    tables: [<table_ref>, ...]          # for table-targeted assumptions
    facts: [<table_ref>, <table_ref>]   # for chasm-attribution assumptions
    shared_dims: [<col_ref>, ...]       # for chasm-attribution assumptions
    note: <≤ 80 chars prose>            # optional — short reinforcement
```

**Closed enum for `assumption`:**

| Value | Meaning | Required fields |
|---|---|---|
| `denormalized_attributes` | These columns live on parent tables — no separate dim tables exist | `columns`, `note` |
| `shared_conformed_date_dim` | All time-anchored measures should join through this dim | `dim`, `note` |
| `surrogate_keys_only` | These tables expose surrogate primary keys; don't show them to users | `tables`, `note` |
| `chasm_attribution` | Two fact tables share some dims but not all; queries combining them attribute via shared dims and values repeat across non-shared dims (this is intentional, not a fanout bug — it's how ThoughtSpot's chasm-trap handling works) | `facts` (≥ 2), `shared_dims` (≥ 1), `note` |

**Example (where phantom-table and chasm-attribution reinforcement live):**

```yaml
schema_assumptions:
  - assumption: denormalized_attributes
    columns: [Product Category, Customer Region, Employee Manager]
    note: do not infer separate dim tables — follow column_id
  - assumption: shared_conformed_date_dim
    dim: DM_DATE_DIM.Date
    note: cross-fact joins should anchor here, not on raw fact dates
  - assumption: surrogate_keys_only
    tables: [DM_ORDER_DETAIL, DM_INVENTORY]
    note: primary keys are surrogate; do not expose in user-facing output
  - assumption: chasm_attribution
    facts: [DM_INVENTORY, DM_ORDER_DETAIL]
    shared_dims: [Product, DM_DATE_DIM.Date]
    note: Inventory has no Customer/Region link; values repeat per customer for fulfillment queries
```

---

## How `chasm_attribution` enables (and clarifies) cross-fact queries

A **chasm trap** exists when two fact tables share *some* dimensions but not all
— e.g., `DM_INVENTORY` (per Product, per Date) and `DM_ORDER_DETAIL` (per
Product, per Date, per Customer, per Region). They share Product and Date, but
Inventory has no Customer or Region link.

ThoughtSpot's engine handles chasm traps natively as a **first-class capability**
(see [TS docs on attribution and chasm traps](https://community.thoughtspot.com/s/article/What-is-Attribution-and-Chasm-Traps)).
A question like *"customer sales + inventory by SKU=123, region=West, this
month"* aggregates each fact at its own grain, then attributes inventory across
customers via the shared (Product, Date) keys. The repeating inventory value
per customer is intentional — useful for fulfillment-checking, valid for
attribution analyses (e.g., marketing spend → sales).

External SQL agents don't know this. Without a structured signal, two failure
modes appear:

| Failure | What happens without `chasm_attribution` |
|---|---|
| Direct fact-to-fact join | Agent invents a join condition between facts that have no shared key — fanout, garbage results |
| Refusal | Agent recognizes there's no join path and refuses the question, even though TS would handle it correctly |

`chasm_attribution` is the structured signal:

- **Facts** that have no direct join — listed
- **Shared dims** that bridge them — listed
- **Note** explaining the attribution semantics — short prose

The agent reads this and knows: aggregate each fact at its own grain (filtered
by the shared dims and the user's filters), then `LEFT JOIN` via shared dims at
output time. Non-shared dims will see repeated values from the other fact —
that's the attribution working correctly.

### Worked example — fulfillment query

For Dunder Mifflin with `chasm_attribution: [DM_INVENTORY, DM_ORDER_DETAIL]`,
question *"customer sales + inventory by SKU=123, region=West, this month":*

```sql
WITH cust_sales AS (
  SELECT C.CUSTOMER_NAME, P.PRODUCT_SKU, OD.PRODUCT_ID,
         DATE_TRUNC('MONTH', D.DATE) AS MONTH,
         SUM(OD.AMOUNT) AS TOTAL_SALES
  FROM DUNDERMIFFLIN.PUBLIC_SV.DM_ORDER_DETAIL OD
  JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_CUSTOMER C ON OD.CUSTOMER_ID = C.CUSTOMER_ID
  JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_PRODUCT  P ON OD.PRODUCT_ID  = P.PRODUCT_ID
  JOIN DUNDERMIFFLIN.PUBLIC_SV.DM_DATE_DIM D ON OD.ORDER_DATE  = D.DATE
  WHERE P.PRODUCT_SKU = '123' AND C.REGION = 'West'
    AND D.DATE >= DATE_TRUNC('MONTH', CURRENT_DATE)
  GROUP BY C.CUSTOMER_NAME, P.PRODUCT_SKU, OD.PRODUCT_ID, MONTH
),
inv_balance AS (
  SELECT INV.PRODUCT_ID,
         DATE_TRUNC('MONTH', INV.BALANCE_DATE) AS MONTH,
         INV.FILLED_INVENTORY AS BALANCE,
         ROW_NUMBER() OVER (PARTITION BY INV.PRODUCT_ID,
                                          DATE_TRUNC('MONTH', INV.BALANCE_DATE)
                            ORDER BY INV.BALANCE_DATE DESC) AS rn
  FROM DUNDERMIFFLIN.PUBLIC_SV.DM_INVENTORY INV
  WHERE INV.BALANCE_DATE >= DATE_TRUNC('MONTH', CURRENT_DATE)
)
SELECT cs.CUSTOMER_NAME, cs.PRODUCT_SKU, cs.TOTAL_SALES,
       ib.BALANCE AS INVENTORY_BALANCE   -- repeats per customer (intentional)
FROM cust_sales cs
LEFT JOIN inv_balance ib
  ON ib.PRODUCT_ID = cs.PRODUCT_ID
  AND ib.MONTH = cs.MONTH
  AND ib.rn = 1
ORDER BY cs.TOTAL_SALES DESC
```

The repeating `INVENTORY_BALANCE` per customer is the chasm-attribution
behavior — semantically valid for the fulfillment-check use case the user is
performing.

### Marketing attribution — the same shape covers it

The classic chasm-attribution use case is attributing marketing spend (no
direct customer link) to actual customer sales via shared Date + Region:

```yaml
- assumption: chasm_attribution
  facts: [DM_MARKETING_SPEND, DM_ORDER_DETAIL]
  shared_dims: [DM_DATE_DIM.Date, Region]
  note: marketing spend attributed to sales via shared date+region
```

Same structure handles fulfillment, marketing attribution, and any other
chasm-bridging analysis without needing separate concepts.

### When `chasm_attribution` is the wrong rule

The rule says *"these facts can be queried together; here's how the
attribution works."* It is **not** a license to combine facts that share
*nothing* — that's still a join error. Detection logic should require **at
least one shared dimension**; pairs with zero shared dims are not chasm
attributions and should not be declared.

---

## How `schema_assumptions` reinforces phantom-table prevention

The phantom-table failure (Test 4: 8 FAILs from invented `DM_CATEGORY`, plus
DM_EMPLOYEE / DM_CUSTOMER patterns) is primarily prevented at the **per-column**
level via `column_id` resolution + `ai_context.role` + `column.description`.

`schema_assumptions.denormalized_attributes` is the **meta-level reinforcement**
— it states the assumption once at Model scope rather than column-by-column.
Useful because:

- It reaches external agents (lives in Model TML; always exported)
- It frames the assumption positively (*"these columns are denormalized; follow column_id"*) rather than negatively per column (*"no separate X table"*)
- An LLM that orientates to top-of-context Model-level rules sees the pattern before drilling into per-column TML

**Layering for a phantom-table failure (Test 4 example):**

| Layer | Mechanism |
|---|---|
| 1 (truth) | `column_id: DM_PRODUCT::PRODUCT_CATEGORY` + `tables[].fqn` |
| 2 (semantic role) | `ai_context.role: label` |
| 3 (instruction) | System-prompt clauses 2 & 3 (resolve via `column_id`, never invent tables) |
| 4 (per-column prose backstop) | `column.description: "...no separate category table"` |
| 5 (Model-level meta backstop) | `model_instructions.schema_assumptions.denormalized_attributes` |

If layer 1 is correct, layers 2-5 don't need to do anything. Layers 2-5 exist to
catch LLM rounding errors. `schema_assumptions` is layer 5 — meta-level
reinforcement, not the primary prevention.

---

## Worked example — full `model_instructions` for Dunder Mifflin

```yaml
model_instructions:

  exclusion_rules:
    - applies_to: Total Sales
      exclude_when: line_total < 0
      reason: refund line items

  aggregation_defaults:
    - column: Customer Name
      default_agg: count_distinct
    - column: Order ID
      default_agg: count_distinct

  time_defaults:
    default_period: last 90 days
    default_grain: day
    fiscal_year_start: 2026-02-01

  output_formatting:
    - apply_to_unit: currency
      format: USD, no decimals, thousands separator
    - apply_to_unit: percentage
      format: one decimal place, % symbol

  schema_assumptions:
    - assumption: denormalized_attributes
      columns: [Product Category, Customer Region, Employee Manager]
      note: do not infer separate dim tables — follow column_id
    - assumption: shared_conformed_date_dim
      dim: DM_DATE_DIM.Date
      note: cross-fact joins should anchor here, not on raw fact dates
    - assumption: chasm_attribution
      facts: [DM_INVENTORY, DM_ORDER_DETAIL]
      shared_dims: [Product, DM_DATE_DIM.Date]
      note: Inventory has no Customer/Region link; values repeat per customer for fulfillment queries
```

---

## Safeguards (binding rules)

### 1. Structured-only

Allowed-key list is closed at every level. Top-level keys, `assumption:` enums,
`default_agg:` enums, `default_grain:` enums, `apply_to_unit:` enums — all
closed. Free-text rule descriptions are rejected; only `reason:` / `note:`
fields (≤ 80 chars) accept short prose.

### 2. Generator system-prompt rule

Skill generators (Step 6.5) and any downstream LLM prompt that consumes
`model_instructions` must treat the structured rules as **authoritative** for
their respective scope:

- `exclusion_rules` apply automatically to the `applies_to` measure
- `aggregation_defaults` apply when the LLM aggregates the named column without explicit user direction
- `time_defaults` apply when the user's question omits a time qualifier
- `output_formatting` applies when the result column matches the `apply_to_unit`
- `schema_assumptions` are read at orientation time, before per-column resolution

### 3. Deploy-time validation

Before TML import, validate:

- Every `applies_to:`, `column:`, `dim:`, and refs in `columns:`/`tables:`/`facts:`/`shared_dims:` resolve to real Model columns/tables
- Every `default_agg:`, `default_grain:`, `apply_to_unit:`, `assumption:` value is from its closed enum
- `exclude_when:` predicates reference physical columns that exist on the same table as `applies_to`
- `chasm_attribution` rules require **≥ 2 distinct fact tables in `facts:` and ≥ 1 shared dim in `shared_dims:`** — pairs with zero shared dims are not chasm attributions
- `note:` and `reason:` fields are ≤ 80 chars
- Top-level keys are from the allowed-key list

Validation failures block import; the user is shown the offending rule and the
specific failure.

### 4. Absent means absent — never infer

If `model_instructions` is missing entirely, the LLM falls back to plain
schema-only reasoning. The system prompt **must not** instruct the LLM to "use
sensible defaults" for any of these categories. Either a rule is declared (LLM
applies it) or absent (LLM does not invent one).

### 5. Prose has a home — `model.description`

`model_instructions` is structured-only. Narrative context for the Model —
business background, history, ownership, gotchas that don't fit a structured
rule — goes in `model.description` (the Model-level prose surface, parallel to
`column.description` for individual columns).

---

## Where `model_instructions` lives in TML

**TBD — see [open-items.md #4](open-items.md).** The TML location for
Model-level instructions has not yet been verified against a live tenant.
Candidate locations under investigation:

- `model.properties.instructions` (parallel to per-column `properties.ai_context`)
- A top-level `model_instructions` key under `model:`
- A separate companion document (less preferred — duplicates the
  feedback-vs-Model split that we're trying to avoid)

Until verified, Step 6.5 emits the structured form to `instructions.md` for
**manual paste** by the user. Once the TML location is verified, Step 9 will
write directly via `tml/import`.

---

## Motivation — why this schema exists

The `agent-expressibility-eval` Test 4 runs surfaced four failure clusters that
required Model-level (not per-column) reinforcement:

| Failure cluster | What `model_instructions` adds |
|---|---|
| Phantom dim tables (`DM_CATEGORY`, `DM_EMPLOYEE`) | `schema_assumptions.denormalized_attributes` — meta-level reinforcement of per-column `column_id` |
| Cross-fact chasm fanout (wrong-direction join on raw dates) | `schema_assumptions.shared_conformed_date_dim` — explicit anchor for join behavior |
| Cross-fact attribution (intentional repeat per non-shared dim) | `schema_assumptions.chasm_attribution` — declares that two facts can be queried together via shared dims, with intentional value repetition |
| Default time interpretation drift | `time_defaults` — global default period and grain |
| Inconsistent currency / percentage formatting | `output_formatting` — keyed by `ai_context.unit` |

Phrase-triggered patterns (term aliases, default measures by phrase) are
deferred to feedback when bundling for external agents is decided. This schema
covers what fits cleanly into the **untriggered, always-applied** category — and
explicitly carries the meta-level reinforcement for the phantom-table failure
cluster.

The full failure analysis lives in
`/Users/damianwaldron/Dev/agent-expressibility-eval/runs/dunder-mifflin-sales-inventory__1777408743/`.
