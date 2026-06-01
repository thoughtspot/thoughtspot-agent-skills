# tools/ts-cli/tests/test_report_entry.py
"""Tests for the report package's public entry points."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from ts_cli.report import build_report, build_reports


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    return r


@patch("ts_cli.report.ThoughtSpotClient")
def test_build_report_returns_dict_with_schema_version(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    # First call: resolve_source (search by GUID). Then: walk_dependents_recursive (empty).
    client.post.side_effect = [
        _resp([{
            "metadata_id": "g-1", "metadata_name": "X",
            "metadata_type": "LOGICAL_TABLE",
            "metadata_header": {"id": "g-1", "name": "X"},
        }]),
        _resp([{
            "metadata_id": "g-1", "dependent_objects": {
                "dependents": {"g-1": {}}
            }
        }]),
    ]

    out = build_report("baa451a6-02a0-42d1-8347-8cd4af13b505", profile="test", with_deep=False)
    assert out["schema_version"] == "1.0"
    assert out["source"]["guid"] == "g-1"


def test_build_reports_multi_source_shape():
    """Just check the wrapper shape on the multi-source entry."""
    with patch("ts_cli.report.build_report") as mock_single:
        mock_single.return_value = {"schema_version": "1.0", "source": {"guid": "a"}}
        out = build_reports(["a", "b"], profile="test", with_deep=False)
    assert out["schema_version"] == "1.0"
    assert len(out["reports"]) == 2
