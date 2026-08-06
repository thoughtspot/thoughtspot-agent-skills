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

    # BL-178 defect 3 — `alias_table`/`alias_name` name the construct as it can
    # be REFERENCED. For a direct `alias.COL` right-hand side that is the physical
    # column it aliases; for anything computed it is the DECLARED left-hand-side
    # name, because that is the only name another metric can reference it by.
    # sv_translate keys both fact_idx and metric_idx on `alias_table.alias_name`,
    # so taking the first qualified token of the expression indexed a computed
    # construct under a physical column of its own table.

    def test_computed_fact_alias_is_the_declared_name(self):
        c = _parse_column_entry(
            "STORE_SALES.net_line as STORE_SALES.ss_ext_sales_price - "
            "STORE_SALES.ss_net_profit", "facts")
        assert c["source_column"] == "net_line"
        assert c["alias_table"] == "store_sales"
        assert c["alias_name"] == "net_line"

    def test_agg_wrapped_metric_alias_is_the_declared_name(self):
        # The `agg_wrap` branch previously returned the aggregated column's alias
        # AND name, so `metric_idx` was keyed `store_sales.net_line` — the metric
        # resolved its own inner reference to itself.
        c = _parse_column_entry(
            "STORE_SALES.total_net as SUM(store_sales.net_line)", "metrics")
        assert c["alias_table"] == "store_sales"
        assert c["alias_name"] == "total_net"

    def test_cross_table_metric_alias_is_its_own_table(self):
        # A metric declared on COMPANIES that aggregates an EMPLOYEES construct
        # must index under `companies.…` — and its resolver's default alias for
        # bare identifiers is COMPANIES, the table it is declared on.
        c = _parse_column_entry(
            "COMPANIES.AVG_HEADCOUNT as AVG(employees.headcount)", "metrics")
        assert c["alias_table"] == "companies"
        assert c["alias_name"] == "AVG_HEADCOUNT"

    def test_direct_dimension_alias_still_tracks_the_physical_column(self):
        # Unchanged: a bare `alias.COL` right-hand side is a physical-column
        # alias and both fields must keep pointing at it.
        c = _parse_column_entry("T.COL as other.PHYSICAL_COL", "dimensions")
        assert c["alias_table"] == "other"
        assert c["alias_name"] == "PHYSICAL_COL"
        assert c["expr"] is None


class TestQuotedCommasInComments:
    """BL-196 — the entry splitter must not break on commas inside comment=''.

    Semantic View DDL carries free text in `comment='...'` on nearly every
    construct, and that text routinely contains commas. A paren-only splitter
    shatters such entries into fragments and silently inflates the construct
    count, with the debris landing in `unsupported[]`.
    """

    COMMA_DDL = textwrap.dedent("""\
        create or replace semantic view DB.S.COMMA_SV
            tables (
                DB.S.DIM_CUST primary key (ID) with synonyms=('a','b')
                    comment='Identity, segmentation, geography, and territory attributes.',
                DB.S.FACT_SALES primary key (LINE_ID)
                    comment='Sales facts, at invoice-line grain.'
            )
            relationships (
                FACT_TO_CUST as FACT_SALES(CUST_ID) references DIM_CUST(ID)
            )
            facts (
                FACT_SALES.AMOUNT as fact_sales.amount
                    comment='Revenue, net of returns, in USD.'
            )
            dimensions (
                DIM_CUST.SEGMENT as dim_cust.segment
                    comment='Retail, Etail, Designer, or Other.',
                DIM_CUST.NOTE as dim_cust.note
                    comment='It''s a quoted, escaped apostrophe, plus commas.'
            )
            comment='Top level, with a comma.';""")

    def test_table_count_not_inflated(self):
        r = parse_sv_ddl(self.COMMA_DDL)
        assert len(r["tables"]) == 2
        assert [t["alias"] for t in r["tables"]] == ["DIM_CUST", "FACT_SALES"]

    def test_comments_survive_intact(self):
        r = parse_sv_ddl(self.COMMA_DDL)
        by = {t["alias"]: t for t in r["tables"]}
        assert by["DIM_CUST"]["comment"] == (
            "Identity, segmentation, geography, and territory attributes.")
        assert by["DIM_CUST"]["synonyms"] == ["a", "b"]

    def test_no_fragment_debris(self):
        r = parse_sv_ddl(self.COMMA_DDL)
        assert r["unsupported"] == []
        assert len(r["dimensions"]) == 2
        assert len(r["facts"]) == 1

    def test_escaped_apostrophe_inside_comment(self):
        r = parse_sv_ddl(self.COMMA_DDL)
        note = next(d for d in r["dimensions"] if d["source_column"] == "NOTE")
        assert note["comment"] == (
            "It's a quoted, escaped apostrophe, plus commas.")

    def test_splitter_is_quote_aware(self):
        from ts_cli.snowflake_ops import _split_top_level
        assert _split_top_level("a, 'x, y', b") == ["a", "'x, y'", "b"]
        assert _split_top_level("T.A as t.a comment='p, q', T.B as t.b") == [
            "T.A as t.a comment='p, q'", "T.B as t.b"]
        # a doubled quote is an escaped literal, so the string stays open
        assert _split_top_level("x comment='it''s, fine', y") == [
            "x comment='it''s, fine'", "y"]
        # paren nesting still respected
        assert _split_top_level("f(a, b), c") == ["f(a, b)", "c"]


