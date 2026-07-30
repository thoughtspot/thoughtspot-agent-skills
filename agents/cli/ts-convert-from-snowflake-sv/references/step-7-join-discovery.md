This file serves **Step 7: Find join names (Scenario A only)** in
`agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — the join-discovery options
presented when a Semantic View has multiple tables but no `relationships(...)`
block (GAP-03, "joinless semantic views").

---

**Option 1 — Database constraint discovery:**

Query Snowflake for foreign key relationships between the SV's tables:

```sql
-- For each table in the SV:
SHOW IMPORTED KEYS IN TABLE {db}.{schema}.{table};
```

The result contains `pk_table_name`, `pk_column_name`, `fk_table_name`, `fk_column_name`,
and `key_sequence` (for composite FKs with the same constraint name). Build relationships
from these — each FK→PK pair becomes a join. Composite FKs (multiple rows with the same
constraint name) become composite equi-joins.

If FK constraints are found, present them for confirmation:

```
Found {n} foreign key relationships:

  1. {FK_TABLE}.{FK_COL} → {PK_TABLE}.{PK_COL}  (MANY_TO_ONE)
  2. {FK_TABLE}.({COL1},{COL2}) → {PK_TABLE}.({COL1},{COL2})  (composite, MANY_TO_ONE)

Accept these joins? [Y / edit / skip]
```

If no FK constraints are found, offer to fall back to Option 2 (column overlap analysis).

**Option 2 — Column overlap analysis (deeper dive):**

For each pair of tables in the SV:

1. **Scan column name overlap** — find columns with identical names (case-insensitive)
   across the two tables:
   ```sql
   SELECT a.COLUMN_NAME
   FROM INFORMATION_SCHEMA.COLUMNS a
   JOIN INFORMATION_SCHEMA.COLUMNS b
     ON UPPER(a.COLUMN_NAME) = UPPER(b.COLUMN_NAME)
   WHERE a.TABLE_SCHEMA = '{schema}' AND a.TABLE_NAME = '{table_a}'
     AND b.TABLE_SCHEMA = '{schema}' AND b.TABLE_NAME = '{table_b}'
     AND a.TABLE_CATALOG = '{db}' AND b.TABLE_CATALOG = '{db}';
   ```

2. **Check composite key uniqueness** — for each candidate set of join columns,
   verify uniqueness on the target table:
   ```sql
   SELECT COUNT(*) AS total_rows,
          COUNT(DISTINCT ({col1}, {col2})) AS distinct_keys
   FROM {db}.{schema}.{table};
   ```
   If `total_rows == distinct_keys`, the column set is a valid unique key.

3. **Validate cardinality** — confirm the join direction:
   ```sql
   SELECT MAX(cnt) FROM (
     SELECT {join_cols}, COUNT(*) AS cnt
     FROM {db}.{schema}.{from_table}
     GROUP BY {join_cols}
   );
   ```
   `max(cnt) == 1` → ONE_TO_ONE; `max(cnt) > 1` → MANY_TO_ONE from the source table.

4. **Present suggestions with evidence:**
   ```
   Suggested joins (based on column overlap analysis):

     1. EMPLOYEES.(COMPANY_ID, DEPARTMENT) → EMPLOYEE_SUMMARY_VW.(COMPANY_ID, DEPARTMENT)
        Uniqueness: 15 rows, 15 distinct keys ✓
        Cardinality: MANY_TO_ONE (max 12 employees per group)
        Type: LEFT_OUTER

   Accept / Modify / Skip each:
   ```

**Option 3 — User-specified joins:**

Prompt the user to define each join:

```
Specify joins between the {n} tables.

For each join, provide:
  From table: ______
  From column(s): ______  (comma-separated for composite)
  To table: ______
  To column(s): ______
  Cardinality: MANY_TO_ONE / ONE_TO_ONE / MANY_TO_MANY
  Type: LEFT_OUTER (default) / INNER / RIGHT_OUTER / OUTER   (OUTER = full outer; FULL_OUTER is invalid TML)

Add another join? [Y / done]
```

**Option 4 — Skip (separate model per table):**

Since ThoughtSpot cannot query across unjoined tables in a single model, create a
separate model for each table:

```
⚠ No joins defined. Creating {n} separate models — one per table.
  Cross-table queries will not be possible.

  Model 1: {TABLE_A} ({m} columns)
  Model 2: {TABLE_B} ({p} columns)

  You can combine them later by editing Model TML and adding joins.

Proceed? [Y / n]
```

Each model gets its own `model_tables` entry (single table), its own columns
(only those from that table), and its own formulas (only those referencing that
table's columns). Import each model separately.

All discovered/specified joins (Options 1–3) are added to the `relationships` map
and treated identically to SV-declared relationships in Step 8 (inline joins on the
FROM table).
