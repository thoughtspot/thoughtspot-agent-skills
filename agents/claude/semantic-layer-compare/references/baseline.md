# Baseline — Schema, Taxonomy, and Importance Rationale

Records the decisions made during the v2 restructure so future runs stay consistent.

---

## Schema version history

| Version | Date | Change |
|---|---|---|
| v1 | April 2026 | Wide format (1 row per feature, platforms as columns, 13 columns, 135 features) |
| v2 | April 2026 | Long format (1 row per feature × platform, 12 columns, 138 features × 10 platforms = 1,380 rows) |

---

## Column structure (v2 — current)

```
feature_id, category, sub_category, property, description,
human_importance, human_importance_notes,
agentic_importance, agentic_importance_notes,
platform, platform_equivalent, platform_notes
```

### Why long format?

- Adding a new platform requires only new rows, not a new column
- Each platform row is self-contained — no "Other Platform Notes" catch-all field
- Importance ratings are per-concept (duplicated across platform rows for the same feature)
- `platform_equivalent = None` rows are explicit absence records, not blank cells

### v1 → v2 transformation

The transform.py script at `~/Dev/semantic-layer-research/transform.py` performs the
wide→long conversion. It reads the v1 CSV and produces v2 rows by:
- Extracting Snowflake/Databricks/dbt/Cube columns into platform rows
- Parsing the "Other Platform Notes" field for LookML/AtScale/Power BI/Governance notes
- Splitting "High — rationale" importance fields into separate level + notes columns
- Assigning feature IDs from category-based prefix counters
- Deriving sub_category from property name + description keyword matching
- Adding OSI rows via a coverage function based on the OSI v1.0 specification

---

## Category taxonomy

| Category | Notes |
|---|---|
| `Model` | Replaces "Model-Level" and "Table" from v1 |
| `Column` | Replaces "Column-Level" from v1 |
| `Structural` | Replaces "Join" from v1 |
| `Calculation` | Replaces "Formula" from v1 |
| `Filtering` | Replaces "Parameter" from v1 |
| `Governance` | Same as "Governance-Only" in v1 |
| `Platform Extension` | Replaces all "{Platform}-Only" categories from v1 |
| `AI / Transport` | Same as "Supplementary AI Artifact" in v1 |

---

## Feature ID prefix codes

| Prefix | Origin |
|---|---|
| `MDL` | ThoughtSpot model-level |
| `COL` | ThoughtSpot column-level |
| `JON` | ThoughtSpot join |
| `FRM` | ThoughtSpot formula |
| `PRM` | ThoughtSpot parameter |
| `TBL` | ThoughtSpot table |
| `SFV` | Snowflake SV–native |
| `DBX` | Databricks UC–native |
| `DBT` | dbt MetricFlow–native |
| `CUB` | Cube.dev–native |
| `LKL` | LookML–native |
| `ATS` | AtScale SML–native |
| `GOV` | Governance–native |
| `PBI` | Power BI–native |
| `SAI` | Supplementary AI artifact |
| `OSI` | OSI-native |

IDs are never renumbered. Gaps are acceptable.

---

## Importance rating decisions

### Human vs Agentic — key contrast cases

| Property | Human | Agentic | Reason |
|---|---|---|---|
| `column_groups[]` / display folders | High | Low | Humans navigate folders; agents iterate all columns |
| `ai_context` / field-level NL directives | Low | High | Invisible to humans; critical for agent interpretation |
| `synonyms[]` | High | High | Both need alternate phrasings, but for different reasons |
| Verified Query / Golden Query | Low–High | High | Few-shot grounding; dramatically improves agent accuracy |
| `certificate_status` / governance | High | Low | Trust signal for humans; agents rarely check endorsement |
| `aggregation:` | Medium | High | Agents must know aggregation rule to generate correct SQL |
| MCP / OSI | N/A (human) | High | Entirely agent-facing transport/interchange layer |
| Display formatting (format_pattern) | High | Low | Humans need formatted values; agents generate data |
| Semi-additive flag | Low | High | Users see correct values; agents must know not to SUM |

### When to use N/A

- Human importance: `N/A` for purely technical/internal constructs (manifests, MCP, OSI)
- Agentic importance: rarely `N/A`; most properties have some agentic relevance

---

## OSI v1.0 coverage notes

OSI (Open Semantic Interchange) v1.0 finalized January 27, 2026.
Partners include Snowflake (lead), Salesforce, dbt Labs, Databricks, Cube, ThoughtSpot,
AtScale, Alation, Atlan, Collibra, and 40+ others.

**Covers:** semantic_model, datasets[], fields[], dimensions[], measures[], relationships[],
ai_context, custom_extensions, multi-dialect SQL expressions

**Does not cover in v1.0:** filters, RLS, parameters, hierarchies, calculation groups,
synonyms, pre-aggregations, perspectives, verified queries, governance metadata,
display formatting, semantic type hints, i18n, materialization

**Phase 2 roadmap (mid-2026):** domain-specific extensions, 50+ native platform connectors,
expanded coverage of the currently missing features above.

The `OSI` platform rows in the CSV represent OSI as an interchange standard, not a BI tool.
Many `None` equivalents are intentional — OSI v1.0 deliberately covers ~80% of analytics work.

---

## Run summary

| Run | Date | Features | Platforms | Total rows |
|---|---|---|---|---|
| v1 (initial) | April 2026 | 135 | — (wide format) | 135 |
| v2 (restructure) | April 2026 | 138 | 10 | 1,380 |

The 3 additional features in v2 are OSI-native (OSI-001: interchange format, OSI-002: multi-dialect SQL, OSI-003: custom_extensions).

---

## Output location

`~/Dev/semantic-layer-research/semantic-layer-properties.csv`

Kept outside the `thoughtspot-skills` repo because it is a research output, not a skill
reference file. The skill produces it; the skill does not consume it.
