# Step 5 — TML Generation Detail

Reference detail for **Step 5 — Generate TML Files**: multi-datasource edge-case
hand-assembly procedures, the Model TML invariants and hand-assembly template, the
parameter-migration lookup table and gotchas, the formula-translation edge-case rule set,
the full Tableau Sets → ThoughtSpot column-set/query-set translation (Phase 2a/2b/2c), and
the SQL View TML template. The step's spine (which path to take, which CLI command to run,
and the decision points) stays in `SKILL.md` — this file is what the spine links out to for
the full rule/template detail.

---

## Multi-query datasources (one datasource that JOINS several Custom SQL Queries) — hand assembly onto multiple tables

A published/`sqlproxy` datasource often joins several Custom SQL Queries server-side. GENERATE
mode and a single-view `--reconcile-table` bind it to **one** ThoughtSpot table — and every
formula referencing a column from the *other* queries is then silently filtered as
**"Unresolved Custom SQL Query alias"** while the base model still imports and *looks* clean.
Detect this and build a **multi-table model** instead.

> **Detection.** Formulas reference `(Custom SQL Query N)`-suffixed columns spanning more than
> one query, **and** the single-view reconcile leaves a large share of formulas filtered with
> "Unresolved Custom SQL Query alias". If you see that pattern, the datasource is multi-table.

> **Preferred path — parse the published datasource's `.tds` (ts-cli ≥ 0.38.0).** The physical
> tables + joins live in the datasource's `.tds` (see Step 3.5). If you can get it — download it
> (`ts tableau download {id}` → the `.tds` inside the `.tdsx`) or have the user supply the
> `.tds`/`.tdsx` — then **`ts tableau parse {file}.tds`** extracts the real tables/joins/columns/
> calcs, and `ts tableau build-model {file}.tds … ` (GENERATE mode) builds the multi-table model
> **automatically, no hand-assembly**. Use the hand-assembly procedure below only when the `.tds`
> is unavailable (you have just the `.twb` and no Tableau access — the consultant/remote case).

Procedure when the `.tds` is unavailable — hand-assembly (live-verified 2026-07-05, CPG Merch migration):
1. **Find the tables that cover the referenced columns.** Collect every physical column the
   datasource's formulas reference (strip the `(Custom SQL Query N)` suffix). Search the
   connection (`ts metadata search --name …`) for the tables that expose them; a greedy
   set-cover over candidate tables gives the minimal table set. Confirm the set + the shared
   **join key** with the user (never silently add joins — Step 3.6).
2. **Hand-build the base model TML** (`*.phase0.model.tml`): the chosen tables in
   `model_tables[]`, joined on the shared key (anchor table first), and **all** their physical
   `columns[]` as `TABLE::col`. **(M16)** Table exports come back all-`ATTRIBUTE` — classify
   the numeric metrics as `MEASURE` (name heuristic: `*_SALES`, `UNITS`, `CLICKS`, counts, etc.)
   or KPIs/axes render empty. De-dupe display names across tables (suffix the non-anchor copy).
3. **Import the base**, then add formulas with `ts tableau build-model --existing-guid {guid}`.
   The merge flow (ts-cli ≥ 0.35.0) resolves each bare column to its **real owning table**
   (not the anchor), validates qualified `[TABLE::COL]` refs against the model, cascade-drops
   dependents deterministically, and **auto-migrates the TWB parameters onto the model** before
   formula import — so no separate parameter step and no runaway `--max-retries`.

> **(M15) Absent columns are a data gap, not a translation failure.** If a referenced column
> exists in **no** available table (e.g. forecast/CI columns like `REVENUE_FORECAST`,
> `SALES_CI_*`, `ACTIVATION_COST`), the formulas that use it cannot migrate until that data is
> loaded into a warehouse table the connection exposes. Surface these explicitly (which
> columns, which formulas) in the Step 7 review and the Step 12 report — don't let them vanish
> into the filtered count.

> **(M14) Collision-renamed formulas.** When a formula's name collides with a column or
> parameter (e.g. formula `Sales` vs column `SALES`, or formula `Metric` vs parameter
> `Metric`), `build-model` renames the formula (`Formula Sales`, `Metric Selection`, …).
> Downstream liveboard tiles (Step 10) must reference the **renamed** form, and any
> coverage/gap diff must account for renames or it over-counts "missing".

## Blend-merged models (multiple datasources spanning one connected component) — hand assembly

GENERATE mode builds one model per single datasource — it cannot produce the merged,
multi-datasource model a blend relationship requires (inline cross-datasource joins,
column-conflict renaming across datasources). **Blend-aware model grouping** (requires
`blend_plan` from Step 3e):

`ts tableau parse` emits a `blend_plan`: `components` (each `{primary, members}`),
`ds_table_map` (datasource caption → ThoughtSpot table name), and `joins`
(`{with, table, on, type, cardinality}`). Use these directly — one model per
component, joins as given. The cardinality is a `MANY_TO_ONE` default; confirm it
in the Step 7 review. (TML file assembly from `blend_plan` is still done here per
the Template below — see the deferred follow-up to codify emission.) When
`blend_plan["components"]` is non-empty, datasources connected by blend relationships
produce a **single merged model** instead of separate models, assembled by hand as
described below.

The merge procedure:

1. **One model per component.** For each entry in `blend_plan["components"]`, generate a
   single model TML named after that entry's `primary` datasource's display name,
   containing:
   - All `model_tables[]` entries from every member datasource (tables + SQL views),
     resolved via `blend_plan["ds_table_map"]`
   - All `columns[]` from every member datasource (with `column_id` prefixed by the
     correct table name: `TABLE_NAME::col_name`)
   - All `formulas[]` from every member datasource
   - The joins from `blend_plan["joins"]` whose `table` belongs to this component
     (see next step)

   For multi-table datasources (internal joins within one datasource), the blend link
   column determines which table is the join anchor. Resolve the link column from Step 3e
   to its owning table via the column-to-table mapping already built in Step 3b.

2. **Apply the blend joins as given.** `blend_plan["joins"]` already covers every blend
   edge across every component — star topologies (one primary, multiple secondaries) and
   transitive chains alike, not just edges from the primary. Append each join
   (`{with, table, on, type, cardinality}`) to the `model_tables[]` entry named by the
   join's `table`, in the shape the Template below shows.

   **Cardinality heuristic:** `blend_plan` always emits `MANY_TO_ONE`. If the secondary
   datasource has no dimension-only columns (all columns are measures or aggregated), it
   is likely a fact table → override to `MANY_TO_MANY`. Surface the choice in the review
   checkpoint (Step 7) so the user can confirm or override.

3. **Datasources not in any blend** are not part of this hand-assembly procedure at all —
   they use the GENERATE-mode path above.

4. **Column name conflicts:** when merging, if two datasources define columns with the same
   display name but different semantics, disambiguate by prefixing with the datasource
   display name (e.g. `Orders Revenue` vs `Targets Revenue`). Log every rename.

The `model_tables[]` section references both regular tables (from Step 5a) and SQL
Views (from Step 5c) — both are referenced by `name` in the same way.

---

## Model TML hard rules

These apply to every model Step 5 generates. Violations cause silent data loss or import
rejections with no clear error. See `../../../shared/schemas/ts-model-conversion-invariants.md`
for full detail.

