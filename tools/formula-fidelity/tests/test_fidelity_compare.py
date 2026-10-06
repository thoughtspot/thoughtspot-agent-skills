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
I = lambda v: {"t": "num", "v": str(v), "ts_type": "INT64"}  # noqa: E731,E741


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
    assert K.canon_ts(10 ** 30, "DATE")["t"] == "num"           # overflow: not a date, no crash
    assert K.canon_ts(7, "INT64") == {"t": "num", "v": "7", "ts_type": "INT64"}
    assert "ts_type" not in K.canon_ts(7.5, "DOUBLE")
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
    (N(5), {"t": "str", "v": "5"}, K.EQUAL),                     # numeric oracle, numeric string
    (N(7), {"t": "str", "v": " 7"}, K.VALUE_DIFF),               # never stripped
    ({"t": "str", "v": "007"}, N(7), K.VALUE_DIFF),              # str oracle must match exactly
    ({"t": "str", "v": "7"}, N(7), K.VALUE_DIFF),
    ({"t": "date", "v": "2026-02-10"}, I(1770681600), K.EQUAL),  # AgentQL epoch seconds, INT64
    ({"t": "date", "v": "2026-02-10"}, N(1770681600), K.VALUE_DIFF),  # untyped: no epoch rule
    ({"t": "date", "v": "2026-02-10"}, I(1770681601), K.VALUE_DIFF),
    ({"t": "date", "v": "2026-02-10"}, I("1770681600.5"), K.VALUE_DIFF),
    ({"t": "date", "v": "2026-02-10"}, I("1e400"), K.VALUE_DIFF),     # overflow → VALUE_DIFF
    ({"t": "date", "v": "2026-02-10"}, I("NaN"), K.VALUE_DIFF),
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


KD = {"tag": "ci", "kind": "platform-semantics", "backlog": "BL-333", "reason": "r"}
S = lambda v: {"t": "str", "v": v}  # noqa: E731
WARN_T = {"status": "APPROXIMATED", "formula": "x", "traps": ["case-insensitive"]}


def test_classify_attributes_known_divergence_per_key():
    case = dict(CASE, known_divergence=dict(KD, keys=["1"]))
    o = {"values": {"1": S("a"), "2": S("x"), "3": S("y")}}
    r = K.classify_case(case, o, WARN_T, None,
                        {"values": {"1": S("b"), "2": S("x"), "3": S("y")}})
    assert r["verdict"] == K.MISMATCH and r["warned"] and not r["silent_wrong"]  # never hidden
    assert r["cause"]["explained"] and r["cause"]["unexplained_keys"] == []
    # a wrong key the tag does not list stays unexplained
    r = K.classify_case(case, o, WARN_T, None,
                        {"values": {"1": S("b"), "2": S("z"), "3": S("y")}})
    assert not r["cause"]["explained"] and r["cause"]["unexplained_keys"] == ["2"]


def test_stale_tag_is_flagged():
    case = dict(CASE, known_divergence=dict(KD, keys=["1", "2"]))
    o = {"values": {"1": S("a"), "2": S("x")}}
    r = K.classify_case(case, o, OK_T, None, {"values": {"1": S("a"), "2": S("x")}})
    assert r["verdict"] == K.MATCH and r["stale_divergence"]
    r = K.classify_case(case, o, OK_T, None, {"values": {"1": S("b"), "2": S("x")}})
    assert r["verdict"] == K.MISMATCH and r["stale_divergence"]
    assert r["cause"]["stale_keys"] == ["2"]


def test_case_level_tag_explains_no_key():
    case = dict(CASE, known_divergence=dict(KD, keys=["*"]))
    r = K.classify_case(case, {"values": {"1": S("a")}}, OK_T, None, {"values": {"1": S("b")}})
    assert r["silent_wrong"] and not r["cause"]["explained"]
    r = K.classify_case(case, {"values": {"1": S("a")}}, OK_T, "rejected", None)
    assert r["verdict"] == K.IMPORT_FAILED and r["cause"]["tag"] == "ci"


def test_silent_versus_warned():
    o = {"values": {"1": N(1)}}
    a = {"values": {"1": N(2)}}
    r = K.classify_case(CASE, o, OK_T, None, a)
    assert r["silent_wrong"] and not r["warned"]
    r = K.classify_case(CASE, o, {"status": "APPROXIMATED", "traps": []}, None, a)
    assert r["silent_wrong"] and not r["warned"]          # APPROXIMATED with no trap is silent
    r = K.classify_case(CASE, o, WARN_T, None, a)
    assert r["warned"] and not r["silent_wrong"]


def test_zero_rows_is_run_failed_not_silent():
    o = {"values": {"1": N(1), "2": N(2)}}
    r = K.classify_case(CASE, o, OK_T, None, {"values": {}, "zero_rows": True,
                                             "error": "AgentQL returned SUCCESS with 0 rows"})
    assert r["verdict"] == K.RUN_FAILED and not r["silent_wrong"]
    r = K.classify_case(CASE, o, OK_T, None, {"values": {}, "error": None})
    assert r["verdict"] == K.RUN_FAILED


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
