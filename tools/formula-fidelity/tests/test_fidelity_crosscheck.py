"""M1 bronze cross-check: agreement is decided at the case's own tolerance (BL-356), and the
harness steps around it (recheck, rebuild, run) neither lose nor mislabel cases.

Every value here is SYNTHETIC, authored in this file; ``formulas`` is not needed (``agree``
is a pure function). No network, no data dir.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import sys
from decimal import Decimal

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "ts-cli"))

import crosscheck_formulas as CC  # noqa: E402
import run_literal  # noqa: E402
from fidelity import literal as L  # noqa: E402
from fidelity.compare import numbers_close  # noqa: E402

TIGHT = {"rel": 1e-12}


def _num(v):
    return {"t": "num", "v": v}


# -- agree --------------------------------------------------------------------------

def test_last_digit_disagreement_is_disputed_at_case_tolerance():
    # one unit in the 11th decimal of a value near 8: ~1.2e-12 relative, inside the old
    # 1e-9 bound and outside the case's declared 1e-12 (the BL-356 relation, made up here)
    assert not CC.agree(_num("8.10000000000"), _num(8.10000000001), TIGHT)


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


def test_non_numeric_and_infinite():
    assert not CC.agree(_num("1"), {"t": "bool", "v": True}, TIGHT)
    assert not CC.agree(_num("abc"), _num(1.0), TIGHT)
    assert CC.agree(_num("inf"), _num(float("inf")), TIGHT)
    assert not CC.agree(_num("inf"), _num(1e308), TIGHT)


@pytest.mark.parametrize("exp, got", [("NaN", float("nan")), ("nan", 1.0), ("1", float("nan")),
                                      ("sNaN", 1.0), ("sNaN", float("nan"))])
def test_nan_is_never_agreement_and_never_a_crash(exp, got):
    # an oracle that says NaN is not evidence; a signalling NaN must not raise
    assert CC.agree(_num(exp), _num(got), TIGHT) is False


# -- recheck --------------------------------------------------------------------------

def test_recheck_keeps_the_case_set_and_marks_unevaluated_ids_stale():
    entries = [{"id": "a", "crosscheck": "agree"}, {"id": "b", "crosscheck": "agree"},
               {"id": "c", "crosscheck": "disputed"}]
    out, changes, stale = run_literal.recheck(
        entries, {"a": "agree", "b": "disputed", "x": "agree"})
    assert [e["id"] for e in out] == ["a", "b", "c"]  # no id added, none dropped
    assert [e["crosscheck"] for e in out] == ["agree", "disputed", "disputed"]
    assert changes == [("b", "agree", "disputed")]
    assert stale == ["c"]
    assert out[2].get("crosscheck_stale") is True
    assert "crosscheck_stale" not in out[0] and "crosscheck_stale" not in out[1]
    assert entries[1]["crosscheck"] == "agree"  # input not mutated


def test_recheck_clears_stale_once_re_evaluated():
    out, _, stale = run_literal.recheck(
        [{"id": "a", "crosscheck": "agree", "crosscheck_stale": True}], {"a": "agree"})
    assert stale == [] and "crosscheck_stale" not in out[0]


def test_stale_flag_survives_the_manifest_line():
    assert '"crosscheck_stale": true' in L.manifest_line(
        {"id": "a", "source": "poi", "crosscheck": "agree", "crosscheck_stale": True})


def test_crosscheck_from_the_old_rule_is_refused():
    with pytest.raises(L.DataError, match="predates BL-356"):
        run_literal.check_crosscheck_rule({"a": {"status": "agree", "bronze": {}}})
    with pytest.raises(L.DataError):
        run_literal.check_crosscheck_rule({"a": {"status": "disputed", "bronze": {}}})


def test_crosscheck_from_the_new_rule_is_accepted():
    run_literal.check_crosscheck_rule({
        "a": {"status": "agree", "bronze": {}, "tolerance": TIGHT},
        "b": {"status": "unavailable", "bronze": "#NAME?"}})  # undecided: nothing to check


# -- rebuild ---------------------------------------------------------------------------

def test_rebuild_drops_cases_now_disputed():
    run_cases = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    entries = [{"id": "a", "crosscheck": "agree"}, {"id": "b", "crosscheck": "disputed"},
               {"id": "c", "crosscheck": "unavailable"}]
    kept, dropped = run_literal.drop_disputed(run_cases, entries)
    assert [it["id"] for it in kept] == ["a", "c"]
    assert dropped == ["b"]


def test_missing_from_run_lists_non_disputed_ids_only():
    entries = [{"id": "a", "crosscheck": "agree"}, {"id": "b", "crosscheck": "disputed"},
               {"id": "c", "crosscheck": "unavailable"}, {"id": "d", "crosscheck": "agree"}]
    assert run_literal.missing_from_run([{"id": "a"}], entries) == ["c", "d"]
    assert run_literal.missing_from_run([{"id": x} for x in "acd"], entries) == []


def test_rebuild_refuses_a_run_that_misses_manifest_ids(monkeypatch, tmp_path, capsys):
    entries = [{"id": "a", "crosscheck": "agree"}, {"id": "b", "crosscheck": "agree"}]
    full = tmp_path / "full.json"
    full.write_text('{"run": {}, "cases": [{"id": "a"}]}')
    monkeypatch.setattr(run_literal, "_load", lambda args: (tmp_path, entries, [], {}))
    called = []
    monkeypatch.setattr(run_literal, "_outputs", lambda *a: called.append(a))
    args = run_literal._args(["--data-dir", str(tmp_path), "rebuild", "--manifest", "m",
                              "--results", "r", "--full-run", str(full)])
    assert run_literal.cmd_rebuild(args) == 2
    assert "b" in capsys.readouterr().err and not called
    args.allow_partial = True
    assert run_literal.cmd_rebuild(args) == 0 and called


# -- run -------------------------------------------------------------------------------

def test_fresh_path_never_overwrites(tmp_path):
    p = tmp_path / "2026-10-07-excel-m1-full.json"
    assert run_literal.fresh_path(p) == p
    p.write_text("{}")
    now = _dt.datetime(2026, 10, 7, 2, 57, 39, tzinfo=_dt.timezone.utc)
    alt = run_literal.fresh_path(p, now)
    assert alt.name == "2026-10-07-excel-m1-full-025739Z.json"
    alt.write_text("{}")
    with pytest.raises(L.DataError, match="refusing to overwrite"):
        run_literal.fresh_path(p, now)
