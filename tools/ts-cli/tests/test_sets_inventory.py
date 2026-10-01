"""Unit tests for `ts_cli.sets.inventory` — composition of discovery, consumers,
classification and grant provenance (ts-object-set-manager, spec §5/§7)."""
from unittest.mock import MagicMock, patch

import pytest

from ts_cli.sets import inventory as inv

SET = {"guid": "s1", "name": "B", "model_guid": "m1", "model_name": "M", "author": "a",
       "cohort_type": "ADVANCED", "grouping_type": "COLUMN_BASED", "anchor_column": "Order Id"}
CONS = {"dependents": [{"guid": "a1", "name": "Ans", "type": "ANSWER", "author_id": "u1"}],
        "liveboards": {}, "unreadable": [], "other_types": [], "error": None}
CLS = {"class": "X", "reason": "", "target": None}


def _grant(pid, perm):
    return {"principal_id": pid, "principal_name": pid, "principal_type": "USER",
            "permission": perm}


def test_record_carries_class_and_provenance():
    grants = {"s1": [_grant("u1", "READ_ONLY")], "a1": []}
    rec = inv.build_set_record(SET, CONS, {"class": "CANDIDATE_ANSWER", "reason": "r", "target": None}, grants)
    assert rec["class"] == "CANDIDATE_ANSWER"
    assert rec["grants"][0]["provenance"] == "REQUIRED"   # u1 owns the consuming Answer


def test_unreadable_grants_are_unknown():
    rec = inv.build_set_record(SET, CONS, CLS, None)
    assert rec["grants"][0]["provenance"] == "UNKNOWN"


def test_certain_consumers_still_label_unexplained():
    grants = {"s1": [_grant("u9", "READ_ONLY")], "a1": []}
    rec = inv.build_set_record(SET, CONS, CLS, grants)
    assert rec["grants"][0]["provenance"] == "UNEXPLAINED"


# --- R10: uncertain consumers never yield EXPLAINED/UNEXPLAINED --------------------

def _cons_with_error():
    return dict(CONS, error="some dependents are not visible to this user (hasInaccessibleDependents)")


def _cons_authorless():
    return dict(CONS, dependents=[{"guid": "a1", "name": "Ans", "type": "ANSWER", "author_id": ""}])


@pytest.mark.parametrize("cons", [_cons_with_error(), _cons_authorless()],
                         ids=["dependents_error", "authorless_dependent"])
def test_uncertain_consumers_make_view_grant_unknown(cons):
    grants = {"s1": [_grant("u9", "READ_ONLY")], "a1": []}
    rec = inv.build_set_record(SET, cons, CLS, grants)
    assert [g["provenance"] for g in rec["grants"]] == ["UNKNOWN"]


@pytest.mark.parametrize("cons", [_cons_with_error(), _cons_authorless()],
                         ids=["dependents_error", "authorless_dependent"])
def test_uncertain_consumers_also_downgrade_explained(cons):
    grants = {"s1": [_grant("u9", "READ_ONLY")], "a1": [_grant("u9", "READ_ONLY")]}
    rec = inv.build_set_record(SET, cons, CLS, grants)
    assert [g["provenance"] for g in rec["grants"]] == ["UNKNOWN"]


@pytest.mark.parametrize("cons", [_cons_with_error(), _cons_authorless()],
                         ids=["dependents_error", "authorless_dependent"])
def test_uncertain_consumers_keep_modify_direct(cons):
    grants = {"s1": [_grant("u9", "MODIFY")], "a1": []}
    rec = inv.build_set_record(SET, cons, CLS, grants)
    assert [g["provenance"] for g in rec["grants"]] == ["DIRECT"]


def test_uncertain_consumers_keep_required():
    cons = dict(CONS, error="hidden")
    grants = {"s1": [_grant("u1", "READ_ONLY")], "a1": []}
    rec = inv.build_set_record(SET, cons, CLS, grants)
    assert [g["provenance"] for g in rec["grants"]] == ["REQUIRED"]


# --- R12: other_types consumers make provenance uncertain ---------------------------

def _cons_other_types():
    return dict(CONS, other_types=[{"guid": "f1", "name": "Fb", "type": "FEEDBACK"}])


def test_other_types_consumer_makes_view_grant_unknown():
    """Review probe: the FEEDBACK consumer's owner (u7) holds READ_ONLY on the Set but
    its author_id is not in the record, so it would read UNEXPLAINED."""
    grants = {"s1": [_grant("u7", "READ_ONLY")], "a1": []}
    rec = inv.build_set_record(SET, _cons_other_types(), CLS, grants)
    assert [g["provenance"] for g in rec["grants"]] == ["UNKNOWN"]
    assert inv.summarise([{"models": [{"discovery": "COMPLETE", "sets": [rec]}]}])[
        "unexplained_grants"] == 0


