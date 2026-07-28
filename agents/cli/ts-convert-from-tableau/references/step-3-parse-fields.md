# Step 3 — TWB Parse Field Extraction Detail

Reference detail for **Step 3 — Parse TWB XML**: the field-by-field extraction rules for
what `ts tableau parse`'s JSON represents (per relation/element type), the SQL dialect notes
for pass-through formulas, and the blend date-grain resolution strategy. The step's spine
(run the parser, read the JSON, the per-datasource classification, and the topological
sort/dashboard-count/blend-graph procedures) stays in `SKILL.md`.

## Relation wrapper handling

TWB XML wraps `<relation>` elements in one of three structures. Check in order:
1. `_.fcp.ObjectModelEncapsulateLegacy.false...relation` tag
2. `_.fcp.ObjectModelEncapsulateLegacy.true...relation` tag
3. `<relation>` directly under `<connection class='federated'>` (fallback)

All three contain the same child elements — the wrapper determines where to look.

## Per-datasource field extraction

For each datasource, extract:

**Physical tables** — `<relation>` elements of `type="table"`:
- `name` attribute = table alias used in joins
- `table` attribute = fully-qualified physical table name — may be `[DB].[SCHEMA].[TABLE]`
  format; strip brackets and split on `.` to extract db, schema, and table components
- For Published Datasources (sqlproxy): if table name is `[sqlproxy]`, use
  `connection.get('dbname')` instead

**Custom SQL relations** — `<relation>` elements of `type="text"`:
- These contain raw SQL in the element text content — do NOT try to extract a table name
- Flag the relation as `source_type: "custom-sql"` and save the full SQL text
- Refactor the SQL: replace `<<` with `<`, `>>` with `>`, `==` with `=` (XML encoding
  artifacts from the TWB)
- These will generate a `sql_view:` TML instead of a `table:` TML (see Step 5c)
- Extract column names from the SQL `SELECT` clause aliases for column mapping

**Joins** — `<relation>` elements of `type="join"`:
- `join` attribute = join type (`inner` | `left` | `right` | `full`)
- `<clause>` child = join condition (decode HTML entities: `&quot;`→`"`,
  `&amp;`→`&`, `&lt;`→`<`, `&gt;`→`>`)
- Extract left and right table references from the clause

**Physical columns** — from `<metadata-records>` → `<metadata-record class="column">`:
- `local-name` = column identifier
- `remote-name` = physical column name in the database (use for `db_column_name`)
- `local-type` = Tableau data type
- `parent-name` = which table this column belongs to
- Also extract from `<column>` elements WITHOUT a `<calculation>` child:
  `name` (strip brackets), `datatype`, `role` (dimension/measure), `caption` (display name)

**Calculated fields** — `<column>` elements WITH a `<calculation class="tableau">` child:
- Skip columns where `param-domain-type` is `list` or `range` — these are Tableau
  parameters, not calculated fields
- `caption` or `name` = display name
- `calculation formula` attribute = Tableau expression (decode HTML entities)
- `datatype` attribute
- Build a cross-reference map: Tableau internal names (`[Calculation_1234567890]`) →
  display names. Calculated fields reference each other by internal ID in the TWB XML,
  not by display name — resolve these references before translating formulas.

**Parameters** — `<datasource name="Parameters">` children:
- For each `<column>` with `param-domain-type` attribute:
  - `caption` = display name (used as ThoughtSpot parameter name)
  - `datatype` = `string` | `integer` | `real` | `date` | `boolean`
  - `param-domain-type` = `list` | `range` | `any`
  - `value` attribute or `calculation.formula` = default value
  - `<member value="...">` children = list values (when `param-domain-type="list"`)
  - `<range min="..." max="...">` child = range bounds (when `param-domain-type="range"`)
- Save parameter definitions — these generate `model.parameters[]` in Step 5b
- **SQL-lookup parameters** (where the list values come from a database query rather
  than static `<member>` elements): save the query/column reference — at migration
  time (Step 5b), query the warehouse to populate `list_config.list_choice[]` with
  current values. In audit mode (no connection), flag as "requires connection"

## Redshift and Postgres dialect notes

When `<connection class="redshift">` or `<connection class="postgres">` is detected,
pass-through SQL (`sql_*_op`) formulas should use the corresponding dialect syntax. Key
differences from Snowflake:
- String concatenation: `||` (same as Snowflake)
- Date truncation: `date_trunc('month', col)` (same syntax, both dialects)
- `LISTAGG` → Redshift: `LISTAGG(col, ',') WITHIN GROUP (ORDER BY col)`; Postgres: `string_agg(col, ',' ORDER BY col)`
- Type casting: Redshift uses `::type`; Postgres uses `CAST(x AS type)` or `::type`

No other mapping changes are needed — the Tableau-to-ThoughtSpot formula translation is
warehouse-agnostic (ThoughtSpot formulas are the target, not SQL). The dialect only matters
for `sql_*_op` pass-through functions.

## Blend date-grain linking columns (Step 3e)

When a `<column-instance>` has a `derivation` other than `"None"` (e.g. `"Month"`,
`"Month-Trunc"`, `"Year"`, `"Year-Trunc"`), the blend links at a specific time grain.
For the ThoughtSpot model join, the physical date column is used directly — ThoughtSpot's
date bucketing at query time handles the grain alignment.

