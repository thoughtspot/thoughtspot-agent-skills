<!-- currency: domo — 2026-07 (Domo Beast Mode) -->
# Domo Beast Mode → ThoughtSpot formula translation

The translation map behind `ts domo build-model`. The authoritative source is
`tools/ts-cli/ts_cli/domo/functions.py` (`FUNCTION_MAP` / `PASSTHROUGH_MAP` /
`_UNSUPPORTED_RE`); this doc must agree with the code. The tables below are tables, not
prose, on purpose: `tools/validate/check_formula_catalog.py` only scans markdown table
rows, so a prose function list is invisible to it — and that is exactly how six invalid
function names shipped in the first revision of this PR. Strategy (same as the rest of the family): deterministically translate
the common subset; emit everything else as **NEEDS REVIEW** with the original Beast Mode
preserved — never faked. Coverage → status: `AUTO → Migrated`, `PARTIAL → Approximated`,
`MANUAL → NEEDS REVIEW`.

Beast Mode syntax is SQL-like and close to ThoughtSpot's, so most translation is two mechanical
passes plus a function-name map:

1. **Column refs**: Domo backtick-quotes columns — `` `Revenue` `` → `[Revenue]`.
2. **Function/aggregation rename** (tables below).
3. **Operators** (`+ - * / ( )`, comparisons) pass through unchanged.

## Data type mapping (dataset `schema.columns[].type`)

| Domo `type` | TS `data_type` | Default `column_type` | Notes |
|---|---|---|---|
| `STRING` | `VARCHAR` | `ATTRIBUTE` | |
| `DATETIME` | `DATE_TIME` | `ATTRIBUTE` | `DATE` if time part is always midnight; override-able |
| `DOUBLE` | `DOUBLE` | `MEASURE` | |
| `LONG` | `INT64` | `MEASURE` | override to `ATTRIBUTE` for id-like longs |

`column_type` defaults are heuristic (numeric → measure); an `overrides.json` entry wins.

## Aggregations (`AGG_MAP`)

Used both as a card column `aggregation` and inside Beast Mode formulas.

| Domo | ThoughtSpot | Status | Notes |
|---|---|---|---|
| `SUM` | `sum` | Migrated | |
| `AVG` / `AVERAGE` | `average` | Migrated | |
| `MIN` | `min` | Migrated | |
| `MAX` | `max` | Migrated | |
| `COUNT` | `count` | Migrated | |
| `COUNT(DISTINCT x)` | `unique count(x)` | Migrated | distinct-count idiom (TS: `unique count`, a space not underscore) |
| `MEDIAN` | — | NEEDS REVIEW | no clean TML aggregation keyword |
| `STDDEV` / `VARIANCE` | `stddev` / `variance` | Approximated | verify sample vs population |

## Functions (`FUNCTION_MAP`) — deterministic 1:1 name maps (Migrated)

Function names are token-rewritten; arguments pass through unchanged.

### Math

| Domo | ThoughtSpot | Notes |
|---|---|---|
| `ABS(x)` | `abs(x)` |  |
| `ROUND(x)` | `round(x)` | 2-arg form: TS 2nd arg is a rounding increment, not a decimal-place count |
| `FLOOR(x)` | `floor(x)` |  |
| `CEIL(x)` / `CEILING(x)` | `ceil(x)` |  |
| `POWER(x, n)` / `POW(x, n)` | `pow(x, n)` |  |
| `SQRT(x)` | `sqrt(x)` |  |
| `EXP(x)` | `exp(x)` |  |
| `LN(x)` | `ln(x)` |  |
| `LOG(x)` | `log(x)` |  |
| `MOD(a, b)` | `mod(a, b)` |  |
| `SIGN(x)` | `sign(x)` |  |

### String

| Domo | ThoughtSpot | Notes |
|---|---|---|
| `CONCAT(a, b)` | `concat(a, b)` | N args; `+` is numeric-only and does not join strings |
| `LENGTH(x)` / `LEN(x)` | `strlen(x)` |  |
| `SUBSTRING(x, s, n)` / `SUBSTR(x, s, n)` | `substr(x, s, n)` | zero-indexed start; `substring (` does not exist |
| `LEFT(x, n)` | `left(x, n)` |  |
| `RIGHT(x, n)` | `right(x, n)` |  |
| `INSTR(x, v)` | `strpos(x, v)` | 1-indexed, returns 0 when not found |

### Date

