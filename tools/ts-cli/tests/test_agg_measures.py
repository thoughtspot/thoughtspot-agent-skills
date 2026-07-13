from ts_cli.aggregate.measures import classify_measure, build_rewrite_plans


def test_sum_column_is_directly_additive():
    plan = classify_measure("Sales", aggregation="SUM")
    assert plan["class"] == "SUM"
    assert plan["decomposable"] is True
    assert plan["components"] == [
        {"alias": "sales_sum", "source_column": "Sales", "func": "SUM", "reagg": "SUM"}
    ]
    # Live-verified (aggregate-aware cluster, 2026-07-13): query routing to an
    # aggregate fires ONLY for FORMULA measures, never a plain measure column
    # (default-aggregation switching on columns isn't coded). So even a direct
    # SUM must surface as a formula over its hidden stored component, not a
    # plain column — see skill Open Item #0.
    assert plan["model_expr"] == "sum ( [sales_sum] )"


def test_min_column_gets_formula_model_expr():
    plan = classify_measure("Low Price", aggregation="MIN")
    assert plan["class"] == "MIN"
    assert plan["decomposable"] is True
    assert plan["components"] == [
        {"alias": "low_price_min", "source_column": "Low Price", "func": "MIN", "reagg": "MIN"}
    ]
    assert plan["model_expr"] == "min ( [low_price_min] )"


def test_max_column_gets_formula_model_expr():
    plan = classify_measure("Peak Price", aggregation="MAX")
    assert plan["class"] == "MAX"
    assert plan["model_expr"] == "max ( [peak_price_max] )"


def test_min_expr_gets_formula_model_expr():
    plan = classify_measure("Low Price", expr="min ( [Price] )")
    assert plan["class"] == "MIN"
    assert plan["components"][0]["alias"] == "low_price_min"
    assert plan["model_expr"] == "min ( [low_price_min] )"


def test_max_expr_gets_formula_model_expr():
    plan = classify_measure("Peak Price", expr="max ( [Price] )")
    assert plan["class"] == "MAX"
    assert plan["components"][0]["alias"] == "peak_price_max"
    assert plan["model_expr"] == "max ( [peak_price_max] )"


def test_every_decomposable_plan_has_model_expr():
    # After the routing fix, EVERY decomposable class (SUM/MIN/MAX/COUNT/AVG/
    # RATIO) has a non-None model_expr — there is no more "plain column, no
    # formula needed" case.
    plans = [
        classify_measure("Sales", aggregation="SUM"),
        classify_measure("Low Price", aggregation="MIN"),
        classify_measure("Peak Price", aggregation="MAX"),
        classify_measure("Orders", aggregation="COUNT"),
        classify_measure("Avg Sale", expr="average ( [Sales] )"),
        classify_measure("Margin Pct", expr="sum ( [Profit] ) / sum ( [Revenue] )"),
    ]
    for plan in plans:
        assert plan["decomposable"] is True
        assert plan["model_expr"] is not None


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


def test_formula_backed_measure_column_is_not_double_planned():
    # A MEASURE column carrying a formula_id is the formula's surface, not a
    # physical warehouse column — it must not yield a spurious raw-SUM plan.
    model_tml = {"model": {
        "columns": [
            {"name": "Avg Sale Col", "column_id": "FACT::X",
             "formula_id": "formula_Avg Sale",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            {"name": "Sales", "column_id": "FACT::AMOUNT",
             "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        ],
        "formulas": [
            {"id": "formula_Avg Sale", "name": "Avg Sale", "expr": "average ( [Sales] )"},
        ],
    }}
    plans = build_rewrite_plans(model_tml)
    assert set(plans) == {"Avg Sale", "Sales"}  # no "Avg Sale Col" plan
    assert plans["Avg Sale"]["class"] == "AVG"
    # No plan may claim the formula-backed column as a physical source column.
    sources = [c["source_column"] for p in plans.values() for c in p["components"]]
    assert "Avg Sale Col" not in sources


def test_colliding_slugs_get_unique_aliases():
    # "Avg Sale" and "Avg-Sale" both slug to avg_sale; non-ASCII names slug to
    # the "measure" fallback. All aliases across plans must be unique, and any
    # renamed alias must be rewritten inside its plan's model_expr too.
    model_tml = {"model": {
        "formulas": [
            {"id": "f1", "name": "Avg Sale", "expr": "average ( [Sales] )"},
            {"id": "f2", "name": "Avg-Sale", "expr": "average ( [Sales USD] )"},
            {"id": "f3", "name": "売上", "expr": "sum ( [Amount JP] )"},
            {"id": "f4", "name": "収益", "expr": "sum ( [Amount JP 2] )"},
        ],
    }}
    plans = build_rewrite_plans(model_tml)
    all_aliases = [c["alias"] for p in plans.values() for c in p["components"]]
    assert len(all_aliases) == len(set(all_aliases))
    # Deterministic: first occurrence keeps the base alias, later ones get _2, _3...
    assert [c["alias"] for c in plans["Avg Sale"]["components"]] == [
        "avg_sale_sum", "avg_sale_cnt"]
    assert [c["alias"] for c in plans["Avg-Sale"]["components"]] == [
        "avg_sale_sum_2", "avg_sale_cnt_2"]
    assert plans["Avg-Sale"]["model_expr"] == (
        "sum ( [avg_sale_sum_2] ) / sum ( [avg_sale_cnt_2] )")
    # Empty slugs fall back to "measure" instead of colliding on "_sum".
    assert plans["売上"]["components"][0]["alias"] == "measure_sum"
    assert plans["収益"]["components"][0]["alias"] == "measure_sum_2"


def test_non_ascii_name_gets_fallback_slug():
    plan = classify_measure("売上", expr="sum ( [Amount] )")
    assert plan["components"][0]["alias"] == "measure_sum"


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