However, if the source and target columns are physically different date columns with
different native grains (e.g. source has daily `Order Date`, target has monthly
`Month of Order Date` that is already pre-truncated), the join requires a
**date-truncation formula** or **SQL View** to materialize the matching grain.

**Resolution strategy:**
1. If both columns are date/datetime type and the derivation indicates a truncation
   (`Month-Trunc`, `Year-Trunc`), emit a model formula:
   `date_trunc ( 'month' , [TABLE::Order Date] )` and use that formula as the join key
   via a SQL View (the formula can't be a direct join key in model TML).
2. **Surface the grain mismatch** to the user in the review checkpoint with a recommendation:
   - "Blend links `Order Date` (daily) to `Month of Order Date` (monthly) at month grain.
     Recommend: create a SQL View with `DATE_TRUNC('MONTH', ORDER_DATE) AS ORDER_MONTH` and
     join on `ORDER_MONTH = MONTH_OF_ORDER_DATE`."
3. If both columns are the same physical type and grain, use them directly in the join `on`
   clause — no materialization needed.

## Published datasource (sqlproxy) resolution detail (Step 3.5)

**What the TWB DOES contain for sqlproxy datasources** (extract these in Step 3b regardless
of API access — they are `<column>` elements directly under the `<datasource>` element): all
**calculated fields** with full Tableau formula text (same as direct-connection datasources);
**column definitions** with captions, datatypes, and roles; **metadata records**
(local-name, remote-name, local-type, parent) — often complete enough for column mapping.

**What the TWB does NOT contain** (it lives only in the published datasource's `.tds`): the
**physical table structure** (table names, joins, db/schema/table paths); the **connection
details** (database, schema) that link to the warehouse. This means formula extraction and
translation work without the physical model — the `.tds` adds physical table resolution and
join definitions, not the formulas.

**Where the physical model actually is — and how to get it.** The join/table structure is
**not** returned by the field API. `ts tableau datasource --fields` (VizQL `read-metadata`)
returns **columns/calcs only**, not tables or joins. The full physical model (tables, joins,
custom SQL) lives in the published datasource's **`.tds`**. Two ways to obtain and parse it:
download it (needs Tableau access — `ts tableau download {datasource_id}` fetches the
`.tdsx`; the `.tds` inside carries the model), or be supplied it (the user provides the
`.tds`/`.tdsx` alongside the `.twb`). Then **`ts tableau parse` accepts a `.tds`/`.tdsx`
directly** (ts-cli ≥ 0.38.0) — its root *is* the `<datasource>`, and parse extracts its
tables/joins/columns/calcs just like a workbook datasource. Feed that to `build-model`
GENERATE mode and it builds the multi-table model automatically — no hand-assembly (see
Step 5b "Multi-query datasources"). Without the `.tds` (only the `.twb`, no Tableau access),
fall back to the hand-built multi-table base in Step 5b.

**Flow when the user has Tableau API access (Step 3.5, choice Y):** for each sqlproxy
datasource, extract `dbname` from the `<connection>` element, then:

Progress label: `"Querying Tableau API (not ThoughtSpot) to resolve published datasource
columns…"` — make it clear this is a Tableau Server query, not a ThoughtSpot metadata search.

```bash
# Find the published datasource by name
ts tableau datasources --profile {PROFILE} --name "{dbname}"
```

Parse the JSON output to get the datasource `id`, then:

```bash
# Get field metadata
ts tableau datasource {id} --profile {PROFILE} --fields
```

The `fields` array contains: `fieldCaption` (column display name → ThoughtSpot column
name), `dataType` (`real`/`integer`/`string`/`date`/`datetime`/`boolean` → TS data type),
`columnClass` (`COLUMN` physical, `CALCULATION` formula, `BIN`, `GROUP`), `formula` (for
calculated fields — the Tableau formula text for Step 5 translation).

Merge the resolved fields into the parsed datasource structure, replacing opaque sqlproxy
column references with real names and types. Proceed to Step 4.

**textscan (CSV) / excel-direct sources — offer to download for warehouse provisioning.**
Essential when the data only exists in Tableau Cloud and hasn't been loaded into a warehouse:

```bash
# Download the published datasource content
ts tableau download {datasource_id} --profile {PROFILE} --output-dir {output_dir}
```

The command downloads the TDSX archive, extracts it, and **validates CSV files** for row
integrity (column count consistency, corrupt lines). If `is_valid: false`, report the
corrupt lines and offer to auto-fix (strip them) before proceeding to warehouse load (the
DunderMifflin live test, 2026-06-26, found a corrupt line — `1tou` — in a Tableau Cloud
textscan download; this is a known Tableau artifact). If `is_valid: true`, proceed — the CSV
is clean for loading.

Surface: "The data for datasource '{name}' is a {type} file hosted on Tableau Cloud. It
needs to be loaded into a warehouse table before ThoughtSpot can connect to it. I've
downloaded and validated it — {row_count} rows, {status}. Shall I help set up the warehouse
table? (This will require a Snowflake/Databricks connection.)" If yes, this is the handoff
point for **BL-010 (`ts-load-source-data`)** when that skill is built. Until then, guide the
user through manual warehouse provisioning (CREATE TABLE + stage + COPY INTO for Snowflake,
or INSERT VALUES for Databricks).

**Prerequisites:** Tableau profile configured via `/ts-profile-tableau` (optional — skill
degrades gracefully); `ts` CLI v0.73.0+ (includes `ts tableau build-model` with
`--max-retries`, enriched error reporting, GENERATE mode output, and `--table-name-map`).
