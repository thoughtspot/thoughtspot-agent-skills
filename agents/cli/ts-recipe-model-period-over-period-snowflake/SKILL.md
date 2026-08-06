---
name: ts-recipe-model-period-over-period-snowflake
description: Adds period-over-period comparison (this week vs the same week last year, this month vs the same month last year) to a ThoughtSpot Model by building role-played date aliases over offset date keys. Use this skill whenever someone wants prior-period, year-over-year, week-over-week, month-over-month, "vs last year", "same period last year", growth, or variance-versus-prior comparisons in a ThoughtSpot Model or a Snowflake Semantic View, or asks how to compare a measure to itself at an earlier date. Analyses the existing model first, creates or augments the date dimension, and verifies the result reconciles.
---

# Period-over-Period for a ThoughtSpot Model

"How did this week compare to the same week last year?" has no native answer in a
ThoughtSpot Model. A measure aggregates the rows in the bucket you grouped by, and the
prior period's rows are in a *different* bucket — so no formula on the measure can reach
them. The shift has to happen in the **join**, not in the aggregate.

This skill builds that join. The result is a plain `SUM` measure that works at every
grain and with every attribute:

```
                    ┌──────────────┐
  DM_ORDER ────────►│              │  joined on DATE_VALUE        → Amount
                    │ DM_DATE_DIM  │
  DM_ORDER_364_     │              │  joined on DATE_364_DAYS_AGO → Amount 364 Days Ago
  DAYS_AGO ────────►└──────────────┘
     (same physical table, second alias)
```

Both aliases point at the *same physical table*. Only the join key differs. Because the
second alias joins the calendar on an offset column, the rows it contributes to week `W`
are the rows from 364 days before `W` — and 364 days is exactly 52 weeks, so the
comparison is day-of-week aligned and one column serves day, week and month roll-ups.

**Why the alias and not a formula?** Three alternatives exist and all are narrower.
`sum_if` cannot do it at date grain at all; a window `LAG` welds the metric to one grain;
a denormalised column forces you to pre-commit to a dimensional grain. Each is the right
answer sometimes — the measured trade-offs are in
[references/alternative-approaches.md](references/alternative-approaches.md). Read it if
the user asks "why not just use a formula?", and note that **on I/O all four approaches
are equivalent** — this is a semantics decision, not a performance one.

Ask one question at a time for **dependent** decisions. Batch **independent** questions
into a single prompt to cut round-trips.

---

## Prerequisites

- ThoughtSpot profile configured — run `/ts-profile-thoughtspot` if not
- `DATAMANAGEMENT` privilege (to import the Model)
- A warehouse profile for the analysis queries — `/ts-profile-snowflake`
- Warehouse write access is **preferred but not required** — Step 4 branches on it

---

## Step 0 — Overview

Display this plan and wait for confirmation before starting.

```
ts-recipe-model-period-over-period-snowflake — add prior-period comparison to a ThoughtSpot Model

  1. Identify the target Model ........................ you choose
  2. Analyse the model ................................ auto
       date dimension present? offset keys present?
       how does the fact reach the calendar?
  3. Choose the comparisons ........................... you choose
       364 days (day + week)  /  12 calendar months
  4. Warehouse write access? .......................... you choose
       A direct DDL   B hand-off script   C prototype only
  5. Create or augment the date dimension ............. auto
  6. Verify the date spine ............................ auto  (orphan gate)
  7. Build the alias nodes and joins .................. auto
  8. Add the prior-period measures .................... auto
  9. Verify against the warehouse ..................... auto  (reconciliation gate)
 10. Report .......................................... auto

Confirmation required: steps 1, 3, 4, and the Step 9 result
```

---

## Step 1 — Identify the target

```bash
ts metadata search --name "%{name}%" --profile {profile}
```

Do **not** pass `--subtype ONE_TO_ONE_LOGICAL` when looking for a Model — Models are
`WORKSHEET`. Filter on `metadata_type` client-side if you need to narrow.

Export it with its tables so Step 2 can read the join graph:

```bash
ts tml export {model_guid} --profile {profile} --fqn --associated --parse
```

---

## Step 2 — Analyse the model

Four questions, answered from the exported TML plus one warehouse query. Report all four
before proposing anything.

### 2a. Is there a date dimension?

Look for a `model_tables` entry whose columns are predominantly dates and which the fact
joins *to* (not from). Three outcomes:

| Finding | Route |
|---|---|
| A date dimension exists | Step 5 augments it |
| No date dimension; the fact carries a raw date column | Step 5 creates one |
| A date dimension exists but the fact joins on a **timestamp** | Fix first — see the trap below |

