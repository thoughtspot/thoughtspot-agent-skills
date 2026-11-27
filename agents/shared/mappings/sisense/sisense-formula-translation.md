<!-- currency: sisense — 2026-11 (Sisense L2024.x JAQL; 2026-11-26 measured values + widget filter scope verified against a production Sisense migration and live imports); 2026-08-26 finding 14.3: COUNT_DISTINCT axis corrected -- Sisense count==distinct and countduplicates==exact total, so BOTH are exact; the doc had reversed it in four places while functions.py (declared authoritative here) had it right -->
# Sisense JAQL → ThoughtSpot formula translation

The translation map behind `ts sisense build-model`. The authoritative source is
`tools/ts-cli/ts_cli/sisense/functions.py` (`FUNCTION_MAP` / `UNSUPPORTED`); this
doc must agree with the code. Strategy (unchanged from the standalone converter):
deterministically translate the common subset; emit everything else as **NEEDS REVIEW** with
the original Sisense formula preserved — never faked. Coverage → status:
`AUTO → Migrated`, `PARTIAL → Approximated`, `MANUAL → NEEDS REVIEW`.

## String literals and `a * b / c` (BL-365, ts-cli 0.165.0)

ThoughtSpot reads a doubled quote in a single-quoted literal as **two** quotes (`'it''s'` is
`it''s`), its backslash escape fails before a space, and it reads `a * b / c` as
`a * ( b / c )` — with a division of two integers fixed-point at scale 6 (live, se-thoughtspot
2026-10-07; [formula reference](../../schemas/thoughtspot-formula-patterns.md#string-literals)).
So a Sisense literal is read SQL-standard (`''` is one quote), a literal holding a quote is emitted **double-quoted** (`"O'Brien"`), a
backslash doubled, and every product under a division bracketed (`( a * b ) / c`) — the
translator's last step, `formula_text.ts_finalize_formula`. Copying `'O''Brien'` across was a silent
wrong answer.

## Aggregations — plain JAQL `agg`, no formula

How a simple measure's JAQL `agg` reads in ThoughtSpot. **The CLI has no code path that emits
these** (BL-308): the `AGG_MAP` / `translate_agg` that once described one had no caller and
was deleted on 2026-11-08 (BL-447), because it mapped `count` to `aggregation: COUNT_DISTINCT`,
invariant I5's forbidden form. Use this table when building such a measure by hand.

| Sisense `agg` | ThoughtSpot | Status | Notes |
|---|---|---|---|
| `sum` | `SUM` | Migrated | |
| `avg` | `AVERAGE` | Migrated | |
| `count` | `unique count ( [T::col] )` **formula** | Migrated | Sisense `count` is a **distinct** count — see the note on the row below. Never the column aggregation `COUNT_DISTINCT`: ThoughtSpot stores that as an attribute on a text or date column, so search lists the values instead of counting them (I5, live 2026-10-29). |
| `countduplicates` / `dupcount` | `COUNT` | **Migrated** | **Exact, not approximated** (corrected 2026-08-26, finding 14.3). Sisense `count` returns *unique* values while `dupCount` returns the *total* including duplicates, so they map **opposite to the intuitive reading** — `count` → `unique count`, `countduplicates` → `COUNT`. Both are exact. |
| `min` | `MIN` | Migrated | |
| `max` | `MAX` | Migrated | |
| `stdev` | `STD_DEVIATION` | Migrated | sample standard deviation |
| `var` | `VARIANCE` | Migrated | sample variance |
| `median` / `stdevp` / `varp` / `mode` | — | NEEDS REVIEW | no clean TML aggregation keyword |

## Formula functions (`FUNCTION_MAP`) — deterministic 1:1 subset

Used inside a JAQL `formula`. Function names are rewritten in the resolved expression.

| Sisense function | ThoughtSpot | Notes |
|---|---|---|
| `sum` / `avg`(`average`) / `min` / `max` | `sum` / `average` / `min` / `max` | aggregation |
| `count` | `unique count` | Sisense `count` is **distinct** (`FUNCTION_MAP` in `functions.py`) — NOT `count` |
| `countduplicates` / `dupcount` | `count` | Sisense `dupCount` is the **exact total** including duplicates (`FUNCTION_MAP` in `functions.py`); ThoughtSpot `count` is also a total, so the translation is exact. Documented here from 2026-08-26: finding 14.3 removed it from the Approximated table (correctly — it is not approximated) and it briefly appeared in neither table. |
| `abs` | `abs` | |
| `round` | `round` | 1-arg direct; 2-arg is Approximated (see below) |
| `ceiling` | `ceil` | |
| `floor` | `floor` | |
| `power` | `pow` | |
| `sqrt` / `exp` / `mod` / `sign` | `sqrt` / `exp` / `mod` / `sign` | |
| `log` | `ln` | Sisense `Log` is the **natural** log (Sisense has no separate `Ln`) |
| `ln` | `ln` | defensive alias if a JAQL variant uses `ln` |
| `log10` | `log10` | |
| `ddiff(d1, d2)` | `diff_days(d1, d2)` | date difference, day grain |
| `stdev` | `stddev` | sample standard deviation (formula form) |
| `var` | `variance` | sample variance (formula form) |
| `median` | `median` | |
| `if` | `if` | conditional |
| `isnull` | `isnull` | TS spells it `isnull`, **not** `is_null` |
| `ifnull` | `ifnull` | |

### Context placeholders

A JAQL formula references fields through `[key]` placeholders resolved against a `context`:

- `{dim: "[Table.Column]"}` → the model column ref `[Column]` (the `Table.` qualifier and a
  trailing date-hierarchy tag like `Date (Calendar)` are stripped).
- If the expression already wraps the placeholder in an aggregation (`sum([rev])`), the bare
  column is substituted and the wrapping function maps via `FUNCTION_MAP`.
- If the placeholder appears bare and the fragment carries an `agg`, that agg is applied here
  (`agg([Column])`).
- A nested `{formula, context}` fragment recurses; an unsupported nested formula makes the whole
  formula NEEDS REVIEW.

## Widget measures → Answer formulas (`ts sisense build-liveboard`)

A widget's measures (an indicator's value, a chart's Values, a pivot's Values) are emitted as
**Answer formulas** named after the widget item. A plain `agg` over a column that is already
a Model `SUM` measure stays that column when nothing scopes it; everything else is a formula.
Code: `ts_cli/sisense/widget_fields.py` and `ts_cli/sisense/scope.py`.

### Measured values

`(agg, [Dim])` is a measured value: the aggregate restricted by `[Dim]`'s own filter in the
formula context. In Sisense that filter **replaces** any dashboard or widget filter on the same
column (verified on a live cube: a HIRED measured value kept its count under a
`Status = APPLIED` widget filter). So:

| Sisense | ThoughtSpot |
|---|---|
| `(count([id]), [Status])`, `[Status]` members `['HIRED']` | `group_aggregate ( unique_count_if ( [Status] = 'HIRED' , [id] ) , query_groups ( ) , query_filters ( ) - { [Status] } )` |
| `(sum([amt]), [Flag], [Type])` | `group_aggregate ( sum_if ( ( [Flag] = 1 ) and ( [Type] = 'X' ) , [amt] ) , … , query_filters ( ) - { [Flag] , [Type] } )` |
| `(count([id]), [Status]) / count([id])` | the measured value as above `/` `unique count([id])` (only the measured part is scoped) |

Members are literals; on a `numeric` JAQL item a numeric member is emitted bare (`[Flag] = 1`;
JAQL sends `"1"`, and `[Flag] = '1'` does not compile against a number column). Several
members → `[c] in { 'a' , 'b' }`; `exclude` → `!=` / `not ( [c] in { … } )`; a `from`/`to`
range → comparisons joined by `and`; an `all` filter restricts nothing but still drops the
query filter on the column. `count` → `unique_count_if`, `sum` → `sum_if`, `dupCount` →
`count_if`; other aggregates use `agg ( if ( cond ) then x else null )`. A member list on a
datetime column, a relative-date or ranking filter → **NEEDS REVIEW**.

Before 2026-11-26 the tuple was copied through verbatim as `(unique count([id]),[Status])`
and reported Migrated; ThoughtSpot cannot parse it.

### Widget filters and ignored dashboard filters

| Sisense | ThoughtSpot |
|---|---|
| Widget filter on a column with **no** Liveboard filter | search tokens: `[c] = 'a' 'b'`, `[c] != 'a'`, `[n] >= 5` |
| Widget filter on a column that **also** has a dashboard filter | folded into every measure as a condition (`unique_count_if ( [c] = 'a' , [id] )`), because a Liveboard filter on a column replaces the tile's own filter there; Sisense applies both |
| `metadata.ignore.ids` / `.dimensions` (dashboard filters the widget does not take) | each aggregate → `group_aggregate ( agg , G , query_filters ( ) - { [col] … } )` |
| `metadata.ignore.all` | each aggregate → `group_aggregate ( agg , G , { } )` |

`G` is `{ }` for a single-value widget (indicator) and `query_groups ( )` otherwise. Inside a
measured value the tile condition is applied too, except on the measured value's own columns.
All of these were imported on a cluster and every tile read back against direct SQL
(`ts-convert-from-sisense` open-item #6, and the Liveboard-filter table in
[thoughtspot-formula-patterns.md](../../schemas/thoughtspot-formula-patterns.md#group_aggregate)).

## `round` (BL-331)

| Sisense | ThoughtSpot | Notes |
|---|---|---|
| `round(x, n)`, literal `n` | `round(x, 10^-n)` | Exact mapping (AUTO). TS's 2nd arg is a rounding **increment** (`round(x, 0.01)` for 2 decimals), not Sisense's decimal-place **count**: `round(x, 2)` in TS is nearest-2 and `round(x, 0)` is NULL (live-probed 2026-10-06) |
| `round(x, n)`, non-literal `n` / 3+ args | — | NEEDS REVIEW |

## Approximated (mapped with a caveat → PARTIAL)

| Sisense | ThoughtSpot | Why review |
|---|---|---|
| `case(...)` | nested `if(...)` | mapped mechanically; verify the branch semantics |
| ~~`countduplicates` (as a formula wrapper)~~ | — | **Removed 2026-08-26 (finding 14.3): this is not approximated.** `countduplicates` → `count(...)` preserves duplicate-count semantics exactly, because Sisense `dupCount` *is* a total count and ThoughtSpot `count` *is* a total count. Listing it here labelled two exact translations as lossy in the conversion report. |

## Flagged — NEEDS REVIEW (`UNSUPPORTED`, never faked)

Presence of any of these (or an unknown function, or an unresolvable placeholder) makes the
whole formula NEEDS REVIEW; the original Sisense expression is preserved for a manual rebuild.

| Category | Sisense functions |
|---|---|
| Window / ranking | `rank`, `ordering`, `rsum`, `rpsum`, `rpavg`, `prev`, `next`, `all`, `now` |
| Time-intelligence — period-to-date | `ytdsum`, `ytdavg`, `mtdsum`, `mtdavg`, `qtdsum`, `qtdavg`, `wtdsum` |
| Time-intelligence — prior period | `pastday`, `pastweek`, `pastmonth`, `pastquarter`, `pastyear` |
| Growth / diff | `growth`, `growthrate`, `diffpastyear`, `diffpastmonth`, `growthpastyear`, `ydiff`, `qdiff`, `mdiff`, `hdiff`, `mndiff`, `sdiff` |
| Population / advanced statistics | `stdevp`, `varp`, `mode`, `largest`, `smallest`, `percentile`, `quartile`, `correl`, `covar`, `slope` |
| R integration | `rdouble`, `rint` |

> Note: `ddiff` is the one date function that IS supported (→ `diff_days`); the growth/diff
> family above is not. Sample `stdev` / `var` / `median` ARE supported; their **population**
> variants (`stdevp` / `varp` / `mode`) are not.
