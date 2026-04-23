---
name: semantic-layer-compare
description: Research and generate a cross-platform semantic layer property comparison CSV in long (key-value) format — one row per feature × platform. Covers ThoughtSpot, Snowflake SV, Databricks UC, dbt MetricFlow, Cube.dev, LookML, AtScale SML, Power BI / Fabric, Governance Platforms, and OSI. Importance and platform support scored 1–5. Output goes to ~/Dev/semantic-layer-research/.
---

# Semantic Layer Property Comparison

Research and produce a CSV that maps every semantic layer property across platforms,
rating each by its importance for human BI interaction and agentic AI interaction.
The output uses a long (key-value) format — one row per feature × platform — so new
platforms can be added as additional rows without restructuring the file.

---

## References

| File | Purpose |
|---|---|
| [~/.claude/shared/schemas/thoughtspot-model-tml.md](~/.claude/shared/schemas/thoughtspot-model-tml.md) | ThoughtSpot Model TML — full field reference, all property types |
| [~/.claude/shared/schemas/snowflake-schema.md](~/.claude/shared/schemas/snowflake-schema.md) | Snowflake Semantic View YAML schema |
| [~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md](~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md) | ThoughtSpot ↔ Snowflake property coverage matrix |
| [~/.claude/skills/semantic-layer-compare/references/baseline.md](references/baseline.md) | Column definitions, category/sub-category taxonomy, importance rationale, and schema history |

If `~/Dev/semantic-layer-research/transform.py` exists, it can be used to perform a wide→long
format transformation in bulk when adding a new platform to an existing CSV.

For platforms not covered by local reference files (dbt MetricFlow, Cube.dev, LookML,
AtScale SML, Power BI, OSI), fetch current official documentation before writing any rows.
Do not rely on training knowledge alone for versioned YAML schemas or emerging standards.

---

## Output

Default output directory: `~/Dev/semantic-layer-research/`
Default filename: `semantic-layer-properties.csv`

If the file already exists and the user has not asked for a full regeneration, ask whether
to overwrite, add a new platform, or refresh specific platform rows.

---

## CSV column structure (long format)

```
feature_id, category, sub_category, property, description,
human_importance, human_importance_notes,
agentic_importance, agentic_importance_notes,
platform, platform_equivalent, platform_notes, platform_score
```

**Column definitions:**

| Column | Format / Values |
|---|---|
| `feature_id` | Stable prefix-coded ID: `MDL-001`, `COL-001`, `ARC-001`, etc. Never renumber existing IDs. |
| `category` | Broad grouping — one of the canonical categories listed below |
| `sub_category` | Finer functional type within category — see sub-category list below |
| `property` | Canonical concept name; for platform-specific rows, use the platform's own term |
| `description` | 1–2 sentences; platform-agnostic explanation of what the property does |
| `human_importance` | `1`–`5` (or `0` for N/A) — see Importance ratings below |
| `human_importance_notes` | Brief rationale for the human importance rating |
| `agentic_importance` | `1`–`5` (or `0` for N/A) — see Importance ratings below |
| `agentic_importance_notes` | Brief rationale for the agentic importance rating |
| `platform` | Exactly one of the platform names listed below |
| `platform_equivalent` | Feature name/form in this platform; `None` if absent |
| `platform_notes` | Pros, cons, limitations, gaps, or "No equivalent in {platform}" |
| `platform_score` | `1`–`5` — how well this platform supports this feature (see scale below) |

Every feature must have a row for every platform — even when `platform_equivalent` is `None`.
A row with `None` is informative: it tells readers the feature does not exist on that platform.

---

## Canonical categories

| Category | Covers |
|---|---|
| `Model` | Top-level model configuration, identity, access-control, optimization |
| `Column` | Column/field/dimension/measure definitions and properties |
| `Structural` | Joins, relationships, entity declarations, cardinality |
| `Calculation` | Formulas, derived metrics, expressions, calculation groups |
| `Filtering` | Filters, parameters, RLS, mandatory conditions |
| `Governance` | Catalog-layer metadata: certification, glossary, quality, popularity |
| `Platform Extension` | Properties with no ThoughtSpot equivalent (specific to one platform) |
| `AI / Transport` | AI context directives, verified queries, sample data, MCP, OSI interchange standard |

---

## Canonical sub-categories

