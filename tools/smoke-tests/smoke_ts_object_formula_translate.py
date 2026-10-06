#!/usr/bin/env python3
"""smoke_ts_object_formula_translate.py — live smoke for ts-object-formula-translate.

1. One formula per translator-backed dialect at context level 0 (no network), plus the
   reverse direction (`--from thoughtspot --to excel`).
2. Level 2 against a real Model: `--validate compile` (VALIDATE_ONLY — creates nothing)
   and `--validate execute` (scratch Model + AgentQL, deleted afterwards).
3. The 60-formula Excel regression set (tools/ts-cli/tests/fixtures/excel_regression/):
   each translator output, with its columns swapped for same-typed SALARY_RATES columns,
   is imported with `--policy VALIDATE_ONLY` — which parses the formula and CREATES NOTHING.
   `--skip-excel-regression` skips it; `--salary-rates-guid` overrides the table.
4. Asserts no `ZZ_FORMULA_PROBE_%` object is left on the cluster.

The Model is only read. Pick a small one with at least one physical MEASURE column and
one physical ATTRIBUTE column (`ts metadata search --subtype WORKSHEET`).

Usage:
    python tools/smoke-tests/smoke_ts_object_formula_translate.py --ts-profile se-thoughtspot \\
        --model-guid 93b6ff6b-f4d9-4941-bb02-c64fe71a3c3c
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
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
    ("excel", '=IFERROR([@a]/[@b],0)', "safe_divide ( [TABLE::a] , [TABLE::b] )"),
    ("google_sheets", "=IFERROR(A2/B2)", "[TABLE::A] / [TABLE::B]"),
]

REGRESSION = Path(__file__).resolve().parents[1] / "ts-cli" / "tests" / "fixtures" / "excel_regression"
SALARY_RATES = "503a5cdf-b11d-4834-b313-97ad3518dc4b"  # AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST
# Same-typed SALARY_RATES columns the regression set's placeholders are swapped for.
SUBSTITUTE = {"VARCHAR": "[SALARY_RATES::DEPARTMENT]", "DATE": "[SALARY_RATES::EFFECTIVE_DATE]"}
NUMBER = "[SALARY_RATES::BASE_RATE]"


def _probe_tml(table_guid: str, expr: str, role: str) -> str:
    escaped = expr.replace("\\", "\\\\").replace('"', '\\"')
    agg = "\n      aggregation: SUM" if role == "MEASURE" else ""
    return (f"model:\n  name: ZZ_FORMULA_PROBE_EXCEL_SMOKE_DELETE_ME\n  model_tables:\n"
            f"  - name: SALARY_RATES\n    fqn: {table_guid}\n  formulas:\n"
            f"  - id: formula_P\n    name: P\n    expr: \"{escaped}\"\n  columns:\n"
            f"  - name: RATE_ID\n    column_id: SALARY_RATES::RATE_ID\n    properties:\n"
            f"      column_type: ATTRIBUTE\n  - name: P\n    formula_id: formula_P\n"
            f"    properties:\n      column_type: {role}{agg}\n")


def _validate_only(profile: str, tml: str) -> str:
    """VALIDATE_ONLY import of one Model TML (creates nothing). Returns "OK" or the error."""
    with tempfile.NamedTemporaryFile("w", suffix=".tml", delete=False) as fh:
        fh.write(tml)
        path = fh.name
    try:
        res = subprocess.run(["ts", "tml", "import", "--file", path, "--policy", "VALIDATE_ONLY",
                              "--profile", profile], capture_output=True, text=True)
    finally:
        Path(path).unlink()
    try:
        status = json.loads(res.stdout)[0]["response"]["status"]
    except (ValueError, LookupError, TypeError):
        return f"unreadable import response: {(res.stdout + res.stderr)[:200]}"
    return "OK" if status.get("status_code") == "OK" else status.get("error_message", "FAILED")


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
    ap.add_argument("--salary-rates-guid", default=SALARY_RATES,
                    help="Table the Excel regression set is validated against (VALIDATE_ONLY)")
    ap.add_argument("--skip-excel-regression", action="store_true")
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

    def reverse():
        out = run_ts(["formula", "translate", "safe_divide ( sum ( [T::a] ) , sum ( [T::b] ) )",
                      "--from", "thoughtspot", "--to", "excel"], a.ts_profile)
        want = "=IF(SUM(Table1[b])=0,0,SUM(Table1[a])/SUM(Table1[b]))"
        if out["formula"] != want:
            _fail(f"--to excel: got {out['formula']!r}, want {want!r}")

    r.step("reverse: ThoughtSpot → Excel", reverse)

    def excel_regression():
        columns = json.loads((REGRESSION / "columns.json").read_text())
        failures = []
        cases = [ln.split("|", 3) for ln in (REGRESSION / "input.txt").read_text().splitlines()
                 if ln.strip()]
        for cid, _name, role, src in cases:
            out = run_ts(["formula", "translate", src, "--from", "excel", "--role", role.lower(),
                          "--columns", "@" + str(REGRESSION / "columns.json")], a.ts_profile)
            if out["formula"] is None:
                failures.append(f"{cid}: {out['status']} {out['notes'][-1:]}")
                continue
            expr = re.sub(r"\[TABLE::([A-Z_0-9]+)\]", lambda m: SUBSTITUTE.get(
                columns[m.group(1)]["data_type"], NUMBER), out["formula"])
            result = _validate_only(a.ts_profile, _probe_tml(a.salary_rates_guid, expr, out["role"]))
            if result != "OK":
                failures.append(f"{cid}: {result}")
        if failures:
            _fail(f"{len(failures)} of {len(cases)} failed VALIDATE_ONLY: {failures}")
        r.info(f"{len(cases)} Excel regression formulas VALIDATE_ONLY-clean (nothing created)")

    if not a.skip_excel_regression:
        r.step("Excel regression set, VALIDATE_ONLY", excel_regression)

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
