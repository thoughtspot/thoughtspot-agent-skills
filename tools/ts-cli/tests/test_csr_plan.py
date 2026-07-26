"""Unit tests for the pure CSR planning engine."""
from __future__ import annotations

import pytest

from ts_cli.csr_plan import (
    CSR_TABLE_DDL,
    OPERATIONS,
    build_csr_steps,
    build_update_payload,
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


def test_payload_replace_is_the_default_operation():
    payload = build_update_payload("T2_PUBLISH", {"PROD_NM": ["Analyst"]})
    assert payload == {
        "identifier": "T2_PUBLISH",
        "clear_csr": False,
        "column_security_rules": [
            {"column_identifier": "PROD_NM", "is_unsecured": False,
             "group_access": [{"operation": "REPLACE",
                               "group_identifiers": ["Analyst"]}]}],
    }


def test_payload_honours_add_and_remove():
    for operation in ("ADD", "REMOVE"):
        payload = build_update_payload("T2", {"COST": ["Finance"]}, operation=operation)
        access = payload["column_security_rules"][0]["group_access"][0]
        assert access["operation"] == operation


def test_payload_rejects_an_unknown_operation():
    with pytest.raises(ValueError, match="ADD, REMOVE, REPLACE"):
        build_update_payload("T2", {"COST": ["Finance"]}, operation="UPSERT")


def test_payload_for_a_column_secured_for_nobody_keeps_an_empty_group_list():
    payload = build_update_payload("T2", {"COST": []})
    access = payload["column_security_rules"][0]["group_access"][0]
    assert access == {"operation": "REPLACE", "group_identifiers": []}


def test_clear_always_ships_the_required_empty_array():
    # `column_security_rules` is a REQUIRED field, which is why `clear_csr: true`
    # alone is rejected. Emitting both is the whole point of this branch.
    assert build_update_payload("T2", {}, clear=True) == {
        "identifier": "T2", "clear_csr": True, "column_security_rules": []}


def test_clear_refuses_to_be_combined_with_rules():
    with pytest.raises(ValueError, match="clear"):
        build_update_payload("T2", {"COST": ["Finance"]}, clear=True)


def test_unsecure_emits_is_unsecured_without_group_access():
    payload = build_update_payload("T2", {}, unsecure=["COST"])
    assert payload["column_security_rules"] == [
        {"column_identifier": "COST", "is_unsecured": True}]


def test_payload_requires_something_to_do():
    with pytest.raises(ValueError, match="nothing to do"):
        build_update_payload("T2", {})


def test_payload_sorts_columns_so_a_dry_run_is_diffable():
    payload = build_update_payload("T2", {"ZED": ["A"], "ALPHA": ["B"]})
    names = [r["column_identifier"] for r in payload["column_security_rules"]]
    assert names == ["ALPHA", "ZED"]


def test_payload_refuses_an_empty_table_identifier():
    with pytest.raises(ValueError, match="table"):
        build_update_payload("", {"COST": ["Finance"]})


def _rows(*triples):
    return [{"org_name": o, "table_name": t, "column_name": c, "group_name": g}
            for o, t, c, g in triples]


def test_steps_group_rows_by_org_and_table():
    rows = _rows(("ORG1", "T2", "COST", "Finance"),
                 ("ORG1", "T2", "PROD_NM", "Analyst"),
                 ("ORG2", "T2", "COST", "Finance"))
    steps = build_csr_steps(rows)
    assert [(s["org_name"], s["table_name"]) for s in steps] == [
        ("ORG1", "T2"), ("ORG2", "T2")]
    assert steps[0]["rules"] == {"COST": ["Finance"], "PROD_NM": ["Analyst"]}


def test_steps_collect_several_groups_onto_one_column():
    rows = _rows(("ORG1", "T2", "COST", "Finance"), ("ORG1", "T2", "COST", "Audit"))
    assert build_csr_steps(rows)[0]["rules"] == {"COST": ["Audit", "Finance"]}


def test_steps_drop_the_blank_group_sentinel_from_the_group_list():
    # A blank group_name means "secured, nobody". It is the ABSENCE of groups, so it
    # must never travel as a literal "" group identifier the platform would reject.
    rows = _rows(("ORG1", "T2", "COST", ""))
    assert build_csr_steps(rows)[0]["rules"] == {"COST": []}


def test_steps_are_sorted_for_a_stable_plan():
    rows = _rows(("ORG2", "T9", "A", "G"), ("ORG1", "T1", "A", "G"))
    steps = build_csr_steps(rows)
    assert [s["org_name"] for s in steps] == ["ORG1", "ORG2"]


def test_steps_prefer_the_guid_as_the_table_identifier_when_known():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "guid-1",
               "published": False, "secured_columns": []}]
    step = build_csr_steps(rows, tables)[0]
    assert step["table_identifier"] == "guid-1"
    assert step["table_name"] == "T2"


def test_steps_fall_back_to_the_name_when_no_guid_was_resolved():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    assert build_csr_steps(rows)[0]["table_identifier"] == "T2"


def test_a_published_table_is_marked_blocked():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "guid-1",
               "published": True, "secured_columns": []}]
    step = build_csr_steps(rows, tables)[0]
    assert step["blocked"].startswith("CSR_BLOCKED")
    assert "published" in step["blocked"]


def test_an_unpublished_table_is_not_blocked():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "guid-1",
               "published": False, "secured_columns": []}]
    assert build_csr_steps(rows, tables)[0]["blocked"] == ""


def test_prune_unsecures_only_columns_absent_from_the_manifest():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "g",
               "published": False, "secured_columns": ["COST", "SALARY", "SSN"]}]
    step = build_csr_steps(rows, tables, prune=True)[0]
    assert step["unsecure"] == ["SALARY", "SSN"]


def test_without_prune_nothing_is_unsecured_however_stale():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    tables = [{"org_name": "ORG1", "table_name": "T2", "table_guid": "g",
               "published": False, "secured_columns": ["COST", "SALARY"]}]
    assert build_csr_steps(rows, tables, prune=True) != build_csr_steps(rows, tables)
    assert build_csr_steps(rows, tables)[0]["unsecure"] == []


def test_steps_carry_the_operation_through():
    rows = _rows(("ORG1", "T2", "COST", "Finance"))
    assert build_csr_steps(rows, operation="ADD")[0]["operation"] == "ADD"
