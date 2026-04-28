# ThoughtSpot Feedback TML — Structure Reference

How `nls_feedback` (Spotter coaching) entries are represented in TML for import via
the REST API or `ts tml import`. Each entry is one phrase-to-search mapping —
either a Reference Question (whole-question phrasing) or a Business Term
(phrase → existing column / formula).

The canonical proto definition lives at the internal ThoughtSpot source
(`callosum/public/edoc.proto`); this file is a working reference for skill
authors who do not have access to the proto. Field shapes here are confirmed
against a verified working TML payload — see [Verified example](#verified-example)
below.

---

## Top-level structure

```yaml
guid: "0e4406c7-d978-4be7-abd7-c34e8f7da835"        # Model GUID — feedback is owned by a Model
obj_id: "DunderMifflinSales-0e4406c7"                # {ModelName}-{guid8} convention (same as other TML types)
nls_feedback:
  feedback:
    - id: "1"
      type: REFERENCE_QUESTION
      access: USER
      feedback_phrase: "total sales"
      search_tokens: "sum [Amount]"
      rating: UPVOTE
      display_mode: UNDEFINED
      chart_type: KPI
    - id: "2"
      type: BUSINESS_TERM
      access: GLOBAL
      feedback_phrase: "by company"
      search_tokens: "[Company]"
      rating: UPVOTE
      display_mode: TABLE_MODE
      chart_type: KPI
```

| Field | Required | Notes |
|---|---|---|
| `guid` | Yes | The **Model** GUID. Feedback entries are dependents of the Model and share its scope |
| `obj_id` | Yes for export; ignored on import for new entries | `{ModelName-no-spaces}-{first-8-of-guid}` — matches Model/Answer convention |
| `nls_feedback.feedback[]` | Yes | Array of entries; one per phrase mapping |

A single TML payload may contain many entries; ThoughtSpot upserts each by `id`.
Imports use `ts tml import --policy ALL_OR_NONE` exactly like other TML types.

---

## Per-entry fields

| Field | Required | Type / values | Notes |
|---|---|---|---|
| `id` | Yes on import | string (numeric in practice: `"1"`, `"2"`, ...) | Stable per Model. Use `next_id(used_ids)` pattern (skill helpers); duplicate IDs are upserted |
| `type` | Yes | `REFERENCE_QUESTION` \| `BUSINESS_TERM` | Determines how Spotter consumes the entry — full question vs phrase mapping |
| `access` | Yes | `USER` \| `GLOBAL` | `USER` = private to creator; `GLOBAL` = shared with all Model consumers |
| `feedback_phrase` | Yes | string | The natural-language phrase the user types |
| `parent_question` | No (BUSINESS_TERM only) | string | Links this BT to a canonical REFERENCE_QUESTION; the parent's phrase is the value. Used for "this phrase is part of question X" coaching grouping |
| `search_tokens` | Yes | string | The tokenised search bar query — bracketed column names, operators, literals. See [Search tokens](#search-tokens) |
| `formula_info` | No (REFERENCE_QUESTION only — see open-items) | object | Inline formula definition; **rejected on BUSINESS_TERM** with `EDOC_FEEDBACK_TML_INVALID` (verified — see `ts-object-model-coach/references/open-items.md` #12) |
| `rating` | Yes | `UPVOTE` \| `DOWNVOTE` | DOWNVOTE is anti-coaching — Spotter avoids the mapping. Preserve on import; never silently flip |
| `display_mode` | Yes | `CHART_MODE` \| `TABLE_MODE` \| `UNDEFINED` | How the answer is rendered. `UNDEFINED` is the safe default |
| `chart_type` | Yes | enum — see [Chart type](#chart-type) | Required even on BUSINESS_TERM (verified — `open-items.md` #12). `KPI` is the universally safe default |
| `axis_config` | No | array of `{x, y, color}` mappings | Per-entry chart axis hints. Each element keyed by axis name with an array of column display names |
| `nl_context` | No | string | Free-text creator note — appears in the TS UI as "context for Spotter". Keep brief (`"testing where this coaching goes"` is typical) |

---

## Search tokens

`search_tokens` is the same syntax as the ThoughtSpot search bar — a single string
with bracketed column references, literals, operators, and modifiers:

```yaml
search_tokens: "sum [Amount] [Category] = 'printers' [Category] = 'printer paper' [order date] = 'this year'"
```

Rules:
- Column names go in square brackets: `[Amount]`, `[order date]`
- String literals in single quotes: `'printers'`, `'this year'`
- Operators: `=`, `>`, `<`, `<=`, `>=`, `!=`, `sort by`, `top N`, `bottom N`
- Aggregation prefixes: `sum`, `avg`, `count`, `min`, `max`, `unique count`
- Date granularity modifiers on date columns: `[order date].monthly`,
  `.quarterly`, `.yearly`, `.daily`, `.weekly`, `.'this year'`, `.'last month'`
- Comparison: `[Category].electronics vs [Category].printers` for side-by-side
- All bracketed names must reference columns or formulas that exist on the Model
  at import time — otherwise the entry is silently dropped (verified in
  `feedback_ts_tml_import_constraints` memory)

For BUSINESS_TERM entries, `search_tokens` typically references a single column
or formula:

```yaml
- type: BUSINESS_TERM
  feedback_phrase: "by company"
  search_tokens: "[Company]"
```

For REFERENCE_QUESTION entries, `search_tokens` is the full canonical query:

```yaml
- type: REFERENCE_QUESTION
  feedback_phrase: "sales monthly by country"
  search_tokens: "sum [Amount] [order date].monthly by [Country]"
```

---

## Chart type

Verified valid values (probed on champ-staging 2026-04-26, see
`ts-object-model-coach/references/open-items.md` #11):

| Value | Use for |
|---|---|
| `KPI` | Single-value metric — universally safe default |
| `COLUMN` | Vertical bars; default for category × measure |
| `BAR` | Horizontal bars |
| `LINE` | Time series |
| `PIE` | Share-of-total breakdowns |
| `STACKED_COLUMN` | Multi-series category breakdowns |
| `AREA` | Cumulative time series |
| `SCATTER` | Two-measure correlations |
| `TREEMAP` | Hierarchical share |
| `HEATMAP` | Two-dimension density |
| `WATERFALL` | Variance over time |
| `ADVANCED_PIVOT_TABLE` | Crosstab with row/column groupings (verified 2026-04-26 from a live BUSINESS_TERM export) |

**Rejected** (`EDOC_FEEDBACK_TML_INVALID` "Invalid chart_type field"):
- `TABLE` — use `chart_type: COLUMN` + `display_mode: TABLE_MODE` for table rendering instead
- `TABLE_MODE` — that's a `display_mode`, not a `chart_type`
- Any lowercase variant (`table`, `column`) — must be UPPERCASE

---

## Display mode

| Value | Effect |
|---|---|
| `CHART_MODE` | Render as the chart specified in `chart_type` |
| `TABLE_MODE` | Render as a table; `chart_type` still required (use `KPI` or `COLUMN`) |
| `UNDEFINED` | Spotter chooses; safe default for entries that don't pin presentation |

---

## Axis config

When `display_mode: CHART_MODE` and the chart benefits from explicit axis
mapping, attach `axis_config` to the entry. Each entry in the array is a chart
slot with column-name lists per axis:

```yaml
axis_config:
  - x:
      - Month(order date)
    "y":
      - Total Amount
    color:
      - Company
```

Recognised keys (verified): `x`, `y`, `color`. Each takes an array of column
display names — the same names that appear inside `[brackets]` in
`search_tokens`. For bare `KPI` entries the only meaningful key is `y`:

```yaml
axis_config:
  - "y":
      - Total Amount
```

`y` is quoted in YAML because lowercase `y` is otherwise interpreted as boolean
true.

For `chart_type: ADVANCED_PIVOT_TABLE`, axis_config can be omitted; the pivot
infers groupings from `search_tokens` ordering.

---

## Type-specific patterns

### REFERENCE_QUESTION

Whole-question phrasing → tokenised search. Spotter matches the user's NL
typing against `feedback_phrase` (and paraphrase variants) and dispatches the
`search_tokens` query.

```yaml
- id: "9"
  type: REFERENCE_QUESTION
  access: GLOBAL
  feedback_phrase: "sales monthly by country"
  search_tokens: "sum [Amount] [order date].monthly by [Country]"
  rating: UPVOTE
  display_mode: UNDEFINED
  chart_type: LINE
  axis_config:
    - x:
        - Month(order date)
      "y":
        - Total Amount
      color:
        - Country
  nl_context: ""
```

### BUSINESS_TERM with parent_question

Phrase → column / formula mapping that's part of a canonical question.
`parent_question` carries the parent's `feedback_phrase` verbatim:

```yaml
- id: "4"
  type: BUSINESS_TERM
  access: GLOBAL
  feedback_phrase: "by company"
  parent_question: "sum of amount by company monthly for this year where category is printers or printer paper, top 10 companies by amount"
  search_tokens: "[Company]"
  rating: UPVOTE
  display_mode: TABLE_MODE
  chart_type: KPI
  axis_config:
    - "y":
        - Company
```

Multiple BUSINESS_TERMs can share the same `parent_question` — they collectively
decompose the parent into reusable phrase fragments.

### BUSINESS_TERM standalone

For a phrase that maps to a column / formula but isn't tied to a parent question:

```yaml
- id: "1"
  type: BUSINESS_TERM
  access: GLOBAL
  feedback_phrase: "stock"
  search_tokens: "[Inventory Balance]"   # references existing Model column or formula
  rating: UPVOTE
  display_mode: UNDEFINED
  chart_type: KPI
```

Per `ts-object-model-coach/references/open-items.md` #12: BUSINESS_TERM cannot define a
new formula inline. `search_tokens` must reference artifacts already on the
Model.

---

## Rating semantics

| Rating | Spotter behaviour |
|---|---|
| `UPVOTE` | Use this mapping when the phrase is matched |
| `DOWNVOTE` | **Avoid** this mapping when the phrase is matched — anti-coaching, not absence-of-coaching |

Both ratings are first-class signal. `DOWNVOTE` entries should be preserved
through import/edit cycles — silently dropping or flipping them removes
correction signal.

---

## Verified example

The structure of every field above was verified against this exported TML
fragment (champ-staging, Dunder Mifflin Sales & Inventory):

```yaml
guid: "0e4406c7-d978-4be7-abd7-c34e8f7da835"
obj_id: "DunderMifflinSales-0e4406c7"
nls_feedback:
  feedback:
    - id: "1"
      type: REFERENCE_QUESTION
      access: USER
      feedback_phrase: "sum of amount this year where category is printers or printer paper"
      search_tokens: "sum [Amount] [Category] = 'printers' [Category] = 'printer paper' [order date] = 'this year'"
      rating: UPVOTE
      display_mode: CHART_MODE
      chart_type: KPI
      axis_config:
        - "y":
            - Total Amount
      nl_context: "testing where this coaching goes"
    - id: "3"
      type: BUSINESS_TERM
      access: USER
      feedback_phrase: "top 10"
      parent_question: "sum of amount by company monthly for this year where category is printers or printer paper, top 10 companies by amount"
      search_tokens: "top 10 [order date].monthly"
      rating: DOWNVOTE
      display_mode: CHART_MODE
      chart_type: ADVANCED_PIVOT_TABLE
    - id: "5"
      type: REFERENCE_QUESTION
      access: GLOBAL
      feedback_phrase: "sum of amount by company monthly for this year where category is printers or printer paper, top 10 companies by amount"
      search_tokens: "top 10 [order date].monthly [Company] [Amount] [Category] = [Category].printers [Category].'printer paper' [order date] = 'this year' sort by [Amount]"
      rating: UPVOTE
      display_mode: CHART_MODE
      chart_type: LINE
      axis_config:
        - x:
            - Month(order date)
          "y":
            - Total Amount
          color:
            - Company
      nl_context: ""
```

---

## Hard import constraints

Per `feedback_ts_tml_import_constraints` memory and verified open-items:

1. Every column / formula referenced in `search_tokens` must exist on the
   Model at import time — entries with stale references are silently dropped.
   Validate before import.
2. `chart_type` must be UPPERCASE and from the verified valid set above.
   `TABLE` is rejected.
3. `chart_type` and `display_mode` are required on every entry, including
   BUSINESS_TERM (open-items #12).
4. `formula_info` on BUSINESS_TERM is rejected — the API parses the expression
   as a search query, not a formula definition. Promote the formula to the
   Model first via `/ts-object-answer-promote`, then reference it in
   `search_tokens`.
5. Successful feedback imports return `{header, status: {status_code: OK}}`
   with empty `diff: {}` and no `object` field — different from Model TML.
   Don't interpret empty diff as failure.

---

## Open items

Field-level coverage gaps that should be closed when the proto is accessible
or when more example exports are collected:

- Are there per-entry timestamp fields (`created`, `modified`) that survive
  round-trip? Headers from the dependents API include them, but the example
  shows none in the entry body. May be set by the server.
- Is there a `language` or `locale` field on entries? Spotter is multilingual;
  storage location for non-English coaching is unverified.
- Full enum lists for `chart_type` — current verified set is 12 values; the
  proto likely has more (e.g. `BUBBLE`, `GEO_HEATMAP`, `SANKEY`).
- Whether `formula_info` is required for REFERENCE_QUESTION entries that
  perform a calculation in `search_tokens` (e.g. `sum [Amount] / [Quantity]`)
  or whether the calculation parses inline.

When the proto becomes accessible, reconcile this file and update
`ts-object-model-coach/references/open-items.md` accordingly.
