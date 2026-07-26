"""Unit tests for ts_cli.commands.share — payload builders and pure helpers."""
from __future__ import annotations

import pytest

from ts_cli.commands.share import build_share_payload, expand_uniform_grants, resolve_guids


def _perm(group="Analyst", mode="READ_ONLY"):
    return [{"principal": {"type": "USER_GROUP", "identifier": group}, "share_mode": mode}]


def test_build_share_payload_puts_message_at_the_top_level():
    """The single fact that blocks every share call if it is wrong.

    Every published example nests `message` inside `notification`; the API rejects that
    with `Variable "$message" of required type "String!" was not provided`. The
    shareMetadata request schema agrees with the live behaviour: message and
    notify_on_share are top-level, and message is required.
    """
    payload = build_share_payload(["guid-1"], "LOGICAL_TABLE", _perm(),
                                  message="granting tenant access")
    assert payload["message"] == "granting tenant access"
    assert "notification" not in payload
    assert payload["notify_on_share"] is False


def test_build_share_payload_shape():
    payload = build_share_payload(["g1", "g2"], "LOGICAL_COLUMN", _perm(),
                                  message="m", notify_on_share=True)
    assert payload == {
        "metadata_type": "LOGICAL_COLUMN",
        "metadata_identifiers": ["g1", "g2"],
        "permissions": _perm(),
        "message": "m",
        "notify_on_share": True,
    }


def test_build_share_payload_accepts_logical_column():
    """LOGICAL_COLUMN is absent from the docs' supported-object list but works."""
    payload = build_share_payload(["c1"], "LOGICAL_COLUMN", _perm(), message="m")
    assert payload["metadata_type"] == "LOGICAL_COLUMN"


def test_build_share_payload_dedupes_identifiers_preserving_order():
    payload = build_share_payload(["g2", "g1", "g2"], "LOGICAL_TABLE", _perm(), message="m")
    assert payload["metadata_identifiers"] == ["g2", "g1"]


def test_build_share_payload_rejects_unsupported_type():
    with pytest.raises(ValueError, match="CONNECTION"):
        build_share_payload(["g1"], "CONNECTION", _perm(), message="m")


def test_build_share_payload_rejects_empty_identifiers():
    with pytest.raises(ValueError, match="at least one object"):
        build_share_payload([], "LOGICAL_TABLE", _perm(), message="m")


def test_build_share_payload_rejects_empty_permissions():
    with pytest.raises(ValueError, match="at least one principal"):
        build_share_payload(["g1"], "LOGICAL_TABLE", [], message="m")


def test_build_share_payload_rejects_blank_message():
    """`message` is required by the schema, so an empty one fails server-side."""
    with pytest.raises(ValueError, match="message"):
        build_share_payload(["g1"], "LOGICAL_TABLE", _perm(), message="   ")


def test_client_accepts_an_explicit_org_overriding_the_env(monkeypatch):
    """Per-Org grants need a per-Org token without mutating process state."""
    from ts_cli import client as client_module

    profiles = {"p": {"base_url": "https://example.thoughtspot.cloud",
                      "token_env": "THOUGHTSPOT_TOKEN_P"}}
    monkeypatch.setattr(client_module, "load_profiles", lambda: profiles)
    monkeypatch.setenv("TS_ORG", "Primary")

    scoped = client_module.ThoughtSpotClient("p", org="ORG1")
    assert scoped._org == "ORG1"
    assert "org1" in scoped._cache_key()

    default = client_module.ThoughtSpotClient("p")
    assert default._org == "Primary"


# ---------------------------------------------------------------------------
# ts share resolve — the pure helpers
# ---------------------------------------------------------------------------

_OBJECTS = [
    {"guid": "tbl-1", "name": "T2_PUBLISH", "type": "LOGICAL_TABLE", "subtype": "",
     "columns": [{"guid": "col-prod", "name": "PROD_NM"},
                 {"guid": "col-amt", "name": "AMOUNT"}]},
    {"guid": "lb-1", "name": "Sales LB", "type": "LIVEBOARD", "subtype": "", "columns": []},
]


