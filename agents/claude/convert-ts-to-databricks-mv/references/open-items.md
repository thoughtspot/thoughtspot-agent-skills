# Open Items — convert-ts-to-databricks-mv

Unverified Unity Catalog Metric View API behaviors. Each item has a test script that
can be run against a live Databricks instance to confirm the finding. Update the
**Finding** line when resolved.

---

## Item 1: Composed Measure Ordering

**Question:** Can `MEASURE(m)` reference a measure defined *later* in the YAML, or must
the referenced measure appear before the referencing measure?

**Risk:** High — if forward references fail, the YAML generation must emit measures in
dependency order.

**Finding:** *(unverified)*

**Test script:**

```python
from databricks import sql as dbsql
import os

conn = dbsql.connect(
    server_hostname=os.environ['DBX_HOSTNAME'],
    http_path=os.environ['DBX_HTTP_PATH'],
    access_token=os.environ['DBX_TOKEN']
)
cursor = conn.cursor()

# This YAML deliberately puts the composed measure BEFORE its dependencies
yaml_forward_ref = """
version: "1.1"
source: {catalog}.{schema}.{fact_table}
measures:
  - name: ratio
    expr: try_divide(MEASURE(total_a), MEASURE(total_b))
  - name: total_a
    expr: SUM({col_a})
  - name: total_b
    expr: SUM({col_b})
"""

try:
    cursor.execute(f"""
        CREATE OR REPLACE VIEW `{catalog}`.`{schema}`.`oi_forward_ref_test`
        WITH METRICS LANGUAGE YAML
        AS $${yaml_forward_ref}$$
    """)
    # Test query
    cursor.execute(f"SELECT MEASURE(ratio) FROM `{catalog}`.`{schema}`.`oi_forward_ref_test`")
    print("FORWARD REF: OK — MEASURE() can reference measures defined later")
except Exception as e:
    print(f"FORWARD REF FAILED: {e}")
    print("Conclusion: Must emit measures in dependency order")
finally:
    cursor.execute(f"DROP VIEW IF EXISTS `{catalog}`.`{schema}`.`oi_forward_ref_test`")
    conn.close()
```

**Skill impact:** If forward references fail, update Step 9 to topologically sort measures
so that composed measures are emitted after their dependencies.

---

## Item 2: Backtick vs Double-Quote for Reserved Words in `expr`

**Question:** Inside UC Metric View YAML `expr` strings, should reserved word column
names be quoted with backticks (`` `date` ``) or double quotes (`"date"`)?

**Risk:** High — wrong quoting causes DDL failures.

**Finding:** *(unverified — backtick assumed based on Databricks SQL conventions)*

**Test script:**

```python
from databricks import sql as dbsql
import os

conn = dbsql.connect(
    server_hostname=os.environ['DBX_HOSTNAME'],
    http_path=os.environ['DBX_HTTP_PATH'],
    access_token=os.environ['DBX_TOKEN']
)
cursor = conn.cursor()

# First create a table with a reserved word column name
cursor.execute(f"""
    CREATE OR REPLACE TABLE `{catalog}`.`{schema}`.`oi_reserved_word_test`
    (`date` DATE, revenue DOUBLE)
""")

# Test 1: backtick quoting in expr
yaml_backtick = """
version: "1.1"
source: {catalog}.{schema}.oi_reserved_word_test
dimensions:
  - name: the_date
    expr: "`date`"
measures:
  - name: total_revenue
    expr: SUM(revenue)
"""

# Test 2: double-quote quoting in expr
yaml_doublequote = """
version: "1.1"
source: {catalog}.{schema}.oi_reserved_word_test
dimensions:
  - name: the_date
    expr: '"date"'
measures:
  - name: total_revenue
    expr: SUM(revenue)
"""

for label, yaml_content in [("BACKTICK", yaml_backtick), ("DOUBLE_QUOTE", yaml_doublequote)]:
    try:
        cursor.execute(f"""
            CREATE OR REPLACE VIEW `{catalog}`.`{schema}`.`oi_reserved_{label.lower()}`
            WITH METRICS LANGUAGE YAML AS $${yaml_content}$$
        """)
        cursor.execute(f"SELECT MEASURE(total_revenue) FROM `{catalog}`.`{schema}`.`oi_reserved_{label.lower()}`")
        print(f"{label}: OK")
    except Exception as e:
        print(f"{label} FAILED: {e}")
    finally:
        cursor.execute(f"DROP VIEW IF EXISTS `{catalog}`.`{schema}`.`oi_reserved_{label.lower()}`")

cursor.execute(f"DROP TABLE IF EXISTS `{catalog}`.`{schema}`.`oi_reserved_word_test`")
conn.close()
```

**Skill impact:** Update the `expr` construction logic in Step 8, the validation
checklist in Step 11, and the schema reference if double-quote is correct.

