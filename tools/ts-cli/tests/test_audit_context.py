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

from unittest.mock import MagicMock, patch

import yaml


def _resp(body, ok=True, status=200):
    r = MagicMock()
    r.ok, r.status_code = ok, status
    r.json.return_value = body
    return r


def _client_with_one_model(guid, name="Sales"):
    """A client whose export returns one Model TML; every search returns []."""
    edoc = yaml.safe_dump(_sample_model(name=name, guid=guid))

    def post(url, json=None, **_kw):
        if url.endswith("/metadata/tml/export"):
            return _resp([{"edoc": edoc}])
        return _resp([])

    client = MagicMock()
    client.post.side_effect = post
    return client


def _build_with_one_model(guid, angles, name="Sales"):
    from ts_cli.audit.context import build_context
    return build_context(_client_with_one_model(guid, name), [guid], angles)


def _cons(dependents=None, other_types=None, error=None):
    return {"dependents": dependents or [], "liveboards": {}, "unreadable": [],
            "other_types": other_types or [], "error": error}


_ONE_SET = {"sets": {"m1": [{"guid": "s1", "name": "B"}]}, "incomplete": [], "notes": []}


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_h_angle_records_sets_and_their_dependents(disc, cons):
    from ts_cli.audit.checks_human import check_h5
    disc.return_value = _ONE_SET
    cons.return_value = _cons()
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
    disc.return_value = _ONE_SET
    cons.return_value = _cons(dependents=[
        {"guid": "a1", "name": "Uses B", "type": "ANSWER", "author_id": "u"}])
    ctx = _build_with_one_model("m1", angles=["H"])
    assert ctx.dependents["s1"][0]["guid"] == "a1"
    assert ctx.dependents["s1"][0]["source_guid"] == "s1"
    assert check_h5(ctx) == []


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_failed_set_dependents_keep_h5_silent(disc, cons):
    from ts_cli.audit.checks_human import check_h5
    disc.return_value = _ONE_SET
    cons.return_value = _cons(error="x")
    ctx = _build_with_one_model("m1", angles=["H"])
    assert "s1" not in ctx.dependents and check_h5(ctx) == []
    assert any("B" in w and "s1" in w for w in ctx.warnings)


@patch("ts_cli.audit.context.fetch_consumers")
@patch("ts_cli.audit.context.discover_sets")
def test_set_whose_only_dependent_is_another_set_keeps_h5_silent(disc, cons):
    """R14: a Set consumed only by another Set is not an orphan. `other_types` rows
    are not in `dependents`, so recording `[]` would report it as one."""
    from ts_cli.audit.checks_human import check_h5
    disc.return_value = _ONE_SET
    cons.return_value = _cons(other_types=[{"guid": "s2", "name": "C", "type": "SET"}])
    ctx = _build_with_one_model("m1", angles=["H"])
    assert "s1" not in ctx.dependents and check_h5(ctx) == []
    assert any("s1" in w for w in ctx.warnings)


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
def test_set_discovery_only_runs_for_the_h_angle(disc, cons):
    _build_with_one_model("m1", angles=["A", "D", "P", "S"])
    disc.assert_not_called()
    cons.assert_not_called()
