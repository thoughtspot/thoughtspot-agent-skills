# `ai_context` Schema — Declarative-Only Spec

`ai_context` is the structured, machine-parsable signal channel on a Model column.
It exists to give downstream LLMs — Spotter, third-party agents writing SQL against
the underlying physical schema, anything that reads the TML — the load-bearing
constraints they need to write correct queries: additivity, time anchor, and (for
dimensions) the role of the column in NL questions.

This file is the authoritative spec. Generators in `ts-object-model-coach`
(Step 6.1) and validators in Step 8b read these rules.

For full worked examples grounded in real Test 4 failures, see
[ai-context-examples.md](ai-context-examples.md).

---

## How to read this TML — layers, audiences, priorities

ThoughtSpot Model TML is a layered artifact. Both `ai_context` and `description`
are read by LLMs — the difference is **structured-and-authoritative** vs
**prose-and-supplementary**, not AI-vs-human.

| Layer | Read by | Priority | Treat as |
|---|---|---|---|
| `tables[].fqn` + `tables[].columns[].db_column_name` | LLM | Highest for "where does X live?" | **SQL identifiers — the truth.** |
| `tables[].columns[].column_id` (`TABLE::COL`) | LLM | Resolution mechanism | Resolve to physical via `fqn`. |
| `model.columns[].name` (display names) | LLM + humans | — | **TS logical names — never SQL identifiers.** |
| `model.columns[].properties.ai_context` | LLM | **Authoritative** | Declarative constraints — trust as primary. |
| `column.description` | LLM + humans | Supplementary | Prose narrative — complements `ai_context`; if it contradicts `ai_context`, trust `ai_context`. |
| `formulas[].expression` | LLM | TS DSL | **Not SQL** — re-implement from scratch in target SQL. |

The Test 4 failures (65.3% vs 80.2%) came from confusing these layers — primarily
treating display names and TS DSL as SQL identifiers.

---

## The hard rule: structured only, no prose

`ai_context` contains **only enums, refs, and lists of refs**. Free-form text — even
one sentence — is rejected at deploy validation.

| Surface | What goes here | LLM treatment |
|---|---|---|
| `ai_context` | Closed enums, column refs, physical paths, lists of those. | Authoritative — primary signal channel. |
| `column.description` | Prose. Business meaning, gotchas, history, edge cases. Sentences allowed. | Supplementary narrative — read alongside `ai_context`, trusted as context but not constraints. |

Why this split: the test data showed that prose in the *primary* AI signal channel
tempts the model to over-read and invent constraints, and to copy TS DSL formula
text verbatim into emitted SQL. Structured values are unambiguous and
machine-checkable. Prose still has a job — narrating *why* — and that job belongs
in `column.description` where it serves both LLMs (as supplementary context) and
humans (as the readable surface).

---

## Allowed-key list (closed)

`ai_context` keys must come from this set. Anything else is rejected at deploy.

```
additivity
non_additive_dimension
time_basis
source
grain_keys
unit
null_semantics
role
```

All values are enums, `<col_ref>` strings, `<SCHEMA.TABLE.COLUMN>` paths, or lists
of those. Never free text.

---

## Mandatory tier — load-bearing for measures

These four address the categories where Test 4 lost the most points vs. Test 3.

| Axis | Form | Test failure it prevents |
|---|---|---|
| `additivity` | Closed enum: `additive` / `semi_additive` / `non_additive`. For `semi_additive`, also `non_additive_dimension: <col_ref>`. | Semi-Additive (50% TML vs 80% SV) — wrong SUM. |
| `time_basis` | Single `<col_ref>` to a date dim that **exists in the Model**. Use the shared conformed date dim if one exists. | Period-over-Period (50% TML vs 75% SV) and Cross-Entity chasm — joins on the wrong date. |
| `grain_keys` | List of `<col_ref>` — the column refs that uniquely identify one fact row. Structured replacement for prose grain sentences. | Cross-Entity (60% TML vs 90% SV) — fanout from unknown grain. |
| `source` (conditional override) | Physical path `<SCHEMA.TABLE.COLUMN>`. **Omit when `column_id` resolves cleanly via the table's `fqn`.** Required when the column_id doesn't match the physical path (renamed/aliased columns, view-backed columns). | Aggregation (33% TML vs 67% SV), Ranking (0% TML vs 50% SV) — invented columns. |

`time_basis` may be legitimately absent for time-agnostic measures (e.g. a global
`count_distinct(Region)`). Absence is not inferred — see Safeguard 4.

---

## Optional tier — measures

| Axis | Form | When it earns its keep |
|---|---|---|
| `unit` | Closed enum: `currency` / `count` / `ratio` / `percentage` / `duration`. | Output formatting and ratio-of-ratios questions. |
| `null_semantics` | Closed enum: `zero` / `unknown` / `no_snapshot`. | Drives correct `COALESCE`. Matters for snapshots and event facts. |

---

## Dimensions — what applies and what doesn't

