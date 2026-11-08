"""`ts snowflake build-model`'s stdout summary (commands/snowflake._build_model_summary)."""
from ts_cli.commands.snowflake import _build_model_summary


def _info(**extra):
    return {"attributes": [], "measures": [], "formula_count": 0,
            "fact_types": {"measure": 0, "attribute": 0}, "rename_map": {}, **extra}


def _summary(info):
    return _build_model_summary(
        model_name="M", model_file="m.tml", build_info=info, skipped=[],
        spotter_enabled=None, existing_guid=None, lint_findings=[],
        import_status="not_requested", model_guid=None)


def test_reselected_columns_are_reported_with_the_reason():
    # BL-447 review: build-model selected a key again as an attribute (its table's only
    # column became a `unique count` formula) and the summary never said so, though the
    # rules doc and the skill changelog claimed it was reported.
    s = _summary(_info(reselected_columns=["customer_id"]))
    assert s["reselected_columns"]["columns"] == ["customer_id"]
    assert "only column" in s["reselected_columns"]["reason"]


def test_nothing_reselected_adds_no_key():
    assert "reselected_columns" not in _summary(_info(reselected_columns=[]))
    assert "reselected_columns" not in _summary(_info())
