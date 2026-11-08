#!/usr/bin/env python3
"""
smoke_ts_convert_from_sisense.py — offline smoke test for ts-convert-from-sisense.

Runs `ts sisense build-liveboard --target-model` over a small synthetic bundle (an "acme"
clinic: one fact, one dimension, three widgets, two dashboard filters) and a synthetic target
Model TML, then lints the output and checks the migration report:
  1. `ts sisense build-liveboard --target-model` -> Liveboard TML + migration-report.json
  2. `ts tml lint`                                -> pre-import lint, offline
  3. the report carries what it must: a bottom-N ranking kept as `bottom N`, a disabled
     widget filter reported and not applied, a disabled dashboard filter reported Skipped,
     and a chip on a column the Model lacks reported NEEDS REVIEW rather than dropped.

Everything is synthetic and written to a temp dir. No live ThoughtSpot or Sisense connection.

Usage:
    python tools/smoke-tests/smoke_ts_convert_from_sisense.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult  # noqa: E402

MODEL_TML = """\
model:
  name: Acme Clinic
  model_tables:
  - name: fact_visit
    joins:
    - with: dim_case
      'on': "[fact_visit::case_id_] = [dim_case::id_]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - name: dim_case
  columns:
  - name: Case Status
    column_id: dim_case::status
    properties: {column_type: ATTRIBUTE}
  - name: Visit Cost
    column_id: fact_visit::cost
    properties: {column_type: MEASURE, aggregation: SUM}
"""


def _item(dim, agg=None, title="", filt=None, disabled=None):
    jaql = {"dim": dim, "title": title or dim}
    if agg:
        jaql["agg"] = agg
    if filt is not None:
        jaql["filter"] = filt
    item = {"jaql": jaql}
    if disabled is not None:
        item["disabled"] = disabled
    return item


def _widget(oid, title, wtype, panels):
    return {"oid": oid, "title": title, "type": wtype, "subtype": wtype,
            "metadata": {"panels": [{"name": n, "items": items} for n, items in panels]}}


def _bundle() -> dict:
    cost, status = "[fact_visit.cost]", "[dim_case.status]"
    widgets = [
        _widget("w1", "Total Cost", "indicator", [("value", [_item(cost, "sum")])]),
        _widget("w2", "Cheapest Statuses", "chart/bar", [
            ("categories", [_item(status)]), ("values", [_item(cost, "sum")]),
            ("filters", [_item(status, filt={"bottom": 3, "by": {"dim": cost, "agg": "sum"}})])]),
        _widget("w3", "Cost by Status", "chart/column", [
            ("categories", [_item(status)]), ("values", [_item(cost, "sum")]),
            ("filters", [_item(status, filt={"members": ["Test"]}, disabled=True)])]),
    ]
    tables = [{"id": "fact_visit", "name": "fact_visit", "columns": [
                  {"id": "case_id_", "name": "case_id_", "oid": "c1", "type": 8},
                  {"id": "cost", "name": "cost", "oid": "c2", "type": 40}]},
              {"id": "dim_case", "name": "dim_case", "columns": [
                  {"id": "id_", "name": "id_", "oid": "c3", "type": 8},
                  {"id": "status", "name": "status", "oid": "c4", "type": 18}]}]
    return {
        "dashboard": {"title": "Acme Visits", "filters": [
            {"jaql": {"dim": "[dim_case.status]", "filter": {"members": ["Open"]}}, "disabled": True},
            {"jaql": {"dim": "[dim_case.priority]", "filter": {"members": ["High"]}}}]},
        "widgets": widgets,
        "datamodel": {"title": "acme", "datasets": [{"schema": {"tables": tables}}],
                      "relations": [{"columns": [{"table": "fact_visit", "column": "c1"},
                                                 {"table": "dim_case", "column": "c3"}]}]},
    }


def _run_ts(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["ts", *args], capture_output=True, text=True, timeout=120)


def _check(res: subprocess.CompletedProcess, what: str) -> None:
    if res.returncode != 0:
        raise RuntimeError(f"{what} failed (exit {res.returncode}): {res.stderr.strip() or res.stdout.strip()}")


def main() -> int:
    r = SmokeTestResult()
    print("\nSmoke test: ts-convert-from-sisense (--target-model, offline)\n")
    with tempfile.TemporaryDirectory(prefix="smoke_ts_sisense_") as tmp:
        tmp_path = Path(tmp)
        bundle, model, out = tmp_path / "bundle.json", tmp_path / "model.tml", tmp_path / "out"
        bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
        model.write_text(MODEL_TML, encoding="utf-8")

        def _build():
            _check(_run_ts(["sisense", "build-liveboard", "--input", str(bundle), "--target-model", str(model),
                            "--out", str(out)]), "ts sisense build-liveboard")
            lbs = list(out.glob("*.liveboard.tml"))
            assert lbs, "no liveboard TML produced"
            return json.loads((out / "migration-report.json").read_text(encoding="utf-8"))

        ok, report = r.step("ts sisense build-liveboard --target-model", _build)
        if not ok:
            return r.summary()

        def _lint():
            _check(_run_ts(["tml", "lint", "--dir", str(out)]), "ts tml lint")
            return len(list(out.glob("*.tml")))

        ok, n = r.step("ts tml lint (offline)", _lint)
        if ok:
            r.info(f"linted {n} TML file(s) clean")

        def _report():
            rows = {row["visual"]: row for row in report["visuals"]}
            lb = next(out.glob("*.liveboard.tml")).read_text(encoding="utf-8")
            assert "bottom 3" in lb and "top 3" not in lb, "bottom-N not carried as bottom N"
            assert "ranking" not in (rows["Cheapest Statuses"].get("note") or ""), "bottom-N flagged as not carried"
            assert "Test" not in lb, "a disabled widget filter was applied"
            assert "disabled widget filter" in (rows["Cost by Status"].get("note") or ""), "disabled filter not reported"
            chips = [row for row in report["visuals"] if row["visual"].startswith("filter chip")]
            assert any(c["status"] == "Skipped" for c in chips), "disabled dashboard filter not reported Skipped"
            assert any(c["status"] == "NEEDS REVIEW" for c in chips), "unexposed chip not reported NEEDS REVIEW"
            return {k: v["status"] for k, v in rows.items()}

        ok, statuses = r.step("migration report carries every decision", _report)
        if ok:
            r.info(f"statuses: {json.dumps(statuses)}")
    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
