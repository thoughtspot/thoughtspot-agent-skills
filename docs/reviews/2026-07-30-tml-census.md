# TML property census — se-thoughtspot, 2026-07-30

A read-only property census of real ThoughtSpot logical-table TML on the
`se-thoughtspot` cluster (`https://se-thoughtspot-cloud.thoughtspot.cloud`), run to
validate our schema references and OSI construct-mapping coverage against what the
product actually emits in the wild.

**Nothing was created, modified or deleted on the instance.** Every call was
`ts metadata search` (read) or `ts tml export` (read). No repo file was edited.

| | |
|---|---|
| Population | 15,204 `LOGICAL_TABLE` objects |
| Sample requested | 506 GUIDs |
| Exported successfully | **500** |
| Export failures | 6 (all instance-side, see below) |
| Distinct key-paths observed | **207** across four document types |
| Ground truth compared against | 4 schema refs (read from the **working tree**, ~12:57 local) + `docs/ossie/ts-osi-construct-mapping.md` (read from **`main`** via `git show`, to avoid racing the branch edit) |

> ### ⚠️ Concurrency note — read this before acting on §5
>
> Another agent is editing the schema refs and the construct mapping on this working tree
> **during** this census. My schema-ref ground truth was snapshotted at ~12:57; by the time
> the report was written, that agent had already landed several of the corrections below.
> **§5.4 reconciles the overlap** — 4 findings are already fixed, and the census's
> contribution to those is larger-sample corroboration plus, in one case
> (`calendar` on a Table column), a fact that agent explicitly recorded as *not* observed.
> Everything else in §5 is new and unaddressed.

Artifacts (persist for follow-up, nothing deleted):
`/private/tmp/claude-501/-Users-damianwaldron-Dev-thoughtspot-agent-skills/83419929-bba5-40c7-8502-4d6f018c64fd/scratchpad/tml-census/`
— `all-logical-tables.json` (the 15,204-object search), `sample.json`, `exports/` (500
parsed documents), `inventory.json` / `inventory.md` (raw path census), `buckets.json`
(classification), and the five scripts (`build_sample.py`, `export_sample.py`,
`census.py`, `ground_truth.py`, `classify.py`, `probe.py`, `probe2.py`, `probe3.py`).

---

## 1. Sample composition

### 1.1 Population, by metadata subtype

| Subtype | Population | In sample | Exported |
|---|--:|--:|--:|
| `ONE_TO_ONE_LOGICAL` (Table) | 11,971 | 255 | 255 |
| `WORKSHEET` (Model **and** legacy Worksheet) | 2,397 | 148 | 143 |
| `USER_DEFINED` (uploaded / CSV Table) | 753 | 20 | 20 |
| `AGGR_WORKSHEET` (View) | 43 | 43 | 42 |
| `SQL_VIEW` (SQL View) | 40 | 40 | 40 |
| **Total** | **15,204** | **506** | **500** |

### 1.2 Exported documents, by TML root key (the authoritative type)

| Root key | Docs | From spread stratum | From targeted stratum | Target | Met? |
|---|--:|--:|--:|---|:-:|
| `model:` | **143** | 45 | 98 | ≥40 | ✅ 3.6× |
| `table:` | **275** | 205 | 70 | ≥30 | ✅ 9× |
| `view:` | **42** | 1 | 41 | ≥10 combined | ✅ |
| `sql_view:` | **40** | 0 | 40 | (with `view:`) | ✅ |
| `worksheet:` | **0** | — | — | ~10 | ❌ **none exist** — see 1.4 |

### 1.3 Sampling method

Four strata, de-duplicated by GUID:

| Stratum | Method | Picked |
|---|---|--:|
| `A-spread` | every 60th object across the whole ordered 15,204-object result set | 254 |
| `B-model` | `WORKSHEET`-subtype objects, round-robin across **authors** (largest author first) to maximise variety, excluding the `TS:` system objects | 100 |
| `C-rare` | **all** 40 `SQL_VIEW` + **all** 43 `AGGR_WORKSHEET` — the whole population of both, since they are scarce and high-value for schema validation | 82 |
| `D-table` | additional Tables, round-robin across **connections** (1,899 distinct) to spread warehouse types | 70 |

Export command was plain `ts tml export <guid…> --profile se-thoughtspot --format JSON`,
batched 12 GUIDs per call with a 0.5 s pause, whole-batch failures retried singly. **No
`--fqn`, no `--associated`, no `--include-obj-id`** — so `fqn` and `obj_id` paths are
absent from this census *by construction*, not by absence in the product. Any conclusion
about those two keys is out of scope here.

### 1.4 Finding: there is no legacy `worksheet:` TML left on this cluster

The brief asked for ~10 `worksheet:` documents for contrast. **Zero are obtainable.**

- All 2,397 `WORKSHEET`-subtype objects were checked: **2,394 carry
  `metadata_header.worksheetVersion: "V2"`**, and every one of the 143 sampled V2 objects
  exported with root key `model:`. V2 *is* a Model.
- The only 3 objects **without** `worksheetVersion` — `TS: Service Resources`,
  `TS: Database`, `TS: Search` — are ThoughtSpot's own system worksheets, and all 3
  return `FORBIDDEN … Cannot download TML due to lack of access to objects`.

So on a current Cloud build, `worksheet:` is not reachable by export at all. `NM6` in the
construct mapping (reject `worksheet:` documents) is still correct as a defensive rule,
but it is defending against an input that this cluster can no longer produce.

### 1.5 Export failures (6 / 506 — all instance-side, none a CLI or method fault)

| Object | Error |
|---|---|
| `TS: Service Resources` | `FORBIDDEN` — Cannot download TML due to lack of access to objects |
| `Product Usage (Deprecated)` | `FORBIDDEN` — same |
| `TS: External Table Current Row Count [Deprecated]` | `FORBIDDEN` — same |
| `Retail Sales (AD)` | `OBJECT_INVALID_STATE` — "Worksheet has …" (broken object) |
| `Care Provider - BW` | `OBJECT_INVALID_STATE` — same |
| `Abhas's Testing Parameters` | `WORKSHEET_FORMULA_GENERATION_ERROR` |

### 1.6 Incidental ts-cli bug found (report only — no repo edit made)

`ts tml export --parse` **crashes** with `TypeError: argument of type 'NoneType' is not
iterable` when any object in the batch returns a null `edoc` — which is exactly what a
`FORBIDDEN` or `OBJECT_INVALID_STATE` object returns. One inaccessible GUID kills the
whole batch.

```
tools/ts-cli/ts_cli/commands/tml.py:391  → detect_tml_type(parsed_tml)
tools/ts-cli/ts_cli/commands/tml.py:258  → for key in _TML_TYPE_KEYS: if key in parsed:
TypeError: argument of type 'NoneType' is not iterable
```

`detect_tml_type()` needs a `parsed is None` guard, and the `--parse` loop needs to skip
(and report) docs whose `edoc` is null rather than parse it. This census had to abandon
`--parse` and parse the `edoc` strings itself. **Recommend a `BL-` item or a small fix PR.**

---

## 2. Per-type property inventory

Full tables. `[]` marks a list level; `{*}` marks a level whose keys are user-chosen
names. `Occ` = total occurrences across the sample; `Docs` = how many documents of that
type contain the path.

### `model:` — 143 documents, 97 distinct paths

