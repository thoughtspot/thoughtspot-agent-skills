"""Unit tests for ts_cli.dbt_metricflow — MetricFlow metrics → ThoughtSpot formulas.

Fixtures mirror the dbt Fusion / manifest v12 shape observed on 2026-09-08
(nested v2 ``semantic_model:`` spec compiled into top-level ``semantic_models``
and ``metrics`` with ``type_params.metric_aggregation_params``).
"""
from ts_cli.dbt_metricflow import (
    metrics_in_scope,
    semantic_models_in_scope,
    translate_metrics,
)

PATH = "models/staging/barbershop"


def _sm(name, model_uid, measures=()):
    return {
        "unique_id": f"semantic_model.p.{name}", "name": name,
        "depends_on": {"nodes": [model_uid]},
        "measures": list(measures),
    }


def _simple(name, sm, agg, expr, label=None, filter=None, meta=None, description=None,
            fusion_shape=False):
    """dbt Cloud 2026.9.1 shape by default (column at type_params.expr);
    ``fusion_shape=True`` puts it inside metric_aggregation_params like a local
    dbt Fusion parse does."""
    mp = {"semantic_model": sm, "agg": agg, "agg_params": None,
          "agg_time_dimension": None, "non_additive_dimension": None}
    tp = {"metric_aggregation_params": mp, "expr": None}
    if fusion_shape:
        mp["expr"] = expr
    else:
        tp["expr"] = expr
    return {
        "name": name, "type": "simple", "label": label, "description": description,
        "filter": filter, "config": {"enabled": True, "meta": meta or {}},
        "depends_on": {"nodes": [f"semantic_model.p.{sm}"]},
        "type_params": tp,
    }


def _ratio(name, sm, num, den, label=None, num_filter=None, depends_on_sm=False):
    """dbt Cloud shape by default: depends_on lists the *metric* nodes."""
    deps = [f"semantic_model.p.{sm}"] if depends_on_sm else [f"metric.p.{num}", f"metric.p.{den}"]
    return {
        "name": name, "type": "ratio", "label": label, "filter": None,
        "config": {"enabled": True, "meta": {}},
        "depends_on": {"nodes": deps},
        "type_params": {
            "numerator": {"name": num, "filter": num_filter, "alias": None,
                          "offset_window": None, "offset_to_grain": None},
            "denominator": {"name": den, "filter": None, "alias": None,
                            "offset_window": None, "offset_to_grain": None}},
    }


def _derived(name, sm, expr, inputs, label=None):
    return {
        "name": name, "type": "derived", "label": label, "filter": None,
        "config": {"enabled": True, "meta": {}},
        "depends_on": {"nodes": [f"metric.p.{n}" for n, _, _ in inputs]},
        "type_params": {"expr": expr, "metrics": [
            {"name": n, "alias": a, "filter": None, "offset_window": ow, "offset_to_grain": None}
            for n, a, ow in inputs]},
    }


def _manifest(metrics, extra_nodes=None, extra_sms=None):
    nodes = {
        "model.p.transactions": {"resource_type": "model", "name": "transactions",
                                 "original_file_path": f"{PATH}/transactions.sql", "columns": {}},
        "model.p.stg_orders": {"resource_type": "model", "name": "stg_orders",
                               "original_file_path": "models/staging/jaffle/stg_orders.sql",
                               "columns": {}},
    }
    nodes.update(extra_nodes or {})
    sms = {"semantic_model.p.transactions": _sm("transactions", "model.p.transactions"),
           "semantic_model.p.stg_orders": _sm("stg_orders", "model.p.stg_orders")}
    sms.update(extra_sms or {})
    return {"nodes": nodes, "semantic_models": sms,
            "metrics": {f"metric.p.{m['name']}": m for m in metrics}}


