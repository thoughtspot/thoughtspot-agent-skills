# Snowflake Semantic View pattern round-trip fidelity

**Date:** 2026-09-08 · **Branch:** `feat/sv-patterns-roundtrip-fidelity` · **Design spec:** `docs/superpowers/specs/2026-09-02-sv-patterns-roundtrip-design.md` (with its 2026-09-08 amendment) · **Authoritative numbers:** `.superpowers/sdd/2026-09-02-sv-patterns-roundtrip/REMEDIATION.md`

**Corpus under test:** `Snowflake-Labs/coco-skills`, `skills/semantic-view-patterns/snippets/` — 25 self-contained Semantic View modelling patterns, each shipping `schema.sql` + `seed_data.sql` + `semantic_view.sql` + `queries.sql`. Sixteen were in scope; nine were excluded with reasons (§1.7).

**Converters under test:** `ts` CLI **0.137.0**, driven per `agents/cli/ts-convert-from-snowflake-sv/SKILL.md` (inbound) and `agents/cli/ts-convert-to-snowflake-sv/SKILL.md` (outbound). ThoughtSpot cluster `se-thoughtspot`; a Snowflake account with one scratch database and per-pattern scratch schemas; a pre-existing ThoughtSpot connection over that database. No infrastructure identifiers appear in this document by design — see the redaction note in §1.6.

**Verdict vocabulary** (per query, used verbatim throughout): `EXACT` · `NUMERIC_DIFF` · `SHAPE_DIFF` (row count or grouping differs) · `UNAVAILABLE` (the construct did not survive to that stage, so no faithful statement exists) · `ERROR` (the statement ran and the engine rejected it).

**Structural status vocabulary** (per section of a parsed Semantic View): `MEASURED` · `UNVERIFIABLE` · `NOT_MEASURED` · `PARSE_INCOMPLETE`. `unverifiable` is also a per-construct count column inside a `MEASURED` section — a pair the comparison cannot judge is never counted as survival.

---

## Headline

**Only 8 of 44 corpus queries return the right answer after a Snowflake → ThoughtSpot → Snowflake round trip on the documented path.** With a hand-authored formula file that no `ts` command produces, 9 of 44.

Both figures are measured over the **11 of 16 patterns that produced a ThoughtSpot Model at all**. `ts snowflake build-model` **failed outright on 5 of 16** patterns — `accumulating_snapshot`, `fact_as_relationship_key`, `multi_path_metrics`, `range_join`, `time_intelligence` — and **partially on 2** more (`variables`, `window_metrics`: the structural import landed, the formula pass did not). In **all five** outright failures, the construct that blocks the import *is the construct the pattern exists to demonstrate*.

| | RT (documented path) | RTF (hand-authored formulas) |
|---|---|---|
| `A_vs_C` EXACT | **8 / 44** | **9 / 44** |
| `A_vs_C` wrong-but-answered (`NUMERIC_DIFF` + `SHAPE_DIFF`) | 1 | 3 |
| `A_vs_C` `ERROR` | 35 | 32 |
| Regenerated view deployed as emitted | **11 of 11 legs** | **3 of 12 legs** |
| Structural constructs verified (deployable legs only) ¹ | **65 / 146** | **61 / 109** |

¹ Reported dimension loss is **inflated** by a `parse-sv` identity defect — see §1.10 item 2. No query verdict is affected.

The "deployed as emitted" and "EXACT" rows point in opposite directions, and that asymmetry is the study's central structural finding. The unaided leg **always deploys and always loses every formula**; the assisted leg **keeps the formulas and usually will not compile**. Nine of twelve RTF legs failed to deploy as `build-sv` emitted them; five were rescued by the same one-class hand repair, four could not be rescued at all.

### Not all loss is equal — and the scored verdict cannot tell the difference

**"8 of 44" is the wrong shape for the decision a reader has to make.** The verdict scoring treats a query that dies on a missing identifier and a query that returns $25,400 where the truth is $5,300 as the same miss. They are not the same miss. A loud failure costs an afternoon; a silent one ships wrong figures to a business user who has no way to know. Broken out over the same 44 queries:

| Outcome | RT | RTF | What it means for a user |
|---|--:|--:|---|
| **EXACT** | **8** | **9** | round-tripped faithfully |
| **Loud failure** (`ERROR` — missing identifier, rejected DDL) | 32 | 29 | visible; blocks the migration before anyone trusts a number |
| **Silently wrong** (ran, returned a different number) | **1** | **3** | **invisible; ships wrong figures** |
| Not comparable (stage A fails on the *original* view — corpus defect, §1.8) | 3 | 3 | measurement limit, stated |
| | **44** | **44** | |

Outside this denominator, and loud: **5 of 16 patterns produced no Model at all**, and `time_intelligence`'s 5 queries had no deployed view on either leg.

**The silent-wrong counts of 1 and 3 are a FLOOR, not a total, and the scoring therefore UNDERSTATES semantic loss.** Of the three wrong-numbers findings below, **exactly one (W1, ASOF) appears in the scored verdicts at all**. The other two were found only by direct probing — W2 because a louder unrelated failure upstream (a dropped table alias) killed all five of its queries before any of them reached the semi-additivity, and W3 because its pattern's formula import failed so no query ever scored against the mis-translated window. **A fidelity harness that counts only `EXACT` will systematically miss this class: an upstream loud failure shields the silent one downstream.** Repairing `semi_additive_metric`'s alias rename would convert five loud errors into five silent wrong answers, and the RT silent-wrong count would go from 1 to 6 with no converter change at all.

Two caveats point in **opposite** directions and the evidence does not support resolving them into one number: the **query verdicts are optimistic** for the reason just given, while **reported dimension loss is inflated** by a `parse-sv` identity defect (§1.10 item 2). Both are stated wherever a number appears.

---

The three findings that matter most are therefore not in the `EXACT` column, because they are not failures. They are **wrong numbers returned without an error, from output that imports cleanly and lints cleanly**:

| | Construct | Correct | Returned | Visible in the scored verdicts? | Where |
|---|---|---|---|---|---|
| **W1** | ASOF join | $2,100 | **$5,100** (outbound) / $3,800 (inbound) | **yes** — the only one | §3.1 |
| **W2** | `NON ADDITIVE BY` | $5,300 | **$25,400** | **no** — probe only, masked by an alias rename | §3.2 |
| **W3** | fixed `PARTITION BY` | year-to-date | **lifetime total** | **no** — probe only, read off the emitted formula | §3.3 |

Each fires on the construct its pattern was written to demonstrate. Each survives every gate in the pipeline. This is audit angle 15's thesis — *"does converted output produce the same numbers, not just valid-importing TML?"* — three times over, and §7 recommends unparking it.

---

## 1. Method

### 1.1 Why this corpus

Two properties make it worth more than a normal example set. **It ships its own data**, so nothing is synthesised and both sides of the comparison hold identical rows. And **it is organised by construct, not by subject area** — one pattern per Semantic View modelling construct — which is very nearly the axis along which `agents/cli/ts-convert-from-snowflake-sv/references/coverage-matrix.md` is written. The corpus therefore reads as a probe of that matrix almost row for row.

The matrix already *predicts* specific losses and names a backlog item for most of them (rows 16/BL-181, 27/BL-194, 39/BL-180, 4 and 38/BL-166). Row 28 concedes the gap outright: *"not exercised on a live fixture — the TPC-DS fixture contains no window-on-metric construct, so this row's evidence is unit-level only."* Those were predictions. Nothing in the repo tested them end to end. §5 records, for each, whether this study **confirms**, **refutes**, or is **new** against it.

### 1.2 Three stages, and what each hop attributes

Each numbered query in a pattern's `queries.sql` is a clean `(DIMENSIONS, METRICS, WHERE)` tuple. That is what makes the exercise tractable: one tuple, three engines.

| Stage | Engine | How the query is expressed |
|---|---|---|
| **A** | the original Snowflake Semantic View | `queries.sql` verbatim |
| **B** | the ThoughtSpot Model | the same tuple as AgentQL, via `ts agentql fetch-data` |
| **C** | the regenerated `_RT` / `_RTF` Semantic View | `queries.sql` rewritten through a name map |

Two stages can only say *something* broke. Three give two independent hops, so every discrepancy is attributable:

- **A ≠ B** → the from-converter (`parse-sv` / `translate-formulas` / `build-model`)
- **B ≠ C** → the to-converter (`build-sv`)
- **A ≠ C** → net round-trip loss. **This is the headline number.**

Stage C needs the rewrite because identifiers change across the round trip. The map is assembled mechanically from the `parse-sv` JSON, the exported Model TML and the `build-sv` output; a name that cannot be mapped is itself a finding — the construct did not survive.

The attribution earned its keep on `asof_join`, where **both legs are wrong and wrong differently** (§3.1). A two-stage design would have reported one wrong total and no cause.

### 1.3 The two outbound legs — RT and RTF — and why the split exists

`ts snowflake build-sv` takes an optional `--formulas` map. Without it, **every** Model formula column is dropped on the way out. **Nothing in the documented flow produces that file**; both files used in the pilot carried a self-declared note reading *"HAND-AUTHORED. No ts-cli command produces this file."*

The pilot ran two of three patterns *with* a hand-authored file and one *without*, so the three were never on comparable footing — and the difference flattered exactly the wrong pattern. `multi_fact_table`'s published "2/4" was an assisted number; unaided it is **1/4**. `derived_metrics`' "0/4" was an unaided number; assisted it is **2/4**. Read as one table the old numbers said `derived_metrics` was twice as lossy as `multi_fact_table`; on equal footing they are identical on both legs.

Every pattern from that point on therefore ran **both legs, reported separately, never merged**:

- **RT** — `build-sv` with **no** `--formulas`. What a user following the documented flow actually gets.
- **RTF** — `build-sv` **with** a hand-authored `--formulas`. The converter's ceiling.

The driver refuses two legs naming the same view and refuses a stage-C function reused across legs, and its output carries **no top-level `A_vs_C`** — a consumer must name its leg, so the two cannot be averaged or fudged.

One boundary on the ceiling: `--formulas` cannot create a column the inbound leg never produced. **The RTF ceiling is bounded by the inbound leg**, which is why `window_metrics`' formula file omits two of its metrics and `derived_metrics`' carries one formula against an original seven.

### 1.4 Verdicts, tolerance, and the four structural statuses

Numeric comparison normalises on column name and row ordering — AgentQL returns rows unordered, and both sides are sorted before comparison, so ordering is not scored as a fidelity question. Decimals compare equal within a **relative tolerance of 1e-12**, compared natively as `Decimal` rather than coerced to float.

**The tolerance was tightened from 1e-9 mid-study, and the spec was amended rather than the code reverted.** 1e-9 was an estimate, and an adversarial review falsified it against the spec's own stated intent (*"tight enough that a real semantic divergence cannot hide inside it"*): at relative 1e-9 the threshold reaches one cent at $10M and one dollar at $1B, so `123456789.01` and `123456789.02` compared `EXACT`. For a study whose headline numbers are revenue totals, that is precisely the divergence class worth catching. Decimal-native comparison landed in the same change, so the tighter bound costs no legitimate precision. The standing rule: **a comparison that needs a looser tolerance to pass is a finding, not a tuning problem** — record the delta, never widen the bound.

`UNAVAILABLE` is deliberately a distinct verdict from `ERROR`. A metric that vanished structurally and a metric that blew up at query time are different findings with different fixes. Both stay in every denominator: they are queries that **could not be measured**, never queries that passed.

Structural comparison parses **both** DDLs with the same parser — `parse-sv` on the original `GET_DDL`, and again on the regenerated DDL — then diffs the two JSON documents section by section. Each section carries one of four statuses:

| Status | Meaning |
|---|---|
| `MEASURED` | both sides parsed; pairs judged `same` / `changed` / `unverifiable` |
| `UNVERIFIABLE` | the comparison cannot judge survival (e.g. the regenerated side carries `expr: null`) |
| `NOT_MEASURED` | the section is empty on both sides — which is **not** survival |
| `PARSE_INCOMPLETE` | `parse-sv` could not read one side's entries |

`survived` is read from the tool's own rollup and is **never derived by subtraction** — subtraction silently reabsorbs `unverifiable` into survival, the easiest way to publish a false pass. The `UNVERIFIABLE` status was introduced mid-study for exactly that reason (§9).

### 1.5 The oracle

Many `queries.sql` carry expected values in comments — `semi_additive_metric` q1, for instance: `-- Expected: 2024-05-31 → $7,500.00 (1250 + 5300 + 950)`. Where present, that independently validates stage A, so the study is not comparing two wrong answers to each other and calling it agreement.

| Oracle status | Patterns | n |
|---|---|---|
| Oracle present, **passes** | `accumulating_snapshot`¹, `asof_join`, `entity_facts`, `fact_as_relationship_key`, `multi_path_metrics`, `range_join`, `role_playing_dimensions`, `semi_additive_metric` | **8** |
| Oracle **absent** | `ai_metadata`, `derived_metrics`², `multi_fact_table`², `shared_degenerate_dimension`, `tags`, `time_intelligence`, `variables`, `window_metrics` | **8** |

¹ `accumulating_snapshot` is honestly **5 of 5 queries oracled, 4 EXACT and 1 row-count difference** — not the "PASS 5/5" first reported (§9).
² Given a *substitute*, not an oracle: `derived_metrics` tied to its own `seed_data.sql` arithmetic, `multi_fact_table`'s substrate proved unmodified. Neither is independent and neither is reported as one.

**No pattern's stage A ever disagreed with the corpus's own stated numbers.** Where an oracle exists, the baseline is sound and the losses downstream are real rather than measurement error. Where it does not, the pattern is reported as oracle-absent and **never as implicitly correct** — which matters most for the patterns that look *best*: `multi_fact_table`'s clean verdicts establish that three engines agree with each other, not that any of them is right.

The oracle also served a second purpose it was not designed for. After the schema-collision error (§9), the standing ruling became: *a pattern whose oracle passes is proven uncontaminated at stage A*; a pattern that shares a colliding table name and ships no oracle cannot self-verify.

### 1.6 Pipeline, provenance, and redaction

Per pattern, in order: deploy `schema.sql` → `seed_data.sql` → `semantic_view.sql`; `GET_DDL` the deployed view as the source of truth; `ts snowflake parse-sv` → `introspect` → `ts tables create` → `translate-formulas` → `build-model` (two-pass, per coverage-matrix L7) → `ts tml export` → `build-sv` → `lint-ddl` → deploy the regenerated view.

The comparison engine was written for this study, frozen before the runs, and lives at `.svrt/bin/` — **225 tests passing, 1 skipped**, after five fix rounds, three adversarial refute-briefed reviews and mutation sweeps, then three further rounds during the runs. Nothing under `.svrt/bin` or `.svrt/tests` was modified by any run or by the remediation pass. Engine defects found during the runs are **reported, not patched** (§6.3).

