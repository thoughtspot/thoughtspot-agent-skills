import json
from unittest.mock import MagicMock, patch

from ts_cli.cli import app

from runners import runner  # shared, stream-separated (BL-139)

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
    # Dispatch on the ENDPOINT rather than a fixed call order: the audit's call sequence
    # legitimately changes (it grew a transitive dependent walk), and a positional
    # side_effect list turns that into a spurious test failure rather than a real one.
    exports = iter([[{"edoc": MODEL_EDOC}], [{"edoc": ANSWER_EDOC}]])

    def src_post(path, json=None, **kw):
        if "tml/export" in path:
            return MagicMock(json=lambda: next(exports, []))
        return MagicMock(json=lambda: [])      # searches: no further dependents/subtypes

    src = MagicMock()
    src.post.side_effect = src_post
    # target client: find_model_by_name (search), then model_columns export
    def tgt_post(path, json=None, **kw):
        if "tml/export" in path:
            return MagicMock(json=lambda: [{"edoc": TGT_EDOC}])
        return MagicMock(json=lambda: [{"metadata_id": "tgt-1", "metadata_name": "Sales",
                                        "metadata_type": "LOGICAL_TABLE"}])

    tgt = MagicMock()
    tgt.post.side_effect = tgt_post
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


# ---------------------------------------------------------------------------
# BL-147 — audit must RESOLVE an Org name, never pass it through raw
# ---------------------------------------------------------------------------

@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.share.assert_org_context")
@patch("ts_cli.commands.share._resolve_org_id", return_value=12750490)
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_audit_resolves_an_org_NAME_to_a_numeric_id(mock_cls, mock_resolve, mock_assert, _rp,
                                                    tmp_path):
    """`auth/token/full` SILENTLY ignores a non-numeric `org_identifier` and falls back to
    the caller's default Org. Passing the name straight through therefore reads the WRONG
    ORG while reporting success -- and the audit produces the file a human approves, so
    that lands as a plausible column-mapping.csv for objects that are not the tenant's.

    The lucky failure is a missing GUID. The dangerous one is two Orgs with same-named
    Models, which is the normal shape of this migration.
    """
    src, tgt = MagicMock(), MagicMock()
    src.post.side_effect = [MagicMock(json=lambda: [{"edoc": MODEL_EDOC}]),
                            MagicMock(json=lambda: [])]
    tgt.post.side_effect = [MagicMock(json=lambda: []), MagicMock(json=lambda: [])]
    mock_cls.side_effect = [src, tgt]

    runner.invoke(app, ["migrate", "audit", "--source-profile", "src",
                        "--target-profile", "tgt", "--source-org", "ORG1",
                        "--model", "src-1", "--out-dir", str(tmp_path)])

    # The NAME went to the resolver, and the numeric id -- never the name -- to the client.
    assert mock_resolve.call_args_list[0].args[1] == "ORG1"
    assert mock_cls.call_args_list[0].kwargs["org"] == "12750490"
    # And the session was read back before being trusted.
    assert mock_assert.called


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_audit_without_an_org_builds_a_plain_client(mock_cls, _rp, tmp_path):
    """Omitting --source-org means "the profile's default Org", which must not be turned
    into a resolution attempt for the empty string."""
    src, tgt = MagicMock(), MagicMock()
    src.post.side_effect = [MagicMock(json=lambda: [{"edoc": MODEL_EDOC}]),
                            MagicMock(json=lambda: [])]
    tgt.post.side_effect = [MagicMock(json=lambda: []), MagicMock(json=lambda: [])]
    mock_cls.side_effect = [src, tgt]

    runner.invoke(app, ["migrate", "audit", "--source-profile", "src",
                        "--target-profile", "tgt", "--model", "src-1",
                        "--out-dir", str(tmp_path)])

    assert "org" not in mock_cls.call_args_list[0].kwargs