class TestScope:
    def test_semantic_models_scoped_to_model_path(self):
        man = _manifest([])
        scope = semantic_models_in_scope(man, PATH)
        assert set(scope) == {"transactions"}
        assert scope["transactions"]["table"] == "TRANSACTIONS"

    def test_metric_from_other_directory_is_ignored(self):
        man = _manifest([_simple("orders", "stg_orders", "count", "ORDER_ID"),
                         _simple("tips", "transactions", "sum", "TIP_AMOUNT")])
        scope = semantic_models_in_scope(man, PATH)
        assert [m["name"] for m in metrics_in_scope(man, scope)] == ["tips"]

    def test_ratio_scoped_through_metric_dependencies_dbt_cloud_shape(self):
        man = _manifest([_simple("tips", "transactions", "sum", "TIP_AMOUNT"),
                         _simple("rev", "transactions", "sum", "SERVICE_PRICE"),
                         _ratio("rate", "transactions", "tips", "rev")])
        scope = semantic_models_in_scope(man, PATH)
        assert {m["name"] for m in metrics_in_scope(man, scope)} == {"tips", "rev", "rate"}

    def test_ratio_over_out_of_scope_metric_is_excluded(self):
        man = _manifest([_simple("orders", "stg_orders", "count", "ORDER_ID"),
                         _simple("tips", "transactions", "sum", "TIP_AMOUNT"),
                         _ratio("mixed", "transactions", "tips", "orders")])
        scope = semantic_models_in_scope(man, PATH)
        assert {m["name"] for m in metrics_in_scope(man, scope)} == {"tips"}

    def test_fusion_shape_depends_on_semantic_model_directly(self):
        man = _manifest([_simple("tips", "transactions", "sum", "TIP_AMOUNT", fusion_shape=True),
                         _simple("rev", "transactions", "sum", "SERVICE_PRICE", fusion_shape=True),
                         _ratio("rate", "transactions", "tips", "rev", depends_on_sm=True)])
        r = translate_metrics(man, PATH)
        assert {f["name"] for f in r["formulas"]} == {"tips", "rev", "rate"}
        assert next(f for f in r["formulas"] if f["name"] == "tips")["expr"] == "sum ( [TRANSACTIONS::TIP_AMOUNT] )"

    def test_disabled_metric_is_ignored(self):
        mt = _simple("tips", "transactions", "sum", "TIP_AMOUNT")
        mt["config"]["enabled"] = False
        man = _manifest([mt])
        assert metrics_in_scope(man, semantic_models_in_scope(man, PATH)) == []


