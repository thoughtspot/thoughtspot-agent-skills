<!-- currency: sisense — 2026-07 (Sisense L2024.x JAQL) -->
# Sisense JAQL → ThoughtSpot formula translation

The translation map behind `ts sisense build-model`. The authoritative source is
`tools/ts-cli/ts_cli/sisense/functions.py` (`AGG_MAP` / `FUNCTION_MAP` / `UNSUPPORTED`); this
doc must agree with the code. Strategy (unchanged from the standalone converter):
deterministically translate the common subset; emit everything else as **NEEDS REVIEW** with
the original Sisense formula preserved — never faked. Coverage → status:
`AUTO → Migrated`, `PARTIAL → Approximated`, `MANUAL → NEEDS REVIEW`.

## Aggregations (`AGG_MAP`) — plain JAQL `agg`, no formula

A simple measure's JAQL `agg` becomes a TML column `aggregation:` keyword.

| Sisense `agg` | ThoughtSpot aggregation | Status | Notes |
|---|---|---|---|
| `sum` | `SUM` | Migrated | |
| `avg` | `AVERAGE` | Migrated | |
| `count` | `COUNT` | Migrated | |
| `countduplicates` | `COUNT` | Approximated | DupCount approximated as COUNT |
| `min` | `MIN` | Migrated | |
| `max` | `MAX` | Migrated | |
| `stdev` | `STD_DEVIATION` | Migrated | sample standard deviation |
| `var` | `VARIANCE` | Migrated | sample variance |
| `median` / `stdevp` / `varp` / `mode` | — | NEEDS REVIEW | no clean TML aggregation keyword |

## Formula functions (`FUNCTION_MAP`) — deterministic 1:1 subset

Used inside a JAQL `formula`. Function names are rewritten in the resolved expression.

| Sisense function | ThoughtSpot | Notes |
|---|---|---|
| `sum` / `avg`(`average`) / `count` / `min` / `max` | `sum` / `average` / `count` / `min` / `max` | aggregation |
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

## Approximated (mapped with a caveat → PARTIAL)

| Sisense | ThoughtSpot | Why review |
|---|---|---|
| `case(...)` | nested `if(...)` | mapped mechanically; verify the branch semantics |
| `round(x, n)` (2-arg) | `round(x, n)` | TS's 2nd arg is a rounding **increment** (e.g. `round(x, 0.01)` for 2 decimals), not Sisense's decimal-place **count** |
| `countduplicates` (as a formula wrapper) | `count(...)` | duplicate-count semantics not preserved |

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
