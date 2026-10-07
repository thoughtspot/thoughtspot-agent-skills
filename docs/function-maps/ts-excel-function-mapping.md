<!-- currency: excel — 2026-10 (Microsoft 365 function reference) -->
# Microsoft Excel formula functions → ThoughtSpot function mapping

**Status:** research draft (2026-10-06) — written from documentation and this repo's
live-verified references; **no row has been import-probed on a ThoughtSpot instance** except two
`NETWORKDAYS`-family forms: the per-weekday counting form for weekend codes 1, 11 and `"1000001"` without
holidays, and the inline-holiday term with code 1 (live-verified 2026-10-06 — [probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form); see
[Unverified](#unverified)); the semantics of `day_number_of_week`, `diff_months`/`diff_years` and
string comparison (`=`, `contains`, `strpos`) were settled by compiled-SQL probes on 2026-10-06
(gaps G11, G12; BL-333) · **Translator-backed since ts-cli 0.158.0:** the rows listed under
[Translator coverage](#translator-coverage-ts-formula-translate---from-excel) are applied as code by
`ts formula translate --from excel` (BL-339) · **Coverage:** 415 functions rowed, one per function, from the
in-scope categories of Microsoft's
[Excel functions (by category)](https://support.microsoft.com/en-us/office/excel-functions-by-category-5f91f4e9-7b42-46d2-9bd1-63f26a86c0eb)
page as rendered on 2026-10-06, plus 109 out-of-scope functions counted but not rowed ·
**Classifications:** `direct` (native ThoughtSpot formula equivalent, possibly as a
documented composition of native functions) · `passthrough` (requires a ThoughtSpot `sql_*_op`
pass-through — warehouse-dialect-specific, bypasses ThoughtSpot's query planning; **Snowflake is
the reference dialect** for every template in this document) · `structural` (not a formula on the
ThoughtSpot side: the function's job is done by a **Model or Answer construct** — a join, a filter,
a sort, a grouping — see [**E13**](#how-to-read-the-tables)) · `unmappable` (no native expression and no single
reference-warehouse function to pass through; needs a UDF, a pre-computed column, or a different
workbook design) · **TS ground truth:**
[`agents/shared/schemas/thoughtspot-formula-patterns.md`](../../agents/shared/schemas/thoughtspot-formula-patterns.md)
(the *formula reference*), the
[Snowflake formula mapping](../../agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md),
and the [Ossie function map](../ossie/ts-ossie-function-mapping.md) (the *Ossie map*), whose
live-verified findings this document inherits rather than re-derives. Spellings already decided by
the repo's converters are reused and cited: the
[Power BI map](../../agents/shared/mappings/powerbi/powerbi-formula-translation.md) (DAX shares
most of Excel's function names), and the [Qlik](../../agents/shared/mappings/qlik/qlik-thoughtspot-formula-translation.md),
[Tableau](../../agents/shared/mappings/tableau/tableau-formula-translation.md) and
[Sisense](../../agents/shared/mappings/sisense/sisense-formula-translation.md) maps.

This map answers one question per Excel function: *if a workbook's logic is rebuilt as a
ThoughtSpot Model, what does this function become?* It is not a converter specification — there
is no Excel converter in this repo — but it is written so one could be built from it, in the
same shape as the Ossie map. Rules are numbered **E1**–**E18**; they are this document's own and
do not continue the Ossie map's sequence.

---

## How to read the tables

Every row's ThoughtSpot cell is written in ThoughtSpot formula syntax with the canonical spacing
(`concat ( [a] , [b] )`). `[T::x]` is a Model column; a short `[x]`, `[r]`, `[pv]` is any
operand — a column, a literal or a runtime parameter — in the position the Excel argument held.
`[formula_Name]` is a reference to another formula by **id**, which resolves on first import
(CLAUDE.md, invariant I9).

- **E1 — one row per function, inventory from Microsoft's category page.** Every function the
  page lists under an in-scope category has exactly one row. Where the page lists a function
  under two categories it is rowed once: `LET` (Math and Logical) under
  [Dynamic arrays](#dynamic-arrays-let-and-lambda), and `CEILING`, `FLOOR`, `FORECAST` and
  `CONCATENATE` (each also under Compatibility) in their functional sections. The dynamic-array
  family is gathered into its own section from Logical, Lookup and reference, Math and
  Information. Out-of-scope categories are counted, not rowed — see
  [Out of scope](#out-of-scope-counted-not-rowed).
- **E2 — `direct` may be a composition.** ThoughtSpot has no `SIGN`, `PI`, `EOMONTH`,
  `NETWORKDAYS` or population standard deviation, but each is exactly expressible in native
  functions and arithmetic. Those rows are `direct` and give the composition. Classifying only
  name matches as `direct` would push dozens of exactly-expressible functions into
  `passthrough` — and this repo has a record of exactly that pessimism (the converters'
  "unmapped" cells have repeatedly turned out to have native forms).
- **E3 — a `direct` row whose argument space is only partly covered names its fallback.** Many
  Excel functions are `direct` for the arguments a workbook actually uses and `passthrough` or
  `unmappable` beyond (`SEARCH` with wildcards, `WEEKNUM` return type 21, `PRODUCT` over
  non-positive values, `NETWORKDAYS` with a holiday list). The row is classified on the covered
  case and the Notes name the fallback and, where there is one, its `sql_*_op` variant.
- **E4 — every `passthrough` row names its variant.** The `sql_*_op` family is typed
  (`sql_string_op`, `sql_int_op`, `sql_double_op`, `sql_bool_op`, `sql_date_op`,
  `sql_date_time_op`, and the aggregate forms `sql_string_aggregate_op`, `sql_int_aggregate_op`,
  `sql_double_aggregate_op`, `sql_date_time_aggregate_op`). The variant fixes the column's type
  **and** its attribute/measure role, so it is part of the mapping ([**E7** of the Ossie map's
  passthrough caveat](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)).
- **E5 — a range is a column; a cell is a row's value; a criteria pair is a condition.** This
  is the framing rule, and every other row depends on it. Excel is cell-addressed; a Model is
  column-addressed. So:
  - a **range argument** is a column of the Model, and a function that reduces a range is an
    aggregate evaluated at the query's grain — `SUM(B:B)` or `SUM(Sales[Amount])` is
    `sum ( [SALES::Amount] )`. An Excel Table's **structured reference** `Sales[Amount]` maps
    one-for-one onto `[SALES::Amount]`, and is the easiest workbook shape to convert;
  - a **single-cell reference** in a row-wise formula (`=B2*C2` filled down, or the structured
    `[@Amount]`) is that row's value of the column — a row-level formula, `[T::b] * [T::c]`;
  - a **criteria range / criteria pair** (`SUMIF`, `COUNTIFS`, the `D*` database functions) is
    a boolean condition on the row, and the function becomes ThoughtSpot's native `*_if`
    family: `SUMIFS(C:C, A:A, "West")` is `sum_if ( [T::a] = 'West' , [T::c] )`;
  - **paired ranges** (`SUMPRODUCT`, `CORREL`, `SUMX2MY2`) are paired by position in Excel and
    by row in a Model — the same pairing for columns of one table, and only through a
    row-for-row join otherwise. Excel skips a pair if either value is non-numeric; for nullable
    columns, wrap each aggregate in its `*_if` form under
    `not ( isnull ( [x] ) ) and not ( isnull ( [y] ) )`.

  A **two-dimensional** range (`B2:D100` as one argument) has no single-column reading; it is
  either a list of columns (as in `BYROW`) or it is unmappable.
- **E6 — position has no row-level analogue; order must be supplied.** A Model has no row
  numbers, no "cell above", no sheet order and no spill area. Functions whose *meaning* is a
  position — `OFFSET`, `INDIRECT`, `ROW`, `COLUMN`, `CELL`, `ADDRESS`, `CHOOSEROWS`, `DROP`,
  every reshaping function (`TOCOL`, `WRAPROWS`, `TRANSPOSE`) and every **array-returning**
  function whose result is a spilled block (`FREQUENCY`, `LINEST`, `MODE.MULT`, `TEXTSPLIT`) —
  are `unmappable` as formulas. The spill operator `#` and implicit-intersection `@` are syntax,
  not functions, and get no rows; `@` on a structured reference is simply the row-level reading
  in **E5**.

  Some ordered idioms have a native **downgrade** under an explicit **ordering assumption**:
  the workbook's row order is replaced by a sort column the Model actually has (a date, a
  period number), and the downgrade is correct only if that column reproduces the sheet's
  order. The expanding range `SUM($B$2:B2)` filled down is `cumulative_sum ( [T::b] , [T::date] )`;
  the previous row is the LAG idiom `moving_sum ( [T::b] , 1 , -1 , [T::date] )`; a positional
  cash-flow schedule (`NPV`, `MIRR`) needs a period-number column. Two further caveats from the
  Ossie map apply to every such downgrade: a ThoughtSpot window function **cannot declare its own
  partition** — it partitions by whatever dimensions the search carries
  ([Ossie map E13](../ossie/ts-ossie-function-mapping.md#window-functions)) — and its sort
  argument must be a physical column, not a formula.
- **E7 — several arguments are row-wise; one range argument is an aggregate.** Excel overloads
  its reducers: `SUM(B:B)` aggregates a column, `SUM(B2, C2, D2)` adds three cells of one row.
  The second is arithmetic, `[T::b] + [T::c] + [T::d]`. The trap is sharpest for `MAX`/`MIN`:
  ThoughtSpot `max`/`min` are **aggregate-only**, so `MAX(B2, C2)` must become
  `greatest ( [T::b] , [T::c] )` — mapping it to `max` collapses the column to one value and
  turns an attribute into a measure (the Snowflake mapping's scalar MIN/MAX trap).
- **E8 — ThoughtSpot has no error values.** Excel's `#DIV/0!`, `#N/A`, `#VALUE!`, `#NUM!` are
  values a cell can hold; a ThoughtSpot formula has NULL or a failed query. Each error therefore
  has its own fate, and `IFERROR` / `ISERROR` translate by *cause*:
  - **division by zero** is not an error in ThoughtSpot: a plain `[a] / [b]` returns **NULL** on a
    zero divisor, because ThoughtSpot guards the divisor when it compiles the formula ([probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat),
    2026-10-06 — this corrects the earlier reading that a raw `/` fails the whole Snowflake query).
    `IFERROR(a/b, 0)` is `safe_divide ( [a] , [b] )`, which compiles to
    `CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END` and returns **0** on a zero divisor, *not* NULL — but a **NULL** divisor differs: Excel treats a blank as 0 and returns the fallback, `safe_divide` returns NULL, so a nullable divisor needs `ifnull ( [b] , 0 )`;
  - **`#N/A` from a lookup** is a NULL on the joined side of the Model join that replaced the
    lookup ([**E13**](#how-to-read-the-tables)), caught by `ifnull` / `isnull`;
  - **a failed conversion** (`VALUE("abc")`) is **not** a NULL: `to_double` of text that is
    not a number fails the whole query (Snowflake *Numeric value '…' is not recognized*; live
    2026-10-07, [probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat) —
    this corrects the earlier reading from the Ossie map's `TRY_CAST` row). The NULL-on-failure
    form is the pass-through `sql_double_op ( "TRY_TO_DOUBLE({0})" , [s] )`, which the
    translator emits inside `IFERROR` and `ISNUMBER(VALUE(…))`; `to_integer` / `to_date` were not
    probed for this;
  - **a not-found search** (`FIND`, `SEARCH`) is `0` from `strpos`, not an error — so
    `ISNUMBER(FIND(…))` becomes `strpos ( … ) > 0`.

  Once translated, distinctions between error *types* (`ISERR` vs `ISERROR`, `ERROR.TYPE`) do
  not survive, and an `isnull` test cannot tell "failed" from "was NULL in the data".
- **E9 — dates are values, not serial numbers.** Excel stores a date as a day count from its
  1900 epoch (serial 1 = 1900-01-01, including the fictitious 1900-02-29 inherited from Lotus
  1-2-3), and lets date arithmetic be number arithmetic. A Model column is typed DATE or
  DATETIME, and ThoughtSpot does **not** support arithmetic on dates (the Tableau map's
  pipeline step P4). So `A2 + 30` is `add_days ( [T::d] , 30 )`, `B2 - A2` is
  `diff_days ( [T::b] , [T::a] )` (**end first** — the reverse of SQL `DATEDIFF`) — for DATETIME operands `diff_time ( [T::b] , [T::a] ) / 86400`, which keeps the time fraction Excel's subtraction has (`diff_time` is seconds, end first — probe record §7); `add_days` takes whole days, so `d + 0.5` has no `add_days` form — and a date
  literal is `to_date ( '2024-01-15' , '%Y-%m-%d' )` — a bare `'2024-01-15'` parses as
  subtraction (`'%Y-%m-%d'` compiles to Snowflake `'YYYY-MM-DD'`; a Java-style `'yyyy-MM-dd'` is passed through verbatim — live 2026-10-07). Where a source column really holds serial numbers (a CSV export of a sheet), the
  conversion is `add_days ( to_date ( '1899-12-30' , '%Y-%m-%d' ) , [T::serial] )`, exact for
  serials from 61 (1900-03-01) onward because the 1899-12-30 base absorbs the phantom leap day.
  Times of day are fractions of a serial day in Excel and have no ThoughtSpot type at all.
- **E10 — booleans are not numbers, and blank is not zero.** Excel coerces `TRUE` to 1 in
  arithmetic (`--(A2>5)`, `SUMPRODUCT((A:A="x")*B:B)`) and treats a blank cell as 0 in
  arithmetic and `""` in text. ThoughtSpot does neither: a condition used as a number is
  `if ( c ) then 1 else 0`, and NULL propagates through `+` and `concat`. Wrap nullable operands
  in `ifnull ( [x] , 0 )` or `ifnull ( [s] , '' )` where the sheet relied on blanks behaving as
  zero. The same root causes the `MAXIFS`/`MINIFS` difference: Excel returns 0 for no match,
  `max_if` returns NULL.
- **E11 — criteria strings become conditions.** The criteria argument of `SUMIF`, `COUNTIF`,
  `AVERAGEIF`, the `*IFS` family and the `D*` database functions is a small language of its own,
  translated per the table below. Two semantic traps run through it: **Excel criteria matching
  of text is case-insensitive** — which ThoughtSpot's native `=`, `contains` and `strpos` now
  match exactly, because ThoughtSpot lowercases both sides of a string comparison
  (live-verified 2026-10-06, se-thoughtspot: `[DEPARTMENT] = 'engineering'` compiles to
  `LOWER(DEPARTMENT) = 'engineering'`; [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive); `!=` and `in { }` not
  probed) — and **`"<>x"` also matches blanks** (a NULL is never `!=` anything in SQL).
- **E12 — `round`'s second argument is an increment (settled).** Live-probed on se-thoughtspot,
  2026-10-06: ThoughtSpot compiles `round ( x , n )` to `n * ROUND(x / NULLIF(n, 0))`. On
  `1234.5678`, `round ( x , 0 )` = **NULL**, `round ( x , 2 )` = 1234, `round ( x , 0.01 )` = 1234.57,
  `round ( x , 10 )` = 1230; the result is INT64 for an integer increment and DOUBLE for a fractional
  one. So Excel `ROUND(x, 2)` is `round ( [x] , 0.01 )`, zero digits is `round ( [x] , 1 )` — never
  `0`, which silently yields NULL — and `MROUND` is native. Corroboration: AgentQL's `ROUND(x, N)`
  originally compiled to exactly this multiple-of-N semantics before SCAL-319323 made AgentQL
  translate a digit count into a `10^-N` increment
  ([`ts-object-model-agentql-query/references/limitations.md:104`](../../agents/cli/ts-object-model-agentql-query/references/limitations.md)).
  **Repo errors this exposed:** BL-331 (PR #558) corrects every translator and mapping doc in the repo that read it as a digit count — Snowflake SV, Tableau, Databricks (both directions), Sisense, the formula reference and the Ossie map; BL-332 tracks the upstream apache/ossie converter.
- **E13 — `structural` means the function is a Model or Answer construct.** A lookup
  (`VLOOKUP`, `XLOOKUP`, `INDEX`/`MATCH`) does not compute a value; it relates two tables. In a
  Model that relationship is a **join**, after which the looked-up column is simply present and
  needs no formula. Likewise `FILTER` is a filter, `SORT` is the Answer's sort, `UNIQUE` is a
  search on an attribute, `GROUPBY`/`PIVOTBY` are an Answer, and `TAKE(SORT(…), n)` is a top-N.
  These rows are counted separately because neither `direct` (no formula is emitted) nor
  `unmappable` (the capability is fully there) describes them honestly. Where a structural
  function appears *inside* an aggregate, it usually collapses back to a formula:
  `SUM(FILTER(…))` is `sum_if`, `COUNTA(UNIQUE(…))` is `unique count`.
- **E14 — names, `LET` and `LAMBDA` are inlined or hoisted.** A workbook defined name, a `LET`
  binding and a named `LAMBDA` are all reusable expressions. ThoughtSpot has formulas that
  reference formulas but no user-defined functions, so a binding becomes its own formula
  (referenced by id) and a non-recursive `LAMBDA` is macro-expanded at each call site. Arguments
  are known at expansion time, which is why `ISOMITTED` folds to a constant. Recursion has no
  expansion and is unmappable.
- **E15 — type tests resolve from the column's type.** A worksheet cell can hold any type; a
  Model column has exactly one. `ISNUMBER`, `ISTEXT`, `ISLOGICAL`, `ISNONTEXT`, `TYPE`, `T`, `N`
  and the `…A` statistical variants (`AVERAGEA`, `MAXA`, `STDEVA`) that treat text and booleans
  specially therefore resolve at conversion time from the column's data type — usually to a
  constant, or to the plain function. Their common *idioms* (`ISNUMBER(SEARCH(…))`,
  `ISNUMBER(VALUE(…))`) are different tests and are rowed on the relevant function.

E16–E18 are section-specific and stated where they apply: E16 under
[Math and trigonometry](#math-and-trigonometry), E17 under [Statistical](#statistical), E18 under
[Financial](#financial).

### Criteria strings *(not counted — arguments)*

Applies to every `*IF` / `*IFS` / `D*` row ([**E11**](#how-to-read-the-tables)). `[T::x]` is the criteria range's column.

| Excel criterion | ThoughtSpot condition | Notes |
|---|---|---|
| `5` / `"5"` / `"=5"` | `[T::x] = 5` | |
| `">5"`, `">=5"`, `"<5"`, `"<=5"` | `[T::x] > 5` … | |
| `"<>5"` | `( [T::x] != 5 or isnull ( [T::x] ) )` | **Excel counts blanks as not-equal**; SQL `NULL != 5` is NULL, so the `or isnull` is required to match. |
| `"West"` | `[T::x] = 'West'` | Case-insensitive in Excel, and **case-insensitive natively too**: ThoughtSpot compiles `=` to `LOWER(x) = 'west'` (live-verified 2026-10-06 — [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive)). Exact. The former `ILIKE` fallback is unnecessary. |
| `"We*"` | `strpos ( [T::x] , 'We' ) = 1` | Prefix. Case-insensitive, matching Excel: `strpos` compiles to `POSITION('we' IN LOWER(x))` (live-verified 2026-10-06; the composed `= 1` form inherits it but was not itself probed). |
| `"*st"` | `substr ( [T::x] , strlen ( [T::x] ) - 2 , 2 ) = 'st'` | Suffix composition, as the Ossie map's `ENDSWITH`. |
| `"*es*"` | `contains ( [T::x] , 'es' )` | Case-insensitive, matching Excel (`LOWER(x) LIKE '%es%'`, live-verified 2026-10-06). |
| `"?est"`, `"W*t"` | `sql_bool_op ( "{0} ILIKE '_est'" , [T::x] )` | **Variant: `sql_bool_op`.** Interior wildcards and `?` have no native form. `~*` / `~?` escape a literal wildcard. |
| `"="` or `""` (blank) | `isnull ( [T::x] )` | With `COUNTIF`, count a non-null key: `count_if ( isnull ( [T::x] ) , [T::key] )` — counting `[T::x]` itself returns 0. |
| `"<>"` (non-blank) | `not ( isnull ( [T::x] ) )` | |
| `">"&C1` (cell reference) | `[T::x] > [Threshold]` | The referenced cell is an input — a runtime **parameter** — or another column. A parameter keeps the formula native but makes it untranslatable onward to static SQL. |
| `">="&DATE(2024,1,1)` | `[T::x] >= to_date ( '2024-01-01' , 'yyyy-MM-dd' )` | Date criteria per [**E9**](#how-to-read-the-tables). |
| `{"a","b"}` (array constant, summed) | `[T::x] in { 'a' , 'b' }` | The `SUM(SUMIFS(…, {"a","b"}))` OR-idiom. **Curly braces** (BL-170), and `>-` block-scalar YAML. |
| Database criteria block (two rows) | `( c11 and c12 ) or ( c21 )` | Same row = AND, different rows = OR. |


### Implicit type coercion *(not counted — arguments)*

Excel converts an argument to the type its slot expects; ThoughtSpot type-checks the formula at
import and rejects it instead (*Function X expects 1st argument to be …*, error_code 14516).
Formula fidelity M1 found 36 translations rejected this way, all reported TRANSLATED (BL-352..355,
[report](../reviews/2026-10-06-fidelity-m1-excel.md)). The translator writes each conversion out
(`ts_cli/excel/coerce.py`), and a type checker over the emitted formula
(`ts_cli/excel/typecheck.py`) turns any remaining provable type error into NEEDS_REVIEW, so this
class cannot come back TRANSLATED. **ThoughtSpot's "Numeric" is an integer:** a DOUBLE or a
decimal literal is rejected in the integer slots (`substr`, `left`, `right`, `add_days`,
`add_months`, `mod`) and by `to_double` itself (VALIDATE_ONLY, se-thoughtspot, 2026-10-07 —
[probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)).

| Excel argument | Slot | ThoughtSpot form | Notes |
|---|---|---|---|
| `"2001-03-31"`, `"2001-03-31T10:20:30"`, `"2001/03/31"`, `"31/03/2001"` | date | `to_date ( '2001-03-31' , '%Y-%m-%d' )` | The pattern is inferred from the literal (`%Y-%m-%d`, `%Y-%m-%dT%H:%M:%S`, `%Y/%m/%d`, `%d/%m/%Y`, `%m/%d/%Y`); ThoughtSpot compiles it to `TO_DATE('…','YYYY-MM-DD')` (live 2026-10-07). **Ambiguous day/month order** (`"03/04/2026"`: Excel takes it from the locale), an impossible date, text that is not a date (Excel `#VALUE!`) and text before 1900 (not a date to Excel) are NEEDS_REVIEW. **A slashed day/month date that does parse** (`"25/12/2020"`, `"12/25/2020"`, `"07/07/2020"`) is APPROXIMATED with a locale trap: Excel reads it in the workbook's locale and returns `#VALUE!` in the other order. ISO and year-first dates stay TRANSLATED |
| a number (literal) | date | `to_date ( '<its date>' , '%Y-%m-%d' )` | Excel's serial number, converted at translation time. Serial 0 (Excel's "1900-01-00"), 60 (the fictitious 29 Feb 1900) and negatives are NEEDS_REVIEW |
| a number column | date | `add_days ( to_date ( '1899-12-30' , '%Y-%m-%d' ) , floor ( [T::n] ) )` | Exact for serials from 61 (1900-03-01); `floor` drops the time fraction, which a date function ignores. Trap names the serial-60 caveat. A **text column** in a date slot is NEEDS_REVIEW (its format is the workbook's locale) |
| a date | number (`VALUE`) or text | `diff_days ( [T::d] , to_date ( '1899-12-30' , '%Y-%m-%d' ) )`; in text `to_string ( diff_days ( … ) )` | Excel's serial: `UPPER(d)` / `LEN(d)` / `"x"&d` read the serial's digits (2000-01-01 → `36526`). `to_string` of a DATE has no one-argument form (rejected). A **DATE_TIME** where text is expected is NEEDS_REVIEW (a serial with a time fraction has no exact text) |
| `"2.5"` (numeric text literal) | number | `2.5` | Folded. Non-numeric text in arithmetic is NEEDS_REVIEW (Excel `#VALUE!`) |
| a text column | number | `to_double ( [T::s] )` | APPROXIMATED, with a trap: text that is not a number **fails the whole query** (*Numeric value '…' is not recognized*, live 2026-10-07; not NULL) where Excel shows `#VALUE!` in one cell, and Excel also reads currency, percent and date text. Inside `IFERROR`, `sql_double_op ( "TRY_TO_DOUBLE({0})" , [T::s] )` (NULL, so the fallback applies) |
| a boolean | number | `if ( b ) then 1 else 0` | E10 |
| a number | text | a literal: its text (`2.50` → `'2.5'`); a column: `to_string ( [T::n] )` | A literal is written in Excel's General format when that is plain digits (integers below 1E+15, at most 15 significant digits, from 1E-4); otherwise (E+ notation, rounding to 15 digits) NEEDS_REVIEW. `to_string` rejects Text, so only non-text operands are wrapped. **A DOUBLE or DECIMAL column is APPROXIMATED**, with a trap: `to_string` follows the warehouse type — the column's scale (`95000.00`), Snowflake's float form (`1e+20`) or binary noise — where Excel writes General format. An integer column is exact |
| a boolean | text | `if ( b ) then 'TRUE' else 'FALSE'` | Excel's capitals; `to_string` gives `true` / `false` (BL-349) |
| a number | condition | `[T::n] != 0` | |
| a DOUBLE or decimal | integer (count, position) | `floor ( [T::n] )`; a literal is truncated (`2.7` → `2`) | Excel truncates toward zero: `floor` is exact for x ≥ 0, and a negative count or position is `#VALUE!` in Excel. A month offset (`EDATE`, `EOMONTH`), which may be negative, is `if ( x < 0 ) then ceil ( x ) else floor ( x )`. **`to_integer` rounds** (2.7 → 3, −2.7 → −3; live 2026-10-07), so it is never used for truncation |
| `IF` / `IFERROR` branches of different types | one type | number and text: the number becomes `to_string ( … )`; boolean and text: `'TRUE'` / `'FALSE'` | APPROXIMATED, with a trap: an Excel cell holds either type, a ThoughtSpot column one. A date beside text is NEEDS_REVIEW (BL-354) |
| text compared with a number or a boolean (`"yes"=[@Flag]`) | comparison | `true` / `false` | Excel orders values of different types by type (numbers < text < booleans) and never finds them equal, so the comparison is a constant. **APPROXIMATED**, with a trap: the fold assumes every cell holds the warehouse column's type, and a blank cell is 0 / `''` to Excel. A date compared with text is NEEDS_REVIEW |

---

## Coverage summary

| Section | Rows | `direct` | `passthrough` | `structural` | `unmappable` |
|---|--:|--:|--:|--:|--:|
| [Math and trigonometry](#math-and-trigonometry) | 80 | 61 | 9 | 0 | 10 |
| [Statistical](#statistical) | 111 | 49 | 14 | 0 | 48 |
| [Text](#text) | 49 | 20 | 22 | 0 | 7 |
| [Date and time](#date-and-time) | 25 | 20 | 5 | 0 | 0 |
| [Logical](#logical) | 11 | 11 | 0 | 0 | 0 |
| [Information](#information) | 21 | 13 | 0 | 0 | 8 |
| [Lookup and reference](#lookup-and-reference) | 22 | 4 | 0 | 7 | 11 |
| [Dynamic arrays, LET and LAMBDA](#dynamic-arrays-let-and-lambda) | 29 | 7 | 0 | 8 | 14 |
| [Database](#database) | 12 | 12 | 0 | 0 | 0 |
| [Financial](#financial) | 55 | 34 | 0 | 0 | 21 |
| **Total** | **415** | **231** | **50** | **15** | **119** |

56% of the in-scope functions (231 of 415) are expressible in ThoughtSpot's native formula language, and a further 4% (15) are `structural` — fully supported, but as a join, filter, sort or Answer rather than a formula — so 59% of Excel's in-scope functions have a native ThoughtSpot home. The 50 `passthrough` rows concentrate in **text handling** (22: 4 to absent `trim`/`upper`/`lower`/`replace`; 3 to case-sensitive comparison — `EXACT`, `FIND`, `FINDB` — because ThoughtSpot's native `=` / `strpos` are case-insensitive (live-verified 2026-10-06; BL-333); 4 to code points; 3 to regular expressions; 3 to number/date-to-text formatting; 5 to string aggregation, repetition, title case, control-character stripping and machine translation), **order statistics and estimators** (14 statistical rows — percentiles, `LARGE`/`SMALL`, `TRIMMEAN`, mode, skew and kurtosis) and **combinatorics, randomness and base conversion** (9 math rows — factorials, `RAND`, `BASE`/`DECIMAL`, and `ATAN2`). The 119 `unmappable` rows are dominated by two families that need a capability rather than a spelling: **statistical distributions, special functions and tests** (38 of the 48 unmappable statistical rows — no `erf`, gamma or beta function on either side; the other 10 are array-returning functions and ETS forecasting) and **iterative or coupon-schedule finance** (21 financial rows); the rest are mostly cell-metadata, position-dependent or array-reshaping functions that have no meaning without a grid ([**E6**](#how-to-read-the-tables)).

---

## Math and trigonometry

Source: the *Math and trigonometry functions* list of Microsoft's category page. `LET`,
`SEQUENCE` and `RANDARRAY` are rowed under [Dynamic arrays](#dynamic-arrays-let-and-lambda).

- **E16 — ThoughtSpot trigonometry is in radians, as Excel's is.** `sin ( 30 )` compiles to `SIN(30)` and returns −0.988, and `asin ( 0.5 )` returns 0.5236 (probe record §7, live 2026-10-07). This rule used to say the opposite — degrees, with a `180 / π` conversion on every call, copied from the Ossie and Tableau maps — and every forward and inverse row was wrong for every non-zero input (BL-364). The hyperbolic family has no native functions: the translator passes them through to Snowflake (`SINH`, …), whose double arithmetic matches Excel's where the `exp` / `ln` compositions lose precision.

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ABS(x)` | direct | `abs ( [x] )` |  |
| `ACOS(x)` | direct | `acos ( [x] )` | Excel and ThoughtSpot trigonometry are both in **radians** ([**E16**](#math-and-trigonometry); probe record §7, live 2026-10-07). Returns radians. Outside −1…1 Excel returns `#NUM!`. Translator: a literal outside the domain (outside −1…1) is NEEDS_REVIEW (an error in Excel); a column is APPROXIMATED with a trap — the warehouse returns NaN, `Infinity`, NULL or fails the query there. |
| `ACOSH(x)` | direct | `ln ( [x] + sqrt ( [x] * [x] - 1 ) )` | No native hyperbolic functions; the logarithmic identity is exact for `x ≥ 1` (Excel's own domain). **Translator: `sql_double_op ( "ACOSH({0})" , [x] )`** — the Snowflake function, which matched Python's `math` to the last digit (probe record §7, live 2026-10-07). The composition is exact algebra but not exact arithmetic: as `ASINH`. Translator: a literal outside the domain (x < 1) is NEEDS_REVIEW (an error in Excel); a column is APPROXIMATED with a trap — the warehouse returns NaN, `Infinity`, NULL or fails the query there. |
| `ACOT(x)` | direct | `1.5707963267949 - atan ( [x] ) * 3.14159265358979 / 180` | `π/2 − atan(x)` in radians, which is Excel's principal range `(0, π)` for every sign of `x`. |
| `ACOTH(x)` | direct | `0.5 * ln ( ( [x] + 1 ) / ( [x] - 1 ) )` | Domain `abs(x) > 1`, as in Excel. |
| `AGGREGATE(function_num, options, ref, [k])` | direct | the aggregate selected by `function_num` — e.g. `9` → `sum ( [x] )`, `1` → `average ( [x] )`, `4` → `max ( [x] )` | Classified on `function_num` 1–13, each of which has a row of its own in this map (`SUM`, `AVERAGE`, `COUNT`, `STDEV.S`, …). `14`–`19` (`LARGE`, `SMALL`, `PERCENTILE.*`, `QUARTILE.*`) take the class of those rows ([**E3**](#how-to-read-the-tables)). The `options` argument is mostly moot: "ignore error values" is what ThoughtSpot aggregates already do with NULLs ([**E8**](#how-to-read-the-tables)), and "ignore hidden rows" has no analogue — a Model has no hidden rows; the query's filters are the analogue and they apply by default. |
| `ARABIC(text)` | **unmappable** | — | Roman-numeral parsing. No native function and no Snowflake function; it needs a UDF or a pre-computed column. |
| `ASIN(x)` | direct | `asin ( [x] )` | As `ACOS`. Translator: a literal outside the domain (outside −1…1) is NEEDS_REVIEW (an error in Excel); a column is APPROXIMATED with a trap — the warehouse returns NaN, `Infinity`, NULL or fails the query there. |
| `ASINH(x)` | direct | `ln ( [x] + sqrt ( [x] * [x] + 1 ) )` | Exact for all `x`. **Translator: `sql_double_op ( "ASINH({0})" , [x] )`** — the Snowflake function, which matched Python's `math` to the last digit (probe record §7, live 2026-10-07). The composition is exact algebra but not exact arithmetic: `x * x` loses precision for a small `x` and overflows for a large one. |
| `ATAN(x)` | direct | `atan ( [x] )` | As `ACOS`. |
| `ATAN2(x_num, y_num)` | passthrough | `sql_double_op ( "ATAN2({0}, {1})" , [y] , [x] )` | **Variant: `sql_double_op`.** **Excel's argument order is `(x, y)`, the reverse of SQL `ATAN2(y, x)`**, so the operands swap. Leaving them in Excel order imports cleanly and returns the angle measured from the wrong axis. Pass-through for the same reason as the Ossie map's `ATAN2` row: the quadrant table is easy to get wrong at the axes. Excel `ATAN2(0, 0)` is `#DIV/0!`; Snowflake returns 0 (a trap). |
| `ATANH(x)` | direct | `0.5 * ln ( ( 1 + [x] ) / ( 1 - [x] ) )` | Domain `abs(x) < 1`. **Translator: `sql_double_op ( "ATANH({0})" , [x] )`** — the Snowflake function, which matched Python's `math` to the last digit (probe record §7, live 2026-10-07). The composition is exact algebra but not exact arithmetic: `( 1 + x ) / ( 1 - x )` loses precision for a small `x`. Translator: a literal outside the domain (|x| ≥ 1) is NEEDS_REVIEW (an error in Excel); a column is APPROXIMATED with a trap — the warehouse returns NaN, `Infinity`, NULL or fails the query there. |
| `BASE(number, radix, [min_length])` | passthrough | `sql_string_op ( "TO_CHAR({0}, 'FMXXXXXXXXXXXXXXXX')" , [x] )` | **Variant: `sql_string_op`.** Covers radix 16 only, through Snowflake's hexadecimal format element ([**E3**](#how-to-read-the-tables)). Other radices (2, 8, 36…) have no warehouse function and are unmappable. *Unverified:* the `X` format element on `TO_CHAR` for this purpose. |
| `CEILING(number, significance)` | direct | `ceil ( [x] / [sig] ) * [sig]` | Two-argument form per the Power BI map (`powerbi-formula-translation.md`, `CEILING(x, sig)` row). One-argument usage is `ceil ( [x] )`. Also listed under Compatibility; rowed once, here ([**E1**](#how-to-read-the-tables)). For a negative `number` with a positive `significance` Excel rounds toward zero, which `ceil ( x / sig ) * sig` also does; a negative `significance` with a negative `number` rounds away from zero in Excel, which the composition matches because the division flips the sign twice.. **A zero `significance` returns 0 in Excel**; `[x] / 0` is NULL in ThoughtSpot, so the translator emits `if ( [sig] = 0 ) then 0 else ceil ( [x] / [sig] ) * [sig]` unless the significance is a non-zero literal (BL-347, fidelity M1). A positive `number` with a negative `significance` is `#NUM!` in Excel and a number here. **A DOUBLE is snapped before `ceil` / `floor`** (translator, ts-cli 0.161.0): `ceil ( round ( [x] / [sig] , 0.000000001 ) )` — binary representation error otherwise pushes an exact step over the edge (`1.1 * 100` is `110.00000000000001`, so the raw form gave 1.11 where Excel, working to 15 significant digits, gives 1.1; live 2026-10-07, probe record §7). Exact literals and integer / DECIMAL columns are not snapped. More than 15 digits is NEEDS_REVIEW (the `10^n` factor overflows the INT64 result). **Integer operands** (translator, ts-cli 0.162.0): Snowflake divides two NUMBER(38,0) values at scale 6, so `floor ( 1999999 / 2000000 )` gave 1 (live 2026-10-07). Two INT operands use the division-free remainder form, e.g. `[x] - ( if ( mod ( [x] , [s] ) < 0 ) then mod ( [x] , [s] ) + [s] else mod ( [x] , [s] ) )` for floor (`mod` takes the dividend's sign), with `if ( [s] = 0 ) then null` where no zero guard applies — `mod` by zero fails the query. Two literals fold; a DECIMAL operand is APPROXIMATED with the scale-6 trap. |
| `CEILING.MATH(number, [significance], [mode])` | direct | `ceil ( [x] / abs ( [sig] ) ) * abs ( [sig] )` | Default `significance` is 1, giving `ceil ( [x] )`. **`significance` is taken as its absolute value** — dividing by a signed negative significance turns Excel's round-toward-zero into round-away for a negative number (BL-346, fidelity M1: `CEILING.MATH` had shared `CEILING`'s rule). A negative number rounds **toward** zero by default (`ceil`); a non-zero `mode` rounds it **away** from zero: `if ( [x] < 0 ) then floor ( [x] / abs ( [sig] ) ) * abs ( [sig] ) else ceil ( [x] / abs ( [sig] ) ) * abs ( [sig] )`. A literal significance is folded (`abs ( -2 )` → `2`). A zero `significance` returns 0: `if ( [sig] = 0 ) then 0 else …` (BL-347). A non-literal `mode` is NEEDS_REVIEW (it picks the direction). Checked by value against every sign and mode combination and Microsoft's worked examples (`tests/test_excel_m1_fixes.py`). **A DOUBLE is snapped before `ceil` / `floor`** (translator, ts-cli 0.161.0): `ceil ( round ( [x] / [sig] , 0.000000001 ) )` — binary representation error otherwise pushes an exact step over the edge (`1.1 * 100` is `110.00000000000001`, so the raw form gave 1.11 where Excel, working to 15 significant digits, gives 1.1; live 2026-10-07, probe record §7). Exact literals and integer / DECIMAL columns are not snapped. More than 15 digits is NEEDS_REVIEW (the `10^n` factor overflows the INT64 result). **Integer operands** (translator, ts-cli 0.162.0): Snowflake divides two NUMBER(38,0) values at scale 6, so `floor ( 1999999 / 2000000 )` gave 1 (live 2026-10-07). Two INT operands use the division-free remainder form, e.g. `[x] - ( if ( mod ( [x] , [s] ) < 0 ) then mod ( [x] , [s] ) + [s] else mod ( [x] , [s] ) )` for floor (`mod` takes the dividend's sign), with `if ( [s] = 0 ) then null` where no zero guard applies — `mod` by zero fails the query. Two literals fold; a DECIMAL operand is APPROXIMATED with the scale-6 trap. |
| `CEILING.PRECISE(number, [significance])` | direct | `ceil ( [x] / abs ( [sig] ) ) * abs ( [sig] )` | Always rounds up (toward +∞) whatever the sign of `significance`. Translator: `significance` taken as `abs ( [sig] )` (a literal folded), a zero significance returns 0 (BL-347). **A DOUBLE is snapped before `ceil` / `floor`**, as `CEILING.MATH`: `round ( [x] / [sig] , 0.000000001 )`. **Integer operands** (translator, ts-cli 0.162.0): Snowflake divides two NUMBER(38,0) values at scale 6, so `floor ( 1999999 / 2000000 )` gave 1 (live 2026-10-07). Two INT operands use the division-free remainder form, e.g. `[x] - ( if ( mod ( [x] , [s] ) < 0 ) then mod ( [x] , [s] ) + [s] else mod ( [x] , [s] ) )` for floor (`mod` takes the dividend's sign), with `if ( [s] = 0 ) then null` where no zero guard applies — `mod` by zero fails the query. Two literals fold; a DECIMAL operand is APPROXIMATED with the scale-6 trap. |
| `COMBIN(n, k)` | passthrough | `sql_double_op ( "FACTORIAL({0}) / (FACTORIAL({1}) * FACTORIAL({0} - {1}))" , [n] , [k] )` | **Variant: `sql_double_op`.** No native factorial. Snowflake `FACTORIAL` overflows above 33, so large `n` should use the multiplicative form in the template instead. Excel truncates non-integer arguments; wrap them in `FLOOR()` inside the template to match. |
| `COMBINA(n, k)` | passthrough | `sql_double_op ( "FACTORIAL({0} + {1} - 1) / (FACTORIAL({1}) * FACTORIAL({0} - 1))" , [n] , [k] )` | **Variant: `sql_double_op`.** `COMBIN(n + k − 1, k)`, with the same overflow caveat. |
| `COS(x)` | direct | `cos ( [x] )` | Excel and ThoughtSpot trigonometry are both in **radians** ([**E16**](#math-and-trigonometry); probe record §7, live 2026-10-07). The former rule here, `cos ( [x] * 180 / 3.14159265358979 )`, assumed degrees and was wrong for every non-zero input (`sin ( 30 )` compiles to `SIN(30)` and returns −0.988). |
| `COSH(x)` | direct | `( exp ( [x] ) + exp ( -1 * [x] ) ) / 2` | **Translator: `sql_double_op ( "COSH({0})" , [x] )`** — the Snowflake function, which matched Python's `math` to the last digit (probe record §7, live 2026-10-07). The composition is exact algebra but not exact arithmetic: `exp` overflows for a large `x` sooner than `COSH` does. |
| `COT(x)` | direct | `1 / tan ( [x] * 180 / 3.14159265358979 )` | As the Tableau map's `COT` row (`tableau-formula-translation.md`). |
| `COTH(x)` | direct | `( exp ( 2 * [x] ) + 1 ) / ( exp ( 2 * [x] ) - 1 )` |  |
| `CSC(x)` | direct | `1 / sin ( [x] * 180 / 3.14159265358979 )` |  |
| `CSCH(x)` | direct | `2 / ( exp ( [x] ) - exp ( -1 * [x] ) )` |  |
| `DECIMAL(text, radix)` | passthrough | `sql_int_op ( "TO_NUMBER({0}, 'XXXXXXXXXXXXXXXX')" , [s] )` | **Variant: `sql_int_op`.** Radix 16 only, as `BASE`; other radices are unmappable. *Unverified* on a live connection. |
| `DEGREES(angle)` | direct | `[x] * 180 / 3.14159265358979` | No native `degrees`; as the Ossie map. **Translator: `sql_double_op ( "DEGREES({0})" , [x] )`**: over literals the composition is fixed-point decimal arithmetic in the warehouse (`180 / 3.14159…` keeps scale 6 — see `ROUNDUP`, BL-348); the Snowflake function computes in double (probe record §7, live 2026-10-07). |
| `EVEN(number)` | direct | `if ( [x] >= 0 ) then ceil ( [x] / 2 ) * 2 else floor ( [x] / 2 ) * 2` | Rounds **away from zero** to the next even integer, so negatives use `floor`. `EVEN(0) = 0`, `EVEN(1) = 2`, `EVEN(-1) = -2` all hold. |
| `EXP(number)` | direct | `exp ( [x] )` | Present per the Ossie map and the Qlik map's live probe (`exp` confirmed 2026-07-30, BL-171). |
| `FACT(number)` | passthrough | `sql_double_op ( "FACTORIAL(FLOOR({0}))" , [x] )` | **Variant: `sql_double_op`** — `sql_int_op` overflows INT64 from 21! (probe record §7, live 2026-10-07: 25! returned 1.5511210043330986E+25). No native factorial. Excel truncates the argument; `FLOOR` inside the template matches that for non-negative input. Snowflake caps at 33!. A negative number (Excel `#NUM!`) or one above 33 fails the **whole query**: a literal is NEEDS_REVIEW, a column APPROXIMATED with that trap. |
| `FACTDOUBLE(number)` | **unmappable** | — | Double factorial. Neither ThoughtSpot nor Snowflake has one, and there is no closed form without the gamma function, which neither has either. |
| `FLOOR(number, significance)` | direct | `floor ( [x] / [sig] ) * [sig]` | Two-argument form per the Power BI map. Also in Compatibility; rowed here. **A DOUBLE is snapped before `ceil` / `floor`** (translator, ts-cli 0.161.0): `floor ( round ( [x] / [sig] , 0.000000001 ) )` — binary representation error otherwise pushes an exact step over the edge (`1.1 * 100` is `110.00000000000001`, so the raw form gave 1.11 where Excel, working to 15 significant digits, gives 1.1; live 2026-10-07, probe record §7). Exact literals and integer / DECIMAL columns are not snapped. More than 15 digits is NEEDS_REVIEW (the `10^n` factor overflows the INT64 result). **Integer operands** (translator, ts-cli 0.162.0): Snowflake divides two NUMBER(38,0) values at scale 6, so `floor ( 1999999 / 2000000 )` gave 1 (live 2026-10-07). Two INT operands use the division-free remainder form, e.g. `[x] - ( if ( mod ( [x] , [s] ) < 0 ) then mod ( [x] , [s] ) + [s] else mod ( [x] , [s] ) )` for floor (`mod` takes the dividend's sign), with `if ( [s] = 0 ) then null` where no zero guard applies — `mod` by zero fails the query. Two literals fold; a DECIMAL operand is APPROXIMATED with the scale-6 trap. |
| `FLOOR.MATH(number, [significance], [mode])` | direct | `floor ( [x] / [sig] ) * [sig]` | Non-zero `mode` rounds negatives **toward** zero: `if ( [x] < 0 ) then ceil ( [x] / [sig] ) * [sig] else floor ( [x] / [sig] ) * [sig]`. Translator: `significance` taken as `abs ( [sig] )` (a literal folded), a zero significance returns 0 (BL-347). **A DOUBLE is snapped before `ceil` / `floor`**, as `CEILING.MATH`: `round ( [x] / [sig] , 0.000000001 )`. **Integer operands** (translator, ts-cli 0.162.0): Snowflake divides two NUMBER(38,0) values at scale 6, so `floor ( 1999999 / 2000000 )` gave 1 (live 2026-10-07). Two INT operands use the division-free remainder form, e.g. `[x] - ( if ( mod ( [x] , [s] ) < 0 ) then mod ( [x] , [s] ) + [s] else mod ( [x] , [s] ) )` for floor (`mod` takes the dividend's sign), with `if ( [s] = 0 ) then null` where no zero guard applies — `mod` by zero fails the query. Two literals fold; a DECIMAL operand is APPROXIMATED with the scale-6 trap. |
| `FLOOR.PRECISE(number, [significance])` | direct | `floor ( [x] / abs ( [sig] ) ) * abs ( [sig] )` | Always rounds down (toward −∞). Translator: `significance` taken as `abs ( [sig] )` (a literal folded), a zero significance returns 0 (BL-347). **A DOUBLE is snapped before `ceil` / `floor`**, as `CEILING.MATH`: `round ( [x] / [sig] , 0.000000001 )`. **Integer operands** (translator, ts-cli 0.162.0): Snowflake divides two NUMBER(38,0) values at scale 6, so `floor ( 1999999 / 2000000 )` gave 1 (live 2026-10-07). Two INT operands use the division-free remainder form, e.g. `[x] - ( if ( mod ( [x] , [s] ) < 0 ) then mod ( [x] , [s] ) + [s] else mod ( [x] , [s] ) )` for floor (`mod` takes the dividend's sign), with `if ( [s] = 0 ) then null` where no zero guard applies — `mod` by zero fails the query. Two literals fold; a DECIMAL operand is APPROXIMATED with the scale-6 trap. |
| `GCD(n1, n2, ...)` | **unmappable** | — | No native function and, as far as this map could establish, no Snowflake built-in (*unverified* — see [Unverified](#unverified)). It is an iterative algorithm with no closed form. |
| `INT(number)` | direct | `floor ( [x] )` | **Excel `INT` rounds down toward −∞** (`INT(-1.5) = -2`), which is exactly `floor`. This is *not* the Tableau `INT` row, which truncates toward zero, and not `to_integer`, which rounds to nearest (live-verified per `tableau-formula-translation.md`: `to_integer(8.6) = 9`). |
| `ISO.CEILING(number, [significance])` | direct | `ceil ( [x] / abs ( [sig] ) ) * abs ( [sig] )` | Same as `CEILING.PRECISE`. Translator: `significance` taken as `abs ( [sig] )` (a literal folded), a zero significance returns 0 (BL-347). **A DOUBLE is snapped before `ceil` / `floor`**, as `CEILING.MATH`: `round ( [x] / [sig] , 0.000000001 )`. **Integer operands** (translator, ts-cli 0.162.0): Snowflake divides two NUMBER(38,0) values at scale 6, so `floor ( 1999999 / 2000000 )` gave 1 (live 2026-10-07). Two INT operands use the division-free remainder form, e.g. `[x] - ( if ( mod ( [x] , [s] ) < 0 ) then mod ( [x] , [s] ) + [s] else mod ( [x] , [s] ) )` for floor (`mod` takes the dividend's sign), with `if ( [s] = 0 ) then null` where no zero guard applies — `mod` by zero fails the query. Two literals fold; a DECIMAL operand is APPROXIMATED with the scale-6 trap. |
| `LCM(n1, n2, ...)` | **unmappable** | — | As `GCD`. |
| `LN(number)` | direct | `ln ( [x] )` |  |
| `LOG(number, [base])` | direct | `log10 ( [x] )`; with a base, `ln ( [x] ) / ln ( [base] )` | **Excel's default base is 10**, not *e* — unlike SQL `LOG`, Qlik `Log` and Sisense `log`, all of which this repo maps to `ln`. Base 2 is `log2 ( [x] )`; other bases go through change-of-base. Translator: a literal outside the domain (x ≤ 0, a base ≤ 0 or 1) is NEEDS_REVIEW (an error in Excel); a column is APPROXIMATED with a trap — the warehouse returns NaN, `Infinity`, NULL or fails the query there. |
| `LOG10(number)` | direct | `log10 ( [x] )` |  |
| `MDETERM(array)` | **unmappable** | — | Matrix algebra over a cell block. A Model column is a vector of rows, not a matrix ([**E5**](#how-to-read-the-tables)). |
| `MINVERSE(array)` | **unmappable** | — | As `MDETERM`; also array-returning ([**E6**](#how-to-read-the-tables)). |
| `MMULT(array1, array2)` | **unmappable** | — | As `MINVERSE`. |
| `MOD(number, divisor)` | direct | `[x] - [y] * floor ( [x] / [y] )` | **Sign trap.** Excel's result takes the sign of the **divisor** (`MOD(-7, 4) = 1`); SQL `MOD` — and therefore ThoughtSpot's `mod`, which follows the warehouse — takes the sign of the **dividend** (Snowflake `MOD(-7, 4) = -3`). The floor identity is Excel's own documented definition and is exact for every sign. `mod ( [x] , [y] )` is safe only when both operands are known non-negative. **Verification:** hand-derived and arithmetic-checked only — **not** import-probed and **not** result-checked against Excel on a live instance. |
| `MROUND(number, multiple)` | direct | `round ( [x] , abs ( [m] ) )` | ThoughtSpot `round`'s increment argument **is** `MROUND` ([**E12**](#how-to-read-the-tables)). `abs` is required: on the probe `round(x, -2)` returned 1234 — a negative increment does not round to hundreds. **Sign rule:** Excel returns `#NUM!` when `number` and `multiple` have different signs; the composition returns a value instead, so flag sources that relied on the error. Halves round away from zero on both sides for exact numeric input. |
| `MULTINOMIAL(n1, n2, ...)` | passthrough | `sql_double_op ( "FACTORIAL({0} + {1}) / (FACTORIAL({0}) * FACTORIAL({1}))" , [a] , [b] )` | **Variant: `sql_double_op`.** Extend the template per argument. Overflow as `COMBIN`. |
| `MUNIT(dimension)` | **unmappable** | — | Returns an identity matrix — array-shaped ([**E6**](#how-to-read-the-tables)). |
| `ODD(number)` | direct | `if ( [x] >= 0 ) then ceil ( ( [x] + 1 ) / 2 ) * 2 - 1 else floor ( ( [x] - 1 ) / 2 ) * 2 + 1` | Away from zero to the next odd integer. Checked at `0 → 1`, `1 → 1`, `1.5 → 3`, `2 → 3`, `-1 → -1`, `-1.5 → -3`. |
| `PERCENTOF(data_subset, data_all)` | direct | `safe_divide ( sum ( [x] ) , group_aggregate ( sum ( [x] ) , { } , query_filters ( ) ) )` | Share of the grand total — the formula reference's *Percentage Contribution Pattern*. Swap `{ }` for `{ [T::category] }` when the denominator is a category total. `safe_divide` returns **0**, not an error, on a zero total ([**E8**](#how-to-read-the-tables)). |
| `PI()` | direct | `3.141592653589793` | No native `pi`. **Translator: `sql_double_op ( "PI()" )`**, the warehouse's double: a decimal literal under `/` is fixed-point at scale 6 (`-1 / 3.141592653589793` returned −0.318310, seven digits short), and ThoughtSpot reads `x * 180 / 3.14…` as `x * ( 180 / 3.14… )` (live 2026-10-07, probe record §7). The literal is right only outside a division. |
| `POWER(number, power)` | direct | `pow ( [x] , [y] )` | **`pow`, not `power`** — `power` is rejected by the parser (formula reference, verified 2026-06-13). Excel's `^` operator lands here too. |
| `PRODUCT(number1, ...)` | direct | range: `exp ( sum ( ln ( [x] ) ) )`; arguments: `[a] * [b] * [c]` | There is no product aggregate. The log-sum identity is exact for **strictly positive** values ([**E3**](#how-to-read-the-tables)); a column that can hold zero or negatives falls back to `sql_double_aggregate_op ( "EXP(SUM(LN(ABS({0})))) * IFF(MOD(COUNT_IF({0} < 0), 2) = 1, -1, 1) * IFF(COUNT_IF({0} = 0) > 0, 0, 1)" , [x] )`. Multiple scalar arguments are row-wise multiplication ([**E7**](#how-to-read-the-tables)). |
| `QUOTIENT(numerator, denominator)` | direct | `if ( [x] / [y] >= 0 ) then floor ( [x] / [y] ) else ceil ( [x] / [y] )` | Truncation toward zero. A zero denominator errors the whole query on Snowflake rather than returning `#DIV/0!` in one cell ([**E8**](#how-to-read-the-tables)); guard it with `if ( [y] = 0 ) then … else …` when the column can hold zero. Translator: a zero divisor gives NULL (ThoughtSpot's `/`, probe record §7), not a query error. **Integer operands** (translator): `( [x] - mod ( [x] , [y] ) ) / [y]`, guarded `if ( [y] = 0 ) then null` (`mod` by zero fails the query), because Snowflake divides integers at scale 6 (`QUOTIENT(1999999, 2000000)` gave 1, live 2026-10-07); literals fold, a literal zero divisor is NEEDS_REVIEW, a DECIMAL operand is APPROXIMATED. |
| `RADIANS(angle)` | direct | `[x] * 3.14159265358979 / 180` | **Translator: `sql_double_op ( "RADIANS({0})" , [x] )`**: over literals the composition is fixed-point decimal arithmetic in the warehouse (`180 / 3.14159…` keeps scale 6 — see `ROUNDUP`, BL-348); the Snowflake function computes in double (probe record §7, live 2026-10-07). |
| `RAND()` | passthrough | `sql_double_op ( "UNIFORM(CAST(0 AS FLOAT), CAST(1 AS FLOAT), RANDOM())" )` | **Variant: `sql_double_op`**, zero-placeholder template. Excel recalculates on every edit; a warehouse value is re-drawn per query and may be served from ThoughtSpot's result cache, so it is neither stable nor fresh. Rarely meaningful in a Model. |
| `RANDBETWEEN(bottom, top)` | passthrough | `sql_int_op ( "UNIFORM({0}, {1}, RANDOM())" , [lo] , [hi] )` | **Variant: `sql_int_op`.** Same volatility caveat as `RAND`. Snowflake `UNIFORM` requires constant bounds. |
| `ROMAN(number, [form])` | **unmappable** | — | As `ARABIC`. |
| `ROUND(number, num_digits)` | direct | `round ( [x] , 0.01 )` for `num_digits = 2`; `round ( [x] , 1 )` for 0; `round ( [x] , 100 )` for −2 | **The second argument is an increment, not a digit count** ([**E12**](#how-to-read-the-tables), live-probed on se-thoughtspot 2026-10-06) — `num_digits = n` becomes the literal `10^-n`. **`round ( [x] , 0 )` returns NULL**, not the integer rounding (the increment 0 hits `NULLIF(n, 0)`), so zero digits must be emitted as `1`. An integer increment yields INT64, a fractional one DOUBLE. Excel rounds halves **away from zero** (`ROUND(-2.5, 0) = -3`); ThoughtSpot's compiled `n * ROUND(x / n)` inherits Snowflake `ROUND`, which is half-away-from-zero for exact `NUMBER` but can land either side of a half on a `FLOAT` column. A **non-literal** `num_digits` cannot be folded to an increment and falls back to `sql_double_op ( "ROUND({0}, {1})" , [x] , [d] )` ([**E3**](#how-to-read-the-tables)). |
| `ROUNDDOWN(number, num_digits)` | direct | `if ( [x] >= 0 ) then floor ( [x] * 100 ) * 0.01 else ceil ( [x] * 100 ) * 0.01` | Toward zero; `100` is `10^num_digits` folded (here 2 digits). Exact up to floating-point representation of the scaled value. Multiply by the increment, never divide by the factor (scale 6 — see `ROUNDUP`, BL-348). **A DOUBLE is snapped before `ceil` / `floor`** (translator, ts-cli 0.161.0): `floor ( round ( [x] * F , 0.000000001 ) )` — binary representation error otherwise pushes an exact step over the edge (`1.1 * 100` is `110.00000000000001`, so the raw form gave 1.11 where Excel, working to 15 significant digits, gives 1.1; live 2026-10-07, probe record §7). Exact literals and integer / DECIMAL columns are not snapped. More than 15 digits is NEEDS_REVIEW (the `10^n` factor overflows the INT64 result). |
| `ROUNDUP(number, num_digits)` | direct | `if ( [x] >= 0 ) then ceil ( [x] * 100 ) * 0.01 else floor ( [x] * 100 ) * 0.01` | Away from zero; mirror of `ROUNDDOWN`. **Idiom:** `ROUNDUP(MONTH(d)/3, 0)` is the calendar quarter number, `quarter_number ( [d] )` — which follows the Model's calendar, so a fiscal calendar shifts it (a trap, not a downgrade). **Multiply by the increment (`0.01` = `10^-num_digits`), never divide by the factor:** `ceil ( [x] * F ) / F` divides two integers, and Snowflake keeps a quotient at scale 6, so a round to more than 6 digits came back with 6 (BL-348, fidelity M1; live 2026-10-07 — `/ to_double ( F )` is cut the same way). Negative `num_digits`: `… ( [x] / 100 ) * 100`. **A DOUBLE is snapped before `ceil` / `floor`** (translator, ts-cli 0.161.0): `ceil ( round ( [x] * F , 0.000000001 ) )` — binary representation error otherwise pushes an exact step over the edge (`1.1 * 100` is `110.00000000000001`, so the raw form gave 1.11 where Excel, working to 15 significant digits, gives 1.1; live 2026-10-07, probe record §7). Exact literals and integer / DECIMAL columns are not snapped. More than 15 digits is NEEDS_REVIEW (the `10^n` factor overflows the INT64 result). |
| `SEC(x)` | direct | `1 / cos ( [x] * 180 / 3.14159265358979 )` |  |
| `SECH(x)` | direct | `2 / ( exp ( [x] ) + exp ( -1 * [x] ) )` |  |
| `SERIESSUM(x, n, m, coefficients)` | **unmappable** | — | The coefficients argument is a positional cell array whose *order* is the exponent ([**E6**](#how-to-read-the-tables)). With literal coefficients the series expands to native `pow` arithmetic, which a converter can emit, but the function as written in a sheet references a range. |
| `SIGN(number)` | direct | `if ( [x] > 0 ) then 1 else if ( [x] < 0 ) then -1 else 0` | The Ossie map records no native `sign`; the Qlik map's header records `sign` as live-confirmed present (BL-171) while its own N13 row says absent. The composition is correct either way, so it is used ([Unverified](#unverified)). |
| `SIN(x)` | direct | `sin ( [x] )` | Excel and ThoughtSpot trigonometry are both in **radians** ([**E16**](#math-and-trigonometry); probe record §7, live 2026-10-07). |
| `SINH(x)` | direct | `( exp ( [x] ) - exp ( -1 * [x] ) ) / 2` | **Translator: `sql_double_op ( "SINH({0})" , [x] )`** — the Snowflake function, which matched Python's `math` to the last digit (probe record §7, live 2026-10-07). The composition is exact algebra but not exact arithmetic: `exp ( x ) - exp ( - x )` cancels for a small `x` (1e-10 loses six digits). |
| `SQRT(number)` | direct | `sqrt ( [x] )` |  |
| `SQRTPI(number)` | direct | `sqrt ( [x] * 3.14159265358979 )` |  |
| `SUBTOTAL(function_num, ref1, ...)` | direct | the aggregate selected by `function_num` — `9`/`109` → `sum ( [x] )`, `1`/`101` → `average ( [x] )`, … | As `AGGREGATE`. The "ignore other subtotals" rule has nothing to act on — a Model column holds no subtotal rows. The `1xx` hidden-row variants and the AutoFilter behaviour both correspond to the query's filters, which ThoughtSpot aggregates respect by default. |
| `SUM(number1, ...)` | direct | range: `sum ( [x] )`; arguments: `[a] + [b]` | `SUM(Table1[Amount])` and `SUM(B:B)` are the column aggregate ([**E5**](#how-to-read-the-tables)); `SUM(B2, C2, D2)` is row-wise addition ([**E7**](#how-to-read-the-tables)). Row-wise, Excel treats a blank cell as 0 while `+` propagates NULL — wrap nullable operands in `ifnull ( [a] , 0 )` ([**E10**](#how-to-read-the-tables)). |
| `SUMIF(range, criteria, [sum_range])` | direct | `sum_if ( [T::range] > 5 , [T::sum_range] )` | The criteria string becomes a condition per the criteria table ([**E11**](#how-to-read-the-tables)). Without `sum_range`, the range is summed: `sum_if ( [T::x] > 5 , [T::x] )`. Text criteria are **case-insensitive** in Excel, which a native `=` is not. |
| `SUMIFS(sum_range, criteria_range1, criteria1, ...)` | direct | `sum_if ( [T::region] = 'West' and [T::d] >= to_date ( '2024-01-01' , 'yyyy-MM-dd' ) , [T::amount] )` | Criteria pairs are ANDed. Note the argument order differs from `SUMIF` (`sum_range` first). OR-logic idioms (`SUM(SUMIFS(..., {"a","b"}))`) become `in { 'a' , 'b' }`. |
| `SUMPRODUCT(array1, [array2], ...)` | direct | `sum ( [T::x] * [T::y] )` | Excel pairs arrays by **position**; the Model pairs columns by **row**, which is the same thing for columns of one table ([**E5**](#how-to-read-the-tables)). The boolean-coercion idiom `SUMPRODUCT(--(A=x), B)` is a conditional sum: `sum_if ( [T::a] = 'x' , [T::b] )` ([**E10**](#how-to-read-the-tables)). Columns from two *different* tables pair only if a join relates them row-for-row. |
| `SUMSQ(number1, ...)` | direct | `sum ( [x] * [x] )` |  |
| `SUMX2MY2(array_x, array_y)` | direct | `sum ( [x] * [x] - [y] * [y] )` | Same-row pairing as `SUMPRODUCT`; Excel skips pairs where either value is non-numeric, so wrap in `sum_if ( not ( isnull ( [x] ) ) and not ( isnull ( [y] ) ) , … )` for nullable columns ([**E5**](#how-to-read-the-tables)). |
| `SUMX2PY2(array_x, array_y)` | direct | `sum ( [x] * [x] + [y] * [y] )` | As `SUMX2MY2`. |
| `SUMXMY2(array_x, array_y)` | direct | `sum ( pow ( [x] - [y] , 2 ) )` | As `SUMX2MY2`. |
| `TAN(x)` | direct | `tan ( [x] )` | As `SIN`. |
| `TANH(x)` | direct | `( exp ( 2 * [x] ) - 1 ) / ( exp ( 2 * [x] ) + 1 )` | **Translator: `sql_double_op ( "TANH({0})" , [x] )`** — the Snowflake function, which matched Python's `math` to the last digit (probe record §7, live 2026-10-07). The composition is exact algebra but not exact arithmetic: `exp ( 2 * x )` overflows for `x` above about 355, giving NaN where Excel gives 1. |
| `TRUNC(number, [num_digits])` | direct | `if ( [x] >= 0 ) then floor ( [x] ) else ceil ( [x] )` | With digits, scale as `ROUNDDOWN`. **This diverges from the Ossie map**, which classes `TRUNC` as `passthrough` on the ground that `floor` disagrees for negatives — true of bare `floor`, but the sign-split composition is exact and native, so per [**E2**](#how-to-read-the-tables) it is `direct` (see [gap **G5**](#open-questions--gaps)). Translator: `ROUNDDOWN`'s rule with `num_digits` defaulting to 0, including its DOUBLE snap `round ( [x] * F , 0.000000001 )`. |

---

## Statistical

Source: the *Statistical functions* list. `FORECAST` is also listed under Compatibility and is
rowed here.

- **E17 — a function with a `cumulative` flag is classified on its CDF form.** In practice
  `NORM.DIST(…, TRUE)` is the call that matters, so the row's class is the cumulative one and the
  Notes give the density where it is native. Neither ThoughtSpot nor Snowflake has `erf`, the
  incomplete gamma or the incomplete beta function, so **every CDF, inverse CDF and p-value test
  except the exponential and Weibull families is `unmappable`** — not for want of a composition
  but because the special function underneath has no implementation to call. A literal
  probability argument (a confidence level written into the formula) can be folded to a
  constant at conversion time, which is what makes `CONFIDENCE.NORM` `direct`.

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `AVEDEV(number1, ...)` | direct | `average ( abs ( [x] - group_aggregate ( average ( [x] ) , query_groups ( ) , query_filters ( ) ) ) )` | Mean absolute deviation needs the mean at the query grain *inside* the row-level expression, which is what `group_aggregate ( … , query_groups ( ) , … )` supplies. *Unverified* composition — a `group_aggregate` inside a row-level expression inside an aggregate is the shape of the formula reference's weighted-average pattern, but this exact formula has not been import-probed. |
| `AVERAGE(number1, ...)` | direct | range: `average ( [x] )`; arguments: `( [a] + [b] ) / 2` | Both sides ignore blanks/NULLs in a range. Row-wise, Excel's `AVERAGE(B2, C2)` skips a blank argument (dividing by 1); the arithmetic form does not — guard with `ifnull` and a count of non-null arguments when that matters ([**E7**](#how-to-read-the-tables)). |
| `AVERAGEA(value1, ...)` | direct | numeric column: `average ( [x] )`; boolean column: `average_if ( not ( isnull ( [b] ) ) , if ( [b] ) then 1 else 0 )` | **`AVERAGEA` counts text as 0 and `TRUE` as 1**; `AVERAGE` skips both. In a Model a column has one type ([**E15**](#how-to-read-the-tables)), so the difference collapses to the column's type: identical to `AVERAGE` on a numeric column, a 0/1 average on a boolean column, and **0** on a text column (every non-blank value counts as 0). Blanks are skipped by both. |
| `AVERAGEIF(range, criteria, [average_range])` | direct | `average_if ( [T::range] > 5 , [T::avg_range] )` | Criteria per [**E11**](#how-to-read-the-tables). |
| `AVERAGEIFS(average_range, criteria_range1, criteria1, ...)` | direct | `average_if ( c1 and c2 , [T::avg_range] )` | Criteria pairs ANDed, as `SUMIFS`. |
| `BETA.DIST(x, alpha, beta, cumulative, [A], [B])` | **unmappable** | — | Classified on the CDF form ([**E17**](#statistical)). No incomplete beta function natively or in Snowflake. |
| `BETA.INV(probability, alpha, beta, [A], [B])` | **unmappable** | — | Inverse distribution; as `BETA.DIST`. |
| `BINOM.DIST(number_s, trials, probability_s, cumulative)` | **unmappable** | — | CDF is a sum over 0…k with no closed form. The PMF (`cumulative = FALSE`) is a pass-through: `sql_double_op ( "(FACTORIAL({1}) / (FACTORIAL({0}) * FACTORIAL({1} - {0}))) * POWER({2}, {0}) * POWER(1 - {2}, {1} - {0})" , [k] , [n] , [p] )`. |
| `BINOM.DIST.RANGE(trials, probability_s, number_s, [number_s2])` | **unmappable** | — | A sum of PMF terms; as `BINOM.DIST`. |
| `BINOM.INV(trials, probability_s, alpha)` | **unmappable** | — | Inverse CDF; as `BINOM.DIST`. |
| `CHISQ.DIST(x, deg_freedom, cumulative)` | **unmappable** | — | Needs the incomplete gamma function ([**E17**](#statistical)). |
| `CHISQ.DIST.RT(x, deg_freedom)` | **unmappable** | — | As `CHISQ.DIST`. |
| `CHISQ.INV(probability, deg_freedom)` | **unmappable** | — | As `CHISQ.DIST`. |
| `CHISQ.INV.RT(probability, deg_freedom)` | **unmappable** | — | As `CHISQ.DIST`. |
| `CHISQ.TEST(actual_range, expected_range)` | **unmappable** | — | The statistic itself is native (`sum ( pow ( [obs] - [exp] , 2 ) / [exp] )`), but the function returns the *p-value*, which needs the chi-square CDF. |
| `CONFIDENCE.NORM(alpha, standard_dev, size)` | direct | `1.95996398454005 * stddev ( [x] ) / sqrt ( count ( [x] ) )` | For a **literal** `alpha` the normal quantile is a constant the converter computes at conversion time (shown for `alpha = 0.05`) ([**E3**](#how-to-read-the-tables)). A column- or parameter-driven `alpha` needs `NORM.S.INV` and is unmappable. |
| `CONFIDENCE.T(alpha, standard_dev, size)` | **unmappable** | — | The t quantile depends on `size − 1` degrees of freedom, which is data-dependent, so it cannot be folded to a constant as `CONFIDENCE.NORM` can. |
| `CORREL(array1, array2)` | direct | `( sum ( [x] * [y] ) - sum ( [x] ) * sum ( [y] ) / count ( [x] ) ) / ( ( count ( [x] ) - 1 ) * stddev ( [x] ) * stddev ( [y] ) )` | Sample covariance over the product of sample standard deviations — an algebraic identity in native aggregates (the *n − 1* factors cancel to Pearson's *r*). Exact when `x` and `y` are non-null on the same rows; otherwise every aggregate must be the `*_if` form under `not ( isnull ( [x] ) ) and not ( isnull ( [y] ) )`, which is how Excel pairs ([**E5**](#how-to-read-the-tables)). Fallback when the pairing guard is unwieldy: `sql_double_aggregate_op ( "CORR({0}, {1})" , [x] , [y] )`. **Verification:** hand-derived and arithmetic-checked only — **not** import-probed and **not** result-checked against Excel on a live instance. |
| `COUNT(value1, ...)` | direct | `count ( [x] )` | Excel `COUNT` counts **numbers only**; on a numeric Model column that is `count` of non-null values. On a text column Excel returns 0 — the converter should emit the literal `0` and an issue rather than `count` ([**E15**](#how-to-read-the-tables)). |
| `COUNTA(value1, ...)` | direct | `count ( [x] )` | Counts non-empty cells of any type. **A formula returning `""` is non-empty to `COUNTA`**; the warehouse equivalent of `""` is an empty string, which `count` also counts, so the two agree — but a column that stores blanks as `''` rather than NULL is counted in full by both, which is usually not what the sheet author meant. |
| `COUNTBLANK(range)` | direct | `count_if ( isnull ( [x] ) or [x] = '' , [T::key] )` | Counts empty cells **and** cells holding `""`. On a non-text column drop the `= ''` branch. `count_if` counts the non-null values of its **second** argument where the condition holds, so pointing it at a non-null key counts the rows where `[x]` is NULL; `sum ( if ( isnull ( [x] ) ) then 1 else 0 )` is equivalent. |
| `COUNTIF(range, criteria)` | direct | `count_if ( [T::x] > 5 , [T::x] )` | Criteria per [**E11**](#how-to-read-the-tables). A **blank** criterion (`"="` or `""`) must count a different column: `count_if ( isnull ( [T::x] ) , [T::key] )` — `count_if ( isnull ( [T::x] ) , [T::x] )` is always 0, because it counts non-null values of `[T::x]`. Text criteria are case-insensitive in Excel. |
| `COUNTIFS(criteria_range1, criteria1, ...)` | direct | `count_if ( c1 and c2 , [T::key] )` | Counts rows, so the counted column should be a non-null key, the same rule the Ossie map gives for `COUNT(*)`. |
| `COVARIANCE.P(array1, array2)` | direct | `( sum ( [x] * [y] ) - sum ( [x] ) * sum ( [y] ) / count ( [x] ) ) / count ( [x] )` | Population covariance by the computational identity. Pairing caveat as `CORREL`. Fallback `sql_double_aggregate_op ( "COVAR_POP({0}, {1})" , [x] , [y] )`. |
| `COVARIANCE.S(array1, array2)` | direct | `( sum ( [x] * [y] ) - sum ( [x] ) * sum ( [y] ) / count ( [x] ) ) / ( count ( [x] ) - 1 )` | Sample covariance. Fallback `COVAR_SAMP`. The identity can lose precision when the mean is large relative to the spread; the warehouse function is numerically safer. |
| `DEVSQ(number1, ...)` | direct | `variance ( [x] ) * ( count ( [x] ) - 1 )` | Sum of squared deviations is the sample variance times *n − 1* — exact, and needs no level-of-detail mean. |
| `EXPON.DIST(x, lambda, cumulative)` | direct | CDF: `1 - exp ( -1 * [lambda] * [x] )`; PDF: `[lambda] * exp ( -1 * [lambda] * [x] )` | Closed form on both branches ([**E17**](#statistical)). |
| `F.DIST(x, deg_freedom1, deg_freedom2, cumulative)` | **unmappable** | — | Needs the incomplete beta function. |
| `F.DIST.RT(x, deg_freedom1, deg_freedom2)` | **unmappable** | — | As `F.DIST`. |
| `F.INV(probability, deg_freedom1, deg_freedom2)` | **unmappable** | — | As `F.DIST`. |
| `F.INV.RT(probability, deg_freedom1, deg_freedom2)` | **unmappable** | — | As `F.DIST`. |
| `F.TEST(array1, array2)` | **unmappable** | — | The variance ratio is native; the p-value needs the F CDF. |
| `FISHER(x)` | direct | `0.5 * ln ( ( 1 + [x] ) / ( 1 - [x] ) )` |  |
| `FISHERINV(y)` | direct | `( exp ( 2 * [y] ) - 1 ) / ( exp ( 2 * [y] ) + 1 )` |  |
| `FORECAST(x, known_y's, known_x's)` | direct | as `FORECAST.LINEAR` | Also in Compatibility; rowed here. Identical to `FORECAST.LINEAR`. |
| `FORECAST.ETS(target_date, values, timeline, ...)` | **unmappable** | — | Exponential triple smoothing (AAA ETS) fitted per call. No native or warehouse *function*; Snowflake's ML forecasting is a separately trained object, not an expression. |
| `FORECAST.ETS.CONFINT(...)` | **unmappable** | — | As `FORECAST.ETS`. |
| `FORECAST.ETS.SEASONALITY(...)` | **unmappable** | — | As `FORECAST.ETS`. |
| `FORECAST.ETS.STAT(...)` | **unmappable** | — | As `FORECAST.ETS`. |
| `FORECAST.LINEAR(x, known_y's, known_x's)` | direct | `[formula_Intercept] + [formula_Slope] * [new_x]` | Least-squares prediction from the `INTERCEPT` and `SLOPE` rows, referenced by formula id. `new_x` is a literal or a runtime parameter; a parameter keeps the formula native but makes it non-portable to static SQL (formula reference, *Runtime Parameters*). |
| `FREQUENCY(data_array, bins_array)` | **unmappable** | — | Returns a spilled array of bin counts ([**E6**](#how-to-read-the-tables)). The *analysis* is native — a bucketing formula (`if ( [x] <= 10 ) then '0-10' else if …`) plus `count` in a search — but that is a Model attribute and an Answer, not a translation of this function. |
| `GAMMA(number)` | **unmappable** | — | No gamma function natively or in Snowflake. |
| `GAMMA.DIST(x, alpha, beta, cumulative)` | **unmappable** | — | As `GAMMA`. |
| `GAMMA.INV(probability, alpha, beta)` | **unmappable** | — | As `GAMMA`. |
| `GAMMALN(x)` | **unmappable** | — | As `GAMMA`. |
| `GAMMALN.PRECISE(x)` | **unmappable** | — | As `GAMMA`. |
| `GAUSS(z)` | **unmappable** | — | `NORM.S.DIST(z) − 0.5`; needs the normal CDF ([**E17**](#statistical)). |
| `GEOMEAN(number1, ...)` | direct | `exp ( average ( ln ( [x] ) ) )` | Exact for positive values; Excel errors on any value ≤ 0, while `ln` of a non-positive value yields NULL or a warehouse error. |
| `GROWTH(known_y's, [known_x's], [new_x's], [const])` | **unmappable** | — | Array-returning exponential regression ([**E6**](#how-to-read-the-tables)). The single-prediction case is `exp ( )` of a `FORECAST.LINEAR` over `ln ( [y] )`, which is native. |
| `HARMEAN(number1, ...)` | direct | `count ( [x] ) / sum ( 1 / [x] )` | Positive values only, as Excel. |
| `HYPGEOM.DIST(sample_s, number_sample, population_s, number_pop, cumulative)` | **unmappable** | — | CDF is a sum; the PMF is a ratio of `COMBIN` pass-throughs. |
| `INTERCEPT(known_y's, known_x's)` | direct | `average ( [y] ) - [formula_Slope] * average ( [x] )` | References the `SLOPE` formula by id. Pairing caveat as `CORREL`. Fallback `sql_double_aggregate_op ( "REGR_INTERCEPT({0}, {1})" , [y] , [x] )`. **Verification:** hand-derived and arithmetic-checked only — **not** import-probed and **not** result-checked against Excel on a live instance. |
| `KURT(number1, ...)` | passthrough | `sql_double_aggregate_op ( "KURTOSIS({0})" , [x] )` | **Variant: `sql_double_aggregate_op`.** A native composition from power sums exists but is long and numerically fragile. *Unverified:* that Snowflake's `KURTOSIS` uses the same bias-corrected sample excess-kurtosis estimator as Excel. |
| `LARGE(array, k)` | passthrough | `sql_double_aggregate_op ( "CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0} DESC))[{1} - 1] AS FLOAT)" , [x] , [k] )` | **Variant: `sql_double_aggregate_op`.** `k = 1` is `max ( [x] )` and the converter prefers it ([**E3**](#how-to-read-the-tables)). Duplicates are kept, as in Excel; Snowflake array subscripts are 0-based, hence `k − 1`. `k` is usually a literal and can be baked into the template. *Unverified* inside a ThoughtSpot template — the subscripted `ARRAY_AGG` shape ([Unverified](#unverified)). |
| `LINEST(known_y's, [known_x's], [const], [stats])` | **unmappable** | — | Returns an array of coefficients and statistics. Its single-regressor coefficients are the `SLOPE` and `INTERCEPT` rows. |
| `LOGEST(known_y's, [known_x's], [const], [stats])` | **unmappable** | — | As `LINEST`, exponential. |
| `LOGNORM.DIST(x, mean, standard_dev, cumulative)` | **unmappable** | — | CDF needs the normal CDF. The PDF is native: `exp ( -1 * pow ( ln ( [x] ) - [mu] , 2 ) / ( 2 * [sd] * [sd] ) ) / ( [x] * [sd] * sqrt ( 2 * 3.14159265358979 ) )`. |
| `LOGNORM.INV(probability, mean, standard_dev)` | **unmappable** | — | Needs the inverse normal CDF. |
| `MAX(number1, ...)` | direct | range: `max ( [x] )`; arguments: `greatest ( [a] , [b] )` | **`MAX` over a range is the aggregate; `MAX(B2, C2)` over cells is row-wise and must be `greatest`** ([**E7**](#how-to-read-the-tables)). ThoughtSpot `max` is aggregate-only. The common clamp `MAX(0, x)` is `greatest ( 0 , [x] )`, as in the Tableau map. |
| `MAXA(value1, ...)` | direct | `max ( [x] )` | As `AVERAGEA`: on a numeric column identical to `MAX`; on a boolean column `max ( if ( [b] ) then 1 else 0 )`. |
| `MAXIFS(max_range, criteria_range1, criteria1, ...)` | direct | `max_if ( c1 and c2 , [T::x] )` | Excel returns 0 when no row matches; `max_if` returns NULL ([**E10**](#how-to-read-the-tables)) — wrap in `ifnull ( … , 0 )` to match. |
| `MEDIAN(number1, ...)` | direct | `median ( [x] )` |  |
| `MIN(number1, ...)` | direct | range: `min ( [x] )`; arguments: `least ( [a] , [b] )` | Mirror of `MAX`. |
| `MINA(value1, ...)` | direct | `min ( [x] )` | As `MAXA`. |
| `MINIFS(min_range, criteria_range1, criteria1, ...)` | direct | `min_if ( c1 and c2 , [T::x] )` | Same 0-versus-NULL difference as `MAXIFS`. |
| `MODE.MULT(number1, ...)` | **unmappable** | — | Returns a vertical array of every mode ([**E6**](#how-to-read-the-tables)). |
| `MODE.SNGL(number1, ...)` | passthrough | `sql_double_aggregate_op ( "MODE({0})" , [x] )` | **Variant: `sql_double_aggregate_op`.** No native mode (the Qlik map's `Mode` row agrees). **Tie-break differs:** Excel returns the tied value that occurs *first in the range*; Snowflake `MODE` picks an arbitrary one, and a Model has no "first" ([**E6**](#how-to-read-the-tables)). |
| `NEGBINOM.DIST(number_f, number_s, probability_s, cumulative)` | **unmappable** | — | As `BINOM.DIST`. |
| `NORM.DIST(x, mean, standard_dev, cumulative)` | **unmappable** | — | Classified on the CDF form, which needs `erf`. The PDF is native: `exp ( -1 * pow ( [x] - [mu] , 2 ) / ( 2 * [sd] * [sd] ) ) / ( [sd] * sqrt ( 2 * 3.14159265358979 ) )` ([**E17**](#statistical)). |
| `NORM.INV(probability, mean, standard_dev)` | **unmappable** | — | Inverse normal CDF. A **literal** probability folds to a constant at conversion time, as `CONFIDENCE.NORM`. |
| `NORM.S.DIST(z, cumulative)` | **unmappable** | — | As `NORM.DIST`; PDF is the `PHI` row. |
| `NORM.S.INV(probability)` | **unmappable** | — | As `NORM.INV`. |
| `PEARSON(array1, array2)` | direct | as `CORREL` | Excel documents the two as identical. |
| `PERCENTILE.EXC(array, k)` | passthrough | `sql_double_aggregate_op ( "CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0}))[FLOOR(0.9 * (COUNT({0}) + 1)) - 1] AS FLOAT) + (0.9 * (COUNT({0}) + 1) - FLOOR(0.9 * (COUNT({0}) + 1))) * (COALESCE(CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0}))[FLOOR(0.9 * (COUNT({0}) + 1))] AS FLOAT), CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0}))[FLOOR(0.9 * (COUNT({0}) + 1)) - 1] AS FLOAT)) - CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0}))[FLOOR(0.9 * (COUNT({0}) + 1)) - 1] AS FLOAT))" , [x] )` | **Variant: `sql_double_aggregate_op`.** No single warehouse function — `PERCENTILE_CONT` is the *inclusive* method — so the template does Excel's exclusive interpolation by hand on the sorted array, the same `ARRAY_AGG` indexing as `LARGE`/`SMALL`: rank `h = k(n + 1)`, value `x[⌊h⌋] + (h − ⌊h⌋)(x[⌊h⌋+1] − x[⌊h⌋])` (1-based; the template subtracts 1 for Snowflake's 0-based subscripts, and `COALESCE` covers `h = n`, where the upper element is out of range). `k` is baked in (0.9 shown). Excel returns `#NUM!` for `k` outside `[1/(n+1), n/(n+1)]`; the template returns NULL or an edge value instead. *Unverified* as `LARGE`. |
| `PERCENTILE.INC(array, k)` | passthrough | `sql_double_aggregate_op ( "PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY {0})" , [x] )` | **Variant: `sql_double_aggregate_op`.** `PERCENTILE_CONT` uses the same linear interpolation at rank `k(n − 1) + 1` as Excel's inclusive method. `k = 0.5` is `median ( [x] )` and the converter prefers it ([**E3**](#how-to-read-the-tables)); `k` is baked into the template, as in the Ossie map. |
| `PERCENTRANK.EXC(array, x, [significance])` | passthrough | `sql_double_aggregate_op ( "RANK() OVER (ORDER BY SUM({0})) / (COUNT(*) OVER () + 1)" , [x] )` | **Variant: `sql_double_aggregate_op`.** Read per row as the rank of each row's value in the column ([**E5**](#how-to-read-the-tables)). Excel truncates to 3 significant digits by default; add `FLOOR(… * 1000) / 1000` to match. The operand is aggregated inside the window (`ORDER BY SUM({0})`) per the formula reference's *Window functions inside `sql_*_aggregate_op`* rules; *unverified* on a live search, and the window is global, so it is right only when the search returns one row per value. |
| `PERCENTRANK.INC(array, x, [significance])` | direct | `floor ( ( 1 - rank_percentile ( sum ( [x] ) , 'asc' ) / 100 ) * 1000 ) / 1000` | `rank_percentile` is documented as `(1 − PERCENT_RANK()) × 100`, so the inversion and rescale give `PERCENT_RANK`, which is Excel's inclusive formula `(rank − 1)/(n − 1)`; the `floor ( … * 1000 ) / 1000` reproduces Excel's default 3-digit truncation. Same global-only, query-grain restriction as the Ossie map's `PERCENT_RANK` row: correct when the search returns one row per value. A scalar `x` that is not itself in the column (Excel interpolates) has no native form. |
| `PERMUT(number, number_chosen)` | passthrough | `sql_double_op ( "FACTORIAL({0}) / FACTORIAL({0} - {1})" , [n] , [k] )` | **Variant: `sql_double_op`.** Overflow as `COMBIN`. |
| `PERMUTATIONA(number, number_chosen)` | direct | `pow ( [n] , [k] )` | Permutations with repetition are `n^k`. |
| `PHI(x)` | direct | `exp ( -0.5 * [x] * [x] ) / sqrt ( 2 * 3.14159265358979 )` | Standard normal density — closed form. |
| `POISSON.DIST(x, mean, cumulative)` | **unmappable** | — | CDF is a sum over 0…x. The PMF passes through: `sql_double_op ( "EXP(-{1}) * POWER({1}, {0}) / FACTORIAL({0})" , [k] , [lambda] )`. |
| `PROB(x_range, prob_range, [lower_limit], [upper_limit])` | direct | `sum_if ( [T::x] between [lo] and [hi] , [T::p] )` | Probability mass inside a range is a conditional sum. Without `upper_limit`, the condition is `[T::x] = [lo]`. |
| `QUARTILE.EXC(array, quart)` | passthrough | `sql_double_aggregate_op ( "CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0}))[FLOOR(0.25 * (COUNT({0}) + 1)) - 1] AS FLOAT) + (0.25 * (COUNT({0}) + 1) - FLOOR(0.25 * (COUNT({0}) + 1))) * (COALESCE(CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0}))[FLOOR(0.25 * (COUNT({0}) + 1))] AS FLOAT), CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0}))[FLOOR(0.25 * (COUNT({0}) + 1)) - 1] AS FLOAT)) - CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0}))[FLOOR(0.25 * (COUNT({0}) + 1)) - 1] AS FLOAT))" , [x] )` | **Variant: `sql_double_aggregate_op`.** `PERCENTILE.EXC` at `quart / 4` (`quart = 1` shown). *Unverified* as `LARGE`. |
| `QUARTILE.INC(array, quart)` | passthrough | `sql_double_aggregate_op ( "PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {0})" , [x] )` | **Variant: `sql_double_aggregate_op`.** `PERCENTILE.INC` at `quart / 4`. `quart = 0` is `min`, `2` is `median`, `4` is `max` — all native, preferred ([**E3**](#how-to-read-the-tables)). |
| `RANK.AVG(number, ref, [order])` | passthrough | `sql_double_aggregate_op ( "RANK() OVER (ORDER BY SUM({0}) DESC) + (COUNT(*) OVER (PARTITION BY SUM({0})) - 1) / 2" , [x] )` | **Variant: `sql_double_aggregate_op`.** Ties get the average of the ranks they span. ThoughtSpot's `rank` is competition rank (`RANK.EQ`), so not a substitute. Operand aggregated inside both windows (`SUM({0})`), per the formula reference's window rules; *unverified* on a live search. Global ordering only — a ranking over a subset needs a `PARTITION BY` and the `group_aggregate` wrapping. |
| `RANK.EQ(number, ref, [order])` | direct | `rank ( sum ( [x] ) , 'desc' )` | Competition rank on both sides. `order = 0` (the default) is descending; non-zero is `'asc'`. **Global only** — `rank` has a fixed arity of two (live-proven in the Ossie map), so an Excel rank over a *subset* range (one region's rows) has no native form and falls back to the partitioned pass-through with `group_aggregate` wrapping (formula reference, *Rank Functions*). |
| `RSQ(known_y's, known_x's)` | direct | `pow ( [formula_Correl] , 2 )` | Square of Pearson's *r*; references the `CORREL` formula. |
| `SKEW(number1, ...)` | passthrough | `sql_double_aggregate_op ( "SKEW({0})" , [x] )` | **Variant: `sql_double_aggregate_op`.** *Unverified* that Snowflake `SKEW` is Excel's adjusted sample estimator. |
| `SKEW.P(number1, ...)` | passthrough | `sql_double_aggregate_op ( "SKEW({0}) * (COUNT({0}) - 2) / SQRT(COUNT({0}) * (COUNT({0}) - 1))" , [x] )` | **Variant: `sql_double_aggregate_op`.** Converts the sample estimator to the population one; valid only if `SKEW` is the adjusted sample form (as above). |
| `SLOPE(known_y's, known_x's)` | direct | `[formula_Covariance S] / variance ( [x] )` | Sample covariance over sample variance of `x`. Pairing caveat as `CORREL`; fallback `REGR_SLOPE` pass-through. |
| `SMALL(array, k)` | passthrough | `sql_double_aggregate_op ( "CAST((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0} ASC))[{1} - 1] AS FLOAT)" , [x] , [k] )` | **Variant: `sql_double_aggregate_op`.** Mirror of `LARGE`; `k = 1` is `min ( [x] )`. *Unverified* as `LARGE`. |
| `STANDARDIZE(x, mean, standard_dev)` | direct | `( [x] - [mean] ) / [sd]` | Scalar arguments. When `mean` and `sd` are the column's own, they are `group_aggregate ( average ( [x] ) , query_groups ( ) , query_filters ( ) )` and the `group_stddev` equivalent. |
| `STDEV.P(number1, ...)` | direct | `sqrt ( variance ( [x] ) * ( count ( [x] ) - 1 ) / count ( [x] ) )` | **ThoughtSpot `stddev` is sample-only.** Population variance is sample variance times `(n − 1)/n`, an exact identity, so this is `direct` per [**E2**](#how-to-read-the-tables) — the Ossie map classes `STDDEV_POP` as `passthrough` and should be revisited (gap [**G5**](#open-questions--gaps)). Edge case: for a single value `variance` is NULL while Excel's `STDEV.P` is 0. Substituting plain `stddev` would silently change the divisor. **Verification:** hand-derived and arithmetic-checked only — **not** import-probed and **not** result-checked against Excel on a live instance. |
| `STDEV.S(number1, ...)` | direct | `stddev ( [x] )` | Sample standard deviation on both sides. |
| `STDEVA(value1, ...)` | direct | `stddev ( [x] )` | As `AVERAGEA` for type handling. |
| `STDEVPA(value1, ...)` | direct | as `STDEV.P` | As `AVERAGEA` for type handling. |
| `STEYX(known_y's, known_x's)` | direct | `sqrt ( ( count ( [y] ) - 1 ) / ( count ( [y] ) - 2 ) * variance ( [y] ) * ( 1 - pow ( [formula_Correl] , 2 ) ) )` | Standard error of the regression estimate by the identity `s²_y·(n−1)(1−r²)/(n−2)`. |
| `T.DIST(x, deg_freedom, cumulative)` | **unmappable** | — | Needs the incomplete beta function. |
| `T.DIST.2T(x, deg_freedom)` | **unmappable** | — | As `T.DIST`. |
| `T.DIST.RT(x, deg_freedom)` | **unmappable** | — | As `T.DIST`. |
| `T.INV(probability, deg_freedom)` | **unmappable** | — | As `T.DIST`. |
| `T.INV.2T(probability, deg_freedom)` | **unmappable** | — | As `T.DIST`. |
| `T.TEST(array1, array2, tails, type)` | **unmappable** | — | The t statistic is native; the p-value needs the t CDF. |
| `TREND(known_y's, [known_x's], [new_x's], [const])` | **unmappable** | — | Array-returning ([**E6**](#how-to-read-the-tables)). The single-value case is `FORECAST.LINEAR`. |
| `TRIMMEAN(array, percent)` | passthrough | `sql_double_aggregate_op ( "REDUCE(ARRAY_SLICE((ARRAY_AGG({0}) WITHIN GROUP (ORDER BY {0})), FLOOR(COUNT({0}) * 0.2 / 2), COUNT({0}) - FLOOR(COUNT({0}) * 0.2 / 2)), CAST(0 AS FLOAT), (acc, v) -> acc + CAST(v AS FLOAT)) / (COUNT({0}) - 2 * FLOOR(COUNT({0}) * 0.2 / 2))" , [x] )` | **Variant: `sql_double_aggregate_op`.** Excel drops `⌊n × percent / 2⌋` values from **each** tail (the excluded count is rounded down to an even number), then averages the rest; the template slices the sorted array and sums the slice. `percent` is baked in (0.2 shown). Doubly *unverified*: the subscripted/sliced `ARRAY_AGG` shape as `LARGE`, and Snowflake's higher-order `REDUCE` with a lambda inside a ThoughtSpot template ([Unverified](#unverified)). |
| `VAR.P(number1, ...)` | direct | `variance ( [x] ) * ( count ( [x] ) - 1 ) / count ( [x] )` | As `STDEV.P`, without the root. **Verification:** hand-derived and arithmetic-checked only — **not** import-probed and **not** result-checked against Excel on a live instance. |
| `VAR.S(number1, ...)` | direct | `variance ( [x] )` |  |
| `VARA(value1, ...)` | direct | `variance ( [x] )` | As `AVERAGEA` for type handling. |
| `VARPA(value1, ...)` | direct | as `VAR.P` | As `AVERAGEA` for type handling. |
| `WEIBULL.DIST(x, alpha, beta, cumulative)` | direct | CDF: `1 - exp ( -1 * pow ( [x] / [beta] , [alpha] ) )`; PDF: `[alpha] / pow ( [beta] , [alpha] ) * pow ( [x] , [alpha] - 1 ) * exp ( -1 * pow ( [x] / [beta] , [alpha] ) )` | Closed form on both branches. |
| `Z.TEST(array, x, [sigma])` | **unmappable** | — | The z statistic is native; the p-value needs the normal CDF. |

---

## Text

Source: the *Text functions* list. `CONCATENATE` is also listed under Compatibility and is rowed
here. ThoughtSpot's native string functions are `concat`, `substr` (0-based), `left`, `right`,
`strlen`, `strpos` (1-based, 0 when absent) and `contains` — and nothing else: `trim`, `ltrim`,
`rtrim`, `replace`, `upper`, `lower`, `starts_with` and `ends_with` are live-verified **absent**
(formula reference, BL-170/BL-171).

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ARRAYTOTEXT(array, [format])` | **unmappable** | — | Serialises a cell array ([**E6**](#how-to-read-the-tables)). The down-a-column reading is string aggregation — the `TEXTJOIN` pass-through. |
| `ASC(text)` | **unmappable** | — | Full-width → half-width conversion for DBCS locales. No native or Snowflake function. |
| `BAHTTEXT(number)` | **unmappable** | — | Spells a number as Thai baht text. |
| `CHAR(number)` | passthrough | `sql_string_op ( "CHR({0})" , [n] )` | **Variant: `sql_string_op`.** As the Tableau map's `CHAR` row. Excel `CHAR` uses the platform code page (Windows-1252 on Windows) while `CHR` takes a Unicode code point, so codes 128–159 differ; 1–127 agree. Translator: a literal code 1–127 is TRANSLATED; 128–255 is APPROXIMATED with the code-page trap, since Mac Excel uses Mac Roman (Windows-1252 and Unicode agree on 160–255: `CHR(233)` is `é`, `CHR(150)` is U+0096 where Windows-1252 150 is an en dash; probe record §7, live 2026-10-07); a column is APPROXIMATED with the same trap. |
| `CLEAN(text)` | passthrough | `sql_string_op ( "REGEXP_REPLACE({0}, '[[:cntrl:]]', '')" , [s] )` | **Variant: `sql_string_op`.** Excel removes code points 0–31 only; the POSIX `[:cntrl:]` class also removes 127. *Unverified:* POSIX bracket classes in Snowflake's regex dialect. |
| `CODE(text)` | passthrough | `sql_int_op ( "UNICODE({0})" , [s] )` | **Variant: `sql_int_op`.** First character's code; code-page caveat as `CHAR`. **Not `ASCII`**: Snowflake `ASCII` returns the first UTF-8 *byte* (`ASCII('é')` = 195; `UNICODE` = 233, Excel 233; probe record §7, live 2026-10-07). Empty text is `#VALUE!` in Excel and 0 here. |
| `CONCAT(text1, ...)` | direct | `concat ( [a] , [b] , ... )` | **`+` does not concatenate in ThoughtSpot**, so `&` lands here too. Classified on the dominant use — joining cells of one row ([**E7**](#how-to-read-the-tables)). `CONCAT(A2:A100)` over a column is string aggregation and falls back to the `TEXTJOIN` pass-through with an empty delimiter ([**E3**](#how-to-read-the-tables)). **NULL trap:** Excel treats a blank as `""`; warehouse `CONCAT` returns NULL if any argument is NULL, so wrap nullable operands in `ifnull ( [a] , '' )` ([**E10**](#how-to-read-the-tables)). **Every `concat` argument must be Text** (live-verified 2026-10-06, [probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)): a number is rejected (*"concat expects 2nd argument to be Text"*), so wrap it in `to_string ( [n] )` — and only it: `to_string` rejects a Text argument. `concat` takes N arguments, so a `&` chain is one flat `concat`. **Non-text operands** (translator, fidelity M1): a number is `to_string ( [x] )`; a boolean is `if ( [b] ) then 'TRUE' else 'FALSE'` — `to_string` gives lower-case `true` (BL-349); a date is its serial number, `to_string ( diff_days ( [d] , to_date ( '1899-12-30' , '%Y-%m-%d' ) ) )`, because Excel's `&` reads a date as a number (BL-350). See [Implicit type coercion](#implicit-type-coercion-not-counted--arguments). |
| `CONCATENATE(text1, ...)` | direct | `concat ( [a] , [b] , ... )` | As `CONCAT`, without range support. Also in Compatibility; rowed here. |
| `DBCS(text)` | **unmappable** | — | Half-width → full-width; as `ASC`. |
| `DETECTLANGUAGE(text)` | **unmappable** | — | AI language detection. No native function and no single Snowflake function returns a language code. |
| `DOLLAR(number, [decimals])` | passthrough | `sql_string_op ( "TO_CHAR({0}, '$999,999,999,990.00')" , [x] )` | **Variant: `sql_string_op`.** Number-to-currency-text. Usually the wrong layer: a ThoughtSpot column's display format does this without turning a measure into text (which stops it aggregating). The currency symbol and separators are locale-dependent in Excel and fixed in the template. |
| `EXACT(text1, text2)` | passthrough | `sql_bool_op ( "{0} = {1}" , [a] , [b] )` | **Variant: `sql_bool_op`.** **Reclassified from `direct` 2026-10-06.** `EXACT` is case-sensitive; ThoughtSpot's native `=` is **not** — it compiles to `LOWER(a) = LOWER(b)`-style SQL and lowercases literals at compile time (live-verified 2026-10-06, se-thoughtspot — [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive)), so `[a] = [b]` answers `EXACT("Apple","apple")` with TRUE. The pass-through compares in the warehouse, case-sensitively under Snowflake's default collation; a column with a case-insensitive collation additionally needs `COLLATE 'utf8'` inside the template. Semantic gap tracked as BL-333. |
| `FIND(find_text, within_text, [start_num])` | passthrough | `sql_int_op ( "POSITION({0} IN {1})" , [find] , [within] )` | **Variant: `sql_int_op`.** **Reclassified from `direct` 2026-10-06.** `FIND` is case-sensitive; native `strpos` is **not** — it compiles to `POSITION('x' IN LOWER(s))` with the literal lowercased (live-verified 2026-10-06, se-thoughtspot — [probe record §4](../reviews/2026-10-06-formula-semantics-probes.md#4-string-comparison-is-case-insensitive-bl-333), [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive); BL-333). `strpos ( [within] , [find] )` (haystack first) remains the native form when the data's case is consistent, and is the right mapping for `SEARCH`. Both are 1-based and return **0** when absent, where Excel returns `#VALUE!` — so `ISNUMBER(FIND(x, s))` becomes `sql_int_op ( "POSITION({0} IN {1})" , 'x' , [s] ) > 0` ([**E8**](#how-to-read-the-tables)). `start_num > 1` is `sql_int_op ( "POSITION({0}, {1}, {2})" , [find] , [within] , [start] )` (Snowflake's three-argument form; `POSITION(… IN … FROM n)` is not valid Snowflake) or `CHARINDEX({0}, {1}, {2})` ([**E3**](#how-to-read-the-tables)). |
| `FINDB(find_text, within_text, [start_num])` | passthrough | as `FIND` | **Variant: `sql_int_op`.** Reclassified with `FIND` 2026-10-06. The `B` variants count double-byte characters as 2 only when a DBCS language is the Excel default; otherwise they are identical to the plain functions, which is the covered case ([**E3**](#how-to-read-the-tables)). The DBCS byte count has no warehouse equivalent (UTF-8 `OCTET_LENGTH` is a different count). Translator (the `B` rows): the plain function's rule, APPROXIMATED with the DBCS trap. |
| `FIXED(number, [decimals], [no_commas])` | passthrough | `sql_string_op ( "TO_CHAR(ROUND({0}, 2), '999,999,999,990.00')" , [x] )` | **Variant: `sql_string_op`.** With `no_commas = TRUE`, `to_string ( round ( [x] , 0.01 ) )` is native but does not pad trailing zeros. Display-format caveat as `DOLLAR`. |
| `LEFT(text, [num_chars])` | direct | `left ( [s] , n )` | Default `num_chars` is 1. A DOUBLE count is `floor ( [n] )` (BL-355). |
| `LEFTB(text, [num_bytes])` | direct | as `LEFT`: `left ( [s] , [n] )` | As `FINDB`. |
| `LEN(text)` | direct | `strlen ( [s] )` | **There is no `len`** (live-verified absent, Qlik map S01). Trailing spaces count on both sides. `LEN` of a number counts its displayed digits in Excel; `strlen ( to_string ( [x] ) )` may differ by format. Translator: a number is `strlen ( to_string ( [x] ) )`, a date its serial's digits (BL-350). |
| `LENB(text)` | direct | as `LEN`: `strlen ( [s] )` | As `FINDB`. |
| `LOWER(text)` | passthrough | `sql_string_op ( "LOWER({0})" , [s] )` | **Variant: `sql_string_op`.** No native `lower` (formula reference, verified 2026-06-13). |
| `MID(text, start_num, num_chars)` | direct | `substr ( [s] , [start] - 1 , [n] )` | **Index base differs** — Excel is 1-based, `substr` is 0-based, so the `− 1` is mandatory (the Qlik and Tableau maps' `Mid`/`MID` rows). **A DOUBLE start or count is rejected** by `substr` (*expects 2nd argument to be Numeric* — an integer); Excel truncates a fractional one, so the translator emits `floor ( [start] ) - 1` / `floor ( [n] )`, and truncates a literal (BL-355, fidelity M1). |
| `MIDB(text, start_num, num_bytes)` | direct | as `MID`: `substr ( [s] , [start] - 1 , [n] )` | As `FINDB`. |
| `NUMBERVALUE(text, [decimal_separator], [group_separator])` | direct | `to_double ( [s] )` | Covers the default separators ([**E3**](#how-to-read-the-tables)). **`to_double` fails the whole query on text that is not a number** (live 2026-10-07, [**E8**](#how-to-read-the-tables)); for the null-on-failure reading of `#VALUE!` use `sql_double_op ( "TRY_TO_DOUBLE({0})" , [s] )`. Custom separators need `sql_double_op ( "TO_DOUBLE(REPLACE(REPLACE({0}, '.', ''), ',', '.'))" , [s] )`. Excel also accepts a trailing `%` (divides by 100); `to_double` does not. |
| `PHONETIC(reference)` | **unmappable** | — | Extracts Japanese furigana stored as cell metadata. |
| `PROPER(text)` | passthrough | `sql_string_op ( "INITCAP({0})" , [s] )` | **Variant: `sql_string_op`.** As the Tableau map's `PROPER` row. Excel capitalises after **any** non-letter (`o'neil` → `O'Neil`, `2-way` → `2-Way`); Snowflake `INITCAP`'s default delimiter set is close but not identical. |
| `REGEXEXTRACT(text, pattern, [return_mode], [case_sensitivity])` | passthrough | `sql_string_op ( "REGEXP_SUBSTR({0}, {1})" , [s] , [pattern] )` | **Variant: `sql_string_op`.** `return_mode = 0` (first match) only; modes 1 (all matches) and 2 (capture groups) return arrays and are unmappable. **Pattern dialect differs:** Excel uses PCRE2, Snowflake POSIX ERE with Perl-style escapes — no look-arounds, no lazy quantifiers. `case_sensitivity = 1` adds the `'i'` parameter. |
| `REGEXREPLACE(text, pattern, replacement, [occurrence], [case_sensitivity])` | passthrough | `sql_string_op ( "REGEXP_REPLACE({0}, {1}, {2})" , [s] , [pattern] , [repl] )` | **Variant: `sql_string_op`.** `occurrence` maps to `REGEXP_REPLACE`'s fifth argument (0 = all, Excel's default). Dialect caveat as `REGEXEXTRACT`; backreferences are `$1` in Excel and `\\1` in Snowflake. |
| `REGEXTEST(text, pattern, [case_sensitivity])` | passthrough | `sql_bool_op ( "REGEXP_INSTR({0}, {1}) > 0" , [s] , [pattern] )` | **Variant: `sql_bool_op`.** **Not `REGEXP_LIKE`.** Excel tests for a match *anywhere* in the text; Snowflake `REGEXP_LIKE` implicitly anchors the pattern to the **whole** string, so `REGEXP_LIKE('abc', 'b')` is false where `REGEXTEST("abc", "b")` is TRUE. `REGEXP_INSTR(…) > 0` is the search semantics. |
| `REPLACE(old_text, start_num, num_chars, new_text)` | direct | `concat ( left ( [s] , [start] - 1 ) , [new] , substr ( [s] , [start] - 1 + [n] , strlen ( [s] ) ) )` | **Excel `REPLACE` is positional, not SQL `REPLACE`.** It overwrites `num_chars` characters starting at `start_num`; substring substitution is `SUBSTITUTE`. Mapping it to `sql_string_op ( "REPLACE(…)" )` — the reflex from every other map in this repo — produces a valid formula with a different meaning. The composition uses only native functions (`substr` 0-based, so the tail starts at `start − 1 + n`). |
| `REPLACEB(old_text, start_num, num_bytes, new_text)` | direct | as `REPLACE`: `concat ( left ( [s] , [start] - 1 ) , [new] , substr ( [s] , [start] - 1 + [n] , strlen ( [s] ) ) )` | As `FINDB`. |
| `REPT(text, number_times)` | passthrough | `sql_string_op ( "REPEAT({0}, {1})" , [s] , [n] )` | **Variant: `sql_string_op`.** The Snowflake map records that the CLI emits a native `repeat` which is **unverified** (BL-226); the pass-through does not depend on it. |
| `RIGHT(text, [num_chars])` | direct | `right ( [s] , n )` | A DOUBLE count is `floor ( [n] )` (BL-355). |
| `RIGHTB(text, [num_bytes])` | direct | as `RIGHT`: `right ( [s] , [n] )` | As `FINDB`. |
| `SEARCH(find_text, within_text, [start_num])` | direct | `strpos ( [within] , [find] )` | **Reclassified from `passthrough` 2026-10-06.** **`SEARCH` is case-insensitive and supports wildcards; `FIND` is neither.** Native `strpos` is case-insensitive — it compiles to `POSITION('x' IN LOWER(s))`, literal lowercased at compile time (live-verified 2026-10-06, se-thoughtspot — [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive)) — so it is exactly `SEARCH` for a wildcard-free `find_text` (**operand order reversed**, haystack first). Wildcards `?`/`*` (escaped `~`) fall back to `sql_int_op ( "REGEXP_INSTR({1}, {0}, 1, 1, 0, 'i')" , [pattern] , [within] )` with the pattern translated ([**E3**](#how-to-read-the-tables)). Not-found is 0, not `#VALUE!` ([**E8**](#how-to-read-the-tables)). With `start_num`: `sql_int_op ( "POSITION(LOWER({0}), LOWER({1}), {2})" , [find] , [within] , [start] )` — `strpos`'s own compiled form with Snowflake's start position (translator). |
| `SEARCHB(find_text, within_text, [start_num])` | direct | as `SEARCH`: `strpos ( [within] , [find] )`; with `start_num`, `sql_int_op ( "POSITION(LOWER({0}), LOWER({1}), {2})" , … )` | As `FINDB`. Reclassified with `SEARCH` 2026-10-06. |
| `SUBSTITUTE(text, old_text, new_text, [instance_num])` | passthrough | `sql_string_op ( "REPLACE({0}, {1}, {2})" , [s] , [old] , [new] )` | **Variant: `sql_string_op`.** This is the function SQL `REPLACE` actually corresponds to — all occurrences, case-sensitive, on both sides. There is no native `replace` (BL-170). `instance_num` needs `REGEXP_REPLACE({0}, {1}, {2}, 1, {3})` with `old_text` regex-escaped. |
| `T(value)` | direct | text column: `[s]`; other types: `''` | Returns the value if it is text, else `""`. Resolved from the column's type ([**E15**](#how-to-read-the-tables)). |
| `TEXT(value, format_text)` | passthrough | `sql_string_op ( "TO_CHAR({0}, 'YYYY-MM-DD')" , [d] )`; full day name `sql_string_op ( "INITCAP({0})" , day_of_week ( [d] ) )` (`day_of_week` returns lower case, `friday`; live 2026-10-07) | **Variant: `sql_string_op`.** Format codes are translated, not passed through — see the format-code table below. Single-token date formats have native equivalents (`"mmmm"` → `month ( [d] )`, `"dddd"` → `day_of_week ( [d] )`), but both return **lower case** names (live 2026-10-07), so the translator uses `TO_CHAR` and `INITCAP ( day_of_week … )` ([**E3**](#how-to-read-the-tables)). Like `DOLLAR`, it often belongs in a column's display format instead. **Translator:** the subset in the format-code table marked *translator*; every other code is NEEDS_REVIEW. |
| `TEXTAFTER(text, delimiter, [instance_num], [match_mode], [match_end], [if_not_found])` | direct | `if ( strpos ( [s] , [d] ) > 0 ) then substr ( [s] , strpos ( [s] , [d] ) - 1 + strlen ( [d] ) , strlen ( [s] ) ) else ''` | First-instance, case-sensitive form ([**E3**](#how-to-read-the-tables)). Not-found is `#N/A` in Excel; the `else` must be type-matched, so it carries `if_not_found` or `''`. Other instances and case-insensitive `match_mode` fall back to `sql_string_op ( "SUBSTR({0}, REGEXP_INSTR({0}, {1}, 1, {2}, 1))" , [s] , [d] , [n] )` with the delimiter regex-escaped. |
| `TEXTBEFORE(text, delimiter, [instance_num], ...)` | direct | `if ( strpos ( [s] , [d] ) > 0 ) then left ( [s] , strpos ( [s] , [d] ) - 1 ) else ''` | Mirror of `TEXTAFTER`, same fallback shape. |
| `TEXTJOIN(delimiter, ignore_empty, text1, ...)` | passthrough | `sql_string_aggregate_op ( "LISTAGG({0}, ', ') WITHIN GROUP (ORDER BY {0})" , [s] )` | **Variant: `sql_string_aggregate_op`.** Classified on the range reading ([**E5**](#how-to-read-the-tables)) — joining a column down its rows is string aggregation, and ThoughtSpot has none (the Qlik map's `Concat` row). Flag per the aggregate pass-through policy (PT1). Excel joins in sheet order; a Model has no row order, so `WITHIN GROUP (ORDER BY …)` must name one ([**E6**](#how-to-read-the-tables)). Joining cells across one row is native `concat` with the delimiter interleaved; `ignore_empty = TRUE` then needs an `if ( isnull … )` guard per operand. `LISTAGG` skips NULLs, which is `ignore_empty = TRUE`. |
| `TEXTSPLIT(text, col_delimiter, [row_delimiter], ...)` | **unmappable** | — | Returns a spilled array ([**E6**](#how-to-read-the-tables)). One token is `sql_string_op ( "SPLIT_PART({0}, {1}, {2})" , [s] , [d] , [n] )`, as the Ossie map's `SPLIT_PART` — but that is `INDEX(TEXTSPLIT(…), n)`, not `TEXTSPLIT`. |
| `TRANSLATE(text, [source_language], [target_language])` | passthrough | `sql_string_op ( "SNOWFLAKE.CORTEX.TRANSLATE({0}, 'en', 'de')" , [s] )` | **Variant: `sql_string_op`.** Excel's `TRANSLATE` is **machine translation between languages** — not SQL `TRANSLATE`, which maps characters, and mapping by name would silently do the wrong thing. Snowflake Cortex's function is the semantic match. Caveats: per-row LLM cost on every query, non-deterministic output, and Cortex availability by region. *Unverified* inside a `sql_*_op` template. |
| `TRIM(text)` | passthrough | `sql_string_op ( "TRIM(REGEXP_REPLACE({0}, ' +', ' '))" , [s] )` | **Variant: `sql_string_op`.** **Excel `TRIM` also collapses runs of internal spaces to one**; SQL `TRIM` only strips the ends. A bare `TRIM({0})` template imports and leaves `"a␣␣b"` as `"a␣␣b"` where Excel returns `"a␣b"`. Excel removes only the ASCII space (32), not the non-breaking space (160); the regex above matches that. No native `trim` (BL-170). |
| `UNICHAR(number)` | passthrough | `sql_string_op ( "CHR({0})" , [n] )` | **Variant: `sql_string_op`.** Snowflake `CHR` takes a Unicode code point, which is exactly `UNICHAR`. `UNICHAR(0)` is `#VALUE!` and a surrogate (55296–57343) `#N/A` in Excel: NEEDS_REVIEW as a literal, a trap on a column. |
| `UNICODE(text)` | passthrough | `sql_int_op ( "UNICODE({0})" , [s] )` | **Variant: `sql_int_op`.** Code point of the first character. Empty text is `#VALUE!` in Excel and 0 here. |
| `UPPER(text)` | passthrough | `sql_string_op ( "UPPER({0})" , [s] )` | **Variant: `sql_string_op`.** No native `upper`. A number, boolean or date argument is converted first, as Excel does: a date is its serial number's digits (`UPPER` of 2000-01-01 is `36526`), `to_string ( diff_days ( [d] , to_date ( '1899-12-30' , '%Y-%m-%d' ) ) )` (BL-350, fidelity M1); the same for `LOWER`, `TRIM`, `LEN`, `LEFT`, `RIGHT`, `MID`, `SEARCH`, `FIND`, `EXACT`, `SUBSTITUTE`. See [Implicit type coercion](#implicit-type-coercion-not-counted--arguments). |
| `VALUE(text)` | direct | `to_double ( [s] )` | Numeric strings ([**E3**](#how-to-read-the-tables)). Excel `VALUE` also parses date, time, currency and percentage strings into serial numbers; those need `to_date` with a known format instead ([**E9**](#how-to-read-the-tables)). Translator (BL-353): a number argument is returned as is (`to_double` rejects a DOUBLE); a date is its serial, `diff_days ( [d] , to_date ( '1899-12-30' , '%Y-%m-%d' ) )`. **Non-numeric text fails the whole query** under `to_double` (Snowflake *Numeric value '…' is not recognized*, live 2026-10-07 — not NULL), so a text column is APPROXIMATED with that trap; inside `IFERROR` it is `sql_double_op ( "TRY_TO_DOUBLE({0})" , [s] )`. A non-numeric text literal is NEEDS_REVIEW (Excel `#VALUE!`), as in arithmetic. |
| `VALUETOTEXT(value, [format])` | direct | `to_string ( [x] )` | `format = 1` (strict, quoting text) adds quotes: `concat ( '"' , [s] , '"' )`. |

### `TEXT` format codes *(not counted — arguments)*

| Excel `format_text` | ThoughtSpot | Class |
|---|---|---|
| `"yyyy"` | `to_string ( year ( [d] ) )` | direct |
| `"mmmm"` | `month ( [d] )` | direct — `month` returns the name, **in lower case** (`march`, live 2026-10-07); Excel's `March` is `sql_string_op ( "TO_CHAR({0}, 'MMMM')" , [d] )`, which the translator emits. Locale-dependent on both sides. |
| `"mmm"` | `left ( month ( [d] ) , 3 )` | direct — but lower case (`mar`, live); the translator emits `TO_CHAR({0}, 'MON')` (`Mar`). |
| `"mm"` (month) | `right ( concat ( '0' , to_string ( month_number ( [d] ) ) ) , 2 )` | direct — zero-padded by composition. Excel reads `m`/`mm` as **minutes** when it follows `h` or precedes `s`; the converter must disambiguate by context. |
| `"dddd"` | `day_of_week ( [d] )` | direct — day name, **in lower case** (`friday`, live 2026-10-07): Excel's `Friday` is `sql_string_op ( "INITCAP({0})" , day_of_week ( [d] ) )` (translator). |
| `"ddd"` | `left ( day_of_week ( [d] ) , 3 )` | direct — but **lower case** (`fri`; `day_of_week` is lower case, live 2026-10-07). The translator emits `sql_string_op ( "TO_CHAR({0}, 'DY')" , [d] )`, which gives Excel's `Fri`. |
| `"dd"` | `right ( concat ( '0' , to_string ( day ( [d] ) ) ) , 2 )` | direct |
| `"yyyy-mm-dd"` and other multi-token date formats (**translator**: `yyyy` `yy` `mmmm` `mmm` `mm` `dd` `ddd` `hh` `ss` and the separators `- / : . ,` space, as `TO_CHAR`, live 2026-10-07; `dddd` alone as `INITCAP` of `day_of_week`; single `m` / `d` / `h`, `AM/PM` and `dddd` inside a longer format are NEEDS_REVIEW) | `sql_string_op ( "TO_CHAR({0}, 'YYYY-MM-DD')" , [d] )` | passthrough — tokens translated to Snowflake's format model (`yyyy`→`YYYY`, `mm`→`MM`, `dd`→`DD`, `mmm`→`MON`, `hh`→`HH24`, `mm` after `hh`→`MI`, `ss`→`SS`, `AM/PM`→`AM`). A native `concat` of the padded parts above is also exact. |
| `"0.00"`, `"0"`, `"000.00"` (any run of `0` / leading `#` before the point, `0`s after) | `sql_string_op ( "TO_CHAR({0}, 'FM9…90.00')" , [x] )`, 30 digit positions | passthrough — **translator**. Rounds half away from zero as Excel (live: 2.675 → `2.68`, −2.5 with `"0"` → `-3`). A negative value that rounds to zero prints `-0.00` (live); Excel's output there is unverified, so a column is APPROXIMATED and such a literal NEEDS_REVIEW. Text that is not a number is returned unchanged, as Excel does. A fractional `#` (`"#.##"`) is NEEDS_REVIEW |
| `"#,##0"`, `"#,##0.00"` | `sql_string_op ( "TO_CHAR({0}, 'FM999,…,990')" , [x] )` | passthrough — **translator**; group separator fixed, not locale-driven. |
| `"0%"` | `concat ( to_string ( round ( [x] * 100 , 1 ) ) , '%' )` | direct — increment 1 per [**E12**](#how-to-read-the-tables).  **Translator:** `sql_string_op ( "TO_CHAR({0} * 100, 'FM…0') || '%'" , [x] )`, which also covers `"0.0%"` and the other decimal counts. |
| `"$#,##0.00"` | as `DOLLAR` | passthrough |
| Conditional sections (`"[>1000]0,K;0"`), colour codes (`[Red]`) | — | unmappable — display rules, not text; a ThoughtSpot column's number format and conditional formatting are the home for them. |

---

## Date and time

Source: the *Date and time functions* list. ThoughtSpot's date functions are listed in the formula
reference; the four traps that recur below are **`month` returns a name** (use `month_number`),
**`diff_*` takes the end date first**, **no arithmetic on dates** ([**E9**](#how-to-read-the-tables)), and
**`day_number_of_week` numbers Monday = 1**, where Excel's default numbers Sunday = 1. The
Monday base is now **settled**: `day_number_of_week` compiles to fixed arithmetic,
`(MOD((DATEDIFF(day, DATE '1970-01-01', d) + 3), 7) + 1)`, independent of the warehouse's
`WEEK_START` (live-verified 2026-10-06, se-thoughtspot). ThoughtSpot's week comes from the
**Model's calendar**, Gregorian with a Monday week start when nothing else is set (ThoughtSpot
domain review, 2026-10-06). **Every week-dependent row below therefore assumes a Monday week
start and diverges on a Model whose calendar starts elsewhere.** `start_of_*` accept a calendar
argument (`start_of_week ( [date] , 'Calendar Name' )`), but translations do not emit it; a
workbook's fiscal or non-Monday week convention is a note pointing at the Model's calendar
([formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md#date-functions)).

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `DATE(year, month, day)` | direct | `add_days ( add_months ( to_date ( concat ( to_string ( [y] ) , '-01-01' ) , '%Y-%m-%d' ) , [m] - 1 ) , [d] - 1 )` | **Overflow-safe.** Excel normalises out-of-range parts — `DATE(2024, 13, 1)` is 2025-01-01 and `DATE(2024, 3, 0)` is 2024-02-29 — and so does building from 1 January with `add_months` / `add_days`. The Qlik map's `MakeDate` composition (`concat` of all three parts) rejects those inputs instead. Excel also adds 1900 to a year below 1900 (`DATE(24, 1, 1)` is 1924): the translator writes `if ( [y] < 0 or [y] > 9999 ) then null else if ( [y] < 1900 ) then [y] + 1900 else [y]` for a column year (Excel's `#NUM!` range as NULL) and folds literal parts to one `to_date` literal. Literal parts counted from a month before March 1900 — `DATE(1900, 2, 29)` and `DATE(1900, 1, 60)` are Excel's fictitious 29 February 1900, serial 60 — are NEEDS_REVIEW. An omitted part is 0. `[y]` must be an integer — `to_string` of a double may render `2024.0` — so a DOUBLE part is truncated first (`floor`). |
| `DATEDIF(start_date, end_date, unit)` | direct | `"D"`: `diff_days ( [end] , [start] )`; `"M"`: `diff_months ( [end] , [start] ) - if ( day ( [end] ) < day ( [start] ) ) then 1 else 0`; `"Y"`: `floor ( [formula_Months] / 12 )` | **Argument order reversed** — ThoughtSpot `diff_*` takes end first. `DATEDIF` counts **complete** months and years; `diff_months` counts month **boundaries** — it compiles to `DATEDIFF(month, epoch, end) - DATEDIFF(month, epoch, start)` (live-verified 2026-10-06, se-thoughtspot: Jan31→Feb1 = 1, Jan31→Feb28 = 1, Jan20→Mar15 = 2) — so the day-of-month correction is **confirmed necessary**, and `diff_years` (= `EXTRACT(YEAR …)` difference: Dec31→Jan1 = 1) must never stand in for `"Y"` (gap [**G12**](#open-questions--gaps), closed). `"YM"` is `mod ( [formula_Months] , 12 )`. `"MD"` and `"YD"` have no clean form, and Microsoft itself documents `"MD"` as unreliable ([**E3**](#how-to-read-the-tables)). Excel errors when `start > end`; `diff_*` returns a negative value. **Verification:** hand-derived and arithmetic-checked only — **not** import-probed and **not** result-checked against Excel on a live instance. |
| `DATEVALUE(date_text)` | direct | `to_date ( [s] , 'yyyy-MM-dd' )` | The format must be known and stated; Excel infers it from the system locale. The result is a DATE, not a serial number ([**E9**](#how-to-read-the-tables)). |
| `DAY(serial_number)` | direct | `day ( [d] )` | Day of month. `day_number_of_month` does not exist (formula reference). |
| `DAYS(end_date, start_date)` | direct | `diff_days ( [end] , [start] )` | The one Excel date difference whose argument order **already matches** ThoughtSpot (end first) — a converter that reflexively swaps every `diff_*` gets this one wrong. |
| `DAYS360(start_date, end_date, [method])` | direct | `( year ( [e] ) - year ( [s] ) ) * 360 + ( month_number ( [e] ) - month_number ( [s] ) ) * 30 + ( least ( day ( [e] ) , 30 ) - least ( day ( [s] ) , 30 ) )` | The European method (`method = TRUE`): both 31sts become 30. The US/NASD default (`method` omitted or FALSE) is `( year ( [e] ) - year ( [s] ) ) * 360 + ( month_number ( [e] ) - month_number ( [s] ) ) * 30 + ( if ( day ( [e] ) = 31 and day ( [s] ) >= 30 ) then 30 else day ( [e] ) ) - least ( day ( [s] ) , 30 )`: a start 31st becomes 30, and an end 31st becomes 30 only when the start day is already ≥ 30. Excel additionally treats a **last-day-of-February start** as the 30th; that rule is not in the composition — add `if ( month_number ( [s] ) = 2 and month_number ( add_days ( [s] , 1 ) ) = 3 ) then 30 else …` for the start day — and Excel's actual end-of-February behaviour is known to differ from its documentation, so verify against Excel before shipping ([**E3**](#how-to-read-the-tables), [Unverified](#unverified)). |
| `EDATE(start_date, months)` | direct | `add_months ( [d] , [n] )` | Excel clamps to the last day of a shorter month (`EDATE("2024-01-31", 1)` = 2024-02-29); Snowflake `DATEADD('month')`, which `add_months` compiles to, clamps the same way. A text date is `to_date ( '…' , '%Y-%m-%d' )` and a serial number its date (BL-352, BL-353); a DOUBLE month count is truncated toward zero, `if ( [n] < 0 ) then ceil ( [n] ) else floor ( [n] )` — `add_months` takes an integer (BL-355). |
| `EOMONTH(start_date, months)` | direct | `add_days ( add_months ( start_of_month ( [d] ) , [n] + 1 ) , -1 )` | Start of the month `n + 1` ahead, minus a day. Exact for every month length, and the answer to the Qlik map's "no end-of-month function" rows. Date and month arguments are coerced as for `EDATE` (BL-352, BL-353, BL-355). |
| `HOUR(serial_number)` | direct | `hour_of_day ( [t] )` | **Not `hour`**, which does not exist (BL-171). |
| `ISOWEEKNUM(date)` | passthrough | `sql_int_op ( "WEEKISO({0})" , [d] )` | **Variant: `sql_int_op`.** `week_number_of_year`'s compiled SQL uses ISO-style Thursday logic (`week_number_of_year(2026-01-04)` = 1, live-verified 2026-10-06), but one date does not prove ISO year-boundary behaviour (a late-December date in ISO week 1 was not probed), and the Tableau map records it as not ISO-8601 — so the pass-through stays the honest default until a boundary probe. A native composition exists (Thursday-of-week rule over `day_number_of_week`) but the pass-through is the honest default. |
| `MINUTE(serial_number)` | passthrough | `sql_int_op ( "MINUTE({0})" , [t] )` | **Variant: `sql_int_op`.** No native minute extractor (live-verified absent, BL-171). |
| `MONTH(serial_number)` | direct | `month_number ( [d] )` | **Not `month ( )`**, which returns the month *name* and silently turns an integer column into text. |
| `NETWORKDAYS(start_date, end_date, [holidays])` | direct | `5 * floor ( ( diff_days ( [e] , [s] ) + 1 ) / 7 ) + mod ( diff_days ( [e] , [s] ) + 1 , 7 ) - greatest ( 0 , least ( day_number_of_week ( [s] ) + mod ( diff_days ( [e] , [s] ) + 1 , 7 ) - 1 , 7 ) - greatest ( day_number_of_week ( [s] ) , 6 ) + 1 )` | **Native, contrary to the Qlik map's `NetworkDays` row.** Whole weeks contribute 5 days each; the remaining `r = (n + 1) mod 7` days starting at weekday `w` (1 = Monday) lose `max(0, min(w + r − 1, 7) − max(w, 6) + 1)` weekend days — a remainder window of at most 6 days can wrap only into Monday–Friday, so no second weekend term is needed. Hand-checked across all start weekdays. Covers `end ≥ start` and no `holidays` ([**E3**](#how-to-read-the-tables)); swap and negate for `end < start`. **Prefer the simpler form:** the per-weekday counting form on the `NETWORKDAYS.INTL` row with `k` = 6, 7 (code 1) gives the same count and is live-verified ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)). **`holidays` depends on its form.** *An inline array constant* (`{"2026-12-25", "2026-12-26"}`) is native: subtract one term per holiday `h` that falls inside the range **and** on a working day (Excel never subtracts a weekend holiday): `- ( if ( to_date ( 'h' , 'yyyy-MM-dd' ) >= [s] and to_date ( 'h' , 'yyyy-MM-dd' ) <= [e] and day_number_of_week ( to_date ( 'h' , 'yyyy-MM-dd' ) ) <= 5 ) then 1 else 0 )`. Wrap each literal in `to_date` (a bare `'2026-12-25'` parses as subtraction), and match the pattern to the sheet's text-date locale, because Excel coerces the array's strings with it. One term per holiday assumes each date appears once: Excel's handling of a duplicated holiday was not probed, so **dedupe the array at conversion**. One term per holiday suits a handful of dates, not a full public-holiday calendar. *A cell range* (`A$10:A$20`) is data, not constants: it becomes a calendar table joined to the Model — or the [`ts-recipe-formula-business-days-snowflake`](../../agents/cli/ts-recipe-formula-business-days-snowflake/SKILL.md) UDFs. The inline-array rule applies to `NETWORKDAYS.INTL` too, with the weekday test generalised (see that row). It does **not** apply to `WORKDAY` / `WORKDAY.INTL`, which return a date: there each holiday moves the end date rather than reducing a count. `day_number_of_week` is confirmed fixed at 1 = Monday (gap [**G11**](#open-questions--gaps), closed 2026-10-06). **Verification.** *Live-verified* ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)): the inline-holiday term above, with weekend code 1 — holidays 2026-12-25 (Fri) and 2026-12-26 (Sat), 6 ranges including ranges starting or ending on a holiday and a weekend-only range, all matching Excel — evaluated on the per-weekday counting form. *Not probed:* the composition in this row's ThoughtSpot cell (hand-derived and arithmetic-checked only), duplicate holidays, and holidays with any other weekend code. **Assumes a Monday week start** — the Model calendar's default (Gregorian, Monday first when nothing else is set; ThoughtSpot domain review, 2026-10-06) — and diverges if the Model's calendar starts the week elsewhere. |
| `NETWORKDAYS.INTL(start_date, end_date, [weekend], [holidays])` | direct | `n - Σ ( floor ( n / 7 ) + if ( mod ( k + 7 - w , 7 ) < mod ( n , 7 ) ) then 1 else 0 )` over the non-working weekdays `k`, with `n` = `( diff_days ( [e] , [s] ) + 1 )` and `w` = `day_number_of_week ( [s] )` | **Per-weekday counting form, live-verified.** Every weekend code, numeric or string, is a set of non-working weekdays `k` (1 = Monday … 7 = Sunday) — see the [weekend-code table](#networkdaysintl-weekend-codes-not-counted--arguments). The range holds `n` days starting on weekday `w`; weekday `k` occurs `floor ( n / 7 )` times plus once more when its offset from the start, `mod ( k + 7 - w , 7 )`, falls inside the `mod ( n , 7 )`-day remainder. Workdays are `n` minus the count for each non-working weekday, so code 1 subtracts two counts (`k` = 6, 7), code 11 one (`k` = 7), and `"1000001"` two (`k` = 1, 7). **Verification:** live-verified on se-thoughtspot, 2026-10-06, for codes 1, 11 and `"1000001"` without holidays, over 7 date ranges including single days and weekend-only ranges — every result matched Excel ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)). Other codes were not probed; they differ only in which `k` terms are subtracted. Covers `end ≥ start` and no `holidays` ([**E3**](#how-to-read-the-tables)): for `end < start` Excel returns a **negative** count and this form does not (`n` ≤ 0), so swap the dates and negate. **`holidays`:** an inline array constant subtracts one term per holiday `h` that is in range **and on a working day for this code** — the weekday test is "not in the weekend set K", not `<= 5`: `- ( if ( [h] >= [s] and [h] <= [e] and day_number_of_week ( [h] ) != k1 and day_number_of_week ( [h] ) != k2 ) then 1 else 0 )`, with one `!=` per `k` in K and `[h]` the `to_date` literal. For code 1 (K = {6, 7}) this equals the `<= 5` test that was live-verified ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)); for other codes it is hand-derived. Dedupe the array at conversion, and treat a cell range as for `NETWORKDAYS`. `mod`'s dividend-sign behaviour (see `MOD`) does not arise: `k + 7 - w` ≥ 1 and `n` ≥ 1. **Assumes a Monday week start** — the Model calendar's default (Gregorian, Monday first when nothing else is set; ThoughtSpot domain review, 2026-10-06) — and diverges if the Model's calendar starts the week elsewhere. |
| `NOW()` | direct | `now ( )` | Volatile in Excel; evaluated per query in ThoughtSpot, and in the warehouse's time zone unless `ts_user_timezone` is applied. |
| `SECOND(serial_number)` | passthrough | `sql_int_op ( "SECOND({0})" , [t] )` | **Variant: `sql_int_op`.** As `MINUTE`. |
| `TIME(hour, minute, second)` | passthrough | `sql_date_time_op ( "TIME_FROM_PARTS({0}, {1}, {2})" , [h] , [m] , [s] )` | **Variant: `sql_date_time_op`.** ThoughtSpot has no TIME type (Ossie map, `TIME` literal row), so a standalone time comes back as a DATETIME on a warehouse-default date. The usual Excel use — `date + TIME(h, m, s)` — is native: `add_seconds ( [d] , [h] * 3600 + [m] * 60 + [s] )` ([**E9**](#how-to-read-the-tables)) — but `add_seconds` is documented for a **DATETIME** argument; applied to a DATE column it is *unverified* (it may need `to_date`-free promotion or be rejected), so wrap the date side accordingly once probed. |
| `TIMEVALUE(time_text)` | passthrough | `sql_date_time_op ( "TO_TIME({0})" , [s] )` | **Variant: `sql_date_time_op`.** Excel returns a fraction of a day; there is no TIME type to receive it. `diff_time` against midnight gives seconds-since-midnight natively if a number is what the sheet used. |
| `TODAY()` | direct | `today ( )` |  |
| `WEEKDAY(serial_number, [return_type])` | direct | type 1: `mod ( day_number_of_week ( [d] ) , 7 ) + 1`; type 2: `day_number_of_week ( [d] )`; type 3: `day_number_of_week ( [d] ) - 1` | **The default (`return_type` 1) numbers Sunday = 1**; ThoughtSpot numbers Monday = 1 … Sunday = 7. Types 11–17 start the week on Monday…Sunday: `mod ( day_number_of_week ( [d] ) - k + 7 , 7 ) + 1` with `k` = 1…7. Mapping `WEEKDAY(d)` to bare `day_number_of_week` shifts every value by one day and is wrong for literal comparisons (`WEEKDAY(d) = 1` means Sunday). Not `day_of_week`, which returns the name. Monday base confirmed (gap [**G11**](#open-questions--gaps), closed 2026-10-06). **Assumes a Monday week start** — the Model calendar's default (Gregorian, Monday first when nothing else is set; ThoughtSpot domain review, 2026-10-06) — and diverges if the Model's calendar starts the week elsewhere. |
| `WEEKNUM(serial_number, [return_type])` | direct | `floor ( ( day_number_of_year ( [d] ) - 1 + mod ( day_number_of_week ( start_of_year ( [d] ) ) , 7 ) ) / 7 ) + 1` | Return type 1 (week containing 1 January is week 1, weeks start Sunday). Type 2 (Monday start) replaces the offset with `day_number_of_week ( start_of_year ( [d] ) ) - 1`. Type 21 is ISO and falls back to the `ISOWEEKNUM` pass-through ([**E3**](#how-to-read-the-tables)). `week_number_of_year` is not used: its compiled SQL is ISO-style (see `ISOWEEKNUM`), not Excel's Sunday-start week-containing-1-January rule. The composition rests on `day_number_of_week`'s fixed Monday = 1 base (gap [**G11**](#open-questions--gaps), closed 2026-10-06). Return types 11–17 (week start Monday…Sunday) are a week-start convention: a note pointing at the Model's calendar, not a calendar argument in the formula. **Assumes a Monday week start** — the Model calendar's default (Gregorian, Monday first when nothing else is set; ThoughtSpot domain review, 2026-10-06) — and diverges if the Model's calendar starts the week elsewhere.  **Verification:** hand-derived and arithmetic-checked only — **not** import-probed and **not** result-checked against Excel on a live instance. |
| `WORKDAY(start_date, days, [holidays])` | direct | `add_days ( [s] , [n] + 2 * floor ( ( day_number_of_week ( [s] ) - 1 + [n] ) / 5 ) )` | Covers a weekday start, `days ≥ 0` and no `holidays` ([**E3**](#how-to-read-the-tables)): each completed run of five working days adds a weekend. Checked Mon+4 → Fri, Mon+5 → Mon, Fri+1 → Mon. Relies on `day_number_of_week`'s fixed Monday = 1 base (G11, closed 2026-10-06). A weekend start (Excel rolls it forward) or negative `days` needs a further branch; **`holidays` is not the `NETWORKDAYS` subtract-a-term form:** each in-range working-day holiday pushes the end date one working day later, which can cross a further weekend or holiday, so no fixed number of terms expresses it. With holidays — inline array or range — use a calendar table joined to the Model, or the [`ts-recipe-formula-business-days-snowflake`](../../agents/cli/ts-recipe-formula-business-days-snowflake/SKILL.md) UDFs. Not probed. **Assumes a Monday week start** — the Model calendar's default (Gregorian, Monday first when nothing else is set; ThoughtSpot domain review, 2026-10-06) — and diverges if the Model's calendar starts the week elsewhere. |
| `WORKDAY.INTL(start_date, days, [weekend], [holidays])` | direct | as `WORKDAY` for `weekend = 1` | Other weekend codes as `NETWORKDAYS.INTL`'s weekend-code table. **`holidays` as for `WORKDAY`**: a calendar table or UDF, never the `NETWORKDAYS.INTL` holiday term. Not probed. **Assumes a Monday week start** — the Model calendar's default (Gregorian, Monday first when nothing else is set; ThoughtSpot domain review, 2026-10-06) — and diverges if the Model's calendar starts the week elsewhere. |
| `YEAR(serial_number)` | direct | `year ( [d] )` |  |
| `YEARFRAC(start_date, end_date, [basis])` | direct | basis 2: `diff_days ( [e] , [s] ) / 360`; basis 3: `diff_days ( [e] , [s] ) / 365`; basis 4: `[formula_Days360 EU] / 360`; basis 0: `[formula_Days360 US] / 360` | Bases 2–4 are exact. The **default basis 0** (US 30/360) is the US `DAYS360` composition divided by 360 — given on the `DAYS360` row — and is **partial**: it omits the end-of-February rules (Excel's `YEARFRAC` basis 0 also moves an end date that is the last day of February when the start is too), so dates touching February end fall back to a hand-written rule or a pre-computed column ([**E3**](#how-to-read-the-tables)). Basis 1 (actual/actual) averages year lengths across the span by an Excel-specific rule and is unmappable. |

### `NETWORKDAYS.INTL` weekend codes *(not counted — arguments)*

Applies to `NETWORKDAYS.INTL` and `WORKDAY.INTL`. `k` is the `day_number_of_week` value (1 = Monday … 7 = Sunday) of each
**non-working** weekday; the `NETWORKDAYS.INTL` row subtracts one per-weekday count for each.

| `weekend` | Non-working days | `k` |
|---|---|---|
| `1` (default) | Saturday, Sunday | 6, 7 |
| `2` | Sunday, Monday | 7, 1 |
| `3` | Monday, Tuesday | 1, 2 |
| `4` | Tuesday, Wednesday | 2, 3 |
| `5` | Wednesday, Thursday | 3, 4 |
| `6` | Thursday, Friday | 4, 5 |
| `7` | Friday, Saturday | 5, 6 |
| `11` | Sunday only | 7 |
| `12` | Monday only | 1 |
| `13` | Tuesday only | 2 |
| `14` | Wednesday only | 3 |
| `15` | Thursday only | 4 |
| `16` | Friday only | 5 |
| `17` | Saturday only | 6 |
| 7-character string, e.g. `"0000011"` | each position holding `1`, **Monday first** | the 1-based positions of the `1`s (`"0000011"` → 6, 7; `"1000001"` → 1, 7) |

Code 1 written out in full (`[s]` start, `[e]` end):

```text
( diff_days ( [e] , [s] ) + 1 )
- ( floor ( ( diff_days ( [e] , [s] ) + 1 ) / 7 ) + if ( mod ( 6 + 7 - day_number_of_week ( [s] ) , 7 ) < mod ( diff_days ( [e] , [s] ) + 1 , 7 ) ) then 1 else 0 )
- ( floor ( ( diff_days ( [e] , [s] ) + 1 ) / 7 ) + if ( mod ( 7 + 7 - day_number_of_week ( [s] ) , 7 ) < mod ( diff_days ( [e] , [s] ) + 1 , 7 ) ) then 1 else 0 )
```

A converter can hoist `n` and `w` into their own formulas, referenced by id ([**E14**](#how-to-read-the-tables)), to keep each
count short. All-seven-days `"1111111"` returns 0 in this form; Excel returns `#VALUE!` for it.


---

## Logical

Source: the *Logical functions* list. `LET`, `LAMBDA`, `BYCOL`, `BYROW`, `MAKEARRAY`, `MAP`,
`REDUCE` and `SCAN` are rowed under [Dynamic arrays](#dynamic-arrays-let-and-lambda).

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `AND(logical1, ...)` | direct | `[a] and [b]` | Lower-case infix. `AND` over a **range** ("every row is true") is an aggregate: `count_if ( not ( [c] ) , [T::key] ) = 0` ([**E5**](#how-to-read-the-tables)). |
| `FALSE()` | direct | `false` |  |
| `IF(logical_test, [value_if_true], [value_if_false])` | direct | `if ( cond ) then a else b` | **Parentheses around the condition are mandatory** for TML import. Excel's omitted `value_if_false` returns `FALSE`; ThoughtSpot requires a **type-matched** `else` (`else 0`, `else ''`) — formula reference and the Ossie map's `CASE` row. **`IF(b = 0, 0, a / b)` is exactly `safe_divide ( [a] , [b] )`** (it compiles to `CASE WHEN b = 0 THEN 0 ELSE a / NULLIF(b, 0) END` — [probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)); the translator maps it so, and `--to excel` writes `safe_divide` that way. A `""` branch beside a numeric one must become `null` — ThoughtSpot rejects mixed branch types (*Expecting a Numeric token*), and `null` is accepted in either branch (§7). |
| `IFERROR(value, value_if_error)` | direct | divide: `if ( [b] = 0 ) then [fallback] else [a] / [b]`; otherwise `ifnull ( expr , [fallback] )` | **ThoughtSpot has no error values** ([**E8**](#how-to-read-the-tables)). Each Excel error has a different fate: `#DIV/0!` becomes NULL under a plain `/` ([probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)) — `IFERROR(a/b, 0)` is `safe_divide ( [a] , [b] )`, which returns 0 — **except when `b` is NULL**: Excel reads a blank divisor as 0, raises `#DIV/0!` and returns the fallback, while `safe_divide` with a NULL divisor returns NULL (live-probed 2026-10-06, [probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)), so use `safe_divide ( [a] , ifnull ( [b] , 0 ) )` where the column is nullable; a lookup miss (`#N/A`) is a NULL from an outer join; a failed `to_double` conversion fails the query rather than returning NULL (live 2026-10-07), so around `VALUE` the conversion is `TRY_TO_DOUBLE` (below). All NULL-shaped failures are caught by `ifnull`. An error class that the warehouse raises (an invalid regex in a pass-through) cannot be caught at all. **Fallback `""`** (`IFERROR(a/b, "")`, the usual "leave the cell blank"): there is no blank text in a numeric formula, so the `ts formula translate --from excel` translator emits `safe_divide ( [a] , [b] )` and reports it **APPROXIMATED** — a zero divisor shows 0 where Excel showed a blank; write `IFERROR(…, 0)` in the sheet for exact parity, or `if ( [b] = 0 ) then null else [a] / [b]` for a NULL. Translator-backed (BL-339). **Branch types** (BL-354, fidelity M1): a text fallback beside a numeric value makes the number `to_string ( … )` — the branches of a ThoughtSpot `if` must share a type — APPROXIMATED with a trap. **Around `VALUE`:** `ifnull ( sql_double_op ( "TRY_TO_DOUBLE({0})" , [s] ) , [fallback] )` — `to_double` fails the whole query on non-numeric text instead of returning NULL (live 2026-10-07), so it can never reach the fallback. |
| `IFNA(value, value_if_na)` | direct | `ifnull ( [LOOKUP::col] , [fallback] )` | `#N/A` is a lookup miss; the lookup becomes a join ([**E13**](#how-to-read-the-tables)) and a miss is NULL on the joined side. |
| `IFS(logical_test1, value_if_true1, ...)` | direct | `if ( c1 ) then v1 else if ( c2 ) then v2 else d` | Excel returns `#N/A` when no test is true; ThoughtSpot needs a synthesised, type-matched final `else`. The idiom `IFS(…, TRUE, d)` is that `else`. |
| `NOT(logical)` | direct | `not ( [x] )` | Function form with parentheses. |
| `OR(logical1, ...)` | direct | `[a] or [b]` | Over a range ("any row is true"): `count_if ( [c] , [T::key] ) > 0`. |
| `SWITCH(expression, value1, result1, ..., [default])` | direct | `if ( [x] = v1 ) then r1 else if ( [x] = v2 ) then r2 else d` | Expanded per branch, as the Ossie map's simple `CASE`. No `default` → synthesised `else`, as `IFS`. |
| `TRUE()` | direct | `true` |  |
| `XOR(logical1, ...)` | direct | `mod ( ( if ( [a] ) then 1 else 0 ) + ( if ( [b] ) then 1 else 0 ) , 2 ) = 1` | Excel's N-ary `XOR` is TRUE when an **odd** number of arguments are TRUE — not "exactly one". The two-argument case is also `( [a] and not ( [b] ) ) or ( not ( [a] ) and [b] )`. |

---

## Information

Source: the *Information functions* list (which, as rendered, also carries `STOCKHISTORY`).
`ISOMITTED` is rowed under [Dynamic arrays](#dynamic-arrays-let-and-lambda). Most of this
category inspects *cells* — their type, formula, sheet or error state — and so meets
[**E6**](#how-to-read-the-tables), [**E8**](#how-to-read-the-tables) or [**E15**](#how-to-read-the-tables).

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `CELL(info_type, [reference])` | **unmappable** | — | Returns cell metadata (address, format, file name, width). Nothing in a Model has a cell ([**E6**](#how-to-read-the-tables)). |
| `ERROR.TYPE(error_val)` | **unmappable** | — | There are no error values to classify ([**E8**](#how-to-read-the-tables)); every NULL-shaped failure looks the same. |
| `INFO(type_text)` | **unmappable** | — | Workbook-environment information (OS version, recalculation mode). |
| `ISBLANK(value)` | direct | `isnull ( [x] )` | **A cell holding `""` from a formula is not blank to Excel**, and an empty string is not NULL to `isnull` either, so the two agree. But data loaded from a sheet frequently stores truly empty cells as `''`; where it does, use `isnull ( [x] ) or [x] = ''` and say so in the issue. |
| `ISERR(value)` | direct | `isnull ( expr )` | "Any error except `#N/A`." The distinction does not survive ([**E8**](#how-to-read-the-tables)): a failure is a NULL whichever error Excel would have shown, so `ISERR` and `ISERROR` collapse to the same test — and that test also fires on a value that was simply NULL in the data. Flag it. |
| `ISERROR(value)` | direct | `isnull ( expr )` | As `ISERR`. The common shape `ISERROR(a/b)` is better written as its cause: `[b] = 0`. |
| `ISEVEN(number)` | direct | `mod ( floor ( abs ( [x] ) ) , 2 ) = 0` | Excel truncates the argument first; taking `abs` before `mod` sidesteps the dividend-sign difference noted on `MOD`. |
| `ISFORMULA(reference)` | **unmappable** | — | Cell metadata. |
| `ISLOGICAL(value)` | direct | `true` / `false` by the column's type; a boolean column is `not ( isnull ( [b] ) )` | Type tests resolve statically ([**E15**](#how-to-read-the-tables)). |
| `ISNA(value)` | direct | `isnull ( [LOOKUP::col] )` | As `IFNA`: the lookup is a join and `#N/A` is a NULL on the joined side. |
| `ISNONTEXT(value)` | direct | `true` / `false` by the column's type | Also TRUE for a blank cell, so on a text column the row-level form is `isnull ( [s] )` rather than the constant `false`. |
| `ISNUMBER(value)` | direct | `true` / `false` by type; `ISNUMBER(VALUE(s))` → `sql_bool_op ( "TRY_TO_DOUBLE({0}) IS NOT NULL" , [s] )` | Statically resolved on a typed column ([**E15**](#how-to-read-the-tables)). Its two common *idioms* are not type tests at all: `ISNUMBER(FIND(x, s))` / `ISNUMBER(SEARCH(x, s))` is a containment test (`strpos ( [s] , 'x' ) > 0`, or `contains ( [s] , 'x' )`), and `ISNUMBER(VALUE(s))` is a parse test, which `to_double`'s null-on-failure makes native ([**E8**](#how-to-read-the-tables)). **Not `not ( isnull ( to_double ( [s] ) ) )`:** `to_double` of text that is not a number fails the whole query (*Numeric value '…' is not recognized*, live 2026-10-07, probe record §7) — on exactly the rows the test exists to find; `TRY_TO_DOUBLE` returns NULL instead. |
| `ISODD(number)` | direct | `mod ( floor ( abs ( [x] ) ) , 2 ) = 1` | As `ISEVEN`. |
| `ISREF(value)` | **unmappable** | — | Tests whether an argument is a reference; nothing is a reference in a Model. |
| `ISTEXT(value)` | direct | `true` / `false` by the column's type; a text column is `not ( isnull ( [s] ) )` (a blank cell is not text) | As `ISLOGICAL`. |
| `N(value)` | direct | numeric: `[x]`; boolean: `if ( [b] ) then 1 else 0`; text: `0` | By type ([**E15**](#how-to-read-the-tables)). Excel also converts a date to its serial number; the native equivalent is `diff_days ( [d] , to_date ( '1899-12-30' , 'yyyy-MM-dd' ) )` ([**E9**](#how-to-read-the-tables)). |
| `NA()` | direct | inside an `IF`: `null` — `if ( … ) then [x] else null` | `#N/A` is used to make a chart skip a point, and NULL is ThoughtSpot's skip. `null` is accepted as an `if` branch value (VALIDATE_ONLY 2026-10-06, [probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)); a bare `NA()` outside a branch has no form. **Not `nullif ( 0 , 0 )`**, which this row gave until 2026-10-06: `nullif` is not a ThoughtSpot function and is rejected at import (BL-339, gap [**G9**](#open-questions--gaps)). |
| `SHEET([value])` | **unmappable** | — | Workbook structure. |
| `SHEETS([reference])` | **unmappable** | — | Workbook structure. |
| `STOCKHISTORY(stock, start_date, ...)` | **unmappable** | — | Calls Microsoft's market-data service at recalculation time. The data has to be loaded into the warehouse to be modelled at all. |
| `TYPE(value)` | direct | `1` / `2` / `4` by the column's type | Number = 1, text = 2, logical = 4 — a constant per column ([**E15**](#how-to-read-the-tables)). `16` (error) and `64` (array) never arise. |

---

## Lookup and reference

Source: the *Lookup and reference functions* list. The array-shaping and dynamic-array members of
this category (`FILTER`, `SORT`, `UNIQUE`, `GROUPBY`, `TAKE`, `VSTACK`, …) are rowed under
[Dynamic arrays](#dynamic-arrays-let-and-lambda). This is where `structural` concentrates: a
lookup is a relationship ([**E13**](#how-to-read-the-tables)).

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ADDRESS(row_num, column_num, ...)` | **unmappable** | — | Builds a cell address string ([**E6**](#how-to-read-the-tables)). |
| `AREAS(reference)` | **unmappable** | — | Counts the areas in a multi-area reference. |
| `CHOOSE(index_num, value1, ...)` | direct | `if ( [i] = 1 ) then v1 else if ( [i] = 2 ) then v2 else d` | As the Qlik map's `Pick` row. Excel returns `#VALUE!` for an out-of-range index; the synthesised `else` takes its place. |
| `COLUMN([reference])` | **unmappable** | — | Column number of a cell ([**E6**](#how-to-read-the-tables)). |
| `COLUMNS(array)` | **unmappable** | — | Width of a range — a property of the sheet's layout. (Its value is a constant a converter could fold, but it never means anything in a Model.) |
| `FORMULATEXT(reference)` | **unmappable** | — | Cell metadata. |
| `GETPIVOTDATA(data_field, pivot_table, [field1, item1], ...)` | direct | `group_aggregate ( sum ( [T::m] ) , { } , { [T::field1] = 'item1' } )` | Reads one cell of a pivot table: a measure at a fixed filter, independent of the surrounding sheet. A hard-coded filter argument is accepted by `group_aggregate` (formula reference) but is **untranslatable** onward to a Snowflake Semantic View. The aggregation (`sum`) must be read from the pivot's value-field setting. The pivot's *own* report filters are lost unless added to the filter list. |
| `HLOOKUP(lookup_value, table_array, row_index_num, [range_lookup])` | structural | Model join, then `[LOOKUP::col]` | `VLOOKUP` over a horizontally laid-out table ([**E13**](#how-to-read-the-tables)). The table must first be loaded in its transposed (columnar) form, which is an ETL step, not a formula. |
| `HYPERLINK(link_location, [friendly_name])` | direct | `concat ( "{caption}" , [label] , "{/caption}" , [url] )` | ThoughtSpot's hyperlink markup (formula reference, *Hyperlink Markup*). ThoughtSpot-only — not translatable onward to warehouse SQL. A bare URL column also renders as a link without markup. |
| `IMAGE(source, [alt_text], [sizing], ...)` | **unmappable** | — | Renders an image in a cell. There is no formula form; whether a ThoughtSpot column can be displayed as an image from a URL is a column display setting and is not covered by this map's sources (*unverified*). |
| `INDEX(array, row_num, [column_num])` | structural | Model join (with `MATCH`), then `[LOOKUP::col]` | Classified on the dominant use, `INDEX(return_range, MATCH(key, key_range, 0))`, which is a keyed lookup ([**E13**](#how-to-read-the-tables)). `INDEX` alone with a literal row number is positional and unmappable ([**E6**](#how-to-read-the-tables)). |
| `INDIRECT(ref_text, [a1])` | **unmappable** | — | A reference computed from text at run time. Nothing analogous exists; it is also the usual sign of a sheet whose structure is doing the work a data model should. |
| `LOOKUP(lookup_value, lookup_vector, [result_vector])` | structural | Model join (banded), then `[LOOKUP::col]` | Always approximate match against a sorted vector — a **range** join (tax brackets, price bands). The Model TML reference documents inequality `on` clauses — `'[FACT::x] >= [BANDS::lower] and [FACT::x] < [BANDS::upper]'` — per ThoughtSpot's docs, but no live Model has exercised one (gap [**G13**](#open-questions--gaps)). Excel's band table carries only lower bounds, so the band table needs an upper-bound column added upstream. A small literal band table can instead be an `if` chain. |
| `MATCH(lookup_value, lookup_array, [match_type])` | structural | Model join (inside `INDEX`), or `[x] in { 'a' , 'b' }` | Its position result means nothing alone ([**E6**](#how-to-read-the-tables)); it appears inside `INDEX` (a join) or as the membership idiom `ISNUMBER(MATCH(x, list, 0))`, which over a literal list is `in { }` (curly braces, BL-170) and over another table's column is existence through a join. |
| `OFFSET(reference, rows, cols, [height], [width])` | **unmappable** | — | Position arithmetic ([**E6**](#how-to-read-the-tables)). Two ordered idioms have native **downgrades** under the ordering assumption: the previous row `OFFSET(B5, -1, 0)` is the LAG idiom `moving_sum ( [T::m] , 1 , -1 , [T::order] )`, and a trailing window `SUM(OFFSET(B5, -2, 0, 3, 1))` is `moving_sum ( [T::m] , 2 , 0 , [T::order] )`. Both take their partition from the search, not from the sheet (the Ossie map's [E13](../ossie/ts-ossie-function-mapping.md#window-functions)). |
| `ROW([reference])` | **unmappable** | — | Row number of a cell ([**E6**](#how-to-read-the-tables)). Used as a running index (`ROW() - 1`), it is a row number under the ordering assumption: `sql_int_aggregate_op ( "ROW_NUMBER() OVER (ORDER BY {0})" , start_of_month ( [T::order_date] ) )` — there is no native `row_number` (live-verified absent). The window's `ORDER BY` must match the search's GROUP BY expression — `start_of_month ( [d] )` when the search buckets the date `.monthly`, the raw column only when it is unbucketed (formula reference, *Window functions inside `sql_*_aggregate_op`*, rule 1). *Unverified* on a live search. |
| `ROWS(array)` | direct | `count ( [T::key] )` | The number of rows in a range is the row count of the table, read as a count over a non-null key ([**E5**](#how-to-read-the-tables)). |
| `RTD(prog_id, server, topic1, ...)` | **unmappable** | — | Real-time data from a COM automation server. |
| `TRANSPOSE(array)` | **unmappable** | — | Reshapes a range ([**E6**](#how-to-read-the-tables)). The *presentation* of a transposed table is a pivot-table visualisation, not a formula. |
| `VLOOKUP(lookup_value, table_array, col_index_num, [range_lookup])` | structural | Model join on `[FACT::key] = [LOOKUP::key]`, then `[LOOKUP::col]` | **A lookup is a relationship, not a calculation** ([**E13**](#how-to-read-the-tables)). Exact match (`FALSE`) is a many-to-one join; the looked-up column then appears in the Model and needs no formula. Excel returns the **first** match where the lookup key is duplicated; a join returns every match and fans out the fact rows — dedupe the lookup table on the key first. Approximate match (`TRUE`, the default) is a range join, as `LOOKUP`. Excel exact match is case-insensitive; a warehouse join is not. |
| `XLOOKUP(lookup_value, lookup_array, return_array, [if_not_found], [match_mode], [search_mode])` | structural | Model join, then `ifnull ( [LOOKUP::col] , [if_not_found] )` | As `VLOOKUP`, with `if_not_found` becoming `ifnull` over the joined column (an outer join's miss is NULL). `match_mode` −1/1 (next smaller/larger) is a range join; 2 (wildcard) has no join form. `search_mode` −1 (last-to-first) picks the *last* duplicate — order-dependent, so dedupe deliberately ([**E6**](#how-to-read-the-tables)). |
| `XMATCH(lookup_value, lookup_array, [match_mode], [search_mode])` | structural | as `MATCH` | As `MATCH`. |

---

## Dynamic arrays, LET and LAMBDA

Gathered from Logical (`LET`, `LAMBDA`, `BYCOL`, `BYROW`, `MAKEARRAY`, `MAP`, `REDUCE`, `SCAN`),
Information (`ISOMITTED`), Math (`SEQUENCE`, `RANDARRAY`) and Lookup and reference (the rest).
The reading that makes this family tractable: **a spilled array down a column is a query result,
and a function mapped over a column is a row-level formula.** So the functions that *compute*
per element (`MAP`, `BYROW`) are `direct`, the ones that *shape a result* (`FILTER`, `SORT`,
`UNIQUE`, `GROUPBY`) are `structural`, and the ones that *reshape by position* (`TOCOL`, `WRAPROWS`,
`VSTACK`) are `unmappable` ([**E6**](#how-to-read-the-tables)).

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `BYCOL(array, lambda)` | direct | one measure per column — e.g. `BYCOL(B:D, LAMBDA(c, SUM(c)))` → `sum ( [T::b] )`, `sum ( [T::c] )`, `sum ( [T::d] )` | Applies a LAMBDA to each column of a range; when the body is an aggregate, the result row is simply a set of measures. A non-aggregate body has no meaning per column. |
| `BYROW(array, lambda)` | direct | the LAMBDA body as a row-level formula over the row's columns | `BYROW(B2:D100, LAMBDA(r, MAX(r)))` is `greatest ( [T::b] , [T::c] , [T::d] )` — per-row evaluation is exactly what a ThoughtSpot attribute formula already is ([**E5**](#how-to-read-the-tables), [**E7**](#how-to-read-the-tables)). |
| `CHOOSECOLS(array, col_num1, ...)` | structural | the columns chosen in the search | Selecting columns of a range is selecting columns for an Answer. |
| `CHOOSEROWS(array, row_num1, ...)` | **unmappable** | — | Selects rows by position ([**E6**](#how-to-read-the-tables)). |
| `DROP(array, rows, [columns])` | **unmappable** | — | Drops the first or last N rows by position. |
| `EXPAND(array, rows, [columns], [pad_with])` | **unmappable** | — | Pads an array to a shape. |
| `FILTER(array, include, [if_empty])` | structural | a Model or Answer filter; inside an aggregate, the `*_if` form | A spilled, filtered range is a filtered query: a search filter, or a Model `filters:` entry when it must always apply. `SUM(FILTER(B:B, A:A = "x"))` is not structural at all — it is `sum_if ( [T::a] = 'x' , [T::b] )`, and `COUNTA(FILTER(…))` is `count_if`. |
| `GROUPBY(row_fields, values, function, ...)` | structural | an Answer: the row fields as attributes, the values aggregated by `function` | `GROUPBY` is a search. `function` (`SUM`, `AVERAGE`, `PERCENTOF`…) becomes the measure's aggregation; totals are the Answer's totals; sort and filter arguments are the Answer's sort and filter. |
| `HSTACK(array1, ...)` | **unmappable** | — | Places ranges side by side, aligned **by position**. Columns of one table already sit side by side in a Model; ranges from different tables align only through a key, which `HSTACK` does not have. |
| `ISOMITTED(argument)` | direct | `true` / `false`, resolved when the LAMBDA is inlined | Part of the LAMBDA inlining in [**E14**](#how-to-read-the-tables): whether a call site supplied an argument is known at conversion time, so the test folds to a constant. |
| `LAMBDA([parameter1, ...], calculation)` | direct | the body, inlined at each call site | ThoughtSpot has no user-defined functions. A **named** LAMBDA (Name Manager) that is not recursive is macro-expanded into each formula that calls it ([**E14**](#how-to-read-the-tables)); the expansion is exact. A **recursive** LAMBDA has no expansion and is unmappable. |
| `LET(name1, value1, ..., calculation)` | direct | each bound name as its own formula, referenced by id — `[formula_<name>]` — or inlined | Names become formulas referenced by **id** (`[formula_<Name>]`), which resolve on first import; display-name references do not (CLAUDE.md, invariant I9). Inlining is also exact but repeats the expression. |
| `MAKEARRAY(rows, cols, lambda)` | **unmappable** | — | Generates an array of a given shape ([**E6**](#how-to-read-the-tables)). |
| `MAP(array1, ..., lambda)` | direct | the LAMBDA body as a row-level formula | `MAP(A2:A100, LAMBDA(x, x * 2))` is the formula `[T::a] * 2`: mapping a function over a column is what a row-level formula does. |
| `PIVOTBY(row_fields, col_fields, values, function, ...)` | structural | an Answer shown as a pivot table | As `GROUPBY`, with the column fields on the pivot's column axis. |
| `RANDARRAY([rows], [columns], [min], [max], [integer])` | **unmappable** | — | Generates an array; per-row randomness is the `RAND` pass-through. |
| `REDUCE([initial_value], array, lambda)` | **unmappable** | — | A general left fold has no native form. The special cases that matter are already aggregates — an additive accumulator is `sum`, a `MAX` accumulator is `max` — and would normally have been written that way. |
| `SCAN([initial_value], array, lambda)` | **unmappable** | — | A running fold. The additive, `MAX` and `MIN` accumulators are `cumulative_sum` / `cumulative_max` / `cumulative_min` under the ordering assumption ([**E6**](#how-to-read-the-tables)); a general accumulator has no form. |
| `SEQUENCE(rows, [columns], [start], [step])` | **unmappable** | — | Generates a number sequence; a sequence a Model needs (a date spine, a calendar) is a table. |
| `SORT(array, [sort_index], [sort_order], [by_col])` | structural | the Answer's sort | Sorting is a property of a query, not of a column. |
| `SORTBY(array, by_array1, [sort_order1], ...)` | structural | the Answer's sort | As `SORT`. |
| `TAKE(array, rows, [columns])` | structural | the Answer's top-N | Classified on its dominant use, `TAKE(SORT(…), 10)`, which is a top-N search. `TAKE` of an unsorted range is "the first N rows on the sheet" and unmappable ([**E6**](#how-to-read-the-tables)). |
| `TOCOL(array, [ignore], [scan_by_column])` | **unmappable** | — | Reshape ([**E6**](#how-to-read-the-tables)). Unpivoting wide data into a column is an ETL step. |
| `TOROW(array, [ignore], [scan_by_column])` | **unmappable** | — | Reshape. |
| `TRIMRANGE(range, [trim_rows], [trim_cols])` | direct | `[T::x]` (identity) | Trims empty edge rows and columns from a range. A Model column holds exactly its data rows, so the function is the identity; its sheet-level purpose (stop whole-column references dragging in blank rows) does not arise. |
| `UNIQUE(array, [by_col], [exactly_once])` | structural | the attribute alone in a search; inside a count, `unique count ( [x] )` | A spilled list of distinct values is a search on the attribute. `COUNTA(UNIQUE(A:A))` is `unique count ( [T::a] )` — **a space, not an underscore**. `exactly_once = TRUE` (values occurring once) is a `count = 1` filter on that search. |
| `VSTACK(array1, ...)` | **unmappable** | — | Appends ranges vertically — a **union** of tables. A ThoughtSpot Model joins tables but does not union them; stack the data in a warehouse view (gap [**G19**](#open-questions--gaps)). |
| `WRAPCOLS(vector, wrap_count, [pad_with])` | **unmappable** | — | Reshape. |
| `WRAPROWS(vector, wrap_count, [pad_with])` | **unmappable** | — | Reshape. |

---

## Database

Source: the *Database functions* list. Every function takes the same three arguments — a table, a
field and a **criteria block** — and every one maps to the `*_if` family once the block is read as
a condition ([**E11**](#how-to-read-the-tables)). This is the most cleanly convertible category in Excel: all
twelve are `direct`.

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `DAVERAGE(database, field, criteria)` | direct | `average_if ( <criteria> , [T::field] )` | **The criteria range becomes a condition** ([**E11**](#how-to-read-the-tables)): columns in one criteria row are ANDed, separate rows are ORed — `( [T::region] = 'West' and [T::year] = 2024 ) or ( [T::region] = 'East' )`. The `database` range is the Model's table; `field` is a column by name, or by position resolved from the header row. |
| `DCOUNT(database, field, criteria)` | direct | `count_if ( <criteria> , [T::field] )` | Counts **numeric** cells (as `COUNT`); omitting `field` counts matching records — use a key column. |
| `DCOUNTA(database, field, criteria)` | direct | `count_if ( <criteria> , [T::field] )` | Non-empty cells of any type (as `COUNTA`). |
| `DGET(database, field, criteria)` | direct | `if ( unique_count_if ( <criteria> , [T::field] ) = 1 ) then max_if ( <criteria> , [T::field] ) else null` | Returns the single matching value; Excel errors on zero or several matches. `max_if` alone silently picks one of several. The `else` is `null`, as `NA` (accepted as a branch value; `nullif ( 0 , 0 )`, which this row gave until 2026-10-06, is rejected — BL-339) ([**E8**](#how-to-read-the-tables)). |
| `DMAX(database, field, criteria)` | direct | `max_if ( <criteria> , [T::field] )` |  |
| `DMIN(database, field, criteria)` | direct | `min_if ( <criteria> , [T::field] )` |  |
| `DPRODUCT(database, field, criteria)` | direct | `exp ( sum_if ( <criteria> , ln ( [T::field] ) ) )` | Positive values only, as `PRODUCT`. |
| `DSTDEV(database, field, criteria)` | direct | `stddev_if ( <criteria> , [T::field] )` | Sample. |
| `DSTDEVP(database, field, criteria)` | direct | `sqrt ( variance_if ( <criteria> , [T::field] ) * ( count_if ( <criteria> , [T::field] ) - 1 ) / count_if ( <criteria> , [T::field] ) )` | Population, by the `STDEV.P` identity. |
| `DSUM(database, field, criteria)` | direct | `sum_if ( <criteria> , [T::field] )` |  |
| `DVAR(database, field, criteria)` | direct | `variance_if ( <criteria> , [T::field] )` | Sample. |
| `DVARP(database, field, criteria)` | direct | `variance_if ( <criteria> , [T::field] ) * ( count_if ( <criteria> , [T::field] ) - 1 ) / count_if ( <criteria> , [T::field] )` | Population, by the `VAR.P` identity. |

---

## Financial

Source: the *Financial functions* list. The category splits sharply into closed-form annuity and
discount arithmetic, which is native, and coupon-schedule or root-finding algorithms, which are not.

- **E18 — financial rows keep Excel's conventions, and four things decide the class.** (1) The
  **sign convention** — cash paid out is negative — is preserved in every composition, so
  `PMT` of a positive loan is negative, as in Excel. (2) **`type`** (payment at period end = 0,
  start = 1) is carried as `[t]` where the closed form admits it; rows note when only `type = 0`
  is given. (3) The **day-count `basis`**: actual/360 and actual/365 (bases 2 and 3) are
  `diff_days`, the 30/360 bases (0 and 4) reuse the `DAYS360` compositions, and actual/actual
  (basis 1) is unmappable — rows show basis 2. (4) **Iteration**: `IRR`, `XIRR`, `RATE`, `YIELD`
  and the odd-period yields are solved by Newton iteration in Excel and have no closed form, so
  they are `unmappable`; the coupon-schedule functions (`COUP*`, `PRICE`, `DURATION`,
  `ACCRINT`) are classed `unmappable` because they walk a coupon calendar whose construction
  depends on complete-month arithmetic — now pinned down (gap [**G12**](#open-questions--gaps),
  closed 2026-10-06: `diff_months` counts boundaries) but not yet built into a checked
  coupon-calendar composition. Rate and period arguments are usually literals or
  parameters; author `PMT` once and reference it by id.

| Excel | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ACCRINT(issue, first_interest, settlement, rate, par, frequency, [basis], [calc_method])` | **unmappable** | — | Coupon-schedule accrual ([**E18**](#financial)): the quasi-coupon periods are walked from `first_interest` per frequency and basis. No native or Snowflake function; pre-compute. |
| `ACCRINTM(issue, settlement, rate, par, [basis])` | direct | `[par] * [rate] * diff_days ( [settlement] , [issue] ) / 360` | Shown for basis 2 (actual/360); basis 3 divides by 365, bases 0/4 use the `DAYS360` compositions, basis 1 is unmappable ([**E18**](#financial)). |
| `AMORDEGRC(cost, date_purchased, first_period, salvage, period, rate, [basis])` | **unmappable** | — | French declining-balance depreciation with coefficient tables and a recursive book value. |
| `AMORLINC(cost, date_purchased, first_period, salvage, period, rate, [basis])` | **unmappable** | — | French linear depreciation with a prorated first period and a salvage floor; expressible in principle, but with no source of truth to verify it against here. |
| `COUPDAYBS(settlement, maturity, frequency, [basis])` | **unmappable** | — | Coupon-calendar arithmetic ([**E18**](#financial)). |
| `COUPDAYS(settlement, maturity, frequency, [basis])` | **unmappable** | — | As `COUPDAYBS`. |
| `COUPDAYSNC(settlement, maturity, frequency, [basis])` | **unmappable** | — | As `COUPDAYBS`. |
| `COUPNCD(settlement, maturity, frequency, [basis])` | **unmappable** | — | As `COUPDAYBS`. Stepping back from maturity in `12 / frequency`-month steps needs a complete-months count — composable since gap [**G12**](#open-questions--gaps) closed (2026-10-06), but the walk is not written or checked. |
| `COUPNUM(settlement, maturity, frequency, [basis])` | **unmappable** | — | As `COUPNCD`. |
| `COUPPCD(settlement, maturity, frequency, [basis])` | **unmappable** | — | As `COUPNCD`. |
| `CUMIPMT(rate, nper, pv, start_period, end_period, type)` | direct | `[formula_Pmt] * ( [end] - [start] + 1 ) - [formula_Cumprinc]` | Total payments minus total principal over the span, referencing `PMT` and `CUMPRINC` by formula id. `type = 0` ([**E18**](#financial)). |
| `CUMPRINC(rate, nper, pv, start_period, end_period, type)` | direct | `[formula_Balance End] - [formula_Balance Start]` | Principal repaid between two periods is the change in outstanding balance, where the balance after *k* payments is `[pv] * pow ( 1 + [r] , k ) + [formula_Pmt] * ( pow ( 1 + [r] , k ) - 1 ) / [r]` evaluated at `k = end` and `k = start − 1`. Excel returns the result as a negative number for a positive `pv`, which this sign arrangement preserves. `type = 0`. |
| `DB(cost, salvage, life, period, [month])` | direct | `[cost] * ( 1 - [rate] * [month] / 12 ) * pow ( 1 - [rate] , [period] - 2 ) * [rate]` | Middle periods, with `rate = ROUND(1 − (salvage/cost)^(1/life), 3)`; the first period is `cost × rate × month / 12` and the last prorates `(12 − month) / 12`, each an `if` branch on `period`. The geometric book value makes it closed-form. The 3-decimal rounding of `rate` is part of Excel's definition: `round ( 1 - pow ( [salvage] / [cost] , 1 / [life] ) , 0.001 )` ([**E12**](#how-to-read-the-tables)). Derived, not checked against Excel output. |
| `DDB(cost, salvage, life, period, [factor])` | direct | `greatest ( 0 , least ( [formula_Book] * [f] / [life] , [formula_Book] - [salvage] ) )` with `[formula_Book] = greatest ( [cost] * pow ( 1 - [f] / [life] , [period] - 1 ) , [salvage] )` | Double-declining balance with Excel's salvage floor. The book value before period *p* is geometric until the floor binds and constant at `salvage` after, so `greatest` gives it in closed form. Assumes `factor / life < 1`. Derived, not checked against Excel output ([Unverified](#unverified)). |
| `DISC(settlement, maturity, pr, redemption, [basis])` | direct | `( [redemption] - [pr] ) / [redemption] * 360 / diff_days ( [maturity] , [settlement] )` | Basis 2 shown; other bases per `ACCRINTM`. |
| `DOLLARDE(fractional_dollar, fraction)` | direct | `floor ( [x] ) + ( [x] - floor ( [x] ) ) * pow ( 10 , ceil ( log10 ( [f] ) ) ) / [f]` | `DOLLARDE(1.02, 16)` = 1.125. Excel truncates `fraction` to an integer. Shown for positive `x`; negative values are symmetric in Excel, so use the sign-split of `TRUNC`. |
| `DOLLARFR(decimal_dollar, fraction)` | direct | `floor ( [x] ) + ( [x] - floor ( [x] ) ) * [f] / pow ( 10 , ceil ( log10 ( [f] ) ) )` | Inverse of `DOLLARDE`. |
| `DURATION(settlement, maturity, coupon, yld, frequency, [basis])` | **unmappable** | — | Macaulay duration over the coupon schedule ([**E18**](#financial)). |
| `EFFECT(nominal_rate, npery)` | direct | `pow ( 1 + [nominal] / floor ( [npery] ) , floor ( [npery] ) ) - 1` | Excel truncates `npery`. |
| `FV(rate, nper, pmt, [pv], [type])` | direct | `if ( [r] = 0 ) then -1 * ( [pv] + [pmt] * [n] ) else -1 * ( [pv] * pow ( 1 + [r] , [n] ) + [pmt] * ( 1 + [r] * [t] ) * ( pow ( 1 + [r] , [n] ) - 1 ) / [r] )` | Closed-form annuity, with Excel's cash-flow sign convention (money paid out is negative) and its zero-rate special case ([**E18**](#financial)). `pv` and `type` default to 0. |
| `FVSCHEDULE(principal, schedule)` | direct | `[principal] * exp ( sum ( ln ( 1 + [T::rate] ) ) )` | The schedule range is a column of rates ([**E5**](#how-to-read-the-tables)); the compounded product is the log-sum identity, exact for rates above −1. Order does not matter to a product. |
| `INTRATE(settlement, maturity, investment, redemption, [basis])` | direct | `( [redemption] - [investment] ) / [investment] * 360 / diff_days ( [maturity] , [settlement] )` | Basis 2 shown. |
| `IPMT(rate, per, nper, pv, [fv], [type])` | direct | `-1 * ( [pv] * pow ( 1 + [r] , [per] - 1 ) + [formula_Pmt] * ( pow ( 1 + [r] , [per] - 1 ) - 1 ) / [r] ) * [r]` | Interest in period `per` is the balance carried into it times the rate — Excel's own identity `IPMT = FV(rate, per − 1, PMT, pv) × rate` for `type = 0`. With `type = 1` the first period's interest is 0 and later periods use `per − 2` and subtract the payment. |
| `IRR(values, [guess])` | **unmappable** | — | Root-finding by iteration ([**E18**](#financial)); no closed form, and Snowflake has no IRR function. |
| `ISPMT(rate, per, nper, pv)` | direct | `[pv] * [r] * ( [per] / [n] - 1 )` | Interest for straight-line principal repayment. |
| `MDURATION(settlement, maturity, coupon, yld, frequency, [basis])` | **unmappable** | — | `DURATION / (1 + yld / frequency)`; inherits `DURATION`. |
| `MIRR(values, finance_rate, reinvest_rate)` | direct | `pow ( -1 * sum_if ( [T::cf] > 0 , [T::cf] * pow ( 1 + [rr] , count ( [T::cf] ) - [T::period] ) ) / sum_if ( [T::cf] < 0 , [T::cf] / pow ( 1 + [fr] , [T::period] - 1 ) ) , 1 / ( count ( [T::cf] ) - 1 ) ) - 1` | **Closed form — unlike `IRR`.** The terminal value of the inflows at the reinvestment rate over the present value of the outflows at the finance rate, rooted. Needs a 1-based period column ([**E6**](#how-to-read-the-tables)). |
| `NOMINAL(effect_rate, npery)` | direct | `floor ( [npery] ) * ( pow ( 1 + [effect] , 1 / floor ( [npery] ) ) - 1 )` | Inverse of `EFFECT`. |
| `NPER(rate, pmt, pv, [fv], [type])` | direct | `if ( [r] = 0 ) then -1 * ( [pv] + [fv] ) / [pmt] else ln ( ( [pmt] * ( 1 + [r] * [t] ) - [fv] * [r] ) / ( [pmt] * ( 1 + [r] * [t] ) + [pv] * [r] ) ) / ln ( 1 + [r] )` | Closed form. |
| `NPV(rate, value1, ...)` | direct | `sum ( [T::cf] / pow ( 1 + [r] , [T::period] ) )` | **Excel discounts by position** — the first value one period, the second two. A Model has no positions, so it needs an explicit 1-based period column ([**E6**](#how-to-read-the-tables)); with one, the sum is exact. Excel's `NPV` also discounts the *first* flow, unlike the textbook form; a converter must not "fix" that. |
| `ODDFPRICE(settlement, maturity, issue, first_coupon, rate, yld, redemption, frequency, [basis])` | **unmappable** | — | Odd-first-period bond price ([**E18**](#financial)). |
| `ODDFYIELD(settlement, maturity, issue, first_coupon, rate, pr, redemption, frequency, [basis])` | **unmappable** | — | Iterative yield over an odd first period. |
| `ODDLPRICE(settlement, maturity, last_interest, rate, yld, redemption, frequency, [basis])` | **unmappable** | — | Odd-last-period bond price. |
| `ODDLYIELD(settlement, maturity, last_interest, rate, pr, redemption, frequency, [basis])` | **unmappable** | — | Odd-last-period yield. |
| `PDURATION(rate, pv, fv)` | direct | `( ln ( [fv] ) - ln ( [pv] ) ) / ln ( 1 + [r] )` |  |
| `PMT(rate, nper, pv, [fv], [type])` | direct | `if ( [r] = 0 ) then -1 * ( [pv] + [fv] ) / [n] else -1 * [r] * ( [pv] * pow ( 1 + [r] , [n] ) + [fv] ) / ( ( 1 + [r] * [t] ) * ( pow ( 1 + [r] , [n] ) - 1 ) )` | The base of the annuity family; author it as its own formula and reference it by id from `IPMT`, `PPMT`, `CUMIPMT` and `CUMPRINC`. |
| `PPMT(rate, per, nper, pv, [fv], [type])` | direct | `[formula_Pmt] - [formula_Ipmt]` | Payment minus its interest component. |
| `PRICE(settlement, maturity, rate, yld, redemption, frequency, [basis])` | **unmappable** | — | Coupon-bond price over the coupon schedule ([**E18**](#financial)). |
| `PRICEDISC(settlement, maturity, discount, redemption, [basis])` | direct | `[redemption] - [discount] * [redemption] * diff_days ( [maturity] , [settlement] ) / 360` | Basis 2 shown. |
| `PRICEMAT(settlement, maturity, issue, rate, yld, [basis])` | direct | `( 100 + diff_days ( [maturity] , [issue] ) / 360 * [rate] * 100 ) / ( 1 + diff_days ( [maturity] , [settlement] ) / 360 * [yld] ) - diff_days ( [settlement] , [issue] ) / 360 * [rate] * 100` | Basis 2 shown; a single interest payment at maturity, so no coupon schedule is involved. |
| `PV(rate, nper, pmt, [fv], [type])` | direct | `if ( [r] = 0 ) then -1 * ( [fv] + [pmt] * [n] ) else -1 * ( [fv] + [pmt] * ( 1 + [r] * [t] ) * ( pow ( 1 + [r] , [n] ) - 1 ) / [r] ) / pow ( 1 + [r] , [n] )` | Closed form, sign convention as `FV`. |
| `RATE(nper, pmt, pv, [fv], [type], [guess])` | **unmappable** | — | Iterative root-finding, as `IRR`. |
| `RECEIVED(settlement, maturity, investment, discount, [basis])` | direct | `[investment] / ( 1 - [discount] * diff_days ( [maturity] , [settlement] ) / 360 )` | Basis 2 shown. |
| `RRI(nper, pv, fv)` | direct | `pow ( [fv] / [pv] , 1 / [n] ) - 1` |  |
| `SLN(cost, salvage, life)` | direct | `( [cost] - [salvage] ) / [life]` |  |
| `SYD(cost, salvage, life, per)` | direct | `( [cost] - [salvage] ) * ( [life] - [per] + 1 ) * 2 / ( [life] * ( [life] + 1 ) )` |  |
| `TBILLEQ(settlement, maturity, discount)` | direct | `365 * [discount] / ( 360 - [discount] * diff_days ( [maturity] , [settlement] ) )` | Covers bills of up to 182 days ([**E3**](#how-to-read-the-tables)); longer bills use Excel's quadratic form, which is also native (`sqrt`) but not given here. |
| `TBILLPRICE(settlement, maturity, discount)` | direct | `100 * ( 1 - [discount] * diff_days ( [maturity] , [settlement] ) / 360 )` |  |
| `TBILLYIELD(settlement, maturity, pr)` | direct | `( 100 - [pr] ) / [pr] * 360 / diff_days ( [maturity] , [settlement] )` |  |
| `VDB(cost, salvage, life, start_period, end_period, [factor], [no_switch])` | **unmappable** | — | Declining balance with a switch to straight-line at the period where it pays more, summed over a fractional span. The switch point is found by iteration in Excel's algorithm. |
| `XIRR(values, dates, [guess])` | **unmappable** | — | Iterative, as `IRR`. |
| `XNPV(rate, values, dates)` | direct | `sum ( [T::cf] / pow ( 1 + [r] , diff_days ( [T::d] , group_aggregate ( min ( [T::d] ) , query_groups ( ) , query_filters ( ) ) ) / 365 ) )` | Discounting by **date** rather than position, so no period column is needed — the earliest date is the base, which Excel requires the first date to be. *Unverified* composition: a `group_aggregate` inside a row-level expression inside `sum`, the same shape as `AVEDEV`. |
| `YIELD(settlement, maturity, rate, pr, redemption, frequency, [basis])` | **unmappable** | — | Iterative yield over the coupon schedule. |
| `YIELDDISC(settlement, maturity, pr, redemption, [basis])` | direct | `( [redemption] - [pr] ) / [pr] * 360 / diff_days ( [maturity] , [settlement] )` | Basis 2 shown. |
| `YIELDMAT(settlement, maturity, issue, rate, pr, [basis])` | direct | `( ( 1 + diff_days ( [maturity] , [issue] ) / 360 * [rate] ) - ( [pr] / 100 + diff_days ( [settlement] , [issue] ) / 360 * [rate] ) ) / ( [pr] / 100 + diff_days ( [settlement] , [issue] ) / 360 * [rate] ) * 360 / diff_days ( [maturity] , [settlement] )` | Basis 2 shown; inverse of `PRICEMAT`. |

---

## Translator coverage (`ts formula translate --from excel`)

Since ts-cli 0.158.0 (BL-339) the rows below are **translator-backed**: `ts_cli/excel/` parses the
formula (structured references, A1 cells and ranges, array constants, dotted names) and applies
each row's rule as code — `ts_cli/excel/rules.py` names the row and every ThoughtSpot function the
rule emits, and `tools/validate/check_mapping_code_sync.py` fails if a rule emits a name its row
does not mention, a disproved or uncatalogued name, or if this list and the rule table disagree.
The criteria-string table is translator-backed for the `*IF` / `*IFS` rows. With `--role measure`,
a formula over row-level `[@Col]` references is built at the right grain: additive expressions as
the sum of each column, ratios as a ratio of totals `safe_divide ( sum ( n ) , sum ( d ) )`, a
numeric flag row-level (its column aggregation totals it). Acceptance: a 60-formula workbook,
every output VALIDATE_ONLY-clean on se-thoughtspot (2026-10-06,
`tools/ts-cli/tests/fixtures/excel_regression/`).

**Type check and implicit coercion (ts-cli 0.161.0).** Every translation is type-checked
against ThoughtSpot's argument types before it is reported (`ts_cli/excel/typecheck.py`): a
provable type error is NEEDS_REVIEW with a `type check:` note, never TRANSLATED, and Excel's own
coercions are written out first — see [Implicit type coercion](#implicit-type-coercion-not-counted--arguments).
Formula fidelity M1 (250 LibreOffice and Apache POI cases, 2026-10-06) found 36 translations
rejected at import and 7 silent wrong answers; the after-fixes run is in its
[report](../reviews/2026-10-06-fidelity-m1-excel.md#after-fixes-2026-10-07).

Every other row is **map-backed**: the translator returns NEEDS_REVIEW citing the row, and the
`ts-object-formula-translate` skill composes the answer from it, labelled hand-composed.

<!-- translator-coverage:start -->
`ABS` `ACOS` `ACOSH` `AND` `ASIN` `ASINH` `ATAN` `ATAN2` `ATANH` `AVERAGE` `AVERAGEIF` `AVERAGEIFS` `CEILING` `CEILING.MATH` `CEILING.PRECISE` `CHAR` `CODE` `CONCAT` `CONCATENATE` `COS` `COSH` `COUNT` `COUNTA` `COUNTIF` `COUNTIFS` `DATE` `DATEDIF` `DAY` `DAYS` `DEGREES` `EDATE` `EOMONTH` `EVEN` `EXACT` `EXP` `FACT` `FALSE` `FIND` `FINDB` `FLOOR` `FLOOR.MATH` `FLOOR.PRECISE` `IF` `IFERROR` `IFS` `INT` `ISBLANK` `ISLOGICAL` `ISNONTEXT` `ISNUMBER` `ISO.CEILING` `ISTEXT` `LEFT` `LEFTB` `LEN` `LENB` `LN` `LOG` `LOG10` `LOWER` `MAX` `MAXIFS` `MEDIAN` `MID` `MIDB` `MIN` `MINIFS` `MOD` `MONTH` `MROUND` `NETWORKDAYS` `NETWORKDAYS.INTL` `NOT` `NOW` `ODD` `OR` `PI` `POWER` `QUOTIENT` `RADIANS` `REPLACE` `REPLACEB` `RIGHT` `RIGHTB` `ROUND` `ROUNDDOWN` `ROUNDUP` `SEARCH` `SEARCHB` `SIGN` `SIN` `SINH` `SQRT` `STDEV.S` `SUBSTITUTE` `SUM` `SUMIF` `SUMIFS` `SWITCH` `TAN` `TANH` `TEXT` `TEXTJOIN` `TODAY` `TRIM` `TRUE` `TRUNC` `UNICHAR` `UNICODE` `UPPER` `VALUE` `VAR.S` `WEEKDAY` `YEAR`
<!-- translator-coverage:end -->

---

## Out of scope (counted, not rowed)

| Category | Functions | Why out of scope |
|---|--:|---|
| Engineering | 54 | Base conversion (`BIN2DEC`, `HEX2OCT`…), bitwise operations, complex-number arithmetic (`IM*`), Bessel and error functions and unit `CONVERT` — scientific workbook logic with essentially no BI-model usage; the few with a warehouse counterpart (`BITAND`) would be scalar pass-throughs. |
| Cube | 7 | `CUBEMEMBER`, `CUBEVALUE`, `CUBESET` and the rest query an OLAP / Power Pivot data model from cells — they *are* a semantic-layer query, so their ThoughtSpot equivalent is a search against a Model, not a formula. |
| Web | 3 | `ENCODEURL`, `FILTERXML`, `WEBSERVICE` fetch or parse web content at recalculation time; a Model reads only the warehouse. |
| Compatibility | 42 | Legacy aliases kept for older workbooks; each is the modern function below and takes that row's mapping. |
| Add-in and automation | 3 | `CALL`, `EUROCONVERT`, `REGISTER.ID` invoke DLLs or add-ins. |
| **Total** | **109** | |

**Compatibility aliases** — 42 functions, of which four (`CEILING`, `CONCATENATE`, `FLOOR`,
`FORECAST`) are also listed in a modern category and rowed there; the other 38 map exactly as
their modern successor:

`BETADIST` → `BETA.DIST` · `BETAINV` → `BETA.INV` · `BINOMDIST` → `BINOM.DIST` · `CEILING` (rowed) ·
`CHIDIST` → `CHISQ.DIST.RT` · `CHIINV` → `CHISQ.INV.RT` · `CHITEST` → `CHISQ.TEST` ·
`CONCATENATE` (rowed) · `CONFIDENCE` → `CONFIDENCE.NORM` · `COVAR` → `COVARIANCE.P` ·
`CRITBINOM` → `BINOM.INV` · `EXPONDIST` → `EXPON.DIST` · `FDIST` → `F.DIST.RT` · `FINV` → `F.INV.RT` ·
`FLOOR` (rowed) · `FORECAST` (rowed) · `FTEST` → `F.TEST` · `GAMMADIST` → `GAMMA.DIST` ·
`GAMMAINV` → `GAMMA.INV` · `HYPGEOMDIST` → `HYPGEOM.DIST` (PMF only) · `LOGINV` → `LOGNORM.INV` ·
`LOGNORMDIST` → `LOGNORM.DIST` (CDF only) · `MODE` → `MODE.SNGL` · `NEGBINOMDIST` → `NEGBINOM.DIST` (PMF only) ·
`NORMDIST` → `NORM.DIST` · `NORMINV` → `NORM.INV` · `NORMSDIST` → `NORM.S.DIST` (CDF) ·
`NORMSINV` → `NORM.S.INV` · `PERCENTILE` → `PERCENTILE.INC` · `PERCENTRANK` → `PERCENTRANK.INC` ·
`POISSON` → `POISSON.DIST` · `QUARTILE` → `QUARTILE.INC` · `RANK` → `RANK.EQ` · `STDEV` → `STDEV.S` ·
`STDEVP` → `STDEV.P` · `TDIST` → `T.DIST.2T` / `T.DIST.RT` (by `tails`) · `TINV` → `T.INV.2T` ·
`TTEST` → `T.TEST` · `VAR` → `VAR.S` · `VARP` → `VAR.P` · `WEIBULL` → `WEIBULL.DIST` · `ZTEST` → `Z.TEST`.

The legacy forms matter more than their status suggests: workbooks written before Excel 2010 use
`STDEV`, `VAR`, `PERCENTILE`, `RANK` and `CONCATENATE` almost exclusively, so a converter meets the
aliases more often than the modern names.

Not on the category page as rendered on 2026-10-06, and therefore not counted: the `PY` (Python in
Excel) and `COPILOT` functions. Both execute code or a model call at recalculation time and would
be `unmappable`.

---

## Passthrough caveat (applies to every `passthrough` row)

The `sql_*_op` family embeds raw warehouse SQL: correctness depends on the connection's dialect,
and the expression is opaque to ThoughtSpot's query planner (no automatic aggregation-grain
handling). Every template here is written for **Snowflake**; on another warehouse, re-derive it
from that platform's mapping (`agents/shared/mappings/ts-databricks/` for Databricks) — function
names (`REGEXP_SUBSTR` vs `REGEXP_EXTRACT`), regex dialects and format models all move. A
converter should emit each with an issue of severity warning so users review it, and the aggregate
variants are flagged for review under the repo's pass-through policy (PT1 in
`agents/shared/schemas/ts-model-conversion-invariants.md`).

The Ossie map's three operational rules apply unchanged
([E7–E9 there](../ossie/ts-ossie-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)):
the variant fixes type **and** measure/attribute role; a pass-through carrying `PARTITION BY` is
wrapped in `group_aggregate ( … , query_groups ( ) + { [partition_col] } , query_filters ( ) )`;
and no pass-through may carry a runtime parameter. The last one bites Excel conversions
particularly: **an input cell referenced by a formula is naturally a parameter** in ThoughtSpot,
and a pass-through cannot take one — so a `RANDBETWEEN(1, B1)` or `LARGE(A:A, B1)` with `B1` as an
input cell needs the literal baked in, or a native form.

---

## Reverse direction (ThoughtSpot → Excel)

`ts formula translate '<formula>' --from thoughtspot --to excel [--table Table1]` (ts-cli 0.158.0,
`ts_cli/excel/to_excel.py`) does this deterministically for one formula: row-level references
become `[@Col]`, references inside an aggregate `Table1[Col]`, and a construct with no Excel form
(window functions, `rank`, `sql_*_op`, a `query_groups ( )` grain) comes back NEEDS_REVIEW with
the reason. The table below is the design reference it follows, and what an Excel user rebuilding a
ThoughtSpot Model's logic in a sheet would reach for, and where they could not.

| ThoughtSpot | Nearest Excel | Disposition |
|---|---|---|
| `group_aggregate ( agg , { [a] } , query_filters ( ) )` and the `group_*` shorthands | `SUMIFS` over the whole table keyed on the row's `[a]` (`SUMIFS(C:C, A:A, [@A])`), or a pivot table | composable — fixed-grain LOD is a self-keyed `*IFS` |
| `group_aggregate ( … , query_groups ( ) ± { [a] } , … )` | — | no equivalent — a sheet has no "dimensions in the current query"; the closest is a pivot table's `GETPIVOTDATA` |
| `query_filters ( )` | `SUBTOTAL(109, …)` over a filtered Table | partial — `SUBTOTAL` sees AutoFilter, not slicers on other tables |
| `cumulative_sum` / `_average` / `_max` / `_min` | expanding range `SUM($B$2:B2)` filled down | composable under a fixed sheet order — and that order is exactly what the ThoughtSpot form does *not* fix ([**E6**](#how-to-read-the-tables)) |
| `moving_*` | relative range `AVERAGE(B2:B4)` filled down | composable, same order caveat |
| `rank_percentile ( agg , 'asc' )` | `(1 - PERCENTRANK.INC(range, x)) * 100` | composable |
| `last_value` / `first_value` (semi-additive) | `LOOKUP(2, 1/(A:A=key), B:B)` "last match" idiom | partial — a sheet has no roll-up rule, so a snapshot measure summed in a pivot is silently wrong there too |
| `unique count ( [x] )` / `unique_count_if` | `COUNTA(UNIQUE(range))` / `COUNTA(UNIQUE(FILTER(…)))` | composable |
| `safe_divide ( [a] , [b] )` | `IF(b=0, 0, a/b)` | exact — `IFERROR(a/b, 0)` also swallows every other error; `ts formula translate --from thoughtspot --to excel` writes the `IF` form |
| `start_of_week` / `start_of_quarter` / `start_of_year` | `A2 - WEEKDAY(A2, 2) + 1`, `DATE(YEAR(A2), …)` | composable — the `WEEKDAY(A2, 2)` form assumes the Model calendar's default Monday week start |
| `is_weekend ( [d] )` | `WEEKDAY(A2, 2) > 5` | composable |
| `year ( [d] , fiscal )` and the `fiscal` family | `YEAR(EDATE(A2, 12 - start_month + 1))` style shifts | partial — a sheet has no fiscal-calendar object; each formula hand-encodes the offset |
| `concat ( "{caption}" , … , "{/caption}" , [url] )` | `HYPERLINK(url, label)` | composable |
| `ts_username`, `ts_groups`, `ts_var ( … )` | — | no equivalent — a workbook has no signed-in user to secure against |
| Runtime parameters `[Param]` | an input cell | composable — and the most natural mapping in either direction |
| `sql_*_op` | — | no equivalent — Excel cannot reach the warehouse from a cell formula |

---

## Open questions / gaps

ThoughtSpot capability gaps — and two repo-internal inconsistencies — that this map exposes.
Each line says what it costs an Excel conversion.

| # | Gap | Impact |
|---|---|---|
| **G1** | ~~`round ( x , y )`: increment or digit count?~~ **Closed 2026-10-06** — increment, by live probe ([**E12**](#how-to-read-the-tables)). | Residual cost: repo translators that read it as a digit count emitted wrong roundings (or NULL for zero digits); corrected by BL-331 (PR #558). |
| **G2** | No native `trim`, `upper`, `lower`, `replace` or `proper`. | Every text-cleaning formula in a sheet (and Excel `TRIM` is ubiquitous in imported data) becomes a warehouse pass-through that ThoughtSpot cannot plan or validate. |
| **G3** | No statistical special functions (`erf`, incomplete gamma/beta, gamma), and Snowflake has none either. | 38 of the 48 unmappable statistical functions are distributions, inverse distributions, special functions or hypothesis-test p-values that fail on this alone (the other 10 are array-returning or ETS forecasting), so statistical-inference workbooks cannot move at the formula level; only the closed-form exponential, Weibull, normal/log-normal *densities*, `PHI` and the literal-alpha `CONFIDENCE.NORM` survive. |
| **G4** | No iterative / root-finding capability. | `IRR`, `XIRR`, `RATE` and bond yields — the core of financial-analysis workbooks — have no form short of a UDF. |
| **G5** | The Ossie map classes `STDDEV_POP`, `VAR_POP` and `TRUNC` as `passthrough`, but exact native compositions exist (`variance × (n−1)/n`; sign-split `floor`/`ceil`). The sibling Sigma and Omni function maps likewise classed their population standard-deviation / variance rows `passthrough` until they were aligned to this map's `STDEV.P` / `VAR.P` forms. | Not a ThoughtSpot gap but a repo inconsistency: those maps understated their `direct` share and emit avoidable pass-throughs. The Ossie rows remain to be revisited; the shared compositions are themselves unverified (see [Unverified](#unverified)), so one probe covers all three maps. |
| **G6** | No string aggregation. | `TEXTJOIN` / `CONCAT` over a range — common for "list the products in this order" cells — are aggregate pass-throughs flagged for review. |
| **G7** | No regular expressions. | Excel's new `REGEX*` functions translate only as pass-throughs, with a PCRE2 → POSIX dialect gap a template cannot fix. |
| **G8** | No percentile function beyond `median`. | `PERCENTILE.INC` / `QUARTILE.INC` are pass-throughs, and so are the exclusive variants (`PERCENTILE.EXC`, `QUARTILE.EXC`), built from `ARRAY_AGG` indexing and unverified. |
| **G9** | ~~No documented NULL literal.~~ **Closed 2026-10-06** — `null` is accepted as an `if` branch value; the `nullif ( 0 , 0 )` trick this row relied on is **rejected** (`nullif` is not a ThoughtSpot function — [probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat), BL-339). | `NA()` and `DGET`'s no-match branch use `… else null`. A NULL outside an `if` branch has no form. |
| **G10** | No TIME type. | `TIME`, `TIMEVALUE` and time-of-day arithmetic land on DATETIME pass-throughs with a warehouse-default date part. |
| **G11** | ~~Is `day_number_of_week` fixed at 1 = Monday, or does it follow the instance's week-start setting?~~ **Closed 2026-10-06** — fixed at 1 = Monday … 7 = Sunday: it compiles to `(MOD((DATEDIFF(day, DATE '1970-01-01', d) + 3), 7) + 1)` (live, se-thoughtspot: 2026-10-04 Sun = 7, 2026-10-05 Mon = 1, 2026-10-10 Sat = 6, 2020-01-01 Wed = 3), consistent with the Model's default calendar, Gregorian with a Monday week start (domain review, 2026-10-06). | The `WEEKDAY`, `WEEKNUM`, `NETWORKDAYS` and `WORKDAY` compositions stand. They assume a Monday week start and diverge on a Model whose calendar starts elsewhere. Residual, unverified: whether a non-default Model calendar changes the `+3` constant (one cluster probed); and the default `start_of_week` compiled to `DATE_TRUNC(week, d)`, which is Monday only while the warehouse's `WEEK_START` is 0 or 1 — BL-334. |
| **G12** | ~~`diff_months` / `diff_years`: boundary count or complete periods?~~ **Closed 2026-10-06** — boundaries. `diff_months` = `DATEDIFF(month, epoch, end) - DATEDIFF(month, epoch, start)` (Jan31→Feb1 = 1, Jan31→Feb28 = 1, Jan20→Mar15 = 2, reversed = −1); `diff_years` = `EXTRACT(YEAR FROM end) - EXTRACT(YEAR FROM start)` (Dec31→Jan1 = 1; 2025-07-01→2026-06-30 = 1). Live, se-thoughtspot. | `DATEDIF("M"/"Y")`'s day-of-month correction is confirmed necessary and correct in shape. The coupon-schedule rows stay `unmappable`: a complete-months count is now composable, but the coupon-calendar walk built on it has not been written or checked. |
| **G13** | Range joins (`>=` / `<` in a Model join's `on`) are documented but have never been exercised on a live Model (Model TML reference, *Non-equality joins: zero observed*). | Approximate-match `VLOOKUP` / `LOOKUP` (tax bands, price tiers) depends on them; if they misbehave, every banded lookup needs an ETL-computed band key instead. |
| **G14** | Window functions cannot declare a partition (Ossie map E13). | Every `OFFSET`-style ordered idiom partitions by the user's search instead of by the sheet's structure, so a running total that was per-customer in Excel becomes per-whatever-the-user-groups-by. |
| **G15** | ~~A zero divisor errors the whole Snowflake query.~~ **Corrected 2026-10-06** — ThoughtSpot guards the divisor: a plain `/` returns NULL on zero and `safe_divide` returns 0 ([probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)). | No guard is needed to keep an Answer running; choose `/` (blank-like NULL) or `safe_divide` (0) by what the sheet's `IFERROR` fallback was. |
| **G16** | `sign` and `to_bool` are recorded as live-confirmed present by the Qlik map's header but are absent from the formula reference. | The catalog that the `check_formula_catalog` validator reads is incomplete; this map composes `SIGN` rather than rely on an uncatalogued name. |
| **G17** | No product aggregate. | `PRODUCT` and `FVSCHEDULE` rely on `exp ( sum ( ln ( ) ) )`, exact only for positive values. |
| **G18** | No hyperbolic or extended trigonometric functions, no `pi`. | Cosmetic — every one composes exactly — but each composition is a place for a degree/radian slip. |
| **G19** | No union in a Model. | `VSTACK` (and any sheet that appends monthly tabs) needs a warehouse view before it can be modelled. |

### Unverified

Rows that rest on something this map could not confirm from its sources:

- **No composition in this document has been import-probed**, with two exceptions, both
  live-verified on se-thoughtspot 2026-10-06 ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)): the `NETWORKDAYS.INTL` per-weekday
  counting form for weekend codes 1, 11 and `"1000001"` without holidays (7 ranges), and the inline
  `holidays` term with code 1 (6 ranges), all matching Excel. **Not probed:** the composition on the
  `NETWORKDAYS` row itself, other weekend codes, holidays with any other code, duplicate holidays,
  and `WORKDAY` / `WORKDAY.INTL` in any form. The other natively-composed rows
  (`NETWORKDAYS`, `WORKDAY`, `WEEKNUM`, `WEEKDAY`, `DATE`, `EOMONTH`, `REPLACE`, `TEXTAFTER`, the
  annuity family, the regression family) are hand-derived and spot-checked by arithmetic. A single
  `ts tml import --policy VALIDATE_ONLY` pass, as the Ossie map ran, would settle parse validity;
  numeric correctness needs result checks against Excel.
- **A `group_aggregate` nested in a row-level expression inside an aggregate** (`AVEDEV`, `XNPV`,
  `STANDARDIZE` with column statistics) follows the formula reference's weighted-average shape but
  is not itself verified.
- ~~**`nullif ( 0 , 0 )` as a NULL literal**~~ — disproved 2026-10-06: `nullif` does not exist; `NA` and `DGET` now use `else null` (gap **G9**, closed; BL-339).
- ~~**`day_number_of_week` base**~~ — settled 2026-10-06 (gap **G11**, closed).
- ~~**`diff_months` semantics**~~ — settled 2026-10-06 (gap **G12**, closed).
- **Week-start dependence** — every weekday/week composition assumes the Model calendar's
  default Monday week start; `start_of_week`'s compiled `DATE_TRUNC(week, d)` is Monday only
  while the warehouse's `WEEK_START` is 0 or 1 (BL-334).
- **Case-insensitive comparison beyond the probed forms** — `=`, `contains` and `strpos` are
  live-verified case-insensitive (2026-10-06); `!=`, `in { }` and the `strpos ( … ) = 1` prefix
  composition were not probed (BL-333).
- **Pass-through template syntax that ThoughtSpot's template parser may reject.** The formula
  reference records that the `sql_*_op` parser rejects colon-and-dot JSON path syntax even though
  the warehouse accepts it
  ([`thoughtspot-formula-patterns.md:669-683`](../../agents/shared/schemas/thoughtspot-formula-patterns.md#json--variant-path-access--bracket-notation-only)).
  By the same risk, this map writes every cast as `CAST(… AS FLOAT)` rather than `::FLOAT`, and
  parenthesises every subscripted aggregate as `(ARRAY_AGG(…) WITHIN GROUP (…))[n]` — but neither
  the subscript, `ARRAY_SLICE`, nor the lambda arrow `->` in `TRIMMEAN`'s `REDUCE` has been checked
  against the template parser. Affects `LARGE`, `SMALL`, `PERCENTILE.EXC`, `QUARTILE.EXC`,
  `TRIMMEAN`.
- **Window templates inside `sql_*_aggregate_op`** (`PERCENTRANK.EXC`, `RANK.AVG`, the `ROW`
  idiom) follow the formula reference's two rules (operand aggregated inside the window; `ORDER BY`
  matching the bucketed GROUP BY expression, `thoughtspot-formula-patterns.md:698-723`) but have
  not been run in a search.
- **`add_seconds` on a DATE** (the `TIME` row's native idiom) — documented for DATETIME only.
- **`safe_divide` with a NULL divisor** returning NULL (`IFERROR`, worked shape) — inferred from
  SQL semantics, not probed.
- **Snowflake function behaviour** assumed without a live check: `KURTOSIS` / `SKEW` matching
  Excel's bias-corrected sample estimators; POSIX classes in `REGEXP_REPLACE` (`CLEAN`); the `X`
  hexadecimal format element (`BASE`, `DECIMAL`); `SNOWFLAKE.CORTEX.TRANSLATE` inside a
  pass-through; the absence of `GCD`/`LCM`, `ERF` and distribution functions; `COLLATE 'utf8'` as
  a case-sensitive override (`EXACT`).
- **Excel behaviour** taken from documentation: the `DAYS360` US-method end-of-February rule
  (documented and actual behaviour are known to diverge); `DDB` and `DB` closed forms are derived,
  not checked against Excel output.
- **`sign`** — present per the Qlik audit header, absent from the formula reference (gap
  **G16**); not used.

---

## Worked shape

A small sales workbook built on an Excel Table named `Sales` and a lookup Table `Customers`, and
the ThoughtSpot Model formulas that replace it.

Excel:

```text
Sales[Revenue West 2024]  =SUMIFS(Sales[Amount], Sales[Region], "West", Sales[Date], ">="&DATE(2024,1,1))
Sales[Unit Price]         =IFERROR([@Amount]/[@Qty], 0)
Sales[Customer Segment]   =XLOOKUP([@CustID], Customers[ID], Customers[Segment], "Unknown")
Sales[Avg Order]          =ROUND(AVERAGE(Sales[Amount]), 2)
Sales[Days To Ship]       =NETWORKDAYS([@OrderDate], [@ShipDate])
Sales[Clean Name]         =TRIM([@Name])
Sales[Amount Spread]      =STDEV.P(Sales[Amount])
```

ThoughtSpot — one Model join and seven formulas (each needs a `columns[]` entry referencing it by
`formula_id`):

```yaml
model_tables:
- name: SALES
  joins:
  - with: CUSTOMERS
    'on': '[SALES::Cust Id] = [CUSTOMERS::Id]'     # XLOOKUP is structural: a join, not a formula
    type: LEFT_OUTER
    cardinality: MANY_TO_ONE

formulas:
- id: formula_Revenue West 2024
  name: Revenue West 2024
  expr: "sum_if ( [SALES::Region] = 'West' and [SALES::Date] >= to_date ( '2024-01-01' , 'yyyy-MM-dd' ) , [SALES::Amount] )"

- id: formula_Unit Price
  name: Unit Price
  expr: "safe_divide ( [SALES::Amount] , ifnull ( [SALES::Qty] , 0 ) )"   # IFERROR(a/b, 0); ifnull matches a blank Qty

- id: formula_Customer Segment
  name: Customer Segment
  expr: "ifnull ( [CUSTOMERS::Segment] , 'Unknown' )"               # if_not_found -> ifnull over the join

- id: formula_Avg Order
  name: Avg Order
  expr: "round ( average ( [SALES::Amount] ) , 0.01 )"              # 2nd arg is an increment (E12)

- id: formula_Days To Ship
  name: Days To Ship
  expr: "5 * floor ( ( diff_days ( [SALES::Ship Date] , [SALES::Order Date] ) + 1 ) / 7 ) + mod ( diff_days ( [SALES::Ship Date] , [SALES::Order Date] ) + 1 , 7 ) - greatest ( 0 , least ( day_number_of_week ( [SALES::Order Date] ) + mod ( diff_days ( [SALES::Ship Date] , [SALES::Order Date] ) + 1 , 7 ) - 1 , 7 ) - greatest ( day_number_of_week ( [SALES::Order Date] ) , 6 ) + 1 )"

- id: formula_Clean Name
  name: Clean Name
  expr: "sql_string_op ( \"TRIM(REGEXP_REPLACE({0}, ' +', ' '))\" , [SALES::Name] )"   # Excel TRIM collapses inner spaces

- id: formula_Amount Spread
  name: Amount Spread
  expr: "sqrt ( variance ( [SALES::Amount] ) * ( count ( [SALES::Amount] ) - 1 ) / count ( [SALES::Amount] ) )"
```

Six of the seven are where a name-for-name translator goes wrong: `XLOOKUP` is a join rather than
a function; `IFERROR` around a division is `safe_divide`, because the bare division would give NULL rather
than the fallback 0 on a zero `Qty` (with `ifnull` so a blank `Qty` still gets the fallback); `ROUND`'s second argument changes meaning — `2` digits is the increment `0.01` ([**E12**](#how-to-read-the-tables));
`NETWORKDAYS` exists natively only as a composition; `TRIM` is a pass-through *and* SQL `TRIM` is
not Excel `TRIM`; and `STDEV.P` is not `stddev`. Only `SUMIFS` → `sum_if` is a clean rename, and
there the text criterion `"West"` was case-insensitive in Excel and — because ThoughtSpot lowercases both sides of `=` (live-verified 2026-10-06) — is case-insensitive here too.
