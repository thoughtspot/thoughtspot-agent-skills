"""Unit tests for ts_cli.share_plan — the pure `ts share` planning layer."""
from __future__ import annotations

import pytest

from ts_cli.share_plan import (
    GrantConflictError,
    find_exclusivity_conflicts,
    format_conflicts,
    parse_grant_rows,
)


def test_parse_grant_rows_object_grant():
    rows = [{"org_name": "ORG1", "object_identifier": "T1_PUBLISH",
             "object_type": "LOGICAL_TABLE", "group_name": "Analyst",
             "share_mode": "READ_ONLY"}]
    assert parse_grant_rows(rows) == [{
        "org_name": "ORG1", "object_identifier": "T1_PUBLISH",
        "object_type": "LOGICAL_TABLE", "column_name": "",
        "group_name": "Analyst", "share_mode": "READ_ONLY",
    }]


def test_parse_grant_rows_column_grant_and_case_normalisation():
    rows = [{"ORG_NAME": "org1", "Object_Identifier": "T2_PUBLISH",
             "object_type": "logical_table", "column_name": "PROD_NM",
             "group_name": "Analyst", "share_mode": "read_only"}]
    parsed = parse_grant_rows(rows)
    assert parsed[0]["column_name"] == "PROD_NM"
    assert parsed[0]["object_type"] == "LOGICAL_TABLE"
    assert parsed[0]["share_mode"] == "READ_ONLY"
    # Org, object and group names are identifiers, not enums — case is preserved.
    assert parsed[0]["org_name"] == "org1"
    assert parsed[0]["object_identifier"] == "T2_PUBLISH"


def test_parse_grant_rows_skips_fully_blank_rows():
    rows = [{"org_name": "ORG1", "object_identifier": "T1", "object_type": "LOGICAL_TABLE",
             "group_name": "G", "share_mode": "READ_ONLY"},
            {"org_name": "", "object_identifier": "", "object_type": "",
             "column_name": "", "group_name": "", "share_mode": ""}]
    assert len(parse_grant_rows(rows)) == 1


@pytest.mark.parametrize("missing", ["org_name", "object_identifier", "group_name"])
def test_parse_grant_rows_rejects_missing_required_field(missing):
    row = {"org_name": "ORG1", "object_identifier": "T1", "object_type": "LOGICAL_TABLE",
           "group_name": "Analyst", "share_mode": "READ_ONLY"}
    row[missing] = ""
    with pytest.raises(ValueError, match=missing):
        parse_grant_rows([row])


def test_parse_grant_rows_rejects_unknown_share_mode():
    row = {"org_name": "ORG1", "object_identifier": "T1", "object_type": "LOGICAL_TABLE",
           "group_name": "Analyst", "share_mode": "WRITE"}
    with pytest.raises(ValueError, match="WRITE"):
        parse_grant_rows([row])


def test_parse_grant_rows_rejects_unknown_object_type():
    row = {"org_name": "ORG1", "object_identifier": "T1", "object_type": "CONNECTION",
           "group_name": "Analyst", "share_mode": "READ_ONLY"}
    with pytest.raises(ValueError, match="CONNECTION"):
        parse_grant_rows([row])


def test_parse_grant_rows_column_grant_requires_logical_table():
    row = {"org_name": "ORG1", "object_identifier": "LB1", "object_type": "LIVEBOARD",
           "column_name": "PROD_NM", "group_name": "Analyst", "share_mode": "READ_ONLY"}
    with pytest.raises(ValueError, match="LOGICAL_TABLE"):
        parse_grant_rows([row])


def test_parse_grant_rows_dedupes_identical_rows():
    row = {"org_name": "ORG1", "object_identifier": "T1", "object_type": "LOGICAL_TABLE",
           "group_name": "Analyst", "share_mode": "READ_ONLY"}
    assert len(parse_grant_rows([row, dict(row)])) == 1


def test_parse_grant_rows_rejects_contradictory_duplicate():
    """Same primary key, different share_mode — ambiguous, so refuse rather than pick."""
    base = {"org_name": "ORG1", "object_identifier": "T1", "object_type": "LOGICAL_TABLE",
            "group_name": "Analyst"}
    rows = [{**base, "share_mode": "READ_ONLY"}, {**base, "share_mode": "MODIFY"}]
    with pytest.raises(ValueError, match="conflicting share_mode"):
        parse_grant_rows(rows)


def test_find_exclusivity_conflicts_flags_table_plus_column():
    grants = parse_grant_rows([
        {"org_name": "ORG1", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "group_name": "Analyst", "share_mode": "READ_ONLY"},
        {"org_name": "ORG1", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "column_name": "PROD_NM", "group_name": "Analyst", "share_mode": "READ_ONLY"},
    ])
    conflicts = find_exclusivity_conflicts(grants)
    assert len(conflicts) == 1
    assert conflicts[0]["org_name"] == "ORG1"
    assert conflicts[0]["object_identifier"] == "T2"
    assert conflicts[0]["group_name"] == "Analyst"
    assert conflicts[0]["column_names"] == ["PROD_NM"]


def test_find_exclusivity_conflicts_ignores_no_access_free_combinations():
    """Different groups, or different tables, are not a conflict."""
    grants = parse_grant_rows([
        {"org_name": "ORG1", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "group_name": "Analyst", "share_mode": "READ_ONLY"},
        {"org_name": "ORG1", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "column_name": "PROD_NM", "group_name": "Auditor", "share_mode": "READ_ONLY"},
        {"org_name": "ORG2", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "column_name": "PROD_NM", "group_name": "Analyst", "share_mode": "READ_ONLY"},
    ])
    assert find_exclusivity_conflicts(grants) == []


def test_find_exclusivity_conflicts_flags_no_access_table_grant_too():
    """A NO_ACCESS table grant beside column grants is still refused.

    Whether a table-level NO_ACCESS wipes existing column grants is unverified, so the
    ordering of a revoke-then-grant sequence is not something the tool can guarantee
    inside one manifest. Spec §3.3 says refuse both together; that is what we do.
    """
    grants = parse_grant_rows([
        {"org_name": "ORG1", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "group_name": "ALL", "share_mode": "NO_ACCESS"},
        {"org_name": "ORG1", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "column_name": "PROD_NM", "group_name": "ALL", "share_mode": "READ_ONLY"},
    ])
    conflicts = find_exclusivity_conflicts(grants)
    assert len(conflicts) == 1
    assert conflicts[0]["table_share_modes"] == ["NO_ACCESS"]


def test_format_conflicts_names_org_table_group_and_the_fix():
    grants = parse_grant_rows([
        {"org_name": "ORG1", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "group_name": "Analyst", "share_mode": "READ_ONLY"},
        {"org_name": "ORG1", "object_identifier": "T2", "object_type": "LOGICAL_TABLE",
         "column_name": "PROD_NM", "group_name": "Analyst", "share_mode": "READ_ONLY"},
    ])
    text = format_conflicts(find_exclusivity_conflicts(grants))
    for expected in ("ORG1", "T2", "Analyst", "PROD_NM"):
        assert expected in text
    assert "every column" in text


def test_grant_conflict_error_is_a_value_error():
    assert issubclass(GrantConflictError, ValueError)
