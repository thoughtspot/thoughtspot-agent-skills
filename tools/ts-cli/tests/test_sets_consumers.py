from unittest.mock import MagicMock

import yaml

from ts_cli.sets.consumers import fetch_consumers, liveboard_usage

SET = {"guid": "s1", "name": "Top 10 [Q1]", "model_guid": "m1", "model_name": "M"}


def _lb(vizzes, filters=()):
    return {"liveboard": {"visualizations": vizzes,
                          "filters": [{"column": list(f)} for f in filters]}}


def _viz(i, title, query, cols=()):
    return {"id": i, "answer": {"name": title, "search_query": query,
                                "answer_columns": [{"name": c} for c in cols]}}


def test_set_name_with_brackets_matches_literally():
    doc = _lb([_viz("Viz_1", "A", "[Top 10 [Q1]] [Amount]"), _viz("Viz_2", "B", "[Amount]")])
    assert liveboard_usage(doc, "Top 10 [Q1]") == {"vizzes": [{"id": "Viz_1", "title": "A"}],
                                                   "filter": False}


def test_match_is_case_insensitive():
    doc = _lb([_viz("Viz_1", "A", "[top 10 [q1]]")])
    assert liveboard_usage(doc, "Top 10 [Q1]")["vizzes"] == [{"id": "Viz_1", "title": "A"}]


def test_answer_columns_count_as_use():
    doc = _lb([_viz("Viz_1", "A", "", cols=["Top 10 [Q1]"])])
    assert len(liveboard_usage(doc, "Top 10 [Q1]")["vizzes"]) == 1


def test_formula_reference_counts_as_use():
    doc = _lb([{"id": "Viz_1", "answer": {"name": "A", "search_query": "[Amount]",
                "formulas": [{"name": "f", "expr": "if ( [Top 10 [Q1]] = 'x' ) then 1 else 0"}]}}])
    assert liveboard_usage(doc, "Top 10 [Q1]")["vizzes"] == [{"id": "Viz_1", "title": "A"}]


def test_filter_use_is_detected():
    doc = _lb([], filters=[("Top 10 [Q1]",)])
    assert liveboard_usage(doc, "Top 10 [Q1]")["filter"] is True


def test_substring_is_not_use():
    doc = _lb([_viz("Viz_1", "A", "[Top 10 [Q1]s]")])
    assert liveboard_usage(doc, "Top 10 [Q1]")["vizzes"] == []


_MISSING = object()


def _client(dep_rows, lb_docs, dep_error=False, dep_payload=None, hidden=False,
            returned=False):
    def post(path, json=None, **kw):
        if "metadata/search" in path:
            if dep_error:
                raise SystemExit(1)
            assert json["metadata"][0]["type"] == "LOGICAL_COLUMN"   # F5
            if dep_payload is not None:
                return MagicMock(json=lambda: dep_payload)
            dobj = {"hasInaccessibleDependents": hidden, "dependents": {"s1": dep_rows}}
            if returned is not _MISSING:
                dobj["areInaccessibleDependentsReturned"] = returned
            return MagicMock(json=lambda: [{"metadata_id": "s1", "dependent_objects": dobj}])
        if "tml/export" in path:
            doc = lb_docs.get(json["metadata"][0]["identifier"])
            if doc is None:
                raise SystemExit(1)
            edoc = doc if isinstance(doc, str) else yaml.safe_dump(doc)
            return MagicMock(json=lambda: [{"edoc": edoc}])
        raise AssertionError(path)
    c = MagicMock(); c.post.side_effect = post
    return c


def test_fetch_consumers_uses_logical_column_and_inspects_liveboards():
    deps = {"QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans", "author": "u1"}],
            "PINBOARD_ANSWER_BOOK": [{"id": "l1", "name": "LB", "author": "u2"}]}
    out = fetch_consumers(_client(deps, {"l1": _lb([_viz("V", "T", "[Top 10 [Q1]]")])}), SET)
    assert [d["guid"] for d in out["dependents"]] == ["a1", "l1"]
    assert out["liveboards"]["l1"]["vizzes"] == [{"id": "V", "title": "T"}]
    assert out["unreadable"] == [] and out["error"] is None


