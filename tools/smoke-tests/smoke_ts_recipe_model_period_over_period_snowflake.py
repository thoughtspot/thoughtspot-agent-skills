#!/usr/bin/env python3
"""
smoke_ts_recipe_model_period_over_period_snowflake.py — live smoke test for
ts-recipe-model-period-over-period-snowflake.

Builds a tiny date-offset fixture in Snowflake and asserts the four correctness
properties the recipe depends on. Each check corresponds to a documented claim
in the skill; if one regresses, the skill's guidance is wrong.

  1. The offset join returns the value from exactly 364 days earlier.
  2. RECONCILIATION GATE — with an adequate spine, the prior-period measure
     summed over all periods equals the base measure's grand total (same rows,
     shifted key). This is the skill's Step 9 Check 1.
  3. ORPHAN GATE (negative test) — with a spine that stops at the last fact
     date, prior-period rows fall out and the reconciliation FAILS. Proves the
     Step 6 warning is real and the gate detects it.
  4. GRAIN TRAP (negative test) — a 12-month offset held on the DAY calendar
     is not unique and fans out, over-counting by the number of days in the
     month. Proves the Step 2c warning is real.

Everything is created in a scratch schema and dropped at the end.

Usage:
    python tools/smoke-tests/smoke_ts_recipe_model_period_over_period_snowflake.py \\
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
    ts_snowflake_exec, ts_snowflake_scalar,
)

_SCRATCH = "TS_POP_SMOKE"


def _fq(db: str) -> str:
    return f"{db}.{_SCRATCH}"


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

def _step_build_fixture(sf_profile: str, db: str) -> None:
    """800 days of one-row-per-day sales; AMT is the day offset so every day,
    week and month total is distinguishable. Two calendars: one whose spine
    extends 364 days past the last fact (correct), one that stops at it (short)."""
    s = _fq(db)
    ts_snowflake_exec(sf_profile, query=f"CREATE SCHEMA IF NOT EXISTS {s}")

    ts_snowflake_exec(sf_profile, query=f"""
        CREATE OR REPLACE TABLE {s}.FACT AS
        SELECT DATEADD(day, seq4(), '2024-01-01'::DATE) AS ORDER_DAY,
               DATE_TRUNC('month', DATEADD(day, seq4(), '2024-01-01'::DATE))::DATE AS ORDER_MONTH,
               seq4() AS AMT
        FROM TABLE(GENERATOR(ROWCOUNT => 800))
    """)

    # correct spine: starts 364 days before the first fact, ends 364 days after the last
    ts_snowflake_exec(sf_profile, query=f"""
        CREATE OR REPLACE TABLE {s}.DIM_DATE AS
        SELECT d AS DATE_VALUE,
               DATEADD(day, -364, d) AS DATE_364_DAYS_AGO,
               DATE_TRUNC('week',  d)::DATE AS START_OF_WEEK,
               DATE_TRUNC('month', d)::DATE AS START_OF_MONTH,
               ADD_MONTHS(DATE_TRUNC('month', d)::DATE, -12)::DATE AS BAD_MONTH_OFFSET
        FROM (SELECT DATEADD(day, seq4(), '2023-01-02'::DATE) AS d
              FROM TABLE(GENERATOR(ROWCOUNT => 1528)))
    """)

    # short spine: stops at the last fact date, so recent facts have no D+364 row
    ts_snowflake_exec(sf_profile, query=f"""
        CREATE OR REPLACE TABLE {s}.DIM_DATE_SHORT AS
        SELECT * FROM {s}.DIM_DATE
        WHERE DATE_VALUE <= (SELECT MAX(ORDER_DAY) FROM {s}.FACT)
    """)

    # month-grain dimension — the CORRECT home for a 12-month offset
    ts_snowflake_exec(sf_profile, query=f"""
        CREATE OR REPLACE TABLE {s}.DIM_MONTH AS
        SELECT DISTINCT START_OF_MONTH AS MONTH_START,
               ADD_MONTHS(START_OF_MONTH, -12)::DATE AS MONTH_START_12_MONTHS_AGO
        FROM {s}.DIM_DATE
    """)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _step_offset_join_correct(sf_profile: str, db: str) -> None:
    """The offset join must surface the value from exactly 364 days earlier."""
    s = _fq(db)
    got = ts_snowflake_scalar(sf_profile, f"""
        SELECT SUM(f.AMT)
        FROM {s}.DIM_DATE d JOIN {s}.FACT f ON f.ORDER_DAY = d.DATE_364_DAYS_AGO
        WHERE d.DATE_VALUE = '2025-01-01'
    """)
    expected = ts_snowflake_scalar(sf_profile, f"""
        SELECT SUM(AMT) FROM {s}.FACT
        WHERE ORDER_DAY = DATEADD(day, -364, '2025-01-01'::DATE)
    """)
    if int(got) != int(expected):
        raise RuntimeError(f"Offset join returned {got}, expected {expected}")


def _step_reconciliation_passes(sf_profile: str, db: str) -> None:
    """Step 9 Check 1: with an adequate spine the prior-period total equals the base total."""
    s = _fq(db)
    base = ts_snowflake_scalar(sf_profile, f"SELECT SUM(AMT) FROM {s}.FACT")
    prior = ts_snowflake_scalar(sf_profile, f"""
        SELECT SUM(f.AMT)
        FROM {s}.DIM_DATE d JOIN {s}.FACT f ON f.ORDER_DAY = d.DATE_364_DAYS_AGO
    """)
    if int(base) != int(prior):
        raise RuntimeError(
            f"Reconciliation failed on an adequate spine: base={base} prior={prior}"
        )


def _step_short_spine_orphans(sf_profile: str, db: str) -> None:
    """Negative test: a spine stopping at the last fact date MUST lose rows.
    If this stops failing, the Step 6 orphan gate has nothing to catch."""
    s = _fq(db)
    base = ts_snowflake_scalar(sf_profile, f"SELECT SUM(AMT) FROM {s}.FACT")
    prior = ts_snowflake_scalar(sf_profile, f"""
        SELECT SUM(f.AMT)
        FROM {s}.DIM_DATE_SHORT d JOIN {s}.FACT f ON f.ORDER_DAY = d.DATE_364_DAYS_AGO
    """)
    if int(prior) >= int(base):
        raise RuntimeError(
            f"Expected a short spine to orphan rows, but prior={prior} >= base={base}. "
            "The orphan gate documented in Step 6 may no longer be needed — re-verify."
        )


def _step_day_grain_month_offset_fans_out(sf_profile: str, db: str) -> None:
    """Negative test: a 12-month offset on the DAY calendar is not unique and
    over-counts by roughly the number of days in the month. Proves Step 2c."""
    s = _fq(db)
    correct = ts_snowflake_scalar(sf_profile, f"""
        SELECT SUM(f.AMT)
        FROM {s}.DIM_MONTH m JOIN {s}.FACT f ON f.ORDER_MONTH = m.MONTH_START_12_MONTHS_AGO
        WHERE m.MONTH_START = '2025-01-01'
    """)
    fanned = ts_snowflake_scalar(sf_profile, f"""
        SELECT SUM(f.AMT)
        FROM {s}.DIM_DATE d JOIN {s}.FACT f ON f.ORDER_MONTH = d.BAD_MONTH_OFFSET
        WHERE d.START_OF_MONTH = '2025-01-01'
    """)
    if int(fanned) <= int(correct):
        raise RuntimeError(
            f"Expected the day-grain month offset to fan out, but got "
            f"fanned={fanned} <= correct={correct}. Re-verify the Step 2c warning."
        )
    ratio = int(fanned) / int(correct)
    if not (25 <= ratio <= 32):          # ~one duplicate per day in the month
        raise RuntimeError(
            f"Fan-out ratio {ratio:.1f} outside the expected ~31x — fixture may have drifted"
        )


def _cleanup(sf_profile: str, db: str) -> None:
    ts_snowflake_exec(sf_profile, query=f"DROP SCHEMA IF EXISTS {_fq(db)} CASCADE")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_smoke_test(sf_profile_name: str, db: str, schema: str, no_cleanup: bool) -> int:
    print("\nSmoke test: ts-recipe-model-period-over-period-snowflake")
    print(f"  Snowflake profile : {sf_profile_name}")
    print(f"  Scratch schema    : {_fq(db)}\n")

    r = SmokeTestResult()

    ok, _ = r.step("Load Snowflake profile", load_sf_profile, sf_profile_name)
    if not ok:
        return r.summary()

    ok, _ = r.step(f"Build fixture in {_fq(db)}", _step_build_fixture, sf_profile_name, db)
    built = ok

    if built:
        r.step("Offset join returns the value from 364 days earlier",
               _step_offset_join_correct, sf_profile_name, db)
        r.step("Reconciliation gate passes on an adequate spine",
               _step_reconciliation_passes, sf_profile_name, db)
        r.step("Negative: a short spine orphans rows (Step 6 gate has teeth)",
               _step_short_spine_orphans, sf_profile_name, db)
        r.step("Negative: a month offset on the day calendar fans out ~31x (Step 2c)",
               _step_day_grain_month_offset_fans_out, sf_profile_name, db)

    if built and not no_cleanup:
        r.step(f"Cleanup — drop {_fq(db)}", _cleanup, sf_profile_name, db)
    elif no_cleanup:
        r.info(f"--no-cleanup: scratch schema left at {_fq(db)}")

    return r.summary()


def main() -> int:
    parser = recipe_arg_parser(__doc__)
    args = parser.parse_args()
    return run_smoke_test(
        args.sf_profile, args.sf_target_db, args.sf_target_schema, args.no_cleanup
    )


if __name__ == "__main__":
    sys.exit(main())
