"""Tests for ts_cli.sv_translate — Semantic View formula translation orchestrator.

Tests the orchestrator-level concerns: column classification, identifier
resolution with facts/metrics, semi-additive wrapping, window handling,
USING relationships. SQL-level function mapping is tested in test_sv_sql.py.
"""
from __future__ import annotations

import pytest

from ts_cli.sv_translate import (
    _find_over_split,
    _is_simple_agg,
    _parse_window_spec,
    _unwrap_agg,
    make_resolver,
    translate_sv_formulas,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal parsed SV structures
# ---------------------------------------------------------------------------

def _parsed_workforce():
    """Minimal parsed SV matching the COMPANY_WORKFORCE test fixture."""
    return {
        "view_name": "AGENT_SKILLS.TEST.COMPANY_WORKFORCE_SV",
        "database": "AGENT_SKILLS",
        "schema": "TEST",
        "name": "COMPANY_WORKFORCE_SV",
        "comment": "Company workforce analytics",
        "tables": [
            {"fqn": "AGENT_SKILLS.TEST.COMPANIES", "name": "COMPANIES",
             "alias": "companies", "primary_key": ["COMPANY_ID"],
             "comment": "Parent company master data",
             "synonyms": None, "sample_values": None, "is_enum": False,
             "subquery": None, "range_constraints": None},
            {"fqn": "AGENT_SKILLS.TEST.EMPLOYEES", "name": "EMPLOYEES",
             "alias": "employees", "primary_key": ["EMPLOYEE_ID"],
             "comment": "Employee records", "synonyms": None,
             "sample_values": None, "is_enum": False, "subquery": None,
             "range_constraints": None},
        ],
        "relationships": [
            {"name": "EMPLOYEES_TO_COMPANIES",
             "from_table": "EMPLOYEES", "from_column": "COMPANY_ID",
             "to_table": "COMPANIES", "to_column": "COMPANY_ID",
             "join_type": "equi"},
        ],
        "dimensions": [
            {"source_table": "COMPANIES", "source_column": "COMPANY_ID",
             "alias_table": "companies", "alias_name": "COMPANY_ID",
             "expr": None, "block": "dimensions",
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            {"source_table": "COMPANIES", "source_column": "COMPANY_NAME",
             "alias_table": "companies", "alias_name": "COMPANY_NAME",
             "expr": None, "block": "dimensions",
             "comment": "The registered company name",
             "synonyms": ["Company", "Organisation"],
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            {"source_table": "EMPLOYEES", "source_column": "DEPARTMENT",
             "alias_table": "employees", "alias_name": "DEPARTMENT",
             "expr": None, "block": "dimensions",
             "comment": "Department the employee belongs to",
             "synonyms": ["Team", "Division"],
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "facts": [
            {"source_table": "EMPLOYEES", "source_column": "TENURE_MONTHS",
             "alias_table": "employees", "alias_name": "tenure_months",
             "expr": "DATEDIFF(month, HIRE_DATE, CURRENT_DATE())",
             "block": "facts",
             "comment": "Months since hired", "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            {"source_table": "EMPLOYEES", "source_column": "SALARY_BAND",
             "alias_table": "employees", "alias_name": "salary_band",
             "expr": "CASE WHEN SALARY >= 90000 THEN 'Senior' "
                     "WHEN SALARY >= 70000 THEN 'Mid' ELSE 'Junior' END",
             "block": "facts",
             "comment": "Salary classification band", "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "metrics": [
            {"source_table": "EMPLOYEES", "source_column": "HEADCOUNT",
             "alias_table": "employees", "alias_name": "headcount",
             "expr": "COUNT(EMPLOYEE_ID)", "block": "metrics",
             "comment": "Total employees",
             "synonyms": ["Employee Count", "Staff Count"],
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            {"source_table": "EMPLOYEES", "source_column": "TOTAL_SALARY",
             "alias_table": "employees", "alias_name": "total_salary",
             "expr": "SUM(SALARY)", "block": "metrics",
             "comment": "Sum of salaries", "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            {"source_table": "EMPLOYEES", "source_column": "AVG_TENURE",
             "alias_table": "employees", "alias_name": "avg_tenure",
             "expr": "AVG(employees.tenure_months)", "block": "metrics",
             "comment": "Avg tenure in months", "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "custom_instructions": None,
        "verified_queries": [],
        "extension": None,
        "warnings": [],
        "unsupported": [],
    }


def _parsed_semi_additive():
    """Parsed SV with semi-additive metrics."""
    return {
        "view_name": "DB.S.STOCK_SV",
        "database": "DB", "schema": "S", "name": "STOCK_SV",
        "comment": None,
        "tables": [
            {"fqn": "DB.S.INVENTORY", "name": "INVENTORY",
             "alias": "inv", "primary_key": ["ID"],
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "subquery": None, "range_constraints": None},
        ],
        "relationships": [],
        "dimensions": [
            {"source_table": "INVENTORY", "source_column": "DATE",
             "alias_table": "inv", "alias_name": "DATE",
             "expr": None, "block": "dimensions",
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "facts": [],
        "metrics": [
            {"source_table": "INVENTORY", "source_column": "CLOSING_STOCK",
             "alias_table": "inv", "alias_name": "closing_stock",
             "expr": "SUM(inv.QUANTITY)",
             "block": "metrics",
             "semi_additive": {
                 "order_col": "INVENTORY.BALANCE_DATE",
                 "direction": "asc", "nulls": "last",
             },
             "comment": "Latest inventory", "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            {"source_table": "INVENTORY", "source_column": "OPENING_STOCK",
             "alias_table": "inv", "alias_name": "opening_stock",
             "expr": "SUM(inv.QUANTITY)",
             "block": "metrics",
             "semi_additive": {
                 "order_col": "INVENTORY.BALANCE_DATE",
                 "direction": "desc", "nulls": "last",
             },
             "comment": "Earliest inventory", "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "custom_instructions": None,
        "verified_queries": [],
        "extension": None,
        "warnings": [],
        "unsupported": [],
    }


def _parsed_window():
    """Parsed SV with a window/LOD metric."""
    return {
        "view_name": "DB.S.SALES_SV",
        "database": "DB", "schema": "S", "name": "SALES_SV",
        "comment": None,
        "tables": [
            {"fqn": "DB.S.ORDERS", "name": "ORDERS",
             "alias": "orders", "primary_key": ["ID"],
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "subquery": None, "range_constraints": None},
            {"fqn": "DB.S.REGIONS", "name": "REGIONS",
             "alias": "regions", "primary_key": ["REGION_ID"],
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "subquery": None, "range_constraints": None},
        ],
        "relationships": [],
        "dimensions": [],
        "facts": [],
        "metrics": [
            {"source_table": "ORDERS", "source_column": "REGIONAL_TOTAL",
             "alias_table": "orders", "alias_name": "regional_total",
             "expr": "SUM(orders.AMOUNT) OVER (PARTITION BY regions.REGION)",
             "block": "metrics",
             "comment": "Sum by region", "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            {"source_table": "ORDERS", "source_column": "GRAND_TOTAL",
             "alias_table": "orders", "alias_name": "grand_total",
             "expr": "SUM(orders.AMOUNT) OVER ()",
             "block": "metrics",
             "comment": "Grand total", "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "custom_instructions": None,
        "verified_queries": [],
        "extension": None,
        "warnings": [],
        "unsupported": [],
    }


def _parsed_using():
    """Parsed SV with a USING relationship metric."""
    return {
        "view_name": "DB.S.TEST_SV",
        "database": "DB", "schema": "S", "name": "TEST_SV",
        "comment": None,
        "tables": [
            {"fqn": "DB.S.A", "name": "A", "alias": "a",
             "primary_key": ["ID"], "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False, "subquery": None,
             "range_constraints": None},
            {"fqn": "DB.S.B", "name": "B", "alias": "b",
             "primary_key": ["ID"], "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False, "subquery": None,
             "range_constraints": None},
        ],
        "relationships": [
            {"name": "A_TO_B", "from_table": "A", "from_column": "FK",
             "to_table": "B", "to_column": "PK", "join_type": "equi"},
        ],
        "dimensions": [
            {"source_table": "A", "source_column": "ID",
             "alias_table": "a", "alias_name": "ID",
             "expr": None, "block": "dimensions",
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "facts": [],
        "metrics": [
            {"source_table": "A", "source_column": "TOTAL",
             "alias_table": "a", "alias_name": "total",
             "expr": "SUM(a.AMOUNT)",
             "using_relationship": "A_TO_B",
             "block": "metrics",
             "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "custom_instructions": None,
        "verified_queries": [],
        "extension": None,
        "warnings": [],
        "unsupported": [],
    }


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_is_simple_agg_sum(self):
        assert _is_simple_agg("SUM(SALARY)") == "SUM"

    def test_is_simple_agg_count(self):
        assert _is_simple_agg("COUNT(EMPLOYEE_ID)") == "COUNT"

    def test_is_simple_agg_avg(self):
        assert _is_simple_agg("AVG(emp.COL)") == "AVERAGE"

    def test_is_simple_agg_none_for_complex(self):
        assert _is_simple_agg("SUM(a.X) / COUNT(a.Y)") is None

    def test_is_simple_agg_none_for_none(self):
        assert _is_simple_agg(None) is None

    def test_is_simple_agg_none_for_nested(self):
        assert _is_simple_agg("SUM(CASE WHEN x THEN 1 END)") is None

    def test_unwrap_agg(self):
        fn, inner = _unwrap_agg("sum ( [T::X] )")
        assert fn == "sum"
        assert inner == "[T::X]"

    def test_unwrap_unique_count(self):
        fn, inner = _unwrap_agg("unique count ( [T::X] )")
        assert fn == "unique count"

    def test_find_over_split_present(self):
        pos = _find_over_split("SUM(a.X) OVER (PARTITION BY a.Y)")
        assert pos is not None
        assert pos == 9  # position of 'O' in OVER

    def test_find_over_split_absent(self):
        assert _find_over_split("SUM(a.X)") is None

    def test_find_over_in_string(self):
        assert _find_over_split("'OVER' = a.X") is None

    def test_find_over_nested(self):
        assert _find_over_split("SUM(IFF(a.X OVER 1, 0, 1))") is None

    def test_parse_window_spec_empty(self):
        spec = _parse_window_spec("")
        assert spec["partition_by"] == []
        assert spec["order_by"] == []
        assert spec["frame"] is None

    def test_parse_window_spec_partition(self):
        spec = _parse_window_spec("PARTITION BY region")
        assert spec["partition_by"] == ["region"]

    def test_parse_window_spec_order(self):
        spec = _parse_window_spec("ORDER BY date DESC")
        assert spec["order_by"] == [{"col": "date", "dir": "desc"}]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class TestResolver:
    def test_bare_ident(self):
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        assert resolver("SALARY") == "[EMPLOYEES::SALARY]"

    def test_qualified_physical(self):
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        assert resolver("companies.COMPANY_NAME") == \
            "[COMPANIES::COMPANY_NAME]"

    def test_fact_reference(self):
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        assert resolver("employees.tenure_months") == \
            "[formula_tenure_months]"

    def test_metric_reference(self):
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        assert resolver("employees.headcount") == "[formula_headcount]"

    def test_unknown_alias_raises(self):
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        with pytest.raises(Exception, match="unknown table alias"):
            resolver("nonexistent.COL")


# ---------------------------------------------------------------------------
# Full orchestrator — workforce fixture
# ---------------------------------------------------------------------------

class TestTranslateWorkforce:
    def test_stats(self):
        result = translate_sv_formulas(_parsed_workforce())
        assert result["stats"]["total"] == 8  # 3 dims + 2 facts + 3 metrics
        assert result["stats"]["skipped"] == 0

    def test_dimension_column(self):
        result = translate_sv_formulas(_parsed_workforce())
        dim = next(t for t in result["translated"]
                   if t["name"] == "COMPANY_ID")
        assert dim["role"] == "dimension"
        assert dim["output_kind"] == "column"
        assert dim["column_type"] == "ATTRIBUTE"
        assert dim["table"] == "COMPANIES"

    def test_dimension_with_metadata(self):
        result = translate_sv_formulas(_parsed_workforce())
        dim = next(t for t in result["translated"]
                   if t["name"] == "COMPANY_NAME")
        assert dim["comment"] == "The registered company name"
        assert dim["synonyms"] == ["Company", "Organisation"]

    def test_fact_formula(self):
        result = translate_sv_formulas(_parsed_workforce())
        fact = next(t for t in result["translated"]
                    if t["name"] == "TENURE_MONTHS")
        assert fact["role"] == "fact"
        assert fact["output_kind"] == "formula"
        assert "diff_months" in fact["ts_expr"]
        assert "today ( )" in fact["ts_expr"]

    def test_fact_case(self):
        result = translate_sv_formulas(_parsed_workforce())
        fact = next(t for t in result["translated"]
                    if t["name"] == "SALARY_BAND")
        assert "if (" in fact["ts_expr"]
        assert "'Senior'" in fact["ts_expr"]

    def test_simple_agg_metric_column(self):
        result = translate_sv_formulas(_parsed_workforce())
        metric = next(t for t in result["translated"]
                      if t["name"] == "HEADCOUNT")
        assert metric["role"] == "metric"
        assert metric["output_kind"] == "column"
        assert metric["column_type"] == "MEASURE"
        assert metric["aggregation"] == "COUNT"

    def test_simple_agg_metric_sum(self):
        result = translate_sv_formulas(_parsed_workforce())
        metric = next(t for t in result["translated"]
                      if t["name"] == "TOTAL_SALARY")
        assert metric["aggregation"] == "SUM"
        assert metric["table"] == "EMPLOYEES"
        assert metric["column"] == "SALARY"

    def test_metric_on_fact_formula(self):
        result = translate_sv_formulas(_parsed_workforce())
        metric = next(t for t in result["translated"]
                      if t["name"] == "AVG_TENURE")
        assert metric["output_kind"] == "formula"
        assert metric["column_type"] == "MEASURE"
        assert "[formula_tenure_months]" in metric["ts_expr"]
        assert "average" in metric["ts_expr"]


# ---------------------------------------------------------------------------
# Semi-additive metrics
# ---------------------------------------------------------------------------

class TestSemiAdditive:
    def test_asc_last_value(self):
        result = translate_sv_formulas(_parsed_semi_additive())
        m = next(t for t in result["translated"]
                 if t["name"] == "CLOSING_STOCK")
        assert "last_value" in m["ts_expr"]
        assert "query_groups" in m["ts_expr"]

    def test_desc_first_value(self):
        result = translate_sv_formulas(_parsed_semi_additive())
        m = next(t for t in result["translated"]
                 if t["name"] == "OPENING_STOCK")
        assert "first_value" in m["ts_expr"]


# ---------------------------------------------------------------------------
# Window / LOD metrics
# ---------------------------------------------------------------------------

class TestWindow:
    def test_partition_by(self):
        result = translate_sv_formulas(_parsed_window())
        m = next(t for t in result["translated"]
                 if t["name"] == "REGIONAL_TOTAL")
        assert "group_sum" in m["ts_expr"]
        assert "[REGIONS::REGION]" in m["ts_expr"]

    def test_empty_over(self):
        result = translate_sv_formulas(_parsed_window())
        m = next(t for t in result["translated"]
                 if t["name"] == "GRAND_TOTAL")
        assert "group_sum" in m["ts_expr"]
        assert "PARTITION" not in m["ts_expr"]


# ---------------------------------------------------------------------------
# USING relationship metrics
# ---------------------------------------------------------------------------

class TestUsing:
    def test_using_group_aggregate(self):
        result = translate_sv_formulas(_parsed_using())
        m = next(t for t in result["translated"]
                 if t["name"] == "TOTAL")
        assert "group_sum" in m["ts_expr"] or "group_aggregate" in m["ts_expr"]
        assert "B::PK" in m["ts_expr"]
        assert "query_filters" in m["ts_expr"]