Every number in this document is traceable to an artefact under **`.svrt/work/<pattern>/`**, cited by relative path throughout. **That directory is gitignored** (`.gitignore:81`) — it is a local workspace on the branch author's machine, not a committed fixture, and no fixture corpus was vendored into the repo. The engine's own module hashes, the `ts_cli` version and the worktree HEAD are recorded in each group report's provenance block.

**Redaction.** This repository is public. Findings, verdicts and matrix corrections are publishable; infrastructure detail is not. This document names the ThoughtSpot cluster nickname `se-thoughtspot` and nothing else — no Snowflake account, region, role, warehouse, connection name, database or schema. Where a schema name would otherwise carry meaning, it is generalised ("a scratch schema", "one schema per pattern"). Corpus object names (`ORDERS`, `DIM_DATE`, `CHANNEL_SALES_SV`) are upstream-public and are used unqualified.

### 1.7 Exclusions — the nine upstream patterns not round-tripped

| Pattern(s) | n | Reason |
|---|:-:|---|
| `introspection`, `standard_sql` | 2 | No `semantic_view.sql` — meta/diagnostic patterns, nothing to convert |
| `sv_diagnostics` | 1 | Eleven **deliberately broken** Semantic Views (fan traps, ambiguous paths, reversed relationships). A negative-test corpus; a different exercise |
| `caller_rights`, `row_access_policies` | 2 | Require `ACCOUNTADMIN`; the study's session role does not hold it |
| `materialization`, `inline_sv`, `scoped_dataset` | 3 | Private preview on this build; `materialization` also needs `ACCOUNTADMIN` |
| `system_explain_semantic_query` | 1 | Explain-plan tooling rather than a modelling construct |

`inline_sv` deserves a note, because it is the one exclusion that cost a measurement: `shared_degenerate_dimension` ships a *second* Semantic View built from an inline SQL dataset, and the study's inability to regenerate it is what produced that pattern's tautological q7 (§4.9, §6.3).

### 1.8 Corpus defects — a stage-A failure is **not** a converter finding

**Four of the sixteen patterns ship DDL that does not compile on this Snowflake build.** These are pre-existing faults in the fixtures. Each needed a minimal, documented change before the round trip could begin, and where an oracle existed it was re-verified *after* the change to prove the modification faithful. **None of them is charged against the converter, and none inflates any loss figure in this report.**

| Pattern | Verbatim Snowflake error | Minimal change |
|---|---|---|
| `accumulating_snapshot` | `010905 (42601) … Metric defined with using relationship 'APPLICATIONS.DECISION_COUNT' cannot be referenced in the definition of 'APPLICATIONS.DECISION_RATE'. Only derived metrics can refer to metrics defined with using relationship.` | the three funnel-rate metrics inlined as `DIV0(COUNT(REVIEW_DATE), COUNT(APPLICATION_ID))`. Qualifying the references was probed first and fails identically. Oracle re-verified after |
| `ai_metadata` | `001003 (42000) … syntax error line 56 at position 2 unexpected 'COMMENT'.` | `COMMENT` moved ahead of the `AI_*` clauses. Probes isolated it: `AI_VERIFIED_QUERIES` alone is fine; `COMMENT` after **any** `AI_*` clause is not. Ships no oracle, so this one rests on inspection — the change reorders a clause and alters no content |
| `fact_as_relationship_key` | `001003 (42000) … syntax error line 15 at position 36 unexpected '.'.` | `sales(sales.fiscal_qtr_key)` → `sales(fiscal_qtr_key)`; this build rejects a qualified column inside a relationship's column list. Oracle re-verified after |
| `time_intelligence` | `010202 (42601) … Duplicate expression name 'SALES.REVENUE'.` | the two passthrough `FACTS` entries removed (`sales.revenue`/`sales.units` are declared in both `FACTS` and `METRICS`; nothing references the fact form). The `window_metrics` README states this exact rule, so the fix is the corpus's own advice applied to a sibling that violates it |

A fifth defect is structural rather than a compile failure: **`multi_path_metrics/schema.sql` does not deploy** — `weather` declares both `PRIMARY KEY (city_code, start_date, end_date)` and `UNIQUE` on the same key set, giving `010240 (42601) … Entity 'WEATHER' has duplicate primary or unique keys.` The redundant `UNIQUE` line was deleted; the oracle then passes, so the fix changed no result.

**Four further corpus queries fail on the ORIGINAL view**, three of them contradicting the corpus's own prose. They remove the stage-A baseline for those queries and are counted as unmeasurable, never as converter losses:

| Query | Verbatim error | The corpus's own claim |
|---|---|---|
| `time_intelligence` q4 | *"The entities 'SALES' and 'SALES_LY' are not related."* | its own comment claims the opposite — *"Works because region lives on the current-period entity"* |
| `variables` q5 | *"Expression's derived type 'VARCHAR(10)' does not match provided data type 'DATE' for variable 'ANALYSIS_DATE'."* | its "Type coercion" note claims supplied values are coerced to the declared type — not for `DATE` on this build |
| `window_metrics` q3, q4 | *"Required dimensions [DAILY_SALES.YEAR] must also be requested in the semantic view query."* | both request only `daily_sales.date` while `ytd_revenue` partitions by `year` |

### 1.9 Patterns measured in modified form

Stated plainly, because a reader is entitled to know which numbers describe an untouched artefact:

| Pattern | Modification | Consequence for its numbers |
|---|---|---|
| the four in §1.8 + `multi_path_metrics` | corpus DDL repaired | stage A only; three of the five re-verified against their own oracles after the change |
| `accumulating_snapshot` | physical tables renamed `AS_DIM_DATE` / `AS_LOAN_APPLICATIONS` (a superseded collision remedy) | harmless here — the pattern is blocked at `build-model`, so there is no outbound leg for the rename to contaminate, and its stage A reproduces every corpus number. It is the last remaining deviation of that class |
| `ai_metadata`, `entity_facts` | a **name** added to two unnamed relationships (`orders_to_customers AS …`) | semantically neutral and the entire fix; without it `parse-sv` drops the relationship and ThoughtSpot rejects the joinless Model (§5, new finding N4) |
| `ai_metadata`, `asof_join`, `entity_facts`, `semi_additive_metric`, `shared_degenerate_dimension` | **RTF leg hand-repaired to deploy** — each formula-derived alias prefixed with its owning table alias, and nothing else. `semi_additive_metric` needed two further fixes (qualify two metric aliases; rename `balance_usd` → `balance_usd_fact`) | **every `_RTF` stage-C number on these five describes a view a human repaired, not a view the tool produced.** The undeployable file and its verbatim Snowflake rejection are kept beside each |
| `shared_degenerate_dimension` | RTF leg **reduced** — only the cross-fact `total_revenue` restored | buys +1 metric structurally and **zero** query fidelity |
| `derived_metrics` | its `DIM_DATE` isolated into its own schema after a live clobber, table name unchanged; the original view re-deployed with exactly one token changed | stage A and stage C both read the isolated copy and are unaffected; **stage B is `UNVERIFIABLE`** (§1.10) |
| all 16 | the corpus's own hardcoded database/schema self-references rewritten to the target schema before execution | mechanical; `stage_corpus.py` asserts no corpus self-reference survives staging |
| 6 patterns | deployed into **per-pattern** scratch schemas rather than one shared schema, table names unchanged | the corrected layout after the collision error (§9). Renaming *tables* instead was rejected: it would break every `dim_date.x` reference in the SV DDL and force hand-editing `build-sv`'s own output — the one contamination the study must not make |

### 1.10 Method limits, stated plainly

These bound what the numbers can mean. Items 1–4 were found by the study's own adversarial review of its own engine; item 5 by the adversarial review of this report, which found the study **overstating** loss there. None is hidden inside a survival figure.

**1. Dimension `expr` is null on the return leg — for PASSTHROUGH dimensions only.** `parse-sv` reads `expr: null` for every dimension on a regenerated view, so survival is never actually checked and the pair is counted `unverifiable`, not `survived`. The limit is **narrower than the study assumed for most of its life**: a *computed* dimension comes back with `expr` populated and is fully comparable. Measured directly by hand-diffing original against regenerated DDL text:

| Pattern | computed dimension | original | RT (documented path) | ceiling |
|---|---|---|---|---|
| `window_metrics` | `DAILY_SALES.YEAR` | `as YEAR(sale_date)` | **absent** | `DAILY_SALES.YEAR as YEAR(sale_date)` — **byte-identical** |
| `window_metrics` | `DAILY_SALES.MONTH` | `as MONTH(sale_date)` | **absent** | byte-identical |
| `variables` | `PRICE_TIER` | `as ( CASE … END )` | **absent** | same logic, unqualified, outer parens dropped (undeployable) |
| `time_intelligence` | (computed FACTS) | `as DATEADD('year', 1, SALE_MONTH)` | **absent** | identical expression, relocated `facts()` → `dimensions()` |

So: there is **no hidden class of silently-changed computed dimensions**. On the documented path a computed dimension is **lost, not changed** — a visible failure. When it survives at all it survives byte-identically: no rewriting, no normalisation, no widening.

**2. `parse-sv` derives a dimension's identity from the referenced column, which MANUFACTURES false lost+added pairs and INFLATES reported dimension loss.** `build-sv` always self-qualifies a passthrough dimension's right-hand side, and the deployed DDL is correct:

```
DAILY_SALES.DATE as daily_sales.sale_date with synonyms=('Date','date','day','sale date')
```

`parse-sv` reads that as `alias_name='sale_date'`, `source_column='DATE'`, `expr=None` — **it takes the construct's identity from the referenced column and discards the declared name `DATE`**. On the original's bare form (`DAILY_SALES.DATE as sale_date`) it is correct. The consequence: `daily_sales.date` is reported **lost** and `daily_sales.sale_date` **added** for a dimension that is present and correctly named in the deployed view. Every dimension whose declared name differs from its physical column is affected — the general case, since `build-sv` self-qualifies everything. `role_playing_dimensions` is the extreme case: **all 9 role-played dimensions read as lost+added while stage C proves they resolve fine and returns `EXACT 4/4`.**

**Reported dimension loss across this whole study is therefore inflated.** Anything that measures round-trip fidelity through `parse-sv` will over-report it. Every dimension figure below carries this caveat; the query verdicts do not, because they run against the deployed view.

**3. Two Snowflake output columns sharing a bare name would collapse** before the comparison's normaliser sees them. Declared residual, accepted at the engine's fix cap. **No corpus query has that shape**, so no verdict here is affected — but a comparator reused on another corpus must close it first.

**4. Attribution is incomplete in specific, named cells.** `derived_metrics`' `A_vs_B` and `B_vs_C` (4 queries × 3 cells) are **`UNVERIFIABLE`**, not `ERROR`: its ThoughtSpot logical table still points at the pre-isolation schema, so all four stage-B calls fail with `invalid identifier "ta_1".MONTH`. `A_vs_C` and the structural rollups read the isolated copy and are unaffected. The repair is one `ts tml import` with the corrected `schema` field (prepared, with a pre-change backup, at `.svrt/work/derived_metrics/repair/DIM_DATE.table.tml.json`) and it was refused twice by the session's permission classifier. Nothing else about the pattern is broken.

**5. Four stage-B `UNAVAILABLE` cells are a HARNESS SCOPE DECISION, not a platform or fidelity limit — they are *unasked*, not *unaskable*.** `to_agentql` declines **every** `WHERE` (`.svrt/bin/namemap.py:442-453`), unconditionally and **before inspecting the predicate**; the decline's own comment concedes that no corpus query carrying a `WHERE` "has ever been exercised" through it, and that "there is no translation … **here**". Four cells fall to that rule alone — `entity_facts` q4 and `semi_additive_metric` q1/q2/q5 — and in all four **every construct the query needs is present in the Model and already resolved in the name map**: `orders.order_amount` → `{'name': 'Order Amount', 'wrapper': 'SUM', 'role': 'metric'}` and `balances.balance_date` → `{'name': 'Balance Date', 'wrapper': None, 'role': 'dim'}` (`.svrt/work/*/namemap_remediated.json`). The resolver that returns those, `_look()` (`namemap.py:298-318`), is the same one the dimension and metric loops of the same function already call on every query: **the predicate mapping was one call away.** Provenance completes it — an earlier alias-rewrite (`where_for()`) was broken and was **deleted rather than replaced** during a bug-fix round (`.svrt/tests/test_namemap.py:130`).

**AgentQL demonstrably expresses filters, and this repo live-verified the syntax before this study began.** `agents/cli/ts-object-model-agentql-query/references/patterns.md:288` carries a string-literal filter (`WHERE "t1"."Country" = 'united states'`); `.../references/agentql-rules.md:182` states *"Filter early — put `WHERE` inside CTEs"*, which is the very rule `.svrt/AGENTQL-SHAPE.md:132` presents as its own discovery; and `.../references/udf-reference.md:61` carries `WHERE DIFF_MONTH(…) BETWEEN 1 AND 12` — a `BETWEEN` on a date column, the exact shape of `semi_additive_metric` q5. **These four cells are a limitation of this study's harness. They are not loss, and must not be read as loss.** The `A_vs_C` figures are untouched by them; the correction costs the stage-B `UNAVAILABLE` count, not the headline round-trip number.

**One of the four is genuinely hard — for a different reason, which belongs stated as such.** `entity_facts` q4 filters a **MEASURE** (`orders.order_amount > 500`), and `.../references/limitations.md:64` live-verifies (2026-07-07, re-verified 2026-07-29) that an aggregate condition in AgentQL's `WHERE` is **silently reinterpreted as `HAVING`** — filtering post-aggregation, with no error. A faithful stage-B expression of q4 therefore has to write the corpus's pre-aggregation intent explicitly, and getting it wrong returns a plausible wrong number rather than an error. That is a real difficulty, and it is **not** the justification the harness gave: the harness never looked at the predicate. The other three are an `=` and a `BETWEEN` on a plain dimension and have no such excuse.

**Scope of the `.svrt/AGENTQL-SHAPE.md` justification, stated honestly.** That document sets its own bar at its lines 9–11: a verdict not derivable from a rule in it *"is not justified and must be re-probed — not assumed."* Measured against that bar it justifies **2 of the 16** stage-B `UNAVAILABLE` cells — `derived_metrics` q2 and q4, the three `*_pct_of_total` metrics its §4 table names. It justifies **none of the other fourteen.** Its §4 — "What has NO faithful AgentQL expression" — contains **no `WHERE` rule at all**, and its §3 says the opposite (*"`WHERE` on a non-selected dimension / **It is expressible.**"*), so the four `WHERE` cells are *refuted* by it rather than supported. And its own "do not extrapolate" note (lines 169–175) excludes *"window/semi-additive metrics"* and *"any pattern whose Model carries more than one dimension table"* — which is exactly what the remaining ten are. Those ten are evidentially sound, but on **their own artefacts**: `multi_fact_table` q2/q4, `window_metrics` q1/q2/q5 and `tags` q1 on the pattern's own `skipped.json` (the named metrics are absent from `model.columns[]`), and `variables` q1–q4 on the phase-2 formula-import failure (`build_model.out`: `import_status: "failed"`; the four missing formula columns are in `namemap_remediated.json`'s `unmatched`) — **not** on `variables`' `skipped.json`, which is `[]`, the false success of §2.4.