def test_expand_uniform_grants_object_level_across_orgs_and_groups():
    grants = expand_uniform_grants(_OBJECTS, ["ORG1", "ORG2"], ["Analyst"], "READ_ONLY")
    assert len(grants) == 4  # 2 objects x 2 orgs x 1 group
    assert {g["org_name"] for g in grants} == {"ORG1", "ORG2"}
    assert all(g["column_name"] == "" for g in grants)
    assert all(g["share_mode"] == "READ_ONLY" for g in grants)


def test_expand_uniform_grants_column_level_only_touches_named_columns():
    grants = expand_uniform_grants(_OBJECTS, ["ORG1"], ["Analyst"], "READ_ONLY",
                                   columns=["PROD_NM"])
    assert [g["column_name"] for g in grants] == ["PROD_NM"]
    assert grants[0]["object_identifier"] == "T2_PUBLISH"


def test_expand_uniform_grants_rejects_a_column_no_object_has():
    with pytest.raises(ValueError, match="NOPE"):
        expand_uniform_grants(_OBJECTS, ["ORG1"], ["Analyst"], "READ_ONLY", columns=["NOPE"])


def test_expand_uniform_grants_requires_groups():
    with pytest.raises(ValueError, match="--group"):
        expand_uniform_grants(_OBJECTS, ["ORG1"], [], "READ_ONLY")


def test_expand_uniform_grants_requires_orgs():
    with pytest.raises(ValueError, match="--org"):
        expand_uniform_grants(_OBJECTS, [], ["Analyst"], "READ_ONLY")


def test_expand_uniform_grants_rejects_an_unknown_share_mode():
    with pytest.raises(ValueError, match="WRITE"):
        expand_uniform_grants(_OBJECTS, ["ORG1"], ["Analyst"], "WRITE")


def test_resolve_guids_fills_object_and_column_guids():
    grants = [{"org_name": "ORG1", "object_identifier": "T2_PUBLISH",
               "object_type": "LOGICAL_TABLE", "column_name": "PROD_NM",
               "group_name": "Analyst", "share_mode": "READ_ONLY"}]
    resolved = resolve_guids(grants, _OBJECTS)
    assert resolved[0]["object_guid"] == "tbl-1"
    assert resolved[0]["column_guid"] == "col-prod"


def test_resolve_guids_matches_an_object_by_guid_as_well_as_name():
    grants = [{"org_name": "ORG1", "object_identifier": "tbl-1",
               "object_type": "LOGICAL_TABLE", "column_name": "",
               "group_name": "Analyst", "share_mode": "READ_ONLY"}]
    assert resolve_guids(grants, _OBJECTS)[0]["object_guid"] == "tbl-1"


def test_resolve_guids_rejects_an_object_not_in_the_envelope():
    grants = [{"org_name": "ORG1", "object_identifier": "MISSING",
               "object_type": "LOGICAL_TABLE", "column_name": "",
               "group_name": "Analyst", "share_mode": "READ_ONLY"}]
    with pytest.raises(ValueError, match="MISSING"):
        resolve_guids(grants, _OBJECTS)


def test_resolve_guids_rejects_a_column_the_table_does_not_have():
    grants = [{"org_name": "ORG1", "object_identifier": "T2_PUBLISH",
               "object_type": "LOGICAL_TABLE", "column_name": "NOPE",
               "group_name": "Analyst", "share_mode": "READ_ONLY"}]
    with pytest.raises(ValueError, match="NOPE"):
        resolve_guids(grants, _OBJECTS)


def test_resolve_guids_corrects_a_manifest_object_type_from_the_envelope():
    """A manifest that guessed LOGICAL_TABLE for a Liveboard is corrected, not trusted."""
    grants = [{"org_name": "ORG1", "object_identifier": "Sales LB",
               "object_type": "LOGICAL_TABLE", "column_name": "",
               "group_name": "Analyst", "share_mode": "READ_ONLY"}]
    assert resolve_guids(grants, _OBJECTS)[0]["object_type"] == "LIVEBOARD"
