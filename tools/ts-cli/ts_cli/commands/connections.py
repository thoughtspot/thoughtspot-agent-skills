"""ts connections — list and manage ThoughtSpot data connections."""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Connection management commands.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


@app.command("list")
def list_connections(
    profile: Optional[str] = _profile_option,
    type: str = typer.Option("SNOWFLAKE", "--type", "-t",
                             help="Data warehouse type filter (e.g. SNOWFLAKE, BIGQUERY)"),
) -> None:
    """List all available data connections (auto-paginated).

    Output: JSON array of all connection objects from
    POST /api/rest/2.0/connection/search (all pages, not capped).
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    all_connections: List[Dict[str, Any]] = []
    offset = 0
    page_size = 500
    while True:
        resp = client.post(
            "/api/rest/2.0/connection/search",
            json={"data_warehouse_types": [type], "record_size": page_size, "record_offset": offset},
        )
        page = resp.json()
        if not isinstance(page, list) or not page:
            break
        all_connections.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    print(json.dumps(all_connections))


def _adapt_v2_databases(v2_dbs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert a v2 ``connection/search`` ``databases`` hierarchy into the
    legacy ``fetchConnection`` key shape that ``_merge_tables`` and the v2
    update payload expect.

    v2 keys (``data_type``, ``is_linked_active``, ``auto_created``) are renamed
    to the legacy keys (``type``, ``isLinkedActive``, ``isAutoCreated``) so that
    tables preserved from the existing connection serialize correctly when fed
    to ``POST /api/rest/2.0/connections/{id}/update``.
    """
    databases: List[Dict[str, Any]] = []
    for db in v2_dbs or []:
        schemas: List[Dict[str, Any]] = []
        for sch in db.get("schemas", []) or []:
            tables: List[Dict[str, Any]] = []
            for t in sch.get("tables", []) or []:
                tables.append({
                    "name": t.get("name"),
                    "type": t.get("type", "TABLE"),
                    "description": t.get("description", ""),
                    "selected": t.get("selected", True),
                    "linked": t.get("linked", True),
                    "columns": [
                        {
                            "name": c.get("name"),
                            "type": c.get("data_type", "VARCHAR"),
                            "selected": c.get("selected", True),
                            "isLinkedActive": c.get("is_linked_active", True),
                        }
                        for c in (t.get("columns") or [])
                    ],
                })
            schemas.append({"name": sch.get("name"), "tables": tables})
        databases.append({
            "name": db.get("name"),
            "isAutoCreated": db.get("auto_created", False),
            "schemas": schemas,
        })
    return databases


def _fetch_connection_v2(client: ThoughtSpotClient, connection_id: str) -> Dict[str, Any]:
    """Fetch a connection's warehouse-object hierarchy via the v2
    ``POST /api/rest/2.0/connection/search`` endpoint, adapted to the legacy
    ``{"dataWarehouseInfo": {"databases": [...]}}`` shape.

    Replaces the removed v1 ``/tspublic/v1/connection/fetchConnection`` endpoint
    (404 on ThoughtSpot Cloud builds where the legacy tspublic API is dropped).

    NOTE: server-side warehouse introspection (databases/tables/columns) is only
    returned for connections that authenticate with a stored SERVICE_ACCOUNT.
    OAuth/PKCE/per-user connections return connection metadata with an *empty*
    hierarchy — the same practical limitation v1 had, with no API-side
    workaround. Callers must tolerate an empty hierarchy (``add-tables`` does).
    To discover tables already registered as ThoughtSpot objects, use
    ``ts metadata search`` instead of this command.
    """
    resp = client.post(
        "/api/rest/2.0/connection/search",
        json={
            "connections": [{"identifier": connection_id}],
            "data_warehouse_object_type": "COLUMN",
            "include_details": True,
            "record_size": -1,
            "record_offset": 0,
        },
    )
    data = resp.json()
    conns = data if isinstance(data, list) else data.get("data", data)
    conn = conns[0] if isinstance(conns, list) and conns else (conns or {})
    dwo = conn.get("data_warehouse_objects") or {}
    v2_dbs = dwo.get("databases", []) if isinstance(dwo, dict) else []
    return {"dataWarehouseInfo": {"databases": _adapt_v2_databases(v2_dbs)}}


