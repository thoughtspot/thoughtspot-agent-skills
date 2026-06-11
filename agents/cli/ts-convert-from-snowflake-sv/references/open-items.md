# Open Items: ts-convert-from-snowflake-sv

---

## #1 — sql_view generation path for view/subquery-backed SVs — NOT IMPLEMENTED

Some Snowflake Semantic Views are backed by subqueries or views rather than physical
tables (the `FROM` clause uses a subquery or a named view instead of a direct table
reference). In these cases, the skill cannot bind a ThoughtSpot Table TML to a
physical table — a SQL View TML (`sql_view:`) should be generated instead, and the
model should reference the SQL View by name in `model_tables[]`.

This path is implemented in `ts-convert-from-databricks-mv` (Step 2c — subquery source
→ SQL View TML) and `ts-convert-from-tableau` (Step 5c — custom SQL relations). The
Snowflake-SV skill currently assumes all source tables are physical tables accessible
via the connection schema.

Affected SVs: any that use `FROM (<subquery>)` or `FROM <view_name>` for a source
that is not itself a physical table tracked by the ThoughtSpot connection.

**Workaround:** user manually creates a ThoughtSpot SQL View TML for the subquery/view
source, imports it, and replaces the Table TML reference in the model with the SQL View
GUID/name.

Status: NOT IMPLEMENTED
