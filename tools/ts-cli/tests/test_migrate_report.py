from ts_cli.migrate.schema import ColumnMappingRow, ModelComparison, MATCHED, GAP_BLOCKER, READY, NEEDS_MAPPING
from ts_cli.migrate.report import build_report, render_markdown


def _comp(readiness, rows, deps=()):
    return ModelComparison("Sales", "g1", "g2", rows, list(deps), readiness)


def test_build_report_counts_and_overall():
    rows = [
        ColumnMappingRow("Sales", "Amount", "T::AMT", "Amount", MATCHED),
        ColumnMappingRow("Sales", "Department", "T::DEPT", "", GAP_BLOCKER),
    ]
    report = build_report([_comp(NEEDS_MAPPING, rows, deps=[{"guid": "a"}])])
    assert report["overall_ready"] is False
    m = report["models"][0]
    assert m["column_counts"]["MATCHED"] == 1
    assert m["column_counts"]["GAP_BLOCKER"] == 1
    assert m["blocker_columns"] == ["Department"]
    assert m["dependent_count"] == 1


def test_overall_ready_true_when_all_ready():
    rows = [ColumnMappingRow("Sales", "Amount", "T::AMT", "Amount", MATCHED)]
    report = build_report([_comp(READY, rows)])
    assert report["overall_ready"] is True


def test_render_markdown_includes_model_and_blockers():
    rows = [ColumnMappingRow("Sales", "Department", "T::DEPT", "", GAP_BLOCKER)]
    md = render_markdown(build_report([_comp(NEEDS_MAPPING, rows)]))
    assert "# Org Migration Audit" in md
    assert "Sales" in md and "Department" in md
