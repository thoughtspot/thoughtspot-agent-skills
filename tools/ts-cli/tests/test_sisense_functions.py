"""Unit tests for ts_cli.sisense.functions — JAQL -> ThoughtSpot translation.

Pure functions, no live cluster (per .claude/rules/ts-cli.md). Covers the deterministic
safe subset, the placeholder+agg resolution, case->nested-if and 2-arg-round PARTIAL
caveats, plain-agg translation, and the NEEDS-REVIEW gate for unsupported/unknown funcs.
"""
from ts_cli.sisense.functions import AGG_MAP, FUNCTION_MAP, UNSUPPORTED, translate_agg, translate_jaql


def test_maps_present():
    assert AGG_MAP["sum"] == "SUM"
    assert FUNCTION_MAP["ceiling"] == "ceil"
    assert "rank" in UNSUPPORTED


def test_count_is_distinct_dupcount_is_total():
    # Sisense count == unique/distinct; dupCount/countduplicates == exact total (verified vs docs)
    assert AGG_MAP["count"] == "COUNT_DISTINCT"
    assert AGG_MAP["countduplicates"] == "COUNT"
    assert AGG_MAP["dupcount"] == "COUNT"
    assert translate_agg("count") == ("COUNT_DISTINCT", "Migrated", "")
    assert translate_agg("countduplicates") == ("COUNT", "Migrated", "")


def test_simple_agg_wrapped_placeholder():
    # sum([rev]) with rev already wrapped -> substitute bare column, map sum
    expr, status, _ = translate_jaql("sum([rev])", {"rev": {"dim": "[Commerce.Revenue]"}})
    assert status == "Migrated"
    assert expr == "sum([Revenue])"


def test_bare_placeholder_applies_context_agg():
    # bare [rev] with a context agg -> agg([Column])
    expr, status, _ = translate_jaql("[rev] / 10", {"rev": {"dim": "[Commerce.Revenue]", "agg": "sum"}})
    assert status == "Migrated"
    assert expr == "sum([Revenue]) / 10"


def test_function_rename():
    expr, status, _ = translate_jaql("ceiling([x])", {"x": {"dim": "[T.Cost]"}})
    assert status == "Migrated"
    assert expr == "ceil([Cost])"


def test_ddiff_to_diff_days():
    expr, status, _ = translate_jaql(
        "ddiff([a], [b])", {"a": {"dim": "[T.Start]"}, "b": {"dim": "[T.End]"}})
    assert status == "Migrated"
    assert expr == "diff_days([Start], [End])"


def test_countduplicates_agg_is_exact_count():
    # Sisense dupCount == exact total count -> TS count(), Migrated (NOT approximate)
    expr, status, _ = translate_jaql("[v]", {"v": {"dim": "[T.Visit ID]", "agg": "countduplicates"}})
    assert status == "Migrated"
    assert expr == "count([Visit ID])"


def test_count_agg_is_unique_count():
    # Sisense count == distinct -> TS `unique count`
    expr, status, _ = translate_jaql("[c]", {"c": {"dim": "[T.Customer]", "agg": "count"}})
    assert status == "Migrated"
    assert expr == "unique count([Customer])"


def test_if_maps_to_then_else():
    # Functional if(cond, a, b) -> ThoughtSpot `if (cond) then a else b`, not if(cond, a, b)
    expr, status, _ = translate_jaql("if([q] > 0, 1, 0)", {"q": {"dim": "[T.Qty]"}})
    assert status == "Migrated"
    assert expr == "if ([Qty] > 0) then 1 else 0"


def test_nested_if_maps_to_nested_then_else():
    expr, status, _ = translate_jaql(
        "if([q] > 0, 1, if([q] < 0, -1, 0))", {"q": {"dim": "[T.Qty]"}})
    assert status == "Migrated"
    assert expr == "if ([Qty] > 0) then 1 else if ([Qty] < 0) then -1 else 0"


def test_case_needs_review():
    # `case` multi-branch has no safe 1:1 -> flagged, never emitted as invalid syntax
    expr, status, note = translate_jaql("case([x])", {"x": {"dim": "[T.Cost]"}})
    assert expr is None
    assert status == "NEEDS REVIEW"
    assert "case" in note.lower()


def test_non_3arg_if_needs_review():
    expr, status, _ = translate_jaql("if([q] > 0, 1)", {"q": {"dim": "[T.Qty]"}})
    assert expr is None
    assert status == "NEEDS REVIEW"


def test_paren_strip_only_date_levels():
    # A date-hierarchy tag is stripped, a real parenthetical name is preserved
    e1, _, _ = translate_jaql("[d]", {"d": {"dim": "[T.Order Date (Calendar)]", "agg": "max"}})
    assert e1 == "max([Order Date])"
    e2, _, _ = translate_jaql("[p]", {"p": {"dim": "[T.Profit (Adjusted)]", "agg": "sum"}})
    assert e2 == "sum([Profit (Adjusted)])"


def test_round_two_arg_partial():
    expr, status, note = translate_jaql("round([x], 2)", {"x": {"dim": "[T.Cost]"}})
    assert status == "Approximated"
    assert expr.startswith("round([Cost]")
    assert "increment" in note


def test_unsupported_function_needs_review():
    expr, status, note = translate_jaql("rank([x])", {"x": {"dim": "[T.Cost]"}})
    assert expr is None
    assert status == "NEEDS REVIEW"
    assert "rank" in note


def test_unknown_function_needs_review():
    expr, status, note = translate_jaql("foobar([x])", {"x": {"dim": "[T.Cost]"}})
    assert expr is None
    assert status == "NEEDS REVIEW"
    assert "foobar" in note


def test_nested_formula_recurses():
    ctx = {"m": {"formula": "sum([r])", "context": {"r": {"dim": "[T.Revenue]"}}}}
    expr, status, _ = translate_jaql("[m] * 2", ctx)
    assert status == "Migrated"
    assert expr == "(sum([Revenue])) * 2"


def test_translate_agg_simple_and_review():
    assert translate_agg("sum") == ("SUM", "Migrated", "")
    kw, status, note = translate_agg("median")
    assert kw is None and status == "NEEDS REVIEW" and "median" in note
