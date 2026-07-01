# Audit Check Catalog

Single source of truth for all audit checks. Each check is implemented as a
`check_XX` function in the corresponding Python module under
`tools/ts-cli/ts_cli/audit/`.

To add a new check, see `tools/ts-cli/CLAUDE.md` — "Adding an audit check."

---

## AI Readiness — `checks_ai.py`

| ID | What it detects | Severity logic |
|---|---|---|
| A1 | Description coverage below threshold | GREEN/YELLOW/RED by profile |
| A2 | Synonym coverage below threshold | GREEN/YELLOW/RED by profile |
| A3 | No AI instructions configured | HIGH (Spotter) / MEDIUM (General) |
| A4 | Missing Spotter config | HIGH (Spotter) / MEDIUM (General) |
| A5 | Spotter readiness composite score | Weighted score → severity |

---

## Data Modeling — `checks_data.py`

| ID | What it detects | Severity logic |
|---|---|---|
| D1 | Model complexity (tables, joins, columns, depth) | Thresholds in reference file |
| D2 | VARCHAR join keys (2–5x slower) | HIGH per occurrence |
| D3 | Join type analysis (FULL OUTER, LEFT/RIGHT) | HIGH for FULL OUTER, INFO for others |
| D4 | Progressive joins disabled on large models | HIGH if >5 tables + join_progressive:false |
| D5 | Orphan tables in model (Cartesian risk) | MEDIUM per orphan table |
| D6 | Grain consistency — fact tables with >40% attributes | MEDIUM per model |
| D7 | Model overlap & duplication | Severity by Jaccard and classification |
| D8 | Duplicate table objects (same physical table, multiple TS objects) | HIGH per duplicate group |
| D9 | SQL pass-through function usage (>20% formulas) | MEDIUM / HIGH by percentage |
| D10 | Zero-column tables (bridge vs leaf) | INFO (bridge) / MEDIUM (leaf) |
| D11 | Fan-out join risk (row multiplication) | HIGH with mitigation reduction |
| D12 | Conformed dimension divergence (same column, different type) | MEDIUM per divergence |

---

## Human Readiness — `checks_human.py`

| ID | What it detects | Severity logic |
|---|---|---|
| H1 | Column name quality (anti-pattern regexes) | LOW per bad name |
| H2 | Description quality (too-short, boilerplate) | LOW per violation |
| H3 | Unnecessary hidden columns (not referenced by formulas) | MEDIUM per column |
| H4 | Orphan models (zero dependents) | MEDIUM per model |
| H5 | Orphan sets (zero consumers) | MEDIUM per set |
| H7 | Direct table connections (bypasses semantic layer) | MEDIUM per answer |
| H8 | Formula promotion candidates (duplicated in 2+ answers) | HIGH — link to /ts-object-answer-promote |
| H9 | Redundant answer formulas (duplicating model formula) | LOW per formula |
| H10 | Stale / temporary objects (name pattern match) | LOW (name only), MEDIUM if also orphan |

---

## Performance — `checks_perf.py`

| ID | What it detects | Severity logic |
|---|---|---|
| P1 | SQL View data source (blocks filter pushdown) | MEDIUM per view |
| P2 | Scalar formula density (run at query time) | MEDIUM >5, HIGH >10 |
| P3 | Model filters lacking apply_on_tables | MEDIUM per non-progressive filter |
| P4 | Apply-all-joins anti-pattern (join_progressive:false) | HIGH if >5 tables |
| P5 | No date constraints on fact tables | MEDIUM per model |
| P6 | VARCHAR join keys (performance framing of D2) | HIGH per key |
| P7 | Join depth exceeding thresholds | MEDIUM >3, HIGH >5 |
| P8 | Column sprawl (>75 columns) | MEDIUM per model |
| P9 | High-cardinality ID column indexed as ATTRIBUTE | MEDIUM per column |
| P11 | Excessive indexed columns on Spotter-enabled model | INFO >30 |
| P13 | High RLS rule count (cost compounds per query) | MEDIUM >3, HIGH >6 |
| P14 | RLS expression uses functions (prevents index pruning) | MEDIUM per expression |
| P15 | VARCHAR RLS column without value_casing | MEDIUM per column |
| P16 | Deeply nested if() in formulas | INFO >3, LOW >5 |
| P17 | Formula cross-reference chain depth | INFO >2, LOW >3 |
| P18 | COUNT_DISTINCT aggregation (most expensive) | INFO per column |

---

## Security — `checks_security.py`

| ID | What it detects | Severity logic |
|---|---|---|
| S1 | PII column detection (heuristic regex) | MEDIUM per column |
| S2 | PII indexed without RLS (exposes in autocomplete) | HIGH per column |
| S3 | PII without CLS or masking formula | MEDIUM per column |
| S4 | RLS bypass + PII columns in model | HIGH per model |
| S5 | Credentials in analytics | CRITICAL per column |
| S8 | Overly permissive sharing (FULL access to all users group) | MEDIUM per object |
| S9 | Sharing to external groups | INFO per object |
| S10 | RLS bypass enabled (disables row-level security) | MEDIUM per model |

---

## Check ID gaps

Some IDs are intentionally absent — either consolidated into other checks or
deferred to Phase 2 (usage analysis):

| ID | Status |
|---|---|
| H6 | Duplicate sets — deferred (requires deep set comparison) |
| P10, P12 | Not assigned |
| S6, S7 | Not assigned |
