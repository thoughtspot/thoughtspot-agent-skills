# Connection health check: design

A `ts connections diagnose` command and a `ts-object-connection-health` skill. Together they
report which ThoughtSpot connections are broken, and why.

**Status:** draft, not yet built. Scope, approach and admin-only v1 agreed with the user
(2026-11-19 and 2026-11-25). The user has not yet approved this document. Tracked as BL-621.
The next session starts by getting that approval, then writes the implementation plan.

## Summary

ThoughtSpot cannot show whether a connection is healthy (PDM-5106). Stale connections go
unnoticed until someone edits one or a query fails. They also waste work: Spotter indexing and
row-count stats still run against them.

This is the stopgap until the product does it. The command checks connections and writes JSON.
The skill wraps the command for Claude Code users. Customers can also run the command from their
own scripts or scheduled jobs.

It is piece 1 of 2. Piece 2 adds connections to `ts audit` as a new subject, with its own design.
Piece 1's JSON is piece 2's input.

## Why the internal diagnose route

ThoughtSpot already checks a connection's health internally. The route is reachable with the
normal bearer token (live on se-thoughtspot, 2026-11-18; evidence in Appendix A):

```
GET /callosum/v1/connection/diagnose?connection_id=<guid>
```

- It is not in public v2: `/api/rest/2.0/connection/diagnose` returns 404.
- It checks every registered table and column, not just the login.
- The repo rule for internal `/callosum/v1/` routes applies (`.claude/rules/ts-cli.md`). It stays
  in one module, so a build that drops it breaks in one place.

## Goals

- Classify every connection in scope as healthy, down, drifted or unknown.
- Name the failing tables and columns, with ThoughtSpot's own error code.
- Produce JSON another tool can consume: the audit, a scheduler, a notifier.
- Warn about cost before a large run, and keep the warehouse load bounded.

## Non-goals

- Fixing anything. The command and skill are read-only.
- Comparing with a previous run. Consumers can diff two JSON files. A comparison flag can come
  later if scheduled use needs it.
- Filtering by connection owner. `connection/search` does not return the owner.
- Scheduling. The command is schedulable; setting up the schedule is the customer's job.
- Audit integration. That is piece 2.

## Anti-goals

- **Reporting a connection as broken when we could not test it.** I.e. a per-user OAuth
  BigQuery connection returns 500 code 12136 to anyone who has not authorised it. That is
  `unknown`, never `down`.
- **Reporting a broken connection as healthy.** A down connection returns HTTP 200 with
  `connectivityStatus: FAILED`. The status code alone shows success.
- **Hammering the warehouses.** Each check queries the warehouse and may wake a suspended
  Snowflake warehouse. A run must never fan out unbounded, and a timeout must not be retried.

## Approaches

| | Approach | Trade-off |
|---|---|---|
| A | Command only; the audit becomes the way in later | Least work. Claude Code users have no guided path until piece 2 |
| **B** | **Command plus a small skill (chosen)** | A guided path now, for both ways in the user asked for: a skill, or the Python |
| C | Command plus a connections step bolted onto the `ts-audit` skill | Sooner "audit covers connections", but prose outside the rule engine and report. Piece 2 would rip it out |

The user chose B on 2026-11-19.

## The command: `ts connections diagnose`

### Scope

| Flag | Meaning |
|---|---|
| `--connection NAME` | One connection, by display name (case-insensitive) or GUID. Repeatable |
| `--type TYPE` | One warehouse type, e.g. `SNOWFLAKE`. Same values as `ts connections list --type` |
| none of the above | Every connection the caller can see in the Org |
| `--org ORG` | The Org to run in. Connections are per-Org. Default: the profile's Org |
| `--profile NAME` | As every other command |

A `--connection` that matches nothing is an error (exit 1, naming it), as in `ts audit`.

### Running

- `--dry-run` resolves the scope and prints the count and a rough time range. It calls no
  warehouse. I.e. "1,815 connections, about 25 to 90 minutes at 4 workers".
- `--workers N` checks N connections in parallel. Default 4.
- `--timeout SECONDS` per connection. Default 600. The server likely keeps checking after
  the client gives up, so a short timeout frees a worker while the warehouse is still busy.
  A long default keeps warehouse load close to `--workers`.
