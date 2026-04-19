#!/usr/bin/env python3
"""
smoke_ts_model_builder.py — live smoke test for ts-model-builder.

Verifies the full path:
  1. ThoughtSpot auth
  2. ts connections list — at least one Snowflake connection returned
  3. ts connections get {connection_name} — full hierarchy returned
  4. Build a minimal table TML for a known table
  5. Validate TML structure with check_tml
  6. ts tables create — GUID returned
  7. ts metadata search confirms the table object exists
  8. Cleanup: ts metadata delete (unless --no-cleanup)

Usage:
    python tools/smoke-tests/smoke_ts_model_builder.py \\
        --ts-profile production \\
        --connection-name "My Snowflake Connection" \\
        --db MY_DB \\
        --schema MY_SCHEMA \\
        --table MY_TEST_TABLE \\
        [--no-cleanup]

The specified table must exist as a physical table in Snowflake and be accessible
via the ThoughtSpot connection.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools" / "validate"))
sys.path.insert(0, str(_REPO_ROOT / "tools" / "ts-cli"))
sys.path.insert(0, str(Path(__file__).parent))

try:
    import yaml
except ImportError:
    yaml = None  # yaml only needed for TML validation step

from check_tml import validate_table_tml  # noqa: E402
from _common import (  # noqa: E402
    SmokeTestResult, SkipStep,
    ts_auth_check, run_ts,
)


# ---------------------------------------------------------------------------
# TML builders (simplified — not using _build_table_tml from ts_cli to keep
# the smoke test self-contained and independent of ts-cli internals)
# ---------------------------------------------------------------------------

def _build_test_table_tml(
    connection_name: str,
    db: str,
    schema: str,
    table: str,
) -> dict:
    """Build a minimal Table TML dict (for structural validation)."""
    return {
        "table": {
            "name": f"{db}_{schema}_{table}_SMOKE_TEST",
            "db": db,
            "schema": schema,
            "db_table": table,
            "connection": {
                "name": connection_name,
            },
            "columns": [
                {
                    "name": "SMOKE_TEST_COLUMN",
                    "db_column_name": "SMOKE_TEST_COLUMN",
                    "properties": {
                        "column_type": "ATTRIBUTE",
                    },
                    "db_column_properties": {
                        "data_type": "VARCHAR",
                    },
                }
            ],
        }
    }


def _build_tables_create_spec(
    connection_name: str,
    db: str,
    schema: str,
    table: str,
    logical_name: str,
) -> list[dict]:
    """Build the JSON spec for ts tables create (reads from stdin)."""
    return [
        {
            "name": logical_name,
            "db": db,
            "schema": schema,
            "db_table": table,
            "connection_name": connection_name,
            "columns": [
                {
                    "name": "PROCEDURE_NAME",
                    "data_type": "VARCHAR",
                    "column_type": "ATTRIBUTE",
                },
            ],
        }
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test: ts-model-builder."
    )
    parser.add_argument(
        "--ts-profile", required=True,
        help="ThoughtSpot profile name",
    )
    parser.add_argument(
        "--connection-name", required=True,
        help="Display name of the ThoughtSpot Snowflake connection to test",
    )
    parser.add_argument(
        "--db", required=True,
        help="Snowflake database name (uppercase)",
    )
    parser.add_argument(
        "--schema", required=True,
        help="Snowflake schema name (uppercase)",
    )
    parser.add_argument(
        "--table", required=True,
        help="Physical Snowflake table name to create a logical table object for",
    )
    parser.add_argument(
        "--no-cleanup", action="store_true",
        help="Keep the created ThoughtSpot table object after the test.",
    )
    args = parser.parse_args()

    r = SmokeTestResult()

    print()
    print("=" * 60)
    print("Smoke test: ts-model-builder")
    print("=" * 60)
    print(f"  ThoughtSpot profile:  {args.ts_profile}")
    print(f"  Connection:           {args.connection_name}")
    print(f"  Table:                {args.db}.{args.schema}.{args.table}")
    print()

    # ── ThoughtSpot auth ──────────────────────────────────────────────────────
    ok, whoami = r.step("ThoughtSpot auth (ts auth whoami)", ts_auth_check, args.ts_profile)
    if not ok:
        return r.summary()
    r.info(f"Authenticated as: {whoami.get('display_name', whoami.get('name', '?'))}")

    # ── ts connections list ───────────────────────────────────────────────────
    def _list_connections():
        result = run_ts(["connections", "list", "--type", "SNOWFLAKE"], args.ts_profile)
        if not isinstance(result, list) or not result:
            raise RuntimeError(
                "ts connections list returned no Snowflake connections. "
                "Ensure a Snowflake connection exists and the profile has access."
            )
        return result

    ok, connections = r.step("ts connections list --type SNOWFLAKE", _list_connections)
    if not ok:
        return r.summary()
    r.info(f"Found {len(connections)} Snowflake connection(s)")

    # Verify the requested connection exists
    conn_match = [
        c for c in connections
        if c.get("name") == args.connection_name
        or c.get("metadata_name") == args.connection_name
    ]
    if not conn_match:
        available = [c.get("name") or c.get("metadata_name") for c in connections]
        r.failures.append(
            f"Connection '{args.connection_name}' not found. Available: {available}"
        )
        return r.summary()

    conn_id = conn_match[0].get("id") or conn_match[0].get("metadata_id")
    r.info(f"Connection ID: {conn_id}")

    # ── ts connections get (full schema hierarchy) ────────────────────────────
    # Note: uses v1 API (/tspublic/v1/connection/fetchConnection) which is not
    # available on all instances. Skipped gracefully if the endpoint returns 404.
    def _get_connection():
        try:
            result = run_ts(["connections", "get", args.connection_name], args.ts_profile)
        except RuntimeError as e:
            if "404" in str(e):
                raise SkipStep(
                    "v1 fetchConnection endpoint not available on this instance "
                    "(404). Skipping hierarchy check."
                )
            raise
        if not isinstance(result, dict):
            raise RuntimeError(
                f"ts connections get returned unexpected type: {type(result).__name__}"
            )
        databases = result.get("databases") or result.get("data", {}).get("databases", [])
        return result, databases

    ok, conn_result = r.step(
        f"ts connections get '{args.connection_name}'", _get_connection
    )
    if ok and conn_result:
        _, databases = conn_result
        r.info(f"Connection has {len(databases)} database(s) in hierarchy")

    # ── Build and validate Table TML ─────────────────────────────────────────
    table_tml = _build_test_table_tml(
        args.connection_name, args.db, args.schema, args.table
    )
    table_name = table_tml["table"]["name"]

    def _validate_tml():
        errors = validate_table_tml(table_tml)
        if errors:
            raise RuntimeError(
                f"{len(errors)} TML validation error(s):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    ok, _ = r.step("Validate Table TML structure (check_tml)", _validate_tml)
    if not ok:
        return r.summary()

    # ── ts tables create ──────────────────────────────────────────────────────
    # ts tables create reads a JSON spec array from stdin (no --file option).
    created_guid: str | None = None
    create_spec = _build_tables_create_spec(
        args.connection_name, args.db, args.schema, args.table, table_name
    )
    spec_json = json.dumps(create_spec)

    def _create_table():
        import subprocess as _sp
        cmd = ["ts", "tables", "create", "--profile", args.ts_profile]
        result = _sp.run(cmd, input=spec_json, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ts tables create failed:\n{result.stderr.strip() or result.stdout.strip()}"
            )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"ts tables create returned non-JSON:\n{result.stdout[:200]}"
            ) from e

        # Result format: {table_name: guid}
        if isinstance(parsed, dict):
            guid = parsed.get(table_name) or next(iter(parsed.values()), None)
            if guid:
                return str(guid)

        raise RuntimeError(
            f"Could not extract GUID from ts tables create response: "
            f"{json.dumps(parsed)[:300]}"
        )

    ok, created_guid = r.step(f"ts tables create '{table_name}'", _create_table)
    if ok:
        r.info(f"Created table GUID: {created_guid}")

    # ── Verify table appears in metadata search ───────────────────────────────
    if created_guid:
        def _verify():
            results = run_ts(
                ["metadata", "search", "--subtype", "ONE_TO_ONE_LOGICAL",
                 "--name", f"%{table_name}%"],
                args.ts_profile,
            )
            found = [
                item for item in results
                if item.get("metadata_id") == created_guid
                or item.get("id") == created_guid
            ]
            if not found:
                # May not be indexed yet
                raise RuntimeError(
                    f"Table GUID {created_guid} not found in metadata search. "
                    "Indexing may be delayed — the table was created but search is slow."
                )
            return found[0]

        ok, table_meta = r.step(
            f"Verify '{table_name}' appears in ThoughtSpot metadata", _verify
        )
        if ok and table_meta:
            r.info(f"Table name: {table_meta.get('metadata_name')}")

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if created_guid:
        if args.no_cleanup:
            r.info(f"Skipping cleanup (--no-cleanup). GUID: {created_guid}")
        else:
            def _cleanup():
                run_ts(["metadata", "delete", created_guid], args.ts_profile)

            r.step(
                f"Cleanup: delete '{table_name}' from ThoughtSpot", _cleanup
            )

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
