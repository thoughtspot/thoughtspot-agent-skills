# Feedback TML Verified-Working Patterns — `ts-coach-model`

A library of `nls_feedback` syntax patterns mined from real `BUSINESS_TERM` and
`REFERENCE_QUESTION` entries on production-coached Models. Use this when
generating feedback TML — patterns documented here are **verified to import
without rejection**.

> Mined 2026-04-27 from champ-staging via `POST /api/rest/2.0/metadata/tml/export`
> with `metadata[].type: FEEDBACK` (4 source objects, 53 entries). Updated as
> new patterns are observed.
>
> The mining script lives in [`open-items.md`](open-items.md) #16 and runs
> against any reachable profile.

---

## How to export feedback TML for a Model

Two verified API paths:

**Path 1 — feedback only:**

```http
POST /api/rest/2.0/metadata/tml/export
{
  "metadata": [{"identifier": "<model_or_object_guid>", "type": "FEEDBACK"}],
  "edoc_format": "YAML"
}
```

Response: an array with one object containing `edoc` (the YAML feedback TML)
and `info` (status / name / type).

**Path 2 — Model + associated feedback** (requires version 10.7.0.cl or later):

```http
POST /api/rest/2.0/metadata/tml/export
{
  "metadata": [{"identifier": "<model_guid>", "type": "LOGICAL_TABLE"}],
  "export_options": {"export_with_associated_feedbacks": true},
  "edoc_format": "YAML"
}
```

Use Path 1 when you only need feedback; use Path 2 when coupling feedback
re-import with a Model TML edit. The current skill uses Path 1 in Step 2b /
Step 9c.

---

## search_tokens — verified syntactic shapes

All keys below are verified by appearing in at least one accepted
`nls_feedback` entry. Patterns NOT yet observed are listed at the end as
"untested — likely candidates."

### Column references (the foundation)

| Shape | Example | Notes |
|---|---|---|
| Single column | `[Amount]` | The simplest shape — single-measure or single-attribute |
| Multiple columns space-separated | `[Customer Name] [Amount]` | Most common shape; treat as "show A by B" implicitly |
| Three or more columns | `[Order Date] [Product Category] [Amount]` | Trend-by-dim shape; chart_type LINE is common |
| Case-insensitive | `[order date]` | The parser accepts mixed case; convention is to match Model column display name |

### Aggregation prefix (verified)

| Shape | Example | Notes |
|---|---|---|
| `sum [Col]` | `sum [Amount]` | Explicit aggregation request; common on BUSINESS_TERMs |
| `sum [Col] [Group]` | `sum [Quantity] [Customer Zipcode] [Customer Name]` | Combined with grouping columns |

`sum`, `count`, `avg`, `min`, `max` are all candidates by analogy — `sum` is
the only one verified in the current corpus.

### Filter syntax (verified)

| Shape | Example | Notes |
|---|---|---|
| Equality literal | `[Category] = 'printer paper'` | Single-quoted literal value; no spaces around `=` are also acceptable |
| Multiple filters (implicit AND) | `[Category] = 'printers' [Category] = 'printer paper'` | Two filters on the same column become an OR-set |
| Filter + measure | `[Amount] [Category] = 'printer paper'` | Standard "amount where category is X" shape |

**Verified rejected** (per the failed v1 import attempt 2026-04-27):
- Bare-equals without quotes: `[Order Date] = 2025` → ❌
- Use `[Order Date] = '2025'` instead

### Compare operator (`vs`)

| Shape | Example | Notes |
|---|---|---|
| Two filters compared | `[Category] = 'printers' vs [Category] = 'printer paper'` | Side-by-side comparison; chart_type COLUMN |
| Time-period compare | `[order date] = 'this year' vs [order date] = 'last year'` | The relative-time literal goes inside the filter quotes |

### Date bucketing (dot-suffix syntax)

| Shape | Example | Notes |
|---|---|---|
| Bare bucket | `[order date].monthly` | Bucket name as bare word after dot |
| Quoted bucket | `[order date].'month of year'` | Multi-word bucket names need quoting |

### Top / Bottom N

| Shape | Example | Notes |
|---|---|---|
| `top N [Col].<bucket>` | `top 10 [order date].monthly` | Verified: `top 10` BEFORE the column ref |

The v1 skill emitted `[Customer Name] [Amount] top 10` (keyword AFTER columns)
which was rejected. The verified-working position is **before** the column.

### Sort

| Shape | Example | Notes |
|---|---|---|
| `[Col] sort by [Col]` | `[Amount] sort by [Amount]` | Sort by self for ranked-list anchoring |

### Filter values for relative time (verified)

When inside a filter, the following literal-time strings are accepted:

- `'this year'`, `'last year'`
- `'this quarter'`, `'last quarter'`  *(implied — only `this/last year` directly observed; date-period quoting pattern is the same)*
- `'this month'`, `'last month'`  *(implied)*

Pattern: `[Date Col] = '<period>'` — note the value side is a quoted string,
not a bare keyword.

---

## chart_type — verified working values

From 53 entries, every observed `chart_type` was accepted:

| chart_type | Count in corpus |
|---|---|
| `KPI` | 26 |
| `COLUMN` | 19 |
| `LINE` | 6 |
| `HEATMAP` | 1 |
| `ADVANCED_PIVOT_TABLE` | 1 |

