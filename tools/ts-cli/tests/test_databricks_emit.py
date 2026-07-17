import pytest
from ts_cli.databricks.mv_emit import (
    build_column_index, make_col_resolver, classify_column,
    emit_dimension, emit_measure, emit_filter,
    emit_lod_dimension, emit_window_measure, synthesize_period_dim,
    _moving_range,
    detect_fact_tables, make_ref_resolver, build_metric_view,
)
from ts_cli.databricks.mv_emit_expr import parse_formula, UntranslatableError
from ts_cli.databricks.mv_emit_sql import emit_sql, is_aggregate_present

MODEL = {"model": {"name": "M",
    "model_tables": [{"name": "FACT"}],
    "columns": [
        {"name": "Amount", "column_id": "FACT::AMOUNT", "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}],
    "formulas": []}}
TABLES = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
    "columns": [{"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}}]

class TestColumnIndex:
    def test_physical_column_dot_path(self):
        idx = build_column_index(MODEL["model"], TABLES)
        assert idx["FACT::AMOUNT"]["dbx_type"] == "double"
        r = make_col_resolver(idx, source_table="FACT")
        assert emit_sql(parse_formula("sum ( [FACT::AMOUNT] )"), r) == "SUM(source.AMOUNT)"

    def test_unknown_column_raises(self):
        idx = build_column_index(MODEL["model"], TABLES)
        r = make_col_resolver(idx, source_table="FACT")
        with pytest.raises(UntranslatableError):
            emit_sql(parse_formula("sum ( [FACT::MISSING] )"), r)


class TestJoins:
    def test_single_join(self):
        model = {"name": "M",
            "model_tables": [
                {"name": "FACT", "joins": [
                    {"with": "DIM", "on": "[FACT::DIM_ID] = [DIM::ID]", "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
                {"name": "DIM"}],
            "columns": [], "formulas": []}
        tables = [
            {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact", "columns": []}},
            {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim", "columns": []}}]
        from ts_cli.databricks.mv_emit import build_joins
        joins, dot = build_joins(model, tables, source_table="FACT")
        assert joins == [{"name": "dim", "source": "c.s.dim",
                          "on": "source.DIM_ID = dim.ID",
                          "rely": {"at_most_one_match": True},
                          "cardinality": "many_to_one"}]
        assert dot == {"FACT": "source", "DIM": "dim"}

    def test_two_level_nested_join(self):
        model = {"name": "M",
            "model_tables": [
                {"name": "FACT", "joins": [
                    {"with": "DIM", "on": "[FACT::DIM_ID] = [DIM::ID]", "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
                {"name": "DIM", "joins": [
                    {"with": "SUBDIM", "on": "[DIM::SUBDIM_ID] = [SUBDIM::ID]", "type": "INNER"}]},
                {"name": "SUBDIM"}],
            "columns": [], "formulas": []}
        tables = [
            {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact", "columns": []}},
            {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim", "columns": []}},
            {"table": {"name": "SUBDIM", "db": "c", "schema": "s", "db_table": "subdim", "columns": []}}]
        from ts_cli.databricks.mv_emit import build_joins
        joins, dot = build_joins(model, tables, source_table="FACT")
        assert dot == {"FACT": "source", "DIM": "dim", "SUBDIM": "dim.subdim"}
        # SUBDIM is nested UNDER the "dim" join node's own "joins" list (per the
        # Metric View spec — nested joins are a child list, not flat siblings),
        # and its "on" references the parent's bare alias ("dim"), not the full
        # dot path ("dim.subdim").
        assert joins == [
            {"name": "dim", "source": "c.s.dim",
             "on": "source.DIM_ID = dim.ID",
             "rely": {"at_most_one_match": True},
             "cardinality": "many_to_one",
             "joins": [
                 {"name": "subdim", "source": "c.s.subdim",
                  "on": "dim.SUBDIM_ID = subdim.ID",
                  "rely": {"at_most_one_match": True}}]}]

    def test_referencing_join_missing_raises(self):
        model = {"name": "M",
            "model_tables": [
                {"name": "FACT", "joins": [
                    {"with": "DIM", "referencing_join": "fk_dim", "type": "INNER"}]},
                {"name": "DIM"}],
            "columns": [], "formulas": []}
        tables = [
            {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact", "columns": []}},
            {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim", "columns": []}}]
        from ts_cli.databricks.mv_emit import build_joins
        with pytest.raises(Exception):
            build_joins(model, tables, source_table="FACT")

    def test_referencing_join_resolved_from_source_table(self):
        # Scenario A happy path: the model's join only carries `with` +
        # `referencing_join` (no inline `on`). Per the schema
        # (thoughtspot-model-tml.md "Join Scenarios" Scenario A;
        # thoughtspot-table-tml.md `joins_with[]` field reference), the named
        # join is defined on the SOURCE (FK) table's own Table TML
        # `joins_with[]` — not on the target table's TML.
        model = {"name": "M",
            "model_tables": [
                {"name": "FACT", "joins": [
                    {"with": "DIM", "referencing_join": "FACT_to_DIM", "cardinality": "MANY_TO_ONE"}]},
                {"name": "DIM"}],
            "columns": [], "formulas": []}
        tables = [
            {"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact", "columns": [],
                "joins_with": [
                    {"name": "FACT_to_DIM", "destination": {"name": "DIM"},
                     "on": "[FACT::DIM_ID] = [DIM::ID]", "type": "INNER", "cardinality": "MANY_TO_ONE"}]}},
            {"table": {"name": "DIM", "db": "c", "schema": "s", "db_table": "dim", "columns": []}}]
        from ts_cli.databricks.mv_emit import build_joins
        joins, dot = build_joins(model, tables, source_table="FACT")
        assert joins == [{"name": "dim", "source": "c.s.dim",
                          "on": "source.DIM_ID = dim.ID",
                          "rely": {"at_most_one_match": True},
                          "cardinality": "many_to_one"}]
        assert dot == {"FACT": "source", "DIM": "dim"}


class TestClassifyColumn:
    def test_physical_measure(self):
        col = {"name": "Amount", "column_id": "FACT::AMOUNT",
               "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}
        result = classify_column(col, MODEL["model"])
        assert result["role"] == "measure"
        assert isinstance(result["reason"], str) and result["reason"]

    def test_physical_dimension(self):
        col = {"name": "Region", "column_id": "FACT::REGION",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, MODEL["model"])
        assert result["role"] == "dimension"

    def test_boolean_filter_formula(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_filter", "name": "MV Filter", "expr": "[FACT::STATUS] = 'Active'"}]}
        col = {"name": "MV Filter", "formula_id": "formula_filter",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, model)
        assert result["role"] == "filter"

    def test_group_aggregate_routes_to_window(self):
        # LOD formula -> window (dimension window function, emitted in Task 9).
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_lod", "name": "Category Quantity",
                 "expr": "group_aggregate ( sum ( [FACT::QTY] ) , { [FACT::CATEGORY] } , query_filters ( ) )"}]}
        col = {"name": "Category Quantity", "formula_id": "formula_lod",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, model)
        assert result["role"] == "window"

    def test_moving_sum_routes_to_window(self):
        # Window measure -> window (rolling/cumulative/semi-additive, Task 9).
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_ms", "name": "Trailing 7 Day Amount",
                 "expr": "moving_sum ( [FACT::AMOUNT] , 7 , -1 , [FACT::ORDER_DATE] )"}]}
        col = {"name": "Trailing 7 Day Amount", "formula_id": "formula_ms",
               "properties": {"column_type": "MEASURE"}}
        result = classify_column(col, model)
        assert result["role"] == "window"

    def test_period_offset_sum_if_routes_to_window(self):
        # sum_if(diff_months(...) = N, [m]) -> window (period-offset, Task 9),
        # even though its top node is a plain *_if conditional aggregate.
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_pf", "name": "Current Month Amount",
                 "expr": "sum_if ( diff_months ( [FACT::ORDER_DATE] , today ( ) ) = 0 , [FACT::AMOUNT] )"}]}
        col = {"name": "Current Month Amount", "formula_id": "formula_pf",
               "properties": {"column_type": "MEASURE"}}
        result = classify_column(col, model)
        assert result["role"] == "window"

    def test_plain_sum_if_without_period_offset_is_measure(self):
        # A *_if formula whose condition does NOT contain diff_months/quarters/years
        # is a plain conditional-aggregate measure (Task 8 territory), not window.
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_cond", "name": "Active Amount",
                 "expr": "sum_if ( [FACT::STATUS] = 'Active' , [FACT::AMOUNT] )"}]}
        col = {"name": "Active Amount", "formula_id": "formula_cond",
               "properties": {"column_type": "MEASURE"}}
        result = classify_column(col, model)
        assert result["role"] == "measure"

    @pytest.mark.parametrize("fn", ["group_max", "group_min", "group_unique_count"])
    def test_extended_group_fns_route_to_window(self, fn):
        # Task 9 review: group_max/group_min/group_unique_count join the
        # original 4 group_* fns as LOD -> window routes.
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_lod", "name": "X",
                 "expr": f"{fn} ( [FACT::QTY] , [FACT::CATEGORY] )"}]}
        col = {"name": "X", "formula_id": "formula_lod",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, model)
        assert result["role"] == "window"

    def test_formula_backed_unknown_column_type_is_unknown_role(self):
        # Review fix wave FIX 3: a formula-backed column whose OWN column_type
        # is UNKNOWN previously fell through to the final `dimension` branch
        # with a misleading "formula-backed ATTRIBUTE ..." reason (column_type
        # is UNKNOWN, not ATTRIBUTE) -- must instead route to role=="unknown"
        # (omit+skip), matching the physical-column UNKNOWN behavior.
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_mystery", "name": "Mystery Formula",
                 "expr": "concat ( [FACT::A] , [FACT::B] )"}]}
        col = {"name": "Mystery Formula", "formula_id": "formula_mystery",
               "properties": {"column_type": "UNKNOWN"}}
        result = classify_column(col, model)
        assert result["role"] == "unknown"
        assert "UNKNOWN" in result["reason"]
        assert "ATTRIBUTE" not in result["reason"]

    def test_non_boolean_attribute_formula_is_dimension(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_concat", "name": "Full Name",
                 "expr": "concat ( [FACT::FIRST] , [FACT::LAST] )"}]}
        col = {"name": "Full Name", "formula_id": "formula_concat",
               "properties": {"column_type": "ATTRIBUTE"}}
        result = classify_column(col, model)
        assert result["role"] == "dimension"


