"""Unit tests for ts_cli.share_plan — the pure `ts share` planning layer."""
from __future__ import annotations

import pytest

from ts_cli.share_plan import (
    GrantConflictError,
    build_share_steps,
    find_exclusivity_conflicts,
    format_conflicts,
    parse_grant_rows,
    permission_rows,
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


# ---------------------------------------------------------------------------
# build_share_steps
# ---------------------------------------------------------------------------

def _resolved(**overrides):
    row = {"org_name": "ORG1", "object_identifier": "T2_PUBLISH",
           "object_type": "LOGICAL_TABLE", "column_name": "",
           "group_name": "Analyst", "share_mode": "READ_ONLY",
           "object_guid": "obj-guid-1", "column_guid": ""}
    row.update(overrides)
    return row


def test_build_share_steps_object_grant_uses_object_guid():
    steps = build_share_steps([_resolved()])
    assert len(steps) == 1
    step = steps[0]
    assert step["org_name"] == "ORG1"
    assert step["metadata_type"] == "LOGICAL_TABLE"
    assert step["metadata_identifiers"] == ["obj-guid-1"]
    assert step["permissions"] == [
        {"principal": {"type": "USER_GROUP", "identifier": "Analyst"},
         "share_mode": "READ_ONLY"}]


def test_build_share_steps_column_grant_uses_logical_column_and_column_guid():
    steps = build_share_steps([
        _resolved(column_name="PROD_NM", column_guid="col-guid-1")])
    assert steps[0]["metadata_type"] == "LOGICAL_COLUMN"
    assert steps[0]["metadata_identifiers"] == ["col-guid-1"]


def test_build_share_steps_batches_objects_sharing_one_permission_set():
    steps = build_share_steps([
        _resolved(object_identifier="T1", object_guid="g1"),
        _resolved(object_identifier="T2", object_guid="g2"),
    ])
    assert len(steps) == 1
    assert steps[0]["metadata_identifiers"] == ["g1", "g2"]


def test_build_share_steps_merges_principals_on_one_object():
    steps = build_share_steps([
        _resolved(group_name="Analyst", share_mode="READ_ONLY"),
        _resolved(group_name="Auditor", share_mode="MODIFY"),
    ])
    assert len(steps) == 1
    assert steps[0]["permissions"] == [
        {"principal": {"type": "USER_GROUP", "identifier": "Analyst"},
         "share_mode": "READ_ONLY"},
        {"principal": {"type": "USER_GROUP", "identifier": "Auditor"},
         "share_mode": "MODIFY"},
    ]


def test_build_share_steps_splits_objects_with_different_permission_sets():
    steps = build_share_steps([
        _resolved(object_identifier="T1", object_guid="g1", group_name="Analyst"),
        _resolved(object_identifier="T2", object_guid="g2", group_name="Auditor"),
    ])
    assert len(steps) == 2
    assert {tuple(s["metadata_identifiers"]) for s in steps} == {("g1",), ("g2",)}


def test_build_share_steps_splits_by_org():
    steps = build_share_steps([
        _resolved(org_name="ORG1"), _resolved(org_name="ORG2")])
    assert sorted(s["org_name"] for s in steps) == ["ORG1", "ORG2"]


def test_build_share_steps_never_mixes_object_and_column_types_in_one_call():
    steps = build_share_steps([
        _resolved(group_name="Analyst"),
        _resolved(object_identifier="T9", object_guid="g9", group_name="Analyst",
                  column_name="PROD_NM", column_guid="col-9"),
    ])
    assert {s["metadata_type"] for s in steps} == {"LOGICAL_TABLE", "LOGICAL_COLUMN"}


def test_build_share_steps_labels_describe_each_target():
    steps = build_share_steps([
        _resolved(column_name="PROD_NM", column_guid="col-guid-1")])
    assert steps[0]["labels"] == ["T2_PUBLISH.PROD_NM"]


def test_build_share_steps_requires_a_resolved_guid():
    with pytest.raises(ValueError, match="object_guid"):
        build_share_steps([_resolved(object_guid="")])


def test_build_share_steps_requires_a_resolved_column_guid():
    with pytest.raises(ValueError, match="column_guid"):
        build_share_steps([_resolved(column_name="PROD_NM", column_guid="")])


def test_build_share_steps_is_deterministic():
    rows = [_resolved(object_identifier="T2", object_guid="g2"),
            _resolved(object_identifier="T1", object_guid="g1")]
    assert build_share_steps(rows) == build_share_steps(list(reversed(rows)))


# ---------------------------------------------------------------------------
# permission_rows
# ---------------------------------------------------------------------------

def test_permission_rows_flattens_the_fetch_permissions_shape():
    payload = {"metadata_permission_details": [{
        "metadata_id": "obj-guid-1",
        "metadata_name": "T2_PUBLISH",
        "metadata_type": "LOGICAL_TABLE",
        "principal_permission_info": [{
            "principal_type": "USER_GROUP",
            "principal_sub_type": "LOCAL_GROUP",
            "principal_permissions": [{
                "principal_id": "grp-1", "principal_name": "Analyst",
                "permission": "READ_ONLY", "shared_permission": "READ_ONLY",
                "group_permission": []}]}]}]}
    assert permission_rows(payload) == [{
        "guid": "obj-guid-1", "name": "T2_PUBLISH", "type": "LOGICAL_TABLE",
        "principal_type": "USER_GROUP", "principal_id": "grp-1",
        "principal_name": "Analyst", "permission": "READ_ONLY",
        "shared_permission": "READ_ONLY",
    }]


def test_permission_rows_accepts_a_bare_list():
    payload = [{"metadata_id": "g", "metadata_name": "n", "metadata_type": "LOGICAL_COLUMN",
                "principal_permission_info": [{
                    "principal_type": "USER",
                    "principal_permissions": [{"principal_id": "u", "principal_name": "su",
                                               "permission": "MODIFY"}]}]}]
    rows = permission_rows(payload)
    assert rows[0]["principal_name"] == "su"
    assert rows[0]["shared_permission"] == ""


def test_permission_rows_tolerates_empty_and_missing_sections():
    assert permission_rows(None) == []
    assert permission_rows({}) == []
    assert permission_rows({"metadata_permission_details": [{"metadata_id": "g"}]}) == []
