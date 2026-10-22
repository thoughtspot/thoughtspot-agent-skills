import pytest
from ts_cli.audit.context import AuditContext, make_context


def _sample_model(name="Sales", guid="m-1", tables=None, columns=None,
                  formulas=None, model_tables=None, properties=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "ORDERS", "id": "ORDERS"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
        },
    }


def test_make_context_defaults():
    ctx = make_context()
    assert ctx.models == []
    assert ctx.tables == {}
    assert ctx.dependents == {}
    assert ctx.metadata == []
    assert ctx.ai_instructions == {}
    assert ctx.answers == []
    assert ctx.model_guids == []
    assert ctx.warnings == []


def test_make_context_with_model():
    m = _sample_model()
    ctx = make_context(models=[m])
    assert len(ctx.models) == 1
    assert ctx.models[0]["model"]["name"] == "Sales"


def test_guid_for_extracts_root_guid():
    m = _sample_model(guid="abc-123")
    ctx = make_context(models=[m])
    assert ctx.guid_for(m) == "abc-123"


def test_guid_for_missing_returns_empty():
    m = {"model": {"name": "X"}}
    ctx = make_context(models=[m])
    assert ctx.guid_for(m) == ""


def test_tables_for_model():
    m = _sample_model(model_tables=[
        {"name": "ORDERS", "fqn": "db.schema.ORDERS"},
        {"name": "ITEMS", "fqn": "db.schema.ITEMS"},
    ])
    ctx = make_context(
        models=[m],
        tables={
            "db.schema.ORDERS": {"table": {"name": "ORDERS"}},
            "db.schema.ITEMS": {"table": {"name": "ITEMS"}},
            "db.schema.OTHER": {"table": {"name": "OTHER"}},
        },
    )
    result = ctx.tables_for_model(m)
    assert len(result) == 2
    names = {t["table"]["name"] for t in result}
    assert names == {"ORDERS", "ITEMS"}


def test_tables_for_model_missing_fqn():
    m = _sample_model(model_tables=[{"name": "ORDERS"}])
    ctx = make_context(models=[m], tables={})
    assert ctx.tables_for_model(m) == []


# ── build_context: Set discovery for H5 (BL-302, BL-324) ───────────────────

from unittest.mock import patch

import audit_rule_fixtures as fx

# The fake client, consumer results and Set discovery are builders in
# audit_rule_fixtures (human.py), whose built_* contexts run build_context the same way
# for the H rules' equivalence test.


def _build_with_one_model(guid, angles, name="Sales"):
    """`angles` are categories: the context fetches what their rules require."""
    from ts_cli.audit import data_needs
    from ts_cli.audit.context import build_context
    return build_context(fx.build_client_with_one_model(guid, name), [guid], data_needs(angles))


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_h_angle_records_sets_and_their_dependents(disc, cons):
    from ts_cli.audit.checks_human import check_h5
    disc.return_value = fx.SETS_ONE
    cons.return_value = fx.build_consumers()
    ctx = _build_with_one_model("m1", angles=["H"])
    assert {"type": "SET", "guid": "s1", "name": "B"}.items() <= ctx.dependents["m1"][-1].items()
    assert ctx.dependents["s1"] == []
    assert [f.object_guid for f in check_h5(ctx)] == ["s1"]


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_discovery_uses_the_model_name_from_the_exported_tml(disc, cons):
    disc.return_value = {"sets": {}, "incomplete": [], "notes": []}
    _build_with_one_model("m1", angles=["H"], name="Retail Sales")
    assert disc.call_args[0][1] == [{"guid": "m1", "name": "Retail Sales"}]
    cons.assert_not_called()


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_set_with_consumers_is_not_an_orphan(disc, cons):
    from ts_cli.audit.checks_human import check_h5
    disc.return_value = fx.SETS_ONE
    cons.return_value = fx.build_consumers(dependents=[
        {"guid": "a1", "name": "Uses B", "type": "ANSWER", "author_id": "u"}])
    ctx = _build_with_one_model("m1", angles=["H"])
    assert ctx.dependents["s1"][0]["guid"] == "a1"
    assert ctx.dependents["s1"][0]["source_guid"] == "s1"
    assert check_h5(ctx) == []


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_failed_set_dependents_keep_h5_silent(disc, cons):
    from ts_cli.audit.checks_human import check_h5
    disc.return_value = fx.SETS_ONE
    cons.return_value = fx.build_consumers(error="x")
    ctx = _build_with_one_model("m1", angles=["H"])
    assert "s1" not in ctx.dependents and check_h5(ctx) == []
    assert any("B" in w and "s1" in w for w in ctx.warnings)


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_set_whose_only_dependent_is_another_set_keeps_h5_silent(disc, cons):
    """R14: a Set consumed only by another Set is not an orphan. `other_types` rows
    are not in `dependents`, so recording `[]` would report it as one."""
    from ts_cli.audit.checks_human import check_h5
    disc.return_value = fx.SETS_ONE
    cons.return_value = fx.build_consumers(other_types=[{"guid": "s2", "name": "C", "type": "SET"}])
    ctx = _build_with_one_model("m1", angles=["H"])
    assert "s1" not in ctx.dependents and check_h5(ctx) == []
    assert any("s1" in w for w in ctx.warnings)