| Path | Occ | Docs | Kind | Example values |
|---|--:|--:|---|---|
| `guid` | 143 | 143 | str | `024186e5-b10f-47bd-98bc-b49db3c85dee` · `02b10293-3e73-4a9b-a027-71c13e66508a` |
| `model` | 143 | 143 | dict | — |
| `model.action_object_associations` | 1 | 1 | list | — |
| `model.action_object_associations[].action_name` | 1 | 1 | str | `Generate Forecast` |
| `model.action_object_associations[].context` | 1 | 1 | str | `CONTEXT_MENU` |
| `model.action_object_associations[].enabled` | 1 | 1 | bool | `true` |
| `model.column_groups` | 3 | 3 | list | — |
| `model.column_groups[].column_group_info` | 3 | 3 | list | — |
| `model.column_groups[].column_group_info[].include_ungrouped_columns` | 9 | 3 | bool | `false` · `true` |
| `model.column_groups[].column_group_info[].name` | 9 | 3 | str | `KPIs` · `Location` |
| `model.column_groups[].properties` | 3 | 3 | dict | — |
| `model.column_groups[].properties.default_sort` | 3 | 3 | str | `ENABLE` |
| `model.column_groups[].properties.status` | 3 | 3 | str | `ENABLE` |
| `model.column_groups[].type` | 3 | 3 | str | `DATA_PANEL` |
| `model.columns` | 143 | 143 | list | — |
| `model.columns[].column_id` | 4436 | 142 | str | `DATES::DATE_KEY` · `DATES::FULL_DATE` |
| `model.columns[].data_panel_column_groups` | 9 | 3 | dict | — |
| `model.columns[].data_panel_column_groups.{*}` | 9 | 3 | str | `Location: ''` · `KPIs: ''` |
| `model.columns[].description` | 2023 | 72 | str | `comes from product listing` · `This maps to the product categories in our ERP` |
| `model.columns[].formula_id` | 549 | 69 | str | `formula_Date` · `formula_Per item price` |
| `model.columns[].name` | 4985 | 143 | str | `Date Date Key` · `Full Date` |
| `model.columns[].properties` | 4985 | 143 | dict | — |
| `model.columns[].properties.aggregation` | 1806 | 137 | str | `SUM` · `AVERAGE` |
| `model.columns[].properties.ai_context` | 656 | 16 | str | `Unique integer identifier for calendar dates enabling precise joins and filtering for daily store operations analysis across the Starbucks data model.` · `Calendar date field for trending transactions, net sales, labor hours, wait times, and satisfaction metrics over time in store operations analysis.` |
| `model.columns[].properties.calendar` | 72 | 35 | str | `calendar` · `SeanTSCROOTS` |
| `model.columns[].properties.column_type` | 4985 | 143 | str | `ATTRIBUTE` · `MEASURE` |
| `model.columns[].properties.currency_type` | 81 | 21 | dict | — |
| `model.columns[].properties.currency_type.iso_code` | 81 | 21 | str | `USD` · `INR` |
| `model.columns[].properties.custom_order` | 11 | 7 | list | — |
| `model.columns[].properties.custom_order[]` | 50 | 7 | str | `sunday` · `monday` |
| `model.columns[].properties.format_pattern` | 98 | 38 | str | `###.##%` · `yyyy-MM-dd` |
| `model.columns[].properties.geo_config` | 134 | 43 | dict | — |
| `model.columns[].properties.geo_config.country` | 5 | 5 | bool | `true` |
| `model.columns[].properties.geo_config.custom_file_guid` | 7 | 3 | str | `f3faaa74-147f-4376-ac42-eff0c3779f6f` · `7cf7fb79-5a02-48e7-8f79-df600f76ee77` |
| `model.columns[].properties.geo_config.geometryType` | 7 | 3 | str | `POLYGON` · `MULTI_POLYGON` |
| `model.columns[].properties.geo_config.latitude` | 17 | 17 | bool | `true` |
| `model.columns[].properties.geo_config.longitude` | 17 | 17 | bool | `true` |
| `model.columns[].properties.geo_config.region_name` | 88 | 39 | dict | — |
| `model.columns[].properties.geo_config.region_name.country` | 88 | 39 | str | `UNITED STATES` · `UNITED KINGDOM` |
| `model.columns[].properties.geo_config.region_name.region_name` | 88 | 39 | str | `state` · `zip code` |
| `model.columns[].properties.index_priority` | 20 | 5 | float | `10.0` · `9.0` |
| `model.columns[].properties.index_type` | 3629 | 134 | str | `DONT_INDEX` · `PREFIX_ONLY` |
| `model.columns[].properties.is_additive` | 15 | 4 | bool | `true` |
| `model.columns[].properties.is_attribution_dimension` | 5 | 1 | bool | `false` |
| `model.columns[].properties.is_hidden` | 67 | 11 | bool | `true` |
| `model.columns[].properties.search_iq_preferred` | 135 | 9 | bool | `true` |
| `model.columns[].properties.spotiq_preference` | 15 | 11 | str | `EXCLUDE` |
| `model.columns[].properties.synonym_type` | 2485 | 77 | str | `AUTO_GENERATED` · `USER_DEFINED` |
| `model.columns[].properties.synonyms` | 2812 | 96 | list | — |
| `model.columns[].properties.synonyms[]` | 9329 | 96 | str | `item` · `category` |
| `model.columns[].properties.value_casing` | 545 | 18 | str | `UNKNOWN` |
| `model.description` | 76 | 76 | str | `cognizant.com IT Services Marketing analytics model.` · `The "P2 Retail Sales" worksheet provides a comprehensive overview of retail sales data, capturing various aspects of customer behavior and store performance. It…` |
| `model.filters` | 5 | 5 | list | — |
| `model.filters[].column` | 5 | 5 | list | — |
| `model.filters[].column[]` | 5 | 5 | str | `Event Category` · `Date Filter` |
| `model.filters[].oper` | 5 | 5 | str | `in` · `=` |
| `model.filters[].values` | 5 | 5 | list | — |
| `model.filters[].values[]` | 5 | 5 | str | `content` · `true` |
| `model.formulas` | 69 | 69 | list | — |
| `model.formulas[].expr` | 555 | 69 | str | `add_days ( [fact_retapp_sales::recorddate] , diff_days ( today ( ) , 04/30/2020 ) )` · `if ( [dim_retapp_products::producttype] = "jackets" ) then "creator" else if ( [dim_retapp_products::producttype] = "shirts" ) then "explorer" else "viewer"` |
| `model.formulas[].id` | 555 | 69 | str | `formula_Date` · `formula_License` |
| `model.formulas[].name` | 555 | 69 | str | `Date` · `License` |
| `model.formulas[].properties` | 10 | 8 | dict | — |
| `model.formulas[].properties.column_type` | 10 | 8 | str | `ATTRIBUTE` |
| `model.lesson_plans` | 8 | 8 | list | — |
| `model.lesson_plans[].lesson_id` | 22 | 8 | int | `0` · `1` |
| `model.lesson_plans[].lesson_plan_string` | 22 | 8 | str | `What were [Sales] by [Store Region] in [Date].'last year' ?` · `What were your [top] [Sales] per [Brand] in [Date].'last 2 years' ?` |
| `model.model_tables` | 143 | 143 | list | — |
| `model.model_tables[].alias` | 31 | 6 | str | `fact_connectivity_usage_blitz_transatel_674965` · `dim_date_blitz_transatel_674965` |
| `model.model_tables[].joins` | 193 | 110 | list | — |
| `model.model_tables[].joins[].cardinality` | 237 | 57 | str | `MANY_TO_ONE` · `ONE_TO_MANY` |
| `model.model_tables[].joins[].on` | 233 | 56 | str | `[MARKETING_PERFORMANCE::ACCOUNT_KEY] = [ACCOUNTS::ACCOUNT_KEY]` · `[MARKETING_PERFORMANCE::CAMPAIGN_KEY] = [CAMPAIGNS::CAMPAIGN_KEY]` |
| `model.model_tables[].joins[].referencing_join` | 260 | 58 | str | `SYS_CONSTRAINT_91b2cf64-766c-4fcc-a924-e3e574d4aacc` · `SYS_CONSTRAINT_a97b737f-d55c-4d8b-80b8-039baf005fec` |
| `model.model_tables[].joins[].type` | 241 | 63 | str | `LEFT_OUTER` · `INNER` |
| `model.model_tables[].joins[].with` | 493 | 110 | str | `ACCOUNTS` · `CAMPAIGNS` |
| `model.model_tables[].name` | 599 | 143 | str | `DATES` · `ACCOUNTS` |
| `model.name` | 143 | 143 | str | `TST_COG_05260859_RLO_mdl` · `Liz (SE) Retail Apparel` |
| `model.parameters` | 21 | 21 | list | — |
| `model.parameters[].data_type` | 63 | 21 | str | `CHAR` · `DOUBLE` |
| `model.parameters[].default_value` | 63 | 21 | str | `monthly` · `sales` |
| `model.parameters[].description` | 57 | 20 | str | `` · `Metric parameter on retail sales model` |
| `model.parameters[].id` | 63 | 21 | str | `a09a89e5-6dc8-4e4e-8f6e-63476fe5fe7e` · `2cd47d1c-b04b-4b1b-9c5d-7acc1b6c3285` |
| `model.parameters[].list_config` | 23 | 13 | dict | — |
| `model.parameters[].list_config.list_choice` | 23 | 13 | list | — |
| `model.parameters[].list_config.list_choice[].display_name` | 51 | 9 | str | `Weekly` · `Monthly` |
| `model.parameters[].list_config.list_choice[].value` | 79 | 13 | str | `weekly` · `monthly` |
| `model.parameters[].name` | 63 | 21 | str | `Date Granularity` · `Metric Selector` |
| `model.parameters[].range_config` | 7 | 4 | dict | — |
| `model.parameters[].range_config.include_max` | 7 | 4 | bool | `true` |
| `model.parameters[].range_config.include_min` | 7 | 4 | bool | `true` |
| `model.parameters[].range_config.range_max` | 7 | 4 | str | `05/15/2025` · `2.0` |
| `model.parameters[].range_config.range_min` | 7 | 4 | str | `05/20/2020` · `0.0` |
| `model.properties` | 143 | 143 | dict | — |
| `model.properties.is_bypass_rls` | 143 | 143 | bool | `false` |
| `model.properties.join_progressive` | 143 | 143 | bool | `true` · `false` |
| `model.properties.spotter_config` | 143 | 143 | dict | — |
| `model.properties.spotter_config.is_spotter_enabled` | 143 | 143 | bool | `true` · `false` |

### `table:` — 275 documents, 48 distinct paths

