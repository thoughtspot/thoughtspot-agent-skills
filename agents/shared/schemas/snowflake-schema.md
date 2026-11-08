<!-- currency: snowflake — 2026-11 (2026-11-08 BL-450: Complete Schema re-verified against the YAML spec, CREATE SEMANTIC VIEW, SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML and READ_YAML pages and by live create + READ_YAML + GET_DDL round trips on Snowflake 10.40.103 — use_as_onboarding_question; right_range object + undocumented table constraints:; no dimension-level unique; tags as a list; root-level LOD facts/dimensions (Preview); custom_instructions legacy; unknown keys are parked in the CA extension, never rejected; bridge traversal and role-playing re-run live (findings 13.10, 13.11); materializations YAML procedure (13.9); standalone filters (13.12); Snowflake delta 2026-07..2026-11 also swept by docs/audit/2026-11-08-external.md, its open items routed to BL-543 (LOD) and BL-458 (Cortex Agents); prior 2026-07: derived metrics + named filters + custom_instructions; correction 2026-07: base_table.definition: SQL-query logical-table alternative added to Complete Schema, GA 2026-06-26 — finding 13.4; is_enum dimension property added, GA 2026-06-25 — finding 13.7; BL-064: sample_values blockquote removed from NOT-supported section, verified_queries/unique_keys/relationship type+right_range added to Complete Schema; 2026-07-29 full sweep: top-level max_staleness: key + materializations DDL/YAML coverage row added, public preview release 10.24 Jul 2026 — finding 13.4; facts[] description corrected — pre-aggregated expressions over related tables and window expressions are allowed, not just raw unaggregated columns — finding 13.6; 2026-08-26: derived-metric section corrected — using_relationships and non_additive_dimensions are table-level keys only, plus the two expr restrictions (no aggregations of metrics, no window functions) — finding 13.6); 2026-08-26 finding 13.10: using_relationships marked Preview (available to all accounts) -- shipped Preview 2026-03-13, no GA announcement found through Aug 2026; 2026-08-26 finding 13.7: non_additive_dimensions documented (4 sub-fields + listed-order significance) -- it was absent while the semi-additive path depended on it -->

# Snowflake Semantic View YAML Schema

Full schema reference for `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`. Use during
Step 11 (Validate) to verify the generated YAML is structurally correct.

---

## Complete Schema

