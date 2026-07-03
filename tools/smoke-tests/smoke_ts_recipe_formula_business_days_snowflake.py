#!/usr/bin/env python3
"""
smoke_ts_setup_snowflake_udfs_business_days.py — live smoke test for
ts-setup-snowflake-udfs-business-days.

Creates the three business-day UDFs in the target schema, verifies their
return values against known-good inputs, then drops them.

Steps:
  1.  Load Snowflake profile (CLI method only)
  2.  Create get_business_minutes_clamped
  3.  Create get_business_days_clamped
  4.  Create get_business_duration_str (depends on step 2)
  5.  Verify get_business_days_clamped(Mon→Fri exclusive) = 4
  6.  Verify get_business_minutes_clamped(Mon 09:00→Tue 09:00) = 1440
  7.  Verify get_business_duration_str(Mon 09:00→Tue 09:00) = '24:00'
  8.  Verify weekend clamping: Sat→Mon exclusive = 0 business days
  9.  Cleanup — drop all three UDFs

Usage:
    python tools/smoke-tests/smoke_ts_setup_snowflake_udfs_business_days.py \\
        --sf-profile MY_SF_PROFILE \\
        --sf-target-db MY_DB \\
        --sf-target-schema MY_SCHEMA \\
        [--ts-profile ignored] \\
        [--no-cleanup]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import (  # noqa: E402
    SmokeTestResult, load_sf_profile, check_sf_cli_method,
    create_udf, query_scalar, drop_udfs, recipe_arg_parser,
)


# ---------------------------------------------------------------------------
# UDF DDL
# ---------------------------------------------------------------------------

def _ddl_minutes(db: str, schema: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {db}.{schema}.get_business_minutes_clamped(
    start_ts TIMESTAMP, end_ts TIMESTAMP
)
RETURNS INT
AS
$$
    DATEDIFF('minute',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('second', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('second', -1, DATEADD('day', -1, DATE_TRUNC('day', end_ts)))
            ELSE end_ts
        END
    )
    - (DATEDIFF('week',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('second', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('second', -1, DATEADD('day', -1, DATE_TRUNC('day', end_ts)))
            ELSE end_ts
        END
    ) * 2 * 1440)
$$
""".strip()


