# Audit Check Catalog

Every check `ts audit run` makes is a **rule** in the rule catalog — YAML under
`tools/ts-cli/ts_cli/audit/catalog/` (`categories.yaml`, `profiles.yaml`, `rules/*.yaml`),
read by a small rule engine (`ts_cli/audit/engine/`). The catalog is the single source of
truth: the tables below, the report's category tabs, labels and recommendations, and the
audit JSON's `check_meta` are all generated from it.

---

## How rules work

A rule names the object it reports on (`scope`: a Model, a column, a join, an RLS rule,
an Answer formula, …), how to judge it (`aggregate`: a ratio, a count, each matching item,
a group, a pair of Models, a composite score), and how to grade the result — `bands`
(e.g. `HIGH < 25%, MEDIUM < 50%`) or a fixed or mapped `severity`. A few rules whose logic
no declarative form expresses are **code rules** (`implementation: code:<name>`), a
registered function in `ts_cli/audit/engine/code_rules*.py`; they are described in the
catalog like any other rule.

Rules belong to one or more **categories** (`A` AI Readiness, `D` Data Modeling,
`H` Human Readiness, `P` Performance, `S` Security). `ts audit run --angles A,D` runs every
rule in any of the named categories. Each rule declares the data it reads (`requires`,
`uses`), and the audit fetches exactly that — a rule that needs Answer TML gets it
whichever category selected it.

Rules are measured against an **assessment profile** (`ts audit run --assessment
spotter|general`, default `general`). A profile may override a rule's `status`, `bands`,
`severity`, `message` and `remediation` — never what the rule means.

## Changing a rule

The full procedure — confirming the rule with the user, the syntax, the gates, the
pinned findings and the snapshot check — is [rule-authoring.md](rule-authoring.md).
In short, edit the rule's YAML entry, then:

1. `python3 tools/validate/check_audit_catalog.py --root .` — vocabulary, ids, overrides,
   band order, examples, declared data reads, and that this file is current.
2. `python -m ts_cli.audit.generate` (from `tools/ts-cli/`) — regenerates the tables
   below. Never edit them by hand.
3. `pytest tools/ts-cli/tests/` — every rule's `fires` / `silent` examples run as tests.

A rule's id is permanent. To remove a rule, set `status: retired` (it stays listed under
"Retired rules"); never delete the entry or reuse its id — CI's catalog gate
(`check_audit_catalog.py --base origin/main`) fails either.

---

## Rules

<!-- BEGIN GENERATED -->
<!-- Generated from tools/ts-cli/ts_cli/audit/catalog/ by `python -m ts_cli.audit.generate`. Do not edit by hand: the catalog gate fails when this block is stale. -->

Assessment profiles: `spotter` (Spotter-ready), `general` (General, default). Where a rule grades or words a finding differently per profile, each profile is shown.

### AI Readiness (A)

Description/synonym coverage, AI context, Spotter readiness score.

