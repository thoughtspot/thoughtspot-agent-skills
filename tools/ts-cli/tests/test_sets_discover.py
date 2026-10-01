"""Set discovery via the per-Model cohort listing (spec Appendix A / plan Task 2 amendment).
Membership = presence of `cohortConfig`; a blank header `type` (F2) must not drop a Set."""
from unittest.mock import MagicMock

from ts_cli.sets.discover import by_owner, discover_sets, parse_cohort_columns

M = {"guid": "m1", "name": "Dunder"}


def _row(guid, name, type_="COHORT_ADVANCED", cfg=True, author="pin"):
    r = {"header": {"id": guid, "name": name, "type": type_, "owner": "m1", "authorName": author}}
    if cfg:
        r["cohortConfig"] = {"name": name, "cohort_type": "ADVANCED",
                             "cohort_grouping_type": "COLUMN_BASED", "anchor_column_id": "col-guid"}
    return r


def test_blank_type_row_with_cohort_config_is_a_set():
    (s,) = parse_cohort_columns([_row("s1", "Basket", type_=None)], M)
    assert s == {"guid": "s1", "name": "Basket", "model_guid": "m1", "model_name": "Dunder",
                 "author": "pin", "cohort_type": "ADVANCED", "grouping_type": "COLUMN_BASED",
                 "anchor_column": "col-guid"}


def test_row_without_cohort_config_is_not_a_set():
    assert parse_cohort_columns([_row("c1", "Amount", cfg=False)], M) == []


def test_sorted_case_insensitive():
    rows = [_row("s2", "beta"), _row("s1", "Alpha")]
    assert [s["name"] for s in parse_cohort_columns(rows, M)] == ["Alpha", "beta"]


def _client(by_guid):
    seen = []
    def get(path, params=None, **kw):
        seen.append((path, dict(params or {})))
        guid = path.rsplit("/", 1)[-1]
        val = by_guid[guid]
        if isinstance(val, BaseException):
            raise val
        return MagicMock(status_code=200, json=lambda: val)
    c = MagicMock(); c.get.side_effect = get; c.seen = seen
    return c


def test_discover_calls_per_model_listing_without_doupdate():
    c = _client({"m1": [_row("s1", "Basket")]})
    out = discover_sets(c, [M])
    path, params = c.seen[0]
    assert path == "/callosum/v1/metadata/detail/m1"
    assert params["type"] == "LOGICAL_TABLE" and params["fetchcohortcolumnsonly"] == "true"
    assert "doUpdate" not in params and "doupdate" not in {k.lower() for k in params}
    assert [s["guid"] for s in out["sets"]["m1"]] == ["s1"] and out["incomplete"] == []


def test_zero_sets_is_complete_and_empty():
    out = discover_sets(_client({"m1": []}), [M])
    assert out["sets"]["m1"] == [] and out["incomplete"] == []


def test_failed_call_is_incomplete_not_empty():
    out = discover_sets(_client({"m1": SystemExit(1)}), [M])
    assert "m1" not in out["sets"] and out["incomplete"] == ["m1"]
    assert out["notes"][0]["kind"] == "discovery_failed"


def test_non_list_response_is_incomplete():
    out = discover_sets(_client({"m1": {"code": 10002}}), [M])
    assert out["incomplete"] == ["m1"]


def test_by_owner_marks_incomplete_models_blocked():
    res = {"sets": {"m1": []}, "incomplete": ["m2"], "notes": []}
    assert by_owner(res)["m2"][0]["name"] == "(discovery incomplete)"
    assert "m1" not in by_owner(res)


# --- fix round 1: anomalies make the result less certain, never more favourable ---
from ts_cli.sets.discover import export_doc  # noqa: E402


def test_row_lacking_cohort_config_makes_model_incomplete():
    out = discover_sets(_client({"m1": [_row("s1", "Basket"), _row("c1", "Amount", cfg=False)]}), [M])
    assert "m1" not in out["sets"] and out["incomplete"] == ["m1"]
    (note,) = out["notes"]
    assert note["kind"] == "unrecognised_row" and "1 of 2" in note["detail"]
    assert note["object"] == "Dunder (m1)"


def test_non_dict_element_is_incomplete_without_exception():
    out = discover_sets(_client({"m1": [_row("s1", "Basket"), "x"]}), [M])
    assert "m1" not in out["sets"] and out["incomplete"] == ["m1"]
    assert out["notes"][0]["kind"] == "unrecognised_row"


def test_empty_header_id_is_incomplete():
    out = discover_sets(_client({"m1": [_row("", "Basket")]}), [M])
    assert out["incomplete"] == ["m1"] and "m1" not in out["sets"]


def test_runtime_error_is_incomplete():
    out = discover_sets(_client({"m1": RuntimeError("boom")}), [M])
    assert out["incomplete"] == ["m1"] and "m1" not in out["sets"]
    assert out["notes"][0]["kind"] == "discovery_failed"
    assert out["notes"][0]["object"] == "Dunder (m1)"


def test_one_failing_model_does_not_affect_another():
    m2 = {"guid": "m2", "name": "Other"}
    out = discover_sets(_client({"m1": ["x"], "m2": [_row("s9", "Gamma")]}), [M, m2])
    assert out["incomplete"] == ["m1"] and [s["guid"] for s in out["sets"]["m2"]] == ["s9"]


def test_by_owner_lists_sets():
    res = {"sets": {"m1": parse_cohort_columns([_row("s1", "Basket")], M)}, "incomplete": [], "notes": []}
    assert by_owner(res) == {"m1": [{"name": "Basket", "guid": "s1"}]}


def test_parse_name_none_falls_back_to_empty():
    r = _row("s1", None)
    r["cohortConfig"]["name"] = None
    (s,) = parse_cohort_columns([r], M)
    assert s["name"] == ""


def test_export_doc_parses_edoc():
    c = MagicMock()
    c.post.return_value = MagicMock(json=lambda: [{"edoc": "cohort:\n  name: X\n"}])
    assert export_doc(c, "g1") == {"cohort": {"name": "X"}}


def test_export_doc_none_on_failure():
    c = MagicMock()
    c.post.side_effect = SystemExit(1)
    assert export_doc(c, "g1") is None
