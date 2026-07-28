"""Share-grant scoping and the sets-scan default in `ts migrate apply`
(audit 2026-07-29 findings 17.5/17.6).
"""
import json
from unittest.mock import MagicMock, patch

from ts_cli.cli import app
from ts_cli.migrate import apply_exec
from ts_cli.migrate.apply_plan import (STEP_MOVE_SHIELDED, STEP_REWRITE_CONTENT,
                                       STEP_SHARE, new_ledger)
from ts_cli.migrate.mapping import write_mapping
from ts_cli.migrate.schema import ColumnMappingRow, MATCHED, ModelComparison

from runners import runner  # shared, stream-separated (BL-139)


# ---------------------------------------------------------------------------
# 17.5 -- content grants are per-object, never the union
# ---------------------------------------------------------------------------

def _share_calls(target_client):
    """(guid, group) pairs actually granted through the share endpoint."""
    pairs = set()
    for call in target_client.post.call_args_list:
        if "security/metadata/share" not in call.args[0]:
            continue
        body = call.kwargs["json"]
        pairs.add((body["metadata_identifiers"][0],
                   body["permissions"][0]["principal"]["identifier"]))
    return pairs


def _run_grants(wanted, target=None):
    objects = [{"guid": "src-a1", "name": "A1", "type": "ANSWER"},
               {"guid": "src-a2", "name": "A2", "type": "ANSWER"}]
    ledger = new_ledger({"source": "A", "target": "B"})
    ledger["created"] = {STEP_REWRITE_CONTENT: {"A1": "new-a1", "A2": "new-a2"},
                         STEP_MOVE_SHIELDED: {}}
    tgt = MagicMock()
    tgt.post.return_value = MagicMock(status_code=204)
    ctx = apply_exec.Ctx(MagicMock(), tgt, None, ledger)
    step = {"step": STEP_SHARE, "objects": objects, "target": target or {},
            "mode": {"same_org": False}, "pair": {}}
    with patch.object(apply_exec, "source_group_grants", return_value=wanted), \
         patch.object(apply_exec, "target_stack",
                      return_value=([{"guid": "model-1", "type": "LOGICAL_TABLE"}]
                                    if (target or {}).get("guid") else [])):
        apply_exec.run_share_grants(ctx, step)
    return _share_calls(tgt)


def test_content_gets_its_own_groups_not_the_union():
    """An Answer shared only with Finance on the source must not become visible to HR
    because some other migrated object was shared with HR. The union widened access
    silently, in the step that exists to reproduce the SOURCE's sharing."""
    pairs = _run_grants({"A1": ["Finance"], "A2": ["HR"]})
    assert ("new-a1", "Finance") in pairs and ("new-a2", "HR") in pairs
    assert ("new-a1", "HR") not in pairs
    assert ("new-a2", "Finance") not in pairs


def test_the_shared_stack_still_takes_the_union():
    """Every group DOES need the whole Table -> Model chain: a grant on content whose
    Model is ungranted is accepted and silently dropped (BL-150). Union on the stack is
    the fix for that, and must survive the per-object change."""
    pairs = _run_grants({"A1": ["Finance"], "A2": ["HR"]},
                        target={"guid": "tgt-model"})
    assert ("model-1", "Finance") in pairs and ("model-1", "HR") in pairs


def test_content_with_no_source_grants_gets_none():
    pairs = _run_grants({"A1": ["Finance"]})
    assert not [p for p in pairs if p[0] == "new-a2"]


# ---------------------------------------------------------------------------
# 17.6 -- a bare apply scans for cohort columns itself
# ---------------------------------------------------------------------------

_MODEL_ROW = {"metadata_id": "g1", "metadata_name": "Sales",
              "metadata_type": "LOGICAL_TABLE",
              "metadata_header": {"ownerOrgId": 1}}
_COHORT_ROW = {"metadata_id": "cc-1", "metadata_name": "Region Set",
               "metadata_header": {"owner": "g1", "type": "COHORT_ATTRIBUTE"}}


def _client(cohort_rows):
    def post(path, json=None, **kw):
        if "metadata/search" in path:
            meta = (json or {}).get("metadata", [{}])[0]
            if meta.get("type") == "LOGICAL_COLUMN":
                return MagicMock(json=lambda: list(cohort_rows))
            if meta.get("name_pattern"):
                return MagicMock(json=lambda: [_MODEL_ROW])
        return MagicMock(json=lambda: [])

    client = MagicMock()
    client.post.side_effect = post
    client.get.return_value = MagicMock(json=lambda: {"current_org": {"id": 1}})
    return client


def _write_single_model_mapping(tmp_path):
    write_mapping(tmp_path / "column-mapping.csv", [
        ModelComparison(model_name="Sales", source_model_guid="g1",
                        target_model_guid="g2",
                        rows=[ColumnMappingRow("Sales", "Amount", "T::A",
                                               "Amount", MATCHED)])])


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_a_bare_apply_refuses_a_set_carrying_model(mock_cls, _rp, tmp_path):
    """The docs promise `apply` refuses a cohort-carrying Model with no override, but
    the refusal only fired when the operator happened to pass --sets-scan -- a bare
    apply proceeded and dropped the Set silently (cohort columns are invisible in TML,
    so nothing downstream catches it)."""
    mock_cls.return_value = _client([_COHORT_ROW])
    _write_single_model_mapping(tmp_path)
    result = runner.invoke(app, ["migrate", "apply", "-d", str(tmp_path),
                                 "--source-profile", "src",
                                 "--target-profile", "tgt", "--dry-run"])
    assert result.exit_code == 1
    assert "SET_BLOCKER" in result.stderr


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_a_clean_model_passes_the_self_scan(mock_cls, _rp, tmp_path):
    mock_cls.return_value = _client([])
    _write_single_model_mapping(tmp_path)
    result = runner.invoke(app, ["migrate", "apply", "-d", str(tmp_path),
                                 "--source-profile", "src",
                                 "--target-profile", "tgt", "--dry-run"])
    assert "SET_BLOCKER" not in result.stderr


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_a_supplied_sets_scan_skips_the_self_scan(mock_cls, _rp, tmp_path):
    """An operator who ran `scan-sets` already paid for the answer -- apply must trust
    the file rather than re-scanning the Org."""
    client = _client([_COHORT_ROW])       # a self-scan WOULD find a blocker
    mock_cls.return_value = client
    _write_single_model_mapping(tmp_path)
    scan = tmp_path / "sets-scan.json"
    scan.write_text(json.dumps({"blocked": []}))
    result = runner.invoke(app, ["migrate", "apply", "-d", str(tmp_path),
                                 "--sets-scan", str(scan),
                                 "--source-profile", "src",
                                 "--target-profile", "tgt", "--dry-run"])
    assert "SET_BLOCKER" not in result.stderr
    column_searches = [c for c in client.post.call_args_list
                       if "metadata/search" in c.args[0]
                       and (c.kwargs.get("json") or {}).get("metadata",
                                                            [{}])[0].get("type")
                       == "LOGICAL_COLUMN"]
    assert not column_searches
