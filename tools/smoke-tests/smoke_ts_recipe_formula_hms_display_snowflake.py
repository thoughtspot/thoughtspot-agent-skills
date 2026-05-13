#!/usr/bin/env python3
"""
smoke_ts_recipe_formula_hms_display_snowflake.py — live smoke test for
ts-recipe-formula-hms-display-snowflake.

Creates the four duration-display UDFs in the target schema, verifies their
return values against known-good inputs, then drops them.

Steps:
  1.  Load Snowflake profile (CLI method only)
  2.  Create format_seconds_to_hms
  3.  Create format_seconds_to_dhms
  4.  Create format_minutes_to_hm
  5.  Create format_minutes_to_dhm
  6.  Verify format_seconds_to_hms(3665) = '01:01:05'
  7.  Verify format_seconds_to_dhms(90061) = '01:01:01:01'
  8.  Verify format_minutes_to_hm(65) = '01:05'
  9.  Verify format_minutes_to_dhm(1501) = '01:01:01'
  10. Cleanup — drop all four UDFs

Usage:
    python tools/smoke-tests/smoke_ts_recipe_formula_hms_display_snowflake.py \\
        --sf-profile MY_SF_PROFILE \\
        --sf-target-db MY_DB \\
        --sf-target-schema MY_SCHEMA \\
        [--ts-profile ignored] \\
        [--no-cleanup]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, load_sf_profile, get_snow_cmd, snow_json, snow_exec  # noqa: E402


# ---------------------------------------------------------------------------
# UDF DDL
# ---------------------------------------------------------------------------

def _ddl_hms(db: str, schema: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {db}.{schema}.format_seconds_to_hms(seconds INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(seconds / 3600)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 3600) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(seconds, 60)::STRING, 2, '0')
$$
""".strip()


def _ddl_dhms(db: str, schema: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {db}.{schema}.format_seconds_to_dhms(seconds INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(seconds / 86400)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 86400) / 3600)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(seconds, 3600) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(seconds, 60)::STRING, 2, '0')
$$
""".strip()


def _ddl_hm(db: str, schema: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {db}.{schema}.format_minutes_to_hm(minutes INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(minutes / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(minutes, 60)::STRING, 2, '0')
$$
""".strip()