**One exhibit inside that document is stale.** Its "Deliberately NOT claimed as unavailable" list says the `SELECT *` rewrite was *"verified `EXACT` on queries 1 and 3"* — `derived_metrics` q1 and q3. In `.svrt/work/derived_metrics/results_remediated.json` both read **`ERROR`**, for the reason item 4 above gives: that pattern's ThoughtSpot logical table still points at the pre-isolation schema. The probe was run 2026-09-02, before the isolation, so the conclusion it supports — enumerating the columns explicitly is a faithful rewrite, not a loss — still stands on probes A–C; **the cited evidence no longer reads `EXACT`.** `.svrt/AGENTQL-SHAPE.md` is frozen evidence and is not edited, so the discrepancy is recorded here instead.

---

## 2. Results

### 2.1 Consolidated table — all 16 patterns

`A_vs_C` denominators are **all extracted queries per leg**, including `UNAVAILABLE` and `ERROR`. Structural is `survived_verified / in`, from the tool's own rollup.

| Pattern | Probe | `build-model` | RT leg | **RTF leg — deployed how** | A_vs_C RT | A_vs_C RTF | struct RT | struct RTF | Oracle |
|---|---|---|:-:|:-:|:-:|:-:|:-:|:-:|---|
| `accumulating_snapshot` | one date dimension, four roles | **FAIL** lint I14 | — | — | — | — | — | — | 5/5 oracled: 4 EXACT + 1 row-count |
| `ai_metadata` | AI clauses + verified queries | OK | as emitted | **HAND-REPAIRED**¹ | **2/3** | **3/3** ʰ | 5/10 | 7/10 | absent |
| `asof_join` | ASOF (point-in-time) join | OK | as emitted | **HAND-REPAIRED**¹ | 0/3 | 0/3 ʰ | 5/11 | 7/11 | 1/3, PASS |
| `entity_facts` | entity-level aggregated fact | OK | as emitted | **HAND-REPAIRED**¹ | 0/4 | **1/4** ʰ | 6/13 ³ | 8/13 ³ | 1/4, PASS |
| `fact_as_relationship_key` | computed fact as a join key | **FAIL** import rejected | — | — | — | — | — | — | 1/4, PASS |
| `multi_path_metrics` | fan trap / `USING` scoping | **FAIL** lint I14 | — | — | — | — | — | — | 2/3, PASS |
| `range_join` | `BETWEEN`-style range join | **FAIL** import refused | — | — | — | — | — | — | 3/4, PASS |
| `role_playing_dimensions` | one dimension, two roles | OK | as emitted | **NEVER DEPLOYED** | **4/4** | 0/4 | 7/17 | 7/17 † | 3/4, PASS |
| `shared_degenerate_dimension` | same dimension name, two facts | OK | as emitted | **HAND-REPAIRED, REDUCED**¹ | **1/6** ⁴ | **1/6** ⁴ | 4/13 | 5/13 | absent |
| `tags` | `WITH TAG` governance | OK | as emitted | as emitted (≡ RT — no formula) | 0/1 | 0/1 | 5/12 | 5/12 | absent |
| `time_intelligence` | computed FK time shift | **FAIL** phase-1 import | **NEVER DEPLOYED** | **NEVER DEPLOYED** | 0/5 ⁵ | 0/5 ⁵ | 7/22 † | 11/22 † | absent |
| `variables` | query-time `VARIABLES` | **PARTIAL** phase 2 failed | as emitted | **NEVER DEPLOYED** | 0/5 | 0/5 | 3/9 | 3/9 † | absent |
| `window_metrics` | window frames on metrics | **PARTIAL** phase 2 failed | as emitted | **NEVER DEPLOYED** | 0/5 | 0/5 | 3/11 | 3/11 † | absent |
| `derived_metrics` | metric-on-derived-metric | OK | as emitted | as emitted | 0/4 | **2/4** | 10/17 | 11/17 | absent (seed substitute) |
| `semi_additive_metric` | `NON ADDITIVE BY` | OK | as emitted | **HAND-REPAIRED**² | 0/5 | 0/5 ʰ | 0/7 | 0/7 | 4/5, PASS |
| `multi_fact_table` | three facts, two shared dims | OK | as emitted | as emitted | **1/4** | **2/4** | 17/26 | 18/26 | absent (substrate proved intact) |

**ʰ = this `A_vs_C` RTF number is measured against a view a HUMAN REPAIRED, not a view the tool produced.** Five patterns carry it: `ai_metadata`, `asof_join`, `entity_facts`, `semi_additive_metric`, `shared_degenerate_dimension`. ¹ `build-sv --formulas` emitted a bare unqualified alias that Snowflake rejects; the deployed file prefixes each such alias with its owning table alias and changes nothing else (§1.9, N7). ² the same, plus two further hand-fixes (qualify two metric aliases; rename `balance_usd` → `balance_usd_fact`); `lint-ddl` calls the undeployable file clean. ³ `facts` reads `PARSE_INCOMPLETE` from a **phantom** — `parse-sv` matches a clause name inside carried-over `comment=` text (§5, N2). ⁴ q7 is excluded from **every** figure: its stage C is a tautology and its stage B duplicates q4's statement exactly (§4.9, §6.3 E4). The published `A_vs_C` figure is **1 genuine EXACT of 6 real queries** on both legs. ⁵ neither leg deployed, so all five queries are unmeasurable; excluded from the 44/45-query denominators.

† **Not a survival number.** The leg's DDL never deployed; the rollup is against `build-sv` output that Snowflake rejects. It describes what `build-sv` *emitted*, not what survived a round trip, and three of these additionally read `PARSE_INCOMPLETE` because **`parse-sv` refuses its own emitter's output**. Five leg-rollups carry the marker: `role_playing_dimensions` RTF, `time_intelligence` RT and RTF, `variables` RTF, `window_metrics` RTF. (`REMEDIATION.md` §7 says "six" while naming and marking five; five is correct.)

### 2.2 The funnel — where the round trip stops

| Gate | Patterns through | Lost here |
|---|:-:|---|
| Corpus DDL deploys | 16 → 16 | 0, after five documented corpus repairs (§1.8) |
| `parse-sv` exits 0 | 16 → 16 | 0 — and that is itself a finding: **every silent loss in this study passes this gate** |
| `translate-formulas` | 16 → 16 | 22 constructs dropped into `skipped[]` across 6 patterns (§2.4) |
| `build-model` produces a Model | 16 → **11** | **5** outright: `accumulating_snapshot`, `fact_as_relationship_key`, `multi_path_metrics`, `range_join`, `time_intelligence`. 2 more partial |
| RT leg deploys | 11 → **11** | 0 — the unaided leg always compiles |
| RTF leg deploys as emitted | 12 → **3** | **9**: 5 rescued by hand repair, 4 not rescuable |
| A query returns the right answer (RT) | 44 → **8** | 36 |

### 2.3 Query verdicts — all 45 measured queries, both legs

`derived_metrics`' `A_vs_B` column is `UNVERIFIABLE` per §1.10 item 4, shown as the raw driver value in brackets. **A pattern marked ʰ has an RTF leg that only deployed after a hand repair, so every `A_vs_C RTF` cell on that row describes a human-fixed view** (§1.9); a pattern marked ⁿ never deployed its RTF leg at all, so its RTF column is `ERROR` by construction. **Four `A_vs_B` cells read `UNAVAILABLE — unasked`**: every construct those queries need is present in the Model and resolved in the name map, and this study's harness declined to translate the query's `WHERE` (§1.10 item 5). They are a harness limit, not loss.

| Pattern | q | A_vs_B | A_vs_C RT | A_vs_C RTF |
|---|:-:|---|---|---|
| `ai_metadata` ʰ | 1 order count by customer | EXACT | **EXACT** | **EXACT** |
| | 2 revenue by region | EXACT | **EXACT** | **EXACT** |
| | 3 monthly revenue | NUMERIC_DIFF | ERROR | **EXACT** |
| `asof_join` ʰ | 1 revenue by zip | NUMERIC_DIFF | **NUMERIC_DIFF** | **NUMERIC_DIFF** |
| | 2 revenue by name + zip | NUMERIC_DIFF | ERROR | **NUMERIC_DIFF** |
| | 3 monthly revenue + zip | SHAPE_DIFF | ERROR | **SHAPE_DIFF** |
| `derived_metrics` | 1 total + per-channel by month | UNVERIFIABLE [ERROR] | ERROR | **EXACT** |
| | 2 channel mix, % of total | UNVERIFIABLE [UNAVAILABLE] | ERROR | ERROR |
| | 3 Q1 vs Q2 channel revenue | UNVERIFIABLE [ERROR] | ERROR | **EXACT** |
| | 4 full-year summary | UNVERIFIABLE [UNAVAILABLE] | ERROR | ERROR |
| `entity_facts` ʰ | 1 revenue by value segment | ERROR | ERROR | ERROR |
| | 2 customers by segment + age | ERROR | ERROR | ERROR |
| | 3 monthly revenue by segment | ERROR | ERROR | ERROR |
| | 4 `WHERE` on the per-order fact | **UNAVAILABLE — unasked** | ERROR | **EXACT** |
| `multi_fact_table` | 1 store vs web by category | EXACT | ERROR | **EXACT** |
| | 2 gross vs net by month | UNAVAILABLE | ERROR | ERROR |
| | 3 return rate by product | EXACT | **EXACT** | **EXACT** |
| | 4 brand quarterly performance | UNAVAILABLE | ERROR | ERROR |
| `role_playing_dimensions` ⁿ | 1 revenue by ORDER month | EXACT | **EXACT** | ERROR |
| | 2 revenue by SHIP month | EXACT | **EXACT** | ERROR |
| | 3 fulfilment lag, both roles | EXACT | **EXACT** | ERROR |
| | 4 both roles cross-tabbed | EXACT | **EXACT** | ERROR |
| `semi_additive_metric` ʰ | 1 total balance as of a date | **UNAVAILABLE — unasked** | ERROR | ERROR |
| | 2 balance by account as of a date | **UNAVAILABLE — unasked** | ERROR | ERROR |
| | 3 total balance per date | NUMERIC_DIFF | ERROR | ERROR |
| | 4 avg monthly balance per account | EXACT | ERROR | ERROR |
| | 5 avg monthly balance, Q1 only | **UNAVAILABLE — unasked** | ERROR | ERROR |
| `shared_degenerate_dimension` ʰ | 1 channel revenue by region | EXACT | ERROR | ERROR |
| | 2 store revenue by region | EXACT | ERROR | ERROR |
| | 3 web revenue by region | EXACT | ERROR | ERROR |
| | 4 side-by-side by region | EXACT | ERROR | ERROR |
| | 5 store revenue by category | EXACT | **EXACT** | **EXACT** |
| | 6 web revenue by channel + region | EXACT | ERROR | ERROR |
| | *7 (excluded — stage-C tautology, and its stage B duplicates q4)* | *EXACT* | *EXACT* | *EXACT* |
| `tags` | 1 channel revenue by month | UNAVAILABLE | ERROR | ERROR |
| `variables` ⁿ | 1 default scoring weights | UNAVAILABLE | ERROR | ERROR |
| | 2 rating-only weighting | UNAVAILABLE | ERROR | ERROR |
| | 3 price-tier breakdown | UNAVAILABLE | ERROR | ERROR |
| | 4 tier thresholds at query time | UNAVAILABLE | ERROR | ERROR |
| | 5 "recent products" flag | ERROR ⁶ | ERROR ⁶ | ERROR ⁶ |
| `window_metrics` ⁿ | 1 7-day rolling average | UNAVAILABLE | ERROR | ERROR |
| | 2 today vs 30 days ago | UNAVAILABLE | ERROR | ERROR |
| | 3 YTD cumulative revenue ⁶ | ERROR | ERROR | ERROR |
| | 4 all window metrics ⁶ | ERROR | ERROR | ERROR |
| | 5 `PARTITION BY EXCLUDING` | UNAVAILABLE | ERROR | ERROR |

⁶ stage A fails on the ORIGINAL view — a corpus defect (§1.8), not a converter loss.

**Totals.** `A_vs_C` **RT 9/45 EXACT · RTF 10/45**, or **8/44 · 9/44** with the q7 tautology excluded — independently recomputed from `.svrt/work/*/results_remediated.json` for this report and matching `REMEDIATION.md` §4 exactly. `A_vs_B` **15/44 EXACT** — 16 of the 45 measured cells, less q7, whose stage-B statement is **byte-identical** to q4's against the same Model and returns the same rows (`.svrt/work/shared_degenerate_dimension/stages_capture.json`), making it a duplicate measurement rather than a second one (§4.9, §6.3 E4). That is **15 of 40 measurable cells** once `derived_metrics`' four `UNVERIFIABLE` are also removed. An earlier draft published 16/45 here while §6.3 claimed q7 was excluded from *every* figure; the figure was the half that was wrong.

The inbound leg scores roughly twice the round trip (34% against 18%, both on the same 44-cell base), which locates most of the loss on the **outbound** side. But read the `A_vs_B` column carefully before treating it as reassurance — and read the `UNAVAILABLE` cells more carefully still, because they are **two different things** and the distinction was the study's own largest overstatement:

- **12 of the 44 published stage-B cells are *unaskable*.** The construct is not in the Model at all, so no statement can reach it: `derived_metrics` q2/q4, `multi_fact_table` q2/q4, `tags` q1, `variables` q1–q4, `window_metrics` q1/q2/q5. Each is a real conversion finding, evidenced per pattern (§1.10 item 5).
- **4 of the 44 are *unasked*.** `entity_facts` q4 and `semi_additive_metric` q1/q2/q5 carry a `WHERE`, and **every construct they need is in the Model and resolved in the name map**; this study's harness declined all `WHERE` clauses without inspecting the predicate. AgentQL expresses filters — this repo live-verified the syntax (§1.10 item 5). **These four are not loss.**

So: roughly a quarter of the corpus's questions cannot be put to this Model, and a further tenth were simply never put to it. A high inbound `EXACT` rate on the questions that *can* be asked still coexists with a quarter being unaskable — but the earlier reading of "a third of the corpus's questions unaskable" overstated it by four cells, and §4.4 already disproves the uniform claim on its own: `entity_facts` q4's RTF `A_vs_C` is **EXACT** — a `WHERE` on a per-order fact, answered correctly at stage C, on a construct stage B recorded as beyond reach.

### 2.4 Inbound losses — the `translate-formulas` skip list

22 constructs across 6 of 16 patterns. Every skip is *declared*, which is the good news; every one is also preceded by a `parse-sv` that exited 0 with `unsupported: []`, which is not.