class TestEmitMeasure:
    def test_physical_measure(self):
        idx = build_column_index(MODEL["model"], TABLES)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = MODEL["model"]["columns"][0]
        assert emit_measure(col, resolver) == {
            "name": "amount", "expr": "SUM(source.AMOUNT)", "display_name": "Amount"}

    def test_physical_measure_count_distinct(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Customer Count", "column_id": "FACT::ID",
                "properties": {"column_type": "MEASURE", "aggregation": "COUNT_DISTINCT"}}],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "ID", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = model["columns"][0]
        result = emit_measure(col, resolver)
        assert result["expr"] == "COUNT(DISTINCT source.ID)"

    def test_formula_measure_with_cross_ref_and_resolver(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_contrib", "name": "Contribution", "expr": "[Quantity]"}]}
        col = {"name": "Contribution", "formula_id": "formula_contrib",
               "properties": {"column_type": "MEASURE"}}
        idx = build_column_index(model, [])
        resolver = make_col_resolver(idx, source_table="FACT")

        def ref_resolver(node):
            if node["name"] == "Quantity":
                return "MEASURE(quantity)"
            raise UntranslatableError(f"unexpected ref {node['name']!r}")

        result = emit_measure(col, resolver, ref_resolver, model=model)
        assert result == {
            "name": "contribution", "expr": "MEASURE(quantity)", "display_name": "Contribution"}

    def test_formula_measure_without_ref_resolver_raises(self):
        # No ref_resolver provided -> the default sink raises, deferring
        # ref-bearing formulas to Task 10's role-aware resolver.
        model = {"name": "M", "model_tables": [{"name": "FACT"}], "columns": [],
            "formulas": [{"id": "formula_x", "name": "X", "expr": "[Quantity]"}]}
        col = {"name": "X", "formula_id": "formula_x", "properties": {"column_type": "MEASURE"}}
        idx = build_column_index(model, [])
        resolver = make_col_resolver(idx, source_table="FACT")
        with pytest.raises(UntranslatableError):
            emit_measure(col, resolver, model=model)

    def test_formula_measure_without_refs_still_resolves(self):
        # A formula with no [ref] at all still passes through resolve_refs
        # unchanged (exercises the no-op path, not just the substitution path).
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Amount", "column_id": "FACT::AMOUNT",
                "properties": {"column_type": "MEASURE"}}],
            "formulas": [{"id": "formula_sum", "name": "Total Amount",
                "expr": "sum ( [FACT::AMOUNT] )"}]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = {"name": "Total Amount", "formula_id": "formula_sum",
               "properties": {"column_type": "MEASURE"}}
        result = emit_measure(col, resolver, model=model)
        assert result["expr"] == "SUM(source.AMOUNT)"


