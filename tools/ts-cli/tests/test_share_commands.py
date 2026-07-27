"""Unit tests for the `ts share` command layer — payload builders and pure helpers.

`share.py` holds the payload builder, the shared lookups and the error translator;
`share_planning.py` holds the export/resolve/apply pipeline and its pure helpers.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.commands.share import build_share_payload, explain_share_error
from ts_cli.commands.share_planning import expand_uniform_grants, resolve_guids

# See the Global Constraints section: `runner` is stream-separated so result.stdout is
# parseable JSON; `msg_runner` mixes, which is the only way to see a manual stderr print.
try:
    runner = CliRunner(mix_stderr=False)
except TypeError:            # Click >= 8.2 removed the parameter
    runner = CliRunner()
msg_runner = CliRunner()


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
# ts share resolve -- _try_search / _resolve_object and the SystemExit gotcha
# ---------------------------------------------------------------------------

def test_try_search_swallows_a_system_exit():
    """`client.py` raises SystemExit (not Exception) on an API error. `_try_search`'s
    whole documented purpose is to swallow one candidate's failure so the next can
    run; before the fix `except Exception` let a SystemExit through and killed the
    process instead.
    """
    from ts_cli.commands.share import _try_search

    class _Client:
        @staticmethod
        def post(_path, json=None):
            raise SystemExit(1)

    assert _try_search(_Client(), {"identifier": "T2_PUBLISH"}, 10) == []


def test_try_search_swallows_a_plain_exception():
    from ts_cli.commands.share import _try_search

    class _Client:
        @staticmethod
        def post(_path, json=None):
            raise RuntimeError("boom")

    assert _try_search(_Client(), {"identifier": "T2_PUBLISH"}, 10) == []


def test_resolve_object_falls_through_to_a_typed_probe_after_a_system_exit():
    """Live-observed 2026-07-27: resolving a table BY NAME probes untyped first
    (`{"identifier": name}`), which the platform rejects with HTTP 400 code 10002
    ("Specify the metadata_type for identifier T2_PUBLISH"). `client.py` turns that
    into a SystemExit. Before the fix, `_resolve_object` died right there instead of
    falling through to the typed-candidate loop, so resolving a table BY NAME failed
    outright even though the same call by GUID worked.
    """
    from ts_cli.commands.share import GRANTABLE_TYPES, _resolve_object

    class _Resp:
        def __init__(self, hits):
            self._hits = hits

        def json(self):
            return self._hits

    class _Client:
        @staticmethod
        def post(_path, json=None):
            body = json or {}
            metadata = (body.get("metadata") or [{}])[0]
            if "type" not in metadata:
                raise SystemExit(1)  # the untyped probe's expected 400
            if metadata["type"] == GRANTABLE_TYPES[0]:
                return _Resp([{"metadata_id": "tbl-1", "metadata_name": "T2_PUBLISH",
                              "metadata_type": GRANTABLE_TYPES[0],
                              "metadata_header": {"id": "tbl-1", "name": "T2_PUBLISH"}}])
            return _Resp([])

    resolved = _resolve_object(_Client(), "T2_PUBLISH")
    assert resolved == {"guid": "tbl-1", "name": "T2_PUBLISH",
                        "type": GRANTABLE_TYPES[0], "subtype": ""}


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


# ---------------------------------------------------------------------------
# ts share apply — error translation
# ---------------------------------------------------------------------------

def test_explain_share_error_translates_the_nested_message_mistake():
    body = ('{"error":{"message":"Variable \\"$message\\" of required type '
            '\\"String!\\" was not provided."}}')
    text = explain_share_error(body)
    assert text is not None
    assert "top level" in text.lower()
    assert "notification" in text


def test_explain_share_error_translates_a_missing_principal():
    body = ('{"error":{"message":{"code":13003,"debug":"Principal object does not exist '
            'corresponding to the identifier Analystt"}}}')
    text = explain_share_error(body)
    assert text is not None
    assert "Analystt" in text
    assert "per-Org" in text


def test_explain_share_error_returns_none_for_an_unrecognised_body():
    assert explain_share_error('{"error":{"message":"something else entirely"}}') is None
    assert explain_share_error("") is None


# ---------------------------------------------------------------------------
# Org scoping — the silent-wrong-org guard
# ---------------------------------------------------------------------------

def _patch_org_index(monkeypatch, index):
    """Stub the orgs/search lookup and clear the per-profile cache."""
    from ts_cli.commands import share as share_module

    share_module._ORG_INDEX_CACHE.clear()
    monkeypatch.setattr(share_module, "_org_name_to_id", lambda client, key: index)
    monkeypatch.setattr(share_module, "ThoughtSpotClient",
                        lambda profile_name, org=None: ("client", profile_name, org))
    monkeypatch.setattr(share_module, "resolve_profile", lambda p: p or "p")
    return share_module


def test_client_for_org_resolves_a_name_to_its_numeric_id(monkeypatch):
    """auth/token/full honours org_id (int) and SILENTLY IGNORES a name.

    Verified live 2026-07-26 on nebula-damian-alias: TS_ORG=ORG1 minted a token whose
    current_org was {id: 0, name: Primary}. Passing the name through would apply a
    tenant's grants in the Primary Org while reporting success, so the name must be
    resolved to its id before the client is built.
    """
    share_module = _patch_org_index(monkeypatch, {"ORG1": 12750490, "Primary": 0})
    assert share_module._client_for_org("p", "ORG1") == ("client", "p", "12750490")


def test_client_for_org_passes_a_numeric_org_through(monkeypatch):
    share_module = _patch_org_index(monkeypatch, {"ORG1": 12750490})
    assert share_module._client_for_org("p", "12750490") == ("client", "p", "12750490")


def test_client_for_org_without_an_org_builds_an_unscoped_client(monkeypatch):
    share_module = _patch_org_index(monkeypatch, {"ORG1": 12750490})
    assert share_module._client_for_org("p") == ("client", "p", None)


def test_client_for_org_refuses_an_unknown_org_name(monkeypatch):
    import typer

    share_module = _patch_org_index(monkeypatch, {"ORG1": 12750490, "Primary": 0})
    with pytest.raises(typer.BadParameter, match="NoSuchOrg"):
        share_module._client_for_org("p", "NoSuchOrg")


def test_assert_org_context_refuses_a_session_in_the_wrong_org(monkeypatch):
    """The defence-in-depth guard: org scoping can fail silently, so read it back."""
    import typer

    from ts_cli.commands import share as share_module

    share_module._ORG_INDEX_CACHE.clear()
    monkeypatch.setattr(share_module, "_org_name_to_id",
                        lambda client, key: {"ORG1": 12750490, "Primary": 0})
    monkeypatch.setattr(share_module, "resolve_profile", lambda p: p or "p")
    monkeypatch.setattr(share_module, "ThoughtSpotClient",
                        lambda profile_name, org=None: ("client", profile_name, org))

    class _Resp:
        @staticmethod
        def json():
            return {"current_org": {"id": 0, "name": "Primary"}}

    class _Client:
        @staticmethod
        def get(_path):
            return _Resp()

    with pytest.raises(typer.BadParameter, match="Primary"):
        share_module.assert_org_context(_Client(), "ORG1", "p")


def test_assert_org_context_accepts_a_matching_session(monkeypatch):
    from ts_cli.commands import share as share_module

    share_module._ORG_INDEX_CACHE.clear()
    monkeypatch.setattr(share_module, "_org_name_to_id",
                        lambda client, key: {"ORG1": 12750490})
    monkeypatch.setattr(share_module, "resolve_profile", lambda p: p or "p")
    monkeypatch.setattr(share_module, "ThoughtSpotClient",
                        lambda profile_name, org=None: ("client", profile_name, org))

    class _Resp:
        @staticmethod
        def json():
            return {"current_org": {"id": 12750490, "name": "ORG1"}}

    class _Client:
        @staticmethod
        def get(_path):
            return _Resp()

    assert share_module.assert_org_context(_Client(), "ORG1", "p") is None


# ---------------------------------------------------------------------------
# ts share resolve -- the Strict Object Mode warning
# ---------------------------------------------------------------------------
#
# Column-level sharing (CLS) only takes effect when the cluster is in Strict Object
# Mode, and that flag cannot be read through the REST API (parent spec
# `2026-07-26-ts-security-sharing-design.md` §6, open item #2). `resolve` warns once,
# to stderr, whenever the resolved plan carries a column-level grant. `--skip-group-check`
# keeps these tests offline: no client is ever constructed.

def _write_envelope(tmp_path, objects=_OBJECTS):
    path = tmp_path / "export.json"
    path.write_text(json.dumps({"objects": objects, "orgs": ["ORG1"], "current_grants": {}}))
    return str(path)


def _resolve_args(input_path, *extra):
    return ["share", "resolve", "--input", input_path, "--org", "ORG1",
            "--source", "uniform", "--group", "Analyst", "--share-mode", "READ_ONLY",
            "--skip-group-check", *extra]


def test_resolve_warns_about_strict_object_mode_for_a_column_grant(tmp_path):
    result = msg_runner.invoke(app, _resolve_args(_write_envelope(tmp_path),
                                                   "--column", "PROD_NM"))
    assert result.exit_code == 0, result.output
    assert "Strict Object Mode" in result.output


def test_resolve_does_not_warn_for_an_object_grants_only_plan(tmp_path):
    result = msg_runner.invoke(app, _resolve_args(_write_envelope(tmp_path)))
    assert result.exit_code == 0, result.output
    assert "Strict Object Mode" not in result.output


def test_resolve_warns_once_for_several_column_grants(tmp_path):
    result = msg_runner.invoke(app, _resolve_args(
        _write_envelope(tmp_path), "--column", "PROD_NM", "--column", "AMOUNT"))
    assert result.exit_code == 0, result.output
    assert result.output.count("Strict Object Mode") == 1


def test_resolve_column_grant_warning_does_not_change_the_exit_code_or_leak_to_stdout(
        tmp_path):
    # `runner`, not `msg_runner`: stdout must stay pure JSON with the warning kept off
    # it entirely, and the plan a column grant produces must exit the same as any other.
    result = runner.invoke(app, _resolve_args(_write_envelope(tmp_path),
                                              "--column", "PROD_NM"))
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["summary"]["column_grants"] == 1
    assert "Strict Object Mode" not in result.stdout


# ---------------------------------------------------------------------------
# Org-scoped resolution -- the blocker found in the 2026-07-27 live round
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, hits):
        self._hits = hits

    def json(self):
        return self._hits


def _hit(guid, name, obj_type):
    return {"metadata_id": guid, "metadata_name": name, "metadata_type": obj_type,
            "metadata_header": {"id": guid, "name": name}}


class _OrgClient:
    """A client that can see exactly one object, the way an Org-scoped session does.

    The untyped probe raises SystemExit for an identifier it cannot see, mirroring the
    platform's real 400 (code 10002, "Specify the metadata_type for identifier ..."),
    which is what `client.py` turns into a SystemExit.
    """

    def __init__(self, visible_guid=None, visible_name=None,
                 obj_type="LOGICAL_TABLE", untyped_works=True):
        self.visible_guid = visible_guid
        self.visible_name = visible_name
        self.obj_type = obj_type
        self.untyped_works = untyped_works

    def post(self, _path, json=None):
        body = json or {}
        metadata = (body.get("metadata") or [{}])[0]
        identifier = metadata.get("identifier")
        mine = identifier in (self.visible_guid, self.visible_name)
        if "type" not in metadata:
            if mine and self.untyped_works:
                return _Resp([_hit(self.visible_guid, self.visible_name, self.obj_type)])
            raise SystemExit(1)          # the platform's expected 400
        if mine and metadata["type"] == self.obj_type:
            return _Resp([_hit(self.visible_guid, self.visible_name, self.obj_type)])
        return _Resp([])


def test_find_object_returns_none_instead_of_raising_when_not_visible():
    """`_resolve_object_in_orgs` can only try the next Org if a miss is a return value.

    A miss means "not visible to THIS client's Org", not "does not exist" -- so it must
    not raise, or the loop over Orgs can never reach the Org that owns the object.
    """
    from ts_cli.commands.share import _find_object

    assert _find_object(_OrgClient(visible_guid="other", visible_name="OTHER"),
                        "T4_PER_ORG") is None


def test_find_object_matches_a_guid_through_the_typed_fallback():
    """The secondary half of the 2026-07-27 blocker.

    The typed fallback used to filter on `metadata_name == identifier` only, which a
    GUID can never satisfy. So whenever the untyped probe missed -- which it does for
    any identifier unknown in the current Org -- a GUID that the typed search had just
    returned still fell through to "Could not resolve".
    """
    from ts_cli.commands.share import _find_object

    client = _OrgClient(visible_guid="d3a688f2", visible_name="T4_PER_ORG",
                        untyped_works=False)
    found = _find_object(client, "d3a688f2")
    assert found is not None
    assert found["guid"] == "d3a688f2"
    assert found["name"] == "T4_PER_ORG"


def test_find_object_still_refuses_an_ambiguous_name(monkeypatch):
    """Ambiguity must RAISE, not return None -- otherwise a caller looping over Orgs
    would swallow a genuine refusal and quietly try somewhere else."""
    import typer

    from ts_cli.commands.share import GRANTABLE_TYPES, _find_object

    class _Ambiguous:
        @staticmethod
        def post(_path, json=None):
            body = json or {}
            metadata = (body.get("metadata") or [{}])[0]
            if "type" not in metadata:
                raise SystemExit(1)
            if metadata["type"] == GRANTABLE_TYPES[0]:
                return _Resp([_hit("g1", "DUPE", GRANTABLE_TYPES[0]),
                              _hit("g2", "DUPE", GRANTABLE_TYPES[0])])
            return _Resp([])

    with pytest.raises(typer.BadParameter) as excinfo:
        _find_object(_Ambiguous(), "DUPE")
    assert "matches 2" in str(excinfo.value)


def test_resolve_object_in_orgs_finds_an_object_native_to_a_tenant_org(monkeypatch):
    """The blocker itself.

    `ts share export <guid> --org ORG1` resolved with the DEFAULT-Org client and scoped
    only the permissions read, so any object ORG1 owns failed outright -- exactly the
    case tenant-Org column security is about. Live-verified 2026-07-27 on
    T4_PER_ORG (orgIds=[12750490]).
    """
    from ts_cli.commands import share as share_module

    default_client = _OrgClient(visible_guid="primary-tbl", visible_name="T2_PUBLISH")
    org1_client = _OrgClient(visible_guid="d3a688f2", visible_name="T4_PER_ORG")
    handed_out = []

    def _fake_client_for_org(_profile, org=None):
        handed_out.append(org)
        return org1_client if org == "ORG1" else default_client

    monkeypatch.setattr(share_module, "_client_for_org", _fake_client_for_org)

    resolved, client = share_module._resolve_object_in_orgs("p", ["ORG1"], "d3a688f2")
    assert resolved["name"] == "T4_PER_ORG"
    # The client is returned so columns are listed through the Org that could see it.
    assert client is org1_client
    # Default Org tried first, so the common case costs no extra round-trip.
    assert handed_out == [None, "ORG1"]


def test_resolve_object_in_orgs_prefers_the_default_org(monkeypatch):
    """Unchanged behaviour for a Primary-owned object: resolved in the default Org, and
    no tenant-Org client is ever constructed."""
    from ts_cli.commands import share as share_module

    default_client = _OrgClient(visible_guid="primary-tbl", visible_name="T2_PUBLISH")
    handed_out = []

    def _fake_client_for_org(_profile, org=None):
        handed_out.append(org)
        return default_client

    monkeypatch.setattr(share_module, "_client_for_org", _fake_client_for_org)

    resolved, client = share_module._resolve_object_in_orgs("p", ["ORG1"], "primary-tbl")
    assert resolved["name"] == "T2_PUBLISH"
    assert client is default_client
    assert handed_out == [None]


def test_resolve_object_in_orgs_names_every_org_it_tried(monkeypatch):
    from ts_cli.commands import share as share_module
    import typer

    blind = _OrgClient(visible_guid="nope", visible_name="NOPE")
    monkeypatch.setattr(share_module, "_client_for_org",
                        lambda _profile, org=None: blind)

    with pytest.raises(typer.BadParameter) as excinfo:
        share_module._resolve_object_in_orgs("p", ["ORG1", "ORG2"], "MISSING")
    message = str(excinfo.value)
    assert "ORG1" in message and "ORG2" in message