| Path | Occ | Docs | Kind | Example values |
|---|--:|--:|---|---|
| `guid` | 275 | 275 | str | `0166b554-cfaa-4a29-8c3b-3217452554da` · `01ff5727-c2c7-40bc-8c5e-224e4d3741ea` |
| `table` | 275 | 275 | dict | — |
| `table.columns` | 275 | 275 | list | — |
| `table.columns[].db_column_name` | 2719 | 275 | str | `CLIENT_ENGAGEMENTS_KEY` · `MONTH_KEY` |
| `table.columns[].db_column_properties` | 2719 | 275 | dict | — |
| `table.columns[].db_column_properties.data_type` | 2719 | 275 | str | `INT64` · `VARCHAR` |
| `table.columns[].description` | 147 | 21 | str | `Unique identifier for each sales or distribution channel` · `Name of the sales or distribution channel` |
| `table.columns[].name` | 2719 | 275 | str | `CLIENT_ENGAGEMENTS_KEY` · `MONTH_KEY` |
| `table.columns[].properties` | 2719 | 275 | dict | — |
| `table.columns[].properties.aggregation` | 1307 | 252 | str | `SUM` · `AVERAGE` |
| `table.columns[].properties.calendar` | 1 | 1 | str | `SeanTSCROOTS` |
| `table.columns[].properties.column_type` | 2719 | 275 | str | `MEASURE` · `ATTRIBUTE` |
| `table.columns[].properties.currency_type` | 1 | 1 | dict | — |
| `table.columns[].properties.currency_type.column` | 1 | 1 | str | `TARGET_CURRENCY` |
| `table.columns[].properties.format_pattern` | 37 | 13 | str | `MM/dd/yyyy` · `yyyy-MM-dd HH:mm:ss` |
| `table.columns[].properties.index_type` | 2358 | 259 | str | `DONT_INDEX` · `PREFIX_AND_SUBSTRING` |
| `table.columns[].properties.is_hidden` | 11 | 4 | bool | `true` |
| `table.columns[].properties.synonyms` | 11 | 2 | list | — |
| `table.columns[].properties.synonyms[]` | 11 | 2 | str | `` · `Length of Stay` |
| `table.columns[].properties.value_casing` | 31 | 4 | str | `UNKNOWN` |
| `table.connection` | 273 | 273 | dict | — |
| `table.connection.name` | 273 | 273 | str | `TST_US_07221120_XM6_conn` · `TST_EYU_05210619_V3L_conn` |
| `table.dataset_id` | 4 | 4 | str | `28ede9b627ab` · `f147b3fb21c9` |
| `table.db` | 275 | 275 | str | `DEMOBUILD` · `AM_DB` |
| `table.db_table` | 275 | 275 | str | `CLIENT_ENGAGEMENTS` · `CONSULTANTS` |
| `table.description` | 8 | 8 | str | `DI set 2/16/23` · `This is a link table. Objects in ThoughtSpot can be tagged multiple times.` |
| `table.joins_with` | 50 | 50 | list | — |
| `table.joins_with[].destination` | 165 | 50 | dict | — |
| `table.joins_with[].destination.name` | 165 | 50 | str | `CLIENTS` · `REGIONS` |
| `table.joins_with[].name` | 165 | 50 | str | `SYS_CONSTRAINT_14c56f47-3487-4225-b215-b8b9b57eebdd` · `SYS_CONSTRAINT_5dfac952-ac90-4036-aac2-183ad3521eee` |
| `table.joins_with[].on` | 165 | 50 | str | `[CLIENT_ENGAGEMENTS::CLIENT_KEY] = [CLIENTS::CLIENT_KEY]` · `[CLIENT_ENGAGEMENTS::REGION_KEY] = [REGIONS::REGION_KEY]` |
| `table.joins_with[].type` | 165 | 50 | str | `INNER` · `LEFT_OUTER` |
| `table.name` | 275 | 275 | str | `CLIENT_ENGAGEMENTS` · `CONSULTANTS` |
| `table.properties` | 275 | 275 | dict | — |
| `table.properties.spotter_config` | 275 | 275 | dict | — |
| `table.properties.spotter_config.is_spotter_enabled` | 275 | 275 | bool | `false` · `true` |
| `table.rls_rules` | 2 | 2 | dict | — |
| `table.rls_rules.rules` | 2 | 2 | list | — |
| `table.rls_rules.rules[].expr` | 2 | 2 | str | `ts_groups != "katrina's group"` · `ts_groups = [BANK_EMPLOYEES_1::COUNTRY] ` |
| `table.rls_rules.rules[].name` | 2 | 2 | str | `test` · `RLS By Country` |
| `table.rls_rules.table_paths` | 1 | 1 | list | — |
| `table.rls_rules.table_paths[].column` | 1 | 1 | list | — |
| `table.rls_rules.table_paths[].column[]` | 1 | 1 | str | `COUNTRY` |
| `table.rls_rules.table_paths[].id` | 1 | 1 | str | `BANK_EMPLOYEES_1` |
| `table.rls_rules.table_paths[].table` | 1 | 1 | str | `BANK_EMPLOYEES` |
| `table.rls_rules.tables` | 2 | 2 | list | — |
| `table.rls_rules.tables[].name` | 2 | 2 | str | `FACT_RETAPP_SALES KB` · `BANK_EMPLOYEES` |
| `table.schema` | 275 | 275 | str | `TST_US_07221120_XM6_sch` · `TST_EYU_05210619_V3L_sch` |

### `view:` — 42 documents, 47 distinct paths

| Path | Occ | Docs | Kind | Example values |
|---|--:|--:|---|---|
| `guid` | 42 | 42 | str | `03e26543-e667-4115-a63d-2f9b1a6905bc` · `0a4370f4-67b2-4e64-adf6-3de017a7fba8` |
| `view` | 42 | 42 | dict | — |
| `view.description` | 8 | 8 | str | `This Year vs Last Year` · `[object Object]` |
| `view.formulas` | 19 | 19 | list | — |
| `view.formulas[].expr` | 46 | 19 | str | `group_min ( [Timestamp] , [User Id] )` · `start_of_month ( [Fill Date] )` |
| `view.formulas[].id` | 46 | 19 | str | `formula_User First Login` · `formula_PMPM month` |
| `view.formulas[].name` | 46 | 19 | str | `User First Login` · `PMPM month` |
| `view.formulas[].properties` | 4 | 3 | dict | — |
| `view.formulas[].properties.column_type` | 4 | 3 | str | `ATTRIBUTE` |
| `view.formulas[].was_auto_generated` | 46 | 19 | bool | `false` |
| `view.joins` | 1 | 1 | list | — |
| `view.joins[].destination` | 1 | 1 | str | `TS: External Table Info [Deprecated]` |
| `view.joins[].id` | 1 | 1 | str | `Daily Row Count - Table Info` |
| `view.joins[].name` | 1 | 1 | str | `Daily Row Count - Table Info` |
| `view.joins[].source` | 1 | 1 | str | `TS: Daily Row Count External Table [Deprecated]` |
| `view.joins_with` | 6 | 6 | list | — |
| `view.joins_with[].destination` | 15 | 6 | dict | — |
| `view.joins_with[].destination.name` | 15 | 6 | str | `OptumRx_Member Months` · `TS: External Table Info [Deprecated]` |
| `view.joins_with[].name` | 15 | 6 | str | `PMPM Join by Date` · `Daily Row Count - Table Info` |
| `view.joins_with[].on` | 15 | 6 | str | `[OptumRx View::PMPM month] = [OptumRx_Member Months::Year Month in MM-DD-YYYY]` · `[TS\: Daily Row Count External Table \[Deprecated\]::table_id] = [TS\: External Table Info \[Deprecated\]::table_id]` |
| `view.joins_with[].type` | 15 | 6 | str | `INNER` |
| `view.name` | 42 | 42 | str | `Demo view - hiro` · `Total Sales by Age Group` |
| `view.search_query` | 42 | 42 | str | `[region] [sales]` · `[Sales] [Age Group]` |
| `view.table_paths` | 1 | 1 | list | — |
| `view.table_paths[].id` | 2 | 1 | str | `TS: Daily Row Count External Table [Deprecated]_1` · `TS: External Table Info [Deprecated]_1` |
| `view.table_paths[].join_path` | 1 | 1 | list | — |
| `view.table_paths[].join_path[].join` | 1 | 1 | list | — |
| `view.table_paths[].join_path[].join[]` | 1 | 1 | str | `Daily Row Count - Table Info` |
| `view.table_paths[].table` | 2 | 1 | str | `TS: Daily Row Count External Table [Deprecated]` · `TS: External Table Info [Deprecated]` |
| `view.tables` | 42 | 42 | list | — |
| `view.tables[].id` | 43 | 42 | str | `(Sample) Retail - Apparel` · `Retail MP&A Analysis` |
| `view.tables[].name` | 43 | 42 | str | `(Sample) Retail - Apparel` · `Retail MP&A Analysis` |
| `view.view_columns` | 42 | 42 | list | — |
| `view.view_columns[].name` | 265 | 42 | str | `region` · `Total sales` |
| `view.view_columns[].properties` | 265 | 42 | dict | — |
| `view.view_columns[].properties.aggregation` | 104 | 35 | str | `SUM` · `COUNT` |
| `view.view_columns[].properties.column_type` | 265 | 42 | str | `ATTRIBUTE` · `MEASURE` |
| `view.view_columns[].properties.currency_type` | 5 | 5 | dict | — |
| `view.view_columns[].properties.currency_type.iso_code` | 5 | 5 | str | `USD` · `JPY` |
| `view.view_columns[].properties.format_pattern` | 13 | 11 | str | `MMM yyyy` · `yyyyMMdd HH':'mm':'ss` |
| `view.view_columns[].properties.geo_config` | 1 | 1 | dict | — |
| `view.view_columns[].properties.geo_config.region_name` | 1 | 1 | dict | — |
| `view.view_columns[].properties.geo_config.region_name.country` | 1 | 1 | str | `UNITED STATES` |
| `view.view_columns[].properties.geo_config.region_name.region_name` | 1 | 1 | str | `state` |
| `view.view_columns[].properties.index_type` | 126 | 36 | str | `DONT_INDEX` |
| `view.view_columns[].properties.value_casing` | 75 | 10 | str | `UNKNOWN` |
| `view.view_columns[].search_output_column` | 265 | 42 | str | `region` · `Total sales` |

### `sql_view:` — 40 documents, 15 distinct paths

