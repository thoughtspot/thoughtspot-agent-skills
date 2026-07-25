"""Unit tests for the Orgs Publishing primitives.

Covers the pure payload builders and response interpreters behind
`ts variables create/delete`, `ts metadata parameterize/unparameterize`, and
`ts publish push/unpush/status`. No live connection required.

Expected shapes come from the 2026-07-25 live verification on
nebula-damian-alias, recorded in
docs/superpowers/specs/2026-07-25-ts-publish-orgs-design.md §2.5.
"""
from __future__ import annotations

import pytest

from ts_cli.commands.parameterize import (
    build_parameterize_payload,
    build_unparameterize_payload,
    shared_token_warning,
)
from ts_cli.commands.publish import (
    build_publish_payload,
    build_unpublish_payload,
    explain_publish_error,
    publication_rows,
)
from ts_cli.commands.variables import build_create_variable_payload


# ---------------------------------------------------------------------------
# ts variables create
# ---------------------------------------------------------------------------

def test_create_table_mapping_payload():
    assert build_create_variable_payload("TABLE_MAPPING", "apj_schema") == {
        "type": "TABLE_MAPPING", "name": "apj_schema", "is_sensitive": False,
    }


def test_create_marks_sensitive():
    payload = build_create_variable_payload("CONNECTION_PROPERTY", "sf_password", sensitive=True)
    assert payload["is_sensitive"] is True


def test_create_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unknown variable type"):
        build_create_variable_payload("NOT_A_TYPE", "x")


def test_formula_variable_requires_data_type():
    with pytest.raises(ValueError, match="data_type is required"):
        build_create_variable_payload("FORMULA_VARIABLE", "region_var")


def test_formula_variable_carries_data_type():
    payload = build_create_variable_payload("FORMULA_VARIABLE", "region_var", data_type="VARCHAR")
    assert payload["data_type"] == "VARCHAR"


def test_data_type_rejected_for_non_formula_variable():
    # The API accepts data_type only for FORMULA_VARIABLE; sending it elsewhere
    # is a caller mistake worth catching before the round trip.
    with pytest.raises(ValueError, match="only valid for FORMULA_VARIABLE"):
        build_create_variable_payload("TABLE_MAPPING", "apj_schema", data_type="VARCHAR")


def test_data_type_value_is_not_validated_client_side():
    # The published docs give two conflicting data-type lists (VARCHAR/BIGINT/INT/FLOAT
    # vs VARCHAR/INT32/INT64/DOUBLE), so the value is passed through and the API
    # is left to reject it. Only presence is enforced.
    payload = build_create_variable_payload("FORMULA_VARIABLE", "v", data_type="SOMETHING_NEW")
    assert payload["data_type"] == "SOMETHING_NEW"


# ---------------------------------------------------------------------------
# ts metadata parameterize
# ---------------------------------------------------------------------------

def test_parameterize_logical_table_derives_attribute_field_type():
    # field_type is fully determined by metadata_type, so callers never pass it
    # and can never hit the code-10002 type mismatch by getting it wrong.
    assert build_parameterize_payload("LOGICAL_TABLE", "guid-1", ["schemaName"], "apj_schema") == {
        "metadata_type": "LOGICAL_TABLE",
        "metadata_identifier": "guid-1",
        "field_type": "ATTRIBUTE",
        "field_names": ["schemaName"],
        "variable_identifier": "apj_schema",
    }


def test_parameterize_connection_derives_connection_property_field_type():
    payload = build_parameterize_payload("CONNECTION", "conn-1", ["accountName"], "acct_var")
    assert payload["field_type"] == "CONNECTION_PROPERTY"


def test_parameterize_rejects_unknown_logical_table_field():
    with pytest.raises(ValueError, match="dbName"):
        build_parameterize_payload("LOGICAL_TABLE", "guid-1", ["dbName"], "v")


def test_parameterize_allows_arbitrary_connection_property_names():
    # Connection property names are warehouse-specific and open-ended.
    payload = build_parameterize_payload("CONNECTION", "c", ["someVendorProp"], "v")
    assert payload["field_names"] == ["someVendorProp"]


def test_parameterize_rejects_empty_field_names():
    with pytest.raises(ValueError, match="at least one field"):
        build_parameterize_payload("LOGICAL_TABLE", "guid-1", [], "v")


def test_shared_token_warning_fires_for_multiple_fields():
    # Verified live: binding one variable to two fields writes the SAME ${token}
    # into both, which is almost never intended.
    warning = shared_token_warning(["databaseName", "schemaName"], "apj_schema")
    assert warning is not None
    assert "apj_schema" in warning
    assert "same value" in warning


def test_shared_token_warning_silent_for_single_field():
    assert shared_token_warning(["schemaName"], "apj_schema") is None


def test_unparameterize_requires_restore_value():
    with pytest.raises(ValueError, match="restore value"):
        build_unparameterize_payload("LOGICAL_TABLE", "guid-1", "schemaName", "")


def test_unparameterize_payload():
    assert build_unparameterize_payload("LOGICAL_TABLE", "g", "schemaName", "ALIAS_TESTS") == {
        "metadata_type": "LOGICAL_TABLE",
        "metadata_identifier": "g",
        "field_type": "ATTRIBUTE",
        "field_name": "schemaName",
        "value": "ALIAS_TESTS",
    }


# ---------------------------------------------------------------------------
# ts publish push / unpush
# ---------------------------------------------------------------------------

def test_publish_payload():
    assert build_publish_payload(["g1", "g2"], "LOGICAL_TABLE", ["ORG1"]) == {
        "metadata": [{"identifier": "g1", "type": "LOGICAL_TABLE"},
                     {"identifier": "g2", "type": "LOGICAL_TABLE"}],
        "org_identifiers": ["ORG1"],
        "skip_validation": False,
    }


