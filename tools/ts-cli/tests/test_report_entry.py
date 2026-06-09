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


@patch("ts_cli.report.ThoughtSpotClient")
def test_build_report_with_deep_calls_alias_export(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    uuid = "baa451a6-02a0-42d1-8347-8cd4af13b505"
    # Call 1: resolve_source (GUID path → metadata/search)
    # Call 2: walk_dependents_recursive (empty deps → no Liveboard exports)
    # Call 3: alias/probe TML export (with_deep=True)
    client.post.side_effect = [
        _resp([{
            "metadata_id": "g-1", "metadata_name": "M",
            "metadata_type": "LOGICAL_TABLE",
            "metadata_header": {"id": "g-1", "name": "M"},
        }]),
        _resp([{"metadata_id": "g-1", "dependent_objects": {"dependents": {}}}]),
        _resp([{"info": {"type": "model"}, "edoc": "column_alias:\n  columns: []\n"}]),
    ]
    out = build_report(uuid, profile="test", with_deep=True)
    # Verify the alias export call was actually made (3rd call: resolve + walk + alias probe).
    assert client.post.call_count == 3
    third_call = client.post.call_args_list[2]
    assert "/api/rest/2.0/metadata/tml/export" in third_call.args[0]
    assert third_call.kwargs["json"]["export_options"]["export_with_column_aliases"] is True
    # Coverage should include Column alias TML row.
    assert any("alias" in c["type"].lower() for c in out["coverage"])
