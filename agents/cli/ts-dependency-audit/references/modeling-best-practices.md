# Modeling Best Practices — Audit Framework & Checklist

Authoritative reference for `ts-dependency-audit`. Every check references the TML
field it inspects so the analysis engine can be implemented deterministically.

The skill reads this file at runtime. Changes here change audit behaviour.

---

## Assessment profiles

Two profiles with different pass/fail thresholds. User selects at audit start.

| Profile | Use case | Stance |
|---|---|---|
| **Spotter-ready** | Models serving Spotter / NL search | Aggressive — descriptions >= 95%, synonyms >= 80%, AI context required |
| **General analytics** | Models for manual search / answer building | Lighter — descriptions >= 50%, synonyms optional, AI context recommended |

---

## Five audit angles

| Code | Angle | Focus |
|---|---|---|
| **A** | AI Readiness | Is the model ready for Spotter / NL search? |
| **D** | Data Modeling | Structural best practices — joins, grain, complexity, duplication |
| **H** | Human Readiness | Is the model navigable and well-organised for human users? |
| **P** | Performance | Will queries against this model be fast? |
| **S** | Security | PII exposure, RLS, indexing, access controls |

---

## Scoring conventions

- **Per-check 0.0–1.0 fraction** — e.g. `columns_with_description / total_columns = 0.72`
- **Severity taxonomy** — CRITICAL > HIGH > MEDIUM > LOW > INFO
- **Colour thresholds** — RED / YELLOW / GREEN map fractions to severity per profile
- **Exception allowlist** — known-acceptable findings can be suppressed with a justification;
  suppressed findings still appear in the report marked as "accepted"
- **No composite score** except A5 (Spotter readiness) — each check stands alone

---

## A — AI Readiness

| # | Check | What it detects | TML source | Scoring | Default severity |
|---|---|---|---|---|---|
| A1 | Column description coverage | % of columns with non-empty `description:` | Model: `columns[].description` | Fraction. Spotter-ready: >= 0.95, General: >= 0.50 | RED < 50%, YELLOW 50–79%, GREEN >= 80% |
| A2 | Synonym coverage | % of columns with at least one `synonyms[]` entry | Model: `columns[].synonyms[]` | Fraction. Spotter-ready: >= 0.80, General: >= 0.25 | RED < 25%, YELLOW 25–49%, GREEN >= 50% |
| A3 | AI context presence | Model has Spotter coaching instructions | Model: `model.model_instructions.data_model_instructions` + REST API: `/api/rest/2.0/ai/instructions/get` (open item OI-11) | Boolean | HIGH if absent |
| A4 | Model description | Model-level `description:` present and meaningful | Model: `model.description` | Boolean | MEDIUM if absent |
| A5 | Spotter readiness composite | Weighted score combining A1–A4 + column name quality. The one composite score — ThoughtSpot explicitly recommends it. | Computed from A1–A4 + H1 | Weighted: descriptions 30%, AI context 25%, synonyms 15%, model description 15%, name quality 15% | Ready >= 80, Needs work 50–79, Not ready < 50 |

### Profile thresholds for A checks

| Factor | Spotter-ready target | General analytics target |
|---|---|---|
| Description coverage | >= 95% | >= 50% |
| Synonym coverage | >= 80% | >= 25% |
| AI context | Required | Recommended |
| Model description | Required | Recommended |

---

## D — Data Modeling

