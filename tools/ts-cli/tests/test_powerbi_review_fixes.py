"""Regression tests for the ts-convert-from-powerbi review fixes (PR #255, Damien)."""
from ts_cli.powerbi.tables import _cardinality, _col_role
from ts_cli.powerbi.functions import _refs_to_ids, _DAX_FUNC
from ts_cli.powerbi.answers import _spec_visual
from ts_cli.powerbi.build_model import assemble


# --- #2 cardinality: TMDL omits default-valued cardinality, so partial serialization
#     must not silently downgrade a non-default relationship to MANY_TO_ONE. ---
def test_cardinality_default_is_many_to_one():
    assert _cardinality({}) == "MANY_TO_ONE"


def test_cardinality_from_one_only_is_one_to_one():
    assert _cardinality({"fromCardinality": "one"}) == "ONE_TO_ONE"


def test_cardinality_to_many_only_is_many_to_many():
    # only toCardinality serialized (from defaults to 'many') -> the bridge / M:N case
    assert _cardinality({"toCardinality": "many"}) == "MANY_TO_MANY"


def test_cardinality_one_to_many():
    assert _cardinality({"fromCardinality": "one", "toCardinality": "many"}) == "ONE_TO_MANY"


# --- _col_role AVERAGE-from-summarizeBy (was never asserted; all fixtures used sum) ---
def test_col_role_average():
    assert _col_role({"name": "Amt", "dataType": "double", "summarizeBy": "average"}) == ("MEASURE", "AVERAGE")


def test_col_role_sum():
    assert _col_role({"name": "Amt", "dataType": "double", "summarizeBy": "sum"}) == ("MEASURE", "SUM")


# --- #3 ref hijack: a physical column sharing a measure's name must not be rewritten ---
def test_refs_to_ids_physical_qualified_not_hijacked():
    assert _refs_to_ids("SUM(Fact[Sales])", {"Sales"}, physical_cols={"Sales"}) == "SUM(Fact[Sales])"


def test_refs_to_ids_unqualified_measure_still_rewritten():
    assert _refs_to_ids("[Sales] + 1", {"Sales"}, physical_cols={"Sales"}) == "[formula_Sales] + 1"


def test_refs_to_ids_calc_column_rewritten():
    # a calc column (not physical) still rewrites, qualified or not
    assert _refs_to_ids("SUM(Employee[isNewHire])", {"isNewHire"}, physical_cols=set()) == "SUM([formula_isNewHire])"


# --- #6 trunc: no silently-wrong floor mapping (floor is wrong for negatives) ---
def test_trunc_unmapped_int_still_floor():
    assert "trunc" not in _DAX_FUNC
    assert _DAX_FUNC["int"] == "floor"


# --- #4 migration status is threaded, not a blanket "Migrated" ---
def test_spec_visual_gauge_reports_approximated():
    sv = _spec_visual({"type": "gauge", "fields": []}, 0, "P1", {}, {}, {}, {})
    assert sv["ts_chart"] == "KPI"
    assert sv["ts_chart_status"] == "Approximated"


# --- #5 a measure colliding (case-insensitively) with a physical column name is flagged
#     and NOT emitted as a duplicate-named formula. ---
def test_measure_colliding_with_physical_column_is_flagged_not_emitted():
    inv = {"tables": [{"name": "Fact",
                       "columns": [{"name": "Sales", "dataType": "double", "summarizeBy": "sum"}],
                       "measures": [{"name": "Sales", "expression": "SUM(Fact[Sales])"}]}],
           "relationships": [], "pages": []}
    files, mapping = assemble(inv, {}, "conn", "wh", "sch", "LEFT_OUTER", False, "M")
    row = next(r for r in mapping["measures"] if r["name"] == "Sales")
    assert row["status"] == "NEEDS REVIEW"
    assert "collides" in row["note"]
    model = next(t for f, t in files if f.endswith(".model.tml"))["model"]
    assert not any(fm["name"] == "Sales" for fm in model.get("formulas", []))
