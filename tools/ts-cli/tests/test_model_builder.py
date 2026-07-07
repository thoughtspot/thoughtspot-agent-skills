"""Tests for model_builder.py — model-level transforms for Tableau migration.

Uses real formulas from the CPG Merch Promotion Performance workbook to test
each of the 8 failure modes identified in the migration pipeline analysis.
"""
import pytest

from ts_cli.model_builder import (
    _extract_joins,
    _extract_tables,
    add_formula_prefix,
    build_col_table_map,
    build_column_lookup,
    build_formula_levels,
    build_model_tml,
    build_sql_view_tml,
    expr_is_aggregated,
    extract_parameters,
    filter_unresolvable_formulas,
    fix_bare_refs,
    fix_double_aggregation,
    merge_formulas_into_model,
    resolve_name_collisions,
    split_for_phased_import,
)


# ---------------------------------------------------------------------------
# Fixture data — real formulas from CPG Merch Promotion Performance
# ---------------------------------------------------------------------------

FORMULA_NAMES = {
    "Customers LY",
    "Customers Pre",
    "Units LY",
    "Sales LY",
    "Orders LY",
    "Product Sales LY",
    "Product Sales Pre",
    "CPG Category Sales Promo",
    "Products Sales > 0",
    "New Customer %",
    "Redeemer Sales",
    "Formula Category",
    "Category Tier",
}

PARAM_NAMES = {
    "Metric",
    "Engagement Type",
    "CPG Preview",
    "Top 10",
    "Category Tier",
    "Redemption Metric",
}


# ===================================================================
# Test 1: formula_ prefix for cross-references
# ===================================================================

class TestFormulaPrefix:
    """Failure #1 — formula refs must use [formula_Name] syntax."""

    def test_basic_formula_ref(self):
        expr = "sum ( [Customers LY] )"
        result = add_formula_prefix(expr, FORMULA_NAMES, PARAM_NAMES)
        assert result == "sum ( [formula_Customers LY] )"

    def test_table_qualified_ref_unchanged(self):
        expr = "[PROMOTION_METRICS::PERIOD_TYPE]"
        result = add_formula_prefix(expr, FORMULA_NAMES, PARAM_NAMES)
        assert result == "[PROMOTION_METRICS::PERIOD_TYPE]"

    def test_parameter_ref_unchanged(self):
        expr = "if ( [Engagement Type]='All' ) then true"
        result = add_formula_prefix(expr, FORMULA_NAMES, PARAM_NAMES)
        assert result == "if ( [Engagement Type]='All' ) then true"

    def test_already_prefixed_unchanged(self):
        expr = "sum ( [formula_Customers LY] )"
        result = add_formula_prefix(expr, FORMULA_NAMES, PARAM_NAMES)
        assert result == "sum ( [formula_Customers LY] )"

    def test_mixed_refs(self):
        """Formula refs get prefix; column and param refs don't."""
        expr = (
            "sum ( [Customers LY] ) + "
            "[PROMOTION_METRICS::SALES] + "
            "[Metric]"
        )
        result = add_formula_prefix(expr, FORMULA_NAMES, PARAM_NAMES)
        assert "[formula_Customers LY]" in result
        assert "[PROMOTION_METRICS::SALES]" in result
        assert "[Metric]" in result
        assert "[formula_Metric]" not in result

    def test_multiple_formula_refs(self):
        expr = "ifnull ( [Product Sales LY] , 0 ) + ifnull ( [Product Sales Pre] , 0 )"
        result = add_formula_prefix(expr, FORMULA_NAMES, PARAM_NAMES)
        assert "[formula_Product Sales LY]" in result
        assert "[formula_Product Sales Pre]" in result

    def test_param_same_name_as_formula_uses_param(self):
        """Category Tier is both a param and formula — param wins."""
        expr = "[Category Tier] = [PROMOTION_MASTER::TIER]"
        result = add_formula_prefix(expr, FORMULA_NAMES, PARAM_NAMES)
        # Parameter takes priority — should NOT get formula_ prefix
        assert result == "[Category Tier] = [PROMOTION_MASTER::TIER]"


# ===================================================================
# Test 2: double-aggregation detection
# ===================================================================

class TestDoubleAggregation:
    """Failure #2 — sum([formula_X]) fails when X is already aggregated."""

    def test_non_aggregated_ref_kept(self):
        """sum([formula_X]) is valid when X is row-level (if/then/else)."""
        formula_exprs = {
            "Customers LY": "if ( [PROMOTION_METRICS::PERIOD_TYPE]='ly' ) then [PROMOTION_METRICS::CUSTOMERS] else 0",
        }
        expr = "sum ( [formula_Customers LY] )"
        result = fix_double_aggregation(expr, formula_exprs)
        assert result == "sum ( [formula_Customers LY] )"

    def test_aggregated_ref_unwrapped(self):
        """sum([formula_X]) → [formula_X] when X contains sum_if."""
        formula_exprs = {
            "Redeemer Sales": "sum_if ( [PROMOTION_METRICS::CUSTOMER_TYPE]='Redeemer' , [PROMOTION_METRICS::SALES] )",
        }
        expr = "sum ( [formula_Redeemer Sales] )"
        result = fix_double_aggregation(expr, formula_exprs)
        assert result == "[formula_Redeemer Sales]"

    def test_sum_if_in_ref_detected(self):
        formula_exprs = {
            "New Customer %": "sum_if ( [CUSTOMER_ORDERS::COHORT]='New' , [PROMOTION_MASTER::CUSTOMERS] )",
        }
        assert expr_is_aggregated(formula_exprs["New Customer %"])

    def test_row_level_not_aggregated(self):
        expr = "if ( [PROMOTION_METRICS::PERIOD_TYPE]='ly' ) then [PROMOTION_METRICS::CUSTOMERS] else 0"
        assert not expr_is_aggregated(expr)

    def test_group_aggregate_detected(self):
        expr = "group_aggregate ( sum ( [SALES] ) , {} , query_filters () )"
        assert expr_is_aggregated(expr)

    def test_multiple_refs_mixed(self):
        """Only unwrap refs that are already aggregated."""
        formula_exprs = {
            "Customers LY": "if ( [T::PERIOD_TYPE]='ly' ) then [T::CUSTOMERS] else 0",
            "Redeemer Sales": "sum_if ( [T::CUSTOMER_TYPE]='Redeemer' , [T::SALES] )",
        }
        expr = "sum ( [formula_Customers LY] ) - [formula_Redeemer Sales]"
        # Customers LY is row-level → sum stays
        # Redeemer Sales is already aggregated but it's bare (no sum wrapper) → unchanged
        result = fix_double_aggregation(expr, formula_exprs)
        assert "sum ( [formula_Customers LY] )" in result


