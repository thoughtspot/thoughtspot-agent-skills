<!-- currency: ossie — 2026-08 (apache/ossie @ b5da5d6; core-spec unchanged since 0.2.0.dev0) -->
# What ThoughtSpot could close to become more Ossie-compliant

**Status:** internal review artifact — for ThoughtSpot engineering and product. Not a roadmap,
not a commitment, and **not** for external publication (unlike the two mapping documents it
draws on, this one cites internal paths and internal backlog IDs freely).
**Date:** 2026-07-30 · **Ossie spec version:** `0.2.0.dev0` (apache/ossie @ `b5da5d6`)

**Sources.** Every row below is traceable to work already done, not to opinion:

| Source | What it contributes |
|---|---|
| [ts-ossie-construct-mapping.md](ts-ossie-construct-mapping.md) | Every `lossy→issue` row, every reverse-direction rule **R1–R11**, non-mappings **NM1–NM6**, asks **A1–A8**, verifications **V1–V4** |
| [ts-ossie-function-mapping.md](ts-ossie-function-mapping.md) | 37 `passthrough` rows and the 1 `unmappable` one, rules **E1–E13**, asks **A9–A12** |
| [../reviews/2026-07-29-ossie-converter-learnings.md](../reviews/2026-07-29-ossie-converter-learnings.md) | How other vendors' converters solve the same problems (the `custom_extensions` stash in particular) |
| [../reviews/2026-07-29-ossie-tpcds-fidelity.md](../reviews/2026-07-29-ossie-tpcds-fidelity.md) | Findings **F1–F21** from round-tripping a community TPC-DS fixture — the measured, not reasoned, evidence |
| [../backlog.md](../backlog.md) | **BL-166** (no stash), **BL-170** (string functions live-verified), **BL-171** (emitters fixed 2026-07-30, ts-cli v0.126.1), **BL-186** (the V1–V4 live verifications this document depends on), **BL-187** (the G7 / G13 live verification that corrected this table), **BL-189** / **BL-190** (the two follow-ups the TML census produced) |
| [../reviews/2026-07-30-tml-census.md](../reviews/2026-07-30-tml-census.md) | A 500-document read-only property census of real ThoughtSpot TML on `se-thoughtspot` (2026-07-30) — what the product **actually emits**, versus what our references claim. Source of G14's production evidence, three of the four V-item advances, and 25 undocumented paths. See *How this stays current* |
| [../reviews/2026-07-30-ossie-consolidation-probes.md](../reviews/2026-07-30-ossie-consolidation-probes.md) | The 2026-07-30 window-function probe run (52 `VALIDATE_ONLY` probes, verbatim transcripts) that produced **G15** and moved four function-mapping rows to `passthrough` |

> **Note on the last two rows.** Both are **tracked** in `docs/reviews/`, alongside this
> document's other two evidence sources — so the verbatim probe transcripts and the census
> key-path inventory travel with the repo, and the `T1`–`T4` follow-up labels this document and
> the schema references cite are defined in a file a fresh clone actually has. (They were written
> to an untracked scratch directory first and moved here on review.)

> **See also — and note the corrections.**
> [`docs/gaps/ts-semantic-modelling-gaps.md`](../gaps/ts-semantic-modelling-gaps.md) (2026-09-02)
> places these findings alongside Snowflake Semantic Views and Databricks Metric Views, adds an
> upstream-engagement read, and **records nine claims in this document that did not survive
> re-verification** — chiefly the `custom_extensions` adoption statistic in G1, "stricter than any
> peer" in G2, A1's retracted "Blocking" grade, G12's prose function list, and the V1–V4 paragraph
> below. Read its *Corrections* register before quoting this document externally.

**How to read this.** Three buckets, and the split is the point. Bucket 1 is **ours** — things
ThoughtSpot cannot express that the standard, or another vendor, can. Bucket 2 is **theirs** —
gaps in the Ossie specification we are raising upstream, listed so nobody mistakes an upstream gap
for a ThoughtSpot defect. Bucket 3 is **neither** — things we deliberately chose not to carry,
listed so nobody mistakes a decision for an oversight.

Priority is *impact on interchange fidelity*, not implementation cost, which we are not in a
position to judge.

