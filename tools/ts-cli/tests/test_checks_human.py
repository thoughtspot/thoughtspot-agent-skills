from ts_cli.audit.checks_human import (
    check_h1, check_h2, check_h3, check_h4, check_h5, check_h6,
    check_h7, check_h8, check_h9, check_h10, ALL_CHECKS,
)
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", columns=None, formulas=None, model_tables=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": {},
        },
    }


def _col(name="Amount", description="", is_hidden=False, column_id=None):
    c = {"name": name, "description": description, "properties": {}}
    if is_hidden:
        c["properties"]["is_hidden"] = True
    if column_id:
        c["column_id"] = column_id
    return c


def test_h1_flags_generic_names():
    cols = [
        _col("col1"), _col("field_2"), _col("val"),
        _col("Amount"), _col("Revenue"), _col("Date"),
        _col("Customer"), _col("Product"), _col("Region"), _col("Sales"),
    ]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_h1(ctx)
    assert any(f.check_id == "H1" for f in findings)


def test_h1_passes_good_names():
    cols = [_col("Amount"), _col("Revenue"), _col("Order Date")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_h1(ctx) == []


def test_h3_flags_hidden_not_referenced():
    cols = [
        _col("Amount", is_hidden=True, column_id="T1::Amount"),
        _col("Revenue", column_id="T1::Revenue"),
    ]
    ctx = make_context(models=[_model(columns=cols, formulas=[])])
    findings = check_h3(ctx)
    assert any(f.check_id == "H3" and "Amount" in f.detail for f in findings)


def test_h3_passes_hidden_referenced_by_formula():
    cols = [
        _col("Amount", is_hidden=True, column_id="T1::Amount"),
        _col("Revenue", column_id="T1::Revenue"),
    ]
    formulas = [{"name": "Total", "expr": "sum([Amount])"}]
    ctx = make_context(models=[_model(columns=cols, formulas=formulas)])
    assert check_h3(ctx) == []


def test_h4_flags_zero_dependents():
    ctx = make_context(
        models=[_model(guid="m-1")],
        dependents={},
    )
    findings = check_h4(ctx)
    assert any(f.check_id == "H4" for f in findings)


def test_h4_passes_with_dependents():
    ctx = make_context(
        models=[_model(guid="m-1")],
        dependents={"m-1": [{"guid": "a-1", "type": "ANSWER"}]},
    )
    assert check_h4(ctx) == []


def test_h10_flags_stale_column():
    cols = [_col("DO NOT USE Amount"), _col("Revenue")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_h10(ctx)
    assert any(f.check_id == "H10" for f in findings)


def test_h10_passes_clean_names():
    cols = [_col("Amount"), _col("Revenue")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_h10(ctx) == []


def test_all_checks_has_ten_entries():
    assert len(ALL_CHECKS) == 10
