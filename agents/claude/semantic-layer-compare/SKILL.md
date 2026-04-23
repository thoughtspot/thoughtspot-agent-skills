---
name: semantic-layer-compare
description: Research and generate a cross-platform semantic layer property comparison CSV, covering ThoughtSpot, Snowflake SV, Databricks UC, dbt MetricFlow, Cube.dev, LookML, AtScale SML, Power BI, and supplementary AI artifacts. Output goes to ~/Dev/semantic-layer-research/.
---

# Semantic Layer Property Comparison

Research and produce a CSV that maps every semantic layer property across platforms,
rating each by its importance for human BI interaction and agentic AI interaction.

---

## References

| File | Purpose |
|---|---|
| [~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) | ThoughtSpot Model TML — full field reference, all property types |
| [~/.claude/shared/schemas/snowflake-schema.md](~/.claude/shared/schemas/snowflake-schema.md) | Snowflake Semantic View YAML schema |
| [~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md](~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md) | ThoughtSpot ↔ Snowflake property coverage matrix |
| [~/.claude/skills/semantic-layer-compare/references/baseline.md](references/baseline.md) | Column definitions, category taxonomy, and rationale for importance ratings |

For platforms not covered by local reference files (dbt MetricFlow, Cube.dev, LookML,
AtScale SML, Power BI), use web research to read current official documentation before
writing any rows. Do not rely on training knowledge alone for versioned YAML schemas.

---

## Output

Default output directory: `~/Dev/semantic-layer-research/`
Default filename: `semantic-layer-properties.csv`

If the output directory does not exist, create it before writing.
If the file already exists and the user has not asked for a full regeneration, ask
whether to overwrite or extend with new rows only.

---

## CSV column structure

```
Category, Property, Description, Agentic / Semantic Layer Importance,
Human Importance, Agentic Importance,
Snowflake SV Equivalent, Snowflake Notes / Pros & Cons,
Databricks UC Equivalent, Databricks Notes / Pros & Cons,
dbt MetricFlow Equivalent, Cube.dev Equivalent,
Other Platform Notes
```

**Column definitions:**

| Column | Format |
|---|---|
| Category | One of the canonical categories listed below |
| Property | Short name matching the platform's own terminology |
| Description | 1–2 sentences; what the property does |
| Agentic / Semantic Layer Importance | Free-form; why it matters for semantic layers generally |
| Human Importance | `High/Medium/Low — brief rationale` |
| Agentic Importance | `High/Medium/Low — brief rationale` |
| Snowflake SV Equivalent | Property name, or `None`, or `Partial` |
| Snowflake Notes / Pros & Cons | Limitations, gaps, or advantages vs. ThoughtSpot |
| Databricks UC Equivalent | Property name, or `None`, or `Partial` |
| Databricks Notes / Pros & Cons | Limitations, gaps, or advantages vs. ThoughtSpot |
| dbt MetricFlow Equivalent | Property name, or `None`, or `Partial` |
| Cube.dev Equivalent | Property name, or `None`, or `Partial` |
| Other Platform Notes | LookML, AtScale SML, Power BI, Governance — one clause per platform |

**Importance rating guidance:**

- **High** — directly affects query correctness, metric definition, or AI comprehension
- **Medium** — improves usability or discoverability; absence degrades but doesn't break
- **Low** — cosmetic, administrative, or edge-case; rarely determinative

Human Importance and Agentic Importance are rated independently. A property can be
High for one and Low for the other (e.g., `column_groups[]` is High for humans navigating
a data panel, Low for agents that iterate all columns programmatically).

---

## Canonical categories

Use exactly these category names. Do not invent new ones without a clear gap:

| Category | Covers |
|---|---|
| Model-Level | Top-level model properties (name, description, spotter_config, ai_context, etc.) |
| Column-Level | Column definition properties (name, type, aggregation, synonyms, ai_context, etc.) |
| Join | Join definition and cardinality properties |
| Formula | Calculated columns and formula metadata |
| Parameter | User-parameterized filter and formula inputs |
| Table | Table-level references and configuration |
| Snowflake-Only | Properties that exist in Snowflake SV with no direct TS equivalent |
| Databricks-Only | Properties that exist in Databricks UC with no direct TS equivalent |
| dbt MetricFlow-Only | Properties specific to dbt MetricFlow |
| Cube.dev-Only | Properties specific to Cube.dev |
| LookML-Only | Properties specific to Looker / LookML |
| AtScale SML-Only | Properties specific to AtScale SML |
| Governance-Only | Catalog-layer metadata (glossary, certification, PII, popularity) |
| Power BI-Only | Properties specific to Power BI / Fabric semantic models |
| Supplementary AI Artifact | Constructs that sit alongside the semantic model (verified queries, AI context files, MCP, etc.) |

