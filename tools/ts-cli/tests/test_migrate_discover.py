import json
from unittest.mock import MagicMock

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


def test_find_model_by_name_matches_case_insensitively():
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [
        {"metadata_id": "tgt-1", "metadata_name": "Sales", "metadata_type": "LOGICAL_TABLE"},
    ])
    assert discover.find_model_by_name(client, "sales") == "tgt-1"
    posted_filter = client.post.call_args.kwargs["json"]["metadata"][0]
    assert posted_filter["subtypes"] == ["WORKSHEET", "AGGR_WORKSHEET"]


def test_find_model_by_name_returns_none_when_absent():
    client = MagicMock()
    client.post.return_value = MagicMock(json=lambda: [])
    assert discover.find_model_by_name(client, "Nope") is None


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
