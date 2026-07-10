---
name: ts-convert-from-databricks-mv
description: Convert a Databricks Metric View into ThoughtSpot Table and Model TML. Genie Code runtime — runs the same parse/translate/build/lint pipeline as the CLI skill via the vendored databricks_mv_lib notebook (%run), plus ThoughtSpotClient via %run instead of the ts CLI for import.
---

# Databricks Metric View → ThoughtSpot (Genie Code)

Convert a Databricks Metric View into ThoughtSpot Table and Model TML.

This is the Genie Code version of the CLI skill at `agents/cli/ts-convert-from-databricks-mv/`.
Both runtimes run the exact same parse → translate → build → lint pipeline — this skill
calls it via `%run ../../notebooks/databricks_mv_lib` (vendored from `tools/ts-cli/` at
deploy time) instead of the `ts databricks ...` CLI subcommands. Only the I/O layer
differs: Spark SQL against the live notebook session instead of the Databricks CLI for
reading the Metric View definition, and `ThoughtSpotClient` via `%run` instead of
`ts tml import` for the ThoughtSpot side.

---

## Setup

```python
%run ../../notebooks/ts_client
%run ../../notebooks/databricks_mv_lib
client = ThoughtSpotClient("my-profile")
```

`databricks_mv_lib` is vendored at deploy time from `tools/ts-cli/ts_cli/` — the
same parse/translate/build code the CLI skill runs via `ts databricks ...`. Do
not re-implement any conversion logic inline; if a function is wrong, fix it in
ts-cli and redeploy.

**Serverless compute note (live-verified 2026-07-11):** serverless base
environments do not include PyYAML, so either `%run` fails with
`ModuleNotFoundError: No module named 'yaml'`. Run this first, then the `%run`s:

```python
%pip install pyyaml requests --quiet
```

Classic DBR clusters ship both packages — no install needed there.

---

## References

All paths relative to the `.assistant/skills/` root:

| File | Purpose |
|---|---|
| `../shared/mappings/ts-databricks/ts-from-databricks-rules.md` | Column classification and type mapping rules |
| `../shared/mappings/ts-databricks/ts-databricks-formula-translation.md` | Formula translation rules |
| `../shared/schemas/thoughtspot-table-tml.md` | Table TML field reference |
| `../shared/schemas/thoughtspot-model-tml.md` | Model TML field reference |
| `../shared/schemas/ts-tml-import-gate.md` | Pre-import lint gate + import policy |

---

## Steps

### Step 1: Read the Metric View YAML

Mirrors the CLI skill's Step 4 (`DESCRIBE TABLE EXTENDED`, then extract the
`View Text` row) — but runs directly against the live Spark session instead of
shelling out to the Databricks CLI's Statement Execution API, since a Genie
notebook already has one:

```python
catalog, schema, view_name = "catalog", "schema", "my_metric_view"

rows = spark.sql(
    f"DESCRIBE TABLE EXTENDED {catalog}.{schema}.{view_name}"
).collect()
by_col = {r["col_name"]: r["data_type"] for r in rows}

assert by_col.get("Type") == "METRIC_VIEW", (
    f"{catalog}.{schema}.{view_name} is not a Metric View "
    f"(Type: {by_col.get('Type')})")
mv_yaml = by_col["View Text"]
```

If `DESCRIBE TABLE EXTENDED` doesn't return a `View Text` row (older DBR, or the
object isn't a Metric View), ask the user to paste the MV YAML directly and
assign it to `mv_yaml`.

### Step 2: Parse

```python
parsed = parse_metric_view(mv_yaml)
assert not parsed["unsupported"], parsed["unsupported"]
```

Any `unsupported[]` entry stops the conversion — report it to the user verbatim.

### Step 3: Build the tables map

One entry per source/join alias. `create: true` requires `db`, `schema`,
`db_table`, and `columns` (with `dbx_type`) so Table TML can be generated;
`create: false` means the table already exists in ThoughtSpot under `name`.

```python
tables = {
    "source": {"name": "SALES", "fqn": None, "create": False},
    # "products": {"name": "PRODUCTS", "create": True, "db": "agent_skills",
    #              "schema": "dunder_mifflin", "db_table": "products",
    #              "columns": [{"name": "PRODUCT_ID", "dbx_type": "bigint"}, ...]},
}
```

### Step 4: Translate

```python
translated_doc = translate_metric_view(parsed, tables)
for skip in translated_doc["skipped"]:
    print(f"SKIPPED {skip['role']} '{skip['name']}': {skip['reason']}")
```

### Step 5: Build TML

```python
model_doc, build_info = build_model_tml_dbx(
    model_name="My Model", parsed=parsed, translated_doc=translated_doc,
    tables=tables, mv_fqn="catalog.schema.my_metric_view",
    existing_guid=None)  # set to the model GUID to update in place

table_docs = []
for alias, info in tables.items():
    if isinstance(info, dict) and info.get("create"):
        doc, notes = build_table_tml(info, "MY_CONNECTION_NAME")
        table_docs.append(doc)
        for n in notes:
            print(n)
```

### Step 6: Lint gate (mandatory — see `../shared/schemas/ts-tml-import-gate.md`)

```python
findings = []
for doc in table_docs + [model_doc]:
    findings += validate_tml_invariants(doc) + lint_tml(doc)
assert not findings, findings
```

### Step 7: Import

Tables first, then the model (PARTIAL policy — see the import-gate reference
for why not ALL_OR_NONE). With PARTIAL, per-object failures arrive **in-band**
(HTTP 200, `response.status.status_code == "ERROR"`) — capture the table
import result and gate on it before proceeding to the model import, or a
failed table silently falls through and the model import fails on a missing
dependency with a much less obvious error:

```python
if table_docs:
    table_result = client.tml_import(
        [dump_tml_yaml(d) for d in table_docs], policy="PARTIAL", create_new=True)
    for r in table_result:
        status = r.get("response", {}).get("status", {})
        assert status.get("status_code") == "OK", status

result = client.tml_import([dump_tml_yaml(model_doc)], policy="PARTIAL",
                           create_new=model_doc.get("guid") is None)
model_guid = extract_imported_guid(result)
print(f"Model GUID: {model_guid}")  # save — required for update-in-place
```

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.1.0 | 2026-07-10 | Rewire onto the vendored `databricks_mv_lib` notebook (parse/translate/build/lint vendored from ts-cli v0.45.0) — replaces the hand-rolled "identical to the CLI skill" steps. Lint+import gate linked from the new shared `ts-tml-import-gate.md`. |
| 1.0.0 | 2026-06-15 | Initial release — Genie Code runtime |
