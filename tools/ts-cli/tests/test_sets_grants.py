from unittest.mock import MagicMock

from ts_cli.sets.grants import UNKNOWN_GRANTS, fetch_grants, parse_permissions, provenance


def g(pid, perm, name=None, ptype="USER"):
    return {"principal_id": pid, "principal_name": name or pid, "principal_type": ptype,
            "permission": perm}


def _prov(set_g, cons=None, owners=()):
    return {x["principal_id"]: x["provenance"] for x in provenance(set_g, cons or {}, set(owners))}


def test_modify_is_direct():
    assert _prov([g("u1", "MODIFY")]) == {"u1": "DIRECT"}


def test_view_by_consumer_owner_is_required():
    assert _prov([g("u1", "READ_ONLY")], owners={"u1"}) == {"u1": "REQUIRED"}


def test_view_with_consumer_grant_is_explained():
    assert _prov([g("grpA", "READ_ONLY", ptype="USER_GROUP")],
                 {"a1": [g("grpA", "READ_ONLY", ptype="USER_GROUP")]}) == {"grpA": "EXPLAINED"}


def test_required_beats_explained():
    assert _prov([g("u1", "READ_ONLY")], {"a1": [g("u1", "MODIFY")]}, owners={"u1"}) == {"u1": "REQUIRED"}


def test_unrelated_view_is_unexplained():
    assert _prov([g("u9", "READ_ONLY")], {"a1": [g("u1", "READ_ONLY")]}) == {"u9": "UNEXPLAINED"}


def test_group_membership_is_not_expanded():
    # user's view grant is not explained by their group's grant on the Answer
    assert _prov([g("u1", "READ_ONLY")], {"a1": [g("grpA", "READ_ONLY", ptype="USER_GROUP")]}) == {"u1": "UNEXPLAINED"}


RESP = {"metadata_permission_details": [
    {"metadata_id": "s1", "principal_permission_info": [
        {"principal_type": "USER", "principal_permissions": [
            {"principal_id": "u1", "principal_name": "pin", "permission": "MODIFY"}]}]},
    {"metadata_id": "a1", "principal_permission_info": [
        {"principal_type": "USER_GROUP", "principal_permissions": [
            {"principal_id": "gA", "principal_name": "A", "permission": "READ_ONLY"}]}]}]}


def test_parse_permissions():
    p = parse_permissions(RESP)
    assert p["s1"] == [g("u1", "MODIFY", "pin")]
    assert p["a1"] == [g("gA", "READ_ONLY", "A", "USER_GROUP")]


def test_parse_permissions_keys_by_metadata_id_not_type():
    # Live: the Set reads back as COLUMN, an Answer as QUESTION_ANSWER_BOOK or ANSWER.
    resp = {"metadata_permission_details": [
        dict(RESP["metadata_permission_details"][0], metadata_type="COLUMN"),
        dict(RESP["metadata_permission_details"][1], metadata_type="QUESTION_ANSWER_BOOK")]}
    assert set(parse_permissions(resp)) == {"s1", "a1"}


def test_fetch_grants_uses_defined_and_typed_objects():
    seen = {}
    def post(path, json=None, **kw):
        seen.update(json); return MagicMock(json=lambda: RESP)
    c = MagicMock(); c.post.side_effect = post
    cons = {"dependents": [{"guid": "a1", "type": "ANSWER"}, {"guid": "l1", "type": "LIVEBOARD"}]}
    out = fetch_grants(c, "s1", cons)
    assert seen["permission_type"] == "DEFINED"
    assert seen["record_offset"] == 0 and seen["record_size"] == -1
    assert {"identifier": "s1", "type": "LOGICAL_COLUMN"} in seen["metadata"]
    assert {"identifier": "l1", "type": "LIVEBOARD"} in seen["metadata"]
    assert set(out) == {"s1", "a1"}


def test_fetch_grants_failure_is_none():
    c = MagicMock(); c.post.side_effect = SystemExit(1)
    assert fetch_grants(c, "s1", {"dependents": []}) is None


def _client_returning(body):
    c = MagicMock(); c.post.return_value = MagicMock(json=lambda: body)
    return c


def test_missing_set_entry_is_unknown(capsys):
    # DEFINED returns a PRESENT entry with an empty list for "nothing shared" (share.py,
    # live 2026-07-26), so an absent Set entry is an anomaly and must read as UNKNOWN.
    resp = {"metadata_permission_details": [RESP["metadata_permission_details"][1]]}
    out = fetch_grants(_client_returning(resp), "s1", {"dependents": [{"guid": "a1", "type": "ANSWER"}]})
    assert out is None
    assert "s1" in capsys.readouterr().err


def test_present_empty_set_entry_is_no_grants():
    resp = {"metadata_permission_details": [{"metadata_id": "s1", "principal_permission_info": []}]}
    assert fetch_grants(_client_returning(resp), "s1", {"dependents": []}) == {"s1": []}


def test_missing_consumer_entry_is_tolerated():
    resp = {"metadata_permission_details": [RESP["metadata_permission_details"][0]]}
    out = fetch_grants(_client_returning(resp), "s1", {"dependents": [{"guid": "a1", "type": "ANSWER"}]})
    assert set(out) == {"s1"}


def test_empty_body_is_none():
    assert fetch_grants(_client_returning({}), "s1", {"dependents": []}) is None


def test_non_list_details_is_none(capsys):
    body = {"metadata_permission_details": {"metadata_id": "s1"}}
    assert fetch_grants(_client_returning(body), "s1", {"dependents": []}) is None
    assert "metadata_permission_details" in capsys.readouterr().err


def test_non_dict_body_is_none():
    assert fetch_grants(_client_returning([]), "s1", {"dependents": []}) is None


def test_json_decode_error_is_none(capsys):
    def boom():
        raise ValueError("not json")
    c = MagicMock(); c.post.return_value = MagicMock(json=boom)
    assert fetch_grants(c, "s1", {"dependents": []}) is None
    assert "fetch-permissions failed for s1" in capsys.readouterr().err


def test_no_access_is_dropped_from_provenance():
    assert _prov([g("u1", "NO_ACCESS"), g("u2", "READ_ONLY")]) == {"u2": "UNEXPLAINED"}


def test_unknown_grants_sentinel():
    assert UNKNOWN_GRANTS == [{"principal_id": "", "principal_name": "", "principal_type": "",
                               "permission": "", "provenance": "UNKNOWN"}]
