#!/usr/bin/env python3
"""smoke_ts_object_set_manager.py — live smoke for ts-object-set-manager (read-only).

Runs `ts sets inventory` on one Model and checks the shape and the classes it knows.

Usage:
    python tools/smoke-tests/smoke_ts_object_set_manager.py --ts-profile se-thoughtspot \\
        --model-guid 829a3344-657c-4d34-918d-84a7438afb59
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult, run_ts, ts_auth_check  # noqa: E402

CLASSES = {"KEEP_FILTER", "REVIEW_MANUAL", "KEEP_SHARED", "CANDIDATE_ANSWER",
           "CANDIDATE_VIZ", "REVIEW_DELETE"}
PROV = {"DIRECT", "REQUIRED", "EXPLAINED", "UNEXPLAINED", "UNKNOWN"}
DUNDER = "829a3344-657c-4d34-918d-84a7438afb59"


def _fail(msg: str) -> None:
    # Explicit raise, not `assert`: `python -O` strips asserts and would pass silently.
    raise RuntimeError(msg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts-profile", required=True)
    ap.add_argument("--model-guid", required=True)
    a = ap.parse_args()
    r = SmokeTestResult()
    ok, _ = r.step("auth", ts_auth_check, a.ts_profile)
    if not ok:
        return r.summary()
    tmp = Path(tempfile.mkdtemp(prefix="smoke-sets-tml-"))
    try:
        return _run(a, r, tmp / "tml")
    finally:  # also on an early return when the inventory step fails
        shutil.rmtree(tmp, ignore_errors=True)


def _run(a, r: SmokeTestResult, tml_dir: Path) -> int:
    ok, inv = r.step("inventory", run_ts,
                     ["sets", "inventory", "--model", a.model_guid,
                      "--export-tml", str(tml_dir)], a.ts_profile)
    if not ok:
        return r.summary()

    def check():
        if inv.get("schema") != "ts-sets-inventory/1":
            _fail(f"schema {inv.get('schema')!r}")
        if len(inv["orgs"]) != 1 or len(inv["orgs"][0]["models"]) != 1:
            _fail(f"expected one Org with one Model, got {inv['orgs']!r:.300}")
        org = inv["orgs"][0]
        m = org["models"][0]
        if m["discovery"] != "COMPLETE":
            _fail(f"discovery {m['discovery']}: {org['notes']}")
        if m["set_count"] != len(m["sets"]) or m["set_count"] < 1:
            _fail(f"set_count {m['set_count']} vs {len(m['sets'])} sets")
        for s in m["sets"]:
            if s["class"] not in CLASSES:
                _fail(f"unknown class: {s['name']} {s['class']}")
            bad = [g for g in s["grants"] if g["provenance"] not in PROV]
            if bad:
                _fail(f"unknown provenance on {s['name']}: {bad}")
        by = {s["name"]: s["class"] for s in m["sets"]}
        r.info(f"classes: {by}")
        if org["notes"]:
            r.info(f"notes: {org['notes']}")
        # Dunder Mifflin baseline (spec Appendix A, live 2026-10-02) — re-derive if it drifts
        if a.model_guid == DUNDER:
            if m["set_count"] != 9:
                _fail(f"Dunder Mifflin: expected 9 Sets, got {m['set_count']}: {sorted(by)}")
            expected = {"Product Basket 1": "REVIEW_DELETE",
                        "Product Basket 2": "CANDIDATE_ANSWER",
                        "Product Basket PC": "KEEP_SHARED"}
            wrong = {k: by.get(k) for k, v in expected.items() if by.get(k) != v}
            if wrong:
                _fail(f"Dunder Mifflin class drift: got {wrong}, expected {expected}")

    r.step("classes and provenance", check)

    def check_tml():
        """--export-tml: one file per Set, each that Set's cohort TML (open item #9)."""
        sets = [s for o in inv["orgs"] for m in o["models"] for s in m["sets"]]
        summ = inv["summary"]
        if summ.get("tml_exported") != len(sets) or summ.get("tml_export_failed") != 0:
            _fail(f"export counts {summ.get('tml_exported')}/{summ.get('tml_export_failed')} "
                  f"for {len(sets)} Sets: {[n for o in inv['orgs'] for n in o['notes']]}")
        for s in sets:
            text = Path(s["tml_file"]).read_text(encoding="utf-8")
            if "cohort" not in text or s["guid"] not in text:
                _fail(f"{s['tml_file']} is not {s['name']}'s cohort TML")
        r.info(f"exported {len(sets)} Set TML file(s) to {tml_dir}")

    r.step("Set TML export", check_tml)
    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
