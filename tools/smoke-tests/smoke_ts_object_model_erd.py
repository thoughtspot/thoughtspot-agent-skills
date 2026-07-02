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

import json
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


def step_verify_export_json_ingest(build_erd, out_path, dump_path):
    """The `ts tml export` JSON dump must render directly — no manual split.

    Emulates the CLI's raw stdout shape: a JSON list of {"edoc": "<tml string>"}.
    """
    dump = []
    for tml in sorted(FIXTURES.glob("*.tml")):
        dump.append({"edoc": tml.read_text(encoding="utf-8")})
    with open(dump_path, "w", encoding="utf-8") as fh:
        json.dump(dump, fh)
    build_erd.build([dump_path], out_path, log=lambda *_: None)
    html = open(out_path, encoding="utf-8").read()
    if "Mini Sales" not in html or "__ERD_DATA__" not in html:
        raise RuntimeError("export-JSON dump did not render the model")
    if "MANY_TO_ONE" not in html:
        raise RuntimeError("export-JSON dump lost join cardinality (table edocs not routed)")


def step_verify_no_model_fails_loud(build_erd, out_path):
    """Tables-only input must exit non-zero, never write a silent empty diagram."""
    dump = [{"edoc": t.read_text(encoding="utf-8")}
            for t in sorted(FIXTURES.glob("*.table.tml"))]
    dump_path = out_path + ".tables_only.json"
    with open(dump_path, "w", encoding="utf-8") as fh:
        json.dump(dump, fh)
    try:
        build_erd.build([dump_path], out_path, log=lambda *_: None)
    except SystemExit:
        return  # expected
    raise RuntimeError("tables-only source did not raise SystemExit")


def step_verify_rls_is_reference_based(build_erd, out_path):
    """RLS must be modelled as rule-owner + referenced tables, never join-propagated.

    Guards against the regressed 'inherited via joins' model: the rendered HTML must
    not carry any of the discredited propagation vocabulary.
    """
    build_erd.build([str(FIXTURES)], out_path, log=lambda *_: None)
    html = open(out_path, encoding="utf-8").read()
    banned = ["Propagates through joins", "Inherits RLS", "RLS inherited",
              "via joins", "RLS edge", "rlsAffected"]
    present = [b for b in banned if b in html]
    if present:
        raise RuntimeError("join-propagation RLS vocabulary still present: " + ", ".join(present))


def step_verify_rls_reference_detection(build_erd_parser):
    """A rule that references another table flags that table as in_rls_path;
    a mere join-neighbour of a secured table is NOT flagged."""
    model_tml = {
        "guid": "g-rls",
        "model": {
            "name": "RLS ref test",
            "model_tables": [{"name": "ORDERS"}, {"name": "EMP"}, {"name": "CUST"}],
            "columns": [
                {"name": "OID", "column_id": "ORDERS::OID"},
                {"name": "EID", "column_id": "EMP::EID"},
                {"name": "CID", "column_id": "CUST::CID"},
            ],
        },
    }
    # Rule on ORDERS references EMP; CUST merely joins to ORDERS.
    tables = {
        "ORDERS": {"guid": "t-ord", "table": {"name": "ORDERS", "rls_rules": [
            {"name": "r", "expression": "[EMP::EID] = ts_groups_int"}]}},
        "EMP": {"guid": "t-emp", "table": {"name": "EMP"}},
        "CUST": {"guid": "t-cust", "table": {"name": "CUST", "joins_with": [
            {"name": "CUST_ORDERS", "destination": {"name": "ORDERS"},
             "on": "[CUST::CID] = [ORDERS::OID]", "cardinality": "MANY_TO_ONE"}]}},
    }
    parsed = build_erd_parser.parse_model(model_tml, tables, log=lambda *_: None)
    by_id = {t["id"]: t for t in parsed["tables"]}
    if not by_id["ORDERS"]["rls"]:
        raise RuntimeError("ORDERS should be secured (rule defined on it)")
    if not by_id["EMP"]["in_rls_path"]:
        raise RuntimeError("EMP should be in_rls_path (referenced by ORDERS' rule)")
    if by_id["CUST"]["in_rls_path"]:
        raise RuntimeError("CUST must NOT be in_rls_path — a join neighbour is not RLS-affected")
    if by_id["ORDERS"]["in_rls_path"]:
        raise RuntimeError("ORDERS must NOT be in_rls_path — it owns the rule, not referenced by another")


def step_verify_columns_flat_not_nested():
    """Column groups must be flat headed divs, never <details> nested inside the
    Columns <details> — nested disclosure leaves the inner rows hidden in some
    browsers (rendered fine in headless Chrome but not in the user's Chrome)."""
    js = (REPO_ROOT / "agents" / "shared" / "erd" / "renderer.js").read_text(encoding="utf-8")
    if '<details class="col-group"' in js:
        raise RuntimeError("column groups still emit nested <details> — inner rows can stay hidden")
    if 'class="col-group"' not in js:
        raise RuntimeError("col-group markup missing from renderer")


def step_verify_ai_analysis(build_erd, out_path, corpus_path):
    marker = "SMOKE-DOMAIN-Mini-Sales-analytics"
    corpus = {
        "model-guid-001": {
            "ai_analysis": {
                "domain": marker,
                "objectives": ["SMOKE-OBJECTIVE"],
                "personas": ["SMOKE-PERSONA"],
                "questions": ["SMOKE-QUESTION"],
            },
            "ai_instructions": ["SMOKE-INSTRUCTION"],
        }
    }
    with open(corpus_path, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh)
    build_erd.build([str(FIXTURES)], out_path, ai_analysis_path=corpus_path, log=lambda *_: None)
    html = open(out_path, encoding="utf-8").read()
    missing = [m for m in (marker, "SMOKE-OBJECTIVE", "SMOKE-QUESTION", "SMOKE-INSTRUCTION")
               if m not in html]
    if missing:
        raise RuntimeError(f"--ai-analysis corpus not injected: {', '.join(missing)}")


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

        dump_out = os.path.join(td, "erd_from_dump.html")
        dump_path = os.path.join(td, "export.json")
        r.step("verify ts-tml-export JSON dump ingest",
               step_verify_export_json_ingest, build_erd, dump_out, dump_path)

        r.step("verify no-model source fails loud",
               step_verify_no_model_fails_loud, build_erd,
               os.path.join(td, "erd_empty.html"))

        rls_path = os.path.join(td, "erd_rls.html")
        r.step("verify RLS is reference-based (not join-propagated)",
               step_verify_rls_is_reference_based, build_erd, rls_path)

        import parser as erd_parser  # noqa: E402  (shared/erd is on sys.path)
        r.step("verify RLS reference detection (parser)",
               step_verify_rls_reference_detection, erd_parser)

        r.step("verify column groups are flat (not nested <details>)",
               step_verify_columns_flat_not_nested)

        redact_path = os.path.join(td, "erd_redacted.html")
        r.step("verify --redact-rls", step_verify_redact_rls, build_erd, redact_path)

        ai_path = os.path.join(td, "erd_ai.html")
        corpus_path = os.path.join(td, "corpus.json")
        r.step("verify --ai-analysis corpus injection",
               step_verify_ai_analysis, build_erd, ai_path, corpus_path)

    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