> **Verified 2026-11-08 (BL-450)** against the published pages, all read 2026-11-08:
> [YAML specification](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec),
> [CREATE SEMANTIC VIEW](https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view),
> [SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML](https://docs.snowflake.com/en/sql-reference/stored-procedures/system_create_semantic_view_from_yaml),
> [SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW](https://docs.snowflake.com/en/sql-reference/functions/system_read_yaml_from_semantic_view)
> and [Defining level of detail (LOD) metrics](https://docs.snowflake.com/en/user-guide/views-semantic/sql#label-semantic-views-lod).
> **Also verified live** on Snowflake 10.40.103 (`thoughtspot_partner.ap-southeast-2`): each key
> below was created for real, then read back with `SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW` and
> `GET_DDL`. "Live" in a comment below means that round trip.
>
> **The procedure does not reject unknown keys, so a wrong key name fails silently.**
> `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` accepts any key it does not recognise, in verify-only
> mode and on a real create alike. It stores the key verbatim in the Cortex Analyst extension
> (`with extension (CA='{...}')` in `GET_DDL`), and `READ_YAML` hands it back. A misspelt key
> such as `measures:`, `unique:` or `onboarding_question:` never errors. It is simply not
> applied. An unknown key on a verified query is dropped outright rather than kept. A key is
> **native** only when it compiles to a DDL clause. So a verify-only pass does not prove a key
> name is right. Read `GET_DDL` back.

```yaml
name: string                      # Required. Valid Snowflake identifier. No spaces.
                                  # Pattern: ^[A-Za-z_][A-Za-z0-9_]*$
description: string               # Optional. Human-facing description. DDL: COMMENT = '...'.
module_custom_instructions:       # Optional. Cortex Analyst instructions: one free-text string
                                  # per module. NOT an ON/OFF toggle.
  sql_generation: string          # Optional. DDL: AI_SQL_GENERATION '<text>' (no `=`; BL-254).
  question_categorization: string # Optional. DDL: AI_QUESTION_CATEGORIZATION '<text>'.
# custom_instructions: string     # LEGACY. Do not emit. The spec labels it "legacy; prefer
                                  # module_custom_instructions" and says to migrate it to
                                  # sql_generation. It is an alias for sql_generation, not a
                                  # default for every module: it compiles to
                                  # `ai_sql_generation`, and READ_YAML returns it as
                                  # module_custom_instructions.sql_generation. It cannot be
                                  # combined with module_custom_instructions at all. Even with
                                  # question_categorization alone, the procedure fails with
                                  # 392410 "Custom Instructions set through multiple fields"
                                  # (live). CREATE SEMANTIC VIEW has no CUSTOM_INSTRUCTIONS
                                  # clause.
tags:                             # Optional. GA 2026-05-05. A LIST of tag references, not a
                                  # map. The map form `{db.schema.tag: value}` fails with
                                  # 392400 "Expected an array for tags" (live). The same shape
                                  # is valid at root, table, dimension, time_dimension, fact,
                                  # table-level metric and derived metric. All of those
                                  # round-tripped live, time_dimensions included. The tag
                                  # object must already exist. DDL: WITH TAG (db.schema.tag =
                                  # 'value').
- name:
    database: string
    schema: string
    tag: string
  value: string                   # Always a string, at most 256 characters.

max_staleness: integer            # Optional. PREVIEW: materializations are "Preview Feature
                                  # — Open". Seconds, minimum 120. Required before any
                                  # materialization can be added, and cannot be unset while one
                                  # exists. DDL: MAX_STALENESS = <integer>. It reads back as
                                  # `max_staleness: 7200 seconds` (READ_YAML) and
                                  # `MAX_STALENESS = '7,200 seconds'` (GET_DDL) (live).
                                  # Materializations themselves are not keys in this document.
                                  # See the "Materializations" row in "Advanced constructs".

tables:                           # Required. At least one entry.
- name: string                    # Alias used in expr fields and relationships.
                                  # Must be unique within this semantic view.
  description: string             # Optional. DDL: COMMENT = '...'.
  synonyms:                       # Optional. Informational only. DDL: WITH SYNONYMS (...).
  - string
  base_table:                     # Physical triad OR `definition:` below — mutually exclusive.
    database: string              # Snowflake database name. Uppercase recommended.
    schema: string                # Snowflake schema name. Uppercase recommended.
    table: string                 # Physical table or view name.
    # --- OR (SQL-query logical table — GA 2026-06-26) ---
    definition: string            # SQL query defining the logical table in place of the
                                  # database/schema/table triad. DDL equivalent:
                                  # `ALIAS as (SELECT ...)` inside `tables (...)`.
                                  # Mutually exclusive with database/schema/table. See
                                  # ts-snowflake-properties.md "Field Reference" and
                                  # "Partial Migrations — SQL Views" (D option) — the
                                  # to-snowflake-sv converter does not yet emit this
                                  # (tracked in BL-031).

  primary_key:                    # The spec allows 0 or 1. This repo REQUIRES one on every
    columns:                      # table used as a right_table (Key Structural Rule #3).
    - string                      # List of physical column names.

  unique_keys:                    # Optional. 0 to N uniqueness constraints beyond the PK. This
  - columns:                      # is the only place to declare uniqueness. There is no
    - string                      # dimension-level `unique:` key (see dimensions).
                                  # DDL: UNIQUE (col, ...).

  constraints:                    # Optional. NOT in the published YAML spec. Found live: a
                                  # `type: range` relationship needs this on its right_table.
                                  # Without it the create fails with 010300 "the entity does
                                  # not have a matching DISTINCT RANGE constraint". With it,
                                  # the same view compiles. READ_YAML emits this exact shape
                                  # for a view created in DDL with CONSTRAINT <name> DISTINCT
                                  # RANGE BETWEEN <start> AND <end> EXCLUSIVE (Preview).
  - name: string
    distinct_range:
      start_column: string
      end_column: string

  tags:                           # Optional. Same list form as the root `tags:`.
  - name: {database: string, schema: string, tag: string}
    value: string

  dimensions:                     # Optional. Nested under the owning table.
  - name: string                  # Unique across ALL dimensions, time_dimensions,
                                  # metrics in the entire semantic view.
    synonyms:                     # Optional. Alternate names for natural language queries.
    - string
    description: string           # Optional. Human-facing or AI-facing description.
    expr: string                  # SQL expression. e.g. table_alias.COLUMN_NAME
                                  # Quote reserved words: table_alias."date"
    data_type: string             # Any Snowflake data type. The spec's own examples use
                                  # VARCHAR, VARCHAR(25) and NUMBER(4,0), and READ_YAML returns
                                  # the resolved type. The converter emits TEXT | NUMBER | DATE
                                  # | TIMESTAMP | BOOLEAN, and check_sv_yaml.py enforces that
                                  # subset on this repo's examples. That is a repo rule, not a
                                  # spec limit.
    is_enum: boolean              # Optional. GA 2026-06-25. True means sample_values is the
                                  # full list of values, and the model only chooses from them
                                  # when filtering (spec). DDL: bare `is_enum`.
    sample_values:                # Optional. Example values. They improve Cortex Analyst
    - string                      # accuracy. Native: compiles to DDL `sample_values ('a',
                                  # 'b')` and round-trips (live). The spec lists it under
                                  # "Optional properties for physical dimensions" but leaves it
                                  # out of its general-syntax block.
    labels:                       # Optional. [filter] marks an ENTITY-LEVEL filter. expr must
    - filter                      # resolve to BOOLEAN. DDL: LABELS = (FILTER).
    cortex_search_service:        # Optional. Links dimension to a Cortex Search service.
      service: string             #   Required. Name of the Cortex Search Service.
      literal_column: string      #   Optional. Column in the search service containing literal values.
      database: string            #   Optional. Defaults to the base table's database.
      schema: string              #   Optional. Defaults to the base table's schema.
    tags:                         # Optional. Same list form as the root `tags:`.
    - name: {database: string, schema: string, tag: string}
      value: string
    # NOT dimension keys, so do not emit them:
    #   unique: <bool>    Not in the spec; a legacy semantic-model key. Live, it is not
    #                     rejected. It is kept in the CA extension AND turned into a
    #                     table-level `unique (<DIMENSION_NAME>)` constraint that names the
    #                     dimension, not a column. Declare uniqueness in `unique_keys`.
    #   access_modifier   The spec documents access modifiers for facts and metrics only,
    #                     and CREATE SEMANTIC VIEW says "You cannot mark a dimension as
    #                     private". Live, the opposite happens: YAML `private_access` and DDL
    #                     `PRIVATE` both produce a PRIVATE dimension that queries cannot
    #                     reference (000904 invalid identifier). READ_YAML also prints
    #                     `access_modifier: public_access` on every dimension. That is
    #                     undocumented behaviour, so do not emit a private dimension.

  time_dimensions:                # Optional. Nested under the owning table.
  - name: string                  # Unique across all dimensions, time_dimensions, metrics.
    synonyms:
    - string
    description: string
    expr: string                  # e.g. table_alias.DATE_COLUMN
    data_type: string             # DATE | TIMESTAMP (any date/timestamp type)
    sample_values:                # Optional. Native: DDL `sample_values (...)` (live).
    - string
    tags:                         # Optional. Same list form as the root `tags:`. Native:
    - name: {database: string, schema: string, tag: string}   # WITH TAG (live)
      value: string
    # NOT time_dimension keys. Live, each is stored only in the CA extension, with no DDL
    # clause: is_enum, labels, and unique (unique also adds a table-level
    # `unique (<NAME>)` constraint). access_modifier behaves as it does on dimensions.

  facts:                          # Optional. Per-table row-level named expressions.
                                  # Correction 2026-07 (finding 13.6): most facts are raw
                                  # unaggregated columns, but the current spec is not
                                  # limited to that — expr may also be a pre-aggregated
                                  # expression over a related table (evaluated at THIS
                                  # table's own grain) or a window expression. See
                                  # ts-snowflake-properties.md "facts[]" section.
                                  # lod_dimension_type / lod_dimensions are NOT allowed here:
                                  # 392421 "... on the table-level FACT ... is not allowed"
                                  # (live). LOD entries go in the root-level `facts:` below.
  - name: string                  # Unique across all dims/time_dims/metrics/facts.
    synonyms:
    - string
    description: string
    expr: string                  # e.g. table_alias.COLUMN_NAME
    data_type: string             # NUMBER | TEXT | etc.
    access_modifier: string       # Optional. "private_access" | "public_access" (default).
                                  # DDL: PRIVATE / PUBLIC.
    labels:                       # Optional. [filter], an entity-level filter.
    - string
    tags:                         # Optional. Same list form as the root `tags:`.
    - name: {database: string, schema: string, tag: string}
      value: string

  metrics:                        # Optional. Nested under the owning table.
                                  # NOTE: The keyword is "metrics", NOT "measures". A
                                  # `measures:` block is not rejected. It is stored in the CA
                                  # extension, and the metrics in it do not exist (live).
  - name: string                  # Unique across all dimensions, time_dimensions, metrics.
    synonyms:
    - string
    description: string
    expr: string                  # e.g. SUM(table_alias.COLUMN_NAME)
                                  # WARNING: Do NOT include data_type on metrics.
                                  # SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML stores it in the
                                  # Cortex Analyst (CA) extension JSON (confirmed live
                                  # 2026-11-08), which Cortex then rejects at query time with
                                  # error 392700 "unknown field data_type". Omit data_type
                                  # from metrics entirely.
                                  # default_aggregation is not a metric key either. It lands
                                  # in the CA extension and is not applied (live).
    access_modifier: string       # Optional. "private_access" | "public_access" (default).
    using_relationships:          # Optional. PREVIEW. Relationship path for cross-table metrics.
    - string
    non_additive_dimensions:      # Optional. Semi-additive metric — the dimension(s) the
                                  # metric must NOT be summed across (e.g. a balance
                                  # snapshot over time). Added to THIS BLOCK 2026-08-26
                                  # (finding 13.7). Scope note: the key was already named
                                  # at the derived-metrics blockquote below (added the
                                  # same day by finding 13.6) — the audit's "absent from
                                  # this file entirely" was stale by the time it was
                                  # actioned. What was genuinely missing is the Complete
                                  # Schema entry with its sub-fields, which is what this
                                  # file is read as for Step-11 validation: without it a
                                  # validation pass flags every correctly-emitted
                                  # semi-additive metric as carrying an unknown key.
    - table: string               # Required. Logical table holding the dimension.
      dimension: string           # Required. The non-additive dimension.
      sort_direction: string      # Optional. "ascending" (default; closing/most-recent
                                  # snapshot) | "descending" (opening/earliest). Maps to the
                                  # DDL's NON ADDITIVE BY (dim asc|desc).
      null_order: string          # Optional. "first" | "last" -> the DDL's
                                  # `nulls first|last`. NOT merely for completeness: the
                                  # formula mapping makes it an INSTRUCTION --
                                  # ts-snowflake-formula-translation.md:1020, "Include
                                  # `null_order: last` to match ThoughtSpot last_value
                                  # behaviour" -- and it appears in 9 places across 4
                                  # files. (The audit said it "appears nowhere in the
                                  # repo"; that was wrong, and an earlier draft of this
                                  # comment repeated it.)
                                  #
                                  # LISTED-DIMENSION ORDER IS SIGNIFICANT (key-level note,
                                  # not specific to null_order): entries are applied in
                                  # sequence, so reordering them changes the metric.
    tags:                         # Optional. Same list form as the root `tags:`.
    - name: {database: string, schema: string, tag: string}
      value: string

  filters:                        # Optional. STANDALONE named boolean filters. These are
                                  # NOT the entity-level filters, which are `labels:
                                  # [filter]` on a dimension or fact. The spec says that
                                  # standalone filters "are supported for Cortex Analyst SQL
                                  # generation, but the Snowflake semantic SQL compiler uses
                                  # entity-level filters" and "we recommend using
                                  # entity-level filters instead". There is no DDL clause:
                                  # live, the whole block is stored only in the CA extension.
                                  # They are AI-optional. Cortex Analyst decides whether to
                                  # apply one, whereas a ThoughtSpot model-level filter is
                                  # always applied. See ts-snowflake-properties.md
                                  # "Model-Level Filters" for the migration mapping.
  - name: string                  # Unique across all dimensions/time_dimensions/metrics/filters.
    synonyms:
    - string
    description: string
    expr: string                  # Boolean SQL expression, e.g. table_alias.STATUS = 'ACTIVE'

relationships:                    # Optional. Defined at the top level (not under tables).
- name: string                    # Unique relationship name.
  left_table: string              # Must match a name in tables[].
  right_table: string             # Must match a name in tables[]. Must have primary_key
                                  # (repo rule; see Key Structural Rule #3).
  relationship_columns:           # At least one entry.
  - left_column: string           # Physical column name on left_table.
    right_column: string          # Physical column name on right_table. OMIT it on a
                                  # `type: range` column. Live, the procedure fails with
                                  # 392413 "Cannot specify both right_column and right_range",
                                  # even though the spec's own Range example shows both.
    type: string                  # Optional. "asof" | "range". Default: equality join.
    right_range:                  # Required when type is "range". An OBJECT. A plain string
      start_column: string        # fails with 392400 "Expect message object" (live). The
      end_column: string          # right_table also needs a matching `constraints:` entry.

verified_queries:                 # Optional. Verified Q&A pairs for Cortex Analyst accuracy.
- name: string                    # Query identifier.
  question: string                # Natural-language question.
  sql: string                     # Expected SQL using SV logical names.
  verified_at: integer            # Optional. Unix epoch seconds.
  verified_by: string             # Optional. Who verified the query.
  use_as_onboarding_question: boolean  # Optional. Show as an onboarding suggestion. The YAML
                                  # key is NOT `onboarding_question`, which is the DDL keyword
                                  # (ONBOARDING_QUESTION). Live, `onboarding_question: true` is
                                  # not rejected. It is silently dropped, and the query is
                                  # stored as ONBOARDING_QUESTION false. sv_parse.py's internal
                                  # `onboarding_question` key reads the DDL keyword, so it is
                                  # correct.

variables:                        # Optional. GA June 2026. Top-level session/bind variables.
- name: string                    # Variable identifier.
  data_type: string               # Any Snowflake data type, e.g. NUMBER, NUMBER(5,1),
                                  # STRING, FLOAT (spec examples).
  default_value: string           # Optional. Default value when not overridden per-query.
  description: string             # Optional. Human-facing description.

# metrics:                        # Optional. Root-level DERIVED metrics only. Keys: name,
                                  # synonyms, description, access_modifier, expr, tags. See
                                  # "Derived Metrics (root-level `metrics:`)" below.

facts:                            # Optional. PREVIEW ("Preview Feature — Open"). Root-level
                                  # facts exist ONLY for level-of-detail (LOD) entries. Every
                                  # entry must carry lod_dimension_type. A root fact without it
                                  # fails with 392422 "a recognized lod_dimension_type must be
                                  # specified for the semantic-model-level FACT" (live).
                                  # Cortex Analyst and Cortex Agents do not use LOD metrics yet.
                                  # They work in SQL queries against the view only. Semantics,
                                  # and support in either converter: BL-543 (not implemented).
- name: string                    # Unqualified (no table prefix). In GET_DDL it appears in the
                                  # facts block as `NAME as AGG(...) fixed dimensions (...)`.
  synonyms:                       # Optional. Native (live).
  - string
  description: string             # Optional. Native (live).
  expr: string                    # Aggregate expression, e.g. COUNT(orders.order_id).
  data_type: string
  lod_dimension_type: string      # Required. fixed | include | exclude.
  lod_dimensions:                 # The grain. `[]` is valid for every type: with fixed it is
  - table: string                 # the scalar form; with include/exclude the grain does not
    dimension: string             # change. `table` may be omitted when the dimension name is
                                  # unambiguous.

dimensions:                       # Optional. PREVIEW. Root-level dimensions follow the same
                                  # rules as root-level facts: LOD entries only, with the same
- name: string                    # keys, and they are allowed only at root (live).
  expr: string
  data_type: string
  lod_dimension_type: string      # Required. fixed | include | exclude.
  lod_dimensions:
  - table: string
    dimension: string
```

### Advanced constructs — DDL vs YAML coverage

> **Currency note — re-verified 2026-11-08 (BL-450)** against the published
> [semantic-view YAML spec](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec)
> and the CREATE / ALTER SEMANTIC VIEW pages, and live on Snowflake 10.40.103 (first verified 2026-07-01).
> The published YAML spec has **expanded**: several constructs once exclusive to the DDL
> form are now expressible in YAML. The `YAML?` column below reflects the **spec's
> capability**, not the converter's current behaviour — the to-snowflake-sv converter does
> **not yet emit** the newly-YAML-capable constructs (**BL-031**). When BL-031 runs its live
> round-trip, it must read `GET_DDL` back. A verify-only pass proves nothing about key names
> (see "Complete Schema"). The from-snowflake-sv direction parses DDL via `GET_DDL`.
> `SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW` returns the same view as structured YAML. See
> ts-from-snowflake-rules.md "READ_YAML vs GET_DDL" (finding 13.8).

| Construct | DDL syntax | YAML? | Notes |
|---|---|---|---|
| `facts` | `facts ( TABLE.COL as alias.NAME, ... )` | ✅ now — per-table `facts:` | Spec adds a per-table `facts:` key (name/synonyms/description/access_modifier/expr/data_type/labels/tags). Converter still down-converts facts→metrics until BL-031. |
| `private` / `public` | visibility modifier on facts/metrics (`PRIVATE` / `PUBLIC`) | ✅ now — `access_modifier` | `access_modifier: private_access` / `public_access`. The spec documents it for **facts and metrics only**. A private *dimension* is undocumented, and the CREATE page says it is impossible, but it works live (2026-11-08). See the Complete Schema dimensions block. Do not emit one. |
| `unique` | `UNIQUE (col, ...)` on a logical table | ✅ now — table-level `unique_keys:` | **A table constraint, not a dimension property** (corrected 2026-11-08, BL-450). There is no dimension-level `unique:` key. A legacy `unique: true` on a dimension is not rejected. Live, it turns into a `unique (<DIMENSION_NAME>)` table constraint plus a CA-extension entry. |
| `range between` | `REFERENCES t(BETWEEN start AND end EXCLUSIVE)` + `CONSTRAINT <n> DISTINCT RANGE BETWEEN start AND end EXCLUSIVE` on the right table (Preview) | ✅ now — `relationship_columns[].type: range` + `right_range: {start_column, end_column}` + table `constraints:` | `right_range` is an **object**, not a string, and the range column carries **no** `right_column`. Both were checked live 2026-11-08. A range join also needs the table-level `constraints: [{name, distinct_range: {start_column, end_column}}]`, which the YAML spec does not document. It was found live through READ_YAML. `type: asof` needs neither. |
| filter labels | `labels = (filter)` | ✅ now — `labels: [filter]` | Marks a dimension/fact as a filter |
| `with cortex search service` | on dimensions | ✅ now — `cortex_search_service:` (object) | Links a dimension to a Cortex Search service. Object with `service` (required), `literal_column`, `database`, `schema` sub-fields. |
| legacy `custom_instructions` | *(no DDL clause of its own; it compiles to `AI_SQL_GENERATION`)* | ⚠ legacy — top-level `custom_instructions` | **Do not emit.** The spec marks it legacy and says to migrate it to `module_custom_instructions.sql_generation`, which it is an alias for. It is mutually exclusive with `module_custom_instructions`: setting both fails with 392410 (live 2026-11-08). `CREATE SEMANTIC VIEW` has no `CUSTOM_INSTRUCTIONS` clause (corrected 2026-11-08, BL-450). `ai_sql_generation` / `ai_question_categorization` are not YAML key names either. See the two rows below. |
| `AI_SQL_GENERATION` | `AI_SQL_GENERATION '<free-text instructions>'` (**no `=`** — the `=` form is rejected; BL-254) | ✅ now — `module_custom_instructions.sql_generation` | Free-text instruction string (Jan 12 2026 "custom instructions" release), scoped to SQL generation only |
| `AI_QUESTION_CATEGORIZATION` | `AI_QUESTION_CATEGORIZATION '<free-text instructions>'` (**no `=`** — the `=` form is rejected; BL-254) | ✅ now — `module_custom_instructions.question_categorization` | Free-text instruction string, scoped to question categorization only |
| `ai_verified_queries` | `ai_verified_queries ( 'query' verified_by = '...' )` | ✅ now — `verified_queries[]` | Top-level array; verified queries (→ NLS Feedback TML on the TS side) |
| `using <relationship>` | on metrics | ✅ **Preview (available to all accounts)** — `using_relationships` | Relationship path for cross-table metrics. Shipped Preview 2026-03-13. The YAML spec and the CREATE page still badge it "Preview Feature — Open, available to all accounts" (re-checked 2026-11-08; status qualifier added 2026-08-26, finding 13.10). Material because BL-031 reads this table to decide what the converter may emit, and the neighbouring Materializations row is qualified while this one was not. |
| root-level derived `METRICS` | `METRICS ( alias.NAME as EXPR, ... )` with `table_alias` omitted from the metric name | ✅ now — root-level `metrics:` | Combines per-table metrics across logical tables. **`using_relationships` is NOT valid here** — it is a table-level metric key only (corrected 2026-08-26, audit 13.6). The one exception to Key Structural Rule #1 — see "Derived Metrics" below. Not yet emitted by the to-snowflake-sv converter (BL-031). |
| **LOD metrics** — `FIXED` / `INCLUDE` / `EXCLUDE DIMENSIONS (...)` | `AGG(expr) FIXED DIMENSIONS (t.d, ...)` as a row-level fact/dimension expression, or wrapped inline in a metric `expr` | ✅ **Preview** — root-level `facts:` / `dimensions:` entries with `lod_dimension_type` + `lod_dimensions`, or inline in a metric `expr` | "Preview Feature — Open". Root level only: the LOD keys under `tables[].facts` / `tables[].dimensions` fail with 392421, and a root-level fact without `lod_dimension_type` fails with 392422 (both live 2026-11-08). Cortex Analyst and Cortex Agents do not use LOD metrics yet. Semantics and converter support: **BL-543** (not implemented). |
| named standalone `filters` | *(none — live 2026-11-08: the block is stored only in the CA extension JSON; there is no DDL clause)* | ✅ now — per-table `filters:` | Standalone boolean filter (name/synonyms/description/expr). The spec says it is "supported for Cortex Analyst SQL generation, but the Snowflake semantic SQL compiler uses entity-level filters (defined with labels)" and recommends `labels: [filter]` instead. AI-optional, not always-applied like a ThoughtSpot model-level filter. See ts-snowflake-properties.md "Model-Level Filters". |
| `tags` (object tagging) | `WITH TAG (fully.qualified.tag = 'value', ...)` | ✅ now — `tags:` at root/table/dimension/time_dimension/fact/metric levels | GA 2026-05-05. A **list** of `{name: {database, schema, tag}, value}` objects. The map form fails with 392400. Round-trip verified live at every level on 2026-11-08 (BL-450). |
| **Materializations** — pre-computed dimensions + metrics, refreshed to keep within `MAX_STALENESS` | `CREATE ... MAX_STALENESS = <integer>` (or `ALTER ... SET MAX_STALENESS`) first, then `ALTER SEMANTIC VIEW <sv> ADD MATERIALIZATION <m> WAREHOUSE = <wh> [REFRESH_MODE = AUTO \| FULL \| INCREMENTAL] [IMMUTABLE WHERE (<cond>)] AS DIMENSIONS ... METRICS ... [WHERE (<filter>)]` | ⚠ partial — `max_staleness:` in the SV YAML, plus a **separate** YAML document applied by `SYSTEM$MANAGE_SEMANTIC_VIEW_MATERIALIZATIONS_FROM_YAML` | **"Preview Feature — Open"** ([materializations](https://docs.snowflake.com/en/user-guide/views-semantic/materializations) and [the procedure](https://docs.snowflake.com/en/sql-reference/stored-procedures/system_manage_semantic_view_materializations_from_yaml), read 2026-11-08). Corrected 2026-11-08 (finding 13.9): this row used to call materialization config "DDL-only — no YAML equivalent documented". The procedure takes `materializations: [{name, warehouse, dimensions: [{table, name}], metrics: [{table, name}]}]`. It syncs declaratively: it creates missing entries, replaces changed ones, drops any not listed (`[]` drops all), and is idempotent. That YAML is its own document, not keys inside the SV spec, and it has **no key for `REFRESH_MODE`, `IMMUTABLE WHERE` or the materialization `WHERE`**, so those three stay DDL-only. Live 2026-11-08: `max_staleness: 7200` reads back as `MAX_STALENESS = '7,200 seconds'` in `GET_DDL` (between `comment=` and `ai_sql_generation`) and as `max_staleness: 7200 seconds` in READ_YAML. Whether an added materialization appears in `GET_DDL` was not tested (see ts-from-snowflake-rules.md, BL-100). Materializations benefit Semantic SQL only. Cortex Analyst and Cortex Agents run physical SQL and do not use them. `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`'s 4th argument (`create_or_alter`) keeps the existing materializations through a re-create. |

### Keys that are not semantic view keys — omit them

These keys are **not** part of the semantic view YAML schema. **They do not cause a parse
error.** Corrected 2026-11-08 (BL-450): this section used to say they did. Live, the
procedure accepts each one, then either stores it in the Cortex Analyst extension
(`with extension (CA='...')`, which READ_YAML hands back) or drops it. None takes effect
as written (dimension-level `unique` has a side effect, below), and nothing reports that.
Omit them anyway. `check_sv_yaml.py` flags the
first three when they sit on a table or relationship entry.

| Key | Why it looks valid | What actually happens (live 2026-11-08) |
|---|---|---|
| `relationship_type` | Legacy semantic models used it. Even the `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` page's own example sets `relationship_type: many_to_one` | Kept in the CA extension and not used. The spec says relationship type "is automatically inferred from the data and primary key definitions" |
| `join_type` | Legacy semantic models | Kept in the CA extension and not used |
| `default_aggregation` (metric) | Legacy semantic models | Kept in the CA extension and not applied |
| `measures` (instead of `metrics`) | Common BI vocabulary | Kept in the CA extension. The view has no such metrics |
| `unique` on a dimension / time_dimension | Legacy semantic models | Kept in the CA extension, and also turned into a table-level `unique (<DIMENSION_NAME>)` constraint. Use table-level `unique_keys:` |
| `onboarding_question` on a verified query | It is the DDL keyword (`ONBOARDING_QUESTION`) | Dropped outright. The query is stored with `ONBOARDING_QUESTION false`. The YAML key is `use_as_onboarding_question` |
| `data_type` on a metric | Dimensions and facts carry one | Kept in the CA extension. Cortex Analyst then rejects the view at query time with 392700 |
| `sample_values` on a **table** | It *is* valid on dimensions and time_dimensions | Kept in the CA extension only |

---

## Key Structural Rules

1. **Table-scoped fields:** `dimensions`, `time_dimensions`, `facts` and per-table
   `metrics` are nested **under each `tables[]` entry**, not at the top level of the
   semantic view. There are two exceptions. **Root-level `metrics:`** holds **derived
   metrics** that combine metrics across multiple logical tables (DDL equivalent: a
   `METRICS` entry with the `table_alias` omitted from the metric name). See "Derived
   Metrics" below. **Root-level `facts:` / `dimensions:`** hold **LOD entries only**
   (Preview; every entry needs `lod_dimension_type`; BL-543). A metric scoped to a single
   table's own columns still belongs in that table's `metrics:` list, not at the root.

2. **`metrics` not `measures`:** The correct keyword is `metrics`. Using `measures`
   does **not** cause a parse error, which makes it worse. The procedure stores the
   block in the Cortex Analyst extension, and the view is created without those
   metrics (live 2026-11-08). Corrected from "causes a parse error" (BL-450).

3. **`primary_key` is required** on every table that appears as `right_table` in a
   `relationships[]` entry. This is a **repo rule**, enforced by `check_sv_yaml.py`.
   CREATE SEMANTIC VIEW documents that the referenced columns must be a `PRIMARY KEY`
   or `UNIQUE` constraint. Live on 2026-11-08, `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`
   did *not* enforce this at create time: a relationship to a right table with neither
   was accepted. The procedure infers relationship type from the keys, so always
   declare one. (Corrected from "Missing `primary_key` causes validation failure",
   BL-450.)

4. **Reserved words in column names** must be double-quoted in `expr`:
   ```yaml
   expr: DM_DATE_DIM."date"
   ```
   In YAML, the `expr` value string should be: `DM_DATE_DIM."date"`

5. **`relationships[]` is top-level**, not nested under tables.

6. **`name` uniqueness** applies globally: no two entries across all
   `dimensions`, `time_dimensions`, `metrics` (table-scoped or root-level derived),
   and `filters` in the entire semantic view may share a `name`.

---

## Derived Metrics (root-level `metrics:`)

A semantic view may declare a **root-level** `metrics:` block — the one legitimate
exception to Key Structural Rule #1. Root-level metrics combine per-table metrics
across logical tables; the DDL equivalent is a `METRICS` entry with the
`table_alias` omitted from the metric name.

### Allowed keys — and the two that are not

A root-level (derived) metric accepts **only**: `name`, `synonyms`, `description`,
`access_modifier`, `expr`, `tags`.

> **`using_relationships` and `non_additive_dimensions` are table-level metric keys
> only — they are NOT valid on a root-level metric.** This reference previously
> documented the opposite and its example emitted
> `using_relationships: [fact_sales_to_fact_cost]` on a derived metric (corrected
> 2026-08-26, audit finding 13.6).
>
> The reason is structural, not arbitrary: the Snowflake SQL guide states that
> *"each relationship that you specify must start from the logical table containing
> the metric"*. A derived metric is by definition not tied to a table, so there is
> no start-from table for a relationship path to begin at. The relationships a
> derived metric traverses are resolved from the metrics it references, not declared
> on it.

### Two `expr` restrictions

A derived-metric `expr` may **not**:

- use **aggregations of metrics** — `SUM(fact_sales.revenue)` where `revenue` is
  itself a metric is rejected; reference the metric directly
- use **window functions**

Neither restriction was recorded here before.

```yaml
metrics:                              # Root level — cross-table derived metrics only.
- name: gross_margin_pct
  synonyms:
  - "Gross Margin %"
  description: "Gross margin as a percentage of revenue, spanning two fact tables."
  expr: (fact_sales.revenue - fact_cost.total_cost) / NULLIF(fact_sales.revenue, 0)
  # No using_relationships: — see above. The relationship path is inferred from the
  # referenced metrics' own tables.
```

Use root-level `metrics:` only when the expression genuinely spans more than one
table's metrics. A metric scoped to a single table's own columns still belongs in
that table's `metrics:` list — the normal case under Rule #1. This is
newly-possible for the to-snowflake-sv direction (e.g. cross-fact ratio formulas
could emit as a clean derived metric); the converter does not yet emit these
(**BL-031**).

**BL-031 reads this section as its spec**, which is why the correction matters more
than a docs typo: emitting `using_relationships` on a derived metric would produce
invalid YAML on every one the converter generates.

---

## Reserved Keywords and Case-Sensitive Identifiers

### SQL reserved words in `expr`

Column names that are SQL reserved words must be double-quoted in `expr`:
```yaml
expr: table_alias."date"
```

Common reserved words: `date`, `time`, `schema`, `table`, `value`, `name`, `type`, `key`, `id`, `order`, `group`

### Case-sensitive (lowercase) identifiers

When a Snowflake schema, table, or column was created with double-quoted lowercase
identifiers (e.g. `CREATE SCHEMA "superhero"`), it is case-sensitive and must be
referenced with double quotes. In `SHOW SCHEMAS` / `SHOW TABLES` / `SHOW COLUMNS`,
case-sensitive objects appear in lowercase; case-insensitive objects appear in UPPERCASE.

**Rule:** If `SHOW` output returns a name in lowercase → it requires quoting.

**YAML encoding for Snowflake-quoted identifiers:**

In the Semantic View YAML, Snowflake-quoted identifiers must be wrapped in single
quotes containing the double-quoted value — but **only in `base_table` fields and
`expr` SQL expressions**. See the critical exception for `primary_key` and
`relationship_columns` below.

```yaml
# Schema (case-sensitive lowercase)
base_table:
  schema: '"superhero"'    # ← single-quoted YAML string containing "superhero"
  table: '"colour"'        # ← same pattern for table names

# expr fields — embed quotes directly in the SQL expression string
expr: eye_colour."colour"  # ← table alias unquoted, column double-quoted inline
```

**Detection:** Before generating YAML, run `SHOW SCHEMAS`, `SHOW TABLES`, and
`SHOW COLUMNS` to identify which identifiers are lowercase/case-sensitive, then
apply quoting accordingly.

| Location | Case-insensitive (UPPERCASE) | Case-sensitive (lowercase) |
|---|---|---|
| `base_table.schema` | `schema: PUBLIC` | `schema: '"superhero"'` |
| `base_table.table` | `table: FACT_SALES` | `table: '"colour"'` |
| `expr` column ref | `expr: t.COLUMN_NAME` | `expr: t."column_name"` |
| `primary_key.columns` | `- COLUMN_NAME` | `- column_name` (bare — wrapper views normalize to uppercase) |
| `relationship_columns` | `left_column: COL` | `left_column: col` (bare — wrapper views normalize to uppercase) |

**`primary_key.columns` and `relationship_columns`** always use bare unquoted identifiers.
Lowercase case-sensitive join key columns trigger wrapper view creation in Step 5, which
normalizes all column names to uppercase before the YAML is generated. See
*Known Snowflake Semantic View Limitations — Lowercase case-sensitive base table columns*
at the bottom of this file.

---

## Validation Checklist

Run all checks before calling `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`:

| Rule | Check |
|---|---|
| Unique field names | No two entries across all `dimensions`, `time_dimensions`, `metrics` (table-scoped or root-level derived), and `filters` share a `name` |
| Valid identifiers | `name` (view + all fields) matches `^[A-Za-z_][A-Za-z0-9_]*$` |
| Table-scoped fields | `dimensions`, `time_dimensions`, and per-table `metrics` are nested under `tables[]` entries; root-level `metrics:` is valid ONLY for cross-table derived metrics (see "Derived Metrics") |
| Keyword: `metrics` | No `measures` key anywhere in the YAML |
| Table refs in `expr` | Every `table_alias.column` prefix matches a `name` in `tables[]` |
| Table refs in relationships | Every `left_table` and `right_table` matches a `name` in `tables[]` |
| `primary_key` present | Every `right_table` in a relationship has `primary_key.columns` defined |
| `primary_key` format | `primary_key:` with nested `columns:` list — NOT a bare list under `primary_key:` |
| Case-sensitive identifiers | Lowercase schemas/tables detected via SHOW and wrapped in `'"value"'` in `base_table`; lowercase columns double-quoted inline in `expr` |
| Reserved words quoted | Column names that are SQL reserved words are double-quoted in `expr` |
| Join key identifiers | `primary_key.columns` and `relationship_columns` use bare identifiers — wrapper views (Step 5) ensure all are uppercase before this point |
| Unsupported fields absent | No `relationship_type`, `join_type`, `default_aggregation`, `measures`, dimension-level `unique`, or verified-query `onboarding_question`. None of them errors at create time; see "Keys that are not semantic view keys" |
| Valid `data_type` | Dimensions/time_dimensions only: one of `TEXT`, `NUMBER`, `DATE`, `TIMESTAMP`, `BOOLEAN`. This is the converter's own subset, which `check_sv_yaml.py` enforces. Snowflake itself accepts any data type, e.g. `VARCHAR(25)`. **Never on metrics** — causes Cortex error 392700. |
| No untranslatable formulas | Columns with untranslatable ThoughtSpot formulas are **omitted** entirely |

---

## Example Structure

> Note: `base_table` below uses the physical `database`/`schema`/`table` triad. It may
> instead use `definition: <SQL query>` for a SQL-query logical table (GA 2026-06-26) —
> see `base_table` in "Complete Schema" above. Not shown in this example.

```yaml
name: retail_sales
description: "Migrated from ThoughtSpot: Retail Sales"

tables:
- name: fact_sales
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: FACT_SALES
  metrics:
  - name: revenue
    synonyms:
    - "Revenue"
    - "Sales"
    description: "[TS AI Context] Total transaction value for financial analysis."
    expr: SUM(fact_sales.SALES_AMOUNT)
  time_dimensions:
  - name: sale_date
    synonyms:
    - "Sale Date"
    description: ""
    expr: fact_sales.SALE_DATE
    data_type: DATE

- name: dim_product
  base_table:
    database: ANALYTICS
    schema: PUBLIC
    table: DIM_PRODUCT
  primary_key:
    columns:
    - PRODUCT_ID
  dimensions:
  - name: product
    synonyms:
    - "Product"
    - "Item"
    description: ""
    expr: dim_product.PRODUCT_NAME
    data_type: TEXT
  metrics:
  - name: product_count
    synonyms:
    - "Product Count"
    - "# of Products"
    description: ""
    expr: COUNT(dim_product.PRODUCT_ID)

relationships:
- name: sales_to_product
  left_table: fact_sales
  right_table: dim_product
  relationship_columns:
  - left_column: PRODUCT_ID
    right_column: PRODUCT_ID
```

---

## Execution

```sql
USE ROLE {role};
USE DATABASE {target_database};
USE SCHEMA {target_schema};

-- Dry-run validation (recommended first):
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_database}.{target_schema}', $$
{full yaml content here}
$$, TRUE);

-- Create (remove TRUE flag):
CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('{target_database}.{target_schema}', $$
{full yaml content here}
$$);
```

**Notes:**
- `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` is a **stored procedure** — use `CALL`, not `SELECT`.
- First argument is the fully-qualified target schema: `'DATABASE.SCHEMA'`
- Third argument `TRUE` (`verify_only`) enables dry-run validation without creating the view.
  **It does not catch a wrong key name.** Unknown keys pass and are parked in the CA extension
  (see "Complete Schema"), so read `GET_DDL` back after a real create.
- Optional fourth argument `create_or_alter` (default `FALSE`): `TRUE` uses
  `CREATE OR ALTER SEMANTIC VIEW` semantics, which keep the existing materializations
  where the change allows.
- The `$$` dollar-quoting allows the YAML to contain single quotes safely
- `SYSTEM$READ_YAML_FROM_SEMANTIC_VIEW('<db>.<schema>.<view>')` (a function — use `SELECT`)
  returns an existing view as YAML. It is the inverse of this procedure.

**An existing view of the same name is replaced, not an error.** Per the
[procedure page](https://docs.snowflake.com/en/sql-reference/stored-procedures/system_create_semantic_view_from_yaml)
(read 2026-11-08), the procedure "attempts to replace that semantic view and copy the
grants from that semantic view", which "has the same effect as running CREATE OR REPLACE
SEMANTIC VIEW … COPY GRANTS". The replace needs the OWNERSHIP privilege on the existing
view. Corrected 2026-11-08 (BL-450): this section used to say to expect an "already
exists" error. The YAML path keeps grants. Hand-written `CREATE OR REPLACE` DDL does not,
unless it adds `COPY GRANTS`.

To drop an existing view explicitly:
```sql
DROP SEMANTIC VIEW IF EXISTS {database}.{schema}.{name};
```

Do NOT use `INFORMATION_SCHEMA.SEMANTIC_VIEWS` — the column names vary by Snowflake
version. Use `SHOW SEMANTIC VIEWS` if you need to check for one.

---

## Known Snowflake Semantic View Limitations

### Lowercase case-sensitive base table columns (Cortex Analyst blocker)

Cortex Analyst validates the semantic model YAML against a strict identifier pattern:
`^[A-Za-z_][A-Za-z0-9_$]*$`. Any column name containing `"` characters is rejected
with error 392700:

```
invalid column name "id": name must start with an underscore or a letter,
and only contain letters, underscores, decimal digits (0-9), and dollar signs ($).
```

This surfaces when the underlying Snowflake tables were created with lowercase quoted
identifiers (e.g. `"id"`, `"race_id"`). `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML`
requires `'"id"'` quoting to resolve these columns; Cortex Analyst then rejects that
same encoding at query time. There is no YAML format that satisfies both tools.

**Diagnosis:** Run `SHOW COLUMNS IN TABLE {db}.{schema}.{table}`. If any column name
is returned in lowercase, those columns are case-sensitive and will trigger this issue.

**Fix — create uppercase wrapper views (preferred):**

Before generating the YAML in Step 10, create a new uppercase schema and views:

```sql
CREATE SCHEMA IF NOT EXISTS {db}.{UPPERCASE_SCHEMA_NAME};

CREATE OR REPLACE VIEW {db}.{UPPERCASE_SCHEMA_NAME}.{TABLE_NAME} AS
SELECT "id" AS ID, "column_name" AS COLUMN_NAME, ...
FROM {db}."{lowercase_schema}"."{table}";
```

Point the semantic view's `base_table` entries at the new schema and views. All
identifiers become bare uppercase — no quoting needed anywhere in the YAML, and
both `SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML` and Cortex Analyst accept the result.

**Alternative fix — rename source columns:**

```sql
ALTER TABLE {db}."{schema}"."{table}" RENAME COLUMN "id" TO ID;
```

This is cleaner long-term but modifies the source schema and may break other
queries or integrations that reference the lowercase column names. Use only if you
control the source tables and have verified no downstream dependencies.

---

### Bridge / junction tables and many-to-many traversal

> **Corrected 2026-11-08 (BL-450; audit 2026-09-22 finding 13.10).** This section used to
> say Semantic Views "cannot traverse a two-hop path through a bridge table", and it sent
> many-to-many conversions to raw SQL. **That is no longer true.** The
> [YAML spec](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec)
> now has a "Many-to-many relationships via bridge tables" section, and the
> [SQL guide](https://docs.snowflake.com/en/user-guide/views-semantic/sql) has a matching
> one. Both were read 2026-11-08. Declare one relationship from the bridge to each entity,
> and give the bridge a **composite** `primary_key`. The system "infers the many-to-many path
> from the relationship graph and automatically handles deduplication to prevent fanout
> double-counting".

**Re-run on the original fixture, live 2026-11-08 (Snowflake 10.40.103).** The superhero
fixture (`BIRD.SUPERHERO_SV`, `superhero ← hero_power → superpower`) was rebuilt as two
semantic views. One had the spec's composite key on the bridge
(`primary_key: {columns: [HP_HERO_ID, HP_POWER_ID]}`; its 5,825 rows are all distinct on
that pair). The other had **no** bridge key, as the original did. Every query shape this
section said would fail works in **both** views, through Semantic SQL
(`SEMANTIC_VIEW(...)`):

| Query | Result in both views |
|---|---|
| `superhero_name` + `power_name` (dimensions from both ends) | Rows returned |
| `superhero_name` + a superpower count metric | Rows returned |
| `power_name` + a distinct-hero count metric | Agility 239, Flight 208. Matches a hand-written join |
| `power_name` + `SUM(HEIGHT_CM)` on superhero | Agility 51,072, Flight 30,511. Matches a hand-written join, so no fan-out |
| `superhero_name` + `power_name` + a bridge `COUNT(*)` | 1 per pair |

The bare-bridge control also works, so the composite key is not what changed. The platform
changed after the original write-up. Declare the composite key anyway, as the spec's
example does.

**Converter guidance:** a many-to-many path through a bridge is expressible. Do not route it
to raw SQL. Emit both bridge relationships and the bridge's composite `primary_key`.

**Not covered by this re-run:**
- Cortex Analyst and Cortex Agents generate their own physical SQL, and they were not
  tested. BL-458 tracks the constraints attributed to Cortex Analyst.
- The original failure's error was not reproduced on 10.40.103:
  `Invalid fact specified: The fact entity 'SUPERPOWER' must be related to and have an
  equal or lower level of granularity compared to the base metric or fact entity.`
  If it comes back, the cause is a granularity conflict between the requested fields, not
  bridge traversal as such (see "`SELECT *` on a multi-fact semantic view" below).

### Symmetric join keys (same column name on both FK and PK sides)

Cortex Analyst requires every join key column to be exposed as a **named dimension**,
and resolves join keys **by dimension name** (snake_case of the physical column name).
Dimension names must be globally unique across the entire semantic view.

When FK and PK columns share the same name (e.g. `TRANS.ACCOUNT_ID → ACCOUNT.ACCOUNT_ID`),
you cannot expose both as `account_id` — Snowflake enforces global uniqueness.

**Error:** `Join relationship X using join key 'account_id' which is not defined in
logical table trans.` (error 392700)

**Fix — rename FK columns in wrapper views before generating YAML:**

In the wrapper view for each fact/bridge table, rename every FK column to include the
source table prefix:

```sql
-- Before: "account_id" AS ACCOUNT_ID
-- After:
CREATE OR REPLACE VIEW TRANS AS
SELECT "trans_id" AS TRANS_ID,
       "account_id" AS TRANS_ACCOUNT_ID,   -- renamed FK
       ...
FROM source_schema.trans;
```

Then expose each renamed column as a dimension and update relationships:

```yaml
# TRANS table — dimension for the FK
- name: trans_account_id
  expr: trans.TRANS_ACCOUNT_ID
  data_type: NUMBER
```

```yaml
# Relationship uses the renamed column
relationships:
- name: trans_to_account
  left_table: trans
  right_table: account
  relationship_columns:
  - left_column: TRANS_ACCOUNT_ID   # renamed FK in wrapper view
    right_column: ACCOUNT_ID        # PK stays unchanged
```

**Role-playing tables (one physical table under several logical names).** The base case
needs **no wrapper views** (narrowed 2026-11-08, BL-450; audit 2026-09-22 finding 13.11).
The spec's "Role-playing tables" section gives two logical names over the same
`base_table`, each with the same PK column. That works live on 2026-11-08: TPCH `NATION`
served as both `customer_nation` and `supplier_nation`, and Semantic SQL counts matched a
direct join. It still worked with each role's PK exposed as a dimension under its own name
(`cust_nation_key` and `supp_nation_key`, both `expr: N_NATIONKEY`).

Two separate wrapper views with distinct PK column names (e.g. `DISTRICT` as
`client_district` / `account_district` → `CLIENT_DISTRICT_ID` / `ACCOUNT_DISTRICT_ID`) are
needed **only when the join keys must be exposed as dimensions named after the physical
column**. That is the Cortex Analyst constraint described above: it resolves join keys
by dimension name, and that name must be globally unique. This constraint is attributed to
Cortex Analyst and is unverified under Cortex Agents (BL-458). Create the wrapper views
only in that case. They need DDL rights on the source, which a consultant may not have.

**Note:** This also applies to `primary_key` columns — the PK column must also be
exposed as a dimension with a name matching snake_case(pk_column). For example, if
the PK column is `DISP_ID`, the dimension must be named `disp_id`.

---

### `SELECT *` on a multi-fact semantic view

`SELECT *` across a semantic view that contains multiple fact/bridge tables at
different granularities will always fail with the granularity conflict above.
Always select specific fields from a single granularity path.
