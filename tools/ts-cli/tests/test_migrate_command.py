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


# ---------------------------------------------------------------------------
# BL-152 — a same-Org audit must not pair a Model with ITSELF
# ---------------------------------------------------------------------------

_OWN = {"metadata_id": "9917a017", "metadata_name": "Sales",
        "metadata_type": "LOGICAL_TABLE", "metadata_header": {"ownerOrgId": 12750490}}
_MASTER = {"metadata_id": "2a743be3", "metadata_name": "Sales",
           "metadata_type": "LOGICAL_TABLE", "metadata_header": {"ownerOrgId": 0}}


def _same_org_clients(search_rows):
    """Source and target clients for a same-Org run, both seeing `search_rows`.

    Exports are dispatched by GUID so the test can tell which Model the audit chose as the
    target -- the whole point of the bug is that it chose the wrong one.
    """
    by_guid = {"9917a017": MODEL_EDOC, "2a743be3": TGT_EDOC}

    def post(path, json=None, **kw):
        if "tml/export" in path:
            guid = json["metadata"][0]["identifier"]
            return MagicMock(json=lambda: [{"edoc": by_guid[guid]}])
        if "metadata/search" in path:
            wanted = (json["metadata"][0] or {}).get("name_pattern")
            return MagicMock(json=lambda: list(search_rows) if wanted else [])
        return MagicMock(json=lambda: [])

    clients = []
    for _ in range(3):                     # source, target, and apply's unscoped read
        client = MagicMock()
        client.post.side_effect = post
        client.get.return_value = MagicMock(
            json=lambda: {"current_org": {"id": 12750490}})
        clients.append(client)
    return clients


@patch("ts_cli.migrate.discover.list_dependents", return_value=[])
@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.share.assert_org_context")
@patch("ts_cli.commands.share._resolve_org_id", return_value=12750490)
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_same_org_audit_targets_the_PUBLISHED_master_not_the_source(
        mock_cls, _rid, _assert, _rp, _deps, tmp_path):
    """The Org holds its own Model and the published master under ONE name. A name-only
    lookup returned the source, so the audit compared it with itself: every column
    trivially MATCHED, an empty rename map, verdict READY -- a no-op that passes every
    gate and breaks only once someone deletes the "old" Model (BL-152)."""
    mock_cls.side_effect = _same_org_clients([_OWN, _MASTER])

    result = runner.invoke(app, [
        "migrate", "audit", "--source-profile", "p", "--target-profile", "p",
        "--source-org", "ORG1", "--target-org", "ORG1",
        "--model", "9917a017", "--out-dir", str(tmp_path),
    ])

    assert result.exit_code == 0, (result.stdout + getattr(result, "stderr", ""))
    report = json.loads((tmp_path / "audit-report.json").read_text())
    model = report["models"][0]
    assert model["target_guid"] == "2a743be3", "audited the source against itself"
    # And the comparison is REAL, which is the half a self-pairing hides: the master has
    # no Department, so one column is a GAP. Paired with itself, both were MATCHED.
    assert model["column_counts"]["GAP"] == 1
    assert model["column_counts"]["MATCHED"] == 1


@patch("ts_cli.migrate.discover.list_dependents", return_value=[])
@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.share.assert_org_context")
@patch("ts_cli.commands.share._resolve_org_id", return_value=12750490)
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_same_org_audit_reports_NO_TARGET_when_the_master_is_not_published_in(
        mock_cls, _rid, _assert, _rp, _deps, tmp_path):
    """With only the tenant's own Model in the Org there is no target at all. Saying so is
    actionable -- publish the master first -- where READY was a lie."""
    mock_cls.side_effect = _same_org_clients([_OWN])

    result = runner.invoke(app, [
        "migrate", "audit", "--source-profile", "p", "--target-profile", "p",
        "--source-org", "ORG1", "--target-org", "ORG1",
        "--model", "9917a017", "--out-dir", str(tmp_path),
    ])

    assert result.exit_code == 0, (result.stdout + getattr(result, "stderr", ""))
    report = json.loads((tmp_path / "audit-report.json").read_text())
    assert report["models"][0]["target_guid"] is None
    assert report["models"][0]["readiness"] == "NO_TARGET"
    assert report["overall_ready"] is False
