"""Unit tests for ts_cli.powerbi.parsing — PBIR field resolution and the aggregation enum.

Added per PR #255 review: parsing.py had no test file, and the QueryAggregateFunction
enum was wrong (a single `_field_ref` assertion catches it)."""
from ts_cli.powerbi.parsing import _field_ref, _AGG_FUNC


def _agg_field(func, prop="Amount", entity="Sales"):
    return {"Aggregation": {"Function": func,
            "Expression": {"Column": {"Property": prop,
                           "Expression": {"SourceRef": {"Entity": entity}}}}}}


def test_aggregation_enum_documented_order():
    # QueryAggregateFunction: Sum=0, Avg=1, Count=2, Min=3, Max=4, CountNonNull=5
    assert [_AGG_FUNC[i] for i in range(6)] == ["sum", "average", "count", "min", "max", "count"]


def test_field_ref_min_resolves_to_min_not_max():
    # regression: Function=3 (Min) used to resolve to "max", so an inline Min(...) missed the
    # agg_measures lookup and the field was silently dropped.
    assert _field_ref(_agg_field(3)) == ("Amount", "Sales", "aggregation", "min")


def test_field_ref_count_and_max():
    assert _field_ref(_agg_field(2))[3] == "count"
    assert _field_ref(_agg_field(4))[3] == "max"


def test_field_ref_unknown_code_flags_rather_than_defaulting_to_sum():
    # regression: an unmapped code used to default to "sum" (silently wrong); now None so the
    # caller flags the field as missing instead.
    assert _field_ref(_agg_field(99))[3] is None


def test_field_ref_column_and_measure():
    col = {"Column": {"Property": "Region", "Expression": {"SourceRef": {"Entity": "Geo"}}}}
    assert _field_ref(col) == ("Region", "Geo", "column", None)
    meas = {"Measure": {"Property": "New Hires", "Expression": {"SourceRef": {"Entity": "Employee"}}}}
    assert _field_ref(meas) == ("New Hires", "Employee", "measure", None)
