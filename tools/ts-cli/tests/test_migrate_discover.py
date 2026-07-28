import json
from unittest.mock import MagicMock

import pytest

from ts_cli.migrate import discover
from ts_cli.migrate.schema import ColumnInfo

MODEL_EDOC = json.dumps({
    "guid": "src-guid",
    "model": {
        "name": "Sales",
        "columns": [
            {"name": "Amount", "column_id": "T::AMT", "properties": {"column_type": "MEASURE"}},
            {"name": "Department", "column_id": "T::DEPT", "properties": {"column_type": "ATTRIBUTE"}},
        ],
    },
})
ANSWER_EDOC = json.dumps({
    "guid": "ans-1",
    "answer": {"name": "A1", "search_query": "[Department] [Amount]", "answer_columns": []},
})


def _client_returning(*edocs):
    """Return a mock client whose .post().json() yields export payloads in order."""
    client = MagicMock()
    client.post.side_effect = [MagicMock(json=lambda e=e: [{"edoc": e}]) for e in edocs]
    return client


def test_model_columns_parses_name_binding_and_type():
    cols = discover.model_columns(_client_returning(MODEL_EDOC), "src-guid")
    assert cols[0] == ColumnInfo("Amount", "T::AMT", "MEASURE")
    assert cols[1].name == "Department"


def _search_returning(*rows):
    """Mock client whose metadata/search returns these `(guid, name, owner_org_id)` rows."""
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [
        {"metadata_id": g, "metadata_name": n, "metadata_type": "LOGICAL_TABLE",
         "metadata_header": {"ownerOrgId": o}} for g, n, o in rows])
    return client


def test_name_matches_is_case_insensitive_and_carries_ownership():
    client = _search_returning(("tgt-1", "Sales", 0))
    assert discover.name_matches(client, "sales") == [
        {"guid": "tgt-1", "owner_org_id": 0}]
    posted_filter = client.post.call_args.kwargs["json"]["metadata"][0]
    assert posted_filter["subtypes"] == ["WORKSHEET", "AGGR_WORKSHEET"]


def test_name_matches_drops_partial_name_hits():
    # `name_pattern` is a CONTAINS match, so the API returns near-misses too.
    client = _search_returning(("other", "Sales Archive", 7))
    assert discover.name_matches(client, "Sales") == []


# --- select_source: the tenant's OWN Model -----------------------------------------

def test_select_source_prefers_the_orgs_own_model_over_a_published_master():
    """The master is VISIBLE in the tenant Org once published, so a name match is not
    enough -- treating the master as the source would migrate ITS dependents."""
    candidates = [{"guid": "master", "owner_org_id": 0},
                  {"guid": "tenant-own", "owner_org_id": 12750490}]
    assert discover.select_source(candidates, owner_org_id=12750490) == "tenant-own"


def test_select_source_returns_none_when_the_org_owns_nothing_by_that_name():
    assert discover.select_source([{"guid": "master", "owner_org_id": 0}],
                                 owner_org_id=12750490) is None


def test_select_source_refuses_two_models_it_cannot_tell_apart():
    with pytest.raises(discover.AmbiguousModelName):
        discover.select_source([{"guid": "a", "owner_org_id": 5},
                                {"guid": "b", "owner_org_id": 5}], owner_org_id=5)


# --- select_target: the published master (BL-152) ----------------------------------

def test_select_target_never_returns_the_source_model_itself():
    """The same-Org bug: ORG1 holds its own Model and the published master under one name,
    and a bare lookup returned the source -- pairing it with itself, reporting every column
    MATCHED and READY, and migrating nothing (BL-152)."""
    candidates = [{"guid": "tenant-own", "owner_org_id": 12750490},
                  {"guid": "master", "owner_org_id": 0}]
    assert discover.select_target(candidates, exclude_owner_org_id=12750490,
                                 exclude_guid="tenant-own") == "master"


def test_select_target_excludes_by_guid_even_without_an_org_id():
    # Cross-cluster: Org ids are meaningless across clusters, so the GUID is the only
    # exclusion available and it still has to work on its own.
    candidates = [{"guid": "tenant-own", "owner_org_id": 12750490},
                  {"guid": "master", "owner_org_id": 0}]
    assert discover.select_target(candidates, exclude_guid="tenant-own") == "master"


def test_select_target_keeps_a_primary_owned_target_when_no_org_id_is_excluded():
    """Primary is `0` on every cluster, so a Primary-to-Primary cross-cluster migration
    must not have its legitimate target excluded by id."""
    assert discover.select_target([{"guid": "master", "owner_org_id": 0}],
                                 exclude_owner_org_id=None) == "master"


def test_select_target_returns_none_when_only_the_source_matches():
    assert discover.select_target([{"guid": "tenant-own", "owner_org_id": 12750490}],
                                  exclude_owner_org_id=12750490,
                                  exclude_guid="tenant-own") is None


def test_select_target_refuses_two_candidate_masters():
    with pytest.raises(discover.AmbiguousModelName):
        discover.select_target([{"guid": "a", "owner_org_id": 0},
                                {"guid": "b", "owner_org_id": 3}],
                               exclude_owner_org_id=12750490)


def test_find_target_model_returns_none_when_absent():
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [])
    assert discover.find_target_model(client, "Nope") is None


def test_owning_org_id_reads_the_session_back():
    client = MagicMock()
    client.get.return_value = MagicMock(json=lambda: {"current_org": {"id": 12750490}})
    assert discover.owning_org_id(client) == 12750490


