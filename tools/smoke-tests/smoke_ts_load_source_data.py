#!/usr/bin/env python3
"""
smoke_ts_load_source_data.py — smoke test for ts-load-source-data.

Verifies the load workflow offline (no live Snowflake connection needed):
  1.  ts load infer against a CSV directory
  2.  ts load infer against a Tableau download JSON
  3.  ts load infer against a schema-only manifest
  4.  ts load generate from a schema
  5.  Verify generated CSV structure and row counts

Usage:
    python tools/smoke-tests/smoke_ts_load_source_data.py
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult  # noqa: E402


def run_ts_load(args: list[str]) -> dict | list:
    """Run a ts load command and return parsed JSON."""
    cmd = ["ts", "load"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ts load {' '.join(args)} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout)


def main():
    print("smoke_ts_load_source_data")
    print("=" * 40)
    r = SmokeTestResult()

    with tempfile.TemporaryDirectory(prefix="smoke_load_") as tmpdir:
        tmp = Path(tmpdir)

        # --- Step 1: Infer from CSV directory ---
        csv_dir = tmp / "csvs"
        csv_dir.mkdir()
        (csv_dir / "sales.csv").write_text("id,amount,order_date\n1,9.99,2024-01-15\n2,19.50,2024-02-20\n")
        (csv_dir / "customers.csv").write_text("cust_id,name,email\n1,Alice,a@b.com\n2,Bob,b@c.com\n")

        def step_infer_csv_dir():
            result = run_ts_load(["infer", "--source", str(csv_dir)])
            assert result["source_type"] == "csv_dir", f"Expected csv_dir, got {result['source_type']}"
            assert len(result["tables"]) == 2, f"Expected 2 tables, got {len(result['tables'])}"
            return result

        ok, infer_result = r.step("1. Infer from CSV directory", step_infer_csv_dir)

        # --- Step 2: Infer from Tableau download JSON ---
        download_json = tmp / "download.json"
        download_json.write_text(json.dumps({
            "tdsx_path": "/tmp/test.tdsx",
            "extracted_dir": str(csv_dir),
            "files": ["sales.csv"],
            "data_files": [
                {"name": "sales.csv", "path": str(csv_dir / "sales.csv"),
                 "type": "csv", "validation": {"total_lines": 3, "header_columns": 3, "corrupt_lines": []}}
            ],
        }))

        def step_infer_tableau():
            result = run_ts_load(["infer", "--source", str(download_json)])
            assert result["source_type"] == "tableau_download"
            return result

        r.step("2. Infer from Tableau download JSON", step_infer_tableau)

        # --- Step 3: Infer from schema-only manifest ---
        schema_json = tmp / "schema.json"
        schema_json.write_text(json.dumps({
            "source": "manual",
            "tables": [{"table_name": "DEMO", "columns": [
                {"name": "id", "db_column_name": "ID", "type": "INTEGER"},
                {"name": "value", "db_column_name": "VALUE", "type": "FLOAT"},
            ]}],
        }))

        def step_infer_schema_only():
            result = run_ts_load(["infer", "--source", str(schema_json)])
            assert result["source_type"] == "schema_only"
            return result

        r.step("3. Infer from schema-only manifest", step_infer_schema_only)

        # --- Step 4: Generate from schema ---
        gen_dir = tmp / "generated"

        def step_generate():
            result = run_ts_load(["generate", "--source", str(schema_json),
                                  "--rows", "50", "--output", str(gen_dir)])
            assert len(result) == 1
            assert result[0]["rows"] == 50
            gen_file = gen_dir / "DEMO.csv"
            assert gen_file.exists(), f"Generated file not found: {gen_file}"
            return result

        r.step("4. Generate synthetic data", step_generate)

        # --- Step 5: Verify generated CSV ---
        def step_verify_csv():
            gen_file = gen_dir / "DEMO.csv"
            with open(gen_file, newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                assert header == ["ID", "VALUE"], f"Unexpected header: {header}"
                rows = list(reader)
                assert len(rows) == 50, f"Expected 50 rows, got {len(rows)}"
            return True

        r.step("5. Verify generated CSV structure", step_verify_csv)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
