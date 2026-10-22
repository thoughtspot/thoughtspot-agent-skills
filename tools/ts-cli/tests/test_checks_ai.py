"""The legacy A-checks (checks_ai.py). Their inputs are named builders in
audit_rule_fixtures (ai.py), so the A catalog rules' equivalence test runs over exactly
these contexts."""
import audit_rule_fixtures as fx
from ts_cli.audit.checks_ai import check_a1, check_a2, check_a3, check_a4, check_a5, check_a6, ALL_CHECKS
from ts_cli.audit.context import make_context


def _under(profile, ctx):
    ctx.assessment = profile
    return ctx


def test_a1_flags_low_coverage():
    findings = check_a1(_under("spotter", fx.ai_model_one_of_three_described()))
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].check_id == "A1"


def test_a1_passes_high_coverage():
    assert check_a1(fx.ai_model_all_described()) == []


def test_a1_empty_columns():
    assert check_a1(fx.ai_model_without_columns()) == []


def test_a2_flags_low_coverage():
    findings = check_a2(_under("spotter", fx.ai_model_one_of_three_with_synonyms()))
    assert len(findings) == 1
    assert findings[0].check_id == "A2"


def test_a2_passes_high_coverage():
    assert check_a2(fx.ai_model_all_with_synonyms()) == []


def test_a3_flags_missing_instructions():
    findings = check_a3(_under("spotter", fx.ai_model_uncoached()))
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_a3_passes_with_instructions():
    assert check_a3(fx.ai_model_coached()) == []


def test_a3_skips_model_when_fetch_failed():
    assert check_a3(fx.ai_model_instructions_not_fetched()) == []


def test_a4_flags_missing_description():
    findings = check_a4(fx.ai_model_without_description())
    assert len(findings) == 1
    assert findings[0].severity == "MEDIUM"


def test_a4_passes_with_description():
    assert check_a4(fx.ai_model_described()) == []


def test_a5_flags_not_ready():
    findings = check_a5(fx.ai_model_bare_columns())
    assert len(findings) == 1
    assert findings[0].check_id == "A5"


def test_a5_passes_ready():
    findings = check_a5(fx.ai_model_ready())
    assert findings == [] or findings[0].severity == "INFO"


def test_all_checks_has_six_entries():
    assert len(ALL_CHECKS) == 6


# --- Columns written as exported Model TML writes them -----------------------------
# `synonyms` and `ai_context` under `properties:`, `description` at the column root
# (counted across 599 Models on the SE demo cluster, 2026-10-21). The `fx.build_ai_col` helper
# (audit_rule_fixtures/ai.py) puts `synonyms` at the root, where real TML never does, which is how A2's
# root-only read went unnoticed: it scored every real Model 0%.


class TestA6MeasureAiContext:
    def test_full_coverage_is_clean(self):
        assert check_a6(fx.tml_measures_full_ai_context()) == []

    def test_no_coverage_is_high_and_names_the_measures(self):
        f = check_a6(fx.tml_measures_no_ai_context())
        assert len(f) == 1 and f[0].check_id == "A6" and f[0].severity == "HIGH"
        assert "0/2 measures" in f[0].detail and "Revenue" in f[0].detail and "Qty" in f[0].detail

    def test_partial_coverage_is_medium(self):
        f = check_a6(fx.tml_measures_partial_ai_context())
        assert f[0].severity == "MEDIUM" and f[0].metric == 60.0

    def test_attributes_are_not_counted(self):
        """An ID or label column with no ai_context is often correct (the coach schema:
        a surrogate key carries none), so attributes never lower the score."""
        assert check_a6(fx.tml_measure_and_ten_ids()) == []

    def test_hidden_measures_are_not_counted(self):
        assert check_a6(fx.tml_hidden_measure_uncovered()) == []

    def test_blank_ai_context_counts_as_missing(self):
        f = check_a6(fx.tml_measure_blank_ai_context())
        assert len(f) == 1

    def test_model_without_measures_is_skipped(self):
        assert check_a6(fx.tml_attribute_only()) == []

    def test_long_missing_list_is_truncated(self):
        f = check_a6(fx.tml_eight_measures_uncovered())
        assert "(+3 more)" in f[0].detail


