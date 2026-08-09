# AgentQL limitations — what doesn't work

<!-- currency: spotql — 2026-07 (nebula-damian-alias jul.26.mt dev; epics SCAL-306544 / SCAL-316371 / SCAL-313049) -->

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
  AgentQL Feature Evaluations*. All **Open**: the canonical **known-unsupported** backlog.

Last reconciled: epics + live probe on **nebula-spotQL, 2026-07-07/08**; full re-probe of
every testable row on **nebula-damian-alias (jul.26.mt dev), 2026-07-29** (38-probe sweep,
Snowflake-backed Supplier Model / T1_PUBLISH_MODEL). nebula-spotQL was unreachable that
day, so the 2026-07-29 rows are **single-build findings** — reconfirm on a second build
before treating them as universal. "✓ live" = I ran it; "ticket" = status taken from the
Jira epic, not re-probed.

> **generate-sql SUCCESS ≠ usable.** Some constructs compile (generate-sql SUCCESS) but
> fail at execution or silently return wrong data. For anything risky, check `fetch-data`.

## ❌ Unsupported — hard error (you find out immediately)

| Construct | Failure | Ref |
|---|---|---|
| Self-join of a CTE | `SELF_JOIN` | ✓ live · [SCAL-316389](https://thoughtspot.atlassian.net/browse/SCAL-316389) |
| Non-equi `JOIN … ON` (inequality / constant in ON; between CTEs) | `NON_EQUI_JOIN` | [SCAL-316387](https://thoughtspot.atlassian.net/browse/SCAL-316387), [SCAL-316388](https://thoughtspot.atlassian.net/browse/SCAL-316388) |
| Subquery in `FROM` (derived table) | `TABLE_NOT_FOUND` at compile (was `QUERY_GEN_ERROR` on older builds) | ✓ live 2026-07-29 · [SCAL-319337](https://thoughtspot.atlassian.net/browse/SCAL-319337) |
| `IN (SELECT …)` | **compiles (`generate-sql` SUCCESS) but fails at `fetch-data`** — the subquery's Model name is emitted verbatim into the warehouse SQL, unresolved (*"Object 'X' does not exist"*). Rewrite as a CTE + equi-join (`patterns.md` § Semi-join via CTE — and dedupe the key CTE, or the join fans out) | ✓ live 2026-07-29 · [SCAL-326936](https://thoughtspot.atlassian.net/browse/SCAL-326936), [SCAL-319337](https://thoughtspot.atlassian.net/browse/SCAL-319337) |
| `STDDEV_*` / `VAR_*` on a Model column — **grouped AND scalar** | `UNSUPPORTED_AGGREGATE`. Scalar context worked on earlier builds — **regression on jul.26.mt** ([SCAL-326935](https://thoughtspot.atlassian.net/browse/SCAL-326935)). The CTE workaround still works: materialise the aggregate in a CTE, take the statistic over the CTE column. `MEDIAN` is unaffected (scalar, and now grouped — see ✅) | ✓ live 2026-07-29 · [SCAL-326935](https://thoughtspot.atlassian.net/browse/SCAL-326935) |
| Percentiles other than `MEDIAN` (`PERCENTILE_CONT/DISC`, `APPROX_PERCENTILE`) | `UNSUPPORTED_AGGREGATE` | ✓ live · [SCAL-314707](https://thoughtspot.atlassian.net/browse/SCAL-314707) (closed as MEDIAN-only) |
| `SELECT *` · `COUNT(*)` / `COUNT(1)` | `SELECT_STAR` · `COUNT_STAR` | ✓ live |
| `SUM()` on an aggregate-formula column | `NESTED_AGGREGATE_NOT_SUPPORTED` — use `AGG()` | ✓ live |
| `AGG()` (or a bare reference) to a **semi-additive** measure — outermost op `last_value`/`first_value` with `query_groups()` | `NON_CONVERTIBLE_FUNCTION` ("Non standard sql function QueryGroups") — use `SUM()` instead (identity pass-through over the per-group snapshot). Only when it is the *outermost* op: `sum(last_value(...))` is a normal `AGG()` measure. | ✓ live 2026-07-13 (nebula-aggregate-aware) |
| `moving_sum(group_aggregate(...), …)` at grand-total or grouped by a non-order column | `INVALID_WINDOWING_FUNCTION_ARGUMENTS` — distinct from the semi-additive class; wrapper is still `AGG()` (`SUM()` → NESTED). Needs its order column present; may be a broader `moving_sum`/AgentQL gap (untriaged) | ✓ live 2026-07-13 |
| `ROLLUP` / `CUBE` / `GROUPING SETS` | rejected | [SCAL-319339](https://thoughtspot.atlassian.net/browse/SCAL-319339) |
| Many scalar functions: `INITCAP`, `REGEXP_SUBSTR`, `REGEXP_REPLACE`, `TO_VARCHAR`, bitwise (`BIT_*`), constant-only (`EXP`/`ACOS`/`LOG(b,x)`/`CHR`/`SPACE`/`CURRENT_DATE`/`TO_DATE`), `DAY_OF_YEAR`, `TRUNC(date,part)`, `OVERLAY`/array fns (`CONCAT_WS` now works — see ✅) | rejected / `NO_BASE_TABLES` (`INITCAP`/`REGEXP_SUBSTR`/`TO_VARCHAR`/`CURRENT_DATE` re-verified 2026-07-29; date-arg fns not re-probed — no date column on the CDW test model) | [SCAL-319333–319343](https://thoughtspot.atlassian.net/browse/SCAL-316371) |
| `LTRIM(x, chars)` / `RTRIM(x, chars)` (two-argument form) | compiles, then renders ANSI `trim(leading ' ' from …)`, which Snowflake rejects. The **single-argument** form is correct | ✓ live 2026-08-04 · [SCAL-326943](https://thoughtspot.atlassian.net/browse/SCAL-326943) |
| `CAST(<literal> AS <type>)` | rejected as a fabricated column `Constant_<value>`. Casting a **column** is fine | ✓ live 2026-08-04 · [SCAL-326946](https://thoughtspot.atlassian.net/browse/SCAL-326946) |
| `CAST(<function call> AS <type>)` **in a query block that joins a CTE** | `UNSUPPORTED_EXPRESSION` — *"Failed to traverse CAST source expression"*. The trigger is the **join to a CTE**, not the CTE: the identical expression compiles in a CTE that joins nothing, and fails in either a CTE body or the outer query once one joins a CTE. **The affected set is inconsistent** — `LOWER`, `EXTRACT`, `TRUNC` and `TO_NUMBER` fail; `ABS`, `ROUND`, `MONTH_NUMBER`, arithmetic and bare columns are fine, including `ABS` and `TO_NUMBER` on the *same* column. Workaround: drop the cast where the inner expression already has the target type (`CAST(TRUNC(EXTRACT(…)) AS INTEGER)` → `TRUNC(EXTRACT(…))`), verified to return identical values | ✓ live 2026-08-07 |
| `EXTRACT(DOW …)` | rejected at parse, `DatePart expected`. Exact equivalent: `DAY_IN_WEEK_NUMBER(x) % 7` (Mon=1..Sun=7, so mod 7 gives Sun=0..Sat=6) | ✓ live 2026-08-04 · [SCAL-327864](https://thoughtspot.atlassian.net/browse/SCAL-327864) |
| `EXTRACT(DOY …)` | compiles, then renders `extract(day_of_year from …)`; Snowflake wants `dayofyear`. **Workaround: `DAY_IN_YEAR_NUMBER(x)`**, which returns the true day of year | ✓ live 2026-08-06 · [SCAL-327864](https://thoughtspot.atlassian.net/browse/SCAL-327864) |
| Aggregate over a column the CTE does not otherwise reference (e.g. `HAVING COUNT(other_col) > 0`) | `COLUMN_NOT_FOUND` against `wrapper_<model>_<hash>`. ThoughtSpot materialises a CTE as a wrapper exposing only the columns that CTE mentions, so any other Model column is out of scope inside it. Workaround: use a column the CTE already references | ✓ live 2026-08-06 |
| Variant / semi-structured / JSON (`ARRAY_CONTAINS`, `ARRAY_SIZE`, lateral flatten) | unsupported | [SCAL-316392–316396](https://thoughtspot.atlassian.net/browse/SCAL-316371), [SCAL-318984](https://thoughtspot.atlassian.net/browse/SCAL-318984) |
**Workarounds:** `STDDEV`/`VAR`/percentile → aggregate in a CTE, take the stat in the
outer SELECT (`patterns.md` § Statistics); `MEDIAN` works directly. Membership filters
(`IN (SELECT …)`) → CTE + equi-join (`patterns.md` § Semi-join via CTE). Date math → the
AgentQL UDFs (`udf-reference.md`), not `TRUNC`/`TO_DATE`/`CURRENT_DATE`.

## ⚠️ Silent wrong-answer — avoid (no error, wrong data — the dangerous ones)

| Construct | What actually happens | Ref |
|---|---|---|
| Aggregate condition in `WHERE` (e.g. `WHERE SUM(x) > 0`) | invalid SQL, but silently reinterpreted as `HAVING` — filters post-aggregation, no error. Write `HAVING` explicitly; don't rely on the lenient parse | ✓ live 2026-07-07, re-verified 2026-07-29 |
| **Any dimension-only query on a Model without `join_progressive: true`** | every table in the Model is joined into every query, even one selecting a single dimension column, so results are silently **filtered by the fact table** — members with no fact rows disappear. No error; the row count just looks plausible and is wrong. Anti-join patterns return zero rows. **This is a Model defect, not an AgentQL one** — check `model.properties.join_progressive` via `ts tml export --parse`. UI-built Models set it; hand-authored model TML does not. See `patterns.md` § Dimension-anchored anti-join | ✓ live 2026-08-10 (nebula-damian-alias) — same query, same star: 73 members without it, the true 79 with it |
| Set-operation branches with **mismatched column types** at the same ordinal (e.g. VARCHAR vs DOUBLE) | compiles (`generate-sql` SUCCESS) but fails at `fetch-data` with `QUERY_EXECUTION_FAILED` (e.g. *Numeric value 'United States' is not recognized*) — not caught at compile time | ✓ live 2026-07-07, re-verified 2026-07-29 |
| `QUALIFY …` | clause silently dropped from generated SQL (no `ROW_NUMBER` emitted at all) → you get **all** rows, not the filtered set | ✓ live 2026-07-29 · [SCAL-319330](https://thoughtspot.atlassian.net/browse/SCAL-319330) |
| `FILTER (WHERE …)` on an aggregate | silently dropped → aggregate ignores the filter (returns the unfiltered total) | ✓ live 2026-07-29 · [SCAL-319332](https://thoughtspot.atlassian.net/browse/SCAL-319332) |
| `SUM(CASE WHEN <raw-date '>=' literal> …)` | aggregate returns type-UNKNOWN, all zeros — use integer date-parts inside CASE (not re-probed 2026-07-29 — no date column on the CDW test model) | [SCAL-319329](https://thoughtspot.atlassian.net/browse/SCAL-319329) |
| `DATE_TRUNC(unit, col)` | compiles, then leaks the parser alias, **drops the unit** (`trunc(x, null)`) and **silently drops the `GROUP BY`**, wrapping the date in `min()`. Three failures in one, none of them visible. Use the date-part UDFs in `udf-reference.md` | ✓ live 2026-08-04 · [SCAL-326944](https://thoughtspot.atlassian.net/browse/SCAL-326944) |
| `AVG`/`MIN`/`MAX` on a measure over an **SV or MV backing** | outer aggregate silently dropped — returns the measure's native aggregation (e.g. `AVG` of a `SUM` measure returns the `SUM`). Regular Models hard-error (`NESTED_AGGREGATE_NOT_SUPPORTED`). `MEDIAN`/`STDDEV` fail as nested aggregates on all backings. **Fix:** the CTE statistics pattern — materialise at a grain, apply the statistic in the outer SELECT (`patterns.md` § Statistics). | ✓ live 2026-07-21 · [snowflake-sv-backing.md](snowflake-sv-backing.md) |

> **`LIMIT 100000` is appended to every generated statement**, including statements that
> carry no `LIMIT` of their own (✓ live 2026-08-04). On a large Model a bulk extract is
> silently capped at 100,000 rows with nothing in the response to say so. Whether it is
> configurable is unconfirmed.

> **Diagnostics that name the wrong thing** ([SCAL-326945](https://thoughtspot.atlassian.net/browse/SCAL-326945)):
> a derived table in a `JOIN` reports `Table 't' not found`, where `'t'` is a hardcoded
> placeholder that appears whatever the real alias is; and `GROUP BY 1` reports
> `Missing formula alias: <guid>`, naming neither the construct nor anything the caller
> wrote. Both cost real time to trace back to their cause.

## 🔧 In flight — open bugs (behaviour may change; treat results with care)

| Issue | Status | Ref |
|---|---|---|
| Timestamp (`INT64`) column treated as date without conversion | In Review | [SCAL-317405](https://thoughtspot.atlassian.net/browse/SCAL-317405) |
| Alias not remapped during SQL serialization | In Review | [SCAL-317423](https://thoughtspot.atlassian.net/browse/SCAL-317423) |
| Decimal-precision AgentQL generation | In Review | [SCAL-318288](https://thoughtspot.atlassian.net/browse/SCAL-318288) |
| `Failed to transform QuerySpec: null` on some queries | In Triage | [SCAL-318834](https://thoughtspot.atlassian.net/browse/SCAL-318834) |
| Query with **only** a framed windowing function fails | In Triage | [SCAL-319898](https://thoughtspot.atlassian.net/browse/SCAL-319898) |
| Doubly-complex queries error at `ComplexQueryTransformer` | In Triage | [SCAL-320205](https://thoughtspot.atlassian.net/browse/SCAL-320205) |

## ✅ Fixed — previously broken, now working

| Construct | Previously | Fixed by | Verified |
|---|---|---|---|
| `UNION ALL` / `UNION` / `EXCEPT` / `EXCEPT ALL` / `INTERSECT` / `INTERSECT ALL` at top level | second branch silently dropped | [SCAL-313049](https://thoughtspot.atlassian.net/browse/SCAL-313049) | ✓ live 2026-07-07 (nebula-spotQL) — 2-branch, 3-branch, 5-branch, chained, mixed, with aggregates, window functions, HAVING, multiple measures, arithmetic expressions |
| Set operation **inside a user-defined CTE**, branches without aggregates | previously documented as wholly unsupported — that was too broad | engineering-confirmed; retested after SCAL-313049 | ✓ live 2026-07-08 (nebula-spotQL) — raw-column branches and attribute-only GROUP BY branches both compile (UNION wrapped in its own CTE in generated SQL) and execute; square-bracket identifiers (`[Col]`) also accepted |
| Set operation inside a CTE **with aggregated branches** (`SUM(col) … GROUP BY` in a branch) | `QUERY_GEN_ERROR` (GroupAggregateOptimizationTransformer) | fixed by jul.26.mt | ✓ live 2026-07-29 (nebula-damian-alias, jul.26.mt dev) — compiles (branches materialised from a shared aggregate CTE) and executes with correct values |
| `ORDER BY` on a set-operator result | silently dropped from generated SQL | fixed by jul.26.mt | ✓ live 2026-07-29 (same build) — emitted as `ORDER BY … NULLS LAST` on the combined result; rows verified sorted |
| `LIMIT` on a set-operator result | misplaced into the first branch CTE only | fixed by jul.26.mt | ✓ live 2026-07-29 (same build) — applied to the combined result (`LIMIT 3` → 3 rows) |
| `ROUND(x, N)` | rounded to the nearest **multiple of N** | [SCAL-319323](https://thoughtspot.atlassian.net/browse/SCAL-319323); fixed by jul.26.mt | ✓ live 2026-07-29 (same build) — now rounds to N decimal places (emits `10^-N * round(x / 10^-N)`) |
| `TO_NUMBER(x)` | silently dropped (no-op) | [SCAL-319336](https://thoughtspot.atlassian.net/browse/SCAL-319336); behaviour changed by jul.26.mt | ✓ live 2026-07-29 (same build) — now compiles to `CAST(x AS double)`; hard `QUERY_EXECUTION_FAILED` on non-numeric data. No longer silent, but also not a lenient parse — don't use it on non-numeric columns |
| `CONCAT_WS` | rejected | fixed by jul.26.mt | ✓ live 2026-07-29 (same build) — compiles and executes, incl. in `GROUP BY` |
| `LENGTH()` | listed as forbidden in the early dialect rules | fixed (or never broken on CDW backends) | ✓ live 2026-07-29 (same build) — compiles and executes, incl. `GROUP BY LENGTH(col)` |
| `MEDIAN` in a `GROUP BY` query | grouped statistics rejected (scalar-only) | fixed by jul.26.mt | ✓ live 2026-07-29 (same build) — grouped `MEDIAN` compiles and executes with correct per-group values |

**Remaining caveats for set operations:** branch column-type mismatches are still not
caught at compile time (see ⚠️ table above). The ORDER BY / LIMIT and aggregated-branch
fixes were verified on jul.26.mt only — on older builds expect the previous (silently
wrong / hard-error) behaviour.

## Not bugs — feature requests on the backlog

- Run AgentQL directly on **tables** (not just Models) — [SCAL-319871](https://thoughtspot.atlassian.net/browse/SCAL-319871)
- Custom-calendar switching in AgentQL — [SCAL-318205](https://thoughtspot.atlassian.net/browse/SCAL-318205)

## Maintaining this file

When you re-probe a ❌/⚠️ row and it now works, **remove it** (it's no longer a limitation)
and relax the matching rule in `agentql-rules.md` / `udf-reference.md` / `patterns.md`, then
bump the currency anchor at the top. When you hit a new failure, check it against
[SCAL-316371](https://thoughtspot.atlassian.net/browse/SCAL-316371) first — it's probably
already logged. To find which rows are worth re-probing, refresh ticket statuses from the
two epics (see `open-items.md` § Refreshing limitations from Jira) — but always confirm with
a live probe, since a ticket can be Closed without the behaviour actually changing (e.g.
`PERCENTILE_CONT` is closed as MEDIAN-only yet still errors).
