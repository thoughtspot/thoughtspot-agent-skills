from ts_cli.sets.classify import classify


def _c(deps=(), lbs=None, unreadable=(), other=(), error=None):
    return {"dependents": list(deps), "liveboards": lbs or {}, "unreadable": list(unreadable),
            "other_types": list(other), "error": error}


A = {"guid": "a1", "name": "Ans", "type": "ANSWER", "author_id": "u"}
L = {"guid": "l1", "name": "LB", "type": "LIVEBOARD", "author_id": "u"}


def test_zero_is_review_delete():
    assert classify(_c())["class"] == "REVIEW_DELETE"


def test_one_answer_is_candidate_answer():
    r = classify(_c([A]))
    assert r["class"] == "CANDIDATE_ANSWER" and r["target"]["guid"] == "a1"


def test_one_viz_is_candidate_viz():
    r = classify(_c([L], {"l1": {"vizzes": [{"id": "V", "title": "T"}], "filter": False}}))
    assert r["class"] == "CANDIDATE_VIZ" and r["target"]["viz_id"] == "V"


def test_filter_beats_single_use():
    r = classify(_c([L], {"l1": {"vizzes": [{"id": "V", "title": "T"}], "filter": True}}))
    assert r["class"] == "KEEP_FILTER"


def test_two_vizzes_on_one_liveboard_is_shared():
    lbs = {"l1": {"vizzes": [{"id": "V1", "title": "a"}, {"id": "V2", "title": "b"}], "filter": False}}
    assert classify(_c([L], lbs))["class"] == "KEEP_SHARED"


def test_two_objects_is_shared():
    assert classify(_c([A, dict(A, guid="a2")]))["class"] == "KEEP_SHARED"


def test_unreadable_dependent_is_manual_even_if_single():
    r = classify(_c([L], {}, unreadable=[{"guid": "l1", "name": "LB", "reason": "x"}]))
    assert r["class"] == "REVIEW_MANUAL"


def test_other_type_is_manual():
    assert classify(_c([A], other=[{"guid": "f", "name": "f", "type": "FEEDBACK"}]))["class"] == "REVIEW_MANUAL"


def test_dependents_error_is_manual_never_delete():
    assert classify(_c(error="boom"))["class"] == "REVIEW_MANUAL"


def test_liveboard_dependent_with_zero_matching_vizzes_is_manual():
    # dependency recorded but no viz/filter found by name — evidence conflicts; do not guess
    r = classify(_c([L], {"l1": {"vizzes": [], "filter": False}}))
    assert r["class"] == "REVIEW_MANUAL"


def test_filter_beats_manual():
    lbs = {"l1": {"vizzes": [], "filter": True}}
    assert classify(_c([L, A], lbs, other=[{"guid": "f", "name": "f", "type": "X"}]))["class"] == "KEEP_FILTER"


def test_hidden_dependents_error_with_one_visible_answer_is_manual():
    # Task 3 sets `error` on hasInaccessibleDependents but still lists the visible items.
    # One visible Answer must not become a CANDIDATE: there may be more we cannot see.
    r = classify(_c([A], error="some dependents are not visible to this user"))
    assert r["class"] == "REVIEW_MANUAL"
    assert r["class"] != "CANDIDATE_ANSWER" and r["target"] is None


def test_set_depending_on_set_is_manual_never_delete():
    # A SET dependent lands in other_types; with no ANSWER/LIVEBOARD dependents it must
    # not read as "no recorded dependents".
    r = classify(_c([], other=[{"guid": "s2", "name": "Other Set", "type": "SET"}]))
    assert r["class"] == "REVIEW_MANUAL"
    assert r["class"] != "REVIEW_DELETE"
