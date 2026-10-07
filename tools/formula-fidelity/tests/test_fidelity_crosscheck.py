"""M1 bronze cross-check: agreement is decided at the case's own tolerance (BL-356).

Synthetic values only; ``formulas`` is not needed (``agree`` is a pure function).
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "ts-cli"))

import crosscheck_formulas as CC  # noqa: E402
import run_literal  # noqa: E402
from fidelity.compare import numbers_close  # noqa: E402
from decimal import Decimal  # noqa: E402

TIGHT = {"rel": 1e-12}


def _num(v):
    return {"t": "num", "v": v}


def test_last_digit_disagreement_is_disputed_at_case_tolerance():
    # ~1.2e-12 relative: inside the old 1e-9 bound, outside the case's declared 1e-12
    assert not CC.agree(_num("8.23456789013"), _num(8.23456789014), TIGHT)


def test_float_representation_noise_still_agrees():
    assert CC.agree(_num("0.3"), _num(0.1 + 0.2), TIGHT)
    assert CC.agree(_num("3"), _num(3.0), TIGHT)


def test_declared_abs_tolerance_is_honoured():
    tol = {"rel": 1e-12, "abs": 5e-13}
    assert CC.agree(_num("0"), _num(4e-13), tol)
    assert not CC.agree(_num("0"), _num(6e-13), tol)


def test_agree_matches_the_scorer_rule():
    # whatever the cross-check accepts, the scorer accepts, and vice versa
    for exp, got in (("1.0000000000001", 1.0), ("1.000000000001", 1.0),
                     ("123456.789", 123456.78900001), ("-2.5", -2.5)):
        assert CC.agree(_num(exp), _num(got), TIGHT) == numbers_close(
            Decimal(exp), Decimal(repr(got)), TIGHT)


def test_non_numeric_and_non_finite():
    assert not CC.agree(_num("1"), {"t": "bool", "v": True}, TIGHT)
    assert not CC.agree(_num("abc"), _num(1.0), TIGHT)
    assert CC.agree(_num("inf"), _num(float("inf")), TIGHT)
    assert not CC.agree(_num("inf"), _num(1e308), TIGHT)


def test_recheck_keeps_the_case_set_and_unevaluated_statuses():
    entries = [{"id": "a", "crosscheck": "agree"}, {"id": "b", "crosscheck": "agree"},
               {"id": "c", "crosscheck": "disputed"}]
    out, changes = run_literal.recheck(entries, {"a": "agree", "b": "disputed", "x": "agree"})
    assert [e["id"] for e in out] == ["a", "b", "c"]  # no id added, none dropped
    assert [e["crosscheck"] for e in out] == ["agree", "disputed", "disputed"]
    assert changes == [("b", "agree", "disputed")]
    assert entries[1]["crosscheck"] == "agree"  # input not mutated


def test_rebuild_drops_cases_now_disputed():
    run_cases = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    entries = [{"id": "a", "crosscheck": "agree"}, {"id": "b", "crosscheck": "disputed"},
               {"id": "c", "crosscheck": "unavailable"}]
    kept, dropped = run_literal.drop_disputed(run_cases, entries)
    assert [it["id"] for it in kept] == ["a", "c"]
    assert dropped == ["b"]