class TestSampleValuesLiveDdlForm:
    """BL-197 — live GET_DDL emits `sample_values (...)`, not the authored
    `with sample values (...)`. Only the latter was matched, so the clause
    stayed in the entry text and was mis-read as part of the expression."""

    def _ddl(self, clause):
        return textwrap.dedent(f"""\
            create or replace semantic view DB.S.T_SV
                tables (DB.S.T primary key (ID))
                dimensions (T.STATUS as t.status {clause});""")

    @pytest.mark.parametrize("clause", [
        "sample_values ('Active', 'Inactive') is_enum",
        "with sample values ('Active','Inactive') is_enum",
        "with sample_values ('Active','Inactive') is_enum",
        "SAMPLE_VALUES ('Active','Inactive') IS_ENUM",
    ])
    def test_all_spellings_extract(self, clause):
        d = parse_sv_ddl(self._ddl(clause))["dimensions"][0]
        assert d["sample_values"] == ["Active", "Inactive"]
        assert d["is_enum"] is True

    def test_expr_is_not_polluted(self):
        """A passthrough rename must stay a passthrough (expr None), not
        become `t.status sample_values (...)` — which the translator then
        rejects as an unknown SAMPLE_VALUES function."""
        d = parse_sv_ddl(
            self._ddl("sample_values ('Active', 'Inactive') is_enum")
        )["dimensions"][0]
        assert d["expr"] is None

    def test_computed_expr_keeps_expression_only(self):
        ddl = textwrap.dedent("""\
            create or replace semantic view DB.S.T_SV
                tables (DB.S.T primary key (ID))
                dimensions (T.UP as UPPER(t.status)
                    sample_values ('A', 'B') is_enum);""")
        d = parse_sv_ddl(ddl)["dimensions"][0]
        assert d["sample_values"] == ["A", "B"]
        assert "sample" not in (d["expr"] or "").lower()


# ---------------------------------------------------------------------------
# BL-213 — unqualified derived metrics
#
# `NAME as <expr>` with no table prefix is valid SV grammar and the ONLY way to
# express a ratio spanning two unrelated facts: a metric qualified on a table
# may reference only metrics on directly related entities (Snowflake 010211).
# Every such metric previously landed in unsupported[].
# ---------------------------------------------------------------------------

_DERIVED_DDL = """
create or replace semantic view SV_T
  tables ( F, T )
  relationships ( )
  dimensions ( F.PID as F.PRODUCT_ID )
  metrics (
    F.AMOUNT as SUM(F.LINE_TOTAL),
    T.TARGET_REVENUE as SUM(T.TARGET_AMOUNT),
    ATTAINMENT as F.AMOUNT / T.TARGET_REVENUE
      with synonyms=('Attainment','vs target') comment='Revenue over target.'
  );
"""