@app.command("get")
def get_connection(
    connection_id: str = typer.Argument(..., help="Connection GUID"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Fetch full connection details including existing tables and columns.

    Uses the v2 endpoint POST /api/rest/2.0/connection/search (the v1
    /tspublic/v1/connection/fetchConnection endpoint was removed on newer
    ThoughtSpot Cloud builds and returns 404).

    Output: JSON in the legacy shape (dataWarehouseInfo.databases) for
    backward compatibility. The hierarchy is populated only for connections
    that authenticate with a stored SERVICE_ACCOUNT; OAuth/PKCE connections
    return an empty hierarchy (use `ts metadata search` to find already-
    registered tables instead).

    Requires CAN_CREATE_OR_EDIT_CONNECTIONS privilege.
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    print(json.dumps(_fetch_connection_v2(client, connection_id)))


@app.command("add-tables")
def add_tables(
    connection_id: str = typer.Argument(..., help="Connection GUID"),
    profile: Optional[str] = _profile_option,
) -> None:
    """Add or update tables in a connection (fetch → merge → update).

    Reads a JSON array of tables from stdin with the format:

    \b
    [
      {
        "db": "MY_DATABASE",
        "schema": "MY_SCHEMA",
        "table": "MY_TABLE",
        "type": "TABLE",
        "columns": [
          {"name": "COL1", "type": "VARCHAR"},
          {"name": "COL2", "type": "NUMBER"}
        ]
      }
    ]

    Fetches the current connection state (v2 connection/search — see
    'ts connections get'), merges the new tables in without delinking any
    existing tables, then POSTs the merged payload to the v2 update endpoint:
      POST /api/rest/2.0/connections/{connection_identifier}/update

    Output: JSON response from the update call.
    """
    try:
        new_tables: List[Dict[str, Any]] = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON on stdin: {e}")

    if not isinstance(new_tables, list):
        raise SystemExit("stdin must be a JSON array of table objects.")

    client = ThoughtSpotClient(resolve_profile(profile))

    # 1. Fetch current connection state via the v2 connection/search endpoint.
    #    Falls back to an empty hierarchy on any error, or when the connection's
    #    auth type (OAuth/PKCE) yields no server-side introspection.
    fetch_data: Dict[str, Any] = {}
    try:
        fetch_data = _fetch_connection_v2(client, connection_id)
    except Exception:
        # Error or unavailable — proceed with empty hierarchy (new tables only)
        print(
            "Warning: could not fetch existing connection state. "
            "Proceeding without preserving existing registered tables.",
            file=sys.stderr,
        )

    # 2. Merge new tables into the existing hierarchy
    merged = _merge_tables(fetch_data, new_tables)

    # 3. Update using the v2 endpoint (requires ThoughtSpot Cloud 10.4.0.cl+)
    #    Connection ID goes in the URL path; tables go inside data_warehouse_config.
    #    validate=True triggers ThoughtSpot to verify the table/column changes.
    update_resp = client.post(
        f"/api/rest/2.0/connections/{connection_id}/update",
        json={
            "data_warehouse_config": {
                "externalDatabases": merged,
            },
            "validate": True,
        },
    )
    print(json.dumps(update_resp.json()))


def _build_create_payload(
    name: str,
    account: str,
    user: str,
    role: str,
    warehouse: str,
    private_key: str,
    database: Optional[str] = None,
    description: str = "",
) -> Dict[str, Any]:
    """Build the POST /api/rest/2.0/connection/create body for a Snowflake
    key-pair connection (no tables).

    Mirrors the verified payload shape:
      - configuration carries accountName / user / role / warehouse and the
        private key under the ``private_key`` attribute (NOT ``privateKey``)
      - authenticationType is KEY_PAIR (required — the API defaults to
        SERVICE_ACCOUNT and rejects the key otherwise)
      - externalDatabases is empty and validate is false (tables are added
        later via ``ts tables create``)

    Pure function — no I/O — so it can be unit-tested without a live instance.
    """
    config: Dict[str, Any] = {
        "accountName": account,
        "user": user,
        "role": role,
        "warehouse": warehouse,
        "private_key": private_key,
    }
    if database:
        config["database"] = database
    return {
        "name": name,
        "description": description,
        "data_warehouse_type": "SNOWFLAKE",
        "data_warehouse_config": {
            "configuration": config,
            "authenticationType": "KEY_PAIR",
            "externalDatabases": [],
        },
        "validate": False,
    }


@app.command("create")
def create_connection(
    profile: Optional[str] = _profile_option,
    name: str = typer.Option(..., "--name", help="Unique name for the new connection"),
    account: str = typer.Option(..., "--account",
                                help="Snowflake account identifier (e.g. myorg-myaccount or account.region)"),
    user: str = typer.Option(..., "--user", help="Snowflake username"),
    role: str = typer.Option(..., "--role", help="Snowflake role (must see the target database/schema)"),
    warehouse: str = typer.Option(..., "--warehouse", help="Snowflake warehouse"),
    private_key_path: str = typer.Option(..., "--private-key-path",
                                         help="Path to the unencrypted PKCS#8 private key (.p8) for key-pair auth"),
    database: Optional[str] = typer.Option(None, "--database", help="Default database (optional)"),
    description: str = typer.Option("", "--description", help="Connection description"),
) -> None:
    """Create a Snowflake data connection using key-pair authentication.

    Creates an empty connection (no tables) via
    POST /api/rest/2.0/connection/create with authenticationType=KEY_PAIR and
    validate=false. Register tables afterwards with `ts tables create`
    (referencing this connection by its name).

    The private key is read from --private-key-path and sent to ThoughtSpot in
    the create payload; its value is never printed or logged. Use an unencrypted
    PKCS#8 (.p8) key whose matching public key is registered on the Snowflake
    user (DESC USER shows RSA_PUBLIC_KEY).

    Requires DATAMANAGEMENT or ADMINISTRATION privilege (CAN_CREATE_OR_EDIT_CONNECTIONS
    under RBAC).

    Output: JSON {id, name, data_warehouse_type} of the created connection.
    """
    import os

    key_path = os.path.expanduser(private_key_path)
    try:
        with open(key_path) as fh:
            pem = fh.read().strip()
    except OSError as e:
        raise SystemExit(f"Could not read private key at {private_key_path}: {e}")
    if not pem:
        raise SystemExit(f"Private key file is empty: {private_key_path}")

    payload = _build_create_payload(
        name, account, user, role, warehouse, pem, database, description
    )
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post("/api/rest/2.0/connection/create", json=payload)
    data = resp.json()
    print(json.dumps({
        "id": data.get("id"),
        "name": data.get("name"),
        "data_warehouse_type": data.get("data_warehouse_type"),
    }))


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------

def _merge_tables(
    fetch_response: Dict[str, Any],
    new_tables: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge new tables into the existing connection hierarchy.

    The fetchConnection response structure is:
      { "dataWarehouseInfo": { "databases": [...] } }

    Each database has { "name": ..., "schemas": [...] }
    Each schema has   { "name": ..., "tables":  [...] }
    Each table has    { "name": ..., "type": ..., "selected": true,
                        "linked": true, "columns": [...] }
    Each column has   { "name": ..., "type": ..., "selected": true,
                        "isLinkedActive": true }

    The update payload uses the same structure under the key
    "externalDatabases" (same as "databases" in the fetch response).

    Strategy:
      - All existing tables are preserved unchanged (selected=True, linked=True).
      - New tables that do not exist are added.
      - Existing tables that are being updated get new columns appended;
        existing columns are left unchanged.
    """
    # Extract the existing hierarchy — handle both possible response shapes
    dw_info = fetch_response.get("dataWarehouseInfo", {})
    existing_databases: List[Dict[str, Any]] = (
        dw_info.get("databases", [])
        or dw_info.get("externalDatabases", [])
        or fetch_response.get("databases", [])
        or fetch_response.get("externalDatabases", [])
    )

    # Build an index: (db, schema, table) → table_dict (mutable reference)
    # and (db, schema) → schema_dict, and db → db_dict
    db_index: Dict[str, Any] = {}       # db_name → db_dict
    schema_index: Dict[str, Any] = {}   # (db, schema) → schema_dict
    table_index: Dict[str, Any] = {}    # (db, schema, table) → table_dict

    for db in existing_databases:
        db_name = db["name"]
        db_index[db_name] = db
        for schema in db.get("schemas", []):
            schema_name = schema["name"]
            schema_index[(db_name, schema_name)] = schema
            for table in schema.get("tables", []):
                table_name = table["name"]
                table_index[(db_name, schema_name, table_name)] = table

    # Process each new table
    for entry in new_tables:
        db_name = entry["db"]
        schema_name = entry["schema"]
        table_name = entry["table"]
        table_type = entry.get("type", "TABLE")
        new_columns = entry.get("columns", [])

        key = (db_name, schema_name, table_name)

        if key in table_index:
            # Table exists — append any missing columns
            existing_table = table_index[key]
            existing_col_names = {c["name"] for c in existing_table.get("columns", [])}
            for col in new_columns:
                if col["name"] not in existing_col_names:
                    existing_table.setdefault("columns", []).append({
                        "name": col["name"],
                        "type": col.get("type", "VARCHAR"),
                        "selected": True,
                        "isLinkedActive": True,
                    })
        else:
            # Table is new — build it and insert into hierarchy
            new_table_obj = {
                "name": table_name,
                "type": table_type,
                "selected": True,
                "linked": True,
                "columns": [
                    {
                        "name": col["name"],
                        "type": col.get("type", "VARCHAR"),
                        "selected": True,
                        "isLinkedActive": True,
                    }
                    for col in new_columns
                ],
            }

            schema_key = (db_name, schema_name)
            if schema_key in schema_index:
                schema_index[schema_key].setdefault("tables", []).append(new_table_obj)
            else:
                # Schema is new — build it
                new_schema = {"name": schema_name, "tables": [new_table_obj]}
                if db_name in db_index:
                    db_index[db_name].setdefault("schemas", []).append(new_schema)
                else:
                    # Database is new — build it
                    new_db = {
                        "name": db_name,
                        "isAutoCreated": False,
                        "schemas": [new_schema],
                    }
                    existing_databases.append(new_db)
                    db_index[db_name] = new_db
                schema_index[schema_key] = new_schema

            table_index[key] = new_table_obj

    return existing_databases
