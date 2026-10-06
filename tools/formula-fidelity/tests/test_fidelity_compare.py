"""Comparison rules (harness design §5) and case classification."""
from __future__ import annotations

import datetime as dt
import pathlib
import sys
from decimal import Decimal

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from fidelity import compare as K  # noqa: E402

TOL = {"rel": 1e-12, "abs": 1e-12}
N = lambda v: {"t": "num", "v": str(v)}  # noqa: E731


def test_canon_driver_values():
    assert K.canon(None) == {"t": "null"}
    assert K.canon(True) == {"t": "bool", "v": True}
    assert K.canon(3) == {"t": "num", "v": "3"}
    assert K.canon(Decimal("1.838710")) == {"t": "num", "v": "1.838710"}
    assert K.canon(0.1) == {"t": "num", "v": "0.1"}
    assert K.canon(dt.date(2026, 2, 1)) == {"t": "date", "v": "2026-02-01"}
    assert K.canon(dt.datetime(2026, 2, 1, 3, 4, 5)) == {"t": "datetime", "v": "2026-02-01T03:04:05"}
    assert K.canon("x") == {"t": "str", "v": "x"}


def test_canon_ts_typed_cells():
    assert K.canon_ts(1770681600, "DATE") == {"t": "date", "v": "2026-02-10"}
    assert K.canon_ts("true", "BOOL") == {"t": "bool", "v": True}
    assert K.canon_ts(None, "DOUBLE") == {"t": "null"}


@pytest.mark.parametrize("exp,act,out", [
    (N(3), N("3.0"), K.EQUAL),                                   # INT == DOUBLE
    (N("1234.57"), N("1234.5700000000002"), K.EQUAL),           # within rel 1e-12
    (N(0), N("1e-13"), K.EQUAL),                                 # abs floor near zero
    (N("0.032258"), N(1), K.NUMERIC_DIFF),
    ({"t": "null"}, {"t": "null"}, K.EQUAL),
    ({"t": "null"}, N(0), K.NULL_DIFF),                          # NULL vs value
    (N(0), {"t": "null"}, K.NULL_DIFF),
    ({"t": "str", "v": "ppl"}, {"t": "str", "v": "ple"}, K.VALUE_DIFF),
    ({"t": "str", "v": "Apple"}, {"t": "str", "v": "apple"}, K.VALUE_DIFF),  # case-sensitive
    ({"t": "str", "v": ""}, {"t": "null"}, K.NULL_DIFF),
    ({"t": "bool", "v": True}, {"t": "bool", "v": True}, K.EQUAL),
    ({"t": "bool", "v": True}, N(1), K.VALUE_DIFF),             # bool never equals a number
    (N(5), {"t": "str", "v": "5"}, K.EQUAL),                     # numeric string
    ({"t": "date", "v": "2026-02-10"}, N(1770681600), K.EQUAL),  # AgentQL epoch seconds
    ({"t": "date", "v": "2026-02-10"}, N(1770681601), K.VALUE_DIFF),
    ({"t": "date", "v": "2026-02-10"}, N("1770681600.5"), K.VALUE_DIFF),
    ({"t": "date", "v": "2026-02-10"}, {"t": "datetime", "v": "2026-02-10T00:00:00"}, K.EQUAL),
    ({"t": "date", "v": "2026-02-10"}, {"t": "str", "v": "2026-02-10"}, K.EQUAL),
    ({"t": "error", "v": "Division by zero"}, {"t": "null"}, K.ERROR_EQUIV),
    ({"t": "error", "v": "Division by zero"}, N(0), K.ERROR_VS_VALUE),
    (N(1), {"t": "error", "v": "boom"}, K.TS_ERROR),
])
def test_compare_value(exp, act, out):
    assert K.compare_value(exp, act, TOL) == out


def test_tolerance_is_the_declared_one():
    assert K.compare_value(N(100), N("100.5"), {"rel": 0.01}) == K.EQUAL
    assert K.compare_value(N(100), N("100.5"), {"rel": 0.001}) == K.NUMERIC_DIFF