---

## Item 3: Nested Join `expr` Namespace (Flat vs Hierarchical)

**Question:** In dimension/measure `expr` fields, does a column from a deeply-nested
join use just `join_name.col` (flat namespace) or the full path
`parent_join.nested_join.col` (hierarchical namespace)?

Example: If `nation` is nested inside `customer`, is the correct expr `nation.n_name`
or `customer.nation.n_name`?

**Risk:** High — affects all multi-hop join column references.

**Finding:** *(assumed flat namespace based on Databricks documentation example)*

**Test script:**

```python
from databricks import sql as dbsql
import os

conn = dbsql.connect(
    server_hostname=os.environ['DBX_HOSTNAME'],
    http_path=os.environ['DBX_HTTP_PATH'],
    access_token=os.environ['DBX_TOKEN']
)
cursor = conn.cursor()

# Test with a nested join (fact → customer → nation)
yaml_flat = """
version: "1.1"
source: {catalog}.{schema}.{fact_table}
joins:
  - name: customer
    source: {catalog}.{schema}.customer
    on: source.{fk_cust} = customer.{pk_cust}
    joins:
      - name: nation
        source: {catalog}.{schema}.nation
        on: customer.{fk_nation} = nation.{pk_nation}
dimensions:
  - name: nation_name
    expr: nation.{nation_col}    # FLAT reference
measures:
  - name: total
    expr: SUM({measure_col})
"""

yaml_hierarchical = yaml_flat.replace(
    "expr: nation.{nation_col}",
    "expr: customer.nation.{nation_col}"    # HIERARCHICAL reference
)

for label, yaml_content in [("FLAT", yaml_flat), ("HIERARCHICAL", yaml_hierarchical)]:
    try:
        cursor.execute(f"""
            CREATE OR REPLACE VIEW `{catalog}`.`{schema}`.`oi_namespace_{label.lower()}`
            WITH METRICS LANGUAGE YAML AS $${yaml_content}$$
        """)
        cursor.execute(f"SELECT MEASURE(total) FROM `{catalog}`.`{schema}`.`oi_namespace_{label.lower()}`")
        print(f"{label}: OK")
    except Exception as e:
        print(f"{label} FAILED: {e}")
    finally:
        cursor.execute(f"DROP VIEW IF EXISTS `{catalog}`.`{schema}`.`oi_namespace_{label.lower()}`")

conn.close()
```

**Skill impact:** Update Column `expr` Construction section in the rules reference,
and the expr building code in Step 8 of the skill.

---

## Item 4: `window:` with Missing Date Dimension

**Question:** If a formula translates to a window measure but no date dimension exists
in the metric view, does Databricks reject the YAML at CREATE time or at query time?

**Risk:** Medium — affects error handling for window measure translation.

**Finding:** *(unverified)*

**Skill impact:** Update Step 9 to emit a warning in the Unmapped Report if a window
measure references a dimension name that doesn't exist in the view.

---

## Item 5: Reading Back Metric View Definition

**Question:** What is the most reliable way to read back the YAML definition of a
UC Metric View for a `ts-from-unity-catalog` skill?

Options to test:
1. `SHOW CREATE TABLE catalog.schema.view_name` — does it return the full YAML?
2. `DESCRIBE EXTENDED catalog.schema.view_name` — does it include YAML in the output?
3. Unity Catalog REST API `/api/2.1/unity-catalog/tables/{full_name}` — what is returned?

**Risk:** Low (doesn't affect this skill, needed for ts-from-unity-catalog)

**Finding:** *(unverified)*

**Test script:**

```python
from databricks import sql as dbsql
import os, json, requests

conn = dbsql.connect(
    server_hostname=os.environ['DBX_HOSTNAME'],
    http_path=os.environ['DBX_HTTP_PATH'],
    access_token=os.environ['DBX_TOKEN']
)
cursor = conn.cursor()

# Test SHOW CREATE TABLE
cursor.execute(f"SHOW CREATE TABLE `{catalog}`.`{schema}`.`{existing_view_name}`")
row = cursor.fetchone()
print("SHOW CREATE TABLE result:")
print(row[0] if row else "(empty)")

# Test DESCRIBE EXTENDED
cursor.execute(f"DESCRIBE EXTENDED `{catalog}`.`{schema}`.`{existing_view_name}`")
rows = cursor.fetchall()
print("\nDESCRIBE EXTENDED result:")
for r in rows:
    print(r)

# Test REST API
resp = requests.get(
    f"https://{os.environ['DBX_HOSTNAME']}/api/2.1/unity-catalog/tables/{catalog}.{schema}.{existing_view_name}",
    headers={"Authorization": f"Bearer {os.environ['DBX_TOKEN']}"}
)
print("\nUC REST API response:")
print(json.dumps(resp.json(), indent=2))

conn.close()
```