| Sub-category | Typical properties |
|---|---|
| `identity` | name, description, guid, model identity |
| `type` | column_type, ATTRIBUTE/MEASURE classification, data_type |
| `aggregation` | aggregation function, semi-additive, non-additive, window |
| `join` | join conditions, cardinality, role-play, relationship declarations |
| `filter` | pre-filters, RLS, mandatory filters, access filters |
| `formula` | formula expressions, derived metrics, calculation methods |
| `parameter` | runtime parameters, allowed values, range constraints |
| `synonym` | synonyms, aliases, linguistic schema, Q&A vocabulary |
| `ai-context` | ai_context directives, AI instructions, model-level NL directives |
| `verified-query` | verified queries, golden queries, sample questions, verified answers |
| `sample-data` | sample_values, value-level semantic search |
| `transport-standard` | MCP protocol, OSI interchange format, semantic manifest |
| `display` | format strings, display names, currency, custom sort, i18n |
| `display-folder` | column groups, folder structure, group labels |
| `visibility` | hidden flags, is_hidden, search indexing, public/private |
| `semantic-type` | geo_config, dataCategory, URL, ImageURL semantic hints |
| `table-reference` | model_tables, base_table, dataset objects, source references |
| `connection` | database connections, profiles |
| `hierarchy` | level attributes, hierarchy definitions, default members |
| `calculation-group` | calculation groups, time intelligence templates |
| `perspective` | audience scoping, perspectives, view facades |
| `drillthrough` | drillthrough paths, drill fields |
| `pre-aggregation` | aggregate tables, pre-aggregations, query routing |
| `materialization` | PDTs, derived tables, materialization schedules |
| `access-control` | bypass_rls, access_policy, row_security |
| `entity` | entity declarations, foreign keys, entity graphs |
| `export` | saved queries, semantic manifest, export configs |
| `extensibility` | meta fields, custom_extensions, extends, composite models |
| `model-config` | sets, refinements, datagroups, LookML tests |
| `certification` | certificate status, endorsement |
| `glossary` | glossary terms, term definitions |
| `data-quality` | PII tags, DQ scores |
| `usage` | popularity signals, query frequency |
| `documentation` | README, announcements, dataset descriptions |
| `time-intelligence` | time granularity, offset windows, YTD/MTD, rolling windows |
| `configuration` | catch-all for properties that do not fit another sub-category |
| `i18n` | multi-language labels, locale-keyed translations, model localization |
| `model-inheritance` | extends, refinements, base models, partial models, overrides |
| `metric-registry` | central metric definitions, cross-model reuse, metrics store |
| `writeback` | data writeback, action support, planning scenarios, annotation insertion |
| `federation` | multi-source joins, cross-cloud, cross-database, virtual federation |
| `cicd` | Git-native development, PR review, linting, environment promotion, CI pipelines |
| `testing` | automated semantic model tests, data tests, metric regression tests |
| `streaming` | real-time / near-real-time data, streaming ingestion, sub-minute freshness |

---

## Platform list

Every feature must have a row for each of these platforms:

| Platform | What it covers |
|---|---|
| `ThoughtSpot` | TML model properties; the source definition for most features |
| `Snowflake SV` | CREATE SEMANTIC VIEW DDL / YAML |
| `Databricks UC` | Unity Catalog Metric View YAML v1.1 |
| `dbt MetricFlow` | semantic_models, metrics, saved_queries |
| `Cube.dev` | cubes, views, dimensions, measures, pre_aggregations |
| `LookML` | explores, views, dimensions, measures, derived_table, refinements |
| `AtScale SML` | dataset, dimension, metric, metric_calc, model, composite_model |
| `Power BI / Fabric` | TMDL semantic model + LSDL AI artifacts |
| `Governance Platforms` | Alation, Atlan, Collibra — catalog-layer governance metadata |
| `OSI` | Open Semantic Interchange v1.0 (Jan 2026) — multi-platform interchange YAML |

---

## Importance ratings

Rate `human_importance` and `agentic_importance` independently on a **1–5 numeric scale**.
Use `0` for N/A (feature is not applicable to this dimension at all).

| Score | Meaning |
|---|---|
| `5` | Critical — directly affects query correctness, metric definition, or trust; absence breaks things |
| `4` | High — strong impact on usability or accuracy; absence meaningfully degrades experience |
| `3` | Medium — useful, improves quality; absence is noticeable but not breaking |
| `2` | Low — cosmetic, administrative, or rarely determinative |
| `1` | Minimal — edge-case relevance; almost never matters in practice |
| `0` | N/A — not applicable to this dimension (e.g., human rating for a purely agent-facing artifact) |

## Platform score

Rate `platform_score` per row to indicate how well a given platform supports the feature:

