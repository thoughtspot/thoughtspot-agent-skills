"""Unit tests for ts_cli.tml_lint.lint_tml — the pre-import invariant linter.

Each invariant (I1/I2/I4/I5 + guid placement) gets a positive (violating) case and
the clean baseline is asserted to produce zero findings. Pure-function tests — no
ThoughtSpot connection required.
"""
from ts_cli.tml_lint import lint_tml


# A minimal, valid model TML: one physical column, one formula with its paired
# columns[] entry, one model_table whose id == name. lint_tml() must return [].
def _clean_model() -> dict:
    return {
        "guid": "abc-123",
        "model": {
            "name": "SALES",
            "model_tables": [{"name": "ORDERS", "id": "ORDERS"}],
            "columns": [
                {"name": "Amount", "properties": {"aggregation": "SUM"}},
                {"name": "Revenue", "formula_id": "f_rev"},
            ],
            "formulas": [{"id": "f_rev", "name": "Revenue", "expr": "sum([Amount])"}],
        },
    }


def test_clean_model_has_no_findings():
    assert lint_tml(_clean_model()) == []


def test_non_mapping_top_level_is_flagged():
    assert lint_tml(["not", "a", "dict"]) == ["Top-level TML value must be a mapping"]


def test_guid_nested_in_model_is_flagged():
    data = _clean_model()
    data["model"]["guid"] = "abc-123"
    findings = lint_tml(data)
    assert any("guid is nested inside 'model:'" in f for f in findings)


def test_guid_nested_in_table_is_flagged():
    data = {"table": {"name": "ORDERS", "guid": "x"}}
    findings = lint_tml(data)
    assert any("guid is nested inside 'table:'" in f for f in findings)


def test_table_only_tml_returns_after_guid_check():
    # A table TML (no model:) is not linted for I1/I2/I4/I5; clean table → no findings.
    assert lint_tml({"table": {"name": "ORDERS"}}) == []


def test_i1_unpaired_formula_is_flagged():
    data = _clean_model()
    data["model"]["formulas"].append({"id": "f_orphan", "name": "Orphan", "expr": "1"})
    findings = lint_tml(data)
    assert any(f.startswith("I1:") and "f_orphan" in f for f in findings)


def test_i2_aggregation_in_formula_is_flagged():
    data = _clean_model()
    data["model"]["formulas"][0]["properties"] = {"aggregation": "SUM"}
    findings = lint_tml(data)
    assert any(f.startswith("I2:") and "f_rev" in f for f in findings)


def test_i4_model_table_id_mismatch_is_flagged():
    data = _clean_model()
    data["model"]["model_tables"][0]["id"] = "orders"  # case differs from name
    findings = lint_tml(data)
    assert any(f.startswith("I4:") for f in findings)


def test_i4_missing_id_is_not_flagged():
    # id is optional; absence is valid (name becomes the join target).
    data = _clean_model()
    del data["model"]["model_tables"][0]["id"]
    assert lint_tml(data) == []


def test_i5_count_distinct_on_physical_column_is_flagged():
    data = _clean_model()
    data["model"]["columns"][0]["properties"]["aggregation"] = "COUNT_DISTINCT"
    findings = lint_tml(data)
    assert any(f.startswith("I5:") and "Amount" in f for f in findings)


def test_i5_does_not_flag_formula_columns():
    # A formula column may legitimately resolve to a unique count; only physical
    # columns are checked for COUNT_DISTINCT.
    data = _clean_model()
    data["model"]["columns"][1]["properties"] = {"aggregation": "COUNT_DISTINCT"}
    assert lint_tml(data) == []


def test_i8_duplicate_column_id_is_flagged():
    data = _clean_model()
    data["model"]["columns"] = [
        {"name": "Total Salary", "column_id": "EMP::SALARY", "properties": {"aggregation": "SUM"}},
        {"name": "Avg Salary", "column_id": "EMP::SALARY", "properties": {"aggregation": "AVERAGE"}},
    ]
    findings = lint_tml(data)
    assert any(f.startswith("I8:") and "EMP::SALARY" in f for f in findings)


def test_i8_unique_column_ids_pass():
    data = _clean_model()
    data["model"]["columns"] = [
        {"name": "Total Salary", "column_id": "EMP::SALARY", "properties": {"aggregation": "SUM"}},
        {"name": "Headcount", "column_id": "EMP::ID", "properties": {"aggregation": "COUNT"}},
    ]
    assert not any(f.startswith("I8:") for f in lint_tml(data))


def test_i12_bare_column_id_on_single_table_model_is_flagged():
    # Live-verified (se-thoughtspot, 2026-07-23): a bare column_id ("REGION") on a
    # single-table model fails import ("These column_id/formula_id values are
    # incorrect"); the TABLE::col-qualified form validates. ts tml lint must catch
    # this locally since --policy VALIDATE_ONLY's own error only surfaces at import.
    data = _clean_model()
    data["model"]["columns"] = [
        {"name": "Region", "column_id": "REGION", "properties": {"column_type": "ATTRIBUTE"}},
    ]
    findings = lint_tml(data)
    assert any(f.startswith("I12:") and "REGION" in f for f in findings)