Three of the eight axes can apply to dimension columns. The other five are
measure-only.

| Axis | Applies to dim? | When |
|---|---|---|
| `additivity`, `non_additive_dimension`, `time_basis`, `grain_keys`, `unit` | **No** | Measure-only concepts. |
| `source` | Conditional | Same rule as measures: omit when `column_id` resolves; required when it doesn't. |
| `null_semantics` | Optional | Useful when NULL has business meaning — e.g., NULL `Region` means "not yet assigned" vs. "no region exists." |
| `role` | Recommended | The primary dimensional axis. See below. |

### `role` — disambiguates id / code / label / key

Closed enum:

| Value | Meaning | When the LLM should pick it |
|---|---|---|
| `label` | Human-readable display name | When the user asks for the *thing* by name ("by category", "show customers") |
| `id` | Internal identifier / surrogate key | When asked for counts, joins, or explicit IDs |
| `code` | Short business code | When asked for codes (`SKU`, `Region Code`) |
| `key` | Foreign-key reference for joining | Almost never as output — used only in joins |

Default behavior when `role` is absent: the LLM picks based on column-name patterns
(current behavior). When present, it's authoritative.

### Dimensional tier rules

| Dimension type | What goes in `ai_context` |
|---|---|
| Has an id/code/label sibling pair (e.g., `Product Category` + `Product Category ID`) | `role:` on each |
| Stand-alone label with NULL meaning ("not assigned") | `role: label` + `null_semantics: unknown` |
| Renamed/aliased — `column_id` doesn't resolve | `source:` override (+ optionally `role:`) |
| Sole, unambiguous, fully resolves via `column_id`, no NULL semantics | **Empty.** `column.description` carries any prose. |
| Surrogate key — never user-facing | **Empty.** |

---

## Forbidden — explicitly do NOT include

| Axis | Reason |
|---|---|
| Free-form prose of any kind (`meaning`, `description`, `watch`, `watch_out`, `notes`) | Prose is for humans and lives in `column.description`. Mixing prose into `ai_context` dilutes the signal and tempts the LLM to over-read. |
| `synonyms` | Already in TML `column.synonyms`. |
| `formula` (TS DSL) | **Actively harmful.** Test 4's defining failure mode — LLM transliterated TS DSL as SQL. The actual formula stays in TML's `formulas[]` block where TS reads it; ai_context describes *what* the formula represents (additivity, time_basis), not *how*. |
| `additive_dimensions` | Removed 2026-04-29. Redundant with `non_additive_dimension` (which carries the actual signal). |
| `unit_label` (e.g. `"$"`) | Already in column display format. |
| `example_question` | Covered elsewhere in ThoughtSpot (e.g. `nls_feedback` REFERENCE_QUESTION entries). |
| TS object cross-references (worksheet IDs, model GUIDs) | Useless to a third-party LLM. |

---

## Tiering by column type — reference table

| Column type | Required | Recommended |
|---|---|---|
| MEASURE (additive) | `additivity`, `time_basis`, `grain_keys` | `unit`, `null_semantics` |
| MEASURE (semi-additive) | Above + `non_additive_dimension` | `unit`, `null_semantics` |
| MEASURE (non-additive) | `additivity: non_additive`, `time_basis`, `grain_keys` | `unit`, `null_semantics` |
| MEASURE (formula, multi-input) | Same as the additivity tier above. **Inputs are NOT declared in ai_context** — they're in the formula text. | Same. |
| ATTRIBUTE — id/code/label/key sibling | `role:` | `null_semantics`, `source` (override) |
| ATTRIBUTE — stand-alone with NULL meaning | `role: label` (recommended) + `null_semantics` | `source` (override) |
| ATTRIBUTE — sole, unambiguous, resolves cleanly | — (`ai_context` may be empty) | — |
| ATTRIBUTE — surrogate key, never user-facing | — | — |

---

## Worked example — `Inventory Balance`

This Model has a shared conformed date dim `DM_DATE_DIM`, so `time_basis` points
there — combining with `Amount` joins on the shared date and does not fan out.

```yaml
additivity: semi_additive
non_additive_dimension: DM_DATE_DIM.Date
time_basis: DM_DATE_DIM.Date
grain_keys: [Product, DM_DATE_DIM.Date]
unit: count
null_semantics: no_snapshot
```

`ai_context` size: ~170 chars (well under the 400 hard limit). `source` is omitted
because the formula references `[Filled Inventory]` whose `column_id`
(`DM_INVENTORY::FILLED_INVENTORY`) resolves cleanly via the table's `fqn`.

Prose context for this column — *"end-of-period warehouse position; excludes
in-transit stock"* — goes in `column.description`, not here.

For more worked examples (display-name failures, TS DSL transliteration, chasm
fanout, dimensional disambiguation), see
[ai-context-examples.md](ai-context-examples.md).

---

## Safeguards (binding rules)

### 1. Structured-only

Allowed-key list is closed. Every value lex-checks as an enum, a `<col_ref>`, a
`<SCHEMA.TABLE.COLUMN>` path, or a list of those. Free-text values are rejected at
deploy validation.

