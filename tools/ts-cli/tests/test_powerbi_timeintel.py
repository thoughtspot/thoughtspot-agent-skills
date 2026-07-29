"""Unit tests for the powerbi timeintel generator (Reference Date SPLY/YoY pattern)."""
from ts_cli.powerbi.timeintel import (
    build_time_intelligence,
    merge_into_model,
    sply_expr,
)


def test_sply_expr_reference_year_and_prior_year():
    assert sply_expr("Date", "[formula_isNewHire]", offset=0) == \
        "sum_if(year([Date]) = year([Reference Date]), [formula_isNewHire])"
    assert sply_expr("Date", "[formula_isNewHire]", offset=1) == \
        "sum_if(year([Date]) = year([Reference Date]) - 1, [formula_isNewHire])"


def test_sply_expr_plain_additive_base():
    assert sply_expr("Order Date", "Sales", offset=1) == \
        "sum_if(year([Order Date]) = year([Reference Date]) - 1, Sales)"


def test_build_emits_parameter_and_four_measures_per_spec():
    out = build_time_intelligence(
        [{"base_name": "New Hires", "base_expr": "[formula_isNewHire]"}],
        date_column="Date",
    )
    assert out["parameter"] == {
        "name": "Reference Date", "data_type": "DATE", "default_value": "12/31/2024"}
    names = [f["name"] for f in out["formulas"]]
    assert names == ["New Hires Ref Yr", "New Hires SPLY", "New Hires YoY", "New Hires YoY %"]
    # YoY and YoY% reference the other measures by id, so the cascade resolves in one import
    exprs = {f["name"]: f["expr"] for f in out["formulas"]}
    assert exprs["New Hires YoY"] == "[formula_New Hires Ref Yr] - [formula_New Hires SPLY]"
    assert exprs["New Hires YoY %"] == "safe_divide([formula_New Hires YoY], [formula_New Hires SPLY])"
    # every emitted formula carries an id, and every column's formula_id matches one
    # (CLAUDE.md invariant: formulas[].id must match its columns[].formula_id, else the
    # column never binds on import and the YoY/YoY% cross-refs dangle)
    formula_ids = {f["id"] for f in out["formulas"]}
    for f in out["formulas"]:
        assert f["id"] == f"formula_{f['name']}"
    for c in out["columns"]:
        assert c["properties"]["column_type"] == "MEASURE"
        assert c["formula_id"] == f"formula_{c['name']}"
        assert c["formula_id"] in formula_ids
    assert any("VERIFY per-period numbers" in r for r in out["review"])


def test_build_honours_custom_measure_names():
    out = build_time_intelligence(
        [{"base_name": "Seps", "base_expr": "[formula_isSep]",
          "sply_name": "Seps SPLY", "yoy_name": "Seps YoY Var", "yoy_pct_name": "Seps YoY % Change"}],
        date_column="Date",
    )
    names = [f["name"] for f in out["formulas"]]
    assert names == ["Seps Ref Yr", "Seps SPLY", "Seps YoY Var", "Seps YoY % Change"]


def test_build_skips_spec_missing_base_expr_into_review_never_guesses():
    out = build_time_intelligence(
        [{"base_name": "Mystery Measure"}],  # no base_expr
        date_column="Date",
    )
    assert out["formulas"] == []
    assert any("NEEDS REVIEW" in r for r in out["review"])


def test_merge_into_model_adds_parameter_once_and_appends():
    model = {"name": "M", "parameters": [{"name": "Reference Date", "data_type": "DATE"}],
             "formulas": [{"name": "Existing", "expr": "1"}], "columns": []}
    built = build_time_intelligence(
        [{"base_name": "New Hires", "base_expr": "[formula_isNewHire]"}], date_column="Date")
    merged = merge_into_model(model, built)
    # parameter not duplicated
    assert sum(1 for p in merged["parameters"] if p["name"] == "Reference Date") == 1
    # formulas appended (existing + 4 new)
    assert len(merged["formulas"]) == 5
    assert len(merged["columns"]) == 4


def test_merge_into_model_is_idempotent():
    # Running build-timeintel --model twice on the same file must not duplicate formulas
    # (ThoughtSpot rejects duplicate formula names on import).
    model = {"name": "M"}
    built = build_time_intelligence(
        [{"base_name": "New Hires", "base_expr": "[formula_isNewHire]"}], date_column="Date")
    merge_into_model(model, built)
    merge_into_model(model, build_time_intelligence(
        [{"base_name": "New Hires", "base_expr": "[formula_isNewHire]"}], date_column="Date"))
    assert len(model["formulas"]) == 4
    assert len(model["columns"]) == 4
    assert sum(1 for p in model["parameters"] if p["name"] == "Reference Date") == 1
