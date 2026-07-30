# What ThoughtSpot could close to become more OSI-compliant

**Status:** internal review artifact — for ThoughtSpot engineering and product. Not a roadmap,
not a commitment, and **not** for external publication (unlike the two mapping documents it
draws on, this one cites internal paths and internal backlog IDs freely).
**Date:** 2026-07-30 · **Ossie spec version:** `0.2.0.dev0` (apache/ossie @ `c26b61c`)

**Sources.** Every row below is traceable to work already done, not to opinion:

| Source | What it contributes |
|---|---|
| [ts-osi-construct-mapping.md](ts-osi-construct-mapping.md) | Every `lossy→issue` row, every reverse-direction rule **R1–R11**, non-mappings **NM1–NM6**, asks **A1–A8**, verifications **V1–V4** |
| [ts-osi-function-mapping.md](ts-osi-function-mapping.md) | 33 `passthrough` rows and the 1 `unmappable` one, rules **E1–E12**, asks **A9–A12** |
| [../reviews/2026-07-29-ossie-converter-learnings.md](../reviews/2026-07-29-ossie-converter-learnings.md) | How other vendors' converters solve the same problems (the `custom_extensions` stash in particular) |
| [../reviews/2026-07-29-ossie-tpcds-fidelity.md](../reviews/2026-07-29-ossie-tpcds-fidelity.md) | Findings **F1–F21** from round-tripping a community TPC-DS fixture — the measured, not reasoned, evidence |
| [../backlog.md](../backlog.md) | **BL-166** (no stash), **BL-170** (string functions live-verified), **BL-171** (emitters still wrong), **BL-186** (the V1–V4 live verifications this document depends on) |

**How to read this.** Three buckets, and the split is the point. Bucket 1 is **ours** — things
ThoughtSpot cannot express that the standard, or another vendor, can. Bucket 2 is **theirs** —
gaps in the OSI specification we are raising upstream, listed so nobody mistakes an upstream gap
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

Ordered by priority. "Enables" is the concrete consequence of closing the gap, not a benefit
statement.

