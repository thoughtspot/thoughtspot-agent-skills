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

schemas/
  thoughtspot-tml.md                  — TML export parsing (PyYAML pitfalls, type detection)
  thoughtspot-table-tml.md            — table TML construction reference
  thoughtspot-model-tml.md            — model TML construction reference
  thoughtspot-answer-tml.md           — Answer TML structure (formulas, parameters, sets, data source lookup) — verified
  thoughtspot-liveboard-tml.md        — Liveboard TML structure (visualizations, filters, layout, tabs) — verified
  thoughtspot-view-tml.md             — View (AGGR_WORKSHEET) TML structure — view_columns, joins, table_paths, search_query
  thoughtspot-alert-tml.md            — Monitor Alert TML structure — metric_id references, personalised_view_info
  thoughtspot-feedback-tml.md         — NLS Feedback/Coaching TML structure — search_tokens, formula_info column references
  thoughtspot-sets-tml.md             — Set TML structure (bins, groups, query sets; answer-level vs reusable)
  thoughtspot-formula-patterns.md     — ThoughtSpot formula syntax reference
  thoughtspot-connection.md           — connection object structure
  snowflake-schema.md                 — Snowflake Semantic View YAML reference

worked-examples/snowflake/
  ts-to-snowflake.md                  — end-to-end TS → SV conversion (verified against live instance)
  ts-from-snowflake.md                — end-to-end SV → TS conversion (verified against live instance)
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
