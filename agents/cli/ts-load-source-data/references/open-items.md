# Open Items — ts-load-source-data

Verification items tracked during development. See the
[repo convention](../../../../CLAUDE.md) for the open-items pattern.

---

## #1 — snow stage copy path format — OPEN

The `snow stage copy` command may require different path formats depending on
the snow CLI version. Need to verify the exact syntax for uploading to a table
stage (`@%table_name`) vs a named stage.

**Test:** `snow stage copy ./test.csv @DB.SCH.%TABLE_NAME -c <connection>`

**Status:** OPEN — still open as of 2026-07-11. `_load_via_cli` (`tools/ts-cli/ts_cli/commands/load.py:495`)
implements exactly this call shape (`snow stage copy <path> @{database}.{schema}.%{table_name} -c <connection>`),
and unit tests (`tools/ts-cli/tests/test_load.py`) cover it with a mocked subprocess, but
`tools/smoke-tests/smoke_ts_load_source_data.py` explicitly exercises only the offline
`infer`/`generate` steps ("no live Snowflake connection needed") — no merged evidence of
a live `snow stage copy` run against a real account. Blocked on live Snowflake access to
run the test procedure above.

---

## #2 — COPY INTO with quoted fields — OPEN

Verify that `FIELD_OPTIONALLY_ENCLOSED_BY='"'` correctly handles CSV files with
quoted fields containing commas (the DunderMifflin "First Aid Kit, Office Size"
pattern from the Tableau migration).

**Test:** Load a CSV with quoted-comma fields and verify row counts match.

**Status:** OPEN — still open as of 2026-07-11. Both loading paths (`_load_via_cli` and
`_load_via_python` in `tools/ts-cli/ts_cli/commands/load.py`) issue
`COPY INTO ... FILE_FORMAT=(TYPE=CSV FIELD_OPTIONALLY_ENCLOSED_BY='"' SKIP_HEADER=1)`, but
the CHANGELOG's one live-driven fix for this skill (v0.26.3, #164) addressed the synthetic
*data-generation* type-mismatch bug, not this quoted-field `COPY INTO` path — no merged
evidence of a live test with quoted-comma CSV data. Blocked on live Snowflake access.

---

## #3 — CREATE DATABASE IF NOT EXISTS permissions — OPEN

The Snowflake role used may not have `CREATE DATABASE` privileges. Need to verify
behaviour when the database already exists vs when it needs to be created, and
document the required role permissions.

**Status:** OPEN — still open as of 2026-07-11. `CREATE DATABASE IF NOT EXISTS` is
implemented at `tools/ts-cli/ts_cli/commands/load.py:460` (CLI path) and `:576` (Python
path), covered by mocked unit tests only (`tools/ts-cli/tests/test_load.py`) — no merged
evidence of a live run against a role lacking `CREATE DATABASE` privilege. Blocked on live
Snowflake access with a restricted role to confirm the failure mode and document required
permissions.
