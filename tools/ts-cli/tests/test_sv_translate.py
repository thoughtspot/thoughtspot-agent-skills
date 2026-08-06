"""Tests for ts_cli.sv_translate — Semantic View formula translation orchestrator.

Tests the orchestrator-level concerns: column classification, identifier
resolution with facts/metrics, semi-additive wrapping, window handling,
USING relationships. SQL-level function mapping is tested in test_sv_sql.py.
"""
from __future__ import annotations

import pytest

from ts_cli.sv_parse import parse_sv_ddl
from ts_cli.sv_translate import (
    fact_column_type,
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


def _parsed_passthrough_fact():
    """Parsed SV with a passthrough fact and a computed fact on one table.

    The passthrough fact (`expr is None`) aliases a physical column; the computed
    fact is a genuine formula. BL-178 defect 1 hinges on the two resolving
    differently.
    """
    return {
        "view_name": "TPCDS.PUBLIC.PROBE", "database": "TPCDS",
        "schema": "PUBLIC", "name": "PROBE", "comment": None,
        "tables": [
            {"fqn": "TPCDS.PUBLIC.STORE_SALES", "name": "STORE_SALES",
             "alias": "store_sales", "primary_key": ["SS_ITEM_SK"],
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "subquery": None, "range_constraints": None},
        ],
        "relationships": [],
        "dimensions": [],
        "facts": [
            {"source_table": "STORE_SALES",
             "source_column": "ss_ext_sales_price",
             "alias_table": "store_sales",
             "alias_name": "ss_ext_sales_price",
             "expr": None, "block": "facts", "comment": None,
             "synonyms": None, "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            {"source_table": "STORE_SALES", "source_column": "net_line",
             "alias_table": "store_sales", "alias_name": "net_line",
             "expr": "store_sales.ss_ext_sales_price - 1",
             "block": "facts", "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False, "is_filter": False,
             "is_private": False, "cortex_search_service": None},
        ],
        "metrics": [],
        "custom_instructions": None, "verified_queries": [],
        "extension": None, "warnings": [], "unsupported": [],
    }


def _parsed_renamed_passthrough():
    """A RENAMED passthrough fact plus a non-renamed one, on one table.

    PR #424 review F1: `alias_name` is the physical column for a passthrough, so
    the construct was indexed ONLY under that column and a reference by its
    declared name (`store_sales.revenue`) missed both indexes.
    """
    def _f(declared, physical):
        return {"source_table": "STORE_SALES", "source_column": declared,
                "alias_table": "store_sales", "alias_name": physical,
                "expr": None, "block": "facts", "comment": None,
                "synonyms": None, "sample_values": None, "is_enum": False,
                "is_filter": False, "is_private": False,
                "cortex_search_service": None}
    return {
        "view_name": "T.P.RENAMED", "database": "T", "schema": "P",
        "name": "RENAMED", "comment": None,
        "tables": [
            {"fqn": "T.P.STORE_SALES", "name": "STORE_SALES",
             "alias": "store_sales", "primary_key": ["SS_ITEM_SK"],
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "subquery": None, "range_constraints": None},
        ],
        "relationships": [], "dimensions": [],
        "facts": [_f("revenue", "ss_ext_sales_price"),
                  _f("ss_net_profit", "ss_net_profit")],
        "metrics": [],
        "custom_instructions": None, "verified_queries": [],
        "extension": None, "warnings": [], "unsupported": [],
    }


def _parsed_degenerate_group():
    """Inner metric aggregates the very column the double-agg would group by.

    `group_count ( [COMPANIES::COMPANY_ID] , [COMPANIES::COMPANY_ID] )` is 1 for
    every group — silently wrong rather than loudly wrong (PR #424 review F6).
    """
    return {
        "view_name": "T.P.DEGEN", "database": "T", "schema": "P",
        "name": "DEGEN", "comment": None,
        "tables": [
            {"fqn": "T.P.COMPANIES", "name": "COMPANIES", "alias": "companies",
             "primary_key": ["COMPANY_ID"], "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False, "subquery": None,
             "range_constraints": None},
            {"fqn": "T.P.EMPLOYEES", "name": "EMPLOYEES", "alias": "employees",
             "primary_key": ["EMPLOYEE_ID"], "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False, "subquery": None,
             "range_constraints": None},
        ],
        "relationships": [
            {"name": "E_TO_C", "from_table": "EMPLOYEES",
             "from_column": "COMPANY_ID", "to_table": "COMPANIES",
             "to_column": "COMPANY_ID", "join_type": "equi"},
        ],
        "dimensions": [], "facts": [],
        "metrics": [
            # simple aggregate -> the `col_info` arm of the guard
            {"source_table": "COMPANIES", "source_column": "COMPANY_TALLY",
             "alias_table": "companies", "alias_name": "COMPANY_TALLY",
             "expr": "COUNT(companies.COMPANY_ID)", "block": "metrics",
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "is_filter": False, "is_private": False,
             "cortex_search_service": None},
            # NOT a simple aggregate (trailing arithmetic), so `col_info` is None
            # and only the full-`group_aggregate`-form arm of the guard can catch
            # it — the arm N3 flagged as untested.
            {"source_table": "COMPANIES", "source_column": "TALLY_SCALED",
             "alias_table": "companies", "alias_name": "TALLY_SCALED",
             "expr": "COUNT(companies.COMPANY_ID) * 1", "block": "metrics",
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "custom_instructions": None, "verified_queries": [],
        "extension": None, "warnings": [], "unsupported": [],
    }


def _parsed_dimension_shapes():
    """All three dimension shapes on one table, for resolution by declared name.

    PR #424 re-review N1: `_index_constructs` covered facts and metrics only, so a
    renamed DIMENSION referenced by its declared name fell through to
    assumed-physical and emitted a column that does not exist. Reproducible from
    ts-from-snowflake-dunder.md (`DM_CATEGORY.CATEGORY as dm_category.CATEGORY_NAME`
    referenced as `PARTITION BY dm_category.category`).
    """
    def _d(declared, physical, expr, synonyms=None):
        return {"source_table": "T", "source_column": declared,
                "alias_table": "t", "alias_name": physical, "expr": expr,
                "block": "dimensions", "comment": None, "synonyms": synonyms,
                "sample_values": None, "is_enum": False, "is_filter": False,
                "is_private": False, "cortex_search_service": None}
    return {
        "view_name": "D.P.V", "database": "D", "schema": "P", "name": "V",
        "comment": None,
        "tables": [
            {"fqn": "D.P.T", "name": "T", "alias": "t", "primary_key": ["ID"],
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "subquery": None, "range_constraints": None},
        ],
        "relationships": [],
        "dimensions": [
            # 1. renamed passthrough — declared name != physical column
            _d("CATEGORY", "CATEGORY_NAME", None),
            # 2. plain passthrough — the two names coincide
            _d("PLAIN", "PLAIN", None),
            # 3. bare-column rename — the physical column is the EXPRESSION
            _d("RENAMED_BARE", "RENAMED_BARE", "ID"),
            # 4. computed — becomes a formula, referenced by minted id
            _d("COMPUTED", "COMPUTED", "CONCAT(t.A, ', ', t.B)", ["Full Name"]),
        ],
        "facts": [], "metrics": [],
        "custom_instructions": None, "verified_queries": [],
        "extension": None, "warnings": [], "unsupported": [],
    }


def _parsed_same_table_ratio():
    """The BL-194 shape — a same-table ratio of two simple-aggregate metrics."""
    def _m(name, expr):
        return {"source_table": "ORDERS", "source_column": name,
                "alias_table": "orders", "alias_name": name, "expr": expr,
                "block": "metrics", "comment": None, "synonyms": None,
                "sample_values": None, "is_enum": False, "is_filter": False,
                "is_private": False, "cortex_search_service": None}
    return {
        "view_name": "T.P.ORD", "database": "T", "schema": "P", "name": "ORD",
        "comment": None,
        "tables": [
            {"fqn": "T.P.ORDERS", "name": "ORDERS", "alias": "orders",
             "primary_key": ["ID"], "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False, "subquery": None,
             "range_constraints": None},
        ],
        "relationships": [],
        "dimensions": [
            {"source_table": "ORDERS", "source_column": "ID",
             "alias_table": "orders", "alias_name": "ID", "expr": None,
             "block": "dimensions", "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False, "is_filter": False,
             "is_private": False, "cortex_search_service": None},
        ],
        "facts": [],
        "metrics": [_m("TOTAL_REV", "SUM(AMOUNT)"),
                    _m("ORDER_COUNT", "COUNT(QTY)"),
                    _m("AOV", "orders.TOTAL_REV / orders.ORDER_COUNT")],
        "custom_instructions": None, "verified_queries": [],
        "extension": None, "warnings": [], "unsupported": [],
    }


def _parsed_passthrough_metric():
    """A metric whose right-hand side is a bare physical column (`expr is None`).

    PR #424 review F8: `_translate_metric` had no expr-is-None branch, so this
    crashed with a raw `AttributeError: 'NoneType' object has no attribute
    'strip'` instead of being skipped with a reason.
    """
    return {
        "view_name": "T.P.PT", "database": "T", "schema": "P", "name": "PT",
        "comment": None,
        "tables": [
            {"fqn": "T.P.ORDERS", "name": "ORDERS", "alias": "orders",
             "primary_key": ["ID"], "comment": None, "synonyms": None,
             "sample_values": None, "is_enum": False, "subquery": None,
             "range_constraints": None},
        ],
        "relationships": [], "dimensions": [], "facts": [],
        "metrics": [
            {"source_table": "ORDERS", "source_column": "amt",
             "alias_table": "orders", "alias_name": "AMOUNT",
             "expr": None, "block": "metrics", "comment": None,
             "synonyms": None, "sample_values": None, "is_enum": False,
             "is_filter": False, "is_private": False,
             "cortex_search_service": None},
        ],
        "custom_instructions": None, "verified_queries": [],
        "extension": None, "warnings": [], "unsupported": [],
    }


def _parsed_cyclic_metrics():
    """Two related tables whose metrics reference each other (invalid SV, but a
    hand-written DDL can express it). Guards step 3's nested resolver."""
    def _m(table, name, expr):
        return {"source_table": table.upper(), "source_column": name,
                "alias_table": table, "alias_name": name, "expr": expr,
                "block": "metrics", "comment": None, "synonyms": None,
                "sample_values": None, "is_enum": False, "is_filter": False,
                "is_private": False, "cortex_search_service": None}
    return {
        "view_name": "DB.S.CYCLE", "database": "DB", "schema": "S",
        "name": "CYCLE", "comment": None,
        "tables": [
            {"fqn": "DB.S.A", "name": "A", "alias": "a", "primary_key": ["A_ID"],
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "subquery": None, "range_constraints": None},
            {"fqn": "DB.S.B", "name": "B", "alias": "b", "primary_key": ["B_ID"],
             "comment": None, "synonyms": None, "sample_values": None,
             "is_enum": False, "subquery": None, "range_constraints": None},
        ],
        "relationships": [
            {"name": "B_TO_A", "from_table": "B", "from_column": "A_ID",
             "to_table": "A", "to_column": "A_ID", "join_type": "equi"},
        ],
        "dimensions": [], "facts": [],
        "metrics": [_m("a", "M_A", "SUM(b.M_B)"), _m("b", "M_B", "SUM(a.M_A)")],
        "custom_instructions": None, "verified_queries": [],
        "extension": None, "warnings": [], "unsupported": [],
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
        # BL-178 defect 2: the reference must be the `id` build-model mints —
        # `formula_<display title>` — not `formula_<sql token>`. Ground truth:
        # ts-from-snowflake-identifier-resolution.md:233.
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        assert resolver("employees.tenure_months") == \
            "[formula_Tenure Months]"

    def test_metric_reference(self):
        """Same-table metric-on-metric falls back to the inner metric's formula id.

        NOT an endorsement of the fallback — it pins current behaviour, and the
        behaviour is only half-right. The id is correct (that is BL-178 defect 2,
        fixed), but the reference resolves **only if the inner metric becomes a
        `formulas[]` entry**. A same-table reference to a *simple aggregate*
        (`SUM(col)`) resolves to a `columns[]` entry with an `aggregation:`, which
        has no formula id, so the reference dangles and I13 correctly fails the
        build. HEADCOUNT survives here only because `promote_duplicate_column_ids`
        promotes it (the Employee Id dimension claims the column_id first). The
        real fix is to inline the inner aggregation — **BL-194**.
        """
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        # BL-179: the declared name wins by default; the synonym
        # ('Employee Count') is an alternate NL name, not the identifier.
        assert resolver("employees.headcount") == "[formula_Headcount]"
        promoted = make_resolver(parsed, "employees", promote_synonym=True)
        assert promoted("employees.headcount") == "[formula_Employee Count]"

    def test_same_table_ratio_of_simple_aggs_fails_the_lint_gate(self):
        """The BL-194 shape, pinned so the limitation is visible in the suite.

        A same-table ratio of two simple-aggregate metrics dangles. This asserts
        the CURRENT (loud-failure) behaviour on purpose: when BL-194 lands this
        test must be replaced by one asserting the inlined expression, not
        deleted quietly.
        """
        from ts_cli.sv_build_model import build_model_tml_sv
        from ts_cli.tml_lint import lint_tml
        parsed = _parsed_same_table_ratio()
        translated = translate_sv_formulas(parsed)
        doc, _ = build_model_tml_sv(
            model_name="Orders", parsed=parsed, translated_doc=translated,
            tables={"ORDERS": {"name": "ORDERS", "fqn": "g"}})
        findings = [f for f in lint_tml(doc) if f.startswith("I13:")]
        # BOTH referents are simple aggregates on unique columns, so both stay
        # `columns[]` entries and both references dangle.
        assert len(findings) == 2
        assert any("formula_Total Rev" in f for f in findings)
        assert any("formula_Order Count" in f for f in findings)

    def test_passthrough_fact_resolves_to_physical_column(self):
        """BL-178 defect 1 — documented resolution order is physical-column-first.

        A fact whose expression IS a physical column (`expr` is None) aliases
        that column: step 1 of ts-from-snowflake-rules.md:585-593 applies and the
        reference must be `[TABLE::col]`. The pre-fix code checked the fact index
        first and emitted a formula id for a construct build-model emits as a
        plain `columns[]` entry — every TPC-DS measure dangled as a result.
        """
        parsed = _parsed_passthrough_fact()
        resolver = make_resolver(parsed, "store_sales")
        assert resolver("store_sales.ss_ext_sales_price") == \
            "[STORE_SALES::ss_ext_sales_price]"

    def test_computed_fact_still_resolves_to_formula_id(self):
        # The counterpart to the test above: only a *passthrough* fact takes
        # step 1. A computed fact is a formula and keeps step 2.
        parsed = _parsed_passthrough_fact()
        resolver = make_resolver(parsed, "store_sales")
        assert resolver("store_sales.net_line") == "[formula_Net Line]"

    def test_cyclic_metric_reference_terminates(self):
        """A cyclic SV must not recurse forever in step 3's nested resolver.

        Step 3 builds a resolver for the inner metric's own expression, so
        A-over-B-over-A would recurse without the `_resolving` guard. The guard
        bounds the nesting and breaks the cycle into a formula-id reference — a
        wrong answer for invalid input, never a crash, and never a dangling ref.
        """
        parsed = _parsed_cyclic_metrics()
        resolver = make_resolver(parsed, "a")
        out = resolver("b.M_B")            # terminates
        assert "[formula_M B]" in out      # the cycle broke into an id ref
        assert out.count("group_aggregate") == 2  # bounded, not runaway
        # the whole translate pass completes rather than raising RecursionError
        assert translate_sv_formulas(parsed)["stats"]["translated"] == 2

    def test_metric_on_metric_across_relationship_double_aggregates(self):
        """Step 3 — a metric reference across a relationship becomes `group_*`.

        Ground truth: ts-from-snowflake-rules.md "Double Aggregation
        (Metric-on-Metric)" and ts-from-snowflake-identifier-resolution.md:244.
        The grouping key is the PK on the parent (TO) side.
        """
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "companies")
        assert resolver("employees.headcount") == (
            "group_count ( [EMPLOYEES::EMPLOYEE_ID] , [COMPANIES::COMPANY_ID] )")

    def test_double_aggregation_emits_the_review_marker(self):
        """ts-from-snowflake-rules.md "Double Aggregation (Metric-on-Metric)" / "Report line requirement" (:759-762) requires a 🔄 review marker on every
        double-aggregation formula — the grouping key and relationship direction
        have to be verified by hand (PR #424 review F5)."""
        parsed = _parsed_workforce()
        notes: list[str] = []
        resolver = make_resolver(parsed, "companies", annotations=notes)
        resolver("employees.headcount")
        assert any(n.startswith("🔄") for n in notes), notes
        assert any("EMPLOYEES_TO_COMPANIES" in n for n in notes), notes

    def test_degenerate_grouping_is_skipped_and_flagged(self):
        """Guard the case where the inner measure IS the grouping column.

        `group_count([COMPANIES::COMPANY_ID], [COMPANIES::COMPANY_ID])` counts 1
        per group — a plausible-looking formula with wrong numbers, which is worse
        than no formula. Skip the double-agg and say why (PR #424 review F6).
        """
        parsed = _parsed_degenerate_group()
        notes: list[str] = []
        resolver = make_resolver(parsed, "employees", annotations=notes)
        out = resolver("companies.company_tally")
        assert "group_count" not in out
        assert out == "[formula_Company Tally]"
        assert any("grouping column" in n for n in notes), notes

    def test_degenerate_grouping_full_form_arm_is_also_guarded(self):
        """The `group_aggregate` full-form arm of the F6 guard (N3).

        A non-simple inner expression takes the full form, where `col_info` is
        None and the shorthand arm cannot fire — so the guard has to re-check the
        translated expression's own references. Untested until now.
        """
        parsed = _parsed_degenerate_group()
        notes: list[str] = []
        resolver = make_resolver(parsed, "employees", annotations=notes)
        out = resolver("companies.tally_scaled")
        assert "group_aggregate" not in out
        assert out == "[formula_Tally Scaled]"
        assert any("reads only" in n and "grouping column" in n
                   for n in notes), notes

    def test_renamed_passthrough_resolves_by_declared_name(self):
        """PR #424 review F1 — index the construct under its DECLARED name too.

        `store_sales.revenue` is the only name the SV namespace gives the fact;
        resolving it as an assumed-physical column emitted
        `[STORE_SALES::revenue]`, a column that does not exist.
        """
        parsed = _parsed_renamed_passthrough()
        resolver = make_resolver(parsed, "store_sales")
        assert resolver("store_sales.revenue") == \
            "[STORE_SALES::ss_ext_sales_price]"

    def test_renamed_passthrough_still_resolves_by_physical_name(self):
        parsed = _parsed_renamed_passthrough()
        resolver = make_resolver(parsed, "store_sales")
        assert resolver("store_sales.ss_ext_sales_price") == \
            "[STORE_SALES::ss_ext_sales_price]"

    def test_renamed_passthrough_reference_is_flagged_not_silent(self):
        """The name-collision case must not silently aggregate another column.

        A renamed passthrough's declared name may ALSO be a real physical column
        on the same table — the resolver has no column inventory, so it cannot
        tell. It resolves to the construct (SV-namespace semantics) and annotates
        both candidates so the ambiguity reaches the translation log rather than
        the numbers.
        """
        parsed = _parsed_renamed_passthrough()
        notes: list[str] = []
        resolver = make_resolver(parsed, "store_sales", annotations=notes)
        resolver("store_sales.revenue")
        assert any("revenue" in n and "ss_ext_sales_price" in n for n in notes), \
            notes

    # --- dimensions: the same three-case resolution (N1) -------------------

    def test_renamed_dimension_resolves_by_declared_name(self):
        parsed = _parsed_dimension_shapes()
        notes: list[str] = []
        resolver = make_resolver(parsed, "t", annotations=notes)
        assert resolver("t.category") == "[T::CATEGORY_NAME]"
        assert any("CATEGORY_NAME" in n for n in notes), notes

    def test_renamed_dimension_resolves_by_physical_name_without_flag(self):
        parsed = _parsed_dimension_shapes()
        notes: list[str] = []
        resolver = make_resolver(parsed, "t", annotations=notes)
        assert resolver("t.CATEGORY_NAME") == "[T::CATEGORY_NAME]"
        assert notes == []

    def test_plain_passthrough_dimension_is_unchanged(self):
        parsed = _parsed_dimension_shapes()
        notes: list[str] = []
        resolver = make_resolver(parsed, "t", annotations=notes)
        assert resolver("t.PLAIN") == "[T::PLAIN]"
        assert notes == []

    def test_bare_column_rename_dimension_resolves_to_the_expression(self):
        # `T.RENAMED_BARE as ID` is emitted as a column on `ID`, not on
        # `RENAMED_BARE` — the physical column is the EXPRESSION here, not
        # `alias_name`, which is the declared name for this shape.
        parsed = _parsed_dimension_shapes()
        notes: list[str] = []
        resolver = make_resolver(parsed, "t", annotations=notes)
        assert resolver("t.renamed_bare") == "[T::ID]"
        assert any("ID" in n for n in notes), notes

    def test_computed_dimension_resolves_to_its_formula_id(self):
        # Previously `[T::computed]` — a column that does not exist, because a
        # computed dimension is a formula.
        parsed = _parsed_dimension_shapes()
        resolver = make_resolver(parsed, "t")
        assert resolver("t.computed") == "[formula_Computed]"
        promoted = make_resolver(parsed, "t", promote_synonym=True)
        assert promoted("t.computed") == "[formula_Full Name]"

    def test_unknown_name_on_a_table_with_dimensions_still_assumes_physical(self):
        # The assumed-physical fallback must survive — most references are to
        # columns no dimension block declares.
        parsed = _parsed_dimension_shapes()
        resolver = make_resolver(parsed, "t")
        assert resolver("t.SOME_OTHER_COL") == "[T::SOME_OTHER_COL]"

    def test_unrenamed_passthrough_reference_is_not_flagged(self):
        # No ambiguity when the declared name IS the physical column name.
        parsed = _parsed_renamed_passthrough()
        notes: list[str] = []
        resolver = make_resolver(parsed, "store_sales", annotations=notes)
        assert resolver("store_sales.ss_net_profit") == \
            "[STORE_SALES::ss_net_profit]"
        assert notes == []

    def test_unknown_alias_raises(self):
        parsed = _parsed_workforce()
        resolver = make_resolver(parsed, "employees")
        with pytest.raises(Exception, match="unknown table alias"):
            resolver("nonexistent.COL")

    def test_roleplay_alias_resolves_to_distinct_nodes(self):
        # One physical USER table played by two aliases must resolve to distinct
        # role-play nodes, not collapse onto the shared physical name.
        parsed = {"tables": [
            {"alias": "CASE", "name": "CASE"},
            {"alias": "OWNER", "name": "USER"},
            {"alias": "RESOLVED_BY", "name": "USER"},
        ]}
        resolver = make_resolver(parsed, "case")
        assert resolver("owner.NAME") == "[OWNER::NAME]"
        assert resolver("resolved_by.NAME") == "[RESOLVED_BY::NAME]"
        # single-use physical table keeps its physical name as the node id
        assert resolver("case.ID") == "[CASE::ID]"


# ---------------------------------------------------------------------------
# Full orchestrator — workforce fixture
# ---------------------------------------------------------------------------

class TestPassthroughMetric:
    """PR #424 review F8 — a metric whose RHS is a bare physical column."""

    def test_passthrough_metric_is_skipped_not_crashed(self):
        result = translate_sv_formulas(_parsed_passthrough_metric())
        assert result["stats"]["translated"] == 0
        assert result["stats"]["skipped"] == 1
        skip = result["skipped"][0]
        assert skip["name"] == "amt"
        assert skip["block"] == "metrics"
        # the reason has to name the shape, not leak a Python error string
        assert "no aggregate" in skip["reason"]
        assert "NoneType" not in skip["reason"]


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
        # BL-178 defect 2: the reference is the id build-model mints, so this
        # asserts the full expression rather than a substring — a wrong-token
        # reference passed the old substring check for five weeks.
        assert metric["ts_expr"] == "average ( [formula_Tenure Months] )"


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


class TestFactColumnType:
    """BL-181 — `_translate_fact` hardcoded ATTRIBUTE on both branches, so
    quantities, prices and profit were declared categorical. The SV's own
    `facts()` block is the signal: it holds row-level numeric values."""

    def _fact(self, expr):
        return {"source_table": "T", "source_column": "F", "alias_table": "t",
                "alias_name": "f", "expr": expr, "comment": None,
                "synonyms": [], "is_private": False}

    @pytest.mark.parametrize("expr", [
        None,                                   # passthrough physical column
        "t.amount",
        "t.qty * t.price",
        "t.revenue - t.cost",
        "t.a / t.b",
        "ABS(t.delta)",
        "ROUND(t.rate, 2)",
        "CASE WHEN t.flag THEN 1 ELSE 0 END",   # numeric CASE
    ])
    def test_numeric_facts_are_measures(self, expr):
        assert fact_column_type(self._fact(expr)) == "MEASURE"

    @pytest.mark.parametrize("expr", [
        "CONCAT(t.first, t.last)",
        "t.first || t.last",
        "TO_CHAR(t.d, 'YYYY')",
        "UPPER(t.code)",
        "SUBSTR(t.code, 1, 3)",
        "DATE_TRUNC(month, t.d)",
        "t.amount > 0",
        "t.status = 'X'",
        "CASE WHEN t.n > 1 THEN 'many' ELSE 'one' END",
    ])
    def test_non_numeric_facts_are_attributes(self, expr):
        assert fact_column_type(self._fact(expr)) == "ATTRIBUTE"

    def test_passthrough_fact_translates_as_a_measure_column(self):
        parsed = {"tables": [{"alias": "T", "name": "T", "primary_key": ["ID"]}],
                  "relationships": [], "dimensions": [], "metrics": [],
                  "facts": [self._fact(None)]}
        out = translate_sv_formulas(parsed)["translated"][0]
        assert out["output_kind"] == "column"
        assert out["column_type"] == "MEASURE"

    def test_string_fact_translates_as_an_attribute_formula(self):
        f = self._fact("CONCAT(t.a, t.b)")
        parsed = {"tables": [{"alias": "T", "name": "T", "primary_key": ["ID"]}],
                  "relationships": [], "dimensions": [], "metrics": [], "facts": [f]}
        out = translate_sv_formulas(parsed)["translated"][0]
        assert out["column_type"] == "ATTRIBUTE"


class TestTranslateRecordsNamingDecision:
    """The promotion decision is made once and recorded, so build-model reads
    it rather than being told a second time — two independent naming paths is
    the BL-178 defect-2 shape."""

    PARSED = {"tables": [{"alias": "T", "name": "T", "primary_key": ["ID"]}],
              "relationships": [], "facts": [], "metrics": [],
              "dimensions": [{"source_table": "T", "source_column": "STATUS",
                              "alias_table": "t", "alias_name": "status",
                              "expr": None, "comment": None,
                              "synonyms": ["State", "Condition"],
                              "is_private": False}]}

    def test_default_is_no_promotion(self):
        r = translate_sv_formulas(self.PARSED)
        assert r["options"]["promote_first_synonym"] is False
        assert r["translated"][0]["name"] == "STATUS"

    def test_opt_in_is_recorded(self):
        r = translate_sv_formulas(self.PARSED, promote_synonym=True)
        assert r["options"]["promote_first_synonym"] is True

    def test_synonyms_are_preserved_either_way(self):
        for flag in (False, True):
            r = translate_sv_formulas(self.PARSED, promote_synonym=flag)
            assert r["translated"][0]["synonyms"] == ["State", "Condition"]


# ---------------------------------------------------------------------------
# BL-213 — translating an unqualified derived metric
#
# A derived metric combines metrics that have already aggregated on their own
# entity, so each reference must point at what that metric is EMITTED as. The
# generic resolver always emits [formula_<id>], which DANGLES against a
# simple-agg metric (emitted as a plain column) — the BL-178 shape I13 rejects.
# ---------------------------------------------------------------------------

_D_DDL = """
create or replace semantic view SV_T
  tables ( F, T )
  relationships ( )
  dimensions ( F.PID as F.PRODUCT_ID )
  metrics (
    F.AMOUNT as SUM(F.LINE_TOTAL),
    F.AVG_ORDER_VALUE as DIV0(SUM(F.LINE_TOTAL), COUNT(DISTINCT F.OID)),
    T.TARGET_REVENUE as SUM(T.TARGET_AMOUNT),
    ATTAINMENT as F.AMOUNT / T.TARGET_REVENUE,
    RATIO_TO_FORMULA as F.AVG_ORDER_VALUE / T.TARGET_REVENUE
  );
"""


def _t(name: str) -> dict:
    out = translate_sv_formulas(parse_sv_ddl(_D_DDL))
    return next(e for e in out["translated"] if e["name"] == name)


class TestDerivedMetricTranslation:

    def test_nothing_skipped(self):
        assert translate_sv_formulas(parse_sv_ddl(_D_DDL))["skipped"] == []

    def test_emitted_as_a_measure_formula(self):
        e = _t("ATTAINMENT")
        assert e["output_kind"] == "formula" and e["column_type"] == "MEASURE"

    def test_simple_agg_reference_uses_the_column_display_name(self):
        # AMOUNT is SUM(col) -> a plain column, so [Amount], NOT [formula_Amount]
        assert _t("ATTAINMENT")["ts_expr"] == "[Amount] / [Target Revenue]"

    def test_computed_metric_reference_uses_the_formula_id(self):
        # AVG_ORDER_VALUE is a real formula, so the minted id is correct here
        assert _t("RATIO_TO_FORMULA")["ts_expr"] == (
            "[formula_Avg Order Value] / [Target Revenue]")

    def test_no_reference_dangles(self):
        import re
        out = translate_sv_formulas(parse_sv_ddl(_D_DDL))
        formulas = {f"formula_{e['name'].replace('_', ' ').title()}"
                    for e in out["translated"] if e["output_kind"] == "formula"}
        columns = {e["name"].replace("_", " ").title()
                   for e in out["translated"] if e["output_kind"] == "column"}
        for e in out["translated"]:
            for ref in re.findall(r"\[([^\]]+)\]", e["ts_expr"] or ""):
                if "::" in ref:
                    continue
                assert ref in (formulas | columns), f"{ref} dangles in {e['name']}"

    def test_qualified_metrics_still_translate(self):
        assert _t("AVG_ORDER_VALUE")["output_kind"] == "formula"
        assert _t("AMOUNT")["output_kind"] == "column"
