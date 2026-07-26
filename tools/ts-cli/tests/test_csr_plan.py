"""Unit tests for the pure CSR planning engine."""
from __future__ import annotations

import pytest

from ts_cli.csr_plan import (
    CSR_TABLE_DDL,
    OPERATIONS,
    parse_rule_flags,
    parse_rule_rows,
)


def test_operations_are_the_three_api_verbs():
    assert OPERATIONS == ("ADD", "REMOVE", "REPLACE")


def test_ddl_names_the_manifest_table_and_keys_all_four_columns():
    assert "TS_COLUMN_SECURITY_RULES" in CSR_TABLE_DDL
    assert "PRIMARY KEY (org_name, table_name, column_name, group_name)" in CSR_TABLE_DDL
    # group_name carries the empty-string sentinel, so it cannot be nullable: a
    # nullable column cannot sit in a primary key.
    assert "group_name   VARCHAR NOT NULL" in CSR_TABLE_DDL


def test_parse_rule_flags_single_column_single_group():
    assert parse_rule_flags(["PROD_NM=Analyst"]) == {"PROD_NM": ["Analyst"]}


def test_parse_rule_flags_multiple_groups_and_whitespace():
    assert parse_rule_flags([" PROD_NM = Analyst , Finance "]) == {
        "PROD_NM": ["Analyst", "Finance"]}


def test_parse_rule_flags_empty_group_list_means_secured_for_nobody():
    assert parse_rule_flags(["COST="]) == {"COST": []}


def test_parse_rule_flags_dedupes_groups_preserving_order():
    assert parse_rule_flags(["COST=A,B,A"]) == {"COST": ["A", "B"]}


def test_parse_rule_flags_merges_repeated_flags_for_one_column():
    assert parse_rule_flags(["COST=A", "COST=B"]) == {"COST": ["A", "B"]}


def test_parse_rule_flags_rejects_missing_equals():
    with pytest.raises(ValueError, match="COL=GROUP"):
        parse_rule_flags(["PROD_NM"])


def test_parse_rule_flags_rejects_empty_column_name():
    with pytest.raises(ValueError, match="column name"):
        parse_rule_flags(["=Analyst"])


def test_parse_rule_rows_normalises_and_keeps_identifier_casing():
    rows = [{"ORG_NAME": "ORG1", "TABLE_NAME": "T2_PUBLISH",
             "COLUMN_NAME": "Prod_Nm", "GROUP_NAME": "Analyst"}]
    assert parse_rule_rows(rows) == [
        {"org_name": "ORG1", "table_name": "T2_PUBLISH",
         "column_name": "Prod_Nm", "group_name": "Analyst"}]


def test_parse_rule_rows_allows_blank_group_as_the_no_access_sentinel():
    rows = [{"org_name": "ORG1", "table_name": "T2", "column_name": "COST",
             "group_name": ""}]
    assert parse_rule_rows(rows) == [
        {"org_name": "ORG1", "table_name": "T2", "column_name": "COST",
         "group_name": ""}]


def test_parse_rule_rows_skips_fully_blank_rows():
    rows = [{"org_name": "", "table_name": "", "column_name": "", "group_name": ""}]
    assert parse_rule_rows(rows) == []


def test_parse_rule_rows_refuses_a_partially_filled_row():
    rows = [{"org_name": "ORG1", "table_name": "", "column_name": "COST",
             "group_name": "Analyst"}]
    with pytest.raises(ValueError, match="table_name"):
        parse_rule_rows(rows)


def test_parse_rule_rows_refuses_a_row_with_no_column_name():
    # CSR declares restricted COLUMNS. A row without one has nothing to restrict,
    # and silently dropping it would leave a column unprotected with no trace.
    rows = [{"org_name": "ORG1", "table_name": "T2", "column_name": "",
             "group_name": "Analyst"}]
    with pytest.raises(ValueError, match="column_name"):
        parse_rule_rows(rows)


def test_parse_rule_rows_dedupes_identical_rows():
    row = {"org_name": "ORG1", "table_name": "T2", "column_name": "COST",
           "group_name": "Analyst"}
    assert parse_rule_rows([dict(row), dict(row)]) == [row]
