"""`ts migrate rollback` against the CURRENT ledger schema.

Rollback shipped reading the eight-step executor's ledger (`created[lift_content]`,
`kinds.models`) after the three-step rewrite (PR #367) stopped writing it -- and the
import of the retired step constants made the command crash outright, which nothing
caught because the import was function-local and the command had no tests (audit
2026-07-29, finding 17.1). These tests pin the command to the ledger `apply` actually
writes, and pin the refusals that keep it from deleting real content.
"""
import json
from unittest.mock import MagicMock, patch

from ts_cli.cli import app
from ts_cli.migrate.apply_plan import (
    STEP_MOVE_SHIELDED, STEP_REWRITE_CONTENT, STEP_REWRITE_VIEWS, import_mode,
    new_ledger, rollback_refusal, rollback_sets,
)

from runners import runner  # shared, stream-separated (BL-139)


def _new_org_ledger():
    """A ledger as the current executor writes it after a completed new-Org apply."""
    ledger = new_ledger({"source": "ORG_A", "target": "ORG_B"},
                        import_mode("ORG_A", "ORG_B", "prof", "prof"))
    ledger["completed"] = [
        "backup", STEP_REWRITE_VIEWS, STEP_REWRITE_CONTENT, STEP_MOVE_SHIELDED]
    ledger["created"] = {
        STEP_REWRITE_VIEWS: {"Sales View": "view-1"},
        STEP_REWRITE_CONTENT: {"Revenue Answer": "ans-1", "KPI Board": "lb-1"},
        STEP_MOVE_SHIELDED: {"Shielded Answer": "ans-2"},
    }
    return ledger


# ---------------------------------------------------------------------------
# The pure helpers
# ---------------------------------------------------------------------------

def test_rollback_sets_reads_the_ledger_the_executor_writes():
    """The delete-set comes from rewrite_content + move_shielded (content) and
    rewrite_views (Views) -- the keys `record_completed` actually records. The old
    command read `lift_content`/`kinds`, which no step writes, so a real apply rolled
    back as 'Nothing to roll back'."""
    content, views = rollback_sets(_new_org_ledger())
    assert content == {"Revenue Answer": "ans-1", "KPI Board": "lb-1",
                       "Shielded Answer": "ans-2"}
    assert views == {"Sales View": "view-1"}


def test_rollback_sets_is_empty_on_a_fresh_ledger():
    content, views = rollback_sets(new_ledger({"source": "A", "target": "B"}))
    assert content == {} and views == {}


def test_same_org_ledger_is_refused():
    """A same-Org apply updates objects IN PLACE: the recorded guids are the tenant's
    originals, and deleting them is data loss, not an undo."""
    ledger = new_ledger({"source": "ORG_A", "target": "ORG_A"},
                        import_mode("ORG_A", "ORG_A", "prof", "prof"))
    assert "backup/" in rollback_refusal(ledger)


def test_new_org_ledger_is_not_refused():
    assert rollback_refusal(_new_org_ledger()) is None


def test_legacy_ledger_without_mode_is_refused_only_on_equal_orgs():
    """Ledgers written before `mode` was recorded carry only the pair. Equal Org names
    read as a same-Org run and are refused conservatively; distinct names are the
    normal new-Org topology and proceed."""
    legacy_same = {"pair": {"source": "ORG_A", "target": "ORG_A"}, "created": {}}
    legacy_cross = {"pair": {"source": "ORG_A", "target": "ORG_B"}, "created": {}}
    assert rollback_refusal(legacy_same) is not None
    assert rollback_refusal(legacy_cross) is None


def test_new_ledger_records_the_mode():
    mode = import_mode("A", "B", "p", "p")
    assert new_ledger({"source": "A", "target": "B"}, mode)["mode"] == mode


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def _write_state(tmp_path, ledger):
    (tmp_path / "state.json").write_text(json.dumps(ledger))


