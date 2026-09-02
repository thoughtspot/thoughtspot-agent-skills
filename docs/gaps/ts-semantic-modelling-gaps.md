<!-- currency: semantic-layer-peers — 2026-09 (Ossie 0.2.0.dev0 @ b5da5d6; Snowflake SV GA; Databricks MV 18.2+) -->
# ThoughtSpot semantic modelling: gaps and differentiators

**Status:** internal review artifact — for ThoughtSpot engineering and product. Not a roadmap and
not a commitment. Cites internal paths and backlog IDs freely, so **not for external publication**
as written.
**Date:** 2026-09-02

## What this is

A cross-platform read of where ThoughtSpot's semantic model sits against its three genuine
**peers** — the Apache Ossie interchange standard, Snowflake Semantic Views, and Databricks
Metric Views — assembled from evidence this repo already holds rather than from opinion.

| Part | What it holds |
|---|---|
| **[A — Gaps](#part-a--gaps)** | What ThoughtSpot cannot express, in three buckets: **A1** ours (a product conversation), **A2** the standards' and peers' own gaps, **A3** ours to build (already backlogged) |
| **[B — Differentiators](#part-b--what-thoughtspot-expresses-that-no-peer-can)** | What ThoughtSpot expresses that no peer can — **and five claims we should stop making** |
| **[C — Upstream signal](#part-c--upstream-signal-where-the-ossie-communitys-weight-is)** | Which gaps the Ossie community is independently pushing on, ranked by engagement |
| **[Corrections](#corrections-this-document-makes)** | Eighteen claims in existing repo documents that did not survive re-verification |

A and B belong together. A gap list circulated without the differentiator list reads as a verdict
on the product; a differentiator list circulated without the gap list is marketing.

## The short version

1. **Four gaps are Critical** — they make the numbers come out wrong with no error anywhere:
   **G15** (no `PARTITION BY` on a window formula), **N1** (row-positional window frames where
   peers use date intervals — live-measured divergence on gapped data), **G6** (no axis-bearing
   non-additivity declaration) and **G11** (three silent-failure behaviours on import).
2. **Five gaps are structural, not incidental** — G15, G4, G5, G8/G9 and G12 are expressible by
   **all three** peers, so they will resurface against whatever standard we map next.
3. **The community is converging on our list.** Six of the ten highest-engagement Ossie discussions
   land on gaps we derived independently from converter evidence: identity/naming, keys and
   cardinality, calendars, additivity and filters. That is the semantic-layer industry's current
   unsolved list, not a ThoughtSpot idiosyncrasy.
4. **ThoughtSpot's real differentiators are query-time and governance**, not metadata. Synonyms, AI
   context, parameters and unconditional filters are all matched by peers now. What is not matched:
   chasm-trap control, search-index control, aggregate-aware routing, structured group-aware RLS,
   and publishing one object across Orgs without copying it.
5. **G5 is the one to fix first if only one is fixed** — a Model's own AI configuration is not in
   its own TML, which costs diffability and version control on models that never leave the instance.
   Every other gap costs something only at a tool boundary.
6. **Eighteen existing claims did not survive verification**, five of which are already shaping
   converter behaviour. The root cause is mechanical and fixable: the nine coverage matrices carry
   no currency anchor and no validator watches them.

### Why these three peers and not the BI converters

This repo ships nine `ts-convert-*` skills, but only four of them convert between **semantic
layers**. Tableau, Power BI, Qlik, Sisense and Looker embed their model inside a workbook or
project alongside its visualisations; their "model" is not a peer of a ThoughtSpot Model and a gap
found against one of them usually says more about the workbook format than about semantic
modelling. Ossie, Snowflake Semantic Views and Databricks Metric Views are standalone semantic
layers with the same job as a ThoughtSpot Model, so a gap against them is a like-for-like finding.

### How rows are categorised — and why not by platform

Rows in Part A are grouped by **semantic-layer concern** (identity, keys, types, expressions,
additivity, time, AI context, extensibility, import safety, governance, display), not by which
peer surfaced them. Cutting it this way makes **recurrence** visible, which is the single most
useful signal here:

> A gap that appears against Ossie **and** Snowflake **and** Databricks is structural to
> ThoughtSpot. A gap that appears against exactly one of them is usually a quirk of that format.

Each row therefore carries a **Peers** column showing which of the three can express the thing
ThoughtSpot cannot.

### Importance = interchange fidelity

Ranking is by **impact on interchange fidelity**, not implementation cost, which we are not in a
position to judge. The ladder is stated explicitly so rows stay comparable as the table grows:

| Rung | Meaning | Test |
|---|---|---|
| **Critical** | Silently changes the numbers | The model imports clean, runs clean, and returns a wrong answer. No error anywhere in the pipeline |
| **High** | Permanently lost, no workaround | The construct cannot survive a round trip in at least one direction, and no stash or rewrite recovers it |
| **Medium** | Lossy but loud, or costly workaround | The loss is declared, raises an issue, or can be worked around at a real cost |
| **Low** | Cosmetic or recoverable | Metadata or display concerns a user can restore after the fact |

**Silent-wrong ranks above loud-failure.** This is the existing compliance document's own
principle — a model that "imports clean and then behaves incorrectly … is strictly worse than a
rejected import" ([compliance-gaps, G11](../ossie/ts-ossie-compliance-gaps.md)) — named here so it
is applied consistently rather than per-row.

### Evidence classes

Every row is tagged with how its claim was established. This matters because the classes are not
equally strong, and the Ossie work has already produced three claims that survived only because
somebody challenged them.

| Tag | Meaning | Strength |
|---|---|---|
| `live` | Probed against a real cluster (`se-thoughtspot`) or measured in a TML census | Strongest — the product's actual behaviour |
| `matrix` | A limitation row in a shipped `ts-convert-*` coverage matrix | Strong — written from a converter that had to handle it |
| `spec` | Read from a platform schema/mapping reference in this repo | Medium — accurate as of that file's currency anchor |
| `inferred` | Reasoned from documented semantics, not observed | Weakest — flag before relying on it |

Two cautions carried forward from the Ossie work, because they cost real corrections there:

1. **Acceptance under `VALIDATE_ONLY` is not evidence of support.** Unknown keys in a Model
   `columns[]` entry are silently ignored, so only *rejection* is decisive there. Formula `expr`
   bodies and join `type` values are parsed and enum-validated, so both outcomes carry
   information — pick the discriminating surface before probing.
2. **A query-time semantic cannot be probed by import validation at all.** Say so rather than
   claiming a probe settled it.

---

# Part A — Gaps

Three buckets, and the split is the point. **A1 is ours** — things ThoughtSpot cannot express that
a peer can. **A2 is theirs** — gaps in the standards and the peer products, listed so nobody
mistakes one for a ThoughtSpot defect. **A3 is ours to build** — cases where both sides can express
the thing and our own converter does not bridge it.

---

## A1. ThoughtSpot product gaps

Things ThoughtSpot cannot express that at least one peer can. **Deliberately unrouted** — these are
input to a product conversation, not repo work, so they carry no `BL-NNN` unless repo work already
follows from them.

`G*` identifiers are the canonical ones from
[ts-ossie-compliance-gaps.md](../ossie/ts-ossie-compliance-gaps.md) and are **not renumbered here**;
this document regroups and re-evidences them, and adds peer columns that document does not carry.
Rows with no `G` number are new here.

**Peers** — ● the peer can express it · ○ it cannot · – not applicable / not established.

### Recurrence is the headline

| Concern | Gap | Ossie | Snow­flake | Data­bricks | Fidelity |
|---|---|:-:|:-:|:-:|:-:|
| Expressions — windowing | **G15** No `PARTITION BY` on a window formula | ● | ● | ● | **Critical** |
| Expressions — windowing | **N1** Window frames are **row-positional**, not date-interval | ● | ● | ● | **Critical** |
| Measure semantics | **G6** No semi-additive / non-additive declaration | ○ | ● | ◐ | **Critical** |
| Import safety | **G11** Three silent-failure behaviours on import | – | – | – | **Critical** |
| Extensibility | **G1** No vendor-extension field anywhere in TML | ● | ● | ○ | **High** |
| Identity & naming | **G2** One `name` per column — no identifier/label split | ◐ | ● | ● | **High** |
| Keys & cardinality | **G3** No primary key, unique key or cardinality assertion | ● | ● | ○ | **High** |
| Expressions — functions | **G4** No native string functions, no regex at all | ● | ● | ● | **High** |
| AI context | **G5** A Model's own AI configuration is not in its TML | ● | ● | ● | **High** |
| Type system | **G8** No time-of-day type, no offset-aware timestamp | ● | ● | ● | Medium |
| Type system | **G9** One approximate numeric type — no fixed-point | ● | ● | ● | Medium |
| Time & calendar | **G10** A fiscal/custom calendar cannot be described in TML | – | – | – | Medium |
| Expressions — functions | **G12** The function tail — 17 residual pass-throughs | ● | ● | ● | Medium |
| Type system | **G7** A formula-backed column has no declared datatype | ● | ● | – | Low |
| Governance metadata | **G14** A custom-map geo reference is a GUID | ○ | ○ | ○ | Low |

**Read the ● columns, not the row count.** Five gaps — G15, G4, G5, G8/G9, G12 — are expressible by
**all three** peers. Those are structural to ThoughtSpot and will resurface against the next
standard we map, whatever it is. By contrast G14 is ● nowhere: no peer has custom-map geo either, so
it is a portability problem inside a ThoughtSpot-only feature, not a competitive gap. G10 is the
same shape.

### The four Critical rows

Critical means **the numbers come out wrong with no error anywhere**. Four qualify, and they are
the ones to lead with.

**G15 — a window formula cannot declare its own `PARTITION BY`.** Two shapes, one gap.
`moving_*` / `cumulative_*` take a measure, frame offsets and *order* columns and nothing else —
their partition is completed at query time from whatever dimensions the user's search carries, so
it matches no static `OVER` shape. `rank` / `rank_percentile` take a measure and a direction string
and nothing else — no order columns, no frame — and are always global over the result set.

Live-confirmed by **rejection** on `se-thoughtspot` (2026-07-30, 52 `VALIDATE_ONLY` probes: 31
accepted, 21 rejected; 8 negative controls prove the surface discriminates). A partition argument on
`moving_sum`/`cumulative_sum` is rejected at the parser; `rank` enforces an arity of exactly two and
additionally refuses a `group_aggregate` first argument, so the partition cannot be smuggled through
the measure either. `evidence: live`

All three peers can express a static partition — Snowflake's window metrics take
`PARTITION BY`, `ORDER BY` and a frame clause directly in
[`CREATE SEMANTIC VIEW`](https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view), and
Databricks window measures take `order` and `range`. So the failure is silent and **symmetric**: an
inbound `LAG(x) OVER (PARTITION BY region ORDER BY d)` has no native target, and an outbound
`moving_sum` describes a window no other tool can see — the same model returns different numbers as
soon as a user adds a dimension. The fix is small and has an existence proof inside ThoughtSpot's
own grammar: `first_value`/`last_value` already take an explicit partition argument.

**G6 — no semi-additive / non-additive declaration.** ThoughtSpot says "do not sum this across
time" by choosing a *function* (`last_value`, `first_value`), not by declaring a property of the
measure. The window half is fine — all four spellings live-confirmed, and they take an explicit
partition and time axis. What is missing is the **roll-up declaration**: nothing states the measure
must not be summed across the axis. `evidence: live`

Both warehouse peers have the declaration ThoughtSpot lacks, which is what makes this Critical
rather than theoretical:

| Peer | Declaration | Source |
|---|---|---|
| Snowflake | `NON ADDITIVE BY ( <dimension> [ASC\|DESC] [NULLS FIRST\|LAST] … )` on a metric | [CREATE SEMANTIC VIEW](https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view) |
| Databricks | `semiadditive: first \| last` on a window measure — **a property, but it names the aggregation *method*, not the dimension the measure is non-additive across.** Same information content as ThoughtSpot's function choice, merely relocated out of the expression | [Metric view YAML reference](https://docs.databricks.com/aws/en/business-semantics/metric-views/yaml-reference) |
| Ossie | **None** — this is upstream ask **A12** / [issue #290](https://github.com/apache/ossie/issues/290) | — |

> **Nuance, verified 2026-09-02 and worth carrying.** Only **Snowflake** has the truly declarative
> form — `NON ADDITIVE BY` names the *dimension*, so a consumer can reason about the measure without
> parsing an expression. Databricks' `semiadditive: first|last` names the *method*, which is what
> ThoughtSpot already does via `first_value`/`last_value`; it is better than ThoughtSpot's only in
> that it sits in a declared field rather than inside an expression string. The compliance
> document's phrasing — *"Databricks has its own form"* — is defensible but reads stronger than the
> evidence supports.

The failure mode is the worst available: a silently summed balance sheet, with no error anywhere in
the pipeline. Ossie lacking it too means neither side can fix it alone — G6 and A12 are one problem
seen from two ends.

> **`is_additive` — contested, and the most important open question on this row.** Two sources in
> hand disagree about what the field means, and the disagreement decides how much of G6 survives.
>
> | Source | Reading |
> |---|---|
> | [ThoughtSpot TML properties](https://docs.thoughtspot.com/cloud/latest/tml-properties) | *"Controls extended aggregate options for **attribute** columns"* with a numeric or date type. On this reading it is unrelated to measure additivity and G6 stands untouched |
> | `agents/shared/schemas/thoughtspot-model-tml.md:244` | *"used on **semi-additive models** to explicitly allow summation across time"*. On this reading it is directly about additivity |
>
> **What survives either way** — and this is the claim to make, because it does not depend on
> resolving the conflict: `is_additive` is a **bare boolean with no axis**. Snowflake's
> `NON ADDITIVE BY ( <dimension> )` names *which dimension* the measure is non-additive across;
> a boolean cannot. So the narrowed, defensible form of G6 is **"ThoughtSpot has no axis-bearing
> roll-up declaration"**, not "no declaration at all".
>
> Supporting the narrowing: the census found **15 sightings across 4 Models, every one `true`** —
> no `false` was ever observed, so the field's discriminating behaviour is unevidenced in the wild.
> A second candidate surface, `ai_context.additivity` (a closed enum
> `additive`/`semi_additive`/`non_additive` plus `non_additive_dimension`), *is* axis-bearing — but
> it is defined in a repo-authored schema whose relationship to actual product behaviour is itself
> disputed, so it cannot settle this either.
>
> **This needs one live probe to close:** set `is_additive: false` on a measure, export, and check
> whether it round-trips and what it changes at query time. Until then, do not state G6 more
> strongly than the axis-bearing form.

**N1 — window frames are row-positional, not date-interval.** *New in this document; not in the
`G` series.* A ThoughtSpot `moving_*` frame counts **rows** in the ordering dimension. Databricks'
`range:` counts **wall-clock intervals** (`trailing 7 day`, `leading 3 month`). On dense daily data
the two agree, which is why this hid for so long. On **gapped or sparse** data they diverge, and
neither side errors.

Measured on the same fixture, both platforms, live 2026-07-09:

| Ordering value (gapped series) | ThoughtSpot actual | Databricks actual |
|---|--:|--:|
| day 1 | NULL | NULL |
| day 2 | 10 | 10 |
| **day 5** | **30** | **20** |
| **day 8** | **80** | **50** |

`evidence: live` — a **cross-platform, both-directions** verification, which makes this the
best-evidenced row in this document. Earlier verdicts recorded it as CONFIRMED only because the
fixtures used were dense enough to mask it.

It is Critical by the ladder — the numbers differ with no error anywhere — but note the honest
mitigation: our converter **does** warn. `mv_parse.py` emits a density warning, and three mapping
documents carry the caveat. So the pipeline is loud even though the platforms are silent; the
product gap is that ThoughtSpot has no date-interval frame to translate *into*.

**G11 — three documented silent-failure behaviours on import.** A root-level `synonyms:` is
silently dropped; a nested `guid:` is silently ignored and a **duplicate object created**; and
`aggregation: COUNT_DISTINCT` on a physical column silently overrides `column_type` to `ATTRIBUTE`.
Each produces a model that imports clean and then behaves incorrectly, and each is a rule every
TML-generating tool must independently rediscover. `evidence: live` — every one derived from a real
import failure.

This row has no peer column because it is not a modelling-power gap: it is an **import contract**
gap. Loud rejection would be strictly better than any of the three current behaviours.

> A fourth item was **withdrawn** on 2026-07-30: "`aggregation` on a formula column is silently
> ignored at query time" is true only when the formula's `expr` already contains an aggregate; on a
> **scalar** `expr` the column-level `aggregation` does apply, and the pairing is a legitimate
> idiom. Note that is a *query-time* semantic, which no import probe can settle in either direction.

### The High rows

| # | Gap | Why it matters | Evidence |
|---|---|---|---|
| **G1** | **No vendor-extension field of any kind.** Nowhere in a Table or Model document to park a construct TML cannot natively model | The round trip stops being one-directional. Today `TML → Ossie → TML` is lossless only because the **Ossie** document holds the stash; `Ossie → TML → Ossie` loses every construct TML cannot express, permanently. It is also the single fix for the 45 documented-then-lost rows in **A3** below | `live` + `matrix`. Ossie has `custom_extensions` (`core-spec/spec.md:420-430`); Snowflake has `WITH EXTENSION` and `TAG`. **Do not repeat the compliance document's "10 of 11 vendor converters use it, dbt the sole exception"** — see [Corrections](#corrections-this-document-makes) |
| **G2** | **One `name` per column — no identifier-vs-label split.** `columns[].name` is simultaneously display name, search token and cross-document reference key | Identifiers round-trip losslessly, and two defect classes disappear: normalisation collisions when two display names fold onto one identifier, and the forced rename when a model surfaces both `orders.status` and `customers.status` — ThoughtSpot requires display-name uniqueness across the **whole model** | `live`. Measured as fidelity findings F2 (`sold_year` collapsed to `year`) and F6 (`display_name` synthesised on 7 of 7 constructs) |
| **G3** | **No key declarations anywhere in TML** — no primary key, no unique key, no join-cardinality assertion | Keys survive interchange instead of being reverse-inferred from the join graph. Three things become honest rather than heuristic: `COUNT(*)` translation (which today must *guess* a non-null column), join-cardinality validation at import, and aggregate-awareness reasoning | `live` + external. Snowflake's DDL carries both: `PRIMARY KEY ( … )` and `UNIQUE ( … )` on a table entry. Fidelity finding **F17** dropped a composite PK |
| **G4** | **No native string-function set.** `trim`, `ltrim`, `rtrim`, `replace`, `lower`, `upper`, `split_part`, `starts_with`, `ends_with` do not exist — and there is **no regular-expression support of any kind** | 11 of 37 pass-throughs become native. Each pass-through embeds raw warehouse SQL via `sql_*_op`, coupling the model to one dialect and making the expression opaque to ThoughtSpot's own query planner. Largest single-category win *by function count* | `live`. The four riskiest live-verified on se-thoughtspot 2026-07-29 (`Search did not find "trim ("`, same for `replace`/`starts_with`/`ends_with`) — **BL-170**. It has already cost us: five `ts-cli` emitters shipped the non-existent bare names, **BL-171** |
| **G5** | **A Model's own AI configuration is not in its own TML.** Model-scope Spotter instructions and model-scope synonyms have no field in the Model document — only *per-column* `properties.ai_context` and `properties.synonyms` exist | Spotter configuration becomes version-controllable, diffable and portable with the model it configures. As much an internal gap as an interchange one: **a Model's TML today is not a complete description of that Model** | `live`. Independently re-confirmed 2026-09-02: a 500-document census found 656 per-column `ai_context` values and 2,812 `synonyms` values, and **zero** `model.ai_context` / `model.synonyms`. Data Model Instructions is a real product feature whose **TML location is unknown** — five candidate endpoints returned 500, and the coaching skill currently writes the content to a markdown file for **manual paste into the UI** |

**Why G5 is the one to fix first if only one is fixed.** It is the only High row whose cost is
borne entirely inside ThoughtSpot, independent of any interchange. Every other row on this table
costs something only when a model crosses a tool boundary; G5 costs you diffability, review and
version control of Spotter configuration on a model that never leaves the instance.

### Medium and Low

| # | Gap | Note | Fidelity |
|---|---|---|:-:|
| **G8** | No time-of-day type and no offset-aware timestamp — the documented `data_type` set is `DATE`, `DATE_TIME`, `VARCHAR` and nothing else temporal | A `Time` becomes a `VARCHAR` (or a `DATE_TIME` with a meaningless date part); a `DateTimeTz` silently loses its offset, because display time zone is an instance/user setting, not a column property | Medium |
| **G9** | One approximate numeric type — `DOUBLE` serves both exact-decimal and floating-point intent | A `DECIMAL(18,2)` currency column stops being exact through a round trip. Also removes an asymmetry that is awkward to explain: `TML → Ossie → TML` is exact, `Ossie → TML → Ossie` is not | Medium |
| **G10** | A fiscal or custom calendar cannot be described in TML — the calendar is a **Connection-scoped** object created via `POST /api/rest/2.0/calendars/create` (10.12.0.cl+) and backed by a warehouse table; TML carries only `properties.calendar`, a bare **name** | A TML package referencing a fiscal calendar is **silently wrong** on any instance whose connection lacks a calendar of that name. The loss is two-part: the expression-level `fiscal` argument on `year()` / `quarter_number()` has no home either. Verification **V1** was **substantially settled 2026-07-30** — the value is a calendar *name*; what remains is one narrowed question, and closing it needs a `GET /api/rest/2.0/calendars/…` read, not another export | Medium |
| **G12** | The function tail — **17** residual pass-throughs once G4's 11 string rows and G15's 9 window rows are removed from the 37. Chiefly the `MINUTE`/`SECOND` extractors, percentile *aggregates* (`PERCENTILE_CONT`/`_DISC`/`APPROX_PERCENTILE`), population `stddev`/`variance` and `atan2` | Individually small; together with G4 and G15 they are the **entire** remaining distance between today's 74% native coverage of Ossie's expression language (108 of 146) and near-complete coverage. **Cite the counts, not the compliance document's prose list** — that sentence names `dense_rank` and `NTILE` (both inside G15's window 9) and `date_trunc` and `count(*)` (both classified `direct`, i.e. natively mapped). `dense_rank` and `row_number` are live-confirmed absent as *bare* functions | Medium |
| **G7** | A formula-backed column has no declared datatype — ThoughtSpot derives it from the expression | Cannot be worked around by a stash even in principle (a stash can only carry what TML contains), so **G1 does not subsume it**. Narrow ask: a *declared* type so a consumer need not re-derive it. Note the `description` half of this gap was **withdrawn** — `description` is first-class on a formula-backed entry, carried by 63 of 549 formula columns in the census | Low |
| **G14** | A custom-map geo reference is a GUID (`geo_config.custom_file_guid`), so it is instance-local by construction | Confirmed in production: 3 models / 7 columns carry it. Unlike most properties there is not even a lossy path — a GUID cannot be carried into a portable document, so the geo role must be **dropped entirely** on export | Low |

> **G13 was withdrawn** (2026-07-30) and is retained here only so nobody re-files it. The claim was
> that `FULL_OUTER` is accepted on a Table join and rejected on a Model join. **Both halves were
> false**: it is rejected in both contexts with a byte-identical error, and `OUTER` *is*
> ThoughtSpot's full outer join, so `FULL_OUTER → OUTER` is a rename, not a downgrade. The defect
> was **ours** — two schema references documented a join type the product does not accept.

---

## A2. Standard and peer gaps — not ThoughtSpot's to fix

Listed so an engineering reader can tell the two apart at a glance, and so a gap here is not filed
twice as a ThoughtSpot defect. Several are **mirrors** of a Part A1 row: neither side can express
the other's shape, so neither side can fix it alone.

### A2.1 Apache Ossie specification gaps

Twelve asks, tracked as **A1–A12** in
[ts-ossie-construct-mapping.md](../ossie/ts-ossie-construct-mapping.md) and
[ts-ossie-function-mapping.md](../ossie/ts-ossie-function-mapping.md). Status verified against
[apache/ossie](https://github.com/apache/ossie) on **2026-09-02**.

| # | Ask | Mirrors | Upstream status (2026-09-02) |
|---|---|---|---|
| **A1** | Add `THOUGHTSPOT` to the closed `Dialect` enum **and** to `SKIP_SQL_VALIDATION` — a ThoughtSpot formula is not SQL | — | **High, not blocking** (re-graded 2026-08-31). Filed as [apache/ossie#351](https://github.com/apache/ossie/issues/351). It blocks a faithful `THOUGHTSPOT` dialect entry, not the converter — nvidia ships under `ANSI_SQL` as precedent. The compliance document still carries the retracted "blocks the entire reverse direction" phrasing |
| **A2** | Add a `THOUGHTSPOT` row to the well-known vendor-extension examples table | — | Open, and **mis-targeted**: there is no single table. Three have diverged — `spec.md:439-448` (8 entries), `ossie-schema.json:31` (7), `converters/README.md:70-78` (7). Attach to upstream PR #328. Gates nothing |
| **A3** | A core `filters` construct, or a documented convention for one | — | **Posted 2026-09-01** to [discussion #342](https://github.com/apache/ossie/discussions/342). The venue was corrected from #5 (one comment ever — ours) to #342, which is genuinely live: 7 comments, four of them a sustained design exchange, last activity 2026-09-01. The highest-value semantic gap found — every vendor stashes filters today, and a stashed filter is invisible, so the same model returns different numbers in two tools |
| **A4** | Join `type` and cardinality as first-class fields on `Relationship` | **A1 §keys** | Open — every vendor is stashing or re-deriving them |
| **A5** | Confirm whether `field.label` is a display label or a categorisation label | **G2** | **Overtaken by [PR #287](https://github.com/apache/ossie/pull/287)** — *still open, not merged*, last updated 2026-08-31. It adds an explicit `display_label` to both `Field` and `Metric`, which answers A5 against our reading rather than for it. Re-grade rather than re-post |
| **A6** | First-class support for non-equality (range / ASOF / constant) relationships | — | Interim guidance received 2026-07-30 — carry as an extension inside the relationships section, which both mapping documents now do. Still open: an extension is invisible to consumers that do not read our vendor key, and a *pure* range join cannot be expressed at all (`from_columns`/`to_columns` are required, `minItems: 1`) |
| **A7** | Is deriving `primary_key` from a relationship's `to_columns` acceptable practice? | **G3** | **Partly answered upstream 2026-08-28** (PR #330 / issue #301): derivation is tolerated, and coverage — not equality — is the test. The narrower question of *which* relationships qualify remains open |
| **A8** | Should the converter guide tell an import converter to validate its *own* Ossie output? | — | Open — process, not schema |
| **A9** | Define `EXISTS_IN()` (referenced but specified nowhere); settle whether `DISTINCT` is a general aggregate modifier | — | Open — the one `unmappable` construct in 146, and only because it cannot be read |
| **A10** | A way to express a *dynamic* window partition | **G15** | Open, and **bidirectional**: every ThoughtSpot `cumulative_*`/`moving_*` carries a dynamic partition implicitly, and an Ossie window's *static* `PARTITION BY` has no native ThoughtSpot target either. Neither side can express the other's window shape |
| **A11** | Fix the date-part vocabulary's edges: the `DAYOFWEEK` base, the function-list/part-list asymmetry, a fiscal-calendar declaration | **G10** (part c) | Open — (c) and G10 must be read together |
| **A12** | A declaration for non-additive / semi-additive measures | **G6** | **Posted 2026-09-01** to [issue #290](https://github.com/apache/ossie/issues/290) ("Spec has no way to declare a non-additive metric", opened by Cube.dev 2026-07-29). Venue corrected from discussion #19 — our original scan covered only *discussions*, so an *issue* was structurally invisible to it. Ours is currently the only comment on it |

> **Two status corrections this document makes to the compliance record.** A3 and A12 are listed
> in [ts-ossie-compliance-gaps.md](../ossie/ts-ossie-compliance-gaps.md) as *venue corrected,
> awaiting posting*. Both were **posted on 2026-09-01** and the compliance document has not caught
> up. Also worth recording against that document's headline datum — *"zero replies in 32 days"* on
> the seven asks posted 2026-07-30 — that the two re-routed asks now sit in venues with real
> traffic, which was the point of re-routing them.

**One unfiled candidate.** Runtime **parameters** (`[Parameter Name]` in a formula, resolved per
query from user input) have no representation in the standard at all, which makes every
referencing expression non-portable. Genuinely an upstream gap rather than a ThoughtSpot one, but
no ask has been drafted, so it is recorded rather than numbered.

### A2.2 Snowflake Semantic View gaps

Verified against the [`CREATE SEMANTIC VIEW` grammar](https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view)
and `agents/shared/schemas/snowflake-schema.md` (anchor `snowflake — 2026-07`, amended 2026-08-26).

| Construct ThoughtSpot has | Snowflake position | Grade |
|---|---|:-:|
| `format_pattern` — display formatting | No display-format property anywhere in the schema. `TO_CHAR()` inside a dimension `expr` is the workaround, and it works **without** the "view wrapper" our matrix prescribes | **Hard gap** |
| `custom_order` — value ordering | No value-ordering key. `non_additive_dimensions.sort_direction` is metric-scoped and is not this | **Hard gap** |
| `geo_config` — geographic roles | Dimension `data_type` enum is `TEXT\|NUMBER\|DATE\|TIMESTAMP\|BOOLEAN` — no `GEOGRAPHY`. Structural: a Semantic View is a query layer with no rendering concept, and TS geo is a chart-rendering role | **Hard gap — the strongest of the set** |
| Locale-specific display names | No locale binding. `synonyms` is a free list and can hold non-English strings, so NL *access* in another language is reachable; per-locale *display names* are not | **Hard gap** |
| Column groups / data-panel folders | **Partial** — `tags:` (GA 2026-05-05, valid at five levels) is a name→value carrier that can hold group membership losslessly, though it is not a folder equivalent | Partial |
| Default date bucket | **Partial** — no grain property, but a pre-grained dimension (`expr: DATE_TRUNC('MONTH', t.D)`) expresses it, and Cortex handles grain as a query-time behaviour | Partial |
| Fiscal calendar | **Not a gap** — no `fiscal` argument in `expr`, but the concept is expressible via arbitrary SQL or a joined calendar table. See Part B4 | Not a gap |
| Runtime parameters | **Not a gap** — `variables:` GA June 2026 (`name`, `data_type`, `default_value`, `description`) | Not a gap |

### A2.3 Peer constructs with no ThoughtSpot home — beyond the G-list

Snowflake expresses several things ThoughtSpot cannot, which the `G` numbering does not cover
because the Ossie mapping had no counterpart to surface them. These are **additional A1 rows in
substance**; they are grouped here because Snowflake is the only peer that evidences them.

| Snowflake construct | ThoughtSpot position | Fate in our converter | Fidelity |
|---|---|---|:-:|
| `primary_key` / `unique_keys` | **G3** — no key declarations at all | Parsed, then **dropped** | **High** |
| `CUSTOM_INSTRUCTIONS` / `AI_SQL_GENERATION` / `AI_QUESTION_CATEGORIZATION` | **G5** — no model-scope AI configuration in TML | Parsed, then dropped — `sv_build_model.py` never reads it | **High** |
| Table-level `synonyms` | No table-level synonym concept | Parsed, then dropped | Medium |
| `ACCESS_MODIFIER: PRIVATE` | No "private column" concept | **Mapped** to `index_type: DONT_INDEX`. Note `PUBLIC` is not recognised and falls into `unsupported[]`; and the schema puts `access_modifier` on dimensions and time dimensions too, which our matrix's "facts/metrics" understates | Low |
| `is_enum`, `sample_values`, `unique: bool` | No equivalent — Cortex-Analyst NL aids | Parsed, then dropped | Low |
| `tags:` at five levels, `cortex_search_service`, `using_relationships`, `max_staleness` | No equivalent | **Absent from the from-direction matrix entirely** — three of the four are not even parsed | Low, but unrecorded |

---

## A3. Our converter gaps — the mapping exists and we do not emit it

The narrowest and most actionable bucket, and the one that is **not** a product conversation.
Every row here is a case where the target construct exists on both sides and our own converter
declines to bridge it. All are already tracked; the table exists so a reader does not mistake one
for a ThoughtSpot limitation.

| Row | What is lost | Why it is ours, not the product's | Tracked | Fidelity |
|---|---|---|---|:-:|
| from-SF **L10** | `\|\|` string concatenation — `ts snowflake translate-formulas` rejects the operator and **drops the whole construct** into `skipped[]` | `\|\|` is the ANSI standard operator and `CONCAT` is already a documented **bidirectional** mapping. The skip message itself names the fix. A mechanical N-ary fold, no judgment involved | **BL-180** (Tier 1, ready to fix) | **High** |
| to-SF **L1** | Parameters — formulas referencing one are omitted entirely | Snowflake session/bind `variables:` went GA June 2026, so a target now exists | **BL-031** | Medium |
| to-SF **L12** | `sql_view` with complex SQL is not auto-mapped | The `base_table.definition:` direct form is the documented target and is simply not emitted yet | **BL-031** | Medium |
| to-SF **L13** | Raw `SUM`/`AVG`/`MIN`/`MAX` measures all route to `metrics[]`; `facts[]` is never used | Output is correct and live-verified — this is fidelity of *shape*, not of results | **BL-031** | Low |
| from-DBX **L3** | MV `parameters:` (GA 18.2+) is parsed and not translated | Deferred automation, not an absent target | — | Medium |
| from-DBX **L11** | `build_table_tml` defaults every numeric column to `MEASURE` + `SUM`, so surrogate keys and MV-declared dimensions arrive as summable measures | The function **already accepts** `column_type`/`aggregation` overrides; the skill's `tables.json` spec documents only `{name, dbx_type}`, so no documented run passes them. The MV's own dimension list and join `on` clauses name the right answer for free | **BL-176** | Medium |
| from-DBX **L12** | Any `format:` that is not a currency-on-a-measure is **dropped silently** — no diagnostic, no summary line | The drop may be unavoidable; the **silence** is not. There is no warnings channel to report it in | **BL-196** | Medium |
| to-DBX **L1** | A `sql_view` entry in `--tables` crashes `build-mv` with a `KeyError`-shaped failure | A crash is a defect regardless of whether the construct is mappable | — | Medium |
| to-DBX **L5** | The 2-argument `{0}`-template SQL pass-through raises `UntranslatableError` | The single-argument form is implemented; the template form is unfinished work, not an absent target | — | Low |
| to-SF **L11** | Model-level `filters[]` — **nothing is emitted at all** | The matrix says *"emitted as a named `filters:` entry"* and a properties doc marks emission **"done"**. Neither is true: `_assemble_ddl` has no filter clause and the model's `filters[]` is never read. A silent drop of the construct our own Ossie work calls the loudest semantic loss | — (**new**) | **High** |
| to-SF **L9** | Table `rls_rules` — never read, dropped with **no unmapped-report record** | The stated reason ("RLS rules are not exported in TML") is false — see Corrections #10 | — (**new**) | Medium |
| from-DBX **L3** | MV `parameters:` is reported as `unknown_key`, not parsed | The matrix claims it is "parsed but not translated"; `mv_parse.py` omits it from `_KNOWN_TOP_KEYS` | **BL-102** | Medium |
| to-DBX **L11** | `rank(...)` is classified as a window measure but `emit_window_measure` has no dispatch branch for it | Fails loud into `skipped[]` — a missing branch in our own dispatch table | — | Medium |

### The stash is the single fix for most of this bucket

**BL-166** is the largest item here and deserves its own note, because it is the converter-side
mirror of product gap **G1**. Across the four semantic-layer matrices, **45 limitation rows**
resolve to *"documented in the Unmapped Report, then gone"* — `format_pattern`, `geo_config`,
`column_groups`, `default_date_bucket`, `custom_order` and locale aliases on the way out;
`ACCESS_MODIFIER: PRIVATE`, table-level synonyms, `is_enum` and sample values on the way in.

The sharp part of the finding is that **we already ship the plumbing and do not use it for
preservation**: `ts-convert-to-snowflake-sv` emits `with extension (CA='{ca_json}')` and
`ts-convert-from-snowflake-sv` parses that same clause, yet the from-side matrix records the
handling as *"Parsed only … not mapped to TML"*. Ten of the eleven upstream Ossie vendor
converters solve the identical problem with a `write_stash`/`read_stash` pair over
`custom_extensions`.

> **Correction to BL-166 itself, found while assembling this document.** The entry states *"41
> limitation rows … (13 to-SF, 8 from-SF, 10 to-DBX, 10 from-DBX)"*. Counted 2026-09-02 the
> matrices hold **45** — to-SF 13 ✓, **from-SF 10** (not 8), to-DBX 10 ✓, **from-DBX 12** (not
> 10). The compliance-gaps document corrected the *total* to 45 on 2026-08-31 but BL-166's own
> breakdown was never updated. Worth a one-line fix so the two agree.

---

# Part B — What ThoughtSpot expresses that no peer can

The mirror of Part A, built the same way. The richest source is not marketing material: it is the
**`to-` direction limitation tables** of our own converters. Every row there is a ThoughtSpot
construct a converter had to drop because the target had nowhere to put it — an inventory of
differentiators written from the other end, by engineers with no incentive to flatter the product.

Claims are graded the same way, and the peer-absence half is verified against each vendor's **own
current documentation**, not against our repo's copies of it:

- Snowflake — the [`CREATE SEMANTIC VIEW` grammar](https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view)
- Databricks — the [metric view YAML reference](https://docs.databricks.com/aws/en/business-semantics/metric-views/yaml-reference)
- Ossie — [core-spec](https://github.com/apache/ossie) at `0.2.0.dev0`

## B0. Read this before quoting anything below

Three disciplines, each of which changed a row during drafting:

1. **"Absent from the grammar" ≠ "the product cannot do it."** Snowflake enforces row access with
   *row access policies* and Databricks with Unity Catalog — outside the semantic object. The
   honest claim is **"ThoughtSpot declares it in the model; the peer declares it elsewhere"**,
   which is a real portability and governance difference and is *not* the same as "they can't".
2. **Documented ≠ used.** Several rows below are carried by ≤5 documents out of 500 on a real
   cluster. Accurate to call them supported; misleading to call them adopted.
3. **Five candidate rows were cut entirely** — see B5. Three were true when our converters were written and stopped being true as the peers shipped.

## B1. Query-time semantics — the strongest group

ThoughtSpot's model is consumed by an *unpredictable* query (a search phrase, a Spotter question),
not a fixed report. Several constructs exist specifically to stay correct under that, and they have
no peer analogue because the peers assume the query shape is known.

| Capability | What it does | Peer position | Confidence |
|---|---|---|:-:|
| **Query-aware LOD** — `group_aggregate(m, query_groups(), query_filters())` | The aggregation grain is resolved **from the user's live query** rather than declared | **Matched by Databricks — this claim is cut.** The vendor documents a **Coarser LOD**: *"aggregate at a coarser granularity than the query by excluding specific fields from the grouping"*, with stated use cases *"dynamic groupings"* and *"aggregates that adapt to query groupings"*, spelled `window: [{order: <excluded>, range: all, semiadditive: last}]`. Our matrix's "no Databricks analogue" is a **converter** limitation stated as a platform fact | ~~`matrix`~~ **refuted** |
| **Dynamic window partitions** | Every `moving_*`/`cumulative_*` completes its partition at query time. Note this is **G15's other face**: the same design that blocks a static `PARTITION BY` is what makes these queries adaptive | **None** — and it is why upstream ask **A10** is bidirectional | `live` |
| **Chasm-trap control** — `is_attribution_dimension` | Marks a column as not producing meaningful attributions across a chasm trap, so a multi-fact query fans out correctly instead of double-counting | **None.** Neither peer models multi-fact chasm traps at all; both assume a single source or a star join | `live` |
| **Aggregate-aware routing** — `aggregated_models[]` | A primary Model declares associated aggregate Models; Search/Spotter/Liveboard queries transparently route to a smaller pre-aggregated table when its columns fully satisfy the query | **Partial.** Databricks has `materialization` for query acceleration, but the ThoughtSpot form is a **first-class semantic association** with per-column date-grain declarations | `live`, see caveat |
| **Search-index control** — `index_type` | Five values (`DEFAULT`, `DONT_INDEX`, `PREFIX_ONLY`, `PREFIX_AND_SUBSTRING`, `PREFIX_AND_WORD_SUBSTRING`) governing how a column is reachable by natural-language search | **None.** Neither peer has a search index to control. The heaviest-used property in the census — 3,629 occurrences across 134 of 143 Models | `live` |

**Caveat on aggregate-aware routing.** Real but thinly evidenced: **zero** of 143 Models on
`se-thoughtspot` carry it; the only live evidence is 4 blocks on a different cluster
(champ-staging 26.9.0.cl-31). Routing precedence is **first-match by definition order**, not
auto-smallest. And **do not quote our schema reference's bucket enum** — it documents
`DAY|WEEK|MONTH|QUARTER|YEAR`, while live TML uses the `-LY` form (`DAILY`, `MONTHLY`) plus
`NO_BUCKET`, which our list omits entirely.
([docs](https://docs.thoughtspot.com/cloud/26.6.0.cl/model-aggregate-aware))

## B2. Governance declared *inside* the model

| Capability | What it does | Peer position | Confidence |
|---|---|---|:-:|
| **Row-level security** — `table.rls_rules` | Group- or user-level row filters declared **on the Table object**, with a `ts_groups` variable resolving the current user's groups. Rules are additive (OR), and a table's rules propagate automatically to every Model, Answer and Liveboard built on it | **Much narrower than it looks — both peers enforce row access, just not in the semantic object.** Snowflake's `base_table.definition:` takes arbitrary SQL, so a predicate can sit inside the Semantic View. Databricks is stronger still: Unity Catalog row filters, column masks and **ABAC** flow through a view and are *"evaluated using the session user's identity"* (GA April 2026). The surviving claim is *declaration vs embedding*: ThoughtSpot's rules are structured, introspectable and group-aware, and propagate automatically to every dependent object; a `WHERE` clause and a catalog-level policy are neither structured nor visible to the model | `live`, n=2 |
| **Column security** — CSR and column-level sharing | **Two** mechanisms on different axes, so a tenant can be denied columns either by rule or by share | No in-grammar equivalent in either peer | `spec` |
| **Publishing without copying** | One object lives in the Primary Org and is made *visible* in target Orgs — no copy, no new GUID, no GUID mapping. Per-tenant variation comes from runtime template variables | No peer concept — neither has a multi-tenant object graph at all | `spec` + [docs](https://docs.thoughtspot.com/cloud/latest/orgs-overview) |
| **Per-locale / per-Org column aliases** | One Model showing different display names and descriptions keyed by locale, org and group | No peer concept | **Weak — see caveat** |

**Caveat on RLS.** `rls_rules` lives on the **Table**, never the Model (a Model carries only
`properties.is_bypass_rls`). Its documented shape was **wrong in our own reference until
2026-07-30**, and both the correction and every `Required:` claim inside the block rest on **a
single live sighting** (1 of 275 Tables). Weight the claim accordingly.

**Caveat on aliases — do not lead with this one.** It is **Beta and feature-flag-gated**
(10.13.0.cl+), it is a **separate document type** (`column_alias:`) rather than part of the semantic
model, and `thoughtspot-model-tml.md` has no coverage of it at all (**BL-114**, still open). It also
has a sharp edge: the model reference inside an alias document must use `obj_id`, **not `fqn`** —
`fqn` returns `status_code: OK` and silently persists nothing.

## B3. The natural-language surface

| Capability | Peer position | Confidence |
|---|---|:-:|
| **Per-column `synonyms`** — 2,812 values across 96 of 143 Models | **Matched.** Snowflake has `WITH SYNONYMS`, Databricks v1.1 has agent-metadata synonyms. *Not* a differentiator — see B5 | `live` |
| **Per-column `ai_context`** — free-text business prose, 656 values | Roughly matched (Snowflake `COMMENT`, Databricks `comment`) — the difference is per-column granularity, not existence | `live` |
| **Spotter coaching objects** — reference questions, feedback, business terms as first-class objects | **None.** Ossie's `ai_context.examples` is the nearest concept and is not interchangeable. Deliberately not carried into Ossie (**NM4**) | `spec` |
| **AgentQL (Semantic SQL)** — query the model in a semantic language and inspect the warehouse SQL ThoughtSpot generates | Snowflake has Cortex Analyst and Databricks has Genie; the ThoughtSpot difference is a **queryable, inspectable API contract** over the model | `spec` |

> **The honest framing for this group:** ThoughtSpot's advantage is not that it has NL metadata —
> every peer now does. It is that the coaching artifacts are **first-class, separately governed
> objects** rather than string properties. Note the flip side is **G5**: model-scope AI
> configuration is not in the model's TML at all, so this strength is currently unversioned.

## B4. Presentation and time semantics carried by the model

Snowflake's grammar has none of these (`NOT PRESENT IN GRAMMAR` for every row); Databricks has
display formatting only, added in spec v1.1.

| Property | What it carries | Census reach | Peer |
|---|---|---|:-:|
| `properties.calendar` | Gregorian, **fiscal**, or any custom calendar on a date column | 72 occ / 35 of 143 Models | **◐** — see below |
| `format_pattern` | Display format for a number, **date** or currency column | 98 occ / 38 Models | ○ ◐ ○ |
| `currency_type` | `iso_code`, `column`, or `is_browser` | 81 occ / 21 Models | ○ ◐ ○ |
| `geo_config` | Five role shapes: `region_name` (a dict), `latitude`, `longitude`, `country` (a bare boolean), and `custom_file_guid` + `geometryType` | 134 occ / 43 Models | ○ ○ ○ — **the strongest row here.** Snowflake's dimension type enum has no `GEOGRAPHY`; Databricks denies it explicitly: *"GEOMETRY columns are not supported as dimensions in metric views"* |
| `custom_order` | Explicit value ordering on an attribute (e.g. weekday names) | 11 occ / 7 Models | ○ ○ ○ |
| `column_groups` / `data_panel_column_groups` | Folder structure in the data panel | 3 of 143 Models | **◐** — Snowflake `tags:` (GA 2026-05-05, valid at five levels) is a name→value carrier that could hold group membership losslessly, though it is not a folder/panel equivalent |
| `spotiq_preference` | Exclude a column from SpotIQ analysis | — | ○ ○ ○ |

**Fiscal calendars are the weakest row here — and were nearly overclaimed.** Snowflake has no
`fiscal` argument in its `expr` syntax, which is the narrow claim, and it is true. But the *concept*
is fully expressible two ways: arbitrary SQL in a dimension `expr`, or joining the same kind of
calendar table ThoughtSpot itself uses. A real 1,100-line customer Semantic View in this repo
carries a `DIM_TIME` table with dimensions literally named `"Fiscal Year"`, fiscal quarter, month
and week. And ThoughtSpot's own fiscal calendars **are themselves a warehouse table**. So the
difference is *declaration versus construction*, not capability — say that, not "Snowflake cannot do
fiscal years".

**Two further caveats.** `calendar` is **connection-scoped**: the TML value is a bare *name*, meaningless on
an instance whose connection lacks a calendar so named — this is exactly gap **G10**, and it is why
a strength here is simultaneously a portability weakness. And `format_pattern` is a **date-or-number**
format, not the "number display format" our own Model reference calls it; the census found
`yyyy-MM-dd` among Model column values.

## B5. What we should stop claiming

Four candidates were on the working list and are **cut**. Recording them matters more than the rows
that survived — each would have been refuted by anyone who checked.

| Claimed differentiator | Why it is cut |
|---|---|
| **Model-level filters applied to every query** | **Databricks has it.** The MV YAML has a top-level `filter:` — *"a SQL boolean expression that applies to all queries; equivalent to the WHERE clause"*. ThoughtSpot's own form is weaker than we describe it: "applied to every query" holds only when `apply_on_tables` is absent, and all 5 real models observed use the bare form. Snowflake reaches the same end through `base_table.definition:`. **And our own to-Snowflake converter emits no filter clause at all** — see A3 |
| **Runtime parameters** | **Both peers have them.** Databricks: *"Bind values at query time with parameters…"* — **Public Preview since 2026-06-26, not GA**; our own schema reference asserts GA in ~9 places and is wrong. Snowflake `variables:` GA June 2026 (single 5-line schema entry, no live round-trip — weak evidence, tag `spec`) |
| **Synonyms for search** | **Both peers have them** — Snowflake `WITH SYNONYMS`, Databricks v1.1 agent metadata |
| **Query-aware LOD** | **Databricks has it** — the "Coarser LOD" form, documented for exactly the *"aggregates that adapt to query groupings"* use case. What survives is narrower and worth stating precisely: ThoughtSpot expresses it as a **first-class function of the query context** (`query_groups()`, `query_filters()`, with set arithmetic over them), where Databricks expresses it as an *exclusion list* on a window. Comparable power, different ergonomics — not a differentiator |
| **`default_date_bucket`** | **Cut for lack of evidence that it exists in a current build.** Our reference lists a value vocabulary with **no citation, no live probe, and zero sightings across 143 Models and 42 Views**. The census's own rule is that a zero of this kind reads as a *possible deprecation signal, not a sampling gap*. Needs a live set-and-export probe before anyone claims it |

**The pattern worth noting.** Three of the four were true when our converters were written and
stopped being true as the peers shipped — Databricks agent metadata (v1.1), Snowflake `variables:`
(June 2026), Databricks parameters (18.2+). That is audit angle 13 doing its job, and it is the
argument for re-running this comparison on a cadence rather than treating it as settled.

---

# Part C — Upstream signal: where the Ossie community's weight is

Ossie is an **early-stage, moving standard** — 91 discussions, 48 open issues, 77 open PRs as of
2026-09-02, with the core spec still at `0.2.0.dev0`. That means engagement is a genuine leading
indicator: a gap several vendors are independently pushing on is far likelier to become spec than
one only we have raised, and a gap the community has *not* raised is one we would have to carry
alone.

Ranked by comments + upvotes/reactions, read 2026-09-02.

## C1. The headline — the community is converging on our list

**Six of the ten highest-engagement discussions map directly onto gaps in Part A that we derived
independently, from converter evidence, before reading them.**

| Upstream item | Engagement | Our gap it lands on |
|---|:-:|---|
| [#342](https://github.com/apache/ossie/discussions/342) Shared Filters, Shared Dimensions & Metric References | **7c · 8↑** | **A3** — model-scope filters; the loudest TS→Ossie loss |
| [#50](https://github.com/apache/ossie/discussions/50) Make Relationship Cardinality Explicit | **5c · 8↑** | **G3** keys & cardinality · **A4** |
| [#31](https://github.com/apache/ossie/discussions/31) Make stable identifiers explicit rather than reusing `name` | **5c · 4↑** | **G2** — a direct hit on the identifier half |
| [#37](https://github.com/apache/ossie/discussions/37) Introduce a concept for "Display name" | **3c · 6↑** | **G2** — the label half · **A5** · drives PR #287 |
| [#44](https://github.com/apache/ossie/discussions/44) Universal calendar support | **3c · 5↑** | **G10** fiscal/custom calendars · **A11(c)** |
| [#19](https://github.com/apache/ossie/discussions/19) Structured `aggregation_method` for Metrics | **3c · 3↑** | **G6** additivity · **A12** |
| [#17](https://github.com/apache/ossie/discussions/17) Replace `is_time` with a `dimension_type` enum | 3c · 8↑ | **G8** type system |
| [#25](https://github.com/apache/ossie/discussions/25) Support field datatype rather than `is_time` | 2c · 7↑ | **G7 / G8** |
| [#32](https://github.com/apache/ossie/discussions/32) Do not prescribe "AI Context" as a key name | 3c · 9↑ | **G5** AI configuration |
| [#4](https://github.com/apache/ossie/discussions/4) Complex Relationship Definitions | 3c · 5↑ | **A6** non-equality joins |

**Why this matters more than it looks.** Part A was built bottom-up from what our converters could
not carry. Part C is what a dozen other vendors independently chose to argue about. The overlap is
the useful signal: **identity/naming, keys and cardinality, calendars, additivity and filters are
not ThoughtSpot idiosyncrasies — they are the semantic-layer industry's current unsolved list.**
That materially strengthens the case for the corresponding A1 rows, because closing them buys
alignment with where the standard is visibly heading, not just with where it is.

## C2. High engagement, no ThoughtSpot gap — watch, don't act

| Upstream item | Engagement | Why it is on our radar |
|---|:-:|---|
| [#46](https://github.com/apache/ossie/discussions/46) How do we expect OSI to be used | 4c · 9↑ | Scope-setting. Determines whether the standard stays semantics-only — which is the premise of our NM3/NM4 non-goals |
| [#40](https://github.com/apache/ossie/discussions/40) Metrics trees / input–output relations between metrics | 6c · 6↑ | **No ThoughtSpot equivalent.** If it lands we inherit a new gap rather than closing one |
| [#29](https://github.com/apache/ossie/discussions/29) Top-level `metrics` vs dataset-level `measures` | 6c · 4↑ | Structural. Would change how every converter maps ThoughtSpot MEASURE columns |
| [#82](https://github.com/apache/ossie/discussions/82) Add `verified_queries` as a core element | 7c · 2↑ | Snowflake already has it and we map it to NLS Feedback TML. Core-spec status would make that mapping portable |
| [#42](https://github.com/apache/ossie/discussions/42) Native support for units | 2c · 6↑ | Adjacent to `currency_type`; a unit concept would give it a home |
| [#21](https://github.com/apache/ossie/discussions/21) Dimension Hierarchies | 3c · 4↑ | Worth checking what ThoughtSpot can express here before it becomes a gap |
| [#109](https://github.com/apache/ossie/discussions/109) Structured dataset `source` representation | **8c** · 1↑ | Highest comment count of any discussion. Bears on our Connection non-mapping |

## C3. A live tension with our own ask — worth knowing before we push A1

[Issue #52](https://github.com/apache/ossie/issues/52), *"Only allow one dialect per OSI document"*
(4 reactions, no comments, open since 2026-01-29), runs **against** the premise of **A1**. A1 asks
for a `THOUGHTSPOT` entry in the `Dialect` enum precisely so a ThoughtSpot formula can travel
alongside warehouse SQL. If one-dialect-per-document carries, that co-existence is the thing being
legislated away.

Related and pulling the other way:
[#16](https://github.com/apache/ossie/discussions/16) *Add Default Dialect at Dataset Level*
(3c · 7↑) would make dialect a **dataset-scoped** property. Neither has been resolved, and A1
should be argued with both in view rather than in isolation.

## C4. Where the ecosystem's energy actually is — converters, not spec

The most-reacted-to open issues are not spec proposals at all:

| Issue | Engagement |
|---|:-:|
| [#227](https://github.com/apache/ossie/issues/227) Add a Lightdash converter | 4c · **7 reactions** |
| [#248](https://github.com/apache/ossie/issues/248) Add a Cube converter | 3c · **5 reactions** |
| [#107](https://github.com/apache/ossie/issues/107) Adopt `ontology-query` as an Ontology Access Layer | 1c · **6 reactions** |
| [PR #289](https://github.com/apache/ossie/pull/289) Bidirectional Cube converter | **12 comments** — the busiest open PR |
| [PR #332](https://github.com/apache/ossie/pull/332) Top-level `prefixes` + Ontology Component | **10 comments** |
| [PR #152](https://github.com/apache/ossie/pull/152) Databricks Unity Catalog Metric View converter | 6 comments |

> **The uncomfortable datum.** Our own [issue #285](https://github.com/apache/ossie/issues/285)
> (*Proposal: ThoughtSpot converter, bidirectional TML ↔ Ossie*) carries **1 comment and 0
> reactions**, as does [#269](https://github.com/apache/ossie/issues/269) (*Evaluate a ThoughtSpot
> TML converter*). Comparable converter proposals draw five to seven reactions. Combined with the
> compliance document's *"zero replies in 32 days"* on seven asks posted into low-traffic
> discussions, the pattern is consistent: **our upstream presence is not landing**, and the two
> asks re-routed on 2026-09-01 into live venues (#342, #290) are the test of whether venue choice
> was the cause. Worth re-reading those two threads in a fortnight — that is a cheap, dated check
> with a real decision attached.

## C5. How to keep this current

Engagement is the fastest-moving thing in this document — faster than either product. The queries
that produced it are cheap and worth re-running with the external audit sweep (angle 13):

```bash
# Discussions by engagement
gh api graphql -f query='{repository(owner:"apache",name:"ossie"){discussions(first:100,
  orderBy:{field:UPDATED_AT,direction:DESC}){nodes{number title upvoteCount
  comments{totalCount}}}}}'

# Open issues and PRs by comments + reactions
gh api "repos/apache/ossie/issues?state=open&per_page=100" --paginate \
  --jq '.[] | {n:.number, c:.comments, r:.reactions.total_count, t:.title}'
```

---

# Corrections this document makes

Assembling this analysis meant re-verifying claims rather than transcribing them, and **eighteen
did not survive**. They are listed here rather than quietly fixed, because several are cited in
documents that will outlive this one, and two are already shaping converter behaviour.

Every claim below was checked against a source *outside* the document making it — vendor
documentation, the live GitHub API, the TML census, or the emitting code.

## D1. Claims in `docs/ossie/ts-ossie-compliance-gaps.md`

| # | Claim | Status |
|---|---|---|
| 1 | *"10 of the eleven vendor converters use `custom_extensions`, dbt the sole exception"* (G1) | **Unsupported — do not repeat.** Uncited; the only "ten of the eleven" in the evidence base is about **CI workflows**, not the stash. And the named exception looks wrong: the same review documents the **Snowflake** converter as the non-user (*"no `write_stash`/`read_stash` pair"*), while dbt is one of only two converters depending on the shared package. **Highest-risk sentence in that document for external credibility** |
| 2 | *"stricter than any peer"* (G2, display-name uniqueness) | **Over-quantified.** The source establishes only "stricter than **Ossie's** per-dataset field uniqueness". The underlying fact — whole-model uniqueness across `columns[]` *and* `formulas[]` — is solid. Rewrite as *"stricter than the standard's per-dataset scope"* |
| 3 | A1 *"Blocking … blocks the entire reverse direction"* | **Retracted at source.** The construct mapping says *"High, not blocking — re-graded 2026-08-31 … that was overstated"*, with nvidia's `ANSI_SQL` shipping as precedent. Also missing: the ask is now [apache/ossie#351](https://github.com/apache/ossie/issues/351) |
| 4 | A7 bare *"Open"* | **Stale.** Partly answered upstream 2026-08-28 (PR #330 / issue #301): derivation is tolerated, coverage not equality is the test |
| 5 | A2 *"**the** well-known vendor-extension examples table"* | **Mis-targeted.** There is no single table — three have diverged (`spec.md:439-448` 8 entries, `ossie-schema.json:31` 7, `converters/README.md:70-78` 7) |
| 6 | G12's prose list of missing functions | **Four of the named items are in the wrong bucket.** `dense_rank` and `NTILE` sit inside G15's window nine; `date_trunc` and `count(*)` are classified **`direct`**, i.e. natively mapped. Cite the 11/9/17 counts instead |
| 7 | The V1–V4 paragraph in *How this stays current* | **Four errors in one paragraph.** V4 is **CLOSED** ("will not be verified, and should not be"); V3 has "nothing to verify"; V1 is **substantially settled** and needs a `calendars` API read, not another export; so "none should be relied on until it is" is wrong for three of four |
| 8 | The venue pointer (*"the authoritative record is the mapping documents' own asks tables, not duplicated here"*) | **Inverted.** The compliance doc now holds the corrected venues while the mapping docs' columns are the dead ones — a reader following the stated pointer lands on exactly the two threads (#5, #19) the correction identifies as dead |
| 9 | A3 and A12 listed as *venue corrected, awaiting posting* | **Both were posted 2026-09-01** (#342 and #290). Correspondingly, *"zero replies in 32 days"* is now a statement about the **old** venues only |

## D2. Claims in the converter coverage matrices

| # | Claim | Status |
|---|---|---|
| 10 | to-SF **L9**: *"RLS rules are not exported in TML"* | **False**, and asserted in three places. `thoughtspot-table-tml.md` documents a full `table.rls_rules` structure, corrected 2026-07-30 by a 275-Table live census. The row also conflates model-level `is_bypass_rls` with table-level rules. Real position: TS RLS **is** exportable, the converter reads none of it, and it is dropped with no unmapped-report record |
| 11 | to-SF **L11**: *"Emitted as a named `filters:` entry"* (and a properties doc marking emission **"done"**) | **False.** `_assemble_ddl` writes `tables`/`relationships`/`dimensions`/`metrics`/`comment`/`with extension` and nothing else — zero occurrences of "filter" in the file. The model's `filters[]` is never read. The gap is **larger** than published *and* the platform is **more capable** than published |
| 12 | from-DBX **#79**: *"percentage formatting has no ThoughtSpot equivalent"* | **Contradicted by our own schema.** `properties.format_pattern` lists `"#,##0.0%"` (percentage) among its common values. Both platforms have it; only the converter does not |
| 13 | to-DBX **L2** (*"no MV field carries free-text AI context"*) and **L6** (*"no Databricks analogue"* for `query_groups()`) | **Both overstated.** MV carries per-column `comment:` and `synonyms:`; and Databricks documents a **Coarser LOD** for exactly the adaptive-grouping use case. Both are converter choices stated as platform facts |
| 14 | from-DBX **L3**: MV `parameters:` is *"parsed"* | **Not parsed.** `mv_parse.py` omits `parameters` from `_KNOWN_TOP_KEYS`, so a real parameter block is reported as `unknown_key`; `mv_build_model.py` still comments *"MVs have no parameters"* (**BL-102**, open) |
| 15 | Databricks `parameters:` is **GA** (asserted in ~9 places incl. a section heading and an anchor URL slug) | **Public Preview**, announced 2026-06-26, with no GA note through August 2026 |
| 16 | `ts-databricks-properties.md` cites `properties.calendar_type` | **Field does not exist** in any ThoughtSpot schema. The real field is `properties.calendar`. Wrong in three places |
| 17 | `sv_build_sv.py`'s `data_panel_column_groups` check | **Dead code.** It tests inside `columns[].properties`, while the schema documents the key as a **sibling** of `properties` — so the branch can never fire |
| 18 | BL-166: *"41 limitation rows (13 to-SF, 8 from-SF, 10 to-DBX, 10 from-DBX)"* | **45**, counted 2026-09-02: from-SF is **10** (not 8) and from-DBX is **12** (not 10). The compliance document corrected the total on 2026-08-31 but BL-166's own breakdown was never updated |

## D3. The promotable finding

Two agents reached this independently, from opposite directions:

> **`agents/cli/ts-convert-*/references/coverage-matrix.md` carries no currency anchor and is
> nudged by no validator.** `check_mapping_currency.py` anchors `agents/shared/mappings`,
> `agents/shared/schemas`, `docs/ossie` and now `docs/gaps` — but not the matrices.
> `check_coverage_matrix.py` checks existence, sections and row counts, never currency.

Every one of items 10–14 above is rot in a file the harness **cannot see**. The Databricks matrices
were last touched 2026-07-31 while five later commits updated the schema they cite; both Snowflake
matrices are unanchored too. This is the shape the repo's two-bucket rule exists for: adding
`agents/cli/ts-convert-*/references/coverage-matrix.md` to `ANCHORED_DIRS` (plus an anchor line in
each of the nine matrices) closes the whole class rather than fixing five instances of it.

**Not done in this change** — it touches nine skill-owned files and warrants its own PR. Recorded
here as the recommended next action.

## D4. A structural finding about the Databricks matrices

The Databricks matrices carry **13 and 10** limitation rows to Snowflake's **13 and 10** — but with
*zero overlap* on the metadata class. Every Databricks L-row is a **formula-emitter** limitation;
RLS, custom sort, column groups, locale aliases, format patterns and default date buckets each have
a row in the Snowflake matrices and **none** in the Databricks ones.

That is not because Databricks supports them. It is because the two converter pairs were audited
along different axes. This is an **angle-9 implementation-drift** finding in the sense
`.claude/rules/repo-audit.md` defines — converters disagreeing on *how* they are built rather than
on semantics — and it is why roughly half of any "Databricks has no equivalent" list currently
reads as unsourced.

---

# How this stays current

Every claim here is about four products that all move, so the document decays by construction. It
carries the same machinery the repo uses for any other external-dependency claim.

- **Currency anchor.** The header carries `<!-- currency: semantic-layer-peers — 2026-09 -->`, and
  `docs/gaps` was added to `ANCHORED_DIRS` in `tools/validate/check_mapping_currency.py` in the same
  change — so this file now nudges at six months like every mapping and schema reference. Without
  that one-line addition the anchor would have been decoration.
- **Re-run cadence.** Part C decays fastest (weeks), Part B next (a vendor release), Part A slowest.
  Fold the Part C queries into the **external audit sweep** (angle 13) rather than running them ad
  hoc — they take under a minute.
- **The dated check with a decision attached.** A3 and A12 were re-posted into live upstream venues
  on 2026-09-01 after 32 days of silence in dead ones. **Re-read #342 and #290 around 2026-09-15.**
  If they are still silent, venue was not the problem and the engagement strategy needs rethinking
  rather than repeating.
- **The evidence classes are not decoration.** Anything tagged `spec` or `inferred` should be
  re-verified before it is quoted outside this repo. Two rows are explicitly flagged as needing a
  live probe: **`is_additive`** (set `false`, export, observe — this decides how much of G6
  survives) and **`default_date_bucket`** (set and export — this decides whether the field exists in
  a current build at all).

## What this document deliberately does not do

- **It does not route the Part A1 gaps.** Under the repo's two-bucket rule a finding is not done
  until it is a validator or a dated `BL-NNN`. A1 is the exception on purpose: these are input to a
  **product** conversation, not repo work. A3 and the Corrections register *are* repo work and carry
  IDs or a recommended action.
- **It does not restate the Ossie compliance document.** `G` numbers stay canonical there; this
  document regroups, adds peer columns, and corrects. Where the two disagree, the Corrections
  register says which is right and why.
- **It does not claim completeness on Databricks.** Per Corrections D4, the Databricks matrices were
  audited along a narrower axis than the Snowflake ones, so absence of a Databricks row is weaker
  evidence than absence of a Snowflake row. Several Part B rows say so inline.