| # | Check | What it detects | TML source | Scoring | Default severity |
|---|---|---|---|---|---|
| D1 | Model complexity | Tables, columns, joins, formulas, and join depth per model | Model: `model_tables[]`, `columns[]`, `formulas[]`, `joins[]` | Per-metric GREEN/YELLOW/RED (see thresholds below) | Varies |
| D2 | Join key quality | VARCHAR-to-VARCHAR joins (2–5x slower than integer). Multi-column joins (missing surrogate key). | Model: `joins[].on` → Table: `columns[].db_column_properties.data_type` | Count of anti-pattern joins / total joins | VARCHAR = HIGH, multi-column = MEDIUM |
| D3 | Join type analysis | FULL OUTER often causes performance issues. LEFT/RIGHT OUTER may indicate data discrepancies (not always — flag for review). | Model: `model_tables[].joins[].type` — values: `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `OUTER` | Count by type | FULL OUTER = HIGH, LEFT/RIGHT OUTER = INFO |
| D4 | Progressive joins | `join_progressive` should be true. Without it, every query joins ALL tables regardless of which columns are searched. | Model: `model.properties.join_progressive` | Boolean | HIGH if false on models with > 5 tables |
| D5 | Orphan tables in model | Tables in `model_tables[]` with no join in either direction — Cartesian product risk. | Model: cross-reference `model_tables[].name` against all `joins[].with` | Count of unjoined tables | HIGH |
| D6 | Grain consistency | Fact tables should be mostly measures, dimension tables mostly attributes. | Model: `columns[].properties.column_type` per table. Heuristic: > 3 MEASUREs = likely fact. | Fraction: attributes-in-fact / total | Fact > 40% ATTRIBUTEs = LOW |
| D7 | Model overlap & duplication | Compare table sets across models. **Not all overlap is bad** — conformed dimension reuse across focused domain models is good Kimball-style design (e.g. Product table shared by Sales and Purchasing models). The anti-pattern is two models with near-identical table sets serving the same audience, or mega-models that should be split into domain-specific models. Classification uses table roles: shared dimension tables (mostly ATTRIBUTEs) vs shared fact tables (mostly MEASUREs). See D7 classification rules below. | Model: set of `model_tables[].fqn` — compare all pairs. For each shared table, classify as dimension or fact using D6 heuristic (> 3 MEASUREs = fact). | Jaccard + table-role analysis | See D7 classification rules |
| D8 | Duplicate tables | Different ThoughtSpot table objects pointing at the same physical table. | Table: `(connection.name, db, schema, db_table)` — group by tuple | Count of duplicates | HIGH |
| D9 | SQL pass-through function usage | `sql_*_aggregate_op` formulas. Legitimate for timezone conversions; overuse indicates TS formula limitations being worked around. | Model: `formulas[].expr` regex for `sql_int_aggregate_op`, `sql_string_aggregate_op`, `sql_bool_aggregate_op` | Count / total formulas | LOW (flag if > 20%) |
| D10 | Zero-column tables | Tables in `model_tables[]` with no columns referencing them via `columns[].column_id`. If the table participates in joins (bridge/intermediary), flag as INFO — may cause query generation issues. If the table is a leaf node (no joins in either direction), flag as MEDIUM — no reason to include it. | Model: `columns[].column_id` split on `::` → table name. Cross-reference against `model_tables[].name`. For leaf detection: check `joins[].with` and which tables source joins. | Count by role (bridge vs leaf) | Bridge = INFO, Leaf = MEDIUM |

### D1 complexity thresholds

| Metric | GREEN | YELLOW | RED | Notes |
|---|---|---|---|---|
| Tables per model | <= 10 | 11–15 | > 15 | Kimball: star schema < 10 dims typical |
| Columns per model | <= 50 | 51–75 | > 75 | ThoughtSpot recommends < 50 for Spotter |
| Joins per model | <= 8 | 9–12 | > 12 | |
| Join depth (longest chain) | <= 3 | 4–5 | > 5 | > 5 degrades query plan complexity |
| Formulas per model | <= 30 | 31–50 | > 50 | |

### D7 model overlap classification rules

Compare every pair of models by their `model_tables[].fqn` sets. For each shared
table, classify it as **dimension** (mostly ATTRIBUTEs) or **fact** (> 3 MEASUREs)
using the D6 heuristic.

| Overlap type | Detection | Severity | Interpretation |
|---|---|---|---|
| **Identical table sets** | Jaccard = 1.0 | HIGH | Genuine duplication — consolidate. Include dependent counts to guide which to keep. |
| **Strict subset** | Model A's tables ⊂ Model B's tables | INFO | The smaller model may be a correctly scoped domain view, OR redundant. Report both models and let the user decide. Not a problem by default. |
| **Shared facts** | Overlap > 0.5 AND shared tables include fact tables | MEDIUM | Two models sharing fact tables AND dimensions is more likely to be real duplication worth investigating. |
| **Conformed dimension reuse** | Overlap > 0.5 BUT shared tables are all dimensions (no shared facts) | INFO | Healthy pattern — dimension tables shared across domain-specific models (e.g. Product in Sales and Purchasing). Report for awareness only. |
| **Low overlap** | Jaccard <= 0.5 | — | No finding. Different models with incidental shared dimensions. |

**Key principle:** small focused domain models sharing conformed dimensions is *good*
design. Mega-models (like a 79-table GTM model) are the anti-pattern. The audit
should guide toward splitting mega-models into focused domains, not merging
well-scoped models together. D1 complexity already penalises mega-models; D7
complements it by distinguishing healthy reuse from wasteful duplication.

---

## H — Human Readiness

| # | Check | What it detects | TML source | Scoring | Default severity |
|---|---|---|---|---|---|
| H1 | Column name quality | Generic (`col1`, `field_1`, `val`), temp (`tmp_*`), digit-leading, all-uppercase-underscore names | Model: `columns[].name` | Fraction: anti-pattern / total | MEDIUM if > 10% |
| H2 | Description quality | Too short (< 20 chars), too long (> 400 chars), boilerplate ("This is a column for...") | Model: `columns[].description` | Count of issues / described columns | LOW |
| H3 | Unnecessary hidden columns | `is_hidden: true` columns not referenced by any formula. Hidden columns cause **locked visualizations**. Unused columns should be removed from the model, not hidden. Exceptions: (a) hidden formulas referenced by other formulas (legitimate intermediaries); (b) hidden columns on zero-column bridge tables needed for join-path correctness — the column ensures the query plan is correct but is not needed in the UI for selection (see D10). | Model: `columns[].properties.is_hidden` cross-ref `formulas[].expr` + D10 bridge-table list | Count of hidden non-dependency columns (excluding bridge-table exceptions) | MEDIUM |
| H4 | Orphan models | Models with zero dependents (no answers, liveboards, or sets) | Metadata API: `ts metadata dependents` — zero entries | Boolean | MEDIUM |
| H5 | Orphan sets | Sets with zero consuming answers or liveboards | Metadata API: `ts metadata dependents` on set GUID | Boolean | MEDIUM |
| H6 | Duplicate sets | Sets across models with equivalent filter definitions | Set TML: `cohort.config.anchor_column_id`, `groups[].conditions[]` | Pairwise comparison | LOW |
| H7 | Direct table connections | Answers connected directly to Tables, bypassing the semantic layer | Answer TML: `tables[].fqn` matched against table vs model inventory | Count | MEDIUM |
| H8 | Formula promotion candidates | Formulas duplicated in 2+ answers against the same model but NOT in the model. Should be promoted for single-source-of-truth. | Answer: `formulas[].expr` normalised, grouped by (expr, data source). Cross-ref Model `formulas[]`. | Count of groups not in model | HIGH → `/ts-object-answer-promote` |
| H9 | Redundant answer formulas | Answer formulas that duplicate one already in the model | Answer `formulas[].expr` matched against Model `formulas[].expr` (normalised) | Count | LOW |
| H10 | Stale / temporary objects | Scan **all** object levels for names or descriptions indicating temporary, deprecated, or abandoned artifacts. **Object-level:** models, tables, answers, liveboards, and sets from the metadata inventory. **Column-level:** columns within each model (e.g. `zDEL` prefixed columns). Phase 1 (heuristic): name/description regex across both levels. Phase 2 (with usage data): cross-reference with BI Server — zero queries in 90 days + stale name = strong removal candidate. | **Object-level:** metadata search `name` + `description` for models, tables, answers, liveboards, sets. **Column-level:** Model `columns[].name`. Phase 2: BI Server query count overlay. | Count by level (object vs column) and object type | Object-level match = LOW (MEDIUM if orphan via H4/H5), Column-level match = LOW, Either + zero usage (Phase 2) = HIGH |

### Stale object name/description patterns (case-insensitive)

| Category | Name patterns | Description patterns | Confidence |
|---|---|---|---|
| Explicit exclusion | `\bdo[-_ ]?not[-_ ]?use\b`, `\bDEPRECATED\b`, `\bOBSOLETE\b` | `do not use`, `deprecated`, `obsolete`, `will be removed`, `scheduled for deletion` | HIGH |
| Temporary | `\btest[-_ ]?\d*\b` (but NOT `test_results`, `test_automation`), `\btmp[-_ ]`, `\btemp[-_ ]` | `temporary`, `for testing`, `test only` | MEDIUM |
| Copy artifacts | `^copy[-_ ]of[-_ ]`, `[-_ ]copy\d*$`, `[-_ ]\(\d+\)$` | `copied from`, `clone of` | MEDIUM |
| Deletion candidates | `\bzDEL\b`, `\bDELETE\b`, `\bTO[-_ ]?DELETE\b`, `\bREMOVE\b` | `to be deleted`, `to be removed`, `pending deletion` | HIGH |
| Backup / archive | `\bbackup\b`, `\barchive\b`, `\bbak\b`, `[-_ ]old$`, `^old[-_ ]` | `backup of`, `archived`, `old version` | MEDIUM |
| Version suffixes | `[-_ ]v\d+$`, `[-_ ]v\d+[-_ ]` (except the latest) | — | LOW |

**False-positive mitigation:** Objects matching `test_results`, `test_automation`,
`test_coverage`, `test_environment`, `test_suite` are **excluded** — these are
legitimate analytics objects about testing, not test objects themselves. The
description provides stronger signal than the name: "do not use" in a description
is deliberate, while "test" in a name is ambiguous.

### Column name anti-patterns

| Pattern | Example | Issue |
|---|---|---|
| `col\d+` | `col1`, `col_23` | Generic — meaningless to users and Spotter |
| `field[-_]?\d+` | `field_1` | Generic |
| `val\d*` | `val`, `val2` | Ambiguous |
| `tmp[-_]?` | `tmp`, `tmp_calc` | Temporary — should be removed or renamed |
| Starts with digit | `1_revenue` | ThoughtSpot keyword conflict risk |
| Only uppercase + underscores | `CUSTOMER_ID` | Not user-friendly; consider display name |

### Description quality rules

| Check | Detection | Severity |
|---|---|---|
| Too short | `len(description) < 20` chars | LOW |
| Too long | `len(description) > 400` chars (Spotter considers up to 400) | LOW |
| Boilerplate | Starts with "This is a", "This column", "Column for" | LOW |

---

## P — Performance

| # | Check | What it detects | TML source | Scoring | Default severity |
|---|---|---|---|---|---|
| P1 | SQL View detection | `SQL_VIEW` data sources block filter pushdown — entire view materialised before filtering | Metadata search: `subtype: SQL_VIEW` | Count | MEDIUM |
| P2 | Scalar formula density | Formulas without aggregation using scalar functions — run at query time in TS calculation engine, not pushed to warehouse | Model: `formulas[]` without matching `columns[]` with `aggregation:` | Fraction. RED > 10. | MEDIUM if > 10 |
| P3 | Model filter progressiveness | Filters lacking `apply_on_tables` run on every query regardless of tables involved. With `apply_on_tables`, filter only activates when those tables are in the search. | Model: `model.filters[].apply_on_tables` — present or absent | Count of non-progressive / total | MEDIUM |
| P4 | Apply-all-joins anti-pattern | `join_progressive: false` causes every query to join ALL tables. Almost always an anti-pattern. | Model: `model.properties.join_progressive` | Boolean | HIGH on models > 5 tables |
| P5 | Date constraint coverage | Large fact tables without `constraints[]` risk full table scans. Date constraints ensure a date filter is applied when certain tables are in the search. | Model: `model.constraints[].constraint[].condition[].date_range_condition` | Boolean per likely-fact table | MEDIUM |
| P6 | VARCHAR join keys | 2–5x slower than integer joins on most warehouses. | Model → Table (same data as D2) | Count | HIGH |
| P7 | Join depth | Deep chains degrade query plan complexity. > 5 = consider splitting. | Model (same data as D1 join depth) | Depth value | HIGH if > 5 |
| P8 | Column sprawl | > 75 columns: wider GROUP BY, more complex plans beyond the Spotter impact. | Model: `len(columns[])` | Count | MEDIUM if > 75 |
| P9 | High-cardinality attribute indexing | GUIDs, transaction IDs indexed as ATTRIBUTEs — wastes storage, pollutes Spotter suggestions with meaningless values. ID columns stored as numbers should be ATTRIBUTEs (not MEASUREs) — the issue is the indexing. | Model: `columns[].properties.index_type` + name regex (`_id$`, `_guid$`, `_uuid$`, `transaction_id`, `row_id`, `surrogate_key`) | Count | MEDIUM |
| P10 | RLS bypass as exception | `is_bypass_rls: true` disables Row-Level Security. Legitimate use cases exist (aggregate-only models) but should be the exception. | Model: `model.properties.is_bypass_rls` | Boolean | MEDIUM (flag as exception) |
| P11 | Secure suggestions overhead | Many indexed columns on a Spotter-enabled model. Each indexed column adds a DB lookup for suggestions. Informational — indexing is correct for searchable columns. | Model: `columns[].properties.index_type` + `model.spotter_config.is_spotter_enabled` | Count of indexed columns | INFO (> 30 indexed on Spotter model) |

### Scalar formula thresholds

| Threshold | Level | Severity |
|---|---|---|
| <= 5 per model | GREEN | — |
| 6–10 | YELLOW | LOW |
| > 10 | RED | MEDIUM |

---

## S — Security

| # | Check | What it detects | TML source | Scoring | Default severity |
|---|---|---|---|---|---|
| S1 | PII column detection | Columns matching PII name patterns. Heuristic — false positives expected. | Model: `columns[].name` (see PII regex table) | Count | Flag for review (severity depends on S2–S4) |
| S2 | PII indexing without RLS | PII columns that are indexed expose values in Spotter autocomplete. **The index can ONLY be secured if the backing table has RLS rules.** No table RLS = indexed PII visible to all users. | Model: `columns[].properties.index_type` + Table: `table.rls_rules` (presence) | PII indexed + no table RLS = HIGH; PII indexed + table has RLS = INFO | HIGH (unsecured) |
| S3 | Column Level Security gaps | PII columns without CLS rules or data masking formulas. CLS is not in standard TML export — requires Beta flag `export_column_security_rules` (open item OI-10). Heuristic fallback: flag PII where no masking formula exists. | Model: `formulas[].expr` checked for masking patterns (`if(is_group_member(...))`, hash/redact referencing PII names) | Count of unprotected PII | HIGH |
| S4 | RLS bypass + PII | `is_bypass_rls: true` AND model contains PII columns. All users see all rows including PII. | Model: `model.properties.is_bypass_rls` + S1 | Boolean (bypass + PII) | HIGH |
| S5 | Credentials in analytics | Columns matching credential patterns (`password`, `secret_key`, `api_key`, `token`). Should never be in an analytics model. | Model: `columns[].name` (credential regex) | Count | CRITICAL |
| S6 | Conformed dimension divergence | Same `db_column_name` across models maps to different `column_type`. Inconsistent classification can cause different access behaviour for the same data. | Model: group `columns[].db_column_name` across all models, check `column_type` | Count of divergent columns | MEDIUM |

### PII regex patterns (case-insensitive)

| Category | Patterns | Confidence |
|---|---|---|
| Email | `email`, `e[-_]?mail`, `email[-_]?addr` | HIGH |
| Phone | `phone`, `mobile`, `cell[-_]?phone`, `fax`, `tel(?:ephone)?` | HIGH |
| National ID | `ssn`, `social[-_]?sec`, `national[-_]?id`, `tax[-_]?id`, `nin`, `sin` | HIGH |
| Date of birth | `dob`, `birth[-_]?date`, `date[-_]?of[-_]?birth`, `birthday` | HIGH |
| Financial | `credit[-_]?card`, `card[-_]?num`, `account[-_]?num`, `iban`, `routing[-_]?num` | HIGH |
| Credentials | `password`, `passwd`, `secret[-_]?key`, `api[-_]?key`, `token` | CRITICAL |
| Person name | `first[-_]?name`, `last[-_]?name`, `surname`, `full[-_]?name`, `given[-_]?name` | MEDIUM |
| Address | `street[-_]?addr`, `postal[-_]?code`, `zip[-_]?code` | MEDIUM |

---

## Cross-check overlap

Some data surfaces in two angles with different framing:

| Check data | Appears in | Framing |
|---|---|---|
| Progressive joins | D4 (modeling anti-pattern) | P4 (performance impact) |
| VARCHAR join keys | D2 (modeling quality) | P6 (query speed) |
| Join depth | D1 metric (complexity) | P7 (query plan degradation) |
| RLS bypass | P10 (exception review) | S4 (PII + bypass = risk) |

---

## Report structure

Output is a single self-contained HTML file (`audit_report.html`) with all CSS/JS
inline — no external dependencies, opens in any browser, shareable via email/Slack.
Companion `audit_findings.json` provides machine-readable data for downstream processing.

### View 1 — Cluster heatmap (landing page)

Colour-coded grid: rows = models (sorted by priority), columns = angles. Each cell
shows worst severity for that model × angle. Click a cell to drill to View 2, click
an angle header for View 3. Severity filter bar and model search at top.

### View 2 — Model scorecard (per-model drill-down)

All checks grouped by angle with expandable sections. CRITICAL/HIGH expanded by
default, MEDIUM/LOW/INFO collapsed. Each finding includes check ID, score, severity,
detail, and recommendation.

### View 3 — By-check detail (cross-model)

One section per check, all findings across all models. Sortable columns, model
filter, links to model scorecards.

### Sidebar navigation

Always-visible: cluster heatmap link, severity summary counts, angle sections,
model list.

### Machine-readable output

`audit_findings.json` — array of all findings for downstream processing.

---

## Open items

| # | Item | Status |
|---|---|---|
| OI-1 | `ts metadata search --all` performance on 1000+ models | OPEN |
| OI-2 | API throttling on 4-way parallel TML export | OPEN |
| OI-3 | `ts metadata dependents` — counts without full export? | OPEN |
| OI-4 | `is_bypass_rls` in exported TML? | OPEN |
| OI-5 | `data_model_instructions` in TML — confirmed at `model.model_instructions.data_model_instructions` | VERIFIED |
| OI-6 | `constant_folding` — does NOT exist as a TML property. Column-picker formulas (IF parameter patterns) have no known TML flag. | OPEN — unverifiable |
| OI-7 | `is_spotter_enabled` — confirmed at `model.spotter_config.is_spotter_enabled` | VERIFIED |
| OI-8 | `apply_on_tables` on model filters — confirmed as progressive filter mechanism | VERIFIED |
| OI-9 | `join_progressive` on model properties — confirmed | VERIFIED |
| OI-10 | Column Level Security — not in standard TML export. Beta flag `export_column_security_rules` unverified. | OPEN |
| OI-11 | NL Instructions API — confirmed Beta since 10.15.0.cl. Not live-tested. | OPEN |