| # | Gap | Evidence | What closing it would enable | Priority |
|---|---|---|---|:-:|
| **G1** | **TML has no vendor-extension field of any kind.** There is nowhere in a Table or Model document to park a construct TML does not natively model. | construct-mapping, *The stash is asymmetric* and rule **X9**; the Ossie side has `custom_extensions` (`core-spec/spec.md:420-430`) and every other vendor's converter uses it | The round trip stops being one-directional. Today `TML → Ossie → TML` is lossless only because the *Ossie* document holds the stash; `Ossie → TML → Ossie` loses every construct TML cannot express, permanently and unfixably. This is also the single fix for the 41 documented-then-lost limitation rows across our four existing converter coverage matrices (13 + 10 + 8 + 10) — see **BL-166** | **High** |
| **G2** | **One `name` field per column — no identifier-vs-label split.** `columns[].name` is simultaneously the human display name (spaces, mixed case, not a valid SQL identifier), the natural-language search token, and the cross-document reference key. | construct-mapping **ID1**–**ID4** and ask **A5**; measured as fidelity findings **F2** (`sold_year` collapsed to `year`) and **F6** (`display_name` synthesised on 7 of 7 constructs) | Identifiers round-trip losslessly. It also removes two whole defect classes we currently have to engineer around: normalisation collisions when two display names fold onto one identifier (**ID2**), and the forced rename when a model surfaces `orders.status` and `customers.status` (**ID4** — ThoughtSpot requires display-name uniqueness across the *whole* model, which is stricter than any peer) | **High** |
| **G3** | **No key declarations anywhere in TML** — no primary key, no unique key, no join-cardinality assertion on the *table*. | construct-mapping Dataset level (`primary_key`, `unique_keys` rows) and ask **A7**; fidelity **F17** (a composite PK dropped); `agents/shared/schemas/snowflake-schema.md:244-245` shows the peer that has it | Keys survive interchange instead of being reverse-inferred from the join graph. Three downstream things become possible rather than heuristic: honest `COUNT(*)` translation (the function mapping's `COUNT(*)` row currently has to pick a column it *believes* is non-null), join-cardinality validation at import, and aggregate-awareness reasoning | **High** |
| **G4** | **No native string-function set.** `trim`, `ltrim`, `rtrim`, `replace`, `lower`, `upper`, `split_part`, `starts_with`, `ends_with` do not exist, and there is **no regular-expression support of any kind**. | function-mapping *String functions* — 11 of 21 rows are `passthrough`, and the four riskiest were live-verified on se-thoughtspot 2026-07-29 (**BL-170**: `Search did not find "trim ("`, same for `replace`, `starts_with`, `ends_with`) | 11 of the 33 total pass-throughs become native. Each pass-through today embeds raw warehouse SQL via `sql_*_op`, which couples the model to one dialect and makes the expression opaque to ThoughtSpot's query planner. This is the largest single-category fidelity win available. It has already cost us internally: **BL-171** tracks five `ts-cli` emitters still generating the non-existent bare names | **High** |
| **G5** | **A Model's own AI configuration is not in its own TML.** Model-scope Spotter instructions and model-scope synonyms have no field in the Model document; only per-column `properties.ai_context` and `properties.synonyms` are in-document. | construct-mapping Semantic model level (`ai_context`, `ai_context.synonyms` rows — both `lossy→issue`) and Dataset level (`ai_context` row) | Spotter configuration becomes version-controllable, diffable, and portable with the model it configures. This is as much an internal gap as an interchange one: a Model's TML today is not a complete description of that Model | **High** |
| **G6** | **No semi-additive / non-additive measure declaration.** ThoughtSpot expresses "do not sum this across time" by choosing a *function* (`last_value`, `first_value`), not by declaring a property of the measure. | function-mapping reverse direction, semi-additive row, and ask **A12**; Snowflake carries `non_additive_dimensions`, Databricks has its own form | A snapshot measure (inventory balance, headcount, ARR) can state its own roll-up rule. The current failure mode is the worst available: a silently summed balance sheet, with no error anywhere in the pipeline | **High** |
| **G7** | **Formula-backed columns carry neither a description nor a declared datatype.** A physical column has both; the moment a column becomes a formula, both homes disappear. | construct-mapping Field level (`description`, `datatype` rows) and Metric level (same two rows) — four `lossy→issue` verdicts from one gap | Metrics carry their documentation and their type through any interchange. Note this cannot be worked around by a stash even in principle (rule **X9**: the stash can only carry what TML contains), so G1 does *not* subsume it — both are needed | **Medium** |
| **G8** | **No time-of-day type, and no offset-aware timestamp type.** The documented `data_type` set has `DATE`, `DATE_TIME` and `VARCHAR` and nothing else temporal. | construct-mapping Datatype map, `Time` and `DateTimeTz` rows (both **declared losses**); function-mapping `TIME '10:30:00'` and `CAST(… AS TIME)` rows, both forced to `sql_date_time_op` | Two of the standard's ten datatypes stop being declared losses. Today a `Time` column becomes a `VARCHAR` (or a `DATE_TIME` with a meaningless date part) and a `DateTimeTz` silently loses its offset — display time zone is an instance/user setting in ThoughtSpot, not a column property | **Medium** |
| **G9** | **One approximate numeric type.** `DOUBLE` serves for both exact-decimal and floating-point intent; there is no fixed-point type. | construct-mapping Datatype map, `Decimal` / `Float` rows (they **collapse** into one another); function-mapping `CAST` target types, `DECIMAL`/`NUMERIC` row | A `DECIMAL(18,2)` currency column stays exact through a round trip instead of becoming floating-point. Also removes an asymmetry that is confusing to explain: `TML → Ossie → TML` is exact, `Ossie → TML → Ossie` is not | **Medium** |
| **G10** | **A fiscal or custom calendar cannot be described in TML.** The calendar is a *Connection-scoped* object created via `POST /api/rest/2.0/calendars/create` (10.12.0.cl+) and backed by a warehouse table; TML carries only `properties.calendar`, a bare name reference. The value vocabulary is not even settled internally. | construct-mapping field-level `calendar` row and verification **V1**; function-mapping fiscal-family row and ask **A11(c)**; `agents/shared/schemas/thoughtspot-model-tml.md` (`properties.calendar`, added 2026-07-30) vs `thoughtspot-sql-view-tml.md:136` (`CALENDAR_TYPE_GREGORIAN`) | A fiscal model becomes deployable and portable through TML alone. Today a TML package that references a fiscal calendar is silently wrong on any instance whose connection lacks a calendar of that name — and the expression-level `fiscal` argument on `year ( )` / `quarter_number ( )` has no home either, so the loss is two-part | **Medium** |
| **G11** | **Four documented silent-failure behaviours on import.** A root-level `synonyms:` is silently dropped; a nested `guid:` is silently ignored and a *duplicate object* is created; `aggregation: COUNT_DISTINCT` on a physical column silently overrides `column_type` to `ATTRIBUTE`; `aggregation` on a formula column is silently ignored at query time. | construct-mapping rules **R7** (root-level `synonyms:`), **R2** (nested `guid:`), **R4(b)** (`COUNT_DISTINCT` override) and **R4(c)** (`aggregation` on a formula column) — every one of them derived from a real import failure, which is why they are rules and not notes | Imports fail loudly instead of succeeding wrongly. Each of these currently produces a model that imports clean and then behaves incorrectly, which is strictly worse than a rejected import — and each one is a rule every TML-generating tool must independently rediscover | **Medium** |
| **G12** | **The function tail:** no `date_trunc`, no `TRUNC`, no `MINUTE`/`SECOND` extractors, no `dense_rank`, no `NTILE`, no percentile functions, no population `stddev`/`variance`, no `atan2`, no `count(*)`. | function-mapping coverage summary — these make up most of the remaining 22 pass-throughs after G4's 11 | Each one removes a `sql_*_op` and its dialect coupling. Individually small; together with G4 they are the entire remaining gap between today's 77% native coverage of the standard's expression language (112 of 146) and near-complete coverage | **Medium** |
| **G13** | **`FULL_OUTER` is accepted on a Table-level join and rejected on a Model inline join** (the error names only `INNER, LEFT_OUTER, OUTER, RIGHT_OUTER`). | construct-mapping relationship `type` row and rule **R5** | Join semantics stop depending on *where* the join was declared. Today a converter must silently downgrade `FULL_OUTER` to `OUTER` in a model inline join, which changes results | **Low** |
| **G14** | **A custom-map geo reference is a GUID** (`geo_config.custom_file_guid`), so it is instance-local by construction. | construct-mapping FieldLevel `geo_config` note, rule **X8**, non-mapping **NM1**, verification **V3** | Geo configuration becomes portable. Today a column whose geo role points at a custom map must have that role dropped entirely on export — a GUID cannot be carried into a portable document, so unlike most properties there is not even a lossy path | **Low** |

---

## 2. OSI spec gaps we are pushing upstream

Not ThoughtSpot's to fix. Listed so an engineering reader can tell the two apart at a glance,
and so a gap on this list is not filed twice.

**Nothing on this list has been posted.** Publication of both mapping documents to
apache/ossie#285 is held pending legal review.

| # | Ask (one line) | Status |
|---|---|---|
| **A1** | Add `THOUGHTSPOT` to the closed `Dialect` enum **and** to `SKIP_SQL_VALIDATION` — a ThoughtSpot formula is not SQL | **Blocking.** Every `THOUGHTSPOT` dialect entry fails schema validation until this lands, which blocks the entire reverse direction |
| **A2** | Add a `THOUGHTSPOT` row to the well-known vendor-extension examples table | Open — trivial, cosmetic |
| **A3** | A core `filters` construct, or a documented convention for one | Open — **the highest-value semantic gap found.** Every vendor stashes filters today, and a stashed filter is invisible, so the same model returns different numbers in two tools |
| **A4** | Join `type` and cardinality as first-class fields on `Relationship` | Open — every vendor is stashing or re-deriving them |
| **A5** | Confirm whether `field.label` is a display label (our reading, and Databricks's) or a categorisation label (what the prose says) | Open — a clarification, but it decides where G2's display names live |
| **A6** | First-class support for non-equality (range / ASOF / constant) relationships | **Interim guidance received 2026-07-30** — carry them as an extension inside the relationships section, which both mapping documents now do. Ask stays open: an extension is invisible to consumers that do not read our vendor key, and a *pure* range join still cannot be expressed at all (`from_columns`/`to_columns` are required with `minItems: 1`) |
| **A7** | Is deriving `primary_key` from a relationship's `to_columns` acceptable practice? | Open — the answer only matters while G3 is open |
| **A8** | Should the converter guide tell an import converter to validate its *own* Ossie output? | Open — process, not schema |
| **A9** | Define `EXISTS_IN()` (referenced but specified nowhere), and settle whether `DISTINCT` is a general aggregate modifier | Open — the one `unmappable` construct in 146, and only because it cannot be read |
| **A10** | A way to express a *dynamic* window partition (Snowflake's `PARTITION BY EXCLUDING`) | Open — the largest fidelity gap in the ThoughtSpot → Ossie direction. Every `cumulative_*` / `moving_*` carries one implicitly |
| **A11** | Fix the date-part vocabulary's edges: the `DAYOFWEEK` base, the function-list/part-list asymmetry, and a fiscal-calendar declaration | Open — **(c) is the mirror of G10**; the two must be read together |
| **A12** | A declaration for non-additive / semi-additive measures, plus a home for the aggregate `Decomposability` classification | Open — **the mirror of G6.** Both sides are missing it, so neither can fix it alone |

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
| **NM2** | Row-level security (`rls_rules`) | Access-control policy, not semantics; the rule expressions name groups that exist only in the source instance. Relocating security policy into a document other tools will read *and rewrite* is a hazard. The two booleans whose loss would change *results* — `is_bypass_rls` and `is_mandatory_token_filter` — are treated as exceptions and preserved |
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
