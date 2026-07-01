from ts_cli.audit.checks_ai import check_a1, check_a2, check_a3, check_a4, check_a5, ALL_CHECKS
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", columns=None, description="", properties=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "description": description,
            "model_tables": [{"name": "T1"}],
            "columns": columns or [],
            "formulas": [],
            "properties": properties or {},
        },
    }


def _col(name="Amount", description="", synonyms=None):
    return {"name": name, "description": description, "synonyms": synonyms or []}


def test_a1_flags_low_coverage():
    cols = [_col("A"), _col("B"), _col("C", description="has desc")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_a1(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].check_id == "A1"


def test_a1_passes_high_coverage():
    cols = [_col("A", description="good"), _col("B", description="good")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_a1(ctx) == []


def test_a1_empty_columns():
    ctx = make_context(models=[_model(columns=[])])
    assert check_a1(ctx) == []


def test_a2_flags_low_coverage():
    cols = [_col("A"), _col("B"), _col("C", synonyms=["revenue"])]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_a2(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "A2"


def test_a2_passes_high_coverage():
    cols = [_col("A", synonyms=["a"]), _col("B", synonyms=["b"])]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_a2(ctx) == []


def test_a3_flags_missing_instructions():
    ctx = make_context(models=[_model(guid="m-1")], ai_instructions={})
    findings = check_a3(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_a3_passes_with_instructions():
    ctx = make_context(
        models=[_model(guid="m-1")],
        ai_instructions={"m-1": {"instructions": "Some coaching text"}},
    )
    assert check_a3(ctx) == []


def test_a4_flags_missing_description():
    ctx = make_context(models=[_model(description="")])
    findings = check_a4(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "MEDIUM"


def test_a4_passes_with_description():
    ctx = make_context(models=[_model(description="Sales data model")])
    assert check_a4(ctx) == []


def test_a5_flags_not_ready():
    cols = [_col("A"), _col("B")]
    ctx = make_context(models=[_model(columns=cols, description="")])
    findings = check_a5(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "A5"


def test_a5_passes_ready():
    cols = [
        _col("Amount", description="Total sale amount", synonyms=["revenue", "sales"]),
        _col("Date", description="Transaction date", synonyms=["order date"]),
    ]
    ctx = make_context(
        models=[_model(columns=cols, description="Sales model")],
        ai_instructions={"m-1": {"instructions": "coaching"}},
    )
    findings = check_a5(ctx)
    assert findings == [] or findings[0].severity == "INFO"


def test_all_checks_has_five_entries():
    assert len(ALL_CHECKS) == 5
