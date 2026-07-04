# tools/ts-cli/tests/test_reconcile_integration.py
from __future__ import annotations
import json

import pytest

from ts_cli.model_builder import build_model_tml
import ts_cli.commands.tableau as tableau_cmd
from ts_cli.commands.tableau import _load_column_name_map, _reconcile_plan


def test_build_model_tml_qualifies_single_table_when_table_unset():
    # sqlproxy columns arrive with no "table" key -> must still qualify against the model table
    tml = build_model_tml(
        model_name="M", connection_name="APJ_TAB",
        tables=[{"name": "vw_dim_promo", "db_table": "VW_DIM_PROMO"}],
        columns=[{"name": "CAMPAIGN_ID", "db_column_name": "CAMPAIGN_ID", "column_type": "ATTRIBUTE"}],
        joins=[], parameters=[], translated_formulas=[],
    )
    col = tml["model"]["columns"][0]
    assert col["column_id"] == "vw_dim_promo::CAMPAIGN_ID"   # NOT bare "CAMPAIGN_ID"


def test_multi_table_qualification_unchanged():
    # when columns carry an explicit table, behaviour is unchanged
    tml = build_model_tml(
        model_name="M", connection_name="C",
        tables=[{"name": "A"}, {"name": "B"}],
        columns=[{"name": "X", "db_column_name": "X", "table": "A", "column_type": "ATTRIBUTE"}],
        joins=[], parameters=[], translated_formulas=[],
    )
    assert tml["model"]["columns"][0]["column_id"] == "A::X"


def test_multi_table_unset_column_stays_bare():
    # multi-table datasource, column with NO "table" key -> must NOT be
    # qualified against tables[0] ("A"); bare column_id is the correct,
    # safe behaviour when the table can't be determined.
    tml = build_model_tml(
        model_name="M", connection_name="C",
        tables=[{"name": "A"}, {"name": "B"}],
        columns=[{"name": "X", "db_column_name": "X", "column_type": "ATTRIBUTE"}],
        joins=[], parameters=[], translated_formulas=[],
    )
    assert tml["model"]["columns"][0]["column_id"] == "X"


def test_reconcile_plan_partitions_and_suggests():
    cols = [{"db_column_name": n} for n in ["CAMPAIGN_ID", "DISCOUNT_RED_DOLLAR", "ORDER_ID"]]
    target = {"CAMPAIGN_ID", "DM_DISCOUNT_RED_DOLLAR", "ORDER_NUM"}
    plan = _reconcile_plan(cols, target)
    assert plan["matched"] == ["CAMPAIGN_ID"]
    assert {m["from"]: m["to"] for m in plan["suggested_mappings"]}.get("DISCOUNT_RED_DOLLAR") == "DM_DISCOUNT_RED_DOLLAR"
    assert "ORDER_ID" in plan["unmatched_drop"]


def _ds(tables, columns=(), joins=()):
    return {
        "name": "DS",
        "tables": list(tables),
        "joins": list(joins),
        "columns": list(columns),
        "calculated_fields": [],
        "calc_map": {},
    }


def test_load_column_name_map_rejects_chain(tmp_path):
    # A -> B, B -> C: applying pairs sequentially on a mutating expr would
    # corrupt the rewrite (B, itself a target, is also a source). Must be
    # rejected up front rather than silently mis-rewriting formulas.
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"A": "B", "B": "C"}))
    with pytest.raises(SystemExit):
        _load_column_name_map(str(p))


def test_load_column_name_map_rejects_convergent(tmp_path):
    # A -> X, B -> X: two different source columns mapping to the same
    # target would collide into a single column_id in the emitted model TML
    # — the same failure mode a rename chain causes, just via convergence
    # instead of chaining. Must be rejected up front.
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"A": "X", "B": "X"}))
    with pytest.raises(SystemExit):
        _load_column_name_map(str(p))


def test_load_column_name_map_accepts_disjoint_map(tmp_path):
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"DISCOUNT_RED_DOLLAR": "DM_DISCOUNT_RED_DOLLAR"}))
    assert _load_column_name_map(str(p)) == {"DISCOUNT_RED_DOLLAR": "DM_DISCOUNT_RED_DOLLAR"}