class TestEmitMeasureRawMeasureWrap:
    """Task 18 Finding 1 fix: a formula-backed MEASURE whose translated SQL
    has no aggregate anywhere (raw physical-column refs, not cross-measure
    MEASURE()/ANY_VALUE() refs) must be wrapped in the column's own declared
    aggregation -- matching ThoughtSpot's own raw_measure + SUM-at-query-time
    semantics (live-verified 2026-07-18) and avoiding Databricks'
    MISSING_AGGREGATION CREATE VIEW failure.
    """

    @staticmethod
    def _amount_qty_model(formula_expr: str, aggregation: str = "SUM"):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Amount", "column_id": "FACT::amount",
                 "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
                {"name": "Qty", "column_id": "FACT::qty",
                 "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}],
            "formulas": [{"id": "formula_x", "name": "X", "expr": formula_expr}]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [
                {"name": "amount", "db_column_properties": {"data_type": "DOUBLE"}},
                {"name": "qty", "db_column_properties": {"data_type": "DOUBLE"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = {"name": "X", "formula_id": "formula_x",
               "properties": {"column_type": "MEASURE", "aggregation": aggregation}}
        return model, resolver, col

    def test_safe_divide_of_two_raw_physical_measures_gets_wrapped(self):
        # safe_divide([Amount], [Qty]) referenced RAW ([TABLE::col], not a
        # [Name] ref to another measure) -- no aggregate anywhere in the
        # translated SQL, so it must be wrapped in the column's own SUM
        # aggregation.
        model, resolver, col = self._amount_qty_model(
            "safe_divide ( [FACT::amount] , [FACT::qty] )")
        result = emit_measure(col, resolver, model=model)
        assert result["expr"] == "SUM(COALESCE(source.amount / NULLIF(source.qty, 0), 0))"

    def test_arithmetic_over_raw_physical_measure_gets_wrapped(self):
        # [Amount] * 1.1 -- arithmetic over a single raw physical measure,
        # still no aggregate present, still must be wrapped.
        model, resolver, col = self._amount_qty_model("[FACT::amount] * 1.1")
        result = emit_measure(col, resolver, model=model)
        assert result["expr"] == "SUM(source.amount * 1.1)"

    def test_wraps_in_the_columns_declared_aggregation_not_always_sum(self):
        # aggregation: AVG on the formula column -- must wrap in AVG(...),
        # not blindly default to SUM.
        model, resolver, col = self._amount_qty_model(
            "[FACT::amount] * 1.1", aggregation="AVG")
        result = emit_measure(col, resolver, model=model)
        assert result["expr"] == "AVG(source.amount * 1.1)"

    def test_cross_measure_ratio_is_not_wrapped(self):
        # safe_divide([Quantity], [Category Quantity]) -- both operands are
        # [Name] refs resolved via ref_resolver into MEASURE()/ANY_VALUE();
        # the translated SQL already contains an aggregate (via the resolved
        # refs), so it must be left exactly as emitted -- NOT wrapped in an
        # outer SUM (mirrors the Dunder golden test's Category Contribution
        # Ratio assertion in test_databricks_to_golden.py).
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [], "formulas": [
                {"id": "formula_ratio", "name": "Category Contribution Ratio",
                 "expr": "safe_divide ( [Quantity] , [Category Quantity] )"}]}
        col = {"name": "Category Contribution Ratio", "formula_id": "formula_ratio",
               "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}
        idx = build_column_index(model, [])
        resolver = make_col_resolver(idx, source_table="FACT")

        def ref_resolver(node):
            if node["name"] == "Quantity":
                return "MEASURE(quantity)"
            if node["name"] == "Category Quantity":
                return "ANY_VALUE(category_quantity)"
            raise UntranslatableError(f"unexpected ref {node['name']!r}")

        result = emit_measure(col, resolver, ref_resolver, model=model)
        assert result["expr"] == (
            "COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)")

    def test_already_aggregated_formula_measure_not_double_wrapped(self):
        # sum([Amount]) already contains SUM(...) -- must stay exactly as
        # emitted, never become SUM(SUM(...)).
        model, resolver, col = self._amount_qty_model("sum ( [FACT::amount] )")
        result = emit_measure(col, resolver, model=model)
        assert result["expr"] == "SUM(source.amount)"


class TestIsAggregatePresent:
    """Unit coverage for the presence-based aggregate detector
    mv_emit.emit_measure's formula branch relies on (via
    mv_emit_sql.wrap_measure_if_needed) -- presence ANYWHERE in the SQL
    string, not "outermost AST node is a call".
    """

    @pytest.mark.parametrize("sql", [
        "SUM(source.amount)",
        "COUNT(DISTINCT source.id)",
        "COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)",
        "SUM(source.amount) OVER (PARTITION BY source.category)",
        "AVG(x) OVER(PARTITION BY y)",
    ])
    def test_true_when_an_aggregate_or_window_is_present(self, sql):
        assert is_aggregate_present(sql) is True

    def test_false_for_a_bare_arithmetic_expression(self):
        assert is_aggregate_present(
            "COALESCE(source.amount / NULLIF(source.qty, 0), 0)") is False


class TestEmitDimension:
    def test_physical_dimension(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Region", "column_id": "FACT::REGION",
                "properties": {"column_type": "ATTRIBUTE"}}],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = model["columns"][0]
        assert emit_dimension(col, resolver) == {
            "name": "region", "expr": "source.REGION", "display_name": "Region"}


class TestEmitFilter:
    def test_boolean_filter_formula(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Status", "column_id": "FACT::STATUS",
                "properties": {"column_type": "ATTRIBUTE"}}],
            "formulas": [{"id": "formula_filter", "name": "MV Filter",
                "expr": "[FACT::STATUS] = 'Active'"}]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "STATUS", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = {"name": "MV Filter", "formula_id": "formula_filter",
               "properties": {"column_type": "ATTRIBUTE"}}
        # NOTE: the mapping doc's illustrative row (ts-to-databricks-rules.md
        # "Filter Generation") shows the single-source, no-prefix form
        # `status = 'Active'`. This module resolves every column through the
        # source./alias. dot-path scheme established in Tasks 6/7 (see
        # "SUM(source.AMOUNT)" and "source.REGION" above) -- there is no
        # no-prefix resolution mode anywhere in mv_emit.py, so the correct,
        # consistent output here carries the same "source." prefix.
        assert emit_filter(col, resolver, model=model) == "source.STATUS = 'Active'"


class TestColumnMetadata:
    def test_comment_and_synonyms(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Region", "column_id": "FACT::REGION",
                "properties": {"column_type": "ATTRIBUTE",
                    "description": "Sales region", "synonyms": ["area", "territory"]}}],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = model["columns"][0]
        result = emit_dimension(col, resolver)
        assert result == {
            "name": "region", "expr": "source.REGION", "display_name": "Region",
            "comment": "Sales region", "synonyms": ["area", "territory"]}
        assert list(result.keys()) == ["name", "expr", "display_name", "comment", "synonyms"]

    def test_currency_format(self):
        model = {"name": "M", "model_tables": [{"name": "FACT"}],
            "columns": [{"name": "Revenue", "column_id": "FACT::REVENUE",
                "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                    "currency_type": {"iso_code": "USD"}}}],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "REVENUE", "db_column_properties": {"data_type": "DOUBLE"}}]}}]
        idx = build_column_index(model, tables)
        resolver = make_col_resolver(idx, source_table="FACT")
        col = model["columns"][0]
        result = emit_measure(col, resolver)
        assert result["format"] == {"type": "currency", "currency_code": "USD"}
        assert list(result.keys()) == ["name", "expr", "display_name", "format"]


# --- Task 9: window classification (LOD, moving/cumulative, semi-additive, ---
# period-offset). Golden contracts are worked-example formulas 3/5/6/7 from
# agents/shared/worked-examples/databricks/ts-to-databricks.md.

class TestEmitLodDimension:
    def test_worked_example_formula_3_category_quantity(self):
        # group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) ,
        #   { [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) )
        # -> SUM(source.QUANTITY) OVER (PARTITION BY products.category.CATEGORY_NAME)
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "formula_cat_qty", "name": "Category Quantity",
             "expr": "group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , "
                     "{ [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) )"}]}
        col = {"name": "Category Quantity", "formula_id": "formula_cat_qty",
               "properties": {"column_type": "MEASURE"}}

        def col_resolver(node):
            if node["table"] == "DM_ORDER_DETAIL":
                return f"source.{node['column']}"
            if node["table"] == "DM_CATEGORY":
                return f"products.category.{node['column']}"
            raise UntranslatableError(f"unexpected table {node['table']!r}")

        result = emit_lod_dimension(col, col_resolver, model=model)
        assert result["expr"] == "SUM(source.QUANTITY) OVER (PARTITION BY products.category.CATEGORY_NAME)"
        assert result["name"] == "category_quantity"
        assert result["display_name"] == "Category Quantity"

    def test_group_sum_two_arg_form(self):
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "f", "name": "Region Total", "expr": "group_sum ( [FACT::AMOUNT] , [FACT::REGION] )"}]}
        col = {"name": "Region Total", "formula_id": "f", "properties": {"column_type": "ATTRIBUTE"}}
        result = emit_lod_dimension(col, lambda n: f"source.{n['column']}", model=model)
        assert result["expr"] == "SUM(source.AMOUNT) OVER (PARTITION BY source.REGION)"

    def test_multiple_partition_cols_comma_joined(self):
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "f", "name": "Multi Partition",
             "expr": "group_aggregate ( sum ( [FACT::AMOUNT] ) , "
                     "{ [FACT::A] , [FACT::B] } , query_filters ( ) )"}]}
        col = {"name": "Multi Partition", "formula_id": "f", "properties": {"column_type": "ATTRIBUTE"}}
        result = emit_lod_dimension(col, lambda n: f"source.{n['column']}", model=model)
        assert result["expr"] == "SUM(source.AMOUNT) OVER (PARTITION BY source.A, source.B)"

    def test_group_max(self):
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "f", "name": "Max Amount", "expr": "group_max ( [FACT::AMOUNT] , [FACT::CATEGORY] )"}]}
        col = {"name": "Max Amount", "formula_id": "f", "properties": {"column_type": "ATTRIBUTE"}}
        result = emit_lod_dimension(col, lambda n: f"source.{n['column']}", model=model)
        assert result["expr"] == "MAX(source.AMOUNT) OVER (PARTITION BY source.CATEGORY)"

    def test_group_unique_count(self):
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "f", "name": "Distinct Customers",
             "expr": "group_unique_count ( [FACT::CUSTOMER_ID] , [FACT::CATEGORY] )"}]}
        col = {"name": "Distinct Customers", "formula_id": "f", "properties": {"column_type": "ATTRIBUTE"}}
        result = emit_lod_dimension(col, lambda n: f"source.{n['column']}", model=model)
        assert result["expr"] == "COUNT(DISTINCT source.CUSTOMER_ID) OVER (PARTITION BY source.CATEGORY)"

    def test_group_aggregate_with_query_groups_raises(self):
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "f", "name": "X",
             "expr": "group_aggregate ( sum ( [FACT::AMOUNT] ) , { [FACT::CATEGORY] } , query_groups ( ) )"}]}
        col = {"name": "X", "formula_id": "f", "properties": {"column_type": "ATTRIBUTE"}}
        with pytest.raises(UntranslatableError):
            emit_lod_dimension(col, lambda n: f"source.{n['column']}", model=model)