**Routing, recorded deliberately.** Under this repo's two-bucket rule a finding is not "done"
until it is a permanent check or a dated backlog entry — but the **bucket-1 gaps below are
intentionally left unrouted**, because they are input to a *product* conversation and not repo
work; only the ones that already imply repo work carry an ID (G1 → **BL-166**, G4 → **BL-170** /
**BL-171**). What *is* routed is the set of open ThoughtSpot-side verifications this document
depends on: **V1–V4** are tracked as **BL-186**.

---

## 1. ThoughtSpot product gaps

Rows are in **allocation order**; the `Priority` column is the authoritative ranking, and after
three corrections the two no longer coincide (G7 was demoted to Low, G13 withdrawn, and G15 is a
High added late). "Enables" is the concrete consequence of closing the gap, not a benefit
statement.

**Three rows were corrected and one added on 2026-07-30, all after ThoughtSpot domain review
challenged a claim — and every challenge was upheld.** G7 lost half its scope, G13 was withdrawn
as not a gap at all, G11 lost one of its four items, and **G15** was added because the reviewed
claim turned out to understate a real gap rather than overstate it. The first two are recorded as
**BL-187**; the method throughout was `VALIDATE_ONLY` probing plus export sampling on
`se-thoughtspot` (a 40-model sample for G7, a 500-document property census for G14, and 52 window
probes for G15). Three lessons worth carrying into any future row on this table:

1. A claim of the form "TML has no field for X" must be checked against *what the product actually
   exports*, not only against our own TML references — which are built from import failures and
   are therefore complete on what breaks, not on what exists.
2. **Acceptance under `VALIDATE_ONLY` is not evidence of support** on a Model `columns[]` entry,
   because unknown keys there are silently ignored — only rejection is decisive. Formula **`expr`
   bodies and join `type` values are different**: those are parsed and enum-validated, so both
   acceptance and rejection carry information. Pick the discriminating surface before probing.