> **Timestamp-to-date join trap.** If the fact's date column is `TIMESTAMP` and the
> dimension key is `DATE`, the join silently matches only rows landing exactly on
> midnight. Measured on a real model: **830 of 176,264 orders joined** — 0.5%. Every
> date-grouped number was reporting on half a percent of the business, with no error.
> Check it before anything else:
> ```sql
> SELECT COUNT(*) AS total,
>        COUNT(d.DATE_VALUE) AS joined_as_is,
>        (SELECT COUNT(*) FROM {fact} f2 JOIN {dim} d2 ON f2.{col}::DATE = d2.DATE_VALUE) AS joined_if_cast
> FROM {fact} f LEFT JOIN {dim} d ON f.{col} = d.DATE_VALUE;
> ```
> If `joined_as_is` << `joined_if_cast`, add a `::DATE` day key in Step 5 and repoint the join.

### 2b. Does the calendar already carry offset keys?

Look for a column holding a shifted date — `DATE_364_DAYS_AGO`, `PRIOR_YEAR_DATE`, or
similar. Usually absent. If present, verify its **grain matches its offset** (see 2c).

### 2c. What grain is each offset key on?

This is the one that silently corrupts numbers.

> **An offset column must live on a dimension whose grain matches the comparison.**
> A 364-day offset belongs on the day-grain calendar. A 12-**month** offset belongs on a
> **month-grain** dimension, because `START_OF_MONTH_12M_AGO` repeats for every day of the
> month and is therefore not unique. Snowflake accepts `UNIQUE` on it without validating,
> then fans out at query time: measured **14,415 against a true 465 — 31× over**, once per
> day in the month, no error.

So: 364-day offset → day dimension. Calendar-month offset → **a separate month dimension**.

### 2d. How does the fact reach the calendar?

| Topology | Aliases needed per comparison |
|---|---|
| Fact joins the calendar directly | **1** (the fact) |
| Fact reaches it through a header/hub table (`line → order → date`) | **2** (hub + fact) |

The hub case is common: revenue sits on the order *line*, the date sits on the order
*header*. Both must be aliased, because the line alias reaches the calendar only through
an order alias.

---

## Step 3 — Choose the comparisons

```
Which comparisons are needed?

  1  364 days ago   — serves day-over-day AND week-over-week, day-of-week aligned
  2  12 calendar months ago — serves month-over-month and year-over-year by month
  3  Both

(364 days = 52 weeks exactly, so option 1 covers weekly comparison with no
 separate week dimension and no week offset column.)
```

Each comparison costs one offset column plus one alias set. Do not build option 2 unless
calendar-month alignment is genuinely wanted — option 1 already answers "vs last year" at
day and week grain.

---

## Step 4 — Warehouse write access

```
Can you run DDL against the warehouse (CREATE/REPLACE on the reporting schema)?

  A  Yes — I'll create/alter the views directly
  B  No, but I can pass a script to someone who can
  C  No — build a throwaway prototype so I can see the shape first
```

- **A** → Step 5 executes the DDL.
- **B** → Step 5 writes the DDL to a file, prints the hand-off note, and pauses.
- **C** → follow [references/prototype-with-sql-view.md](references/prototype-with-sql-view.md),
  then come back to A or B for the real thing.

> **Route C is a prototype, never production.** A ThoughtSpot SQL View is inlined into the
> generated query as an **unfiltered derived table** — ThoughtSpot cannot parse the inner
> SQL, so it cannot push predicates into it, and it inlines the whole thing **once per
> join role**. It also buries the offset definition inside a BI object where no other
> model or tool can reuse it. The reference file shows the actual generated SQL. Use it to
> demonstrate the shape, then implement in the database.

---

## Step 5 — Create or augment the date dimension

DDL templates: [references/date-dimension-ddl.sql](references/date-dimension-ddl.sql) —
covers creating a calendar from scratch, augmenting an existing one, and the month
dimension. Deploy with `ts snowflake exec` so the SQL is never retyped:

```bash
ts snowflake exec --file {skill_dir}/references/date-dimension-ddl.sql \
  --var target_db={db} --var target_schema={schema} --sf-profile {sf_profile}
```