def test_publish_deduplicates_guids_preserving_order():
    payload = build_publish_payload(["g2", "g1", "g2"], "LOGICAL_TABLE", ["ORG1"])
    assert [m["identifier"] for m in payload["metadata"]] == ["g2", "g1"]


def test_publish_rejects_empty_orgs():
    with pytest.raises(ValueError, match="at least one org"):
        build_publish_payload(["g1"], "LOGICAL_TABLE", [])


def test_publish_rejects_unknown_type():
    with pytest.raises(ValueError, match="CONNECTION"):
        build_publish_payload(["g1"], "CONNECTION", ["ORG1"])


def test_unpublish_defaults_to_including_dependencies():
    # Verified live: with include_dependencies false the Connection stays granted
    # to the target Orgs, so rollback would silently leave it behind.
    payload = build_unpublish_payload(["g1"], "LOGICAL_TABLE", ["ORG1"])
    assert payload["include_dependencies"] is True
    assert payload["force"] is False


# ---------------------------------------------------------------------------
# ts publish status
# ---------------------------------------------------------------------------

_ORG_INDEX = {0: "Primary", 12750490: "ORG1", 535312919: "ORG2", 443705360: "ORG3"}


def test_publication_rows_maps_org_ids_to_names():
    results = [{
        "metadata_id": "g1", "metadata_name": "T1_PUBLISH",
        "metadata_header": {"orgIds": [0, 12750490], "ownerOrgId": 0, "type": "ONE_TO_ONE_LOGICAL"},
    }]
    assert publication_rows(results, _ORG_INDEX) == [{
        "guid": "g1", "name": "T1_PUBLISH", "subtype": "ONE_TO_ONE_LOGICAL",
        "owner_org": "Primary", "published_to": ["ORG1"], "is_published": True,
    }]


def test_publication_rows_excludes_owner_org_from_published_to():
    results = [{"metadata_id": "g", "metadata_name": "n",
                "metadata_header": {"orgIds": [0], "ownerOrgId": 0}}]
    row = publication_rows(results, _ORG_INDEX)[0]
    assert row["published_to"] == []
    assert row["is_published"] is False


def test_publication_rows_falls_back_to_raw_id_for_unknown_org():
    results = [{"metadata_id": "g", "metadata_name": "n",
                "metadata_header": {"orgIds": [0, 999], "ownerOrgId": 0}}]
    assert publication_rows(results, _ORG_INDEX)[0]["published_to"] == ["999"]


def test_publication_rows_tolerates_missing_org_ids():
    results = [{"metadata_id": "g", "metadata_name": "n", "metadata_header": {}}]
    row = publication_rows(results, _ORG_INDEX)[0]
    assert row["published_to"] == []


# ---------------------------------------------------------------------------
# Error interpretation — the platform reports GUIDs and numeric ids
# ---------------------------------------------------------------------------

_VAR_INDEX = {"dcc65c68-7b37-4d25-b8ad-5b6f806c6964": "zz_pubtest_schema"}
_OBJ_INDEX = {"d2c12c11-6560-4810-96b8-4b902bbb82dc": "T2_PUBLISH"}


def test_explain_missing_variable_value_resolves_names():
    body = ('{"error":{"message":{"debug":{"code":13151,"debug":"[\\"Error Message: Variable '
            'dcc65c68-7b37-4d25-b8ad-5b6f806c6964 not defined for orgs [443705360] in which '
            'object d2c12c11-6560-4810-96b8-4b902bbb82dc is to be published\\"]"}}}}')
    msg = explain_publish_error(body, _VAR_INDEX, _ORG_INDEX, _OBJ_INDEX)
    assert "zz_pubtest_schema" in msg
    assert "ORG3" in msg
    assert "T2_PUBLISH" in msg


def test_explain_missing_variable_value_degrades_to_guids():
    body = ("Variable unknown-guid not defined for orgs [12750490] in which object "
            "other-guid is to be published")
    msg = explain_publish_error(body, {}, _ORG_INDEX, {})
    assert "unknown-guid" in msg
    assert "ORG1" in msg


def test_explain_unparameterized_object():
    body = ("No template variable node found in the dependency tree for object "
            "d2c12c11-6560-4810-96b8-4b902bbb82dc")
    msg = explain_publish_error(body, _VAR_INDEX, _ORG_INDEX, _OBJ_INDEX)
    assert "T2_PUBLISH" in msg
    assert "not parameterized" in msg


def test_explain_invalid_org():
    body = 'Error Code: INVALID_ORG ... Org not found corresponding to the org_identifier: NO_SUCH_ORG'
    msg = explain_publish_error(body, {}, _ORG_INDEX, {})
    assert "NO_SUCH_ORG" in msg


def test_explain_invalid_org_strips_enclosing_json_escaping():
    # Regression: the identifier is the last token in the message, so it runs
    # straight into the enclosing JSON's escaping. An earlier pattern captured
    # `NOPE\"]"}}}}` verbatim.
    body = ('{"error":{"message":{"debug":{"code":13151,"debug":"[\\"Error Code: INVALID_ORG '
            'Error Message: Org not found corresponding to the org_identifier: NOPE\\"]"}}}}')
    msg = explain_publish_error(body, {}, _ORG_INDEX, {})
    assert "Org 'NOPE' does not exist" in msg


def test_explain_returns_none_for_unrecognised_error():
    assert explain_publish_error("some other failure", {}, _ORG_INDEX, {}) is None
