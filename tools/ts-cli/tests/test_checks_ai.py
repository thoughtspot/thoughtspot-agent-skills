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
    ctx = make_context(models=[_model(columns=cols)], assessment="spotter")
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
    ctx = make_context(models=[_model(columns=cols)], assessment="spotter")
    findings = check_a2(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "A2"


def test_a2_passes_high_coverage():
    cols = [_col("A", synonyms=["a"]), _col("B", synonyms=["b"])]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_a2(ctx) == []


def test_a3_flags_missing_instructions():
    ctx = make_context(models=[_model(guid="m-1")], ai_instructions={"m-1": {}},
                       assessment="spotter")
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


def _tml_ctx(*cols, name="M", assessment="spotter"):
    return AuditContext(models=[{"guid": "g-1", "model": {"name": name, "columns": list(cols)}}],
                        assessment=assessment)


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


# --- Assessment profiles (BL-399) ---------------------------------------------------
# One row per (check, profile): the pass mark, and HIGH below half of it. The table lives
# in ts_cli/audit/assessment.py; these pin each profile's promise from SKILL Step 2b.
import pytest  # noqa: E402

from ts_cli.audit import assessment  # noqa: E402


def _desc_cols(n_described, n):
    return [_col(f"C{i}", description="d" if i < n_described else "") for i in range(n)]


def _syn_cols(n_syn, n):
    return [_col(f"C{i}", synonyms=["s"] if i < n_syn else []) for i in range(n)]


@pytest.mark.parametrize("profile,n_described,expected", [
    ("spotter", 95, None), ("spotter", 94, "MEDIUM"), ("spotter", 48, "MEDIUM"),
    ("spotter", 47, "HIGH"),
    ("general", 50, None), ("general", 49, "MEDIUM"), ("general", 25, "MEDIUM"),
    ("general", 24, "HIGH"),
])
def test_a1_by_profile(profile, n_described, expected):
    f = check_a1(make_context(models=[_model(columns=_desc_cols(n_described, 100))],
                              assessment=profile))
    assert (f[0].severity if f else None) == expected


@pytest.mark.parametrize("profile,n_syn,expected", [
    ("spotter", 80, None), ("spotter", 79, "MEDIUM"), ("spotter", 39, "HIGH"),
    ("general", 25, None), ("general", 24, "MEDIUM"), ("general", 12, "HIGH"),
])
def test_a2_by_profile(profile, n_syn, expected):
    f = check_a2(make_context(models=[_model(columns=_syn_cols(n_syn, 100))],
                              assessment=profile))
    assert (f[0].severity if f else None) == expected


@pytest.mark.parametrize("profile,expected", [("spotter", "HIGH"), ("general", "MEDIUM")])
def test_a3_a4_presence_by_profile(profile, expected):
    ctx = make_context(models=[_model(guid="m-1")], ai_instructions={"m-1": {}},
                       assessment=profile)
    assert [f.severity for f in check_a3(ctx)] == [expected]
    assert [f.severity for f in check_a4(ctx)] == [expected]


@pytest.mark.parametrize("profile,covered,expected", [
    ("spotter", 8, None), ("spotter", 7, "MEDIUM"), ("spotter", 3, "HIGH"),
    ("general", 8, None), ("general", 7, "LOW"), ("general", 0, "LOW"),
])
def test_a6_by_profile(profile, covered, expected):
    """AI context is required for Spotter-ready (graded) and recommended for General
    (a gap is LOW, however deep)."""
    cols = [_tml_col(f"M{i}", "MEASURE", AC if i < covered else None) for i in range(10)]
    f = check_a6(_tml_ctx(*cols, assessment=profile))
    assert (f[0].severity if f else None) == expected


def test_default_profile_is_general():
    assert make_context().assessment == "general" == assessment.DEFAULT


def test_threshold_payload_carries_the_profile_pass_mark():
    f = check_a1(make_context(models=[_model(columns=_desc_cols(10, 100))],
                              assessment="spotter"))
    assert f[0].threshold == {"green": 95, "yellow": 47.5, "assessment": "Spotter-ready"}
    f = check_a6(_tml_ctx(_tml_col("M", "MEASURE"), assessment="general"))
    assert f[0].threshold == {"green": 80, "assessment": "General"}


@pytest.mark.parametrize("name,key", [("spotter", "spotter"), ("Spotter-ready", "spotter"),
                                      ("GENERAL", "general"), (None, "general")])
def test_normalise_accepts_the_skill_labels(name, key):
    assert assessment.normalise(name) == key


def test_unknown_profile_is_refused():
    with pytest.raises(ValueError):
        assessment.normalise("strict")


def test_cli_refuses_an_unknown_assessment():
    from typer.testing import CliRunner
    from ts_cli.cli import app
    res = CliRunner().invoke(app, ["audit", "run", "--models", "g", "--assessment", "strict"])
    assert res.exit_code != 0 and "unknown assessment" in (res.output + str(res.exception))


def test_report_shows_the_assessment():
    from ts_cli.audit.report import compact_payload
    data = {"findings": [], "summary": {}, "check_meta": {},
            "corpus": {"assessment": "Spotter-ready", "models": []}}
    assert compact_payload(data)["C"]["as"] == "Spotter-ready"
