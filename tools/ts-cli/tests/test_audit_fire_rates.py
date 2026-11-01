"""Fire rates (the severity rubric, audit v2 roadmap PR 4.2): how many of a rule's objects
it fires on at MEDIUM or above, per assessment, and when that warns."""
from __future__ import annotations

import copy
import dataclasses
import datetime
import json

from audit_catalog_helpers import PKG_CATALOG
from ts_cli.audit.catalog_model import load_catalog
from ts_cli.audit.catalog_evidence import fire_rate_problems
from ts_cli.audit.fire_rates import fire_rates, object_kind

CAT = load_catalog(PKG_CATALOG)
TODAY = datetime.date(2026, 11, 2)
COUNTS = {"model": 4, "table": 10, "answer": 0, "set": 3}


def _f(rid, guid, sev="MEDIUM"):
    return {"check_id": rid, "object_guid": guid, "severity": sev}


def _cat(**reviews):
    """The shipped catalog with A4's (a model-scoped rule) reviews replaced."""
    cat = copy.deepcopy(CAT)
    cat.rules["A4"] = dataclasses.replace(cat.rules["A4"], fire_rate_reviewed=reviews or None)
    return cat


def _row(rows, rid):
    return next(r for r in rows if r["rule"] == rid)


def test_object_kind_by_scope():
    assert [object_kind(s) for s in ("model", "model.column", "join", "table.rls_rule",
                                     "rls_column_ref", "metadata", "answer.formula", "set")] \
        == ["model", "model", "model", "table", "table", "table", "answer", "set"]


def test_more_than_half_warns_half_does_not():
    three = [_f("A4", f"m-{i}") for i in range(3)]
    row = _row(fire_rates(three, _cat(), "general", COUNTS, TODAY), "A4")
    assert (row["objects"], row["fired"], row["share"], row["warns"]) == (4, 3, 0.75, True)
    two = [_f("A4", "m-0"), _f("A4", "m-1"), _f("A4", "m-1")]  # one Model twice
    assert _row(fire_rates(two, _cat(), "general", COUNTS, TODAY), "A4")["warns"] is False


def test_only_medium_and_above_count():
    low = [_f("A4", f"m-{i}", "LOW") for i in range(4)]
    row = _row(fire_rates(low, _cat(), "general", COUNTS, TODAY), "A4")
    assert (row["fired"], row["warns"], row["by_severity"]) == (0, False, {"LOW": 4})


def test_a_review_silences_only_its_own_assessment_and_lapses():
    three = [_f("A4", f"m-{i}") for i in range(3)]
    fresh = {"date": "2026-10-01", "rate": 0.75, "note": "expected"}

    def warns(cat, profile="general"):
        return _row(fire_rates(three, cat, profile, COUNTS, TODAY), "A4")["warns"]
    assert warns(_cat(general=fresh)) is False
    assert warns(_cat(spotter=fresh)) is True
    assert warns(_cat(general={**fresh, "date": "2026-05-05"})) is True   # 181 days
    assert warns(_cat(general={**fresh, "rate": 0.64})) is True            # 0.75 > 0.64 + 0.10
    assert warns(_cat(general={**fresh, "rate": 0.66})) is False


def test_each_rule_is_counted_against_its_own_objects():
    rows = fire_rates([_f("P13", f"t-{i}") for i in range(6)], CAT, "general", COUNTS, TODAY)
    row = _row(rows, "P13")  # scope table.rls_rule: Tables
    assert (row["kind"], row["objects"], row["fired"], row["warns"]) == ("table", 10, 6, True)


def test_a_rule_naming_no_object_never_warns():
    rows = fire_rates([_f("H8", "none"), _f("D12", ""), _f("D12", "")], CAT, "general",
                      COUNTS, TODAY)
    for rid in ("H8", "D12"):
        row = _row(rows, rid)
        assert (row["share"], row["warns"]) == (None, False) and row["findings"] > 0


def test_no_objects_of_a_kind_is_not_a_division_by_zero():
    row = _row(fire_rates([], CAT, "general", COUNTS, TODAY), "H7")  # answer scope, 0 Answers
    assert (row["objects"], row["share"], row["warns"]) == (0, None, False)


def test_output_carries_no_names_or_guids():
    rows = fire_rates([_f("A4", "secret-guid-1")], CAT, "general", COUNTS, TODAY)
    assert "secret-guid-1" not in json.dumps(rows)


