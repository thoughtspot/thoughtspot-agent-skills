#!/usr/bin/env python3
"""
smoke_ts_object_model_spotql_query.py — live smoke test for ts-object-model-spotql-query.

Exercises the verified SpotQL paths against a real ThoughtSpot instance:
  1. ThoughtSpot auth
  2. Confirm the target Model exists and is a WORKSHEET (Model)
  3. generate-sql on a known-good SpotQL → status SUCCESS + non-empty executable_sql
  4. fetch-data on the same SpotQL → status SUCCESS + at least --min-rows rows
  5. Error path: a deliberately invalid query (SELECT *) returns a structured
     non-SUCCESS status with errors[] (and exit 0) — not a crash

Usage:
    python smoke_ts_object_model_spotql_query.py \\
        --ts-profile champ-staging \\
        --model-guid 4da3a07f-fe29-4d20-8758-260eb1315071 \\
        --spotql 'SELECT "t1"."Product Category", SUM("t1"."Amount") AS "Total Sales" FROM "Dunder Mifflin Sales & Inventory" AS "t1" GROUP BY "t1"."Product Category"' \\
        --min-rows 1
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult, run_ts, ts_auth_check  # noqa: E402


def step_model_is_worksheet(profile: str, model_guid: str) -> None:
    matches = run_ts(["metadata", "search", "--guid", model_guid], profile)
    if not matches:
        raise RuntimeError(f"No object found with GUID '{model_guid}'.")
    header = matches[0].get("metadata_header", {})
    if header.get("type") != "WORKSHEET":
        raise RuntimeError(f"GUID '{model_guid}' is not a Model/WORKSHEET (type={header.get('type')}).")


def step_generate_sql(profile: str, model_guid: str, spotql: str) -> str:
    res = run_ts(["spotql", "generate-sql", spotql, "--model", model_guid], profile)
    if res.get("status") != "SUCCESS":
        raise RuntimeError(f"generate-sql status={res.get('status')} errors={res.get('errors')}")
    if not res.get("executable_sql"):
        raise RuntimeError("generate-sql SUCCESS but executable_sql is empty")
    return res["executable_sql"]


def step_fetch_data(profile: str, model_guid: str, spotql: str, min_rows: int) -> int:
    res = run_ts(["spotql", "fetch-data", spotql, "--model", model_guid], profile)
    if res.get("status") != "SUCCESS":
        raise RuntimeError(f"fetch-data status={res.get('status')} errors={res.get('errors')}")
    n = len(res.get("rows", []))
    if n < min_rows:
        raise RuntimeError(f"fetch-data returned {n} rows, expected >= {min_rows}")
    return n


def step_error_path(profile: str, model_guid: str) -> str:
    """An invalid query must come back as a structured error, not a crash."""
    res = run_ts(["spotql", "generate-sql", "SELECT *", "--model", model_guid], profile)
    if res.get("status") == "SUCCESS":
        raise RuntimeError("expected the invalid query 'SELECT *' to fail, got SUCCESS")
    if not res.get("errors"):
        raise RuntimeError("invalid query returned no errors[] — structured error path broken")
    return res["errors"][0].get("code", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ts-profile", required=True, help="ThoughtSpot profile name")
    parser.add_argument("--model-guid", required=True, help="Model (WORKSHEET) GUID, external-CDW-backed")
    parser.add_argument("--spotql", required=True, help="A known-good SpotQL statement against the Model")
    parser.add_argument("--min-rows", type=int, default=1, help="Minimum rows expected from fetch-data")
    args = parser.parse_args()

    print(f"smoke_ts_object_model_spotql_query — model: {args.model_guid!r}")
    r = SmokeTestResult()

    ok, _ = r.step("ThoughtSpot auth", ts_auth_check, args.ts_profile)
    if not ok:
        return r.summary()

    r.step("Model exists and is a WORKSHEET", step_model_is_worksheet, args.ts_profile, args.model_guid)

    ok, sql = r.step("generate-sql → SUCCESS + warehouse SQL",
                     step_generate_sql, args.ts_profile, args.model_guid, args.spotql)
    if ok and sql:
        r.info(f"  warehouse SQL: {sql[:80]}...")

    ok, n = r.step("fetch-data → SUCCESS + rows",
                   step_fetch_data, args.ts_profile, args.model_guid, args.spotql, args.min_rows)
    if ok:
        r.info(f"  rows returned: {n}")

    ok, code = r.step("error path: invalid query → structured error",
                      step_error_path, args.ts_profile, args.model_guid)
    if ok:
        r.info(f"  error code surfaced: {code}")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
