# tools/smoke-tests/smoke_ts-metadata-report.py
"""Smoke test for `ts metadata report` against SpotterAccuracy.

NOTE: Live run is currently blocked by TLSV1_ALERT_PROTOCOL_VERSION on
champ-clone-spotql.thoughtspotdev.cloud. The test is wired and correct;
re-run once the SSL issue is resolved (see open-items.md #22).

Asserts:
- schema_version == "1.0"
- source.guid matches expected
- at least one dependent (auto-Model)
- aggregate recommendation is SAFE_TO_DROP or REVIEW_RECOMMENDED
"""
from __future__ import annotations

import json
import subprocess
import sys


PROFILE = "SpotterAccuracy"
SOURCE = "baa451a6-02a0-42d1-8347-8cd4af13b505"
EXPECTED_NAME = "EDUCATION_BUSINESS.EDUCATION_BUSINESS.UNIVERSITY_FACULTY"


def main() -> int:
    result = subprocess.run(
        ["ts", "metadata", "report", SOURCE, "--profile", PROFILE, "--format", "json", "--fast"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("FAIL: command returned non-zero", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"FAIL: stdout is not JSON: {e}", file=sys.stderr)
        return 1

    if payload.get("schema_version") != "1.0":
        print(f"FAIL: unexpected schema_version: {payload.get('schema_version')}", file=sys.stderr)
        return 1

    src = payload.get("source") or {}
    if src.get("guid") != SOURCE:
        print(f"FAIL: source.guid mismatch: {src.get('guid')}", file=sys.stderr)
        return 1
    if src.get("name") != EXPECTED_NAME:
        print(f"FAIL: source.name mismatch: {src.get('name')}", file=sys.stderr)
        return 1

    deps = payload.get("dependents") or []
    if len(deps) < 1:
        print(f"FAIL: expected at least 1 dependent (auto-Model), got {len(deps)}", file=sys.stderr)
        return 1

    rec = (payload.get("classification") or {}).get("recommendation")
    if rec not in ("SAFE_TO_DROP", "REVIEW_RECOMMENDED"):
        print(f"FAIL: unexpected recommendation: {rec}", file=sys.stderr)
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
