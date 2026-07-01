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
