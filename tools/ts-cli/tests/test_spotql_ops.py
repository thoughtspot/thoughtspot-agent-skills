"""Unit tests for ts_cli.spotql_ops — pure aggregate-function classification behind
`ts spotql classify-columns` (BL-087 codification of two drifted keyword lists).

Pure-function tests — no ThoughtSpot connection required.
"""
from ts_cli.spotql_ops import (
    classify_expr,
    classify_model_columns,
    is_aggregate_expr,
)


# ---------------------------------------------------------------------------
# is_aggregate_expr / classify_expr — across the full canonical function list
# ---------------------------------------------------------------------------

AGGREGATE_EXAMPLES = [
    "sum([Amount])",
    "count([Order ID])",
    "count_distinct([Customer ID])",
    "unique count([Customer ID])",
    "average([Amount])",
    "min([Amount])",
    "max([Amount])",
    "median([Amount])",
    "stddev([Amount])",
    "variance([Amount])",
    "sum_if([Amount], [Region] = 'West')",
    "unique_count_if([Customer ID], [Region] = 'West')",
    "cumulative_sum([Amount])",
    "cumulative_agg([Amount])",
    "moving_average([Amount], 3)",
    "moving_sum([Amount], 3)",
    "group_aggregate([Amount])",
    "group_count([Order ID])",
    "rank([Amount])",
    "rank_percentile([Amount])",
    "last_value([Amount])",
    "first_value([Amount])",
]


def test_is_aggregate_expr_true_for_every_canonical_function():
    for expr in AGGREGATE_EXAMPLES:
        assert is_aggregate_expr(expr) is True, f"expected aggregate: {expr!r}"


def test_is_aggregate_expr_is_case_insensitive():
    assert is_aggregate_expr("SUM([Amount])") is True
    assert is_aggregate_expr("Sum([Amount])") is True
    assert is_aggregate_expr("GROUP_AGGREGATE([Amount])") is True


def test_is_aggregate_expr_false_for_plain_arithmetic():
    assert is_aggregate_expr("[Revenue] - [Cost]") is False


def test_is_aggregate_expr_false_for_conditional_formula():
    assert is_aggregate_expr("if ( [Revenue] > 10000 ) then 'High' else 'Low'") is False


def test_is_aggregate_expr_false_for_ratio_of_plain_columns():
    assert is_aggregate_expr(
        "( [Revenue] - [Prior Year Revenue] ) / [Prior Year Revenue]"
    ) is False


def test_is_aggregate_expr_false_for_empty_or_none():
    assert is_aggregate_expr("") is False
    assert is_aggregate_expr(None) is False


def test_is_aggregate_expr_does_not_false_positive_on_column_named_like_a_function():
    # A column named "Sum Total" (no immediately-following paren) must not match —
    # only an actual function call sum(...) should trigger.
    assert is_aggregate_expr("[Sum Total] + [Count Total]") is False


def test_classify_expr_measure_for_aggregate():
    result = classify_expr("sum([Amount])")
    assert result == {"column_type": "MEASURE", "aggregation": "SUM", "is_aggregate": True}


def test_classify_expr_attribute_for_non_aggregate():
    result = classify_expr("[Revenue] - [Cost]")
    assert result == {"column_type": "ATTRIBUTE", "aggregation": None, "is_aggregate": False}


def test_classify_expr_aggregation_always_sum_for_measure_regardless_of_which_func():
    # ThoughtSpot ignores the aggregation property on formula columns at query
    # time (self-contained expr) — SUM is the documented convention for ALL
    # MEASURE formulas, not just ones using sum().
    result = classify_expr("max([Amount])")
    assert result["column_type"] == "MEASURE"
    assert result["aggregation"] == "SUM"


# ---------------------------------------------------------------------------
# classify_model_columns — small Model TML fixture
# ---------------------------------------------------------------------------