3. A **query-time** semantic (G11's corrected item is one) cannot be probed by import validation at
   all. Say so rather than claiming a probe settled it.

| # | Gap | Evidence | What closing it would enable | Priority |
|---|---|---|---|:-:|
| **G1** | **TML has no vendor-extension field of any kind.** There is nowhere in a Table or Model document to park a construct TML does not natively model. | construct-mapping, *The stash is asymmetric* and rule **X9**; the Ossie side has `custom_extensions` (`core-spec/spec.md:420-430`) and ten of the eleven vendor converters use it (dbt is the sole exception) | The round trip stops being one-directional. Today `TML → Ossie → TML` is lossless only because the *Ossie* document holds the stash; `Ossie → TML → Ossie` loses every construct TML cannot express, permanently and unfixably. This is also the single fix for the **45** documented-then-lost limitation rows across the four coverage matrices **BL-166** scopes — the Snowflake and Databricks pairs, 13 + 10 + 10 + 12, counted 2026-08-31. (Nine `ts-convert-*` matrices exist in total, 93 rows; the other five are outside BL-166's scope because their losses are fail-loud, which is the opposite of documented-then-lost. An earlier version of this row said "41 … across our four existing" — the arithmetic was transcribed from BL-166 rather than counted, and "four existing" was never true.) See **BL-166** | **High** |
| **G2** | **One `name` field per column — no identifier-vs-label split.** `columns[].name` is simultaneously the human display name (spaces, mixed case, not a valid SQL identifier), the natural-language search token, and the cross-document reference key. | construct-mapping **ID1**–**ID4** and ask **A5**; measured as fidelity findings **F2** (`sold_year` collapsed to `year`) and **F6** (`display_name` synthesised on 7 of 7 constructs) | Identifiers round-trip losslessly. It also removes two whole defect classes we currently have to engineer around: normalisation collisions when two display names fold onto one identifier (**ID2**), and the forced rename when a model surfaces `orders.status` and `customers.status` (**ID4** — ThoughtSpot requires display-name uniqueness across the *whole* model, which is stricter than any peer) | **High** — but **narrowing**: apache/ossie#287 would add `display_label`, which gives the label half a home and reduces this gap to the identifier half (ThoughtSpot still has no stable identifier distinct from the display name). Track with A5. |
| **G3** | **No key declarations anywhere in TML** — no primary key, no unique key, no join-cardinality assertion on the *table*. | construct-mapping Dataset level (`primary_key`, `unique_keys` rows) and ask **A7**; fidelity **F17** (a composite PK dropped); `agents/shared/schemas/snowflake-schema.md:56-62` shows the peer that has both (`primary_key` and `unique_keys`; the line reference moved in PRs #458/#462/#471/#481) | Keys survive interchange instead of being reverse-inferred from the join graph. Three downstream things become possible rather than heuristic: honest `COUNT(*)` translation (the function mapping's `COUNT(*)` row currently has to pick a column it *believes* is non-null), join-cardinality validation at import, and aggregate-awareness reasoning | **High** |
| **G4** | **No native string-function set.** `trim`, `ltrim`, `rtrim`, `replace`, `lower`, `upper`, `split_part`, `starts_with`, `ends_with` do not exist, and there is **no regular-expression support of any kind**. | function-mapping *String functions* — 11 of 21 rows are `passthrough`, and the four riskiest were live-verified on se-thoughtspot 2026-07-29 (**BL-170**: `Search did not find "trim ("`, same for `replace`, `starts_with`, `ends_with`) | 11 of the 37 total pass-throughs become native. Each pass-through today embeds raw warehouse SQL via `sql_*_op`, which couples the model to one dialect and makes the expression opaque to ThoughtSpot's query planner. This is the largest single-category fidelity win available *by function count* — **G15** is now the larger one by consequence. It has already cost us internally: **BL-171** tracked five `ts-cli` emitters generating the non-existent bare names; resolved 2026-07-30 in ts-cli v0.126.1 (#425) | **High** |
| **G5** | **A Model's own AI configuration is not in its own TML.** Model-scope Spotter instructions and model-scope synonyms have no field in the Model document; only per-column `properties.ai_context` and `properties.synonyms` are in-document. | construct-mapping Semantic model level (`ai_context`, `ai_context.synonyms` rows — both `lossy→issue`) and Dataset level (`ai_context` row) | Spotter configuration becomes version-controllable, diffable, and portable with the model it configures. This is as much an internal gap as an interchange one: a Model's TML today is not a complete description of that Model | **High** |
| **G6** | **No semi-additive / non-additive measure declaration.** ThoughtSpot expresses "do not sum this across time" by choosing a *function* (`last_value`, `first_value`), not by declaring a property of the measure. **Narrowed 2026-07-30:** the *window* half of these functions is fine — `first_value` / `last_value` (and the `*_in_period` variants) take an explicit partition argument and an explicit time axis, all four spellings live-confirmed on `se-thoughtspot`, so the window clause itself round-trips faithfully and is the one exception to **G15**. What is missing is only the **roll-up declaration**: nothing states that the measure must not be summed across the axis. | function-mapping reverse direction, semi-additive row, and ask **A12**; Snowflake carries `non_additive_dimensions`, Databricks has its own form | A snapshot measure (inventory balance, headcount, ARR) can state its own roll-up rule. The current failure mode is the worst available: a silently summed balance sheet, with no error anywhere in the pipeline | **High** |
| **G7** | **A formula-backed column has no declared datatype.** ThoughtSpot derives a formula's type from its expression; nothing in Model TML states it. **Corrected 2026-07-30 — the description half of this gap was wrong and has been withdrawn:** `description` *is* a first-class field on the Model `columns[]` entry and works on a formula-backed entry exactly as on a physical one. | construct-mapping Field level and Metric level (`datatype` rows) — **two** `lossy→issue` verdicts, not four. Live-verified on `se-thoughtspot` 2026-07-30: **63 of 549** formula-backed columns and 1,960 of 4,436 physical columns across a 143-Model property census carry a `description` (72 of 143 Models — the second-most-common optional `columns[]` key on the cluster; the earlier 40-model sample measured 14 of 78, same conclusion at a seventh of the evidence), and ThoughtSpot's own Model TML syntax lists `description` as a `columns[]` key; **zero** of the 78 carry any `data_type`, and no such key exists in the documented syntax for either `columns[]` or `formulas[]` | Metrics carry their type through any interchange. Note this cannot be worked around by a stash even in principle (rule **X9**: the stash can only carry what TML contains), so G1 does *not* subsume it — both are needed. The remaining ask is narrow: a **declared** type on a formula, so a consumer need not re-derive it from the expression | **Low** |
| **G8** | **No time-of-day type, and no offset-aware timestamp type.** The documented `data_type` set has `DATE`, `DATE_TIME` and `VARCHAR` and nothing else temporal. | construct-mapping Datatype map, `Time` and `DateTimeTz` rows (both **declared losses**); function-mapping `TIME '10:30:00'` and `CAST(… AS TIME)` rows, both forced to `sql_date_time_op` | Two of the standard's ten datatypes stop being declared losses. Today a `Time` column becomes a `VARCHAR` (or a `DATE_TIME` with a meaningless date part) and a `DateTimeTz` silently loses its offset — display time zone is an instance/user setting in ThoughtSpot, not a column property | **Medium** |
| **G9** | **One approximate numeric type.** `DOUBLE` serves for both exact-decimal and floating-point intent; there is no fixed-point type. | construct-mapping Datatype map, `Decimal` / `Float` rows (they **collapse** into one another); function-mapping `CAST` target types, `DECIMAL`/`NUMERIC` row | A `DECIMAL(18,2)` currency column stays exact through a round trip instead of becoming floating-point. Also removes an asymmetry that is confusing to explain: `TML → Ossie → TML` is exact, `Ossie → TML → Ossie` is not | **Medium** |
| **G10** | **A fiscal or custom calendar cannot be described in TML.** The calendar is a *Connection-scoped* object created via `POST /api/rest/2.0/calendars/create` (10.12.0.cl+) and backed by a warehouse table; TML carries only `properties.calendar`, a bare name reference. The value vocabulary is not even settled internally. | construct-mapping field-level `calendar` row and verification **V1**; function-mapping fiscal-family row and ask **A11(c)**; `agents/shared/schemas/thoughtspot-model-tml.md` (`properties.calendar`, added 2026-07-30) vs `thoughtspot-sql-view-tml.md:136` (`CALENDAR_TYPE_GREGORIAN`, now marked there as withdrawn-and-unverified after the census found it zero times in 500 documents — which strengthens this gap rather than softening it) | A fiscal model becomes deployable and portable through TML alone. Today a TML package that references a fiscal calendar is silently wrong on any instance whose connection lacks a calendar of that name — and the expression-level `fiscal` argument on `year ( )` / `quarter_number ( )` has no home either, so the loss is two-part | **Medium** |
| **G11** | **Three documented silent-failure behaviours on import.** A root-level `synonyms:` is silently dropped; a nested `guid:` is silently ignored and a *duplicate object* is created; `aggregation: COUNT_DISTINCT` on a physical column silently overrides `column_type` to `ATTRIBUTE`. **Corrected 2026-07-30 — a fourth item has been withdrawn:** this gap previously also claimed "`aggregation` on a formula column is silently ignored at query time". Per ThoughtSpot domain review, 2026-07-30, that is true only when the formula's `expr` already contains an aggregate; on a **scalar** `expr` the column-level `aggregation` **does** apply, and the pairing is a legitimate idiom rather than a silent failure. | construct-mapping rules **R7** (root-level `synonyms:`), **R2** (nested `guid:`) and **R4(b)** (`COUNT_DISTINCT` override) — every one derived from a real import failure, which is why they are rules and not notes. The withdrawn fourth item is retained as a corrected note in **R4(c)**, with the scalar-versus-aggregate split recorded there and in `agents/shared/schemas/thoughtspot-model-tml.md`. Note the corrected behaviour is a *query-time* semantic, which a `VALIDATE_ONLY` import probe cannot test in either direction | Imports fail loudly instead of succeeding wrongly. Each of these currently produces a model that imports clean and then behaves incorrectly, which is strictly worse than a rejected import — and each one is a rule every TML-generating tool must independently rediscover | **Medium** |
| **G12** | **The function tail:** no `date_trunc`, no `TRUNC`, no `MINUTE`/`SECOND` extractors, no `dense_rank`, no `NTILE`, no percentile *aggregates* (`PERCENTILE_CONT` / `PERCENTILE_DISC` / `APPROX_PERCENTILE` — note the window-rank `rank_percentile` **is** native and is what keeps `PERCENT_RANK` `direct`), no population `stddev`/`variance`, no `atan2`, no `count(*)`. Live-confirmed 2026-07-30 for `dense_rank` and `row_number` (`Search did not find "dense_rank ( sum ("`), so this row's rank-family claims are no longer documentation-only. | function-mapping coverage summary. The 37 pass-throughs split three ways: **11** are G4's string functions, **9** are G15's window rows, and the remaining **17** are this tail | Each one removes a `sql_*_op` and its dialect coupling. Individually small; together with G4 and G15 they are the entire remaining gap between today's 74% native coverage of the standard's expression language (108 of 146) and near-complete coverage | **Medium** |
| ~~**G13**~~ | ~~**`FULL_OUTER` is accepted on a Table-level join and rejected on a Model inline join.**~~ **WITHDRAWN 2026-07-30 — not a gap. Both halves of the premise were false.** (a) `FULL_OUTER` is rejected on a **Table-level** join too, with the byte-identical error (14528, allowed values `INNER, LEFT_OUTER, OUTER, RIGHT_OUTER`), so the two contexts do not diverge at all — ThoughtSpot's join vocabulary is the same four values everywhere, as its own TML documentation shows for Models, Views and Worksheets alike. (b) `OUTER` **is** ThoughtSpot's full outer join, so `FULL_OUTER → OUTER` is a rename, not a downgrade, and changes no results. | Live-verified on `se-thoughtspot` 2026-07-30 (both contexts probed, with the other four join types passing as controls in the same documents); semantics per ThoughtSpot domain review, 2026-07-30. The defect was **ours, not the product's**: `thoughtspot-table-tml.md` and `thoughtspot-sql-view-tml.md` documented `FULL_OUTER` as a valid `joins_with[].type` and omitted `OUTER` — both corrected in the same change, and `check_tml.py` extended to gate `table.joins_with[].type`, which it had explicitly exempted on the strength of that wrong documentation (SQL View TML has no validator in `check_tml.py` at all, so that context stays ungated — the reference is corrected but nothing enforces it) | Nothing — the gap was not real | **—** |
| **G14** | **A custom-map geo reference is a GUID** (`geo_config.custom_file_guid`), so it is instance-local by construction. **Confirmed present in production 2026-07-30** by a 500-document TML census on se-thoughtspot: 3 models / 7 columns carry `custom_file_guid`, with `geometryType` ∈ {`POLYGON`, `MULTI_POLYGON`}. | construct-mapping FieldLevel `geo_config` note, rule **X8**, non-mapping **NM1**, verification **V3** (now evidence-backed) | Geo configuration becomes portable. Today a column whose geo role points at a custom map must have that role dropped entirely on export — a GUID cannot be carried into a portable document, so unlike most properties there is not even a lossy path | **Low** |
| **G15** | **A window formula cannot declare its own `PARTITION BY`.** Two different shapes, one gap. **`moving_*` / `cumulative_*`** take a measure, frame offsets and **order** columns — and nothing else: their partition is completed at query time from whatever dimensions the user's search or Answer carries, minus those order columns, so it matches no static `OVER` shape. **`rank` / `rank_percentile`** take a measure and a direction string and nothing else — **no order columns and no frame** — so they are not partitionable *or* orderable by the formula; they are always global over the query's result set. Either way there is no argument slot for a partition, in any spelling. *(New 2026-07-30. The one exception is the semi-additive pair `first_value` / `last_value`, whose partition **is** an explicit argument — an existence proof that the concept fits the formula grammar.)* | Per ThoughtSpot domain review, 2026-07-30, and live-confirmed by **rejection** on `se-thoughtspot` the same day (**52** `VALIDATE_ONLY` probes: 31 accepted, 21 rejected — 13 naming an absent function or token and 8 an arity/type error; the surface discriminates because formula bodies are parsed, proven by 8 negative controls that were each rejected): a partition argument on `moving_sum` / `cumulative_sum` is rejected at the parser (`Search did not find "{"`), and `rank` / `rank_percentile` enforce an arity of exactly **two** — measure plus direction (`Function rank expects only 2 arguments`, for a bare attribute, a `{ [attr] }` list and `query_groups ( )` alike), with `rank` additionally refusing a `group_aggregate` first argument so the partition cannot be smuggled through the measure either. **Note the two shapes are evidenced differently:** for `moving_*` / `cumulative_*` the probes establish the *whole* claim, because the order columns are visible in the accepted signature; for `rank` they establish only that no partition or order argument **exists**. That `rank` is therefore evaluated globally over the query's result set is a **query-time** semantic the probes cannot reach — it is taken from ThoughtSpot's own formula documentation and our formula reference, the same evidence class as **G11**'s corrected item, and it is what keeps the `RANK` row `direct`. Recorded as function-mapping rule **E13**; it is the direct cause of **four rows moving `direct` → `passthrough`** (`LAG`, `LEAD`, the `OVER` clause, window aggregation), which took the coverage split from `112`/`33` (77%) to `108`/`37` (74%). Mirror ask upstream: **A10** | Windowing becomes portable in **both** directions, and the fix is small: an explicit partition argument on the ordered window family, of the kind `first_value` already has. Today the failure is silent and symmetric — an inbound `LAG(x) OVER (PARTITION BY region ORDER BY d)` cannot be expressed natively at all, and an outbound `moving_sum` describes a window whose partition no other tool can see, so the same model returns different numbers as soon as a user adds a dimension. This is the largest fidelity gap in the expression layer by *consequence*, where G4 is the largest by function count | **High** |

---

## 2. Ossie spec gaps we are pushing upstream

Not ThoughtSpot's to fix. Listed so an engineering reader can tell the two apart at a glance,
and so a gap on this list is not filed twice.

**Seven of these are already public; the mapping documents are not.** Corrected 2026-08-31 —
this paragraph previously read *"Nothing on this list has been posted"*, which was false when
written. **A3, A4, A5, A6, A8, A11 and A12** were posted as comments on apache/ossie
discussions #5, #50, #37, #4, #35, #44 and #19 respectively on **2026-07-30 between 02:30 and
02:41 UTC**, each naming ThoughtSpot and citing #285, and each mirrored to the ASF list archive.
Legal approval for external publication was subsequently granted (2026-08-31), so nothing here
is held any longer; the two mapping documents had not been posted at the time of writing and
still had not been as of that date. **Result so far: zero replies in 32 days** — which is the
single most useful datum this document carries about venue choice, and the reason the routing
below is being redone rather than repeated. Each ask's **upstream venue** — the live
discussion thread, converter PR, or new issue it should be raised in — was mapped against
apache/ossie's existing discussion index on 2026-07-30 and is recorded in the `Upstream venue`
column of the two mapping documents' own asks tables, not duplicated here.

| # | Ask (one line) | Status |
|---|---|---|
| **A1** | Add `THOUGHTSPOT` to the closed `Dialect` enum **and** to `SKIP_SQL_VALIDATION` — a ThoughtSpot formula is not SQL | **Blocking.** Every `THOUGHTSPOT` dialect entry fails schema validation until this lands, which blocks the entire reverse direction |
| **A2** | Add a `THOUGHTSPOT` row to the well-known vendor-extension examples table | Open — trivial, cosmetic |
| **A3** | A core `filters` construct, or a documented convention for one | Open — **the highest-value semantic gap found.** Every vendor stashes filters today, and a stashed filter is invisible, so the same model returns different numbers in two tools **Venue corrected 2026-08-31: discussion #342**, not #5. #5 has one comment ever — ours. #342 (`jacobwangxt`, 2026-08-26) proposes model-level and metric-level `filters` from TPC-DS at production scale, with a precedent table and a full spec document, and drew 6 comments in two days plus a dev@ thread. Note it has already produced two positions our A3 text does not answer: that `label: filter` plus `hidden` may cover most of it with no schema change, and that filters should be dataset-scoped rather than model-only. |
| **A4** | Join `type` and cardinality as first-class fields on `Relationship` | Open — every vendor is stashing or re-deriving them |
| **A5** | Confirm whether `field.label` is a display label (our reading, and Databricks's) or a categorisation label (what the prose says) | **Overtaken by apache/ossie#287 (open, updated 2026-08-27).** That PR adds an explicit `display_label` on both `Field` and `Metric`, which — if it merges — answers this against our reading rather than for it: `label` is not the display-name home. Re-grade rather than re-post; what is still worth asking is what `label` then means, on #287. Originally: a clarification, but it decides where G2's display names live |
| **A6** | First-class support for non-equality (range / ASOF / constant) relationships | **Interim guidance received 2026-07-30** — carry them as an extension inside the relationships section, which both mapping documents now do. Ask stays open: an extension is invisible to consumers that do not read our vendor key, and a *pure* range join still cannot be expressed at all (`from_columns`/`to_columns` are required with `minItems: 1`) |
| **A7** | Is deriving `primary_key` from a relationship's `to_columns` acceptable practice? | Open — the answer only matters while G3 is open |
| **A8** | Should the converter guide tell an import converter to validate its *own* Ossie output? | Open — process, not schema |
| **A9** | Define `EXISTS_IN()` (referenced but specified nowhere), and settle whether `DISTINCT` is a general aggregate modifier | Open — the one `unmappable` construct in 146, and only because it cannot be read |
| **A10** | A way to express a *dynamic* window partition (Snowflake's `PARTITION BY EXCLUDING`) | Open — **evidence strengthened 2026-07-30, and the ask is now bidirectional.** Still the largest fidelity gap in the ThoughtSpot → Ossie direction: every `cumulative_*` / `moving_*` carries a dynamic partition implicitly, and `query_groups ( ) ± { attr }` was live-confirmed valid, so the lost construct is real. The **reverse** leg is now evidenced too, and is **G15's** mirror: an Ossie window expression's *static* `PARTITION BY` has no native ThoughtSpot target either (live-confirmed by rejection). Neither side can express the other's window shape |
| **A11** | Fix the date-part vocabulary's edges: the `DAYOFWEEK` base, the function-list/part-list asymmetry, and a fiscal-calendar declaration | Open — **(c) is the mirror of G10**; the two must be read together |
| **A12** | A declaration for non-additive / semi-additive measures, plus a home for the aggregate `Decomposability` classification | Open — **the mirror of G6.** Both sides are missing it, so neither can fix it alone **Venue corrected 2026-08-31: issue #290**, not discussion #19. `MikeNitsenko` (Cube.dev) opened "Spec has no way to declare a non-additive metric" on 2026-07-29 — the day before our venue mapping — arguing this ask more rigorously than our comment did, with a worked fan-out example, dbt's `non_additive_dimension` as precedent, and an offer to write the proposal. Our mapping only scanned *discussions*, so an *issue* was structurally invisible to it. Add ThoughtSpot evidence there; discussion #19's last non-ours comment is 2026-01-21. |

**One unfiled candidate.** Runtime **parameters** (`[Parameter Name]` in a formula, resolved
per query from user input) have no representation in the standard at all, which makes every
referencing expression non-portable — construct-mapping *Expression handling* item 6 and
function-mapping **E9**. This is genuinely an upstream gap rather than a ThoughtSpot one, but no
ask has been drafted for it, so it is recorded here rather than numbered.

---

## 3. Deliberate non-goals

Chosen, not missed. Each raises a structured issue when encountered — never a silent drop — so
loss is always visible to the user.

| # | Not carried | Why |
|---|---|---|
| **NM1** | Object identity — `guid`, `obj_id`, `model_tables[].fqn` | Instance-local. A portable document containing them is not portable, and re-importing a stale value fails with `fqn resolution failed`. Enforced by payload rule **X8** |
| **NM2** | Row-level security (`rls_rules`) | Access-control policy, not semantics; the rule expressions name groups that exist only in the source instance. Relocating security policy into a document other tools will read *and rewrite* is a hazard. **Re-weighted 2026-09-01 (ThoughtSpot domain review): the decision is unchanged, its consequence is larger.** Table `rls_rules` is now the mechanism customers are actively migrating *onto* — it has replaced the ABAC `is_mandatory_token_filter` path, which is legacy and being deprecated for security reasons. So this is no longer one control among several but the primary one, and the loss must surface as an **error-severity issue naming every affected table**, not a quiet entry in a coverage matrix. The two booleans whose loss would change *results* are still stashed as exceptions, but they fail in **opposite directions**: dropping `is_bypass_rls: true` applies RLS where it was bypassed (fewer rows — fails closed), while dropping `is_mandatory_token_filter` lets a user with no matching token rule see every value (fails **open**). The latter is preserved for round-trip fidelity on models that still carry it, never synthesised |
| **NM3** | Presentation artifacts — Answers, Liveboards, charts | Separate object types with their own identity. The standard models semantics, not visualisations |
| **NM4** | Spotter coaching objects — reference questions, feedback, business terms | Separate object types that bind search tokens to phrasings. The standard's `ai_context.examples` is the nearest concept and is not interchangeable with them |
| **NM5** | Aggregate-model associations (`aggregated_models`) | A query-routing performance optimisation whose entries are GUIDs of *other* Models — instance-local by construction (NM1), and not semantics. Called out separately because stripping it silently disables routing with no error |
| **NM6** | Legacy Worksheets and Views, Sets, Alerts, and standalone Model **Alias** objects | Predecessors or layers, not models. An Alias is an instance-distribution artifact that points at a published master Model so another Org can use it without a copy — it carries no semantics of its own, so the master is the thing to convert |

---

## How this stays current

Everything above is a claim about two products that both move, so it needs the same treatment
any other external-dependency claim in this repo gets.

- **Currency anchors.** The TML references these findings are grounded in
  (`agents/shared/schemas/thoughtspot-*-tml.md`) carry a `<!-- currency: ... -->` header
  recording the product state they were last validated against.
  `tools/validate/check_mapping_currency.py` nudges when a changed reference has a missing or
  stale anchor. The 2026-07-30 sweep that produced G10 bumped the Model TML anchor.
- **The TML property census — the strongest instrument found so far, and now part of this loop.**
  [`docs/reviews/2026-07-30-tml-census.md`](../reviews/2026-07-30-tml-census.md) (2026-07-30) records a read-only census of **500**
  logical-table TML documents on `se-thoughtspot` — 143 Models, 275 Tables, 42 Views, 40 SQL Views,
  sampled across four strata from a 15,204-object population, **207 distinct key-paths observed**,
  every one classified against our four schema references and this document's construct mapping.
  Nothing was created, modified or deleted.

  It matters here because it attacks the *specific* blind spot lesson 1 above names. Our TML
  references were built from import failures, so they are complete on what breaks and silent on
  what merely exists — and a census of what the product **actually emits** is the only cheap
  instrument that sees the difference. What one run produced:

  | Outcome | Count |
  |---|--:|
  | Paths present in the wild and **absent from our references** | **25** |
  | …of which a documented field was **wrong**, not merely missing | **4** |
  | Paths documented **and** mapped (the reassuring majority) | 168 |
  | Paths documented in our refs and **never observed** in 500 documents | 128 |

  The four wrong fields are the reason this belongs in "how this stays current" rather than in a
  footnote: the View reference's *central* column-reference field was the wrong one
  (`column_id`, 0 sightings, vs `search_output_column`, 265 of 265), and a Table `rls_rules` field
  was documented with the wrong YAML *type*. Neither could have been found by reading our own
  documents, by reading ThoughtSpot's, or by any import probe — only by looking at output. It also
  advanced three of the four V-items in one pass (see above), confirmed a dozen existing invariants
  empirically rather than by inference, and found a `ts-cli` crash (routed as **BL-189**, fixed 2026-07-31 in ts-cli v0.127.2).

  Two limits to record with it. It is **one cluster**, so a finding like the View one is decisive
  for this build and not yet proven universal (census follow-up **T3**, folded into **BL-190**'s scope — see [the census report](../reviews/2026-07-30-tml-census.md)). And it exported without
  `--fqn` / `--include-obj-id`, so it says nothing about the identity rules **NM1** / **X8** — which
  are consequently the least-evidenced part of the construct mapping. Both are routed: the re-run is
  **BL-190**. The right cadence is one census per meaningful build change, and the scripts are
  reusable as-is.
- **Audit angle 13 (product currency)** in `.claude/rules/repo-audit.md` is the recurring
  mechanism: a per-platform specialist re-checks "are our 'cannot do this' verdicts still true?"
  against the delta since the anchor date. G4 is the cautionary tale for *why* — four of its
  rows were `direct` on documentation until a live pass proved otherwise
  (**BL-170**), and five emitters had already shipped the wrong names (**BL-171**). **Angle 18**
  covers the same drift pointed inward, at our own tooling.
- **Verifications V1–V4** in the construct-mapping document are the open ThoughtSpot-side
  questions this document depends on but has not settled — chiefly G10's calendar value
  vocabulary. Each needs a live export to close, and none should be relied on until it is. They
  are routed as **BL-186**, whose V1 leg is ~15 minutes on `se-thoughtspot` and gates the only
  converter behaviour among the four.
- **Round-trip tests, when the converter exists.** Today every fidelity claim here is either
  reasoned from documented semantics or measured once by hand
  (`docs/reviews/2026-07-29-ossie-tpcds-fidelity.md`, which found 21 behaviour issues in one
  pass and had to correct its own harness mid-run). A converter with a golden-fixture and
  property-based round-trip suite — the pattern the Databricks community converter already
  demonstrates — turns this table from a document that decays into one a test run re-proves.
- **The two-bucket rule.** Per `.claude/rules/repo-audit.md`, a finding here is not "done" until
  it is either a permanent automated check or a dated `BL-NNN`. Rows above that are already
  backlogged carry their ID; the rest are, deliberately, an input to a product conversation
  rather than repo work.
