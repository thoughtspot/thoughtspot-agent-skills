from ts_cli.migrate.schema import ColumnMappingRow, ModelComparison, MATCHED, GAP_BLOCKER
from ts_cli.migrate.mapping import HEADER, write_mapping, read_mapping, validate_mapping


def test_write_then_read_round_trips(tmp_path):
    comp = ModelComparison(
        model_name="Sales", source_model_guid="g1", target_model_guid="g2",
        rows=[
            ColumnMappingRow("Sales", "Amount", "T::AMT", "Amount", MATCHED),
            ColumnMappingRow("Sales", "Department", "T::DEPT", "", GAP_BLOCKER),
        ],
    )
    p = tmp_path / "column-mapping.csv"
    write_mapping(p, [comp])
    assert p.read_text().splitlines()[0] == ",".join(HEADER)
    rows = read_mapping(p)
    assert len(rows) == 2
    assert rows[1].tenant_column == "Department" and rows[1].status == GAP_BLOCKER


def test_validate_flags_unmapped_blocker():
    rows = [ColumnMappingRow("Sales", "Department", "T::DEPT", "", GAP_BLOCKER)]
    errors = validate_mapping(rows)
    assert len(errors) == 1 and "Department" in errors[0]


def test_validate_passes_when_blocker_mapped():
    rows = [ColumnMappingRow("Sales", "Department", "T::DEPT", "String1", GAP_BLOCKER)]
    assert validate_mapping(rows) == []