| Path | Occ | Docs | Kind | Example values |
|---|--:|--:|---|---|
| `guid` | 40 | 40 | str | `041e27d0-63d1-4619-a9c4-970f7f4a2e33` · `0ac9b5e1-5a2f-4244-83a6-19d46149babb` |
| `sql_view` | 40 | 40 | dict | — |
| `sql_view.connection` | 40 | 40 | dict | — |
| `sql_view.connection.name` | 40 | 40 | str | `Retail Apparel - Snowflake -TO BE DELETED` · `snowflake_ol_sandbox` |
| `sql_view.description` | 4 | 4 | str | `UNPIVOT of wide-format FDI data (year columns) into long format.\nSource: AGENT_SKILLS.FDI_ANALYTICS.FDI_DATA\nMigrated from Tableau workbook: Foreign Direct In…` · `Connection: B2C marketing\nDate field: Date` |
| `sql_view.name` | 40 | 40 | str | `Banner_Retail_Apparel` · `IDC - SQL VIEW Example` |
| `sql_view.sql_query` | 40 | 40 | str | `SELECT \n      "ta_3"."PRODUCTNAME" "PRODUCTNAME", \n      "ta_2"."STORENAME" "STORENAME", \n      "ta_2"."REGION" "REGION", \n      "ta_3"."PRODUCTTYPE" "PRODU…` · `WITH RankedCompanies AS (
\n    select 
\n        Company, 
\n        Value, 
\n        ROW_NUMBER() OVER (ORDER BY Value DESC) as rn
\n    from (
\n        SEL…` |
| `sql_view.sql_view_columns` | 40 | 40 | list | — |
| `sql_view.sql_view_columns[].description` | 18 | 2 | str | `Fiscal year period string (e.g. _2000_01, _2001_02)` · `Fiscal year start date derived from YEAR_PERIOD (e.g. 2000-01-01)` |
| `sql_view.sql_view_columns[].name` | 385 | 40 | str | `PRODUCTNAME` · `STORENAME` |
| `sql_view.sql_view_columns[].properties` | 385 | 40 | dict | — |
| `sql_view.sql_view_columns[].properties.aggregation` | 137 | 35 | str | `SUM` · `AVERAGE` |
| `sql_view.sql_view_columns[].properties.column_type` | 385 | 40 | str | `ATTRIBUTE` · `MEASURE` |
| `sql_view.sql_view_columns[].properties.index_type` | 288 | 36 | str | `DONT_INDEX` |
| `sql_view.sql_view_columns[].sql_output_column` | 385 | 40 | str | `PRODUCTNAME` · `STORENAME` |

---

## 3. Classification

| Bucket | Count |
|---|--:|
| **UNDOCUMENTED** (absent from our schema refs — the gold) | **25** |
| SCHEMA-DOCUMENTED-BUT-UNMAPPED (in a schema ref, not named in the construct mapping) | 14 |
| DOCUMENTED (in a schema ref *and* mapped) | 168 |
| DOCUMENTED-NEVER-OBSERVED (in our refs, zero occurrences) | 128 |

---

### 3.1 UNDOCUMENTED — paths our schema refs do not describe

Ordered by severity of the gap, not alphabetically. Every row carries live evidence.

#### 3.1.1 High severity — a documented field is *wrong*, not merely missing

| # | Path | Occ | Docs | Evidence | Why it matters |
|---|---|--:|--:|---|---|
| U1 | `view.view_columns[].search_output_column` | 265 | **42/42** | `{"name": "region", "search_output_column": "region", …}` (`Demo view - hiro`); `{"name":"Total sales","search_output_column":"Total sales"}` | **`thoughtspot-view-tml.md` documents `column_id` as the View column-reference field and never mentions `search_output_column`.** In 42 of 42 real Views, `column_id` appears **zero** times and `search_output_column` appears in **every** column (265/265). Our View reference's central field is the wrong one. Worse, `thoughtspot-sql-view-tml.md` lists "Using `search_output_column` — Wrong field name — that does not exist" as a *common import error*, which is true for `sql_view:` and actively misleading for `view:`. |
| U2 | `model.columns[].description` | **2,023** | **72/143** | `"description": "This is the same as Net Sales, in USD"` on `Sales`; `"comes from product listing"` on `Product` (`Liz (SE) Retail Apparel`) | At snapshot time the Model TML reference's `columns[]` table had **no `description` row**, and it is the second-most-common optional column key in the wild. **Already fixed on the concurrent branch** (§5.4) — retained here because this census's numbers are 3.6× the sample that fix was based on, and because §4.1 quantifies the formula-backed split precisely. |
| U3 | `table.rls_rules.table_paths[].column[]` | 1 | 1/275 | `"column": ["COUNTRY"]` (`BANK_EMPLOYEES`) | `thoughtspot-table-tml.md` documents this as a **string** with brackets in the value: `column: "[COL_NAME]"`. Reality is a **list of bare column names**. A generator following the ref emits the wrong YAML type. |
| U4 | `view.view_columns[].properties.geo_config.region_name` as a **dict** | 1 | 1/42 | `{"region_name": {"country": "UNITED STATES", "region_name": "state"}}` (`LMS Banking View`, col `State`) | Both `thoughtspot-view-tml.md` and `thoughtspot-sql-view-tml.md` document `region_name` as a **list** of `{country, region_name}`. The Model ref documents it as a dict. Observed on Views: **dict**, matching the Model ref, not the View ref. The two references disagree and the View/SQL-View one is the one that is wrong. |

#### 3.1.2 Medium severity — real construct, entirely absent from our references

| # | Path | Occ | Docs | Example values | Note |
|---|---|--:|--:|---|---|
| U5 | `model.action_object_associations[]` | 1 | 1/143 | `[{"action_name": "Generate Forecast", "context": "CONTEXT_MENU", "enabled": true}]` (`MT Retail Sales`) | A whole model-level construct we have never documented: **custom actions** bound to a Model. Sub-keys observed: `action_name` (str), `context` (`CONTEXT_MENU`), `enabled` (bool). Not in any schema ref, not in the construct mapping, not in any converter. |
| U6 | `model.columns[].properties.geo_config.custom_file_guid` + `.geometryType` | 7 each | 3/143 | `custom_file_guid: f3faaa74-147f-4376-ac42-eff0c3779f6f`; `geometryType: POLYGON`, `MULTI_POLYGON` | **Custom-map geo roles exist in production.** The construct mapping calls this out as V3 and settles it as a declared loss (rule X8 forbids stashing a GUID) — correct call, now with live evidence. But no *schema ref* documents the two keys, so a round-trip pass-through has nothing to read them from. `geometryType` vocabulary observed: `POLYGON`, `MULTI_POLYGON`. |
| U7 | `model.columns[].properties.geo_config.country` (bool) | 5 | 5/143 | `{"country": true}` | A **fifth** geo-role shape. The Model ref documents `latitude`, `longitude` and `region_name` only. `country: true` (a bare boolean, *not* `region_name.country`, which is a string) is a distinct role and is undocumented. Full observed geo_config shape distribution: `region_name` ×88, `latitude` ×17, `longitude` ×17, `custom_file_guid`+`geometryType` ×7, `country` ×5. |
| U8 | `model.columns[].properties.value_casing` | 545 | 18/143 | `UNKNOWN` | Documented on **Table** columns only. Present on 545 Model columns (incl. 156 formula-backed ones) and 75 View columns. The Model and View column-property tables both need the row. |
| U9 | `view.view_columns[].properties.value_casing` | 75 | 10/42 | `UNKNOWN` | Same gap, View ref. |
| U10 | `table.columns[].properties.format_pattern` | 37 | 13/275 | `MM/dd/yyyy`, `yyyy-MM-dd HH:mm:ss`, `#,###`, `dd MMM YYYY` | Documented on Model and SQL-View columns; **absent from the Table ref**. Present on 13 Tables. |
| U11 | `view.view_columns[].properties.format_pattern` | 13 | 11/42 | `MMM yyyy`, `yyyyMMdd HH':'mm':'ss`, `q yyyy` | Same gap, View ref. Note the quoted-literal date form `HH':'mm':'ss`. |
| U12 | `table.columns[].properties.is_hidden` | 11 | 4/275 | `true` | Documented on Model / SQL-View / View columns; absent from the Table ref. |
| U13 | `view.view_columns[].properties.currency_type` + `.iso_code` | 5 each | 5/42 | `{"iso_code": "USD"}`, `{"iso_code": "JPY"}` | Absent from the View ref's column-property table. |
| U14 | `table.columns[].properties.currency_type` + `.column` | 1 each | 1/275 | `{"column": "TARGET_CURRENCY"}` | `currency_type` is absent from the Table ref entirely — **and** this is the only live sighting anywhere of the `column` form (see V2, §4.2). |
| U15 | `table.columns[].properties.calendar` | 1 | 1/275 | `SeanTSCROOTS` (`FACT_RETAPP_SALES`, col `RECORDDATE`) | `calendar` is documented on Model and SQL-View columns; the Table ref has no row, and V1 explicitly lists "whether `calendar:` is honoured on a **Table** column" as open. **It is** — see §4.2. |
| U16 | `view.formulas[].was_auto_generated` | 46 | **19/42** | `false` | Documented on Model `formulas[]`; absent from the View ref. Present on **46 of 46** View formulas — i.e. always emitted when a View has formulas at all. |
| U17 | `table.dataset_id` | 4 | 4/275 | `28ede9b627ab`, `f147b3fb21c9`, `8e65de074be7`, `35ba9408140f` (`cbre_fact_revenue`, `doordash_report_by_data_usage`, `silvia___test_1`, `gerdau_procurement`) | A root-level Table key we have never documented. 12-hex-char id, appears on uploaded/derived tables. Looks instance-local (identity-like) — likely an `NM1`-class value a portable document must **not** carry, which is exactly why it needs documenting. |
| U18 | `view.joins[].id` | 1 | 1/42 | `Daily Row Count - Table Info` (equal to the sibling `name`) | The View ref documents `joins[].name` but not `joins[].id`. Observed together, same value. |

