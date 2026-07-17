---
name: ts-convert-to-databricks-mv
description: Convert a ThoughtSpot Model into a Databricks Metric View. Genie Code runtime — runs the same detect-fact-table/build-metric-view/build-view-ddl pipeline as the CLI skill via the vendored databricks_mv_lib notebook (%run), plus ThoughtSpotClient via %run instead of the ts CLI for TML export. Model TML only — Worksheets are not supported by this deterministic path.
---

# ThoughtSpot → Databricks Metric View (Genie Code)

Convert a ThoughtSpot Model into a Databricks Metric View.

This is the Genie Code version of the CLI skill at `agents/cli/ts-convert-to-databricks-mv/`.
Both runtimes run the exact same detect-fact-table → build-metric-view → build-view-ddl
pipeline — this skill calls it via `%run ../../notebooks/databricks_mv_lib` (vendored from
`tools/ts-cli/` at deploy time) instead of the `ts databricks build-mv` CLI command. Only the
I/O layer differs: `ThoughtSpotClient` via `%run` instead of `ts tml export` for the
ThoughtSpot side, and `spark.sql` (or a printed/written `.sql` string) instead of a CLI-written
file for the Databricks side.

**Scope (same as the CLI skill):**
- **Model TML only.** A Worksheet cannot be routed through `build_metric_view` — it reads
  `model_tables[]`/`columns[]`, not a Worksheet's `worksheet_columns[]` shape.
- **No `sql_view` support.** A `sql_view` entry in the export must be excluded from `tables`
  before calling `build_metric_view`, or it fails on a missing `["table"]` key.

---

## Setup

```python
%run ../../notebooks/ts_client
%run ../../notebooks/databricks_mv_lib
client = ThoughtSpotClient("my-profile")
```

`databricks_mv_lib` is vendored at deploy time from `tools/ts-cli/ts_cli/` — the same
detect-fact-table/build-metric-view/build-view-ddl code the CLI skill runs via
`ts databricks build-mv`. Do not re-implement any conversion logic inline; if a function is
wrong, fix it in ts-cli and redeploy.

**Serverless compute note:** serverless base environments do not include PyYAML, so either
`%run` fails with `ModuleNotFoundError: No module named 'yaml'`. Run this first, then the
`%run`s:

```python
%pip install pyyaml requests --quiet
```

Classic DBR clusters ship both packages — no install needed there.

**Runtime requirement.** Metric Views are GA — no Preview channel needed. The
`display_name`/`comment`/`synonyms` metadata this pipeline always emits needs Databricks
Runtime **17.3+** on the warehouse/cluster that will run the generated DDL; a model with an
explicit `MANY_TO_ONE` join or a period-over-period window measure (prior month/quarter/year)
needs **18.1+** instead (join `cardinality:` / window `offset:`). See the tiered table in
[../shared/schemas/databricks-metric-view.md](../shared/schemas/databricks-metric-view.md).

---

## References

All paths relative to the `.assistant/skills/` root:

| File | Purpose |
|---|---|
| `../shared/mappings/ts-databricks/ts-to-databricks-rules.md` | Column classification, aggregation, data type rules — what `build_metric_view` implements |
| `../shared/mappings/ts-databricks/ts-databricks-formula-translation.md` | Formula translation rules |
| `../shared/mappings/ts-databricks/ts-databricks-properties.md` | Property coverage matrix, Unmapped Report format |
| `../shared/schemas/databricks-metric-view.md` | Metric View DDL syntax, YAML schema, tiered Runtime table |
| `../shared/schemas/thoughtspot-table-tml.md` | Table TML field reference |
| `../shared/schemas/thoughtspot-model-tml.md` | Model TML field reference |

---

## Steps

### Step 1: Search for the ThoughtSpot object

```python
models = client.metadata_search(type="LOGICAL_TABLE", name="%revenue%")
```

### Step 2: Export and unwrap the TML

```python
export = client.tml_export(["<model_guid>"], fqn=True, associated=True, parse=True)

model_entry = next((e for e in export if e["type"] == "model"), None)
if model_entry is None:
    raise ValueError(
        "no 'model' entry in the export — this GUID is a Worksheet, which "
        "build_metric_view does not support (it reads model_tables[]/columns[], not "
        "worksheet_columns[]). Convert/promote it to a Model in ThoughtSpot first, or "
        "treat this as a manual conversion outside this skill.")

model = model_entry["tml"]["model"]                             # unwrapped bare model dict
tables = [e["tml"] for e in export if e["type"] == "table"]      # list of {"table": {...}} — NOT unwrapped
```