| Score | Meaning |
|---|---|
| `5` | Native, full support — first-class feature, no limitations |
| `4` | Native with minor gaps — supported natively but with documented limitations |
| `3` | Partial support / workaround — achievable via workaround or partially supported |
| `2` | Limited — complex workaround or significant gaps; fragile |
| `1` | Not supported — no equivalent; cannot be achieved on this platform |

**Shortcut rule for existing rows:** native platform → `5`; has a non-None equivalent → `3`; no equivalent → `1`.
Use explicit values in the 4 and 2 ranges only when you have specific evidence.

**Key contrast principle:** Human and Agentic importance diverge intentionally for some categories.
Properties that are invisible to humans (ai_context, verified queries) are often the highest-value
agentic properties. Properties that are highly visible to humans (folder groupings, display names)
may be low-value for agents that iterate programmatically.

---

## Feature ID conventions

Prefix codes for stable feature IDs:

| Prefix | Category |
|---|---|
| `MDL` | Model-level ThoughtSpot properties |
| `COL` | Column-level ThoughtSpot properties |
| `JON` | Join properties |
| `FRM` | Formula properties |
| `PRM` | Parameter properties |
| `TBL` | Table-reference properties |
| `SFV` | Snowflake SV–native features |
| `DBX` | Databricks UC–native features |
| `DBT` | dbt MetricFlow–native features |
| `CUB` | Cube.dev–native features |
| `LKL` | LookML–native features |
| `ATS` | AtScale SML–native features |
| `GOV` | Governance platform–native features |
| `PBI` | Power BI / Fabric–native features |
| `SAI` | Supplementary AI artifact features |
| `OSI` | OSI-native features |
| `ARC` | Cross-platform architecture capabilities (chasm/fan traps, custom calendar, i18n, model inheritance, metric registry, aggregate awareness, RLS, writeback, federation, CI/CD, testing, streaming) |

Never renumber existing IDs. If a row is removed, leave a gap rather than renumbering.

### ARC feature index

| ID | Feature |
|---|---|
| `ARC-001` | Chasm trap and fan trap prevention — automatic double-counting protection for multi-fact-table joins |
| `ARC-002` | Custom calendar support — fiscal year, 4-4-5, 4-5-4, retail, ISO week, non-Gregorian calendars |
| `ARC-003` | Multi-language / i18n — locale-keyed display labels, descriptions, synonyms in one model |
| `ARC-004` | Model inheritance and extension — extends, refinements, base models, single-point-of-definition |
| `ARC-005` | Central metric / column definitions — metrics store, cross-model reuse, single source of truth |
| `ARC-006` | Aggregate awareness / pre-aggregation routing — automatic routing to summary tables |
| `ARC-007` | Row-level security at semantic layer — RLS enforced by the semantic layer across all tools |
| `ARC-008` | Writeback and action support — data writeback, planning scenarios, workflow triggers |
| `ARC-009` | Multi-source / cross-platform data federation — joins across databases, schemas, cloud providers |
| `ARC-010` | CI/CD and Git-native development — code-first, PR review, linting, environment promotion |
| `ARC-011` | Automated testing framework — data tests, metric regression tests, semantic correctness tests |
| `ARC-012` | Real-time / streaming data support — sub-5-minute freshness, streaming ingestion, event-time |

---

## OSI coverage summary (v1.0, Jan 2026)

Use these coverage notes when writing OSI rows:

**OSI v1.0 supports:**
- `semantic_model` — name, description, top-level container
- `datasets[]` — source, primary_key, unique_key, incremental build config
- `fields[]` — row-level attributes for grouping and filtering
- `dimensions[]` — categorical attributes (Where / When / Who)
- `measures[]` — aggregations with aggregate_function; can span datasets
- `relationships[]` — many-to-one or one-to-one FK joins (equality-only)
- `ai_context` — native first-class field on all objects
- `custom_extensions` — vendor metadata (Snowflake, Salesforce, dbt, Databricks)
- Multi-dialect SQL expressions (ANSI, Snowflake, MDX, Tableau, Databricks)

**OSI v1.0 does NOT support (note as "None — [reason]"):**
filters, RLS, parameters, hierarchies, calculation groups, synonyms, pre-aggregations,
perspectives, verified queries, governance metadata, display formatting, semantic type hints,
time intelligence patterns (YTD/MTD), materialization, saved queries, i18n

**OSI governance:** Snowflake-led; 50+ partners including ThoughtSpot, Databricks, dbt Labs,
Cube, AtScale, Alation, Atlan, Collibra. Phase 2 (mid-2026) planned for domain-specific
extensions and expanded coverage.

---

## Steps

### 1. Determine scope

