"""Tests for ts_cli.sv_parse — Snowflake Semantic View DDL parser.

Golden fixtures derived from agents/shared/worked-examples/snowflake/:
  - COMPANY_WORKFORCE_SV (identifier-resolution.md): facts, metrics-on-fact
  - Dunder Mifflin (dunder.md): semi-additive, window, custom instructions
  - BIRD_SUPERHEROS_SV (ts-from-snowflake.md): basic star/snowflake joins
"""
from __future__ import annotations

import textwrap

import pytest

from ts_cli.sv_parse import (
    _extract_comment,
    _extract_sample_values,
    _extract_synonyms,
    _parse_column_entry,
    _parse_relationship_entry,
    _parse_table_entry,
    parse_sv_ddl,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WORKFORCE_DDL = textwrap.dedent("""\
    create or replace semantic view AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.COMPANY_WORKFORCE_SV
        tables (
            AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.COMPANIES primary key (COMPANY_ID)
                comment='Parent company master data',
            AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.EMPLOYEES primary key (EMPLOYEE_ID)
                comment='Employee records linked to companies'
        )
        relationships (
            EMPLOYEES_TO_COMPANIES as EMPLOYEES(COMPANY_ID) references COMPANIES(COMPANY_ID)
        )
        facts (
            EMPLOYEES.TENURE_MONTHS as DATEDIFF(month, HIRE_DATE, CURRENT_DATE())
                comment='Number of months since the employee was hired',
            EMPLOYEES.SALARY_BAND as CASE
                    WHEN SALARY >= 90000 THEN 'Senior'
                    WHEN SALARY >= 70000 THEN 'Mid'
                    ELSE 'Junior'
                END comment='Salary classification band based on annual salary'
        )
        dimensions (
            COMPANIES.COMPANY_ID as companies.COMPANY_ID,
            COMPANIES.COMPANY_NAME as companies.COMPANY_NAME
                with synonyms=('Company','Organisation')
                comment='The registered company name',
            EMPLOYEES.DEPARTMENT as employees.DEPARTMENT
                with synonyms=('Team','Division')
                comment='Department the employee belongs to'
        )
        metrics (
            EMPLOYEES.HEADCOUNT as COUNT(EMPLOYEE_ID)
                with synonyms=('Employee Count','Staff Count')
                comment='Total number of employees',
            EMPLOYEES.TOTAL_SALARY as SUM(SALARY)
                comment='Sum of all employee salaries',
            EMPLOYEES.AVG_TENURE as AVG(employees.tenure_months)
                comment='Average employee tenure in months',
            COMPANIES.AVG_HEADCOUNT_PER_COMPANY as AVG(employees.headcount)
                comment='Average number of employees per company'
        )
        comment='Company workforce analytics';
""")


DUNDER_DDL = textwrap.dedent("""\
    create or replace semantic view DUNDERMIFFLIN.PUBLIC_SV.DUNDER_MIFFLIN_SALES
        tables (
            DUNDERMIFFLIN.PUBLIC.DM_CATEGORY primary key (CATEGORY_ID)
                comment='Product categories',
            DUNDERMIFFLIN.PUBLIC.DM_CUSTOMER primary key (CUSTOMER_ID)
        )
        relationships (
            CUST_TO_CAT as DM_CUSTOMER(CATEGORY_ID) references DM_CATEGORY(CATEGORY_ID)
        )
        dimensions (
            DM_CATEGORY.CATEGORY as dm_category.CATEGORY_NAME
                with synonyms=('Product Category','Category Name')
                comment='Name of the product category'
        )
        metrics (
            DM_CUSTOMER.CLOSING_STOCK non additive by (DM_CUSTOMER.BALANCE_DATE asc nulls last)
                as SUM(dm_customer.FILLED_INVENTORY)
                comment='Latest (closing) inventory quantity',
            DM_CUSTOMER.OPENING_STOCK non additive by (DM_CUSTOMER.BALANCE_DATE desc nulls last)
                as SUM(dm_customer.FILLED_INVENTORY)
                comment='Earliest (opening) inventory quantity',
            DM_CUSTOMER.CATEGORY_QTY
                as SUM(dm_customer.QUANTITY) OVER (PARTITION BY dm_category.category)
                comment='Running total within each category'
        )
        comment='Dunder Mifflin Sales'
        ai_sql_generation = 'Use CLOSING_STOCK for current levels.'
        ai_question_categorization = 'Group under Sales.'
        with extension (CA='{"tables":[]}');
""")


# ---------------------------------------------------------------------------
# View identity
# ---------------------------------------------------------------------------

class TestViewName:
    def test_three_part(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["database"] == "AGENT_SKILLS"
        assert result["schema"] == "IDENTIFIER_RESOLUTION_TEST"
        assert result["name"] == "COMPANY_WORKFORCE_SV"

    def test_fqn(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["view_name"] == "AGENT_SKILLS.IDENTIFIER_RESOLUTION_TEST.COMPANY_WORKFORCE_SV"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class TestTables:
    def test_count(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert len(result["tables"]) == 2

    def test_alias_defaults_to_last_segment(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["tables"][0]["alias"] == "COMPANIES"

    def test_primary_key(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["tables"][0]["primary_key"] == ["COMPANY_ID"]

    def test_table_comment(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["tables"][0]["comment"] == "Parent company master data"

    def test_explicit_alias(self):
        ddl = """create or replace semantic view TEST_SV
            tables (ORDER_TBL as DB.SCHEMA."ORDER" primary key (ID))
            dimensions (ORDER_TBL.NAME as order_tbl.NAME);"""
        result = parse_sv_ddl(ddl)
        assert result["tables"][0]["alias"] == "ORDER_TBL"
        assert '"ORDER"' in result["tables"][0]["fqn"]

    def test_subquery_source(self):
        ddl = """create or replace semantic view TEST_SV
            tables (MY_VIEW as (SELECT * FROM DB.SCHEMA.T) primary key (ID))
            dimensions (MY_VIEW.NAME as my_view.NAME);"""
        result = parse_sv_ddl(ddl)
        t = result["tables"][0]
        assert t["alias"] == "MY_VIEW"
        assert t["is_subquery"] is True
        assert "SELECT * FROM DB.SCHEMA.T" in t["subquery_sql"]

    def test_range_constraint(self):
        ddl = """create or replace semantic view TEST_SV
            tables (
                DB.S.RATES primary key (RATE_ID) unique (START_DT, END_DT)
                    constraint RATE_RANGE distinct range between START_DT and END_DT exclusive
            )
            dimensions (RATES.RATE_ID as rates.RATE_ID);"""
        result = parse_sv_ddl(ddl)
        t = result["tables"][0]
        assert t["range_constraint"]["name"] == "RATE_RANGE"
        assert t["range_constraint"]["start"] == "START_DT"
        assert t["range_constraint"]["end"] == "END_DT"
        assert t["unique_cols"] == ["START_DT", "END_DT"]

    def test_table_synonyms(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.T primary key (ID) with synonyms=('Tab','Table'))
            dimensions (T.NAME as t.NAME);"""
        result = parse_sv_ddl(ddl)
        assert result["tables"][0]["synonyms"] == ["Tab", "Table"]


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

class TestRelationships:
    def test_equi_join(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        rel = result["relationships"][0]
        assert rel["name"] == "EMPLOYEES_TO_COMPANIES"
        assert rel["from_table"] == "EMPLOYEES"
        assert rel["from_cols"] == ["COMPANY_ID"]
        assert rel["to_table"] == "COMPANIES"
        assert rel["to_cols"] == ["COMPANY_ID"]
        assert rel["join_style"] == "equi"

    def test_range_join(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.A primary key (ID), DB.S.B primary key (ID))
            relationships (
                A_TO_B as A(DT) references B(between START_DT and END_DT exclusive)
            )
            dimensions (A.ID as a.ID);"""
        result = parse_sv_ddl(ddl)
        rel = result["relationships"][0]
        assert rel["join_style"] == "range"
        assert rel["to_cols"] == ["START_DT", "END_DT"]

    def test_asof_join(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.A primary key (ID), DB.S.B primary key (ID))
            relationships (
                A_TO_B as A(KEY, EVENT_DT) references B(KEY, ASOF TS)
            )
            dimensions (A.ID as a.ID);"""
        result = parse_sv_ddl(ddl)
        rel = result["relationships"][0]
        assert rel["join_style"] == "asof"
        assert rel["to_cols"] == ["KEY", "TS"]


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

class TestDimensions:
    def test_count(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert len(result["dimensions"]) == 3

    def test_simple_dimension(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        d = result["dimensions"][0]
        assert d["source_table"] == "COMPANIES"
        assert d["source_column"] == "COMPANY_ID"
        assert d["alias_table"] == "companies"
        assert d["alias_name"] == "COMPANY_ID"
        assert d["expr"] is None

    def test_dimension_with_synonyms_and_comment(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        d = result["dimensions"][1]
        assert d["source_column"] == "COMPANY_NAME"
        assert d["synonyms"] == ["Company", "Organisation"]
        assert d["comment"] == "The registered company name"

    def test_private_dimension(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.T primary key (ID))
            dimensions (PRIVATE T.INTERNAL_ID as t.INTERNAL_ID);"""
        result = parse_sv_ddl(ddl)
        assert result["dimensions"][0]["is_private"] is True

    def test_filter_label(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.T primary key (ID))
            dimensions (T.IS_ACTIVE labels = (filter) as T.STATUS = 'ACTIVE');"""
        result = parse_sv_ddl(ddl)
        d = result["dimensions"][0]
        assert d["is_filter"] is True

    def test_cortex_search_service(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.T primary key (ID))
            dimensions (T.DESC as t.DESC with cortex search service MY_SVC);"""
        result = parse_sv_ddl(ddl)
        assert result["dimensions"][0]["cortex_search_service"] == "MY_SVC"

    def test_sample_values_warning(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.T primary key (ID))
            dimensions (T.STATUS as t.STATUS with sample values ('Active','Inactive'));"""
        result = parse_sv_ddl(ddl)
        assert result["dimensions"][0]["sample_values"] == ["Active", "Inactive"]
        assert any("sample_values" in w for w in result["warnings"])

    def test_is_enum_warning(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.T primary key (ID))
            dimensions (T.TYPE as t.TYPE is_enum);"""
        result = parse_sv_ddl(ddl)
        assert result["dimensions"][0]["is_enum"] is True
        assert any("is_enum" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

class TestFacts:
    def test_count(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert len(result["facts"]) == 2

    def test_datediff_fact(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        f = result["facts"][0]
        assert f["source_table"] == "EMPLOYEES"
        assert f["source_column"] == "TENURE_MONTHS"
        assert "DATEDIFF" in f["expr"]
        assert f["comment"] == "Number of months since the employee was hired"

    def test_case_when_fact(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        f = result["facts"][1]
        assert f["source_column"] == "SALARY_BAND"
        assert "CASE" in f["expr"]
        assert "Senior" in f["expr"]
        assert f["comment"] == "Salary classification band based on annual salary"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_count(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert len(result["metrics"]) == 4

    def test_simple_agg(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        m = result["metrics"][0]
        assert m["source_column"] == "HEADCOUNT"
        assert m["expr"] == "COUNT(EMPLOYEE_ID)"
        assert m["synonyms"] == ["Employee Count", "Staff Count"]

    def test_metric_on_fact(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        m = result["metrics"][2]
        assert m["source_column"] == "AVG_TENURE"
        assert "AVG(employees.tenure_months)" in m["expr"]

    def test_double_aggregation(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        m = result["metrics"][3]
        assert m["source_column"] == "AVG_HEADCOUNT_PER_COMPANY"
        assert "AVG(employees.headcount)" in m["expr"]

    def test_semi_additive_asc(self):
        result = parse_sv_ddl(DUNDER_DDL)
        m = result["metrics"][0]
        assert m["source_column"] == "CLOSING_STOCK"
        assert m["semi_additive"]["order_col"] == "DM_CUSTOMER.BALANCE_DATE"
        assert m["semi_additive"]["direction"] == "asc"
        assert m["semi_additive"]["nulls"] == "last"
        assert m["expr"] == "SUM(dm_customer.FILLED_INVENTORY)"

    def test_semi_additive_desc(self):
        result = parse_sv_ddl(DUNDER_DDL)
        m = result["metrics"][1]
        assert m["semi_additive"]["direction"] == "desc"

    def test_window_over(self):
        result = parse_sv_ddl(DUNDER_DDL)
        m = result["metrics"][2]
        assert "OVER" in m["expr"]
        assert "PARTITION BY" in m["expr"]

    def test_using_relationship(self):
        ddl = """create or replace semantic view TEST_SV
            tables (DB.S.A primary key (ID), DB.S.B primary key (ID))
            relationships (A_TO_B as A(FK) references B(PK))
            dimensions (A.ID as a.ID)
            metrics (A.TOTAL USING A_TO_B as SUM(a.AMOUNT));"""
        result = parse_sv_ddl(ddl)
        assert result["metrics"][0]["using_relationship"] == "A_TO_B"


# ---------------------------------------------------------------------------
# Top-level comment
# ---------------------------------------------------------------------------

class TestComment:
    def test_present(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["comment"] == "Company workforce analytics"

    def test_with_ai_clauses_before_extension(self):
        result = parse_sv_ddl(DUNDER_DDL)
        assert result["comment"] == "Dunder Mifflin Sales"

    def test_absent(self):
        ddl = """create or replace semantic view DB.S.V
            tables (DB.S.T primary key (ID))
            dimensions (T.NAME as t.NAME);"""
        result = parse_sv_ddl(ddl)
        assert result["comment"] is None

    def test_escaped_quotes(self):
        ddl = """create or replace semantic view DB.S.V
            tables (DB.S.T primary key (ID))
            dimensions (T.NAME as t.NAME)
            comment='It''s a test view';"""
        result = parse_sv_ddl(ddl)
        assert result["comment"] == "It's a test view"


# ---------------------------------------------------------------------------
# Custom instructions
# ---------------------------------------------------------------------------

class TestCustomInstructions:
    def test_both_present(self):
        result = parse_sv_ddl(DUNDER_DDL)
        ci = result["custom_instructions"]
        assert ci["ai_sql_generation"] == "Use CLOSING_STOCK for current levels."
        assert ci["ai_question_categorization"] == "Group under Sales."

    def test_absent(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["custom_instructions"] is None


# ---------------------------------------------------------------------------
# Verified queries
# ---------------------------------------------------------------------------

class TestVerifiedQueries:
    def test_parsed(self):
        ddl = """create or replace semantic view DB.S.V
            tables (DB.S.T primary key (ID))
            dimensions (T.NAME as t.NAME)
            ai_verified_queries (
                Q1 AS (
                    QUESTION 'How many items?'
                    VERIFIED_AT 1700000000
                    ONBOARDING_QUESTION TRUE
                    VERIFIED_BY '(PURPOSE = admin)'
                    SQL 'SELECT COUNT(*) FROM t'
                )
            );"""
        result = parse_sv_ddl(ddl)
        assert len(result["verified_queries"]) == 1
        vq = result["verified_queries"][0]
        assert vq["name"] == "Q1"
        assert vq["question"] == "How many items?"
        assert vq["sql"] == "SELECT COUNT(*) FROM t"
        assert vq["verified_at"] == 1700000000
        assert vq["onboarding_question"] is True
        assert vq["verified_by"] == "(PURPOSE = admin)"


# ---------------------------------------------------------------------------
# Extension JSON
# ---------------------------------------------------------------------------

class TestExtension:
    def test_parsed(self):
        result = parse_sv_ddl(DUNDER_DDL)
        assert result["extension"] == {"tables": []}

    def test_absent(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["extension"] is None


# ---------------------------------------------------------------------------
# Unsupported
# ---------------------------------------------------------------------------

class TestUnsupported:
    def test_clean_parse(self):
        result = parse_sv_ddl(WORKFORCE_DDL)
        assert result["unsupported"] == []

    def test_unparseable_relationship(self):
        ddl = """create or replace semantic view DB.S.V
            tables (DB.S.A primary key (ID))
            relationships (SOMETHING_WEIRD)
            dimensions (A.ID as a.ID);"""
        result = parse_sv_ddl(ddl)
        assert len(result["unsupported"]) == 1
        assert result["unsupported"][0]["block"] == "relationships"


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestExtractComment:
    def test_basic(self):
        text, cleaned = _extract_comment("COL as expr comment='a description'")
        assert text == "a description"
        assert "comment" not in cleaned

    def test_escaped_quote(self):
        text, cleaned = _extract_comment("COL as expr comment='it''s fine'")
        assert text == "it's fine"


class TestExtractSynonyms:
    def test_basic(self):
        syns, cleaned = _extract_synonyms("COL as t.COL with synonyms=('A','B','C')")
        assert syns == ["A", "B", "C"]
        assert "synonyms" not in cleaned


class TestParseTableEntry:
    def test_simple(self):
        t = _parse_table_entry("DB.SCHEMA.TABLE primary key (PK)")
        assert t["fqn"] == "DB.SCHEMA.TABLE"
        assert t["alias"] == "TABLE"
        assert t["primary_key"] == ["PK"]

    def test_no_pk(self):
        t = _parse_table_entry("DB.S.VIEW_NAME")
        assert t["primary_key"] == []
        assert t["alias"] == "VIEW_NAME"


class TestParseRelationshipEntry:
    def test_equi(self):
        r = _parse_relationship_entry("R as A(FK) references B(PK)")
        assert r["join_style"] == "equi"
        assert r["name"] == "R"


class TestParseColumnEntry:
    def test_dimension(self):
        c = _parse_column_entry("T.COL as t.COL_NAME", "dimensions")
        assert c["source_table"] == "T"
        assert c["source_column"] == "COL"
        assert c["alias_table"] == "t"
        assert c["alias_name"] == "COL_NAME"

    def test_metric_with_agg(self):
        c = _parse_column_entry("T.TOTAL as SUM(t.AMOUNT)", "metrics")
        assert c["expr"] == "SUM(t.AMOUNT)"