| Pattern | skipped | Contents and reason |
|---|:-:|---|
| `accumulating_snapshot` | **6** | all six `USING`-scoped metrics — *"has no aggregate expression (right-hand side is the bare column 'applications.X')"*. Upstream cause: `parse-sv` returns `expr: null` for all six, exit 0, 0 unsupported |
| `tags` | **5** | all five metrics — four with *"cannot resolve multi-part identifier … METRIC_DOMAIN"*, one with *"no table for bare identifier 'WITH'"*. `WITH TAG (…)` is folded into the metric's `expr` |
| `multi_path_metrics` | **4** | all four `USING`-scoped metrics (`LATE_DEPARTURE_COUNT`, `LATE_ARRIVAL_COUNT`, `DEPARTURE_FLIGHT_COUNT`, `ARRIVAL_FLIGHT_COUNT`) — same message. What reaches the Model is one attribute and one metric: precisely the two constructs that do **not** exercise the pattern |
| `derived_metrics` | **3** | the three `*_PCT_OF_TOTAL` — *"no table for bare identifier 'total_revenue'"* |
| `multi_fact_table` | **2** | `net_revenue`, `store_share` — *"no table for bare identifier 'total_gross_revenue'"* |
| `window_metrics` | **2** | `PARTITION BY EXCLUDING` mis-parsed as a table alias (*"unknown table alias 'EXCLUDING daily_sales'"*); `LAG` — *"function 'LAG' is not in ts-snowflake-formula-translation.md"* |
| the other 10 | **0** | — |

Two zeros in that column are **false successes**, not clean results:

- **`variables`: 8/8 translated, 0 skipped.** Every bare variable identifier was resolved against the default table alias — `premium_threshold` → `[PRODUCT_SALES::premium_threshold]`, a column that does not exist. The failure surfaces two steps later at Model import and again at re-deploy. The skip list, which this study treats as the primary inbound-loss signal, reports nothing wrong. The same translator **can** detect this class — it raised *"unknown table alias 'EXCLUDING daily_sales'"* on `window_metrics` — so a **bare** identifier gets a free pass a **qualified** one does not.
- **`time_intelligence`: 15/15 translated, 0 skipped**, and the Model still never imported (§4.11).

---

## 3. The three wrong-numbers findings

These are the study's reason for existing. Everything in §2 is a *loud* failure: a missing identifier a user would see. The three findings below produce **no error at any stage**. The DDL deploys, `ts snowflake lint-ddl` returns `[]`, `ts tml lint` is clean, `build-model` reports `lint_findings: []`, and the query comes back with a number that is wrong.

Each fires on the construct its pattern exists to demonstrate. Two of the three were found only because a probe went looking past a louder failure.

### 3.1 W1 — ASOF join: $5,100 against a true $2,100, and both legs are wrong differently

`asof_join` resolves each order against the customer address that was current *at order time*. Query 1 asks revenue by zip.

| Q1 revenue by zip | 90001 | 90002 | 90003 | 90010 | **total** |
|---|---:|---:|---:|---:|---:|
| stage A — original SV (ASOF) | **300** | **700** | **500** | 600 | **2,100** |
| stage C — regenerated RT (equi) | 1,500 | 1,500 | 1,500 | 600 | **5,100** |
| stage C — regenerated RTF (equi) | 1,500 | 1,500 | 1,500 | 600 | **5,100** |
| stage B — ThoughtSpot Model (`>=`) | 1,500 | 1,200 | 500 | 600 | **3,800** |

Stage A matches the corpus oracle exactly (`90001 $300 · 90002 $700 · 90003 $500 · 90010 $600`), so the baseline is not in question. Mary's entire $1,500 is attributed to **each** of her three historical zips. That is verbatim the mistake the corpus wrote the pattern to prevent.

The verdict is **`NUMERIC_DIFF`, not `ERROR`** — the regenerated view answers the query and gets it wrong. It is the only scored wrong-answer cell in the whole study on the RT leg, and it is the sharpest of the three findings precisely because it did not need a probe to find.

The two legs fail by different mechanisms, which is what three-stage attribution buys:

- **Inbound.** The Model emits exactly what coverage-matrix row 9 promises — `[ORDERS::O_CUSTID] = [CUSTOMER_ADDRESS::CA_CUSTID] and [ORDERS::O_ORDDATE] >= [CUSTOMER_ADDRESS::CA_START_DATE]`. The row is an accurate description of the TML. But **`>=` matches every prior address row**, not the latest one, so stage B over-counts to 3,800.
- **Outbound.** The second column of each side is dropped entirely. The regenerated relationship is `ORDERS(O_CUSTID) references CUSTOMER_ADDRESS(CA_CUSTID)`, `join_style: "equi"` on both legs — the ASOF column pair is gone, giving 5,100.

The structural comparison caught this correctly, and it is worth showing why. `asof_join` has two relationships. `addr_to_name` → `customer_address_to_customer_name` kept its endpoint tuple byte-for-byte and is reported **`renamed`** — correctly not a loss. `orders_to_addr` did **not** keep its endpoint, so it is a genuine **`lost` + `added`** pair. **Endpoint-tuple matching catches the ASOF degradation; name matching would have called it a rename and reported no loss at all.**

Artefacts: `.svrt/work/asof_join/results_remediated.json` (verdicts and deltas), `ddl_orig.sql`, `rt.sql`, `rtf_deployed.sql`, `structural_leg_RT.json`.

### 3.2 W2 — `NON ADDITIVE BY` dropped: $5,300 becomes $25,400

`semi_additive_metric` declares `total_balance as SUM(balance_usd) NON ADDITIVE BY (balance_date)` — a month-end snapshot balance that must **not** be summed across dates. The corpus's own README names the failure mode: *"A002 shows $25,400 instead of the correct $5,300."*

`NON ADDITIVE BY` is **absent from the regenerated view on both legs**. `build-sv` has no semi-additive emitter at all; the hand-authored formula file states it outright. Probed directly — same question, each view addressed with its own alias:

| `total_balance` by account, **no date dimension** | A001 | A002 | A003 |
|---|---:|---:|---:|
| original SV | 1,250 | 5,300 | 950 |
| regenerated SV | **5,850** | **25,400** | **4,500** |

The regenerated view returns, silently and without error, **the exact number the pattern was written to prevent** — the sum across all five monthly snapshots.

**This finding is masked by a louder one, and that is the most instructive thing about it.** All five of this pattern's scored `A_vs_C` verdicts are `ERROR`, for an unrelated reason: `build-sv` does not preserve the Semantic View's table alias. The original declares `tables ( BALANCES as ACCOUNT_BALANCES )` and every corpus query addresses `balances.*`; the regenerated views expose `ACCOUNT_BALANCES.*`, so all ten stage-C calls die on `invalid identifier 'BALANCES.…'` before any of them reaches the semi-additivity. **Repairing the alias rename would convert five loud errors into five silent wrong answers.**

The inbound leg, by contrast, is correct: coverage-matrix rows 21/22 are **confirmed exactly** — `NON ADDITIVE BY (col)` → `last_value(sum(...), query_groups(), {[BALANCE_DATE]})`, live-confirmed here for the first time. The semi-additivity survives into ThoughtSpot and cannot get back out.

Artefacts: `.svrt/work/semi_additive_metric/NOTES.md`, `formulas.json` (which records the missing emitter), `leg_RT.sql`, `leg_RTF_verbatim_exec.log`, `oracle.json`.

### 3.3 W3 — fixed `PARTITION BY` dropped: year-to-date becomes a lifetime total

`window_metrics` declares a year-to-date cumulative revenue:

```sql
SUM(total_revenue) OVER (PARTITION BY daily_sales.year ORDER BY daily_sales.date
                         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
```

`translate-formulas` emits:

```
cumulative_sum ( [DAILY_SALES::total_revenue] , [DAILY_SALES::sale_date] )
```

**The partition is gone.** Year-to-date becomes a lifetime running total. There is no annotation and no warning. Located in `tools/ts-cli/ts_cli/sv_translate.py::_translate_window`: **`partition` is bound to a local and read only on the non-framed `group_*` fall-through** — the `cumulative` and `moving` branches ignore it, and only `order[0]` survives.

This contradicts two of the repo's own authorities at once. The shared mapping doc's decision table routes `PARTITION BY dim1 ORDER BY dim2 ROWS UNBOUNDED PRECEDING` to `moving_sum(group_aggregate(…, {[T::dim1]}, query_filters()), -1, 0, [T::dim2])` and then states the rule explicitly: *"**Flag the fixed-partition case for review** rather than emitting it silently. The formula compiles … which is exactly what makes the divergence dangerous — nothing errors."* Coverage-matrix row 25 prescribes the same `moving_sum` form. **Neither happened.**

Two qualifications, both honest:

- **The window frame itself is not the problem.** A direct numeric test against a hand-repaired diagnostic view that carries the expression through `build-sv --formulas` returned **all 35 rows identical to the original**, first row and last row included. The frame and the fixed partition survive byte-for-byte and numerically when the expression is carried through. They do **not** survive the automated `translate-formulas` path. So the "frame silently widens" hazard that coverage-matrix row 28 might have implied does **not** materialise here — the partition widens on the ThoughtSpot side, and the metric is dropped before the frame can.
- **The wrong number reaches ThoughtSpot, not the regenerated Semantic View.** This one is an *inbound* finding: the mis-translated formula lands in the Model, and the Model's phase-2 formula import then failed on this pattern, so no corpus query scored against it. It is no less real for that — the same `_translate_window` code path serves every window metric on every conversion.

Artefacts: `.svrt/work/window_metrics/NOTES.md`, `skipped.json`, `structural_rtfq.json`, and the deployed diagnostic `DAILY_SALES_SV_RTFQ3`.

### 3.4 What the three have in common

| | W1 ASOF | W2 `NON ADDITIVE BY` | W3 fixed `PARTITION BY` |
|---|---|---|---|
| `parse-sv` | exit 0, `unsupported: []` | exit 0 | exit 0 |
| `translate-formulas` | no skip | no skip | no skip |
| `build-model` | `lint_findings: []` | `lint_findings: []` | `lint_findings: []` |
| `lint-ddl` on the emitted DDL | `[]` | `[]` | n/a |
| Snowflake accepts the regenerated DDL | yes | yes | n/a |
| Error anywhere | **none** | **none** | **none** |
| Wrong by | +143% | +379% | unbounded (grows with history) |
| Found by | a scored verdict | a probe past a louder error | reading the emitted formula |

**Two of three were invisible to the scored verdicts.** That is the finding behind the findings: a fidelity harness that only counts `EXACT` will under-report this class, because a loud unrelated failure upstream shields the silent one downstream. The study's own headline number, 8 of 44, is the *optimistic* reading — it counts a query that dies on a missing identifier and a query that returns $25,400 for $5,300 as the same kind of miss, when only one of them would ever be noticed by a user.

---

## 4. Per pattern

### 4.1 `accumulating_snapshot` — blocked, and the gate is right

**`build-model` exit 1, `import_status: "not_imported"`:**

> `LINT: I14: 'AS_LOAN_APPLICATIONS' joins 'AS_DIM_DATE' 4 times (APP_TO_APPLICATION_DATE, APP_TO_REVIEW_DATE, APP_TO_DECISION_DATE, APP_TO_FUNDING_DATE) — the join path is ambiguous and ThoughtSpot will not load the Model. Give each role its own aliased model_tables entry (name: the physical table, alias: a unique per-role id) and point one join at each.`

The pattern's entire premise is one date dimension serving four roles, and the gate refuses it. The lint is **correct and its message is a complete recipe** — but `build-model` does not perform the aliasing its own message prescribes, even though it demonstrably *can*: it does exactly that for `role_playing_dimensions` (§4.8). Two roles it handles; four it refuses.

Six of the nine metrics had already been dropped upstream (§2.4), so even a repaired Model would have carried none of the funnel. Skip list: 6 — all `USING`-scoped. Oracle: **5 of 5 queries oracled, 4 EXACT and 1 row-count difference** (§9). No outbound leg, no structural comparison.

### 4.2 `ai_metadata` — the best pattern in the study, and it has no oracle

The cleanest case: never renamed, never re-run, colliding with nothing. `A_vs_C` **RT 2/3 · RTF 3/3** — the only pattern to reach a perfect leg. Skip list: 0.

The single RT error is `invalid identifier 'AI_ORDERS.ORDER_MONTH'`: the unaided leg drops every formula and `order_month` is one. Hand-supplying it restores the query completely.

Structural: **RT 10 in / 8 out / 5 verified / 3 unverifiable / 2 lost / 1 renamed; RTF 10 / 10 / 7 / 3 unverifiable / 0 lost / 1 renamed.** Caveats on both legs: `tables` survival is **name only**; dimensions **3 of 4 UNVERIFIABLE** (§1.10 item 1); `facts` **NOT_MEASURED**.

**The whole AI block is absent from both legs and is counted by no rollup row** — two instruction clauses and two verified queries. Two matrix contradictions come out of this pattern (§5, rows 30 and L1). And it ships **no oracle**, so its position at the top of the table establishes that three engines agree with each other, not that any is right.

### 4.3 `asof_join` — see §3.1

`A_vs_C` **RT 0/3 · RTF 0/3**. Skip list: 0. Structural RT 5/11, RTF 7/11; the relationship section is the instrument working as designed (1 verified, 1 lost + 1 added, 1 renamed).

Three things this pattern surfaced that no rollup row sees: both relationships dropped `type=LEFT_OUTER, cardinality=MANY_TO_ONE`; `Orders UNIQUE (o_ordid)` is absent from both legs; and `Orders.order_count` **changed kind** — a metric in the source, a raw `dimensions()` entry on both legs. ThoughtSpot itself demoted it: built as a `MEASURE`, it re-exports as an `ATTRIBUTE` because `o_ordid` is `VARCHAR(10)`, which also puts it outside the name map (`unclassified: ['Order Count']`) and would make it stage-B `UNAVAILABLE` for any query using it.

### 4.4 `entity_facts` — the entity-level aggregated fact is unrecoverable

`A_vs_C` **RT 0/4 · RTF 1/4**. Skip list: 0 — all five formulas translated, including the `CASE`.

Q1–Q3 fail on both legs with `invalid identifier 'CUSTOMERS.VALUE_SEGMENT'`, and this is a **genuine and unrepairable** loss. `value_segment` is a `CASE` over `customers.lifetime_value`, a **PRIVATE entity-level aggregated FACT**. `build-sv` has no `FACTS` emitter and `--formulas` offers only `kind: metric|dimension`, so it has no expressible outbound form. Both candidate hand-authored forms were tried and **both were rejected by Snowflake**: inlining the aggregate into the dimension, and referencing the metric by name — the latter pushing the identical `invalid identifier` onto the metric, because a metric on the customers table may not aggregate the orders table's column. **Only a FACT may.**

Q4's RTF `A_vs_C` is **EXACT** (`Bob Chen 900/1`, `Alice Martin 4200/4`): hand-supplying the `order_amount` fact as a dimension fully restores a `WHERE` on a per-order fact, which the unaided leg loses. Structural: RT 6/13, RTF 8/13; both facts lost on both legs; metrics survive fully. `facts` reads `PARSE_INCOMPLETE` from a phantom (§5, N2).