def _ddl_dhm(db: str, schema: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {db}.{schema}.format_minutes_to_dhm(minutes INT)
RETURNS STRING
AS
$$
    LPAD(TRUNC(minutes / 1440)::STRING, 2, '0') || ':' ||
    LPAD(TRUNC(MOD(minutes, 1440) / 60)::STRING, 2, '0') || ':' ||
    LPAD(MOD(minutes, 60)::STRING, 2, '0')
$$
""".strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_udf(snow_cmd: str, cli_conn: str, ddl: str, name: str) -> None:
    import tempfile, os
    tmp = Path(tempfile.mktemp(suffix=".sql"))
    tmp.write_text(ddl)
    try:
        import subprocess
        r = subprocess.run(
            [snow_cmd, "sql", "-c", cli_conn, "-f", str(tmp)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    finally:
        tmp.unlink(missing_ok=True)


def _query_scalar(snow_cmd: str, cli_conn: str, sql: str):
    rows = snow_json(snow_cmd, cli_conn, sql)
    if not rows:
        raise RuntimeError(f"Query returned no rows: {sql}")
    return list(rows[0].values())[0]


def _drop_udfs(snow_cmd: str, cli_conn: str, db: str, schema: str) -> None:
    fqn = f"{db}.{schema}"
    for sig in [
        f"{fqn}.format_seconds_to_hms(INT)",
        f"{fqn}.format_seconds_to_dhms(INT)",
        f"{fqn}.format_minutes_to_hm(INT)",
        f"{fqn}.format_minutes_to_dhm(INT)",
    ]:
        try:
            snow_exec(snow_cmd, cli_conn, f"DROP FUNCTION IF EXISTS {sig}")
        except Exception:
            pass  # best-effort cleanup


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def _step_load_profile(sf_profile_name: str):
    return load_sf_profile(sf_profile_name)


def _step_check_cli_method(profile: dict) -> tuple[str, str]:
    method = profile.get("method", "")
    if method != "cli":
        raise RuntimeError(
            f"Profile method is '{method}' — smoke tests require method: cli. "
            "Create a CLI-method Snowflake profile via /ts-profile-snowflake."
        )
    cli_conn = profile.get("cli_connection")
    if not cli_conn:
        raise RuntimeError("Profile has no 'cli_connection' field.")
    return get_snow_cmd(profile), cli_conn


def _step_create(snow_cmd, cli_conn, ddl, name):
    _create_udf(snow_cmd, cli_conn, ddl, name)


def _step_verify_hms(snow_cmd, cli_conn, db, schema):
    # 3665s = 1h 1m 5s → '01:01:05'
    sql = f"SELECT {db}.{schema}.format_seconds_to_hms(3665)"
    result = _query_scalar(snow_cmd, cli_conn, sql)
    if str(result) != "01:01:05":
        raise RuntimeError(f"Expected '01:01:05', got {result!r}")


def _step_verify_dhms(snow_cmd, cli_conn, db, schema):
    # 90061s = 1d 1h 1m 1s → '01:01:01:01'
    sql = f"SELECT {db}.{schema}.format_seconds_to_dhms(90061)"
    result = _query_scalar(snow_cmd, cli_conn, sql)
    if str(result) != "01:01:01:01":
        raise RuntimeError(f"Expected '01:01:01:01', got {result!r}")


def _step_verify_hm(snow_cmd, cli_conn, db, schema):
    # 65m = 1h 5m → '01:05'
    sql = f"SELECT {db}.{schema}.format_minutes_to_hm(65)"
    result = _query_scalar(snow_cmd, cli_conn, sql)
    if str(result) != "01:05":
        raise RuntimeError(f"Expected '01:05', got {result!r}")


def _step_verify_dhm(snow_cmd, cli_conn, db, schema):
    # 1501m = 1d 1h 1m → '01:01:01'
    sql = f"SELECT {db}.{schema}.format_minutes_to_dhm(1501)"
    result = _query_scalar(snow_cmd, cli_conn, sql)
    if str(result) != "01:01:01":
        raise RuntimeError(f"Expected '01:01:01', got {result!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_smoke_test(sf_profile_name: str, db: str, schema: str, no_cleanup: bool) -> int:
    fqn = f"{db}.{schema}"
    print(f"\nSmoke test: ts-recipe-formula-hms-display-snowflake")
    print(f"  Snowflake profile : {sf_profile_name}")
    print(f"  Target schema     : {fqn}\n")

    r = SmokeTestResult()
    snow_cmd = "snow"
    cli_conn = ""

    ok, profile = r.step("Load Snowflake profile", _step_load_profile, sf_profile_name)
    if not ok:
        return r.summary()

    ok, (snow_cmd, cli_conn) = r.step(
        "Check CLI method", _step_check_cli_method, profile
    )
    if not ok:
        return r.summary()

    # Create all four UDFs (independent — no ordering requirement)
    created = []
    for udf_name, ddl_fn in [
        ("format_seconds_to_hms",  _ddl_hms),
        ("format_seconds_to_dhms", _ddl_dhms),
        ("format_minutes_to_hm",   _ddl_hm),
        ("format_minutes_to_dhm",  _ddl_dhm),
    ]:
        ok, _ = r.step(
            f"Create {udf_name} in {fqn}",
            _step_create, snow_cmd, cli_conn, ddl_fn(db, schema), udf_name
        )
        if ok:
            created.append(udf_name)

    # Verify each created UDF
    verify_steps = [
        ("format_seconds_to_hms",  "Verify hms: 3665s = '01:01:05'",    _step_verify_hms),
        ("format_seconds_to_dhms", "Verify dhms: 90061s = '01:01:01:01'", _step_verify_dhms),
        ("format_minutes_to_hm",   "Verify hm: 65m = '01:05'",          _step_verify_hm),
        ("format_minutes_to_dhm",  "Verify dhm: 1501m = '01:01:01'",    _step_verify_dhm),
    ]
    for udf_name, label, step_fn in verify_steps:
        if udf_name in created:
            r.step(label, step_fn, snow_cmd, cli_conn, db, schema)

    # Cleanup
    if not no_cleanup and cli_conn:
        r.step(
            f"Cleanup — drop UDFs from {fqn}",
            _drop_udfs, snow_cmd, cli_conn, db, schema
        )
    elif no_cleanup:
        r.info(f"--no-cleanup: UDFs left in {fqn}")

    return r.summary()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sf-profile", required=True,
                        help="Snowflake CLI profile name from ~/.claude/snowflake-profiles.json")
    parser.add_argument("--sf-target-db", required=True,
                        help="Snowflake database to create UDFs in")
    parser.add_argument("--sf-target-schema", required=True,
                        help="Snowflake schema to create UDFs in")
    parser.add_argument("--ts-profile", default=None,
                        help="Ignored — accepted for runner compatibility")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Skip the DROP FUNCTION cleanup step")
    args = parser.parse_args()
    return run_smoke_test(
        args.sf_profile, args.sf_target_db, args.sf_target_schema, args.no_cleanup
    )


if __name__ == "__main__":
    sys.exit(main())
