# Coverage Matrix: ThoughtSpot Model → Snowflake Semantic View

What the `ts-convert-to-snowflake-sv` skill maps and what it does not.
Use this as the canonical limitations reference.

Primary emission target is `CREATE OR REPLACE SEMANTIC VIEW` **DDL** — the
live-verified path. See
[ts-snowflake-properties.md](../../../shared/mappings/ts-snowflake/ts-snowflake-properties.md)
for the full property-by-property detail this matrix summarizes.

---

## Mapped Constructs

### Structure and Schema

| # | ThoughtSpot Construct | Snowflake Semantic View Equivalent | Notes |
|---|---|---|---|
| 1 | Model / Worksheet `name` | Semantic view name | snake_cased |
| 2 | Model / Worksheet `description` | Top-level `comment='...'` | |
| 3 | `model_tables[]` / `table_paths[]` | `tables (...)` clause | Physical names resolved from Table TML |
| 4 | `sql_view` (simple `SELECT * FROM table`) | `tables (...)` entry | Resolved to the underlying physical table automatically |
| 5 | Right-side join table | `primary key (COL)` in its `tables()` entry | |
| 6 | Table-level `description` (Table TML) | `comment='...'` on the table entry | |

### Joins and Relationships

| # | ThoughtSpot Construct | Snowflake Semantic View Equivalent | Notes |
|---|---|---|---|
| 7 | `joins[]` (inline `on`) | `relationships (...)` clause | |
| 8 | `joins[]` (`referencing_join`) | `relationships (...)` clause | Resolved via Table TML `joins_with[]` |
| 9 | `AND`-separated join conditions | Multiple equi-join pairs in the `on` condition | `OR` conditions have no equivalent — require a wrapping view |
| 10 | Multi-hop / chained join paths (`table_paths`) | Unrolled pairwise relationships | Partial — flag at the checkpoint for user review |

### Dimensions and Time Dimensions

| # | ThoughtSpot Construct | Snowflake Semantic View Equivalent | Notes |
|---|---|---|---|
| 11 | `ATTRIBUTE` column (non-date) | `dimensions (...)` clause | |
| 12 | `ATTRIBUTE` column (date/timestamp) | `dimensions (...)` clause | Classified as `time_dimensions` only in the CA extension JSON — the DDL has no separate clause |
| 13 | Formula column — translatable ATTRIBUTE | `dimensions (...)` clause | Expression inlined as a computed column alias |
| 14 | `column.description` | `comment='...'` on the entry | |
| 15 | `properties.synonyms` (column/formula) | `with synonyms=(...)` | First synonym → `with synonyms=('First',...)`; top-level `synonyms:` is dropped on TS import — always read `properties.synonyms` |

### Metrics

| # | ThoughtSpot Construct | Snowflake Semantic View Equivalent | Notes |
|---|---|---|---|
| 16 | `MEASURE` column (`SUM`/`AVG`/`MIN`/`MAX`) | `metrics (...)` clause | `AGG(table.col)` |
| 17 | `MEASURE` column (`COUNT_DISTINCT`) | `metrics (...)` clause | `COUNT(DISTINCT table.col)` |
| 18 | Formula column — translatable MEASURE | `metrics (...)` clause | Expression translated to SQL — see ts-snowflake-formula-translation.md |
| 19 | `last_value(...)` / `first_value(...)` | `metrics` with `non additive by (...)` modifier | |
| 20 | Window/LOD formulas (`cumulative_*`, `moving_*`, `group_*`, `rank`) | `metrics` with `OVER (PARTITION BY ...)` | See the Decision Flowchart in ts-snowflake-formula-translation.md |
| 21 | Ratio metrics (`safe_divide`) | `DIV0(alias1, alias2)` referencing prior metric aliases | Must reference metric aliases, not nested `SUM()` calls |

### AI Context and Metadata

