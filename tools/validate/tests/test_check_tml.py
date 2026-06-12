"""Unit tests for check_tml.validate_model_tml — invariants I4 and I5 (BL-001)."""
import sys
from pathlib import Path

# check_tml.py lives one directory up; import it without packaging.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_tml  # noqa: E402


def _model(**inner):
    return {"model": inner}


# ── I4: join id (when present) must equal name, exact case ──────────────────

def test_i4_id_case_mismatch_is_flagged():
    data = _model(
        model_tables=[{"id": "fact_orders", "name": "FACT_ORDERS"}],
        columns=[], formulas=[],
    )
    errors = check_tml.validate_model_tml(data)
    assert any("does not equal name" in e for e in errors), errors


def test_i4_id_equals_name_passes():
    data = _model(
        model_tables=[{"id": "FACT_ORDERS", "name": "FACT_ORDERS"}],
        columns=[], formulas=[],
    )
    errors = check_tml.validate_model_tml(data)
    assert not any("does not equal name" in e for e in errors), errors


def test_i4_id_omitted_passes():
    data = _model(
        model_tables=[{"name": "FACT_ORDERS"}],
        columns=[], formulas=[],
    )
    errors = check_tml.validate_model_tml(data)
    assert not any("does not equal name" in e for e in errors), errors


# ── I5: COUNT_DISTINCT aggregation on a physical column is forbidden ─────────

def test_i5_count_distinct_on_physical_column_is_flagged():
    data = _model(
        model_tables=[{"name": "ORDERS"}],
        formulas=[],
        columns=[{
            "name": "Unique Customers",
            "column_id": "ORDERS::customer_id",
            "properties": {"column_type": "MEASURE", "aggregation": "COUNT_DISTINCT"},
        }],
    )
    errors = check_tml.validate_model_tml(data)
    assert any("COUNT_DISTINCT" in e for e in errors), errors


def test_i5_unique_count_formula_passes():
    data = _model(
        model_tables=[{"name": "ORDERS"}],
        formulas=[{
            "id": "formula_Unique Customers", "name": "Unique Customers",
            "expr": "unique count ( [ORDERS::customer_id] )",
            "properties": {"column_type": "MEASURE"},
        }],
        columns=[{
            "name": "Unique Customers", "formula_id": "formula_Unique Customers",
            "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                           "index_type": "DONT_INDEX"},
        }],
    )
    errors = check_tml.validate_model_tml(data)
    assert not any("COUNT_DISTINCT" in e for e in errors), errors
