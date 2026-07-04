# tools/ts-cli/tests/test_classify.py
from __future__ import annotations
from ts_cli.tableau.classify import classify_formulas, TRANSLATABLE_TIERS
from ts_cli.tableau_translate import translate_formulas


def _mk(caption, formula):
    return {"caption": caption, "name": caption, "formula": formula,
            "role": "measure", "datatype": "real", "datasource": "t"}


def test_tiers_assigned_by_family():
    formulas = [
        _mk("Rev", "SUM([REVENUE])"),
        _mk("LOD1", "{FIXED [Region] : SUM([Sales])}"),
        _mk("Run1", "RUNNING_SUM(SUM([Sales]))"),
        _mk("Win1", "WINDOW_SUM(SUM([Sales]))"),
    ]
    out = classify_formulas(formulas)
    by = {f["name"]: f["tier"] for f in out["formulas"]}
    assert by["Rev"] == "native"
    assert by["LOD1"] == "lod"
    assert by["Run1"] == "cumulative"
    assert by["Win1"] == "moving"
    assert out["tier_counts"]["native"] == 1


def test_orphan_tier_overrides():
    formulas = [_mk("Ghost", "SUM([REVENUE])")]
    out = classify_formulas(formulas, orphan_calcs={"Ghost"})
    assert out["formulas"][0]["tier"] == "orphan"


def test_complexity_score_present():
    out = classify_formulas([_mk("Rev", "SUM([REVENUE])")])
    assert isinstance(out["formulas"][0]["complexity"], int)


def test_classify_agrees_with_translate_verdict():
    formulas = [
        _mk("Native", "SUM([REVENUE])"),
        _mk("Lod", "{FIXED [R] : SUM([S])}"),
        _mk("Geo", "MAKEPOINT([lat],[lon])"),
        _mk("Split", "SPLIT([Name], ' ', 1)"),          # unmapped -> skipped
    ]
    c = classify_formulas(formulas)
    t = translate_formulas(formulas)
    translated = {x["name"] for x in t["translated"]}
    for row in c["formulas"]:
        if row["tier"] in TRANSLATABLE_TIERS:
            assert row["name"] in translated, f"{row['name']} labeled translatable but translate skipped it"
        else:
            assert row["name"] not in translated, f"{row['name']} labeled untranslatable but translate produced it"
