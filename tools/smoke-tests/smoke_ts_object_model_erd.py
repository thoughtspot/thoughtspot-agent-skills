#!/usr/bin/env python3
"""
smoke_ts_object_model_erd.py — smoke test for ts-object-model-erd.

Verifies the offline (files) path end-to-end:
  1. Discover fixture TMLs (model + tables)
  2. Parse, assemble, render to HTML
  3. Verify output is self-contained, contains expected data

Does NOT require a live ThoughtSpot instance — uses bundled test fixtures.

Usage:
    python tools/smoke-tests/smoke_ts_object_model_erd.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_DIR = REPO_ROOT / "agents" / "cli" / "ts-object-model-erd"
FIXTURES = SKILL_DIR / "tests" / "fixtures"

sys.path.insert(0, str(SKILL_DIR))
sys.path.insert(0, str(REPO_ROOT / "agents" / "shared" / "erd"))


def step_import_modules():
    import build_erd  # noqa: F811
    return build_erd


def step_discover_fixtures(build_erd):
    models, tables = build_erd._discover([str(FIXTURES)])
    if not models:
        raise RuntimeError("No *.model.tml found in fixtures")
    if not tables:
        raise RuntimeError("No *.table.tml found in fixtures")
    return len(models), len(tables)


def step_build_erd(build_erd, out_path):
    logs = []
    result = build_erd.build([str(FIXTURES)], out_path, log=logs.append)
    if result != out_path:
        raise RuntimeError(f"build() returned {result!r}, expected {out_path!r}")
    if not os.path.exists(out_path):
        raise RuntimeError(f"Output file not created: {out_path}")
    return logs


def step_verify_html_content(out_path):
    html = open(out_path, encoding="utf-8").read()
    checks = {
        "Mini Sales model name": "Mini Sales" in html,
        "MANY_TO_ONE cardinality": "MANY_TO_ONE" in html,
        "__ERD_DATA__ injection": "__ERD_DATA__" in html,
        "<svg element present": "<svg" in html,
        "no external resources": not re.search(r'(src|href)\s*=\s*["\']https?://', html),
    }
    failures = [k for k, v in checks.items() if not v]
    if failures:
        raise RuntimeError(f"HTML verification failed: {', '.join(failures)}")
    return len(html)


def step_verify_redact_rls(build_erd, out_path):
    logs = []
    build_erd.build([str(FIXTURES)], out_path, redact_rls=True, log=logs.append)
    html = open(out_path, encoding="utf-8").read()
    if "(redacted)" not in html:
        raise RuntimeError("--redact-rls did not produce '(redacted)' in output")


def main() -> int:
    print("smoke_ts_object_model_erd — offline (files) path")
    print()

    r = SmokeTestResult()

    ok, build_erd = r.step("import build_erd module", step_import_modules)
    if not ok:
        return r.summary()

    ok, counts = r.step("discover fixture TMLs", step_discover_fixtures, build_erd)
    if ok:
        r.info(f"Found {counts[0]} model(s), {counts[1]} table(s)")

    with tempfile.TemporaryDirectory(prefix="ts_erd_smoke_") as td:
        out_path = os.path.join(td, "erd.html")

        ok, logs = r.step("build ERD from fixtures", step_build_erd, build_erd, out_path)
        if ok and logs:
            for msg in logs:
                r.info(f"log: {msg}")

        if ok:
            ok2, size = r.step("verify HTML content", step_verify_html_content, out_path)
            if ok2:
                r.info(f"Output size: {size:,} bytes")

        redact_path = os.path.join(td, "erd_redacted.html")
        r.step("verify --redact-rls", step_verify_redact_rls, build_erd, redact_path)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
