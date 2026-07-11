from ts_cli.aggregate.measures import classify_measure, build_rewrite_plans


def test_sum_column_is_directly_additive():
    plan = classify_measure("Sales", aggregation="SUM")
    assert plan["class"] == "SUM"
    assert plan["decomposable"] is True
    assert plan["components"] == [
        {"alias": "sales_sum", "source_column": "Sales", "func": "SUM", "reagg": "SUM"}
    ]
    assert plan["model_expr"] is None  # plain column, no formula needed


def test_average_decomposes_to_sum_and_count():
    plan = classify_measure("Avg Order Value", expr="average ( [Order Value] )")
    assert plan["class"] == "AVG"
    assert plan["decomposable"] is True
    aliases = [c["alias"] for c in plan["components"]]
    assert aliases == ["avg_order_value_sum", "avg_order_value_cnt"]
    assert plan["components"][0]["func"] == "SUM"
    assert plan["components"][1]["func"] == "COUNT"
    assert plan["model_expr"] == "sum ( [avg_order_value_sum] ) / sum ( [avg_order_value_cnt] )"


def test_ratio_of_additive_sums_decomposes():
    plan = classify_measure("Margin Pct", expr="sum ( [Profit] ) / sum ( [Revenue] )")
    assert plan["class"] == "RATIO"
    assert plan["decomposable"] is True
    assert len(plan["components"]) == 2
    assert plan["model_expr"] == "sum ( [margin_pct_num] ) / sum ( [margin_pct_den] )"


def test_unique_count_is_nonadditive_with_grain_requirement():
    plan = classify_measure("Customers", expr="unique count ( [Customer ID] )")
    assert plan["class"] == "NONADDITIVE"
    assert plan["decomposable"] is False
    assert plan["requires_grain_column"] == "Customer ID"


def test_unrecognised_expr_is_unknown():
    plan = classify_measure("Weird", expr="moving_average ( [X], 3 )")
    assert plan["class"] == "UNKNOWN"
    assert plan["decomposable"] is False


def test_build_rewrite_plans_reads_model_tml():
    model_tml = {"model": {
        "columns": [
            {"name": "Sales", "column_id": "FACT::AMOUNT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "State", "column_id": "DIM::STATE",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
        "formulas": [
            {"id": "formula_Avg Sale", "name": "Avg Sale", "expr": "average ( [Sales] )"},
        ],
    }}
    plans = build_rewrite_plans(model_tml)
    assert set(plans) == {"Sales", "Avg Sale"}
    assert plans["Avg Sale"]["class"] == "AVG"