class TestSimple:
    def test_sum_on_bare_column(self):
        man = _manifest([_simple("total_tips", "transactions", "sum", "TIP_AMOUNT",
                                 label="Total Tips", description="Sum of tips.")])
        r = translate_metrics(man, PATH)
        assert r["formulas"] == [{"id": "formula_Total_Tips", "name": "Total Tips",
                                  "expr": "sum ( [TRANSACTIONS::TIP_AMOUNT] )"}]
        col = r["columns"][0]
        assert col["formula_id"] == "formula_Total_Tips"
        assert col["properties"] == {"column_type": "MEASURE", "aggregation": "SUM"}
        assert col["description"] == "Sum of tips."
        assert r["unmapped"] == []

    def test_count_and_count_distinct_and_average(self):
        man = _manifest([_simple("n", "transactions", "count", "TRANSACTION_ID"),
                         _simple("u", "transactions", "count_distinct", "CUSTOMER_ID"),
                         _simple("a", "transactions", "average", "SERVICE_PRICE")])
        exprs = {f["name"]: f["expr"] for f in translate_metrics(man, PATH)["formulas"]}
        assert exprs == {"n": "count ( [TRANSACTIONS::TRANSACTION_ID] )",
                         "u": "unique count ( [TRANSACTIONS::CUSTOMER_ID] )",
                         "a": "average ( [TRANSACTIONS::SERVICE_PRICE] )"}

    def test_label_falls_back_to_name_and_expr_defaults_to_name(self):
        man = _manifest([_simple("TIP_AMOUNT", "transactions", "sum", None)])
        f = translate_metrics(man, PATH)["formulas"][0]
        assert f["name"] == "TIP_AMOUNT"
        assert f["expr"] == "sum ( [TRANSACTIONS::TIP_AMOUNT] )"

    def test_ts_meta_on_metric_config_carries_to_column_props(self):
        man = _manifest([_simple("t", "transactions", "sum", "TIP_AMOUNT", meta={
            "ts_synonym": "gratuity, tips", "ts_format_pattern": "$#,##0.00",
            "ts_index_type": "dont_index", "ts_ai_context": "Tips in USD."})])
        props = translate_metrics(man, PATH)["columns"][0]["properties"]
        assert props["synonyms"] == ["gratuity", "tips"]
        assert props["format_pattern"] == "$#,##0.00"
        assert props["index_type"] == "DONT_INDEX"
        assert props["ai_context"] == "Tips in USD."

    def test_unsupported_shapes_are_reported_not_dropped(self):
        man = _manifest([
            _simple("med", "transactions", "median", "SERVICE_PRICE"),
            _simple("sqlx", "transactions", "sum", "SERVICE_PRICE - DISCOUNT_APPLIED"),
            _simple("filt", "transactions", "sum", "TIP_AMOUNT",
                    filter="{{ Dimension('transaction__PAYMENT_METHOD') }} = 'Cash'"),
        ])
        r = translate_metrics(man, PATH)
        assert r["formulas"] == []
        reasons = {u["metric"]: u["reason"] for u in r["unmapped"]}
        assert "median" in reasons["med"]
        assert "SQL-expression" in reasons["sqlx"]
        assert "filter" in reasons["filt"]

    def test_legacy_measure_reference_shape(self):
        sm = _sm("transactions", "model.p.transactions",
                 measures=[{"name": "tips_m", "agg": "sum", "expr": "TIP_AMOUNT"}])
        mt = {"name": "tips", "type": "simple", "label": "Tips", "filter": None,
              "config": {"enabled": True, "meta": {}},
              "depends_on": {"nodes": ["semantic_model.p.transactions"]},
              "type_params": {"measure": {"name": "tips_m"}, "metric_aggregation_params": None}}
        man = _manifest([mt], extra_sms={"semantic_model.p.transactions": sm})
        assert translate_metrics(man, PATH)["formulas"][0]["expr"] == "sum ( [TRANSACTIONS::TIP_AMOUNT] )"