Ask the user:
- **Regenerate** — produce the full CSV from scratch (all platforms, all features)
- **Add platform** — add rows for a new platform to an existing CSV
- **Refresh platform** — update rows for a specific platform (e.g., after a spec update)
- **Add features** — add rows for newly discovered features to all platforms

For "Add platform" or "Refresh platform": read the existing CSV first.

### 2. Proactively review platform landscape

Before starting work, run a brief web search to check whether any significant semantic
layer platforms should be added or updated. Specifically check for:

- New major releases (version bumps, new properties) from platforms already covered
- Platforms that have gained traction in the semantic layer space since the last run
  (e.g., Sigma Computing, Lightdash, Omni, GoodData, Malloy, Superset semantic layer)
- Platforms that have announced OSI compatibility, MCP servers, or AI semantic layer features
- Platforms the user may have mentioned in prior context

Report any significant findings before generating the CSV so the user can confirm scope.

### 3. Read local reference files

Read these files before writing any ThoughtSpot, Snowflake, or Databricks rows.
Extract property names and descriptions from the source — do not write from memory:

- `~/.claude/shared/schemas/thoughtspot-model-tml.md`
- `~/.claude/shared/schemas/snowflake-schema.md`
- `~/.claude/shared/schemas/databricks-schema.md`
- `~/.claude/mappings/ts-snowflake/ts-snowflake-properties.md`
- `~/.claude/mappings/ts-databricks/ts-databricks-properties.md`

### 4. Research external platforms

For platforms not covered by local files, fetch current documentation:

| Platform | What to research |
|---|---|
| dbt MetricFlow | semantic_models, all metric types, saved_queries, semantic_manifest.json, MCP server |
| Cube.dev | cubes, views, dimensions, measures, segments, pre_aggregations, access_policy, meta.ai |
| LookML | all field types, dimension_group, parameter, derived_table, datagroups, aggregate_table, refinements, LookML tests, Conversational Analytics (Golden Queries, Agent System Instructions) |
| AtScale SML | all object types: dataset, dimension (with hierarchies, level_attributes, role_play, calculation_groups), row_security, metric, metric_calc, model (perspectives, drillthroughs, aggregates), composite_model |
| Power BI / Fabric | TMDL semantic model, LSDL (AI Data Schema, AI Instructions, Verified Answers), calculation groups, perspectives, translations, linguistic schema |
| OSI | github.com/open-semantic-interchange/OSI — spec.yaml, README, active branches |

Research platforms in parallel to reduce elapsed time.

### 5. Write the CSV

- Write the header row first: `feature_id, category, sub_category, property, description, human_importance, human_importance_notes, agentic_importance, agentic_importance_notes, platform, platform_equivalent, platform_notes, platform_score`
- For each feature, write 10 rows (one per platform) before moving to the next feature
- Group features by category in this order: Model → Column → Structural → Calculation → Filtering → Platform Extension → Governance → AI / Transport
- Within Platform Extension, group by originating platform (Snowflake SV features together, etc.)
- Enclose every field in double quotes; escape literal double quotes as `""`
- `platform_notes` must not be empty when `platform_equivalent` is `None` — always explain why

### 6. Verify and report

After writing:
- Report total row count and breakdown by platform (should be equal across all platforms)
- List any features with unusual importance ratings that warrant review
- Note any platforms where documentation was ambiguous or out of date
- Flag any newly discovered platforms that should be added in a future run

---

## Adding a new platform

1. Run a web search to find the platform's current semantic model specification
2. Assign a new prefix code (extend the table above)
3. For each existing feature, add one new row with the new platform name
4. `platform_equivalent` = the platform's feature name, `None`, or `Partial`
5. `platform_notes` = pros/cons/limitations for this platform
6. Also check whether any new platform-specific features should be added
   (features the new platform has that no existing platform covers)
7. If yes, add those features with rows for ALL existing platforms (most will be `None`)

The transform.py script at `~/Dev/semantic-layer-research/transform.py` provides a
reference implementation for bulk platform addition via Python.

---

## Key distinctions to maintain

**Human vs Agentic importance diverge intentionally.** Do not rate them the same unless
they genuinely are. Column_groups is High human / Low agentic. ai_context is Low human /
High agentic. The divergence is the signal.

**Platform Extension features need ThoughtSpot rows.** A feature in the Snowflake-Only
category still needs a ThoughtSpot row with `platform_equivalent: None` and a brief note.
The `None` row makes the gap explicit.

**OSI is an interchange standard, not a BI platform.** Rate it for its portability value
to multi-platform agent deployments, not for feature parity with BI tools. Many `None`
ratings on OSI are intentional — OSI v1.0 covers ~80% of analytics work and leaves 20%
for future versions.