> **I1 — Every `formulas[]` entry must have a paired `columns[]` entry** with `formula_id:`
> matching the formula's `id`. An unpaired formula is silently dropped on import.
>
> **I2 — Never add `aggregation:` to a `formulas[]` entry.** It belongs only on `columns[]`
> entries. Adding it to `formulas[]` causes `FORMULA is not a valid aggregation type`.
>
> **I3 — Add `index_type: DONT_INDEX`** on every `columns[]` entry that has a `formula_id`
> and `column_type: MEASURE`.
>
> **I4 — `with:` must exactly match the target table's `name:`.** (In ThoughtSpot, `with:`
> resolves against `name`, not an `id`. If you add an `id:` field to a `model_tables` entry,
> it must equal `name:` exactly — same case, same characters — or joins break with
> `"{table} does not exist in schema"` at query time.)
>
> **I5 — `COUNTD(x)` → `unique count ( [T::x] )` formula entry, never `aggregation: COUNT_DISTINCT`.**
> Using `aggregation: COUNT_DISTINCT` silently flips `column_type` from MEASURE to ATTRIBUTE.
>
> **I6 — Connection referenced by name, never GUID.** In every table and sql_view TML block,
> use `connection: name: "{name}"` — the display name from Step 4.5. GUIDs are environment-specific
> and will fail on any ThoughtSpot instance other than the one they were exported from.
> See `../../../shared/schemas/ts-model-conversion-invariants.md` (I1–I6).

> **MEASURE vs ATTRIBUTE classification — don't under-classify, or tiles show no value.**
> A column/formula tagged `ATTRIBUTE` when it should be `MEASURE` imports fine but renders
> as a dimension — KPIs and chart y-axes come up **empty**. Classify deliberately
> (live-verified 2026-06-17):
> - **Formula is a MEASURE if it (transitively) produces a number** — it contains an aggregate
>   (`sum`/`average`/`max`/`min`/`count`/`group_aggregate`) or a ratio (`/`), **or it references
>   another MEASURE formula** by `[formula_<id>]`. The reference case is the trap: a dynamic
>   selector like `if [Param] = 'All' then [formula_Overall_Pct] else [formula_True_Pct]` has no
>   aggregate of its *own* but is a measure because every branch is one. Resolve measure-ness
>   over the formula dependency graph, not just the formula's own text.
> - **A numeric physical column defaults to MEASURE** (`INT64`/`DOUBLE`) **unless it is clearly a
>   dimension** — a key/id (`*_ID`), a calendar number (`FISCAL_*_NUM`, `*_YEAR`, `*_QUARTER`),
>   a name (`*_NAME`), or a date. Tableau's `role` is an unreliable signal here: counts like
>   `QA_FALSE`, `TP_CONNECTIONS`, `BRAND_ID_COUNT` arrive with no `measure` role and would
>   otherwise be mis-tagged ATTRIBUTE. When unsure, prefer MEASURE for a plain numeric metric.
> - **Bare (unbracketed) column references** appear in Tableau formulas (e.g.
>   `SUM(CONSISTENCY_NUMERATOR)`, not `SUM([CONSISTENCY_NUMERATOR])`). Qualify **every** physical
>   column name to `[TABLE::COL]`, not only the bracketed ones, or the formula fails with
>   *"Search did not find …"*.

## Template (hand-assembly shape)

Used directly for blend-merged models; also the structural reference for reviewing
GENERATE-mode output:

```yaml
model:
  name: "Datasource Display Name"
  properties:
    spotter_config:
      is_spotter_enabled: true  # set by Step 5.5 — Spotter is on by default
  model_tables:
  - name: TABLE_NAME
    joins:                      # only if this table has joins to others
    - with: OTHER_TABLE         # must match OTHER_TABLE's name exactly (same case)
      on: "[TABLE_NAME::JOIN_COL] = [OTHER_TABLE::JOIN_COL]"
      type: LEFT_OUTER          # INNER | LEFT_OUTER | RIGHT_OUTER | OUTER
      cardinality: ONE_TO_MANY
  - name: OTHER_TABLE
  parameters:                   # omit if no Tableau parameters to migrate
  - name: Currency
    data_type: VARCHAR
    default_value: "USD"
    list_config:
      list_choice:
      - value: USD
      - value: CAD
      - value: GBP
  formulas:                     # omit section entirely if no translatable calculated fields
  - id: formula_Formula Name    # id: "formula_" + display name
    name: Formula Name
    expr: "ThoughtSpot expression"
    properties:
      column_type: MEASURE      # or ATTRIBUTE — NO aggregation: here (I2)
  - id: formula_Unique Customers   # COUNTD(x) → unique count formula, NOT aggregation: COUNT_DISTINCT (I5)
    name: Unique Customers
    expr: "unique count ( [TABLE_NAME::customer_id] )"
    properties:
      column_type: MEASURE
  columns:
  - name: display_name
    column_id: TABLE_NAME::COLUMN_NAME
    properties:
      column_type: ATTRIBUTE    # or MEASURE
  - name: Formula Name          # paired columns[] entry for every formulas[] entry (I1)
    formula_id: formula_Formula Name   # must match the formula's id exactly
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX    # always on computed MEASURE formula columns (I3)
  - name: Unique Customers      # paired entry for the COUNTD formula (I1 + I5)
    formula_id: formula_Unique Customers
    properties:
      column_type: MEASURE
      aggregation: SUM
      index_type: DONT_INDEX
```

---

## Parameter migration — type mapping and invariants

**Type mapping:**

| Tableau `param-domain-type` | Tableau `datatype` | ThoughtSpot `data_type` | Config |
|---|---|---|---|
| `list` | `string` | `CHAR` | `list_config` with `list_choice[]` from `<member>` values. **Use `CHAR`, not `VARCHAR`** — a string **parameter** typed `VARCHAR` is rejected on import (*"Invalid parameter"*); the model-TML string parameter type is `CHAR` (live-verified 2026-06-17). This is parameters only — table *columns* still use `VARCHAR`. |
| `list` | `date` | `DATE` | `list_config` with date values (strip `#` delimiters) |
| `list` | `integer` | `INT64` | `list_config` |
| `list` | `real` | `DOUBLE` | `list_config` |
| `range` | `integer` | `INT64` | `range_config` with `range_min`, `range_max` — **unless the `<range>` has a `granularity` attribute (step size); then use `list_config`** (see note below) |
| `range` | `real` | `DOUBLE` | `range_config` — same granularity rule applies |
| `range` | `date` | `DATE` | Free-form (no `range_config` — ThoughtSpot range is numeric only) |
| `any` | any | mapped type | Free-form (no config) |
| `list` | `boolean` | `BOOL` | `list_config` with `'true'`/`'false'` values |

**Stepped range → `list_config` (not `range_config`):** A Tableau `<range>` parameter
that has a `granularity` attribute (step size) enumerates to a **small discrete choice
list** → use `list_config` (enumerate min→max by step), NOT `range_config` (which cannot
express the step). Plain ranges (no `granularity`) keep `range_config`.

> **Note:** A parameter that drives a Top-N/Bottom-N set's `count` should be `list_config`
> (discrete choices — live-verified ground truth used `list_config`; `range_config` loses
> the step). Example: `<range granularity='5' min='5' max='25'/>` → `list_choice: [5, 10,
> 15, 20, 25]`, `data_type: INT64`.

**Critical parameter invariants (from live-instance testing):**
- `range_config` values (`range_min`, `range_max`, `default_value`) **must be strings**
  in the TML — `range_min: "1"`, not `range_min: 1`. Bare integers cause
  `"Invalid YAML/JSON syntax in file"` on import. This applies even when the parameter's
  `data_type` is `INT64` or `DOUBLE`.
