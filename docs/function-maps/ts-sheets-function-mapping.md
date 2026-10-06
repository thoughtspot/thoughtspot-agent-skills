<!-- currency: google-sheets — 2026-10 (Google Sheets function list) -->
# Google Sheets formula functions → ThoughtSpot function mapping (delta on Excel)

**Status:** research draft (2026-10-06) — a **delta** on the
[Excel function map](ts-excel-function-mapping.md) (the *Excel map*), written from Google's documentation
and this repo's live-verified references; **no row has been import-probed on a ThoughtSpot instance**
(see [Unverified](#unverified)). Every composition and template below is hand-derived, not
import-probed · **Coverage:** 63 functions rowed — 46 that Excel lacks and 17 shared names whose behaviour differs — plus 451 shared names that take an Excel map row unchanged ([reconciliation](#same-as-the-excel-map-reconciliation)) and 3 out-of-scope engineering functions, from Google's 515-name list · **Classifications:** as the Excel map —
`direct` (native ThoughtSpot formula, possibly a composition) · `passthrough` (a typed `sql_*_op`;
**Snowflake is the reference dialect** for every template here) · `structural` (a Model or Answer
construct rather than a formula — [Excel **E13**](ts-excel-function-mapping.md#how-to-read-the-tables)) ·
`unmappable` (no native expression and no single reference-warehouse function) · **TS ground truth:**
[`thoughtspot-formula-patterns.md`](../../agents/shared/schemas/thoughtspot-formula-patterns.md) (the
*formula reference*), the Excel map and the
[Snowflake formula mapping](../../agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md).
Google's side comes from the
[Google Sheets function list](https://support.google.com/docs/table/25273) and each function's own
help page, as rendered on 2026-10-06; QUERY's language from the
[Google Visualization API Query Language reference](https://developers.google.com/chart/interactive/docs/querylanguage).

Google Sheets shares most of its function names with Excel, and for most of them the ThoughtSpot
translation is the same. This map therefore rows only what differs, and answers one question per
row: *if a sheet's logic is rebuilt as a ThoughtSpot Model, what does this function become, given
that the Excel map already covers its namesake?* Rules are numbered **E1**–**E9** and are this
document's own; the Excel map's rules are cited as **Excel E*n***.

**Translator-backed since ts-cli 0.158.0 (BL-339):** `ts formula translate --from google_sheets` runs
the Excel translator (`ts_cli/excel/`) with this map's delta rules first, then the Excel map's rows
for every name not rowed here (E1). The delta rows it applies as code are listed below and checked
against `ts_cli/excel/rules.py` by `check_mapping_code_sync.py`; every other row of this map is
map-backed (NEEDS_REVIEW citing the row). `QUERY` is reported as structural, never translated.

<!-- translator-coverage:start -->
`ADD` `ARRAYFORMULA` `CONCAT` `COUNTUNIQUE` `DIVIDE` `EQ` `GT` `GTE` `IFERROR` `LT` `LTE` `MINUS` `MULTIPLY` `NE` `POW` `QUERY` `REGEXEXTRACT` `REGEXMATCH` `REGEXREPLACE` `UMINUS` `UNARY_PERCENT` `UPLUS`
<!-- translator-coverage:end -->

---

## How to read the tables

Cell notation is the Excel map's: canonical spacing, `[T::x]` for a Model column, `[x]` for any
operand, `[formula_Name]` for a formula referenced by id.

- **E1 — a delta inventory.** The inventory is Google's function list as rendered on 2026-10-06.
  A function gets a row here **only** if (a) Excel has no function of that name, or (b) the name
  is shared but Google's own help page documents a behaviour that **changes the ThoughtSpot
  translation** — arguments, defaults, case, array behaviour, epoch, format codes. **Every other
  Sheets function takes its Excel map row unchanged:** *same as the Excel map row*. That rule covers 451 functions (a name that is an Excel compatibility alias takes its successor's row); [Same as the Excel map](#same-as-the-excel-map-reconciliation) lists them by
  name, with the count, so the claim is checkable. Where an Excel row says "as `X`" and `X` is rowed
  here, read this map's `X` (so `SEARCHB` follows this map's `SEARCH`).
- **E2 — the Excel map's framing rules apply unchanged.** A range is a column and a criteria pair
  is a condition ([Excel **E5**](ts-excel-function-mapping.md#how-to-read-the-tables)); position has
  no row-level analogue ([Excel **E6**](ts-excel-function-mapping.md#how-to-read-the-tables)); several
  arguments are row-wise ([**E7**](ts-excel-function-mapping.md#how-to-read-the-tables)); there are no
  error values ([**E8**](ts-excel-function-mapping.md#how-to-read-the-tables)); dates are values
  ([**E9**](ts-excel-function-mapping.md#how-to-read-the-tables), amended by **E3** below); booleans are
  not numbers and blank is not zero ([**E10**](ts-excel-function-mapping.md#how-to-read-the-tables));
  criteria strings become conditions ([**E11**](ts-excel-function-mapping.md#how-to-read-the-tables) and
  its [criteria table](ts-excel-function-mapping.md#criteria-strings-not-counted--arguments));
  `round`'s second argument is an increment ([**E12**](ts-excel-function-mapping.md#how-to-read-the-tables));
  `structural` rows ([**E13**](ts-excel-function-mapping.md#how-to-read-the-tables)); `LET`, `LAMBDA` and
  — in Sheets — **named functions** (Data › Named functions) are inlined or hoisted
  ([**E14**](ts-excel-function-mapping.md#how-to-read-the-tables)); type tests resolve from the column's
  type ([**E15**](ts-excel-function-mapping.md#how-to-read-the-tables)). Partial coverage names its
  fallback and every passthrough names its variant
  ([**E3**, **E4**](ts-excel-function-mapping.md#how-to-read-the-tables)).
- **E3 — the date serial has no phantom leap day.** Google: *"Google Sheets uses the 1900 date
  system. It counts the days since December 30, 1899 (not including December 30, 1899)"*
  ([DATE](https://support.google.com/docs/answer/3092969)); `N` and `TO_DATE` use the same base, with
  negative values before it and the fraction as time of day
  ([N](https://support.google.com/docs/answer/3093357),
  [TO_DATE](https://support.google.com/docs/answer/3094239)). So the Excel map's serial conversion
  `add_days ( to_date ( '1899-12-30' , 'yyyy-MM-dd' ) , [T::serial] )` — exact in Excel only from serial
  61, because of Excel's fictitious 1900-02-29 — is exact for **every** Sheets serial, including
  negative ones. The inverse, a date to its serial (Sheets `N`, `TO_PURE_NUMBER` on a date), is
  `diff_days ( [d] , to_date ( '1899-12-30' , 'yyyy-MM-dd' ) )`. `DATE`'s two-digit-year rule (0–1899
  adds 1900) is the same as Excel's, so the Excel `DATE` row stands.
- **E4 — string comparison: Sheets formulas ignore case, QUERY does not.** ThoughtSpot's `=`,
  `contains` and `strpos` are case-insensitive (live-verified 2026-10-06 —
  [probe record §4](../reviews/2026-10-06-formula-semantics-probes.md#4-string-comparison-is-case-insensitive-bl-333), [formula reference](../../agents/shared/schemas/thoughtspot-formula-patterns.md#string-comparison-is-case-insensitive);
  BL-333). On the Sheets side, Google documents `COUNTIF` as *"not case sensitive"*
  ([COUNTIF](https://support.google.com/docs/answer/3093480)), `SEARCH` as *"not case-sensitive"*, and
  `EXACT` and `FIND` as case-sensitive
  ([EXACT](https://support.google.com/docs/answer/3094073), [FIND](https://support.google.com/docs/answer/3094126)) —
  so criteria, `SEARCH`, `EXACT` and `FIND` translate exactly as their Excel rows. The bare `=`
  operator (and `EQ`) is **not documented either way**: the [EQ](https://support.google.com/docs/answer/3093593)
  page says only *"Equivalent to the "=" operator"*. Sheets `"a" = "A"` returning TRUE is
  common knowledge, not a Google statement, so the native `=` mapping below rests on it and is
  marked *unverified* ([G6](#open-questions--gaps)). **QUERY is the opposite and is documented:**
  in the Visualization query language *"Identifiers and string literals are case-sensitive"* and
  *"String matching is case sensitive"* — so a QUERY string filter needs a passthrough to keep its
  meaning (see [QUERY clauses](#query-clauses-not-counted--arguments)).
- **E5 — regular expressions are RE2.** *"Google products use RE2 for regular expressions. Google
  Sheets supports RE2 except Unicode character class matching"*
  ([REGEXEXTRACT](https://support.google.com/docs/answer/3098244)). Snowflake's dialect is POSIX ERE
  with Perl-style escapes. RE2, like Snowflake, has no look-arounds and no back-references inside a
  pattern, so the dialect gap is narrower than Excel's PCRE2 one — but RE2's lazy quantifiers
  (`*?`), named groups, non-capturing groups (`(?:…)`) and inline flags (`(?i)`) still need
  rewriting: translate `(?i)` into the `'i'` regex-parameter argument of the Snowflake function,
  and treat the others as *unverified* in a template. Non-capturing groups matter for
  `REGEXEXTRACT`, because RE2 does not count them when deciding which groups to return: if
  Snowflake rejects `(?:…)` (unverified), rewriting it as a capturing group shifts every later
  group number, so the template's group argument must be renumbered to match. In a replacement string RE2's `$1` is Snowflake's `\\1`. Sheets'
  `REGEX*` functions accept **text only** (each page says numbers must be converted with `TEXT`),
  which a typed `sql_string_op` operand already guarantees.
- **E6 — `ARRAYFORMULA` and spill are already what a Model formula is.** A Sheets formula that
  maps over a range (`ARRAYFORMULA(A2:A * B2:B)`, or the same expression auto-expanded) is a
  row-level formula, `[T::a] * [T::b]` — the
  [Excel **E5**/**E7**](ts-excel-function-mapping.md#how-to-read-the-tables) reading. So when the
  inner expression is **element-wise** (arithmetic, `IF`, text and date functions applied per
  cell), `ARRAYFORMULA` is dropped and its argument translated. It is **not** a no-op when the inner
  expression reads whole ranges per row or collapses them:
  - `ARRAYFORMULA(COUNTIF(A2:A, A2:A))` and `ARRAYFORMULA(SUMIF(A2:A, A2:A, B2:B))` compute, for each
    row, an aggregate over every row with the same key — a fixed-grain aggregate,
    `group_aggregate ( count ( [T::key] ) , { [T::a] } , query_filters ( ) )` and
    `group_aggregate ( sum ( [T::b] ) , { [T::a] } , query_filters ( ) )`, not a row-level formula;
  - `AND` and `OR` are not element-wise: `ARRAYFORMULA(AND(A2:A > 0, B2:B > 0))` returns **one**
    value for the whole range. The per-row intent is written `(A2:A > 0) * (B2:B > 0)`, which is
    `[T::a] > 0 and [T::b] > 0`; the scalar reading is the Excel `AND` row's range aggregate;
  - `ROW(A2:A)` inside an array formula is a row number — positional
    ([Excel **E6**](ts-excel-function-mapping.md#how-to-read-the-tables) and its `ROW` row).
  The patterns that existed only to make a column formula work on a sheet are dropped too: the
  header-row stack `{"Total"; ARRAYFORMULA(…)}` (a column has a name, not a header cell), and the
  blank-row guard `IF(A2:A = "", , …)` (a Model has no empty trailing rows; keep an `isnull` guard
  only where the data has real NULLs). Array literals use `,` between columns and `;` between rows
  (`{1, 2; 3, 4}`, Google's own [SORT](https://support.google.com/docs/answer/3093150) sample); a
  one-row literal list inside a criterion is the Excel criteria table's `in { }` row.
- **E7 — operator functions are their operators.** `ADD`, `MINUS`, `MULTIPLY`, `DIVIDE`, `POW`,
  `UMINUS`, `UPLUS`, `UNARY_PERCENT`, `EQ`, `NE`, `GT`, `GTE`, `LT`, `LTE` and two-argument `CONCAT`
  are, per their Google pages, equivalent to `+`, `-`, `*`, `/`, `^`, unary `-`, unary `+`, postfix
  `%`, `=`, `<>`, `>`, `>=`, `<`, `<=` and `&`. Each translates as its operator, and the operator
  carries the Excel map's caveats: date arithmetic is `add_days` / `diff_days`
  ([Excel **E9**](ts-excel-function-mapping.md#how-to-read-the-tables)), a zero divisor fails the whole
  query ([Excel **E8**](ts-excel-function-mapping.md#how-to-read-the-tables), gap
  [G15](ts-excel-function-mapping.md#open-questions--gaps)), and `+` never concatenates.
- **E8 — Google services and external data are unmappable.** `IMPORT*`, `GOOGLEFINANCE`,
  `GOOGLETRANSLATE`, `DETECTLANGUAGE`, `AI` and `SPARKLINE` call a Google service, fetch from the web
  or draw in a cell at recalculation time. A ThoughtSpot formula reads only the warehouse, so the
  data has to be loaded there first (and then the function is a table, not a formula), and a
  Snowflake Cortex call is a different engine with different output — the Excel map's `TRANSLATE`
  passthrough is a substitute, not a translation.
- **E9 — `QUERY` is a search.** `QUERY(data, query, [headers])` runs a Visualization API query —
  `select`, `where`, `group by`, `pivot`, `order by`, `limit`, `label`, `format` — over a range.
  That *is* an Answer on a Model: columns, filters, grouping and sort. `QUERY` is `structural`; its
  clauses are mapped one by one in [QUERY clauses](#query-clauses-not-counted--arguments).

---

## Coverage summary

| Section | Rows | `direct` | `passthrough` | `structural` | `unmappable` |
|---|--:|--:|--:|--:|--:|
| [Operators](#operators) | 15 | 15 | 0 | 0 | 0 |
| [Math and statistical](#math-and-statistical) | 8 | 7 | 0 | 0 | 1 |
| [Logical](#logical) | 1 | 1 | 0 | 0 | 0 |
| [Text](#text) | 11 | 3 | 8 | 0 | 0 |
| [Date, parser and type tests](#date-parser-and-type-tests) | 11 | 8 | 2 | 0 | 1 |
| [Arrays and filtering](#arrays-and-filtering) | 7 | 1 | 0 | 4 | 2 |
| [QUERY](#query) | 1 | 0 | 0 | 1 | 0 |
| [Google, web and AI services](#google-web-and-ai-services) | 9 | 0 | 0 | 0 | 9 |
| **Total** | **63** | **35** | **10** | **5** | **13** |

63 rows: **46 functions Excel does not have** (44 from Google's list plus 2 documented elsewhere — `COUNTUNIQUEIFS`, `CONTINUE`) and **17 shared names whose Sheets behaviour changes the translation**. Of the 63, 35 are `direct`, 5 `structural` (`ARRAY_CONSTRAIN`, `FILTER`, `SORT`, `SORTN`, `QUERY`), 10 `passthrough` (`CHAR`, `CODE`, `JOIN`, `REGEXEXTRACT`, `REGEXMATCH`, `REGEXREPLACE`, `SPLIT`, `TEXT`, `EPOCHTODATE`, `ISEMAIL`) and 13 `unmappable` (`MARGINOFERROR`, `ISURL`, `CONTINUE`, `FLATTEN`, `AI`, `GOOGLEFINANCE`, `GOOGLETRANSLATE`, `IMPORTDATA`, `IMPORTFEED`, `IMPORTHTML`, `IMPORTRANGE`, `IMPORTXML`, `SPARKLINE`). The `direct` share is high because the largest Sheets-only group — the 15 operator functions — is the operators themselves ([**E7**](#how-to-read-the-tables)). The `passthrough` rows are regular expressions, `SPLIT`'s fragments, code points, string aggregation, `TEXT` format codes, epoch conversion and an approximate `ISEMAIL`; the `unmappable` rows are mostly Google services ([**E8**](#how-to-read-the-tables)) and spills ([Excel **E6**](ts-excel-function-mapping.md#how-to-read-the-tables)). Every other Sheets function — 451 shared names — takes an Excel map row ([reconciliation](#same-as-the-excel-map-reconciliation)), and 3 Sheets-only engineering functions are counted out of scope. Counts are computed by script from the tables in this file.

---

## Operators

Source: Google's *Operator* category. Each is equivalent to an infix operator
([**E7**](#how-to-read-the-tables)), so the class is the operator's.

| Sheets | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ADD(value1, value2)` | direct | `[a] + [b]` | Equivalent to `+`. With a date operand it is date arithmetic: `add_days ( [d] , [n] )` ([Excel **E9**](ts-excel-function-mapping.md#how-to-read-the-tables)). A blank is 0 in Sheets and NULL propagates through `+`; wrap nullable operands in `ifnull ( [a] , 0 )` ([Excel **E10**](ts-excel-function-mapping.md#how-to-read-the-tables)). |
| `DIVIDE(dividend, divisor)` | direct | `[a] / [b]` | Equivalent to `/`. Sheets returns `#DIV/0!` in one cell; ThoughtSpot's plain `[a] / [b]` returns **NULL** on a zero divisor ([probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)), and `safe_divide ( [a] , [b] )` returns 0 — choose by what the sheet did with the error (`IFERROR(…, 0)` is `safe_divide`). |
| `EQ(value1, value2)` | direct | `[a] = [b]` | Equivalent to `=`. On text both sides ignore case: ThoughtSpot lowercases both sides (live-verified 2026-10-06 — [probe record §4](../reviews/2026-10-06-formula-semantics-probes.md#4-string-comparison-is-case-insensitive-bl-333)), and Sheets `=` is case-insensitive by common observation but **not by any Google statement** ([**E4**](#how-to-read-the-tables), [G6](#open-questions--gaps)). A case-sensitive test is `EXACT`, whose Excel row is a `sql_bool_op` passthrough. |
| `GT(value1, value2)` | direct | `[a] > [b]` | Numbers and dates compare natively. On text, neither side's case behaviour for `>` is documented or probed (BL-333). |
| `GTE(value1, value2)` | direct | `[a] >= [b]` | As `GT`. |
| `ISBETWEEN(value_to_compare, lower_value, upper_value, [lower_value_is_inclusive], [upper_value_is_inclusive])` | direct | `[v] between [lo] and [hi]` | Both bounds are inclusive by default, which is `between` (formula reference, *Conditional Functions*). Exclusive flags spell out the comparison: `FALSE` for the lower bound is `[v] > [lo]`, for the upper `[v] < [hi]`, joined with `and` ([ISBETWEEN](https://support.google.com/docs/answer/10538337)). |
| `LT(value1, value2)` | direct | `[a] < [b]` | As `GT`. |
| `LTE(value1, value2)` | direct | `[a] <= [b]` | As `GT`. |
| `MINUS(value1, value2)` | direct | `[a] - [b]` | Equivalent to `-`. Date minus date is `diff_days ( [a] , [b] )` — **later date first**, which is the order `MINUS` already has; date minus a number is `add_days ( [d] , -1 * [n] )` ([Excel **E9**](ts-excel-function-mapping.md#how-to-read-the-tables)). Blank-as-zero as `ADD`. |
| `MULTIPLY(factor1, factor2)` | direct | `[a] * [b]` | Equivalent to `*`. Blank-as-zero as `ADD`. |
| `NE(value1, value2)` | direct | `[a] != [b]` | Equivalent to `<>`. **NULL trap:** a blank cell is `<>` any value in Sheets, while SQL `NULL != x` is NULL, so a nullable operand needs `( [a] != [b] or isnull ( [a] ) )` — the Excel criteria table's `"<>5"` row. `!=` on text was **not** in the case-insensitivity probe (BL-333). |
| `POW(base, exponent)` | direct | `pow ( [x] , [y] )` | Equivalent to `^`, and Sheets' alias of `POWER`. **`pow`, not `power`** (formula reference). |
| `UMINUS(value)` | direct | `-1 * [x]` | Unary minus, written as a product, as the Excel map's compositions do. |
| `UNARY_PERCENT(percentage)` | direct | `[x] / 100` | The postfix `%` operator: `UNARY_PERCENT(100)` = 1 ([UNARY_PERCENT](https://support.google.com/docs/answer/3093982)). |
| `UPLUS(value)` | direct | `[x]` | Unary plus — the value unchanged. |

---

## Math and statistical

Source: Google's *Math* and *Statistical* categories — the functions Excel lacks, and the rounding
functions whose defaults differ.

| Sheets | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `AVERAGE.WEIGHTED(values, weights, [additional_values, additional_weights, ...])` | direct | `sum ( [T::v] * [T::w] ) / sum ( [T::w] )` | Σ(value × weight) / Σ(weight), with the weight a row-level column — the formula reference's *Weighted average*, Step 0 case (weight already per row). Each scalar `additional_value, additional_weight` pair adds `+ [c] * [cw]` to the numerator and `+ [cw]` to the denominator. Google requires non-negative weights with at least one positive ([AVERAGE.WEIGHTED](https://support.google.com/docs/answer/9084098)); a zero weight total is `#DIV/0!` there and NULL under ThoughtSpot's plain `/` (probe record §7) — no guard is needed; use `safe_divide` if 0 is wanted instead ([Excel **E8**](ts-excel-function-mapping.md#how-to-read-the-tables)). |
| `COUNTUNIQUE(value1, [value2, ...])` | direct | `unique count ( [T::x] )` | One range is a distinct count of the column — **a space, not an underscore** (formula reference). Literal arguments fold to a constant. Several ranges count distinct values **across** them (their union); that has no single-column form and needs the columns stacked upstream ([Excel **G19**](ts-excel-function-mapping.md#open-questions--gaps)). Neither Google nor the formula reference says whether distinctness is case-sensitive (`"a"` vs `"A"`) — *unverified* ([G6](#open-questions--gaps)). |
| `COUNTUNIQUEIFS(count_unique_range, criteria_range1, criterion1, [criteria_range2, criterion2, ...])` | direct | `unique_count_if ( c1 and c2 , [T::x] )` | **Not on the function list as rendered 2026-10-06**, but documented on its own page ([COUNTUNIQUEIFS](https://support.google.com/docs/answer/9584429)), so rowed as an inventory supplement. Criteria pairs are ANDed and each criterion string is a condition per the [Excel criteria table](ts-excel-function-mapping.md#criteria-strings-not-counted--arguments). Google returns 0 when nothing matches, as a filtered distinct count does. |
| `FLOOR(value, [factor])` | direct | `floor ( [x] )` when `factor` is omitted; otherwise as the Excel `FLOOR` row, `floor ( [x] / [f] ) * [f]` | **`factor` is optional in Sheets, default 1** ([FLOOR](https://support.google.com/docs/answer/3093487)); Excel's `FLOOR` requires `significance`. The page is self-contradictory on sign (*"factor must be positive"*, then *"any number of the same sign as value"*); the Excel composition is exact for either reading. |
| `MARGINOFERROR(range, confidence)` | **unmappable** | — | Google defines it as `CONFIDENCE.T(1 - confidence, STDEV(range), COUNT(range))` ([MARGINOFERROR](https://support.google.com/docs/answer/12487850)), and the Excel map's `CONFIDENCE.T` row is unmappable: the t quantile depends on `count − 1` degrees of freedom, so it cannot be folded to a constant. For large samples the `CONFIDENCE.NORM` composition is a normal approximation, not this function. |
| `ROUND(value, [places])` | direct | `round ( [x] , 1 )` when `places` is omitted; otherwise as the Excel `ROUND` row (`round ( [x] , 0.01 )` for 2) | **`places` is optional in Sheets, default 0** ([ROUND](https://support.google.com/docs/answer/3093440)); Excel requires it. The default is the increment **`1`** — never `0`, which returns NULL ([Excel **E12**](ts-excel-function-mapping.md#how-to-read-the-tables)); `round ( [x] )` is also 1 (formula reference). Halves round away from zero ("in terms of magnitude"), as Excel. |
| `ROUNDDOWN(value, [places])` | direct | `if ( [x] >= 0 ) then floor ( [x] ) else ceil ( [x] )` when `places` is omitted; otherwise as the Excel `ROUNDDOWN` row | `places` optional, default 0, as `ROUND` ([ROUNDDOWN](https://support.google.com/docs/answer/3093442)). Toward zero. |
| `ROUNDUP(value, [places])` | direct | `if ( [x] >= 0 ) then ceil ( [x] ) else floor ( [x] )` when `places` is omitted; otherwise as the Excel `ROUNDUP` row | `places` optional, default 0 ([ROUNDUP](https://support.google.com/docs/answer/3093443)). Away from zero, as `ROUND`'s magnitude rule. |

---

## Logical

Source: Google's *Logical* category. `IFERROR` is the one shared name whose default changes the
translation.

| Sheets | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `IFERROR(value, [value_if_error])` | direct | one argument: the expression with its error cause turned into NULL — a division is plain `[a] / [b]`; two arguments: as the Excel `IFERROR` row (`safe_divide` around a division, `ifnull ( expr , [fallback] )` around a conversion) | **`value_if_error` is optional in Sheets, *"blank by default"*** ([IFERROR](https://support.google.com/docs/answer/3093304)). A blank is NULL, so `IFERROR(A2 / B2)` is plain `[a] / [b]`, which returns NULL on a zero divisor ([probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)) — **not** `safe_divide`, which returns 0. (Until 2026-10-06 this row gave `[a] / nullif ( [b] , 0 )`; `nullif` is not a ThoughtSpot function and is rejected at import — BL-339.) For the other error causes the NULL is already there: a lookup miss is NULL on the joined side and a failed `to_double` / `to_date` returns NULL ([Excel **E8**](ts-excel-function-mapping.md#how-to-read-the-tables)), so the one-argument form adds nothing to them. |

---

## Text

Source: Google's *Text* category. Native string functions are only `concat`, `substr` (0-based),
`left`, `right`, `strlen`, `strpos` and `contains`; there is no `trim`, `replace`, `upper` or `lower`
(formula reference, BL-170/BL-171).

| Sheets | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `CHAR(table_number)` | passthrough | `sql_string_op ( "CHR({0})" , [n] )` | **Variant: `sql_string_op`.** **Differs from Excel:** Sheets converts *"according to the current Unicode table"* ([CHAR](https://support.google.com/docs/answer/3094120)), not a platform code page, so Snowflake `CHR` (a Unicode code point) is exact for every code — the Excel row's 128–159 caveat does not apply. This is the Excel `UNICHAR` row. |
| `CODE(string)` | passthrough | `sql_int_op ( "UNICODE({0})" , [s] )` | **Variant: `sql_int_op`.** **Differs from Excel:** Sheets returns *"the numeric Unicode map value of the first character"* ([CODE](https://support.google.com/docs/answer/3094122)), so the template is the Excel `UNICODE` row's, not the Excel `CODE` row's `ASCII` with its code-page caveat. |
| `CONCAT(value1, value2)` | direct | `concat ( [a] , [b] )` | **Differs from Excel:** exactly **two scalar** arguments, *"Equivalent to the `&` operator"* ([CONCAT](https://support.google.com/docs/answer/3093592)). Excel's `CONCAT` takes N arguments and ranges; the Excel row's range fallback (string aggregation) never applies here. Nested `CONCAT`s and `&` chains flatten into one N-argument `concat`. NULL trap as the Excel row: wrap nullable operands in `ifnull ( [a] , '' )`. |
| `CONCATENATE(string1, [string2, ...])` | direct | `concat ( [a] , [b] , ... )` | **Differs from Excel:** Sheets accepts **ranges** — `CONCATENATE(A2:B7)` appends *"across rows rather than down columns"* ([CONCATENATE](https://support.google.com/docs/answer/3094123)); Excel's does not. Classified on cells of one row; a single-column range is string aggregation with an empty delimiter, `sql_string_aggregate_op ( "LISTAGG({0}, '') WITHIN GROUP (ORDER BY {0})" , [T::s] )` (**variant: `sql_string_aggregate_op`**, the Excel `TEXTJOIN` row's shape, with its ordering caveat) ([Excel **E3**](ts-excel-function-mapping.md#how-to-read-the-tables)). A two-dimensional range has no column reading. |
| `JOIN(delimiter, value_or_array1, [value_or_array2, ...])` | passthrough | `sql_string_aggregate_op ( "LISTAGG({0}, {1}) WITHIN GROUP (ORDER BY {0})" , [T::s] , [delim] )` | **Variant: `sql_string_aggregate_op`.** Classified on the range reading — joining a column down its rows is string aggregation, which ThoughtSpot lacks ([Excel **G6**](ts-excel-function-mapping.md#open-questions--gaps)); flag per PT1, and name an order, since a Model has no sheet order. `[delim]` is `JOIN`'s first argument, passed as a string literal (a passthrough cannot take a runtime parameter, so a delimiter held in a cell is baked in). Scalar arguments across one row are native: `concat ( [a] , [delim] , [b] )`. Unlike `TEXTJOIN`, `JOIN` has no `ignore_empty` and Google does not say whether blank cells produce doubled delimiters ([JOIN](https://support.google.com/docs/answer/3094077)); `LISTAGG` skips NULLs, so a sheet that relied on empty slots differs. |
| `REGEXEXTRACT(text, regular_expression)` | passthrough | no group: `sql_string_op ( "REGEXP_SUBSTR({0}, {1})" , [s] , [re] )`; one group: `sql_string_op ( "REGEXP_SUBSTR({0}, {1}, 1, 1, 'e', 1)" , [s] , [re] )` | **Variant: `sql_string_op`.** **Differs from Excel:** two arguments only, and **capture groups decide the result** — *"If there are no capture groups, the function returns the whole match"*, otherwise each group is returned, one per column ([REGEXEXTRACT](https://support.google.com/docs/answer/3098244)). Excel's default `return_mode` 0 returns the whole match even when the pattern has groups. So a one-group pattern extracts the **group** (Snowflake's `'e'` parameter with group 1), and an *n*-group pattern spills *n* columns: one formula per group *k*, `…, 1, 1, 'e', k)`. No match is `#N/A` in Sheets and NULL here ([Excel **E8**](ts-excel-function-mapping.md#how-to-read-the-tables)). RE2 dialect ([**E5**](#how-to-read-the-tables)). |
| `REGEXMATCH(text, regular_expression)` | passthrough | `sql_bool_op ( "REGEXP_INSTR({0}, {1}) > 0" , [s] , [re] )` | **Variant: `sql_bool_op`.** **Not `REGEXP_LIKE`**, which anchors the pattern to the whole string. `REGEXMATCH` tests for a match anywhere: Google's own sample `REGEXMATCH("Spreadsheets", "S.r")` matches only the substring `Spr` ([REGEXMATCH](https://support.google.com/docs/answer/3098292)). The page does not state the anchoring outright, so the search reading rests on that sample and RE2's unanchored default (*unverified*). Same reasoning as the Excel `REGEXTEST` row. Case-sensitive on both sides; `(?i)` becomes `REGEXP_INSTR({0}, {1}, 1, 1, 0, 'i')` ([**E5**](#how-to-read-the-tables)). |
| `REGEXREPLACE(text, regular_expression, replacement)` | passthrough | `sql_string_op ( "REGEXP_REPLACE({0}, {1}, {2})" , [s] , [re] , [repl] )` | **Variant: `sql_string_op`.** **Differs from Excel:** three arguments, *"All matching instances in text will be replaced"* ([REGEXREPLACE](https://support.google.com/docs/answer/3098245)) — there is no `occurrence` or `case_sensitivity` argument, and Snowflake's default (occurrence 0) is already "all". Back-references in `replacement` are `$1` in RE2 and `\\1` in Snowflake ([**E5**](#how-to-read-the-tables)). |
| `SEARCH(search_for, text_to_search, [starting_at])` | direct | `strpos ( [within] , [find] )` | **Differs from Excel:** Google documents `SEARCH` as case-insensitive and gives it **no wildcard syntax** ([SEARCH](https://support.google.com/docs/answer/3094154)); Excel's `SEARCH` treats `?`, `*` and `~` as wildcards. So the Excel row's `REGEXP_INSTR` wildcard fallback does not apply: `search_for` is literal, and native `strpos` — case-insensitive, live-verified 2026-10-06 ([probe record §4](../reviews/2026-10-06-formula-semantics-probes.md#4-string-comparison-is-case-insensitive-bl-333)) — is the whole mapping (**operand order reversed**, haystack first). The probe used a **literal** needle, which ThoughtSpot lowercases at compile time; a **column** needle (`strpos ( [T::within] , [T::find] )`) was not probed, so whether both sides are lowercased then is *unverified* ([G7](#open-questions--gaps)). Whether Sheets really treats `*` literally is undocumented (*unverified*). `starting_at > 1` is `sql_int_op ( "POSITION(LOWER({0}), LOWER({1}), {2})" , [find] , [within] , [start] )` (**variant: `sql_int_op`**; Snowflake's three-argument `POSITION` — there is no `POSITION(… IN … FROM n)`). Not-found is `#VALUE!` in Sheets and 0 here ([Excel **E8**](ts-excel-function-mapping.md#how-to-read-the-tables)). `SEARCHB` follows this row ([**E1**](#how-to-read-the-tables)). |
| `SPLIT(text, delimiter, [split_by_each], [remove_empty_text])` | passthrough | fragment *k*: `sql_string_op ( "REGEXP_SUBSTR({0}, '[^,;]+', 1, {1})" , [s] , k )` under the defaults | **Variant: `sql_string_op`.** Classified on its dominant use, as `JOIN` and `ARRAY_CONSTRAIN` are: splitting a delimited cell into a fixed set of columns (`"Last, First"` into two). A spill into *n* columns is *n* formulas, fragment *k* each — the same one-formula-per-output-column treatment as a multi-group `REGEXEXTRACT`; `INDEX(SPLIT(s, d), 1, k)` is fragment *k* directly. Only an unbounded spill (a variable number of fragments laid out across cells) is unmappable ([Excel **E6**](ts-excel-function-mapping.md#how-to-read-the-tables)). The template must honour two **defaults that are TRUE** ([SPLIT](https://support.google.com/docs/answer/3094136)): `split_by_each` (*"each character in delimiter is considered individually"*) and `remove_empty_text` (*"treat consecutive delimiters as one"*). Under both defaults fragment *k* is the template shown, with the delimiter's characters inside the negated class (here `,` and `;`; escape `]`, `^`, `-` and `\` there). Only `split_by_each = FALSE, remove_empty_text = FALSE` is `SPLIT_PART({0}, {1}, {2})`; `SPLIT_PART` keeps empty fragments, so mapping the default `SPLIT` to it returns the wrong fragment whenever two delimiters touch. **Type:** Sheets turns a numeric-looking fragment into a number (`SPLIT("1,2,3", ",")` gives three numbers — observed behaviour, not stated on Google's page, [G6](#open-questions--gaps)); the template returns text, so wrap a numeric fragment in `to_double ( … )` where the sheet used it as a number. |
| `TEXT(number, format)` | passthrough | as the Excel `TEXT` row, with the format codes in [`TEXT` format codes](#text-format-codes-not-counted--arguments) below | **Variant: `sql_string_op`.** **Differs from Excel in its format codes** ([TEXT](https://support.google.com/docs/answer/3094139)): Sheets documents `HH` as a 24-hour code (Excel has no case distinction), adds `mmmmm` and `ss.000`, and rejects `*`, `?` and fraction patterns. Whether `hh` without `AM/PM` is 12-hour in Sheets is *unverified* ([G6](#open-questions--gaps)). Only the differing codes are listed below; every other code takes the Excel map's [format-code table](ts-excel-function-mapping.md#text-format-codes-not-counted--arguments). |

### `TEXT` format codes *(not counted — arguments)*

The Sheets codes whose translation differs from the Excel map's table. Source: Google's
[TEXT](https://support.google.com/docs/answer/3094139) page.

| Sheets `format` | ThoughtSpot | Class |
|---|---|---|
| `"HH"` | `right ( concat ( '0' , to_string ( hour_of_day ( [t] ) ) ) , 2 )`; inside a multi-token pattern, `HH24` in the `TO_CHAR` template | direct — Sheets `HH` is *"the hour on a 24-hour clock"*. |
| `"hh"` with `AM/PM` | `sql_string_op ( "TO_CHAR({0}, 'HH12 AM')" , [t] )` | passthrough — Google documents `hh` as *"the hour on a 12-hour clock"*, which agrees with Excel when `AM/PM` is present. **Without `AM/PM`** Google says nothing more, and Excel reads `hh` as 24-hour; this map keeps the [Excel table](ts-excel-function-mapping.md#text-format-codes-not-counted--arguments)'s reading there (`HH24`) and records the possible difference as *unverified* ([G6](#open-questions--gaps)). |
| `"mmmmm"` | `left ( month ( [d] ) , 1 )` | direct — first letter of the month name. |
| `"ss.000"` | `sql_string_op ( "TO_CHAR({0}, 'SS.FF3')" , [t] )` | passthrough — seconds with milliseconds. *Unverified* inside a template. |
| `"?"`, fraction patterns, `*` | — | not applicable — Sheets `TEXT` does not support them, so a working sheet never contains them. |
| a date/time code mixed with `#` or `0` | — | not applicable — *"the date/time patterns and # or 0 cannot be mixed"* in Sheets. |

---

## Date, parser and type tests

Source: Google's *Date*, *Parser*, *Info* and *Web* categories — the conversions and tests Excel lacks.
The serial-number rule is [**E3**](#how-to-read-the-tables).

| Sheets | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `EPOCHTODATE(timestamp, [unit])` | passthrough | `sql_date_time_op ( "TO_TIMESTAMP_NTZ({0}, 0)" , [x] )` | **Variant: `sql_date_time_op`.** Unix epoch to a **UTC** datetime ([EPOCHTODATE](https://support.google.com/docs/answer/13193461)); `unit` 1 (default, seconds) is scale 0, 2 (milliseconds) scale 3, 3 (microseconds) scale 6 — the second argument of Snowflake `TO_TIMESTAMP_NTZ`. A native `add_seconds ( to_date ( '1970-01-01' , 'yyyy-MM-dd' ) , [x] )` would avoid the passthrough, but `add_seconds` is documented for a DATETIME and is *unverified* on a DATE (the Excel map's `TIME` row). Sheets rejects negative timestamps; the template accepts them. |
| `ISDATE(value)` | direct | DATE / DATETIME column: `true`; text column: `not ( isnull ( to_date ( [s] , 'yyyy-MM-dd' ) ) )` | A type test on a typed column ([Excel **E15**](ts-excel-function-mapping.md#how-to-read-the-tables)). On text it is a parse test, which `to_date`'s NULL-on-failure makes native — for **one stated format**; Sheets accepts any format it recognises (`"July 20 1969"` and `"1969-20-07"` are both TRUE on [ISDATE](https://support.google.com/docs/answer/9061381)), so a mixed-format column needs one `to_date` per format, `or`-ed. |
| `ISEMAIL(value)` | passthrough | `sql_bool_op ( "REGEXP_LIKE({0}, '[^@ ]+@[^@ ]+[.][^@ ]+')" , [s] )` | **Variant: `sql_bool_op`.** An **approximation**: Google checks *"a commonly accepted format for email addresses"* without publishing the rule ([ISEMAIL](https://support.google.com/docs/answer/3256503)), so no template can match it exactly. `REGEXP_LIKE` is right here because the test is whole-string. Flag the row for review. |
| `ISURL(value)` | **unmappable** | — | Google's rule depends on its own list of protocols and top-level domains, and on the sheet's auto-linking (*"it may use a top-level domain that isn't on our list"* — [ISURL](https://support.google.com/docs/answer/3256501)). A passthrough regex test — an optional `http`, `https` or `ftp` scheme, a host containing a dot, a two-or-more-letter final label, an optional path — is a different test, not a translation, and is not given as a mapping. |
| `NETWORKDAYS(start_date, end_date, [holidays])` | direct | as the Excel `NETWORKDAYS` row (prefer its per-weekday counting form); an inline holiday `h` is `to_date ( '2026-12-25' , 'yyyy-MM-dd' )` folded from `DATE(2026, 12, 25)`, or `add_days ( to_date ( '1899-12-30' , 'yyyy-MM-dd' ) , 46381 )` from the serial 46381 | **Differs from Excel in the holiday array only.** Google: *"The values provided within an array for holidays must be date serial number values, as returned by N or date values, as returned by DATE, DATEVALUE or TO_DATE"* ([NETWORKDAYS](https://support.google.com/docs/answer/3092979)). So an array never holds text dates, and the Excel row's advice to match the sheet's text-date locale does not carry over. Convert each element by its form: a serial per [**E3**](#how-to-read-the-tables), a `DATE(y, m, d)` folded to one `to_date` literal, a `DATEVALUE("…")` or `TO_DATE(…)` per their rows. Then apply the Excel row's holiday term — subtract 1 for each `h` in range and on a working day — and dedupe the array at conversion. A range of holidays is a calendar table, as in Excel. **Verification:** the holiday term with weekend code 1 is live-verified ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)) with `to_date` literals; the serial-converted form of `h` was not probed. |
| `NETWORKDAYS.INTL(start_date, end_date, [weekend], [holidays])` | direct | as the Excel `NETWORKDAYS.INTL` row; holidays converted as `NETWORKDAYS` | Same weekend codes and string form as Excel ([NETWORKDAYS.INTL](https://support.google.com/docs/answer/3295902)). **Differs in the holiday array only**, with the same Google rule as `NETWORKDAYS` (serials or date values, never text), converted the same way. The holiday term tests that `h` is **not** in the code's weekend set K (`day_number_of_week ( [h] ) != k` for each `k` in K), not `<= 5`, and the array is deduped at conversion — both as the Excel row. Live-verified for code 1 only ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)). |
| `TO_DATE(value)` | direct | serial column: `add_days ( to_date ( '1899-12-30' , 'yyyy-MM-dd' ) , floor ( [x] ) )`; date column: `[d]` | A number is *"days since December 30, 1899"* and anything else is *"returned without modification"* ([TO_DATE](https://support.google.com/docs/answer/3094239)), so a date or text column is the identity. Exact for every serial ([**E3**](#how-to-read-the-tables)). The fraction (time of day) needs a DATETIME: `sql_date_time_op ( "DATEADD(second, ROUND({0} * 86400), CAST('1899-12-30' AS TIMESTAMP_NTZ))" , [x] )` (**variant: `sql_date_time_op`**) ([Excel **E3**](ts-excel-function-mapping.md#how-to-read-the-tables)). |
| `TO_DOLLARS(value)` | direct | `[x]` | Applies the currency **cell format**; the value is unchanged and stays a number (*"equivalent to applying Format -> Number -> Currency"* — [TO_DOLLARS](https://support.google.com/docs/answer/3094241)). The ThoughtSpot home is the column's currency display format, not a formula. Contrast `DOLLAR`, which returns text (Excel row). No currency conversion is involved. |
| `TO_PERCENT(value)` | direct | `[x]` | Applies the percent format with *"1 = 100%"* ([TO_PERCENT](https://support.google.com/docs/answer/3094284)). The value is **not** multiplied by 100; the ThoughtSpot home is the column's percentage display format. |
| `TO_PURE_NUMBER(value)` | direct | numeric: `[x]`; date: `diff_days ( [d] , to_date ( '1899-12-30' , 'yyyy-MM-dd' ) )` | Removes formatting and returns non-numeric values unchanged ([TO_PURE_NUMBER](https://support.google.com/docs/answer/3094243)). A date becomes its serial ([**E3**](#how-to-read-the-tables)); a datetime's fraction needs `diff_time` against midnight / 86400 added on. |
| `TO_TEXT(value)` | direct | `to_string ( [x] )` | Covers an unformatted number ([Excel **E3**](ts-excel-function-mapping.md#how-to-read-the-tables)). Sheets keeps the **displayed** format — *"Currencies appear as currencies, … dates as dates"* ([TO_TEXT](https://support.google.com/docs/answer/3094285)) — which `to_string` does not reproduce; for a formatted source, translate as `TEXT(value, <that format>)`. |

---

## Arrays and filtering

Source: Google's *Array*, *Filter* and *Google* categories. Excel's dynamic-array functions that Sheets
shares (`UNIQUE`, `CHOOSECOLS`, `TOCOL`, `VSTACK`, `BYROW`, `MAP`, `LAMBDA`…) take their Excel rows;
`UNIQUE`'s Sheets page has Excel's three arguments and no translation-changing difference.

| Sheets | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `ARRAY_CONSTRAIN(input_range, num_rows, num_cols)` | structural | the Answer's top-N, and its chosen columns | Classified on its dominant use, Google's own sample `ARRAY_CONSTRAIN(SORT(A1:F100, 1, TRUE), 10, 6)` ([ARRAY_CONSTRAIN](https://support.google.com/docs/answer/3267036)) — the first 10 rows of a sorted range, which is a top-N search, as the Excel map's `TAKE` row. Over an unsorted range it is "the first N rows on the sheet" and unmappable ([Excel **E6**](ts-excel-function-mapping.md#how-to-read-the-tables)). |
| `ARRAYFORMULA(array_formula)` | direct | the inner formula, translated as a row-level formula when it is element-wise | **A no-op only for element-wise inner expressions** ([**E6**](#how-to-read-the-tables)): a ThoughtSpot Model formula is already evaluated per row, which is what `ARRAYFORMULA` makes a sheet formula do. `ARRAYFORMULA(A2:A * B2:B)` is `[T::a] * [T::b]`. An aggregate wrapped around it collapses as usual: Google's sample `ARRAYFORMULA(SUM(IF(A1:A10 > 5, A1:A10, 0)))` ([ARRAYFORMULA](https://support.google.com/docs/answer/3093275)) is `sum_if ( [T::a] > 5 , [T::a] )`. **Not a no-op:** a per-row `COUNTIF`/`SUMIF` over the whole range becomes `group_aggregate ( … , { [T::key] } , query_filters ( ) )`; `AND`/`OR` collapse the range to one value; `ROW()` is positional (all in [**E6**](#how-to-read-the-tables)). Drop the header-stack and blank-guard idioms. |
| `CONTINUE(source_cell, row, column)` | **unmappable** | — | Historically documented as returning one cell of an expanded array result. **Not on the function list as rendered 2026-10-06 and no current Google help page was found**, so it is rowed as an inventory supplement and its signature is not verified. Either way it addresses a spill by position ([Excel **E6**](ts-excel-function-mapping.md#how-to-read-the-tables)). |
| `FILTER(range, condition1, [condition2, ...])` | structural | a Model or Answer filter of `c1 and c2 …`; inside an aggregate, the `*_if` form | **Differs from Excel:** Sheets takes **any number of conditions, ANDed**, and **no `if_empty`** — no match is `#N/A` ([FILTER](https://support.google.com/docs/answer/3093197)). Excel's `FILTER(array, include, [if_empty])` takes one `include` array. So each condition becomes one `and` term; OR is written in Sheets by adding conditions, `(A2:A = "x") + (A2:A = "y")`, which is `or` ([Excel **E10**](ts-excel-function-mapping.md#how-to-read-the-tables)). `SUM(FILTER(B:B, A:A = "x"))` is `sum_if ( [T::a] = 'x' , [T::b] )`, as the Excel row. |
| `FLATTEN(range1, [range2, ...])` | **unmappable** | — | Reshapes ranges into one column in row-major order, keeping empty values ([FLATTEN](https://support.google.com/docs/answer/10307761)) — the Excel `TOCOL` row. A single-column argument is the identity. Stacking different ranges is a union ([Excel **G19**](ts-excel-function-mapping.md#open-questions--gaps)). |
| `SORT(range, sort_column, is_ascending, [sort_column2, is_ascending2, ...])` | structural | the Answer's sort | **Differs from Excel:** Sheets takes **(column, `TRUE`/`FALSE`) pairs** in precedence order, both required, and `sort_column` may be a range **outside** `range` ([SORT](https://support.google.com/docs/answer/3093150)); Excel's `SORT(array, [sort_index], [sort_order], [by_col])` takes one index and `1`/`-1`. Each pair is one sort column of the Answer, `TRUE` ascending. An outside range is still a Model column; whether an Answer can sort by a column it does not display is outside this map's sources. |
| `SORTN(range, [n], [display_ties_mode], [sort_column1, is_ascending1], ...)` | structural | the Answer's top-N | First `n` rows after a sort ([SORTN](https://support.google.com/docs/answer/7354624)) — a top-N search. `display_ties_mode` 0 (default) and 2 (drop duplicate rows) are a top-N on a search that is already distinct per grouping; 1 (keep ties with the *n*th row) is a filter on `rank ( sum ( [T::m] ) , 'desc' ) <= n` — `rank` is global and takes an aggregate (formula reference, *Rank Functions*); 3 (*n* unique rows plus every duplicate) has no clean form. Default sort is the lowest-index column. |

---

## QUERY

Source: Google's *Google* category, [QUERY](https://support.google.com/docs/answer/3093343).

| Sheets | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `QUERY(data, query, [headers])` | structural | an Answer on the Model that holds `data`: the `select` list as its columns, `where` as filters, `group by` as its attributes, `order by` as its sort | **A search, not a formula** ([**E9**](#how-to-read-the-tables)). `data` is a range, so it becomes the Model table (or tables) it was read from; `headers` (the number of header rows) disappears, because a Model column has a name. Each clause maps per the table below. Three traps: QUERY's string matching is **case-sensitive** where ThoughtSpot's is not ([**E4**](#how-to-read-the-tables)); `month()` is **zero-based**; and `/` returns null on a zero divisor, as ThoughtSpot's plain `/` does. A `query` built by concatenating cell values (`"where B = '"&E1&"'"`) is a runtime parameter in the filter. A QUERY whose result feeds another formula (`SUM(QUERY(…))`) usually collapses to an aggregate, as `SUM(FILTER(…))` does in the Excel map. |

### QUERY clauses *(not counted — arguments)*

Source: the [Query Language reference](https://developers.google.com/chart/interactive/docs/querylanguage).
`[T::x]` is the Model column the QUERY's column letter (`A`, `Col1`) refers to.

| QUERY element | ThoughtSpot | Class | Notes |
|---|---|---|---|
| `select A, B` / `select *` | the Answer's columns | structural | `*` is every column of `data`. Column letters and `Col`*n* are positions in the range; map each to the Model column under that header. |
| `select sum(C)` — `sum`, `avg`, `count`, `max`, `min` | `sum ( [T::c] )`, `average ( … )`, `count ( … )`, `max ( … )`, `min ( … )` | direct | `count` *"Null cells are not counted"*, as ThoughtSpot `count`. `max`/`min` on strings compare *"alphabetically, with case-sensitivity"* in QUERY; ThoughtSpot's string ordering is not documented here. Aggregates take only a column identifier in QUERY. |
| `where` on numbers and dates (`>`, `>=`, `=`, `!=`, `<>`, `and`, `or`, `not`) | a filter, or the condition inside a `*_if` | direct | `<>` and `!=` are both `!=`. |
| `where` text `=` / `!=` | `sql_bool_op ( "{0} = {1}" , [T::x] , 'West' )` | passthrough | **Variant: `sql_bool_op`.** QUERY string literals are case-sensitive (*"Identifiers and string literals are case-sensitive"*); ThoughtSpot's `=` lowercases both sides, so the native `[T::x] = 'West'` would also match `west`. Use the native form only when the column's case is known to be consistent. Same shape as the Excel `EXACT` row. |
| `contains` | `sql_bool_op ( "CONTAINS({0}, {1})" , [T::x] , 'John' )` | passthrough | **Variant: `sql_bool_op`.** Case-sensitive in QUERY (*"matches 'John' … but not 'john adams'"*); the formula reference gives exactly this template for case-sensitive containment. Native `contains` is case-insensitive. |
| `starts with` / `ends with` | `sql_bool_op ( "STARTSWITH({0}, {1})" , [T::x] , 'eng' )` / `sql_bool_op ( "ENDSWITH({0}, {1})" , [T::x] , 'y' )` | passthrough | **Variant: `sql_bool_op`.** Case-sensitive, as `contains`. The native `strpos ( [T::x] , 'eng' ) = 1` and the `substr` suffix composition (Excel criteria table) are case-insensitive. |
| `matches` | `sql_bool_op ( "REGEXP_LIKE({0}, {1})" , [T::x] , '.*ia' )` | passthrough | **Variant: `sql_bool_op`.** A **whole-string** match — *"this is not a global search, so where country matches 'an' will not match 'Canada'"* — which is exactly `REGEXP_LIKE`'s implicit anchoring (the opposite of `REGEXMATCH`). Google calls the dialect "preg"; translate it per [**E5**](#how-to-read-the-tables). |
| `like` with `%` and `_` | `sql_bool_op ( "{0} LIKE {1}" , [T::x] , 'fre%' )` | passthrough | **Variant: `sql_bool_op`.** Same wildcards as SQL `LIKE`; case-sensitive on both sides. A `'x%'` pattern alone is the `starts with` row. |
| `is null` / `is not null` | `isnull ( [T::x] )` / `not ( isnull ( [T::x] ) )` | direct | QUERY treats a column's minority-type values as null (QUERY page); the warehouse column has one type, so that case does not arise. |
| `group by C` | the Answer's attributes | structural | QUERY sorts by the grouping columns unless `order by` says otherwise; set the Answer's sort to match if the order mattered. |
| `pivot D` | a pivot-table visualisation with `D` on the column axis | structural | Pivot implies aggregation; `pivot` without `group by` is one row. |
| `order by C desc` | the Answer's sort | structural | Can sort by an aggregate (`order by max(C)`). |
| `limit n` | the Answer's top-N | structural | With `order by`, a top-N; without it, the first N rows of the sheet — unmappable ([Excel **E6**](ts-excel-function-mapping.md#how-to-read-the-tables)). |
| `offset n` | — | unmappable | Skipping the first N rows is positional; an Answer has no row offset. |
| `label C 'Name'` | the column's display name in the Answer (or the formula's `name`) | structural | Labels are display only — QUERY itself cannot refer to a label. |
| `format C '#,##0.00'` | the column's display format | structural | ICU patterns; display only, as the Excel map's `TEXT` caveats. |
| `options no_format` / `no_values` | — | not applicable | Controls the response payload; nothing to translate. |
| `+`, `-`, `*` | `+`, `-`, `*` | direct | On numbers only in QUERY. |
| `/` | `[a] / [b]` | direct | **Division by zero returns null in QUERY** (*"Division by zero returns null"*), and so does ThoughtSpot's plain `/` ([probe record §7](../reviews/2026-10-06-formula-semantics-probes.md#7-division-null-and-concat-safe_divide-nullif-concat)); `safe_divide` returns 0, not null — so the plain operator is the exact form. |
| `year(d)`, `day(d)`, `quarter(d)` | `year ( [d] )`, `day ( [d] )`, `quarter_number ( [d] )` | direct | Quarters are 1-based in both. |
| `month(d)` | `month_number ( [d] ) - 1` | direct | **Zero-based in QUERY**: *"the function returns 0 for January"*. `month_number` is 1-based; `month ( )` returns the name. |
| `dayOfWeek(d)` | `mod ( day_number_of_week ( [d] ) , 7 ) + 1` | direct | QUERY numbers *"1 for Sunday, 2 for Monday"*; `day_number_of_week` is fixed 1 = Monday … 7 = Sunday (live-verified 2026-10-06 — [probe record §2](../reviews/2026-10-06-formula-semantics-probes.md#2-weekday-week-and-calendar-bl-334)), so the Excel `WEEKDAY` type-1 shift applies. **Assumes a Monday week start** — the Model calendar's default — and diverges if the Model's calendar starts the week elsewhere. |
| `hour(d)` | `hour_of_day ( [d] )` | direct | |
| `minute(d)`, `second(d)`, `millisecond(d)` | `sql_int_op ( "MINUTE({0})" , [d] )`, `…SECOND…`, `sql_int_op ( "DATE_PART(millisecond, {0})" , [d] )` | passthrough | **Variant: `sql_int_op`.** No native minute or second extractor (the Excel `MINUTE` row). *Unverified:* the `millisecond` date part in a template. |
| `dateDiff(a, b)` | `diff_days ( [a] , [b] )` | direct | Days from `b` to `a` — the first argument is the later date, the same order as `diff_days` (*"dateDiff(date "2008-03-13", date "2008-02-12") returns 29"*). QUERY uses *"Only the date parts"*; on a DATETIME, wrap each side in `date ( )`. |
| `toDate(dt)` | `date ( [dt] )` | direct | The date part of a datetime. `toDate(number)` reads the number as **milliseconds** since 1970-01-01 GMT: `sql_date_op ( "TO_DATE(TO_TIMESTAMP_NTZ({0}, 3))" , [x] )` (**variant: `sql_date_op`**, passthrough). |
| `now()` | `now ( )` | direct | QUERY returns GMT; ThoughtSpot's `now ( )` is evaluated in the warehouse's time zone unless `ts_user_timezone` applies (Excel `NOW` row). |
| `upper(s)`, `lower(s)` | `sql_string_op ( "UPPER({0})" , [s] )`, `sql_string_op ( "LOWER({0})" , [s] )` | passthrough | **Variant: `sql_string_op`.** No native `upper`/`lower`. Inside a `where` they usually exist to make a comparison case-insensitive, which native `=` / `contains` already are — so `where lower(B) contains 'x'` is simply `contains ( [T::b] , 'x' )`. |
| Literals `date "2008-03-18"`, `datetime "…"`, `true` | `to_date ( '2008-03-18' , 'yyyy-MM-dd' )`; `true` | direct | Never a bare `'2008-03-18'`, which parses as subtraction (formula reference). |

---

## Google, web and AI services

Source: Google's *Google*, *Web* and *AI* categories. All are unmappable for the one reason in
[**E8**](#how-to-read-the-tables): they reach outside the spreadsheet at recalculation time.

| Sheets | Class | ThoughtSpot | Notes |
|---|---|---|---|
| `AI(prompt, [range])` | **unmappable** | — | Gemini generation, summary or classification in a cell (also `GEMINI()`; [AI](https://support.google.com/docs/answer/15877199)). Output is model-specific and non-deterministic. A Snowflake Cortex call in a passthrough (the Excel `TRANSLATE` row's shape) is a substitute with a different model, per-row cost and no equivalence. |
| `GOOGLEFINANCE(ticker, [attribute], [start_date], [end_date_or_num_days], [interval])` | **unmappable** | — | The fourth argument is `end_date` or `num_days` (Google writes it with a vertical bar). Market data fetched from Google Finance — the Excel `STOCKHISTORY` row. Load the series into the warehouse and model it as a table. |
| `GOOGLETRANSLATE(text, [source_language, target_language])` | **unmappable** | — | Google Translate in a cell ([GOOGLETRANSLATE](https://support.google.com/docs/answer/3093331)). The Excel map's `TRANSLATE` row passes the same job to `SNOWFLAKE.CORTEX.TRANSLATE`; for Sheets that is a different engine whose output will differ, so it is a substitute, not a mapping. If used, note that `source_language` defaults to `"auto"` in Sheets and Cortex needs a stated or empty source. |
| `IMPORTDATA(url)` | **unmappable** | — | Fetches a CSV/TSV from a URL. Load the file as a warehouse table (for example with `ts-load-source-data`) and model that. |
| `IMPORTFEED(url, [query], [headers], [num_items])` | **unmappable** | — | RSS/Atom feed. Ingest upstream. |
| `IMPORTHTML(url, query, index)` | **unmappable** | — | A table or list scraped from a web page. Ingest upstream. |
| `IMPORTRANGE(spreadsheet_url, range_string)` | **unmappable** | — | Reads another spreadsheet. The other sheet is a data source: load it as a table and **join** it, which is what the import was standing in for ([Excel **E13**](ts-excel-function-mapping.md#how-to-read-the-tables)). |
| `IMPORTXML(url, xpath_query)` | **unmappable** | — | XPath over a fetched page — as the Excel map's out-of-scope `WEBSERVICE` / `FILTERXML`. Ingest upstream. |
| `SPARKLINE(data, [options])` | **unmappable** | — | An in-cell chart. There is no formula form; the ThoughtSpot equivalent is a chart in an Answer or Liveboard, built from the same columns. |

---

## Same as the Excel map (reconciliation)

Script-computed from Google's function list as rendered on 2026-10-06 (516 table rows; `UNIQUE` is
listed twice, under *Filter* and *Operator*, giving **515 distinct names**) against the Excel map's
inventory (Microsoft's category page as rendered the same day — the Excel map's 415 rowed functions
plus its 109 counted out-of-scope ones, 520 distinct names). **468 names are shared**;
17 of them are rowed above because Google documents a translation-changing difference
(`CHAR`, `CODE`, `CONCAT`, `CONCATENATE`, `FILTER`, `FLOOR`, `IFERROR`, `NETWORKDAYS`, `NETWORKDAYS.INTL`, `REGEXEXTRACT`, `REGEXREPLACE`, `ROUND`, `ROUNDDOWN`, `ROUNDUP`, `SEARCH`, `SORT`, `TEXT`), so **451 shared names take an Excel map row unchanged** ([**E1**](#how-to-read-the-tables)):
- **362** are rowed in the Excel map and take that row;
- **38** are Excel *compatibility aliases* (marked ‡) and take their **successor's** row, as the Excel map's
  [compatibility list](ts-excel-function-mapping.md#out-of-scope-counted-not-rowed) says (`STDEV` → `STDEV.S`, `PERCENTILE` → `PERCENTILE.INC`, …);
- **51** fall in the Excel map's out-of-scope categories (50 Engineering, 1 Web; marked †)
  and stay out of scope here too.

**Checked and found the same** — shared names whose Google page was read for a difference and
which therefore take the Excel row: `UNIQUE` (same three arguments), `WEEKDAY` (types 1, 2, 3, 11–17,
as Excel), `WEEKNUM` (types 1, 2, 11–17, 21, as Excel), `DATE` (overflow, truncation and the 0–1899
year rule as Excel), `DATEDIF` (same units),
`DATEVALUE`, `TRIM` (inner spaces collapsed; non-breaking space kept, as Excel), `CLEAN`, `CEILING`
(`factor` optional, default 1 — the Excel row already gives the one-argument form; contrast `FLOOR`,
whose Excel row requires `significance` and so is rowed here), `WORKDAY` / `WORKDAY.INTL` (holidays
are a calendar table or UDF on both), `LOG` (base 10
default), `SUBSTITUTE`, `TEXTJOIN`, `MATCH`, `XLOOKUP`, `COUNTIF` (*"not case sensitive"*, as Excel
criteria), `EXACT` and `FIND` (case-sensitive), `N` (serial base per [**E3**](#how-to-read-the-tables);
the Excel row's formula is unchanged and now exact for every date), `IMAGE` (different arguments,
unmappable on both) and `DETECTLANGUAGE` (unmappable on both). `MOD`'s Google page does not state
the sign of the result; the Excel row's floor identity is used, *unverified* for Sheets.

<details>
<summary>The 451 names (rowed in the Excel map unless marked: ‡ compatibility alias, takes its successor's row; † Excel out of scope)</summary>

`ABS` · `ACCRINT` · `ACCRINTM` · `ACOS` · `ACOSH` · `ACOT` · `ACOTH` · `ADDRESS` · `AMORLINC` · `AND` · `ARABIC` · `ASC` · `ASIN` · `ASINH` · `ATAN` · `ATAN2` · `ATANH` · `AVEDEV` · `AVERAGE` · `AVERAGEA` · `AVERAGEIF` · `AVERAGEIFS` · `BASE` · `BETA.DIST` · `BETA.INV` · `BETADIST`‡ · `BETAINV`‡ · `BIN2DEC`† · `BIN2HEX`† · `BIN2OCT`† · `BINOM.DIST` · `BINOM.INV` · `BINOMDIST`‡ · `BITAND`† · `BITLSHIFT`† · `BITOR`† · `BITRSHIFT`† · `BITXOR`† · `BYCOL` · `BYROW` · `CEILING` · `CEILING.MATH` · `CEILING.PRECISE` · `CELL` · `CHIDIST`‡ · `CHIINV`‡ · `CHISQ.DIST` · `CHISQ.DIST.RT` · `CHISQ.INV` · `CHISQ.INV.RT` · `CHISQ.TEST` · `CHITEST`‡ · `CHOOSE` · `CHOOSECOLS` · `CHOOSEROWS` · `CLEAN` · `COLUMN` · `COLUMNS` · `COMBIN` · `COMBINA` · `COMPLEX`† · `CONFIDENCE`‡ · `CONFIDENCE.NORM` · `CONFIDENCE.T` · `CONVERT`† · `CORREL` · `COS` · `COSH` · `COT` · `COTH` · `COUNT` · `COUNTA` · `COUNTBLANK` · `COUNTIF` · `COUNTIFS` · `COUPDAYBS` · `COUPDAYS` · `COUPDAYSNC` · `COUPNCD` · `COUPNUM` · `COUPPCD` · `COVAR`‡ · `COVARIANCE.P` · `COVARIANCE.S` · `CRITBINOM`‡ · `CSC` · `CSCH` · `CUMIPMT` · `CUMPRINC` · `DATE` · `DATEDIF` · `DATEVALUE` · `DAVERAGE` · `DAY` · `DAYS` · `DAYS360` · `DB` · `DCOUNT` · `DCOUNTA` · `DDB` · `DEC2BIN`† · `DEC2HEX`† · `DEC2OCT`† · `DECIMAL` · `DEGREES` · `DELTA`† · `DETECTLANGUAGE` · `DEVSQ` · `DGET` · `DISC` · `DMAX` · `DMIN` · `DOLLAR` · `DOLLARDE` · `DOLLARFR` · `DPRODUCT` · `DSTDEV` · `DSTDEVP` · `DSUM` · `DURATION` · `DVAR` · `DVARP` · `EDATE` · `EFFECT` · `ENCODEURL`† · `EOMONTH` · `ERF`† · `ERF.PRECISE`† · `ERFC`† · `ERFC.PRECISE`† · `ERROR.TYPE` · `EVEN` · `EXACT` · `EXP` · `EXPON.DIST` · `EXPONDIST`‡ · `F.DIST` · `F.DIST.RT` · `F.INV` · `F.INV.RT` · `F.TEST` · `FACT` · `FACTDOUBLE` · `FALSE` · `FDIST`‡ · `FIND` · `FINDB` · `FINV`‡ · `FISHER` · `FISHERINV` · `FIXED` · `FLOOR.MATH` · `FLOOR.PRECISE` · `FORECAST` · `FORECAST.LINEAR` · `FORMULATEXT` · `FREQUENCY` · `FTEST`‡ · `FV` · `FVSCHEDULE` · `GAMMA` · `GAMMA.DIST` · `GAMMA.INV` · `GAMMADIST`‡ · `GAMMAINV`‡ · `GAMMALN` · `GAMMALN.PRECISE` · `GAUSS` · `GCD` · `GEOMEAN` · `GESTEP`† · `GETPIVOTDATA` · `GROWTH` · `HARMEAN` · `HEX2BIN`† · `HEX2DEC`† · `HEX2OCT`† · `HLOOKUP` · `HOUR` · `HSTACK` · `HYPERLINK` · `HYPGEOM.DIST` · `HYPGEOMDIST`‡ · `IF` · `IFNA` · `IFS` · `IMABS`† · `IMAGE` · `IMAGINARY`† · `IMARGUMENT`† · `IMCONJUGATE`† · `IMCOS`† · `IMCOSH`† · `IMCOT`† · `IMCSC`† · `IMCSCH`† · `IMDIV`† · `IMEXP`† · `IMLN`† · `IMLOG10`† · `IMLOG2`† · `IMPOWER`† · `IMPRODUCT`† · `IMREAL`† · `IMSEC`† · `IMSECH`† · `IMSIN`† · `IMSINH`† · `IMSQRT`† · `IMSUB`† · `IMSUM`† · `IMTAN`† · `INDEX` · `INDIRECT` · `INT` · `INTERCEPT` · `INTRATE` · `IPMT` · `IRR` · `ISBLANK` · `ISERR` · `ISERROR` · `ISEVEN` · `ISFORMULA` · `ISLOGICAL` · `ISNA` · `ISNONTEXT` · `ISNUMBER` · `ISO.CEILING` · `ISODD` · `ISOWEEKNUM` · `ISPMT` · `ISREF` · `ISTEXT` · `KURT` · `LAMBDA` · `LARGE` · `LCM` · `LEFT` · `LEFTB` · `LEN` · `LENB` · `LET` · `LINEST` · `LN` · `LOG` · `LOG10` · `LOGEST` · `LOGINV`‡ · `LOGNORM.DIST` · `LOGNORM.INV` · `LOGNORMDIST`‡ · `LOOKUP` · `LOWER` · `MAKEARRAY` · `MAP` · `MATCH` · `MAX` · `MAXA` · `MAXIFS` · `MDETERM` · `MDURATION` · `MEDIAN` · `MID` · `MIDB` · `MIN` · `MINA` · `MINIFS` · `MINUTE` · `MINVERSE` · `MIRR` · `MMULT` · `MOD` · `MODE`‡ · `MODE.MULT` · `MODE.SNGL` · `MONTH` · `MROUND` · `MULTINOMIAL` · `MUNIT` · `N` · `NA` · `NEGBINOM.DIST` · `NEGBINOMDIST`‡ · `NOMINAL` · `NORM.DIST` · `NORM.INV` · `NORM.S.DIST` · `NORM.S.INV` · `NORMDIST`‡ · `NORMINV`‡ · `NORMSDIST`‡ · `NORMSINV`‡ · `NOT` · `NOW` · `NPER` · `NPV` · `OCT2BIN`† · `OCT2DEC`† · `OCT2HEX`† · `ODD` · `OFFSET` · `OR` · `PDURATION` · `PEARSON` · `PERCENTILE`‡ · `PERCENTILE.EXC` · `PERCENTILE.INC` · `PERCENTRANK`‡ · `PERCENTRANK.EXC` · `PERCENTRANK.INC` · `PERMUT` · `PERMUTATIONA` · `PHI` · `PI` · `PMT` · `POISSON`‡ · `POISSON.DIST` · `POWER` · `PPMT` · `PRICE` · `PRICEDISC` · `PRICEMAT` · `PROB` · `PRODUCT` · `PROPER` · `PV` · `QUARTILE`‡ · `QUARTILE.EXC` · `QUARTILE.INC` · `QUOTIENT` · `RADIANS` · `RAND` · `RANDARRAY` · `RANDBETWEEN` · `RANK`‡ · `RANK.AVG` · `RANK.EQ` · `RATE` · `RECEIVED` · `REDUCE` · `REPLACE` · `REPLACEB` · `REPT` · `RIGHT` · `RIGHTB` · `ROMAN` · `ROW` · `ROWS` · `RRI` · `RSQ` · `SCAN` · `SEARCHB` · `SEC` · `SECH` · `SECOND` · `SEQUENCE` · `SERIESSUM` · `SHEET` · `SHEETS` · `SIGN` · `SIN` · `SINH` · `SKEW` · `SKEW.P` · `SLN` · `SLOPE` · `SMALL` · `SQRT` · `SQRTPI` · `STANDARDIZE` · `STDEV`‡ · `STDEV.P` · `STDEV.S` · `STDEVA` · `STDEVP`‡ · `STDEVPA` · `STEYX` · `SUBSTITUTE` · `SUBTOTAL` · `SUM` · `SUMIF` · `SUMIFS` · `SUMPRODUCT` · `SUMSQ` · `SUMX2MY2` · `SUMX2PY2` · `SUMXMY2` · `SWITCH` · `SYD` · `T` · `T.DIST` · `T.DIST.2T` · `T.DIST.RT` · `T.INV` · `T.INV.2T` · `T.TEST` · `TAN` · `TANH` · `TBILLEQ` · `TBILLPRICE` · `TBILLYIELD` · `TDIST`‡ · `TEXTJOIN` · `TIME` · `TIMEVALUE` · `TINV`‡ · `TOCOL` · `TODAY` · `TOROW` · `TRANSPOSE` · `TREND` · `TRIM` · `TRIMMEAN` · `TRUE` · `TRUNC` · `TTEST`‡ · `TYPE` · `UNICHAR` · `UNICODE` · `UNIQUE` · `UPPER` · `VALUE` · `VAR`‡ · `VAR.P` · `VAR.S` · `VARA` · `VARP`‡ · `VARPA` · `VDB` · `VLOOKUP` · `VSTACK` · `WEEKDAY` · `WEEKNUM` · `WEIBULL`‡ · `WEIBULL.DIST` · `WORKDAY` · `WORKDAY.INTL` · `WRAPCOLS` · `WRAPROWS` · `XIRR` · `XLOOKUP` · `XNPV` · `XOR` · `YEAR` · `YEARFRAC` · `YIELD` · `YIELDDISC` · `YIELDMAT` · `Z.TEST` · `ZTEST`‡

</details>

---

## Out of scope (counted, not rowed)

| Category | Functions | Why out of scope |
|---|--:|---|
| Engineering — Sheets-only | 3 | `IMCOTH`, `IMLOG`, `IMTANH`: complex-number functions, out of scope as the Excel map's [Engineering](ts-excel-function-mapping.md#out-of-scope-counted-not-rowed) category is. |

The 51 shared names that Excel puts out of scope (50 Engineering, 1 Web) are counted in the reconciliation above; the 38 compatibility aliases are not out of scope — they take their successor's row.

---

## Passthrough caveat (applies to every `passthrough` row)

The Excel map's [passthrough caveat](ts-excel-function-mapping.md#passthrough-caveat-applies-to-every-passthrough-row)
applies unchanged: every template is **Snowflake**; the variant fixes the column's type and its
attribute/measure role; aggregate passthroughs (`JOIN`, range `CONCATENATE`) are flagged for review
under PT1; a passthrough window must match ThoughtSpot's generated GROUP BY (formula reference,
*Window functions inside `sql_*_aggregate_op`*); and no passthrough may carry a runtime parameter —
so a QUERY string filter whose value comes from a cell needs the literal baked in, or the native
(case-insensitive) form. There is no `sql_number_aggregate_op` or `sql_number_op`; numeric aggregate
templates use `sql_double_aggregate_op` (BL-335).

---

## Open questions / gaps

Gaps this map adds to the Excel map's [G1–G19](ts-excel-function-mapping.md#open-questions--gaps),
which all apply to Sheets too.

| # | Gap | Impact |
|---|---|---|
| **G1** | QUERY's string semantics are case-sensitive; ThoughtSpot's native `=`, `contains` and `strpos` are not (BL-333). | Every QUERY text filter is a `sql_bool_op` passthrough, or accepts a change of meaning on mixed-case data. |
| **G2** | No regular expressions (Excel G7). | `REGEXMATCH`, `REGEXEXTRACT`, `REGEXREPLACE`, `SPLIT`'s fragment idiom and QUERY `matches` are all passthroughs; RE2 → Snowflake is a narrower gap than PCRE2, but lazy quantifiers, named groups and inline flags still need rewriting. |
| **G3** | External data and services ([**E8**](#how-to-read-the-tables)). | Sheets built on `IMPORTRANGE` or `GOOGLEFINANCE` need an ingestion step before any Model exists. |
| **G4** | No string aggregation (Excel G6). | `JOIN` and range `CONCATENATE` are aggregate passthroughs with an order the sheet never had to state. |
| **G5** | No spill (Excel E6). | `FLATTEN` and `CONTINUE` have no formula form; `SPLIT` survives only as a fixed number of fragment formulas, one per output column. |
| **G6** | Sheets behaviours that Google does not document and this map relies on: `=` / `EQ` ignoring case; `REGEXMATCH` matching a substring; `SEARCH` treating `*` literally; `MOD`'s result sign; `COUNTUNIQUE`'s case handling; `TEXT`'s `hh` without `AM/PM` (12-hour per Google's one-line description, 24-hour in Excel); `SPLIT` returning numeric fragments as numbers. | Each is marked *unverified* on its row. A Sheets result check (not a ThoughtSpot probe) settles them. |
| **G7** | `!=`, `<` / `>` on text, `in { }`, and `strpos` / `contains` with a **column** (not literal) needle were not in the case-insensitivity probe (BL-333). | `NE`, `GT`, `LT`… on text columns, and `SEARCH` with a column `search_for`, are mapped natively without proof that they lowercase both sides. |
| **G8** | Repo (**BL-338**): the `ts-object-formula-translate` skill routes the `google_sheets` dialect to the Excel map (`tools/ts-cli/ts_cli/formula_translate/detect.py`, `agents/cli/ts-object-formula-translate/SKILL.md`). | Until it reads this map first, a Sheets formula is translated without the deltas above (`REGEXEXTRACT` groups, `SPLIT` defaults, `CODE`, the one-argument `IFERROR`, QUERY). |

### Unverified

- **No row has been import-probed.** Every composition and template here is hand-derived. The
  live-verified forms this map leans on are the Excel map's `NETWORKDAYS.INTL` per-weekday counting
  form (weekend codes 1, 11 and `"1000001"`, no holidays) and its inline-holiday term (code 1 only),
  both 2026-10-06 ([probe record §6](../reviews/2026-10-06-formula-semantics-probes.md#6-excel-networkdays-family-per-weekday-counting-form)). Not probed: other weekend codes, holidays with other codes,
  serial-converted holidays, duplicate holidays, and `WORKDAY` / `WORKDAY.INTL` in any form.
- **Snowflake functions assumed without a live check:** `REGEXP_SUBSTR` with the `'e'` parameter and a
  group number; `TO_TIMESTAMP_NTZ(n, scale)` for epoch input; `STARTSWITH` / `ENDSWITH`;
  `DATE_PART(millisecond, …)`; `TO_CHAR` with `HH12` and `FF3`; non-capturing groups `(?:…)`; RE2 constructs inside a Snowflake
  pattern ([**E5**](#how-to-read-the-tables)).
- ~~**`[a] / nullif ( [b] , 0 )`**~~ — disproved 2026-10-06: `nullif` is not a ThoughtSpot function. `DIVIDE`, one-argument
  `IFERROR` and QUERY `/` now use plain `[a] / [b]`, which returns NULL on a zero divisor (probe record §7, BL-339).
- **`add_seconds` on a DATE** (`EPOCHTODATE`'s native alternative) — as the Excel map.
- **The undocumented Sheets behaviours** in [G6](#open-questions--gaps).
- **`CONTINUE`** — signature from historical documentation; no current Google page.

---

## Worked shape

A small sales sheet, rebuilt as Model formulas and one Answer.

Sheets:

```text
D2  =ARRAYFORMULA(IF(B2:B = "", , B2:B * C2:C))                      Line total, whole column
E2  =REGEXEXTRACT(A2, "SKU-(\d+)")                                   SKU number
F2  =INDEX(SPLIT(G2, ",;"), 1, 2)                                    second tag
H1  =QUERY(Sales!A:F, "select B, sum(D) where C contains 'West' group by B order by sum(D) desc limit 10")
I2  =ROUND(D2)
```

ThoughtSpot:

```yaml
formulas:
- id: formula_Line Total
  name: Line Total
  expr: "[SALES::Qty] * [SALES::Price]"            # ARRAYFORMULA and the blank guard are dropped (E6)

- id: formula_Sku Number
  name: Sku Number
  expr: "sql_string_op ( \"REGEXP_SUBSTR({0}, 'SKU-([0-9]+)', 1, 1, 'e', 1)\" , [SALES::Item] )"   # one group: Sheets returns the group

- id: formula_Second Tag
  name: Second Tag
  expr: "sql_string_op ( \"REGEXP_SUBSTR({0}, '[^,;]+', 1, 2)\" , [SALES::Tags] )"   # split_by_each + remove_empty_text defaults

- id: formula_Line Total Rounded
  name: Line Total Rounded
  expr: "round ( [formula_Line Total] , 1 )"      # places omitted = 0 digits = increment 1, never 0
```

and the `QUERY` becomes an Answer: columns `[Region]` and `sum ( [Line Total] )`, the filter
`sql_bool_op ( "CONTAINS({0}, {1})" , [SALES::Channel] , 'West' )` — case-sensitive, as QUERY was —
grouped by region, sorted by the sum descending, top 10.

Every line differs from a name-for-name Excel reading: `ARRAYFORMULA` is not a function at all;
Excel's `REGEXEXTRACT` would return `SKU-123` where Sheets returns `123`; `SPLIT`'s defaults split on
**each** of `,` and `;` and drop empty fragments, which `SPLIT_PART` does not; `ROUND` with no
`places` is legal only in Sheets; and the QUERY's `contains` keeps its case sensitivity only through
a passthrough. (`\d` in the sheet's RE2 pattern is written `[0-9]` in the template to keep the escape
out of the YAML string.)
