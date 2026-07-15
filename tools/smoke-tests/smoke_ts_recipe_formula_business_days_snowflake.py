#!/usr/bin/env python3
"""
smoke_ts_recipe_formula_business_days_snowflake.py — live smoke test for
ts-recipe-formula-business-days-snowflake.

Deploys the three business-day UDFs from the skill's single-source DDL template
(references/business-day-udfs.sql) via `ts snowflake exec` — the same command
the skill uses at runtime (BL-079) — verifies their return values against
known-good inputs, then drops them.

Steps:
  1.  Load Snowflake profile (existence check)
  2.  Deploy all three UDFs via `ts snowflake exec -f <template> --var ...`
  3.  Verify get_business_days_clamped(Mon→Fri exclusive) = 4
  4.  Verify get_business_days_clamped(Mon→Fri inclusive) = 5
  5.  Verify weekend clamping: Sat→Mon exclusive = 0 business days
  6.  Verify get_business_minutes_clamped(Mon 09:00→Tue 09:00) = 1440
  7.  Verify get_business_duration_str(Mon 09:00→Tue 09:00) = '24:00'
  8.  Cleanup — drop all three UDFs

Usage:
    python tools/smoke-tests/smoke_ts_recipe_formula_business_days_snowflake.py \\
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
    SmokeTestResult, load_sf_profile, recipe_arg_parser,
    ts_snowflake_exec, ts_snowflake_scalar, ts_snowflake_drop_udfs,
)

# Single-source DDL template the skill ships and deploys.
_SQL_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "agents/cli/ts-recipe-formula-business-days-snowflake/references/business-day-udfs.sql"
)


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------

def _step_deploy(sf_profile, db, schema):
    ts_snowflake_exec(
        sf_profile,
        file=_SQL_TEMPLATE,
        variables={"target_db": db, "target_schema": schema},
    )


def _step_verify_days(sf_profile, db, schema):
    # Mon 2026-01-05 → Fri 2026-01-09, exclusive → 4 business days
    result = ts_snowflake_scalar(
        sf_profile,
        f"SELECT {db}.{schema}.get_business_days_clamped("
        f"'2026-01-05'::TIMESTAMP, '2026-01-09'::TIMESTAMP, FALSE)",
    )
    if int(result) != 4:
        raise RuntimeError(f"Expected 4, got {result!r}")


def _step_verify_inclusive(sf_profile, db, schema):
    # Mon 2026-01-05 → Fri 2026-01-09, inclusive → 5 business days
    result = ts_snowflake_scalar(
        sf_profile,
        f"SELECT {db}.{schema}.get_business_days_clamped("
        f"'2026-01-05'::TIMESTAMP, '2026-01-09'::TIMESTAMP, TRUE)",
    )
    if int(result) != 5:
        raise RuntimeError(f"Expected 5 (inclusive), got {result!r}")


def _step_verify_weekend_clamping(sf_profile, db, schema):
    # Sat 2026-01-03 → Mon 2026-01-05, exclusive.
    # Sat clamps forward to Mon; Mon is the end → 0 business days between them.
    result = ts_snowflake_scalar(
        sf_profile,
        f"SELECT {db}.{schema}.get_business_days_clamped("
        f"'2026-01-03'::TIMESTAMP, '2026-01-05'::TIMESTAMP, FALSE)",
    )
    if int(result) != 0:
        raise RuntimeError(f"Expected 0 (Sat→Mon exclusive, clamped), got {result!r}")


def _step_verify_minutes(sf_profile, db, schema):
    # Mon 09:00 → Tue 09:00 = 1 full business day = 1440 minutes
    result = ts_snowflake_scalar(
        sf_profile,
        f"SELECT {db}.{schema}.get_business_minutes_clamped("
        f"'2026-01-05 09:00:00'::TIMESTAMP, '2026-01-06 09:00:00'::TIMESTAMP)",
    )
    if int(result) != 1440:
        raise RuntimeError(f"Expected 1440, got {result!r}")


def _step_verify_duration_str(sf_profile, db, schema):
    # Mon 09:00 → Tue 09:00 = "24:00"
    result = ts_snowflake_scalar(
        sf_profile,
        f"SELECT {db}.{schema}.get_business_duration_str("
        f"'2026-01-05 09:00:00'::TIMESTAMP, '2026-01-06 09:00:00'::TIMESTAMP)",
    )
    if str(result) != "24:00":
        raise RuntimeError(f"Expected '24:00', got {result!r}")


def _drop_udfs(sf_profile, db, schema):
    fqn = f"{db}.{schema}"
    ts_snowflake_drop_udfs(sf_profile, [
        f"{fqn}.get_business_duration_str(TIMESTAMP, TIMESTAMP)",
        f"{fqn}.get_business_days_clamped(TIMESTAMP, TIMESTAMP, BOOLEAN)",
        f"{fqn}.get_business_minutes_clamped(TIMESTAMP, TIMESTAMP)",
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_smoke_test(sf_profile_name: str, db: str, schema: str, no_cleanup: bool) -> int:
    fqn = f"{db}.{schema}"
    print(f"\nSmoke test: ts-recipe-formula-business-days-snowflake")
    print(f"  Snowflake profile : {sf_profile_name}")
    print(f"  Target schema     : {fqn}\n")

    r = SmokeTestResult()

    ok, _ = r.step("Load Snowflake profile", load_sf_profile, sf_profile_name)
    if not ok:
        return r.summary()

    ok, _ = r.step(
        f"Deploy 3 UDFs via ts snowflake exec into {fqn}",
        _step_deploy, sf_profile_name, db, schema,
    )
    deployed = ok

    if deployed:
        r.step("Verify days: Mon→Fri exclusive = 4",
               _step_verify_days, sf_profile_name, db, schema)
        r.step("Verify days: Mon→Fri inclusive = 5",
               _step_verify_inclusive, sf_profile_name, db, schema)
        r.step("Verify weekend clamping: Sat→Mon exclusive = 0",
               _step_verify_weekend_clamping, sf_profile_name, db, schema)
        r.step("Verify minutes: Mon 09:00→Tue 09:00 = 1440",
               _step_verify_minutes, sf_profile_name, db, schema)
        r.step("Verify duration_str: Mon 09:00→Tue 09:00 = '24:00'",
               _step_verify_duration_str, sf_profile_name, db, schema)

    # Cleanup
    if deployed and not no_cleanup:
        r.step(f"Cleanup — drop UDFs from {fqn}",
               _drop_udfs, sf_profile_name, db, schema)
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
