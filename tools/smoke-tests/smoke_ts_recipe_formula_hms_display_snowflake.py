#!/usr/bin/env python3
"""
smoke_ts_recipe_formula_hms_display_snowflake.py — live smoke test for
ts-recipe-formula-hms-display-snowflake.

Deploys the four duration-display UDFs from the skill's single-source DDL
template (references/duration-udfs.sql) via `ts snowflake exec` — the same
command the skill uses at runtime (BL-079) — verifies their return values
against known-good inputs, then drops them.

Steps:
  1.  Load Snowflake profile (existence check)
  2.  Deploy all four UDFs via `ts snowflake exec -f <template> --var ...`
  3.  Verify format_seconds_to_hms(3665)   = '01:01:05'
  4.  Verify format_seconds_to_dhms(90061) = '01:01:01:01'
  5.  Verify format_minutes_to_hm(65)      = '01:05'
  6.  Verify format_minutes_to_dhm(1501)   = '01:01:01'
  7.  Cleanup — drop all four UDFs

Usage:
    python tools/smoke-tests/smoke_ts_recipe_formula_hms_display_snowflake.py \\
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
    / "agents/cli/ts-recipe-formula-hms-display-snowflake/references/duration-udfs.sql"
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


def _verify(sf_profile, db, schema, fn, arg, expected):
    result = ts_snowflake_scalar(sf_profile, f"SELECT {db}.{schema}.{fn}({arg})")
    if str(result) != expected:
        raise RuntimeError(f"{fn}({arg}): expected {expected!r}, got {result!r}")


def _drop_udfs(sf_profile, db, schema):
    fqn = f"{db}.{schema}"
    ts_snowflake_drop_udfs(sf_profile, [
        f"{fqn}.format_seconds_to_hms(INT)",
        f"{fqn}.format_seconds_to_dhms(INT)",
        f"{fqn}.format_minutes_to_hm(INT)",
        f"{fqn}.format_minutes_to_dhm(INT)",
    ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_smoke_test(sf_profile_name: str, db: str, schema: str, no_cleanup: bool) -> int:
    fqn = f"{db}.{schema}"
    print(f"\nSmoke test: ts-recipe-formula-hms-display-snowflake")
    print(f"  Snowflake profile : {sf_profile_name}")
    print(f"  Target schema     : {fqn}\n")

    r = SmokeTestResult()

    ok, _ = r.step("Load Snowflake profile", load_sf_profile, sf_profile_name)
    if not ok:
        return r.summary()

    ok, _ = r.step(
        f"Deploy 4 UDFs via ts snowflake exec into {fqn}",
        _step_deploy, sf_profile_name, db, schema,
    )
    deployed = ok

    if deployed:
        r.step("Verify format_seconds_to_hms(3665) = '01:01:05'",
               _verify, sf_profile_name, db, schema, "format_seconds_to_hms", "3665", "01:01:05")
        r.step("Verify format_seconds_to_dhms(90061) = '01:01:01:01'",
               _verify, sf_profile_name, db, schema, "format_seconds_to_dhms", "90061", "01:01:01:01")
        r.step("Verify format_minutes_to_hm(65) = '01:05'",
               _verify, sf_profile_name, db, schema, "format_minutes_to_hm", "65", "01:05")
        r.step("Verify format_minutes_to_dhm(1501) = '01:01:01'",
               _verify, sf_profile_name, db, schema, "format_minutes_to_dhm", "1501", "01:01:01")

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
