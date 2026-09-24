"""Unit tests for ts_cli.powerbi.gated — the two gated measure shapes.

Pure functions, no live cluster (per .claude/rules/ts-cli.md). These shapes are the ones
`translate_dax`'s review gate rejects wholesale (CALCULATE / USERELATIONSHIP / VAR-RETURN)
even though both are mechanical and fully described by the DAX. Measured on a real
27-measure supply-chain report: 17 recognised, and the 8 left as NEEDS REVIEW are
dynamic-text captions with no ThoughtSpot equivalent.
"""
from ts_cli.powerbi.functions import translate_dax
from ts_cli.powerbi.gated import describe, parse_calculate, translate

RATIO = """VAR Hit = CALCULATE(
    DISTINCTCOUNT(Fact[Order Line]),
        NOT ISBLANK(Fact[Booked]),
        Fact[Stage] IN {"Early","On Time"})
VAR Total = CALCULATE(
    DISTINCTCOUNT(Fact[Order Line]),
        NOT ISBLANK(Fact[Booked]))
RETURN Hit/Total"""


def test_gated_count_migrates():
    expr, status, _ = translate_dax(
        "CALCULATE(DISTINCTCOUNT(Fact[Order Line]),NOT ISBLANK(Fact[Booked]))",
        home_table="Fact")
    assert status == "Migrated"
    # `unique count` with a SPACE: BL-171 records `unique_count(` as rejected (14516).
    assert expr == ("unique count (if ([Fact::Booked] != null) "
                    "then [Fact::Order Line] else null)")


def test_gated_ratio_migrates_with_the_value_set_expanded():
    expr, status, _ = translate_dax(RATIO, home_table="Fact")
    assert status == "Migrated"
    assert "[Fact::Stage] = 'Early' or [Fact::Stage] = 'On Time'" in expr
    assert expr.count("unique count") == 2


def test_userelationship_is_approximated_not_migrated():
    """A model cannot rewire which date the filter context applies to, so the measure is
    right for the grain and wrong for a page slicing on the role-playing date."""
    expr, status, note = translate_dax(
        "CALCULATE(DISTINCTCOUNT(Fact[Order Line]),"
        "USERELATIONSHIP(Cal[Date],Fact[Booked]))", home_table="Fact")
    assert status == "Approximated"
    assert expr == "unique count ([Fact::Order Line])"
    assert "USERELATIONSHIP" in note


def test_nested_calculate_keeps_the_inner_gate():
    """CALCULATE(CALCULATE(DISTINCTCOUNT(..), <gate>), USERELATIONSHIP(..)) puts the gate
    on the inner call. Reading only the outer level drops it and silently widens the
    counted population, which is worse than refusing the shape."""
    spec = parse_calculate(
        "CALCULATE(CALCULATE(DISTINCTCOUNT(Fact[Order Line]),"
        "NOT ISBLANK(Fact[Arrived])),USERELATIONSHIP(Fact[Arrived],Cal[Date]))")
    assert spec["gates"] == [("Fact", "Arrived")]
    assert spec["userelationship"] is True


def test_an_unreadable_filter_refuses_the_whole_shape():
    """Nothing is guessed: one filter argument we cannot read means no formula at all."""
    assert parse_calculate(
        "CALCULATE(DISTINCTCOUNT(Fact[Order Line]),FILTER(Fact,Fact[Qty]>5))") is None
    assert translate(
        "CALCULATE(DISTINCTCOUNT(Fact[Order Line]),FILTER(Fact,Fact[Qty]>5))") == (
        None, None, None)


def test_non_gated_dax_still_needs_review():
    expr, status, _ = translate_dax("SUMX(Sales, Sales[Qty] * Sales[Price])")
    assert expr is None and status == "NEEDS REVIEW"


def test_ratio_over_different_grains_is_refused():
    mismatched = RATIO.replace("DISTINCTCOUNT(Fact[Order Line]),\n        NOT ISBLANK(Fact[Booked]))",
                               "DISTINCTCOUNT(Fact[Shipment]),\n        NOT ISBLANK(Fact[Booked]))")
    assert translate(mismatched) == (None, None, None)


def test_describe_exposes_the_parameters_for_kpi_discovery():
    d = describe(RATIO)
    assert d["shape"] == "ratio"
    assert d["key"] == "Order Line"
    assert d["numerator_gate"] == "Booked"
    assert d["denominator_gate"] == "Booked"
    assert d["stage_col"] == "Stage"
    assert d["on_time_values"] == ["Early", "On Time"]
