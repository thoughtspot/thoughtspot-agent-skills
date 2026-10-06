"""M1's import failures, re-translated: none may come back TRANSLATED but ill-typed.

Opt-in (needs ``$FORMULA_FIDELITY_DATA``): the cases and the stored 2026-10-06 run live in the
data dir outside the repo, and are read from there at test time — nothing from the corpus is in
this file. Each case the 2026-10-06 run recorded as rejected at import is translated again with
the current translator and its M1 column context; the result must be NEEDS_REVIEW, or a
formula that is different from the rejected one and passes the type checker (BL-352..355).
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


def test_m1_import_failures_are_never_translated_ill_typed():
    import run_literal
    from ts_cli.excel.helpers import from_text
    from ts_cli.excel.typecheck import check, type_of_data_type

    d = _data_dir()
    rejected = _rejected_at_import(json.loads((d / RUN).read_text(encoding="utf-8")))
    assert len(rejected) == 36  # the report's 36 rejected at import
    entries = L.parse_manifest(MANIFEST.read_text())
    cases, fixture, broken = L.materialise(entries, L.SourceCache(d))
    assert not broken
    types = {c["name"]: type_of_data_type(c["ts_type"]) for c in fixture["columns"]}

    def col_type(node):
        return types.get(node.get("column") or node.get("name"))

    seen, bad = 0, []
    for case in cases:
        before = rejected.get(case["id"])
        if before is None:
            continue
        seen += 1
        tr = run_literal.translate_literal_case(case, fixture, "T")
        if tr["status"] == "NEEDS_REVIEW":
            continue
        old_text = before["translation"]["formula"]
        errs = check(from_text(tr["formula"]), col_type)[0]
        prefix = old_text[old_text.index("[") + 1:old_text.index("::")] if "::" in old_text else ""
        if errs or (prefix and tr["formula"] == old_text.replace(prefix, "T")):
            bad.append((case["id"], tr["status"], errs))
    assert seen == len(rejected)
    assert bad == []