| Domo | ThoughtSpot | Notes |
|---|---|---|
| `YEAR(d)` | `year(d)` |  |
| `MONTH(d)` | `month(d)` |  |
| `DAY(d)` | `day(d)` |  |
| `HOUR(d)` | `hour(d)` |  |
| `MINUTE(d)` | `minute(d)` |  |
| `QUARTER(d)` | `quarter(d)` |  |
| `WEEK(d)` | `week(d)` |  |
| `NOW()` | `now()` |  |
| `CURRENT_DATE()` | `today()` |  |

### Type

| Domo | ThoughtSpot | Notes |
|---|---|---|
| `TO_NUMBER(x)` / `TO_DOUBLE(x)` | `to_double(x)` |  |
| `TO_CHAR(x)` / `TO_STRING(x)` | `to_string(x)` |  |
| `TO_DATE(x)` | `to_date(x)` |  |

## SQL pass-throughs (`PASSTHROUGH_MAP`) — Migrated

These six Domo functions have **no ThoughtSpot equivalent** — a bare call is rejected at
import with `error_code 14516` (BL-170/BL-171, live-disproved on se-thoughtspot 2026-06-13
for `upper`/`lower` and 2026-07-29/30 for the rest). They are translated into a
`sql_string_op` pass-through the warehouse evaluates, via the shared
`formula_common.wrap_passthrough_calls` — the same mechanism `ts qlik` and `ts powerbi` use.

| Domo | ThoughtSpot | Notes |
|---|---|---|
| `UPPER(x)` | `sql_string_op ( 'UPPER({0})' , [x] )` | `upper` does not exist in TS |
| `LOWER(x)` | `sql_string_op ( 'LOWER({0})' , [x] )` | `lower` does not exist in TS |
| `TRIM(x)` | `sql_string_op ( 'TRIM({0})' , [x] )` | `trim` does not exist in TS |
| `LTRIM(x)` | `sql_string_op ( 'LTRIM({0})' , [x] )` | `ltrim` does not exist in TS |
| `RTRIM(x)` | `sql_string_op ( 'RTRIM({0})' , [x] )` | `rtrim` does not exist in TS |
| `REPLACE(x, old, new)` | `sql_string_op ( 'REPLACE({0}, {1}, {2})' , [x] , old , new )` | `replace` does not exist in TS |

## Approximated (translated, verify)

| Domo Beast Mode | ThoughtSpot | Notes |
|---|---|---|
| `DATEDIFF(a,b)` / `DATE_DIFF` | `diff_days(a, b)` | verify arg order & unit — Domo may return b−a; TS `diff_days(a,b)` = a−b. For elapsed delivery time use `diff_days(delivered, purchase)`. |
| `STDDEV` / `VARIANCE` | `stddev` / `variance` | verify sample vs population |

## Structural / unsupported → NEEDS REVIEW

Emitted **verbatim** with a NEEDS REVIEW note — the token translator can't faithfully rewrite these,
so a human confirms the ThoughtSpot form (never a wrong-but-valid substitute):

| Domo Beast Mode | Recommended ThoughtSpot rewrite |
|---|---|
| `CASE WHEN c THEN x ELSE y END` | `if (c) then x else y` (nest for multi-branch) |
| `IFNULL(a,b)` / `COALESCE(a,b)` | `if (isnull(a)) then b else a` |
| `NULLIF(a,b)` | `if (a = b) then null else a` |
| `CAST(x AS t)` | `to_double` / `to_string` / `to_date` per target type |
| `RANK` / `ROW_NUMBER` / `LAG` / `LEAD` / running totals / `… OVER (PARTITION BY …)` | `rank` / window / `group_aggregate` — depends on intent, rebuild manually |
| `MEDIAN` / `PERCENTILE` | no clean TML keyword — rebuild manually |

## Worked examples (from the fixture Beast Modes)

| Beast Mode (Domo) | ThoughtSpot formula | Status |
|---|---|---|
| `SUM(\`Revenue\`) - SUM(\`Discount\`)` | `sum([Revenue]) - sum([Discount])` | Migrated |
| `SUM(\`Revenue\`) / COUNT(DISTINCT \`Transaction ID\`)` | `sum([Revenue]) / unique count([Transaction ID])` | Migrated |
| `(SUM(\`Discount\`) / SUM(\`Revenue\`)) * 100` | `(sum([Discount]) / sum([Revenue])) * 100` | Migrated |

Formulas become `[formula_<name>]` id-referenced Model formulas so they import in a single pass
(same convention as `ts qlik`).
