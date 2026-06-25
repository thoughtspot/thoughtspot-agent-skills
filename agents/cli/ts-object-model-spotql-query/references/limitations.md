# SpotQL limitations — what doesn't work (and what now does)

What SpotQL can't do, what fails *silently* (wrong numbers, no error), and what was broken
but is now fixed. **SpotQL behaviour is build-specific and moving fast** — treat this as a
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

## ✅ Now works (was broken in the older catalogue) — don't apply the old workarounds

| Construct | Ref |
|---|---|
| Aggregate × numeric literal — `SUM("x") * 100`, `/ 100.0` (no longer zeros) | ✓ live |
| `NTILE(n)` | ✓ live · [SCAL-317244](https://thoughtspot.atlassian.net/browse/SCAL-317244) |
| `ROWS BETWEEN …` explicit window frame (now preserved) | ✓ live · [SCAL-313194](https://thoughtspot.atlassian.net/browse/SCAL-313194) |
| ≥2 model-derived CTEs JOINed in the main SELECT | ✓ live · [SCAL-314708](https://thoughtspot.atlassian.net/browse/SCAL-314708) |
| CTE selecting `FROM` another CTE (chained CTEs) | ticket · [SCAL-314709](https://thoughtspot.atlassian.net/browse/SCAL-314709) |
| `LAG(col, N)` / `LEAD(col, N)` explicit offset > 1 | ticket · [SCAL-314621](https://thoughtspot.atlassian.net/browse/SCAL-314621) |
| `NTH_VALUE(col, N)` | ticket · [SCAL-314622](https://thoughtspot.atlassian.net/browse/SCAL-314622) |
| `STDDEV` scalar (no GROUP BY); `STDDEV` vs `STDDEV_POP` default fixed | ticket · [SCAL-314705](https://thoughtspot.atlassian.net/browse/SCAL-314705), [SCAL-314706](https://thoughtspot.atlassian.net/browse/SCAL-314706) |
| `CASE` in `GROUP BY`; `GREATEST`/`LEAST` var-args; `SELECT <const> AS x`; `OFFSET` | tickets · [SCAL-314710](https://thoughtspot.atlassian.net/browse/SCAL-314710), [SCAL-316385](https://thoughtspot.atlassian.net/browse/SCAL-316385), [SCAL-316386](https://thoughtspot.atlassian.net/browse/SCAL-316386), [SCAL-318291](https://thoughtspot.atlassian.net/browse/SCAL-318291) |
| `AGG()` on aggregate-formula columns | ✓ live |

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

When you re-probe a ❌/⚠️ row and it now works, move it to **Now works**, date it, cite the
SCAL ticket if one flipped to Closed, and relax the matching rule in `spotql-rules.md` /
`udf-reference.md`. When you hit a new failure, check it against
[SCAL-316371](https://thoughtspot.atlassian.net/browse/SCAL-316371) first — it's probably
already logged.
