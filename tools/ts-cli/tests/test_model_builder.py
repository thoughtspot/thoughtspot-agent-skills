"""Tests for model_builder.py — model-level transforms for Tableau migration.

Uses real formulas from the CPG Merch Promotion Performance workbook to test
each of the 8 failure modes identified in the migration pipeline analysis.
"""
import pytest

from ts_cli.model_builder import (
    add_formula_prefix,
    build_formula_levels,
    build_model_tml,
    expr_is_aggregated,
    extract_parameters,
    filter_unresolvable_formulas,
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
        kept, dropped = filter_unresolvable_formulas(formulas, **self._COMMON)
        assert len(kept) == 1
        assert len(dropped) == 0
