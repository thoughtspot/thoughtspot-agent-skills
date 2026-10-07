"""Case and fixture loading: strict, so a malformed case can never shrink the denominator."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools" / "ts-cli"))

from fidelity import cases as C  # noqa: E402

CASE_DIR = HERE / "cases" / "snowflake"


def _case(**over):
    base = {"id": "x-1", "dialect": "snowflake", "source_formula": "N1 + 1", "role": "row",
            "fixture": "fixture-m0.json", "tolerance": {"rel": 1e-12, "abs": 1e-12},
            "provenance": {"source": "authored in-repo, under the repository licence",
                           "licence": "LicenseRef-ThoughtSpot-EULA (repo LICENSE)"}}
    base.update(over)
    return base


def _parse(*cases):
    return C.parse_cases("\n".join(json.dumps(c) for c in cases))


def test_shipped_m0_cases_load_and_count():
    cases = C.load_cases(CASE_DIR / "m0.jsonl")
    # 50 original + 10 BL-340..343 guards + 11 from the #572 review (2026-10-06)
    # + 24 sf-fix cases for the M2 fixes and their review (BL-357..362, 2026-10-07)
    assert len(cases) == 95
    assert {c["dialect"] for c in cases} == {"snowflake"}
    fx = C.fixtures_for(cases, CASE_DIR)
    assert set(fx) == {"fixture-m0.json"}


def test_shipped_cases_reference_only_fixture_columns():
    """A case naming a column the fixture lacks would fail in the oracle, not here — catch it
    offline instead."""
    from fidelity.report import referenced_columns

    cases = C.load_cases(CASE_DIR / "m0.jsonl")
    fx = C.load_fixture(CASE_DIR / "fixture-m0.json")
    for c in cases:
        assert referenced_columns(c["source_formula"], fx) or c["source_formula"] == "COUNT(*)", c["id"]


def test_shipped_cases_carry_the_repository_licence():
    for c in C.load_cases(CASE_DIR / "m0.jsonl"):
        assert c["provenance"]["licence"] == "LicenseRef-ThoughtSpot-EULA (repo LICENSE)", c["id"]
        assert "Apache" not in c["provenance"]["licence"]


def test_fixture_has_the_promised_edge_rows():
    import datetime as dt

    fx = C.load_fixture(CASE_DIR / "fixture-m0.json")
    rows = fx["rows"]
    assert any(r["N1"] is None for r in rows) and any(r["N2"] == 0 for r in rows)
    assert any(isinstance(r["N1"], (int, float)) and r["N1"] < 0 for r in rows)
    dates = [dt.date.fromisoformat(r["D1"]) for r in rows if r["D1"]]
    assert any(d.isoweekday() == 7 for d in dates), "a Sunday"
    assert any((d + dt.timedelta(days=1)).day == 1 for d in dates), "a month end"


@pytest.mark.parametrize("over,msg", [
    ({"role": "scalar"}, "role must be"),
    ({"dialect": "cobol"}, "unknown dialect"),
    ({"role": "aggregate"}, "needs group_by"),
    ({"source_formula": "  "}, "empty source_formula"),
    ({"tolerance": {"rel": -1}}, "tolerance"),
    ({"tolerance": {"ulp": 1}}, "tolerance"),
    ({"provenance": {"source": "x"}}, "licence"),
    ({"known_divergence": {"tag": "t", "reason": "r", "kind": "vibes", "keys": ["1"]}}, "kind must be"),
    ({"known_divergence": {"tag": "t", "reason": "r", "kind": "translator-bug", "keys": ["1"]}}, "BL id"),
    ({"known_divergence": {"tag": "t", "reason": "r", "kind": "platform-semantics"}}, "keys must list"),
    ({"known_divergence": {"tag": "t", "reason": "r", "kind": "platform-semantics", "keys": []}}, "keys must list"),
    ({"known_divergence": {"tag": "t", "reason": "r", "kind": "platform-semantics", "keys": [2]}}, "keys must list"),
])
def test_bad_cases_are_rejected(over, msg):
    with pytest.raises(C.CaseError, match=msg):
        _parse(_case(**over))


def test_missing_field_and_duplicate_id_and_empty_file():
    bad = _case()
    del bad["provenance"]
    with pytest.raises(C.CaseError, match="missing field"):
        _parse(bad)
    with pytest.raises(C.CaseError, match="duplicate case id"):
        _parse(_case(), _case())
    with pytest.raises(C.CaseError, match="no cases"):
        C.parse_cases("\n\n")
    with pytest.raises(C.CaseError, match="not valid JSON"):
        C.parse_cases("{nope")


def test_fixture_validation():
    fx = {"name": "F", "key": "K", "columns": [
        {"name": "K", "sf_type": "NUMBER", "ts_type": "INT64", "column_type": "ATTRIBUTE"}],
        "rows": [{"K": 1}, {"K": 1}]}
    with pytest.raises(C.CaseError, match="unique"):
        C.check_fixture(fx)
    fx["rows"] = [{"K": 1, "Z": 2}]
    with pytest.raises(C.CaseError, match="unknown column"):
        C.check_fixture(fx)
    fx["rows"] = [{"K": 1}]
    fx["key"] = "Q"
    with pytest.raises(C.CaseError, match="key"):
        C.check_fixture(fx)


def test_write_expected_round_trips():
    cases = _parse(_case(), _case(id="x-2"))
    text = C.write_expected(cases, {"x-2": {"key_column": "ROW_ID", "values": {"1": {"t": "null"}}}})
    again = C.parse_cases(text)
    assert again[0].get("expected") is None
    assert again[1]["expected"]["values"]["1"] == {"t": "null"}


def test_key_column():
    fx = {"key": "ROW_ID"}
    assert C.key_column(_case(), fx) == "ROW_ID"
    assert C.key_column(_case(role="aggregate", group_by="GRP"), fx) == "GRP"