def test_owning_org_id_is_none_when_the_session_read_fails():
    client = MagicMock()
    client.get.side_effect = RuntimeError("401")
    assert discover.owning_org_id(client) is None


def test_used_column_names_finds_referenced_columns_only():
    # Batched contract: ONE export call returns a list of edoc entries, one per dependent.
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [{"edoc": ANSWER_EDOC}])
    used = discover.used_column_names(
        client, dependents=[{"guid": "ans-1"}], source_col_names={"Amount", "Department", "Notes"}
    )
    assert used == {"Amount", "Department"}
    assert client.post.call_count == 1


def test_used_column_names_empty_dependents_makes_no_api_call():
    client = MagicMock()
    used = discover.used_column_names(client, dependents=[], source_col_names={"Amount"})
    assert used == set()
    assert client.post.call_count == 0


# ---------------------------------------------------------------------------
# Following dependents THROUGH Views
# ---------------------------------------------------------------------------

def _walk_client(graph, subtypes):
    """A client returning `graph[guid]` from the v2 dependents query and `subtypes` from
    the header search. Mirrors the real response envelope so the walk is exercised
    through `_normalize_dependents_response` rather than around it."""
    from unittest.mock import MagicMock

    def post(path, json=None, **kw):
        body = json or {}
        meta = body.get("metadata") or [{}]
        if body.get("include_dependent_objects"):
            src = meta[0].get("identifier", "")
            return MagicMock(json=lambda: [{
                "metadata_id": src,
                "dependent_objects": {"dependents": {src: {
                    "LOGICAL_TABLE": [{"id": g, "name": g} for g in graph.get(src, [])]}}},
            }])
        return MagicMock(json=lambda: [
            {"metadata_id": m["identifier"],
             "metadata_header": {"type": subtypes.get(m["identifier"], "")}}
            for m in meta])

    c = MagicMock()
    c.post.side_effect = post
    return c


def test_content_behind_a_view_is_FOUND_not_hidden():
    """`_collect_dependents` is single-hop, so a tenant with 200 Answers over one View
    reported ONE dependent. Those 200 do not need rewriting, but they are exactly what
    breaks if the View is missed -- so the audit has to show them."""
    from ts_cli.migrate.discover import dependents_through_views

    client = _walk_client({"m1": ["v1"], "v1": ["a1", "a2"]},
                          {"v1": "AGGR_WORKSHEET", "a1": "", "a2": ""})
    found = {d["guid"]: d for d in dependents_through_views(client, "m1")}
    assert set(found) == {"v1", "a1", "a2"}


def test_content_behind_a_view_records_WHICH_view_shields_it():
    """"Free" is not actionable; "free because this View shields it" is -- and it is what
    tells you which View must not be missed."""
    from ts_cli.migrate.discover import dependents_through_views

    client = _walk_client({"m1": ["v1"], "v1": ["a1"]}, {"v1": "AGGR_WORKSHEET"})
    found = {d["guid"]: d for d in dependents_through_views(client, "m1")}
    assert found["v1"]["via_view"] is None
    assert found["a1"]["via_view"] == "v1"


def test_a_NON_view_dependent_is_not_followed():
    """Following an Answer would just re-find the Liveboard embedding it, which is
    already in scope on its own account -- and would make the walk O(graph)."""
    from ts_cli.migrate.discover import dependents_through_views

    client = _walk_client({"m1": ["a1"], "a1": ["should_not_appear"]},
                          {"a1": "ONE_TO_ONE_LOGICAL"})
    assert [d["guid"] for d in dependents_through_views(client, "m1")] == ["a1"]


def test_a_CYCLE_terminates():
    """Views can stack, and a cycle would otherwise hang a fleet-wide audit."""
    from ts_cli.migrate.discover import dependents_through_views

    client = _walk_client({"m1": ["v1"], "v1": ["v2"], "v2": ["v1", "m1"]},
                          {"v1": "AGGR_WORKSHEET", "v2": "AGGR_WORKSHEET"})
    guids = [d["guid"] for d in dependents_through_views(client, "m1")]
    assert sorted(guids) == ["v1", "v2"]


def test_an_object_reachable_TWICE_is_reported_once():
    from ts_cli.migrate.discover import dependents_through_views

    client = _walk_client({"m1": ["v1", "a1"], "v1": ["a1"]}, {"v1": "AGGR_WORKSHEET"})
    guids = [d["guid"] for d in dependents_through_views(client, "m1")]
    assert sorted(guids) == ["a1", "v1"]


def test_target_stack_returns_TABLES_BEFORE_the_model():
    """The order IS the fix. A grant on the Model before its Tables is accepted and
    silently dropped under Strict Object Mode -- HTTP 204, no row (live 2026-07-28)."""
    from unittest.mock import MagicMock
    import json as _json
    from ts_cli.migrate.apply_exec import target_stack

    doc = _json.dumps({"guid": "m1", "model": {
        "name": "Sales", "model_tables": [{"name": "T", "fqn": "t1"}]}})
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [{"edoc": doc}])
    stack = target_stack(client, "m1")
    assert [x["guid"] for x in stack] == ["t1", "m1"]
    assert all(x["type"] == "LOGICAL_TABLE" for x in stack)


def test_target_stack_is_empty_when_the_model_cannot_be_exported():
    """Better to grant nothing than to guess at a stack and half-apply it."""
    from unittest.mock import MagicMock
    from ts_cli.migrate.apply_exec import target_stack
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [])
    assert target_stack(client, "m1") == []