def test_unreadable_liveboard_is_recorded():
    deps = {"PINBOARD_ANSWER_BOOK": [{"id": "l1", "name": "LB", "author": "u2"}]}
    out = fetch_consumers(_client(deps, {}), SET)
    assert out["unreadable"][0]["guid"] == "l1"
    assert "l1" not in out["liveboards"]   # never read as "no references found"


def test_unknown_dependent_type_is_other():
    deps = {"FEEDBACK": [{"id": "f1", "name": "fb"}]}
    assert fetch_consumers(_client(deps, {}), SET)["other_types"][0]["type"] == "FEEDBACK"


def test_set_dependent_on_set_is_other_type():
    # Ruling R5: a COHORT bucket (normalised to SET) is not ANSWER/LIVEBOARD.
    deps = {"COHORT": [{"id": "s2", "name": "Other Set", "author": "u3"}]}
    out = fetch_consumers(_client(deps, {}), SET)
    assert out["other_types"] == [{"guid": "s2", "name": "Other Set", "type": "SET"}]
    assert out["dependents"] == [] and out["error"] is None


def test_dependents_failure_sets_error_not_empty():
    out = fetch_consumers(_client({}, {}, dep_error=True), SET)
    assert out["error"] and out["dependents"] == []


def test_malformed_dependents_response_sets_error():
    # A non-list body would normalise to [] — that must not read as "no dependents".
    out = fetch_consumers(_client({}, {}, dep_payload={"error": "boom"}), SET)
    assert out["error"] and out["dependents"] == []


def test_inaccessible_dependents_sets_error_but_lists_visible():
    deps = {"QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans", "author": "u1"}]}
    out = fetch_consumers(_client(deps, {}, hidden=True), SET)
    assert out["error"] and "hasInaccessibleDependents" in out["error"]
    assert [d["guid"] for d in out["dependents"]] == ["a1"]


def test_inaccessible_dependents_with_none_visible_is_still_error():
    out = fetch_consumers(_client({}, {}, hidden=True), SET)
    assert out["error"] and out["dependents"] == []


def test_inaccessible_dependents_that_were_returned_are_not_an_error():
    # R17, live 2026-10-02: an admin gets has=true AND returned=true — the hidden
    # dependents are in the list, so the lookup is complete.
    deps = {"QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans", "author": "u1"}]}
    out = fetch_consumers(_client(deps, {}, hidden=True, returned=True), SET)
    assert out["error"] is None
    assert [d["guid"] for d in out["dependents"]] == ["a1"]


def test_inaccessible_dependents_not_returned_is_error():
    deps = {"QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans", "author": "u1"}]}
    out = fetch_consumers(_client(deps, {}, hidden=True, returned=False), SET)
    assert out["error"] == ("some dependents are not visible to this user "
                            "(hasInaccessibleDependents)")


def test_inaccessible_dependents_with_returned_flag_missing_is_error():
    deps = {"QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Ans", "author": "u1"}]}
    out = fetch_consumers(_client(deps, {}, hidden=True, returned=_MISSING), SET)
    assert out["error"] and "hasInaccessibleDependents" in out["error"]
    assert [d["guid"] for d in out["dependents"]] == ["a1"]


def test_non_dict_export_is_unreadable():
    deps = {"PINBOARD_ANSWER_BOOK": [{"id": "l1", "name": "LB", "author": "u2"}]}
    out = fetch_consumers(_client(deps, {"l1": "just a string"}), SET)
    assert out["unreadable"] == [{"guid": "l1", "name": "LB",
                                  "reason": "export was not Liveboard TML"}]
    assert "l1" not in out["liveboards"]


def test_non_liveboard_export_is_unreadable():
    deps = {"PINBOARD_ANSWER_BOOK": [{"id": "l1", "name": "LB", "author": "u2"}]}
    out = fetch_consumers(_client(deps, {"l1": {"answer": {"name": "x"}}}), SET)
    assert out["unreadable"][0]["reason"] == "export was not Liveboard TML"
    assert "l1" not in out["liveboards"]
