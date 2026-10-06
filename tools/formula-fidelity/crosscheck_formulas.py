#!/usr/bin/env python3
"""Bronze cross-check for M1: re-evaluate each candidate with the Python ``formulas`` library.

``formulas`` (EUPL-1.1) is an external tool: run this in a throwaway uv env, never import it
from ts_cli or vendor it (docs/research/formula-test-cases/oracles.md §2):

    uv run --no-project --python 3.12 --with formulas --with openpyxl \\
        python -I tools/formula-fidelity/crosscheck_formulas.py --data-dir <dir>

For each translatable candidate in ``<data-dir>/extracted/candidates.jsonl`` it writes a
workbook holding ONLY that case's input cells (row r, the case's letters) and the formula —
no cached values, so ``formulas`` must compute — and compares with the corpus value:

- ``agree``        the bronze value equals the oracle of record
- ``disputed``     it differs: the case is quarantined, never scored (oracles.md principle)
- ``unavailable``  ``formulas`` cannot evaluate it (``#NAME?`` / load failure): still scored,
                   counted separately

Output: ``<data-dir>/extracted/crosscheck.json`` (outside the repo — it holds values).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fidelity.sources import render  # noqa: E402  (stdlib-only module)

EPOCH = _dt.date(1899, 12, 30)


def _value(v):
    """formulas' result cell -> plain Python (unwrapping its 1x1 arrays)."""
    try:
        v = v.value[0][0]
    except Exception:  # noqa: BLE001
        pass
    return v


def _canon(v):
    s = str(v)
    if s.startswith("#"):
        return {"t": "error", "v": s}
    if isinstance(v, bool):
        return {"t": "bool", "v": v}
    if type(v).__name__ in ("bool_", "bool"):
        return {"t": "bool", "v": bool(v)}
    try:
        f = float(v)
        if isinstance(v, str):
            return {"t": "str", "v": v}
        return {"t": "num", "v": f}
    except (TypeError, ValueError):
        return {"t": "str", "v": "" if v is None else s}


def agree(expected: dict, got: dict, tol: dict) -> bool:
    et, gt = expected["t"], got["t"]
    if et == "error":
        return gt == "error"  # which error code may differ between engines; not scored here
    if et == "date":
        if gt != "num":
            return False
        return (EPOCH + _dt.timedelta(days=int(got["v"]))).isoformat() == expected["v"]
    if et == "num":
        if gt == "bool":
            return False
        try:
            a, b = float(expected["v"]), float(got["v"])
        except (TypeError, ValueError):
            return False
        bound = max(tol.get("abs", 0), 1e-9 * max(abs(a), abs(b), 1e-300))
        return a == b or (math.isfinite(a) and math.isfinite(b) and abs(a - b) <= bound)
    if et == "bool":
        return gt == "bool" and bool(got["v"]) == expected["v"]
    if et == "str":
        return gt == "str" and got["v"] == expected["v"] or (
            gt == "num" and expected["v"] == _num_text(got["v"]))
    return False


def _num_text(f: float) -> str:
    return str(int(f)) if float(f).is_integer() else repr(f)


def evaluate(cases: list[dict]) -> dict[str, dict]:
    import formulas
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    where = {}
    for r, c in enumerate(cases, 1):
        for inp in c["inputs"]:
            cell = ws[f"{inp['letter']}{r}"]
            if inp["kind"] == "blank":
                continue
            if inp["kind"] == "date":
                cell.value = _dt.datetime.fromisoformat(inp["value"])
                cell.number_format = "yyyy-mm-dd"
            else:
                cell.value = inp["value"]
        formula = render([tuple(t) for t in c["tokens"]], c["letters"], row=r)
        ws[f"Z{r}"] = formula
        where[c["id"]] = f"Z{r}"
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "x.xlsx"
        wb.save(p)
        sol = formulas.ExcelModel().loads(str(p)).finish().calculate()
    got = {}
    for k, v in sol.items():
        m = re.search(r"!([A-Z]+[0-9]+)$", str(k).upper())
        if m:
            got[m.group(1)] = _value(v)
    return {cid: got.get(cell, "#MISSING") for cid, cell in where.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=pathlib.Path)
    ap.add_argument("--chunk", type=int, default=40)
    a = ap.parse_args(argv)
    rows = [json.loads(line) for line in
            (a.data_dir / "extracted" / "candidates.jsonl").read_text().splitlines() if line]
    rows = [r for r in rows if r["translation"]["status"] in ("TRANSLATED", "APPROXIMATED")]
    out: dict[str, dict] = {}

    def run(batch):
        try:
            return evaluate(batch)
        except Exception as exc:  # noqa: BLE001 — one bad formula fails a whole load
            if len(batch) == 1:
                return {batch[0]["id"]: f"#LOADFAIL {type(exc).__name__}"}
            res = {}
            for c in batch:
                res.update(run([c]))
            return res

    for i in range(0, len(rows), a.chunk):
        batch = rows[i:i + a.chunk]
        vals = run(batch)
        for c in batch:
            raw = vals.get(c["id"], "#MISSING")
            if isinstance(raw, str) and raw.startswith(("#NAME", "#LOADFAIL", "#MISSING")):
                out[c["id"]] = {"status": "unavailable", "bronze": str(raw)}
                continue
            got = _canon(raw)
            ok = agree(c["expected"], got, c["tolerance"])
            out[c["id"]] = {"status": "agree" if ok else "disputed", "bronze": got}
        print(f"  {min(i + a.chunk, len(rows))}/{len(rows)}", file=sys.stderr, flush=True)
    (a.data_dir / "extracted" / "crosscheck.json").write_text(json.dumps(out, indent=0, default=str))
    tally: dict[str, int] = {}
    for v in out.values():
        tally[v["status"]] = tally.get(v["status"], 0) + 1
    print(json.dumps(tally))
    return 0


if __name__ == "__main__":
    sys.exit(main())
