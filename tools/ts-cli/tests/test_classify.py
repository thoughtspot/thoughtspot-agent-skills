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
    """The audit-vs-migrate parity contract, including the orphan carve-out.

    Migrate (SKILL.md Step 3g) excludes orphan calcs from `translate-formulas`/
    `build-model` entirely before they ever reach the translator. classify_formulas
    must mirror that exclusion: an orphan is tiered "orphan" unconditionally and is
    never allowed to leak into (or be compared against) the translate verdict — even
    when its expression is syntactically valid and would otherwise translate cleanly.
    "Ghost" below (`SUM([X])`) is exactly that case: it only "orphans" because it
    references a table missing from the datasource, not because of an unsupported
    construct.
    """
    formulas = [
        _mk("Native", "SUM([REVENUE])"),
        _mk("Lod", "{FIXED [R] : SUM([S])}"),
        _mk("Geo", "MAKEPOINT([lat],[lon])"),
        _mk("Split", "SPLIT([Name], ' ', 1)"),          # unmapped -> skipped
        _mk("Ghost", "SUM([X])"),                        # orphan: valid syntax, excluded by policy
    ]
    orphan_calcs = {"Ghost"}
    c = classify_formulas(formulas, orphan_calcs=orphan_calcs)

    # (a) The orphan is always tiered "orphan".
    ghost_row = next(r for r in c["formulas"] if r["name"] == "Ghost")
    assert ghost_row["tier"] == "orphan"

    # Independent translate_formulas() call over the NON-orphan formulas only — this
    # is what migrate actually feeds the translator (Step 3g excludes orphans first),
    # so classify's translate_stats-driven translated set must match THIS, not a run
    # over the full formula set.
    non_orphan_formulas = [f for f in formulas if f["name"] not in orphan_calcs]
    t = translate_formulas(non_orphan_formulas)
    translated = {x["name"] for x in t["translated"]}

    # (b) The orphan must NOT be present in the translated set that backs classify's
    # translate_stats, and translate_stats itself must equal the non-orphan-only run
    # (both in shape AND in the "total" count — 4, not 5). If FIX 1 were reverted
    # (translate_formulas called on the FULL formula set, orphans included), "Ghost" —
    # syntactically valid SUM([X]) — would land in `translated`, classify's
    # translate_stats["total"] would be 5 instead of 4, and every assertion below
    # would trip.
    assert "Ghost" not in translated, "orphan leaked into the translate verdict"
    assert c["translate_stats"]["total"] == len(non_orphan_formulas), (
        "translate_stats includes the orphan — orphans must be excluded from the "
        "translate_formulas() call entirely, not merely re-tiered afterward"
    )
    assert c["translate_stats"] == t["stats"]

    # (c) The translatable<->translated invariant holds over the non-orphan formulas
    # only (orphans are excluded from both sides, matching migrate's exclusion).
    for row in c["formulas"]:
        if row["name"] in orphan_calcs:
            continue
        if row["tier"] in TRANSLATABLE_TIERS:
            assert row["name"] in translated, f"{row['name']} labeled translatable but translate skipped it"
        else:
            assert row["name"] not in translated, f"{row['name']} labeled untranslatable but translate produced it"
