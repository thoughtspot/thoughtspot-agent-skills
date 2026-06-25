# SpotQL limitations — what doesn't work

<!-- currency: spotql — 2026-06 (champ-staging; epics SCAL-306544 / SCAL-316371) -->

What SpotQL can't do, and what fails *silently* (wrong numbers, no error).
**SpotQL behaviour is build-specific and moving fast** — treat this as a
dated snapshot, not gospel. When in doubt, probe with `ts spotql generate-sql` /
`fetch-data` (see the retest use case in `use-cases.md`).

**Authoritative source — two ThoughtSpot Jira epics (review these for live status):**
- **[SCAL-306544](https://thoughtspot.atlassian.net/browse/SCAL-306544)** — *[GA] Support
  Semantic SQL in QueryGen — rollout*. The bug-fix epic: its mostly-**Closed** children are
  the **fixes** below.
- **[SCAL-316371](https://thoughtspot.atlassian.net/browse/SCAL-316371)** — *[BACKLOG]
  SpotQL Feature Evaluations*. All **Open**: the canonical **known-unsupported** backlog.

Last reconciled: epics + live probe on **champ-staging (`champagne-master-aws`),
2026-06-25**. "✓ live" = I ran it; "ticket" = status taken from the Jira epic, not re-probed.

> **generate-sql SUCCESS ≠ usable.** Some constructs compile (generate-sql SUCCESS) but
> fail at execution or silently return wrong data. For anything risky, check `fetch-data`.

## ❌ Unsupported — hard error (you find out immediately)

| Construct | Failure | Ref |
|---|---|---|
| Self-join of a CTE | `SELF_JOIN` | ✓ live · [SCAL-316389](https://thoughtspot.atlassian.net/browse/SCAL-316389) |
| Non-equi `JOIN … ON` (inequality / constant in ON; between CTEs) | `NON_EQUI_JOIN` | [SCAL-316387](https://thoughtspot.atlassian.net/browse/SCAL-316387), [SCAL-316388](https://thoughtspot.atlassian.net/browse/SCAL-316388) |
| Subquery in `FROM` (derived table) / `IN (SELECT …)` | `QUERY_GEN_ERROR` / `QUERY_EXECUTION_FAILED` | ✓ live · [SCAL-319337](https://thoughtspot.atlassian.net/browse/SCAL-319337) |
| `STDDEV_*` / `VAR_*` in a `GROUP BY` query | `UNSUPPORTED_AGGREGATE` (scalar context works) | ✓ live |
| Percentiles other than `MEDIAN` (`PERCENTILE_CONT/DISC`, `APPROX_PERCENTILE`) | `UNSUPPORTED_AGGREGATE` | ✓ live · [SCAL-314707](https://thoughtspot.atlassian.net/browse/SCAL-314707) (closed as MEDIAN-only) |
| `SELECT *` · `COUNT(*)` / `COUNT(1)` | `SELECT_STAR` · `COUNT_STAR` | ✓ live |
| `SUM()` on an aggregate-formula column | `NESTED_AGGREGATE_NOT_SUPPORTED` — use `AGG()` | ✓ live |
| `ROLLUP` / `CUBE` / `GROUPING SETS` | rejected | [SCAL-319339](https://thoughtspot.atlassian.net/browse/SCAL-319339) |
| Many scalar functions: `INITCAP`, `REGEXP_SUBSTR`, `REGEXP_REPLACE`, `TO_VARCHAR`, bitwise (`BIT_*`), constant-only (`EXP`/`ACOS`/`LOG(b,x)`/`CHR`/`SPACE`/`CURRENT_DATE`/`TO_DATE`), `DAY_OF_YEAR`, `TRUNC(date,part)`, `CONCAT_WS`/`OVERLAY`/array fns | rejected / `NO_BASE_TABLES` | [SCAL-319333–319343](https://thoughtspot.atlassian.net/browse/SCAL-316371) |
| Variant / semi-structured / JSON (`ARRAY_CONTAINS`, `ARRAY_SIZE`, lateral flatten) | unsupported | [SCAL-316392–316396](https://thoughtspot.atlassian.net/browse/SCAL-316371), [SCAL-318984](https://thoughtspot.atlassian.net/browse/SCAL-318984) |

**Workarounds:** per-group `STDDEV`/percentile → aggregate in a CTE, take the stat in a
scalar outer SELECT (`patterns.md` § Statistics); `MEDIAN` works scalar. "A or B" → `WHERE
(A) OR (B)`, not a UNION/subquery. Date math → the SpotQL UDFs (`udf-reference.md`), not
`TRUNC`/`TO_DATE`/`CURRENT_DATE`.

## ⚠️ Silent wrong-answer — avoid (no error, wrong data — the dangerous ones)

| Construct | What actually happens | Ref |
|---|---|---|
| `UNION` / `UNION ALL` / `EXCEPT` / `INTERSECT` | only the **first** branch returns; rest silently dropped | ✓ live (asked 2 rows, got 1) |
| `QUALIFY …` | clause silently dropped → you get **all** rows, not the filtered set | [SCAL-319330](https://thoughtspot.atlassian.net/browse/SCAL-319330) |
| `FILTER (WHERE …)` on an aggregate | silently dropped → aggregate ignores the filter | [SCAL-319332](https://thoughtspot.atlassian.net/browse/SCAL-319332) |
| `TO_NUMBER(x)` | silently dropped (no-op) | [SCAL-319336](https://thoughtspot.atlassian.net/browse/SCAL-319336) |
| `SUM(CASE WHEN <raw-date '>=' literal> …)` | aggregate returns type-UNKNOWN, all zeros — use integer date-parts inside CASE | [SCAL-319329](https://thoughtspot.atlassian.net/browse/SCAL-319329) |
| `ROUND(x, N)` | rounds to the nearest **multiple of N**, not N decimal places | [SCAL-319323](https://thoughtspot.atlassian.net/browse/SCAL-319323) |

## 🔧 In flight — open bugs (behaviour may change; treat results with care)

| Issue | Status | Ref |
|---|---|---|
| Timestamp (`INT64`) column treated as date without conversion | In Review | [SCAL-317405](https://thoughtspot.atlassian.net/browse/SCAL-317405) |
| Alias not remapped during SQL serialization | In Review | [SCAL-317423](https://thoughtspot.atlassian.net/browse/SCAL-317423) |
| Decimal-precision SpotQL generation | In Review | [SCAL-318288](https://thoughtspot.atlassian.net/browse/SCAL-318288) |
| `Failed to transform QuerySpec: null` on some queries | In Triage | [SCAL-318834](https://thoughtspot.atlassian.net/browse/SCAL-318834) |
| Query with **only** a framed windowing function fails | In Triage | [SCAL-319898](https://thoughtspot.atlassian.net/browse/SCAL-319898) |
| Doubly-complex queries error at `ComplexQueryTransformer` | In Triage | [SCAL-320205](https://thoughtspot.atlassian.net/browse/SCAL-320205) |

## Not bugs — feature requests on the backlog

- Run SpotQL directly on **tables** (not just Models) — [SCAL-319871](https://thoughtspot.atlassian.net/browse/SCAL-319871)
- Custom-calendar switching in SpotQL — [SCAL-318205](https://thoughtspot.atlassian.net/browse/SCAL-318205)

## Maintaining this file

When you re-probe a ❌/⚠️ row and it now works, **remove it** (it's no longer a limitation)
and relax the matching rule in `spotql-rules.md` / `udf-reference.md` / `patterns.md`, then
bump the currency anchor at the top. When you hit a new failure, check it against
[SCAL-316371](https://thoughtspot.atlassian.net/browse/SCAL-316371) first — it's probably
already logged. To find which rows are worth re-probing, refresh ticket statuses from the
two epics (see `open-items.md` § Refreshing limitations from Jira) — but always confirm with
a live probe, since a ticket can be Closed without the behaviour actually changing (e.g.
`PERCENTILE_CONT` is closed as MEDIAN-only yet still errors).