#### 3.1.3 Aggregation vocabulary observed on Views that no reference lists

Not a missing *path* (the path `view.view_columns[].properties.aggregation` is documented)
but a **value vocabulary** far wider than any of our references admits, so it belongs in
this bucket as an undocumented construct:

| Value | Occ | Where |
|---|--:|---|
| `MOVING_SUM` | 2 | `Growth View` col `prev_year`; `GA - Moving Sum Test` col `Test formula` |
| `RANK` | 1 | `Rank Sales, Quota` col `Rank Sales` |
| `SQL_INT_AGGREGATE_OP` | 1 | `% of Total Test` col `Rank` |

Our documented set is the nine values `SUM COUNT AVERAGE MIN MAX COUNT_DISTINCT NONE
STD_DEVIATION VARIANCE`. `MOVING_SUM`, `RANK` and `SQL_INT_AGGREGATE_OP` are none of
those. This matters directly for the OSI metric-level `aggregation` enum, which is
declared closed at those nine values — a real View would fail payload validation.

---

### 3.2 SCHEMA-DOCUMENTED-BUT-UNMAPPED

Paths present in a schema ref but not named as a mapped/stashed construct in
`docs/ossie/ts-osi-construct-mapping.md` (main). Most are structural container keys the
mapping addresses implicitly; two are substantive.

| Path | Occ | Docs | Verdict |
|---|--:|--:|---|
| `view.search_query` | 42 | 42/42 | **Substantive.** Every View has one, and it is the View's *semantics* — the aggregation and filtering live in the search string, not in `view_columns`. The construct mapping's NM6 rejects `view:` documents outright, so there is no mapping row; that is a defensible scope call, but the mapping should say so with the same explicitness it gives `worksheet:`. Example: `"[TS: External Table Info_1::connection_id] … sum [TS: Daily Row Count_1::row_count] [… ::is_cached] = false [… ::date].daily"` |
| `model.columns[].data_panel_column_groups.{*}` | 9 | 3/143 | **Substantive-ish.** The *key* is a user-chosen folder name and the value is always `''`. The mapping stashes `data_panel_column_groups` wholesale, which is correct; the wildcard level is called out here only so a reader knows the map keys are free-form, not enumerable. Observed: `{"Location": ""}`, `{"KPIs": ""}`. |
| `model` / `table` / `sql_view` / `view` (root keys) | 143/275/40/42 | all | Container — the mapping names the documents, not the root keys. No action. |
| `model.model_tables[].joins` | 193 | 110/143 | Container for the relationship level. No action. |
| `table.rls_rules.tables` | 2 | 2/275 | Under NM2 (RLS deliberately not carried). No action. |
| `view.tables`, `view.view_columns`, `view.joins`, `view.joins[].source`, `view.table_paths[].join_path`, `.join`, `.join[]` | 1–42 | — | All under NM6 (`view:` rejected). No action beyond the NM6 note above. |

---

### 3.3 DOCUMENTED (168 paths)

168 of the 207 observed paths are correctly described in a schema ref and named in the
construct mapping. Full rows are in
`…/scratchpad/tml-census/documented-rows.md` and `inventory.md`. The high-traffic ones,
with observed value vocabularies, confirm our references are right where it counts:

| Path | Occ | Docs | Observed vocabulary / examples |
|---|--:|--:|---|
| `model.columns[].properties.column_type` | 4,985 | 143/143 | `ATTRIBUTE` 3,183 · `MEASURE` 1,802 |
| `model.columns[].column_id` | 4,436 | 143/143 | `dim_retapp_products::productname` — `TABLE::col` form holds universally |
| `model.columns[].formula_id` | 549 | — | `formula_Date` — `formula_` + name convention holds universally |
| `model.columns[].properties.index_type` | 3,629 | — | `DONT_INDEX` 3,598 · `PREFIX_AND_SUBSTRING` 23 · `PREFIX_ONLY` 8 |
| `model.columns[].properties.synonyms[]` | 2,812 | — | lists of strings, always under `properties:` — invariant holds |
| `model.columns[].properties.synonym_type` | 2,485 | — | `USER_DEFINED` 1,496 · `AUTO_GENERATED` 989 |
| `model.columns[].properties.aggregation` | 1,806 | — | `SUM` 1,605 · `AVERAGE` 178 · `COUNT` 21 · `COUNT_DISTINCT` 1 · `MIN` 1 |
| `model.properties.is_bypass_rls` | 143 | 143/143 | `false` ×143 — always emitted |
| `model.properties.join_progressive` | 143 | 143/143 | `true` ×142 · `false` ×1 |
| `model.properties.spotter_config.is_spotter_enabled` | 143 | 143/143 | `true` ×128 · `false` ×15 |
| `table.columns[].db_column_name` | 2,719 | 275/275 | present on **every** column of **every** table — R1 confirmed empirically |
| `table.columns[].db_column_properties.data_type` | 2,719 | 275/275 | `INT64`, `VARCHAR`, `DOUBLE`, `DATE`, … — always present |
| `table.connection.name` | 273 | 273/275 | `name` is the **only** key ever seen in a connection block — the "never `fqn:` in a connection block" invariant holds in 313/313 connection blocks (273 tables + 40 SQL views) |
| `model.columns[].properties.ai_context` | 656 | 16/143 | long business-meaning prose, as documented |

---

### 3.4 DOCUMENTED-NEVER-OBSERVED (128 paths)

**A usage note, not a defect.** Grouped by what the absence tells us. `fqn`/`obj_id`
absences are excluded from interpretation — this census exported without those options.

| Group | Paths | Reading |
|---|---|---|
| `model.constraints.*` (10 paths) | rolling date-window constraints | **Zero** occurrences in 143 models. Verified not a false negative: the only document containing the substring `constraints` has it inside an `ai_context` sentence ("network capacity constraints"). Genuinely unused on this cluster. |
| `model.aggregated_models.*` (7 paths) | aggregate-model routing | **Zero** in 143 models. NM5 is defending an unexercised construct. |
| `model.joins_with.*` (8 paths) | model-level data-augmentation joins | **Zero**. |
| `model.filters[].apply_on_tables`, `.display_name`, `.is_single_value` | filter refinements | Only 5 models have `filters` at all, and all 5 use the bare `{column, oper, values}` form. e.g. `[{"column":["Event Category"],"oper":"in","values":["content"]}]` |
| `model.columns[].properties.default_date_bucket` | default date grain | **Zero** in 143 models — despite being one of the properties the OSI field level leans on for `dimension.is_time`. |
| `model.columns[].properties.currency_type.column` / `.is_browser` | non-`iso_code` currency forms | **Zero on Model columns.** All 81 Model sightings and all 5 View sightings are `iso_code`. The `column` form exists but only on a **Table** column (U14). `is_browser` never seen anywhere. |
| `model.formulas[].was_auto_generated` | AI-generated formula flag | **Zero on Models** (0/555 formula entries) — yet **46/46 on Views**. Asymmetric emission worth recording. |
| `model.model_tables[].id` | table alias id | Zero. Observed `model_tables[]` keys are only `name` (599), `joins` (193), `alias` (31). The ref's advice ("omitting `id` is simpler") matches what the product does. |
| `table.joins_with[].cardinality` | join cardinality | **Zero in 165 table joins.** The Table ref marks it **Required: Yes**. It is never present on export. See §4.3 — this is a schema-ref accuracy problem, not just an absence. |
| `table.joins_with[].is_one_to_one`, `table.columns[].properties.synonym_type` | | Zero. |
| `sql_view.formulas.*` (5), `sql_view.joins_with.*` (8) | | **Zero in 40 SQL Views.** Every SQL View in the sample is minimal: root keys are only `name`/`connection`/`sql_query`/`sql_view_columns` (+`description` ×4), and columns carry only `name`/`sql_output_column`/`properties` (+`description` ×18). |
| `sql_view.sql_view_columns[].data_type` | | Zero — ThoughtSpot infers it from the query, as the ref says it may. |
| `sql_view.sql_view_columns[].properties.*` — 12 of 15 documented properties | `synonyms`, `index_priority`, `is_hidden`, `is_additive`, `is_attribution_dimension`, `calendar`, `format_pattern`, `currency_type`, `geo_config`, `spotiq_preference` | **Zero.** Only `column_type` (385), `index_type` (288) and `aggregation` (137) are ever emitted. The SQL-View property table is largely aspirational — likely transcribed from the Model ref rather than observed. |
| `view.filters.*` (7), `view.view_columns[].column_id`, `.description`, `.phrase`, `.properties.synonyms/index_priority/is_hidden/is_additive/default_date_bucket` | | **Zero in 42 Views.** Combined with U1, the View reference describes a column shape the product does not emit. |
| `view.joins[].on`, `.type`, `.is_one_to_one`; `view.tables[].fqn`; `view.joins_with[].description`, `.is_one_to_one`; `view.formulas[].properties.data_type`, `.aggregation` | | Zero. Only 1 of 42 Views has `joins`/`table_paths` at all, and that one join carries only `id`/`name`/`source`/`destination`. |
| `model.lesson_plans[]` (as a *list-of-scalars* path) | | Artefact of the path notation only — `lesson_plans` **is** observed (§4.3). |