def _ddl_days(db: str, schema: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {db}.{schema}.get_business_days_clamped(
    start_ts TIMESTAMP, end_ts TIMESTAMP, inclusive BOOLEAN
)
RETURNS INT
AS
$$
    (DATEDIFF('day',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('day', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('day', -2, DATE_TRUNC('day', end_ts))
            ELSE end_ts
        END
    ) + CASE WHEN inclusive THEN 1 ELSE 0 END)
    - (DATEDIFF('week',
        CASE
            WHEN DAYNAME(start_ts) = 'Sat' THEN DATEADD('day', 2, DATE_TRUNC('day', start_ts))
            WHEN DAYNAME(start_ts) = 'Sun' THEN DATEADD('day', 1, DATE_TRUNC('day', start_ts))
            ELSE start_ts
        END,
        CASE
            WHEN DAYNAME(end_ts) = 'Sat' THEN DATEADD('day', -1, DATE_TRUNC('day', end_ts))
            WHEN DAYNAME(end_ts) = 'Sun' THEN DATEADD('day', -2, DATE_TRUNC('day', end_ts))
            ELSE end_ts
        END
    ) * 2)
$$
""".strip()


def _ddl_duration_str(db: str, schema: str) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {db}.{schema}.get_business_duration_str(
    start_ts TIMESTAMP, end_ts TIMESTAMP
)
RETURNS STRING
AS
$$
    FLOOR({db}.{schema}.get_business_minutes_clamped(start_ts, end_ts) / 60)
    || ':'
    || LPAD(MOD({db}.{schema}.get_business_minutes_clamped(start_ts, end_ts), 60), 2, '0')
$$
""".strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# UDF deploy (create_udf), scalar query (query_scalar), CLI-method check
# (check_sf_cli_method), and cleanup (drop_udfs) are shared across all
# ts-recipe-formula-*-snowflake smoke tests — see tools/smoke-tests/_common.py.
# Only the signature list for cleanup is skill-specific.

def _drop_udfs(snow_cmd: str, cli_conn: str, db: str, schema: str) -> None:
    fqn = f"{db}.{schema}"
    drop_udfs(snow_cmd, cli_conn, [
        f"{fqn}.get_business_duration_str(TIMESTAMP, TIMESTAMP)",
        f"{fqn}.get_business_days_clamped(TIMESTAMP, TIMESTAMP, BOOLEAN)",
        f"{fqn}.get_business_minutes_clamped(TIMESTAMP, TIMESTAMP)",
    ])


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def _step_verify_days(snow_cmd, cli_conn, db, schema):
    # Mon 2026-01-05 → Fri 2026-01-09, exclusive → 4 business days
    sql = (f"SELECT {db}.{schema}.get_business_days_clamped("
           f"'2026-01-05'::TIMESTAMP, '2026-01-09'::TIMESTAMP, FALSE)")
    result = query_scalar(snow_cmd, cli_conn, sql)
    if int(result) != 4:
        raise RuntimeError(f"Expected 4, got {result!r}")


def _step_verify_minutes(snow_cmd, cli_conn, db, schema):
    # Mon 09:00 → Tue 09:00 = 1 full business day = 1440 minutes
    sql = (f"SELECT {db}.{schema}.get_business_minutes_clamped("
           f"'2026-01-05 09:00:00'::TIMESTAMP, '2026-01-06 09:00:00'::TIMESTAMP)")
    result = query_scalar(snow_cmd, cli_conn, sql)
    if int(result) != 1440:
        raise RuntimeError(f"Expected 1440, got {result!r}")


def _step_verify_duration_str(snow_cmd, cli_conn, db, schema):
    # Mon 09:00 → Tue 09:00 = "24:00"
    sql = (f"SELECT {db}.{schema}.get_business_duration_str("
           f"'2026-01-05 09:00:00'::TIMESTAMP, '2026-01-06 09:00:00'::TIMESTAMP)")
    result = query_scalar(snow_cmd, cli_conn, sql)
    if str(result) != "24:00":
        raise RuntimeError(f"Expected '24:00', got {result!r}")


def _step_verify_weekend_clamping(snow_cmd, cli_conn, db, schema):
    # Sat 2026-01-03 → Mon 2026-01-05, exclusive.
    # Sat clamps forward to Mon; Mon is the end → 0 business days between them.
    sql = (f"SELECT {db}.{schema}.get_business_days_clamped("
           f"'2026-01-03'::TIMESTAMP, '2026-01-05'::TIMESTAMP, FALSE)")
    result = query_scalar(snow_cmd, cli_conn, sql)
    if int(result) != 0:
        raise RuntimeError(
            f"Expected 0 (Sat→Mon exclusive, clamped), got {result!r}"
        )


def _step_verify_inclusive(snow_cmd, cli_conn, db, schema):
    # Mon 2026-01-05 → Fri 2026-01-09, inclusive → 5 business days
    sql = (f"SELECT {db}.{schema}.get_business_days_clamped("
           f"'2026-01-05'::TIMESTAMP, '2026-01-09'::TIMESTAMP, TRUE)")
    result = query_scalar(snow_cmd, cli_conn, sql)
    if int(result) != 5:
        raise RuntimeError(f"Expected 5 (inclusive), got {result!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_smoke_test(sf_profile_name: str, db: str, schema: str, no_cleanup: bool) -> int:
    fqn = f"{db}.{schema}"
    print(f"\nSmoke test: ts-setup-snowflake-udfs-business-days")
    print(f"  Snowflake profile : {sf_profile_name}")
    print(f"  Target schema     : {fqn}\n")

    r = SmokeTestResult()
    snow_cmd = "snow"
    cli_conn = ""

    ok, profile = r.step("Load Snowflake profile", load_sf_profile, sf_profile_name)
    if not ok:
        return r.summary()

    ok, (snow_cmd, cli_conn) = r.step(
        "Check CLI method", check_sf_cli_method, profile
    )
    if not ok:
        return r.summary()

    # Create UDFs in dependency order
    created = []
    ok, _ = r.step(
        f"Create get_business_minutes_clamped in {fqn}",
        create_udf, snow_cmd, cli_conn, _ddl_minutes(db, schema)
    )
    if ok:
        created.append("minutes")

    ok, _ = r.step(
        f"Create get_business_days_clamped in {fqn}",
        create_udf, snow_cmd, cli_conn, _ddl_days(db, schema)
    )
    if ok:
        created.append("days")

    # duration_str depends on minutes — skip if minutes creation failed
    if "minutes" in created:
        ok, _ = r.step(
            f"Create get_business_duration_str in {fqn}",
            create_udf, snow_cmd, cli_conn, _ddl_duration_str(db, schema)
        )
        if ok:
            created.append("duration_str")

    # Verify correctness
    if "days" in created:
        r.step(
            "Verify days: Mon→Fri exclusive = 4",
            _step_verify_days, snow_cmd, cli_conn, db, schema
        )
        r.step(
            "Verify days: Mon→Fri inclusive = 5",
            _step_verify_inclusive, snow_cmd, cli_conn, db, schema
        )
        r.step(
            "Verify weekend clamping: Sat→Mon exclusive = 0",
            _step_verify_weekend_clamping, snow_cmd, cli_conn, db, schema
        )

    if "minutes" in created:
        r.step(
            "Verify minutes: Mon 09:00→Tue 09:00 = 1440",
            _step_verify_minutes, snow_cmd, cli_conn, db, schema
        )

    if "duration_str" in created:
        r.step(
            "Verify duration_str: Mon 09:00→Tue 09:00 = '24:00'",
            _step_verify_duration_str, snow_cmd, cli_conn, db, schema
        )

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
    parser = recipe_arg_parser(__doc__)
    args = parser.parse_args()
    return run_smoke_test(
        args.sf_profile, args.sf_target_db, args.sf_target_schema, args.no_cleanup
    )


if __name__ == "__main__":
    sys.exit(main())