class TestMovingRangeUnit:
    """Unit-level coverage of `_moving_range` itself -- the four canonical
    shapes it must keep mapping exactly, plus the review-finding reproduction:
    pairs that match an anchor condition (end==-1, end==0, start==-1,
    start==0) but derive a non-positive day count N, which must raise rather
    than emit a garbage 'trailing/leading -N day' range string."""

    def test_trailing_exclusive_canonical(self):
        assert _moving_range(7, -1) == "trailing 7 day"

    def test_trailing_inclusive_canonical(self):
        assert _moving_range(6, 0) == "trailing 7 day inclusive"

    def test_leading_exclusive_canonical(self):
        assert _moving_range(-1, 7) == "leading 7 day"

    def test_leading_inclusive_canonical(self):
        assert _moving_range(0, 6) == "leading 7 day inclusive"

    @pytest.mark.parametrize("start,end", [
        (-1, -1),
        (-2, -1),
        (-5, 0),
        (-1, -5),
        (0, -5),
    ])
    def test_non_positive_n_raises(self, start, end):
        with pytest.raises(UntranslatableError):
            _moving_range(start, end)


class TestEmitWindowMeasureMoving:
    """Synthetic moving_sum shapes -- the four live-verified range forms plus
    the unmapped-shape UntranslatableError, per ts-databricks-formula-translation.md
    "Rolling Window Functions" / "Leading Window"."""

    @staticmethod
    def _col_resolver(node):
        return f"source.{node['column']}"

    @staticmethod
    def _model(expr):
        return {"model_tables": [], "columns": [],
                "formulas": [{"id": "f", "name": "X", "expr": expr}]}

    COL = {"name": "X", "formula_id": "f", "properties": {"column_type": "MEASURE"}}

    def test_trailing_exclusive(self):
        model = self._model("moving_sum ( [FACT::AMOUNT] , 7 , -1 , [FACT::ORDER_DATE] )")
        measure, extra = emit_window_measure(self.COL, self._col_resolver, model=model, existing_dims=[])
        assert measure["expr"] == "SUM(source.AMOUNT)"
        assert measure["window"] == [
            {"order": "fact_order_date", "range": "trailing 7 day", "semiadditive": "last"}]

    def test_trailing_inclusive(self):
        model = self._model("moving_sum ( [FACT::AMOUNT] , 6 , 0 , [FACT::ORDER_DATE] )")
        measure, extra = emit_window_measure(self.COL, self._col_resolver, model=model, existing_dims=[])
        assert measure["window"] == [
            {"order": "fact_order_date", "range": "trailing 7 day inclusive", "semiadditive": "last"}]

    def test_leading_exclusive(self):
        model = self._model("moving_sum ( [FACT::AMOUNT] , -1 , 7 , [FACT::ORDER_DATE] )")
        measure, extra = emit_window_measure(self.COL, self._col_resolver, model=model, existing_dims=[])
        assert measure["window"] == [
            {"order": "fact_order_date", "range": "leading 7 day", "semiadditive": "last"}]

    def test_leading_inclusive(self):
        model = self._model("moving_sum ( [FACT::AMOUNT] , 0 , 6 , [FACT::ORDER_DATE] )")
        measure, extra = emit_window_measure(self.COL, self._col_resolver, model=model, existing_dims=[])
        assert measure["window"] == [
            {"order": "fact_order_date", "range": "leading 7 day inclusive", "semiadditive": "last"}]

    def test_unmapped_shape_raises(self):
        model = self._model("moving_sum ( [FACT::AMOUNT] , -2 , 3 , [FACT::ORDER_DATE] )")
        with pytest.raises(UntranslatableError):
            emit_window_measure(self.COL, self._col_resolver, model=model, existing_dims=[])

    @pytest.mark.parametrize("start,end", [
        (-1, -1),  # end==-1 anchor -> N=start=-1 (non-positive)
        (-2, -1),  # end==-1 anchor -> N=start=-2 (non-positive)
        (-5, 0),   # end==0 anchor -> N=start+1=-4 (non-positive)
        (-1, -5),  # start==-1 anchor -> N=end=-5 (non-positive)
        (0, -5),   # start==0 anchor -> N=end+1=-4 (non-positive)
    ])
    def test_anchor_matches_but_non_positive_n_raises(self, start, end):
        # These pairs each match one of the four anchor conditions (end==-1,
        # end==0, start==-1, start==0) but derive a non-positive day count --
        # previously silently emitted a garbage "trailing/leading -N day"
        # range string instead of raising. See Task 9 review finding.
        model = self._model(f"moving_sum ( [FACT::AMOUNT] , {start} , {end} , [FACT::ORDER_DATE] )")
        with pytest.raises(UntranslatableError):
            emit_window_measure(self.COL, self._col_resolver, model=model, existing_dims=[])

    def test_moving_average(self):
        model = self._model("moving_average ( [FACT::AMOUNT] , 30 , -1 , [FACT::ORDER_DATE] )")
        measure, extra = emit_window_measure(self.COL, self._col_resolver, model=model, existing_dims=[])
        assert measure["expr"] == "AVG(source.AMOUNT)"
        assert measure["window"] == [
            {"order": "fact_order_date", "range": "trailing 30 day", "semiadditive": "last"}]

    def test_order_dim_reused_when_already_present(self):
        model = self._model("moving_sum ( [FACT::AMOUNT] , 7 , -1 , [FACT::ORDER_DATE] )")
        existing = [{"name": "order_date", "expr": "source.ORDER_DATE", "display_name": "Order Date"}]
        measure, extra = emit_window_measure(self.COL, self._col_resolver, model=model, existing_dims=existing)
        assert measure["window"] == [
            {"order": "order_date", "range": "trailing 7 day", "semiadditive": "last"}]
        assert extra == []