`tml_export(..., parse=True)` returns one `{"type", "guid", "tml", "info"}` dict per object
(`agents/databricks/notebooks/ts_client.py`) — `type` is the TML top-level key (`"model"`,
`"table"`, `"worksheet"`, `"sql_view"`, ...). Note the asymmetry `build_metric_view` expects:
`model` is passed **unwrapped** (it reads `model["model_tables"]` directly), but each table
entry stays **wrapped** (it reads `t["table"]["name"]`, not `t["name"]`).

**Exclude any `sql_view` entries** from `tables` — `build_metric_view` has no `sql_view`
handling and will crash on a missing `["table"]` key if one is included. Unlike the CLI
skill's Step 4 sql_view classification prompt, there is no automated fallback here; log any
excluded `sql_view` to the user as a manual follow-up (its columns will be omitted from the
Metric View).

### Step 3: Build the Metric View(s)

```python
catalog, schema = "<catalog>", "<schema>"

mvs = []
for fact in detect_fact_tables(model):
    result = build_metric_view(model, tables, fact, catalog=catalog, schema=schema)
    view_name = default_view_name(model["name"], fact)
    ddl = build_view_ddl(result["yaml_doc"], catalog=catalog, schema=schema, view_name=view_name)
    mvs.append({**result, "view_name": view_name, "file": f"{view_name}.sql", "ddl": ddl})
```

**Catalog/schema and the `source:` FQN.** The `catalog`/`schema` passed here become the FQN
of the fact/source table in the emitted `source:` field — `build_metric_view` does not read
the fact table's own `db`/`schema` from Table TML for this purpose, even though joined
dimension tables do use their own TML `db`/`schema` for their `source:` entries. Default
`catalog`/`schema` to the fact table's own `db`/`schema` (from its Table TML) rather than the
first values that come to mind; overriding them changes where `source:` points, and passing a
`catalog`/`schema` that doesn't match the fact table's real location produces a `source:` FQN
for a table that doesn't exist there.

`detect_fact_tables` returns one fact table per independent Metric View — a multi-fact model
produces multiple entries in `mvs`, matching the CLI skill's "one MV per detected fact table"
behavior. To pin a single fact instead of auto-detecting, skip the loop and call
`build_metric_view(model, tables, "<fact_table_name>", catalog=catalog, schema=schema)` directly.

**Multi-catalog caveat:** the single `catalog`/`schema` pair set above applies to **every**
fact in a multi-fact loop — `build_metric_view` has no per-fact catalog/schema override. If
the model's fact tables genuinely live in different catalogs/schemas, call
`build_metric_view` once per fact (skip the loop) with that fact's own `catalog`/`schema`,
mirroring the CLI skill's Step 5 guidance.

**Unmapped Report — review before executing.** Each `result["skipped"]` / `result["warnings"]`
lists untranslatable formulas, dangling cross-references, and filter-classification
advisories. For a multi-fact model, aggregate them across all `mvs` with:

```python
import json

summary = build_summary(model.get("name", "model"), mvs)
print(json.dumps(summary, indent=2))   # summary["skipped"] / summary["warnings"] = the Unmapped Report
```

Present these to the user in the format defined in
[../shared/mappings/ts-databricks/ts-databricks-properties.md](../shared/mappings/ts-databricks/ts-databricks-properties.md)
before Step 4.

### Step 4: Review and execute

```python
for mv in mvs:
    print(mv["ddl"])        # review — this is the exact DDL that will run
```

After the user confirms:

```python
for mv in mvs:
    spark.sql(mv["ddl"])    # execute mode
```

For file-only mode (no Databricks access, or the user wants to defer execution), skip the
`spark.sql` loop — write `mv["ddl"]` to a `.sql` file, or leave the printed DDL from the
review step as the deliverable.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.0 | 2026-07-18 | Rewire Genie skill to call the vendored `build_metric_view`/`build_view_ddl` (deterministic emit) instead of agentic mapping. |
| 1.0.0 | 2026-06-15 | Initial release — Genie Code runtime |