- When a formula references another formula inside `sum()` — e.g.
  `sum([Attrition Count])` where `Attrition Count` is `if(x='Yes') then 1 else 0` —
  ThoughtSpot rejects it with *"Function sum expects 1st argument to be Numeric"*. The
  fix is to **inline the referenced formula's expression**: write
  `sum ( if ( [x] = 'Yes' ) then 1 else 0 )` directly, not `sum ( [Attrition Count] )`.
  Apply this when any MEASURE formula references another formula column inside an
  aggregation function.
- After importing a model with parameters, **export the model** and read the
  `parameters[].id` field — ThoughtSpot assigns the UUID on import. You need this UUID
  for Step 10f (liveboard parameter chips).

---

## Formula translation rules — edge cases and special patterns

Use `tableau-formula-translation.md`.
- Convert Tableau join types: `full` → `OUTER`, `left` → `LEFT_OUTER`,
  `right` → `RIGHT_OUTER`, `inner` → `INNER`
- Write formulas in topological dependency order (Level 0 first)
- Resolve Tableau internal IDs (`[Calculation_\d+]`) to display names before translating
- **LOD expressions** (`{FIXED}`, `{INCLUDE}`, `{EXCLUDE}`) → `group_aggregate()` — see
  the LOD section in `tableau-formula-translation.md`
- **`TOTAL(SUM(x))` / percent-of-total** → `group_aggregate(..., {}, query_filters())`
- **Tableau bins** (`class='bin'`): **prompt the user** for how to create each one — there
  are two valid representations and the choice is theirs:

  ```
  This workbook has {N} bin field(s):
    - Age (bin):     binned on [Age],     size = parameter "Age Groups" (dynamic)
    - Balance (bin): binned on [Balance], size = parameter "Balance (bin) Parameter" (dynamic)

  How should each bin be created?
    F  floor() formula        — keeps it dynamic when the size is parameter-driven
    C  cohort / column set     — native BIN_BASED set, fixed bin size
    B  both
  (default: F for parameter-driven bins, C for fixed-size bins)
  ```

  - **F — `floor()` formula**: `floor([x]/size)*size` referencing the migrated parameter
    (resolve its internal name to the parameter caption) or a literal for fixed size. Stays
    dynamic if parameter-driven.
  - **C — cohort**: a separate **`cohort:` TML object** (`cohort_grouping_type: BIN_BASED`,
    `anchor_column_id`, `bins.{minimum_value,maximum_value,bin_size}`) bound to the model by
    `obj_id`. A cohort needs a fixed range — **prompt the user for `minimum_value`,
    `maximum_value`, and `bin_size`**, offering the Tableau parameter's default as the
    suggested `bin_size`. If the user can't supply the range, **fall back to a warehouse
    lookup** (`SELECT MIN/MAX`, with their authorization) — prompt first, DB lookup second.
    See the Bins section in `tableau-formula-translation.md` and
    `../../../shared/schemas/thoughtspot-sets-tml.md`. Generate as `*.cohort.tml` and import
    **after** the model.
  - **B — both**: emit the formula *and* the cohort.

  Offer the smart default per bin (F for dynamic, C for fixed) so the user can just accept.
