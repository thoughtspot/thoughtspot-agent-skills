<!-- currency: sisense — 2026-07 (Sisense L2024.x JAQL); 2026-08-26 finding 14.3: COUNT_DISTINCT axis corrected -- Sisense count==distinct and countduplicates==exact total, so BOTH are exact; the doc had reversed it in four places while functions.py (declared authoritative here) had it right -->
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
| `count` | `COUNT_DISTINCT` | Migrated | Sisense `count` is a **distinct** count (`functions.py:29`) — see the note on the row below. |
| `countduplicates` / `dupcount` | `COUNT` | **Migrated** | **Exact, not approximated** (corrected 2026-08-26, finding 14.3). Sisense `count` returns *unique* values while `dupCount` returns the *total* including duplicates, so they map **opposite to the intuitive reading** — `count` → `COUNT_DISTINCT`, `countduplicates` → `COUNT`. Both are exact. This doc declares `sisense/functions.py` authoritative; the code had it right and these rows had it backwards. |
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
| `count` | `unique count` | Sisense `count` is **distinct** (`functions.py:45`) — NOT `count` |
| `countduplicates` / `dupcount` | `count` | Sisense `dupCount` is the **exact total** including duplicates (`functions.py:46-47`); ThoughtSpot `count` is also a total, so the translation is exact. Documented here from 2026-08-26: finding 14.3 removed it from the Approximated table (correctly — it is not approximated) and it briefly appeared in neither table. |
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
