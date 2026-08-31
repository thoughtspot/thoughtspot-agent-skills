# OSSIE mapping — consolidation pass, full report

**Date:** 2026-07-30 · **Branch:** `feat/ossie-consolidation` (from `main` @ `d88bdc5`)
**Instance:** `se-thoughtspot` (`https://se-thoughtspot-cloud.thoughtspot.cloud`)
**Probe method:** BL-170 / G7-G13 harness — `ts tml import --file X --profile se-thoughtspot
--policy VALIDATE_ONLY`, one variable per probe, verbatim responses recorded.
**Substrate:** Payroll Test Model `acf62370-9744-4178-a7c5-1b3ba35dc930` and its tables
`PAYROLL_LOCATIONS` `d58dff50-…` / `PAYROLL_COMPANIES` `b4a638c9-…`.
**Nothing posted to apache/ossie** (legal hold). Nothing created, modified or deleted on the
instance — see §5.

---

## 1. Headline

| Work item | Outcome |
|---|---|
| **A — aggregation semantics** | Applied, all four consequences. The universal claim "`aggregation` on a formula column is ignored at query time" was **wrong** and is now split scalar-vs-aggregate, attributed *per ThoughtSpot domain review, 2026-07-30*. Knock-on: gaps **G11** lost one of its four items; rule **R4** lost one of its three reasons; the TPC-DS fidelity report's "benign" note was re-justified on narrower grounds. |
| **B — window rework** | **52 live probes.** The user's ruling was upheld and, crucially, **proven by rejection** rather than accepted on authority. **Four rows flipped `direct` → `passthrough`** (`LAG`, `LEAD`, the `OVER` clause, window aggregation). Split `112`/`33`/`1` (77%) → **`108`/`37`/`1` (74%)**. New rule **E13**, new gap **G15** (High). The user's stated exception held: `first_value` / `last_value` **do** take an explicit partition — verified, including a multi-column one — and stay `direct`. |
| **C — census routing** | 18 schema-reference changes across four TML refs; 13 construct-mapping changes; one **HIGH** correction (the View reference's central column-reference field was the wrong one). **3 BL entries touched:** BL-189 and BL-190 filed, BL-186 substantially advanced. C4 resolved *against* widening the enum — the wide vocabulary is View-only, evidenced. |
| **D — sweep** | 5 contradicted claims found and fixed outside the primary targets, including one in a *live conversion mapping* (`ts-snowflake-formula-translation.md`) that presented a lossy approximation as an equivalence. |
| Gates | 347 validator tests pass; full `check_*.py` sweep clean; 101 anchor links verified, 0 broken; coverage-summary arithmetic re-derived from the table rows and cross-checked against the actual row classifications. |

---

## 2. Work item A — aggregation-on-formula-column semantics

### 2.1 The correction

| `expr` shape | Example | Does `columns[].properties.aggregation` apply? |
|---|---|---|
| **Scalar** (row-level) | `[FACT::AMOUNT] - [FACT::COST]` | **Yes** — evaluated per row, then rolled up by the declared aggregation, exactly like a physical fact column with a default aggregation |
| **Aggregate** | `sum ( [FACT::AMOUNT] - [FACT::COST] )` | **No** — a no-op |

The previous text stated the no-op case **universally**, which made a load-bearing property look
inert. Attribution recorded as *per ThoughtSpot domain review, 2026-07-30* at every site.

**Evidence class, stated explicitly at every site.** This is a **query-time** semantic, so
`VALIDATE_ONLY` cannot probe it — both shapes import clean with any `aggregation:` value. I
verified only that much (probe `W0_control_sum`, accepted). The scalar/aggregate distinction rests
on domain review, not on a probe, and closing it empirically needs a query-result comparison
against live data. This is now written into the schema reference as a bounded-evidence note rather
than left as an implicit claim.

### 2.2 The four consequences, as applied

| # | Required | Where applied |
|---|---|---|
| (a) | Split the claim in `thoughtspot-model-tml.md` with attribution + the VALIDATE_ONLY caveat | Replaced the flat paragraph with a two-row table, two generator rules, and an explicit *Evidence class* block. Adds the practical consequence the old text obscured: **a scalar ratio must not carry `SUM`**, because the sum of per-row ratios is not the ratio of the sums |
| (b) | Same split on the construct mapping's metric `aggregation` row **and** rule **R4(c)** | Metric row rewritten; **R4** now rests on (a) and (b) alone, and (c) is retained as a *corrected note* precisely because the wrong version of it is quoted downstream in **G11** |
| (c) | Record the scalar-formula + column-aggregation emission as a Phase-3 design option | New rule **R4-P3** with a two-pattern trade-off table. Pattern B is more idiomatic and **reusable at row grain**; its cost is a round-trip subtlety. Scoped honestly: B is only available for a single outer aggregate over an otherwise-scalar expression — `SUM(a - b)` qualifies, `SUM(a) / SUM(b)` does not |
| (d) | `TML → Ossie` must compose scalar formula + column aggregation into `AGG(scalar_expr)` | The metric row previously described this composition for `column_id` entries only. It now states it for the formula case: a scalar formula column carrying `aggregation: AVERAGE` becomes `AVG(<translated scalar expr>)`, not the bare scalar. Backed structurally — the payload `shape` enum gained `scalar_formula_plus_aggregation`, without which a round trip collapses pattern B to `formula` and **silently loses the aggregate** |

### 2.3 Knock-on corrections (not in the brief, required by consistency)

- **`ts-ossie-compliance-gaps.md` G11** — "**Four** documented silent-failure behaviours" → **three**,
  with the withdrawn item explained. A legitimate idiom had been filed as a product defect.
- **`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`** — its "both are benign" note cited the
  universal claim. **The verdict survives but the reasoning did not:** I checked all five emitted
  exprs and every one is an aggregate expr (including both ratios — `sum ( … ) / unique count ( … )`
  and `safe_divide ( sum ( … ) , sum ( … ) )`), so the stamped `SUM` is genuinely inert *in those
  five cases*. Note now says so, and adds that a scalar `expr` would **not** have been benign.
- **`agents/databricks/shared/schemas/thoughtspot-model-tml.md`** carries the same wrong sentence
  but is **gitignored and generated** (`.gitignore:63`) — verified untracked, so it regenerates from
  `agents/shared/`. No edit needed; recorded so a reader does not think it was missed.

---

## 3. Work item B — window-function rework

### 3.1 Probe design, and why this evidence is decisive

Per BL-187's silent-unknown-key trap, the surface was chosen before probing. Unknown **keys** on a
Model `columns[]` entry are silently ignored, so acceptance there proves nothing. A formula
**`expr` body is parsed**, so acceptance *and* rejection both carry information. Proven in-run by
**8 negative controls, all rejected**: `rank_over` (invented), `dense_rank`, `row_number`, `lag`,
`nth_value`, `moving_count`, `moving_stddev`, `cumulative_count`.

Two rejection *classes* appeared, and the stricter one is what carries the reclassification:

| Class | Example | Reading |
|---|---|---|
| `Search did not find "…"` | `Search did not find "{"` | The token/function is not in the grammar at that position |
| **Arity/type error** | `Function rank expects only 2 arguments.` | The function is known and the **signature is enforced** — the strongest form of evidence available without a round trip |

**52 probes: 31 accepted, 21 rejected** (13 not-found, 8 arity/type).

### 3.2 The finding, in one line each

1. **`moving_*` / `cumulative_*` have no partition slot.** A 5th `{ [attr] }` or `query_groups ( )`
   argument to `moving_sum`, and a 3rd to `cumulative_sum`, are both rejected. The trailing
   arguments are **order** columns (bare refs, and more than one is accepted).
2. **`rank` / `rank_percentile` are arity-locked at two.** Any third argument, in any of three
   spellings, is rejected with `Function rank expects only 2 arguments`. The first argument **must**
   be aggregated, and **may not** be a `group_aggregate` — so the partition cannot be smuggled in
   through the measure either. This settles queue item 2c: **the `rank ( agg ( [m] ) , 'desc' )`
   composition row is CONFIRMED**, and its stated boundary is now proven rather than asserted.
3. **`first_value` / `last_value` are the exception — the user's stated exception held.** The
   partition argument accepts `query_groups ( )`, a fixed `{ [attr] }`, a **multi-column**
   `{ [a] , [b] }`, `{ }`, and `query_groups ( ) - { [attr] }`. The axis slot is typed and enforced
   (`Function last_value expects 3rd argument to be List`). All four spellings share the shape.
4. **Consequence for classification.** For `moving_*` / `cumulative_*` there is **no** `OVER` shape
   a native formula reproduces independently of the search — not even an unpartitioned one, because
   ThoughtSpot's partition is never empty, it is populated from the query. That is why those rows
   became `passthrough` rather than `direct`-with-a-caveat.

### 3.3 Two acceptances that prove less than they look (recorded so nobody over-reads them)

- `rank ( sum ( [m] ) , 'descending' )` — **accepted.** The direction string is not validated at
  import. Same trap class as the `'%Y'` format-pattern acceptance in the 2026-07-29 pass.
- `last_value ( … , … , { [a VARCHAR column] } )` — **accepted.** The axis column's type is not
  validated at import, so acceptance does not establish the axis is temporal.

Both are written into the docs beside the rows they qualify.

### 3.4 Reclassification, row by row

| Row | Before | After | Why |
|---|---|---|---|
| `LAG(...) OVER (...)` | direct | **passthrough** | `moving_sum` idiom is real and validates, but matches no `OVER` shape (E13). Native form retained as a **documented downgrade**; the `default` argument is a second reason it is one |
| `LEAD(...) OVER (...)` | direct | **passthrough** | Mirror of `LAG` |
| `OVER (PARTITION BY … ORDER BY …)` | direct | **passthrough** | The old "clean structural rewrite" claim holds for `PARTITION BY` **alone** (→ `group_aggregate`, still lossless) and breaks as soon as an `ORDER BY` is present, which is most window use |
| Window aggregation `AGG(x) OVER (…)` | direct | **passthrough** | Inherits the `OVER` problem. Also narrowed: `moving_count` / `moving_stddev` / `cumulative_count` proven absent, so a windowed `COUNT`/`STDDEV`/`VARIANCE` has no ordered form at all |
| `RANK()` | direct | **direct** (kept) | Boundary now proven by rejection, not asserted. Two new evidenced restrictions added (aggregated-first-arg; no `group_aggregate`) plus the query-context caveat and the unvalidated-direction caveat |
| `PERCENT_RANK()` | direct | **direct** (kept) | Same arity proof for `rank_percentile` |
| `FIRST_VALUE` / `LAST_VALUE` | direct | **direct** (kept) | The section's exception, now evidenced — explicit partition **and** explicit axis |
| Frame clause | direct | **direct** (kept) | **Deliberately scoped to the frame boundaries only**, so the partition loss is counted **once** (on the `OVER` row) and not twice. All four boundary shapes live-confirmed |
| `ROW_NUMBER` / `DENSE_RANK` / `NTILE` / `CUME_DIST` / `NTH_VALUE` | passthrough | passthrough | Unchanged; three of them now *evidenced* absent rather than assumed |

**Note on `DENSE_RANK`:** queue item 2c flagged that the internal Tableau mapping uses a SQL
pass-through for it, implying native rank composition might not exist. Resolved: the two references
**agree, and for the right reason** — `rank` composition exists, `dense_rank` does not.

### 3.5 Derived numbers — every one re-checked

Coverage summary: Window `14 | 9 | 5 | 0` → **`14 | 5 | 9 | 0`**; Total `146 | 112 | 33 | 1` →
**`146 | 108 | 37 | 1`**; **77% → 74%**. Arithmetic re-derived programmatically from the table rows
*and* cross-checked against the actual per-row classifications in the section body (5 direct / 9
passthrough / 14 rows — matches).

Every dependent figure was grepped and updated:

| Site | Change |
|---|---|
| function-mapping coverage summary + prose | `112`/`33`, 77% → `108`/`37`, 74%; the `passthrough` concentration list gained a fifth entry (windowing with a declared partition); new revision note |
| function-mapping header | rules `E1–E12` → **`E1–E13`** |
| construct-mapping `expression.dialects[]` row | "112 are `direct` … 33 are `passthrough`" → 108 / 37 |
| gaps doc *Sources* row | "33 `passthrough` rows … **E1–E12**" → 37 … **E1–E13** |
| gaps **G4** | "11 of the 33 total" → "11 of the 37"; largest-win claim qualified (*by function count*; G15 is larger *by consequence*) |
| gaps **G12** | Recomputed the three-way split: **11** G4 strings + **9** G15 window + **17** tail = 37; "77% (112 of 146)" → "74% (108 of 146)" |

Two `112`/`33`/`77%` mentions deliberately **remain** — both are historical ("the split was X
before"), which is correct.

### 3.6 A10 and the gaps doc

- **A10** rewritten with **both-directions** evidence: `Ossie → TS` (declared `PARTITION BY` has no
  target — proven by rejection) and `TS → Ossie` (dynamic partition inexpressible — and
  `query_groups ( ) ± { attr }` live-confirmed *valid*, so the lost construct is real, not
  hypothetical). Adds the `first_value` existence proof: the concept **fits** ThoughtSpot's formula
  grammar, which makes the ask cheap. Status line in the gaps doc updated to match.
- **New gap G15** (High) — "a window formula cannot declare its own `PARTITION BY`". Positioned
  against G4: G4 is the largest expression-layer gap *by function count*, G15 *by consequence*.
- **G6** (semi-additive) **narrowed** — the *window* half of `first_value`/`last_value` is fine and
  round-trips; only the **roll-up declaration** is missing. Previously conflated.
- Gaps-doc intro corrected: the table claimed "Ordered by priority" but has been in allocation
  order since G7's demotion. Now says so, and the lesson list grew to three (adding: a query-time
  semantic cannot be probed by import validation at all).

### 3.7 Reconciliation with `thoughtspot-formula-patterns.md`

The window section gained a leading platform-fact block (no partition slot, with the verbatim
rejections), a rank-signature table (four constraints, each proven), a semi-additive
partition-grouping table (five accepted forms + the List-type enforcement), the seven
proven-absent functions, and both non-validation caveats. The *Prefer native functions* guidance
gained the operative qualifier — "covers the use case" now has a stated meaning, and the native
`moving_sum` is named as a **documented downgrade** rather than a silent substitution. Currency
anchor bumped.

---

## 4. Verbatim probe transcripts (all 52, in run order)

Base document = the exported Payroll Test Model plus exactly **one** new `formulas[]` entry and its
matching `columns[]` entry. `WPROBE ` prefix on every probe name.

| # | Probe | `expr` (verbatim) | exit | Status | Verbatim response / `error_message` |
|---|---|---|:-:|---|---|
| 1 | `W0_control_sum` | `sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] )` | 0 | OK | `{"columns_added": 1}` |
| 2 | `W0b_negctl_bogus_fn` | `rank_over ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'desc' )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W0b_negctl_bogus_fn, Error: Search did not find "rank_over ( sum (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 3 | `W1_rank_agg_desc` | `rank ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'desc' )` | 0 | OK | `{"columns_added": 1}` |
| 4 | `W2_rank_percentile_agg_asc` | `rank_percentile ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'asc' )` | 0 | OK | `{"columns_added": 1}` |
| 5 | `W3_rank_no_direction` | `rank ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W3_rank_no_direction, Error: Function rank expects 2 arguments, found 1.` |
| 6 | `W4_rank_bare_column` | `rank ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 'desc' )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W4_rank_bare_column, Error: Function rank expects 1st argument to be aggregated.` |
| 7 | `W5_rank_explicit_partition_attr` | `rank ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'desc' , [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W5_rank_explicit_partition_attr, Error: Function rank expects only 2 arguments.` |
| 8 | `W6_rank_explicit_partition_braces` | `rank ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'desc' , { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W6_rank_explicit_partition_braces, Error: Function rank expects only 2 arguments.` |
| 9 | `W7_rank_query_groups_partition` | `rank ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'desc' , query_groups ( ) )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W7_rank_query_groups_partition, Error: Function rank expects only 2 arguments.` |
| 10 | `W8_dense_rank_native` | `dense_rank ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'desc' )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W8_dense_rank_native, Error: Search did not find "dense_rank ( sum (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 11 | `W9_row_number_native` | `row_number ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'desc' )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W9_row_number_native, Error: Search did not find "row_number ( sum (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 12 | `M1_moving_sum_trailing` | `moving_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 2 , 0 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 13 | `M2_moving_sum_lag1` | `moving_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 1 , -1 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 14 | `M3_moving_sum_lead1` | `moving_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , -1 , 1 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 15 | `M4_moving_average` | `moving_average ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 2 , 0 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 16 | `M5_cumulative_sum` | `cumulative_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 17 | `M6_cumulative_average` | `cumulative_average ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 18 | `M7_moving_sum_group_aggregate_arg` | `moving_sum ( group_aggregate ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_ID] } , query_filters ( ) ) , 1 , -1 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 19 | `M8_negctl_raw_agg_in_moving_sum` | `moving_sum ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 1 , -1 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M8_negctl_raw_agg_in_moving_sum, Error: Search did not find "sum (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 20 | `M9_moving_sum_two_trailing_attrs` | `moving_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 1 , -1 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] , [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] )` | 0 | OK | `{"columns_added": 1}` |
| 21 | `M10_moving_sum_partition_braces_5th` | `moving_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 1 , -1 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] , { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M10_moving_sum_partition_braces_5th, Error: Search did not find "{" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 22 | `M11_moving_sum_query_groups_5th` | `moving_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 1 , -1 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] , query_groups ( ) )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M11_moving_sum_query_groups_5th, Error: Search did not find "query_groups ( ) )" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 23 | `M12_cumulative_sum_partition_braces` | `cumulative_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] , { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M12_cumulative_sum_partition_braces, Error: Search did not find "{" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 24 | `M13_cumulative_sum_two_attrs` | `cumulative_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] , [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] )` | 0 | OK | `{"columns_added": 1}` |
| 25 | `M14_negctl_lag_native` | `lag ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 1 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M14_negctl_lag_native, Error: Search did not find "lag (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 26 | `M15_negctl_moving_count` | `moving_count ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 2 , 0 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M15_negctl_moving_count, Error: Search did not find "moving_count (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 27 | `F1_last_value_query_groups` | `last_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 28 | `F2_first_value_query_groups` | `first_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 29 | `F3_last_value_explicit_fixed_partition` | `last_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 30 | `F4_first_value_explicit_fixed_partition` | `first_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 31 | `F5_last_value_empty_partition` | `last_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , { } , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 32 | `F6_last_value_query_groups_minus` | `last_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) - { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 33 | `F7_last_value_in_period` | `last_value_in_period ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 34 | `F8_first_value_in_period` | `first_value_in_period ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 35 | `F9_negctl_nth_value` | `nth_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 2 , query_groups ( ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE F9_negctl_nth_value, Error: Search did not find "nth_value ( sum (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 36 | `F10_last_value_nondate_axis` | `last_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) , { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } )` | 0 | OK | `{"columns_added": 1}` |
| 37 | `G1_group_aggregate_query_groups_minus` | `group_aggregate ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) - { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } , query_filters ( ) )` | 0 | OK | `{"columns_added": 1}` |
| 38 | `G2_group_aggregate_query_groups_plus` | `group_aggregate ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) + { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } , query_filters ( ) )` | 0 | OK | `{"columns_added": 1}` |
| 39 | `W10_rank_group_aggregate_first_arg` | `rank ( group_aggregate ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] } , query_filters ( ) ) , 'desc' )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W10_rank_group_aggregate_first_arg, Error: Search did not find "group_aggregate ( sum (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 40 | `W11_rank_asc_direction` | `rank ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'asc' )` | 0 | OK | `{"columns_added": 1}` |
| 41 | `W12_rank_bogus_direction` | `rank ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'descending' )` | 0 | OK | `{"columns_added": 1}` |
| 42 | `W13_rank_percentile_arity3` | `rank_percentile ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , 'asc' , [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE W13_rank_percentile_arity3, Error: Function rank_percentile expects only 2 arguments.` |
| 43 | `F11_last_value_multi_col_partition` | `last_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , { [PAYROLL_COMPANIES::COMPANY_PAYROLL_STATUS] , [PAYROLL_COMPANIES::COMPANY_COUNTRY] } , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] } )` | 0 | OK | `{"columns_added": 1}` |
| 44 | `F12_last_value_two_axis_cols` | `last_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] , [PAYROLL_COMPANIES::FIRST_SUCCESSFUL_PAYROLL_PAYDAY] } )` | 0 | OK | `{"columns_added": 1}` |
| 45 | `F13_last_value_bare_axis_no_braces` | `last_value ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE F13_last_value_bare_axis_no_braces, Error: Function last_value expects 3rd argument to be List.` |
| 46 | `M16_cumulative_sum_group_aggregate_arg` | `cumulative_sum ( group_aggregate ( sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , { [PAYROLL_COMPANIES::PAYROLL_COMPANY_ID] } , query_filters ( ) ) , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 47 | `M17_moving_sum_arity_2` | `moving_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M17_moving_sum_arity_2, Error: Function moving_sum expects 2nd argument to be Numeric.` |
| 48 | `M18_moving_max_min` | `moving_max ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 2 , 0 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 0 | OK | `{"columns_added": 1}` |
| 49 | `M19_negctl_moving_stddev` | `moving_stddev ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , 2 , 0 , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M19_negctl_moving_stddev, Error: Search did not find "moving_stddev (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 50 | `M20_negctl_cumulative_count` | `cumulative_count ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] , [PAYROLL_COMPANIES::PAYROLL_COMPANY_CREATED_AT] )` | 1 | **ERROR** | `Formula addition failed. Formula: WPROBE M20_negctl_cumulative_count, Error: Search did not find "cumulative_count (" in your data or metadata. Expecting one of the valid keywords, such as, "(", "-", "abs" etc..` |
| 51 | `M21_cumulative_sum_one_arg_group_aggregate` | `cumulative_sum ( group_aggregate ( max ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] ) , query_groups ( ) , query_filters ( ) ) )` | 0 | OK | `{"columns_added": 1}` |
| 52 | `M22_cumulative_sum_one_arg_bare` | `cumulative_sum ( [PAYROLL_COMPANIES::FAILED_PAYROLLS] )` | 0 | OK | `{"columns_added": 1}` |

Representative full response body (probe 1, `W0_control_sum` — every accepted probe returned the
same envelope, differing only in `modified`):

```json
[{"response": {"header": {"author_name": "damian.waldron@thoughtspot.com", "author_guid": "f7d116f1-5b6f-4113-9226-c84236bb015a", "created": 1783679059271, "metadata_type": "LOGICAL_TABLE", "owner_guid": "acf62370-9744-4178-a7c5-1b3ba35dc930", "worksheet_version": "V2", "description": "", "type": "WORKSHEET", "id_guid": "acf62370-9744-4178-a7c5-1b3ba35dc930", "is_versioning_enabled": false, "name": "Payroll Test Model", "modified_by": "f7d116f1-5b6f-4113-9226-c84236bb015a", "objId": "PayrollTestModel-acf62370", "modified": 1785383678997, "author_display_name": "Damian Waldron"}, "diff": {"columns_added": 1}, "status": {"status_code": "OK"}}, "request_index": 0}]
```

Artifacts (persist, nothing deleted):
`…/scratchpad/window-probes/` — `probe.py`, `probe2.py`, `probe3.py`, `payroll-model.json`
(pre-probe baseline), `payroll-after.json` / `payroll-final.json` (post-run comparisons),
`results.json` / `results2.json` / `results3.json`, `full-log.txt` / `full-log2.txt`, and the 52
per-probe `probe_*.json` documents submitted.

---

## 5. Cleanup confirmation — zero persistence

Run after **all 52** probes:

```
ts metadata search --name "%WPROBE%" --profile se-thoughtspot   ->  []
Payroll Test Model edoc identical to pre-probe export:  True
  formulas 9 (unchanged) | columns 8 (unchanged)
  'WPROBE' present anywhere in the document:  False