class TestRatioAndDerived:
    def _base(self):
        return [_simple("total_tips", "transactions", "sum", "TIP_AMOUNT", label="Total Tips"),
                _simple("total_service_revenue", "transactions", "sum", "SERVICE_PRICE",
                        label="Total Service Revenue"),
                _simple("total_discounts", "transactions", "sum", "DISCOUNT_APPLIED",
                        label="Total Discounts Given")]

    def test_ratio_uses_safe_divide_over_formula_id_refs(self):
        man = _manifest(self._base() + [_ratio("tip_rate", "transactions", "total_tips",
                                               "total_service_revenue", label="Tip Rate")])
        f = next(x for x in translate_metrics(man, PATH)["formulas"] if x["name"] == "Tip Rate")
        assert f["expr"] == "safe_divide ( [formula_Total_Tips] , [formula_Total_Service_Revenue] )"

    def test_derived_substitutes_aliases_with_formula_refs(self):
        man = _manifest(self._base() + [_derived(
            "net_revenue", "transactions", "revenue - discounts",
            [("total_service_revenue", "revenue", None), ("total_discounts", "discounts", None)],
            label="Net Revenue")])
        f = next(x for x in translate_metrics(man, PATH)["formulas"] if x["name"] == "Net Revenue")
        assert f["expr"] == "[formula_Total_Service_Revenue] - [formula_Total_Discounts_Given]"

    def test_derived_over_ratio_resolves_in_second_pass(self):
        man = _manifest(self._base() + [
            _derived("tip_pct", "transactions", "tip_rate * 100",
                     [("tip_rate", None, None)], label="Tip Pct"),
            _ratio("tip_rate", "transactions", "total_tips", "total_service_revenue",
                   label="Tip Rate")])
        r = translate_metrics(man, PATH)
        f = next(x for x in r["formulas"] if x["name"] == "Tip Pct")
        assert f["expr"] == "[formula_Tip_Rate] * 100"
        assert r["unmapped"] == []

    def test_offset_and_filter_inputs_are_unmapped(self):
        man = _manifest(self._base() + [
            _derived("wow", "transactions", "revenue - revenue_prev",
                     [("total_service_revenue", "revenue", None),
                      ("total_service_revenue", "revenue_prev", "1 week")]),
            _ratio("cash_tip_rate", "transactions", "total_tips", "total_service_revenue",
                   num_filter="{{ Dimension('transaction__PAYMENT_METHOD') }} = 'Cash'")])
        reasons = {u["metric"]: u["reason"] for u in translate_metrics(man, PATH)["unmapped"]}
        assert "offset" in reasons["wow"]
        assert "filter" in reasons["cash_tip_rate"]

    def test_ratio_over_untranslatable_input_is_reported(self):
        man = _manifest([_simple("med", "transactions", "median", "SERVICE_PRICE"),
                         _simple("n", "transactions", "count", "TRANSACTION_ID"),
                         _ratio("r", "transactions", "med", "n")])
        r = translate_metrics(man, PATH)
        assert {u["metric"] for u in r["unmapped"]} == {"med", "r"}
        assert [f["name"] for f in r["formulas"]] == ["n"]

    def test_cumulative_and_conversion_reported(self):
        man = _manifest(self._base() + [
            {"name": "running", "type": "cumulative", "label": None, "filter": None,
             "config": {"enabled": True, "meta": {}},
             "depends_on": {"nodes": ["semantic_model.p.transactions"]}, "type_params": {}}])
        reasons = {u["metric"]: u["reason"] for u in translate_metrics(man, PATH)["unmapped"]}
        assert "cumulative" in reasons["running"]