class TestEmitWindowMeasureCumulative:
    def test_cumulative_sum(self):
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "f", "name": "Running Total",
             "expr": "cumulative_sum ( [FACT::AMOUNT] , [FACT::ORDER_DATE] )"}]}
        col = {"name": "Running Total", "formula_id": "f", "properties": {"column_type": "MEASURE"}}
        measure, extra = emit_window_measure(
            col, lambda n: f"source.{n['column']}", model=model, existing_dims=[])
        assert measure["expr"] == "SUM(source.AMOUNT)"
        assert measure["window"][0]["range"] == "cumulative"
        assert measure["window"][0]["semiadditive"] == "last"


class TestEmitWindowMeasureSemiAdditive:
    def test_worked_example_formula_7_inventory_balance(self):
        # last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) ,
        #   { [DM_DATE_DIM::DATE_VALUE] } )
        # The formula's ordering date, [DM_DATE_DIM::DATE_VALUE], is join-equal
        # (per the model's own join predicate) to the fact table's own
        # DM_INVENTORY::BALANCE_DATE column, which already has an existing
        # "balance_date" dimension -- the worked example's documented answer
        # reuses that dimension rather than the joined-through dot-path
        # ("dates.DATE_VALUE"), which has no dimension of its own in this MV.
        model = {
            "model_tables": [
                {"name": "DM_INVENTORY", "joins": [
                    {"with": "DM_DATE_DIM",
                     "on": "[DM_INVENTORY::BALANCE_DATE] = [DM_DATE_DIM::DATE_VALUE]"},
                ]},
                {"name": "DM_DATE_DIM"},
            ],
            "columns": [
                {"name": "Balance Date", "column_id": "DM_INVENTORY::BALANCE_DATE",
                 "properties": {"column_type": "ATTRIBUTE"}},
            ],
            "formulas": [
                {"id": "formula_inv_bal", "name": "Inventory Balance",
                 "expr": "last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , "
                         "{ [DM_DATE_DIM::DATE_VALUE] } )"},
            ],
        }
        col = {"name": "Inventory Balance", "formula_id": "formula_inv_bal",
               "properties": {"column_type": "MEASURE"}}

        def col_resolver(node):
            if node["table"] == "DM_INVENTORY":
                return f"source.{node['column']}"
            if node["table"] == "DM_DATE_DIM":
                return f"dates.{node['column']}"
            raise UntranslatableError(f"unexpected table {node['table']!r}")

        existing_dims = [
            {"name": "balance_date", "expr": "source.BALANCE_DATE", "display_name": "Balance Date"},
        ]

        measure, extra_dims = emit_window_measure(
            col, col_resolver, model=model, existing_dims=existing_dims)

        assert measure["expr"] == "SUM(source.FILLED_INVENTORY)"
        assert measure["window"] == [{"order": "balance_date", "semiadditive": "last", "range": "current"}]
        assert extra_dims == []

    def test_first_value_semiadditive_first(self):
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "f", "name": "Opening Balance",
             "expr": "first_value ( sum ( [FACT::AMOUNT] ) , query_groups ( ) , { [FACT::ORDER_DATE] } )"}]}
        col = {"name": "Opening Balance", "formula_id": "f", "properties": {"column_type": "MEASURE"}}
        measure, extra = emit_window_measure(
            col, lambda n: f"source.{n['column']}", model=model, existing_dims=[])
        assert measure["window"] == [
            {"order": "fact_order_date", "semiadditive": "first", "range": "current"}]