PAYROLL_LOCATIONS has joins_with:  False   (unchanged — no probe touched it)
```

Confirmed twice: once after wave 1+2 (probes 1–50) and again after wave 3 (probes 51–52).
**No objects created, no objects modified, nothing left behind.** Every call used
`--policy VALIDATE_ONLY`; the only non-probe calls were `ts tml export` and
`ts metadata search`, both read-only.

---

## 6. Work item C — census routing, per-item disposition

### 6.1 C1 — `thoughtspot-view-tml.md`: `search_output_column` vs `column_id` (**HIGH**)

Applied, and it is the largest single correction in the pass. A correction banner at the top of the
file carries the evidence table (265/265 vs **0**; three keys ever emitted:
`name`, `search_output_column`, `properties`) plus the **single-cluster caveat the census itself
states**, verbatim in substance: 42 Views on one SE demo cluster is decisive for *this* build, not
proven universal, so **generate `search_output_column` and tolerate `column_id` on input** rather
than assuming the census was wrong. Census follow-up **T3** is **folded into BL-190's scope** on
review (it was unrouted when this report was first written).

I went past the report to characterise the field, because "not `column_id`" was not enough to
generate correctly. From the 500-document corpus:

- `search_output_column` is the column's label **in the View's own `search_query` output**,
  including the aggregation or bucket prefix — `name: LINEAMOUNT` / `search_output_column:
  Total LINEAMOUNT`; `name: YM` / `Month(YM)`; `name: row_count` / `Average num_rows`. Equal to
  `name` in **256 of 265**; where it differs, the difference is exactly that prefix.
- It contains `::` in **0 of 265** — so it is not a table-path reference in any case.
- A **formula** column is referenced by `formulas[].name`, **not** `formulas[].id`.

All four keying-off sites were corrected, not just the field row: the YAML example, the Field
Reference, *Dependency Management Notes* (both the remove and rename flows, now noting the match is
a **label** match that must tolerate a prefix), and the *Self-validation Checklist*. Also added: the
`view.search_query` row now records that it is where a View's **semantics** live (42/42) — the
practical reason `view_columns[]` alone is insufficient.

Nine more census findings folded into the same file: the seven properties actually emitted (with
the never-emitted ones demoted to *unverified* rather than left as documented), `value_casing`,
`format_pattern`, `currency_type.iso_code`, `formulas[].was_auto_generated` (46/46),
`joins[].id`, the `geo_config.region_name` **dict** correction, and the wider `aggregation`
vocabulary. Currency anchor bumped.

> ### ⚠️ Correction — my "no code depends on the old field" claim was FALSE
>
> This section originally read: *"Verified no code depends on the old field: grepped `view_columns`
> across `agents/`, `tools/`, `docs/` — the only reader is `agents/shared/erd/parser.py`, which
> touches `rls_rules.rules` only."* **The PR #420 reviewer disproved it.** `tools/ts-cli/ts_cli/
> dependency/mutate.py` depends on `column_id` in four places, and my grep missed it because I
> searched for the container key `view_columns` and then read only the *first* hit rather than every
> one — `mutate.py`'s View helpers reference the container through a local (`v.get("view_columns")`)
> inside functions named `_strip_view_*`, so the grep found them and I did not follow through.
> Filed as **BL-191** (Tier 1, ready-to-fix; **no code changed here** — this PR is documentation-only):
>
> | Defect | Consequence |
> |---|---|
> | `_strip_view_columns`' `column_id` branch never fires (`.get(…, "")` → `""`) | Only the exact-display-name fallback works; a decorated name (`Total LINEAMOUNT`) is missed |
> | `_strip_view_formulas` binds columns by `column_id == formulas[].id` | Real binding is `search_output_column == formulas[].name`, so the formula is deleted and **its `view_columns[]` entry is left behind — a dangling reference**, exactly what the checklist item this PR added forbids |
> | Docstrings assert "real view column_ids are prefixed, e.g. `Orders_1::Revenue`" | 0 of 265 contain `::`; the 9 that differ from `name` differ by a *decoration*, needing an inside-the-token match |
> | `migrate/rewrite.py` already models it correctly (`_DECORATED_FIELDS = ("search_output_column",)`) | The two View readers in one codebase disagree — and the correct model was already there to copy |
> | Tests at `test_dependency_mutate.py:287`/`:648` use `{"name", "column_id"}` fixtures | A shape the census shows does not occur; they pass *because* the fixture matches the wrong model, so they are part of the defect, not the safety net |
>
> **Two lessons worth more than the fix.** (1) The reviewer's find is independent corroboration of
> this pass's own census characterisation — `rewrite.py:59`'s comment ("the column name is
> substituted INSIDE the token") and its `Total LINEAMOUNT` / `Month(YM)` examples were written
> from live evidence on 2026-07-28, before this census, and they match it exactly. (2) A
> "does any code depend on this?" check is not a grep, it is a grep **plus reading every hit**. I
> asserted a negative from a partial read, in the same report that criticises other documents for
> asserting negatives from absence.

### 6.2 C2 — `thoughtspot-model-tml.md`

| Census item | Applied |
|---|---|
| `action_object_associations[]` | New section — YAML, a field table, and a **disposition**: it is a presentation binding naming an action by display name only, so it is a no-op on an instance lacking that action. Do not emit; pass through only |
| `value_casing` on Model columns | New row — 545 sightings / 18 Models, **156 of them formula-backed** |
| `calendar` on a **Table** column | Routed to `thoughtspot-table-tml.md` as instructed (see C2b), and the Model ref's `calendar` row now cross-references it |
| `index_priority` may export as a float | Row rewritten: **a number, emitted non-integrally** (`10.0`, all 20 sightings, confirmed in the raw `edoc`). Stated consequence: *a strict integer validator rejects real ThoughtSpot output.* Also fixed in the payload schema (`"type": "integer"` → `"number"`) |
| Hybrid joins — fix the either/or framing | The `joins` row softened **and** a *Hybrid joins* block added with the 493-join key-set distribution and the operative rule: read inline attributes whenever present, regardless of `referencing_join`; when generating, still pick one form (precedence between them is unverified — stated rather than guessed) |
| *(beyond the brief, same evidence)* | `geo_config` extended to **five** roles with the `country: true` boolean called out as distinct from `region_name.country` (a string) and `custom_file_guid` flagged instance-local; the `calendar` **value vocabulary rewritten** as a sub-table settling V1; `properties` rows annotated always-emitted; `lesson_plans` evidence 4 → 8 Models; `description` evidence raised to 63/549 + 1,960/4,436; `cardinality` vocabulary recorded (`MANY_TO_MANY` never); non-equality joins recorded as **unexercised** (0 observed) so the range-join docs are not read as evidenced |

### 6.2b C2b / C3 — `thoughtspot-table-tml.md`

| Item | Applied |
|---|---|
| `rls_rules.table_paths[].column` is a **list**, not a bracketed string (**C3**) | Corrected in the YAML **and** in a new `rls_rules` field table. States where the brackets *do* belong (the rule `expr`). Grepped for generators of the old shape — none found |
| `joins_with[].cardinality` de-required | `Required: Yes` → **`On import`**, with the 0-of-165 evidence, the round-trip consequence (**re-importing an exported Table TML submits a document with no `cardinality`**), and the honest statement that export evidence alone cannot decide *which* of the two readings is right. Prescribes: emit it, tolerate its absence |
| `calendar` on a Table column | New row — this is the half of **V1** the earlier 40-model run reported as *not* observed |
| *(beyond the brief)* | `format_pattern`, `is_hidden`, `currency_type` (with the **only** live sighting anywhere of the `column` form — a bare column name) added; `dataset_id` documented as instance-local; the `connection` block noted **absent on 2 Falcon tables** despite being Required, so a reader that assumes it crashes |

### 6.3 C4 — the wide aggregation vocabulary: **Models or Views only?**

**Resolved: View-only. The enum was deliberately NOT widened.** I did not take this from the report
— I re-derived it from all 500 census documents:

| Document type | `aggregation` values observed |
|---|---|
| `model:` | `SUM` 1605 · `AVERAGE` 178 · `COUNT` 21 · `COUNT_DISTINCT` 1 · `MIN` 1 |
| `table:` | `SUM` 1291 · `AVERAGE` 14 · `COUNT` 1 · `COUNT_DISTINCT` 1 |
| `sql_view:` | `SUM` 133 · `AVERAGE` 4 |
| `view:` | `SUM` 93 · `AVERAGE` 5 · `COUNT` 2 · **`MOVING_SUM` 2** · **`RANK` 1** · **`SQL_INT_AGGREGATE_OP` 1** |

All four non-standard sightings are on `view:` documents (`Growth View`/`prev_year`,
`GA - Moving Sum Test`/`Test formula`, `Rank Sales, Quota`/`Rank Sales`,
`% of Total Test`/`Rank`). **No window value appears on any document type a converter accepts.**

So per the brief: a note was added under **NM6** stating the View vocabulary is wider, citing the
evidence in both directions, and recording that the nine-value payload enum is **correct as scoped
and deliberately not widened**. The wider vocabulary was also documented in the View reference,
where it *is* in scope. This closes census recommendation **M3** by scoping rather than by
extension — the census offered both options and the evidence chose.

### 6.4 C5 — BL entries filed (**BL-189** and **BL-190** — see the numbering note)

> **Numbering note.** I verified the next free number at branch time (max was **BL-187**) and filed
> BL-188/BL-189. Between branching and pushing, **main merged PR #419 which claimed BL-188** for an
> unrelated entry ("Generate the persona/routing docs from `SKILL.md` frontmatter"). Caught on the
> rebase — `docs/backlog.md` was the only conflicting file. Resolved by keeping **both** entries and
> renumbering mine up to **BL-189** / **BL-190**, including every cross-reference (the two entries'
> forward pointers to each other, BL-186's pointer, the priority-index rows, and three citations in
> the gaps doc). The lesson for a long-running branch: *re-check the next free number at push time,
> not only at branch time* — a backlog ID is a shared, monotonic resource and any concurrent PR can
> take it.

- **BL-189** (Tier 2) — `ts tml export --parse` crashes on a null `edoc`. Filed **ready-to-fix**:
  both call sites (`tml.py:258`, `:391`), the two-part fix (a `parsed is None` guard **and** a
  skip-and-report path that surfaces the per-document `status`/`error_message` the response already
  carries), and the unit test shape per `.claude/rules/ts-cli.md` (no live instance). **No code was
  changed in this PR**, as instructed. Its severity is argued rather than asserted: batching is the
  *documented* export method, and `TS:` system objects return `FORBIDDEN` on every cluster, so one
  unreadable GUID aborts a batch of twelve with a `TypeError` instead of a diagnosis.
- **BL-190** (Tier 3) — census follow-ups **T2 and T3**: re-run with `--fqn --associated --include-obj-id`, **and against a second cluster**.
  Frames it as evidencing **NM1 / X8**, the least-evidenced rules in the construct mapping, and
  lists four specific questions a re-run settles. Notes the ordering dependency: `--parse` is
  unusable until BL-189 is fixed, so fix that first.
- Both added to the **priority index** in their tiers (the index is checked by BL-185's future
  validator, so placement matters).

### 6.5 C6 — BL-186 refined

Rewritten with a per-item status table. **V1 substantially settled** (named calendars *and* the
Table-column sighting — both of which the earlier 40-model run reports as *not* seen; the
`CALENDAR_TYPE_GREGORIAN` literal is 0-of-500), **V2 half settled** (`column` form confirmed live as
a bare column name — answering one of its two original questions outright), **V3 confirmed present
and closeable**, **V4 untouched and now negatively evidenced twice**.

The operative refinement is about *method*, not status: all three residuals now need **object
construction or an API read, not more surveying** — V1's sentinel question needs
`GET /api/rest/2.0/calendars/…`, so the `calendars/create` leg the entry originally specified is no
longer the cheapest path. The construct mapping's V1–V4 table and its drive-by-evidence block were
updated in parallel, with the earlier bullets **kept** (they record what was known when) and a
superseding census block added that says plainly where the census **contradicts** one of them.

### 6.6 C7 — the census in the gaps doc's currency paragraph

Added as a first-class bullet under *How this stays current*, cited with its full internal path
(allowed there — that document declares it cites internal paths freely). It is framed as *the
instrument that attacks the specific blind spot the doc's own lesson 1 names*, with the outcome
counts (25 undocumented paths / **4 wrong fields** / 168 confirmed / 128 documented-never-observed)
and the argument for why it belongs in the currency loop: the four wrong fields **could not** have
been found by reading our own docs, ThoughtSpot's docs, or any import probe — only by looking at
output. Both limits recorded with it (one cluster → T3 and no identity flags → both now in BL-190), and a cadence
proposed (one census per meaningful build change; scripts reusable as-is). The census and this
report were also added to the *Sources* table.

---

## 7. Work item D — sweep for contradicted claims

| # | Claim found | Where | Disposition |
|---|---|---|---|
| 1 | "`aggregation` on a formula column is ignored at query time" (universal) | construct-mapping ×2, model-tml, fidelity review | Corrected — §2 |
| 2 | G11's fourth silent-failure item | gaps doc | Withdrawn with explanation |
| 3 | **Fixed `PARTITION BY` → `group_aggregate` grain presented as a mapping** | `agents/shared/mappings/ts-snowflake/ts-snowflake-formula-translation.md` (cumulative reverse-translation decision table) | **The most consequential D finding — this one is in a live conversion path, not a design doc.** `group_aggregate` fixes the grain of the **measure**; it does **not** give `moving_sum` a `PARTITION BY`. The row is now marked an **approximation**, with two operative rules: flag the fixed-partition case for review (it *compiles*, verified 2026-07-10, which is exactly what makes it dangerous — nothing errors), and use a wrapped `sql_*_aggregate_op` where fidelity outranks nativeness. The table's other two rows are unaffected and I said so. Currency anchor bumped |
| 4 | `view_columns[].column_id` cross-referenced in the SQL-View comparison table | `thoughtspot-sql-view-tml.md` | Corrected to `search_output_column` with a pointer. Also fixed there: `geo_config.region_name` list→dict, the `CALENDAR_TYPE_GREGORIAN` literal **withdrawn as unverified** (0 of 500, incl. 0 of 40 SQL Views where that file claimed it), the 12 never-observed properties marked unverified with the honest framing (*may well be accepted on import — nothing says they are rejected — but nothing establishes they are honoured*), and the observed `aggregation` values recorded. Anchor bumped |
| 5 | *Checked and cleared* — `cumulative_sum` with a single argument, in `tableau-formula-translation.md:750` | Tableau mapping | Looked like an arity bug. **Probed it** (probes 51–52): a 1-argument `cumulative_sum` is **accepted**, both bare and wrapping a `group_aggregate`. No defect — and it is an additional E13 data point (both halves of the window can be left to the query), now recorded in formula-patterns |

Cross-platform mappings checked and found **already correct**: the Snowflake mapping's other
cumulative rows (it already stated the dynamic-partition fact), and the Tableau mapping's
`rank()` arity completion — which independently records the *same* `Function rank expects 2
arguments, found 1` error this run reproduced.

**Internal-path hygiene.** The two upstream-facing mapping documents cite internal paths **only** in
their declared ground-truth headers, which is their established convention. My one violation — a
full path to the View reference in the NM6 body — was corrected to a by-name citation (*the View TML
reference*) and that file added to the header declaration, so the convention now covers it. The
census is cited in those two documents **by name and date only**; the full path lives in the gaps
doc, which permits it. Internal backlog IDs in the mapping docs (`BL-170` ×9) are pre-existing
house style, explicitly framed as "tracked internally as", and were left alone.

---

## 8. Verification run

```
347 passed in 8.55s                        (tools/validate/tests/)
full check_*.py sweep over --root .        no failures
101 anchor links checked, 0 broken         (GitHub-slug verifier, 8 touched files)
coverage summary arithmetic                re-derived from table rows: 146 = 108 + 37 + 1 ✓
                                           per-section subtotals all balance ✓
                                           cross-checked vs actual row classifications:
                                             window section = 5 direct / 9 passthrough / 14 ✓
