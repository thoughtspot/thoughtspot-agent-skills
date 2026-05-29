# Open Items: ts-model-from-tableau

---

## #1 — VALIDATE_ONLY policy in ts CLI — NEEDS VERIFICATION

The skill uses `ts tml import --policy VALIDATE_ONLY` for the fix loop. Verify that the `ts` CLI supports this policy flag and returns structured error JSON (not just HTTP status).

Alternative: if VALIDATE_ONLY is unsupported, use `--policy PARTIAL` with a dry-run flag, or call the REST v2 endpoint directly:
`POST /api/rest/2.0/metadata/tml/import` with `{"import_policy": "VALIDATE_ONLY", "dry_run": true}`

Status: NEEDS VERIFICATION against live cluster

---

## #2 — Connection schema fetch for empty `externalDatabases` — VERIFIED WORKAROUND

When the REST v2 `connections get` endpoint returns no tables (empty `externalDatabases`), the Callosum `fetchConnection` API can be used with an explicit `database` parameter. However, the `ts` CLI may not expose this. In that case, ask the user for the database name and proceed with `YOUR_DATABASE`/`YOUR_SCHEMA` placeholders — ThoughtSpot issues a warning, not an error, for placeholder values.

Status: WORKAROUND DOCUMENTED in Step 4

---

## #3 — COLLECTION datasources — NOT IMPLEMENTED

Tableau COLLECTION datasources (multiple primary data sources combined) should generate one model per underlying table. This edge case is not handled in v1.0.0.

Status: DEFERRED to v1.1.0

---

## #4 — Custom SQL relations — PARTIAL

When a Tableau relation uses custom SQL, the skill extracts the physical table name from the SQL string (table after `FROM`). Complex multi-table SQL or subqueries are not handled.

Status: PARTIAL — simple `FROM table` pattern only