- **Manual groups** (`class='categorical-bin'`) → a **`GROUP_BASED` cohort** (`*.cohort.tml`):
  one `groups[]` entry per `<bin>`, its `<value>` list → the condition `value[]`, the calc's
  `default` → `null_output_value`. **Classify by the calculation `class`, not the field name** —
  a field called "… (clusters)" is usually a `categorical-bin` (translatable), not k-means.
  Only true statistical clustering is untranslatable. Bind by the model `obj_id`; import after
  the model. Watch the value-format caveat (stored values must match the group's values).
  - **Cohort vs. `if/then` formula:** if each group is a **contiguous, non-overlapping range**,
    an `if … then … else if … then … else …` formula is cleaner (ThoughtSpot has **no `CASE`** —
    use the if/then/else-if chain); if groups are **arbitrary/interleaved value sets**, use the
    cohort (a range formula would misclassify). Check membership before choosing — see the
    categorical-bin section in `tableau-formula-translation.md`.
- **`Number of Records` / row-count fields** → `count([column])`. **Prompt the user for which
  column to count** (default the table's primary key); carry the same choice into dependent
  formulas (e.g. percent-of-total). Don't emit `sum(1)`.
- **Referencing one formula from another:** use the **formula id** `[formula_<id>]`, **not**
  its display name `[<Name>]` — the name form errors *"Search did not find …"*. E.g.
  `[formula_Attrition Count] / sum([T::EMPLOYEECOUNT])`. (Column refs still use `[T::COL]`.)
- **Model-level vs answer-level formulas.** A calculated field used across many worksheets
  belongs in the **model** `formulas[]` (reusable). One used by **only a single worksheet**
  can instead be an **answer-level formula** on that liveboard viz (`answer.formulas[]`,
  with a matching `answer_columns[]` entry) — keeping the model lean. Decide by reuse: shared
  → model; viz-specific → answer-level.
- **Growth / decline (Tableau `pcdf` / percent-difference / running-percent table calcs).**
  Prefer the **`growth of`** search keyword when the breakdown is over a **date**:
  `growth of [Measure] by [Date]` (this is a viz `search_query`, not a model formula). If
  there is **no date** (e.g. growth across a *sector* attribute), build explicit
  this-period vs last-period formulas and a percentage — but when a date exists, `growth of`
  is the right tool.
- **Running calculations** (`RUNNING_SUM`, etc.) → `cumulative_sum()`, etc.
- **Rank functions** → `rank()`
- **Window functions** (WINDOW_SUM, WINDOW_AVG, etc.) → `moving_sum()`, `moving_average()`,
  etc. — requires identifying the sort dimension from the worksheet shelf. See "Window /
  Moving Functions" in `tableau-formula-translation.md`.
- **Pass-through fallback** for formulas with valid Snowflake SQL but no native ThoughtSpot
  function (partitioned RANK, DENSE_RANK, WINDOW_* when sort dimension is unknown): use
  `sql_*_aggregate_op()` pass-through functions — see "Pass-Through Fallback" in
  `tableau-formula-translation.md`. Always prefer native functions first.
- **Comma-separated-list / string-concatenation technique** (FIRST/LAST/LOOKUP/PREVIOUS_VALUE used
  together to build one delimited string of a column's values — e.g. Jonathan Drummey's CSV-list /
  set-member-list dashboards): do **NOT** omit — translate the *intent* to **`LISTAGG` string
  aggregation** (`sql_string_aggregate_op ( "LISTAGG({0}, ', ') WITHIN GROUP (ORDER BY {0})" , [col] )`,
  answer-level, ⚑ flag for review per PT1) or a plain table of the values. The feeder/`Last` scaffolding
  calcs collapse into the one LISTAGG formula. See `tableau-formula-translation.md` "String aggregation".
- **Geospatial formulas** — full 13-function set (`MAKEPOINT`, `MAKELINE`, `BUFFER`, `OUTLINE`,
  `DISTANCE`, `AREA`, `LENGTH`, `INTERSECTS`, `SHAPETYPE`, `DIFFERENCE`, `INTERSECTION`,
  `SYMDIFFERENCE`, `VALIDATE`): omit the spatial formula entirely. For `MAKEPOINT(lat, lon)`,
  ensure the underlying latitude and longitude columns are migrated as individual `ATTRIBUTE`
  columns — they are useful for filtering and display even without a map visualization. For
  `DISTANCE`/`BUFFER`/`AREA`/`LENGTH`/`INTERSECTS`/`DIFFERENCE`/`INTERSECTION`/`SYMDIFFERENCE`,
  flag more prominently (the spatial computation is lost, not just the wrapper). See
  `tableau-formula-translation.md` "Geospatial Policy". Log each omission.
- **Embedded-RLS user attributes** (`USERATTRIBUTE`, `USERATTRIBUTEINCLUDES`): rejected at
  translate time — no CLI translation yet. See `tableau-formula-translation.md` "Untranslatable
  Patterns" and BL-071 for the ABAC `ts_var()` translation candidate.
- **Row-offset table calculations** (`INDEX`, `LOOKUP`, `FIRST`, `LAST`, `SIZE` —
  standalone, NOT as `WINDOW_*`/`RUNNING_*` offset args). Apply the tiered decision tree
  from `tableau-formula-translation.md` "Row-Offset Table Calculations":

  1. **Top-N filter intent** — `INDEX() <= N` or `INDEX() = N` inside an IF/CASE or set
     filter → route to the existing query-set machinery (Step 5b query-set emission).
     Use `rank ( [measure] , 'desc' )` + filter formula `[rank] <= N`.

  2. **Native rank** — `INDEX()` used for display row numbering where `ordering_type` is
     `Field` with a single date/continuous dimension → `rank ( [measure] , 'asc' )`.

  3. **Native window functions** — sort is unambiguously recoverable from the
     `<table-calc>` addressing (Step 3f) + worksheet shelf (Step 9b). Uses native
     ThoughtSpot functions (no SQL pass-through, works with all column types):
     - `INDEX()` → `rank ( sum ( [measure] ) , 'asc' )` (ranks by value, not row position — acceptable)
     - `LOOKUP(agg, N)` where N < 0 (LAG) → `moving_sum ( [measure] , abs(N) , -abs(N) , [sort_col] )`
     - `LOOKUP(agg, N)` where N > 0 (LEAD) → `moving_sum ( [measure] , -N , N , [sort_col] )`
     - `LOOKUP(agg, FIRST())` → `first_value ( sum ( [measure] ) , query_groups ( ) , { [sort_col] } )`
     - `LOOKUP(agg, LAST())` → `last_value ( sum ( [measure] ) , query_groups ( ) , { [sort_col] } )`
     - Bare `FIRST()` / `LAST()` standalone → **omit + log** (these return row *offsets* in
       Tableau, not data values — `FIRST()` = distance-to-first-row, `LAST()` = distance-to-last-row;
       no TS equivalent). Exception: `FIRST()+1` for row numbering → `rank()` approximation.
     - `SIZE()` → `sql_int_aggregate_op ( "COUNT(*) OVER ()" )` ⚑ flag PT1 (only row-offset needing pass-through)
     - All are **answer-level only** (in `answer.formulas[]`, not model `formulas[]`).
     - **SQL pass-through alternative:** when exact SQL semantics are needed (e.g.,
       partitioned LEAD/LAG with date bucketing), `sql_*_aggregate_op` works if the
       ORDER BY date expression matches the search query's date aggregate (e.g.,
       `start_of_month([date])` with `[date].monthly`) and all shelf GROUP BY columns
       are in PARTITION BY. See `tableau-formula-translation.md` "SQL pass-through alternative".

  4. **Omit + log** — addressing is ambiguous (`ordering_type='CellInPane'`, multi-dim
     `Table`, or no deterministic shelf sort). Log: `"[func]() — addressing context is
     ambiguous (ordering_type={type}); omit + log."` This is the current behavior,
     preserved for genuinely unrecoverable cases.

  **Resolving the sort column:** Use the `table_calc_addressing` / `ws_table_calc_overrides`
  maps from Step 3f. Check the worksheet override first, then fall back to the column-level
  definition. Map `ordering_type` to a sort column per the resolution table in
  `tableau-formula-translation.md` "Row-Offset Table Calculations". If resolution fails,
  fall through to Tier 4.

- **`PREVIOUS_VALUE()` (true recursion)** — still untranslatable (recursive CTE, not a
  scalar expression). Omit + log. The string-aggregation exception (FIRST/LAST/LOOKUP/
  PREVIOUS_VALUE CSV technique → LISTAGG) takes precedence and is handled above.
- **Other truly untranslatable formulas** (k-means clustering, geospatial): unchanged — omit
  from `formulas[]` entirely, omit the corresponding `columns[]` entry, and log the
  omission. See `tableau-formula-translation.md` "Untranslatable Patterns".
- Every join MUST have a non-empty `on` field. Multi-column joins are fine —
  `on: "[A::k1] = [B::k1] AND [A::k2] = [B::k2]"`.
- **Join keys must be physical columns — you cannot join on a model formula.** And a
  ThoughtSpot relationship is **binary**: a join's `on` cannot span more than two tables, so
  **multi-table join keys must be co-located into ONE relation first** (e.g. targets keyed by
  `(month, category)` where `month` derives from one table and `category` lives on another →
  build a **single SQL view spanning both** so both keys sit on one relation). If a needed
  key simply **doesn't exist** (e.g. month-of-order-date when orders only have a full
  `ORDER_DATE`), **stop and advise the user**; don't skip it or fake a formula key. Present
  the **two ways to make the column(s) physically exist**, and let the user choose:
  1. **ThoughtSpot SQL View** (a `sql_view` TML — Step 5c): write the derived/pre-aggregated
     columns into a `SELECT` over the connection (`DATE_TRUNC('month', ORDER_DATE) AS …`,
     `GROUP BY …`). Its `sql_output_columns` are physical → valid multi-column join keys. Fast,
     stays entirely in TML, no warehouse change. Use this as the foundation table for the model.
  2. **Database table/view** the user creates in the warehouse, then **adds to the connection**
     so ThoughtSpot can see it — then bind a normal Table TML to it. More setup (DB work +
     connection refresh) but governed/reusable outside this model.
  State exactly what the object needs to expose (which derived/aggregated columns, at what
  grain) so the user can act. A ThoughtSpot join can be multi-column; the keys just have to be
  real columns the relation exposes.
- **Cross-datasource formulas (Tableau data blends).** When datasources are merged into a
  single model via blend-aware grouping (Step 5b), cross-datasource references resolve
  naturally — all columns from all blended datasources exist in the same model. A formula
  like `SUM([Sales]) - SUM([OtherDS].[Target])` becomes
  `sum ( [ORDERS::Sales] ) - sum ( [TARGETS::Target] )` because both `ORDERS` and `TARGETS`
  are `model_tables[]` entries in the same model.

  **Reference resolution:** Tableau formulas reference other datasources in two formats:
  - **By federated ID:** `[federated.xxx].[column_name]` (the internal XML format)
  - **By caption:** `[Datasource Caption].[column_name]` (the display format)

  During formula translation:
  1. Detect the datasource prefix (`[federated.xxx]` or `[Caption]`) using the
     `ds_id_to_caption` mapping from Step 5b — match against both IDs and captions
  2. Strip the prefix, leaving just `[column_name]`
  3. Resolve the column name against the merged model's `columns[]` (it will exist because
     the secondary datasource's columns were included in the merge)
  4. Prefix with the correct `TABLE_NAME::` for the ThoughtSpot model reference

  **If a cross-datasource formula references a datasource NOT in the blend group** (shouldn't
  happen in well-formed workbooks, but possible in hand-edited TWBs): log a warning and omit
  the formula with a flag in the audit report.
- No `fqn` in `model_tables`
- `obj_id` is optional on fresh import — omit it unless repointing an existing model

---

## Tableau Sets → ThoughtSpot column sets (Phase 2a/2b/2c)

> **Construct distinction:** A Tableau **set** is a top-level `<group ...>` element (a named
> in/out partition on a dimension column). It is **entirely different** from a **manual group**
> (`<column><calculation class='categorical-bin'>`) — which is handled as a `GROUP_BASED`
> cohort in the formula translation rules above. Do NOT confuse the two. Sets are identified by
> the `<group>` XML element; manual groups by the calculation `class`.

