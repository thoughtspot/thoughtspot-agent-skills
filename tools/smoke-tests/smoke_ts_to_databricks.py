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


def _build_mv_yaml(model_tml: dict) -> str:
    """Build a minimal MV YAML from a parsed ThoughtSpot model TML."""
    model = model_tml.get("model", {})
    model_tables = model.get("model_tables", [])
    if not model_tables:
        raise RuntimeError("Model has no model_tables")

    dims = []
    measures = []

    for mt in model_tables:
        for col in mt.get("columns", []):
            col_type = col.get("properties", {}).get("column_type", "ATTRIBUTE")
            name = col.get("name", "unknown")
            col_id = col.get("column_id", "")
            phys_col = col_id.split("::")[-1] if "::" in col_id else col_id

            if col_type == "MEASURE":
                agg = col.get("properties", {}).get("aggregation", "SUM")
                agg_map = {
                    "SUM": "SUM", "COUNT": "COUNT",
                    "COUNT_DISTINCT": "COUNT(DISTINCT",
                    "AVERAGE": "AVG", "AVG": "AVG",
                    "MIN": "MIN", "MAX": "MAX",
                }
                agg_fn = agg_map.get(agg, "SUM")
                if agg == "COUNT_DISTINCT":
                    measures.append({"name": name, "expr": f"COUNT(DISTINCT {phys_col})"})
                else:
                    measures.append({"name": name, "expr": f"{agg_fn}({phys_col})"})
            else:
                dims.append({"name": name, "expr": phys_col})

    mv = {"version": 0.1, "dimensions": dims, "measures": measures}
    return yaml.dump(mv, default_flow_style=False, sort_keys=False)


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

    # Step 5: Build MV YAML
    ok, mv_yaml = r.step("Build MV YAML from TML", _build_mv_yaml, tml)
    if ok:
        parsed = yaml.safe_load(mv_yaml)
        r.info(f"Generated: {len(parsed.get('dimensions', []))} dimensions, "
               f"{len(parsed.get('measures', []))} measures")

    # Step 6: Generate DDL
    def build_ddl():
        if not args.target_fqn:
            raise SkipStep("No --target-fqn specified; DDL generation skipped")
        ddl = (
            f"CREATE OR REPLACE VIEW {args.target_fqn}\n"
            f"WITH METRICS LANGUAGE YAML AS $$\n"
            f"{mv_yaml}$$"
        )
        assert "WITH METRICS LANGUAGE YAML" in ddl
        assert "version:" in ddl
        return ddl

    ok, ddl = r.step("Generate DDL", build_ddl)

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