stale-figure grep (112 / 33 / 77% / E1-E12) only the 2 intentional historical mentions remain
zero-persistence check                     [] / edoc identical / no joins_with
```

---

## 8b. Two table-rendering defects found by a structural check (one fixed, one left)

I ran a markdown table-integrity check (cell counts per row vs the header, discounting escaped and
code-span pipes) over all nine touched files. Two genuine mismatches, both **pre-existing**:

| Site | Defect | Disposition |
|---|---|---|
| `ts-ossie-compliance-gaps.md` — the withdrawn **G13** row | 4 cells in a 5-cell table, so every cell after *Evidence* rendered one column left | **Fixed** — I was already restructuring that table to add G15, so leaving a shifted row in it was not defensible |
| `thoughtspot-formula-patterns.md` — the `pow` row in the math-functions table | 3 cells in a 2-column table; GitHub drops the third, so the "**Not** `power` — that name is rejected" note **did not render at all** | **Fixed on the review round.** I first left it, reasoning that widen-vs-fold was a content decision. On reflection that was the wrong call: the invisible text is a *verified parser gotcha*, the file was already being edited in this pass, and the table's own `safe_divide` row establishes the house style (an em-dash note inside cell 2). Folded to match it, so the warning now renders. One line, no table restructuring |

---

## 8c. Commits and the BL-number collision

Three commits on `feat/ossie-consolidation` → PR **#420** (opened, **not merged**, per the brief):

```
4be5fb8 docs(schemas): finish the index_priority number sweep — MetricLevel payload + SQL-View reference
c9e4efc docs(ossie): fix the withdrawn G13 row's column count (pre-existing shift, table edited in the same pass)
eb408bf docs(ossie): aggregation semantics corrected + window rework (4 rows -> passthrough, 74%) + TML census routed
```

**Rebased once, onto `main` @ `eff8815`.** `main` moved three commits (#417–#419) while this branch
was open. Only `docs/backlog.md` conflicted — and the conflict was substantive rather than textual:
**PR #419 claimed `BL-188`** for an unrelated entry after I had verified 187 as the max and filed
BL-188/BL-189. Resolved by keeping both entries and renumbering mine to **BL-189** / **BL-190**,
carrying every cross-reference with them (each entry's pointer to the other, BL-186's forward
pointer, both priority-index rows, three citations in the gaps doc). Verified afterwards: no
duplicate `## BL-` heading, and no stale `BL-188` reference anywhere in `docs/ossie/`.