class TestDerivedMetricParsing:

    def test_no_longer_unsupported(self):
        assert parse_sv_ddl(_DERIVED_DDL).get("unsupported") == []

    def test_derived_metric_is_parsed(self):
        names = [m["source_column"] for m in parse_sv_ddl(_DERIVED_DDL)["metrics"]]
        assert "ATTAINMENT" in names

    def test_flagged_is_derived(self):
        m = _metric(_DERIVED_DDL, "ATTAINMENT")
        assert m["is_derived"] is True

    def test_derived_metric_has_no_owning_table(self):
        m = _metric(_DERIVED_DDL, "ATTAINMENT")
        assert m["source_table"] is None and m["alias_table"] is None

    def test_expression_captured(self):
        assert _metric(_DERIVED_DDL, "ATTAINMENT")["expr"] == "F.AMOUNT / T.TARGET_REVENUE"

    def test_modifiers_still_parsed(self):
        m = _metric(_DERIVED_DDL, "ATTAINMENT")
        assert m["synonyms"] == ["Attainment", "vs target"]
        assert m["comment"] == "Revenue over target."

    def test_qualified_metrics_unaffected(self):
        m = _metric(_DERIVED_DDL, "AMOUNT")
        assert m["source_table"] == "F" and not m.get("is_derived")

    def test_unqualified_dimension_is_not_treated_as_derived(self):
        # only the metrics block may omit the table qualifier
        ddl = _DERIVED_DDL.replace(
            "dimensions ( F.PID as F.PRODUCT_ID )",
            "dimensions ( BARE as F.PRODUCT_ID )")
        assert not any(d.get("is_derived")
                       for d in parse_sv_ddl(ddl).get("dimensions", []))


def _metric(ddl: str, name: str) -> dict:
    return next(m for m in parse_sv_ddl(ddl)["metrics"]
                if m["source_column"] == name)


# ---------------------------------------------------------------------------
# BL-214 — several unique keys on one logical table
#
# A date dimension carrying more than one offset column needs a unique key per
# offset, because Snowflake requires every referenced key to be a primary or
# unique key of the entity. Only the first `unique (...)` was consumed; the rest
# stayed in the entry text and were swallowed into the table NAME, breaking
# every downstream lookup keyed on it.
# ---------------------------------------------------------------------------

_MULTI_UNIQUE_DDL = """
create or replace semantic view SV_T
  tables (
    DD primary key (DATE_VALUE) unique (D7) unique (D28) unique (D364),
    F
  )
  relationships ( f2d as F (DAY) references DD (D7) )
  dimensions ( DD.DV as DD.DATE_VALUE )
  metrics ( F.AMT as SUM(F.LINE_TOTAL) );
"""


class TestMultipleUniqueKeys:

    def test_table_name_is_not_polluted(self):
        dd = _table(_MULTI_UNIQUE_DDL, "DD")
        assert dd["name"] == "DD" and dd["alias"] == "DD"

    def test_all_unique_keys_captured(self):
        assert _table(_MULTI_UNIQUE_DDL, "DD")["unique_cols"] == ["D7", "D28", "D364"]

    def test_primary_key_still_parsed(self):
        assert _table(_MULTI_UNIQUE_DDL, "DD")["primary_key"] == ["DATE_VALUE"]

    def test_single_unique_key_unchanged(self):
        ddl = _MULTI_UNIQUE_DDL.replace("unique (D7) unique (D28) unique (D364)",
                                        "unique (D7)")
        assert _table(ddl, "DD")["unique_cols"] == ["D7"]

    def test_no_unique_key_unchanged(self):
        ddl = _MULTI_UNIQUE_DDL.replace(" unique (D7) unique (D28) unique (D364)", "")
        assert _table(ddl, "DD").get("unique_cols") is None

    def test_composite_unique_key_still_works(self):
        ddl = _MULTI_UNIQUE_DDL.replace("unique (D7) unique (D28) unique (D364)",
                                        "unique (A, B)")
        assert _table(ddl, "DD")["unique_cols"] == ["A", "B"]

    def test_relationship_to_a_later_unique_key_resolves(self):
        ddl = _MULTI_UNIQUE_DDL.replace("references DD (D7)", "references DD (D364)")
        r = parse_sv_ddl(ddl)["relationships"][0]
        assert r["to_table"] == "DD" and r["to_cols"] == ["D364"]


def _table(ddl: str, name: str) -> dict:
    return next(t for t in parse_sv_ddl(ddl)["tables"] if t["alias"] == name)
