# tools/ts-cli/tests/test_reconcile_integration.py
from __future__ import annotations
from ts_cli.model_builder import build_model_tml


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
