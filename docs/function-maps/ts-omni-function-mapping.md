<!-- currency: omni — 2026-10 (Omni docs; apache/ossie @ 2491533 converters/omni) -->
# Omni Analytics → ThoughtSpot function mapping

**Status:** research draft (2026-10-06) — not yet reviewed, not live-verified on a ThoughtSpot
cluster in this pass (except `round`, and the `day_number_of_week` / `diff_months` / `diff_years` / string-case semantics, settled by 2026-10-06 probes on se-thoughtspot); revised
2026-10-06 after an independent review; every ThoughtSpot target is taken from the repo's
verified references, not invented · **Coverage:** 216/216 functions, operators and constructs across Omni's three
expression surfaces — **workbook table calculations** (135), the **modelling layer** (50) and
the **filter syntax** used by filtered measures, LoD fields and topics (31) — as documented on
docs.omni.co, read 2026-10-06 · **Classifications:** `direct` (native ThoughtSpot formula
equivalent, possibly a documented composition of native functions) · `passthrough` (requires a
ThoughtSpot `sql_*_op` pass-through — warehouse-dialect-specific, bypasses ThoughtSpot's query
planning) · `unmappable` (no faithful ThoughtSpot formula; the converter raises an issue and
preserves the source) · `structural` (modelling layer only — handled by Model/Table/connection
structure, not by a formula) · **TS ground truth:**
[`thoughtspot-formula-patterns.md`](../../agents/shared/schemas/thoughtspot-formula-patterns.md)
(the *formula reference*) and
[`ts-snowflake-formula-translation.md`](../../agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)
(the *Snowflake formula mapping*), plus the live-verified findings recorded in the
[Ossie function map](../ossie/ts-ossie-function-mapping.md). They override any other
description of ThoughtSpot's formula language, including this document. · **Upstream
converter:** apache/ossie `converters/omni` @ `2491533`, cited as `omni_to_ossie.py:N`,
`_common.py:N`, `README.md:N` (read only; not executed).

Omni has three places an expression lives, and they behave very differently:

