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
| `sql_view` | Virtual table defined by a SQL query — no `db`/`schema`/`db_table`; provides `sql_query` and `sql_view_columns[]` |

`metadata_detail` in the search response is frequently `null` — do not rely on it to
distinguish Worksheets from Models. The actual type is only known after TML export.

---

## SQL View Objects (`sql_view`)

A `sql_view` object represents a ThoughtSpot virtual table backed by a SQL query
rather than a physical table. It does **not** have `db`, `schema`, or `db_table`
fields. Key fields:

```python
sv = parsed['sql_view']
sv['name']              # logical name (e.g. "Account District")
sv['sql_query']         # Snowflake SQL string (e.g. "SELECT * FROM BIRD.\"financial\".\"district\"")
sv['sql_view_columns']  # list of {name, sql_output_column, properties} — no data_type
sv['connection']        # ThoughtSpot connection metadata (not needed for conversion)
```

**Column types are not in `sql_view_columns`.** If the view is a simple `SELECT *`
from a known physical table, borrow types from that table's TML `columns[]`. For
complex views, determine types by running `SHOW COLUMNS` against the Snowflake view
after creating it.

### Classifying sql_view complexity

Apply this regex to `sql_query` (case-insensitive, strip whitespace first):

```python
import re

SIMPLE_SELECT_STAR = re.compile(
    r'^\s*select\s+\*\s+from\s+[\w".]+(?:\s+(?:as\s+)?\w+)?\s*$',
    re.IGNORECASE
)

def classify_sql_view(sql_query: str) -> str:
    """Returns 'simple' or 'complex'."""
    q = sql_query.strip().rstrip(';')
    if SIMPLE_SELECT_STAR.match(q):
        return 'simple'
    return 'complex'
```

**Simple** — `SELECT * FROM [db.]schema.table [AS alias]` with nothing else:
- Extract the physical table FQN from the FROM clause
- Resolve `db`, `schema`, `db_table` from that FQN
- Treat the sql_view exactly like a regular `table` object going forward
- Borrow column types from the matching physical table TML

**Complex** — anything else (WHERE clauses, column lists, JOINs, aggregations,
subqueries, UNION, etc.):
- Cannot be safely auto-mapped to a physical table
- Requires user decision at the Step 10 checkpoint (see SKILL.md Step 5)

### Extracting physical table from a simple sql_view

```python
FQN_RE = re.compile(
    r'from\s+((?:"[^"]+"|[\w]+)(?:\.(?:"[^"]+"|[\w]+)){0,2})',
    re.IGNORECASE
)

def extract_fqn(sql_query: str):
    """Returns (db, schema, table) tuple or None."""
    m = FQN_RE.search(sql_query)
    if not m:
        return None
    parts = [p.strip('"') for p in m.group(1).split('.')]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    return None, None, parts[0]
```