### 4.5 `fact_as_relationship_key` — expression and join do not agree

**`build-model` exit 1, lint clean, ThoughtSpot rejected the import:**

> `Error while translating 1st join of SALES . Could not find column: SALES::FISCAL_QTR_KEY.`

The converter translated the fact's expression **correctly** into a formula column — `concat ( to_string ( year ( [SALES::sale_date] ) ) , '-Q' , … )` — and, independently, emitted the join as `on: "[SALES::FISCAL_QTR_KEY] = [FISCAL_QUARTERS::FISCAL_QUARTER_KEY]"`: a physical column id for a column that exists only as a formula. **Two halves of one construct in incompatible namespaces.** Skip list: 0. Oracle: 1 of 4 queries oracled, and it passes — attainment 43.8 / 44.4 / 35.8 / 36.0 / 42.4 / **53.7**, against the corpus's *"Q1-Q4 2023 at 43-44%, declining late year; Q2 2024 best at 53.7%"*. No outbound leg.

### 4.6 `multi_path_metrics` — the disambiguation is gone three steps before the round trip begins

`parse-sv` exits 0 with `unsupported: []` and `warnings: []`, and returns `expr: null` **with no `using` key at all** for every one of the four `USING`-scoped metrics. `translate-formulas` then skips all four. What reaches the Model is one attribute and one metric — precisely the two constructs that do not exercise the pattern. **And the shape is then refused outright**, exit 1, by lint I14 (the same ambiguous-join-path gate as §4.1).

Oracle **PASS** on both oracled queries (`sunny=2 (2 late), rainy=2 (0 late)`; `rainy=1 (1), sunny=1 (0), cloudy=2 (1)`), so the baseline is sound and the loss is real. No outbound leg.

An off-documented-path `build-sv` probe against the locally generated, never-imported Model TML was **deliberately not attempted**: the four `USING` metrics never reached the Model, so nothing about the pattern could have survived the outbound leg. Recorded so its absence is a decision, not an oversight.

### 4.7 `range_join` — not a weaker join, a nonsensical one

**`parse-sv` drops the range join's equality key.** DDL:

```
ORDERS_TO_SEGMENT as ORDERS(CUSTOMER_ID,ORDER_DATE)
  references CUSTOMER_SEGMENTS(CUSTOMER_ID,between VALID_FROM and VALID_TO exclusive)
```

parsed:

```json
"from_cols":["CUSTOMER_ID","ORDER_DATE"], "to_cols":["VALID_FROM","VALID_TO"]
```

`CUSTOMER_ID` is gone from `to_cols`. **Both lists are still length 2, so nothing downstream can detect the mis-alignment** — the pairing silently becomes `CUSTOMER_ID→VALID_FROM`, `ORDER_DATE→VALID_TO`. Exit 0, `unsupported: []`, `warnings: []`. ThoughtSpot then refuses the import:

> `Error while translating 1st join of ORDERS . Invalid join expression [ORDERS::CUSTOMER_ID] >= [CUSTOMER_SEGMENTS::VALID_FROM] and [ORDERS::CUSTOMER_ID]`

The nuance matters for the pattern's actual question. The converter **did not** degrade the range to an equi join — it emitted a real `>= / <` predicate. But it bound **both endpoints to `ORDERS::CUSTOMER_ID`** (a VARCHAR customer id) and dropped `ORDER_DATE`, the actual range probe. The identical defect appears in `multi_path_metrics` (`references WEATHER(CITY_CODE, between …)` also loses `CITY_CODE`), so it is the **compound** range form — equality column plus range — that the parser mishandles, not one fixture. Skip list: 0 (9/9 translated). Oracle **PASS** on all three oracled queries. No outbound leg.

### 4.8 `role_playing_dimensions` — role playing SURVIVES, and it is the study's best result

`parse-sv` kept both aliases against one FQN; `build-model` emitted two `model_tables[]` entries carrying `alias: ORDER_DATE_DIM` / `alias: SHIP_DATE_DIM` on the same table with one join each; the exported Model TML keys the nine dimension columns by **alias** (`ORDER_DATE_DIM::YEAR` vs `SHIP_DATE_DIM::YEAR`); and `build-sv` emitted both aliases back out. **`A_vs_C` RT is EXACT 4/4**, including the cross-tab query that uses both roles at once and the query whose December order ships in January. **The two roles do not merge.** The pilot's feared alias collapse does not reproduce.

`A_vs_B` is also **EXACT 4/4** after the stage-B recompute (§9) — it read `NUMERIC_DIFF 4/4` before, entirely from the study's own engine.

Two caveats, and they pull in opposite directions. Its structural rollup is **7/17**, of which the shortfall is largely *manufactured*: all 9 role-played dimensions read as lost+added because `parse-sv` takes their identity from the referenced column (§1.10 item 2). And its **RTF leg does not deploy at all** — its only formula is the fact `orders.revenue AS AMOUNT`, and `facts()` is unreachable by construction, so both candidate destinations were tried and both are invalid Snowflake. `A_vs_C` RTF is therefore `ERROR 4/4` on a pattern whose RT leg is perfect. Skip list: 0. Oracle **PASS** on all three oracled queries, including the 8-row cross-tab.

### 4.9 `shared_degenerate_dimension` — a single-instance alias is collapsed, and it breaks every query

This pattern locates §4.8's mechanism precisely. It declares `regions AS region_dim` and references the entity as `regions` everywhere. The round trip returns it under the **physical** name:

```
… .REGION_DIM primary key (REGION)
REGION_DIM.region as region_dim.REGION …
```

`build-model` emits `alias:` **only when two entries share one physical table**. With a single entry the alias is judged redundant — but it is not redundant, because every query written against the Semantic View names it. Result: `invalid identifier 'REGIONS.REGION'` on **five of the six real corpus queries, on both legs**. This is `semi_additive_metric`'s `balances` → `ACCOUNT_BALANCES` defect reproducing, and the pair of patterns pins the trigger: **alias preservation is a side effect of needing disambiguation, not a goal.** Role playing survives because it *forces* the aliasing; a plain renamed entity does not, and is silently de-aliased.

**Query 7 is a tautology and must never be counted.** It targets a *different* semantic view — the inline-SQL sibling both created by the one `semantic_view.sql`. The stage-C rewriter substitutes only the FQN it was given, and the inline view's name does not contain the original's as a substring, so q7's stage C **re-ran stage A's statement against stage A's own view** and read `EXACT` by construction. Confirmed, not merely suspected. **Published figure: 1 genuine EXACT (q5, the only real query that never names `regions.`) of 6 real queries, 5 ERROR.** This is not fixable by re-running (§6.3).

**Its stage B is not a tautology — it is a duplicate, which is a different defect with the same exclusion.** q7's stage B is a real AgentQL call against the Model, so nothing there is circular. But q7's `(DIMENSIONS, METRICS)` tuple is **identical to q4's**, so `to_agentql` emitted a **byte-identical statement** against the same Model and it returned the same rows (`stages_capture.json`, verified for this report). It measures nothing q4 did not. **q7 is therefore excluded from the stage-B figure as well** — which is what makes §6.3's E4 claim, "excluded from every published figure", true; before this correction the `A_vs_B` headline carried q7 in both numerator and denominator.

This pattern also exists to test that a dimension name appearing on two fact tables is not collapsed by a naive list comparison, and it verified that the comparator handles it: `dims lost: ['regions.region', 'store_orders.order_month', 'web_orders.order_month']` — two distinct qualified keys, both reported. A bare-name set comparison would have shown one `order_month` and hidden one of the two losses.

Two input reconciliations `build-model` required, neither automated:

- **The flat-namespace collision.** `store_orders.order_month` and `web_orders.order_month` are distinct in the Semantic View and collide in the Model; `build-model` exits 1 and points at the skill's Step 8.5. Applying its option A produced the title **`Order Month  Web` with a double space**, exactly as Step 8.5's own step 4 predicts — and its prescribed fix is to post-process the Model TML, **which `build-model --profile` gives no opportunity to do because it builds and imports in one shot. The documented remedy is incompatible with the documented command.** The double space propagates into the formula id and out again as `order_month_web`.
- **Physical column case.** This corpus writes physical references in lower case (`REGIONS.REGION as region`, `SUM(amount)`), which is valid Snowflake. `build-model` copies the DDL's right-hand side verbatim into every `column_id` and join token, and ThoughtSpot's join translation is case-sensitive: `Could not find column: REGION_DIM::region.` The skill's own SKILL.md states the rule the command does not implement.

### 4.10 `tags` — `WITH TAG` does not just fail to map; it destroys every metric it annotates

`parse-sv` has no tag field and **does not drop the clause** — it folds the whole `WITH TAG (...)` text into the metric's `expr`, with `unsupported=[]` and `warnings=[]`. The resulting `expr` is not valid SQL, so `translate-formulas` skips **all five metrics**. `build-model` then **exits 0** and imports a Model whose `measures` list is **empty**.

A Snowflake governance annotation with no ThoughtSpot equivalent takes the business logic with it, silently, **with a success exit code**. The one corpus query is `UNAVAILABLE` at stage B (nothing to query) and `ERROR` at stage C. Its RTF leg is content-identical to RT because no formula column exists for the formula file to attach to — and that identity is itself the finding. Structural 5/12 on both legs. Skip list: 5 of 7.

### 4.11 `time_intelligence` — a computed FACT used as a join key breaks the forward leg outright

`build-model` emitted the fact as a model-level formula column (`formula_id: formula_Sale Month Shifted Ly`) and the join predicate against a **physical** table column (`[FACT_SALES::SALE_MONTH_SHIFTED_LY] = [DIM_CALENDAR::MONTH]`) — the same two-namespaces defect as §4.5. Result, with `lint_findings: []`:

```
"import_status": "failed", "model_guid": null,
"import_error": "Error while translating 1st join of SALES_LY . Could not find column:
FACT_SALES::SALE_MONTH_SHIFTED_LY. …"
```

Phase 1 never landed, so unlike the other two `build-model` failures in group C **there is no Model on the cluster at all**. Skip list: **0 of 15** — every formula translated, and the Model still could not import. Neither leg deployed, so its five queries are unmeasurable and excluded from the study's denominators, and both its structural rollups carry the † marker.

Two other observations from this pattern: coverage-matrix row 39/BL-180 is **reproduced exactly** (`DIV0` → `safe_divide` in all four ratio metrics, `annotations: []`, no flag); and the single-use alias `CALENDAR as DIM_CALENDAR` did not survive while the role-played `SALES`/`SALES_LM`/`SALES_LY` did — §4.9's rule again.

### 4.12 `variables` — invisible to the parser, and their references resolved onto fake columns

No `variables` key in `parsed.json`; `unsupported=[]`. `translate-formulas` then reports **8/8 translated, 0 skipped** — a false success (§2.4). The failure surfaces two steps later as *"Formula addition failed. Formula: Price Tier, Error: Search did not find \"PRODUCT_SALES::premium_threshold ) then 'premium' else if (\""*, and on the return leg as *"Value was provided for variable 'PRICE_WEIGHT' but no such variable is defined."*

`build-model` phase 1 imported and phase 2 failed, so the Model exists and carries no formula columns. RT deploys and returns `ERROR 5/5`; RTF does not deploy. q5's stage A fails on the original view (§1.8), so four of its five queries are converter-attributable and one is not. Structural 3/9. Two `classify-columns` wrapper contradictions (`Total Sales` COUNT→SUM, `Avg Rating` AVERAGE→SUM).

### 4.13 `window_metrics` — see §3.3, and row 28's missing fixture is now run

`A_vs_C` **0/5 on both legs**; q3 and q4's stage A fails on the original view (§1.8). Skip list: 2. `build-model` phase 1 imported, phase 2 failed. Structural 3/11.

**Coverage-matrix row 28's conceded gap is now closed with a live fixture.** Of three window-metrics-referencing-metrics: **0 of 3 survive** — two skipped at translate (`PARTITION BY EXCLUDING` mis-parsed as a table alias; `LAG` unmapped) and one rejected at Model import. The row's optimism (*"shares row #26/#27's resolver, so the BL-178 fix covers it"*) is not supported. But the failure is **not** frame widening: §3.3 shows the frame and the fixed partition survive byte-for-byte and numerically through `build-sv --formulas`.

A second reason the unqualified emission is fatal here, bisected across five probe views: for a **window** metric, the sole difference between failing and deploying was qualifying the *metric* name — unqualified, `SUM(total_revenue) OVER (…)` cannot resolve its base metric (`invalid identifier 'TOTAL_REVENUE'`). That is the corpus README's own gotcha #5, verbatim.

### 4.14 `derived_metrics` — the pilot's worst-looking pattern is, at the ceiling, tied for the best

`A_vs_C` **RT 0/4 · RTF 2/4**. Skip list: 3.

Its four losses split into **two different legs with two different causes**, which is exactly what the three-stage design exists to separate. The three `*_PCT_OF_TOTAL` metrics were lost **inbound** — `translate-formulas`: *"no table for bare identifier 'total_revenue'"*. `total_revenue` survived inbound as a live formula column and was lost **outbound** — `build_sv.log`: `SKIPPED formula 'Total Revenue': not in translated_formulas`. Conflating them would misreport the study. Metrics surviving: 3 of 7 (RT), 4 of 7 (RTF); the other 3 are an inbound loss identical on both legs.

Structural RT 10/17, RTF 11/17. Three relationships kept their endpoints and each dropped `type=LEFT_OUTER, cardinality=MANY_TO_ONE` — **not measured** by any row, since relationships are matched on endpoint only. Its stage-B cells are `UNVERIFIABLE` (§1.10 item 4). Oracle absent; stage A tied to `seed_data.sql` arithmetic instead (month 1 → 5000+2000+1000 = 8000; all six months tie out) — a weaker guarantee, reported as such.

**This pattern refuted the study's sharpest prediction.** Coverage-matrix row 27 / BL-194 says a same-table metric-on-metric reference dangles, I13 fires, and `build-model` **exits 1** — *"Fails loudly rather than emitting a broken Model."* Reality: `build-model` exited **0**, `import_status: "imported"`, `lint_findings: []`. The three metrics were dropped **one stage earlier** by `translate-formulas`, so nothing dangling ever reached TML assembly and I13 could not fire. A silent-ish declared skip, not a loud stop (§5).

### 4.15 `semi_additive_metric` — see §3.2

`A_vs_C` **0/5 on both legs**, and `--formulas` cannot move it: the table-alias rename blocks every query upstream of formulas. Skip list: 0. Structural **0 of 7 verified on either leg** — and the zero is honest, not an artefact. Construct identity is `alias_table.alias_name`, so the single alias rename detonates every row into a matched lost+added pair; decomposed:

| What actually happened | Verdict |
|---|---|
| table alias `balances` → `account_balances` | **real loss** — every query written against `balances.*` breaks |
| 3 dimensions, same columns, new alias prefix | consequence of the above |
| FACT `balances.balance_usd` → metric `account_balances.balance_usd_fact` | **real change of kind.** No `FACTS` emitter; the fact returned as a metric and had to be renamed to stop it shadowing the physical column |
| `total_balance` `SUM(…) NON ADDITIVE BY (…)` → plain `SUM(…)` | **real semantic loss** — §3.2 |
| `PRIMARY KEY (BALANCE_ID)` present, absent in regenerated | **real loss, not measured** by any row (`tables` basis is name only) |

A rename-matching heuristic was proposed during the study and **rejected**: it would have manufactured survival over two genuine defects (§9). Two metrics are additionally emitted **unqualified** (`alias_table: None`) — degraded into derived metrics, which is the `010271` Snowflake rejection its RTF leg hit. Oracle: 4 of 5 queries oracled, **all PASS**, re-verified live.

### 4.16 `multi_fact_table` — the only pattern with a clean unaided round trip

`A_vs_C` **RT 1/4 · RTF 2/4**, and the only pattern where both legs deploy exactly as emitted. Skip list: 2 (`net_revenue`, `store_share` — both lost inbound, both for `derived_metrics`' reason: a derived metric referencing another derived metric by **bare** name). `total_gross_revenue`, which references two **table-qualified** metrics, survived both legs — and that contrast is what settles the real discriminator (§5).

Structural RT 17/26, RTF 18/26 — the highest in the study. All six relationships dropped `type`/`cardinality`, unmeasured. q3 (return rate by product) passes on both legs: raw measures only, no derived metric, no non-additive semantics. **Both its EXACT verdicts are on the plain kind of question**, and the pattern ships no oracle, so they establish three-engine agreement rather than correctness.

---

## 5. Synthesis — every finding against a named coverage-matrix row

`agents/cli/ts-convert-from-snowflake-sv/references/coverage-matrix.md`. **Corrections land in the same PR as this report** — a matrix row proven wrong is edited, not just noted.

### 5.1 Confirms

| Row | Claim | Evidence |
|---|---|---|
| **21 / 22** | `non additive by (col asc/desc nulls last) as AGG(...)` → `last_value` / `first_value(agg(...), query_groups(), {date})` | **Confirmed exactly, and live for the first time.** `semi_additive_metric` inbound. The row is right; the *return* leg has no emitter at all (§3.2) |
| **39 / BL-180** | `NULLIF` guard → `safe_divide`, semantics change silently, `annotations: []` | **Reproduced exactly** — `DIV0` → `safe_divide` in all four `time_intelligence` ratio metrics, no annotation |
| **14 / BL-179** | `build-sv` emits the ThoughtSpot column name as the first synonym | **Reproduced** — `with synonyms=('Date','date','day','sale date')` |
| **4** | PK not written to TML; the reverse leg can only restore a PK some relationship implies | **Confirmed twice** — `asof_join`'s `Orders UNIQUE (o_ordid)` absent from both legs; `semi_additive_metric`'s `PRIMARY KEY (BALANCE_ID)` lost. Both keys a relationship pointed at were restored |
| **13** | Computed dimensions → `formulas[]`, `column_type: ATTRIBUTE` | **True on the forward leg.** The return leg is a new finding (N7) |
| **16 / BL-181**, *second half only* | "every fact returns from the reverse leg inside `dimensions()`, never `facts()`" | **Confirmed** on both fact-bearing group-C patterns, and understated: `build-sv` has **no `FACTS` emitter at all**. The row's first half is refuted below |
| **L1** | `AI_SQL_GENERATION` free text should be parsed and surfaced as candidate Data Model Instructions | **Confirmed impossible today.** `custom_instructions` is `null` for **5 of 5** group-A patterns, every one carrying an `AI_SQL_GENERATION` clause that `GET_DDL` round-trips verbatim. `sv_parse.py:118` requires an `=` that Snowflake's syntax — authored *and* `GET_DDL` — does not have. **15 of 25 corpus patterns carry the clause; 16 occurrences; zero with `=`.** Silently dropped, no warning. One-line fix |
| **L7** | Formulas referencing `[TABLE::COL]` fail on initial CREATE, succeed on UPDATE | **Confirmed operationally** — the two-pass import was mandatory on every pattern that imported |

### 5.2 Refutes

| Row | Claim | What this study found |
|---|---|---|
| **16 / BL-181**, *first half* | facts → `formulas[]` **ATTRIBUTE only**; `sv_translate.py:454-468` hardcodes it; consequence "quantities/prices/profits are declared to Cortex Analyst as categorical dimensions" | **STALE — confirmed three times independently, on three groups, and now with the rule.** Facts are typed by their **data type**: four numeric facts across three patterns (`entity_facts.order_amount`, `entity_facts.lifetime_value`, `accumulating_snapshot.requested_amount`, `.funded_amount`) come back **`MEASURE, aggregation: SUM`**; the one string-valued fact (`fact_as_relationship_key.fiscal_qtr_key`, a `CONCAT`) comes back `ATTRIBUTE`. `fact_column_type()` exists at `sv_naming.py:94`, the fix landed in commit `afabc0e`, and the row's cited line numbers now point at unrelated code. **A documented limitation that was fixed without the doc being updated — a matrix correction, not a backlog item.** |
| **27 / BL-194** | same-table metric-on-metric dangles, I13 fires, `build-model` **exits 1** — "fails loudly rather than emitting a broken Model" | **Refuted twice, and the real discriminator is different in kind.** `derived_metrics`: exit **0**, `imported`, `lint_findings: []` — the three metrics were dropped one stage earlier by `translate-formulas` (*"no table for bare identifier 'total_revenue'"*), so nothing dangling reached TML assembly. `multi_fact_table` refuted it again on a **cross-fact** shape: `NET_REVENUE` and `STORE_SHARE` failed with the same bare-identifier message while `TOTAL_GROSS_REVENUE`, which references two **table-qualified** metrics, survived by inlining. **The discriminator is qualification, not same-table-ness**, and the failure mode is a declared skip, not a loud exit. The row is wrong on both the trigger and the consequence |
| **3** | "Table aliases (explicit + implicit) → `model_tables[].name`", no caveat | **Needs the caveat.** An alias survives **only when two entries share one physical table**. Single-instance aliases are dropped for the physical name: `regions AS region_dim` → `REGION_DIM`, `BALANCES AS ACCOUNT_BALANCES` → `ACCOUNT_BALANCES`, `CALENDAR as DIM_CALENDAR` → `DIM_CALENDAR`. Every query addressing the alias then fails. Three patterns, three independent reproductions |
| **8** | `references TABLE(between START and END exclusive)` → `joins[].on` with `>=`/`<` | **Accurate only for the bare form.** The **compound** form `references TO(COL, between S and E)` — what both range-carrying fixtures use, and what a range join normally needs — loses its equality column at `parse-sv` and is emitted with **both endpoints bound to the same wrong column**. ThoughtSpot refuses the import. Recorded as a limitation nowhere |
| **9** | `references TABLE(COL1, ASOF COL2)` → `joins[].on` with `=` on COL1, `>=` on the ASOF col | **Text accurate, meaning misleading — and this is the study's sharpest finding (§3.1).** The from-direction emits exactly that, so the row describes the TML correctly. It is wrong as a statement of *coverage*: `>=` matches every prior row where ASOF matches only the latest, so the "mapped" construct returns **materially wrong numbers with no error** (3,800 against a true 2,100 at stage B). The to-direction, which this matrix does not cover, is worse — the ASOF pair is dropped and the join becomes a single-column equi join (5,100). A reader planning a migration would take row 9 as "ASOF is handled" |
| **24** | `PARTITION BY EXCLUDING` → `group_aggregate(… query_groups()-{dim})` | **Not implemented for a qualified dimension reference** — *"unknown table alias 'EXCLUDING daily_sales' in reference 'EXCLUDING daily_sales.date'"*. The construct maps to nothing |
| **25** | `ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW` → `moving_sum(group_aggregate(…, {[T::dim]}, query_filters()), -1, 0, [T::order_col])` | **Refuted — §3.3.** Emits bare `cumulative_sum(inner, order_col)` and **drops a fixed `PARTITION BY` with no flag**. Contradicts the shared mapping doc's decision table *and* that doc's own explicit "flag the fixed-partition case for review" rule |
| **26** | metric-on-fact → `average([formula_<id>])`; a **passthrough** fact is a `columns[]` entry so the reference resolves to `[TABLE::col]` | **Premise contradicted** — the passthrough fact became a `formulas[]` entry, not a `columns[]` entry. Consequence untested |
| **28** | "shares row #26/#27's resolver, so the BL-178 fix covers it; **not exercised on a live fixture**" | **Now exercised, and the optimism is not supported: 0 of 3 window-metrics-on-metrics survive.** Two skipped at translate, one rejected at Model import. But the frame itself survives byte-for-byte and numerically (§3.3), so row 28's failure is **not** frame widening |
| **30** | `ai_verified_queries (...)` → NLS Feedback TML (`REFERENCE_QUESTION` entries) | **Contradicted, via a defect that is in no row.** `ai_metadata`'s `GET_DDL` carries both verified queries in full; `parsed.json` carries `verified_queries: []` and the top-level `comment` as an **empty string**. See N2 |
| **L3** | `ACCESS_MODIFIER: PRIVATE` — "omit private facts/metrics; or include with `index_type: DONT_INDEX`" | **Applied to nothing.** `customers.lifetime_value` was included as a fully public, queryable `MEASURE`. It does carry `DONT_INDEX` — but so does the non-private `Order Amount`, so that is fact handling, not a response to the marker. `is_private: true` is parsed and then unused |

### 5.3 New — no matrix row, mapped or unmapped

| # | Construct / behaviour | Severity and evidence |
|---|---|---|
| **N1** | **`USING (relationship)` on a metric** | **Absent from the matrix entirely**, and not merely unmapped: dropped **silently**. `parse-sv` exits 0 with `unsupported: []` and returns `expr: null`; all six `accumulating_snapshot` metrics and all four `multi_path_metrics` metrics then land in `skipped[]`. `_DIM_METRIC_ENTRY_RE` expects `TABLE.COL as <expr>` and `GET_DDL` renders `APPLICATIONS.APPLICATION_COUNT using (APP_TO_APPLICATION_DATE) as COUNT(...)`. **The loss is invisible at parse and only becomes visible in the skip list.** It is the defining construct of two patterns and exists precisely to make cross-fact metrics safe |
| **N2** | **`_extract_clause` scans the RAW DDL** against its own docstring, which states it "assumes string literals have already been blanked out" | Fires twice on two different keywords. `ai_metadata`'s `comment='…'` text contains `AI_VERIFIED_QUERIES (pre-approved SQL for common questions)`, so the extractor matched **inside the comment** — reproduced directly: `_extract_clause(ddl, 'ai_verified_queries')` → `'pre-approved SQL for common questions'`. `_extract_top_level_comment` uses the same raw scan and lands past the real `comment=`. The same defect gives `entity_facts`' regenerated views a **phantom** `PARSE_INCOMPLETE` on `facts` — they have no `facts (` clause at all, but the carried-over comment (*"…aggregated **facts (**lifetime_value) used to define…"*) produces one, plus a non-zero exit. **Any Semantic View whose comment mentions a clause name followed by `(` is affected.** This is why row 30 fails |
| **N3** | **`WITH TAG (...)` is swallowed into the metric's `expr`** | New, and **not benign** — §4.10. All five metrics die at translate; `build-model` exits **0** and imports a Model with an empty `measures` list. A silent, total loss with a success exit code |
| **N4** | **Unnamed relationships are dropped** | `FROM(FK) references TO` without a relationship name is valid Snowflake, `GET_DDL` preserves it, and **2 of 5 group-A patterns write it**. `_RELATIONSHIP_RE` (`sv_parse.py:100`) requires `NAME as FROM(cols) references TO(cols)`, so the entry lands in `unsupported[]` and the view parses with **zero relationships**. `build-model` proceeds anyway and emits a joinless Model; ThoughtSpot rejects it with `Schema validation failed.` **Adding a name is the entire fix.** Row 7 spells only the named form; there is no row for the unnamed one |
| **N5** | **`VARIABLES` are invisible to the parser and their references resolved onto fake columns** | New, and **not benign** — §4.12. No `variables` key, `unsupported=[]`, then a **false 8/8 success** at translate. Fatal at Model import *and* at re-deploy |
| **N6** | **`LAG` / `LEAD` map to nothing** | Rows 23–25 stop at `OVER` / `PARTITION` / cumulative. Skipped with *"function 'LAG' is not in ts-snowflake-formula-translation.md"* |
| **N7** | **`build-sv --formulas` emits formula-derived constructs with a bare, unqualified alias** | **Systematic, not incidental: 9 of 12 RTF legs did not deploy as emitted.** The rule, pinned precisely: **an unqualified name is illegal in `dimensions()` always, and illegal in `metrics()` when the expression is a bare physical column** rather than an expression over other metrics — which is why `derived_metrics` and `multi_fact_table` deploy verbatim and nothing else does. Row 13 documents the forward direction and says nothing about this |
| **N8** | **A computed fact used as a join key kills the FORWARD leg** | Row 16 predicts facts return inside `dimensions()` on the *reverse* leg. It does not predict that the *forward* leg emits the fact as a formula column and the join predicate against a physical column id, making the Model unimportable. **Two patterns, independently** (`fact_as_relationship_key`, `time_intelligence`), and `time_intelligence` never got a Model at all |
| **N9** | **All per-column descriptions are lost on the ThoughtSpot round trip** | Confirmed on both `--parse` and raw edoc. The Model-level description survives. Row 15 claims `comment` → `description` is mapped: true **inbound**, does not survive the **return** leg |
| **N10** | **Join `type` and `cardinality` are dropped on every outbound leg** | `DROPPED join attrs on <rel>: type=LEFT_OUTER, cardinality=MANY_TO_ONE` — **22 relationships across 9 patterns, every one that reached `build-sv`** (19 of them on a leg that deployed), counted from the `build_sv` logs under `.svrt/work/*/`. **No rollup row sees it**, because relationships are matched on endpoint only. Same class as the OSSIE review's F1: a join-semantics change with a numeric consequence and no declaring row |
| **N11** | **A lower-cased DDL blocks the import** | `build-model` copies the DDL's right-hand side verbatim into every `column_id` and join token; ThoughtSpot's join translation is case-sensitive. The skill's own SKILL.md states the reconciliation rule; **no command performs it.** Rows 12/18 imply a clean physical-column mapping |
| **N12** | **A `COUNT` metric over a `VARCHAR` key is demoted to an `ATTRIBUTE` by ThoughtSpot** | `asof_join`'s `Orders.order_count AS COUNT(o_ordid)` was built as a `MEASURE`, imported, and re-exported as an `ATTRIBUTE`. It is consequently unclassified in the name map and would be stage-B `UNAVAILABLE` for any query using it; on the outbound leg it emerges inside `dimensions()` as a raw column |
| **N13** | **`build-sv` output is not re-readable by `parse-sv`** | `build-sv` emits `ORDER_DATE_DIM.ORDER_YEAR as order_date_dim.YEAR`; `parse-sv` takes the qualified RHS as the construct's identity. This is §1.10 item 2 — a method limit *and* a converter finding: **the repo's own parser refuses its own emitter's output**, putting the entries in `unsupported[]` while `lint-ddl` passes the same file |
| **N14** | **Step 8.5's documented remedy has nowhere to run** | It tells the operator to post-process the Model TML after `build-model`; `build-model --profile` builds and imports in one call. Its own predicted artifact (`Order Month  Web`, double space) therefore ships, and propagates into the formula id |
| **N15** | **`build-model` refuses an aliasing it can perform** | Lint I14 blocks `accumulating_snapshot` (4 roles) and `multi_path_metrics` (2 roles) with a message that spells out the exact fix, while `build-model` performs precisely that aliasing unprompted for `role_playing_dimensions`. Two patterns lost to a capability the tool has |
| **N16** | **`ts classify-columns` reports `wrapper: SUM` for every `raw_measure`, contradicting the declared aggregation in 7 of 7 non-SUM cases** | Three separate denominators, stated separately because conflating them misreports the finding: **33 `MEASURE` columns** were classified across **11 Models** (10 of which carry measures); **7** of those columns declare a non-SUM aggregation; those 7 sit in **5 patterns** — `Order Count` (COUNT) ×3, `Customer Count` (COUNT), `Total Sales` (COUNT), `Avg Rating` (AVERAGE), `Avg Daily Balance` (AVERAGE). All **33** get `wrapper: SUM`, so the 7 are contradictions and the other 26 coincide. **The defect is confined to one field.** The same dict's `aggregation` field records the column's declared value **correctly** (`COUNT`, `AVERAGE`) and only `wrapper` — the field consumers actually read — overrides it with `SUM`. So the command is not blind to the declared aggregation; it reads it accurately and then contradicts it one key over, which makes this a narrow and cheap fix rather than a missing capability. **A false-PASS risk as well as a false-FAIL one**: `SUM` over an `AVERAGE` column coincides with the right answer on any single-row group. A ts-cli finding, reported rather than worked around — recounted for BL-251 from `.svrt/work/_remediation/classify/*.json` (11 files) |

---

## 6. What the gates did, and did not, catch

### 6.1 Every gate green, every finding survives

| Gate | Result | Findings caught |
|---|---|---|
| corpus DDL deploy | 5 of 16 patterns needed a repair first | — (a corpus signal, not a converter gate) |
| `ts snowflake parse-sv` | **exit 0 on 16 of 16**, `unsupported: []` on the silent-loss patterns | **none of N1, N3, N5, W1, W3.** Every silent loss in this study passes this gate |
| `ts snowflake translate-formulas` | 22 skips across 6 patterns, each declared | the *declared* inbound losses — its skip list is the study's most useful signal. **Missed N5 entirely** (false 8/8) and cannot see W3 |
| `ts snowflake build-model` | `lint_findings: []` on every wrong-numbers pattern; **exit 0 with an empty `measures` list on `tags`** | I14 caught two ambiguous join paths (correctly, if unhelpfully — N15); nothing else |
| `ts tml lint` (I13) | clean | did not fire on row 27's predicted dangling reference, because nothing dangling ever reached it (§5.2) |
| `ts snowflake lint-ddl` | **`[]` on 8 of 8 generated DDLs in group C, four of which Snowflake rejects outright** | **zero.** Its stated remit includes "identifier validity" and "undeclared table references"; it fired zero times when it should have fired four |
| Snowflake `CREATE SEMANTIC VIEW` | rejected 9 of 12 RTF legs | the only gate that catches N7 — and it is not ours |

**Two internal inconsistencies are worth naming as gate findings in their own right.** `lint-ddl` passes DDL that Snowflake rejects, while `parse-sv` on the *same file* puts the offending entries in `unsupported[]` — the repo's own parser refuses its own emitter's output while the repo's own linter blesses it. And `build-model` can exit 0 having imported a Model with no measures at all.

### 6.2 The gate-shaped findings

Three findings are structural, offline and judgment-free — validator-shaped rather than backlog-shaped, which is the preferred exit under the two-bucket rule:

- **`lint-ddl` must reject an unqualified alias in `dimensions()`, and in `metrics()` where the expression is a bare physical column** (N7). Deterministic, and it would have caught 9 of 12 RTF legs before deployment.
- **`parse-sv` must blank string literals and comments before any clause scan** (N2). Four independent raw-text scans were found in the study's *own* engine for the same root cause; `sv_parse.py` has at least one.
- **`translate-formulas` must not resolve a bare identifier onto the default table alias** (N5). It already refuses the qualified form.

### 6.3 Defects in the study's own instrument

Reported, not patched — `.svrt/bin` was frozen before the runs. Recorded here so a reader can judge the numbers and so a successor harness starts from them.

| # | Defect | Impact on published numbers |
|---|---|---|
| E1 | `to_agentql` discarded the wrapper the name map computed and emitted a hardcoded `SUM`, so `AVG`/`MIN`/`MAX`/`COUNT`/`COUNT_DISTINCT` all emitted as `SUM` | **Stage B only.** Found independently by two groups, fixed, and all stage-B verdicts recomputed (§9). `A_vs_C` never passes through AgentQL |
| E2 | `extract_queries.py` split statements on `;` **inside `--` comments**, leaking a comment tail into the next query as bare SQL | 4 of 19 group-A queries corrupted; **query counts never changed, 66 → 66**, so a count-based check would have reported all clear. Both affected patterns were already blocked at `build-model`, so **zero published verdicts depended on them** — but one `expected` list was emptied, which is what made `accumulating_snapshot`'s "oracle PASS 5/5" vacuous for one query. Fixed and re-extracted |
| E3 | A **fourth** raw-text scan (`CLAUSE.finditer` and `split_csv`'s depth counter) ran with string literals kept, so `WHERE d.note = 'see METRICS in the docs'` yielded `metrics: ["in the docs'"]` | Live in the corpus (`variables` carries `analysis_date => '2024-03-31'`) and merely happens to contain no comma, paren or keyword. Fixed; re-extraction is byte-identical on all 16, so it changed nothing |
| E4 | A single `--orig-sv-fqn` cannot express a multi-Semantic-View `queries.sql`, so a query naming a second view that was never regenerated is **silently exempt** from the substitution and reads `EXACT` by construction | **This is `shared_degenerate_dimension` q7** (§4.9). It corrupts **stage C only**. q7's stage B is a genuine AgentQL call — but a **duplicate** one: byte-identical to q4's statement against the same Model, returning the same rows, so it measures nothing twice over. On both grounds q7 is excluded from **every** published figure: the `A_vs_C` **8/44 · 9/44** and the `A_vs_B` **15/44** (§2.3). This row asserted that exclusion while the stage-B headline still read 16/45; the figure was corrected, not the claim. Not fixable by re-running; the fix is to force `sv_fqn != orig_sv_fqn` to `UNAVAILABLE`, and to reject a second query whose emitted stage-B statement is identical to one already scored. **Five corpus directories ship more than one Semantic View, so the shape recurs** |
| E5 | The name map's colmap keys on the bare alias name, so two same-named dimensions on different fact tables map onto **one** Model column | No corpus query uses `order_month`, so **no verdict is affected** — but on a pattern whose queries did, stage B would silently answer with the wrong fact table's column: exactly the false PASS the qualified comparison was built to prevent, one layer up |

Three operational notes on the `ts` CLI, recorded because each cost a cycle: `ts snowflake exec -f` on any file ending in a comment block reports `000900 (42601) … Empty SQL statement` and exits 1 **after** every real statement has run, making exit codes untrustworthy for the deploy step; `ts snowflake lint-ddl`'s positional argument is a **file path**, not DDL text (passing DDL yields `OSError: [Errno 63] File name too long` with a traceback); and `ts snowflake build-model --tables` takes a **path**, not inline JSON, despite its help text. `sv_build_model.py` also reads `fqn`, not `guid`, from the tables map — which matters on a shared cluster, where `ts metadata search` finds 52 tables named `DIM_PRODUCT` and `build-model` dies with `Found multiple data sources with same name`. GUID enrichment of the local tables map is load-bearing, not a nicety.

---

## 7. Recommendation on audit angle 15

**Angle 15 — conversion fidelity, "does converted output produce semantically equivalent results, the same numbers, not just valid-importing TML?" — should be unparked, with this corpus named as its Snowflake fixture. The recommendation is qualified in three specific ways, and the qualifications matter more than the headline.**

`.claude/rules/repo-audit.md` parks angle 15 with a recorded reason: it *"needs live data on both sides to test properly."* This corpus **is** live data on both sides, it ships its own seed data so nothing is synthesised, and it is organised by construct, which is the axis a fidelity angle needs. The exercise produced three wrong-numbers findings — each on a construct the coverage matrix lists as **Mapped** — that no existing gate in this repo can see. That is angle 15's thesis demonstrated rather than argued, and it is the strongest evidence for unparking that exists.

**The three qualifications.**

**(1) Half the corpus cannot vouch for itself.** Eight of sixteen patterns ship **no oracle at all**. For those, agreement between stage A and stage C establishes that two engines agree, not that either is right — and the two patterns that look *best* in this study (`ai_metadata`, `multi_fact_table`) are both oracle-absent. An angle-15 fixture whose pass condition is "A equals C" would report those as clean fidelity when nothing has checked the number. **Any adoption must treat the oracled and un-oracled halves differently**, and should probably start by contributing expected-value comments upstream for the eight that lack them.

**(2) Four of sixteen patterns ship DDL that does not compile.** A fixture that needs five documented repairs before it runs is not yet a fixture; it is a corpus plus a patch set. The repairs here are minimal, recorded, and three of five were re-validated against their own oracles — but they are hand knowledge held in one report. **Adoption needs the patch set committed as part of the fixture**, or upstream fixes, before a second person can reproduce these numbers.

**(3) It measures the from-direction well and the to-direction only as far as the from-direction reaches.** Five of sixteen patterns never produced a Model, so they contributed no round-trip data at all; the RTF ceiling is bounded by the inbound leg by construction; and nine of twelve outbound legs needed a hand repair or could not deploy. As a probe of `ts-convert-from-snowflake-sv` this corpus is excellent. As a probe of `ts-convert-to-snowflake-sv` it is currently gated behind the from-direction's failures, and will stay that way until N7 and the `build-model` blockers land.

**What should be built, and what should not.** The study's own non-goals were explicit — no new repo tooling, no committed harness, no fixture vendored — and that was right for a first pass, because a comparator's requirements were unknown. They are now known, and they are specific: endpoint-tuple matching for relationships (name matching would have scored §3.1's ASOF degradation as a rename and reported no loss); a fourth `UNVERIFIABLE` status so an unjudgeable pair is never counted as survival; `Decimal`-native comparison at 1e-12; per-leg output with no top-level round-trip figure; and stage-C substitution that refuses a query naming a view it did not regenerate. **A rerunnable harness is now a well-specified piece of work rather than a speculative one** — and §6.2's three validators are the cheaper half of the same value, deliverable first and per-PR.

**What would make the recommendation unqualified.** Three specific closures, in this order of value: (a) **oracle coverage** — expected-value comments for the eight oracle-absent patterns (`ai_metadata`, `derived_metrics`, `multi_fact_table`, `shared_degenerate_dimension`, `tags`, `time_intelligence`, `variables`, `window_metrics`), ideally contributed upstream, since without them "A equals C" is not a fidelity pass; (b) **the four non-compiling corpus DDLs** (§1.8) plus `multi_path_metrics`' duplicate-key schema — either fixed upstream or committed as a reproducible patch set, so a second person can reproduce these numbers without holding five repairs in their head; (c) **the five from-direction blockers** — lint I14's refusal to perform the aliasing it prescribes (N15), the compound range join (row 8), `USING`-scoped metrics (N1), computed facts as join keys (N8) and unnamed relationships (N4) — because until they land, five of sixteen patterns contribute no outbound data and the to-direction stays measured only as far as the from-direction reaches. Close (a) and (b) and the corpus is a fixture; close (c) and it is a fixture that exercises both directions.

**One honest caution about scope.** Angle 15 is listed as *"the highest-value external angle"* and this study supports that. But it is also the most expensive: this exercise consumed 102 Snowflake objects across six schemas, 57 ThoughtSpot objects on a shared cluster, four concurrent run groups, eight fix rounds on its own instrument and a full remediation pass — and it produced a document, not a gate. **Unparking angle 15 as a full-sweep angle is justified; running it at the weekly external cadence is not.** Tie it to the full sweep, or to a release, and let §6.2's validators carry the per-PR load.

---

## 8. Routing

Per the two-bucket rule in `.claude/rules/repo-audit.md`: every finding exits to a **permanent automated check** (preferred) or a **dated `BL-NNN`**. Nothing stays as "we noticed this."

**Filed.** `origin/main`'s `docs/backlog.md` ends at **BL-239**; this branch files **BL-240 – BL-261** (22 items). An earlier draft of this paragraph said main ended at BL-229 and that new ids would start at BL-231 — both were already stale when the items were written, which is precisely the failure mode the resolution rule exists for. **Re-check the highest id on `origin/main` immediately before merging** rather than trusting this range: `BL-NNN` is cited roughly a thousand times across the repo, so a duplicated id silently changes what those citations mean.

| Bucket | Findings | Notes |
|---|---|---|
| **`coverage-matrix` — corrected in this branch** | **16 rows edited** — 3, 7, 8, 9, 13, 15, 16, 21, 22, 24, 25, 26, 27, 28, 30, **L1** — plus **4 new rows**: **L12** (`USING`, N1), **L13** (`WITH TAG`, N3), **L14** (`VARIABLES`, N5), **L15** (`LAG`/`LEAD`, N6). N7 lands in row 13, N9 in row 15, N4 in row 7 | Counted from `git diff origin/main` on the matrix file, not from prose: an earlier draft claimed 11 corrections and cited **L3**, which this branch does not touch. The most important single edit is **row 16**: a reader consulting the matrix today is told facts are `ATTRIBUTE`-only, and that has been false since commit `afabc0e`. The next most important is **row 9** — a reader is told ASOF is handled. **Three claims in §5 did not land and are outstanding, each with no matrix row and no backlog item:** §5.2's refutation of **L3** (`ACCESS_MODIFIER: PRIVATE` applied to nothing — the row still reads as it does on `origin/main`), **N10** (join `type`/`cardinality`) and **N11** (physical-column case) |
| **validator promotion** (preferred exit) | **§6.2's three**: `lint-ddl` unqualified-alias check; `parse-sv` literal/comment blanking before any clause scan; `translate-formulas` bare-identifier resolution | All three are structural, offline and judgment-free, and each would have caught a class this study found rather than a single instance |
| **dated `BL-NNN`** | **BL-240 – BL-261**, mapped finding-by-finding in the table below | Six findings this section routes here are **not yet filed** — named under that table, not left implicit |
| **cross-ref, not re-filed** | row 4 and row 38 → **BL-166** (the stash); row 39 → **BL-180**; row 14 → **BL-179**; row 27's correction → **BL-194**, whose characterisation this study refutes | BL-194 needs rewriting rather than closing — the construct still fails, for a different reason and in a different place |
| **`no-action (justified)`** | E3 (fixed, changed nothing) · E5 (no corpus query has the shape; disclosed as a limit) · the five corpus DDL repairs of §1.8 | Corpus defects belong upstream, not in this repo's backlog |

### 8.1 What was filed, against which finding

| Filed | Tier | Finding |
|---|:-:|---|
| **BL-240** | 1 | **W1** — ASOF join wrong on both legs; coverage-matrix row 9 reads as "mapped" (§3.1) |
| **BL-241** | 1 | **W2, first half** — `build-sv` has no `NON ADDITIVE BY` emitter: $5,300 → $25,400 (§3.2) |
| **BL-242** | 1 | **W3** — `_translate_window` drops a fixed `PARTITION BY`; YTD becomes a lifetime total (§3.3) |
| **BL-243** | 1 | **N3** — `WITH TAG` folded into the metric expression; `build-model` exits 0 with an empty `measures` list |
| **BL-244** | 1 | **N5** — `VARIABLES` invisible to `parse-sv`, then a false 8/8 at translate |
| **BL-245** | 2 | **§1.3** — `build-sv` drops every Model formula without `--formulas`, and no documented command produces that file |
| **BL-246** | 2 | **N7** — unqualified formula-derived aliases; 9 of 12 RTF legs undeployable as emitted |
| **BL-247** | 2 | **N13 + §6.2** — VALIDATOR: `lint-ddl` passes DDL Snowflake rejects and `parse-sv` puts in `unsupported[]` |
| **BL-248** | 2 | **N4** — the unnamed relationship form is dropped, giving a joinless Model ThoughtSpot rejects |
| **BL-249** | 2 | **row 8** — the compound range join loses its equality column, both lists staying length 2 |
| **BL-250** | 2 | **N1** — `USING (relationship)` on a metric, dropped silently and absent from the matrix |
| **BL-251** | 2 | **N16** — `classify-columns` sets `wrapper: SUM` on all 33 classified measures, contradicting the declared aggregation in 7 of 7 non-SUM cases while `aggregation` records it correctly |
| **BL-252** | 2 | **§6.3 operational note** — `introspect` emits no `fqn`, so `build-model` collides on a generic table name |
| **BL-253** | 2 | **W2, second half + row 3** — a table alias dropped for the physical name; **masks BL-241** and must not ship before it |
| **BL-254** | 3 | **L1** — `parse-sv` never parses `ai_sql_generation`: the regex requires an `=` the syntax does not have |
| **BL-255** | 3 | **N2 + row 30** — `_extract_clause` scans raw DDL against its own docstring's contract |
| **BL-256** | 3 | **N9** — per-column descriptions lost on the return leg |
| **BL-257** | 3 | **row 16, second half** — `build-sv` has no `facts()` emitter, so a fact block cannot round-trip |
| **BL-258** | 3 | two further `parse-sv` defects on the hand-written-DDL path (implicit `references <table>`; a comment-preceded metric) |
| **BL-259** | 3 | `sv_build_model.py` stamps `aggregation: SUM` on an already-aggregated formula — candidate double aggregation, **UNRESOLVED** |
| **BL-260** | 3 | **row 24** — `PARTITION BY EXCLUDING` maps to nothing when the dimension reference is qualified |
| **BL-261** | 4 | `ts snowflake build-sv --help` cites `ts tml export --output-dir`, which does not exist |

**Six findings this section routes to a dated item are NOT in `docs/backlog.md` on this branch, under any id, and are not absorbed into BL-240 – BL-261.** They must be filed before merge: **N8** (a computed fact used as a join key kills the forward leg, two patterns), **N10** (join `type`/`cardinality` dropped on all 22 relationships that reached `build-sv`), **N11** (a lower-cased DDL blocks the import), **N12** (a `COUNT` over a `VARCHAR` key demoted to `ATTRIBUTE`), **N14** (Step 8.5's remedy has nowhere to run) and **N15** (`build-model` refuses an aliasing it performs unprompted elsewhere). N10 and N11 additionally have no matrix row, so they are currently routed **nowhere at all**. E4 is routed conditionally ("if a harness is built") and is correctly unfiled today.

**The grouping rule, restated to match what was actually filed.** This section originally mandated four groupings; two of them were rejected once the items were written, and the splits are right. **W2 became two items:** BL-241 (the missing emitter — a `build-sv` capability gap) and BL-253 (the alias dropped for the physical name — a naming defect that *masks* BL-241 and also carries `shared_degenerate_dimension` and `time_intelligence`). **N7 and N13 became two items:** BL-246 (the emitter writes an unqualified alias) and BL-247 (the gate that blesses it), because the second is a validator promotion with a different owner and a different exit. One grouping held: **N2 and row 30 are one entry** (BL-255). The fourth — **N8 covering both its patterns** — is untested, because N8 is not filed yet; it should hold when it is. So the rule is: **one entry per root cause *and* per distinct fix owner** — a defect and the gate that should have caught it are two items, not one.

**Not changed in this branch, deliberately:** no converter code, no shared mapping or schema file, and no to-direction coverage matrix. Every behaviour finding is routed, and the six above are named as unrouted rather than counted as done.

**Teardown.** The four run groups wrote four manifest fragments in four different shapes; merging and reconciling them **against the live account** — not trusting them — found **five live objects named by no fragment** (`CUSTOMERS`, `ORDERS`, `CUSTOMER_ADDRESS`, `CUSTOMER_NAME`, `LOAN_APPLICATIONS` — the pre-isolation and pre-rename copies left behind when three patterns moved) that teardown would have abandoned on a shared cluster. The merged manifest now names **all 102 live Snowflake objects** across six schemas (48 tables, 44 semantic views, 1 view, 3 tags) and **57 ThoughtSpot objects**, six entries flagged as deliberately not live. Teardown is a `DROP SCHEMA` of the six schemas plus deletion of the ThoughtSpot GUIDs, and it happens only **after** this report and its refute-briefed review are complete, because it destroys the evidence the report rests on.

---

## 9. Where the study corrected itself

A reader should trust a report that shows its own corrections. Five are material, and two of them are corrections to overstatements by the study's own controller.

**1. The table-collision analysis was wrong, and it destroyed live data.** The pre-flight check used `grep -ho 'CREATE OR REPLACE TABLE [a-z_]*' */schema.sql` — **lowercase-only, digit-truncating, and scanning only `schema.sql`**. It reported "zero collisions among the 16", which is why the design spec put all sixteen patterns in **one** schema. Re-measured properly in Python across every `.sql` file: 32 distinct table names, **two collisions** — `DIM_DATE` (three patterns) and `ORDERS` (four). Every pattern deploys with `CREATE OR REPLACE TABLE`, so a later pattern silently overwrites an earlier one's data with an incompatible shape and **the earlier pattern's stage A then returns wrong rows with no error.**

This fired live, twice. `DIM_DATE` was clobbered mid-run, killing `derived_metrics`' stage A — *the original view* stopped working, not only the regenerated one. And `entity_facts` silently replaced the `ORDERS` table `asof_join` had created six seconds earlier. Two run groups hit the hazard independently and isolated into private schemas **without being told to**. The spec was amended the same day to one schema per pattern with table names unchanged, `asof_join` and `entity_facts` were **re-run end to end** under isolation, and only the isolated numbers are published. The oracle became the contamination test.

It is worth stating what the wrong check cost and what it did not: it cost two full pattern re-runs, one substrate repair, and one pattern's stage-B attribution. It cost **no published verdict**, because the remediation pass recomputed **all 95 `A_vs_C` cells** and found **zero drift** — which independently confirms that no pattern's substrate moved after it was measured.

**2. An early collision remedy contaminated the thing being measured, and was superseded.** The first response was to rename the physical tables (`AS_*` / `AJ_*` / `EF_*`) while preserving every logical alias, so `queries.sql` and the oracles stayed untouched. That kept the *source* side faithful and broke the *return* side: `build-sv` names the regenerated view's logical alias after the ThoughtSpot table, so the rename also renamed the alias the corpus queries address, and stage C became `invalid identifier`. **The remedy was reverted in favour of schema isolation.** One pattern still carries the rename (`accumulating_snapshot`, blocked anyway) and it is disclosed in §1.9.

**3. Stage-B contamination was narrower than the controller briefed.** The brief said five patterns' stage-B verdicts were contaminated by the wrapper defect (E1) and had to be recomputed. On measurement: **all 11 colmaps were already correct** — the name map had preferred the declared aggregation all along, and the defect lived only in `to_agentql`'s hardcoded `SUM`. Five patterns carried the contradiction; **only three had a verdict move**, because `entity_facts` and `variables` fail upstream and the wrapper never reached a comparison. Twelve verdicts moved, all `NUMERIC_DIFF → EXACT`, the largest being `role_playing_dimensions` from **0/4 to 4/4** — a pattern the study had been reporting as an inbound failure was correct all along and the study's own instrument was wrong. Two group predictions were thereby settled by measurement rather than argument.

**4. The `accumulating_snapshot` oracle was overstated — but not in the way predicted.** The controller expected E2's emptied `expected` list to have made the "PASS 5/5" partly vacuous. On re-verification, **all five queries do carry oracle values**: 4 EXACT and 1 row-count difference (the corpus lists an all-NULL row this build does not return, and that row is a corpus artefact — q2 and q3 *do* return their all-NULL rows because their `USING` paths have unmatched source rows and q1's does not). **The genuine vacuity was different: q2 could not be *run at all* before the fix.** The honest statement is "5 of 5 oracled, 4 EXACT + 1 row-count", not "PASS 5/5". `fact_as_relationship_key`'s "PASS (Q1/Q4)" is likewise better stated as "1 of 4 queries oracled, and it passes".

**5. The declared `expr: None` dimension limit was narrower than the study assumed for most of its life**, and one brief's premise about which pattern could test it was **wrong and was corrected by the agent running it**. The limit applies to **passthrough** dimensions only; computed dimensions return with `expr` populated and byte-identical (§1.10 item 1). In the same pass, the *opposite* correction landed: `parse-sv`'s dimension-identity defect means **reported dimension loss across the whole study is inflated** (§1.10 item 2) — a false-FAIL direction, but still a wrong published number, and every dimension figure here carries the caveat.

Four further self-corrections are worth recording briefly, because each was a false number caught before publication:

- A review reported that *"only 42% of the survival matrix is honestly measurable."* That figure was computed on the **raw corpus** `semantic_view.sql` files, which parse badly; this study's pipeline parses `GET_DDL` output, which on the pilot pattern gave `unsupported: 0`. **Pessimistic and wrong for this study**, and it was stopped before it entered the report.
- The engine's headline number was, at one point, **untested**: mutating the driver to compute `A_vs_C` by comparing stage A against **itself** left the suite green at 139 tests. Every round-trip verdict would have read `EXACT` regardless of stage C. All four driver tests handed two or three stages the same rows, so nothing asserted the stages were distinguishable. That mutation is now red.
- **The stage-B loss figure overstated itself by four cells, and the report's own justification document refuted it.** The `A_vs_B` headline read *"16 of the 45 stage-B cells are `UNAVAILABLE` — the construct is not in the Model at all"*, attributing all sixteen to a "declared engine limit". Four of them (`entity_facts` q4, `semi_additive_metric` q1/q2/q5) are declined solely because they carry a `WHERE`, with every predicate column already resolved in the colmap — a **harness scope decision**, and one this repo's own AgentQL skill contradicts with live-verified filter syntax. `.svrt/AGENTQL-SHAPE.md` §3 says `WHERE` on a non-selected dimension *"is expressible"*, and its §4 has no `WHERE` rule at all, so the document cited as justification for all sixteen justifies **two**. Corrected to **12 unaskable, 4 unasked** (§1.10 item 5). This is the study overstating loss — the opposite direction to everything else in this section, and the reason a fidelity report needs a refute-briefed review of its *optimistic* and *pessimistic* claims alike.
- The engine briefly reported *"0 of 7 metrics survived"* on `derived_metrics` when three survived intact — three metrics read as `changed` for **self-qualification only** (`SUM(revenue)` → `SUM(store_sales.REVENUE)`, on a metric that *is* on `store_sales`). A false FAIL, and a wrong headline that would have sent someone hunting a converter bug that does not exist. The normaliser now normalises a qualifier **only** when it matches the construct's own table, with a mandatory test that **foreign** qualification still reports `changed` — that test is what stops the fix becoming a false PASS. And the underlying behaviour (the converter rewriting unqualified column refs into self-qualified form) is recorded as a real observation rather than absorbed silently by the tool built to measure it.

One correction was **refused**, and the refusal is as important as the acceptances. An implementer proposed reporting `semi_additive_metric`'s structural `0 of 7` as *unmeasured* rather than zero, believing it a measurement artefact of a table rename. The premise was checked against real data and resolves the other way: the alias drop and the two unqualified metrics are **two genuine defects**, and a rename-matching heuristic would have **manufactured survival over both**. `0 of 7` is honest and is published with both root causes named.

---

## 10. Scope limits

- **This measures 16 constructs, not Semantic Views in general.** The excluded nine (§1.7) include the whole `sv_diagnostics` negative-test set, row-access policies, caller-rights views, materialisation, inline Semantic Views and scoped datasets. Nothing here generalises to them.
- **Five patterns contributed no round-trip data**, so the outbound converter is unmeasured on ambiguous multi-role joins, compound range joins, `USING`-scoped metrics and computed join keys. Those are exactly the constructs most likely to be mis-inferred.
- **`tables` survival is name-only on every leg**, and no property of a table is compared. `facts` is `NOT_MEASURED` wherever both sides are empty, which is not survival. Relationships are matched on endpoint only, which is why N10 is invisible to every rollup.
- **Six patterns' stage A rests on agreeing with itself across two runs** — oracle-absent, and not given a substitute. They are reported as oracle-absent, never as implicitly correct.
- **One cell of the study is `UNVERIFIABLE`** (§1.10 item 4) and one command would restore it.
- **Four stage-B cells were never asked, not unanswerable** (§1.10 item 5). This study's harness declines every `WHERE` without inspecting the predicate; AgentQL expresses filters and this repo live-verified the syntax. Those four are a limit of the instrument, and a successor harness closes them by calling the resolver it already has.
- **No conversion code was fixed.** Findings are recorded and routed; fixing them is separate work on separate branches. Two of the three wrong-numbers findings have a one-file locus (`sv_translate.py::_translate_window` for W3; the `build-sv` emitter for W2's outbound half), so the routing is not open-ended.
- **The three wrong-numbers findings are measured, not reasoned.** Every figure in §3 comes from a live query against a deployed view, and the two found by probe were probed precisely because the study distrusted a loud upstream failure. Where a claim in this document is reasoned rather than measured, it says so.
