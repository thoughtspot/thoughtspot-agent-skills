# Connection Select — Shared Reference

Canonical flow for identifying and selecting a ThoughtSpot data connection.
Used by conversion skills and any skill that generates table TML referencing
a connection by name.

## Prompt

Don't dump the full connection list by default — a long list is noise when
the user already knows the one they want. Ask:

```
How would you like to identify the connection?
  N  Name it     — type the exact connection name; I'll use it directly
  F  Filter      — give a partial string; I'll list only connections that match
  L  List all    — show every connection and pick by number

Enter N / F / L:
```

Skills may add options to this menu (e.g. Tableau adds **T** for trust-without-
validation). The core N/F/L options and their resolution rules below are fixed.

## Fetch

Fetch connections once (auto-paginated, returns all):

```bash
ts connections list --profile {profile}
```

Add `--type {TYPE}` (e.g. `DATABRICKS`, `SNOWFLAKE`) when the skill targets a
specific warehouse type.

## Resolution rules

Resolve the user's choice against the fetched result:

- **N (name it)** — match the typed name against the returned `name` values
  (case-sensitive). Exactly one match → use it. No match → show the closest
  names and re-ask. Don't fabricate a name the list doesn't contain — the table
  TML needs the exact, case-sensitive connection name.
- **F (filter)** — keep connections whose `name` contains the string
  (case-insensitive), show them as a short numbered list (name, type, database),
  and pick from that. One match → auto-select and confirm; none → widen the
  string or switch to **L**.
- **L (list all)** — show the full numbered list and pick by number.

If only one connection exists in total (or only one matches the target
database/type), auto-select it and confirm regardless of the choice. Use the
exact `name` value from the API response.

## Existing vs create (E/C prompt)

When the skill supports creating a new connection (e.g. Snowflake key-pair via
`ts connections create`), ask first whether to use an existing connection or
create a new one:

```
The generated tables need a ThoughtSpot connection that can reach {database}.
  E  Use an existing connection
  C  Create a new connection   ({warehouse_type}, {auth_type})

Enter E / C:
```

> **When to create:** a ThoughtSpot connection only sees databases its warehouse
> **role** (or credentials) can access. If no existing connection can see the
> target database, table creation fails with *"Database {db} does not exist in
> connection"* — that is the signal to create one (do **not** trial-and-error
> existing connections to find out).

On **E**, proceed with the N/F/L prompt above. On **C**, collect credentials
per the skill's creation instructions (Snowflake: `ts connections create`;
other warehouses may require creation in the ThoughtSpot UI).

Skills where connection creation is out of scope (e.g. Databricks — no
`ts connections create` path) should omit the E/C prompt and go directly to
the N/F/L prompt with a note directing users to the ThoughtSpot UI if no
suitable connection exists.