| # | ThoughtSpot Construct | Snowflake Semantic View Equivalent | Notes |
|---|---|---|---|
| 22 | `ai_context` | Merged into `comment='...'` with `[TS AI Context]` prefix | Partial — semantic specificity lost (an AI directive becomes a human-facing description) |
| 23 | Semantic layer structure | `with extension (CA='...')` JSON | Maps each table's columns into `dimensions[]`, `time_dimensions[]`, `metrics[]`; relationship names also listed |
| 24 | `model.properties.spotter_config.is_spotter_enabled` | User confirmation at the Step 10/12 checkpoint | Not itself an SV property |

---

## Unmapped Constructs (Limitations)

| # | ThoughtSpot Construct | Limitation | Workaround |
|---|---|---|---|
| L1 | Parameters (`parameters[]`) | Formulas referencing a parameter are omitted. Snowflake session/bind `variables:` is now GA (June 2026) but automated mapping is not yet implemented | Logged in the Unmapped Report; recommended re-implementation path is a Snowflake `variables:` entry (tracked in BL-031) |
| L2 | Fiscal calendar functions (`year([date], fiscal)`, `quarter_number([date], fiscal)`) | No fiscal parameter in Snowflake SV `expr` syntax — untranslatable at the expression level | Omit the column; surface a suggested `custom_instructions` snippet so Cortex Analyst approximates fiscal-year grouping at the SQL-generation layer |
| L3 | Format patterns (`format_pattern`) | No Snowflake equivalent | Apply in the BI tool, or via `TO_CHAR()` in a view wrapper |
| L4 | Default date buckets (`default_date_bucket`) | `time_dimensions` have no default-grain property | Document in the Unmapped Report |
| L5 | Custom sort order (`custom_order`) | No explicit value-ordering concept in Snowflake SV | Apply in the BI tool, or Snowflake `ORDER BY` |
| L6 | Geo configuration (`geo_config`) | No geospatial concept in Snowflake SV | Column migrated as a plain dimension; note in the Unmapped Report |
| L7 | Column groups / data panel groups (`column_groups`, `data_panel_column_groups`) | No grouping concept in Snowflake SV | Document group membership in the Unmapped Report; re-create in the BI tool |
| L8 | Hyperlink markup (`concat("{caption}", ..., "{/caption}", ...)`) | ThoughtSpot-specific display hint with no SQL equivalent | Omit the column; log in the Formula Translation Log |
| L9 | Row-level security (`is_bypass_rls`) | RLS rules are not exported in TML | Re-implement using Snowflake row access or column masking policies |
| L10 | Locale-specific column aliases (`column_alias_udf.tml`) | No locale support in Snowflake SV | English names/synonyms migrated only; document in the Unmapped Report |
| L11 | Model-level filters (`filters[]`) | Emitted as a named `filters:` entry, but Cortex Analyst applies it AI-optionally — not on every query the way the ThoughtSpot original was always applied | Add a Snowflake row access policy, or wrap the table in a view with the filter built in, if unconditional enforcement is required |
| L12 | `sql_view` (complex SQL — WHERE, JOIN, aggregation, subquery) | Not auto-mapped to a physical table | C/M/S user decision at the Step 10 checkpoint (Create a view / Map to an existing object / Skip). A Direct option (`base_table.definition:`) is the documented future target but not yet emitted — tracked in BL-031 |
| L13 | `facts[]` routing for raw SUM/AVG/MIN/MAX MEASUREs | Converter currently routes every MEASURE to `metrics[]` — `facts[]` is a planned future enhancement, not current behavior | None needed today; `metrics[]` output is correct and live-verified. Tracked in BL-031 |

### Notes on limitations

**L3–L7, L9, L10** are hard blockers — Snowflake Semantic View has no equivalent
concept. Document and re-implement elsewhere (BI tool or a Snowflake-native policy).

**L1, L11, L13** are "Partial" or "Planned" — a real (if not yet automated) Snowflake
construct exists (`variables:`, `filters:`, `facts[]`) but the converter does not emit
it yet. See `ts-snowflake-properties.md` for full detail and BL-031 tracking.

**L8** is a formula-level omission, not a structural gap — see the Untranslatable
Patterns sections of `ts-snowflake-formula-translation.md`.

**L12** is Partial — simple `sql_view` (`SELECT * FROM table`) auto-resolves; only
complex SQL requires a user decision.