| ID | What it detects | Severity | Finding text | Remediation |
|---|---|---|---|---|
| A1 | **Description coverage below threshold.** Share of a Model's columns with a non-blank description, against the profile's pass mark (Spotter-ready 95%, General 50%). | Spotter-ready: HIGH < 47.5%, MEDIUM < 95% · General: HIGH < 25%, MEDIUM < 50% | “{matched}/{total} columns have descriptions ({pct:.0f}%)” | Run /ts-object-model-coach to improve descriptions, synonyms, AI context |
| A2 | **Synonym coverage below threshold.** Share of a Model's columns carrying synonyms (under `properties:`, where Model TML keeps them, or at the column root), against the profile's pass mark (Spotter-ready 80%, General 25%). | Spotter-ready: HIGH < 40%, MEDIUM < 80% · General: HIGH < 12.5%, MEDIUM < 25% | “{matched}/{total} columns have synonyms ({pct:.0f}%)” | Run /ts-object-model-coach to improve descriptions, synonyms, AI context |
| A3 | **No AI instructions configured.** A Model with no Spotter coaching — no instruction in its ai/instructions response and no `model_instructions.data_model_instructions` in its TML. A Model whose instructions lookup failed is skipped, not reported. | Spotter-ready: HIGH · General: MEDIUM | “No AI/Spotter coaching instructions configured” | Run /ts-object-model-coach to improve descriptions, synonyms, AI context |
| A4 | **Missing Spotter config.** A Model with no (or a blank) description. | Spotter-ready: HIGH · General: MEDIUM | “Model has no description” | Run /ts-object-model-coach to improve descriptions, synonyms, AI context |
| A5 | **Spotter readiness composite score.** A weighted readiness score per Model — descriptions 30%, coaching 25%, synonyms 15%, Model description 15%, column-name quality 15% — graded HIGH below 50 and MEDIUM below 80. Not profile-aware. A Model without columns counts as one column, so its score is still defined. | HIGH < 50, MEDIUM < 80 | “Spotter readiness score {score:.0f}/100 (Ready >= 80)” | Run /ts-object-model-coach to improve descriptions, synonyms, AI context |
| A6 | **Measure AI context coverage below threshold.** Share of a Model's visible MEASURE columns with a non-blank `properties.ai_context`. Attributes are not counted: the coach's ai_context schema requires it on every measure (additivity, time basis, grain keys) and leaves it empty, correctly, on most attributes such as surrogate keys. Hidden columns are not searched, so they are not counted. A Model without visible measures is skipped. | Spotter-ready: HIGH < 40%, MEDIUM < 80% · General: LOW < 80% | “{matched}/{total} measures have AI context ({pct:.0f}%) — missing: {unmatched_names}” | Run /ts-object-model-coach to improve descriptions, synonyms, AI context |

### Data Modeling (D)

Complexity, join quality/types, progressive joins, duplicates, grain consistency, SQL pass-through, zero-column tables.

