from ts_cli.migrate.schema import (
    ColumnInfo, MATCHED, GAP, GAP_BLOCKER, BINDING_MISMATCH, READY, NEEDS_MAPPING, NO_TARGET,
)
from ts_cli.migrate.match import classify_columns, readiness, compare_model


def _rows_by_col(rows):
    return {r.tenant_column: r for r in rows}


def test_classify_matched_gap_blocker_and_binding_mismatch():
    source = [
        ColumnInfo("Amount", "T::AMT"),        # matches target exactly
        ColumnInfo("Department", "T::DEPT"),   # absent in target, used -> GAP_BLOCKER
        ColumnInfo("Notes", "T::NOTES"),       # absent in target, unused -> GAP
        ColumnInfo("Region", "T2::REGION"),    # name matches but binding differs
    ]
    target = [
        ColumnInfo("Amount", "T::AMT"),
        ColumnInfo("Region", "T::REG"),        # same display name, different column_id
    ]
    rows = classify_columns("Sales", source, target, used_names={"department"})
    by = _rows_by_col(rows)
    assert by["Amount"].status == MATCHED and by["Amount"].published_column == "Amount"
    assert by["Department"].status == GAP_BLOCKER and by["Department"].published_column == ""
    assert by["Notes"].status == GAP
    assert by["Region"].status == BINDING_MISMATCH and by["Region"].published_column == "Region"


def test_matching_is_case_insensitive():
    source = [ColumnInfo("amount", "T::AMT")]
    target = [ColumnInfo("Amount", "T::AMT")]
    rows = classify_columns("Sales", source, target, used_names=set())
    assert rows[0].status == MATCHED


def test_readiness_no_target_then_needs_mapping_then_ready():
    src = [ColumnInfo("Department", "T::DEPT")]
    # No target model at all
    comp = compare_model("Sales", "g1", None, src, [], {"department"}, dependents=[{"guid": "a"}])
    assert comp.readiness == NO_TARGET
    # Target exists but blocker unmapped
    comp2 = compare_model("Sales", "g1", "g2", src, [], {"department"}, dependents=[])
    assert comp2.readiness == NEEDS_MAPPING
    # Target exists, all columns matched
    comp3 = compare_model("Sales", "g1", "g2", [ColumnInfo("Amount", "T::AMT")],
                          [ColumnInfo("Amount", "T::AMT")], set(), dependents=[])
    assert comp3.readiness == READY
