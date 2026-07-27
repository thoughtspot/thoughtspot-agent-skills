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


# ---------------------------------------------------------------------------
# code 13152 — unpublish blocked by dependents still published
# ---------------------------------------------------------------------------

# The exact body observed live when unpublishing a Liveboard with
# include_dependencies=true while a sibling Answer still held the same Model.
_13152_BODY = (
    '{"error":{"message":{"debug":{"code":13152,'
    '"incident_id_guid":"a932d3df-1d2c-4be0-8b55-6f2f36ea7d3e",'
    '"debug":"[\\"Operation Unsuccessful. Following objects have dependents present: '
    '{\\\\\\"443705360\\\\\\":[\\\\\\"0930baf3-3224-40dc-be5f-e1b1e827ac29\\\\\\"]}\\"]"}}}}'
)
_MODEL_INDEX = {"0930baf3-3224-40dc-be5f-e1b1e827ac29": "T1_PUBLISH_MODEL"}


def test_explain_dependents_present_resolves_names():
    msg = explain_publish_error(_13152_BODY, {}, _ORG_INDEX, _MODEL_INDEX)
    assert "T1_PUBLISH_MODEL" in msg
    assert "ORG3" in msg


def test_explain_dependents_present_gives_the_working_order():
    # The deadlock has a correct sequence and nothing else documents it.
    msg = explain_publish_error(_13152_BODY, {}, _ORG_INDEX, _MODEL_INDEX)
    assert "--keep-dependencies" in msg


def test_explain_dependents_present_degrades_to_guids():
    msg = explain_publish_error(_13152_BODY, {}, {}, {})
    assert "0930baf3-3224-40dc-be5f-e1b1e827ac29" in msg
    assert "443705360" in msg


def test_explain_dependents_present_handles_several_orgs_and_objects():
    body = ('Following objects have dependents present: '
            '{"12750490":["guid-a","guid-b"],"443705360":["guid-c"]}')
    msg = explain_publish_error(body, {}, _ORG_INDEX, {})
    for token in ("ORG1", "ORG3", "guid-a", "guid-b", "guid-c"):
        assert token in msg


def test_guids_in_body_extraction():
    from ts_cli.commands.publish import guids_in_body
    assert guids_in_body(_13152_BODY) >= {"0930baf3-3224-40dc-be5f-e1b1e827ac29"}
    # the incident id is GUID-shaped too; harmless, it simply will not resolve
    assert guids_in_body("no guids here") == set()


# ---------------------------------------------------------------------------
# Cohort column dependency — a documented limitation reported only by GUID
# ---------------------------------------------------------------------------

_COHORT_BODY = (
    '{"error":{"message":{"debug":{"code":13151,"debug":"[\\"Error Message: '
    'Cannot publish/unpublish objects with Cohort Column as dependency. '
    'ColumnId: f72fafa0-c0d5-4707-9dd8-24364b175e3d\\"]"}}}}'
)


def test_explain_cohort_dependency_names_the_column():
    idx = {"f72fafa0-c0d5-4707-9dd8-24364b175e3d": "RSET_QTY_ON_HAND_BINS"}
    msg = explain_publish_error(_COHORT_BODY, {}, _ORG_INDEX, idx)
    assert "RSET_QTY_ON_HAND_BINS" in msg
    assert "cohort" in msg.lower()
    # Verified live: the block is Model-wide, not usage-based, so the guidance
    # must not suggest that content avoiding the column will publish.
    assert "whether or not they actually use the column" in msg


def test_explain_cohort_dependency_degrades_to_guid():
    msg = explain_publish_error(_COHORT_BODY, {}, _ORG_INDEX, {})
    assert "f72fafa0-c0d5-4707-9dd8-24364b175e3d" in msg


def test_cohort_check_precedes_the_generic_missing_variable_match():
    # Both share code 13151; the cohort text must not fall through to the
    # variable-coverage branch and produce a misleading message.
    msg = explain_publish_error(_COHORT_BODY, {}, _ORG_INDEX, {})
    assert "not defined for org" not in msg


# ---------------------------------------------------------------------------
# BL-146 — the cohort gate must run BEFORE anything is created
# ---------------------------------------------------------------------------

def test_apply_refuses_a_cohort_closure_before_creating_any_variable(tmp_path):
    """The publish API refuses a cohort-carrying closure anyway -- but at the END of the
    run, after the variable exists and the fields are parameterized. Those are left
    behind, and the RE-RUN then dies at variable creation with `HTTP 409 Duplicate
    template variable name`, pointing at an entirely different problem: the operator goes
    hunting a variable conflict instead of the Set that actually blocked them. Recovery
    needs a manual `unparameterize` first, because a bound variable cannot be deleted.

    Observed live 2026-07-27 on T1_PUBLISH_MODEL / RSET_QTY_ON_HAND_BINS.
    """
    import json as _json
    from unittest.mock import patch

    from runners import runner
    from ts_cli.cli import app

    closure = tmp_path / "closure.json"
    closure.write_text(_json.dumps({
        "roots": [{"guid": "m1", "name": "Sales", "type": "model"}],
        "cohort_columns": ["RSET_QTY_BINS"],
        "tables": [], "variables": [],
    }))
    matrix = tmp_path / "matrix.json"
    matrix.write_text(_json.dumps({"coverage": {"complete": True}, "assignments": []}))

    with patch("ts_cli.commands.publish_planning.ThoughtSpotClient") as mock_cls:
        result = runner.invoke(app, ["publish", "apply", "-c", str(closure),
                                     "-m", str(matrix), "--publish-to", "ORG1"])

    assert result.exit_code != 0
    combined = result.stdout + getattr(result, "stderr", "")
    assert "RSET_QTY_BINS" in combined
    # The operator must be told the Set is the problem, not a variable conflict...
    assert "cohort" in combined.lower()
    # ...and told that nothing needs cleaning up, or they will go looking.
    assert "nothing needs cleaning up" in combined
    # Nothing was created: no client was even constructed.
    assert not mock_cls.called


def test_apply_proceeds_when_the_closure_carries_no_cohort_column(tmp_path):
    """The gate must not refuse an ordinary closure -- it narrows the failure, it does not
    add one. Reaching the client construction is enough; the run itself is not exercised
    here."""
    import json as _json
    from unittest.mock import patch

    from runners import runner
    from ts_cli.cli import app

    closure = tmp_path / "closure.json"
    closure.write_text(_json.dumps({
        "roots": [{"guid": "m1", "name": "Sales", "type": "model"}],
        "cohort_columns": [], "tables": [], "variables": [],
    }))
    matrix = tmp_path / "matrix.json"
    matrix.write_text(_json.dumps({"coverage": {"complete": True}, "assignments": []}))

    with patch("ts_cli.commands.publish_planning.ThoughtSpotClient") as mock_cls:
        result = runner.invoke(app, ["publish", "apply", "-c", str(closure),
                                     "-m", str(matrix), "--publish-to", "ORG1"])

    combined = result.stdout + getattr(result, "stderr", "")
    assert "cohort" not in combined.lower()
    assert mock_cls.called