def test_compare_rows_shape():
    rows = K.compare_rows({"1": N(1), "2": N(2)}, {"2": N(2), "3": N(3)}, TOL)
    assert [(r["key"], r["outcome"]) for r in rows] == [
        ("1", K.MISSING), ("2", K.EQUAL), ("3", K.EXTRA)]


CASE = {"id": "c", "tolerance": TOL}
OK_T = {"status": "TRANSLATED", "formula": "x"}


def test_classify_match_and_silent_wrong():
    o = {"values": {"1": N(1), "2": N(2)}}
    r = K.classify_case(CASE, o, OK_T, None, {"values": {"1": N(1), "2": N(2)}})
    assert r["verdict"] == K.MATCH and not r["silent_wrong"]
    r = K.classify_case(CASE, o, {"status": "APPROXIMATED"}, None,
                        {"values": {"1": N(1), "2": N(3)}})
    assert r["verdict"] == K.MISMATCH and r["silent_wrong"]
    assert r["mismatch_kinds"] == [K.NUMERIC_DIFF]
    assert r["cause"]["tag"] == "unexplained" and not r["cause"]["explained"]


def test_classify_attributes_known_divergence():
    case = dict(CASE, known_divergence={"tag": "ci", "kind": "platform-semantics",
                                        "backlog": "BL-333", "reason": "r"})
    r = K.classify_case(case, {"values": {"1": {"t": "str", "v": "a"}}}, OK_T, None,
                        {"values": {"1": {"t": "str", "v": "b"}}})
    assert r["verdict"] == K.MISMATCH and r["silent_wrong"]  # classified, never hidden
    assert r["cause"] == {"explained": True, "tag": "ci", "kind": "platform-semantics",
                          "backlog": "BL-333", "reason": "r"}


def test_classify_loud_classes():
    o = {"values": {"1": N(1)}}
    assert K.classify_case(CASE, {"values": {"1": {"t": "error", "v": "bad"}}}, OK_T, None,
                           None)["verdict"] == K.ORACLE_FAILED
    assert K.classify_case(CASE, {"values": {}}, OK_T, None, None)["verdict"] == K.ORACLE_FAILED
    r = K.classify_case(CASE, o, {"status": "NEEDS_REVIEW", "notes": ["no map"]}, None, None)
    assert r["verdict"] == K.TRANSLATE_FAILED and r["detail"] == "no map"
    r = K.classify_case(CASE, o, OK_T, "error_code 14516", None)
    assert r["verdict"] == K.IMPORT_FAILED and not r["silent_wrong"]
    r = K.classify_case(CASE, o, OK_T, None, {"values": {}, "error": "[X] nope"})
    assert r["verdict"] == K.RUN_FAILED
    r = K.classify_case(CASE, o, OK_T, None, None)  # never queried: loud, not MISSING
    assert r["verdict"] == K.RUN_FAILED and not r["silent_wrong"]
    r = K.classify_case(CASE, {"values": {"1": N(1), "2": N(2)}}, OK_T, None,
                        {"values": {"1": N(1), "2": {"t": "error", "v": "x"}}})
    assert r["verdict"] == K.RUN_FAILED


def test_classify_error_equiv():
    o = {"values": {"1": N(1), "2": {"t": "error", "v": "Division by zero"}}}
    r = K.classify_case(CASE, o, OK_T, None, {"values": {"1": N(1), "2": {"t": "null"}}})
    assert r["verdict"] == K.ERROR_EQUIV and not r["silent_wrong"]
    r = K.classify_case(CASE, o, OK_T, None, {"values": {"1": N(1), "2": N(0)}})
    assert r["verdict"] == K.MISMATCH and r["mismatch_kinds"] == [K.ERROR_VS_VALUE]


def test_counts_cover_every_verdict():
    c = K.counts([{"verdict": K.MATCH}, {"verdict": K.MISMATCH}, {"verdict": K.MATCH}])
    assert c[K.MATCH] == 2 and c[K.MISMATCH] == 1 and set(c) == set(K.VERDICTS)