---

## 4. Special-attention answers

### 4.1 Do formula-backed `columns[]` entries carry `description` / `data_type` / other type fields?

**`description`: YES — decisively. `data_type`: NO — never, in any form.**

| Observation | Count |
|---|---|
| Formula-backed `columns[]` entries in the sample | 549 |
| …carrying `description` | **63** |
| Physical `columns[]` entries | 4,436 |
| …carrying `description` | **1,960** |
| Models with at least one column `description` | **72 / 143** |
| Model `columns[]` with a bare `data_type` | **0** |
| Model `columns[]` with `properties.data_type` | **0** |

Full key sets observed:

```
formula-backed columns[]:  name (549), formula_id (549), properties (549), description (63)
physical      columns[]:  name (4436), column_id (4436), properties (4436),
                          description (1960), data_panel_column_groups (9)
model formulas[] entries:  id (555), name (555), expr (555), properties (10)
model formulas[].properties: column_type (10)   ← nothing else, ever
```

Live examples of a **formula** column carrying a description:

- `Liz (SE) Retail Apparel` → column `Date` (`formula_id: formula_Date`) →
  `"This is on daily grain, back 2 years rolling"`
- `P2 Retail Sales_13 month calendar` → `Average Ticket Size` →
  `"The average sales price by pos transaction number"`
- `Assurant People Analytics Demo` → `Number of Employees` →
  `"This is the number of active employees who are currently employed"`

**Consequence — two construct-mapping fidelity verdicts are wrong.** The mapping states,
at the Field level: *"A formula-backed field has no documented description field on the
Model `columns[]`/`formulas[]` entry. Nothing in TML holds it, so per **X9** it cannot be
stashed either — `Ossie → TML` raises an issue"* → fidelity `lossy→issue (formula)`. And
at the Metric level: *"`description` | no documented description field on a Model
`columns[]`/`formulas[]` entry … per **X9** it cannot be stashed"* → `lossy→issue`.

Both rest on a premise the wild contradicts: `model.columns[].description` exists, is
honoured on formula-backed entries, and is the second-most-common optional column key on
the cluster. `description` should be **`lossless` for physical *and* formula-backed
fields, and `lossless` for metrics**, and the X9 argument does not apply.

Conversely the mapping's `datatype` verdict — *"A formula-backed field has no declared
type in Model TML, so it is omitted `TML → Ossie` and raises an issue `Ossie → TML`"* —
is **confirmed exactly**: zero Model columns carry a type in any form.

Formula-column `properties` keys observed, for completeness (all 549 entries): `column_type`
549, `index_type` 423, `aggregation` 362, `synonyms` 272, `synonym_type` 207,
`value_casing` 156, `ai_context` 90, `search_iq_preferred` 36, `format_pattern` 30,
`currency_type` 29, `spotiq_preference` 11, `calendar` **5**, `index_priority` 3,
`custom_order` 2, `geo_config` 2, `is_hidden` 2. Note `calendar` and `geo_config` on
*formula* columns — neither reference contemplates that.

### 4.2 `calendar:` on columns — and with what values? (settles **V1**)

**Observed on Model columns (72 sightings, 36 models) and on a Table column (1). Never on
SQL View or View columns. `CALENDAR_TYPE_GREGORIAN` does not occur anywhere in 500
documents.**

| Value | Occurrences | Distinct docs | Interpretation |
|---|--:|--:|---|
| `calendar` (the literal string) | 70 | 34 models | The **default** spelling. Appears across 34 mutually-unrelated models (`TST_*`, `PUB_*`, `VER_*`, `DAI_*`, `WEL_*`, plus `Retail Sales - RLS`, `Transaction History`, `Inventory Planning`, `Care Provider`, `Mobile Network Analysis`, `Employee Recognition`), almost always on a column named `Full Date` or `Month Start Date`. |
| `SeanTSCROOTS` | 1 (model) + 1 (table) | `454 Cal Test (Sean)` col `Transaction Date`; `FACT_RETAPP_SALES` col `RECORDDATE` | A real custom-calendar **object name**. |
| `Dupont_Fiscal_Cal` | 1 | `Test Custom Calendars` col `Eff Start Date` | A real custom-calendar **object name**. |
| `CALENDAR_TYPE_GREGORIAN` | **0** | — | Not emitted by this build, on any document type. |
| `default` | **0** | — | Not emitted either. |

**V1 verdict:**

1. **The vocabulary is a calendar *name*.** ThoughtSpot's public TML docs
   (`[ default | calendar_name ]`) are closer to right than our own
   `thoughtspot-sql-view-tml.md`, which records `CALENDAR_TYPE_GREGORIAN`. That literal
   should be treated as **unverified / probably wrong** — 500 documents, zero sightings,
   including zero on the SQL Views where our ref claims it.
2. **The default spelling is the literal `calendar`, not `default`.** Neither our refs nor
   the TML docs say this.
3. **`calendar:` *is* honoured on a Table column** — `FACT_RETAPP_SALES.RECORDDATE:
   SeanTSCROOTS`. That half of V1 is answered YES.
4. Still open: whether `calendar` (the literal) is a genuine default sentinel or a
   customer calendar coincidentally named "calendar". The 34-model spread across unrelated
   tenants strongly favours *default sentinel*, but confirming it needs a
   `GET /api/rest/2.0/calendars/…` read, which is outside this census's scope.

The construct mapping's decision — *"a converter must not emit this property until they
are [reconciled]"* — is now resolvable in favour of the name form, with the literal
`calendar` as the do-nothing default.

### 4.3 `lesson_plans`? (settles the "provisional shape" caveat)

**Confirmed live in 8 / 143 models, with exactly the documented shape.**

```json
[{"lesson_id": 0,
  "lesson_plan_string": "What were [Sales] by [Store Region] in [Date].'last year' ?"},
 {"lesson_id": 1,
  "lesson_plan_string": "What were your [top] [Sales] per [Brand] in [Date].'last 2 years' ?"}]
```

Models: `Copy of Retail Sales - KM`, `(Sample) Retail - Apparel - LH`,
`(Sample) Retail - Apparel - JDUB`, `(Sample) Retail - Apparel - jhegele`, +4.

`lesson_id` is a 0-based integer; `lesson_plan_string` is a ThoughtSpot search string with
`[column]` tokens and `.'last year'` date modifiers. It is a **sibling of `properties:`**,
confirming the ref. `thoughtspot-model-tml.md` can drop its "**not live-verified here**,
so treat the shape as provisional" hedge, and the mapping's `lesson_plans` stash key is
correct as written.

### 4.4 Join `type` vocabulary actually observed — `OUTER` vs `FULL_OUTER`

**`FULL_OUTER` does not appear anywhere in 500 documents — not even at Table level, where
our Table ref says it is valid.**

| Surface | `type` values observed |
|---|---|
| Model `model_tables[].joins[]` (inline, n=233) | `LEFT_OUTER` 198 · `INNER` 37 · `OUTER` 3 · `RIGHT_OUTER` 3 |
| Table `joins_with[]` (n=165) | `INNER` 161 · `RIGHT_OUTER` 2 · `LEFT_OUTER` 1 · `OUTER` 1 |
| View `joins[]` (n=1) | *absent* |
| SQL View `joins_with[]` (n=0) | — |

The Model ref's rule — *"`FULL_OUTER` is **not valid** in model TML inline joins … use
`OUTER`"* — is **confirmed** (`OUTER` observed ×3, `FULL_OUTER` ×0). At snapshot time the
Table and SQL-View refs both listed `FULL_OUTER` as a legal `type` and omitted `OUTER`;
165 real table joins never use `FULL_OUTER`. **The concurrent branch has since corrected
both refs** to the single four-value vocabulary `INNER | LEFT_OUTER | RIGHT_OUTER | OUTER`,
backed by a live import probe (error 14528 on the Table context). This census's
export-side evidence is independent and agrees: **zero `FULL_OUTER` in 500 documents, in
any context.** No further action.

Cardinality:

| Surface | `cardinality` values |
|---|---|
| Model inline joins (n=233) | `MANY_TO_ONE` 223 · `ONE_TO_MANY` 11 · `ONE_TO_ONE` 3 (`MANY_TO_MANY` never) |
| Table `joins_with[]` (n=165) | **absent in all 165** |

**Finding — `table.joins_with[].cardinality` is documented Required but never emitted.**
`thoughtspot-table-tml.md` marks it `Required: Yes`. Zero of 165 real table joins carry
it. Either it is required on *import* but dropped on *export* (most likely), or the
requirement is wrong. Either way the ref should say which, because a round-trip that
re-imports an exported Table TML verbatim would be submitting a document our own ref
calls invalid.

**Finding — the `joins[]` "either/or" framing is too strict.** The Model ref says each
`joins[]` entry is *"either a **referencing join** (`with` + `referencing_join`) or an
**inline join** (`with` + `on` + `type` + `cardinality`)"*. Observed key-set distribution
across 493 model joins:

| Key set | Count | |
|---|--:|---|
| `with` + `referencing_join` | 248 | pure Scenario A |
| `with` + `on` + `type` + `cardinality` | 233 | pure Scenario B |
| `with` + `referencing_join` + `type` | **8** | **mixed** |
| `with` + `referencing_join` + `cardinality` | **4** | **mixed** |