class TestEmitWindowMeasurePeriodOffset:
    SALES_MODEL = {"model_tables": [], "columns": [], "formulas": [
        {"id": "formula_monthly", "name": "Monthly Revenue",
         "expr": "sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = 0 , "
                 "[DM_ORDER_DETAIL::LINE_TOTAL] )"},
        {"id": "formula_prior_month", "name": "Prior Month Revenue",
         "expr": "sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = -1 , "
                 "[DM_ORDER_DETAIL::LINE_TOTAL] )"},
        {"id": "formula_last_year", "name": "Same Month Last Year",
         "expr": "sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = -12 , "
                 "[DM_ORDER_DETAIL::LINE_TOTAL] )"},
        {"id": "formula_prior_quarter", "name": "Prior Quarter Revenue",
         "expr": "sum_if ( diff_quarters ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = -1 , "
                 "[DM_ORDER_DETAIL::LINE_TOTAL] )"},
    ]}

    @staticmethod
    def _col_resolver(node):
        if node["table"] == "DM_ORDER_DETAIL":
            return f"source.{node['column']}"
        if node["table"] == "DM_DATE_DIM":
            return f"orders.dates.{node['column']}"
        raise UntranslatableError(f"unexpected table {node['table']!r}")

    def test_worked_example_formulas_5_and_6_monthly_and_prior_month(self):
        # Formula 5: sum_if(diff_months([DATE_VALUE], today()) = 0, [LINE_TOTAL])
        #   -> window: [{order: order_month, semiadditive: last, range: current}]
        #   + synthesized order_month dim: DATE_TRUNC('MONTH', orders.dates.DATE_VALUE)
        # Formula 6: same condition = -1 -> adds offset: -1 month, REUSING the
        #   same synthesized order_month dim (no duplicate).
        monthly_col = {"name": "Monthly Revenue", "formula_id": "formula_monthly",
                        "properties": {"column_type": "MEASURE"}}
        existing_dims: list = []
        monthly_measure, monthly_extra = emit_window_measure(
            monthly_col, self._col_resolver, model=self.SALES_MODEL, existing_dims=existing_dims)

        assert monthly_measure["expr"] == "SUM(source.LINE_TOTAL)"
        assert "offset" not in monthly_measure["window"][0]
        assert monthly_measure["window"][0]["range"] == "current"
        assert monthly_measure["window"][0]["semiadditive"] == "last"
        assert len(monthly_extra) == 1
        assert monthly_extra[0]["expr"] == "DATE_TRUNC('MONTH', orders.dates.DATE_VALUE)"
        month_dim_name = monthly_extra[0]["name"]
        assert monthly_measure["window"][0]["order"] == month_dim_name

        existing_dims = existing_dims + monthly_extra  # simulate Task 10 merging it in

        prior_col = {"name": "Prior Month Revenue", "formula_id": "formula_prior_month",
                     "properties": {"column_type": "MEASURE"}}
        prior_measure, prior_extra = emit_window_measure(
            prior_col, self._col_resolver, model=self.SALES_MODEL, existing_dims=existing_dims)

        assert prior_measure["expr"] == "SUM(source.LINE_TOTAL)"
        assert prior_measure["window"] == [
            {"order": month_dim_name, "range": "current",
             "semiadditive": "last", "offset": "-1 month"}]
        assert prior_extra == []  # reused the existing month dim, no duplicate synthesized

    def test_diff_months_minus_12_gives_offset_minus_1_year(self):
        col = {"name": "Same Month Last Year", "formula_id": "formula_last_year",
               "properties": {"column_type": "MEASURE"}}
        measure, extra = emit_window_measure(
            col, self._col_resolver, model=self.SALES_MODEL, existing_dims=[])
        assert measure["window"][0]["offset"] == "-1 year"

    def test_diff_quarters_minus_1_gives_offset_minus_3_month(self):
        col = {"name": "Prior Quarter Revenue", "formula_id": "formula_prior_quarter",
               "properties": {"column_type": "MEASURE"}}
        measure, extra = emit_window_measure(
            col, self._col_resolver, model=self.SALES_MODEL, existing_dims=[])
        assert measure["window"][0]["offset"] == "-3 month"

    def test_count_if_family_period_offset(self):
        # Any *_if family fn works, not just sum_if (classify_column routes all
        # 8 the same way when their condition contains diff_months/quarters/years).
        model = {"model_tables": [], "columns": [], "formulas": [
            {"id": "f", "name": "Distinct Buyers This Month",
             "expr": "unique_count_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = 0 , "
                     "[DM_ORDER_DETAIL::CUSTOMER_ID] )"}]}
        col = {"name": "Distinct Buyers This Month", "formula_id": "f",
               "properties": {"column_type": "MEASURE"}}
        measure, extra = emit_window_measure(
            col, self._col_resolver, model=model, existing_dims=[])
        assert measure["expr"] == "COUNT(DISTINCT source.CUSTOMER_ID)"


class TestSynthesizePeriodDim:
    def test_month_grain(self):
        node = {"node": "col", "table": "DM_DATE_DIM", "column": "DATE_VALUE"}
        dim = synthesize_period_dim(node, "month", lambda n: f"orders.dates.{n['column']}")
        assert dim["expr"] == "DATE_TRUNC('MONTH', orders.dates.DATE_VALUE)"
        assert dim["name"]
        assert dim["display_name"]


# --- Task 10: build_metric_view assembly + detect_fact_tables + ------------
# make_ref_resolver. Wires Tasks 6-9 together into one MV yaml_doc per fact
# table, and absorbs 4 required follow-ups from earlier task reviews (T8
# filter-boolean guard, T8 UNKNOWN-column omission, T8 filter-ambiguity
# warnings, T9 semi-additive order-dim reuse).

class TestDetectFactTables:
    def test_two_fact_model_returns_both_in_model_order(self):
        model = {
            "model_tables": [{"name": "FACT_A"}, {"name": "DIM"}, {"name": "FACT_B"}],
            "columns": [
                {"name": "Amount A", "column_id": "FACT_A::AMOUNT",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Region", "column_id": "DIM::REGION",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Amount B", "column_id": "FACT_B::AMOUNT",
                 "properties": {"column_type": "MEASURE"}},
            ],
            "formulas": [],
        }
        assert detect_fact_tables(model) == ["FACT_A", "FACT_B"]

    def test_single_fact_model_returns_one(self):
        model = {
            "model_tables": [{"name": "FACT"}, {"name": "DIM"}],
            "columns": [
                {"name": "Amount", "column_id": "FACT::AMOUNT",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Region", "column_id": "DIM::REGION",
                 "properties": {"column_type": "ATTRIBUTE"}},
            ],
            "formulas": [],
        }
        assert detect_fact_tables(model) == ["FACT"]

    def test_formula_measure_table_resolved_via_first_col_ref(self):
        # A formula-backed MEASURE column carries no column_id -- its table is
        # the table its first physical [T::col] ref resolves to.
        model = {
            "model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Double Amount", "formula_id": "f",
                 "properties": {"column_type": "MEASURE"}},
            ],
            "formulas": [{"id": "f", "name": "Double Amount", "expr": "[FACT::AMOUNT] * 2"}],
        }
        assert detect_fact_tables(model) == ["FACT"]

    def test_join_target_dimension_with_own_formula_measure_is_excluded(self):
        # A dimension table that is a join TARGET (named as a `with` value on
        # another table's joins[]) can still carry a formula MEASURE that
        # resolves (via the first-physical-column-ref DFS) to its OWN table --
        # e.g. a plain count() over one of its own columns, no cross-table
        # condition involved at all. It must NOT be returned as a fact table:
        # measure-attribution alone is not sufficient, join-root-ness is also
        # required. Regression guard for the Dunder Mifflin golden-test bug
        # (detect_fact_tables previously returned any measure-bearing table
        # regardless of whether it was itself a join target).
        model = {
            "model_tables": [
                {"name": "FACT", "joins": [{"with": "DIM"}]},
                {"name": "DIM"},
            ],
            "columns": [
                {"name": "Amount", "column_id": "FACT::AMOUNT",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Dim Count", "formula_id": "f",
                 "properties": {"column_type": "MEASURE"}},
            ],
            "formulas": [{"id": "f", "name": "Dim Count", "expr": "count ( [DIM::VALUE] )"}],
        }
        assert detect_fact_tables(model) == ["FACT"]


class TestMakeRefResolver:
    def test_measure_role_ref(self):
        resolver = make_ref_resolver({"Quantity": "measure"})
        assert resolver({"node": "ref", "name": "Quantity"}) == "MEASURE(quantity)"

    def test_lod_dimension_role_ref(self):
        resolver = make_ref_resolver({"Category Quantity": "lod_dimension"})
        assert resolver({"node": "ref", "name": "Category Quantity"}) == "ANY_VALUE(category_quantity)"

    def test_unknown_ref_raises(self):
        resolver = make_ref_resolver({"Quantity": "measure"})
        with pytest.raises(UntranslatableError):
            resolver({"node": "ref", "name": "Something Else"})


