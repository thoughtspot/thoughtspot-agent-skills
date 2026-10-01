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
