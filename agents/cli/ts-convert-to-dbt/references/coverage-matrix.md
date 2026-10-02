# Coverage Matrix: ThoughtSpot → dbt

What `ts-convert-to-dbt` maps and what it does not. Unlike
`ts-convert-from-dbt`, this skill performs the translation itself — see
[concept-mapping.md](concept-mapping.md) for the full construct-by-construct
detail behind each row here.

Three commands are covered: `ts dbt-export build` (Case A, new project),
`ts dbt-export diff`/`sync` (Case B, existing project), and
`ts dbt-export build-model` (the return leg — `schema.yml` back to a unified
Model TML).

---

## Mapped Constructs

| # | ThoughtSpot Construct | dbt Equivalent | Notes |
|---|---|---|---|
| 1 | Model `model_tables[]` physical table | Staging dbt model + `sources.yml` entry, **aliased to the Table's own name** | One `sources:` entry per distinct `(database, schema)`; multi-location Models get suffixed source names. Each staging model carries `config.alias: <TABLE>` so it materialises under the name ThoughtSpot already knows — without it `stg_appointments` builds `STG_APPOINTMENTS` and the return leg imports a SECOND Table beside the original, with the Model repointed at the copy (v0.133.0). An adopted Case B name is never aliased: those models already materialise somewhere real |
| 2 | Model `model_tables[]` role-play alias | Thin passthrough dbt model (`ref()` to the base staging model) | |
| 3 | **All 13 documented column tags** — `ts_column_type`, `ts_aggregation`, `ts_synonym`, `ts_format_pattern`, `ts_index_type`, `ts_index_priority`, `ts_attr_dim`, `ts_additive`, `ts_spotiq_pref`, `ts_hidden`, `ts_calendar_type`, `ts_currency_type`, `ts_geo_config` | `ts_*` tags under `config.meta` in `models/schema.yml`, and read back by both `build-model` paths | Tag set verified against docs.thoughtspot.com/cloud/**26.9.0.cl**/dbt-integration-metadata-tags (2026-09-09). YAML syntax verified by a live `dbt-fusion parse` + compiled `manifest.json` inspection (2026-08-27) and confirmed compiling in dbt Cloud (2026-08-30). Round-trip asserted property-for-property by `TestFullPropertyRoundTrip` |
| 3a | `properties.currency_type` (all three forms) | `ts_currency_type` nested block — `{type: from_isocode, isocode}` / `{type: from_column, column}` / `{type: from_browser}` | Shapes from the docs page's verbatim YAML; TML side per `thoughtspot-model-tml.md` |
| 3b | `properties.geo_config` (4 of 5 census-observed roles) | `ts_geo_config` nested block — `{type: latitude}` / `{type: longitude}` / `{type: country}` / `{type: sub_nation_region, country, region_type}` | The 5th (custom-map) role has no tag type — see L20 |
| 4 | Column `description` | dbt column `description:` | A plain dbt field, not a tag. Round-trip verified live 2026-09-09 (open-items #14) |
| 5 | Column `properties.ai_context` | `ts_ai_context` under `config.meta` | **ts-cli extension** — a gap filed with ThoughtSpot that has not shipped natively, so the server-side sync does not read it (confirmed 2026-09-09, ts-convert-from-dbt open-items #16). Both `build-model` commands do |
| 6 | Model column display name that a physical name can't produce | `ts_display_name` under `config.meta` | **ts-cli extension**, honoured by both `build-model` commands as of v0.133.0. Suppressed when the name is derivable (raw, prettified, or `<TABLE>_<COL>`), so the file stays quiet |
| 7 | Single-column join (cardinality / type / name) | `relationships` data test with `ts_join_*` tags under `config.meta`, `severity: warn` | Same live verification as row 3. `ts_join_name` carries the join's **own** ThoughtSpot name; the derived `<left>_to_<right>` form is still generated for platforms with identifier rules (Snowflake SV) but no longer emitted here, since it renamed every join on each round trip (v0.133.0) |
| 8 | Single-column join (identity only) | MetricFlow entity pair in `models/semantic_models.yml` (legacy top-level spec) | Not verified against ThoughtSpot's own MetricFlow importer — see [open-items.md](open-items.md) #2 |
| 9 | Measure column | MetricFlow `measures:` + a `type: simple` `metrics:` entry in `models/semantic_models.yml` | Secondary artifact only; the primary artifact's `ts_aggregation` tag is what actually controls aggregation on sync. Same caveat as row 8 |
| 10 | Formula (calculated) column | `ts_formula` under `config.meta` in `models/schema.yml` — expression preserved verbatim, placed on the model matching the first `[TABLE::COL]` reference | Round-trip verified live 2026-09-09: 14 formulas rebuilt with zero delta (open-items #3, #14) |
| 11 | Table-level RLS rules (`rls_rules` on the Table TML) | `ts_rls_rules` under the model-level `config.meta` in `models/schema.yml` | Applied back by `ts dbt build-model`, which patches each affected Table TML from the compiled manifest. `generate-sync-tml` preserves existing `rls_rules` on its own, so a resync does not need the patch. Verified live 2026-09-09 |
| 12 | Case B — update an existing dbt project in place | `ts dbt-export diff` (read-only change-set) / `ts dbt-export sync` (writes new tables; `--update-metadata` also updates existing ones) | Verified live end-to-end 2026-09-09 (open-items #14). Diffing covers `models/schema.yml` only — see L4 |
| 13 | Case B — an existing project's own model naming | Adopted, not renamed (`adopted_names` / `dbt_output_tables` in the output) | Matched by `{{ source() }}` location or by the Table's `db_table` equalling a dbt model name. `removed_tables` is scoped to the adopted models' directories (`scoped_to`) so unrelated models are never reported |
| 14 | Return leg — `schema.yml` back to one unified ThoughtSpot Model | `ts dbt-export build-model --schema-yml` → Model TML (pipe to `ts tml import`) | Reverses rows 3–11 out of a `schema.yml`. Exists because `generate-tml` emits one Model per FK-source (fact) table, so a multi-fact project becomes several overlapping Models — [open-items.md](open-items.md) #11 |
| 15 | The five ts-cli extension tags — `ts_formula`, `ts_display_name`, `ts_ai_context`, `ts_column_exclude`, `ts_rls_rules` | Round-trip in both directions, editable from ThoughtSpot **or** by hand in `schema.yml` | Invisible to ThoughtSpot's server-side sync, so only `ts-convert-from-dbt` **Path Y** is lossless. Both `build-model` commands now honour all five identically (v0.133.0 — the schema.yml reader previously ignored `ts_display_name` and `ts_column_exclude`); `TestCustomTagReaderParity` pins that. `ts_ai_context` is an unshipped product gap, not a native tag |
| 16 | `ts_rls_rules` on the offline return leg | `ts dbt-export build-model --rls-out <dir>` writes one `<TABLE>_rls_rules.json` per model | RLS lives on the **Table** TML, so a Model-only offline command cannot apply it — it writes the block for manual merge, and warns by name if the flag is omitted. `ts dbt build-model` (dbt Cloud) applies it automatically |
| 17 | Exporting into the per-file layout the generator reads | `ts tml export --associated --split-dir <dir>` | v0.133.0 — writes `model.json` + one `table_<NAME>.json` per Table, the exact shape `--model`/`--tables-dir` expect, and prints only a `{split_dir, written[]}` manifest. Replaces the inline split loop SKILL.md Step 3 carried. Two same-named Tables get distinct filenames rather than one silently overwriting the other |
| 18 | Reviewing a change-set before applying it | `ts dbt-export diff --format md`, `ts dbt-export sync --dry-run` | v0.133.0 — `--dry-run` returns before the first write (including under `--update-metadata`) and both render through ONE function over ONE change-set, so a reviewed plan and an applied plan cannot describe it differently. The markdown leads with the `removed_*` lists, the only lines needing a human decision. `TestSyncDryRun::test_dry_run_holds_under_update_metadata_too` pins the write-nothing guarantee |
| 19 | Updating an existing Model in place from the offline return leg | `ts dbt-export build-model --model-guid <guid> --import --profile <p>` | v0.133.0 — sets `guid` at the document root (the only placement ThoughtSpot accepts) and imports with `create_new=false`. Replaces a hand-edit between two commands whose failure mode was silent: without the guid the import CREATES A SECOND MODEL rather than erroring |

---

## Unmapped Constructs (Limitations)

### DEFERRED — not yet implemented

| # | ThoughtSpot Construct | Limitation | Notes |
|---|---|---|---|
| L1 | Composite-key joins (2+ columns) | No entity or `relationships` test emitted — reported in `skipped_composite_joins` | dbt's own single-column test limitation is shared, not specific to this exporter; see [open-items.md](open-items.md) #5 |
| L2 | Formula column whose expression carries no `[TABLE::COL]` reference | No `ts_formula` entry — reported in `skipped_formulas` | There is no dbt model to attach it to. See [open-items.md](open-items.md) #3 |
| L3 | Column Security Rules (CSR) | Not emitted at all | CSR is not part of Table TML; it lives behind `security/column/fetch`. Design decision pending on the `schema.yml` key shape — [open-items.md](open-items.md) #13 |
| L4 | Case B diffing of `models/semantic_models.yml` | `diff`/`sync` only diff `models/schema.yml` — a change to the secondary MetricFlow artifact on an existing table is un-reported | See [open-items.md](open-items.md) #4 |
| L5 | Secondary artifact still emits the **legacy** MetricFlow spec | dbt's current nested `semantic_model:` block (which `ts dbt build-model` can now read and translate) is not emitted | Follow-up (a) in ts-convert-from-dbt open-items #14 |
| L7 | `index_type` values other than `DEFAULT` / `DONT_INDEX` | No `ts_index_type` equivalent — reported in `unmapped_properties` | ThoughtSpot's tag only documents those two of TML's five values |
| L20 | `properties.geo_config` — custom-map role (`custom_file_guid` + `geometryType`) | No `ts_geo_config` type exists for it — reported in `unmapped_properties` | Also instance-local: `thoughtspot-model-tml.md` says "a portable document must not carry it — the geo role has to be dropped rather than translated" |
| L21 | `properties.value_casing`, `custom_order`, `default_date_bucket`, `search_iq_preferred` | Real Model column properties with **no `ts_*` tag at all** — nothing to map to | Now **reported** in `unmapped_properties` (v0.133.0). They were previously not collected at all, so they vanished with no trace |

### Never auto-applied by `sync` (reported for manual review)

| # | Change | Reason | Notes |
|---|---|---|---|
| L10 | `removed_tables` / `removed_source_tables` | Deleting a dbt model is not this tool's call | Printed by both `diff` and `sync` |
| L11 | `changed_tables`, without `--update-metadata` | Default is additive-only | With `--update-metadata` these ARE applied — `ts_*` meta, non-empty descriptions, and new/changed `relationships` tests |
| L12 | Removing a column that carries non-`ts_*` content | Ambiguous ownership | Even under `--update-metadata`, `_is_ts_only_column` refuses to delete a column with a `description`, a non-`ts_*` meta key, or a non-`relationships` data test. `removed_relationship` is never auto-deleted either |
| L13 | A column description cleared in ThoughtSpot | Would silently wipe hand-written dbt text | `modified_description` only fires on non-empty new text — `diff` does not report the clear and `sync` does not apply it |
| L14 | Columns tagged `ts_column_exclude` | Deliberately absent from the Model | `diff` never reports them as removed/changed and `sync` never deletes them |
| L19 | Any `ts_*` tag outside the generator's own vocabulary | Preserved, never cleared | `dbt_build_export.GENERATED_COLUMN_META_KEYS` / `GENERATED_MODEL_META_KEYS` declare exactly what `build` can emit; `sync --update-metadata` clears only those. Everything else — `ts_column_exclude`, and any tag a ThoughtSpot release newer than this build adds — is left as written and listed under `preserved_meta`. `diff` excludes them from `modified_meta` so it reports exactly what `sync` applies. The bug never shipped — it was found and fixed inside this branch; the four documented tags that originally triggered it are themselves generated now, so the boundary now serves forward-compatibility |

### Not verified — needs live confirmation

| # | ThoughtSpot Construct | Limitation | Notes |
|---|---|---|---|
| L15 | Generated `schema.yml`/`semantic_models.yml` syntax on real **dbt-core** | Verified against dbt-fusion 2.0.0-preview.212 and dbt Cloud only; not against any dbt-core version, including the "1.7 and earlier" line ThoughtSpot's own MetricFlow docs describe | See [open-items.md](open-items.md) #8 |
| L16 | Entity naming collisions across unrelated Models sharing a dbt project | Two Models joining differently-defined tables with the same node key would emit colliding MetricFlow entity names | See [open-items.md](open-items.md) #6 |
| L17 | `ts_index_type` case sensitivity on ThoughtSpot's native sync | The lower-case/upper-case round-trip maps may be unnecessary | See [open-items.md](open-items.md) #12 |
| L18 | Column-deletion path under `--update-metadata` | Unit-tested only — no live run has removed a column | The `ts columns impact` pre-deletion gate is documented in SKILL.md Step 6b but has not gated a real deletion; see [open-items.md](open-items.md) #14 |