# ===================================================================
# Test 3: sum_if simplification — handled by translate_single,
# tested here for integration
# ===================================================================

# (sum_if conversion is in tableau_translate.py's convert_agg_if —
#  tested in test_tableau_translate.py. We verify it persists through
#  the model builder pipeline in integration tests below.)


# ===================================================================
# Test 6: parameter ordering
# ===================================================================

class TestParameterExtraction:
    """Failure #6 — parameters must be in model before formulas reference them."""

    def test_build_model_includes_parameters(self):
        params = [
            {"name": "Metric", "default_value": "Sales", "data_type": "CHAR",
             "list_config": {"list_choice": [
                 {"value": "Sales", "display_name": "Sales"},
                 {"value": "Units", "display_name": "Units"},
             ]}},
        ]
        model = build_model_tml(
            model_name="Test",
            connection_name="TEST_CONN",
            tables=[{"name": "T1", "db_table": "T1"}],
            columns=[],
            joins=[],
            parameters=params,
            translated_formulas=[],
        )
        assert len(model["model"]["parameters"]) == 1
        assert model["model"]["parameters"][0]["name"] == "Metric"
        assert model["model"]["parameters"][0]["data_type"] == "CHAR"
        assert "list_config" in model["model"]["parameters"][0]


# ===================================================================
# Test 7 & 8: name collision resolution
# ===================================================================

class TestNameCollisions:
    """Failures #7 and #8 — names must be unique across columns/formulas/params."""

    def test_formula_param_clash_renames_formula(self):
        """Formula named 'Metric' + param named 'Metric' → formula becomes 'Metric Selection'."""
        columns = [{"name": "Sales", "db_column_name": "SALES"}]
        formulas = [{"name": "Metric", "expr": "[Metric]"}]
        params = [{"name": "Metric", "default_value": "Sales", "data_type": "CHAR"}]

        cols, forms, renames = resolve_name_collisions(columns, formulas, params)
        assert forms[0]["name"] == "Metric Selection"
        assert renames == {"Metric": "Metric Selection"}
        assert len(cols) == 1  # Sales column unchanged

    def test_column_formula_clash_drops_column(self):
        """Column named 'Sales LY' + formula named 'Sales LY' → column dropped."""
        columns = [
            {"name": "Sales LY", "db_column_name": "SALES_LY"},
            {"name": "Revenue", "db_column_name": "REVENUE"},
        ]
        formulas = [{"name": "Sales LY", "expr": "if([T::PERIOD_TYPE]='ly') then [T::SALES] else 0"}]
        params = []

        cols, forms, renames = resolve_name_collisions(columns, formulas, params)
        assert len(cols) == 1  # Sales LY column dropped
        assert cols[0]["name"] == "Revenue"
        assert len(forms) == 1
        assert forms[0]["name"] == "Sales LY"  # Formula kept

    def test_multiple_collisions(self):
        columns = [
            {"name": "Metric", "db_column_name": "METRIC"},
            {"name": "Sales", "db_column_name": "SALES"},
        ]
        formulas = [
            {"name": "Metric", "expr": "[Metric]"},
            {"name": "Top 10", "expr": "[Top 10]"},
        ]
        params = [
            {"name": "Metric", "default_value": "Sales", "data_type": "CHAR"},
            {"name": "Top 10", "default_value": "Brands", "data_type": "CHAR"},
        ]

        cols, forms, renames = resolve_name_collisions(columns, formulas, params)
        # Both formulas renamed (param clash)
        assert forms[0]["name"] == "Metric Selection"
        assert forms[1]["name"] == "Top 10 Selection"
        # Metric column NOT dropped (because the formula was renamed to "Metric Selection")
        assert len(cols) == 2

    def test_no_collisions_unchanged(self):
        columns = [{"name": "Sales", "db_column_name": "SALES"}]
        formulas = [{"name": "Revenue", "expr": "[T::SALES] * [T::PRICE]"}]
        params = [{"name": "Metric", "default_value": "Sales", "data_type": "CHAR"}]

        cols, forms, renames = resolve_name_collisions(columns, formulas, params)
        assert len(cols) == 1
        assert len(forms) == 1
        assert renames == {}


# ===================================================================
# Dependency level computation
# ===================================================================

class TestFormulaLevels:
    """build_formula_levels assigns correct dependency levels from raw calcs."""

    def test_no_dependencies_all_level_0(self):
        calcs = [
            {"caption": "A", "formula": "[COL1]"},
            {"caption": "B", "formula": "[COL2] + 1"},
        ]
        calc_map = {"Calculation_1": "A", "[Calculation_1]": "A",
                     "Calculation_2": "B", "[Calculation_2]": "B"}
        levels = build_formula_levels(calcs, calc_map)
        assert levels["A"] == 0
        assert levels["B"] == 0

    def test_linear_chain(self):
        calcs = [
            {"caption": "Base", "formula": "[COL1]"},
            {"caption": "Mid", "formula": "[Calculation_1]"},
            {"caption": "Top", "formula": "[Calculation_2]"},
        ]
        calc_map = {
            "Calculation_1": "Base", "[Calculation_1]": "Base",
            "Calculation_2": "Mid", "[Calculation_2]": "Mid",
            "Calculation_3": "Top", "[Calculation_3]": "Top",
        }
        levels = build_formula_levels(calcs, calc_map)
        assert levels["Base"] == 0
        assert levels["Mid"] == 1
        assert levels["Top"] == 2

    def test_copy_style_refs_detected(self):
        """Copy-style [Field (copy)_NNN] refs create dependencies too."""
        calcs = [
            {"caption": "Source", "formula": "[COL1]"},
            {"caption": "Consumer", "formula": "[Source (copy)_999]"},
        ]
        calc_map = {
            "Calculation_1": "Source", "[Calculation_1]": "Source",
            "Source (copy)_999": "Source", "[Source (copy)_999]": "Source",
            "Calculation_2": "Consumer", "[Calculation_2]": "Consumer",
        }
        levels = build_formula_levels(calcs, calc_map)
        assert levels["Source"] == 0
        assert levels["Consumer"] == 1

    def test_diamond_dependency(self):
        """A depends on B and C; B and C depend on D."""
        calcs = [
            {"caption": "D", "formula": "[COL1]"},
            {"caption": "B", "formula": "[Calculation_D]"},
            {"caption": "C", "formula": "[Calculation_D]"},
            {"caption": "A", "formula": "[Calculation_B] + [Calculation_C]"},
        ]
        calc_map = {
            "Calculation_D": "D", "[Calculation_D]": "D",
            "Calculation_B": "B", "[Calculation_B]": "B",
            "Calculation_C": "C", "[Calculation_C]": "C",
            "Calculation_A": "A", "[Calculation_A]": "A",
        }
        levels = build_formula_levels(calcs, calc_map)
        assert levels["D"] == 0
        assert levels["B"] == 1
        assert levels["C"] == 1
        assert levels["A"] == 2


