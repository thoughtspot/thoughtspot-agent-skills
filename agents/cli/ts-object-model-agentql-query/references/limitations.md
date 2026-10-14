# AgentQL limitations — what doesn't work

<!-- currency: spotql — 2026-10 (SE demo cluster, 26.9.0.cl PROD; epics SCAL-306544 / SCAL-316371) -->

What AgentQL can't do, and what fails *silently* (wrong numbers, no error).
**AgentQL behaviour is build-specific and moving fast** — treat this as a
dated snapshot, not gospel. When in doubt, probe with `ts agentql generate-sql` /
`fetch-data` (see the retest use case in `use-cases.md`).

> **Backing-store-specific:** if the Model is backed by a **Snowflake Semantic
> View**, also read [snowflake-sv-backing.md](snowflake-sv-backing.md)
> (EXPERIMENTAL) — the `100072` NULL-key bug, window-via-CTE, no `FROM`-subqueries,
> and non-additive-metric behaviour are characterised there.

**Authoritative source — two ThoughtSpot Jira epics (review these for live status):**
- **[SCAL-306544](https://thoughtspot.atlassian.net/browse/SCAL-306544)** — *[GA] Support
  Semantic SQL in QueryGen — rollout*. The bug-fix epic: its mostly-**Closed** children are
  the **fixes** below.
- **[SCAL-316371](https://thoughtspot.atlassian.net/browse/SCAL-316371)** — *[BACKLOG]
  AgentQL Feature Evaluations*. The canonical **known-unsupported** backlog.

Last reconciled: **2026-10-14**, against both epics plus an ~80-probe live sweep on the
**SE demo cluster, build 26.9.0.cl (PROD)**, Snowflake-backed "DunderMifflin Sales" Model
(single table, has a date column) and the multi-table "Dunder Mifflin" Model (aggregate
formulas). That is the **second build** to agree with the 2026-07-29 sweep (jul.26.mt dev),
so the rows re-verified on both are no longer single-build findings. The date rows that
2026-07-29 could not reach (no date column on that Model) were probed this time. Earlier:
nebula-spotQL 2026-07-07/08. "✓ live <date>" = probed on that date; "ticket" = status taken
from Jira, not probed.

> **generate-sql SUCCESS ≠ usable.** Many constructs compile (generate-sql SUCCESS) but
> fail at execution or silently return wrong data. For anything risky, check `fetch-data`.

> **A Jira status is not evidence either way.** On 26.9.0.cl, `CAST(<literal>)` works while
> its ticket is still New, and scalar `STDDEV` still fails although
> [SCAL-314019](https://thoughtspot.atlassian.net/browse/SCAL-314019) is closed as fixed in
> 26.8.0.cl. The probe is the source of truth.

## ❌ Unsupported — hard error (you find out immediately, or at `fetch-data`)

| Construct | Failure | Ref |
|---|---|---|
| Self-join of a CTE | `SELF_JOIN` | ✓ live 2026-10-14 · [SCAL-316389](https://thoughtspot.atlassian.net/browse/SCAL-316389) |
| Non-equi `JOIN … ON` (inequality / constant in ON; between CTEs) | Model ⋈ CTE: `NON_EQUI_JOIN`. **Between two CTEs the error is misleading** — `CTE table alias not found: b`, naming the right-hand CTE rather than the inequality | ✓ live 2026-10-14 · [SCAL-316387](https://thoughtspot.atlassian.net/browse/SCAL-316387), [SCAL-316388](https://thoughtspot.atlassian.net/browse/SCAL-316388) |
| Subquery in `FROM` (derived table) | `TABLE_NOT_FOUND` at compile (was `QUERY_GEN_ERROR` on older builds) | ✓ live 2026-10-14 · [SCAL-319337](https://thoughtspot.atlassian.net/browse/SCAL-319337) |
| `IN (SELECT …)` | **compiles (`generate-sql` SUCCESS) but fails at `fetch-data`** — the subquery is emitted untranslated into the warehouse SQL (Snowflake syntax error on 26.9.0.cl; *"Object 'X' does not exist"* on jul.26.mt). Rewrite as a CTE + equi-join (`patterns.md` § Semi-join via CTE — and dedupe the key CTE, or the join fans out) | ✓ live 2026-10-14 · [SCAL-326936](https://thoughtspot.atlassian.net/browse/SCAL-326936), [SCAL-319337](https://thoughtspot.atlassian.net/browse/SCAL-319337) |
| `STDDEV_*` / `VAR_*` on a Model column — **grouped AND scalar** | `UNSUPPORTED_AGGREGATE`. Scalar context worked on earlier builds — regression on jul.26.mt, **still present on 26.9.0.cl** despite [SCAL-314019](https://thoughtspot.atlassian.net/browse/SCAL-314019) being closed as fixed. Two forms work: the CTE workaround (materialise the aggregate in a CTE, take the statistic over the CTE column) and the window form `STDDEV_SAMP(SUM(x)) OVER ()`. `MEDIAN` is unaffected (scalar and grouped — see ✅) | ✓ live 2026-10-14 · [SCAL-326935](https://thoughtspot.atlassian.net/browse/SCAL-326935) |
| Percentiles other than `MEDIAN` (`PERCENTILE_CONT/DISC`, `APPROX_PERCENTILE`) | `UNSUPPORTED_AGGREGATE` | ✓ live 2026-10-14 · [SCAL-314707](https://thoughtspot.atlassian.net/browse/SCAL-314707) (closed as duplicate) |
| `SELECT *` · `COUNT(*)` / `COUNT(1)` | `SELECT_STAR` · `COUNT_STAR` | ✓ live 2026-10-14 |
| `SUM()` on an aggregate-formula column | `NESTED_AGGREGATE_NOT_SUPPORTED` — use `AGG()` (which works) | ✓ live 2026-10-14 |
| `AGG()` (or a bare reference) to a **semi-additive** measure — outermost op `last_value`/`first_value` with `query_groups()` | `NON_CONVERTIBLE_FUNCTION` ("Non standard sql function QueryGroups") — use `SUM()` instead (identity pass-through over the per-group snapshot). Only when it is the *outermost* op: `sum(last_value(...))` is a normal `AGG()` measure. | ✓ live 2026-07-13 (nebula-aggregate-aware) — not re-probed |
| `moving_sum(group_aggregate(...), …)` at grand-total or grouped by a non-order column | `INVALID_WINDOWING_FUNCTION_ARGUMENTS` — distinct from the semi-additive class; wrapper is still `AGG()` (`SUM()` → NESTED). Needs its order column present; may be a broader `moving_sum`/AgentQL gap (untriaged) | ✓ live 2026-07-13 — not re-probed |
| `ROLLUP` / `CUBE` / `GROUPING SETS` | rejected — `Failed to deserialize SQL: NullPointerException` on 26.9.0.cl | ✓ live 2026-10-14 · [SCAL-319339](https://thoughtspot.atlassian.net/browse/SCAL-319339) |
| Unknown scalar functions: `INITCAP`, `REGEXP_SUBSTR`, `TO_VARCHAR` | `Failed to deserialize SQL: Unknown function` | ✓ live 2026-10-14 · [SCAL-319333](https://thoughtspot.atlassian.net/browse/SCAL-319333), [SCAL-319334](https://thoughtspot.atlassian.net/browse/SCAL-319334), [SCAL-319335](https://thoughtspot.atlassian.net/browse/SCAL-319335) |
| `REGEXP_REPLACE` | `NO_BASE_TABLES_IN_QUERY_NOT_SUPPORTED` | ✓ live 2026-10-14 · [SCAL-319338](https://thoughtspot.atlassian.net/browse/SCAL-319338) |
| `CURRENT_DATE`, `NOW()` | `SQL_DATE_FUNCTION` — an explicit validation error (*"Use literal dates"*). `TO_DATE('<literal>')` in a filter works — see ✅ | ✓ live 2026-10-14 (`CURRENT_DATE`) |
| `LOG(base, x)` (two-argument) | `Invalid number of operands for the operator: OP_LOG2` | ✓ live 2026-10-14 · [SCAL-319341](https://thoughtspot.atlassian.net/browse/SCAL-319341) |
| `DAY_OF_YEAR(x)`, `EXTRACT(DOY …)` | compiles, then renders `extract(day_of_year from …)`; Snowflake wants `dayofyear` → fails at `fetch-data`. **Workaround: `DAY_IN_YEAR_NUMBER(x)`**, which returns the true day of year | ✓ live 2026-10-14 · [SCAL-319342](https://thoughtspot.atlassian.net/browse/SCAL-319342), [SCAL-327864](https://thoughtspot.atlassian.net/browse/SCAL-327864) |
| `EXTRACT(DOW …)` | rejected at parse, `DatePart expected`. Exact equivalent: `DAY_IN_WEEK_NUMBER(x) % 7` (Mon=1..Sun=7, so mod 7 gives Sun=0..Sat=6) | ✓ live 2026-10-14 · [SCAL-327864](https://thoughtspot.atlassian.net/browse/SCAL-327864) |
| `DATE_TRUNC(unit, col)` · `TRUNC(date, part)` | **compiles, then fails at `fetch-data`.** The generated SQL leaks the parser alias (`"t1".order date` / `"t1".tabledate`), **drops the unit** (`trunc(x, null)`) and **drops the `GROUP BY`**, wrapping the date in `min()` — the leaked alias is what makes the warehouse reject it, on columns with and without spaces in the name. Over a CTE column it fails at compile (`NullPointerException`). Use the date-part UDFs in `udf-reference.md` | ✓ live 2026-10-14 · [SCAL-326944](https://thoughtspot.atlassian.net/browse/SCAL-326944), [SCAL-319342](https://thoughtspot.atlassian.net/browse/SCAL-319342) |
| Bitwise (`BITAND`, `BIT_*`) | compiles to `&`, which Snowflake rejects (`Unknown function "&"`) at `fetch-data` | ✓ live 2026-10-14 (`BITAND`) · [SCAL-319340](https://thoughtspot.atlassian.net/browse/SCAL-319340) |
| `OVERLAY(… PLACING …)` | compiles, fails at `fetch-data` (syntax error at `placing`) | ✓ live 2026-10-14 · [SCAL-319343](https://thoughtspot.atlassian.net/browse/SCAL-319343) |
| `REGEXP_LIKE(x, p)` / `~` / `!~` | compiles, then emits `like_regex`, which the warehouse cannot parse → fails at `fetch-data`. Filed for Trino; **reproduces on Snowflake**. Use `LIKE` / `ILIKE` | ✓ live 2026-10-14 (`REGEXP_LIKE`) · [SCAL-338545](https://thoughtspot.atlassian.net/browse/SCAL-338545) |
| `LTRIM(x, chars)` / `RTRIM(x, chars)` (two-argument form) | compiles, then renders ANSI `trim(leading 'D' from …)`, which Snowflake rejects. The **single-argument** form is correct | ✓ live 2026-10-14 · [SCAL-326943](https://thoughtspot.atlassian.net/browse/SCAL-326943) |
| `CAST(<function call> AS <type>)` **in a query block that joins a CTE** | `UNSUPPORTED_EXPRESSION` — *"Failed to traverse CAST source expression"*. The trigger is the **join to a CTE**, not the CTE: the identical expression compiles in a CTE that joins nothing, and fails in either a CTE body or the outer query once one joins a CTE. **The affected set is inconsistent** — `LOWER`, `EXTRACT`, `TRUNC` and `TO_NUMBER` fail; `ABS`, `ROUND`, `MONTH_NUMBER`, arithmetic and bare columns are fine. Workaround: drop the cast where the inner expression already has the target type (`CAST(TRUNC(EXTRACT(…)) AS INTEGER)` → `TRUNC(EXTRACT(…))`), verified to return identical values | ✓ live 2026-10-14 (`LOWER`, `EXTRACT` fail; `ABS` passes) · [SCAL-330772](https://thoughtspot.atlassian.net/browse/SCAL-330772) |
| Outer aggregation over a **set-operation CTE** (`WITH u AS (… UNION ALL …) SELECT u.k, SUM(u.v) FROM u GROUP BY u.k`) | `10000` — *"Failed to transform QuerySpec: null"* | ✓ live 2026-10-14 · [SCAL-330561](https://thoughtspot.atlassian.net/browse/SCAL-330561), [SCAL-318834](https://thoughtspot.atlassian.net/browse/SCAL-318834) |
| Variant / semi-structured / JSON (`ARRAY_CONTAINS`, `ARRAY_SIZE`, lateral flatten) | unsupported. **Ticket movement:** the variant children were closed *Fixed* 2026-08-28 and [SCAL-318984](https://thoughtspot.atlassian.net/browse/SCAL-318984) *Support for JSON* is closed, but the parent [SCAL-325271](https://thoughtspot.atlassian.net/browse/SCAL-325271) is still *In Design* — not probed (no VARIANT column on the test Models) | ticket · [SCAL-316392–316396](https://thoughtspot.atlassian.net/browse/SCAL-316371) |

**Workarounds:** `STDDEV`/`VAR`/percentile → aggregate in a CTE, take the stat in the
outer SELECT (`patterns.md` § Statistics), or `STDDEV_SAMP(SUM(x)) OVER ()`; `MEDIAN`
works directly. Membership filters (`IN (SELECT …)`) → CTE + equi-join (`patterns.md`
§ Semi-join via CTE). Date math → the AgentQL UDFs (`udf-reference.md`), not
`DATE_TRUNC`/`TRUNC`/`CURRENT_DATE`. Regex → `LIKE` / `ILIKE`.

## ⚠️ Silent wrong-answer — avoid (no error, wrong data — the dangerous ones)

| Construct | What actually happens | Ref |
|---|---|---|
| Aggregate condition in `WHERE` (e.g. `WHERE SUM(x) > 0`) | invalid SQL, but silently reinterpreted as `HAVING` — filters post-aggregation, no error. Write `HAVING` explicitly; don't rely on the lenient parse | ✓ live 2026-10-14 |
| **Any dimension-only query on a Model without `join_progressive: true`** | every table in the Model is joined into every query, even one selecting a single dimension column, so results are silently **filtered by the fact table** — members with no fact rows disappear. No error; the row count just looks plausible and is wrong. Anti-join patterns return zero rows. **This is a Model defect, not an AgentQL one** — check `model.properties.join_progressive` via `ts tml export --parse`. UI-built Models set it; hand-authored model TML does not. See `patterns.md` § Dimension-anchored anti-join | ✓ live 2026-08-10 — same query, same star: 73 members without it, the true 79 with it. Not re-probed |
| Set-operation branches with **mismatched column types** at the same ordinal (e.g. VARCHAR vs DOUBLE) | compiles (`generate-sql` SUCCESS) but fails at `fetch-data` with `QUERY_EXECUTION_FAILED` (e.g. *Numeric value 'Dwight Schrute' is not recognized*) — not caught at compile time | ✓ live 2026-10-14 |
| `QUALIFY …` | clause silently dropped from generated SQL (no `ROW_NUMBER` emitted at all) → you get **all** rows, not the filtered set (60 rows where top-1-per-group is 5) | ✓ live 2026-10-14 · [SCAL-319330](https://thoughtspot.atlassian.net/browse/SCAL-319330) |
| `FILTER (WHERE …)` on an aggregate | silently dropped → aggregate ignores the filter and returns the unfiltered total (9,305 where the `SUM(CASE …)` control gives 1,756). Use `SUM(CASE WHEN … THEN x ELSE 0 END)` | ✓ live 2026-10-14 · [SCAL-319332](https://thoughtspot.atlassian.net/browse/SCAL-319332) |
| `SUM(CASE WHEN <raw-date '>=' literal> …)` | the generated warehouse SQL is **correct**, but the result column comes back typed `UNKNOWN` with an empty value — the defect is in ThoughtSpot's result typing, not the SQL. Use integer date-parts inside the CASE (`YEAR(d) >= 2025` returns the right number), or move the date condition to `WHERE` | ✓ live 2026-10-14 · [SCAL-319329](https://thoughtspot.atlassian.net/browse/SCAL-319329) |
| `AVG`/`MIN`/`MAX` on a measure over an **SV or MV backing** | outer aggregate silently dropped — returns the measure's native aggregation (e.g. `AVG` of a `SUM` measure returns the `SUM`). Regular Models hard-error (`NESTED_AGGREGATE_NOT_SUPPORTED`). `MEDIAN`/`STDDEV` fail as nested aggregates on all backings. **Fix:** the CTE statistics pattern — materialise at a grain, apply the statistic in the outer SELECT (`patterns.md` § Statistics). | ✓ live 2026-07-21 · [snowflake-sv-backing.md](snowflake-sv-backing.md). Not re-probed |
| `LIMIT n` with **n > 100,000** | silently rewritten to `LIMIT 100000` — see the note below | ✓ live 2026-10-14 |

> **Every generated statement is capped at 100,000 rows.** `LIMIT 100000` is appended to
> statements that carry no `LIMIT` of their own, and an explicit larger `LIMIT` (e.g.
> `LIMIT 200000`) is **rewritten down** to 100,000 (✓ live 2026-10-14). On a large Model a
> bulk extract is silently truncated with nothing in the response to say so. Whether it is
> configurable is unconfirmed. Smaller explicit limits are honoured as written.

> **Diagnostics that name the wrong thing** ([SCAL-326945](https://thoughtspot.atlassian.net/browse/SCAL-326945)):
> a derived table in a `JOIN` reports `Table 't' not found`, where `'t'` is a hardcoded
> placeholder that appears whatever the real alias is; `GROUP BY 1` reports
> `Missing formula alias: <guid>`; and a non-equi join between two CTEs reports
> `CTE table alias not found` (✓ live 2026-10-14). None names the construct the caller wrote.

## 🔧 In flight — open bugs (behaviour may change; treat results with care)

| Issue | Status (Jira, 2026-10-14) | Ref |
|---|---|---|
| Timestamp (`INT64`) column treated as date without conversion | Resolved — fix version 26.9.0.sw (software release, unreleased). Not probed (no INT64 timestamp column) | [SCAL-317405](https://thoughtspot.atlassian.net/browse/SCAL-317405) |
| Alias not remapped during SQL serialization | Resolved — fix version 26.9.0.sw. Not probed | [SCAL-317423](https://thoughtspot.atlassian.net/browse/SCAL-317423) |
| Doubly-complex queries error at `ComplexQueryTransformer` | Resolved — fix version 26.9.0.sw. Not probed | [SCAL-320205](https://thoughtspot.atlassian.net/browse/SCAL-320205) |
| `Failed to transform QuerySpec: null` on some queries | In Triage. Reproduces via outer aggregation over a set-op CTE (❌ above) | [SCAL-318834](https://thoughtspot.atlassian.net/browse/SCAL-318834) |
| Grouped query combining a distinct-count **aggregate-formula** measure (`AGG`) with any other measure fails | New. A raw `COUNT(DISTINCT x)` alongside `SUM(y)` works on 26.9.0.cl; the ticket's case needs a `count_distinct` formula column, which the test Models lack — not probed | [SCAL-330560](https://thoughtspot.atlassian.net/browse/SCAL-330560) |

## ✅ Fixed — previously broken, now working

"Both builds" = verified on jul.26.mt dev (2026-07-29) **and** 26.9.0.cl PROD (2026-10-14).

| Construct | Previously | Fixed by | Verified |
|---|---|---|---|
| `UNION ALL` / `UNION` / `EXCEPT` / `EXCEPT ALL` / `INTERSECT` / `INTERSECT ALL` at top level | second branch silently dropped | [SCAL-313049](https://thoughtspot.atlassian.net/browse/SCAL-313049) (26.9.0.cl) | ✓ live 2026-07-07 (nebula-spotQL), re-verified 2026-10-14 |
| Set operation **inside a user-defined CTE**, branches without aggregates | previously documented as wholly unsupported — that was too broad | engineering-confirmed; retested after SCAL-313049 | ✓ live 2026-07-08 (nebula-spotQL) — raw-column branches and attribute-only GROUP BY branches both compile and execute; square-bracket identifiers (`[Col]`) also accepted |
| Set operation inside a CTE **with aggregated branches** (`SUM(col) … GROUP BY` in a branch) | `QUERY_GEN_ERROR` (GroupAggregateOptimizationTransformer) | fixed by jul.26.mt | ✓ live 2026-07-29. (Aggregating *over* such a CTE still fails — see ❌) |
| `ORDER BY` / `LIMIT` on a set-operator result | ORDER BY silently dropped; LIMIT misplaced into the first branch | fixed by jul.26.mt | ✓ both builds — applied to the combined result, rows verified sorted |
| `ROUND(x, N)` | rounded to the nearest **multiple of N** | [SCAL-319323](https://thoughtspot.atlassian.net/browse/SCAL-319323) | ✓ both builds — `ROUND(AVG(x), 2)` = 23.23 for a true 23.22795 |
| `TO_NUMBER(x)` | silently dropped (no-op) | behaviour changed by jul.26.mt ([SCAL-319336](https://thoughtspot.atlassian.net/browse/SCAL-319336) still Open) | ✓ both builds — compiles to `CAST(x AS double)`; hard `QUERY_EXECUTION_FAILED` on non-numeric data. Don't use it on non-numeric columns |
| `CONCAT_WS` · `LENGTH()` | rejected · listed as forbidden in the early dialect rules | fixed by jul.26.mt | ✓ both builds — incl. in `GROUP BY` |
| `MEDIAN` in a `GROUP BY` query | grouped statistics rejected (scalar-only) | fixed by jul.26.mt | ✓ both builds — correct per-group values |
| A query whose **only** window function is framed (`SUM(x) OVER (ORDER BY d ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)`) | failed | [SCAL-319898](https://thoughtspot.atlassian.net/browse/SCAL-319898) (26.9.0.cl) | ✓ live 2026-10-14 — rolling values correct |
| `LIMIT n OFFSET m` | `OFFSET` ignored | [SCAL-318291](https://thoughtspot.atlassian.net/browse/SCAL-318291) (26.9.0.cl) | ✓ live 2026-10-14 — returns ranks 2–3 |
| Decimal literals in arithmetic (`SUM(x) * 1.25`) | precision lost | [SCAL-318288](https://thoughtspot.atlassian.net/browse/SCAL-318288) (26.9.0.cl) | ✓ live 2026-10-14 — exact (1,756 × 1.25 = 2,195) |
| `GREATEST` / `LEAST` with 3+ arguments | variable arguments rejected | [SCAL-316385](https://thoughtspot.atlassian.net/browse/SCAL-316385) (26.8.0.cl) | ✓ live 2026-10-14 — emitted as `greatest(a, b, 5)` |
| Selecting a constant as a label (`SELECT 'x' AS lbl, SUM(…)`) | failed | [SCAL-316386](https://thoughtspot.atlassian.net/browse/SCAL-316386) (26.8.0.cl) | ✓ live 2026-10-14 |
| `NTILE(n)` | emitted a literal `$tiles` argument | [SCAL-317244](https://thoughtspot.atlassian.net/browse/SCAL-317244) (26.8.0.cl) | ✓ live 2026-10-14 |
| `LAG(x, N, default)` / `LEAD(x, N)` | optional arguments dropped | [SCAL-314621](https://thoughtspot.atlassian.net/browse/SCAL-314621) | ✓ live 2026-10-14 — `LAG(…, 2, 0)` and `LEAD(…, 3)` correct |
| Joining two or more model-derived CTEs in the main SELECT · CTE selecting `FROM` an earlier CTE | `QuerySpec` transform failure · GUID mismatch | [SCAL-314708](https://thoughtspot.atlassian.net/browse/SCAL-314708) (26.8.0.cl) | ✓ live 2026-10-14 |
| `CASE` expression in `GROUP BY` | failed | [SCAL-314710](https://thoughtspot.atlassian.net/browse/SCAL-314710) | ✓ live 2026-10-14 |
| String literal containing both `'` and `"` | extra backslashes in the compiled SQL | [SCAL-317434](https://thoughtspot.atlassian.net/browse/SCAL-317434) | ✓ live 2026-10-14 |
| `CAST(<literal> AS <type>)` | rejected as a fabricated column `Constant_<value>` | **no ticket closure** — [SCAL-326946](https://thoughtspot.atlassian.net/browse/SCAL-326946) is still New | ✓ live 2026-10-14 — compiles to `min(CAST('1' AS integer))` and returns 1 |
| Constant-only scalar functions (`EXP(1)`, `CHR(65)`, `SPACE(2)`) | `NO_BASE_TABLES` | not ticketed as fixed ([SCAL-319341](https://thoughtspot.atlassian.net/browse/SCAL-319341) still Open) | ✓ live 2026-10-14 — wrapped in `min(…)` and correct. `LOG(b, x)` still fails — see ❌ |
| `TO_DATE('<literal>')` in a filter | `NO_BASE_TABLES` | — | ✓ live 2026-10-14 — `WHERE d >= TO_DATE('2025-01-01')` returns the same total as the `YEAR(d) >= 2025` control |
| Aggregate over a column a CTE does not otherwise reference (`HAVING COUNT(other_col) > 0`) | `COLUMN_NOT_FOUND` against `wrapper_<model>_<hash>` | — | ✓ live 2026-10-14 — compiles and executes |

**Remaining caveats for set operations:** branch column-type mismatches are still not
caught at compile time (see ⚠️ table above), and an outer aggregation over a set-op CTE
fails (see ❌). On builds older than jul.26.mt expect the previous ORDER BY / LIMIT and
aggregated-branch behaviour.

## Not bugs — feature requests and security behaviour

- Run AgentQL directly on **tables** (not just Models) — [SCAL-319871](https://thoughtspot.atlassian.net/browse/SCAL-319871) (Open)
- Custom-calendar switching in AgentQL — [SCAL-318205](https://thoughtspot.atlassian.net/browse/SCAL-318205) (Open)
- **Security (ticket, not probed):** data returned through AgentQL now honours Column
  Security Rules ([SCAL-315768](https://thoughtspot.atlassian.net/browse/SCAL-315768), fixed
  26.8.0.cl); a report that AgentQL answers were not RLS-protected was closed as an
  incorrect expectation ([SCAL-330036](https://thoughtspot.atlassian.net/browse/SCAL-330036)).

## Maintaining this file

When you re-probe a ❌/⚠️ row and it now works, **move it to ✅** with the date and build,
and relax the matching rule in `agentql-rules.md` / `udf-reference.md` / `patterns.md`, then
bump the currency anchor at the top. When you hit a new failure, check it against
[SCAL-316371](https://thoughtspot.atlassian.net/browse/SCAL-316371) first — it's probably
already logged. To find which rows are worth re-probing, refresh ticket statuses from the
two epics (see `open-items.md` § Refreshing limitations from Jira) — but always confirm with
a live probe, since ticket status and behaviour diverge in both directions (see the note
at the top).
