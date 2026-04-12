# ThoughtSpot TML Parsing Reference

Known pitfalls when exporting and parsing ThoughtSpot TML via the REST API.
Applies to any skill that calls `/api/rest/2.0/metadata/tml/export`.

---

## Non-printable Characters

Some TML contains special characters (e.g. `#x0095`) that cause `yaml.safe_load` to
raise a `ReaderError`. Strip them before parsing every `edoc` string:

```python
import re, yaml

def parse_edoc(edoc: str):
    cleaned = re.sub(r'[^\x09\x0A\x0D\x20-\x7E\x85\xA0-\uD7FF\uE000-\uFFFD]', '', edoc)
    return yaml.safe_load(cleaned)
```

Apply this to **all** edoc strings, not just ones that look suspicious.

---

## `schema` Field Name in PyYAML

ThoughtSpot Table TML contains a top-level `schema` key inside the `table` object:
```yaml
table:
  name: DM_DATE_DIM
  db: DUNDERMIFFLIN
  schema: PUBLIC
  db_table: DM_DATE_DIM
```

After `yaml.safe_load`, this field is stored as `"schema"` — **not** `"schema_"`:
```python
tbl.get("schema")    # correct
tbl.get("schema_")   # wrong — always returns None
```

The underscore variant is a common mistake. If `schema` appears to be missing, always
print `tbl.keys()` to verify before concluding it is absent.

---

## Schema IS Exported by the API

The `/api/rest/2.0/metadata/tml/export` endpoint with `export_fqn: true` and
`export_associated: true` **does** include `schema` in every Table TML that has one
set in ThoughtSpot. Do **not** prompt the user for the schema value unless:
- The `schema` key is genuinely absent from the parsed dict, **and**
- You have printed `tbl.keys()` to confirm it is not just a parsing artefact.

---

## Debugging Parsed TML Structure

When inspecting any parsed TML object, emit all keys before filtering:
```python
print(f"Table keys: {list(tbl.keys())}")
```
This prevents silent misses caused by field name assumptions.

---

## TML Object Types

After export, separate parsed objects by top-level key:

| Top-level key | Type |
|---|---|
| `worksheet` | Worksheet (columns in `worksheet_columns[]`) |
| `model` | Model (columns in `model.columns[]`, tables in `model_tables[]`) |
| `table` | Physical table definition — provides `db`, `schema`, `db_table`, `columns[]` |

`metadata_detail` in the search response is frequently `null` — do not rely on it to
distinguish Worksheets from Models. The actual type is only known after TML export.
