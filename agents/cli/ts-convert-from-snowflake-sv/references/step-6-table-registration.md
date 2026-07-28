This file serves **Step 6A: Discover and verify existing ThoughtSpot Table objects**
and **Step 6B: Create ThoughtSpot Table objects for views (Scenario B)** in
`agents/cli/ts-convert-from-snowflake-sv/SKILL.md` — the Step 6A table-plan
confirmation template, and the full Step 6B `ts snowflake introspect` /
connection-selection / `ts tables create` command sequence.

---

## Step 6A — Table Plan confirmation template

```
Table Plan:
  ✓  {TABLE_1}  — found (GUID: {guid}) — all {n} columns present → use as-is
  ⚠  {TABLE_2}  — found (GUID: {guid}) — missing {n} columns: {COL_A}, {COL_B} → update
  ✗  {TABLE_3}  — not found in ThoughtSpot → create new

Actions to be taken:
  • Update {TABLE_2}: add {n} missing columns
  • Create {TABLE_3}: {n} columns from Snowflake schema

No changes have been made yet. Proceed? (yes/no):
```

---

## Step 6B — command sequence

**Use `ts snowflake introspect` to query Snowflake and build the table spec:**

1. First, choose the ThoughtSpot connection (step 2 below), then run:

   ```bash
   ts snowflake introspect \
     --parsed parsed.json --sf-profile {sf_profile} \
     --connection-name "{connection_name}" --output-dir ./introspect_out
   ```

   This queries `INFORMATION_SCHEMA.COLUMNS` for all SV source tables in one batch,
   maps Snowflake types to ThoughtSpot types, and produces:
   - `introspect_out/tables-spec.json` — input for `ts tables create`
   - `introspect_out/tables.json` — input for `ts snowflake build-model --tables`

   The summary JSON on stdout includes `{tables, total_columns, warnings}`.

   If `ts snowflake introspect` is not available or the Snowflake profile is not set up,
   fall back to the manual batch query:
   ```sql
   SELECT table_name, column_name, data_type
   FROM {database}.information_schema.columns
   WHERE table_schema = '{SCHEMA}'
   ORDER BY table_name, ordinal_position;
   ```

2. Choose which ThoughtSpot connection to use — **use an existing one or create a new
   one**. Use the connection **name** directly in table TML — no GUID lookup is needed
   or possible from available procedures.

   Follow the **E/C prompt** then **N/F/L connection selection** flow in
   [../../shared/references/connection-select.md](../../../shared/references/connection-select.md),
   with `{database}` from the semantic view, warehouse type = Snowflake, and
   auth type = key-pair.

   **C — create a new connection (Snowflake, key-pair auth).** Collect the connection
   name, Snowflake account identifier, user, role, warehouse, and the path to the
   **unencrypted PKCS#8 private key** (`.p8`), then run:

   ```bash
   ts connections create \
     --name "{connection_name}" \
     --account "{account}" --user "{user}" --role "{role}" --warehouse "{warehouse}" \
     --database "{database}" \
     --private-key-path "{key_path}" \
     --profile {profile}
   ```

   The role must have `USAGE` on `{database}` and its schema (and `SELECT` on the
   tables) — otherwise the tables won't resolve. The matching **public** key must already
   be registered on the Snowflake user (`DESC USER {user}` shows `RSA_PUBLIC_KEY`).

   **Credential handling (required):** never ask the user to paste a private key,
   password, or secret into the conversation. The key is passed **by file path only** —
   `ts connections create` reads it and never echoes it. Key-pair is the only auth this
   path supports; for password/OAuth, direct the user to create the connection in the
   ThoughtSpot UI and return on the **E** path. The command prints
   `{id, name, data_warehouse_type}` — use the returned `name` for the table spec.

3. Create ThoughtSpot Table objects for all tables in one command:
   ```bash
   cat introspect_out/tables-spec.json | ts tables create --profile {profile}
   ```
   The `tables-spec.json` from `ts snowflake introspect` is ready to use. This command
   handles JDBC retry and GUID resolution automatically, and outputs `{name: guid}`.
   The `introspect_out/tables.json` is the tables map for `ts snowflake build-model`
   in Step 8 — use it directly.