The transferable lesson: **a backlog ID is a shared monotonic resource, so re-check the next free
number at push time, not only at branch time.** Any concurrent PR can take it, and a long-running
branch will not notice until the rebase.

---

## 8d. Review round — PR #420 verdict FIX-FIRST, 13 items, all applied

The reviewer verified the arithmetic, the probes, the census routing and the RANK judgement call as
clean, and **endorsed RANK-stays-`direct` with a better rationale than mine**: `rank` has no
*order-column* argument at all, so its window genuinely is the query result set; `moving_*` /
`cumulative_*` **do** take order columns, so their partition is query-dims-minus-order-cols, which
matches no static `OVER` shape. That is a structural distinction rather than the "fine but real"
judgement call I recorded in §9.1 — concern 1 is downgraded accordingly.

| # | Item | Fix |
|---|---|---|
| **1** | **Blocking.** The new `#### properties.calendar — observed values` sub-block was inserted **mid-table**, orphaning the `properties.synonym_type` and `data_panel_column_groups` rows, which rendered as literal pipe text | Sub-block moved to after `data_panel_column_groups`, before `### formulas[] fields`. **See the tooling note below** |
| **2** | **Blocking.** §6.1's "no code depends on the old field" was **false** | **BL-191** filed (Tier 1, ready-to-fix, code untouched); §6.1 replaced with a correction banner naming all four defects and the two lessons |
| **3** | **Blocking.** The Worked shape (`:993`) still carried the withdrawn universal claim — a **third** site my sweep missed | Scalar/aggregate split applied there, phrased as *why the `SUM` is inert in this specific example* plus the R4-P3 contrast |
| **4** | **Blocking.** G15 contradicted my own probes *and* the RANK row by lumping `rank` in with the order-columns behaviour | G15 rewritten as **two shapes, one gap**; `rank`/`rank_percentile` correctly described as measure + direction only, no order columns, no frame. Evidence-class note added to the RANK **and** PERCENT_RANK rows: the arity is probe-proven, "always global" is documentation-derived |
| **5** | **Blocking.** The un-probeable evidence-class note was at 2 of 5 sites | Added to the Metric `aggregation` row, **R4(c)**, and the TPC-DS fidelity note. Now at all five, plus the new Worked-shape site |
| 6 | The `OVER` row's "both live-confirmed" overreached | Replaced with an explicit probed / **not probed** split: `{ }` was probed only as a `last_value` partition, never in `group_aggregate`; the `query_groups ( )` form of the `cumulative_sum` rejection was never probed. Those three cells now say they rest on the formula reference |
| 7 | The `OVER` row named a wildcard `sql_*_aggregate_op`, violating **E4** | `sql_number_aggregate_op` "(or the typed sibling …)", mirroring the window-aggregation row |
| 8 | Both reports were untracked | **Moved into `docs/reviews/`** as `2026-07-30-tml-census.md` and `2026-07-30-ossie-consolidation-probes.md`; three gaps-doc citations repointed (including a malformed leading slash, `/.superpowers/…`). This is what makes the `T1`–`T4` labels resolvable |
| 9 | T3/T4 were unrouted | **T4** → a **BL-186** pointer (its body already describes the `calendars/…` read; no new ID). **T3** → folded into **BL-190**'s scope, heading and index row; `view-tml` and the gaps doc repointed |
| 10 | Missing house-style separator before `## BL-189` | Blank line + `---` added |
| 11 | BL-186's index row said "V2-residual + V4 remain", contradicting its own body | Now "V3 closed; three residuals: V1's sentinel question, V2's round-trip + `is_browser`, V4 in full" |
| 12 | `description` evidence still cited the 40-model sample in three places | Upgraded to the census figures (63/549 formula-backed, 1,960/4,436 physical, 72/143 Models) at construct-mapping `:241` and `:260` and gaps `:77`, keeping the old figure as a "same conclusion, a seventh of the evidence" aside |
| 13 | `view-tml`'s "256 of 265" had no tracked source | Now cites the moved census report at both sites |

