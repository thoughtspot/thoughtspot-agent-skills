"""M1's import failures, re-translated: none may come back TRANSLATED but ill-typed.

Opt-in (needs ``$FORMULA_FIDELITY_DATA``): the cases and the stored 2026-10-06 run live in the
data dir outside the repo, and are read from there at test time — nothing from the corpus is in
this file. Each case the 2026-10-06 run recorded as rejected at import is translated again with
the current translator and its M1 column context, and checked against expectations that do
not come from the translator: a hand-written NEEDS_REVIEW set, and the committed live
after-fixes run (BL-352..355).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "ts-cli"))

from fidelity import literal as L  # noqa: E402

RUN = "runs/2026-10-06-excel-m1-full.json"
MANIFEST = HERE / "cases" / "excel" / "m1-manifest.jsonl"


def _data_dir() -> pathlib.Path:
    root = os.environ.get(L.DATA_DIR_ENV)
    d = pathlib.Path(root or "/nonexistent")
    if not (d / RUN).is_file():
        pytest.skip(f"${L.DATA_DIR_ENV} not set or has no {RUN}")
    return d


def _rejected_at_import(run: dict) -> dict:
    return {c["id"]: c for c in run["cases"] if c.get("import_error")}


# Independent expectations (review of #574: the first version only asked the type checker
# about its own output). Of the 36 rejected on 2026-10-06, exactly these may be NEEDS_REVIEW,
# each for a reason Excel itself gives (the report's "After fixes" section): a date-time text
# before 1900, text that is not a date, serial number 0.
EXPECTED_NEEDS_REVIEW = {
    "lo-date_time-day-sheet2-r5",
    "lo-date_time-eomonth-sheet2-r7",
    "poi-formulaevaltestdata_copy-everythingtests-f940",
}
# The live after-fixes evidence (committed, redacted: id, status, class only).
AFTER = HERE / "runs" / "2026-10-07-excel-m1.json"


def test_m1_import_failures_are_fixed_by_independent_evidence():
    import run_literal

    d = _data_dir()
    rejected = _rejected_at_import(json.loads((d / RUN).read_text(encoding="utf-8")))
    assert len(rejected) == 36  # the report's 36 rejected at import
    live = {c["id"]: c for c in json.loads(AFTER.read_text(encoding="utf-8"))["cases"]}
    entries = L.parse_manifest(MANIFEST.read_text())
    cases, fixture, broken = L.materialise(entries, L.SourceCache(d))
    assert not broken
    seen = 0
    for case in cases:
        if case["id"] not in rejected:
            continue
        seen += 1
        tr = run_literal.translate_literal_case(case, fixture, "T")
        # 1. the hand-written expectation, not the checker's say-so
        assert (tr["status"] == "NEEDS_REVIEW") == (case["id"] in EXPECTED_NEEDS_REVIEW), \
            (case["id"], tr["status"])
        # 2. the live run: ThoughtSpot accepted every translated one at import
        after = live[case["id"]]
        assert after["class"] != "IMPORT_FAILED", case["id"]
        # 3. today's translator still gives the status that run measured (no silent drift)
        assert after["translation_status"] == tr["status"], case["id"]
    assert seen == 36