Corpus did NOT include: `BAR`, `PIE`, `STACKED_COLUMN`, `AREA`, `SCATTER`,
`TREEMAP`, `WATERFALL` — but [open-items.md #11](open-items.md) verified
those separately. Universal whitelist: any value listed in #11 except `TABLE`.

`TABLE` remains rejected — for tabular display use `chart_type: COLUMN` +
`display_mode: TABLE_MODE`.

---

## display_mode — verified working values

| display_mode | Count in corpus |
|---|---|
| `CHART_MODE` | 24 |
| `UNDEFINED` | 18 |
| `TABLE_MODE` | 11 |

`UNDEFINED` is the typical pairing with `chart_type: KPI` (no axes needed).
`CHART_MODE` pairs with COLUMN/LINE/etc. `TABLE_MODE` is for tabular display.

---

## axis_config — verified working shape

Present on 8/53 entries. Two observed shapes:

```yaml
# Shape A — y-only axis (KPIs and pivots)
axis_config:
- "y":
  - Total Amount
  - Company
```

```yaml
# Shape B — x + y axes with column-name-with-filter notation
axis_config:
- x:
  - MONTH_OF_YEAR(order date)
  "y":
  - Amount(order date = this year)
  - Amount(order date = last year)
```

Notes:
- Axis values are **synthetic display names**, not GUIDs — e.g.
  `Amount(category = printers)` is the rendered name of "Amount filtered by
  Category = printers"
- Date bucket function-style: `MONTH_OF_YEAR(order date)`,
  `DATE_TRUNC_MONTH(order date)` etc. (the corpus shows `MONTH_OF_YEAR`)
- The `y` key is sometimes quoted (`"y":`) and sometimes bare — both work

Omit `axis_config` entirely for entries where `display_mode: UNDEFINED` and
`chart_type: KPI` — the corpus has 18 such entries, all without axis config.

---

## parent_question — verified usage

`parent_question` on `BUSINESS_TERM` entries is set to the **broader question
the term participates in**, not just the term itself. Examples from the
corpus:

| feedback_phrase | parent_question |
|---|---|
| `total amount` | `total amount this year vs last year by order date` |
| `top 10` | `sum of amount by company monthly for this year where category is printers or printer paper, top 10 companies by amount` |
| `by company` | `sum of amount by company monthly for this year where category is printers or printer paper, top 10 companies by amount` |
| `category is printers or printer paper` | `sum of amount this year where category is printers or printer paper` |

Pattern: when the user is teaching Spotter that a phrase like `top 10` means
"limit to top 10 by the active measure in this question", the parent_question
provides the disambiguating context. Without it, `top 10` is ambiguous.

For `REFERENCE_QUESTION` entries, `parent_question` is typically **the same
as `feedback_phrase`** (the entry IS the canonical question, not a fragment).

---

## nl_context — verified usage

Empty string (`""`) on observed REFERENCE_QUESTION entries. Field exists but
is unused in the current corpus. Likely present for forward-compatibility
with future Spotter NL features.

---

## rating — verified values

`UPVOTE` and `DOWNVOTE` both observed. UPVOTE is the standard for affirmative
coaching; DOWNVOTE is used to teach Spotter what NOT to do (corpus shows one
DOWNVOTE on `top 10` with parent_question — telling Spotter that "top 10"
alone is not a complete question).

---

## access — verified values

`GLOBAL` and `USER` both observed. Per the skill's existing convention
([open-items.md #2 sub](open-items.md)):
- `GLOBAL` = visible to all Spotter users on the Model — shared coaching
- `USER` = visible only to the entry's author — personal / experimental

The skill defaults all generated entries to `GLOBAL`. Existing `USER` entries
are gated behind explicit opt-in at Step 5.

---

## Untested — likely candidates worth probing next

Patterns not yet observed in the corpus but plausible by analogy:

| Untested pattern | Why it might work | Test next time |
|---|---|---|
| `count [Col]` | Aggregation prefix; `sum [Col]` works | Add a "How many distinct customers" question |
| `[Col] > 100` | Numeric-comparison filter | Add a "where amount > X" filter question |
| `[Col] in ('a', 'b')` | Documented in the v1 keyword vocab | Replaces multi-equality OR-set |
| `[Date].'last 30 days'` | Bucket dot-suffix is verified; relative-period bucket might also work | Add a "last 30 days" question |
| `[Date] = 'q1 2025'` | Non-relative date-period filter | Add a "Q1 2025 amount" question |

Mark each as VERIFIED here once observed.

---

## Maintenance

This file is built from the mining script in
[open-items.md](open-items.md) #16. Re-run quarterly (or when a new TS
release lands) to pick up new verified patterns. The script:

1. Enumerates Models on each profile (`ts metadata search --subtype WORKSHEET --all`)
2. For each, calls `metadata/search` with `include_dependent_objects: true` to
   count feedback entries (skip Models with 0)
3. For Models with feedback, calls `metadata/tml/export` with
   `metadata[].type: FEEDBACK` to get the YAML
4. Parses each `nls_feedback.feedback[]` entry, extracts `search_tokens` and
   `axis_config` shapes, tallies feature counts, updates this file

Verified-pattern updates are a PR-time deliverable, not a hot-path skill
behaviour — the skill follows whatever this file currently says.