@pytest.mark.parametrize("dep_rows,orphan", [
    ({}, True),
    ({"QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Uses B", "author": "u"}]}, False),
])
@patch("ts_cli.audit.context.discover_sets")
def test_h5_records_sets_whose_hidden_dependents_were_returned(disc, dep_rows, orphan):
    """R17 end to end through the real fetch_consumers: has+returned is a clean lookup,
    so the Set is recorded and H5 decides on what was returned."""
    from ts_cli.audit.checks_human import check_h5
    from ts_cli.audit import data_needs
    from ts_cli.audit.context import build_context
    disc.return_value = fx.SETS_ONE
    ctx = build_context(fx.build_client_with_set_dependents("m1", dep_rows), ["m1"],
                        data_needs(["H"]))
    assert "s1" in ctx.dependents
    assert not any("s1" in w for w in ctx.warnings)
    assert [f.object_guid for f in check_h5(ctx)] == (["s1"] if orphan else [])


def test_h5_emits_one_finding_per_set_listed_by_several_sources():
    """R18: the same Set appears under the Model AND each underlying Table's COHORT
    bucket. One finding per Set, not one per source."""
    from ts_cli.audit.checks_human import check_h5
    assert [f.object_guid for f in check_h5(fx.h5_set_listed_by_several_sources())] == ["s1"]


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_incomplete_discovery_is_a_warning_and_invents_no_set_rows(disc, cons):
    disc.return_value = {"sets": {}, "incomplete": ["m1"], "notes": [
        {"kind": "discovery_failed", "object": "Sales (m1)", "detail": "cohort listing failed: 500"}]}
    ctx = _build_with_one_model("m1", angles=["H"])
    assert not any(d.get("type") == "SET" for d in ctx.dependents.get("m1", []))
    assert any("discovery_failed" in w and "Sales (m1)" in w for w in ctx.warnings)
    cons.assert_not_called()


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_set_discovery_runs_only_when_a_selected_rule_requires_sets(disc, cons):
    _build_with_one_model("m1", angles=["A", "D", "P", "S"])
    disc.assert_not_called()
    cons.assert_not_called()


# ── R15: SET rows do not make a Model "used" for H4 ────────────────────────

@pytest.mark.parametrize("error", [None, "dependents lookup failed"])
@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_h4_fires_for_a_model_whose_only_dependents_are_sets(disc, cons, error):
    """A Set is a column on the Model, so anything using it is already a Model
    dependent. A SET row alone must not clear an orphan Model — clean or failed lookup."""
    from ts_cli.audit.checks_human import check_h4
    disc.return_value = fx.SETS_ONE
    cons.return_value = fx.build_consumers(error=error)
    ctx = _build_with_one_model("m1", angles=["H"])
    assert any(d.get("type") == "SET" for d in ctx.dependents["m1"])  # kept for H5
    assert [f.object_guid for f in check_h4(ctx)] == ["m1"]
    assert check_h4(ctx)[0].detail == "Orphan model — zero dependents (no answers or liveboards)"


def test_h4_is_silent_when_a_model_has_an_answer_beside_its_sets():
    from ts_cli.audit.checks_human import check_h4
    assert check_h4(fx.h4_model_with_answer_beside_sets()) == []


@patch("ts_cli.audit.context.discover_sets")
def test_h5_is_silent_when_the_set_dependents_response_is_empty(disc):
    """Final review must-fix 1 + R14: a `[]` dependents body is not "zero consumers".
    The real fetch_consumers errors, so the Set is not recorded and H5 stays silent."""
    from ts_cli.audit.checks_human import check_h5
    disc.return_value = fx.SETS_ONE
    ctx = _build_with_one_model("m1", angles=["H"])   # every search returns []
    assert "s1" not in ctx.dependents and check_h5(ctx) == []
    assert any("s1" in w and "did not include this Set" in w for w in ctx.warnings)