**Augment additively.** If the dimension is a view other objects already read, keep every
existing column and add the new ones. A dropped or renamed column breaks dependents —
and in ThoughtSpot it is refused outright (see Step 7's rename note).

**Two keys are needed per comparison:**

| Comparison | On the day calendar | On the month dimension |
|---|---|---|
| 364 days | `DATE_364_DAYS_AGO = DATEADD(day, -364, d)` | — |
| 12 months | — | `MONTH_START_12_MONTHS_AGO = ADD_MONTHS(month_start, -12)` |

The fact also needs a key at the matching grain: a `::DATE` day key, and for the
month comparison a `DATE_TRUNC('month', …)::DATE` month key.

---

## Step 6 — Verify the date spine (orphan gate)

> **The calendar must extend 364 days PAST the last fact date** (and the month dimension
> 12 months past the last fact month). The offset join matches a fact on day `D` to the
> calendar row where `DATE_364_DAYS_AGO = D`, i.e. the row for `D + 364`. If that row does
> not exist, the fact orphans into a **NULL bucket**. Measured: a phantom blank week
> carrying **2,089,360**.

```sql
SELECT MIN({date_col}) AS first_fact, MAX({date_col}) AS last_fact FROM {fact};
SELECT MIN(DATE_VALUE) AS spine_start, MAX(DATE_VALUE) AS spine_end FROM {date_dim};
-- spine_end must be >= last_fact + 364
```

Extend the calendar if it falls short. Then confirm zero orphans:

```sql
SELECT COUNT(*) AS orphaned_fact_rows
FROM {fact} f LEFT JOIN {date_dim} d ON f.{day_key} = d.DATE_364_DAYS_AGO
WHERE d.DATE_364_DAYS_AGO IS NULL AND f.{day_key} <= (SELECT MAX(DATE_VALUE) - 364 FROM {date_dim});
-- expect 0
```

---

## Step 7 — Build the alias nodes and joins

### Naming convention

**Alias = the fact table plus the literal offset, spelled the same as the dimension key
it joins.** The join then reads coherently and cannot lie about what it does:

```
DM_ORDER_364_DAYS_AGO   →  DM_DATE_DIM.DATE_364_DAYS_AGO
DM_ORDER_12_MONTHS_AGO  →  DM_MONTH.MONTH_START_12_MONTHS_AGO
```

Avoid `_LY` / `_PY`. They are one character apart, both gloss as "last year", and `_LY` is
factually wrong on a 364-day offset — 364 days is not a year. Aliases are developer-facing
(they prefix every `column_id`), so precision beats brevity. Business language belongs in
the measure's **display name**, which is what an end user actually sees.

### Alias shape

```yaml
- name: DM_ORDER                      # the PHYSICAL table
  alias: DM_ORDER_364_DAYS_AGO        # unique per-role node id
  fqn: {same GUID as the base node}
  joins:
  - name: DM_ORDER_364_DAYS_AGO_TO_DM_DATE_DIM
    with: DM_DATE_DIM                 # the ALIAS (or base name) of the target
    'on': '[DM_ORDER::DM_ORDER_ORDER_DAY] = [DM_DATE_DIM::DATE_364_DAYS_AGO]'
    type: LEFT_OUTER                  # type AND cardinality are both required
    cardinality: MANY_TO_ONE
```

Four rules, each of which will otherwise cost an import cycle:

1. `with:` carries the **alias**; the `on:` clause uses **physical** table names on both sides.
2. `type` and `cardinality` must both be present — ThoughtSpot rejects one without the other.
3. An alias node shares the base table's `fqn`. It needs no separate Table TML — an alias is
   a second reference to the same Table object.
4. **Give each alias exactly one calendar join.** A month-role alias must join the month
   dimension *only*. Adding a day-calendar join too creates a second path to the month
   dimension and the query fails.

> **Do not duplicate the same ordered table pair on one node.** `ts tml lint` invariant
> **I14** rejects it, and without an alias the Model **will not load at all** — the join
> path is ambiguous and there is no "pick one" fallback.

### Trim the alias column set

Copy only the join keys and any grouping columns genuinely wanted for the prior period.
A naive full copy adds hundreds of near-duplicate columns and degrades NL search more than
it helps. Set each alias's join key to `index_type: DONT_INDEX`.

### Renaming a key on a live Model

A column rename is delete + add, and ThoughtSpot refuses it while a Model depends on the
column:

```
Deleted columns have dependents. — DATE_364_AGO
```

The sequence is **add the new column alongside the old → rebuild the Model on the new
name → drop the old column**. Three round trips. It fails safely rather than breaking the
join, but plan for it.

---

## Step 8 — Add the prior-period measures

Plain aggregates over the alias. No formula, no window, no condition:

```yaml
- name: Amount 364 Days Ago
  column_id: DM_ORDER_DETAIL_364_DAYS_AGO::LINE_TOTAL
  properties: { column_type: MEASURE, aggregation: SUM }
```

Give each a display name a user can read while browsing, and synonyms for search:

| Measure | Display name | Synonyms |
|---|---|---|
| 364-day offset | `Amount 364 Days Ago` | `same week last year`, `prior period revenue` |
| 12-month offset | `Amount 12 Months Ago` | `same month last year`, `vs last year` |

**Growth ratios.** In ThoughtSpot add a formula column, `[Amount] / [Amount 364 Days Ago]`.
In a Snowflake Semantic View this must be an **unqualified derived metric** —
`GROWTH AS f.AMOUNT / f_prior.AMOUNT_364_DAYS_AGO` with no table prefix on the left. A
metric qualified on a table may only reference metrics on *directly related* entities
(`010211`), and the two aliases are not related to each other. Note `DIV0()` is rejected in
a derived metric (`010271`) — use plain `/` and guard zero denominators in the data.

---

## Step 9 — Verify against the warehouse (reconciliation gate)

Structure can be perfect and the numbers still wrong. Run both checks and show the user
the output before declaring success.

**Check 1 — grand-total reconciliation.** Every additive prior-period measure must sum to
the *same* grand total as its base measure, because it is the same fact rows viewed
through a shifted key. A mismatch means orphaned rows or fan-out.

```bash
ts spotql fetch-data 'SELECT SUM("Amount") a, SUM("Amount 364 Days Ago") b FROM "{model}" AS "t1"' \
  -m {model_guid} --profile {profile}
# a and b must be IDENTICAL
```

**Check 2 — spot-check one period against hand-written SQL.** Pick a period in the middle
of the data and compare to the warehouse directly:

```sql
SELECT d.START_OF_WEEK, SUM(f.{measure})
FROM {fact} f JOIN {date_dim} d ON f.{day_key} = d.DATE_364_DAYS_AGO
WHERE d.START_OF_WEEK = '{week}' GROUP BY 1;
```

If Check 1 passes but Check 2 fails, the offset key is wrong. If Check 1 fails, look for
orphans (Step 6) or a grain mismatch (Step 2c).

---

## Step 10 — Report

```
Period-over-period added to {model_name}

  Comparisons      364 days ago (day + week) | 12 calendar months ago
  Alias nodes      DM_ORDER_364_DAYS_AGO, DM_ORDER_DETAIL_364_DAYS_AGO, …
  New measures     Amount 364 Days Ago, Amount 12 Months Ago
  Warehouse        {created|augmented} {date_dim}{, DM_MONTH}

  Verification
    grand-total reconciliation   PASS  594,188,083.19 = 594,188,083.19
    spot check 2019-06-03        PASS  383,117.11 = 383,117.11
    orphaned fact rows           0

  Not carried over
    {anything the user should know — e.g. growth ratios needing a formula column}
```

---

## Error Handling

| Symptom | Cause | Fix |
|---|---|---|
| Model will not load | Same table pair joined twice without an alias | Add an alias node per role (Step 7) |
| `010246 Multi-path relationship` | An alias has two routes to one dimension | Give each alias exactly one calendar join |
| Prior-period total ≠ base total | Orphaned facts | Extend the spine 364 days past the last fact (Step 6) |
| Prior period is a clean multiple too high (e.g. 31×) | Offset key on the wrong grain | Move a month offset to a month dimension (Step 2c) |
| A blank/NULL bucket with a large value | Same orphan cause | Step 6 |
| Date numbers cover a tiny fraction of the data | Timestamp joined to a date key | Add a `::DATE` day key (Step 2a) |
| `Deleted columns have dependents` | Renaming a key a Model uses | Add new → repoint → drop old (Step 7) |
| `010211 metric from an unrelated entity` | Qualified SV ratio across two facts | Make it an unqualified derived metric (Step 8) |
| `010271 Unsupported expression in derived metric` | `DIV0()` in a derived metric | Use plain `/` (Step 8) |
| `010277 Required dimensions … must also be requested` | A window `LAG` metric, not this recipe | See alternative-approaches.md |

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-08-06 | Initial release. Alias-join recipe with model analysis, warehouse-access branching, and the two verification gates. All behaviours live-verified on Snowflake (`thoughtspot_partner.ap-southeast-2`) and ThoughtSpot (`nebula-damian-alias`): the 31× month-grain fan-out, the 2,089,360 NULL orphan bucket, the 830/176,264 timestamp-join loss, `sum_if` invariance, window-`LAG` grain lock (`010277`), the denormalised-column `FULL OUTER` requirement, derived-metric grammar (`010211`/`010271`), and the four-way I/O parity benchmark on a 100M-row clustered fact. |
