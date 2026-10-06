"""Report builder: silent wrong answers lead, every class is counted, repros are minimal."""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from fidelity import compare as K  # noqa: E402
from fidelity.report import build_report, referenced_columns, repro_rows  # noqa: E402

FX = {"name": "M0", "key": "ROW_ID", "group": "GRP",
      "columns": [{"name": n, "sf_type": "X", "ts_type": "X", "column_type": "ATTRIBUTE"}
                  for n in ("ROW_ID", "GRP", "S1", "S2", "N1")],
      "rows": [{"ROW_ID": 1, "GRP": "A", "S1": "Apple", "S2": "pie", "N1": 1},
               {"ROW_ID": 2, "GRP": "A", "S1": "apple", "S2": None, "N1": 2}]}
N = lambda v: {"t": "num", "v": str(v)}  # noqa: E731
S = lambda v: {"t": "str", "v": v}  # noqa: E731


def _item(cid, formula, verdict_inputs, kd=None, role="row", status="TRANSLATED"):
    oracle, actual = verdict_inputs
    case = {"id": cid, "source_formula": formula, "role": role, "fixture": "fx",
            "group_by": "GRP" if role == "aggregate" else None,
            "tolerance": {"rel": 1e-12}, "known_divergence": kd}
    tr = {"status": status, "formula": f"emit [ZZ_T::S1] {cid}"}
    it = dict(case, translation=tr, oracle=oracle, actual=actual, import_error=None)
    it["result"] = K.classify_case(case, oracle, tr, None, actual)
    return it


def _run(items):
    return {"run": {"ts_table": "ZZ_T", "date": "2026-10-06", "runtime_s": 9.9,
                    "cleanup": {"ts_confirmed_absent": True, "warehouse_confirmed_absent": True}},
            "cases": items}


def test_report_leads_with_silent_wrong_and_groups_by_cause():
    bug = {"tag": "substr", "kind": "translator-bug", "backlog": "BL-340", "reason": "r"}
    sem = {"tag": "ci", "kind": "platform-semantics", "backlog": "BL-333", "reason": "r"}
    items = [
        _item("ok", "N1", ({"values": {"1": N(1)}}, {"values": {"1": N(1)}})),
        _item("new", "S1", ({"values": {"1": S("a")}}, {"values": {"1": S("b")}})),
        _item("bug", "SUBSTR(S1, 2, 3)", ({"values": {"1": S("ppl")}}, {"values": {"1": S("ple")}}), bug),
        _item("sem", "S1 = 'Apple'", ({"values": {"2": N(0)}}, {"values": {"2": N(1)}}), sem,
              status="APPROXIMATED"),
    ]
    md = build_report(_run(items), {"fx": FX}, "T")
    head, _, rest = md.partition("## Counts by class")
    assert head.index("## Silent wrong answers") < head.index("### Unexplained (1)") \
        < head.index("### Translator bugs (open BL item) (1)") \
        < head.index("### Documented platform semantics (translator warns) (1)")
    assert "**3 silent wrong answer(s)**" in md and "1 of 4 matched" in md
    assert "substr (BL-340)" in head and "ci (BL-333)" in head
    assert "expected 'ppl', ThoughtSpot returned 'ple' (VALUE_DIFF)" in head
    assert "[T::S1]" in md and "[ZZ_T::" not in md       # long scratch name shortened
    assert "| MISMATCH | 3 |" in rest and "| MATCH | 1 |" in rest and "**4**" in rest
    assert md.index("## Counts by class") < md.index("## Per-case results")


def test_loud_failures_listed_with_bl_and_cleanup_flagged():
    case = {"id": "imp", "source_formula": "TO_CHAR(S1)", "role": "row", "fixture": "fx",
            "group_by": None, "tolerance": {"rel": 0},
            "known_divergence": {"tag": "t", "kind": "translator-bug", "backlog": "BL-343",
                                 "reason": "r"}}
    tr = {"status": "TRANSLATED", "formula": "to_string ( x )"}
    oracle = {"values": {"1": S("x")}}
    it = dict(case, translation=tr, oracle=oracle, actual=None,
              import_error="expects 2 arguments")
    it["result"] = K.classify_case(case, oracle, tr, "expects 2 arguments", None)
    run = _run([it])
    run["run"]["cleanup"] = {"ts_confirmed_absent": False, "remaining": ["g-1"]}
    md = build_report(run, {"fx": FX}, "T")
    assert "| imp | IMPORT_FAILED |" in md and "BL-343: expects 2 arguments" in md
    assert "**0 silent wrong answer(s)**" in md
    assert "**objects left behind:** `['g-1']`" in md


def test_repro_rows_keep_only_referenced_columns():
    assert referenced_columns("CONCAT(S1, 'S2')", FX) == ["S1"]  # literal not a column
    case = {"source_formula": "SUBSTR(S1, 2, 3)", "role": "row"}
    assert repro_rows(case, FX, "2") == [{"ROW_ID": 2, "S1": "apple"}]
    agg = {"source_formula": "SUM(N1)", "role": "aggregate", "group_by": "GRP"}
    assert repro_rows(agg, FX, "A") == [{"ROW_ID": 1, "GRP": "A", "N1": 1},
                                        {"ROW_ID": 2, "GRP": "A", "N1": 2}]
