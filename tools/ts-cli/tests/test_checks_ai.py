from ts_cli.audit.checks_ai import check_a1, check_a2, check_a3, check_a4, check_a5, check_a6, ALL_CHECKS
from ts_cli.audit.context import AuditContext, make_context


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
    ctx = make_context(models=[_model(guid="m-1")], ai_instructions={"m-1": {}})
    findings = check_a3(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_a3_passes_with_instructions():
    ctx = make_context(
        models=[_model(guid="m-1")],
        ai_instructions={"m-1": {"nl_instructions_info": [
            {"instructions": ["Some coaching text"], "scope": "GLOBAL"}]}},
    )
    assert check_a3(ctx) == []


def test_a3_skips_model_when_fetch_failed():
    ctx = make_context(models=[_model(guid="m-1")], ai_instructions={})
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
        ai_instructions={"m-1": {"nl_instructions_info": [
            {"instructions": ["coaching"], "scope": "GLOBAL"}]}},
    )
    findings = check_a5(ctx)
    assert findings == [] or findings[0].severity == "INFO"


def test_all_checks_has_six_entries():
    assert len(ALL_CHECKS) == 6


# --- Columns written as exported Model TML writes them -----------------------------
# `synonyms` and `ai_context` under `properties:`, `description` at the column root
# (counted across 599 Models on the SE demo cluster, 2026-10-21). The `_col` helper
# above puts `synonyms` at the root, where real TML never does, which is how A2's
# root-only read went unnoticed: it scored every real Model 0%.


def _tml_col(name, ctype="ATTRIBUTE", ai_context=None, synonyms=None, hidden=False, desc=None):
    props = {"column_type": ctype}
    if ai_context is not None:
        props["ai_context"] = ai_context
    if synonyms is not None:
        props["synonyms"] = synonyms
    if hidden:
        props["is_hidden"] = True
    c = {"name": name, "column_id": f"T::{name}", "properties": props}
    if desc:
        c["description"] = desc
    return c


def _tml_ctx(*cols, name="M"):
    return AuditContext(models=[{"guid": "g-1", "model": {"name": name, "columns": list(cols)}}])


AC = "additivity: additive\ntime_basis: DM_DATE.Date\ngrain_keys: [T.ID]"


class TestA6MeasureAiContext:
    def test_full_coverage_is_clean(self):
        assert check_a6(_tml_ctx(_tml_col("Revenue", "MEASURE", AC), _tml_col("Qty", "MEASURE", AC))) == []

    def test_no_coverage_is_high_and_names_the_measures(self):
        f = check_a6(_tml_ctx(_tml_col("Revenue", "MEASURE"), _tml_col("Qty", "MEASURE")))
        assert len(f) == 1 and f[0].check_id == "A6" and f[0].severity == "HIGH"
        assert "0/2 measures" in f[0].detail and "Revenue" in f[0].detail and "Qty" in f[0].detail

    def test_partial_coverage_is_medium(self):
        f = check_a6(_tml_ctx(*[_tml_col(f"M{i}", "MEASURE", AC if i < 3 else None) for i in range(5)]))
        assert f[0].severity == "MEDIUM" and f[0].metric == 60.0

    def test_attributes_are_not_counted(self):
        """An ID or label column with no ai_context is often correct (the coach schema:
        a surrogate key carries none), so attributes never lower the score."""
        assert check_a6(_tml_ctx(_tml_col("Revenue", "MEASURE", AC),
                             *[_tml_col(f"ID{i}") for i in range(10)])) == []

    def test_hidden_measures_are_not_counted(self):
        assert check_a6(_tml_ctx(_tml_col("Revenue", "MEASURE", AC),
                             _tml_col("Raw", "MEASURE", hidden=True))) == []

    def test_blank_ai_context_counts_as_missing(self):
        f = check_a6(_tml_ctx(_tml_col("Revenue", "MEASURE", "   ")))
        assert len(f) == 1

    def test_model_without_measures_is_skipped(self):
        assert check_a6(_tml_ctx(_tml_col("Region"))) == []

    def test_long_missing_list_is_truncated(self):
        f = check_a6(_tml_ctx(*[_tml_col(f"M{i}", "MEASURE") for i in range(8)]))
        assert "(+3 more)" in f[0].detail


class TestSynonymsUnderProperties:
    def test_a2_reads_properties_synonyms(self):
        cols = [_tml_col(f"C{i}", synonyms=["x"]) for i in range(4)]
        assert check_a2(_tml_ctx(*cols)) == []

    def test_a2_still_flags_missing_synonyms(self):
        f = check_a2(_tml_ctx(*[_tml_col(f"C{i}") for i in range(4)]))
        assert len(f) == 1 and "0/4" in f[0].detail

    def test_a2_root_synonyms_still_count(self):
        c = {"name": "C", "synonyms": ["x"], "properties": {"column_type": "ATTRIBUTE"}}
        assert check_a2(_tml_ctx(c)) == []

    def test_a5_counts_properties_synonyms(self):
        """Same Model, synonyms present vs absent: the readiness score must differ by
        the synonym weight (15 points at 100% coverage)."""
        with_syn = check_a5(_tml_ctx(_tml_col("C", synonyms=["x"], desc="d")))
        without = check_a5(_tml_ctx(_tml_col("C", desc="d")))
        assert with_syn and without
        assert round(with_syn[0].metric - without[0].metric) == 15
