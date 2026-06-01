#!/usr/bin/env python3
"""
smoke_ts_from_databricks.py — live smoke test for ts-convert-from-databricks-mv.

Verifies the full path:
  1. Databricks auth (databricks CLI)
  2. List Metric Views in a catalog
  3. Fetch a known Metric View definition via DESCRIBE TABLE EXTENDED
  4. Parse the YAML from the View Text row
  5. Extract dimensions and measures
  6. Verify column counts match expectations
  7. (Optional) Build a minimal Model TML from the MV structure

Usage:
    python tools/smoke-tests/smoke_ts_from_databricks.py \\
        --dbx-profile Production \\
        --mv-fqn "demo_qsr.prayansh.ecommerce_transactions_basic_sales_metrics_view"

Notes:
  - The Metric View must already exist in Databricks.
  - The SQL warehouse must be on the Preview channel.
"""
from __future__ import annotations

import argparse
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
    load_dbx_profile, get_dbx_warehouse_id,
    databricks_sql, dbx_sql_rows,
)


def _parse_mv_yaml(dbx_profile: str, mv_fqn: str) -> dict:
    """Fetch and parse the Metric View YAML definition."""
    data = databricks_sql(dbx_profile, f"DESCRIBE TABLE EXTENDED {mv_fqn}")
    rows = data.get("result", {}).get("data_array", [])

    view_text = None
    mv_type = None
    for row in rows:
        if row[0] == "View Text":
            view_text = row[1]
        if row[0] == "Type":
            mv_type = row[1]

    if mv_type != "METRIC_VIEW":
        raise RuntimeError(f"Expected Type=METRIC_VIEW, got {mv_type}")
    if not view_text:
        raise RuntimeError("No View Text found in DESCRIBE output")

    return yaml.safe_load(view_text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dbx-profile", required=True,
                        help="Databricks profile name from ~/.claude/databricks-profiles.json")
    parser.add_argument("--mv-fqn", required=True,
                        help="Fully qualified Metric View name (catalog.schema.view)")
    args = parser.parse_args()

    r = SmokeTestResult()
    print(f"\nSmoke test: ts-convert-from-databricks-mv")
    print(f"  MV: {args.mv_fqn}")
    print()

    # Step 1: Databricks auth
    ok, profile = r.step("Load Databricks profile",
                         load_dbx_profile, args.dbx_profile)
    if not ok:
        return r.summary()

    ok, wh_id = r.step("Extract warehouse ID",
                        get_dbx_warehouse_id, profile)
    if not ok:
        return r.summary()
    r.info(f"Warehouse ID: {wh_id}")

    # Step 2: Test SQL connectivity
    ok, _ = r.step("Test SQL connectivity (SELECT 1)",
                    databricks_sql, args.dbx_profile, "SELECT 1 AS test")
    if not ok:
        return r.summary()

    # Step 3: List Metric Views
    parts = args.mv_fqn.split(".")
    catalog = parts[0] if len(parts) >= 3 else ""

    def list_mvs():
        rows = dbx_sql_rows(
            args.dbx_profile,
            f"SELECT table_catalog, table_schema, table_name "
            f"FROM system.information_schema.tables "
            f"WHERE table_type = 'METRIC_VIEW' AND table_catalog = '{catalog}'"
        )
        if not rows:
            raise RuntimeError(f"No Metric Views found in catalog '{catalog}'")
        return rows

    ok, mv_list = r.step(f"List Metric Views in '{catalog}'", list_mvs)
    if ok:
        r.info(f"Found {len(mv_list)} Metric View(s)")

    # Step 4: Fetch and parse MV definition
    ok, mv_def = r.step("Fetch and parse MV YAML",
                         _parse_mv_yaml, args.dbx_profile, args.mv_fqn)
    if not ok:
        return r.summary()

    # Step 5: Validate YAML structure
    def validate_yaml():
        assert "version" in mv_def, "Missing 'version' field"
        assert "source" in mv_def or "entities" in mv_def, \
            "Missing 'source' (v0.1) or 'entities' (v1.1)"
        dims = mv_def.get("dimensions", [])
        measures = mv_def.get("measures", [])
        if not dims and not measures:
            raise RuntimeError("MV has no dimensions or measures")
        return {"dimensions": len(dims), "measures": len(measures)}

    ok, counts = r.step("Validate YAML structure", validate_yaml)
    if ok:
        r.info(f"Version: {mv_def.get('version')}")
        r.info(f"Source: {mv_def.get('source', 'N/A')}")
        r.info(f"Dimensions: {counts['dimensions']}, Measures: {counts['measures']}")
        if mv_def.get("filter"):
            r.info(f"Filter: {mv_def['filter']}")

    # Step 6: Validate dimension expressions
    def check_dimensions():
        for d in mv_def.get("dimensions", []):
            assert "name" in d, f"Dimension missing 'name'"
            assert "expr" in d, f"Dimension '{d.get('name')}' missing 'expr'"
        return True

    r.step("Validate dimension entries", check_dimensions)

    # Step 7: Validate measure expressions
    def check_measures():
        for m in mv_def.get("measures", []):
            assert "name" in m, f"Measure missing 'name'"
            assert "expr" in m, f"Measure '{m.get('name')}' missing 'expr'"
        return True

    r.step("Validate measure entries", check_measures)

    # Step 8: Verify source table exists
    def check_source():
        source = mv_def.get("source")
        if not source:
            raise SkipStep("v1.1 MV (entities) — source table check skipped")
        rows = dbx_sql_rows(args.dbx_profile, f"DESCRIBE TABLE {source}")
        if not rows:
            raise RuntimeError(f"Source table {source} returned no columns")
        return len(rows)

    ok, col_count = r.step("Verify source table exists", check_source)
    if ok:
        r.info(f"Source table has {col_count} columns")

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
