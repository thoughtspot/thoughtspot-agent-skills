import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:  # older click
    runner = CliRunner()

MODEL_EDOC = json.dumps({
    "guid": "src-1",
    "model": {"name": "Sales", "columns": [
        {"name": "Amount", "column_id": "T::AMT", "properties": {"column_type": "MEASURE"}},
        {"name": "Department", "column_id": "T::DEPT", "properties": {"column_type": "ATTRIBUTE"}},
    ]},
})
TGT_EDOC = json.dumps({
    "guid": "tgt-1",
    "model": {"name": "Sales", "columns": [
        {"name": "Amount", "column_id": "T::AMT", "properties": {"column_type": "MEASURE"}},
    ]},
})
ANSWER_EDOC = json.dumps({"guid": "ans-1", "answer": {"name": "A1", "search_query": "[Department]"}})


@patch("ts_cli.migrate.discover.list_dependents", return_value=[{"type": "ANSWER", "guid": "ans-1", "name": "A1"}])
@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_audit_writes_mapping_and_flags_blocker(mock_cls, _rp, _deps, tmp_path):
    # source client export: model, then the dependent answer (for used-column scan)
    src = MagicMock()
    src.post.side_effect = [
        MagicMock(json=lambda: [{"edoc": MODEL_EDOC}]),   # export_parsed(mg) -- reused by model_columns via doc=
        MagicMock(json=lambda: [{"edoc": ANSWER_EDOC}]),  # used_column_names -> single batched dependent export
    ]
    # target client: find_model_by_name (search), then model_columns export
    tgt = MagicMock()
    tgt.post.side_effect = [
        MagicMock(json=lambda: [{"metadata_id": "tgt-1", "metadata_name": "Sales", "metadata_type": "LOGICAL_TABLE"}]),
        MagicMock(json=lambda: [{"edoc": TGT_EDOC}]),
    ]
    mock_cls.side_effect = [src, tgt]

    result = runner.invoke(app, [
        "migrate", "audit",
        "--source-profile", "src", "--target-profile", "tgt",
        "--model", "src-1", "--out-dir", str(tmp_path),
    ])

    assert result.exit_code == 0, (result.stdout + getattr(result, "stderr", ""))
    mapping = (tmp_path / "column-mapping.csv").read_text()
    assert "Department,T::DEPT,,GAP_BLOCKER" in mapping   # unmapped, used -> blocker
    assert "Amount,T::AMT,Amount,MATCHED" in mapping
    report = json.loads((tmp_path / "audit-report.json").read_text())
    assert report["overall_ready"] is False