def test_other_types_consumer_keeps_modify_direct():
    grants = {"s1": [_grant("u7", "MODIFY")], "a1": []}
    rec = inv.build_set_record(SET, _cons_other_types(), CLS, grants)
    assert [g["provenance"] for g in rec["grants"]] == ["DIRECT"]


# --- inventory_org ------------------------------------------------------------------

def test_incomplete_model_has_null_set_count_never_zero():
    with patch.object(inv, "discover_sets",
                      return_value={"sets": {}, "incomplete": ["m1"], "notes": []}):
        out = inv.inventory_org(object(), "Primary", [{"guid": "m1", "name": "M"}])
    (m,) = out["models"]
    assert m["discovery"] == "INCOMPLETE" and m["set_count"] is None


def test_complete_model_with_no_sets_counts_zero():
    with patch.object(inv, "discover_sets",
                      return_value={"sets": {"m1": []}, "incomplete": [], "notes": []}):
        out = inv.inventory_org(object(), "Primary", [{"guid": "m1", "name": "M"}])
    assert out["models"][0]["set_count"] == 0


def _run_org(cons, grants):
    with patch.object(inv, "discover_sets",
                      return_value={"sets": {"m1": [SET]}, "incomplete": [], "notes": []}), \
         patch.object(inv, "fetch_consumers", return_value=cons), \
         patch.object(inv, "fetch_grants", return_value=grants):
        return inv.inventory_org(object(), "Primary", [{"guid": "m1", "name": "M"}])


def test_dependents_error_recorded_as_note():
    out = _run_org(dict(CONS, error="boom"), {"s1": [], "a1": []})
    assert [n["kind"] for n in out["notes"]] == ["dependents_failed"]
    assert out["models"][0]["sets"][0]["class"] == "REVIEW_MANUAL"


def test_unreadable_grants_recorded_as_note():
    out = _run_org(CONS, None)
    notes = [n for n in out["notes"] if n["kind"] == "grants_unreadable"]
    assert len(notes) == 1 and notes[0]["object"] == "M / B"
    assert out["models"][0]["sets"][0]["grants"][0]["provenance"] == "UNKNOWN"


def test_unreadable_export_recorded_as_note():
    cons = dict(CONS, dependents=CONS["dependents"] + [
        {"guid": "l1", "name": "LB", "type": "LIVEBOARD", "author_id": "u2"}],
        unreadable=[{"guid": "l1", "name": "LB",
                     "reason": "Liveboard TML export failed or was refused"}])
    out = _run_org(cons, {"s1": []})
    (n,) = [n for n in out["notes"] if n["kind"] == "export_unreadable"]
    assert n == {"kind": "export_unreadable", "object": "M / B / LB (l1)",
                 "detail": "Liveboard TML export failed or was refused"}


def test_unrecognised_dependent_recorded_as_note():
    out = _run_org(_cons_other_types(), {"s1": []})
    (n,) = [n for n in out["notes"] if n["kind"] == "unrecognised_dependent"]
    assert n == {"kind": "unrecognised_dependent", "object": "M / B / Fb (f1)",
                 "detail": "type FEEDBACK not inspected"}


def test_unexpected_classify_error_propagates():
    """Amendment 4: no silent fallback to a lighter class."""
    with patch.object(inv, "discover_sets",
                      return_value={"sets": {"m1": [SET]}, "incomplete": [], "notes": []}), \
         patch.object(inv, "fetch_consumers", return_value=CONS), \
         patch.object(inv, "fetch_grants", return_value={"s1": []}), \
         patch.object(inv, "classify", side_effect=RuntimeError("bug")):
        with pytest.raises(RuntimeError):
            inv.inventory_org(MagicMock(), "Primary", [{"guid": "m1", "name": "M"}])


# --- summarise ----------------------------------------------------------------------

def test_summary_counts():
    orgs = [{"models": [{"discovery": "COMPLETE", "set_count": 2, "sets": [
        {"class": "REVIEW_DELETE", "grants": [{"provenance": "UNEXPLAINED"}]},
        {"class": "KEEP_SHARED", "grants": [{"provenance": "DIRECT"}]}]},
        {"discovery": "INCOMPLETE", "set_count": None, "sets": []}]}]
    s = inv.summarise(orgs)
    assert s == {"models": 2, "models_incomplete": 1, "sets": 2,
                 "by_class": {"REVIEW_DELETE": 1, "KEEP_SHARED": 1}, "unexplained_grants": 1}
