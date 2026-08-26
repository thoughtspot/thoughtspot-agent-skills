#!/usr/bin/env python3
"""
smoke_ts_to_databricks.py — live smoke test for ts-convert-to-databricks-mv.

Verifies the full path:
  1. ThoughtSpot auth (ts CLI)
  2. Databricks auth (databricks CLI)
  3. Export a ThoughtSpot model TML
  4. Parse the TML and extract columns
  5. Map columns to MV YAML (dimensions + measures)
  6. Generate CREATE VIEW ... WITH METRICS DDL
  7. Validate the DDL structure
  8. (Optional with --execute) Execute DDL and verify creation
  9. (Optional) Cleanup: DROP VIEW

Usage:
    python tools/smoke-tests/smoke_ts_to_databricks.py \\
        --ts-profile production \\
        --dbx-profile Production \\
        --model-guid "abc123-..." \\
        --target-fqn "demo.agent_skills_testing.smoke_test_mv" \\
        [--execute] \\
        [--no-cleanup]

Notes:
  - The ThoughtSpot model must already exist.
  - --execute requires CREATE TABLE permission on the target schema.
  - The SQL warehouse must be on the Preview channel.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

from _common import (
    SmokeTestResult, SkipStep,
    ts_auth_check, run_ts,
    load_dbx_profile, get_dbx_warehouse_id,
    databricks_sql, dbx_sql_rows,
)



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ts-profile", required=True, help="ThoughtSpot profile name")
    parser.add_argument("--dbx-profile", required=True, help="Databricks profile name")
    parser.add_argument("--model-guid", required=True, help="ThoughtSpot model GUID")
    parser.add_argument("--target-fqn", default="",
                        help="Target MV FQN (catalog.schema.name) — required for --execute")
    parser.add_argument("--execute", action="store_true",
                        help="Actually create the MV in Databricks (needs CREATE TABLE permission)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Don't drop the MV after testing")
    args = parser.parse_args()

    r = SmokeTestResult()
    print(f"\nSmoke test: ts-convert-to-databricks-mv")
    print(f"  Model GUID: {args.model_guid}")
    if args.target_fqn:
        print(f"  Target MV: {args.target_fqn}")
    print()

    # Step 1: ThoughtSpot auth
    ok, whoami = r.step("ThoughtSpot auth", ts_auth_check, args.ts_profile)
    if not ok:
        return r.summary()
    r.info(f"Logged in as: {whoami.get('display_name', 'unknown')}")

    # Step 2: Databricks auth
    ok, profile = r.step("Load Databricks profile",
                         load_dbx_profile, args.dbx_profile)
    if not ok:
        return r.summary()

    ok, _ = r.step("Test Databricks SQL connectivity",
                    databricks_sql, args.dbx_profile, "SELECT 1 AS test")
    if not ok:
        return r.summary()

    # Step 3: Export TML
    def export_tml():
        data = run_ts(["tml", "export", args.model_guid, "--fqn", "--associated", "--parse"],
                      args.ts_profile)
        if isinstance(data, list):
            for item in data:
                if item.get("type") == "model" or "model" in item.get("tml", {}):
                    return item.get("tml", item)
            return data[0].get("tml", data[0]) if data else {}
        return data

    ok, tml = r.step("Export ThoughtSpot TML", export_tml)
    if not ok:
        return r.summary()

    # Step 4: Parse and count columns
    def count_columns():
        model = tml.get("model", {})
        total = 0
        attrs = 0
        meas = 0
        for mt in model.get("model_tables", []):
            for col in mt.get("columns", []):
                total += 1
                ct = col.get("properties", {}).get("column_type", "ATTRIBUTE")
                if ct == "MEASURE":
                    meas += 1
                else:
                    attrs += 1
        if total == 0:
            raise RuntimeError("Model has no columns")
        return {"total": total, "attributes": attrs, "measures": meas}

    ok, col_counts = r.step("Parse TML columns", count_columns)
    if ok:
        r.info(f"Columns: {col_counts['total']} total "
               f"({col_counts['attributes']} ATTRIBUTE, {col_counts['measures']} MEASURE)")

    # Steps 5+6: emit via the SHIPPED converter.
    #
    # These two steps used to call a local `_build_mv_yaml()` re-implementation and
    # then assert `"WITH METRICS LANGUAGE YAML" in ddl` against a string built two
    # lines earlier — an assertion that cannot fail (audit 6.1). So the emitter this
    # smoke test exists to guard (mv_emit*.py, mv_build_view.py: LOD routing, window
    # measures, cross-references, aggregation wrapping) had zero coverage while the
    # harness reported PASS. Routing through `ts databricks build-mv` is also what
    # `.claude/rules/ts-cli.md` requires: "Do not rewrite a `ts ... build-model` call
    # as an inline Python script."
    def build_ddl():
        if not args.target_fqn:
            raise SkipStep("No --target-fqn specified; DDL generation skipped")
        catalog, schema, view = args.target_fqn.split(".", 2)
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            (td_path / "model.json").write_text(json.dumps(tml))
            (td_path / "tables.json").write_text(json.dumps({"tables": []}))
            env = dict(os.environ)
            env["PYTHONPATH"] = str(_TS_CLI_SRC)
            res = subprocess.run(
                [sys.executable, "-m", "ts_cli.cli", "databricks", "build-mv",
                 "--model", str(td_path / "model.json"),
                 "--tables", str(td_path / "tables.json"),
                 "--catalog", catalog, "--schema", schema,
                 "--view-name", view, "--output-dir", str(td_path)],
                capture_output=True, text=True, env=env,
            )
            if res.returncode != 0:
                raise RuntimeError(
                    f"ts databricks build-mv failed (exit {res.returncode}):\n{res.stderr}")
            emitted = sorted(td_path.glob("*.sql"))
            if not emitted:
                raise RuntimeError(f"build-mv produced no .sql in {td_path}")
            ddl = emitted[0].read_text()
        # Assert against what the EMITTER produced, not against our own f-string.
        if "WITH METRICS LANGUAGE YAML" not in ddl:
            raise RuntimeError("emitted DDL missing WITH METRICS LANGUAGE YAML")
        if "version:" not in ddl:
            raise RuntimeError("emitted DDL carries no MV YAML body (no `version:`)")
        return ddl

    ok, ddl = r.step("Emit DDL via `ts databricks build-mv`", build_ddl)
    if ok and ddl:
        r.info(f"Emitted DDL: {len(ddl.splitlines())} lines")

    # Step 7: Execute (optional)
    if args.execute and ddl:
        def execute_ddl():
            databricks_sql(args.dbx_profile, ddl)
            return True

        ok, _ = r.step("Execute DDL in Databricks", execute_ddl)

        if ok:
            # Verify creation
            def verify():
                data = databricks_sql(
                    args.dbx_profile,
                    f"DESCRIBE TABLE EXTENDED {args.target_fqn}"
                )
                rows = data.get("result", {}).get("data_array", [])
                for row in rows:
                    if row[0] == "Type" and row[1] == "METRIC_VIEW":
                        return True
                raise RuntimeError("Created view is not a METRIC_VIEW")

            r.step("Verify MV creation", verify)

            # Cleanup
            if not args.no_cleanup:
                def cleanup():
                    databricks_sql(args.dbx_profile,
                                   f"DROP VIEW IF EXISTS {args.target_fqn}")
                    return True

                r.step("Cleanup: DROP VIEW", cleanup)
    elif args.execute and not ddl:
        r.info("Skipping execution — DDL generation failed")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