def test_dry_run_lists_the_delete_set_offline(tmp_path):
    """--dry-run must work with no client at all: it is the first thing an operator
    runs, possibly before credentials for the broken target even exist."""
    _write_state(tmp_path, _new_org_ledger())
    result = runner.invoke(app, ["migrate", "rollback", "-d", str(tmp_path),
                                 "--dry-run"])
    assert result.exit_code == 0
    assert "view-1" in result.stdout and "ans-1" in result.stdout
    assert "nothing was deleted" in result.stderr.lower()


def test_command_refuses_a_same_org_ledger(tmp_path):
    ledger = new_ledger({"source": "ORG_A", "target": "ORG_A"},
                        import_mode("ORG_A", "ORG_A", "prof", "prof"))
    ledger["created"] = {STEP_REWRITE_CONTENT: {"A1": "ans-1"}}
    _write_state(tmp_path, ledger)
    result = runner.invoke(app, ["migrate", "rollback", "-d", str(tmp_path),
                                 "--dry-run"])
    assert result.exit_code == 1
    assert "backup/" in result.stderr


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.share.assert_org_context")
@patch("ts_cli.commands.share._resolve_org_id", return_value=1)
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_live_rollback_deletes_with_the_right_type_per_object(
        mock_cls, _rid, _assert, _rp, tmp_path):
    """The delete endpoint requires the correct `type` per item. The old command sent
    LOGICAL_TABLE for everything, which cannot delete an Answer or Liveboard."""
    search_rows = [
        {"metadata_id": "ans-1", "metadata_type": "ANSWER"},
        {"metadata_id": "ans-2", "metadata_type": "ANSWER"},
        {"metadata_id": "lb-1", "metadata_type": "LIVEBOARD"},
        {"metadata_id": "view-1", "metadata_type": "LOGICAL_TABLE"},
    ]
    deletes = []

    def post(path, json=None, **kw):
        if "metadata/search" in path:
            return MagicMock(json=lambda: search_rows)
        if "metadata/delete" in path:
            deletes.append(json["metadata"])
            return MagicMock(status_code=204)
        return MagicMock(json=lambda: [])

    client = MagicMock()
    client.post.side_effect = post
    mock_cls.return_value = client

    _write_state(tmp_path, _new_org_ledger())
    result = runner.invoke(app, ["migrate", "rollback", "-d", str(tmp_path),
                                 "--target-profile", "tgt"])
    assert result.exit_code == 0, result.stderr

    assert len(deletes) == 2                       # content batch, then Views batch
    content_batch, views_batch = deletes
    assert {(m["identifier"], m["type"]) for m in content_batch} == {
        ("ans-1", "ANSWER"), ("ans-2", "ANSWER"), ("lb-1", "LIVEBOARD")}
    assert views_batch == [{"identifier": "view-1", "type": "LOGICAL_TABLE"}]


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.share.assert_org_context")
@patch("ts_cli.commands.share._resolve_org_id", return_value=1)
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_objects_already_gone_are_skipped_not_errors(
        mock_cls, _rid, _assert, _rp, tmp_path):
    """Re-runnability: a second rollback after a partial first one must finish the job,
    and the search simply not returning a guid means it is already deleted."""
    def post(path, json=None, **kw):
        if "metadata/search" in path:
            return MagicMock(json=lambda: [
                {"metadata_id": "view-1", "metadata_type": "LOGICAL_TABLE"}])
        if "metadata/delete" in path:
            assert all(m["identifier"] == "view-1" for m in json["metadata"])
            return MagicMock(status_code=204)
        return MagicMock(json=lambda: [])

    client = MagicMock()
    client.post.side_effect = post
    mock_cls.return_value = client

    _write_state(tmp_path, _new_org_ledger())
    result = runner.invoke(app, ["migrate", "rollback", "-d", str(tmp_path),
                                 "--target-profile", "tgt"])
    assert result.exit_code == 0, result.stderr
    assert "already gone" in result.stderr