### The tooling note item 1 earns

**My table-integrity check could not have found item 1, and I should have known that.** It compared
*cell counts per row against the header*, so a block inserted **between** two rows of a table leaves
every row's cell count intact — the rows are still well-formed, they are simply no longer part of a
table. I ran a check whose failure mode was exactly the defect it needed to catch.

The check that does find it is structural, not arithmetic: *does a table resume with a **data** row
after intervening prose?* (A resumption with a header + `|---|` separator is a new table and fine.)
Written and run after the fix over all ten touched files: **0 occurrences**, so item 1 was the only
one of its kind. Both checks are worth keeping — they fail on disjoint defects.

**The generalisable lesson:** a structural validator's blind spot is usually the shape it cannot
represent, not the values it gets wrong. Mine modelled a table as a list of rows, so a table
*interrupted* was unrepresentable and therefore invisible.

---

## 9. Concerns

1. **~~The window reclassification is a judgement call at one boundary~~ — DOWNGRADED on review;
   the boundary is structural, not a judgement call.** I recorded this as the pass's one soft spot:
   `RANK`/`PERCENT_RANK` kept `direct` while `LAG`/`LEAD` moved to `passthrough`. The reviewer
   supplied the sharper rationale: **`rank` takes no order-column argument at all**, so there is no
   partition for the query to complete and its window genuinely *is* the result set;
   `moving_*` / `cumulative_*` **do** take order columns, so their partition is
   query-dimensions-minus-order-columns — which matches no static `OVER` shape. The two families
   differ in signature, not in degree, so the split is principled and the alternative reading
   (sweeping the section, `106`/`39`, 73%) is not equally defensible. **What survives as a real
   caveat** is narrower and is now written into both rows: the *arity* is probe-proven, but "`rank`
   is global" is a **query-time** semantic the probes cannot reach — it is documentation-derived,
   the same evidence class as item 3 below.