12 real joins are hybrids — a `referencing_join` *plus* an inline attribute. Examples:
`Copy of Retail Sales - KM` / `Retail Sales` / `Rank demo Retail Sales` →
`{"with":"Dim_Promotion","referencing_join":"Promotion_Key - Promotion_Key","type":"LEFT_OUTER"}`;
`Demo Bank Deposits` (×4) →
`{"with":"CUST_PROFILING_ALL","referencing_join":"KP_DEPOSIT_MONTHLY_AGRMNT_PRTY_OW_to_CUST_PROFILING_ALL","cardinality":"MANY_TO_ONE"}`.
A parser that branches strictly on "has `referencing_join` ⇒ ignore `type`/`cardinality`"
silently drops a join attribute on 12/493 joins. The OSI relationship-level stash
(`join_shape` as a closed `referencing | inline` enum) has the same blind spot.

**Non-equality joins: zero observed.** No model inline join contains `>=`, `<=`, `>` or
`<` in its `on` expression. The range/ASOF join support the Model ref documents, and the
`residual_predicates` / `unrepresentable_joins` machinery the construct mapping designs
for it, are correct but **entirely unexercised on this cluster** — no live evidence either
way.

### 4.5 `parameters` / `list_config` shapes

**21 / 143 models carry parameters (63 parameters total). Both documented invariants hold.**

| Key | Occurrences (of 63) |
|---|--:|
| `id`, `name`, `data_type`, `default_value` | 63 (always) |
| `description` | 57 |
| `list_config` | 23 |
| `range_config` | 7 |