# A compact 2-table model exercising every routing path build_metric_view has
# to wire together: 1 plain dimension (Region), 1 plain measure (Amount), 1
# LOD dimension formula (Category Quantity, reusing Amount/Region so no extra
# physical columns are needed), 1 boolean filter formula (reusing Amount), 1
# join. Mirrors the real-world pattern from the Dunder Mifflin worked example
# where a physical column doubles as both its own dimension/measure AND an
# LOD/filter formula's input.
COMPACT_MODEL = {
    "model_tables": [
        {"name": "FACT", "joins": [
            {"with": "DIM", "on": "[FACT::DIM_ID] = [DIM::ID]",
             "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
        {"name": "DIM"},
    ],
    "description": "Compact test MV",
    "columns": [
        {"name": "Region", "column_id": "DIM::REGION",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "Amount", "column_id": "FACT::AMOUNT",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Category Quantity", "formula_id": "formula_lod",
         "properties": {"column_type": "ATTRIBUTE"}},
        {"name": "MV Filter", "formula_id": "formula_filter",
         "properties": {"column_type": "ATTRIBUTE"}},
    ],
    "formulas": [
        {"id": "formula_lod", "name": "Category Quantity",
         "expr": "group_aggregate ( sum ( [FACT::AMOUNT] ) , { [DIM::REGION] } , query_filters ( ) )"},
        {"id": "formula_filter", "name": "MV Filter", "expr": "[FACT::AMOUNT] > 100"},
    ],
}
COMPACT_TABLES = [
    {"table": {"name": "FACT", "db": "cat", "schema": "sch", "db_table": "fact_tbl",
        "columns": [
            {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
            {"name": "DIM_ID", "db_column_properties": {"data_type": "VARCHAR"}},
        ]}},
    {"table": {"name": "DIM", "db": "cat", "schema": "sch", "db_table": "dim_tbl",
        "columns": [
            {"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}},
            {"name": "ID", "db_column_properties": {"data_type": "VARCHAR"}},
        ]}},
]


class TestBuildMetricView:
    def test_compact_model_full_yaml_doc(self):
        result = build_metric_view(
            COMPACT_MODEL, COMPACT_TABLES, source_table="FACT", catalog="cat", schema="sch")
        assert result["skipped"] == []
        doc = result["yaml_doc"]
        assert list(doc.keys()) == [
            "version", "comment", "source", "joins", "dimensions", "measures", "filter"]
        assert doc == {
            "version": "1.1",
            "comment": "Compact test MV",
            "source": "cat.sch.fact_tbl",
            "joins": [{
                "name": "dim", "source": "cat.sch.dim_tbl",
                "on": "source.DIM_ID = dim.ID",
                "rely": {"at_most_one_match": True},
                "cardinality": "many_to_one",
            }],
            "dimensions": [
                {"name": "region", "expr": "dim.REGION", "display_name": "Region"},
                {"name": "category_quantity",
                 "expr": "SUM(source.AMOUNT) OVER (PARTITION BY dim.REGION)",
                 "display_name": "Category Quantity"},
            ],
            "measures": [
                {"name": "amount", "expr": "SUM(source.AMOUNT)", "display_name": "Amount"},
            ],
            "filter": "source.AMOUNT > 100",
        }

    def test_unknown_column_type_omitted(self):
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Amount", "column_id": "FACT::AMOUNT",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Mystery", "column_id": "FACT::MYSTERY",
                 "properties": {"column_type": "UNKNOWN"}},
            ],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [
                {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
                {"name": "MYSTERY", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        result = build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")
        doc = result["yaml_doc"]
        dim_names = [d["name"] for d in doc["dimensions"]]
        assert "mystery" not in dim_names
        assert any(s["name"] == "Mystery" for s in result["skipped"])
        assert any("Mystery" in w for w in result["warnings"])

    def test_non_boolean_named_filter_rerouted_to_dimension(self):
        # "Double Filter" matches the filter-detection name heuristic but its
        # expr is arithmetic, not boolean -- required follow-up #1: must NOT
        # land in filter:, and required follow-up #3: must be warned about.
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Amount", "column_id": "FACT::AMOUNT",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Double Filter", "formula_id": "formula_df",
                 "properties": {"column_type": "ATTRIBUTE"}},
            ],
            "formulas": [
                {"id": "formula_df", "name": "Double Filter", "expr": "[FACT::AMOUNT] * 2"},
            ]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}}]
        result = build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")
        doc = result["yaml_doc"]
        assert "filter" not in doc
        dim_names = [d["name"] for d in doc["dimensions"]]
        assert "double_filter" in dim_names
        double = next(d for d in doc["dimensions"] if d["name"] == "double_filter")
        assert double["expr"] == "source.AMOUNT * 2"
        assert any("Double Filter" in w for w in result["warnings"])

    def test_boolean_filter_gets_a_confirmation_warning(self):
        # Required follow-up #3: every boolean-ATTRIBUTE formula routed to
        # filter: must also surface a warning for the checkpoint to confirm.
        result = build_metric_view(
            COMPACT_MODEL, COMPACT_TABLES, source_table="FACT", catalog="cat", schema="sch")
        assert any("MV Filter" in w for w in result["warnings"])

    def test_measure_referencing_another_measure_uses_measure_ref(self):
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Amount", "column_id": "FACT::AMOUNT",
                 "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
                {"name": "Double Amount", "formula_id": "formula_double",
                 "properties": {"column_type": "MEASURE"}},
            ],
            "formulas": [
                {"id": "formula_double", "name": "Double Amount", "expr": "[Amount] * 2"},
            ]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}}]
        result = build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")
        assert result["skipped"] == []
        double = next(m for m in result["yaml_doc"]["measures"] if m["name"] == "double_amount")
        assert double["expr"] == "MEASURE(amount) * 2"

    def test_duplicate_display_name_raises(self):
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Amount", "column_id": "FACT::AMOUNT",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Amount", "column_id": "FACT::AMOUNT2",
                 "properties": {"column_type": "ATTRIBUTE"}},
            ],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [
                {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
                {"name": "AMOUNT2", "db_column_properties": {"data_type": "DOUBLE"}}]}}]
        with pytest.raises(ValueError):
            build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")

    def test_duplicate_machine_name_raises(self):
        # Review fix wave FIX 2: two DISTINCT display names ("Order-ID" and
        # "Order ID") both collapse to the same to_snake() machine name
        # ("order_id") -- the display_name-only check misses this. Must raise
        # ValueError naming the collision even though display_name differs.
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Order-ID", "column_id": "FACT::ORDER_ID_A",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Order ID", "column_id": "FACT::ORDER_ID_B",
                 "properties": {"column_type": "ATTRIBUTE"}},
            ],
            "formulas": []}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [
                {"name": "ORDER_ID_A", "db_column_properties": {"data_type": "VARCHAR"}},
                {"name": "ORDER_ID_B", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        with pytest.raises(ValueError, match="order_id"):
            build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")

    def test_formula_backed_unknown_column_skipped_not_emitted(self):
        # Review fix wave FIX 3, integration-level: a formula-backed UNKNOWN
        # column must be skipped by build_metric_view, not emitted as a
        # dimension.
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Amount", "column_id": "FACT::AMOUNT",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Mystery Formula", "formula_id": "formula_mystery",
                 "properties": {"column_type": "UNKNOWN"}},
            ],
            "formulas": [
                {"id": "formula_mystery", "name": "Mystery Formula",
                 "expr": "concat ( [FACT::A] , [FACT::B] )"},
            ]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [
                {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
                {"name": "A", "db_column_properties": {"data_type": "VARCHAR"}},
                {"name": "B", "db_column_properties": {"data_type": "VARCHAR"}}]}}]
        result = build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")
        doc = result["yaml_doc"]
        dim_names = [d["name"] for d in doc["dimensions"]]
        assert "mystery_formula" not in dim_names
        assert any(s["name"] == "Mystery Formula" for s in result["skipped"])
        assert any("Mystery Formula" in w for w in result["warnings"])

    def test_semiadditive_order_dim_reused_end_to_end(self):
        # Required follow-up #4: build_metric_view must thread `tables` +
        # resolved join predicates through so a window measure's order: dim
        # reuses an already-emitted date dimension (matched via the join-
        # equal column) instead of synthesizing a redundant duplicate.
        model = {
            "model_tables": [
                {"name": "DM_INVENTORY", "joins": [
                    {"with": "DM_DATE_DIM",
                     "on": "[DM_INVENTORY::BALANCE_DATE] = [DM_DATE_DIM::DATE_VALUE]",
                     "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
                {"name": "DM_DATE_DIM"},
            ],
            "columns": [
                {"name": "Balance Date", "column_id": "DM_INVENTORY::BALANCE_DATE",
                 "properties": {"column_type": "ATTRIBUTE"}},
                {"name": "Inventory Balance", "formula_id": "formula_inv_bal",
                 "properties": {"column_type": "MEASURE"}},
            ],
            "formulas": [
                {"id": "formula_inv_bal", "name": "Inventory Balance",
                 "expr": "last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , "
                         "query_groups ( ) , { [DM_DATE_DIM::DATE_VALUE] } )"},
            ],
        }
        tables = [
            {"table": {"name": "DM_INVENTORY", "db": "c", "schema": "s",
                "db_table": "dm_inventory", "columns": [
                    {"name": "BALANCE_DATE", "db_column_properties": {"data_type": "DATE"}},
                    {"name": "FILLED_INVENTORY", "db_column_properties": {"data_type": "DOUBLE"}},
                ]}},
            {"table": {"name": "DM_DATE_DIM", "db": "c", "schema": "s",
                "db_table": "dm_date_dim", "columns": [
                    {"name": "DATE_VALUE", "db_column_properties": {"data_type": "DATE"}},
                ]}},
        ]
        result = build_metric_view(
            model, tables, source_table="DM_INVENTORY", catalog="c", schema="s")
        assert result["skipped"] == []
        doc = result["yaml_doc"]
        assert [d["name"] for d in doc["dimensions"]] == ["balance_date"]
        inv_balance = next(m for m in doc["measures"] if m["name"] == "inventory_balance")
        assert inv_balance["expr"] == "SUM(source.FILLED_INVENTORY)"
        assert inv_balance["window"] == [
            {"order": "balance_date", "semiadditive": "last", "range": "current"}]


# --- Review fix wave: FIX 1 -- cascade-skip dangling MEASURE()/ANY_VALUE() ---
# references. A formula can CLASSIFY as measure/lod_dimension (so
# `_build_ref_roles` treats it as a valid ref target) yet FAIL during its own
# EMISSION (emit_sql raises UntranslatableError) and land in `skipped`. A
# sibling formula referencing it by name has already resolved to
# MEASURE(<name>)/ANY_VALUE(<name>) and emits successfully -- without the
# cascade, that reference would point at a name in neither `dimensions:` nor
# `measures:`: a silently invalid Metric View.

class TestCascadeSkipDanglingRefs:
    def test_direct_dangling_measure_ref_cascades_to_skip(self):
        # Amount's own formula uses a function with no Databricks translation
        # -> fails emission, lands in skipped. Double Amount references
        # [Amount] -- classification alone makes it a valid ref target, so
        # Double Amount itself emits fine as "MEASURE(amount) * 2" ... except
        # "amount" never actually makes it into measures:. The cascade must
        # catch this and skip Double Amount too.
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Amount", "formula_id": "formula_amount",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Double Amount", "formula_id": "formula_double",
                 "properties": {"column_type": "MEASURE"}},
            ],
            "formulas": [
                {"id": "formula_amount", "name": "Amount",
                 "expr": "totally_unsupported_fn ( [FACT::X] )"},
                {"id": "formula_double", "name": "Double Amount", "expr": "[Amount] * 2"},
            ]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "X", "db_column_properties": {"data_type": "DOUBLE"}}]}}]

        result = build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")

        measure_names = {m["name"] for m in result["yaml_doc"]["measures"]}
        assert "amount" not in measure_names
        assert "double_amount" not in measure_names

        skipped_names = {s["name"] for s in result["skipped"]}
        assert "Amount" in skipped_names
        assert "Double Amount" in skipped_names

        # A warning must name the missing dependency ("amount", the machine
        # name Double Amount's expr referenced via MEASURE(amount)).
        assert any("amount" in w for w in result["warnings"])

    def test_transitive_dangling_chain_all_skipped(self):
        # C references B references A; A fails emission. The cascade must
        # remove B (dangling ref to "a") on one pass, THEN remove C (now
        # dangling on "b", only detectable once B is actually gone) on the
        # next pass -- exercising the fixed-point repeat, not just one pass.
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "A", "formula_id": "formula_a",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "B", "formula_id": "formula_b",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "C", "formula_id": "formula_c",
                 "properties": {"column_type": "MEASURE"}},
            ],
            "formulas": [
                {"id": "formula_a", "name": "A", "expr": "totally_unsupported_fn ( [FACT::X] )"},
                {"id": "formula_b", "name": "B", "expr": "[A] * 2"},
                {"id": "formula_c", "name": "C", "expr": "[B] * 3"},
            ]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [{"name": "X", "db_column_properties": {"data_type": "DOUBLE"}}]}}]

        result = build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")

        assert result["yaml_doc"]["measures"] == []
        skipped_names = {s["name"] for s in result["skipped"]}
        assert skipped_names == {"A", "B", "C"}

    def test_dangling_ref_does_not_affect_healthy_siblings(self):
        # A dangling formula's removal must not disturb an unrelated, fully
        # healthy measure in the same MV.
        model = {"model_tables": [{"name": "FACT"}],
            "columns": [
                {"name": "Amount", "formula_id": "formula_amount",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Double Amount", "formula_id": "formula_double",
                 "properties": {"column_type": "MEASURE"}},
                {"name": "Quantity", "column_id": "FACT::QTY",
                 "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
            ],
            "formulas": [
                {"id": "formula_amount", "name": "Amount",
                 "expr": "totally_unsupported_fn ( [FACT::X] )"},
                {"id": "formula_double", "name": "Double Amount", "expr": "[Amount] * 2"},
            ]}
        tables = [{"table": {"name": "FACT", "db": "c", "schema": "s", "db_table": "fact",
            "columns": [
                {"name": "X", "db_column_properties": {"data_type": "DOUBLE"}},
                {"name": "QTY", "db_column_properties": {"data_type": "DOUBLE"}}]}}]

        result = build_metric_view(model, tables, source_table="FACT", catalog="c", schema="s")

        measure_names = {m["name"] for m in result["yaml_doc"]["measures"]}
        assert measure_names == {"quantity"}
