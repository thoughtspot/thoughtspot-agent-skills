# Baseline — Column Definitions and Importance Rating Rationale

This file records the decisions made when the comparison CSV was first produced,
so future runs stay consistent with the same taxonomy and rating criteria.

---

## Column structure (13 columns)

```
Category, Property, Description, Agentic / Semantic Layer Importance,
Human Importance, Agentic Importance,
Snowflake SV Equivalent, Snowflake Notes / Pros & Cons,
Databricks UC Equivalent, Databricks Notes / Pros & Cons,
dbt MetricFlow Equivalent, Cube.dev Equivalent,
Other Platform Notes
```

`Other Platform Notes` is a single column that captures LookML, AtScale SML, Power BI,
and Governance platform notes in one field, using semicolons or short platform-prefixed
clauses. This avoids unbounded column growth as new platforms are added.

---

## Importance rating criteria

### Human Importance — what raises or lowers the rating

| Signal | Effect |
|---|---|
| Visible in the UI data panel or report header | +High |
| Controls query correctness or join behaviour | +High |
| Affects only display formatting | Medium |
| Invisible to end users; affects only admin workflows | Low |
| Optional metadata that improves but doesn't gate usability | Medium |

### Agentic Importance — what raises or lowers the rating

| Signal | Effect |
|---|---|
| Directs how an AI agent interprets a column or metric | +High |
| Provides synonyms or alternate phrasings for NL matching | +High |
| Defines aggregation semantics (sum, avg, count distinct) | +High |
| Provides verified query examples or answer templates | +High |
| Controls RLS or data access scope | +High |
| Affects only visual layout or grouping | Low |
| Administrative metadata (certification, announcements) | Low |
| Available via programmatic column iteration | Medium or Low (agent can discover it) |

### Key contrast cases

| Property | Human | Agentic | Reason |
|---|---|---|---|
| `column_groups[]` / folder groupings | High | Low | Humans navigate folders; agents iterate all columns |
| `ai_context` / field-level NL directives | Low | High | Invisible to humans; critical for agent interpretation |
| `synonyms[]` | Medium | High | Aids search but humans use column names; agents need alternate phrasings |
| Verified Query / Golden Query | Low | High | Hidden infrastructure; dramatically improves agent answer quality |
| `certificate_status` / Governance | High | Low | Trust signal for humans; agents typically don't check endorsement status |
| `aggregation:` | Medium | High | Humans see aggregated values; agents must know the aggregation rule to generate correct SQL |
| MCP transport | None | High | Entirely agent-facing; humans never interact with this layer |

---

## Category taxonomy — rationale for ordering

1. **Model-Level** — top-level model identity and configuration
2. **Column-Level** — the most populated category; drives most query and AI behaviour
3. **Join** — structural; must be correct for queries to work at all
4. **Formula** — calculated columns; important for derived metrics
5. **Parameter** — dynamic filter inputs; important for interactive and parameterized queries
6. **Table** — table references and source configuration
7. **{Platform}-Only** — properties that expose capability gaps vs. ThoughtSpot
8. **Governance-Only** — catalog-layer metadata that overlays all platforms
9. **Power BI-Only** — SSAS-heritage features not common elsewhere
10. **Supplementary AI Artifact** — last, because these live outside the model definition itself

---

## Output location

Default: `~/Dev/semantic-layer-research/semantic-layer-properties.csv`

Rationale: kept outside the `thoughtspot-skills` repo because it is a research output,
not a skill reference file. The skill produces it; the skill does not consume it.

---

## First run summary (April 2026)

- **135 data rows** across 15 categories
- Platforms covered: ThoughtSpot (model properties as baseline), Snowflake SV, Databricks UC,
  dbt MetricFlow, Cube.dev, LookML, AtScale SML, Governance platforms, Power BI / Fabric,
  Supplementary AI Artifacts (Snowflake legacy semantic_model.yaml, Verified Query Repository,
  dbt semantic_manifest.json, Power BI LSDL, ThoughtSpot Data Model Instructions, Looker
  Golden Queries + Agent System Instructions, Cube meta.ai.searchable, MCP protocol)
- Research method: local MD files for ThoughtSpot / Snowflake / Databricks; web research
  for all other platforms
- AtScale SML vocabulary corrected in round 3 — actual object types are catalog, package,
  connection, dataset, dimension, row_security, metric, metric_calc, model, composite_model.
  No dedicated KPI or named_set objects in SML v1.6.
