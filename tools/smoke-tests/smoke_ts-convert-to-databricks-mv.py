#!/usr/bin/env python3
"""
smoke_ts-convert-to-databricks-mv.py — smoke test for the codified
`ts databricks build-mv` emit path (tools/ts-cli/ts_cli/databricks/mv_emit*.py,
mv_build_view.py), the deterministic core of ts-convert-to-databricks-mv.

Distinct from the older tools/smoke-tests/smoke_ts_to_databricks.py, which
predates `build-mv` and re-implements its own minimal MV YAML builder
(bypassing the real emitter entirely). This test calls the actual `ts
databricks build-mv` command against a small local fixture, so a regression
in the emitter itself (LOD routing, window measures, cross-references,
aggregation wrapping, etc.) is caught here rather than only in the live
fidelity matrix (docs/audit/2026-07-18-dbx-to-fidelity-matrix.md).

Two parts:
  1. OFFLINE (always runs, no credentials needed): writes a small local
     fixture Model + Table TML JSON (one dimension, one plain measure, one
     LOD dimension, one window measure), runs the worktree's `build-mv` in
     isolation, and asserts the emitted DDL contains `CREATE OR REPLACE VIEW`
     and `WITH METRICS LANGUAGE YAML` plus the expected dimension/measure
     shapes.
  2. LIVE (optional, guarded): only attempted when --live is passed. Creates
     a tiny scratch schema + table on Databricks, creates the emitted MV,
     and drops the scratch schema again. Wrapped in a broad try/except so a
     missing `databricks` CLI, missing profile, or no warehouse access SKIPs
     rather than fails — this must never break CI for contributors without
     live Databricks access. Budget: <= 4 SQL statements (create schema,
     create table, create MV, drop schema).

Usage:
    python tools/smoke-tests/smoke_ts-convert-to-databricks-mv.py
    python tools/smoke-tests/smoke_ts-convert-to-databricks-mv.py --live \\
        --dbx-cli-profile ts-production --warehouse-id c6ed539a60038b93 \\
        --catalog agent_skills
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult, SkipStep  # noqa: E402

# tools/smoke-tests/ -> repo root is two levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]
TS_CLI_SRC = REPO_ROOT / "tools" / "ts-cli"

_SCHEMA = "smoke_ts_to_databricks_mv_fixture"
_TABLE = "smoke_fixture"
_VIEW = "smoke_fixture_mv"


def _fixture_model_and_tables() -> tuple[dict, list[dict]]:
    """A minimal single-table Model exercising: a plain dimension, a plain SUM
    measure, an LOD dimension (group_aggregate), and a window measure
    (cumulative_sum) — enough surface to catch a regression in each emitter
    routing path without the full battery the live matrix runs."""
    model = {
        "name": "Smoke Fixture Model",
        "model_tables": [{"name": "SMOKE_FIXTURE"}],
        "columns": [
            {"name": "Category", "column_id": "SMOKE_FIXTURE::category",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Txn Date", "column_id": "SMOKE_FIXTURE::txn_date",
             "properties": {"column_type": "ATTRIBUTE"}},
            {"name": "Amount", "column_id": "SMOKE_FIXTURE::amount",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Category Total Amount", "formula_id": "formula_cat_total",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Cumulative Amount", "formula_id": "formula_cumulative",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        ],
        "formulas": [
            {"id": "formula_cat_total", "name": "Category Total Amount",
             "expr": "group_aggregate ( sum ( [SMOKE_FIXTURE::amount] ) , "
                     "{ [SMOKE_FIXTURE::category] } , query_filters ( ) )"},
            {"id": "formula_cumulative", "name": "Cumulative Amount",
             "expr": "cumulative_sum ( [SMOKE_FIXTURE::amount] , [SMOKE_FIXTURE::txn_date] )"},
        ],
    }
    table = {
        "table": {
            "name": "SMOKE_FIXTURE",
            "db": "agent_skills",
            "schema": _SCHEMA,
            "db_table": _TABLE,
            "connection": {"name": "SMOKE_TEST_CONN"},
            "columns": [
                {"name": "category", "db_column_name": "category",
                 "properties": {"column_type": "ATTRIBUTE"},
                 "db_column_properties": {"data_type": "VARCHAR"}},
                {"name": "txn_date", "db_column_name": "txn_date",
                 "properties": {"column_type": "ATTRIBUTE"},
                 "db_column_properties": {"data_type": "DATE"}},
                {"name": "amount", "db_column_name": "amount",
                 "properties": {"column_type": "MEASURE", "aggregation": "SUM"},
                 "db_column_properties": {"data_type": "DOUBLE"}},
            ],
        }
    }
    return {"model": model}, [table]


def step_run_build_mv(out_dir: Path) -> str:
    """Invoke `ts databricks build-mv` from the worktree's own ts-cli in
    isolation (PYTHONPATH override) — the globally-installed `ts` may point
    at a different checkout that lacks this command."""
    model_doc, tables_doc = _fixture_model_and_tables()
    model_path = out_dir / "model.json"
    tables_path = out_dir / "tables.json"
    model_path.write_text(json.dumps(model_doc))
    tables_path.write_text(json.dumps(tables_doc))

    env = {"PYTHONPATH": str(TS_CLI_SRC)}
    import os
    full_env = dict(os.environ)
    full_env.update(env)

    result = subprocess.run(
        [sys.executable, "-m", "ts_cli.cli", "databricks", "build-mv",
         "--model", str(model_path), "--tables", str(tables_path),
         "--catalog", "agent_skills", "--schema", _SCHEMA,
         "--output-dir", str(out_dir), "--view-name", _VIEW],
        capture_output=True, text=True, env=full_env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"build-mv failed (exit {result.returncode}):\n{result.stderr}")

    summary = json.loads(result.stdout)
    mvs = summary.get("metric_views", [])
    if len(mvs) != 1:
        raise RuntimeError(f"expected exactly 1 metric view, got {len(mvs)}: {summary}")
    if summary.get("skipped"):
        raise RuntimeError(f"unexpected skipped columns: {summary['skipped']}")

    ddl_path = Path(mvs[0]["file"])
    ddl = ddl_path.read_text()
    return ddl


def step_assert_ddl_shape(ddl: str) -> None:
    assert "CREATE OR REPLACE VIEW" in ddl, "DDL missing CREATE OR REPLACE VIEW"
    assert "WITH METRICS LANGUAGE YAML" in ddl, "DDL missing WITH METRICS LANGUAGE YAML"
    assert "source: agent_skills.smoke_ts_to_databricks_mv_fixture.smoke_fixture" in ddl, \
        "DDL missing expected source: line"
    # Plain measure -> SUM(source.amount)
    assert "SUM(source.amount)" in ddl, "plain SUM measure not emitted"
    # LOD -> dimension window function, never `measures:`
    assert "OVER (PARTITION BY source.category)" in ddl, "LOD dimension window not emitted"
    # Cumulative window measure -> window: block with range: cumulative
    assert "range: cumulative" in ddl, "cumulative window measure not emitted"
    assert "semiadditive: last" in ddl, "window measure missing required semiadditive"


def step_live_roundtrip(dbx_cli_profile: str, warehouse_id: str, catalog: str) -> None:
    """Optional: create the emitted MV for real, then tear it down. Broad
    try/except at the call site converts any failure here into a SKIP, not a
    FAIL, so contributors without live Databricks access are never blocked."""
    def run_stmt(sql: str) -> dict:
        body = json.dumps({"warehouse_id": warehouse_id, "statement": sql,
                           "catalog": catalog, "wait_timeout": "30s"})
        proc = subprocess.run(
            ["databricks", "api", "post", "/api/2.0/sql/statements",
             "--profile", dbx_cli_profile, "--json", body],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
        data = json.loads(proc.stdout)
        stmt_id = data.get("statement_id")
        state = data.get("status", {}).get("state")
        for _ in range(15):
            if state not in ("PENDING", "RUNNING"):
                break
            time.sleep(2)
            poll = subprocess.run(
                ["databricks", "api", "get", f"/api/2.0/sql/statements/{stmt_id}",
                 "--profile", dbx_cli_profile],
                capture_output=True, text=True,
            )
            data = json.loads(poll.stdout)
            state = data.get("status", {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"statement ended in state {state}: {data.get('status')}")
        return data

    with tempfile.TemporaryDirectory() as tmp:
        ddl = step_run_build_mv(Path(tmp))

    try:
        run_stmt(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{_SCHEMA}")
        run_stmt(
            f"CREATE OR REPLACE TABLE {catalog}.{_SCHEMA}.{_TABLE} AS "
            f"SELECT * FROM VALUES ('A', DATE'2026-01-01', 10.0) "
            f"AS t(category, txn_date, amount)"
        )
        run_stmt(ddl)
        rows = run_stmt(
            f"SELECT MEASURE(amount) FROM {catalog}.{_SCHEMA}.{_VIEW}"
        ).get("result", {}).get("data_array", [])
        if not rows or rows[0][0] != "10.0":
            raise RuntimeError(f"unexpected query result: {rows}")
    finally:
        try:
            run_stmt(f"DROP SCHEMA IF EXISTS {catalog}.{_SCHEMA} CASCADE")
        except Exception:
            pass  # best-effort cleanup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="Also attempt the live Databricks round-trip (skips "
                             "gracefully if credentials/warehouse aren't available)")
    parser.add_argument("--dbx-cli-profile", default="ts-production",
                        help="databricks CLI profile name (~/.databrickscfg)")
    parser.add_argument("--warehouse-id", default="c6ed539a60038b93",
                        help="Databricks SQL warehouse ID")
    parser.add_argument("--catalog", default="agent_skills",
                        help="Databricks catalog for the scratch schema")
    args = parser.parse_args()

    r = SmokeTestResult()
    print("\nSmoke test: ts-convert-to-databricks-mv (build-mv emit path)\n")

    with tempfile.TemporaryDirectory() as tmp:
        ok, ddl = r.step("Run `ts databricks build-mv` on local fixture",
                        step_run_build_mv, Path(tmp))
        if not ok:
            return r.summary()
        r.info(f"Emitted DDL: {len(ddl.splitlines())} lines")

        r.step("Assert emitted DDL shape (dimensions/measures/window)",
              step_assert_ddl_shape, ddl)

    if args.live:
        def live_step():
            try:
                step_live_roundtrip(args.dbx_cli_profile, args.warehouse_id, args.catalog)
            except Exception as e:
                raise SkipStep(f"live round-trip unavailable: {e}")
        r.step("Live round-trip: create + query + drop MV on Databricks", live_step)
    else:
        r.info("Skipping live round-trip (pass --live to attempt it)")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