MODEL_TML_FIXTURE = {
    "guid": "model-guid-123",
    "model": {
        "columns": [
            {
                "name": "Region",
                "column_id": "FACT_ORDERS::REGION",
                "properties": {"column_type": "ATTRIBUTE"},
            },
            {
                "name": "Amount",
                "column_id": "FACT_ORDERS::AMOUNT",
                "properties": {"column_type": "MEASURE"},
            },
            {
                "name": "Profit Margin",
                "formula_id": "formula_Profit Margin",
                "properties": {"column_type": "MEASURE"},
            },
            {
                "name": "Total Employees",
                "formula_id": "formula_Total Employees",
                "properties": {"column_type": "MEASURE"},
            },
        ],
        "formulas": [
            {
                "id": "formula_Profit Margin",
                "name": "Profit Margin",
                "expr": "[Revenue] - [Cost]",
            },
            {
                "id": "formula_Total Employees",
                "name": "Total Employees",
                "expr": "sum([Employees])",
            },
        ],
    },
}


def _by_name(results, name):
    return next(r for r in results if r["name"] == name)


def test_classify_model_columns_returns_one_entry_per_column():
    results = classify_model_columns(MODEL_TML_FIXTURE)
    assert len(results) == 4
    assert {r["name"] for r in results} == {
        "Region", "Amount", "Profit Margin", "Total Employees",
    }


def test_classify_model_columns_attribute():
    r = _by_name(classify_model_columns(MODEL_TML_FIXTURE), "Region")
    assert r["column_type"] == "ATTRIBUTE"
    assert r["kind"] == "attribute"
    assert r["needs_agg"] is False
    assert r["aggregation"] is None


def test_classify_model_columns_raw_measure_plain_column():
    r = _by_name(classify_model_columns(MODEL_TML_FIXTURE), "Amount")
    assert r["column_type"] == "MEASURE"
    assert r["kind"] == "raw_measure"
    assert r["needs_agg"] is False
    assert r["aggregation"] == "SUM"


def test_classify_model_columns_raw_measure_non_aggregate_formula():
    # MEASURE column backed by a formula whose expr has no aggregate call —
    # still a raw measure: query-time SUM/AVG/etc. applies on top.
    r = _by_name(classify_model_columns(MODEL_TML_FIXTURE), "Profit Margin")
    assert r["column_type"] == "MEASURE"
    assert r["kind"] == "raw_measure"
    assert r["needs_agg"] is False
    assert r["aggregation"] == "SUM"


def test_classify_model_columns_aggregate_formula_measure():
    r = _by_name(classify_model_columns(MODEL_TML_FIXTURE), "Total Employees")
    assert r["column_type"] == "MEASURE"
    assert r["kind"] == "aggregate_measure"
    assert r["needs_agg"] is True
    assert r["aggregation"] is None


def test_classify_model_columns_respects_explicit_aggregation_property():
    tml = {
        "model": {
            "columns": [
                {
                    "name": "Avg Amount",
                    "column_id": "FACT_ORDERS::AMOUNT",
                    "properties": {"column_type": "MEASURE", "aggregation": "AVERAGE"},
                },
            ],
            "formulas": [],
        },
    }
    r = _by_name(classify_model_columns(tml), "Avg Amount")
    assert r["kind"] == "raw_measure"
    assert r["aggregation"] == "AVERAGE"


def test_classify_model_columns_missing_formula_id_falls_back_to_raw():
    # A formula_id that doesn't resolve to any formulas[] entry (malformed/partial
    # export) must not crash — conservative fallback to raw_measure.
    tml = {
        "model": {
            "columns": [
                {
                    "name": "Orphan Formula Column",
                    "formula_id": "formula_does_not_exist",
                    "properties": {"column_type": "MEASURE"},
                },
            ],
            "formulas": [],
        },
    }
    r = _by_name(classify_model_columns(tml), "Orphan Formula Column")
    assert r["kind"] == "raw_measure"
    assert r["needs_agg"] is False


def test_classify_model_columns_accepts_bare_model_dict_without_wrapper():
    bare = MODEL_TML_FIXTURE["model"]
    results = classify_model_columns(bare)
    assert len(results) == 4


def test_classify_model_columns_empty_model_returns_empty_list():
    assert classify_model_columns({"model": {}}) == []