### 2. Generator system-prompt rule (four clauses)

Skill generators (Step 6.1) and any downstream LLM prompt that consumes TML +
`ai_context` must include this clause verbatim:

> *"This TML mixes ThoughtSpot DSL with metadata. Distinguish them when emitting SQL:*
>
> 1. *The `formulas[]` block contains **ThoughtSpot formula DSL**, not SQL. Functions
>    like `last_value(...)`, `query_groups(...)`, `growth_rate(...)`,
>    `cumulative_sum(...)` and any other TS-specific formula functions are **not** SQL
>    functions. Re-implement the formula's intent in target SQL from scratch — never
>    copy or partially translate the DSL.*
> 2. *Square-bracket column refs (`[Amount]`, `[Stock Quantity]`) and curly-brace dim
>    refs (`{DM_DATE_DIM.DATE}`) are **TS logical references**, not SQL identifiers.
>    Resolve each to its physical path via `column_id: TABLE::COL` plus the table's
>    `fqn` (or via an explicit `source:` axis when present, which overrides
>    column_id).*
> 3. *Column and table **display names** (e.g. `Total Sales`, `Inventory Balance`,
>    `Product Category`) are **TS logical names**. They are never valid SQL
>    identifiers — resolve them to physical paths the same way as bracket refs.*
> 4. *The `ai_context` block declares constraints on the column's result
>    (additivity, time_basis, grain_keys, role). Respect them when writing SQL; do
>    not infer constraints that are not declared. All prose context for a column
>    lives in `column.description`, not `ai_context`."*

### 3. Deploy-time validation (Step 8b)

Before TML import, validate:

- Every `source:` value (when present) resolves to a physical column that actually
  exists in the underlying Snowflake schema.
- Every `time_basis:` and `non_additive_dimension:` value references a real Model
  column (and `time_basis:` is on a date dim).
- `additivity: semi_additive` requires `non_additive_dimension` to be populated.
- `additivity:`, `unit:`, `null_semantics:`, `role:` values are from their closed
  enums.
- Every value lex-checks as an enum or ref — **no free-text patterns** (rejects any
  value containing whitespace + alpha-only words that don't match a ref shape).
- Total `ai_context` payload ≤ 400 chars per column (verified hard limit;
  see `open-items.md #14`).

Validation failures block import; the user is shown the offending columns and the
specific rule that failed.

### 4. Absent means absent — never infer

If `ai_context.additivity` is missing, the LLM falls back to plain column-name
reasoning. The system prompt **must not** instruct the LLM to "use a sensible
default." Defaults are where hallucination starts. Either an axis is present (LLM
uses it) or absent (LLM treats it as unknown). No bridging with guesses.

### 5. Fall-back priority when 400-char budget is tight

Drop optional tier first, in this order:

```
null_semantics  →  unit  →  role
```

**Mandatory tier is never dropped.** If the mandatory tier alone cannot fit
(extremely rare — typical is ~170 chars), the column needs structural simplification
(shorter `grain_keys`, shorter ref names), not axis dropping.

### 6. Prose has a home — `column.description`

Step 6.1 generates one prose `description` (≤ 200 chars; sentences allowed) per
column **AND** the structured `ai_context`. Both surfaces are populated, with no
overlap:

- `ai_context` answers *"what constraints does an LLM need to write correct
  SQL?"* — additivity, time anchor, grain, role. Authoritative; read first.
- `column.description` answers *"what's the business meaning?"* — gotchas, edge
  cases, history. Read by LLMs as supplementary narrative and by humans as the
  readable surface.

---

## Motivation — why this schema exists

The `agent-expressibility-eval` runs (Test 3 vs Test 4) showed that giving Claude a
ThoughtSpot Model TML as semantic context **degraded** answer quality vs. a
Snowflake `DESCRIBE SEMANTIC VIEW` context (65.3% vs 80.2%; FAILs jumped 5 → 17).
The four failure clusters and their fixes:

| Failure cluster | Fix in this schema |
|---|---|
| Wrong physical column references (`Total_Sales`, `[Amount]`, phantom `DM_CATEGORY`) | Clauses 2 & 3 of the system-prompt rule (resolve via `column_id` + `fqn`); `source:` override for renamed columns; `role:` for label/id disambiguation |
| TS DSL formulas transliterated as SQL (`last_value(...)`, `query_groups(...)`) | Clause 1 of the system-prompt rule; `formula` axis forbidden in ai_context |
| Semi-additive trap (SUM'd `FILLED_INVENTORY` across dates) | `additivity` mandatory + `non_additive_dimension` required for semi-additive |
| Chasm fanout on cross-fact joins (inventory + sales on raw dates) | `time_basis` mandatory, anchored on conformed date dim |

The full failure analysis lives in
`/Users/damianwaldron/Dev/agent-expressibility-eval/runs/dunder-mifflin-sales-inventory__1777408743/`.
