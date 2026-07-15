# tools/ts-cli/tests/test_migrate_schema.py
from ts_cli.migrate.schema import (
    ColumnInfo, ColumnMappingRow, ModelComparison,
    MATCHED, GAP, GAP_BLOCKER, BINDING_MISMATCH, READY, NEEDS_MAPPING, NO_TARGET,
)


def test_column_info_defaults():
    c = ColumnInfo(name="Amount", column_id="T::AMT")
    assert c.column_type == ""


def test_model_comparison_defaults():
    m = ModelComparison(model_name="Sales", source_model_guid="g1", target_model_guid=None, rows=[])
    assert m.dependents == []
    assert m.readiness == NEEDS_MAPPING


def test_status_constants_are_distinct_strings():
    assert len({MATCHED, GAP, GAP_BLOCKER, BINDING_MISMATCH}) == 4
    assert len({READY, NEEDS_MAPPING, NO_TARGET}) == 3
    assert MATCHED == "MATCHED"
