# Shared Reference Files — Conventions

Loaded when editing agents/shared/. These files are consumed by BOTH runtimes.

## Dual-runtime impact

Changes here affect:
- **Claude Code** — immediately, via `~/.claude/shared/` symlink
- **CoCo** — only after `./scripts/stage-sync.sh` (or manual `snow stage copy`)

Do not skip the stage push. Claude Code will pick up your changes automatically;
CoCo will not.

## Directory map

```
mappings/ts-snowflake/
  ts-from-snowflake-rules.md          — rules for SV → TS direction
  ts-to-snowflake-rules.md            — rules for TS → SV direction
  ts-snowflake-formula-translation.md — authoritative formula mapping (41 KB)
  ts-snowflake-properties.md          — column/join property mapping rules

mappings/ts-databricks/
  ts-from-databricks-rules.md         — rules for MV → TS direction
  ts-to-databricks-rules.md           — rules for TS → MV direction
  ts-databricks-formula-translation.md — ThoughtSpot ↔ Databricks SQL formula mapping
  ts-databricks-properties.md         — column/property coverage matrix for MV ↔ TS

mappings/tableau/
  tableau-formula-translation.md      — Tableau → ThoughtSpot formula and function mapping
  tableau-tml-rules.md                — TML generation rules for Tableau workbook conversion

schemas/
  thoughtspot-tml.md                  — TML export parsing (PyYAML pitfalls, type detection)
  thoughtspot-table-tml.md            — table TML construction reference
  thoughtspot-model-tml.md            — model TML construction reference
  ts-model-conversion-invariants.md  — canonical hard rules every Model-producing conversion skill must obey
  thoughtspot-answer-tml.md           — Answer TML structure (formulas, parameters, sets, data source lookup) — verified
  thoughtspot-liveboard-tml.md        — Liveboard TML structure (visualizations, filters, layout, tabs) — verified
  thoughtspot-view-tml.md             — View (AGGR_WORKSHEET) TML structure — view_columns, joins, table_paths, search_query
  thoughtspot-alert-tml.md            — Monitor Alert TML structure — metric_id references, personalised_view_info
  thoughtspot-feedback-tml.md         — NLS Feedback/Coaching TML structure — search_tokens, formula_info column references
  thoughtspot-sets-tml.md             — Set TML structure (bins, groups, query sets; answer-level vs reusable)
  thoughtspot-sql-view-tml.md         — SQL View TML structure (sql_view: type — query-backed, distinct from view:/AGGR_WORKSHEET)
  thoughtspot-formula-patterns.md     — ThoughtSpot formula syntax reference
  thoughtspot-connection.md           — connection object structure
  snowflake-schema.md                 — Snowflake Semantic View YAML reference
  databricks-metric-view.md           — Databricks Metric View YAML schema (v0.1/v1.1)

worked-examples/tableau/
  liveboard-kpi-sparkline.md          — KPI viz with sparkline: client_state_v2 requirement, before/after, verified template (2026-06-11)
  static-set-to-column-set.md         — Tableau static set → ThoughtSpot column set: worksheet binding, EQ-list, {Null}, NE/except, formula-col anchor, live-verified (2026-06-12)
  topn-set-to-query-set.md            — Tableau Top-N/Bottom-N set → ThoughtSpot query set (ADVANCED/COLUMN_BASED): dynamic (rank + parameter-filter formula, model param) vs static (top N keyword) forms, live-verified (2026-06-12)
  data-blend-to-model.md             — two-datasource blend → single ThoughtSpot model with LEFT_OUTER inline join; cross-ds formula translation, join-on-secondary pattern, date-grain caveats (2026-06-14)

worked-examples/snowflake/
  ts-to-snowflake.md                  — end-to-end TS → SV conversion (verified against live instance)
  ts-from-snowflake.md                — end-to-end SV → TS conversion — BIRD_SUPERHEROS_SV (verified against live instance)
  ts-from-snowflake-dunder.md         — end-to-end SV → TS conversion — DUNDER_MIFFLIN_SALES_INVENTORY (multi-value synonyms, descriptions, semi-additive, unique count, concat; verified against live instance)
  ts-from-snowflake-identifier-resolution.md — end-to-end SV → TS conversion — COMPANY_WORKFORCE_SV (facts, metric-on-fact inlining, double aggregation via group_count/group_sum, duplicate column_id fix; verified against live instance 2026-06-13)

worked-examples/databricks/
  ts-to-databricks.md                 — end-to-end TS → MV conversion — DUNDER_MIFFLIN (multi-fact split, flattened views, LOD dimensions, semi-additive, MEASURE()/ANY_VALUE() cross-refs; verified against live instance 2026-05-25)
  ts-from-databricks.md               — end-to-end MV → TS conversion — e-commerce transactions (direct + computed dims, ratio + window + conditional measures; verified against live instance 2026-05-28)
  ts-from-databricks-sql-view.md      — end-to-end MV → TS conversion — SELECT subquery source → SQL View + Model (CASE formula, COUNT DISTINCT ratio, filter baked into sql_query; verified against live instance 2026-05-28)
```

## Worked examples are ground truth

`worked-examples/snowflake/` contains outputs verified against a live ThoughtSpot and
Snowflake instance. If a rule in `mappings/` or `schemas/` conflicts with what a worked
example produces, investigate before changing either. Do not update a rule without also
updating the worked example to show the correct new output — this is how you verify
a rule change is correct, not just syntactically plausible.

## Formula translation is authoritative

`mappings/ts-snowflake/ts-snowflake-formula-translation.md` is the canonical source for
all formula decisions. Extend this file when adding new mappings. Do not add inline
formula logic to SKILL.md files — if a formula appears in a skill, it should be
cross-referenced to this file.

## Adding new mappings

1. Add the rule to the relevant mapping file
2. Push to stage: `./scripts/stage-sync.sh`
3. Update the worked example if the rule changes existing output
4. Run `python tools/validate/check_yaml.py` to confirm YAML blocks still parse

## Future platforms

New platform mappings go in a new subdirectory (e.g. `mappings/ts-databricks/`).
Do not modify Snowflake mapping files for other platforms — keep each platform's
rules isolated so they can evolve independently.