2. **The frame-clause row stays `direct` by a decomposition choice.** Frames *are* exactly
   expressible; the partition is not. Counting the loss once (on the `OVER` row) rather than twice
   avoids double-counting one defect across two rows, but it means the frame row's `direct` verdict
   is conditional on the native path being reachable — which I state inline. If a reviewer prefers
   the loss attributed to every row that touches it, that row flips too.
3. **The aggregation-semantics correction is un-probeable and stays that way.** It rests on domain
   review. `VALIDATE_ONLY` accepts both shapes with any `aggregation:`, so no import probe can
   settle it; closing it needs a query-result comparison on live data. Everywhere the claim appears
   now says this explicitly, but it remains the one substantive change in this pass with no
   empirical backing. **Nothing was filed for it** — it is a documentation correction, not repo
   work, and the docs carry their own evidence-class note.
4. **The View `search_output_column` finding is one cluster.** Decisive for this build; the file now
   says *generate the new field, tolerate the old one on input*, which is the safe posture either
   way. **Routing resolved on review** (it was flagged here as open): **T3** — re-run against a
   second cluster — is folded into **BL-190**'s scope with its heading and index row updated, and
   **T4** — the `calendars/…` read that closes V1's sentinel question — is now a pointer to
   **BL-186**, whose body already describes exactly that leg, rather than a new ID. So all four
   census follow-ups are routed: T1 → BL-189, T2 + T3 → BL-190, T4 → BL-186.