---

## Steps

### 1. Determine scope

Ask the user whether to:
- **Regenerate** — produce the full CSV from scratch across all platforms (default)
- **Extend** — add rows for a new platform or category to an existing CSV
- **Refresh** — re-research a specific platform's rows and update them in place

If extending or refreshing, read the existing CSV first to avoid duplicating rows.

### 2. Read local reference files

Read these files before writing any ThoughtSpot, Snowflake, or Databricks rows.
Do not write rows from memory — pull property names and descriptions from the source:

- `~/.claude/shared/schemas/thoughtspot-model-tml.md` — all TML model properties
- `~/.claude/shared/schemas/snowflake-schema.md` — all Snowflake SV properties
- `~/.claude/shared/schemas/databricks-schema.md` — all Databricks UC properties
- `~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md` — Snowflake coverage matrix
- `~/.claude/mappings/ts-databricks/ts-databricks-properties.md` — Databricks coverage matrix

### 3. Research external platforms

For each platform not covered by local files, fetch current official documentation:

| Platform | What to research |
|---|---|
| dbt MetricFlow | semantic_models, metrics (all types), saved_queries, semantic_manifest.json, MCP server |
| Cube.dev | cubes, views, dimensions, measures, segments, pre_aggregations, access_policy, meta.ai |
| LookML | explores, views, dimensions/measures/filters, dimension_groups, parameter fields, derived_table, datagroups, aggregate_table, refinements, LookML tests, Conversational Analytics Golden Queries, Agent System Instructions |
| AtScale SML | All object types: catalog, package, connection, dataset, dimension (hierarchies, level_attributes, role_play, calculation_groups), row_security, metric (semi_additive, calculation_method), metric_calc, model (perspectives, drillthroughs, aggregates), composite_model |
| Power BI / Fabric | Calculation groups, perspectives, translations, dataCategory, Q&A linguistic schema, LSDL (AI Data Schema, AI Instructions, Verified Answers) |
| Supplementary artifacts | Snowflake legacy semantic_model.yaml, Verified Query Repository, ThoughtSpot Data Model Instructions, Looker Golden Queries, Cube meta.ai.searchable, MCP protocol (Model Context Protocol) |

Research each platform in parallel where possible to reduce elapsed time.

### 4. Write the CSV

- Write the header row first
- Group rows by Category (ThoughtSpot-native categories first, then platform-specific, then Supplementary AI Artifact last)
- Within each Category, order rows by conceptual importance (core identity fields before optional/advanced)
- Enclose every field value in double quotes
- Escape any literal double quotes inside a value as `""`
- Do not add trailing commas or blank rows between categories

### 5. Verify and report

After writing:
- Report the total row count (header + data)
- List the categories and row counts
- Note any properties you could not find authoritative documentation for
- Note any platforms where documentation was outdated or ambiguous

---

## Extending to new platforms

When the user asks to add a platform not already in the CSV:

1. Research that platform's full property specification via web search
2. Add a new `{Platform}-Only` category for properties with no TS equivalent
3. Add the platform as a new column in `Other Platform Notes` for existing rows where relevant
   — do this by reading the existing CSV and updating affected rows, not by appending duplicates
4. If adding a column requires restructuring the CSV header, regenerate the full file

New columns beyond the current 13 require user confirmation before adding, as they affect
all existing rows.

---

## Key distinctions to preserve

**Human vs. Agentic importance is not the same thing.** Rate them independently.
Properties that are invisible to humans (like `ai_context` or verified query repositories)
are often the highest-value agentic properties. Properties that are highly visible to
humans (like folder groupings or display labels) may be low-value for agents that iterate
programmatically.

**Supplementary AI Artifacts are a distinct category from model properties.** These are
constructs that live alongside the semantic model — verified queries, AI instruction files,
sample questions, Golden Queries, MCP configurations. They are not part of the core model
YAML but are critical for agentic interaction. Keep them in their own category; do not
merge them into platform-specific rows.

**Platform-only rows capture capability gaps, not just differences.** A Snowflake-Only
row means ThoughtSpot cannot represent this concept at all (e.g., `AI_VERIFIED_QUERIES`
at the view level). A row with `Partial` in an equivalent column means the concept exists
but with meaningful limitations. Be precise.