- `data_type` vocabulary observed: `CHAR` 24 · `DOUBLE` 15 · `DATE` 14 · `INT64` 10.
  **`BOOL` never observed** (the ref's boolean-list example is unverified). **`VARCHAR`
  never observed** — consistent with the ref's warning that `CHAR` is the correct spelling
  for string list parameters (I10 holds).
- `list_choice[]` items: **79/79 are objects** — zero bare strings. Invariant I10 confirmed.
- Within those objects: `value` 79/79 (always), `display_name` 51/79 — so `display_name`
  is genuinely optional, as documented. Live example of the `value`-only form:
  `Hiro - Salesforce` → `{"name":"bucket","data_type":"CHAR","default_value":"weekly",
  "list_config":{"list_choice":[{"value":"weekly"},{"value":"monthly"}]}}`.
- `range_config` always carries all four keys together: `range_min`, `range_max`,
  `include_min`, `include_max` (7/7).
- `list_config` and `range_config` never co-occur — the mutual exclusion holds.

Full example: `P2 Retail Sales_13 month calendar` →
`{"id":"a09a89e5-…","name":"Date Granularity","data_type":"CHAR","default_value":"monthly",
"list_config":{"list_choice":[{"value":"weekly","display_name":"Weekly"},
{"value":"monthly","display_name":"Monthly"},…]}}`.

### 4.6 Anything under `properties.*` we have never seen?

Yes — five things, all covered above, plus two value-level surprises:

1. `value_casing` on Model and View columns (U8, U9) — 545 + 75 sightings.
2. `format_pattern` on Table and View columns (U10, U11).
3. `is_hidden` on Table columns (U12).
4. `currency_type` on Table and View columns (U13, U14).
5. `calendar` on Table columns (U15) and on **formula** columns (5 sightings).
6. `geo_config.country: true` and `geo_config.custom_file_guid`/`geometryType` (U6, U7).
7. **`index_priority` is emitted as a non-integral number**: every one of the 20 sightings
   is `10.0`, `9.0`, `8.0`, `7.0`, `2.0` — confirmed in the raw `edoc` payload, not an
   artefact of our JSON parsing (`"index_priority":10.0` appears verbatim in the edoc
   string returned for `Liz (SE) Retail Apparel`). Our refs and the OSI payload schema
   both declare it `integer`. A strict integer validator rejects real ThoughtSpot output.

Also worth recording: **`is_mandatory_token_filter` was never observed** (0/500). The
construct mapping stashes it because it *fails open*, which remains the right call, but V4
("that it survives a TML round trip at all") is **not** settled by this census — no
sampled object uses it.

And: **2 of 275 Tables have no `connection` block at all** — `MetricsMonitoring`
(`db: thoughtspot_internal_stats`) and `sav_dim_unit` (`db: falcon_default_schema`), both
Falcon/in-memory tables. The Table ref marks `table.connection.name` **Required: Yes**.
A converter that assumes a connection block exists will crash on these.

---

## 5. Recommended follow-ups

### 5.1 Schema-reference rows to add or correct

Ordered by blast radius. All are `agents/shared/schemas/` edits.

| # | File | Change | Severity |
|---|---|---|:-:|
| S1 | `thoughtspot-view-tml.md` | **Replace `view_columns[].column_id` with `search_output_column`** as the documented column-reference field (42/42 Views, 265/265 columns). Keep `column_id` only if a live counter-example is found; otherwise remove it and the `<table_path_id>::<column_name>` prose, which no observed View uses. This also invalidates the file's "Dependency Management Notes" and "Self-validation Checklist", both of which key off `column_id`. | **HIGH** |
| S2 | `thoughtspot-model-tml.md` | Add a **`columns[].description`** row (2,023 occ / 72 of 143 models; valid on formula-backed entries). — **ALREADY DONE on the concurrent branch.** Only outstanding action: update its cited evidence from "14 of 78 formula-backed columns across a 40-model sample" to this census's **63 of 549 across 143 models** (same conclusion, 7× the evidence). | ~~HIGH~~ done |
| S3 | `thoughtspot-table-tml.md` | Fix `rls_rules.table_paths[].column` — it is a **list of bare column names** (`["COUNTRY"]`), not the string `"[COL_NAME]"` the ref shows. | **HIGH** |
| S4 | `thoughtspot-view-tml.md`, `thoughtspot-sql-view-tml.md` | Fix `geo_config.region_name` — observed as a **dict** on Views (matching the Model ref), not the list both files document. | MED |
| S5 | `thoughtspot-table-tml.md` | Note that `joins_with[].cardinality`, marked Required, is **absent from 165/165 exported joins** — state whether it is import-required/export-dropped. | MED |
| S6 | `thoughtspot-model-tml.md` | Loosen the `joins[]` "either A or B" framing: 12/493 real joins carry `referencing_join` **plus** `type` or `cardinality`. Parsers must read inline attributes even when `referencing_join` is present. | MED |
| S7 | `thoughtspot-model-tml.md` | Add `columns[].properties.value_casing` (545 occ) and note `calendar` + `geo_config` occur on **formula-backed** columns too. | MED |
| S8 | `thoughtspot-table-tml.md` | Add `columns[].properties.format_pattern` (37), `.is_hidden` (11), `.currency_type` (1, `column` form), `.calendar` (1). | MED |
| S9 | `thoughtspot-view-tml.md` | Add `view_columns[].properties.value_casing` (75), `.format_pattern` (13), `.currency_type.iso_code` (5); add `formulas[].was_auto_generated` (46/46); add `joins[].id`. | MED |
| S10 | `thoughtspot-model-tml.md` | New section: **`action_object_associations[]`** — `{action_name, context: CONTEXT_MENU, enabled}`. Wholly undocumented model-level construct. | MED |
| S11 | `thoughtspot-model-tml.md` | Extend `geo_config` with the `country: true` boolean role and the `custom_file_guid` + `geometryType` (`POLYGON` \| `MULTI_POLYGON`) custom-map form. | MED |
| S12 | `thoughtspot-model-tml.md` + `thoughtspot-sql-view-tml.md` | **Rewrite the `calendar` value vocabulary per §4.2**: the value is a calendar **name**; the default spelling is the literal `calendar`; **`CALENDAR_TYPE_GREGORIAN` was not observed once in 500 documents** and should be marked unverified/withdrawn in the SQL-View ref. Add that `calendar` is honoured on **Table** columns. | MED |
| S13 | `thoughtspot-view-tml.md` | Widen the View `aggregation` vocabulary: `MOVING_SUM`, `RANK`, `SQL_INT_AGGREGATE_OP` observed beyond the documented nine. | MED |
| S14 | `thoughtspot-table-tml.md` | Document `dataset_id` (4 occ) as an export-only, instance-local root key that must not be carried into a portable document. | LOW |
| S15 | `thoughtspot-table-tml.md` | Note that Falcon / `thoughtspot_internal_stats` tables have **no `connection` block**, so `connection.name` is not universally present despite being Required for warehouse-backed tables. | LOW |
| S16 | `thoughtspot-model-tml.md` | Drop the "not live-verified … provisional" hedge on `lesson_plans`. — **ALREADY DONE on the concurrent branch** (cites 4 Models). Census raises the count to **8 of 143**. | ~~LOW~~ done |
| S17 | `thoughtspot-sql-view-tml.md` | Mark the 12 never-observed `sql_view_columns[].properties.*` rows as unverified; 40/40 real SQL Views emit only `column_type`, `index_type`, `aggregation`. | LOW |
| S18 | all four refs | Record `index_priority` as a **number, emitted non-integrally** (`10.0`), not an integer. | LOW |

### 5.2 Construct-mapping rows to add or correct

`docs/ossie/ts-osi-construct-mapping.md` — coordinate with whoever owns the branch.

| # | Change | Severity |
|---|---|:-:|
| M1 | **Field level, `description` row:** change `lossless (physical) / lossy→issue (formula)` → **`lossless`**. The X9 argument is factually wrong: `model.columns[].description` exists and is honoured on formula-backed entries. — **ALREADY DONE on the concurrent branch.** Outstanding: upgrade the cited evidence to 63/549 across 143 models. | ~~HIGH~~ done |
| M2 | **Metric level, `description` row:** change `lossy→issue` → **`lossless`**; remove the `MetricLevel` note saying "No key exists here for `description`". — **ALREADY DONE on the concurrent branch.** | ~~HIGH~~ done |
| M3 | **Metric level `aggregation` enum** (and `MetricLevel.column_properties.aggregation` in the payload schema): the closed nine-value enum rejects real ThoughtSpot output. Add `MOVING_SUM`, `RANK`, `SQL_INT_AGGREGATE_OP`, or scope the enum to Model columns and handle View columns separately. | **HIGH** |
| M4 | **`V1` — advance it past the concurrent branch's own note.** That branch records "*in every case the value was the bare lowercase token `calendar`*" and "*no `calendar:` value was observed on a **Table** column*". **This census observes both of the things it says it did not:** two real *named* calendars on Model columns (`SeanTSCROOTS` on `454 Cal Test (Sean)`, `Dupont_Fiscal_Cal` on `Test Custom Calendars`) **and** a `calendar:` on a **Table** column (`FACT_RETAPP_SALES.RECORDDATE: SeanTSCROOTS`). That confirms the `calendar_name` reading directly and answers the Table-column half of V1 YES. | **MED — new evidence** |
| M5 | **`V2` — partially resolve.** `currency_type.column` observed live **once**, on a Table column, with a **bare column name** (`TARGET_CURRENCY`) — *not* a `TABLE::Column` reference. `is_browser` still unobserved. | MED |
| M6 | **`V3` — add live evidence.** Custom-map `geo_config` (`custom_file_guid` + `geometryType`) confirmed in 3 production models / 7 columns; `geometryType` vocabulary `POLYGON`, `MULTI_POLYGON`. The declared-loss-under-X8 verdict stands, now grounded. | LOW |
| M7 | **`V4` — record as still open.** `is_mandatory_token_filter` was observed **zero** times in 500 documents; the round-trip question is untested. | LOW |
| M8 | **`RelationshipLevel.join_shape`** is a closed `referencing \| inline` enum, but 12/493 real joins are hybrids (`referencing_join` + `type`/`cardinality`). Either widen it or make the stash carry both the shape and the inline attributes independently. | MED |
| M9 | **New field-level / model-level construct:** `action_object_associations[]`. Decide whether it is a presentation artifact (→ `NM3`-class) or a stashable model property, and say so explicitly rather than leaving it unmentioned. | MED |
| M10 | **`FieldLevel.column_properties`** — add `value_casing` for Model columns (documented today as a Table-only refinement, observed 545× on Model columns); add the `geo_config.country` boolean role. | MED |
| M11 | **`NM1` / `X8`** — add `table.dataset_id` to the identity-like keys that must never be carried. | LOW |
| M12 | **`NM6`** — note that `worksheet:` is no longer obtainable by export on a current Cloud build (2,394/2,397 `WORKSHEET` objects are V2 Models; the 3 V1 survivors are FORBIDDEN system objects). The rule stays, but its likelihood of firing is now near zero. | LOW |
| M13 | **`NM6` / View scope** — `view.search_query` carries the View's actual semantics (aggregation + filters). If `view:` stays out of scope, say so with the same explicitness given to `worksheet:`, because a reader may otherwise assume `view_columns[]` is sufficient. | LOW |

### 5.3 V-items settled by this census

| Item | Before | After this census |
|---|---|---|
| **V1** — `calendar` value vocabulary | Two candidate spellings (`default \| calendar_name` vs `CALENDAR_TYPE_GREGORIAN`), unreconciled; Table-column support unknown. The concurrent branch narrowed it to "only ever the bare token `calendar`, never on a Table column" | **SETTLED (mostly), beyond the branch's own position.** The value is a calendar **name** — two real named calendars observed (`SeanTSCROOTS`, `Dupont_Fiscal_Cal`), which the branch reports as not seen; the literal `calendar` is the default spelling (34 models / 70 columns); `CALENDAR_TYPE_GREGORIAN` and `default` are unobserved in 500 docs across all 4 types; **Table columns do carry it** (`FACT_RETAPP_SALES.RECORDDATE`), which the branch explicitly reports as not observed. Residual: whether the literal `calendar` is a sentinel or a coincidental name. |
| **V2** — `currency_type` `column` / `is_browser` forms | Only `iso_code` ever seen | **PARTIALLY SETTLED.** `column` form confirmed live (Table column, bare column name `TARGET_CURRENCY`, no `TABLE::` prefix). `is_browser` still zero sightings. Round-trip survival still untested. |
| **V3** — custom-map `geo_config` | Documented, listed as "nothing to verify" | **CONFIRMED PRESENT** in production (3 models, 7 columns); `geometryType` ∈ {`POLYGON`, `MULTI_POLYGON`}. Verdict unchanged (declared loss under X8), now evidence-backed. |
| **V4** — `is_mandatory_token_filter` round trip | Untested | **STILL OPEN** — zero sightings in 500 documents; census cannot speak to it. |
| `lesson_plans` "provisional shape" caveat | Documented from ThoughtSpot's TML reference, not live-verified | **VERIFIED** — 8 models, exact documented shape. |
| `FULL_OUTER` invalid in model inline joins | Asserted from an import error message | **CONFIRMED** — `OUTER` ×3, `FULL_OUTER` ×0 in 493 joins (and ×0 in 165 Table joins too). |
| I10 — `list_choice` entries must be objects, `CHAR` not `VARCHAR` | Asserted from an import failure | **CONFIRMED** — 79/79 objects, zero bare strings; `CHAR` ×24, `VARCHAR` ×0. |
| R1 — `db_column_name` on every table column | Asserted ("some instances reject import without it") | **CONFIRMED** — present on 2,719/2,719 columns across 275/275 Tables. |
| "never `fqn:` inside a connection block" | Hard invariant | **CONFIRMED** — `name` is the only key in all 313 observed connection blocks. |

### 5.4 Reconciliation with the concurrent branch work

Between the ground-truth snapshot (~12:57) and this write-up, the other agent landed
working-tree edits to `thoughtspot-model-tml.md`, `thoughtspot-table-tml.md`,
`thoughtspot-sql-view-tml.md` and `docs/ossie/ts-osi-construct-mapping.md`. Overlap:

| Census finding | Concurrent-branch status | Census's marginal contribution |
|---|---|---|
| U2 / S2 / M1 / M2 — `model.columns[].description` exists and works on formula-backed entries | **Already fixed.** Model ref has a `description` row; both mapping fidelity verdicts flipped to `lossless`; `MetricLevel` note rewritten | **Corroborates at 3.6× the sample.** Branch cites *14 of 78 formula-backed columns across 40 models*; census measures **63 of 549 across 143 models** (and 1,960 of 4,436 physical columns, 72/143 models). Also confirms the negative half exactly: **0 of 4,985 Model columns carry `data_type` in any form**, and `formulas[].properties` only ever holds `column_type` (10 of 555). |
| S16 — `lesson_plans` provisional hedge | **Already removed**, citing 4 Models | Raises the count to **8 of 143** and confirms `lesson_id` is 0-based |
| §4.4 — `FULL_OUTER` / `OUTER` vocabulary | **Already corrected** in all three refs + the `RelationshipLevel.type` payload enum, from a live *import* probe | Independent *export*-side confirmation: **0 `FULL_OUTER` in 500 documents**. Across **all 421 typed joins of every document type**: `INNER` 213 · `LEFT_OUTER` 199 · `RIGHT_OUTER` 5 · `OUTER` 4 — exactly the corrected four-value vocabulary and nothing else |
| M4 — V1 `calendar` vocabulary | Branch records **only** the bare token `calendar` (12 models) and states *"no `calendar:` value was observed on a **Table** column"* | **Contradicts that gap with live evidence.** Two *named* calendars on Model columns (`SeanTSCROOTS`, `Dupont_Fiscal_Cal`) **and** one on a **Table** column (`FACT_RETAPP_SALES.RECORDDATE`). Also widens the bare-token count to 34 models / 70 columns. V1's Table-column question is answered. |

**All other findings in §5.1 / §5.2 are untouched by that branch** — in particular the
HIGH-severity View `search_output_column` error (S1), the `rls_rules.table_paths[].column`
type error (S3), `action_object_associations` (S10/M9), the View aggregation vocabulary
(S13/M3), the 12 hybrid joins (S6/M8), and the never-emitted
`table.joins_with[].cardinality` (S5).

### 5.5 Non-schema follow-up

| # | Item |
|---|---|
| T1 | **Fix the `ts tml export --parse` crash** (§1.6): `detect_tml_type()` dereferences a `None` parse, so a single `FORBIDDEN` object aborts a whole batch. Needs a null guard in `tools/ts-cli/ts_cli/commands/tml.py` (`:258`, `:391`) plus a skip-and-report path for null `edoc`. Worth a unit test with a null-edoc fixture. |
| T2 | **Re-run this census with `--fqn --associated --include-obj-id`** to cover the `fqn` / `obj_id` / `destination.fqn` paths this run deliberately excluded — the NM1/X8 identity rules are the least evidenced part of the mapping. |
| T3 | **Re-run against a second cluster** before treating the View `search_output_column` finding (S1) as universal. 42 Views on one SE demo cluster is decisive for *this* build, but `column_id` may be a legacy or version-gated spelling. |
| T4 | Probe `GET /api/rest/2.0/calendars/*` on se-thoughtspot to close V1's residual question (is the literal `calendar` a sentinel, or a calendar object named "calendar"?). |