def test_review_shape_is_validated():
    ok = {"date": "2026-11-02", "rate": 0.89, "note": "Most Models have no coaching yet."}
    rule = lambda r: dataclasses.replace(CAT.rules["A3"], fire_rate_reviewed=r)  # noqa: E731
    profiles = list(CAT.profiles)
    assert fire_rate_problems(rule({"spotter": ok}), profiles) == []
    for bad in ({"spot": ok}, {"spotter": {**ok, "date": "soon"}},
                {"spotter": {**ok, "rate": 1.5}}, {"spotter": {**ok, "rate": "high"}},
                {"spotter": {**ok, "note": ""}}, {"spotter": {**ok, "by": "me"}}, ["spotter"]):
        assert fire_rate_problems(rule(bad), profiles), bad


def test_shipped_reviews():
    reviewed = {(r.id, pid) for r in CAT.rules.values()
                for pid in (r.fire_rate_reviewed or {})}
    assert reviewed == {("A3", "general"), ("A3", "spotter"), ("A6", "spotter"),
                        ("A1", "spotter"), ("A2", "spotter")}


def test_the_command_reads_a_snapshot(tmp_path):
    from typer.testing import CliRunner

    import audit_rule_fixtures as fx
    from ts_cli.audit.snapshot import write_snapshot
    from ts_cli.commands.audit import app
    write_snapshot(fx.ai_model_without_description(), tmp_path / "snap", ["A", "D", "H", "P", "S"])
    res = CliRunner().invoke(app, ["fire-rates", "--snapshot-in", str(tmp_path / "snap"),
                                   "--assessment", "general"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout[res.stdout.index("{"):])
    a4 = _row(payload["rules"], "A4")
    # one Model, no description: A4 fires on all of it, unreviewed, so it warns
    assert (a4["objects"], a4["fired"], a4["warns"]) == (1, 1, True)
    assert payload["assessment"] == "general"


# ── second review ────────────────────────────────────────────────────────────

def test_metadata_rules_are_counted_against_tables():
    assert object_kind("metadata") == "table"


def test_only_judged_objects_are_counted(tmp_path):
    """A Model the run does not judge (malformed TML, BL-406) is not in the denominator."""
    from typer.testing import CliRunner

    import audit_rule_fixtures as fx
    from ts_cli.audit.snapshot import write_snapshot
    from ts_cli.commands.audit import app
    ctx = fx.ai_model_without_description()
    bad = copy.deepcopy(ctx.models[0])
    bad["guid"] = "m-bad"
    bad["model"]["name"] = "Unreadable"
    bad["model"]["columns"] = [{"name": "x", "column_id": "T::X", "properties": ["oops"]}]
    ctx.models.append(bad)
    ctx.model_guids = [m["guid"] for m in ctx.models]
    write_snapshot(ctx, tmp_path / "snap", ["A", "D", "H", "P", "S"])
    res = CliRunner().invoke(app, ["fire-rates", "--snapshot-in", str(tmp_path / "snap"),
                                   "--assessment", "general"])
    a4 = _row(json.loads(res.stdout[res.stdout.index("{"):])["rules"], "A4")
    assert (a4["objects"], a4["fired"], a4["warns"]) == (1, 1, True)


def test_a_review_dated_in_the_future_or_as_a_datetime_does_not_hold():
    three = [_f("A4", f"m-{i}") for i in range(3)]
    for date in ("2099-01-01", datetime.datetime(2026, 10, 1, 10, 0)):
        cat = _cat(general={"date": date, "rate": 0.75, "note": "x"})
        assert _row(fire_rates(three, cat, "general", COUNTS, TODAY), "A4")["warns"] is True


def test_review_boundaries():
    three = [_f("A4", f"m-{i}") for i in range(3)]  # 0.75

    def warns(date, rate):
        cat = _cat(general={"date": date, "rate": rate, "note": "x"})
        return _row(fire_rates(three, cat, "general", COUNTS, TODAY), "A4")["warns"]
    assert warns("2026-05-06", 0.75) is False   # exactly 180 days
    assert warns("2026-05-05", 0.75) is True    # 181
    assert warns("2026-10-01", 0.65) is False   # exactly 10 points above
    assert warns("2026-10-01", 0.6499) is True


def test_a_datetime_review_date_fails_the_gate():
    rule = dataclasses.replace(CAT.rules["A3"], fire_rate_reviewed={
        "general": {"date": datetime.datetime(2026, 11, 2, 10, 0), "rate": 0.5, "note": "x"}})
    assert fire_rate_problems(rule, list(CAT.profiles))