5. **`check_tml.py` still has no `sql_view` validator** (pre-existing, noted in BL-187). This pass
   made *more* SQL-View corrections — the withdrawn `CALENDAR_TYPE_GREGORIAN` and the 12 unverified
   properties — so the gap between what that reference says and what any gate enforces widened
   slightly. Documentation-only by design here, but worth folding into the next `check_tml.py`
   change.
6. **`index_priority` typed `integer` — swept properly on the second pass, and the first pass had
   missed half of it.** The census's S18 says "all four refs". I initially fixed two sites (the
   Model reference and the payload schema's `FieldLevel`), then swept and found **two more**: the
   payload schema's **`MetricLevel`** carried its own `"type": "integer"`, and
   `thoughtspot-sql-view-tml.md` documented it as "Integer" in both its field table and its YAML
   example. All four are now `number`. I also grepped `tools/ts-cli/` for `index_priority`: **no
   hits**, so no converter code types it `int`. Worth recording as a process note — a
   "documented in N places" finding needs the grep, not a reading of the two obvious sites.
7. **~~The two reports this pass cites live in a gitignored directory.~~ RESOLVED on review.**
   Both were written to `.superpowers/sdd/` (gitignored) and have been **moved into
   `docs/reviews/`** alongside the comparable TPC-DS and converter-learnings reports:
   `2026-07-30-tml-census.md` and `2026-07-30-ossie-consolidation-probes.md` (this file). The
   gaps-doc *Sources* rows now link them as tracked files, and — the reason this mattered more than
   tidiness — the `T1`–`T4` census follow-up labels that the gaps doc, the View reference and
   `BL-190` all cite are now **defined in a file a fresh clone has**. A malformed leading slash in
   one of those citations (`/.superpowers/…`) was fixed in the same pass.