1. **Table calculations** — Excel/Google-Sheets-style formulas (`=SUM(B:B)`, `=B1/B0`;
   the [Sheets map](ts-sheets-function-mapping.md) records where Sheets departs from Excel)
   evaluated over a single query's **result grid**, after the query runs
   ([docs](https://docs.omni.co/analyze-explore/calculations/index.md): "performed post query
   processing on the result set"). Function inventory:
   [Supported table calculation functions](https://docs.omni.co/analyze-explore/calculations/all.md)
   and its per-category pages. These live in workbooks, not in the model files, so **the
   upstream Ossie converter never sees them.**
2. **The modelling layer** — YAML views whose dimensions and measures carry warehouse `sql:`,
   an `aggregate_type`, filtered measures, level-of-detail blocks and Omni-specific generators
   (timeframes, durations, bins, groups, templated filters). This is the LookML-shaped surface,
   and the repo's [Looker mapping](../../agents/shared/mappings/looker/lookml-to-ts-formula-translation.md)
   decisions are reused for it.
3. **Filter syntax** — the operator vocabulary (`is:`, `greater_than:`, `time_for_duration:` …)
   used inside measure `filters:`, LoD `filters:` and topic filters
   ([Filter operators](https://docs.omni.co/modeling/filters/operators/index.md)). It is the
   predicate language of a filtered measure, so it carries expression semantics.

Field `format:` (named formats, Excel-style format strings) is display-only and is **not
counted** — it changes how a value renders, never the value. The Omni AI context fields
(`ai_context`, `synonyms`, `sample_values`) are metadata, not expressions.

---

## How to read the tables

Every ThoughtSpot cell is written in canonical formula syntax: column references are
`[TABLE::Column]`, a formula is referenced by id as `[formula_<Name>]`, and the spaces around
parentheses and commas are the canonical form (`concat ( [a] , [b] )`). In the table-calculation
part, `[B]` stands for **the ThoughtSpot formula of grid column B** — a measure such as
`sum ( [T::x] )` or an attribute such as `[T::d]` — and `[T::x]` is the column underneath it.

- **E1 — one row per construct.** Every function on Omni's supported-function pages, every
  operator in its operator table, every documented reference form, every `aggregate_type`,
  every view/dimension/measure parameter that changes a value, and every filter operator gets
  exactly one row. **Argument vocabularies** (DATEDIF units, `timeframes` names, `duration`
  intervals, relative-date strings like `7 days ago`, `TEXT` format tokens) are arguments, not
  constructs; they are in sub-tables marked *(not counted)*.
- **E2 — `direct` may be a composition.** ThoughtSpot has no `EOMONTH`, `WEEKDAY`, `ROUNDUP` or
  positional `REPLACE`, but each is exactly expressible in native functions; those rows are
  `direct` and the cell gives the composition (same rule as the Ossie map's E2).
- **E3 — a `direct` row whose argument space is only partly covered names its fallback**, with
  its `sql_*_op` variant. A converter branches on the argument (a DATEDIF unit, a grid column's
  aggregate, a pivot direction), so the fallback is not hypothetical.
- **E4 — every `passthrough` row names its variant** (`sql_string_op`, `sql_int_op`,
  `sql_double_op`, `sql_bool_op`, `sql_date_op`, `sql_date_time_op`, and the
  `sql_string_aggregate_op` / `sql_int_aggregate_op` / `sql_double_aggregate_op` /
  `sql_date_time_aggregate_op` aggregate forms). Templates are written in **Snowflake**
  dialect; Omni SQL is whatever the connection's warehouse speaks (`README.md:139-143`), so the
  template must be re-derived per dialect.
- **E5 — table calculations are grid functions; the mapping depends on the reference shape.**
  A table calc sees only the result grid. Three reference shapes, three targets:
  1. **Current-row cell** (`B1` written on row 1) → the referenced column's own formula, `[B]`.
  2. **Whole-column range** (`B:B`) → an aggregate *over the query's grouped rows*, i.e. SQL
     `AGG2(AGG1(x)) OVER ()`. The native form
     `group_aggregate ( AGG ( [T::x] ) , { } , query_filters ( ) )` re-aggregates **base
     rows**, so it is exact **only** when `AGG2∘AGG1` collapses to one aggregate over base rows:
     SUM of a SUM or COUNT measure, MIN of a MIN, MAX of a MAX, or MIN/MAX of a dimension
     column. Every other combination — AVERAGE of a SUM, MEDIAN, STDEV, COUNT of grid rows,
     MAX of a SUM — is a pass-through carrying the window verbatim:
     `sql_double_aggregate_op ( "AVG(SUM({0})) OVER ()" , [T::x] )`. Rows are classified on the
     common case (the grid column is a SUM measure) and name the native fast path.
     **That `OVER ()` family is contradicted by
     [formula reference lines 702-722](../../agents/shared/schemas/thoughtspot-formula-patterns.md#window-functions-inside-sql__aggregate_op)
     until probed.** That section, live-verified on se-thoughtspot (2026-06-15), says a window
     inside `sql_*_aggregate_op` in an aggregated search must (1) `ORDER BY` the GROUP BY
     expression exactly as bucketed (`start_of_month ( [d] )` for `[d].monthly`) and (2) carry
     **every** other search dimension in `PARTITION BY`, or Snowflake rejects the unmatched
     GROUP BY column. An `OVER ()` with a dimension in the search violates rule 2, and
     partitioning by every dimension would shrink each window to a single grid row, destroying
     the whole-grid semantics. The one candidate shape that satisfies both rules is a
     **single-dimension** grid with that dimension moved into the window's `ORDER BY` and a full
     frame — `AVG(SUM({0})) OVER (ORDER BY {1} ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED
     FOLLOWING)` with `{1}` = the bucketed dimension — and even that is unprobed. The rows stay
     classified `passthrough` because no other target exists, but none is usable until a probe
     settles it. Separately, a **row-level grid** (one grid row per base row) needs no window at
     all: there the Excel map's base-row compositions apply directly, and each affected row names
     them.
     **Native fast paths via a named inner formula** (formula reference lines 432-441: a group
     function cannot nest inside another, so the inner aggregate is its own formula referenced by
     name) are offered, unverified, only where they survive **base-row replication**: the inner
     `group_aggregate ( sum ( [T::x] ) , query_groups ( ) , query_filters ( ) )` is a row-level
     scalar copied onto every base row of its group, so an outer `max` / `min` is unaffected but
     an outer `average` / `median` / `stddev` weights each grid value by its group's row count.
     So MAX/MIN of a column of sums get a fast path, as do COUNT/COUNTA on a one-dimension grid
     (`unique count` of the dimension); AVERAGE, MEDIAN, STDEV and VAR do not.
  3. **Ordered references** (`B0` previous row, relative ranges `B1:B7`, `ROW()`, `INDEX`)
     depend on the grid's **sort order**, which belongs to the Omni query, not the calc. The
     converter takes the query's sort column as the ThoughtSpot order argument; it must be a
     physical column (Ossie map E6), else the row raises an issue. In a **pass-through** window
     (`INDEX`, `ROW`, `PIVOTINDEX`, `PIVOTOFFSET`) the `ORDER BY` argument is instead the
     search's **bucketed** GROUP BY expression — `start_of_month ( [T::d] )` for `[d].monthly`,
     never the raw column — per the formula reference's live-verified rule (lines 702-722).
- **E6 — grain coupling is the native case here, not the failure case.** The Ossie map's E13
  (a ThoughtSpot window cannot declare `PARTITION BY`; the partition is completed from the
  search) made SQL `OVER` clauses lossy. Omni table calcs have the *same* property — they are
  defined relative to whatever query they sit in — so ThoughtSpot's query-context functions
  are **faithful when the ThoughtSpot search carries the Omni query's dimensions**. One known
  divergence: for an *unpivoted* multi-dimension query, Omni's `B0` reads the previous grid row
  even across a group boundary, while ThoughtSpot partitions by the non-order dimensions. For a
  *pivoted* query the two agree (Omni offsets run down each pivot column; ThoughtSpot puts the
  pivot dimension in the partition). Omni itself warns that range calcs "depend on the shape of
  a specific result set" and may not be promotable to the shared model (calculations index,
  "Promote table calculations").
- **E7 — row-limit pushdown.** Omni evaluates a range calc on the *returned* rows after the
  row limit unless "Apply before row limit" / `calcs_default_pushdown` is on. ThoughtSpot's
  `group_aggregate` and window functions evaluate over the full result, i.e. **pushdown-on**.
  A pushdown-off Omni calc over a truncated result has no ThoughtSpot equivalent and the
  converter records the difference.
- **E8 — literals.** Omni calc strings take **double quotes only** ("single quotes are not
  valid"); ThoughtSpot string literals are emitted single-quoted. Omni booleans must be
  upper-case `TRUE`/`FALSE`; ThoughtSpot uses `true`/`false`. Date strings (`"2022-12-22"`)
  are always wrapped: `to_date ( '2022-12-22' , 'yyyy-MM-dd' )` (a bare date parses as
  subtraction — formula reference, Date Functions).
- **E9 — model references become column or formula references, never inlined text.**
  `${view.field}` resolves to `[VIEW::Column]` for a physical column and to the id-reference
  `[formula_<Name>]` for a modelled field. The Looker mapping's §1 rule ("every cross-field
  reference must be inlined") predates the repo's id-reference invariant (root `CLAUDE.md`,
  Critical TML invariants: id-refs resolve on first import and are order-independent), which
  wins.

---

## Coverage summary

| Section | Rows | `direct` | `passthrough` | `unmappable` | `structural` |
|---|--:|--:|--:|--:|--:|
| **Part 1 — table calculations** | | | | | |
| AI functions | 5 | 0 | 5 | 0 | — |
| Date and time functions | 15 | 13 | 2 | 0 | — |
| Logic functions | 13 | 9 | 4 | 0 | — |
| Math and number functions | 50 | 23 | 27 | 0 | — |
| Position functions | 10 | 2 | 4 | 4 | — |
| Text functions | 19 | 9 | 10 | 0 | — |
| Operators, literals and references | 23 | 22 | 0 | 1 | — |
| *Part 1 subtotal* | *135* | *78* | *52* | *5* | — |
| **Part 2 — modelling layer** | | | | | |
| Measure `aggregate_type` | 13 | 10 | 2 | 1 | 0 |
| Measure constructs | 8 | 8 | 0 | 0 | 0 |
| Dimension constructs | 19 | 10 | 1 | 4 | 4 |
| View, relationship and topic constructs | 10 | 0 | 0 | 2 | 8 |
| *Part 2 subtotal* | *50* | *28* | *3* | *7* | *12* |
| **Part 3 — filter syntax** | 31 | 24 | 4 | 3 | — |
| **Total** | **216** | **130** | **59** | **15** | **12** |

60% of the 216 constructs (64% of the 204 that are expressions rather than model structure) are
expressible in ThoughtSpot's native formula language. *(Recounted 2026-10-06 after the
case-sensitivity probe: EXACT, FIND and the `contains` / `starts_with` / `ends_with` /
`sql_like` filters moved to `passthrough`; SEARCH and the `case_insensitive` modifier moved to
`direct` — BL-333.)* The split is very uneven by surface. The
**modelling layer and filter syntax are mostly native** (52 of 69 expression rows,
75%) because Omni's model is LookML-shaped and ThoughtSpot's `*_if` and `group_aggregate`
families cover filtered measures and Omni's `level_of_detail` almost one-to-one. **Table
calculations are the weak surface** (58%): the `passthrough` set concentrates in **grid
aggregates that are not distributive** (AVERAGE/MEDIAN/STDEV/COUNT over a column of sums —
E5), **case-sensitive comparison and whitespace text handling** (native string comparison
lowercases both sides; no native `upper`/`lower`/`trim`/`replace`), the **warehouse AI functions**, and **bitwise** arithmetic. The 15 `unmappable` rows are: **five** table-calc
constructs — positional and cross-query lookup (`MATCH`, `PIVOT`, `VLOOKUP`, `XLOOKUP`,
cross-tab references); **seven** modelling constructs — `percentile_distinct_on`,
`dynamic_top_n`, three templated-filter forms (the `.filter` block, `range_start`/`range_end`,
`in_query`/`is_selected`), topic `default_filters` and topic `always_having_*`; and **three**
filter operators that filter by another query (`field_name_in_query`,
`field_name_not_in_query`) or by the query's own date filter (`date_offset_from_query`).
**The 26 grid-aggregate pass-throughs are additionally contradicted by the formula
reference's window rule (E5) until probed**, so the usable share of Part 1 today is lower than
its `passthrough` count suggests.

---

# Part 1 — Table calculations

Source: [Supported table calculation functions](https://docs.omni.co/analyze-explore/calculations/all.md)
(the index — 112 functions in six categories) and the per-category pages it links. Where Omni
documents a deviation from Google Sheets, the Omni behaviour is what is mapped. Where Omni is
silent, Sheets semantics come from the [Sheets map](ts-sheets-function-mapping.md) for the
functions it rows, and from the [Excel map](ts-excel-function-mapping.md) for every other
function (which the Sheets map's reconciliation confirms take their Excel row).

## AI functions

Source: [AI functions](https://docs.omni.co/analyze-explore/calculations/ai.md) (beta;
Snowflake, Databricks and BigQuery only). Omni "translates [them] to native SQL functions in
your warehouse", so a pass-through is the faithful target by construction. All five are
row-level, so attribute-typed scalar variants; each is a warehouse AI call **per row of the
result**, so the cost caveat travels with the formula.

| Omni | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `AI_CLASSIFY(text, c1, c2, ...)` | passthrough | `sql_string_op ( "CAST(SNOWFLAKE.CORTEX.CLASSIFY_TEXT({0}, ARRAY_CONSTRUCT('positive','negative','neutral'))['label'] AS VARCHAR)" , [T::text] )` | **Variant: `sql_string_op`.** Omni names `CLASSIFY_TEXT` as the Snowflake equivalent. The categories are literals baked into the template. JSON access uses **bracket notation, never `:`** — the colon path form is rejected inside a pass-through (formula reference, "JSON / VARIANT path access"); `CAST` rather than `::` for the same reason. |
| `AI_COMPLETE(prompt)` | passthrough | `sql_string_op ( "SNOWFLAKE.CORTEX.COMPLETE('<model>', {0})" , [T::prompt] )` | **Variant: `sql_string_op`.** Omni lets the warehouse pick the model; Snowflake's `COMPLETE` requires one, so the converter must choose and record it. |
| `AI_EXTRACT(text, labels)` | passthrough | `sql_string_op ( "ai_extract({0}, array('name','city'))" , [T::text] )` | **Variant: `sql_string_op`.** Omni documents this as **not available on Snowflake**; the template shown is Databricks. Returns JSON on Databricks and free text on BigQuery per Omni, so the result type differs by warehouse. |
| `AI_SENTIMENT(text)` | passthrough | `sql_double_op ( "SNOWFLAKE.CORTEX.SENTIMENT({0})" , [T::text] )` | **Variant: `sql_double_op`** — a numeric score, not a string. |
| `AI_SUMMARIZE(text)` | passthrough | `sql_string_op ( "SNOWFLAKE.CORTEX.SUMMARIZE({0})" , [T::text] )` | **Variant: `sql_string_op`.** |

## Date and time functions

Source: [date & time functions](https://docs.omni.co/analyze-explore/calculations/date-time.md).

| Omni | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `DATE(year, month, day)` | direct | `add_days ( add_months ( to_date ( concat ( to_string ( [y] ) , '-01-01' ) , 'yyyy-MM-dd' ) , [m] - 1 ) , [d] - 1 )` | No native date constructor. The composition builds 1 January of the year and offsets it, which also reproduces the spreadsheet behaviour for out-of-range parts (`DATE(2022, 13, 1)` = 2023-01-01). An all-literal call folds to `to_date ( '2022-12-22' , 'yyyy-MM-dd' )`. |
| `DATEDIF(start_date, end_date, "unit")` | direct | per-unit — see the unit table below | **Argument order is reversed:** `diff_*` take `( [end] , [start] )`. Unit compositions are the [Excel map](ts-excel-function-mapping.md)'s `DATEDIF` row (Omni follows Sheets semantics, and Sheets' `DATEDIF` takes the Excel row unchanged — same units, checked against Google's page in the [Sheets map](ts-sheets-function-mapping.md#same-as-the-excel-map-reconciliation)): `D`, `M`, `Y` and `YM` are native; `MD`/`YD` fall back to `sql_int_op` ([E3](#how-to-read-the-tables)). The `"M"`/`"Y"` day-of-month correction is **confirmed necessary** by the 2026-10-06 probe: `diff_months` counts month boundaries crossed and `diff_years` is a calendar-year difference (formula reference). |
| `DAY(date)` | direct | `day ( [d] )` | |
| `DAYS(end_date, start_date)` | direct | `diff_days ( [end] , [start] )` | Omni's `DAYS` is already end-first, so — unlike `DATEDIF` — no reordering. |
| `EOMONTH(date_value, offset_months)` | direct | `add_days ( add_months ( start_of_month ( [d] ) , [n] + 1 ) , -1 )` | No native end-of-month; first of month *n+1* minus one day is exact. |
| `HOUR(time)` | direct | `hour_of_day ( [t] )` | Not `hour` — a bare `hour` does not exist (Power BI map, BL-171). A time-only *string* argument (`HOUR("15:30")`) has no native parse; such literals are folded at conversion time. |
| `MINUTE(time)` | passthrough | `sql_int_op ( "MINUTE({0})" , [t] )` | **Variant: `sql_int_op`.** No native minute extractor (live-verified 2026-07-30, Power BI map). |
| `MONTH(date)` | direct | `month_number ( [d] )` | **Not `month`**, which returns the month *name*. |
| `NETWORKDAYS(start_date, end_date)` | direct | `5 * floor ( ( diff_days ( [e] , [s] ) + 1 ) / 7 ) + mod ( diff_days ( [e] , [s] ) + 1 , 7 ) - greatest ( 0 , least ( day_number_of_week ( [s] ) + mod ( diff_days ( [e] , [s] ) + 1 , 7 ) - 1 , 7 ) - greatest ( day_number_of_week ( [s] ) , 6 ) + 1 )` | The [Excel map](ts-excel-function-mapping.md)'s `NETWORKDAYS` composition, reused with its status (hand-checked across all start weekdays, **not** import-probed; covers `end ≥ start`; rests on `day_number_of_week` being fixed at 1 = Monday, which is now live-verified — se-thoughtspot 2026-10-06, Excel gap G11 settled; the weekend arithmetic assumes the Model calendar's Monday week start (the default — Gregorian, Monday — when the Model sets no other calendar; ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere). A simpler live-verified alternative is the Excel map's `NETWORKDAYS.INTL` per-weekday counting form with weekend code 1 (se-thoughtspot, 2026-10-06 — [probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)). Omni has no `holidays` argument, so the Excel map's holiday caveat does not arise. The repo's [business-days recipe](../../agents/cli/ts-recipe-formula-business-days-snowflake/SKILL.md) UDF, `sql_int_op ( "<db>.<schema>.get_business_days_clamped({0},{1}, TRUE)" , [s] , [e] )`, is the pass-through fallback ([E3](#how-to-read-the-tables)). |
| `NOW()` | direct | `now ( )` | |
| `SECOND(time)` | passthrough | `sql_int_op ( "SECOND({0})" , [t] )` | **Variant: `sql_int_op`.** As `MINUTE`. |
| `TODAY()` | direct | `today ( )` | |
| `WEEKDAY(date, [return_type])` | direct | `mod ( day_number_of_week ( [d] ) , 7 ) + 1` | **Base shift is mandatory.** Omni's default numbers 1 = Sunday; ThoughtSpot's `day_number_of_week` numbers 1 = Monday … 7 = Sunday — **fixed, live-verified** (se-thoughtspot, 2026-10-06: compiles to `(MOD((DATEDIFF(day, DATE '1970-01-01', d) + 3), 7) + 1)`, independent of the warehouse's `WEEK_START`; formula reference — settles Excel gap G11). `mod ( … , 7 ) + 1` maps Sunday 7 → 1 and Monday 1 → 2. `return_type` 2 (Monday = 1) is `day_number_of_week ( [d] )` unchanged; 3 (Monday = 0) is `day_number_of_week ( [d] ) - 1`. The mapping assumes the Model calendar's Monday week start (the default — Gregorian, Monday — when the Model sets no other calendar; ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere. |
| `WEEKNUM(date, [type])` | direct | `floor ( ( day_number_of_year ( [d] ) - 1 + mod ( day_number_of_week ( start_of_year ( [d] ) ) , 7 ) ) / 7 ) + 1` | The [Excel map](ts-excel-function-mapping.md)'s `WEEKNUM` composition for type 1 (Sunday start, the week containing 1 January is week 1 — Omni's default). Type 2 (Monday start) replaces the offset with `day_number_of_week ( start_of_year ( [d] ) ) - 1`. `week_number_of_year` is deliberately not used: its compiled SQL uses ISO-style Thursday logic (`week_number_of_year(2026-01-04)` = 1, live probe 2026-10-06), which is neither type 1 nor type 2. The `day_number_of_week` fixed Monday base the composition rests on is now **live-verified** (2026-10-06, Excel gap G11 settled); the composition itself is still *not* import-probed. The composition assumes the Model calendar's Monday week start (the default — Gregorian, Monday — when the Model sets no other calendar; ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere; an Omni `week_start_day` / fiscal setting corresponds to the Model's calendar, not to a formula change — see the `week_start_day` row. |
| `YEAR(date)` | direct | `year ( [d] )` | |

### `DATEDIF` units *(not counted — arguments)*

| Unit | ThoughtSpot | Class |
|---|---|---|
| `"D"` | `diff_days ( [end] , [start] )` | direct |
| `"M"` | `diff_months ( [end] , [start] ) - if ( day ( [end] ) < day ( [start] ) ) then 1 else 0` | direct — complete months, per the Excel map. The correction is **confirmed necessary**: `diff_months` compiles to `DATEDIFF(month, epoch, end) - DATEDIFF(month, epoch, start)`, i.e. month *boundaries* (live probe, se-thoughtspot, 2026-10-06: Jan31→Feb1 = 1, Jan31→Feb28 = 1, Jan20→Mar15 = 2; Excel gap G12 settled). The composition itself is not import-probed. |
| `"Y"` | `floor ( [formula_Months] / 12 )` (`[formula_Months]` = the `"M"` formula) | direct — as the Excel map. Native `diff_years` is **not** a substitute: it is `EXTRACT(YEAR FROM end) - EXTRACT(YEAR FROM start)` (live probe 2026-10-06: Dec31→Jan1 = 1, 2025-07-01→2026-06-30 = 1). `"YM"` is `mod ( [formula_Months] , 12 )`. |
| `"YM"` | `mod ( [formula_Months] , 12 )` | direct — as the Excel map. |
| `"MD"` / `"YD"` | `sql_int_op ( "<dialect expression>" , [start] , [end] )` | passthrough — remainder units with no clean native form (Microsoft itself documents `"MD"` as unreliable — Excel map). |

## Logic functions

Source: [logic functions](https://docs.omni.co/analyze-explore/calculations/logic.md).

| Omni | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `AND(condition1, condition2, ...)` | direct | `( [c1] ) and ( [c2] )` | Function form becomes the infix keyword; each operand parenthesised (Power BI translator does the same, `functions.py` `_and_repl`). |
| `BITAND(value1, value2)` | passthrough | `sql_int_op ( "BITAND({0}, {1})" , [a] , [b] )` | **Variant: `sql_int_op`.** ThoughtSpot has no bitwise operators. |
| `BITOR(value1, value2)` | passthrough | `sql_int_op ( "BITOR({0}, {1})" , [a] , [b] )` | **Variant: `sql_int_op`.** |
| `BITRSHIFT(value, shift_amount)` | passthrough | `sql_int_op ( "BITSHIFTRIGHT({0}, {1})" , [a] , [n] )` | **Variant: `sql_int_op`.** Snowflake spells it `BITSHIFTRIGHT`; the name is dialect-specific. |
| `BITXOR(value1, value2)` | passthrough | `sql_int_op ( "BITXOR({0}, {1})" , [a] , [b] )` | **Variant: `sql_int_op`.** |
| `IF(condition, true_value, false_value)` | direct | `if ( [cond] ) then [a] else [b]` | Parentheses around the condition are mandatory for import. |
| `IFERROR(value, [value_if_error])` | direct | `ifnull ( [v] , [alt] )` | **Approximate — flagged.** Omni documents IFERROR as firing when the formula "returns null due to an error" (Omni errors surface as null, e.g. `1/0`). ThoughtSpot cannot distinguish an error-null from a genuine null, so `ifnull` also replaces genuine nulls. With no second argument Omni returns blank, so the call reduces to `[v]`. |
| `IFNA(value, default_value)` | direct | `ifnull ( [v] , [default] )` | Omni defines IFNA as "returns the specified value if the formula returns null" — exactly `ifnull`. |
| `IFS(c1, v1, c2, v2, ..., [default])` | direct | `if ( [c1] ) then [v1] else if ( [c2] ) then [v2] else [default]` | When no default is given (the idiom is a trailing `TRUE, "F"` pair, which becomes the `else`), ThoughtSpot still requires a type-matched `else` — `''` or `0` is synthesised, which turns Omni's no-match null into a value. |
| `ISBLANK(value)` | direct | `isnull ( [x] )` | Spreadsheet `ISBLANK` is false for an empty string; `isnull` agrees. See the open question on `isnull` support. |
| `ISNUMBER(value)` | direct | `not ( isnull ( [x] ) )` for a numeric column; `false` otherwise | ThoughtSpot columns are typed, so the test resolves at conversion time from the column's data type: a numeric column is a number wherever it is not null; a text column is never one (spreadsheet `ISNUMBER("123")` is false too). |
| `NOT(logical_expression)` | direct | `not ( [x] )` | Function form with parentheses. Omni's numeric truthiness (`NOT(0)` = TRUE) needs an explicit `[x] = 0` when the operand is numeric. |
| `OR(condition1, condition2)` | direct | `( [c1] ) or ( [c2] )` | |

## Math and number functions

Source: [math and number functions](https://docs.omni.co/analyze-explore/calculations/math-number.md).
Grid aggregates follow [E5](#how-to-read-the-tables). Literal-list and same-row-cell arguments
(`AVERAGE(1, 2, 3)`, `AVERAGE(A1, C1)`) are row-wise arithmetic and always `direct`.
Trigonometry: Omni (like Sheets) works in **radians**, and so does ThoughtSpot (`sin ( 30 )` compiles
to `SIN(30)`, live 2026-10-07, probe record §7), so the trig rows are the identity. **Corrected
2026-10-07 (BL-364):** they converted by `180 / π` on an unprobed "ThoughtSpot is degrees" assumption.

| Omni | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ABS(value)` | direct | `abs ( [x] )` | |
| `ACOS(number)` | direct | `acos ( [x] )` | Radians on both sides (BL-364). |
| `ATAN(number)` | direct | `atan ( [x] )` | As `ACOS`. |
| `AVERAGE(value1, ...)` | passthrough | `sql_double_aggregate_op ( "AVG(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Average of the grid's per-row sums, which is not `average` over base rows. **No native fast path, and the reason is base-row weighting:** the FP:432-441 two-formula route (inner `group_aggregate ( sum ( [T::x] ) , query_groups ( ) , query_filters ( ) )`, referenced by name) returns a row-level scalar replicated onto every base row, so an outer `average` weights each group value by its row count. A literal or same-row-cell argument list is row-wise arithmetic and `direct`. |
| `AVERAGEIFS(range, criteria_range1, criterion1, ...)` | passthrough | `sql_double_aggregate_op ( "AVG(CASE WHEN SUM({1}) > 20 THEN SUM({0}) END) OVER ()" , [T::x] , [T::c] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Criteria test *grid values* (usually measures), so a row-level `average_if` is not equivalent. Omni does not support text criteria in the `*IF` family, so criteria on a string dimension do not arise. |
| `CEILING(value, [significance])` | direct | `ceil ( [x] )`; `ceil ( [x] / [s] ) * [s]` with significance | Composition taken from the Power BI translator (`functions.py` `_ceiling_repl`). |
| `CORREL(array1, array2)` | passthrough | `sql_double_aggregate_op ( "CORR(SUM({0}), SUM({1})) OVER ()" , [T::a] , [T::b] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. **Row-level grid (one grid row per base row, or numeric dimension columns) → `direct`** with the [Excel map](ts-excel-function-mapping.md)'s `CORREL` composition, `( sum ( [x] * [y] ) - sum ( [x] ) * sum ( [y] ) / count ( [x] ) ) / ( ( count ( [x] ) - 1 ) * stddev ( [x] ) * stddev ( [y] ) )`, carrying its status (algebraic identity, pairing caveat, no import probe recorded). Over a column of *sums* the identity would need the grid values as row-level inputs, which the FP:432-441 route supplies only with base-row weighting (see `AVERAGE`), so the common case stays a pass-through. |
| `COS(number)` | direct | `cos ( [x] )` | Radians on both sides (BL-364). |
| `COT(number)` | direct | `1 / tan ( [x] )` | No native `cot`; reciprocal of `tan` is exact except at 0: `COT(0)` is NULL in ThoughtSpot (NULL-safe `/`), where a SQL `COT(0)` errors (BL-370). |
| `COUNT(value)` | passthrough | `sql_int_aggregate_op ( "COUNT(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_int_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Counts *grid rows* with a numeric value, not base rows. **Unverified native fast path, one-dimension grid:** the grid has one row per value of its dimension, so the count is `group_aggregate ( unique count ( [T::dim] ) , { } , query_filters ( ) )` (off by one if a dimension value has a null measure). A single-cell `COUNT(A1)` is `if ( not ( isnull ( [A] ) ) ) then 1 else 0`. |
| `COUNTA(value)` | passthrough | `sql_int_aggregate_op ( "COUNT(MAX({0})) OVER ()" , [T::d] )` | **Variant: `sql_int_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Non-empty grid cells of any type. **Unverified native fast path, one-dimension grid:** `group_aggregate ( unique count ( [T::dim] ) , { } , query_filters ( ) )`, as `COUNT`. |
| `COUNTIF(cell_range, criteria)` | passthrough | `sql_int_aggregate_op ( "COUNT(CASE WHEN SUM({0}) >= 2 THEN 1 END) OVER ()" , [T::x] )` | **Variant: `sql_int_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Omni: string data types are not supported, single criterion only. |
| `COUNTIFS(cell_range, criteria1, ...)` | passthrough | `sql_int_aggregate_op ( "COUNT(CASE WHEN SUM({0}) > 2 AND SUM({1}) > SUM({0}) THEN 1 END) OVER ()" , [T::a] , [T::b] )` | **Variant: `sql_int_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. |
| `COVAR(array1, array2)` | passthrough | `sql_double_aggregate_op ( "COVAR_SAMP(SUM({0}), SUM({1})) OVER ()" , [T::a] , [T::b] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Omni: equivalent to `COVAR.S` (sample). Row-level grid → `direct` with the [Excel map](ts-excel-function-mapping.md)'s `COVARIANCE.S` composition (divide by `count ( [x] ) - 1`). |
| `COVARIANCE.P(array1, array2)` | passthrough | `sql_double_aggregate_op ( "COVAR_POP(SUM({0}), SUM({1})) OVER ()" , [T::a] , [T::b] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Row-level grid → `direct` with the [Excel map](ts-excel-function-mapping.md)'s `COVARIANCE.P` composition, `( sum ( [x] * [y] ) - sum ( [x] ) * sum ( [y] ) / count ( [x] ) ) / count ( [x] )` (same status as `CORREL`). |
| `DEGREES(radians)` | direct | `( [x] * 180 ) / sql_double_op ( "PI()" )` | No native `degrees`. Bracketed, with the warehouse's PI: `a * b / c` is read as `a * ( b / c )` (BL-365). |
| `EXP(number)` | direct | `exp ( [x] )` | |
| `FLOOR(value, [significance])` | direct | `floor ( [x] )`; `floor ( [x] / [s] ) * [s]` with significance | As `CEILING`. |
| `INT(value)` | direct | `floor ( [x] )` | Omni: alias for `FLOOR` (rounds down, so `INT(-8.9)` = −9, as `floor`). |
| `INTERCEPT(known_y, known_x)` | passthrough | `sql_double_aggregate_op ( "REGR_INTERCEPT(SUM({0}), SUM({1})) OVER ()" , [T::y] , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Row-level grid → `direct` with the [Excel map](ts-excel-function-mapping.md)'s `INTERCEPT` composition, `average ( [y] ) - [formula_Slope] * average ( [x] )` (references `SLOPE` by id; status as `CORREL`). |
| `LARGE(array, k)` | passthrough | `sql_double_aggregate_op ( "NTH_VALUE(SUM({0}), 4) OVER (ORDER BY SUM({0}) DESC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. `k` baked into the template. `nth_value` does not exist natively (Ossie map). |
| `LN(number)` | direct | `ln ( [x] )` | |
| `LOG(number, [base])` | direct | `log10 ( [x] )`; `log2 ( [x] )`; `ln ( [x] ) / ln ( [base] )` | Omni defaults the base to **10**. Fixed bases 10 and 2 are native; others by change of base, with `/` (as the Excel map) so a base of 1 yields null rather than `safe_divide`'s 0. |
| `LOG10(number)` | direct | `log10 ( [x] )` | |
| `MAX(range)` | passthrough | `sql_double_aggregate_op ( "MAX(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. The largest grid value of a SUM column is the largest *group sum*. **Unverified native fast path (FP:432-441):** formula `[formula_Row Sum]` = `group_aggregate ( sum ( [T::x] ) , query_groups ( ) , query_filters ( ) )`, then `group_aggregate ( max ( [formula_Row Sum] ) , { } , query_filters ( ) )`. Unlike `AVERAGE`, `max` is immune to the base-row replication of the inner value; whether the inner `query_groups ( )` keeps the query grain inside an outer `{ }` is the unprobed point. A `max` measure or dimension column needs no inner formula: `group_aggregate ( max ( [T::x] ) , { } , query_filters ( ) )`. |
| `MAXIFS(max_range, criteria_range1, criteria1, ...)` | passthrough | `sql_double_aggregate_op ( "MAX(CASE WHEN SUM({1}) > 5 THEN SUM({0}) END) OVER ()" , [T::x] , [T::c] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. |
| `MEDIAN(range)` | passthrough | `sql_double_aggregate_op ( "MEDIAN(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Median of group values; native `median` is over base rows. |
| `MIN(range)` | passthrough | `sql_double_aggregate_op ( "MIN(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Mirror of `MAX`, with the same unverified FP:432-441 fast path using `min`. |
| `MINIFS(min_range, criteria_range1, criteria1, ...)` | passthrough | `sql_double_aggregate_op ( "MIN(CASE WHEN SUM({1}) > 5 THEN SUM({0}) END) OVER ()" , [T::x] , [T::c] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. |
| `MOD(dividend, divisor)` | direct | `[x] - [y] * floor ( [x] / [y] )` | **Sign trap**, as the [Excel map](ts-excel-function-mapping.md)'s `MOD` row: spreadsheet `MOD` takes the sign of the **divisor** (`MOD(-7, 4) = 1`); ThoughtSpot `mod` follows the warehouse, and Snowflake takes the sign of the dividend (−1). The floor identity is exact for every sign; `mod ( [x] , [y] )` is safe only when both operands are known non-negative. |
| `MODE(range)` | passthrough | `sql_double_aggregate_op ( "MODE(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. No native mode. |
| `OMNI_RANK(number, range, [is_in_row_direction])` | direct | `rank ( sum ( [T::x] ) , 'desc' )` | Column direction (down the rows) is the global result-set rank `RANK` maps to. **Row direction** (`TRUE` — across pivot columns within one row) is a rank partitioned by the row dimensions, which has no native form ([E3](#how-to-read-the-tables)): `sql_int_aggregate_op ( "RANK() OVER (PARTITION BY {1} ORDER BY SUM({0}) DESC)" , [T::x] , [T::row_dim] )`, wrapped per Ossie map E8. Omni does not document the sort direction; descending is assumed from `RANK`'s default. |
| `RAND()` | passthrough | `sql_double_op ( "UNIFORM(CAST(0 AS FLOAT), CAST(1 AS FLOAT), RANDOM())" )` | **Variant: `sql_double_op`**, zero-placeholder template. Volatile: re-evaluated per query on both sides. |
| `RANK(number, ref, [direction])` | direct | `rank ( sum ( [T::x] ) , 'desc' )` | ThoughtSpot `rank` is global over the result rows and competition-ranked — exactly a spreadsheet `RANK` over a whole-column range of grid values (Omni even gives `RANK(B1, B:B, 0)` as a canonical range calc). Omni's default is descending; `direction` 1 → `'asc'`. The first argument must be aggregated (live-proven, formula reference Rank Functions), which the grid column already is. A **bounded** `ref` (`B1:B10`) is not the whole result and falls back to a pass-through. |
| `ROUND(number, [num_digits])` | direct | `round ( [x] , 0.01 )` for `num_digits` = 2; `round ( [x] , 1 )` for 0; `round ( [x] , 100 )` for −2 | **Settled by live probe (se-thoughtspot, 2026-10-06): ThoughtSpot's second argument is an increment, not a digit count.** ThoughtSpot compiles `round ( x , n )` to `n * ROUND(x / NULLIF(n, 0))`; on 1234.5678, `round ( x , 0 )` = NULL, `round ( x , 2 )` = 1234, `round ( x , 0.01 )` = 1234.57, `round ( x , 10 )` = 1230. The result is INT64 for an integer increment and DOUBLE for a fractional one. So `num_digits = n` becomes the literal `10^-n`, and 0 digits is `1`, never `0`. A non-literal digit count cannot be folded and raises an issue. Files still reading it as a digit count are listed under [open questions](#open-questions-and-gaps). |
| `ROUNDDOWN(number, [num_digits])` | direct | `if ( [x] >= 0 ) then floor ( [x] * 100 ) / 100 else ceil ( [x] * 100 ) / 100` (for 2 digits) | Toward zero. The sign branch is what makes it exact — `floor` alone is wrong for negatives (the reason the Ossie map passes `TRUNC` through). Binary floating point can differ from a warehouse `TRUNC` on decimal types at representation edges; `sql_double_op ( "TRUNC({0}, 2)" , [x] )` is the exact fallback. |
| `ROUNDUP(number, [num_digits])` | direct | `if ( [x] >= 0 ) then ceil ( [x] * 100 ) / 100 else floor ( [x] * 100 ) / 100` (for 2 digits) | Away from zero; mirror of `ROUNDDOWN`. |
| `SLOPE(known_y, known_x)` | passthrough | `sql_double_aggregate_op ( "REGR_SLOPE(SUM({0}), SUM({1})) OVER ()" , [T::y] , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Row-level grid → `direct` with the [Excel map](ts-excel-function-mapping.md)'s `SLOPE` composition, `[formula_Covariance S] / variance ( [x] )`. |
| `SMALL(array, n)` | passthrough | `sql_double_aggregate_op ( "NTH_VALUE(SUM({0}), 4) OVER (ORDER BY SUM({0}) ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Mirror of `LARGE`. |
| `SQRT(number)` | direct | `sqrt ( [x] )` | |
| `STDEV(value)` | passthrough | `sql_double_aggregate_op ( "STDDEV_SAMP(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Omni's page says STDEV "estimates the standard deviation based on a population", but separates it from `STDEV.P` and links Sheets' `STDEV` (sample) — read as **sample** and flagged. No native fast path, for the base-row weighting reason given on `AVERAGE`. Row-level grid → `stddev ( [x] )`. |
| `STDEV.P(value)` | passthrough | `sql_double_aggregate_op ( "STDDEV_POP(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Row-level grid → `direct` with the [Excel map](ts-excel-function-mapping.md)'s `STDEV.P` composition, `sqrt ( variance ( [x] ) * ( count ( [x] ) - 1 ) / count ( [x] ) )` — an exact identity (ThoughtSpot `stddev` is sample-only), carrying that row's status and its single-value edge case (NULL vs 0). Over a column of sums, base-row weighting as `AVERAGE`. |
| `SUM(range)` | direct | `group_aggregate ( sum ( [T::x] ) , { } , query_filters ( ) )` | The one distributive case: the sum of a column of sums (or counts) is the grand total over base rows ([E5](#how-to-read-the-tables)). A **bounded** relative range is a moving window (see the references table); a sum over a column of averages or unique counts is not distributive and falls back to `sql_double_aggregate_op ( "SUM(<agg>({0})) OVER ()" , [T::x] )` — a grid template, so contradicted by FP:702-722 until probed ([E5](#how-to-read-the-tables)). |
| `SUMIF(range, criteria, [sum_range])` | passthrough | `sql_double_aggregate_op ( "SUM(CASE WHEN SUM({0}) > 5 THEN SUM({1}) END) OVER ()" , [T::b] , [T::c] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. The criteria compare grid values; Omni rejects text criteria. |
| `SUMIFS(sum_range, criteria_range1, criteria1, ...)` | passthrough | `sql_double_aggregate_op ( "SUM(CASE WHEN SUM({1}) > 5 THEN SUM({0}) END) OVER ()" , [T::b] , [T::c] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. |
| `SUMPRODUCT(range1, range2, ...)` | passthrough | `sql_double_aggregate_op ( "SUM(SUM({0}) * SUM({1})) OVER ()" , [T::a] , [T::b] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Σ of per-row products over the grid. |
| `TRUNC(number)` | direct | `if ( [x] >= 0 ) then floor ( [x] ) else ceil ( [x] )` | **Omni doc contradiction, flagged:** the page says TRUNC "truncates … by removing the decimal portion" (toward zero) *and* "Alias for `FLOOR`" (down). They differ for negatives. Mapped to toward-zero (the described behaviour and Sheets'); if Omni really floors, the target is `floor ( [x] )`. Needs a probe on Omni. |
| `VALUE(text)` | direct | `to_double ( [s] )` | Returns NULL on a non-numeric string. |
| `VAR(value)` | passthrough | `sql_double_aggregate_op ( "VAR_SAMP(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Row-level grid → `variance ( [x] )`. |
| `VAR.P(value)` | passthrough | `sql_double_aggregate_op ( "VAR_POP(SUM({0})) OVER ()" , [T::x] )` | **Variant: `sql_double_aggregate_op`.** **Contradicted by FP:702-722 until probed** ([E5](#how-to-read-the-tables) shape 2): an `OVER ()` with a search dimension in the GROUP BY breaks that page's live-verified rule. Row-level grid → `direct` with the [Excel map](ts-excel-function-mapping.md)'s `VAR.P` composition, `variance ( [x] ) * ( count ( [x] ) - 1 ) / count ( [x] )`. |

## Position functions

Source: [position functions](https://docs.omni.co/analyze-explore/calculations/position.md).
This is where the grid model and ThoughtSpot's search model are furthest apart: ThoughtSpot
rows have no stable position, and an Answer cannot read another Answer.

| Omni | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `INDEX(range, position_number)` | passthrough | `sql_double_aggregate_op ( "NTH_VALUE(SUM({0}), 1) OVER (ORDER BY {1} ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)" , [T::x] , start_of_month ( [T::d] ) )` | **Variant: `sql_double_aggregate_op`.** Position is defined by the grid sort ([E5](#how-to-read-the-tables)). Per [FP:702-722](../../agents/shared/schemas/thoughtspot-formula-patterns.md#window-functions-inside-sql__aggregate_op) the window `ORDER BY` must be the GROUP BY expression **bucketed as the search buckets it** (`start_of_month ( [T::d] )` for `[d].monthly`; the raw column fails), and every other search dimension must be in `PARTITION BY` — so the template is valid only for a grid whose sole dimension is the sort column. `position_number` 0 (whole range) is unmappable. |
| `MATCH(search_key, range)` | unmappable | — issue | Returns the *position* of a value in the sorted grid. Needs a row number and a conditional search over it, i.e. a window inside an aggregate, which one SQL template cannot express and ThoughtSpot has no native row position for. |
| `PIVOT(ref, column_index)` | unmappable | — issue | Reads the *k*-th pivot column. The pivot's *k*-th value is data-dependent, so there is no fixed formula. When the user names the pivot value, the manual rebuild is native: `group_aggregate ( sum_if ( [T::pivot_dim] = 'Complete' , [T::x] ) , query_groups ( ) - { [T::pivot_dim] } , query_filters ( ) )`. |
| `PIVOTINDEX()` | passthrough | `group_aggregate ( sql_int_aggregate_op ( "DENSE_RANK() OVER (PARTITION BY {1} ORDER BY {0})" , [T::pivot_dim] , [T::row_dim] ) , query_groups ( ) + { [T::row_dim] } , query_filters ( ) )` | **Variant: `sql_int_aggregate_op`.** The pivot column's 1-based index, assuming pivot columns sort ascending. Per [FP:702-722](../../agents/shared/schemas/thoughtspot-formula-patterns.md#window-functions-inside-sql__aggregate_op) the row dimension(s) must be in `PARTITION BY` and `ORDER BY` must match the pivot's GROUP BY expression (bucketed, e.g. `start_of_month ( [T::d] )`, when the pivot is a date); wrapped per Ossie map E8. `dense_rank` is not native (Ossie map). |
| `PIVOTOFFSET(value_ref, row_offset, column_offset, ...)` | passthrough | `group_aggregate ( sql_double_aggregate_op ( "LAG(SUM({0}), 1) OVER (PARTITION BY {1} ORDER BY {2})" , [T::x] , [T::row_dim] , [T::pivot_dim] ) , query_groups ( ) + { [T::row_dim] } , query_filters ( ) )` | **Variant: `sql_double_aggregate_op`; wrapped per Ossie map E8.** A one-cell column offset is a `LAG` across the pivot dimension within each row — exactly [FP:702-722](../../agents/shared/schemas/thoughtspot-formula-patterns.md#window-functions-inside-sql__aggregate_op)'s verified LEAD shape, so the `ORDER BY` argument must be bucketed to match the search (`start_of_month ( [T::d] )` for a monthly date pivot). The row-offset half swaps the roles. The `num_rows`/`num_cols` range form is unmappable. |
| `PIVOTROW(ref)` | direct | `group_aggregate ( sum ( [T::x] ) , query_groups ( ) - { [T::pivot_dim] } , query_filters ( ) )` | For the documented use, `SUM(PIVOTROW(A1))` — the row's total across pivot columns. Other wrapping aggregates follow [E5](#how-to-read-the-tables). A bare `PIVOTROW` (an array) has no scalar target. |
| `ROW()` | passthrough | `sql_int_aggregate_op ( "ROW_NUMBER() OVER (ORDER BY {0})" , start_of_month ( [T::d] ) )` | **Variant: `sql_int_aggregate_op`.** `row_number` is not native. Per [FP:702-722](../../agents/shared/schemas/thoughtspot-formula-patterns.md#window-functions-inside-sql__aggregate_op) the `ORDER BY` must be the search's bucketed GROUP BY expression (shown for `[d].monthly`), and any other search dimension must be in `PARTITION BY` — which would restart the numbering, unlike Omni. So exact only on a grid whose sole dimension is the sort column. |
| `SWITCH(expression, case1, result1, ..., [default])` | direct | `if ( [x] = 'apple' ) then 'fruit' else if ( [x] = 'banana' ) then 'fruit' else 'unknown'` | Expanded to an equality chain, as the Ossie map's simple `CASE`. A missing default is synthesised type-matched. |
| `VLOOKUP(lookup_value, lookup_range, column_number)` | unmappable | — issue | Reads another tab's (another query's) result grid. ThoughtSpot formulas cannot reference another Answer. When both queries sit on the same Model, the manual rebuild is a `group_aggregate` over the lookup key. |
| `XLOOKUP(lookup_value, tab!lookup_range, tab!return_range)` | unmappable | — issue | As `VLOOKUP`. Omni takes the **minimum** return value when several rows match — the manual rebuild is `group_aggregate ( min ( [T::ret] ) , { [T::key] } , query_filters ( ) )` if the tabs share a Model. |

## Text functions

Source: [text functions](https://docs.omni.co/analyze-explore/calculations/text.md). The
native ThoughtSpot string set is only `concat`, `substr`, `left`, `right`, `strlen`, `strpos`
and `contains` (formula reference, BL-170).

| Omni | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `CHAR(number)` | passthrough | `sql_string_op ( "CHR({0})" , [n] )` | **Variant: `sql_string_op`.** |
| `CONCAT(string1, string2, ...)` | direct | `concat ( [a] , [b] , ... )` | N-ary. |
| `CONCATENATE(string1, ...)` | direct | `concat ( [a] , [b] , ... )` | Alias. |
| `CLEAN(text)` | passthrough | `sql_string_op ( "REGEXP_REPLACE({0}, '[[:cntrl:]]', '')" , [s] )` | **Variant: `sql_string_op`.** Aligned with the [Excel map](ts-excel-function-mapping.md)'s `CLEAN` row. Omni says "non-printable ASCII characters removed", which `[:cntrl:]` (0–31 *and* 127) matches more closely than Excel's 0–31; the Excel map's *unverified* status (POSIX classes in Snowflake's regex dialect) carries over. |
| `EXACT(string1, string2)` | passthrough | `sql_bool_op ( "{0} = {1}" , [a] , [b] )` | **Variant: `sql_bool_op`.** Case-sensitive equality. **Reclassified from `direct` (2026-10-06):** native `[a] = [b]` is **case-insensitive** — ThoughtSpot compiles it to `LOWER(a) = …` with literals lowercased at compile time (live probe, se-thoughtspot, 2026-10-06; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md), "String comparison is case-insensitive"), so `'Abc' = 'abc'` is true natively. The pass-through keeps Snowflake's `=`, which is case-sensitive under the default collation. BL-333. |
| `FIND(find_text, within_text)` | passthrough | `sql_int_op ( "POSITION({0} IN {1})" , [find] , [within] )` | **Variant: `sql_int_op`.** Case-sensitive. **Reclassified from `direct` (2026-10-06):** native `strpos ( [within] , [find] )` compiles to `POSITION('x' IN LOWER(within))` — case-insensitive (live probe, se-thoughtspot, 2026-10-06; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md)) — so it is `SEARCH`, not `FIND`. Snowflake `POSITION` is case-sensitive under the default collation and keeps the 1-based / 0-when-absent contract. **No-match differs:** 0 where Omni most likely yields null (Omni surfaces errors as null) — wrap the template in `NULLIF(…, 0)` if null is wanted, flagged pending an Omni probe. Omni's FIND has no start-index argument. BL-333. |
| `LEFT(text, [num_chars])` | direct | `left ( [s] , n )` | `num_chars` defaults to 1. |
| `LEN(text)` | direct | `strlen ( [s] )` | |
| `LOWER(text)` | passthrough | `sql_string_op ( "LOWER({0})" , [s] )` | **Variant: `sql_string_op`.** No native `lower`. |
| `MID(text, start_num, num_chars)` | direct | `substr ( [s] , [start] - 1 , [n] )` | **1-based → 0-based**: the `- 1` is mandatory. |
| `PROPER(text)` | passthrough | `sql_string_op ( "INITCAP({0})" , [s] )` | **Variant: `sql_string_op`.** |
| `REPLACE(old_text, start_num, num_chars, new_text)` | direct | `concat ( left ( [s] , [start] - 1 ) , [new] , substr ( [s] , [start] - 1 + [n] , strlen ( [s] ) ) )` | **Positional** replace (not substring substitution — that is `SUBSTITUTE`). Native by composition. |
| `RIGHT(text, [num_chars])` | direct | `right ( [s] , n )` | |
| `SEARCH(find_text, within_text)` | direct | `strpos ( [within] , [find] )` | **Reclassified from `passthrough` (2026-10-06):** Omni's `SEARCH` is case-insensitive, and so is native `strpos` — it compiles to `POSITION('x' IN LOWER(within))` with the literal lowercased at compile time (live probe, se-thoughtspot, 2026-10-06; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md)). **Operand order reversed** (haystack first). **No-match:** `strpos` returns 0, where Omni most likely returns null (as `FIND`); `if ( strpos ( [within] , [find] ) = 0 ) then null else strpos ( [within] , [find] )` if null is wanted (`nullif` does not exist — BL-339) — flagged. Only a literal needle was probed (it was lowercased at compile time); a **column** `find_text` is *untested* — the haystack is wrapped in `LOWER`, the needle may not be. |
| `SUBSTITUTE(text, old_text, new_text)` | passthrough | `sql_string_op ( "REPLACE({0}, {1}, {2})" , [s] , [old] , [new] )` | **Variant: `sql_string_op`.** No native `replace` (BL-170). Omni has no `instance_num` argument. |
| `TRIM(text)` | passthrough | `sql_string_op ( "REGEXP_REPLACE(TRIM({0}), ' +', ' ')" , [s] )` | **Variant: `sql_string_op`.** Omni's TRIM also collapses *repeated interior* spaces ("leaving only single spaces between words"), which SQL `TRIM` does not — so the template is not just `TRIM({0})`. No native `trim` (BL-170). |
| `T(value)` | direct | `[x]` for a text column; `''` otherwise | Type-dispatched at conversion time, as `ISNUMBER`. |
| `TEXT(value, "format")` | passthrough | `sql_string_op ( "TO_VARCHAR({0}, '$999,990.00')" , [x] )` | **Variant: `sql_string_op`.** No general formatter. The spreadsheet format (`$0.00`) is **not** a Snowflake format model and must be translated (`$999,990.00` shown for `$0.00` with thousands grouping); the translation is *unverified*. Single-token date formats have native targets (`year_name`, `month`, `day_of_week` — Ossie map `TO_CHAR` row). Often the better answer is a column `format_pattern` instead of a formula. |
| `UPPER(text)` | passthrough | `sql_string_op ( "UPPER({0})" , [s] )` | **Variant: `sql_string_op`.** |

## Operators, literals and references

Sources: the "Supported operators" table on the math page, and the arguments / cell
references / totals sections of the [calculations index](https://docs.omni.co/analyze-explore/calculations/index.md).
Omni documents no `<>` or `!=` operator; the converter uses `NOT(a = b)` → `not ( [a] = [b] )`
when it meets one.

| Omni | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `a & b` | direct | `concat ( [a] , [b] )` | `+` does not concatenate in ThoughtSpot. |
| `a + b` | direct | `[a] + [b]` | Numeric only. |
| `a - b` | direct | `[a] - [b]` | Two dates subtract to a day count only via `diff_days ( [a] , [b] )` (Power BI map). |
| `a * b` | direct | `[a] * [b]` | |
| `a / b` | direct | `[a] / [b]` | Omni's documented null idiom is `1/0` (divide-by-zero yields null). `/` keeps that; `safe_divide` returns **0**, so it is used only where the source guarded the denominator. |
| `a ^ b` | direct | `pow ( [a] , [b] )` | `pow`, not `power`. |
| `a > b` | direct | `[a] > [b]` | |
| `a >= b` | direct | `[a] >= [b]` | |
| `a = b` | direct | `[a] = [b]` | On text, both sides are case-insensitive: Sheets-style `=` ignores case (observed, but not stated on Google's pages — [Sheets map **E4**](ts-sheets-function-mapping.md#how-to-read-the-tables)), and ThoughtSpot compiles `=` to `LOWER(a) = …` with literals lowercased (live probe, se-thoughtspot, 2026-10-06 — [probe record §4](../reviews/2026-10-06-formula-semantics-probes.md#4-string-comparison-is-case-insensitive-bl-333); BL-333) — so the native form is exact. For a case-sensitive test use `EXACT`. |
| `a < b` | direct | `[a] < [b]` | |
| `a <= b` | direct | `[a] <= [b]` | |
| `-x` (unary) | direct | `- [x]` | Omni ignores unary `+`. |
| String literal `"text"` | direct | `'text'` | [E8](#how-to-read-the-tables). |
| Logical literal `TRUE` / `FALSE` | direct | `true` / `false` | Case changes only; Omni would read a lower-case `true` as a cell reference. |
| Current-row cell reference (`B1` on row 1) | direct | `[B]` | The referenced column's own ThoughtSpot formula or column ([E5](#how-to-read-the-tables) shape 1). |
| Offset cell reference (`B0`, `B2`) | direct | `moving_sum ( [T::x] , 1 , -1 , [T::sort_col] )` for the previous row; `moving_sum ( [T::x] , -1 , 1 , [T::sort_col] )` for the next | The ThoughtSpot single-row LAG/LEAD idiom (formula reference, Moving Functions; sign conventions live-verified 2026-06-15). **Ordering assumption:** the Omni query's sort column becomes the order argument ([E5](#how-to-read-the-tables)). Faithful for single-dimension and pivoted queries; for an unpivoted multi-dimension query ThoughtSpot partitions where Omni does not ([E6](#how-to-read-the-tables)). The first row yields null on both sides. The argument is a column reference, not a raw aggregate (Ossie map E5). |
| Relative range (`B1:B7`, a moving window) | direct | `moving_average ( [T::x] , 0 , 6 , [T::sort_col] )` | A range spanning offsets *i…j* from the current row is `moving_<agg> ( [T::x] , -i , j , [T::sort_col] )` under ThoughtSpot's opposite-sign convention (`B1:B7` on row 1 = current row and the 6 below). Native only for SUM / AVERAGE / MIN / MAX; any other aggregate over a window has no ordered native form and falls back to `sql_double_aggregate_op ( "<AGG>(SUM({0})) OVER (ORDER BY {1} ROWS BETWEEN …)" , [T::x] , [T::sort_col] )` with the actual frame. Frames are row-positional on both sides (live-verified on gapped dates). |
| Whole-column range (`C:C`) | direct | `group_aggregate ( <agg> ( [T::x] ) , { } , query_filters ( ) )` | The range itself is an argument; its full treatment is [E5](#how-to-read-the-tables) shape 2 and the per-function rows. `{ }` is the whole-result grouping. |
| Column total (`B_TOTAL`, `${view.measure:column_total}`) | direct | `group_aggregate ( sum ( [T::x] ) , { } , query_filters ( ) )`; in a pivot, `{ [T::pivot_dim] }` | Omni computes totals by re-running the measure at total grain, so the measure's own aggregate is used — `unique count ( [T::x] )` stays a unique count, which `group_aggregate` reproduces exactly. |
| Row total (`B_ROW_TOTAL`, `:row_total`) | direct | `group_aggregate ( sum ( [T::x] ) , query_groups ( ) - { [T::pivot_dim] } , query_filters ( ) )` | The total across pivot columns. The numbered offset form (`B2_ROW_TOTAL`) is an offset reference applied to this formula. |
| Grand total (`B_GRAND_TOTAL`, `:grand_total`) | direct | `group_aggregate ( sum ( [T::x] ) , { } , query_filters ( ) )` | |
| Cross-tab reference (`'Tab Name'!A:A`) | unmappable | — issue | Reads another query's grid; see `VLOOKUP`. |
| Model field reference `${view.field}` in a calc | direct | `[VIEW::Column]` or `[formula_<Name>]` | [E9](#how-to-read-the-tables). |

---

# Part 2 — Modelling layer

Sources: [Measures](https://docs.omni.co/modeling/measures/index.md) and their parameter pages
([`aggregate_type`](https://docs.omni.co/modeling/measures/parameters/aggregate-type.md),
[`filters`](https://docs.omni.co/modeling/measures/parameters/filters.md),
[`sql`](https://docs.omni.co/modeling/measures/parameters/sql.md),
[`custom_primary_key_sql`](https://docs.omni.co/modeling/measures/parameters/custom-primary-key-sql.md),
[`level_of_detail`](https://docs.omni.co/modeling/measures/parameters/level-of-detail.md));
[Dimensions](https://docs.omni.co/modeling/dimensions/index.md) and theirs; the
[templated filters](https://docs.omni.co/modeling/templated-filters/index.md) page. Omni's
model is LookML-shaped, so the measure rows reuse the
[Looker mapping](../../agents/shared/mappings/looker/lookml-to-ts-formula-translation.md) §2
(measure types), §5 (`tier`), §6/§6a (filtered measures) and the
[LookML TML rules](../../agents/shared/mappings/looker/lookml-tml-rules.md) (I1 paired
`columns[]` entry, I2 no `aggregation` in `formulas[]`, I5 `count_distinct` is a formula).

The **Via Ossie** column records what apache/ossie's Omni importer does with each construct, so
the Omni → Ossie → ThoughtSpot path can be compared with the direct one. "Stashed" means the
original YAML is kept in `custom_extensions[OMNI]` — lossless for Omni → Ossie → Omni, but
**invisible to any other Ossie consumer**, including a ThoughtSpot converter reading the
`expression`. A row marked **silent** emits an Ossie expression that computes a different number
with no warning.

## Measure `aggregate_type`

Omni measures are `sql:` + `aggregate_type`; `sql` is the operand (`${orders.sale_price}`). A
simple aggregate on a physical column may be a `columns[]` measure with `aggregation:`; anything
else is a formula with a paired `columns[]` entry (I1).

| Omni | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `sum` | direct | `sum ( [T::x] )` (or `aggregation: SUM`) | `SUM(view.field)` (`omni_to_ossie.py:99`, `:609`) — exact | |
| `count` | direct | `count ( [T::pk] )` | `COUNT(*)` when there is no `sql` (`omni_to_ossie.py:600-601`) | Omni counts rows of the view, deduplicated by its primary key under fan-out ([symmetric aggregates](https://docs.omni.co/analyze-explore/sql/symmetric-aggregates.md)). ThoughtSpot has no `count(*)`; the count is over the view's primary key, and ThoughtSpot's own join-aware SQL handles the fan-out. Via Ossie the key is lost: `COUNT(*)` over a joined result over-counts, and the Ossie map's `COUNT(*)` row then needs a declared `primary_key` to recover. With `sql`, `count` is `count ( [T::x] )` (non-null values). |
| `count_distinct` | direct | `unique count ( [T::x] )` | `COUNT(DISTINCT view.field)` (`omni_to_ossie.py:606-607`) — exact | **A space, not an underscore**, and always a formula, never `aggregation: COUNT_DISTINCT` (I5). |
| `average` | direct | `average ( [T::x] )` | `AVG(view.field)` — exact | |
| `min` | direct | `min ( [T::x] )` | `MIN(view.field)` — exact | Aggregate-only. |
| `max` | direct | `max ( [T::x] )` | `MAX(view.field)` — exact | Aggregate-only. |
| `median` | direct | `median ( [T::x] )` | `MEDIAN(view.field)` (`omni_to_ossie.py:100`) — exact | |
| `list` | passthrough | `sql_string_aggregate_op ( "LISTAGG(DISTINCT {0}, ', ') WITHIN GROUP (ORDER BY {0})" , [T::x] )` | `LISTAGG(x, ', ')`, warned, measure stashed (`omni_to_ossie.py:705-706`, `:615-618`) | **Variant: `sql_string_aggregate_op`** (formula reference's own LISTAGG example). The Looker map says "not directly supported — approximate with concat or omit"; `concat` is row-wise, so the pass-through is the faithful target. *Whether Omni's `list` de-duplicates and how it orders is not documented — `DISTINCT` and the order are assumptions, flagged.* |
| `percentile` (+ `percentile: 75`) | passthrough | `sql_double_aggregate_op ( "PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {0})" , [T::x] )` | `PERCENTILE_CONT(p/100)`, warned, stashed; a missing or non-numeric `percentile` silently becomes 0.5 (`omni_to_ossie.py:698-704`) | **Variant: `sql_double_aggregate_op`.** `percentile: 50` → native `median ( [T::x] )`. Continuous vs discrete is not documented by Omni; `PERCENTILE_CONT` is the upstream assumption, kept. |
| `sum_distinct_on` (+ `custom_primary_key_sql`) | direct | `sum ( group_aggregate ( max ( [T::x] ) , query_groups ( ) + { [T::key] } , query_filters ( ) ) )` | **Plain `SUM(x)` — the dedup key is dropped** (`omni_to_ossie.py:707-712`); warned, stashed | One value per distinct key, then summed at the query grain. `sum ( group_aggregate ( … ) )` is the repo's established re-aggregation shape (formula reference, Weighted average; Tableau map); the `query_groups ( ) + { key }` grouping is valid ThoughtSpot (and only untranslatable to a Snowflake SV). **Not live-verified for this construct.** Via Ossie, the number is the fanned-out sum — exactly what `sum_distinct_on` exists to prevent. |
| `average_distinct_on` | direct | `average ( group_aggregate ( max ( [T::x] ) , query_groups ( ) + { [T::key] } , query_filters ( ) ) )` | Plain `AVG(x)`, key dropped (`omni_to_ossie.py:709-712`) | As `sum_distinct_on`. |
| `median_distinct_on` | direct | `median ( group_aggregate ( max ( [T::x] ) , query_groups ( ) + { [T::key] } , query_filters ( ) ) )` | Plain `MEDIAN(x)`, key dropped (`omni_to_ossie.py:709-712`) | As `sum_distinct_on`; `median` over a `group_aggregate` is the least-attested of the three — verify. |
| `percentile_distinct_on` | unmappable | — issue | `PERCENTILE_CONT(p)` over the raw operand, key dropped (`omni_to_ossie.py:713-718`) | No native percentile to wrap around the deduplicating `group_aggregate`, and a `sql_double_aggregate_op` template cannot contain a ThoughtSpot `group_aggregate` argument with any certainty. *If formula arguments to a pass-through are resolved before templating, `sql_double_aggregate_op ( "PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {0})" , [formula_Deduped] )` might work — unverified.* |

An unknown `aggregate_type` is a `ConversionError` upstream (`omni_to_ossie.py:619-621`), so a
new Omni aggregate type breaks the Ossie import rather than degrading.

## Measure constructs

| Omni | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| Raw-SQL measure (`sql: AVG(${orders.sales_price})`, no `aggregate_type`) | direct | per SQL function — see [Raw SQL reference](#raw-sql-in-sql--the-common-functions) | `${…}` references rewritten, always stashed (`omni_to_ossie.py:591-598`) | Classified on the common aggregates, which are native; the long tail follows the Snowflake formula mapping and the Ossie map ([E3](#how-to-read-the-tables)). |
| Derived measure over measures (`sql: ${orders.total_revenue} / ${orders.count}`) | direct | `[formula_Total Revenue] / [formula_Count]` | Raw-SQL path; view qualifiers kept (`omni_to_ossie.py:597`) | Id-references ([E9](#how-to-read-the-tables)). `/` not `safe_divide`, unless the source guards with `NULLIF` (then `safe_divide`, Looker map §4 — note it returns 0, not null). |
| Filtered measure (`filters:`) | direct | `sum_if ( [T::state] = 'California' and [T::age] >= 65 , [T::x] )`; `count` → `count_if ( … , [T::pk] )`; `count_distinct` → `unique_count_if ( … , [T::x] )` | **Expression emitted unfiltered**, warned, measure stashed (`omni_to_ossie.py:623-626`) | The `*_if` family (formula reference, Conditional Aggregates) — preferred over the Looker map's `sum ( if … )` form, which is equivalent. Each filter entry is a predicate from [Part 3](#part-3--filter-syntax), AND-ed. Via Ossie the warning is loud but the Ossie expression is the **unfiltered** total — a ThoughtSpot converter reading Ossie gets a wrong number unless it reads the stash. |
| `level_of_detail` — `fixed: [dims]` | direct | `average ( group_aggregate ( sum ( [T::x] ) , { [CUSTOMERS::Id] } , query_filters ( ) ) )` | **Silent:** `level_of_detail` is not a native key (`omni_to_ossie.py:95-96`), so the measure is stashed, but the emitted expression is the plain outer aggregate (`AVG(x)`) with no warning | Omni's doc gives the SQL: inner `aggregate_type` at the fixed grain, outer `aggregate_type` at the query grain. That is exactly outer-agg over `group_aggregate` with a fixed grouping. The most consequential upstream gap in this document. |
| `level_of_detail` — `always_exclude: [dims]` | direct | `average ( group_aggregate ( average ( [T::x] ) , query_groups ( ) - { [STORES::Region] } , query_filters ( ) ) )` | Silent, as `fixed` | |
| `level_of_detail` — `always_include: [dims]` | direct | `sum ( group_aggregate ( sum ( [T::x] ) , query_groups ( ) + { [USERS::User Id] } , query_filters ( ) ) )` | Silent, as `fixed` | `query_groups ( ) + { }` is valid ThoughtSpot (marked untranslatable only to Snowflake SV). |
| `level_of_detail` — `cancel_query_filters: true` | direct | third argument `{ }` | Silent, as `fixed` | `{ }` blinds the LoD to query-level filters only; **model-level filters still apply** (formula reference, live-verified 2026-07-09). Whether Omni's cancellation also ignores topic `always_where_filters` is not documented — flagged. |
| `level_of_detail` / measure `filters` with `cancel_query_filter: true` on one field | direct | `group_aggregate ( sum_if ( [STORES::State] = 'California' , [T::x] ) , query_groups ( ) , query_filters ( ) - { [STORES::State] } )` | Silent (LoD) / unfiltered (measure filter) | Keep the query grain, ignore the query's filter on that one field and apply the measure's own condition. (An LoD with `fixed: [...]` keeps that grouping in place of `query_groups ( )`.) **Caveat:** `query_filters ( ) - { [col] }` does not remove a filter applied to a *derived* formula built from that column (formula reference, live-verified). |

## Dimension constructs

| Omni | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| `sql:` raw SQL dimension | direct | per SQL function — see [Raw SQL reference](#raw-sql-in-sql--the-common-functions) | References translated, original stashed (`omni_to_ossie.py:396-407`) | Classified on the common functions ([E3](#how-to-read-the-tables)). Omni's `${zip_code}::string` cast → `to_string ( [T::Zip Code] )`. |
| Implicit `sql` (schema-layer default, same-named column) | direct | `[T::Column]` | `expr = dname` (`omni_to_ossie.py:394-395`) — exact | A plain column, `db_column_name` always set. |
| `${TABLE}.column` | direct | `[T::Column]` | → `column` (`_common.py:376`) — exact | Looker map §1. |
| `${field}` / `${view.field}` | direct | `[VIEW::Column]` or `[formula_<Name>]` | → `field` / `view.field` (`_common.py:377-379`) — exact | [E9](#how-to-read-the-tables); cross-view references resolve through Model joins (Looker map §7). |
| `${view.field[timeframe]}` | direct | per timeframe — see the timeframe table below | **Flattened to the base field**, warned, original stashed (`omni_to_ossie.py:399-401`, `_common.py:380-392`) | E.g. `${orders.created_at[date]}` → `date ( [ORDERS::Created At] )`. Via Ossie `[month]` becomes the raw timestamp: a `CASE` on it silently changes grain. |
| `timeframes: [...]` | direct | the date column itself, plus a formula per non-bucket timeframe | `dimension.is_time: true`; exact list stashed (`omni_to_ossie.py:424-426`) | ThoughtSpot buckets any date column at search time (`monthly`, `quarterly`, …), so the bucketing timeframes need no formula; extraction timeframes (`month_name`, `day_of_week_num` …) become formulas when they are to be searchable by name. |
| `duration: {sql_start, sql_end, intervals}` | direct | `diff_days ( [T::End] , [T::Start] )` etc. — see the interval table below | **Silent:** no `sql`, so `expr = dname` (`omni_to_ossie.py:394-395`) — a reference to a column of the dimension's own name, which does not exist; `duration` stashed generically (`:428-437`) | One formula per interval, `diff_*` **end first**. Looker map §3 `duration`. Omni: an unparameterised `${duration}` reference is always null. |
| `bin_boundaries: [21, 65]` | direct | `if ( [T::age] < 21 ) then '< 21' else if ( [T::age] < 65 ) then '>= 21 and < 65' else '65 and above'` | **Silent:** emitted as the unbinned operand; `bin_boundaries` stashed generically (`omni_to_ossie.py:428-437`) | Looker map §5 (`tier`). Labels follow Omni's documented example; Omni does not let them be configured. Null input: Omni's bucket for null is undocumented — a null falls to the final `else` here, flagged. |
| `groups: [{filter: {is: [...]}, name}]` + `else` / `else_raw_value` | direct | `if ( [T::status] in { 'Cancelled' , 'Returned' } ) then 'Test' else if ( [T::status] in { 'Processing' , 'Shipped' } ) then 'going' else 'Other'` | **Silent:** emitted as the ungrouped column; `groups` stashed generically | Curly-brace `in` list (live-verified), so `>-` YAML. `else_raw_value: true` → `else [T::status]`. |
| `level_of_detail` on a dimension | structural | a SQL View (or warehouse table) computing the per-key aggregate, joined on the `fixed` key | **Silent:** expression is the row-level operand (`users.age`), not the aggregate | Omni's LoD *dimension* is categorical — it can be grouped by. A ThoughtSpot `group_aggregate` formula is measure-typed and cannot be a grouping attribute, so the formula form covers only measure use (`group_aggregate ( max ( [USERS::Age] ) , { [USERS::Country] } , query_filters ( ) )`). Grouping by it needs model structure. |
| `dynamic_top_n: {n, by, desc, else}` | unmappable | — issue | **Silent:** plain dimension, setting stashed | A dimension whose *values* depend on a ranking query. `rank` is aggregate-only, so `if ( rank ( … ) <= 10 ) …` is a measure, not a groupable attribute. ThoughtSpot's search-time `top 10 [d] by [m]` covers the query use; a model-level equivalent does not exist. |
| `convert_tz` | structural | connection / user timezone | **Silent:** stashed generically | Timezone conversion is runtime configuration in ThoughtSpot (see the repo's [`ts-variable-timezone`](../../agents/cli/ts-variable-timezone/SKILL.md) skill), not a formula. `convert_tz: false` → leave the column unconverted. |
| `custom_calendar` / model `fiscal_month_offset` | structural | ThoughtSpot custom calendar; `fiscal` argument on date functions | `custom_calendar` (a dimension parameter): stashed generically, silently (`omni_to_ossie.py:428-437`). `fiscal_month_offset` is a **model-file** setting: the model file is stashed verbatim (`README.md:126`) | Fiscal *offsets* are native (`year ( [d] , fiscal )`); week-based retail calendars need a calendar table — see [`ts-object-calendar-builder`](../../agents/cli/ts-object-calendar-builder/SKILL.md). Omni's `custom_calendar` / `fiscal_month_offset` corresponds to the ThoughtSpot **Model's calendar** (no formula change): translated formulas do not name a calendar, and the Model supplies it — Gregorian with a Monday week start when nothing else is set (ThoughtSpot domain review, 2026-10-06). Stays `structural`. |
| `week_start_day` | structural | instance / calendar week-start setting | As a dimension parameter ([docs](https://docs.omni.co/modeling/dimensions/parameters/week-start-day.md)): stashed generically, silently. As a model-level setting it rides in the verbatim model-file stash (`README.md:126`) | Affects `week` timeframes and `start_of_week`. ThoughtSpot's default is Gregorian with a **Monday** week start (ThoughtSpot domain review, 2026-10-06) — `monday` needs nothing. Another start day corresponds to the ThoughtSpot Model's calendar (no formula change); every Monday-based row in this map (`WEEKDAY`, `WEEKNUM`, `NETWORKDAYS`, `day_of_week_num`, the `day_of_week` filter, the `week` timeframe) diverges if the Model's calendar starts the week elsewhere. `day_number_of_week` stays 1 = Monday under the default calendar (live probe 2026-10-06). The default `start_of_week` compiled to `DATE_TRUNC(week, d)`, Monday only under warehouse `WEEK_START` 0/1 — BL-334. |
| `-- DO NOT PARSE` raw SQL | passthrough | `sql_double_op ( "SNOWFLAKE.CORTEX.SENTIMENT({0})" , [T::State] )` (Omni's own example) | Emitted as an `ANSI_SQL` expression — a **documented limitation**, not a bug: Ossie has no `OMNI` dialect, and `--dialect` can prepend a warehouse dialect on export (`_common.py:39-43`, `README.md:139-143`) | **Variant per return type.** By definition dialect SQL Omni will not parse; it can only be a pass-through. |
| Templated value `{{filters.view.field.value}}` | direct | a ThoughtSpot runtime parameter, e.g. `if ( [Timeframe Selector] = 'Daily' ) then date ( [T::d] ) else …` | **Dropped from the Ossie model**, stashed, warned (`omni_to_ossie.py:319-334`) | A filter-only field used as a parameter maps to a ThoughtSpot parameter (formula reference, Runtime Parameters). `direct` only when the SQL around the template is itself translatable; a parameter inside a pass-through is not portable (Ossie map E9). |
| Templated filter block `{{# view.field.filter }} … {{/ … }}` (+ `{{^ }}` default) | unmappable | — issue | Dropped, stashed, warned (`omni_to_ossie.py:319-334`) | Injects the user's *filter predicate* as SQL text. ThoughtSpot formulas cannot read a filter predicate except through `query_filters ( )` inside `group_aggregate`. The common "selector" idiom (`WHEN {{# x.timeframe_selector.filter }} 'Daily' {{/ }}`) is rebuilt by hand as a list parameter. |
| Templated `range_start` / `range_end` | unmappable | — issue | Dropped, stashed, warned | Reads a date filter's bounds; ThoughtSpot formulas cannot. A pair of date parameters is the manual rebuild (cf. the Power BI SPLY parameter pattern, [`sply-parameter.md`](../../agents/shared/worked-examples/powerbi/sply-parameter.md)). |
| Templated `in_query` / `is_selected` / `is_filtered` | unmappable | — issue | Dropped, stashed, warned | Query-shape introspection; no ThoughtSpot formula equivalent. |

### Timeframes *(not counted — arguments)*

Source: [`timeframes`](https://docs.omni.co/modeling/dimensions/parameters/timeframes.md); default
set `raw, date, week, month, quarter, year`.

| Omni timeframe | ThoughtSpot | Class |
|---|---|---|
| `raw` | `[T::d]` | direct |
| `date` | `date ( [T::d] )` | direct |
| `week` | `start_of_week ( [T::d] )` | direct — assumes the Model calendar's Monday week start (the default — Gregorian, Monday — when the Model sets no other calendar; ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere. Omni's default week also starts on Monday; a non-Monday `week_start_day` corresponds to the ThoughtSpot Model's calendar (no formula change). *Residual caveat:* the default form compiled to Snowflake `DATE_TRUNC(week, d)` (live probe 2026-10-06), which is Monday only while the warehouse's `WEEK_START` is 0 or 1 — BL-334. |
| `month` | `start_of_month ( [T::d] )` | direct |
| `quarter` | `start_of_quarter ( [T::d] )` | direct |
| `year` | `start_of_year ( [T::d] )` | direct — assumes Omni's `year` is a truncated date, not an integer (displayed as `2024`); if an integer, `year ( [T::d] )`. |
| `hour` | `start_of_hour ( [T::d] )` | direct |
| `minute` | `start_of_min ( [T::d] )` | direct |
| `second` | `sql_date_time_op ( "DATE_TRUNC('second', {0})" , [T::d] )` | passthrough |
| `millisecond` | `sql_date_time_op ( "DATE_TRUNC('millisecond', {0})" , [T::d] )` | passthrough |
| `day_of_month` | `day ( [T::d] )` | direct |
| `day_of_quarter` | `day_number_of_quarter ( [T::d] )` | direct — Omni: fiscal day of quarter when a fiscal offset is set → add `fiscal`. |
| `day_of_week_name` | `day_of_week ( [T::d] )` | direct |
| `day_of_week_num` | `day_number_of_week ( [T::d] )` | direct — ThoughtSpot's base is **1 = Monday … 7 = Sunday** (live-verified, se-thoughtspot, 2026-10-06); Omni's base is still undocumented. Assumes the Model calendar's Monday week start (the default — Gregorian, Monday — when the Model sets no other calendar; ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere. |
| `day_of_year` | `day_number_of_year ( [T::d] )` | direct |
| `hour_of_day` | `hour_of_day ( [T::d] )` | direct |
| `month_name` | `month ( [T::d] )` | direct — `month` returns the name. |
| `month_num` | `month_number ( [T::d] )` | direct |
| `quarter_of_year` | `quarter_number ( [T::d] )` | direct |
| `fiscal_quarter` | `quarter_number ( [T::d] , fiscal )` | direct — assumes a number; if Omni returns a truncated fiscal-quarter date, `start_of_quarter ( [T::d] , fiscal )`. Omni's fiscal setting corresponds to the ThoughtSpot Model's calendar (no formula change). |
| `fiscal_year` | `year ( [T::d] , fiscal )` | direct |

### `duration` intervals *(not counted — arguments)*

| Interval | ThoughtSpot |
|---|---|
| `seconds` | `diff_time ( [T::End] , [T::Start] )` |
| `minutes` | `diff_minutes ( [T::End] , [T::Start] )` |
| `hours` | `diff_hours ( [T::End] , [T::Start] )` |
| `days` | `diff_days ( [T::End] , [T::Start] )` |
| `weeks` | `diff_weeks ( [T::End] , [T::Start] )` |
| `months` | `diff_months ( [T::End] , [T::Start] )` |
| `quarters` | `diff_quarters ( [T::End] , [T::Start] )` |
| `years` | `diff_years ( [T::End] , [T::Start] )` |

Whether Omni counts complete intervals or boundaries crossed is undocumented. The
ThoughtSpot side is now known (live probe, se-thoughtspot, 2026-10-06; formula reference):
`diff_months` counts month **boundaries** crossed and `diff_years` is a **calendar-year**
difference (`EXTRACT(YEAR …)` subtraction). If Omni turns out to count complete intervals, use
the `DATEDIF` `"M"`/`"Y"` compositions instead.

## View, relationship and topic constructs

These carry expression semantics (they change which rows a measure sees) but are model
structure, not formulas.

| Omni | Class | ThoughtSpot | Via Ossie | Notes |
|---|---|---|---|---|
| View `sql:` (SQL-defined view) | structural | ThoughtSpot SQL View | Dataset `source: SELECT …` (`_common.py:360-363`) | |
| Query view (`query:` saved query as a view) | structural | SQL View materialising the query's generated SQL | **Not converted**, file stashed, warned (`omni_to_ossie.py:133-141`) | |
| `primary_key: true` / `custom_compound_primary_key_sql` | structural | join cardinality on the Model; the key column for `count` | Native `primary_key` (`omni_to_ossie.py:343-345`, compound `:313-318`) | Drives Omni's symmetric aggregates; ThoughtSpot derives fan-out handling from join cardinality. |
| Relationship `on_sql` (equi-join) | structural | Model join | Native relationship | |
| Relationship `on_sql` (non-equi / range) | structural | SQL View carrying the join | Stashed, warned (`omni_to_ossie.py:467-470`) | Model joins are equi-joins. |
| Relationship `where_sql` | structural | SQL View, or a filter on the joined Table | Stashed, warned (`omni_to_ossie.py:519-520`) | |
| Topic `always_where_filters` / `always_where_sql` | structural | Model-level filter | Topic stashed verbatim (`README.md:126-128`) | Row-level and mandatory, which is what a Model filter is. |
| Topic `default_filters` | unmappable | — issue | Topic stashed verbatim | A *removable* default. ThoughtSpot Model filters cannot be removed by a user; the nearest analogue is a Liveboard/Answer filter, which is content, not model. |
| Topic `access_filters` | structural | Row-level security rule | Topic stashed verbatim | User-attribute driven, as ThoughtSpot RLS on the Table. |
| Topic `always_having_filters` / `always_having_sql` | unmappable | — issue | Topic stashed verbatim | A mandatory filter on *aggregated* results; ThoughtSpot Model filters are row-level. |

## Raw SQL in `sql:` — the common functions

Omni's `sql:` is warehouse SQL, so translation **defers to the
[Snowflake formula mapping](../../agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md)**
(or the matching per-warehouse mapping) and the full ANSI inventory in the
[Ossie function map](../ossie/ts-ossie-function-mapping.md). This short reference covers what
appears most in Omni models; it is not a re-derivation.

| SQL in `sql:` | ThoughtSpot | Source / trap |
|---|---|---|
| `SUM` / `AVG` / `MIN` / `MAX` / `MEDIAN` | `sum` / `average` / `min` / `max` / `median` | Ossie map, Aggregate functions |
| `COUNT(DISTINCT x)` | `unique count ( [T::x] )` | space, not underscore |
| `CASE WHEN … THEN … ELSE … END` | `if ( c1 ) then r1 else if ( c2 ) then r2 else d` | final `else` mandatory and type-matched |
| `COALESCE(a, b)` / `IFNULL` / `NVL` | `ifnull ( [a] , [b] )` (right-nest for more) | |
| `NULLIF(a, b)` | `if ( [a] = [b] ) then null else [a]`; as a divisor, `x / NULLIF(b, 0)` is plain `[x] / [b]` | **No `nullif` in ThoughtSpot** — rejected at import (probe record §7, 2026-10-06, BL-339); plain `/` already returns NULL on a zero divisor |
| `IFF(c, a, b)` | `if ( c ) then [a] else [b]` | |
| `a \|\| b` / `CONCAT` | `concat ( [a] , [b] )` | `+` is numeric-only |
| `UPPER` / `LOWER` / `TRIM` / `REPLACE` | `sql_string_op ( "UPPER({0})" , [s] )` etc. | none native (BL-170) |
| `SUBSTRING(s, start, len)` | `substr ( [s] , start - 1 , len )` | 0-based |
| `DATE_TRUNC('month', d)` | `start_of_month ( [d] )` | no `date_trunc` |
| `DATEDIFF(day, a, b)` | `diff_days ( [b] , [a] )` | end first |
| `DATEADD(day, n, d)` | `add_days ( [d] , n )` | |
| `EXTRACT(MONTH FROM d)` | `month_number ( [d] )` | **not** `month ( )` — the Looker map's §4 row says `month`, which returns the name |
| `CAST(x AS VARCHAR)` / `x::string` | `to_string ( [x] )` | |
| `x IN ('a', 'b')` | `[x] in { 'a' , 'b' }` | curly braces |
| `x LIKE 'foo%'` | `strpos ( [x] , 'foo' ) = 1` | other shapes per Ossie map `LIKE` row |
| `PERCENTILE_CONT(p) WITHIN GROUP (ORDER BY x)` | `sql_double_aggregate_op ( "PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY {0})" , [x] )` | `p = 0.5` → `median` |
| `LISTAGG(x, ', ')` | `sql_string_aggregate_op ( "LISTAGG({0}, ', ')" , [x] )` | |
| `x:path.key` (Snowflake JSON) | `sql_string_op ( "PARSE_JSON({0})['path']['key']" , [x] )` | bracket notation only (Looker map §4) |
| `SUM(x) OVER (PARTITION BY …)` | Ossie map Window functions (E13) | ordered windows with a partition are pass-throughs |

---

# Part 3 — Filter syntax

Source: [Filter syntax](https://docs.omni.co/modeling/filters/index.md) and the
[operators reference](https://docs.omni.co/modeling/filters/operators/index.md). Each operator
becomes the *condition* of a `*_if` aggregate (filtered measures), of a `group_aggregate`
filter (LoD), or of a Model filter (topics). Values are written unquoted in Omni YAML; they are
emitted quoted and typed. **Via Ossie, every measure filter is dropped** — the expression is
emitted unfiltered (`omni_to_ossie.py:623-626`) — so that column is omitted below. Operator semantics are cited per
row to the operator's own page (fetched 2026-10-06); claims marked *unsourced* are not stated
on any fetched page.

| Omni operator | Class | ThoughtSpot condition | Notes |
|---|---|---|---|
| `and` | direct | `( c1 ) and ( c2 )` | Sibling fields in one `filters:` block are also AND-ed. |
| `or` | direct | `( c1 ) or ( c2 )` | |
| `is` | direct | `[x] = 'v'`; array → `[x] in { 'a' , 'b' }`; `true` → `[x] = true`; `null` → `isnull ( [x] )` | `is: falsey` (false *or* null) → `( [x] = false ) or isnull ( [x] )`. Legacy `is: ""` outside an `and`/`or` means *no filter* — emit nothing. **Case:** native string `=` is case-insensitive (live probe, se-thoughtspot, 2026-10-06; BL-333). Whether Omni's `is` on a string is case-sensitive by default is unsourced here (the `case_insensitive` modifier suggests it is); if it is, exact parity is `sql_bool_op ( "{0} = {1}" , [x] , 'v' )`. `in { }` was *not* probed. |
| `not` | direct | `[x] != 'v'`; array → `not ( [x] in { 'a' , 'b' } )` | Omni defines `not` as inequality, the negation of `is` ([not](https://docs.omni.co/modeling/filters/operators/not.md)). No `not in` keyword. *Unsourced:* the operator page does not say whether null rows are kept; SQL `<>` / `NOT IN` drop them — flagged. **Case:** whether ThoughtSpot `!=` lowercases like `=` was *not* probed (2026-10-06); see the `is` row. |
| `not_` prefix (`not_contains`, `not_day_of_week`, …) | direct | `not ( <condition> )` | Not valid on `is`, `and`, `or` ([filter syntax](https://docs.omni.co/modeling/filters/index.md), Negation). *Unsourced:* null handling, as `not`. |
| `cancel_query_filter: true` | direct | filter argument `query_filters ( ) - { [T::x] }` inside `group_aggregate` | See the LoD row above and its derived-formula caveat. |
| `field_name_in_query` + `query_structure` | unmappable | — issue | Filters by another query's results (e.g. top-10 users). No formula form; the ThoughtSpot analogue is a reusable **Set** (cohort) — see [`ts-object-set-manager`](../../agents/cli/ts-object-set-manager/SKILL.md). |
| `field_name_not_in_query` | unmappable | — issue | As above, negated. |
| `before` | direct | `[d] < to_date ( '2024-01-01' , 'yyyy-MM-dd' )`; relative `7 days ago` → `[d] < add_days ( today ( ) , -7 )` | See the relative-date table. |
| `on_or_after` | direct | `[d] >= to_date ( '2024-01-01' , 'yyyy-MM-dd' )` | |
| `between_dates` | direct | `[d] >= <start> and [d] < add_days ( <end> , 1 )` | **Inclusive of both dates** per [between_dates](https://docs.omni.co/modeling/filters/operators/between-dates.md); on a timestamp column "inclusive of the end date" means the whole end day, hence the half-open bound at end + 1 day. |
| `time_for_duration: [start, duration]` | direct | `[d] >= <start> and [d] < add_days ( <start> , 30 )` | Source: [time_for_duration](https://docs.omni.co/modeling/filters/operators/time-for-duration.md) (`[2024-06-01, 30 days]` = 1–30 June, so the end is exclusive). *Unsourced:* the "complete" anchoring — `30 complete days ago` is read as `add_days ( today ( ) , -30 )` with today excluded. |
| `date_offset_from_query` (+ `cancel_query_filter`) | unmappable | — issue | Shifts the **query's own date filter** (period-over-period). ThoughtSpot formulas cannot read a filter's value; the manual rebuild is the parameter pattern in [`sply-parameter.md`](../../agents/shared/worked-examples/powerbi/sply-parameter.md). |
| `day_of_month` | direct | `day ( [d] ) = 15` | |
| `day_of_quarter` | direct | `day_number_of_quarter ( [d] ) = 1` | |
| `day_of_week` | direct | `day_of_week ( [d] ) = 'Monday'`; numeric `n` → `mod ( day_number_of_week ( [d] ) , 7 ) = n` | Omni accepts the full day name **or a number 0 = Sunday … 6 = Saturday** ([day_of_week](https://docs.omni.co/modeling/filters/operators/day-of-week.md)). `mod ( … , 7 )` maps ThoughtSpot's 1 = Monday … 7 = Sunday onto that base (the fixed Monday base is live-verified, se-thoughtspot 2026-10-06 — Excel gap G11 settled). The numeric form assumes the Model calendar's Monday week start (the default — Gregorian, Monday — when the Model sets no other calendar; ThoughtSpot domain review, 2026-10-06) and diverges if the Model's calendar starts the week elsewhere. |
| `day_of_year` | direct | `day_number_of_year ( [d] ) = 1` | |
| `hour_of_day` | direct | `hour_of_day ( [d] ) = 9` | |
| `month_of_year` | direct | `month_number ( [d] ) = 1`; a name → `month ( [d] ) = 'January'` | Omni accepts the full month name or 1–12 ([month_of_year](https://docs.omni.co/modeling/filters/operators/month-of-year.md)). |
| `quarter_of_year` | direct | `quarter_number ( [d] ) = 1` | |
| `between` | direct | `[x] between 10 and 20` | Inclusive on both sides in ThoughtSpot and in Omni ([between](https://docs.omni.co/modeling/filters/operators/between.md): "inclusive of the minimum and maximum values"). |
| `greater_than` | direct | `[x] > 10` | |
| `greater_than_or_equal_to` | direct | `[x] >= 10` | |
| `less_than` | direct | `[x] < 10` | |
| `less_than_or_equal_to` | direct | `[x] <= 10` | |
| `contains` | passthrough | `sql_bool_op ( "CONTAINS({0}, {1})" , [s] , 'Blob' )` | **Variant: `sql_bool_op`.** Omni's `contains` is **case-sensitive by default** ([contains](https://docs.omni.co/modeling/filters/operators/contains.md)). **Reclassified from `direct` (2026-10-06):** native `contains ( [s] , 'Blob' )` compiles to `LOWER(s) LIKE '%blob%' ESCAPE '!'` — case-insensitive (live probe, se-thoughtspot, 2026-10-06; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md)). Snowflake `CONTAINS` is case-sensitive under the default collation. With `case_insensitive: true`, native `contains` is exact (see that row). BL-333. |
| `starts_with` | passthrough | `sql_bool_op ( "STARTSWITH({0}, {1})" , [s] , 'Blob' )` | **Variant: `sql_bool_op`.** Omni: case-sensitive by default ([starts_with](https://docs.omni.co/modeling/filters/operators/starts-with.md)). **Reclassified from `direct` (2026-10-06):** the native composition `strpos ( [s] , 'Blob' ) = 1` rests on `strpos`, which lowercases (live probe, se-thoughtspot, 2026-10-06; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md)); the composed form itself was *not* probed. `left ( [s] , 4 ) = 'Blob'` uses native `=`, which also lowercases. No native `starts_with` (BL-170). BL-333. |
| `ends_with` | passthrough | `sql_bool_op ( "ENDSWITH({0}, {1})" , [s] , 'Blob' )` | **Variant: `sql_bool_op`.** Omni: case-sensitive by default ([ends_with](https://docs.omni.co/modeling/filters/operators/ends-with.md)). **Reclassified from `direct` (2026-10-06):** the native form `right ( [s] , 4 ) = 'Blob'` ends in a native `=`, which compiles to `LOWER(…) = 'blob'` (live probe, se-thoughtspot, 2026-10-06; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md)). No native `ends_with` (BL-170). BL-333. |
| `is_empty` | direct | `[s] = ''` (`false` → `[s] != ''`) | Omni's [is_empty](https://docs.omni.co/modeling/filters/operators/is-empty.md) page says "empty string values" and its `or` example lists "is empty" (`is: ""`) and "is null" (`is: null`) as separate conditions, so null is **not** included. Legacy `is: ""` reads as `is_empty: true` inside `and`/`or` and as *no filter* outside them (same page). |
| `sql_like` | passthrough | `sql_bool_op ( "{0} LIKE {1}" , [s] , 'a%b' )` | **Variant: `sql_bool_op`.** Source: [sql_like](https://docs.omni.co/modeling/filters/operators/sql-like.md) — `%` and `_` wildcards, **case-sensitive by default**. **Reclassified from `direct` (2026-10-06):** the native prefix / suffix / `contains` compositions this row used all lowercase both sides (live probe, se-thoughtspot, 2026-10-06; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md)), so only Snowflake `LIKE` (case-sensitive) keeps the semantics for every pattern shape. BL-333. |
| `case_insensitive: true` (modifier) | direct | the wrapped operator's **native** form: `[s] = 'admin'`, `contains ( [s] , 'admin' )`, `strpos ( [s] , 'admin' ) = 1` | **Reclassified from `passthrough` (2026-10-06):** ThoughtSpot's native string comparison is already case-insensitive — `[s] = 'admin'` compiles to `LOWER(s) = 'admin'` and `contains` to `LOWER(s) LIKE '%admin%'`, with literals lowercased at compile time (live probe, se-thoughtspot, 2026-10-06; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md), "String comparison is case-insensitive"). So the modifier needs no `LOWER` pass-through. *Not tested:* `!=` and `in { }` (the `not` / array forms of `is`), and the composed `strpos … = 1` form. |

### Relative date values *(not counted — arguments)*

| Omni value | ThoughtSpot |
|---|---|
| `today` | `today ( )` |
| `N days ago` | `add_days ( today ( ) , -N )` |
| `N weeks ago` / `N months ago` / `N years ago` | `add_weeks` / `add_months` / `add_years ( today ( ) , -N )` |
| `N complete days ago` | as above, with the current partial period excluded |
| `this quarter` / `last month` (named periods) | `start_of_quarter ( today ( ) )` bounds; resolved against a `custom_calendar` when one is set (Omni) |

---

## Passthrough caveat (applies to every `passthrough` row)

The `sql_*_op` family embeds raw warehouse SQL: correctness depends on the connection's
dialect, and the expression is opaque to ThoughtSpot's query planner. The converter emits each
one with a warning-severity issue. The Ossie map's three operational rules apply unchanged —
**the variant fixes type and measure/attribute role** (its E7), **a pass-through carrying
`PARTITION BY` is wrapped in `group_aggregate ( … , query_groups ( ) + { [partition] } ,
query_filters ( ) )`** (its E8), and **no pass-through carries a runtime parameter** (its E9) —
see [Passthrough caveat](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row).
Two Omni-specific additions:

- **The grid `OVER ()` templates conflict with a live-verified rule.** Formula reference lines
  702-722: in an aggregated search, a pass-through window's `ORDER BY` must match the bucketed
  GROUP BY expression and every other search dimension must appear in `PARTITION BY`. Every
  grid-aggregate template in Part 1 breaks the second rule whenever the search has a dimension;
  they are recorded as **contradicted until probed**, not merely unverified ([E5](#how-to-read-the-tables)).
- **Grid templates also assume a single-stage query.** Every `… OVER ()` template in Part 1 relies
  on the window being evaluated over the query's grouped rows. ThoughtSpot can generate
  multi-stage SQL (chasm/fan-trap handling across multiple fact tables); there the template may
  land at the wrong stage. Such formulas should be checked in a search with the intended
  dimensions before they are relied on.
- **The AI functions bill per row.** A warehouse AI call inside a ThoughtSpot formula runs on
  every query that touches the column; it is not cached the way an Omni workbook result is.

---

## Reverse direction (ThoughtSpot → Omni)

Brief, because nothing in the repo converts this way yet. Most ThoughtSpot constructs land on
Omni's **modelling layer**, where the fit is unusually good; only the ordered window family
needs table calculations, which Omni says may not be promotable to the shared model.

| ThoughtSpot | Omni | Disposition |
|---|---|---|
| `sum_if` / `count_if` / `unique_count_if` / `average_if` | measure `filters:` when the condition is a field filter; otherwise `sql: SUM(CASE WHEN … END)` | native |
| `group_aggregate ( agg , { dims } , query_filters ( ) )` | `level_of_detail: {fixed: [dims]}` | native — near one-to-one |
| `group_aggregate ( … , query_groups ( ) - { d } , … )` / `+ { d }` | `always_exclude` / `always_include` | native |
| `group_aggregate ( … , … , { } )` | `cancel_query_filters: true` | native |
| `query_filters ( ) - { [col] }` | `cancel_query_filter: true` on that field | native |
| `cumulative_*` / `moving_*` | table calc over a relative range, or raw-SQL window in `sql:` | lossy — a table calc is bound to one query |
| `rank ( agg , dir )` | `RANK(B1, B:B, dir)` table calc | table calc only |
| `last_value` / `first_value` (semi-additive) | no native construct; LoD `max` on the date plus a filtered measure, or raw SQL | manual |
| Runtime parameter | filter-only field + templated filter `{{filters.v.f.value}}` | native |
| `sql_*_op` | raw `sql:` (or `-- DO NOT PARSE`) | native — Omni SQL *is* warehouse SQL |
| `unique count` | `aggregate_type: count_distinct` | native |

The upstream Ossie exporter emits only `AGG(view.field)` measures and raw-SQL measures
(`README.md:122`), so a ThoughtSpot → Ossie → Omni path would land every LoD and filtered
measure as raw SQL, losing the structured Omni form even where Omni has one.

---

## Open questions and gaps

**ThoughtSpot gaps that drive the `passthrough` set** (verified absences, from the formula
reference and the Ossie/Power BI maps):

1. No `lower` / `upper` / `trim` / `replace` — 6 Omni rows (LOWER, UPPER, TRIM, SUBSTITUTE,
   PROPER, CLEAN) cannot be native. (SEARCH and `case_insensitive` left this list on
   2026-10-06: native comparison is already case-insensitive.)
1a. **No case-sensitive native string comparison** (live probe, se-thoughtspot, 2026-10-06;
   formula reference, "String comparison is case-insensitive"; BL-333). `=`, `contains` and
   `strpos` compile to `LOWER(col) …` with literals lowercased at compile time, so 6 rows whose
   Omni semantics are case-sensitive — `EXACT`, `FIND`, and the `contains` / `starts_with` /
   `ends_with` / `sql_like` filters — are `sql_bool_op` / `sql_int_op` pass-throughs over
   Snowflake's case-sensitive default collation. *Not tested:* `!=`, `in { }`, the composed
   `strpos … = 1` form, and string join keys.
2. No grid-row aggregation other than the distributive cases — 26 of the 27 math
   pass-throughs are aggregates *over a column of aggregates* (E5). A native
   "aggregate over the query result" (`AGG2` over `query_groups ( )` rows) would make most of
   them `direct`; this is the single largest lever.
3. No minute / second extraction; no `nth_value`, `row_number`, `dense_rank`; no percentile,
   mode, correlation, covariance or regression aggregates; no bitwise operators.
4. No row position and no cross-Answer reference — the five `unmappable` table-calc rows.
5. A `group_aggregate` formula is measure-typed, so an aggregated value cannot be a grouping
   attribute (LoD dimensions, `dynamic_top_n`).

**Upstream converter gaps (apache/ossie `converters/omni` @ `2491533`)** — candidates to raise
upstream, most severe first:

1. **Silent wrong numbers, no warning:** `level_of_detail` on measures and dimensions,
   `bin_boundaries`, `groups`, `duration`, `dynamic_top_n`, `convert_tz`, `custom_calendar`
   all reach the generic stash loop (`omni_to_ossie.py:428-437`; `level_of_detail` absent from
   `_MEASURE_NATIVE_KEYS`, `:95-96`) while the Ossie `expression` keeps only the bare operand.
   `duration` is worst: with no `sql` its expression is the dimension's own name
   (`:394-395`), a column that does not exist.
2. **Warned but wrong:** measure `filters` emitted unfiltered (`:623-626`); `*_distinct_on`
   emitted as the plain aggregate with the dedup key dropped (`:707-718`); timeframe references
   flattened to the raw field (`:399-401`).
3. **Semantic drift:** `count` with no `sql` becomes `COUNT(*)` (`:600-601`), losing Omni's
   primary-key-distinct counting under fan-out; a missing `percentile` silently defaults to the
   median (`:698-704`).
4. **Dialect label (documented limitation, not a bug):** every imported expression is labelled
   `ANSI_SQL`, because the Ossie dialect enum has no `OMNI` entry (`_common.py:39-43`,
   `README.md:139-143`). A consumer must not trust the label for `-- DO NOT PARSE` or other
   warehouse-specific SQL.
5. **Out of scope by design:** table calculations live in workbooks, not model files, so none
   of Part 1 is reachable via Ossie.

**Contradictions inside the repo's own references** (to settle before a converter is built):

- **Week base, month/year differences and string case — SETTLED, live probe on
  se-thoughtspot, 2026-10-06** (formula reference rows `day_number_of_week`, `start_of_week`,
  `diff_months`, `diff_years`, `contains`, `strpos`): `day_number_of_week` is fixed 1 = Monday
  (Excel gap G11 — `WEEKDAY`, `WEEKNUM`, `NETWORKDAYS` and the `day_of_week` filter rest on it);
  `diff_months` counts month boundaries and `diff_years` is a calendar-year difference (Excel
  gap G12 — the `DATEDIF` `"M"`/`"Y"` correction is needed); string comparison is
  case-insensitive (BL-333 — six rows reclassified above). **Calendars** (ThoughtSpot domain review, 2026-10-06): the `start_of_*` functions accept an optional custom-calendar string argument, but translations do not use it — the Model supplies the calendar, Gregorian with a Monday week start by default, so every Monday-based row here assumes that and diverges under a Model calendar that starts elsewhere. The default `start_of_week` compiled to `DATE_TRUNC(week, d)`, which is Monday only under warehouse `WEEK_START` 0/1 (BL-334).

- **`round` second argument — SETTLED, live probe on se-thoughtspot, 2026-10-06:** the second
  argument is an **increment**. ThoughtSpot compiles `round ( x , n )` to
  `n * ROUND(x / NULLIF(n, 0))`; on 1234.5678 it returned `round ( x , 0 )` = NULL,
  `round ( x , 2 )` = 1234, `round ( x , 0.01 )` = 1234.57, `round ( x , 10 )` = 1230, typed
  INT64 for an integer increment and DOUBLE for a fractional one. **Repo errors this exposed:** BL-331 (PR #558) corrects every translator and mapping doc in the repo that read it as a digit count — Snowflake SV, Tableau, Databricks (both directions), Sisense, the formula reference and the Ossie map; BL-332 tracks the upstream apache/ossie converter.
- **Looker map §4:** `EXTRACT(MONTH FROM col)` → `month ( )` returns the month *name*
  (contradicts the formula reference and Power BI map); §2 `count` "includes nulls" contradicts
  the formula reference ("count of non-null values").
- **`isnull` support:** Looker map §6a says `isnull()` is rejected on some instances and
  prescribes `[x] = null`; the formula reference lists `isnull` as native (its `isnotnull` row was disproved 2026-10-06 —
  rejected at import, BL-339; write `not ( isnull ( x ) )`). This document uses `isnull` per the
  formula reference.

**Omni documentation ambiguities** (each would change a row; probe on Omni):
`STDEV` sample vs population wording; `TRUNC` "alias for FLOOR" vs truncation; `list`
de-duplication and order; `day_of_week_num` timeframe base (the `day_of_week` *filter* is
0 = Sunday, sourced); `OMNI_RANK` default direction; whether `cancel_query_filters` also ignores
topic filters; null handling of `not` / `not_*`; FIND/SEARCH no-match result (null vs 0);
`year` / `fiscal_quarter` timeframe return types. (`between` / `between_dates` inclusivity and
`is_empty` vs null are now sourced — Part 3.)

**Not live-verified in this pass:** every composition marked as such above —
`sum`/`average`/`median` over `group_aggregate ( … , query_groups ( ) + { key } , … )`, the
`WEEKNUM` and `NETWORKDAYS` compositions (reused from the Excel map with its status — their
`day_number_of_week` base is now live-verified, but the compositions are not import-probed),
the `DATE` composition, the `start_of_week` `WEEK_START` dependence (BL-334),
the FP:432-441 MAX/MIN/COUNT fast paths, and the `TEXT` format-model translation. The
`… OVER ()` grid templates are **contradicted** by the formula reference (lines 702-722), not
merely unverified.

---

## Worked shape

One construct per classification, from Omni YAML and a table calc to the ThoughtSpot formulas
the converter would emit.

Omni (`views/orders.view.yaml`, plus two table calcs on a query grouped by `orders.created_at[month]`):

```yaml
dimensions:
  age_bin:
    sql: ${users.age}
    bin_boundaries: [21, 65]
measures:
  revenue:
    sql: ${orders.amount}
    aggregate_type: sum
  distinct_customers:
    sql: ${orders.customer_id}
    aggregate_type: count_distinct
  california_revenue:
    sql: ${orders.amount}
    aggregate_type: sum
    filters:
      users.state:
        is: California
  avg_customer_lifetime_spend:
    sql: ${orders.amount}
    aggregate_type: average
    level_of_detail:
      aggregate_type: sum
      fixed: [customers.id]
  p95_response:
    sql: ${orders.response_time}
    aggregate_type: percentile
    percentile: 95
# table calcs, column B = revenue:
#   =B1/B0 - 1          (month-over-month growth)
#   =B1/SUM(B:B)        (share of total)
```

ThoughtSpot (Model `formulas[]`; each needs a paired `columns[]` entry by `formula_id`, I1):

```yaml
formulas:
- id: formula_Age Bin
  name: Age Bin
  expr: "if ( [USERS::Age] < 21 ) then '< 21' else if ( [USERS::Age] < 65 ) then '>= 21 and < 65' else '65 and above'"

- id: formula_Distinct Customers
  name: Distinct Customers
  expr: "unique count ( [ORDERS::Customer Id] )"                       # space, not underscore

- id: formula_California Revenue
  name: California Revenue
  expr: "sum_if ( [USERS::State] = 'California' , [ORDERS::Amount] )"   # Via Ossie: unfiltered

- id: formula_Avg Customer Lifetime Spend
  name: Avg Customer Lifetime Spend
  expr: >-
    average ( group_aggregate ( sum ( [ORDERS::Amount] ) , { [CUSTOMERS::Id] } , query_filters ( ) ) )
                                                                        # Via Ossie: silently AVG(amount)

- id: formula_P95 Response
  name: P95 Response
  expr: "sql_double_aggregate_op ( \"PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY {0})\" , [ORDERS::Response Time] )"

- id: formula_Revenue MoM Growth
  name: Revenue MoM Growth
  expr: "sum ( [ORDERS::Amount] ) / moving_sum ( [ORDERS::Amount] , 1 , -1 , [ORDERS::Created At] ) - 1"

- id: formula_Revenue Share
  name: Revenue Share
  expr: >-
    sum ( [ORDERS::Amount] ) / group_aggregate ( sum ( [ORDERS::Amount] ) , { } , query_filters ( ) )
```

`revenue` itself needs no formula — it is a `columns[]` measure with `aggregation: SUM`. The
traps a naive translator hits here: the distinct-count spelling; the LoD collapsing to a plain
average (which is exactly what the Ossie route produces); the filter vanishing on the Ossie
route; the percentile needing an aggregate pass-through; and the two table calcs, which are
native **only because** `SUM(B:B)` over a SUM column is distributive and `B0` reads the previous
month in a single-dimension query — `AVERAGE(B:B)`, or the same `B0` in an unpivoted
two-dimension query, would not be ([E5](#how-to-read-the-tables), [E6](#how-to-read-the-tables)).
The growth formula uses `/`, not `safe_divide`, so a zero prior month yields null as Omni's
does; the `{ }` braces force `>-` YAML.
