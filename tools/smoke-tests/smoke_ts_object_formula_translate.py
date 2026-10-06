#!/usr/bin/env python3
"""smoke_ts_object_formula_translate.py — live smoke for ts-object-formula-translate.

1. One formula per translator-backed dialect at context level 0 (no network).
2. Level 2 against a real Model: `--validate compile` (VALIDATE_ONLY — creates nothing)
   and `--validate execute` (scratch Model + AgentQL, deleted afterwards).
3. Asserts no `ZZ_FORMULA_PROBE_%` object is left on the cluster.

The Model is only read. Pick a small one with at least one physical MEASURE column and
one physical ATTRIBUTE column (`ts metadata search --subtype WORKSHEET`).

Usage:
    python tools/smoke-tests/smoke_ts_object_formula_translate.py --ts-profile se-thoughtspot \\
        --model-guid 93b6ff6b-f4d9-4941-bb02-c64fe71a3c3c
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult, run_ts, ts_auth_check  # noqa: E402

LEVEL0 = [
    ("tableau", "ROUND(SUM([Sales]) / COUNTD([Customer]), 2)",
     "round ( sum ( [TABLE::Sales]) / unique count ( [TABLE::Customer]) , 0.01 )"),
    ("dax", "DIVIDE(SUM(Sales[Amount]), DISTINCTCOUNT(Sales[Customer]))",
     "safe_divide(sum([Sales::Amount]), unique count([Sales::Customer]))"),
    ("qlik", "Round(Sum(Sales), 0.01)", "round(sum([TABLE::Sales]), 0.01)"),
    ("sisense", "ROUND(SUM([rev]), 2)", "round(sum([TABLE::rev]), 0.01)"),
    ("snowflake", "DATEDIFF('day', order_date, ship_date)",
     "diff_days ( [TABLE::ship_date] , [TABLE::order_date] )"),
    ("databricks", "date_add(`order_date`, 3)", "add_days ( [TABLE::order_date] , 3 )"),
]


def _fail(msg: str) -> None:
    # Explicit raise, not `assert`: `python -O` strips asserts and would pass silently.
    raise RuntimeError(msg)


def _measure_column(profile: str, guid: str) -> str:
    data = run_ts(["tml", "export", guid], profile)
    doc = json.loads(data[0]["edoc"])
    cols = [c for c in doc.get("model", {}).get("columns", [])
            if c.get("column_id") and (c.get("properties") or {}).get("column_type") == "MEASURE"]
    cols.sort(key=lambda c: (c.get("properties") or {}).get("aggregation", "SUM") != "SUM")
    if cols:
        return cols[0]["name"]
    _fail("Model has no physical MEASURE column to probe")
    return ""


def _probes_left(profile: str) -> list:
    return run_ts(["metadata", "search", "--subtype", "WORKSHEET", "--name", "ZZ_%PROBE%"], profile)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts-profile", required=True)
    ap.add_argument("--model-guid", required=True)
    a = ap.parse_args()
    r = SmokeTestResult()
    ok, _ = r.step("auth", ts_auth_check, a.ts_profile)
    if not ok:
        return r.summary()

    def level0():
        for dialect, src, want in LEVEL0:
            out = run_ts(["formula", "translate", src, "--from", dialect], a.ts_profile)
            if out["status"] != "TRANSLATED" or out["formula"] != want:
                _fail(f"{dialect}: got {out['status']} {out['formula']!r}, want {want!r}")
            if not all(x["placeholder"] for x in out["references"]):
                _fail(f"{dialect}: level-0 references must all be placeholders")
        r.info(f"{len(LEVEL0)} dialects translated at level 0")

    r.step("level 0, one formula per dialect", level0)

    ok, col = r.step("pick a MEASURE column", _measure_column, a.ts_profile, a.model_guid)
    if not ok:
        return r.summary()
    src = f'ROUND(SUM("{col}"), 2)'

    def run_level(level: str):
        out = run_ts(["formula", "translate", src, "--from", "snowflake", "--model",
                      a.model_guid, "--name", "Smoke Probe", "--validate", level], a.ts_profile)
        v = out["verification"]
        if out["unresolved"] or v.get("result") != "OK":
            _fail(f"{level}: {v.get('result')} {v.get('error')} unresolved={out['unresolved']}")
        if level == "execute":
            if not v.get("sql") or v.get("scratch", {}).get("confirmed_absent") is not True:
                _fail(f"execute: sql={bool(v.get('sql'))} scratch={v.get('scratch')}")
            r.info(f"execute: {len(v.get('rows') or [])} row(s); scratch {v['scratch']['guid']} deleted")
        else:
            r.info(f"compile: {out['formula']}")

    r.step("level 2 --validate compile", run_level, "compile")
    r.step("level 2 --validate execute", run_level, "execute")

    def nothing_left():
        left = _probes_left(a.ts_profile)
        if left:
            _fail(f"scratch Models left behind: {[x.get('metadata_id') for x in left]}")

    r.step("no ZZ_FORMULA_PROBE_% object left", nothing_left)
    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