class TestSynonymsUnderProperties:
    def test_a2_reads_properties_synonyms(self):
        assert check_a2(fx.tml_four_columns_with_synonyms()) == []

    def test_a2_still_flags_missing_synonyms(self):
        f = check_a2(fx.tml_four_columns_without_synonyms())
        assert len(f) == 1 and "0/4" in f[0].detail

    def test_a2_root_synonyms_still_count(self):
        assert check_a2(fx.tml_root_synonyms_column()) == []

    def test_a5_counts_properties_synonyms(self):
        """Same Model, synonyms present vs absent: the readiness score must differ by
        the synonym weight (15 points at 100% coverage)."""
        with_syn = check_a5(fx.tml_described_column_with_synonyms())
        without = check_a5(fx.tml_described_column())
        assert with_syn and without
        assert round(with_syn[0].metric - without[0].metric) == 15


# --- Assessment profiles (BL-399) ---------------------------------------------------
# One row per (check, profile): the pass mark, and HIGH below half of it. The table lives
# in ts_cli/audit/assessment.py; these pin each profile's promise from SKILL Step 2b.
import pytest  # noqa: E402

from ts_cli.audit import assessment  # noqa: E402


@pytest.mark.parametrize("profile,n_described,expected", [
    ("spotter", 95, None), ("spotter", 94, "MEDIUM"), ("spotter", 48, "MEDIUM"),
    ("spotter", 47, "HIGH"),
    ("general", 50, None), ("general", 49, "MEDIUM"), ("general", 25, "MEDIUM"),
    ("general", 24, "HIGH"),
])
def test_a1_by_profile(profile, n_described, expected):
    f = check_a1(_under(profile, fx.build_described_columns(n_described)))
    assert (f[0].severity if f else None) == expected


@pytest.mark.parametrize("profile,n_syn,expected", [
    ("spotter", 80, None), ("spotter", 79, "MEDIUM"), ("spotter", 39, "HIGH"),
    ("general", 25, None), ("general", 24, "MEDIUM"), ("general", 12, "HIGH"),
])
def test_a2_by_profile(profile, n_syn, expected):
    f = check_a2(_under(profile, fx.build_synonym_columns(n_syn)))
    assert (f[0].severity if f else None) == expected


@pytest.mark.parametrize("profile,expected", [("spotter", "HIGH"), ("general", "MEDIUM")])
def test_a3_a4_presence_by_profile(profile, expected):
    ctx = _under(profile, fx.ai_model_uncoached())
    assert [f.severity for f in check_a3(ctx)] == [expected]
    assert [f.severity for f in check_a4(ctx)] == [expected]


@pytest.mark.parametrize("profile,covered,expected", [
    ("spotter", 8, None), ("spotter", 7, "MEDIUM"), ("spotter", 3, "HIGH"),
    ("general", 8, None), ("general", 7, "LOW"), ("general", 0, "LOW"),
])
def test_a6_by_profile(profile, covered, expected):
    """AI context is required for Spotter-ready (graded) and recommended for General
    (a gap is LOW, however deep)."""
    f = check_a6(_under(profile, fx.build_tml_measures(covered)))
    assert (f[0].severity if f else None) == expected


def test_default_profile_is_general():
    assert make_context().assessment == "general" == assessment.DEFAULT


def test_threshold_payload_carries_the_profile_pass_mark():
    f = check_a1(_under("spotter", fx.build_described_columns(10)))
    assert f[0].threshold == {"green": 95, "yellow": 47.5, "assessment": "Spotter-ready"}
    f = check_a6(_under("general", fx.build_tml_measures(0, 1)))
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