**Detection — scan for top-level `<group>` elements in the datasource XML.**

For each `<group>` element, inspect its `<groupfilter>` tree and classify:

- **Static set (Phase 2a — translate):** the groupfilter tree contains **only**
  `function='union'` and `function='member'` nodes (optionally `function='level-members'`).
  There is **no** `function='end'` and **no** `function='except'`/`'intersect'`.

  Extract:
  - `caption` attribute → set name
  - The `level='[Dimension]'` attribute on the groupfilter → anchor column → its ThoughtSpot
    column **display name** (map via the model's column mapping). **If `level` is a calculated
    field** (`[Calculation_NNN]`, i.e. a set anchored on a derived dimension like
    `YEAR([Order Date])`): **resolve the internal ID to the calc's display name** via the calc
    cross-reference map (Step 3), and **ensure that calc is emitted as a model formula column**
    (an ATTRIBUTE formula, e.g. `year ( [Order Date] )`) so the set has a column to anchor on.
    Column sets **can** anchor on a formula column by its display name (live-verified 2026-06-12 —
    a set anchored on the `Sales Rep` formula column imported cleanly). Never emit the raw
    `Calculation_NNN` id as `anchor_column_id`.
  - Each child `<groupfilter function='member' member='...'/>` → a member value:
    - **HTML-decode** the value (`&quot;` → `"`, `&amp;` → `&`, `&lt;` → `<`, `&gt;` → `>`)
    - Strip Tableau's surrounding double-quotes from string values (e.g. `'"Aaron Bergman"'` → `Aaron Bergman`)
    - **Match `filter_value_type` to the anchor's type** — text → `STRING`; a numeric calc anchor
      (e.g. `year()` → integer, member `2018`) → `DOUBLE`; a date anchor → `DATE_FILTER` (per 1.5.9).
    - **`%null%` member → use the literal `{Null}` grouping value.** NULL **is** selectable in a column
      set (live-verified 2026-06-12 — the UI emits the token `{Null}` for a null selection). Emit a
      condition `operator: EQ, value: ["{Null}"], filter_value_type: STRING`.
      - **`%null%` *included*** (a `union`/member set putting NULL **in** the set) → add the `EQ {Null}`
        condition alongside the member-list condition with `combine_type: ANY` (in the list **or** null).
      - **`%null%` *excluded*** (an `except` removing NULL) → no condition needed: nulls already fall to
        the catch-all "out" bucket via `combine_non_group_values`. (Or be explicit with `NE`/no-`{Null}`.)
      No formula alternative is required for null — column sets handle it directly via `{Null}`.

- **Top-N / Bottom-N set (Phase 2b — TRANSLATE to a query set):** groupfilter tree contains
  `function='end'` (with `count` and/or `order` child/attributes). Translate to a
  `cohort_type: ADVANCED` / `COLUMN_BASED` query set in **one of two forms, chosen by `count`:**
  - **Literal `count='N'` (static N)** → the simplest form: the embedded answer's `search_query`
    is a plain **`top N [dimension] [measure]`** (or **`bottom N …`**) keyword search (anchor
    dimension first, then measure) — **no formulas, no parameter**. (The `top N` keyword
    search_query IS correct for a fixed N.)
  - **`count='[Parameters].[X]'` (dynamic, parameter-driven N)** → a **rank formula +
    parameter-filter formula**, with N read from the migrated model parameter. This is the only
    form that stays in sync with the parameter as the user changes it. (B2VBWeek11 uses this.)

  Detection (applies to both forms):
  - `end='top'` → `top N` keyword / `rank(..., 'desc')`; `end='bottom'` → `bottom N` keyword /
    `rank(..., 'asc')`.
  - The `order` child's `expression` (e.g. `SUM([measure])`) → the ranking measure (and, in the
    dynamic form, the rank's aggregation). If the ordering measure is a *derived/conditional*
    field (null-pad, IF-exclude), use the plain underlying measure and **flag** the dropped nuance.
  - `count` type selects the form: `[Parameters].[X]` → dynamic (filter references the migrated
    model param `[<alias>::<param>]`); a literal `N` → static (`top N`/`bottom N` keyword).
  - The innermost `level='[Dim]'` → anchor/return column display name.

  Extract:
  - Set `caption` → cohort name.
  - Ordering measure column display name (via the model's column mapping).
  - Parameter name (if `count` is a parameter reference) — must already exist on the model
    (migrated via the Parameters datasource → `model.parameters[]`).

  Emit one `*.cohort.tml` per Top-N/Bottom-N set — see **Query-set TML emission** below.
  Log: `"Set '<name>' is a Top-N/Bottom-N set → translated to a ThoughtSpot query set (rank
  formula + parameter-filter, Phase 2b) — flag for review."`

  Flag dropped nuances: if the ordering measure is conditional/null-padded, note the
  simplification: `"Dropped null-padding / conditional ranking — using plain <measure>; verify
  ranking matches the Tableau set."`

- **`except` of a member-list (TRANSLATABLE) — column set with `NE`:** an `except` whose excluded
  side is a `union`/`member` list (e.g. *all categories except {Furniture, %null%}*) maps to a column
  set: one group with an `operator: NE` condition per excluded member, `combine_type: ALL` ("not A AND
  not B"). `operator: NE` is a valid cohort operator (live-verified 2026-06-12). Any `%null%` in the
  excluded side needs no condition — it's already excluded by `combine_non_group_values` (catch-all).
  Anchor + member rules are the same as a static set.
- **`intersect` of two member lists (Phase 2c — TRANSLATABLE):** groupfilter tree has
  `function='intersect'` and **both** children are member/union sub-trees (no `function='end'`,
  `'filter'`, or nested set-op). Compute the **set intersection at conversion time** — the members
  common to both lists. Emit a `GROUP_BASED` column set with `operator: EQ` conditions for the
  shared members (same emission as a static set). If the intersection is empty, log and skip:
  `"Set '<name>' intersect yields zero common members — omitted."` Otherwise log:
  `"Set '<name>' is an intersect of two member lists → column set (GROUP_BASED, {N} common members, Phase 2c) — flag for review."`

- **`except` where the excluded side is a Top-N/Bottom-N (Phase 2c — TRANSLATABLE):** groupfilter
  tree has `function='except'` and the excluded child contains `function='end'`. This means "all
  dimension values EXCEPT the Top/Bottom N" — the **complement** of the Top-N set. Translate to a
  query set using an **inverted rank filter**: `[formula_rank] > N` (or `> [param]`) instead of
  `<= N`. All other emission rules are identical to Phase 2b (same rank formula, same anchor/measure,
  same static-vs-dynamic form selection). Log:
  `"Set '<name>' is 'all except Top/Bottom-N' → query set with inverted rank filter (Phase 2c) — flag for review."`

- **Condition-based set (Phase 2c — TRANSLATE to a query set):** groupfilter tree contains
  `function='filter'` (with a `quantitative` or `expression` child specifying an aggregate condition
  like `SUM([Sales]) > 10000`). This is a Tableau set created via the **Condition tab** — membership
  is determined by an aggregate condition evaluated per dimension member at query time.

  Detection:
  - `function='filter'` in the groupfilter tree (distinct from `'end'` which is Top-N).
  - The condition expression is in the `expression` attribute or a `<groupfilter function='quantitative'>`
    child with `<groupfilter function='range' from='...' to='...'/>` bounds.
  - The `level='[Dim]'` attribute → anchor column display name (same resolution as static/Top-N sets).

  Extract:
  - Set `caption` → cohort name.
  - The aggregate expression (e.g. `SUM([Sales])`) → translate through the formula translation
    reference to a ThoughtSpot formula.
  - The comparison operator and threshold(s) from the `range` element or the expression itself.

  Emit as a query set (`cohort_type: ADVANCED`, `cohort_grouping_type: COLUMN_BASED`) with:
  - One formula: the translated condition as a boolean expression
    (e.g. `sum ( [Model_1::Sales] ) > 10000`). Set `properties.column_type: ATTRIBUTE`.
  - `search_query: "[<measure>] [<dimension>] [formula_condition] [formula_condition] = true"`
  - Same `answer` structure as the Top-N query set (tables, table_paths, answer_columns, display_mode).

  Log: `"Set '<name>' is a condition-based set (condition: <expr>) → query set with condition
  formula (Phase 2c) — flag for review."`

- **Computed set operations — intersect / except of mixed types (Phase 2c — TRANSLATE to a
  multi-formula query set):** a set operation (`intersect` or `except`) where at least one side
  is a computed set (Top-N, condition-based) and the other is a member list, a computed set, or
  `level-members` (all). The query set's embedded answer can hold **multiple formulas** — compose
  each side's filter logic into the same answer and combine via the `search_query`.

  **Composition rules — build one formula per side, then combine:**

  | Side type | Formula to generate |
  |---|---|
  | Member list (`union`/`member`) | `formula_members`: `[Model_1::Dim] = 'val1' or [Model_1::Dim] = 'val2' or ...` (one `or` per member). Set `properties.column_type: ATTRIBUTE`. |
  | Top-N (`function='end'`) | `formula_rank`: `rank ( sum ( [Model_1::measure] ) , 'desc' )` + `formula_topn`: `[formula_rank] <= N` (or `<= [Model_1::param]`). Same as Phase 2b. |
  | Condition (`function='filter'`) | `formula_cond`: translated aggregate condition (e.g. `sum ( [Model_1::Sales] ) > 10000`). Set `properties.column_type: ATTRIBUTE`. |

  **Combining in `search_query`:**

  | Operation | search_query pattern |
  |---|---|
  | **Intersect** (A ∩ B) | `"[measure] [dimension] ... [formula_a] = true [formula_b] = true"` — both filters must pass (AND). |
  | **Except** (A EXCEPT B) | `"[measure] [dimension] ... [formula_a] = true [formula_b] = false"` — A passes, B fails. For Top-N exclusion, invert the rank filter: `[formula_rank] > N` instead of `<= N`, then use `= true`. |

  The `answer_columns`, `table_columns`, and `ordered_column_ids` include the dimension, the
  aggregated measure, and every formula column. The `display_mode` is `TABLE_MODE`.

  **Example — "East States ∩ Top 10 by Revenue":**
  ```yaml
  cohort:
    name: East Top Revenue
    answer:
      formulas:
      - id: formula_members
        name: member_filter
        expr: "[Model_1::State] = 'NY' or [Model_1::State] = 'CA' or [Model_1::State] = 'TX'"
        properties:
          column_type: ATTRIBUTE
      - id: formula_rank
        name: rank
        expr: "rank ( sum ( [Model_1::Revenue] ) , 'desc' )"
        properties:
          column_type: ATTRIBUTE
      - id: formula_topn
        name: topn_filter
        expr: "[formula_rank] <= 10"
      search_query: "[Revenue] [State] [formula_rank] [formula_members] = true [formula_topn] = true"
      # ... tables, table_paths, answer_columns, display_mode as per Phase 2b
    config:
      cohort_type: ADVANCED
      cohort_grouping_type: COLUMN_BASED
      anchor_column_id: State
      return_column_id: State
  ```

  Log: `"Set '<name>' is a computed set operation (<op> of <type-A> and <type-B>) → query set
  with {N} formulas (Phase 2c) — flag for review."`

  **Deeply nested set-ops:** if a side is itself a set operation (e.g. `(A ∩ B) EXCEPT C`),
  recursively decompose — flatten all member lists into one `or` formula, and each computed side
  into its own formula pair. The search_query combines all filters. Flag deeply nested cases
  prominently: `"Nested set operation — {depth} levels deep; verify the combined filter logic."`

- **Set control / dynamic set (no static members) → an interactive filter; drop the scaffolding.** A set
  whose groupfilter tree is **`level-members` only** (`ui-enumeration="all"`, `ui-builder="filter-group"`)
  has no fixed membership — it's a Tableau **Set Control** the user toggles live, usually feeding
  `IF [Set] THEN measure ELSE NULL` calcs. **That set + IF-calc machinery is Tableau scaffolding to fake
  interactive filtering — ThoughtSpot does it natively.** Translate the *intent*, not the scaffolding:
  1. **Migrate the anchor as a model formula column** if it's a calc (e.g. `01. Month` =
     `DATE(DATETRUNC('month',[Order Date]))` → `start_of_month ( [Order Date] )`) — a useful filterable
     dimension. (Same calc-anchor rule as a static set.)
  2. **Map the control to an interactive filter** on that column (Step 10). The filter *is* the selection.
  3. **Drop the `IF [Set] THEN measure ELSE NULL` referencing calcs** — do NOT migrate them as formulas.
     The measure + filter replaces them (`sum(sales)` filtered to the chosen months). Treat them like the
     "redundant pass-through formula" case: recognize the intent and collapse to the native pattern.
  4. **Do not emit a cohort.** The only case needing more than a filter is a genuine side-by-side
     **in-set vs out-set comparison** viz — handle that with a grouping attribute (a real static column set)
     or two answers; flag it specifically rather than generalising a "capability gap" onto every control.
  Log: `"Set '<name>' is a dynamic Set Control → mapped to a filter on <anchor> (anchor calc migrated as a column); its IF-[Set] scaffolding calcs were collapsed into measure+filter, not migrated."`
- **Worksheet set action (no equivalent — defer):** a `<action>` element that adds/removes
  members from a set based on viz selection. No ThoughtSpot equivalent. Log:
  `"Set action on '<set name>' has no ThoughtSpot equivalent — omitted."`

**Emit one `*.cohort.tml` per static set** — see "Column-set TML emission" below. **Emit one
`*.cohort.tml` per Top-N/Bottom-N set** — see "Query-set TML emission" below. Import
cohorts after the model (the payload order in Step 5.5 already includes `*.cohort.tml`).
**Import order for query sets: model (with parameter) → cohort** — the set's formula
references the parameter, which must exist on the model first.

> **⚠ MANDATORY — flag every set conversion for the user to review.** Set conversions are
> *semantic reinterpretations*, not literal 1:1 translations — a column set, a filter, dropped
> scaffolding, or a deferral may not behave exactly like the Tableau set. For **each** set, surface
> its outcome and ask the user to confirm it matches intent, in **both** the Step 7 review checkpoint
> and the Migration Summary (Step 10g) / Step 12 report. Show a per-set line with its kind and how it
> was handled, e.g.:
> ```
> Sets ({N}) — review each result matches intent:
>   ✓ State Set            → column set (GROUP_BASED, 3 members)         [verify membership]
>   ✓ Category Set         → column set via NE (except {Furniture})      [verify exclusion + nulls]
>   ✓ Year Set             → column set on formula column "Order Year"   [verify the calc + values]
>   ⚠ Customer Group 1     → column set (231 members)                    [large list — spot-check]
>   ⚙ 01. Month Set        → interactive filter on "Order Month"; IF-[Set] calcs collapsed to
>                            measure+filter, NOT migrated                [confirm filter ≈ the control]
>   ✓ State_TopN           → query set (rank desc by SUM gallons, N=topN param)   [verify ranking + N]
>   ✓ State_BottomN        → query set (rank asc by SUM gallons, N=topN param)    [verify ranking + N]
>   ✓ Region_Intersect     → column set (GROUP_BASED, 4 common members from intersect)   [verify membership]
>   ✓ State_NotTopN        → query set (inverted rank desc, all except top N)          [verify ranking + N]
>   ✓ HighRevCustomers     → query set (condition: SUM(Revenue) > 10000)               [verify condition]
>   ✓ East_TopRevenue     → query set (member-list ∩ Top-N, 3 formulas)              [verify combined filter]
> ```
> The reinterpreted ones (`except`→`NE`, `%null%`→`{Null}`, formula-anchor, set-control→filter,
> collapsed `IF [Set]` calcs, **Top-N/Bottom-N → query set**, **condition-based → query set**,
> **member-list intersect → computed common members**, **all-except-Top-N → inverted rank**)
> especially need a human eye — call them out explicitly, don't bury them. For Top-N/Bottom-N
> and condition-based sets, explicitly call out any dropped ranking nuances (null-padding,
> conditional measure) or simplified conditions so the user can verify the result matches intent.

### Set IN/OUT semantics — the column set IS the In/Out classification

A Tableau set returns a **boolean per row** — every dimension value is either a **member (IN)** or
not (**OUT**). The migrated `GROUP_BASED` column set already encodes exactly that: its group label is
the **In** value and the `combine_non_group_values` catch-all (`null_output_value`) is the **Out**
value. So the three ways Tableau uses In/Out all map cleanly — translate the *intent*, don't migrate
the `IF [Set]` scaffolding calcs:

- **Compare In vs Out** (e.g. "Compare In vs Out" / "Part to Whole" dashboards) → **group a measure by
  the cohort column** (`[measure] [Set]` → two groups, In vs Out). Native — this is the comparison; it
  is **not** a capability gap for a static set.
- **In/Out measure** (`IF [Set] THEN [Sales] END` / `Set Sales` / `Group 1 Sales`) → a **conditional
  aggregate**. Three equivalent forms (all live-verified 2026-06-12) — a column set **is**
  formula-referenceable as `[<cohort name>] = '<in/out label>'`:
  - **Literal translation** (mirrors Tableau's `IF [Set] THEN x END` exactly):
    `sum ( if ( [Product Category set] = 'in' ) then [Sales] else null )`.
  - **`sum_if` shorthand** (preferred, esp. for large member lists — no inlining):
    `sum_if ( [Product Category set] = 'in' , [Sales] )` (and `… = 'out'` for OUT). Family:
    `sum_if`/`average_if`/`count_if`/`unique_count_if`/`max_if`/`min_if`.
  - **Dimension + member list** (no cohort dependency; fine for small lists):
    `sum_if ( [Category] in { 'Furniture','Technology' } , [Sales] )` /
    `sum_if ( not ( [Category] in { 'Furniture','Technology' } ) , [Sales] )`.
  - ⚠️ **Pitfall (cohort-ref forms):** the cohort **name must differ from its group labels** — a
    name==label collision (e.g. cohort `Focus Categories` with group also `Focus Categories`) makes the
    formula fail with *"Search did not find …"*. Emit distinct labels (group `in`, out `out`); see the
    emission template.
- **Filter to In / Out** → filter on the cohort column = the In label (or the Out label).
- **`IF [Set] THEN [dimension]` label calcs** (`In`, `Out`, `Set Label`) → the cohort column itself
  (its two labels), or the dimension filtered to In/Out.

Pick `sum_if(...)` when In and Out are wanted as **separate measure columns** (KPIs, side-by-side, an
In/Out ratio) — reference the cohort for large lists, the dimension for small; pick **grouping by the
cohort** for an in-vs-out **breakdown** viz. Either way the pile of `IF [Set] THEN …` calcs collapses onto the one
column set / a couple of `sum_if`s — don't emit them as per-row formulas.

See `../../../shared/schemas/thoughtspot-sets-tml.md` (column set + query set) and the live-verified
worked examples `../../../shared/worked-examples/tableau/static-set-to-column-set.md` (column set) and
`../../../shared/worked-examples/tableau/topn-set-to-query-set.md` (Top-N/Bottom-N query set).

### Column-set TML emission (static set → `GROUP_BASED` cohort)

For each static set detected above, generate a `.cohort.tml` file with the following shape:

```yaml
# guid omitted on first import
cohort:
  name: "<set caption>"              # from the Tableau set's group caption attribute
  config:
    cohort_type: SIMPLE
    cohort_grouping_type: GROUP_BASED
    anchor_column_id: "<dimension display name>"  # ThoughtSpot column DISPLAY name (live-verified), from groupfilter level=
    combine_non_group_values: true          # DEFAULT CATCH-ALL: every value not matched by a group — incl. NULL — combined into one group
    null_output_value: "out"                # OUT label for the catch-all — keep DISTINCT from the cohort name (see below)
    groups:
    - name: "in"                     # IN label — MUST differ from the cohort `name` above, or formula refs
                                     # (`sum_if([<cohort>] = 'in', …)`) fail with "Search did not find" (live-verified).
                                     # Formula refs must match this label EXACTLY (case-sensitive).
      combine_type: ANY              # ANY = membership in the value list ("in set")
      conditions:
      - operator: EQ                 # PROVEN pattern (changelog 1.5.6, from a working column set):
        column_name: "<dim name>"    #   operator: EQ with a MULTI-VALUE list = "in set".
        value: ["Aaron Bergman", "Aaron Hawkins", ...]  # NOT operator: IN.
        filter_value_type: STRING    # STRING for text anchors; for a DATE anchor use DATE_FILTER
                                     # + date_filter_values instead (changelog 1.5.9).
  worksheet:                         # BINDING FIELD IS `worksheet:` NOT `model:` (live-verified — `model:` → "Table cant be empty")
    id: "<model display name>"
    name: "<model display name>"
    obj_id: "<model obj_id>"         # stable object id, e.g. TEST_SV_..._AI_CONTEXT-889a704f (from the model's exported TML header)
```

Key rules:
- `anchor_column_id` and `column_name` = the dimension's ThoughtSpot **display name** (live-verified —
  works even for a multi-table model). Map from `level='[Dimension]'` via the same column mapping as Step 5b.
- `combine_non_group_values: true` is the **default catch-all**: every value not matched by a group
  condition — including NULL — is combined into one group, labelled by `null_output_value`. This
  mirrors Tableau's in/out semantics: unmatched + NULL rows land in the catch-all ("out") bucket.
- Member values must be **HTML-decoded** and have Tableau's surrounding double-quotes stripped,
  AND converted to the column's **stored** format, not Tableau's display format (changelog 1.5.6:
  e.g. `01.Apr.15` → `2015-04-01`) — display-format values match nothing.
- Membership uses `operator: EQ` with the full value list + `combine_type: ANY` (proven in 1.5.6) —
  do **not** use `operator: IN`. For a **DATE** anchor, switch each condition to
  `filter_value_type: DATE_FILTER` + `date_filter_values` (changelog 1.5.9), not `STRING`/`value[]`.
- **`%null%` is selectable as a grouping value** — column sets DO support NULL membership (live-verified
  2026-06-12). To **include** null in the set, add a condition `operator: EQ, value: ["{Null}"],
  filter_value_type: STRING` to the group (with `combine_type: ANY` so it's "in the list OR null"). To
  **exclude** null, omit it (the catch-all already excludes it). The literal token is `{Null}`. No
  IF/THEN/ELSE formula alternative is needed for null.
- **`except` / not-in** → `operator: NE` (live-verified 2026-06-12): one `NE` condition per excluded
  value, `combine_type: ALL`. (`except {Furniture, %null%}` → `NE Furniture`; null auto-excluded.)
- Bind the set to its model via the **`worksheet:`** block (`id`/`name` = the model display name;
  `obj_id` = the model's stable object id, from the model's exported TML header) — **not** `model:`.
  Using `model:` fails import with `"Invalid save request, Table cant be empty"` (live-verified
  2026-06-12: set "Focus Categories" created on model `TEST_SV_DMSI_AI_CONTEXT` only after switching
  `model:` → `worksheet:`).
- No top-level `guid` on first import.
- File extension: `<SetName>.cohort.tml`; write to
  `/tmp/ts_tableau_mig/output/{workbook_name}/`

Write each file to `/tmp/ts_tableau_mig/output/{workbook_name}/{DatasourceName}.model.tml`.

### Query-set TML emission (Top-N/Bottom-N → ADVANCED cohort)

For each Top-N/Bottom-N set detected above, generate a `.cohort.tml` file. There are **two
forms** (see classification above): the **dynamic** form (parameter-driven N — a rank formula +
parameter-filter formula, live-verified 2026-06-12 against se-thoughtspot, model
`TEST_SV_DMSI_AI_CONTEXT`), and the simpler **static** form (fixed N — a `top N`/`bottom N`
keyword search, no formulas) shown after it. Cross-refs:
`../../../shared/schemas/thoughtspot-sets-tml.md` (query set section) +
`../../../shared/worked-examples/tableau/topn-set-to-query-set.md`.

**Dynamic form (parameter-driven N — `count='[Parameters].[X]'`):**

```yaml
# guid omitted on first import
cohort:
  name: "<set caption>"
  answer:
    tables:
    - id: "<model display name>"
      name: "<model display name>"
      obj_id: "<model obj_id>"
    table_paths:
    - id: "<model display name>_1"          # self-path alias used by the formulas
      table: "<model display name>"
    formulas:
    - id: formula_filter
      name: filter
      expr: "[formula_rank] <= [<model display name>_1::<paramName>] "
      was_auto_generated: false
    - id: formula_rank
      name: rank
      expr: "rank ( sum ( [<model display name>_1::<measure col>] ) , 'desc' )"   # 'asc' for Bottom-N
      properties:
        column_type: ATTRIBUTE
      was_auto_generated: false
    search_query: "[<measure>] [<dimension>] [formula_rank] [formula_filter] = true"
    answer_columns:
    - name: <dimension display name>
    - name: "<aggregated measure display name>"   # e.g. "Total gallons" for a SUM measure
    - name: rank
    table:
      table_columns:
      - column_id: <dimension display name>
        show_headline: false
      - column_id: "<aggregated measure display name>"
        show_headline: false
      - column_id: rank
        show_headline: false
      ordered_column_ids:
      - <dimension display name>
      - rank
      - "<aggregated measure display name>"
      client_state: ""
    display_mode: TABLE_MODE
  worksheet:
    id: "<model display name>"
    name: "<model display name>"
    obj_id: "<model obj_id>"
  config:
    cohort_type: ADVANCED
    anchor_column_id: <dimension display name>
    return_column_id: <dimension display name>
    cohort_grouping_type: COLUMN_BASED
    hide_excluded_query_values: true
    group_excluded_query_values: "Excluded values"
    pass_thru_filter:
      accept_all: false
```

Key rules:
- **Parameter prerequisite (dynamic form)** — the `count` parameter MUST be on the model first
  (already migrated via the Parameters datasource → `model.parameters[]`). The set's
  `formula_filter` references it as `[<model display name>_1::<paramName>]`. **Import order:
  model (with param) → cohort.** (The static form below has no parameter dependency.)
- **Top vs Bottom** — `end='top'` → `rank(sum(measure), 'desc')`; `end='bottom'` →
  `rank(sum(measure), 'asc')` (user-confirmed 2026-06-12).
- Rank aggregation = the set's `order` expression aggregation (SUM here). Translate the
  ordering measure to its TS column; if it's a derived/conditional field, use the plain
  measure + **flag** the dropped nuance for review.
- `table_paths` alias = `<model display name>_1`; all `formulas[].expr` column refs use
  `[<alias>::<col>]`. `answer_columns`, `config`, and `table.*` use **display names** (no alias).
- `answer_columns` measure entry uses the **aggregated display name** ThoughtSpot generates
  (`Total <measure>` for a SUM measure, e.g. `Total gallons`).
- A **stepped range parameter** (Tableau `<range granularity='5' min='5' max='25'/>`) maps
  to `list_config` (enumerate min→max by step: `[5,10,15,20,25]`), NOT `range_config`. See
  the Parameter migration section for this rule.
- Bind via `worksheet:` (id/name/obj_id) — NOT `model:` (same rule as column sets).
- No top-level `guid` on first import.
- File: `<SetName>.cohort.tml` → `/tmp/ts_tableau_mig/output/{workbook_name}/`.

**Static form (fixed N — literal `count`):** no formulas, no parameter; the `top N`/`bottom N`
keyword `search_query` defines membership. Use this when the Tableau set's `count` is a literal.

```yaml
# guid omitted on first import
cohort:
  name: "<set caption>"
  answer:
    tables:
    - id: "<model display name>"
      name: "<model display name>"
      obj_id: "<model obj_id>"
    search_query: "top 10 [<dimension>] [<measure>]"   # anchor dimension FIRST, then measure; "bottom 10 …" for Bottom-N; N is the literal count
    answer_columns:
    - name: <dimension display name>
    - name: "<aggregated measure display name>"         # e.g. "Total gallons"
    table:
      table_columns:
      - column_id: <dimension display name>
        show_headline: false
      - column_id: "<aggregated measure display name>"
        show_headline: false
      ordered_column_ids:
      - <dimension display name>
      - "<aggregated measure display name>"
      client_state: ""
    display_mode: TABLE_MODE
  worksheet:
    id: "<model display name>"
    name: "<model display name>"
    obj_id: "<model obj_id>"
  config:
    cohort_type: ADVANCED
    anchor_column_id: <dimension display name>
    return_column_id: <dimension display name>
    cohort_grouping_type: COLUMN_BASED
    hide_excluded_query_values: false       # false = show a remainder bucket (label below); true = hide non-members
    group_excluded_query_values: "Others"   # label for the non-member remainder bucket
    pass_thru_filter:
      accept_all: false
```
> Live-verified 2026-06-12 against se-thoughtspot (set "Static Top 10" on model
> `TEST_SV_DMSI_AI_CONTEXT`). The `top N [dimension] [measure]` keyword `search_query` (**anchor
> dimension first, then measure**) is the correct representation for a fixed-N query set — no
> formulas, no parameter. `hide_excluded_query_values` is a display choice: `false` keeps a
> remainder bucket (labelled by `group_excluded_query_values`, e.g. "Others"); `true` hides
> non-members.

---

## SQL View TML template (Step 5c)

```yaml
sql_view:
  name: "Datasource Custom SQL"
  connection:
    name: "Connection Display Name"
  sql_query: |
    SELECT col1, col2, col3
    FROM catalog.schema.table_name
    WHERE condition = 'value'
  sql_view_columns:
  - name: COL1
    sql_output_column: col1
    data_type: VARCHAR
    properties:
      column_type: ATTRIBUTE
  - name: COL2
    sql_output_column: col2
    data_type: DOUBLE
    properties:
      column_type: MEASURE
      aggregation: SUM
```
