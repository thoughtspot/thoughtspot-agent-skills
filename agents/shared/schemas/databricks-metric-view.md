<!-- currency: databricks — 2026-07 (PR1 window deep-analysis 2026-07-09: trailing/leading/cumulative/all/semi-additive range behavior live-verified against a Databricks fixture + ThoughtSpot number-match; corrected trailing/leading moving_sum anchor args (C1/C3) and the period-filter offset mechanism from wall-clock to row-relative (C6/C6a); exclusive-default confirmed (C2); materialization: block documented for the first time (C9); quarter/year period-offset grains Deferred (C8); see BL-032; PR1.5 semantic deep-dive 2026-07-09: LOD dimension × filter (A1) CONFIRMED filter-aware on TS under both filter kinds, cross-platform DIVERGENCE for a DBX consumer's ad hoc query-time WHERE (A2, DBX-internal asymmetry); cross-measure ratio × grain (B1) CONFIRMED ratio-of-sums cross-platform at every grain; global filter: × window ordering (C1) CONFIRMED filter-before-window cross-platform, frame semantics DIVERGENCE (date-interval vs row-positional); semi-additive × date-range filter (D1) CONFIRMED last/first-in-filtered-range cross-platform; trailing-window frame (E1) DIVERGENCE — DBX date-interval vs TS row-positional on gapped data, density caveat added; A3 follow-up (user-suggested) 2026-07-09: group_aggregate's `{}` filter argument CORRECTS the A1/A2 "no TS analogue" conclusion — `{}` is search-filter-blind but model-filter-aware, reproducing DBX's MV-filter-aware + query-WHERE-blind composite when paired with a mirrored model-level filters: block; subtraction form query_filters() - {col} import-accepted but does not exclude a derived-formula filter — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md; see BL-032) -->

# Databricks Metric View Schema

Reference for Databricks Unity Catalog Metric Views. Metric Views define reusable
semantic layers with dimensions, measures, and filters using YAML embedded in SQL DDL.

**Generally available (verified 2026-06-17).** Unity Catalog Business Semantics (which
includes Metric Views) went **GA on 2026-04-02**. The earlier "Preview channel required"
instruction is **obsolete** — do **not** flip warehouses to the Preview channel. Current
requirement: a SQL warehouse running **Databricks Runtime 17.3 or above** plus `CAN USE`
permission. (A `PARSE_SYNTAX_ERROR` on a GA-era runtime is no longer attributable to the
warehouse channel.) Sources: Databricks "Redefining the Semantics Data Layer" (2026-04) and
the [create/edit](https://docs.databricks.com/aws/en/business-semantics/metric-views/create-edit)
+ [YAML reference](https://docs.databricks.com/aws/en/business-semantics/metric-views/yaml-reference) docs.

---

## DDL Syntax

### Create

```sql
CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name}
WITH METRICS LANGUAGE YAML AS $$
version: 0.1
source: {catalog}.{schema}.{table_name}
...
$$
```

**Not** `CREATE METRIC VIEW` — that syntax does not exist.

### Describe (retrieve definition)

```sql
DESCRIBE TABLE EXTENDED {catalog}.{schema}.{view_name}
```

The YAML definition is in the `View Text` row of the output. Parse the result set,
find the row where `col_name = 'View Text'`, and extract the `data_type` column value.

Additional metadata rows: `Type` = `METRIC_VIEW`, `Language` = `YAML`,
`Table Properties` contains `metric_view.raw_yml` with the raw YAML.

### Discover (list Metric Views)

```sql
SELECT table_catalog, table_schema, table_name
FROM system.information_schema.tables
WHERE table_type = 'METRIC_VIEW'
  AND table_catalog = '{catalog}'
```

There is no `SHOW METRIC VIEWS` command.

### Drop

```sql
DROP VIEW {catalog}.{schema}.{view_name}
```

---

## Source Forms (verified 2026-07)

`source:` — whether at the top level or on a `joins[]` entry — accepts **four**
forms, not just a table FQN:

| Form | Example | Notes |
|---|---|---|
| Table FQN | `source: catalog.schema.table_name` | Most common — a physical table or view |
| Parenthesized SQL | `source: (SELECT ... FROM ...)` | Inline subquery, wrapped in parens |
| Bare SQL query | `source: SELECT ... FROM ...` | Inline subquery, **no parens** — the current YAML reference documents this form written directly, starting with `SELECT` or `WITH` |
| Another metric view | `source: catalog.schema.another_metric_view` | MV-on-MV — chains one metric view as the source of another |

**Detecting a SQL source (either form):** strip leading whitespace and check whether
the value starts with `(SELECT`, `(WITH`, `SELECT `, or `WITH ` (case-insensitive).
Do not assume parentheses are present — a bare SQL source silently mis-detected as a
table FQN produces a Table TML whose measure columns cannot be queried as plain
columns (`METRIC_VIEW_MISSING_MEASURE_FUNCTION`).

**Detecting an MV-on-MV source:** a plain FQN cannot be distinguished from a
physical table by string shape alone — query
`system.information_schema.tables WHERE table_type = 'METRIC_VIEW'` for the
referenced FQN before assuming it is a physical table. See
[ts-from-databricks-rules.md](../mappings/ts-databricks/ts-from-databricks-rules.md)
for the from-direction handling of both forms (chained MVs are currently a fail-loud
case, not a supported flattening).

---

## Version 0.1 — Single Source (legacy)

> **Legacy spec version (note added 2026-06-17).** The current GA YAML reference documents
> **version 1.1** only, and the `version` field **defaults to 1.1**; v0.1 is no longer
> surfaced in the product docs. Treat this section as "may be encountered on older Metric
> Views" — the from-databricks parser must still read it, but **emit v1.1 for all
> conversions**. Newer GA constructs (top-level `materialization:` — see "Materialization
> Block" below; `fields:` as an alias for `dimensions:` — see "`fields:` vs `dimensions:`"
> below) originated from **BL-032** and are now documented in this file.

Single source table, flat list of dimensions and measures, optional global filter.
Column metadata is limited to `name`, `expr`, and `window` — no `display_name`,
`comment`, or `synonyms`. Use v1.1 for rich column metadata even on single-source MVs.

### Schema

```yaml
version: 0.1                        # Required. "0.1" for single-source.

source: catalog.schema.table_name   # Required. Table FQN, SQL query (parenthesized or
                                    # bare), or another metric view — see Source Forms above.

filter: <sql_boolean_expression>    # Optional. Global WHERE clause applied to all queries.
                                    # Uses column names from the source table directly.
                                    # Live-verified 2026-07-09 (docs/audit/2026-07-09-dbx-
                                    # semantic-claim-matrix.md, A1/A2): this global filter IS
                                    # seen by a partition-window LOD dimension computed inside
                                    # the same MV — but an ad hoc query-time WHERE clause
                                    # layered on top of an MV with NO global filter: is
                                    # filter-BLIND for that same LOD dimension (it prunes output
                                    # rows only, not the window's computed value). See the
                                    # Filter section of ts-from-databricks-rules.md /
                                    # ts-to-databricks-rules.md for the ThoughtSpot-side caveat.
                                    # A3 follow-up, live-verified 2026-07-09 (same matrix):
                                    # ThoughtSpot's group_aggregate(sum(x), {dim}, {}) + a
                                    # model-level filters: block mirroring this filter:
                                    # reproduces BOTH the filter-aware (this block) and the
                                    # filter-blind (ad hoc query-time WHERE) DBX conditions in
                                    # one construct — see the same rules-files section.

dimensions:                         # Optional (but a MV with no dimensions or measures is useless).
  - name: <identifier>              # Required. Only 3 fields allowed: name, expr, window.
    expr: <sql_expression>          # Required. SQL expression using source table columns.

measures:                           # Optional.
  - name: <identifier>              # Required. Only 3 fields allowed: name, expr, window.
    expr: <sql_aggregate_expression> # Required. Must include the aggregate function
                                    # (SUM, COUNT, AVG, etc.).
    window:                         # Optional. Semi-additive window (see Window section).
      - order: <dimension_name>
        range: current
        semiadditive: last           # REQUIRED when window is present.
```

**v0.1 Column limitations (verified 2026-05-25):**
- Only 3 properties per column: `name`, `expr`, `window`
- Adding `display_name`, `comment`, or `synonyms` fails with `Unrecognized field`
- **Recommendation:** Use v1.1 even for single-source MVs to get rich metadata

### Verified Example

From `demo_qsr.prayansh.ecommerce_transactions_basic_sales_metrics_view` on TS_WS
workspace (retrieved 2026-05-21):

```yaml
version: 0.1

source: demo_qsr.prayansh.ecommerce_transactions
filter: NOT is_return AND transaction_status = 'Completed'

dimensions:
  - name: Transaction Date
    expr: date_trunc('day', transaction_date)

  - name: Product Category
    expr: product_category

  - name: Region
    expr: region

  - name: Customer Segment
    expr: customer_segment

measures:
  - name: Total Sales
    expr: SUM(product_price * quantity * (1 - discount_percent))

  - name: Total Transactions
    expr: COUNT(DISTINCT transaction_id)

  - name: Average Order Value
    expr: SUM(product_price * quantity * (1 - discount_percent)) / COUNT(DISTINCT transaction_id)

  - name: Total Discount Amount
    expr: SUM(product_price * quantity * discount_percent)

  - name: Unique Customers
    expr: COUNT(DISTINCT customer_id)
```

### DESCRIBE TABLE EXTENDED Output Format

The output is a result set with columns `[col_name, data_type, comment, metadata]`:

| col_name | data_type | Notes |
|---|---|---|
| `Transaction Date` | `timestamp` | Dimension columns |
| `Product Category` | `string` | |
| `Total Sales` | `double measure` | Measure columns have ` measure` suffix on data_type |
| `Total Transactions` | `bigint measure` | |
| *(empty row)* | | Separator |
| `# Detailed Table Information` | | Section header |
| `Type` | `METRIC_VIEW` | Confirms this is a Metric View |
| `View Text` | *YAML string* | **The full YAML definition** |
| `Language` | `YAML` | |
| `Table Properties` | *key=value pairs* | Contains `metric_view.raw_yml`, `metric_view.from.name`, etc. |

### Key observations from v0.1

- `expr` in measures always includes the aggregate function (e.g., `SUM(col)`)
- `expr` in dimensions can be computed (e.g., `date_trunc('day', col)`, `CASE WHEN...`)
- `filter` applies globally — there is no per-dimension/measure filter
- **Only 3 fields per column:** `name`, `expr`, `window` — any other field is rejected
- No `display_name`, `comment`, `synonyms`, `description`, `primary_key`, or `foreign_key` fields
- Column names in `expr` reference the source table's columns directly (no table alias prefix)
- Subqueries are allowed in measure expressions (e.g., `COUNT(DISTINCT x) / (SELECT COUNT(DISTINCT x) FROM table)`)

---

## Version 1.1 — Rich Metadata (verified 2026-05-25)

v1.1 adds rich column metadata (`display_name`, `comment`, `synonyms`) and
multi-source join support. **Use v1.1 even for single-source MVs** — it supports
`source:` (single FQN) just like v0.1, but with full column metadata.

### Schema — Single Source (v1.1)

> **`fields:` vs `dimensions:` (GA 2026-04).** The GA YAML reference uses `fields:`
> as the canonical key for dimension columns. `dimensions:` is accepted as a backward-
> compatible alias. Parsers must check for `fields:` first, falling back to `dimensions:`.
> The `to-databricks` direction continues emitting `dimensions:` (accepted by all runtimes).

```yaml
version: 1.1                        # Required. "1.1" for rich metadata.
comment: >-                         # Optional. View-level description.
  Human-readable description of the Metric View.

source: catalog.schema.table_name   # Single-source mode — same as v0.1. Also accepts a SQL
                                    # query (parenthesized or bare) or another metric view —
                                    # see Source Forms above.

filter: <sql_boolean_expression>    # Optional. Global WHERE clause. See the "Live-verified
                                    # 2026-07-09" note under the v0.1 `filter:` field above —
                                    # this global filter IS seen by LOD/window dimensions
                                    # computed in the same MV; an ad hoc query-time WHERE on an
                                    # unfiltered MV is not.

dimensions:                         # GA canonical key is `fields:`; `dimensions:` accepted for backward compat.
  - name: <identifier>              # Required. Machine-readable identifier.
    expr: <sql_expression>          # Required. SQL expression or column reference.
    display_name: '<label>'         # Optional. Human-readable label.
    comment: '<description>'        # Optional. Column-level description.
    synonyms: ['alias1', 'alias2'] # Optional. Alternative search terms.

measures:
  - name: <identifier>
    expr: <sql_aggregate_expression> # Required. Aggregate function embedded.
    display_name: '<label>'
    comment: '<description>'
    synonyms: ['alias1', 'alias2']
    window:                          # Optional. Semi-additive window.
      - order: <dimension_name>
        range: current
        semiadditive: last           # REQUIRED when window is present.
```

### Schema — Multi-Source with Joins (v1.1)

v1.1 supports star-schema joins via a `joins:` field on the `source`. Joins can be
**nested** to express multi-hop relationships (e.g., fact → order → customer).

```yaml
version: 1.1
comment: >-
  Multi-source Metric View description.

source: catalog.schema.fact_table   # Required. The primary fact table — table FQN, SQL
                                    # query, or another metric view (see Source Forms above).

joins:                              # Optional. Dimension table joins.
  - name: <alias>                   # Required. Alias used in expr references.
    source: <catalog.schema.dim>    # Required. Fully qualified dimension table (or SQL
                                    # query — see Source Forms above).
    "on": source.<fk> = <alias>.<pk>  # Required IF `using` is not specified. Join condition
                                    # (SQL boolean expression).
    using: [<col1>, <col2>]         # Required IF `on` is not specified. Array of column
                                    # names present in BOTH the parent (source or parent
                                    # join alias) and the joined table. `on` and `using`
                                    # are mutually exclusive — exactly one must be present.
    rely:                           # Optional. Cardinality hint (pre-18.1 syntax).
      at_most_one_match: true       # Declares many-to-one relationship.
    cardinality: many_to_one        # Optional (Runtime 18.1+). Alternative to rely: block.
                                    # Values: many_to_one, one_to_many.
                                    # Equivalent: cardinality: many_to_one ↔ rely: { at_most_one_match: true }.
                                    # When both are present, cardinality: takes precedence.
                                    # Default when NEITHER rely: nor cardinality: is present: many_to_one.
    joins:                          # Optional. NESTED sub-joins under this join.
      - name: <sub_alias>
        source: <catalog.schema.sub_dim>
        "on": <alias>.<fk> = <sub_alias>.<pk>   # or `using: [<col>]` — same on/using rule applies
        rely:
          at_most_one_match: true

filter: <sql_boolean_expression>    # Optional. Uses alias.column or source.column syntax.
                                    # Same MV-filter-vs-query-time-WHERE asymmetry applies —
                                    # see the "Live-verified 2026-07-09" note under the v0.1
                                    # `filter:` field above.

dimensions:                         # GA canonical key is `fields:`; `dimensions:` accepted for backward compat.
  - name: <identifier>
    expr: <alias>.<column>          # References use join alias prefix (dot-path for nested).
    display_name: '<label>'
    comment: '<description>'
    synonyms: ['alias1', 'alias2']

measures:
  - name: <identifier>
    expr: <sql_aggregate_expression>
    display_name: '<label>'
    comment: '<description>'
    synonyms: ['alias1', 'alias2']
    format:                         # Optional. Display formatting.
      type: <currency|percentage>
      currency_code: <ISO_code>     # For currency type.
      decimal_places:
        type: exact
        places: <int>
    window:
      - order: <dimension_name>
        range: <current|cumulative|trailing <N> <unit>|leading <N> <unit>|all> [inclusive|exclusive]
        semiadditive: <last|first>  # REQUIRED when window is present.
        offset: <-N period>         # Optional. Period offset for comparisons (e.g., "-1 month").
```

### Join Structure (verified 2026-05-26)

Joins use **nested hierarchy**, not sibling-level references. Each join's `on` clause
references its **parent** (either `source` for top-level joins, or the parent join's
alias for nested joins):

```yaml
joins:
  - name: orders                                # top-level: references source
    source: catalog.schema.dm_order
    "on": source.ORDER_ID = orders.ORDER_ID
    joins:
      - name: customers                         # nested: references parent (orders)
        source: catalog.schema.dm_customer
        "on": orders.CUSTOMER_ID = customers.CUSTOMER_ID
      - name: employees                         # nested: references parent (orders)
        source: catalog.schema.dm_employee
        "on": orders.EMPLOYEE_ID = employees.EMPLOYEE_ID
  - name: products                              # top-level: references source
    source: catalog.schema.dm_product
    "on": source.PRODUCT_ID = products.PRODUCT_ID
    joins:
      - name: category                          # nested: references parent (products)
        source: catalog.schema.dm_category
        "on": products.CATEGORY_ID = category.CATEGORY_ID
```

**Column references use dot-path through the join hierarchy:**
- `source.COL` — fact table column
- `orders.COL` — first-level join column
- `orders.customers.COL` — nested join column (through orders)
- `products.category.COL` — nested join column (through products)

**Cardinality hints** tell the optimizer each fact row matches at most one dimension
row. Two equivalent syntaxes exist:

| Syntax | Runtime | Example |
|---|---|---|
| `rely: { at_most_one_match: true }` | All (pre-18.1 and later) | Original syntax |
| `cardinality: many_to_one` | 18.1+ only | GA-era alternative; also supports `one_to_many` |

When both `rely:` and `cardinality:` are present on the same join, `cardinality:`
takes precedence. Parsers must check `cardinality:` first, falling back to `rely:`.

**Default cardinality (verified 2026-07):** when a join specifies **neither**
`rely:` nor `cardinality:`, the spec's default is `many_to_one`.

**Sibling-level references do NOT work.** A join's `on` clause cannot reference
another join at the same level — only `source` or the parent join alias. Nesting
is the mechanism for multi-hop relationships.

**Join condition: `on` vs `using` (verified 2026-07).** A join specifies exactly
one of:
- `"on": <sql_boolean_expression>` — arbitrary join condition (dot-path column refs)
- `using: [<col1>, <col2>, ...]` — shorthand for columns present under the **same
  name** in both the parent (`source` or the parent join's alias) and the joined
  table; equivalent to AND-ing an equality per column, e.g.
  `using: [ORDER_ID]` ≡ `"on": source.ORDER_ID = orders.ORDER_ID`.

`on` and `using` are mutually exclusive (XOR) — a join must have one, not both.

### Format Field (verified 2026-05-26)

Measures support a `format:` field for display formatting:

```yaml
measures:
  - name: revenue
    expr: SUM(LINE_TOTAL)
    format:
      type: currency
      currency_code: USD
      decimal_places:
        type: exact
        places: 2
  - name: growth_pct
    expr: ...
    format:
      type: percentage
      decimal_places:
        type: exact
        places: 1
```

| Format type | Fields | Notes |
|---|---|---|
| `currency` | `currency_code`, `decimal_places` | ISO 4217 code (USD, EUR, etc.) |
| `percentage` | `decimal_places` | Value is multiplied by 100 for display |

### Window with Offset — Period-over-Period (verified 2026-05-26; requires Runtime 18.1+)

> **Runtime gate:** The `offset` property requires **Runtime 18.1+**. On Runtime 17.3,
> MVs with `offset` in a `window:` entry cause `PARSE_SYNTAX_ERROR`. The base `window:`
> syntax (`order`, `range`, `semiadditive`) works on Runtime 17.3+; only `offset` is gated.

The `window:` field supports an `offset` property for period comparisons:

```yaml
measures:
  - name: monthly_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
  - name: prior_month_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 month           # one period back
  - name: prior_year_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_month
        semiadditive: last
        range: current
        offset: -1 year            # same month, prior year
  - name: cumulative_revenue
    expr: SUM(LINE_TOTAL)
    window:
      - order: order_date
        semiadditive: last
        range: cumulative           # running total
```

**Live-verified 2026-07-09 — row-relative, not wall-clock** (matrix C6/C6a,
`docs/audit/2026-07-08-dbx-window-claim-matrix.md`): `range: current` (with or
without `offset`) is evaluated **relative to each output row's own period**, as
ordered by the `order:` dimension — it is **not** anchored to wall-clock `today()`.
Querying `prior_month_revenue` across a multi-month trend returns the *previous row's*
period value for every row (a `LAG`-style shift), not a filter to a single fixed
calendar month. An out-of-range `offset` (e.g. the earliest row has no "prior" row)
evaluates to `NULL`, not `0`. See
[ts-databricks-formula-translation.md](../mappings/ts-databricks/ts-databricks-formula-translation.md)
for the corrected ThoughtSpot translation.

| `range` value | Meaning |
|---|---|
| `current` | Current period only |
| `cumulative` | Running total from start to current period |
| `trailing <N> <unit>` | Rolling look-back window of `<N> <unit>` (e.g. `trailing 7 day`) ending at the anchor row |
| `leading <N> <unit>` | Rolling look-ahead window of `<N> <unit>` starting at the anchor row. **Live-verified 2026-07-09** — see [ts-databricks-formula-translation.md](../mappings/ts-databricks/ts-databricks-formula-translation.md) and `docs/audit/2026-07-08-dbx-window-claim-matrix.md` (C3). |
| `all` | The entire partition, unbounded in both directions — scoped **per query partition**, not table-wide. **Live-verified 2026-07-09** — see the same matrix (C4). |

**Anchor-row modifier (Live-verified 2026-07-09 — matrix C1/C2/C3):** `trailing` and
`leading` ranges accept an optional `inclusive|exclusive` modifier (e.g.
`trailing 7 day exclusive`) controlling whether the anchor (current) row is included
in the window. The modifier applies **only** to `trailing`/`leading` — `current`,
`cumulative`, and `all` do not accept it.

**Default: `exclusive`** (Runtime 18.1 + YAML 1.1; DBSQL 2026.10 preview, release
note 2026-03-26) — confirmed live 2026-07-08: `trailing N day` == `trailing N day
exclusive` at all 24 fixture rows, including matched boundary `NULL`s (matrix C2).

**Corrected ThoughtSpot equivalence.** The `trailing N day` ↔ `moving_sum([m], N, 0,
[date])` mapping documented in this repo before 2026-07-09 is **wrong** —
`moving_sum([m], N, 0, [date])` always includes the anchor row, so it reproduces
`trailing (N+1) day inclusive`, not `trailing N day` (default/exclusive). Corrected
mappings (all four forms live-verified against every row of a 24-row fixture,
including boundary partial-window/NULL rows):

| DBX Metric View `range` | ThoughtSpot formula |
|---|---|
| `trailing N day` (default) / `trailing N day exclusive` | `moving_sum([m], N, -1, [date])` |
| `trailing N day inclusive` | `moving_sum([m], N-1, 0, [date])` |
| `leading N day` (default) / `leading N day exclusive` | `moving_sum([m], -1, N, [date])` |
| `leading N day inclusive` | `moving_sum([m], 0, N-1, [date])` |

**Live-verified 2026-07-09** — see `docs/audit/2026-07-08-dbx-window-claim-matrix.md`
(C1, C2, C3).

**Density caveat (E1, live-verified 2026-07-09 on gapped data) — see
`docs/audit/2026-07-09-dbx-semantic-claim-matrix.md`.** The four corrected mappings
above were re-verified on data with date gaps and found to **diverge**: Databricks'
`trailing`/`leading N day` frame is a genuine date-interval window, while ThoughtSpot's
`moving_sum` counts rows. On dense daily data the two framings are indistinguishable
(which is why the original C1/C3 verification above didn't catch this); on gapped data
they produce different numbers.

Row-positional: matches Databricks' date-interval trailing/leading windows only when the order column is dense at the window's unit grain (one row per unit, no gaps) — see docs/audit/2026-07-09-dbx-semantic-claim-matrix.md (E1).

**Partial-window / boundary behavior (Live-verified 2026-07-09 — matrix bonus
finding):** Databricks `trailing`/`leading` windows return a **partial sum** when
1..N-1 rows are available in the requested direction, and `NULL` only when **zero**
rows are available — never an error, never a silent 0. ThoughtSpot's `moving_sum`
matches this exactly at every boundary row of the fixture. An out-of-range `offset`
(see below) also evaluates to `NULL` on both platforms.

`offset` uses `<-N period>` syntax where period is `month`, `year`, `day`, etc.
Cross-measure references can then compute growth rates:

```yaml
  - name: mom_growth_pct
    expr: (MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100
```

### Materialization Block (Public Preview)

`materialization:` is a top-level key — a sibling of `source:`, `fields:`/`dimensions:`,
`measures:`, `joins:`, and `filter:` — that configures automatic query acceleration via
materialized views. **Public Preview** status (per the `yaml-reference` docs page;
`create-edit` does not mention this block at all). Absent by default: omitting
`materialization:` does not change query semantics, only whether Databricks maintains
an acceleration structure behind the Metric View.

| Field | Required? | Notes |
|---|---|---|
| `schedule` | Optional | Refresh schedule string, same syntax as the materialized-view `SCHEDULE` clause (e.g. `every 6 hours`) |
| `mode` | Required | Only documented value today: `relaxed` |
| `materialized_views[]` | Required | List of materialization definitions |
| `materialized_views[].name` | Required | Identifier for the materialized view |
| `materialized_views[].type` | Required | `aggregated` or `unaggregated` |
| `materialized_views[].dimensions[]` | Conditional | Field names to materialize (documented alongside `aggregated` type) |
| `materialized_views[].measures[]` | Conditional | Measure names to materialize (documented alongside `aggregated` type) |

```yaml
materialization:
  schedule: every 6 hours
  mode: relaxed
  materialized_views:
    - name: baseline
      type: unaggregated
    - name: daily_status_metrics
      type: aggregated
      dimensions:
        - order_date
        - order_status
      measures:
        - total_revenue
        - order_count
```

**No ThoughtSpot equivalent** — this is a Databricks-side performance/refresh hint
with no analog in Model TML. See
[ts-databricks-properties.md](../mappings/ts-databricks/ts-databricks-properties.md)
("MV fields with no TS equivalent").

**verified 2026-07-08** — docs research only, see
`docs/audit/2026-07-08-dbx-window-docs-findings.md`; not live-SQL-tested (the parser
only needs to recognize the block's shape and pass it through, not execute
materialization).

### LOD Patterns (verified 2026-05-25)

Level of Detail calculations use **dimension window functions**, not measure
`AGGREGATE OVER` (which causes `PARSE_SYNTAX_ERROR`).

```yaml
# LOD as a DIMENSION with window function
dimensions:
  - name: category_quantity
    expr: SUM(QUANTITY) OVER (PARTITION BY PRODUCT_CATEGORY)
    display_name: 'Category Quantity'
    comment: 'Total units sold at the category grain, independent of query GROUP BY.'

# Cross-measure ratio referencing the LOD dimension
measures:
  - name: quantity
    expr: SUM(QUANTITY)
  - name: category_contribution_ratio
    expr: MEASURE(quantity) / ANY_VALUE(category_quantity)
    comment: 'Product share of category total units.'
```

**Rules:**
- LOD calculations → `dimensions[]` with `AGG() OVER (PARTITION BY ...)` in `expr`
- Cross-measure references → `MEASURE(measure_name)` in measure `expr`
- Referencing a dimension from a measure → `ANY_VALUE(dimension_name)`
- `AGGREGATE OVER` in YAML `expr` is NOT supported (causes `PARSE_SYNTAX_ERROR`)

### Semi-Additive Measures (verified 2026-05-25)

The `window` field on a measure requires `semiadditive` as a property. Using
`window` without `semiadditive` fails with `Missing required creator property 'semiadditive'`.

```yaml
measures:
  - name: inventory_balance
    expr: SUM(FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    comment: 'Semi-additive snapshot measure.'
    window:
      - order: balance_date       # dimension to order by
        range: current            # current row only
        semiadditive: last        # REQUIRED — take last value
```

Valid `semiadditive` values: `last`, `first`.

### Querying Metric Views

Measures must be wrapped in the `MEASURE()` function when querying. `agg()` is a
documented synonym for `MEASURE()` in this query context (DBSQL release note
2026-04-30) — query-side only; there is no verified evidence it is accepted inside
a metric view's YAML `expr` for cross-measure references, so this repo's
translation tables continue to emit `MEASURE()`:

```sql
SELECT product_name, MEASURE(quantity), MEASURE(amount)
FROM agent_skills.dunder_mifflin.dunder_mifflin_sales_mv
GROUP BY product_name
```

Without `MEASURE()` (or its `agg()` synonym), the query fails with
`METRIC_VIEW_MISSING_MEASURE_FUNCTION`.

### Differences from v0.1

| Aspect | v0.1 | v1.1 |
|---|---|---|
| Source | `source:` only | `source:` (fact table) + optional `joins:` (dimension tables) |
| Column fields | `name`, `expr`, `window` only | + `display_name`, `comment`, `synonyms`, `format:` |
| View-level comment | Not supported | `comment:` at top level |
| Column references | Direct column name | Direct (single-source) or `alias.column` dot-path (multi-source) |
| Joins | Not supported | Nested `joins:` with `rely:` or `cardinality:` (18.1+) — star schema support |
| LOD | Not available | Dimension window functions: `AGG() OVER (PARTITION BY ...)` |
| Cross-measure refs | Not available | `MEASURE(name)` in measure `expr` |
| Semi-additive | `window` with `semiadditive` | Same — `semiadditive` required in both versions |

### Verified v1.1 Example — Dunder Mifflin Sales MV (joined star schema)

From `agent_skills.dunder_mifflin.dunder_mifflin_sales_mv` (verified 2026-05-26).
Demonstrates nested joins, dot-path column refs, LOD, cross-measure, format, and
window with offset:

```yaml
version: 1.1
source: agent_skills.dunder_mifflin.dm_order_detail

joins:
  - name: orders
    source: agent_skills.dunder_mifflin.dm_order
    "on": source.DM_ORDER_DETAIL_ORDER_ID = orders.ORDER_ID
    joins:
      - name: customers
        source: agent_skills.dunder_mifflin.dm_customer
        "on": orders.DM_ORDER_CUSTOMER_ID = customers.CUSTOMER_ID
        rely: { at_most_one_match: true }
      - name: employees
        source: agent_skills.dunder_mifflin.dm_employee
        "on": orders.DM_ORDER_EMPLOYEE_ID = employees.EMPLOYEE_ID
        rely: { at_most_one_match: true }
      - name: dates
        source: agent_skills.dunder_mifflin.dm_date_dim
        "on": orders.DM_ORDER_ORDER_DATE = dates.DATE_VALUE
        rely: { at_most_one_match: true }
    rely: { at_most_one_match: true }
  - name: products
    source: agent_skills.dunder_mifflin.dm_product
    "on": source.DM_ORDER_DETAIL_PRODUCT_ID = products.PRODUCT_ID
    joins:
      - name: category
        source: agent_skills.dunder_mifflin.dm_category
        "on": products.DM_PRODUCT_CATEGORY_ID = category.CATEGORY_ID
        rely: { at_most_one_match: true }
    rely: { at_most_one_match: true }

comment: >-
  Dunder Mifflin Sales metrics built on normalized star schema — revenue,
  quantity, pricing, and period-over-period analysis.

dimensions:
  - name: order_date
    expr: orders.DM_ORDER_ORDER_DATE
    display_name: Order Date
    comment: Date the order was placed.
    synonyms: ['order placed', 'purchase date']
  - name: product_category
    expr: products.category.CATEGORY_NAME       # dot-path through nested join
    display_name: Product Category
    synonyms: ['category', 'product line']
  - name: customer_name
    expr: orders.customers.COMPANY_NAME         # dot-path through nested join
    display_name: Customer Name
    synonyms: ['customer', 'client', 'buyer']
  - name: employee_name
    expr: "CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)"
    display_name: Employee
    synonyms: ['sales rep', 'rep', 'salesperson']
  - name: category_total_revenue
    expr: SUM(source.LINE_TOTAL) OVER (PARTITION BY products.category.CATEGORY_NAME)
    display_name: Category Total Revenue
    comment: "Fixed LOD: total revenue at category grain."

measures:
  - name: revenue
    expr: SUM(source.LINE_TOTAL)
    display_name: Revenue
    format: { type: currency, currency_code: USD, decimal_places: { type: exact, places: 2 } }
    synonyms: ['sales', 'total sales', 'amount']
  - name: order_count
    expr: COUNT(DISTINCT orders.ORDER_ID)
    display_name: Order Count
    synonyms: ['number of orders']
  - name: category_contribution_pct
    expr: MEASURE(revenue) / ANY_VALUE(category_total_revenue) * 100
    display_name: Category Contribution %
    format: { type: percentage, decimal_places: { type: exact, places: 1 } }
  - name: monthly_revenue
    expr: SUM(source.LINE_TOTAL)
    window: [{ order: order_month, semiadditive: last, range: current }]
  - name: prior_month_revenue
    expr: SUM(source.LINE_TOTAL)
    window: [{ order: order_month, semiadditive: last, range: current, offset: -1 month }]
  - name: mom_growth_pct
    expr: (MEASURE(monthly_revenue) - MEASURE(prior_month_revenue)) / MEASURE(prior_month_revenue) * 100
    display_name: MoM Growth %
    format: { type: percentage, decimal_places: { type: exact, places: 1 } }
```

### Verified v1.1 Example — Dunder Mifflin Inventory MV

From `agent_skills.dunder_mifflin.dunder_mifflin_inventory_mv` (created 2026-05-25):

```yaml
version: 1.1
comment: >-
  Dunder Mifflin Inventory analysis — semi-additive stock levels.
source: agent_skills.dunder_mifflin.dm_inventory_flat

dimensions:
  - name: balance_date
    expr: DM_INVENTORY_BALANCE_DATE
    display_name: 'Balance Date'
    comment: 'Date the inventory balance was snapshotted.'

  - name: product_name
    expr: PRODUCT_NAME
    display_name: 'Product Name'
    synonyms: ['product', 'item']

measures:
  - name: inventory_balance
    expr: SUM(FILLED_INVENTORY)
    display_name: 'Inventory Balance'
    comment: 'Semi-additive snapshot measure.'
    synonyms: ['stock', 'stock on hand', 'current inventory']
    window:
      - order: balance_date
        range: current
        semiadditive: last
```

---

## Comparison with Snowflake Semantic Views

| Feature | Snowflake SV | Databricks MV |
|---|---|---|
| Format | SQL DDL (`CREATE SEMANTIC VIEW`) or YAML via `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` | `CREATE VIEW ... WITH METRICS LANGUAGE YAML AS $$ ... $$` |
| Retrieval | `GET_DDL('SEMANTIC_VIEW', ...)` | `DESCRIBE TABLE EXTENDED` → `View Text` row |
| Discovery | `SHOW SEMANTIC VIEWS IN SCHEMA` | `information_schema.tables WHERE table_type='METRIC_VIEW'` |
| Multi-table | `tables()` + `relationships()` | `joins:` with nested hierarchy (v1.1) — star schema via nested sub-joins |
| Dimensions | Nested under each table | Flat list — direct column or `AGG() OVER (PARTITION BY)` for LOD |
| Metrics/Measures | `metrics()` clause — aggregation in expression | `measures:` — aggregation embedded in `expr`; `MEASURE()` for cross-refs |
| Time dimensions | Separate `time_dimensions` section | No distinction — dates are regular dimensions |
| Synonyms | `with synonyms=(...)` | v1.1: `synonyms:` list; v0.1: not supported |
| Per-column comments | `comment='...'` | v1.1: `comment:` and `display_name:`; v0.1: not supported |
| LOD | Via SQL expressions | Dimension window functions: `SUM(x) OVER (PARTITION BY dim)` |
| Semi-additive | `last_value()` in SQL | `window: [{order: dim, range: current, semiadditive: last}]` |
| Cross-measure refs | Via SQL expressions | `MEASURE(measure_name)` + `ANY_VALUE(dim_name)` |
| Global filter | Not a concept | `filter:` block — filter-aware for LOD/window dimensions computed inside the same MV; an ad hoc query-time `WHERE` on an MV with no `filter:` is filter-blind for those same dimensions (live-verified 2026-07-09, `docs/audit/2026-07-09-dbx-semantic-claim-matrix.md` A1/A2). ThoughtSpot's `group_aggregate(sum(x), {dim}, {})` + a mirrored model-level `filters:` block reproduces both the filter-aware and filter-blind DBX readings at once (A3, same matrix) |
| CA extension | `with extension (CA='...')` | Not applicable |
| Preview required | No | No — GA since 2026-04-02 |

---

## SQL Execution via Databricks CLI

All SQL operations use the Statement Execution API via the Databricks CLI:

```bash
databricks api post /api/2.0/sql/statements \
  --profile {dbx_profile} \
  --json '{
    "warehouse_id": "{warehouse_id}",
    "statement": "{sql_statement}",
    "wait_timeout": "50s"
  }'
```

The `warehouse_id` is extracted from the profile's `sql_warehouse_http_path`:
```
/sql/1.0/warehouses/c6ed539a60038b93  →  c6ed539a60038b93
```

Response format:
```json
{
  "status": {"state": "SUCCEEDED"},
  "manifest": {"schema": {"columns": [...]}},
  "result": {"data_array": [[...], ...]}
}
```

For `PENDING` state, poll the statement ID:
```bash
databricks api get /api/2.0/sql/statements/{statement_id} --profile {dbx_profile}
```