- Progress goes to stderr: `[37/1815] APJ_TAB … drifted (37s)`.
- No automatic retry on this route. That covers a timeout and a 502, 503 or 504, which the
  client retries elsewhere. A retry would start a second check on the same warehouse. Each
  is reported as `unknown`.
- A 401 re-authenticates once, as the client already does. If the token is then valid but
  this route still returns 401 for one connection, that connection is `unknown`. The run
  continues. Only an invalid token aborts the run.

### Who can run it

Admins only in v1 (user decision, 2026-11-25). The command checks for the ADMINISTRATION
privilege before any diagnose call, and exits 1 without it. Reuse `is_admin` in
`ts_cli/dependency/cascade.py`, which reads `auth/session/user`.

Why: every probe ran as an admin. A non-admin may not get an error. ThoughtSpot may instead
leave out the tables they cannot see, and a connection would then read `healthy` when it is
not. Opening it to connection owners is a later change, after a non-admin probe.

### The response

From the probes. No field carries credentials or connection settings.

| Path | Meaning |
|---|---|
| `connectivityStatus` | `SUCCESSFUL` or `FAILED` |
| `errorString` | On `FAILED`: text holding `Error Code: <code>`, an incident id and a message |
| `tableStatuses[].tableName` | ThoughtSpot table name |
| `tableStatuses[].externalTableName.{databaseName, schemaName, tableName}` | Warehouse location |
| `tableStatuses[].tableStatus` | `SUCCESSFUL` or a failure |
| `tableStatuses[].columnStatuses[].{columnName, externalColumnName, columnStatus, errorCode, errorString}` | Per column |
| Non-2xx body: `code`, `debug`, `incident_id_guid`, `parameter` | ThoughtSpot's error envelope. 12136 is in `code` |

There is no table GUID. `externalTableName.gid` was 0 every time. So piece 2 matches a
failure to a ThoughtSpot Table by database, schema and table name.

### Classification

One status per connection. The rules are applied in this order:

| Response | `status` | `reason` |
|---|---|---|
| HTTP 200, `connectivityStatus` is not `SUCCESSFUL` | `down` | `connection_failed` |
| HTTP 200, any table or column status is not `SUCCESSFUL` | `drifted` | `objects_failed` |
| HTTP 200, everything `SUCCESSFUL` | `healthy` | none |
| HTTP 500, code 12136 | `unknown` | `oauth_not_authorised` |
| Timeout | `unknown` | `timeout` |
| Any other non-2xx, or a non-JSON body | `unknown` | `error` |

Only `SUCCESSFUL` counts as success. I.e. a status of `PARTIAL`, should one ever appear, counts
as a failure.

A connection with no registered tables is `healthy` with `tables_checked: 0`, so a consumer can
tell it apart.

### Output

JSON on stdout. Diagnostics on stderr only.

```json
{
  "cluster": "https://example.thoughtspot.cloud",
  "org": "Primary",
  "checked_at": "2026-11-19T09:00:00Z",
  "summary": {"healthy": 15, "down": 2, "drifted": 2, "unknown": 1},
  "connections": [
    {
      "id": "a679842a-…", "name": "APJ_TAB", "type": "SNOWFLAKE",
      "status": "drifted", "reason": "objects_failed",
      "error_code": null, "error_message": null, "duration_s": 37.2,
      "tables_checked": 58, "tables_failed": 0,
      "columns_checked": 400, "columns_failed": 6,
      "failures": [
        {"table": "DIM_DATE", "database": "AGENT_SKILLS", "schema": "…",
         "external_table": "DIM_DATE", "column": "MONTH",
         "error_code": "EXTERNAL_OBJECT_NOT_FOUND",
         "error_message": "No column found with name MONTH in table DIM_DATE."}
      ]
    }
  ]
}
```

- `failures` holds only failing tables and columns. A failing table has `column: null`.
- `--full` adds `raw`: the unmodified diagnose response.
- `error_code` and `error_message` hold the connection-level error, for `down` and `unknown`.
- `-o FILE` writes the JSON to a file instead of stdout.
- Exit 0 when the run completes, whatever it finds. The consumer reads `summary`.

## The skill: `ts-object-connection-health`

The name follows `ts-object-{type}-{verb}`. `ts-object-set-manager` sets the precedent for a
`ts-object-*` skill that reports on every object of one type. Category: Platform & Governance.

