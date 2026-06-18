#!/usr/bin/env python3
"""
smoke_ts_dependency_audit.py — live smoke test for ts-dependency-audit.

Verifies the audit workflow against a real ThoughtSpot instance:
  1.  ThoughtSpot auth
  2.  Enumerate models via ts metadata search
  3.  Enumerate tables via ts metadata search
  4.  Export a model TML and verify structure for analysis
  5.  Walk dependents to discover sets (COHORT bucket)
  6.  Verify formula extraction from an answer TML
  7.  Verify join quality detection (data_type lookup)
  8.  Verify PII column name pattern matching

Usage:
    python tools/smoke-tests/smoke_ts_dependency_audit.py \\
        --ts-profile production \\
        --model-guid abc123...          # a model with at least one dependent

Credentials are read via the ts CLI profile (handles auth and token caching).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run: pip install PyYAML")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))

from _common import SmokeTestResult, SkipStep, ts_auth_check, run_ts  # noqa: E402


# ---------------------------------------------------------------------------
# PII detection helper (mirrors the skill logic)
# ---------------------------------------------------------------------------

PII_PATTERNS = [
    (r"email|e[-_]?mail|email[-_]?addr", "Email"),
    (r"phone|mobile|cell[-_]?phone|fax|tel(?:ephone)?", "Phone"),
    (r"ssn|social[-_]?sec|national[-_]?id|tax[-_]?id|nin\b|sin\b", "National ID"),
    (r"dob|birth[-_]?date|date[-_]?of[-_]?birth|birthday", "Date of birth"),
    (r"credit[-_]?card|card[-_]?num|account[-_]?num|iban|routing[-_]?num", "Financial"),
    (r"password|passwd|secret[-_]?key|api[-_]?key", "Credentials"),
    (r"first[-_]?name|last[-_]?name|surname|full[-_]?name|given[-_]?name", "Name"),
    (r"street[-_]?addr|postal[-_]?code|zip[-_]?code", "Address"),
]


def detect_pii(column_name: str) -> str | None:
    """Return PII category if column name matches a pattern, else None."""
    lower = column_name.lower()
    for pattern, category in PII_PATTERNS:
        if re.search(pattern, lower):
            return category
    return None


# ---------------------------------------------------------------------------
# Main smoke test
# ---------------------------------------------------------------------------

def run_smoke_test(ts_profile: str, model_guid: str) -> int:
    print(f"\n=== ts-dependency-audit smoke test ===")
    print(f"    Profile:    {ts_profile}")
    print(f"    Model GUID: {model_guid}")
    print()

    r = SmokeTestResult()

    # Step 1: Auth
    r.step("1. ThoughtSpot auth", ts_auth_check, ts_profile)

    # Step 2: Enumerate models
    def enum_models():
        result = run_ts(
            ["metadata", "search", "--subtype", "WORKSHEET", "--all"],
            ts_profile,
        )
        if not isinstance(result, list) or len(result) == 0:
            raise RuntimeError("No models found")
        r.info(f"   Found {len(result)} model(s)")
        return result

    ok, models = r.step("2. Enumerate models", enum_models)

    # Step 3: Enumerate tables
    def enum_tables():
        result = run_ts(
            ["metadata", "search", "--subtype", "ONE_TO_ONE_LOGICAL", "--all"],
            ts_profile,
        )
        if not isinstance(result, list):
            raise RuntimeError("Tables search returned non-list")
        r.info(f"   Found {len(result)} table(s)")
        return result

    ok, tables = r.step("3. Enumerate tables", enum_tables)

    # Step 4: Export model TML
    def export_model():
        result = run_ts(
            ["tml", "export", model_guid, "--fqn", "--parse", "--associated"],
            ts_profile,
        )
        if not isinstance(result, list) or len(result) == 0:
            raise RuntimeError("TML export returned empty result")
        model_tml = None
        for item in result:
            edoc = item.get("edoc", "")
            if isinstance(edoc, str):
                parsed = yaml.safe_load(edoc)
            else:
                parsed = edoc
            if parsed and "model" in parsed:
                model_tml = parsed
                break
        if not model_tml:
            raise RuntimeError("No model TML found in export")
        model = model_tml["model"]
        col_count = len(model.get("columns", []))
        table_count = len(model.get("model_tables", []))
        formula_count = len(model.get("formulas", []))
        r.info(f"   Model: {model.get('name', '?')}")
        r.info(f"   Tables: {table_count}, Columns: {col_count}, Formulas: {formula_count}")
        return result, model_tml

    ok, export_result = r.step("4. Export model TML (with --associated)", export_model)
    tml_bundle = export_result[0] if export_result else None
    model_tml = export_result[1] if export_result else None

    # Step 5: Walk dependents to find sets
    def find_sets():
        result = run_ts(
            ["metadata", "dependents", model_guid],
            ts_profile,
        )
        if not isinstance(result, list):
            raise RuntimeError(f"Dependents returned non-list: {type(result)}")
        set_count = sum(
            1 for dep in result
            if dep.get("type", "").upper() in ("SET", "COHORT")
        )
        total = len(result)
        r.info(f"   Dependents: {total} total, {set_count} set(s)")
        return result

    if ok:
        r.step("5. Walk dependents (sets/cohorts)", find_sets)

    # Step 6: Verify formula extraction
    def verify_formula_extraction():
        if not model_tml:
            raise SkipStep("No model TML available")
        formulas = model_tml.get("model", {}).get("formulas", [])
        if not formulas:
            raise SkipStep("Model has no formulas")
        for f in formulas:
            if "name" not in f or "expr" not in f:
                raise RuntimeError(f"Formula missing name or expr: {f}")
        r.info(f"   Validated {len(formulas)} formula(s)")
        return formulas

    r.step("6. Verify formula extraction from TML", verify_formula_extraction)

    # Step 7: Verify join quality detection
    def verify_join_quality():
        if not model_tml:
            raise SkipStep("No model TML available")
        model = model_tml["model"]
        join_count = 0
        for mt in model.get("model_tables", []):
            joins = mt.get("joins", [])
            join_count += len(joins)
        r.info(f"   Found {join_count} join(s) in model")
        if not tml_bundle:
            raise SkipStep("No associated TMLs for data type lookup")
        table_tmls = []
        for item in tml_bundle:
            edoc = item.get("edoc", "")
            if isinstance(edoc, str):
                parsed = yaml.safe_load(edoc)
            else:
                parsed = edoc
            if parsed and "table" in parsed:
                table_tmls.append(parsed)
        r.info(f"   Found {len(table_tmls)} associated table TML(s) for data type lookup")
        return join_count

    r.step("7. Verify join quality detection", verify_join_quality)

    # Step 8: PII pattern matching
    def verify_pii_detection():
        test_cases = {
            "customer_email": "Email",
            "phone_number": "Phone",
            "ssn": "National ID",
            "birth_date": "Date of birth",
            "credit_card_num": "Financial",
            "revenue": None,
            "order_date": None,
        }
        for col_name, expected in test_cases.items():
            result = detect_pii(col_name)
            if result != expected:
                raise RuntimeError(
                    f"PII detection mismatch: {col_name} → {result}, expected {expected}"
                )
        r.info(f"   All {len(test_cases)} PII pattern tests passed")

    r.step("8. PII column name pattern matching", verify_pii_detection)

    return r.summary()


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ts-dependency-audit smoke test")
    parser.add_argument("--ts-profile", required=True, help="ThoughtSpot profile name")
    parser.add_argument("--model-guid", required=True, help="GUID of a model to audit")
    args = parser.parse_args()

    sys.exit(run_smoke_test(args.ts_profile, args.model_guid))


if __name__ == "__main__":
    main()