def test_i12_qualified_column_id_on_single_table_model_passes():
    data = _clean_model()
    data["model"]["columns"] = [
        {"name": "Region", "column_id": "ORDERS::REGION", "properties": {"column_type": "ATTRIBUTE"}},
    ]
    assert not any(f.startswith("I12:") for f in lint_tml(data))


def test_i12_does_not_flag_multi_table_models():
    # Multi-table ownership resolution is a separate, harder problem (see
    # BL follow-up #2/#4) — scoping I12 to single-table avoids false positives on
    # pre-existing, out-of-scope junk columns in real multi-table conversions.
    data = _clean_model()
    data["model"]["model_tables"].append({"name": "CUSTOMERS"})
    data["model"]["columns"] = [
        {"name": "Region", "column_id": "REGION", "properties": {"column_type": "ATTRIBUTE"}},
    ]
    assert not any(f.startswith("I12:") for f in lint_tml(data))


def test_i12_does_not_flag_missing_column_id():
    # A column with neither column_id nor formula_id is out of scope for this
    # check (it's a different, pre-existing test-fixture shorthand elsewhere in
    # this suite) — I12 only fires when column_id is present but unqualified.
    data = _clean_model()
    assert not any(f.startswith("I12:") for f in lint_tml(data))


def test_i12_does_not_flag_formula_columns():
    data = _clean_model()
    data["model"]["columns"] = [
        {"name": "Revenue", "formula_id": "formula_Revenue", "properties": {"column_type": "MEASURE"}},
    ]
    data["model"]["formulas"] = [{"id": "formula_Revenue", "name": "Revenue", "expr": "sum([ORDERS::AMOUNT])"}]
    assert not any(f.startswith("I12:") for f in lint_tml(data))


# ---------------------------------------------------------------------------
# I13 — dangling [formula_*] cross-references (BL-183, promoted from BL-178)
# ---------------------------------------------------------------------------

def _model_with_formula_refs(inner_id: str, ref: str) -> dict:
    """A two-formula model where the outer formula references `ref`."""
    return {
        "model": {
            "name": "SALES",
            "model_tables": [{"name": "ORDERS"}, {"name": "CUSTOMERS"}],
            "columns": [
                {"name": "Tenure Months", "formula_id": inner_id},
                {"name": "Avg Tenure", "formula_id": "formula_Avg Tenure"},
            ],
            "formulas": [
                {"id": inner_id, "name": "Tenure Months",
                 "expr": "diff_months ( today ( ) , [ORDERS::HIRE_DATE] )"},
                {"id": "formula_Avg Tenure", "name": "Avg Tenure",
                 "expr": f"average ( [{ref}] )"},
            ],
        },
    }


def test_i13_resolving_id_reference_passes():
    # The positive case — the check must not be satisfiable by rejecting every
    # bracket reference (BL-183 approach step 1).
    data = _model_with_formula_refs("formula_Tenure Months", "formula_Tenure Months")
    assert not any(f.startswith("I13:") for f in lint_tml(data))


def test_i13_dangling_formula_reference_in_expr_is_flagged():
    # BL-178's exact symptom: the emitted ref is the SQL token, the minted id is
    # the display name, so the reference matches nothing.
    data = _model_with_formula_refs("formula_Tenure Months", "formula_tenure_months")
    findings = [f for f in lint_tml(data) if f.startswith("I13:")]
    assert len(findings) == 1
    assert "formula_tenure_months" in findings[0]
    # names the referring formula so the finding is actionable
    assert "formula_Avg Tenure" in findings[0]


def test_i13_dangling_column_formula_id_is_flagged():
    data = _clean_model()
    data["model"]["columns"].append(
        {"name": "Orphan", "formula_id": "formula_Missing"})
    findings = [f for f in lint_tml(data) if f.startswith("I13:")]
    assert len(findings) == 1
    assert "formula_Missing" in findings[0]


def test_i13_ignores_table_qualified_and_plain_refs():
    # `[TABLE::COL]` refs and display-name refs are other invariants' business
    # (XREF / I9) — I13 only gates `formula_*`-prefixed id references.
    data = _clean_model()
    data["model"]["formulas"] = [
        {"id": "f_rev", "name": "Revenue",
         "expr": "sum ( [ORDERS::AMOUNT] ) + [Some Other Name]"},
    ]
    data["model"]["columns"] = [{"name": "Revenue", "formula_id": "f_rev"}]
    assert not any(f.startswith("I13:") for f in lint_tml(data))


def test_i13_flags_every_distinct_dangling_ref_once():
    data = _clean_model()
    data["model"]["formulas"] = [
        {"id": "f_a", "name": "A", "expr": "sum ( [formula_x] ) + [formula_y]"},
    ]
    data["model"]["columns"] = [{"name": "A", "formula_id": "f_a"}]
    findings = [f for f in lint_tml(data) if f.startswith("I13:")]
    assert len(findings) == 2


def test_multiple_violations_accumulate():
    data = _clean_model()
    data["model"]["guid"] = "x"
    data["model"]["formulas"].append({"id": "f_orphan", "name": "O", "expr": "1"})
    data["model"]["model_tables"][0]["id"] = "orders"
    findings = lint_tml(data)
    assert len(findings) >= 3