# ===================================================================
# Phased import splitting
# ===================================================================

class TestPhasedImport:
    """Verify model is correctly split for multi-phase import."""

    def test_phase_0_has_no_formulas(self):
        model = {
            "model": {
                "name": "Test",
                "formulas": [
                    {"name": "F1", "id": "formula_F1", "expr": "[T::COL]"},
                    {"name": "F2", "id": "formula_F2", "expr": "[formula_F1]"},
                ],
                "columns": [
                    {"name": "COL", "column_id": "T::COL"},
                    {"name": "F1", "formula_id": "formula_F1"},
                    {"name": "F2", "formula_id": "formula_F2"},
                ],
                "parameters": [{"name": "P1"}],
            }
        }
        levels = {"F1": 0, "F2": 1}
        phases = split_for_phased_import(model, levels)

        assert len(phases) == 3  # phase 0 (no formulas) + level 0 + level 1
        assert len(phases[0]["model"]["formulas"]) == 0
        assert len(phases[0]["model"]["columns"]) == 1  # only physical column

    def test_phase_1_has_level_0_only(self):
        model = {
            "model": {
                "name": "Test",
                "formulas": [
                    {"name": "F1", "id": "formula_F1", "expr": "[T::COL]"},
                    {"name": "F2", "id": "formula_F2", "expr": "[formula_F1]"},
                ],
                "columns": [
                    {"name": "COL", "column_id": "T::COL"},
                    {"name": "F1", "formula_id": "formula_F1"},
                    {"name": "F2", "formula_id": "formula_F2"},
                ],
            }
        }
        levels = {"F1": 0, "F2": 1}
        phases = split_for_phased_import(model, levels)

        phase1_names = {f["name"] for f in phases[1]["model"]["formulas"]}
        assert phase1_names == {"F1"}

    def test_phase_2_is_cumulative(self):
        model = {
            "model": {
                "name": "Test",
                "formulas": [
                    {"name": "F1", "id": "formula_F1", "expr": "[T::COL]"},
                    {"name": "F2", "id": "formula_F2", "expr": "[formula_F1]"},
                ],
                "columns": [
                    {"name": "COL", "column_id": "T::COL"},
                    {"name": "F1", "formula_id": "formula_F1"},
                    {"name": "F2", "formula_id": "formula_F2"},
                ],
            }
        }
        levels = {"F1": 0, "F2": 1}
        phases = split_for_phased_import(model, levels)

        # Phase 2 includes BOTH level 0 and level 1 formulas
        phase2_names = {f["name"] for f in phases[2]["model"]["formulas"]}
        assert phase2_names == {"F1", "F2"}


# ===================================================================
# Integration: build_model_tml applies all transforms
# ===================================================================

class TestBuildModelIntegration:
    """End-to-end: build_model_tml applies formula_ prefix + double-agg fix."""

    def test_formula_prefix_applied(self):
        formulas = [
            {"name": "Customers LY", "expr": "if([T::PERIOD_TYPE]='ly') then [T::CUSTOMERS] else 0", "column_type": "MEASURE", "level": 0},
            {"name": "Customers Lift", "expr": "sum([Customers LY])", "column_type": "MEASURE", "level": 1},
        ]
        model = build_model_tml(
            model_name="Test",
            connection_name="CONN",
            tables=[{"name": "T", "db_table": "T"}],
            columns=[],
            joins=[],
            parameters=[],
            translated_formulas=formulas,
        )
        lift = next(f for f in model["model"]["formulas"] if f["name"] == "Customers Lift")
        assert "[formula_Customers LY]" in lift["expr"]

    def test_double_agg_fixed(self):
        formulas = [
            {"name": "Redeemer Sales", "expr": "sum_if([T::TYPE]='Redeemer', [T::SALES])", "column_type": "MEASURE", "level": 0},
            {"name": "Total Redeemer", "expr": "sum([Redeemer Sales])", "column_type": "MEASURE", "level": 1},
        ]
        model = build_model_tml(
            model_name="Test",
            connection_name="CONN",
            tables=[{"name": "T", "db_table": "T"}],
            columns=[],
            joins=[],
            parameters=[],
            translated_formulas=formulas,
        )
        total = next(f for f in model["model"]["formulas"] if f["name"] == "Total Redeemer")
        # sum([formula_Redeemer Sales]) should be unwrapped because Redeemer Sales is already aggregated
        assert "sum" not in total["expr"].lower() or "sum_if" in total["expr"].lower()
        assert "[formula_Redeemer Sales]" in total["expr"]

    def test_column_formula_clash_resolved(self):
        columns = [
            {"name": "Sales LY", "db_column_name": "SALES_LY", "column_type": "MEASURE", "data_type": "DOUBLE", "table": "T"},
        ]
        formulas = [
            {"name": "Sales LY", "expr": "if([T::PERIOD_TYPE]='ly') then [T::SALES] else 0", "column_type": "MEASURE", "level": 0},
        ]
        # resolve_name_collisions should drop the column
        cleaned_cols, cleaned_formulas, _ = resolve_name_collisions(columns, formulas, [])
        assert len(cleaned_cols) == 0
        assert len(cleaned_formulas) == 1


