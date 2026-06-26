# Open Items — ts-load-source-data

Verification items tracked during development. See the
[repo convention](../../../../CLAUDE.md) for the open-items pattern.

---

## #1 — snow stage copy path format — UNVERIFIED

The `snow stage copy` command may require different path formats depending on
the snow CLI version. Need to verify the exact syntax for uploading to a table
stage (`@%table_name`) vs a named stage.

**Test:** `snow stage copy ./test.csv @DB.SCH.%TABLE_NAME -c <connection>`

---

## #2 — COPY INTO with quoted fields — UNVERIFIED

Verify that `FIELD_OPTIONALLY_ENCLOSED_BY='"'` correctly handles CSV files with
quoted fields containing commas (the DunderMifflin "First Aid Kit, Office Size"
pattern from the Tableau migration).

**Test:** Load a CSV with quoted-comma fields and verify row counts match.

---

## #3 — CREATE DATABASE IF NOT EXISTS permissions — UNVERIFIED

The Snowflake role used may not have `CREATE DATABASE` privileges. Need to verify
behaviour when the database already exists vs when it needs to be created, and
document the required role permissions.