def test_load_column_name_map_missing_file_exits():
    with pytest.raises(SystemExit):
        _load_column_name_map("/no/such/file.json")


def test_load_column_name_map_none_returns_empty():
    assert _load_column_name_map(None) == {}


def test_generate_flow_reconcile_plan_mode_prints_and_returns_without_writing(
    monkeypatch, tmp_path, capsys,
):
    monkeypatch.setattr(
        tableau_cmd, "_fetch_target_columns",
        lambda guid, profile: {"CAMPAIGN_ID", "DM_DISCOUNT_RED_DOLLAR"},
    )
    ds = _ds(
        tables=[{"name": "foo", "db_table": "foo"}],
        columns=[
            {"name": "CAMPAIGN_ID", "db_column_name": "CAMPAIGN_ID", "column_type": "ATTRIBUTE"},
            {"name": "DISCOUNT_RED_DOLLAR", "db_column_name": "DISCOUNT_RED_DOLLAR", "column_type": "MEASURE"},
        ],
    )
    parsed = {"parameters": []}

    result = tableau_cmd._generate_flow(
        ds=ds, name="Test", slug="test", connection_name="CONN", parsed=parsed,
        cleaned_cols=list(ds["columns"]), cleaned_formulas=[], translated=[], skipped=[],
        rename_map={}, raw_levels={}, validation_issues=[], out_path=tmp_path,
        dry_run=False,
        reconcile_table="guid-123", reconcile_plan_mode=True, column_name_map={}, profile="p",
    )

    assert result == {"reconcile_plan": True}
    plan = json.loads(capsys.readouterr().out)
    assert plan["matched"] == ["CAMPAIGN_ID"]
    assert {m["from"]: m["to"] for m in plan["suggested_mappings"]} == {
        "DISCOUNT_RED_DOLLAR": "DM_DISCOUNT_RED_DOLLAR",
    }
    assert list(tmp_path.iterdir()) == []  # no phased TML written in plan mode


def test_generate_flow_reconcile_apply_mode_drops_and_reports(monkeypatch, tmp_path):
    monkeypatch.setattr(
        tableau_cmd, "_fetch_target_columns", lambda guid, profile: {"CAMPAIGN_ID"},
    )
    ds = _ds(
        tables=[{"name": "foo", "db_table": "foo"}],
        columns=[
            {"name": "CAMPAIGN_ID", "db_column_name": "CAMPAIGN_ID", "column_type": "ATTRIBUTE"},
            {"name": "Order Id", "db_column_name": "ORDER_ID", "column_type": "ATTRIBUTE"},
        ],
    )
    parsed = {"parameters": []}

    result = tableau_cmd._generate_flow(
        ds=ds, name="Test", slug="test", connection_name="CONN", parsed=parsed,
        cleaned_cols=list(ds["columns"]), cleaned_formulas=[], translated=[], skipped=[],
        rename_map={}, raw_levels={}, validation_issues=[], out_path=tmp_path,
        dry_run=True,
        reconcile_table="guid-123", reconcile_plan_mode=False, column_name_map={}, profile="p",
    )

    assert result["columns"] == 1  # ORDER_ID dropped, only CAMPAIGN_ID kept
    assert result["reconcile_dropped"] == {"columns": ["ORDER_ID"], "formulas": []}


def test_generate_flow_without_reconcile_table_unchanged(tmp_path):
    """Omitting --reconcile-table must leave Tier-1-only behavior untouched."""
    ds = _ds(
        tables=[{"name": "foo", "db_table": "foo"}],
        columns=[
            {"name": "CAMPAIGN_ID", "db_column_name": "CAMPAIGN_ID", "column_type": "ATTRIBUTE"},
        ],
    )
    parsed = {"parameters": []}

    result = tableau_cmd._generate_flow(
        ds=ds, name="Test", slug="test", connection_name="CONN", parsed=parsed,
        cleaned_cols=list(ds["columns"]), cleaned_formulas=[], translated=[], skipped=[],
        rename_map={}, raw_levels={}, validation_issues=[], out_path=tmp_path,
        dry_run=True,
    )

    assert result["columns"] == 1
    assert "reconcile_dropped" not in result
    assert "reconcile_plan" not in result
