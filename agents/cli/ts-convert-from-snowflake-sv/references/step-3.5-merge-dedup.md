This file serves **Step 3.5: Merge and Deduplication (merge mode only)** in
`agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — the full dedup rule set applied
when combining multiple Semantic Views' parse results into one merged result.

---

**1. Tables** — union of all `tables[]` entries across all SVs.
- Deduplicate by **physical identity**: two entries with the same
  `base_table.database + schema + table` represent the same Snowflake table. Keep one.
- If their column definitions differ (different dimensions, different data types for
  the same column name), flag as a **column conflict** — list each conflicting column
  and ask the user which definition wins before continuing.

**2. Relationships** — union of all `relationships[]`.
- Deduplicate by (left_table, right_table, left_column, right_column) — exact match
  on all four fields. Keep one entry.
- If the same table pair has conflicting relationship definitions (different column
  pairs), flag as a **relationship conflict** for user resolution.

**3. Metrics** — union of all `metrics[]`.
- Deduplicate by (name, expr) — exact match on both. Keep one entry.
- If same name but different expr: flag as a **metric conflict**. User must choose
  which definition wins or rename one before the merge can proceed. Do not silently
  prefer either definition.

**4. Dimensions / time_dimensions / metrics / facts (if present)** — union across all
views, deduplicated by (table_name, column_name). DDL `facts ()` entries (row-level named
expressions) are also merged and available for identifier resolution in Step 9.

**5. Fact table identification in merged context** — re-run the fact-table detection
algorithm (tables with no incoming relationships in the merged relationship set = fact
tables). If a table was a fact in one SV but gains an incoming relationship from
another SV in the merged graph, present it to the user:
```
{TABLE} had no incoming joins in {SV1} but gains one from {SV2} in the merged model.
Treat as:  F — Fact table   D — Dimension table
```

**6. Present merge summary and require confirmation before continuing:**
```
Merging {M} Semantic Views:

  {SV1}:  {n} tables, {n} relationships, {n} metrics
  {SV2}:  {n} tables, {n} relationships, {n} metrics
  ...

Merged result:  {n} tables ({x} deduplicated), {n} relationships, {n} metrics
Conflicts:      {None / list of conflicts to resolve}

Output model name: {name from Step 2}
Proceed? YES / NO
```

If there are unresolved conflicts, require all to be resolved before accepting YES.
After confirmation, continue with Step 4 using the merged result.