| ID | What it detects | Severity | Finding text | Remediation |
|---|---|---|---|---|
| D1 | **Model complexity exceeds threshold.** Three size measures per Model, each reported on its own when over its MEDIUM line and graded HIGH over its HIGH line: tables (30 / 50), joins (30 / 50) and formulas (30 / 50). Column count is P8's and join depth P7's. The table and join lines come from production call-home data (2026-10: 268k Models, 99th percentile 35 tables). | graded per size measure (tables, joins, formulas), each against its own lines — HIGH, MEDIUM | “{value} {measure} (>{yellow} HIGH, >{green} MEDIUM)” | — |
| D2 | **VARCHAR join keys detected.** Per join (inline, or referencing a Table's `joins_with`): HIGH when its key columns are string-typed on their Table TML (P6's test — a key whose Table TML is not in scope has an unknown type and is not reported), and, separately, MEDIUM when it joins on more than one key pair. The Table TMLs are optional enrichment: the multi-key finding needs none. One join can yield both findings. | graded per join: HIGH for string-typed keys, MEDIUM for more than one key pair — HIGH, MEDIUM | HIGH: “VARCHAR join key(s): {varchar_keys:all}”; MEDIUM: “Multi-column join ({key_pairs} keys)” | — |
| D3 | **Join type analysis (FULL OUTER, LEFT/RIGHT).** An outer join (inline, or referencing a Table's `joins_with`; the model's own type wins): HIGH for a full outer join (ThoughtSpot's `OUTER`), INFO for LEFT_OUTER and RIGHT_OUTER. The type is read case-insensitively. | HIGH when the join type is OUTER; otherwise INFO | HIGH: “FULL OUTER join causes performance issues”; INFO: “{join type} join — may indicate data discrepancies” | — |
| D4 | **Progressive joins disabled on large models.** A Model with more than 5 tables and `join_progressive` off joins every table on every query. Counted as the Model's tables when join_progressive is not set, so the count is 0 — and silent — on a progressive Model. Same rule as P4. | HIGH > 5 | “join_progressive is false on model with {count} tables (>5)” | — |
| D5 | **Orphan tables in model (Cartesian risk).** A table of a multi-table Model that is on neither side of any join — keyed by its alias, else its name, on the declaring side and by the join's `with` on the other. | HIGH | “Table '{name}' has no joins — Cartesian product risk” | — |
| D6 | **Grain consistency — fact tables with >40% attributes.** A fact table (more than 3 MEASURE columns) more than 40% of whose model columns are ATTRIBUTEs, its columns found by its alias, else its name. The metric is that share as a percentage, rounded to one place. | LOW | “Fact table '{name}' has {number of ATTRIBUTE columns}/{number of the table's columns} ATTRIBUTE columns (>40%)” | — |
| D7 | **High model overlap detected.** Two Models whose table sets (each table's fqn, else its name) share tables, graded by Jaccard similarity: HIGH when identical, MEDIUM above 0.5. Reported once per pair, on the first Model's guid. | HIGH ≥ 1, MEDIUM > 0.5 | HIGH: “Identical table sets ({union} tables) — likely duplicate models”; MEDIUM: “High overlap: {shared}/{union} tables shared (Jaccard {similarity:.2f})” | Run /ts-dependency-manager (Repoint mode) to consolidate overlapping models |
| D8 | **Duplicate table objects found.** Two or more Table objects (ONE_TO_ONE_LOGICAL or SQL_VIEW in the metadata) on one physical table — the same connection, database, schema and table name. Reported once per physical table, on the first object's guid. | HIGH > 1 | “{size} ThoughtSpot objects point to the same physical table” | Run /ts-dependency-manager (Remove mode) to remove duplicate table objects |
| D9 | **SQL pass-through function usage (>20% formulas).** More than 20% of a Model's formulas call sql_int_aggregate_op, sql_string_aggregate_op or sql_bool_aggregate_op (any case). | LOW > 20% | “{matched}/{total} formulas use sql_*_aggregate_op ({pct:.0f}%)” | — |
| D10 | **Zero-column tables (bridge vs leaf).** A model table no model column comes from: INFO when it is on either side of a join (a bridge), MEDIUM when not (a leaf). Looked up — and reported — by the table's `name`, so an aliased table always reads zero-column (BL-305, kept). | INFO when the table's place in the joins is bridge; otherwise MEDIUM | “Zero-column {role} table '{name}'” | — |
| D11 | **Fan-out join risk (row multiplication).** A join whose cardinality contains ONE_TO_MANY or MANY_TO_MANY: MEDIUM when both ends read as fact tables (more than 3 MEASURE columns), INFO otherwise. Both ends are looked up by name — the declaring model table's `name` and the join's `with` — so an aliased end reads as unknown (BL-305, kept), and the INFO wording says ONE_TO_MANY whatever the cardinality (kept). | MEDIUM when the join links two fact tables; otherwise INFO | MEDIUM: “Fan-out risk: fact-to-fact join '{table the join starts from}' -> '{with}' with {join cardinality}”; INFO: “ONE_TO_MANY join '{table the join starts from}' -> '{with}'” | — |
| D12 | **Conformed dimension divergence.** A column (by `db_column_name`, else `name`) whose column type differs between Models. Each Model contributes one type per column name — a later column, or a later Model of the same name, overwrites an earlier one — and the detail lists every Model with its type. | MEDIUM | “Column '{name}' classified differently across models: {models}” | — |

### Human Readiness (H)

Name quality, hidden columns, orphans, direct table connections, formula promotion candidates.

| ID | What it detects | Severity | Finding text | Remediation |
|---|---|---|---|---|
| H1 | **Column name quality (anti-pattern regexes).** The share of a Model's columns whose names a person would not search for: col1, field_2, val, tmp_x, a leading digit (any case), or SHOUTING_SNAKE warehouse names. One finding per Model over 10%, listing the first five such names. The same two patterns A5 scores name quality with. | MEDIUM > 10% | “{matched}/{total} columns have anti-pattern names ({pct:.0f}%): {matched_names:head5}” | — |
| H2 | **Description quality (too-short, boilerplate).** Column descriptions that are too short (under 20 characters, stripped), too long (over 400) or open with boilerplate ("This is a", "Column for", "Field for", "The ", "A "); a blank or absent description is A1's remit, not this rule's. One finding per Model, its metric the number of columns with an issue, listing the first three. | LOW | “{count} description quality issues: {issues}” | — |
| H3 | **Unnecessary hidden columns.** A hidden Model column that no formula references by `[<name>]` — nor, when it surfaces a formula, by that formula's `[<display name>]` (an id reference is not seen). Excused when it is the last carrier of a joined table: its `column_id` prefix names a table that declares or receives a join (by `name`, not alias) and no other visible column has that prefix. | MEDIUM | “Hidden column '{name}' not referenced by any formula” | Remove unnecessary hidden columns via TML reimport |
| H4 | **Orphan model with no dependents.** A Model with no dependents but Sets — no Answer or Liveboard (a Set is a column on the Model, so anything using it is a Model dependent already). A Model the dependents lookup did not list has none. | MEDIUM | “Orphan model — zero dependents (no answers or liveboards)” | Run /ts-dependency-manager (Remove mode) if confirmed unused |
| H5 | **Orphan sets (zero consumers).** A Set (once, however many dependents lists name it) whose consumer lookup came back clean and empty. A Set whose lookup failed, was partial or was never made is skipped (`requires: [sets]`): absence means "not looked up", never "no consumers" (BL-302). | MEDIUM | “Orphan set '{name}' — zero consuming answers or liveboards” | — |
| H7 | **Direct table connections (bypasses semantic layer).** An Answer built straight off a Table: one finding per table reference whose `fqn` is a Table's guid — a model table's `fqn` in any Model, or a Table TML in the context. An Answer on a Model carries the Model's guid; an fqn matching nothing known is unresolved, not a bypass (BL-301). The Model and Table TMLs are what the guids are known from, not a requirement: an Answer is judged against whatever the context holds. | MEDIUM | “Answer connects directly to table '{fqn}', bypassing the model layer” | — |
| H8 | **Formula promotion candidate.** The same Answer formula — compared lower-cased, stripped, whitespace collapsed; blank ones ignored — in two Answer formulas or more, and on no Model. Counted per formula, so one Answer holding it twice counts twice. The finding is named by that count, with no guid, listing the first three Answers. | HIGH ≥ 2 | “Formula duplicated in {size} answers but not in model: {members:head3}” | Run /ts-object-answer-promote to promote formula to model |
| H9 | **Redundant answer formulas (duplicating model formula).** An Answer formula whose expression (normalised as H8's) equals a Model formula's — a blank one included — named with the last such Model formula. | LOW | “Answer formula '{name}' duplicates model formula '{Model formula with the same expression}'” | — |
| H10 | **Stale / temporary objects (name pattern match).** A Model name, column name or column description that reads as stale or temporary (do not use, deprecated, test, tmp, copy of, (2), backup, old, …; a name on the safe list — test_results, test_suite, … — never does). Each match is its own finding, a description quoted to 60 characters. Always LOW: nothing reads H4's result. | LOW | “{what} matches stale pattern: '{value}'” | — |

### Performance (P)

SQL Views, scalar formulas, filter/join progressiveness, date constraints, column sprawl.

| ID | What it detects | Severity | Finding text | Remediation |
|---|---|---|---|---|
| P1 | **SQL View used as model source.** A SQL_VIEW Table in the metadata blocks filter pushdown into the warehouse. | MEDIUM | “SQL_VIEW data source blocks filter pushdown” | — |
| P2 | **Scalar formula density (run at query time).** How many of a Model's formulas are scalar — no `columns[]` entry surfacing the formula (by `formula_id`) declares an `aggregation` — graded MEDIUM above 5 and HIGH above 10. Scalar formulas run at query time in the ThoughtSpot engine. | HIGH > 10, MEDIUM > 5 | “{count} scalar formulas (run at query time in TS engine)” | — |
| P3 | **Model filters lacking apply_on_tables.** A Model filter with no `apply_on_tables` is always applied — on every query, whichever tables it touches. | MEDIUM > 0 | “{count}/{total} filters lack apply_on_tables (run on every query)” | — |
| P4 | **Apply-all-joins anti-pattern (join_progressive:false).** A Model with more than 5 tables and `join_progressive` off joins every table on every query. Counted as the Model's tables when join_progressive is not set, so the count is 0 — and silent — on a progressive Model. Same rule as D4. | HIGH > 5 | “join_progressive: false on {count}-table model — every query joins ALL tables” | — |
| P5 | **No date constraints on fact tables.** A Model with fact tables (a `model_tables` entry with more than 3 MEASURE columns, matched by its `name`) but no `date_range_condition` in its `constraints`, so every query scans all history. | MEDIUM | “No date constraints on model with fact tables: {fact tables, first 3}” | — |
| P6 | **VARCHAR join keys (performance framing of D2).** A join (inline, or referencing a Table's `joins_with`) whose key columns are string-typed on their Table TML; string keys join 2-5x slower than integers. A key whose Table TML is not in scope has an unknown type and is not reported. Same keys as D2's HIGH half. | HIGH | “VARCHAR join key(s) — 2-5x slower than integer: {string-typed join keys}” | — |
| P7 | **Join depth exceeding thresholds.** The longest join chain across a Model's tables (the same depth D1 grades), MEDIUM above 3 hops and HIGH above 5. | HIGH > 5, MEDIUM > 3 | “Join depth {value} (>5 HIGH, >3 MEDIUM) — complex query plans” | — |
| P8 | **Column sprawl.** A Model's column count. Above 500 columns Search Data gets hard to use, and above 1,500 query performance suffers (field experience; 0.57% and 0.06% of production Models in the 2026-10 call-home data, where the 99th percentile is 390). The Spotter-ready profile draws the lines lower, at 250 and 500 — PROVISIONAL: more columns give Spotter more names to confuse, but no measurement sets these numbers yet. | Spotter-ready: HIGH > 500, MEDIUM > 250 · General: HIGH > 1500, MEDIUM > 500 | Spotter-ready: “{count} columns — above 250 Spotter has more names to confuse (provisional line); above 500 Search Data gets hard to use” · General: “{count} columns — above 500 Search Data gets hard to use; above 1,500 queries slow down” | — |
| P9 | **High-cardinality ID column indexed as ATTRIBUTE.** An ATTRIBUTE column that is text-search indexed (no `index_type: DONT_INDEX`) and whose name ends like an identifier (`_id`, `_guid`, `_uuid`, `transaction_id`, `row_id`, `surrogate_key`; any case). | MEDIUM | “High-cardinality ID column '{name}' indexed as ATTRIBUTE” | — |
| P11 | **Excessive indexed columns on Spotter-enabled model.** More than 30 text-search indexed columns on a Model with Spotter enabled (`properties.spotter_config.is_spotter_enabled`). Counted as the indexed columns of a Spotter-enabled Model, so the count is 0 — and silent — without Spotter. | INFO > 30 | “{count} indexed columns on Spotter-enabled model” | — |
| P13 | **High RLS rule count (cost compounds per query).** A Table's RLS rule count, MEDIUM above 3 and HIGH above 6; each rule adds to every query's cost. | HIGH > 6, MEDIUM > 3 | “{count} RLS rules — cost compounds linearly per query” | — |
| P14 | **RLS expression uses functions (prevents index pruning).** An RLS rule expression that calls UPPER, LOWER, TRIM, CAST, CONCAT, CONTAINS or IF (any case), defeating index and partition pruning. The detail quotes the first 80 characters of the expression. Same trigger as S9. | MEDIUM | “RLS expression uses functions — prevents index/partition pruning: {expr:.80}” | — |
| P15 | **VARCHAR RLS column without value_casing.** A column an RLS rule references (resolved by name on the Table TML's own `columns[]`) whose warehouse type is a string type and which sets no `value_casing`. An unresolved reference has an unknown type and is not reported. S8 is the same walk without the `value_casing` guard. | MEDIUM | “VARCHAR RLS column '{name}' without value_casing” | — |
| P16 | **Deeply nested if() in formulas.** A Model formula making more than 3 `if (` calls (INFO), or more than 5 (LOW). | LOW > 5, INFO > 3 | “Formula has {value} if() calls” | — |
| P17 | **Formula cross-reference chain depth.** The longest chain of formula-to-formula references starting at a formula (by id or display name, BL-300), INFO above 2 and LOW above 3. Formulas sharing a name are one node and report once. | LOW > 3, INFO > 2 | “Formula reference chain depth {value}” | — |
| P18 | **COUNT_DISTINCT aggregation (most expensive).** A Model column aggregated with COUNT_DISTINCT, which is expensive to compute. | INFO | “COUNT_DISTINCT aggregation on '{name}'” | — |

### Security (S)

PII detection, indexing without RLS, CLS gaps, RLS bypass, credentials in analytics.

| ID | What it detects | Severity | Finding text | Remediation |
|---|---|---|---|---|
| S1 | **PII column detection (heuristic regex).** A Model column whose name reads as personal data — email, phone, national id, date of birth, financial account, person name or street address (the first matching pattern names the category). Always INFO: the pattern's confidence is reported in the detail, never graded. | INFO | “PII detected ({kind of personal data the name suggests}, {how confidently the name suggests personal data} confidence): '{name}'” | Review security settings via ThoughtSpot UI or TML reimport |
| S2 | **PII indexed without RLS (exposes in autocomplete).** A PII column (see S1) that is text-search indexed (no `index_type: DONT_INDEX`), so its values surface in search suggestions. HIGH when the Table its `column_id` prefix names (through `model_tables`, alias first) has no RLS rules on its Table TML — or that Table TML is not in scope — and INFO when it has. The detail says which, so the message is worded per severity. | INFO when the column's table has row-level security; otherwise HIGH | HIGH: “PII column '{name}' is indexed WITHOUT table RLS”; INFO: “PII column '{name}' is indexed (table has RLS)” | Review security settings via ThoughtSpot UI or TML reimport |
| S3 | **PII without CLS or masking formula.** A PII column (see S1) that no masking formula covers: some Model formula calls `is_group_member` and the column's name appears anywhere in the Model's formula expressions (a heuristic over all formulas at once, not per formula). The detail says "no CLS", but column-level security is never read: that wording is the legacy text, kept until the check is fixed. | HIGH | “PII column '{name}' ({kind of personal data the name suggests}) has no CLS or masking formula” | Review security settings via ThoughtSpot UI or TML reimport |
| S4 | **RLS bypass + PII columns in model.** A Model with `properties.is_bypass_rls` set that also holds PII columns (see S1). Counted as the PII columns of a bypassing Model, so the count is 0 — and silent — without the bypass. | HIGH > 0 | “RLS bypass enabled AND model contains {count} PII column(s)” | Review security settings via ThoughtSpot UI or TML reimport |
| S5 | **Credentials in analytics.** A Model column named like a credential — password, passwd, secret key, api key or token as a whole word, any case. CRITICAL, except HIGH for `token`. | HIGH when the credential word in the column name is token; otherwise CRITICAL | “Credential column '{name}' in analytics model” | Review security settings via ThoughtSpot UI or TML reimport |
| S8 | **VARCHAR column used in an RLS rule.** A column an RLS rule references (resolved by name on the Table TML's own `columns[]`) whose warehouse type is a string type. An unresolved reference has an unknown type and is not reported. P15 is the same walk with a `value_casing` guard. | MEDIUM | “VARCHAR RLS column '{name}'” | — |
| S9 | **Function call in an RLS rule expression.** An RLS rule expression that calls UPPER, LOWER, TRIM, CAST, CONCAT, CONTAINS or IF (any case), which prevents filter pushdown. The detail quotes the first 80 characters of the expression. Same trigger as P14. | HIGH | “Function in RLS expression prevents filter pushdown: {expr:.80}” | — |
| S10 | **RLS bypass enabled (disables row-level security).** A Model with `properties.is_bypass_rls` set, so every user sees every row. | MEDIUM | “is_bypass_rls: true — all users see all rows regardless of RLS rules” | — |
| S11 | **RLS join closes a loop with the Model's joins.** The Model's join graph plus the joins an RLS rule on one of its Tables uses (a join on a path some rule expression references, walked outward from the secured table). ThoughtSpot checks only the Model's own joins at import, so a rule that joins back into the Model's graph imports cleanly and then fails every query it applies to with "Guid Mismatch" — query generation sees one table with two roots. CRITICAL: the Model is broken for every user the rule applies to, not merely at risk. One finding per RLS join that closes such a loop. Second routes (diamonds) through an RLS join are not reported: nothing shows them failing. | CRITICAL | “RLS on '{table}' joins out to '{target}' ('{join}'), and joins lead back {back} — a loop query generation cannot resolve (queries fail with "Guid Mismatch")” | Drop one of the two joins, or point the Model at a copy of the table without this RLS rule (or move the rule to another table). |

### Legacy `threshold` payloads

The `threshold` dict each finding has always carried, kept for readers of older audit JSON (the uniform `bands` payload supersedes it).

| ID | `threshold` |
|---|---|
| A1 | Spotter-ready: green=95, assessment=Spotter-ready, yellow=47.5 · General: green=50, assessment=General, yellow=25 |
| A2 | Spotter-ready: green=80, assessment=Spotter-ready, yellow=40 · General: green=25, assessment=General, yellow=12.5 |
| A5 | ready=80, needs_work=50 |
| A6 | Spotter-ready: green=80, assessment=Spotter-ready, yellow=40 · General: green=80, assessment=General |
| D1 | set per finding — graded per size measure (tables, joins, formulas), each against its own lines |
| D4 | min_tables_for_flag=5 |
| D6 | max_attribute_pct=40 |
| D7 | MEDIUM: high_overlap=0.5 |
| D9 | max_pct=20 |
| H1 | max_pct=10 |
| P2 | green=5, yellow=10 |
| P7 | green=3, yellow=5 |
| P8 | Spotter-ready: max=250 · General: max=500 |
| P11 | info=30 |
| P13 | medium=3, high=6 |
| P16 | info=3, low=5 |
| P17 | info=2, low=3 |

### Retired rules

A retired rule keeps its id, which is never reused.

| ID | Title | Why |
|---|---|---|
| H6 | Duplicate sets | Deferred — requires deep set comparison. Retired with no logic: the id stays allocated so it is never reused, and the rule never runs (no profile may revive it). |
| P10 | RLS bypass as exception | Retired before the rule catalog: flagged `is_bypass_rls: true` until ts-audit's check overhaul (#131) removed it. S10 and S4 report RLS bypass now. Recorded as retired so the id is never reused. |
| P12 | Reserved (never assigned) | Retired without ever running: the id was left unassigned when the checks were renumbered (#131). Recorded as retired so it is never handed out by accident. |
| S6 | Conformed dimension divergence (pre-catalog) | Retired before the rule catalog: ran as S6 until ts-audit's check overhaul (#131) moved the check to the data-modeling angle, where it runs as D12. Recorded as retired so the id is never reused. |
| S7 | Reserved (never assigned) | Retired without ever running: the id was left unassigned when the checks were renumbered (#131). Recorded as retired so it is never handed out by accident. |
<!-- END GENERATED -->