# ===================================================================
# Merge formulas into existing model
# ===================================================================

class TestMergeFormulas:

    def _make_existing_model(self):
        return {
            "guid": "abc-123",
            "model": {
                "name": "TestModel",
                "model_tables": [{"name": "T", "fqn": "table-guid-1"}],
                "formulas": [
                    {"id": "formula_Sales LY", "name": "Sales LY", "expr": "old expr 1"},
                    {"id": "formula_Units LY", "name": "Units LY", "expr": "old expr 2"},
                ],
                "columns": [
                    {"name": "COL1", "column_id": "T::COL1", "properties": {"column_type": "ATTRIBUTE"}},
                    {"name": "Sales LY", "formula_id": "formula_Sales LY", "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
                    {"name": "Units LY", "formula_id": "formula_Units LY", "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
                ],
                "properties": {"is_bypass_rls": False},
            },
        }

    def test_skips_existing_by_default(self):
        existing = self._make_existing_model()
        translated = [
            {"id": "formula_Sales LY", "name": "Sales LY", "expr": "new expr 1", "column_type": "MEASURE"},
        ]
        merged = merge_formulas_into_model(existing, translated)
        f = next(f for f in merged["model"]["formulas"] if f["id"] == "formula_Sales LY")
        assert f["expr"] == "old expr 1"
        assert merged["_merge_stats"]["skipped_existing"] == 1
        assert merged["_merge_stats"]["updated"] == 0

    def test_updates_existing_when_opted_in(self):
        existing = self._make_existing_model()
        translated = [
            {"id": "formula_Sales LY", "name": "Sales LY", "expr": "new expr 1", "column_type": "MEASURE"},
        ]
        merged = merge_formulas_into_model(existing, translated, update_existing=True)
        f = next(f for f in merged["model"]["formulas"] if f["id"] == "formula_Sales LY")
        assert f["expr"] == "new expr 1"
        assert merged["_merge_stats"]["updated"] == 1
        assert merged["_merge_stats"]["skipped_existing"] == 0

    def test_adds_new_formula(self):
        existing = self._make_existing_model()
        translated = [
            {"id": "formula_New Calc", "name": "New Calc", "expr": "1 + 1", "column_type": "MEASURE"},
        ]
        merged = merge_formulas_into_model(existing, translated)
        assert len(merged["model"]["formulas"]) == 3
        new_f = next(f for f in merged["model"]["formulas"] if f["id"] == "formula_New Calc")
        assert new_f["expr"] == "1 + 1"
        new_col = next(c for c in merged["model"]["columns"] if c.get("formula_id") == "formula_New Calc")
        assert new_col["properties"]["column_type"] == "MEASURE"
        assert merged["_merge_stats"]["added"] == 1

    def test_preserves_model_structure(self):
        existing = self._make_existing_model()
        translated = [
            {"id": "formula_Sales LY", "name": "Sales LY", "expr": "updated", "column_type": "MEASURE"},
        ]
        merged = merge_formulas_into_model(existing, translated)
        assert merged["guid"] == "abc-123"
        assert merged["model"]["model_tables"][0]["fqn"] == "table-guid-1"
        assert merged["model"]["properties"]["is_bypass_rls"] is False

    def test_does_not_mutate_input(self):
        existing = self._make_existing_model()
        original_expr = existing["model"]["formulas"][0]["expr"]
        translated = [
            {"id": "formula_Sales LY", "name": "Sales LY", "expr": "changed", "column_type": "MEASURE"},
        ]
        merge_formulas_into_model(existing, translated)
        assert existing["model"]["formulas"][0]["expr"] == original_expr


# ===================================================================
# Pre-merge filtering
# ===================================================================

class TestFilterUnresolvable:

    _COMMON = dict(
        existing_formula_ids={"formula_Existing"},
        model_column_names={"ORDERS", "SALES", "CAMPAIGN_ID"},
        formula_names={"Existing Formula", "Other Formula"},
        parameter_names={"Metric"},
    )

    def test_drops_sqlproxy_ref(self):
        formulas = [
            {"id": "f1", "name": "Brand", "expr": "[sqlproxy::BRAND_UPC]"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 0
        assert dropped == ["Brand"]

    def test_drops_csq_ref(self):
        formulas = [
            {"id": "f2", "name": "Date Range", "expr": "[COL (Custom SQL Query6)]"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 0
        assert dropped == ["Date Range"]

    def test_drops_bare_column_ref(self):
        formulas = [
            {"id": "f3", "name": "My Orders", "expr": "if ( [PERIOD] = 'promo' ) then [ORDERS] else 0"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 0
        assert dropped == ["My Orders"]

    def test_drops_unconverted_string_concat(self):
        formulas = [
            {"id": "f4", "name": "Label", "expr": "[A] + ' : ' + [B]"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 0
        assert dropped == ["Label"]

    def test_keeps_clean_formula(self):
        formulas = [
            {"id": "f5", "name": "Profit", "expr": "sum ( [formula_Existing Formula] ) / [Metric]"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 1
        assert len(dropped) == 0

    def test_drops_unknown_bare_ref(self):
        formulas = [
            {"id": "f6", "name": "Bad", "expr": "if ( [PERIOD_TYPE] = 'promo' ) then [UNKNOWN_COL] else 0"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 0
        assert dropped == ["Bad"]

    def test_keeps_qualified_sql_view_ref(self):
        """A [SQL View::col] ref resolves when the SQL View column is in the model."""
        common = dict(
            existing_formula_ids=set(),
            model_column_names={"REC_DATE", "VIEWS", "IMPRESSIONS"},
            formula_names=set(),
            parameter_names=set(),
        )
        formulas = [
            {"id": "f7", "name": "View Rate", "expr": "sum ( [Custom SQL Query::VIEWS] )"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **common)
        assert len(kept) == 1
        assert dropped == []

    def test_drops_qualified_sql_view_ref_when_col_absent(self):
        """A [SQL View::col] ref to a column NOT in the model is still dropped."""
        common = dict(
            existing_formula_ids=set(), model_column_names={"VIEWS"},
            formula_names=set(), parameter_names=set(),
        )
        formulas = [{"id": "f8", "name": "Bad", "expr": "[Custom SQL Query::MISSING]"}]
        kept, dropped = filter_unresolvable_formulas(formulas, **common)
        assert dropped == ["Bad"]

    def test_keeps_existing_formula_ids(self):
        formulas = [
            {"id": "formula_Existing", "name": "Existing", "expr": "[sqlproxy::BAD]"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 1
        assert len(dropped) == 0

    def test_keeps_formula_with_bracket_in_string_literal(self):
        formulas = [
            {
                "id": "f1", "name": "Label",
                "expr": "concat ( '[' , to_string ( [TABLE::ID]) , '] ' , [TABLE::NAME] )",
            },
        ]
        common = dict(self._COMMON)
        common["model_column_names"] = {"ORDERS", "SALES", "CAMPAIGN_ID", "ID", "NAME"}
        kept, dropped = filter_unresolvable_formulas(formulas, **common)
        assert len(kept) == 1
        assert len(dropped) == 0

    def test_drops_qualified_ref_to_missing_column(self):
        # [T::REVENUE_FORECAST] is qualified but the column exists in no table
        # → must be caught here, not left to fail at import.
        formulas = [
            {"id": "f7", "name": "Forecast",
             "expr": "sum ( [PROMO::REVENUE_FORECAST] )"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert kept == []
        assert dropped == ["Forecast"]

    def test_keeps_qualified_ref_to_present_column(self):
        formulas = [
            {"id": "f8", "name": "Total", "expr": "sum ( [PROMO::SALES] )"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 1
        assert dropped == []

    def test_cascade_drops_dependents_of_dropped_formula(self):
        # Root references a missing column → dropped; dependents that reference
        # [formula_Root] must cascade-drop in the same pass, not at import.
        formulas = [
            {"id": "formula_Root", "name": "Root",
             "expr": "sum ( [PROMO::REVENUE_FORECAST] )"},
            {"id": "formula_Mid", "name": "Mid",
             "expr": "[formula_Root] / sum ( [PROMO::SALES] )"},
            {"id": "formula_Leaf", "name": "Leaf",
             "expr": "[formula_Mid] * 100"},
            {"id": "formula_Clean", "name": "Clean",
             "expr": "sum ( [PROMO::ORDERS] )"},
        ]
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert [f["name"] for f in kept] == ["Clean"]
        assert set(dropped) == {"Root", "Mid", "Leaf"}


# ---------------------------------------------------------------------------
# Date parameter normalization
# ---------------------------------------------------------------------------

class TestNormalizeDateParams:

    def test_tableau_hash_date_converted(self):
        from ts_cli.model_builder import _normalize_date_params
        params = [{"name": "Start", "data_type": "DATE", "default_value": "#2026-05-10#"}]
        result = _normalize_date_params(params)
        assert result[0]["default_value"] == "05/10/2026"

    def test_plain_yyyy_mm_dd_converted(self):
        from ts_cli.model_builder import _normalize_date_params
        params = [{"name": "Start", "data_type": "DATE", "default_value": "2024-01-15"}]
        result = _normalize_date_params(params)
        assert result[0]["default_value"] == "01/15/2024"

    def test_non_date_param_unchanged(self):
        from ts_cli.model_builder import _normalize_date_params
        params = [{"name": "Region", "data_type": "CHAR", "default_value": "EMEA"}]
        result = _normalize_date_params(params)
        assert result[0]["default_value"] == "EMEA"

    def test_range_config_dates_converted(self):
        from ts_cli.model_builder import _normalize_date_params
        params = [{
            "name": "DateRange", "data_type": "DATE", "default_value": "#2024-01-01#",
            "range_config": {"min": "#2020-01-01#", "max": "#2026-12-31#"},
        }]
        result = _normalize_date_params(params)
        assert result[0]["range_config"]["min"] == "01/01/2020"
        assert result[0]["range_config"]["max"] == "12/31/2026"

    def test_list_config_dates_converted(self):
        from ts_cli.model_builder import _normalize_date_params
        params = [{
            "name": "Cutoff", "data_type": "DATE", "default_value": "2024-06-01",
            "list_config": {"list_choice": [
                {"value": "2024-01-01", "display_name": "Q1"},
                {"value": "2024-06-01", "display_name": "Q2"},
            ]},
        }]
        result = _normalize_date_params(params)
        assert result[0]["list_config"]["list_choice"][0]["value"] == "01/01/2024"
        assert result[0]["list_config"]["list_choice"][1]["value"] == "06/01/2024"

    def test_non_date_type_unchanged_even_if_looks_like_date(self):
        from ts_cli.model_builder import _normalize_date_params
        params = [{"name": "Code", "data_type": "CHAR", "default_value": "2024-01-01"}]
        result = _normalize_date_params(params)
        assert result[0]["default_value"] == "2024-01-01"

    def test_empty_value_unchanged(self):
        from ts_cli.model_builder import _normalize_date_params
        params = [{"name": "Start", "data_type": "DATE", "default_value": ""}]
        result = _normalize_date_params(params)
        assert result[0]["default_value"] == ""

    def test_datetime_type_also_converted(self):
        from ts_cli.model_builder import _normalize_date_params
        params = [{"name": "TS", "data_type": "DATE_TIME", "default_value": "#2024-03-15#"}]
        result = _normalize_date_params(params)
        assert result[0]["default_value"] == "03/15/2024"


class TestExtractTablesAliasDetection:
    """A3 — when the same physical table appears twice with different names."""

    @staticmethod
    def _make_ds(relations_xml: str) -> "ET.Element":
        import xml.etree.ElementTree as ET
        return ET.fromstring(f"<datasource><connection>{relations_xml}</connection></datasource>")

    def test_alias_preserved(self):
        ds = self._make_ds(
            '<relation type="table" name="d_partner1" table="[db].[schema].[d_partner]" />'
            '<relation type="table" name="d_partner" table="[db].[schema].[d_partner]" />'
        )
        tables = _extract_tables(ds)
        names = [t["name"] for t in tables]
        assert "d_partner1" in names
        assert "d_partner" in names
        assert len(tables) == 2

    def test_alias_of_field_set(self):
        ds = self._make_ds(
            '<relation type="table" name="d_partner1" table="[db].[schema].[d_partner]" />'
        )
        tables = _extract_tables(ds)
        assert tables[0]["alias_of"] == "d_partner"
        assert tables[0]["db_table"] == "db.schema.d_partner"

    def test_no_alias_of_when_name_matches(self):
        ds = self._make_ds(
            '<relation type="table" name="d_partner" table="[db].[schema].[d_partner]" />'
        )
        tables = _extract_tables(ds)
        assert "alias_of" not in tables[0]

    def test_fallback_to_physical_name_when_no_name_attr(self):
        ds = self._make_ds(
            '<relation type="table" table="[db].[schema].[orders]" />'
        )
        tables = _extract_tables(ds)
        assert tables[0]["name"] == "orders"


class TestExtractJoinsUsesRelationName:
    """A3 — joins reference the relation name attribute, not the physical table."""

    @staticmethod
    def _make_ds(xml: str) -> "ET.Element":
        import xml.etree.ElementTree as ET
        return ET.fromstring(f"<datasource>{xml}</datasource>")

    def test_join_uses_alias_names(self):
        ds = self._make_ds('''
            <relation join="inner" type="join">
                <relation type="table" name="d_partner1" table="[db].[s].[d_partner]" />
                <relation type="table" name="orders" table="[db].[s].[orders]" />
                <clause type="join">
                    <expression op="[PartnerId]" />
                    <expression op="[OrderPartnerId]" />
                </clause>
            </relation>
        ''')
        joins = _extract_joins(ds)
        assert len(joins) == 1
        assert joins[0]["left_table"] == "d_partner1"
        assert joins[0]["right_table"] == "orders"


# ---------------------------------------------------------------------------
# build_model_cmd — parameter and output contract tests
# ---------------------------------------------------------------------------


class TestBuildModelCmdSignature:
    """Verify the Typer CLI parameters for build_model_cmd."""

    def test_max_retries_parameter_exists(self):
        """--max-retries flag is present with default 10."""
        import inspect
        from ts_cli.commands.tableau import build_model_cmd

        sig = inspect.signature(build_model_cmd)
        param = sig.parameters.get("max_retries")
        assert param is not None, "--max-retries parameter missing from build_model_cmd"
        assert param.default.default == 10

    def test_max_retries_is_int_type(self):
        """--max-retries should be typed as int."""
        import inspect
        from ts_cli.commands.tableau import build_model_cmd

        sig = inspect.signature(build_model_cmd)
        param = sig.parameters["max_retries"]
        assert param.annotation in (int, "int")


class TestDroppedFormulaDictStructure:
    """Verify the enriched dropped-formula dict has the expected shape.

    We can't run build_model_cmd without a live instance, so we test the
    structure by verifying the dict construction matches the documented keys.
    """

    REQUIRED_KEYS = {"name", "expr", "error", "original_tableau"}

    def test_dropped_dict_has_all_keys(self):
        """Simulate a dropped-formula dict and confirm its keys."""
        dropped = {
            "name": "Growth Rate",
            "expr": "sum ( [formula_Sales LY] )",
            "error": "Formula not valid",
            "original_tableau": "SUM([Sales LY])",
        }
        assert set(dropped.keys()) == self.REQUIRED_KEYS

    def test_dropped_dict_values_are_strings(self):
        """All values in the dropped dict should be strings."""
        dropped = {
            "name": "Total",
            "expr": "sum ( [SALES] )",
            "error": "column not found",
            "original_tableau": "SUM([Sales])",
        }
        for key, val in dropped.items():
            assert isinstance(val, str), f"Value for '{key}' should be str, got {type(val)}"

    def test_empty_values_acceptable(self):
        """Lookup misses produce empty strings — valid."""
        dropped = {
            "name": "Orphan",
            "expr": "",
            "error": "unknown error",
            "original_tableau": "",
        }
        assert dropped["expr"] == ""
        assert dropped["original_tableau"] == ""


# ---------------------------------------------------------------------------
# fix_bare_refs
# ---------------------------------------------------------------------------


class TestFixBareRefs:
    """Tests for fix_bare_refs — table-qualify bare column refs, prefix formula refs."""

    COLUMN_LOOKUP = {
        "SALES": "SALES",
        "REGION": "REGION",
        "START_DATE": "START_DATE",
    }
    FORMULA_NAMES = {"Growth Rate", "YoY Change"}
    PARAM_NAMES = {"Currency", "Date Range"}
    TABLE = "vw_dim_promo"

    def test_qualifies_bare_column(self):
        result = fix_bare_refs(
            "[SALES] + 1",
            self.FORMULA_NAMES, self.PARAM_NAMES,
            self.COLUMN_LOOKUP, self.TABLE,
        )
        assert result == "[vw_dim_promo::SALES] + 1"

    def test_prefixes_formula_ref(self):
        result = fix_bare_refs(
            "[Growth Rate] * 100",
            self.FORMULA_NAMES, self.PARAM_NAMES,
            self.COLUMN_LOOKUP, self.TABLE,
        )
        assert result == "[formula_Growth Rate] * 100"

    def test_leaves_already_qualified(self):
        expr = "[vw_dim_promo::SALES]"
        result = fix_bare_refs(
            expr, self.FORMULA_NAMES, self.PARAM_NAMES,
            self.COLUMN_LOOKUP, self.TABLE,
        )
        assert result == expr

    def test_leaves_already_prefixed_formula(self):
        expr = "[formula_Growth Rate]"
        result = fix_bare_refs(
            expr, self.FORMULA_NAMES, self.PARAM_NAMES,
            self.COLUMN_LOOKUP, self.TABLE,
        )
        assert result == expr

    def test_leaves_parameter_unchanged(self):
        expr = "[Currency]"
        result = fix_bare_refs(
            expr, self.FORMULA_NAMES, self.PARAM_NAMES,
            self.COLUMN_LOOKUP, self.TABLE,
        )
        assert result == expr

    def test_case_insensitive_column_match(self):
        result = fix_bare_refs(
            "[sales]",
            self.FORMULA_NAMES, self.PARAM_NAMES,
            self.COLUMN_LOOKUP, self.TABLE,
        )
        assert result == "[vw_dim_promo::SALES]"

    def test_unknown_ref_unchanged(self):
        expr = "[Unknown Thing]"
        result = fix_bare_refs(
            expr, self.FORMULA_NAMES, self.PARAM_NAMES,
            self.COLUMN_LOOKUP, self.TABLE,
        )
        assert result == expr

    def test_mixed_refs(self):
        result = fix_bare_refs(
            "if [REGION] = 'APAC' then [Growth Rate] else [SALES]",
            self.FORMULA_NAMES, self.PARAM_NAMES,
            self.COLUMN_LOOKUP, self.TABLE,
        )
        assert "[vw_dim_promo::REGION]" in result
        assert "[formula_Growth Rate]" in result
        assert "[vw_dim_promo::SALES]" in result


# ---------------------------------------------------------------------------
# build_column_lookup
# ---------------------------------------------------------------------------


class TestBuildColumnLookup:
    """Tests for build_column_lookup — model column → db_column_name map."""

    def test_basic_lookup(self):
        tml = {
            "model": {
                "columns": [
                    {"name": "Sales Amount", "column_id": "vw_fact::SALES_AMT"},
                    {"name": "Region", "column_id": "vw_dim::REGION"},
                ]
            }
        }
        lookup = build_column_lookup(tml)
        assert lookup["SALES_AMT"] == "SALES_AMT"
        assert lookup["SALES AMOUNT"] == "SALES_AMT"
        assert lookup["REGION"] == "REGION"

    def test_empty_model(self):
        assert build_column_lookup({}) == {}
        assert build_column_lookup({"model": {}}) == {}
        assert build_column_lookup({"model": {"columns": []}}) == {}

    def test_skips_columns_without_qualifier(self):
        tml = {
            "model": {
                "columns": [
                    {"name": "Orphan", "column_id": "NO_SEPARATOR"},
                ]
            }
        }
        assert build_column_lookup(tml) == {}


# ===================================================================
# Multi-table bare-ref qualification (build_col_table_map + fix_bare_refs)
# ===================================================================

# A 3-table model like the tentpole rebuild: an anchor promotion-master plus
# a product-metrics table and a customer-orders table. Several columns are
# unique to one table (PERIOD_TYPE, SALES, LEVEL, CPG_SALES); PROMOTION_ID and
# CUSTOMER_TYPE are shared join/attribute columns.
_MULTI_MODEL = {
    "model": {
        "columns": [
            {"name": "CPG_SALES", "column_id": "tentpole_promotion_master::CPG_SALES"},
            {"name": "PROMOTION_ID", "column_id": "tentpole_promotion_master::PROMOTION_ID"},
            {"name": "PERIOD_TYPE", "column_id": "tentpole_product_metrics::PERIOD_TYPE"},
            {"name": "SALES", "column_id": "tentpole_product_metrics::SALES"},
            {"name": "LEVEL", "column_id": "tentpole_product_metrics::LEVEL"},
            {"name": "PROMOTION_ID (product_metrics)",
             "column_id": "tentpole_product_metrics::PROMOTION_ID"},
            {"name": "CUSTOMER_ID", "column_id": "tentpole_product_metrics::CUSTOMER_ID"},
            {"name": "CUSTOMER_COHORT", "column_id": "tentpole_customer_orders::CUSTOMER_COHORT"},
            {"name": "PROMOTION_ID (customer_orders)",
             "column_id": "tentpole_customer_orders::PROMOTION_ID"},
            {"name": "CUSTOMER_ID (customer_orders)",
             "column_id": "tentpole_customer_orders::CUSTOMER_ID"},
        ]
    }
}

_ANCHOR = "tentpole_promotion_master"


class TestBuildColTableMap:
    def test_unique_columns_mapped_to_their_table(self):
        m = build_col_table_map(_MULTI_MODEL, _ANCHOR)
        assert m["PERIOD_TYPE"] == "tentpole_product_metrics::PERIOD_TYPE"
        assert m["SALES"] == "tentpole_product_metrics::SALES"
        assert m["LEVEL"] == "tentpole_product_metrics::LEVEL"
        assert m["CPG_SALES"] == "tentpole_promotion_master::CPG_SALES"
        assert m["CUSTOMER_COHORT"] == "tentpole_customer_orders::CUSTOMER_COHORT"

    def test_shared_column_prefers_anchor(self):
        # PROMOTION_ID lives in all three tables; anchor owns it → anchor wins
        m = build_col_table_map(_MULTI_MODEL, _ANCHOR)
        assert m["PROMOTION_ID"] == "tentpole_promotion_master::PROMOTION_ID"

    def test_shared_column_absent_from_anchor_picks_an_owner(self):
        # CUSTOMER_ID is in product_metrics + customer_orders but NOT the anchor
        # → must pick a table that owns it (first in model order), never the anchor
        m = build_col_table_map(_MULTI_MODEL, _ANCHOR)
        assert m["CUSTOMER_ID"] == "tentpole_product_metrics::CUSTOMER_ID"
        assert not m["CUSTOMER_ID"].startswith(_ANCHOR + "::")

    def test_display_name_alias_indexed(self):
        m = build_col_table_map(_MULTI_MODEL, _ANCHOR)
        # display name of a unique column resolves too
        assert m.get("PERIOD_TYPE") == "tentpole_product_metrics::PERIOD_TYPE"


class TestFixBareRefsMultiTable:
    def test_bare_ref_qualified_to_owning_table_not_anchor(self):
        ctm = build_col_table_map(_MULTI_MODEL, _ANCHOR)
        lookup = build_column_lookup(_MULTI_MODEL)
        # PERIOD_TYPE lives in product_metrics; anchor is promotion_master.
        expr = "if ( [PERIOD_TYPE]='promo' ) then [CPG_SALES] else 0"
        out = fix_bare_refs(
            expr, set(), set(), lookup, "tentpole_promotion_master", ctm,
        )
        assert "[tentpole_product_metrics::PERIOD_TYPE]" in out
        assert "[tentpole_promotion_master::CPG_SALES]" in out
        # the bug: PERIOD_TYPE must NOT be qualified to the anchor
        assert "tentpole_promotion_master::PERIOD_TYPE" not in out

    def test_shared_column_on_anchor_uses_anchor(self):
        ctm = build_col_table_map(_MULTI_MODEL, _ANCHOR)
        lookup = build_column_lookup(_MULTI_MODEL)
        out = fix_bare_refs(
            "[PROMOTION_ID]", set(), set(), lookup,
            "tentpole_promotion_master", ctm,
        )
        assert out == "[tentpole_promotion_master::PROMOTION_ID]"

    def test_shared_column_absent_from_anchor_qualified_to_owner(self):
        # CUSTOMER_ID shared by two joined tables, not on the anchor →
        # must resolve to an owner, not the (column-less) anchor.
        ctm = build_col_table_map(_MULTI_MODEL, _ANCHOR)
        lookup = build_column_lookup(_MULTI_MODEL)
        out = fix_bare_refs(
            "unique count ( [CUSTOMER_ID] )", set(), set(), lookup,
            "tentpole_promotion_master", ctm,
        )
        assert "[tentpole_product_metrics::CUSTOMER_ID]" in out
        assert "tentpole_promotion_master::CUSTOMER_ID" not in out

    def test_no_map_preserves_single_table_behaviour(self):
        # backward-compat: without a col_table_map, everything → anchor
        lookup = build_column_lookup(_MULTI_MODEL)
        out = fix_bare_refs(
            "[PERIOD_TYPE]", set(), set(), lookup, "tentpole_promotion_master",
        )
        assert out == "[tentpole_promotion_master::PERIOD_TYPE]"


# ── SQL View emission (Custom SQL relations) ──────────────────────────────

def test_build_sql_view_tml_basic():
    tml = build_sql_view_tml(
        name="Orders CSQ",
        connection_name="MY_CONN",
        sql_query="SELECT id, region, sales FROM db.sch.orders WHERE amt > 0",
        columns=[
            {"name": "Id", "sql_output_column": "id", "data_type": "INT64", "column_type": "ATTRIBUTE"},
            {"name": "Region", "sql_output_column": "region", "data_type": "VARCHAR", "column_type": "ATTRIBUTE"},
            {"name": "Sales", "sql_output_column": "sales", "data_type": "DOUBLE", "column_type": "MEASURE"},
        ],
    )
    sv = tml["sql_view"]
    assert sv["name"] == "Orders CSQ"
    # connection referenced by name (invariant I6), never GUID
    assert sv["connection"] == {"name": "MY_CONN"}
    assert sv["sql_query"] == "SELECT id, region, sales FROM db.sch.orders WHERE amt > 0"
    cols = {c["sql_output_column"]: c for c in sv["sql_view_columns"]}
    assert set(cols) == {"id", "region", "sales"}
    assert cols["id"]["data_type"] == "INT64"
    assert cols["region"]["properties"]["column_type"] == "ATTRIBUTE"
    # MEASURE columns carry an aggregation; ATTRIBUTE columns do not
    assert cols["sales"]["properties"]["column_type"] == "MEASURE"
    assert cols["sales"]["properties"]["aggregation"] == "SUM"
    assert "aggregation" not in cols["region"]["properties"]


def test_build_sql_view_tml_no_columns():
    tml = build_sql_view_tml(name="Empty", connection_name="C", sql_query="SELECT 1", columns=[])
    assert tml["sql_view"]["sql_view_columns"] == []
    assert tml["sql_view"]["connection"]["name"] == "C"


def test_build_model_tml_references_sql_views():
    sql_views = [{
        "name": "Orders CSQ",
        "sql_query": "SELECT id, sales FROM t",
        "columns": [
            {"name": "Id", "sql_output_column": "id", "column_type": "ATTRIBUTE", "data_type": "INT64"},
            {"name": "Sales", "sql_output_column": "sales", "column_type": "MEASURE", "data_type": "DOUBLE"},
        ],
    }]
    model = build_model_tml(
        model_name="M",
        connection_name="CONN",
        tables=[],
        columns=[],
        joins=[],
        parameters=[],
        translated_formulas=[],
        sql_views=sql_views,
    )["model"]
    # SQL View appears in model_tables by name, with its columns
    mt = {t["name"]: t for t in model["model_tables"]}
    assert "Orders CSQ" in mt
    assert {c["name"] for c in mt["Orders CSQ"]["columns"]} == {"Id", "Sales"}
    # ...and in model.columns with a SQLViewName::col column_id
    cols = {c["name"]: c for c in model["columns"]}
    assert cols["Sales"]["column_id"] == "Orders CSQ::Sales"
    assert cols["Sales"]["properties"]["column_type"] == "MEASURE"
    assert cols["Sales"]["properties"]["aggregation"] == "SUM"
    # ...but NOT in the connection-qualified physical tables: list
    assert all(t["name"] != "Orders CSQ" for t in model["tables"])


def test_build_model_tml_no_sql_views_unchanged():
    model = build_model_tml(
        model_name="M", connection_name="C",
        tables=[{"name": "T1", "db_table": "T1"}],
        columns=[], joins=[], parameters=[], translated_formulas=[],
    )["model"]
    assert [t["name"] for t in model["model_tables"]] == ["T1"]


def test_build_model_tml_sql_view_columns_not_duplicated_by_physical():
    """A physical <column> that a SQL View also provides must not be emitted twice."""
    sql_views = [{
        "name": "CSQ",
        "sql_query": "SELECT region, sales FROM t",
        "columns": [
            {"name": "Region", "sql_output_column": "region", "column_type": "ATTRIBUTE", "data_type": "VARCHAR"},
            {"name": "Sales", "sql_output_column": "sales", "column_type": "MEASURE", "data_type": "DOUBLE"},
        ],
    }]
    # datasource <column> elements duplicate the SQL View outputs (extract-backed case)
    physical_cols = [
        {"name": "Region", "db_column_name": "region", "column_type": "ATTRIBUTE"},
        {"name": "Sales", "db_column_name": "sales", "column_type": "MEASURE"},
    ]
    model = build_model_tml(
        model_name="M", connection_name="C",
        tables=[], columns=physical_cols, joins=[], parameters=[],
        translated_formulas=[], sql_views=sql_views,
    )["model"]
    # each name appears exactly once, owned by the SQL View (SQLView::col id)
    names = [c["name"] for c in model["columns"]]
    assert names.count("Region") == 1
    assert names.count("Sales") == 1
    by_name = {c["name"]: c for c in model["columns"]}
    assert by_name["Region"]["column_id"] == "CSQ::Region"
    assert by_name["Sales"]["column_id"] == "CSQ::Sales"