class TestSupersedeAndIntegration:
    def test_metric_supersedes_same_named_ts_formula_case_insensitive(self):
        man = _manifest([_simple("total_tips", "transactions", "sum", "TIP_AMOUNT",
                                 label="Total Tips")])
        r = translate_metrics(man, PATH, existing_formula_names={"TOTAL TIPS", "Net Revenue"})
        assert r["superseded"] == ["TOTAL TIPS"]

    def test_build_model_tml_replaces_ts_formula_and_appends_metrics(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man = _manifest([
            _simple("total_tips", "transactions", "sum", "TIP_AMOUNT", label="Total Tips"),
            _simple("med", "transactions", "median", "SERVICE_PRICE")])
        man["nodes"]["model.p.transactions"]["columns"] = {
            "TIP_AMOUNT": {"config": {"meta": {"ts_column_type": "measure",
                                               "ts_aggregation": "sum"}}},
            "Total Tips": {"config": {"meta": {"ts_formula": "sum ( [TRANSACTIONS::TIP_AMOUNT] )",
                                               "ts_column_type": "measure",
                                               "ts_aggregation": "sum",
                                               "ts_index_type": "dont_index"}}},
            "Avg Tip": {"config": {"meta": {"ts_formula": "average ( [TRANSACTIONS::TIP_AMOUNT] )",
                                            "ts_column_type": "measure"}}},
        }
        tml = build_model_tml_from_manifest(man, {}, PATH, "M")
        report = tml.pop("_metrics_report")
        model = tml["model"]
        names = [f["name"] for f in model["formulas"]]
        assert names == ["Avg Tip", "Total Tips"]           # ts_formula dup dropped, metric appended
        assert names.count("Total Tips") == 1
        assert [c["name"] for c in model["columns"] if c.get("formula_id")] == ["Avg Tip", "Total Tips"]
        assert report["superseded"] == ["Total Tips"]
        assert report["unmapped"][0]["metric"] == "med"

    def test_no_metrics_flag_leaves_model_untouched(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man = _manifest([_simple("total_tips", "transactions", "sum", "TIP_AMOUNT")])
        tml = build_model_tml_from_manifest(man, {}, PATH, "M", metrics=False)
        assert "_metrics_report" not in tml
        assert "formulas" not in tml["model"]

    def test_manifest_without_semantic_layer_is_a_noop(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man = {"nodes": {"model.p.t": {"resource_type": "model", "name": "t",
                                        "original_file_path": f"{PATH}/t.sql", "columns": {}}}}
        tml = build_model_tml_from_manifest(man, {}, PATH, "M")
        assert "_metrics_report" not in tml


class TestEntityJoins:
    def _scope(self, fact_entities, dim_entities):
        man = _manifest([])
        man["nodes"]["model.p.customers"] = {"resource_type": "model", "name": "customers",
                                             "original_file_path": f"{PATH}/customers.sql", "columns": {}}
        man["semantic_models"]["semantic_model.p.transactions"]["entities"] = fact_entities
        man["semantic_models"]["semantic_model.p.customers"] = {
            "unique_id": "semantic_model.p.customers", "name": "customers",
            "depends_on": {"nodes": ["model.p.customers"]}, "entities": dim_entities}
        return man, semantic_models_in_scope(man, PATH)

    def test_foreign_to_primary_becomes_left_outer_many_to_one(self):
        from ts_cli.dbt_metricflow import entity_joins
        man, scope = self._scope(
            [{"name": "transaction", "type": "primary", "expr": "TRANSACTION_ID"},
             {"name": "customer", "type": "foreign", "expr": "CUSTOMER_ID"}],
            [{"name": "customer", "type": "primary", "expr": "CUSTOMER_ID"}])
        [ej] = entity_joins(scope)
        assert (ej["source"], ej["target"], ej["entity"]) == ("TRANSACTIONS", "CUSTOMERS", "customer")
        assert ej["join"] == {"name": "transactions_to_customers", "with": "CUSTOMERS",
                              "on": "[TRANSACTIONS::CUSTOMER_ID] = [CUSTOMERS::CUSTOMER_ID]",
                              "type": "LEFT_OUTER", "cardinality": "MANY_TO_ONE"}

    def test_entity_name_used_when_expr_absent_and_sql_expr_skipped(self):
        from ts_cli.dbt_metricflow import entity_joins
        _, scope = self._scope(
            [{"name": "customer", "type": "foreign", "expr": None},
             {"name": "region", "type": "foreign", "expr": "upper(REGION_CODE)"}],
            [{"name": "customer", "type": "primary", "expr": None},
             {"name": "region", "type": "primary", "expr": "REGION_CODE"}])
        out = entity_joins(scope)
        assert [ej["entity"] for ej in out] == ["customer"]
        assert out[0]["join"]["on"] == "[TRANSACTIONS::customer] = [CUSTOMERS::customer]"

    def test_ambiguous_primary_is_skipped(self):
        from ts_cli.dbt_metricflow import entity_joins
        man, scope = self._scope(
            [{"name": "customer", "type": "foreign", "expr": "CUSTOMER_ID"},
             {"name": "customer", "type": "primary", "expr": "CUSTOMER_ID"}],
            [{"name": "customer", "type": "primary", "expr": "CUSTOMER_ID"}])
        assert entity_joins(scope) == []

    def test_build_model_uses_entity_join_only_when_no_ts_join_test(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man, _ = self._scope(
            [{"name": "customer", "type": "foreign", "expr": "CUSTOMER_ID"}],
            [{"name": "customer", "type": "primary", "expr": "CUSTOMER_ID"}])
        tml = build_model_tml_from_manifest(man, {}, PATH, "M")
        rep = tml.pop("_metrics_report")
        fact = next(t for t in tml["model"]["model_tables"] if t["name"] == "TRANSACTIONS")
        assert fact["joins"][0]["with"] == "CUSTOMERS" and fact["joins"][0]["type"] == "LEFT_OUTER"
        assert [ej["entity"] for ej in rep["entity_joins"]] == ["customer"]
        # an explicit ts_join_* relationships test on the same pair wins and no duplicate is added
        man["nodes"]["test.p.rel"] = {
            "resource_type": "test", "original_file_path": f"{PATH}/schema.yml",
            "test_metadata": {"name": "relationships", "kwargs": {
                "model": "{{ get_where_subquery(ref('transactions')) }}", "to": "ref('customers')",
                "column_name": "CUSTOMER_ID", "field": "CUSTOMER_ID"}},
            "config": {"meta": {"ts_join_type": "inner", "ts_join_name": "txn_cust"}}}
        tml = build_model_tml_from_manifest(man, {}, PATH, "M")
        fact = next(t for t in tml["model"]["model_tables"] if t["name"] == "TRANSACTIONS")
        assert [(j["name"], j["type"]) for j in fact["joins"]] == [("txn_cust", "INNER")]
        assert "_metrics_report" not in tml

    def test_no_metrics_flag_skips_entity_joins(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest
        man, _ = self._scope(
            [{"name": "customer", "type": "foreign", "expr": "CUSTOMER_ID"}],
            [{"name": "customer", "type": "primary", "expr": "CUSTOMER_ID"}])
        tml = build_model_tml_from_manifest(man, {}, PATH, "M", metrics=False)
        assert all("joins" not in t for t in tml["model"]["model_tables"])


class TestInferredColumnVsMetricNameCollision:
    def _man(self):
        man = _manifest([_simple("transaction_total", "transactions", "sum", "TRANSACTION_TOTAL",
                                 label="Transaction Total")])
        man["nodes"]["model.p.transactions"]["unique_id"] = "model.p.transactions"
        cat = {"nodes": {"model.p.transactions": {"columns": {
            "TRANSACTION_TOTAL": {"type": "NUMBER(38,2)", "name": "TRANSACTION_TOTAL"},
            "PAYMENT_METHOD": {"type": "TEXT", "name": "PAYMENT_METHOD"}}}}}
        return man, cat

    def test_untagged_column_is_renamed_with_table_prefix(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest, find_display_name_collisions
        man, cat = self._man()
        tml = build_model_tml_from_manifest(man, cat, PATH, "M", pretty_names=True)
        renames = tml.pop("_inferred_renames")
        assert renames == [{"column_id": "TRANSACTIONS::TRANSACTION_TOTAL",
                            "from": "Transaction Total", "to": "Transactions Transaction Total"}]
        names = [c["name"] for c in tml["model"]["columns"]]
        assert "Transactions Transaction Total" in names and names.count("Transaction Total") == 1
        tml.pop("_inferred_columns"); tml.pop("_metrics_report")
        assert find_display_name_collisions(tml) == []

    def test_declared_column_collision_is_left_for_fail_fast(self):
        from ts_cli.dbt_build_export import build_model_tml_from_manifest, find_display_name_collisions
        man, cat = self._man()
        man["nodes"]["model.p.transactions"]["columns"] = {
            "TRANSACTION_TOTAL": {"config": {"meta": {"ts_column_type": "measure", "ts_aggregation": "sum"}}}}
        tml = build_model_tml_from_manifest(man, cat, PATH, "M", pretty_names=True)
        assert "_inferred_renames" not in tml
        tml.pop("_inferred_columns", None); tml.pop("_metrics_report")
        assert [n for n, _ in find_display_name_collisions(tml)] == ["transaction total"]