Steps:

1. **Overview.** What it checks, that it is read-only, and that it queries each warehouse.
2. **Profile and Org.**
3. **Scope.** All connections, chosen by name, or one warehouse type.
4. **Confirm cost.** Run `--dry-run`. Show the count and time range. Say that suspended
   warehouses may wake. Get a yes before going on.
5. **Run.** Write the JSON to a run folder with the time in its name, as `ts-audit` does.
6. **Summarise.** Counts first. Then `down`, `drifted` with their top failures, and `unknown`
   with reasons. Each group gets its next step:
   - `down`: edit the connection's credentials or network settings. Suggest deleting it only
     if it is unused and not a per-user OAuth connection (open item 1).
   - `drifted`: re-sync the table, or remove the dead columns with `ts-dependency-manager`.
   - `unknown` (OAuth): run the check as the connection's owner.

## Repo obligations

Per the root `CLAUDE.md` change-impact map:

- ts-cli: new module for the route, registration in `connections.py`, README entry, unit tests,
  version bump in both files.
- Skill: SKILL.md with `metadata` (category, summary), a place in `CURATED_ORDER`, regenerated
  README tables, `agents/cli/SETUP.md` symlink step, changelog at 1.0.0.
- `tools/smoke-tests/smoke_ts_object_connection_health.py`.
- `references/open-items.md` holding Appendix A's findings and item 1 below.
- `CHANGELOG.md` entry.

## Left to the builder

- **Thread safety.** How workers share a client (one per worker, or a shared session) is the
  builder's call. A token refresh must not race between workers.
- **Disabling the retry on timeout.** The client retries a GET read timeout today. The mechanism
  for skipping that on this route is the builder's call.
- **The time estimate's formula** for `--dry-run`. Appendix A's timings are the only data.

## Open items to verify live

Items 1 to 3 must be verified before merge.

1. **Per-user OAuth on Snowflake and Databricks.** The only OAuth sample was BigQuery (500,
   code 12136). Snowflake and Databricks are 1,797 of 1,815 connections. If an unauthorised
   one returns 200 with `FAILED`, it would read `down`. Then classification also needs the
   connection's authentication type, and a reason of its own.
2. **A 401 from this route.** Confirm whether one connection can return 401 while the token
   is valid, so the run treats it as `unknown` rather than aborting.
3. **Does the server stop when the client times out?** Diagnose a large connection with a
   short timeout and watch the warehouse's query history. If it keeps running, the 600s
   default stands. If it stops, the default can come down.
4. **Non-admins (deferred past v1).** Probe what a non-admin sees for a connection they do not
   own. Needed before v1's admin-only check is lifted.

## Appendix A: live probe, se-thoughtspot, 2026-11-18

**Route discovery.**

| Request | Result |
|---|---|
| `POST`/`GET /api/rest/2.0/connection/diagnose` | 404 |
| `POST /callosum/v1/connection/diagnose` | 405 |
| `GET …/diagnose?id=` / `?connectionId=` / `?guid=` / `?dataSourceId=` | 400, code 10002, "Connection does not exist" |
| `GET …/diagnose?connection_id=` | 200 |

The 10002 error is misleading: it means the parameter name was wrong.

**Sample of 23 connections across seven warehouse types.** The cluster has 1,815 connections:
1,783 Snowflake, 14 Databricks, 7 BigQuery, 5 Redshift, 4 Postgres, 1 SQL Server, 1 GCP Postgres.

| Outcome | Count | Example |
|---|---|---|
| Healthy | 18 | Snowflake, Databricks, Redshift, BigQuery, Postgres, GCP Postgres |
| Down: `connectivityStatus: FAILED`, `CONNECTION_CREATION_ERROR` | 2 | A SQL Server and a Postgres connection |
| Drifted: connection up, columns failed | 2 | APJ_TAB, 6 of 400 columns |
| Unknown: 500, code 12136 | 1 | A per-user OAuth BigQuery connection |

Column error codes seen: `EXTERNAL_OBJECT_NOT_FOUND` (column dropped in the warehouse) and
`EXTERNAL_COLUMN_DATATYPE_MISMATCH`.

**Timings.** 1 to 9 seconds for most connections. 32 and 37 seconds for the two with the most
registered columns (APJ_TAB has 58 tables).
