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
# A row of the per-Model cohort listing (`/callosum/v1/metadata/detail/{guid}`,
# fetchcohortcolumnsonly). Membership is `cohortConfig`, never the header type (BL-325).
_COHORT_ROW = {"header": {"id": "cc-1", "name": "Region Set", "type": "COHORT_ATTRIBUTE"},
               "cohortConfig": {"name": "Region Set"}}


def _client(cohort_rows, fail_discovery=False):
    """Mock source client. `client.get` serves the session read-back and the per-Model
    cohort listing; `fail_discovery` makes the listing exit as the client does after
    its own retries."""
    def post(path, json=None, **kw):
        if "metadata/search" in path:
            meta = (json or {}).get("metadata", [{}])[0]
            if meta.get("name_pattern"):
                return MagicMock(json=lambda: [_MODEL_ROW])
        return MagicMock(json=lambda: [])

    def get(path, params=None, **kw):
        if "/callosum/v1/metadata/detail/" in path:
            if fail_discovery:
                raise SystemExit(1)
            rows = list(cohort_rows) if path.endswith("/g1") else []
            return MagicMock(json=lambda: rows)
        return MagicMock(json=lambda: {"current_org": {"id": 1}})

    client = MagicMock()
    client.post.side_effect = post
    client.get.side_effect = get
    return client


def _detail_gets(client):
    return [c for c in client.get.call_args_list
            if "/callosum/v1/metadata/detail/" in c.args[0]]


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
    assert not _detail_gets(client)


# ---------------------------------------------------------------------------
# BL-325 -- the gate uses shared Set discovery
# ---------------------------------------------------------------------------

def test_column_dependents_queries_logical_column():
    """BL-325 (3): Set dependents need type LOGICAL_COLUMN; the default returns none."""
    from ts_cli.migrate.discover import column_dependents
    seen = {}
    c = MagicMock()
    c.post.side_effect = lambda path, json=None, **kw: (seen.update(json), MagicMock(json=lambda: []))[1]
    column_dependents(c, "s1")
    assert seen["metadata"][0]["type"] == "LOGICAL_COLUMN"


def _apply(tmp_path):
    _write_single_model_mapping(tmp_path)
    return runner.invoke(app, ["migrate", "apply", "-d", str(tmp_path),
                               "--source-profile", "src",
                               "--target-profile", "tgt", "--dry-run"])


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_a_blank_type_set_still_blocks_apply(mock_cls, _rp, tmp_path):
    """BL-325 (1): 2 of 3 live Sets had a blank header type."""
    mock_cls.return_value = _client([dict(_COHORT_ROW, header=dict(_COHORT_ROW["header"], type=""))])
    result = _apply(tmp_path)
    assert result.exit_code == 1 and "SET_BLOCKER" in result.stderr


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_apply_refuses_when_discovery_for_the_mapped_model_fails(mock_cls, _rp, tmp_path):
    """A failed cohort listing must make the gate stricter, never looser: a Model whose
    Sets could not be listed is treated as blocked, not as clean."""
    client = _client([], fail_discovery=True)
    mock_cls.return_value = client
    result = _apply(tmp_path)
    assert _detail_gets(client)
    assert result.exit_code == 1 and "SET_BLOCKER" in result.stderr


_LONG_GUID = "00000000-0000-0000-0000-0000000000g1"


def _scan(client):
    with patch("ts_cli.commands.share._client_for_org", return_value=client):
        return runner.invoke(app, ["migrate", "scan-sets", "--model", _LONG_GUID,
                                   "--source-profile", "src"])


def _scan_client(cohort_rows, fail_discovery=False, dependents=()):
    client = _client(cohort_rows, fail_discovery)
    base_get = client.get.side_effect

    def get(path, params=None, **kw):
        if path.endswith("/" + _LONG_GUID):
            path = path[: -len(_LONG_GUID)] + "g1"
        return base_get(path, params=params, **kw)

    def post(path, json=None, **kw):
        if "metadata/search" in path:
            meta = (json or {}).get("metadata", [{}])[0]
            if meta.get("type") == "LOGICAL_COLUMN":
                return MagicMock(json=lambda: [{"dependent_objects": {
                    "dependents": {meta.get("identifier", ""): {"QUESTION_ANSWER_BOOK": list(dependents)}}}}])
        return MagicMock(json=lambda: [])

    client.get.side_effect = get
    client.post.side_effect = post
    return client


def test_scan_sets_blocks_a_blank_type_set_and_queries_its_dependents_as_logical_column():
    client = _scan_client([dict(_COHORT_ROW, header=dict(_COHORT_ROW["header"], type=""))])
    result = _scan(client)
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["models_blocked"] == 1
    assert report["blocked"][0]["cohort_columns"] == [{"name": "Region Set", "guid": "cc-1"}]
    dep_calls = [c.kwargs["json"]["metadata"][0] for c in client.post.call_args_list
                 if "metadata/search" in c.args[0]]
    assert dep_calls and all(m["type"] == "LOGICAL_COLUMN" and m["identifier"] == "cc-1"
                             for m in dep_calls)


def test_scan_sets_reports_a_failed_discovery_as_blocked_without_a_blank_dependents_lookup():
    """Amendment 2: the `(discovery incomplete)` sentinel has guid "" -- it must still
    block the Model, and must never be passed to `column_dependents`."""
    client = _scan_client([], fail_discovery=True)
    with patch("ts_cli.migrate.discover.column_dependents") as deps:
        result = _scan(client)
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["models_blocked"] == 1
    assert report["blocked"][0]["cohort_columns"] == [
        {"name": "(discovery incomplete)", "guid": ""}]
    assert not deps.call_args_list


def test_scan_sets_leaves_a_clean_model_unblocked():
    result = _scan(_scan_client([]))
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["summary"]["models_blocked"] == 0


# ---------------------------------------------------------------------------
# BL-325 review fix -- discovery notes reach the operator
# ---------------------------------------------------------------------------

def test_scan_sets_surfaces_a_failed_listing_in_stderr_and_the_report():
    result = _scan(_scan_client([], fail_discovery=True))
    assert result.exit_code == 0, result.stderr
    assert "discovery_failed" in result.stderr and "cohort listing failed" in result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["models_incomplete"] == 1
    assert [n["kind"] for n in report["discovery_notes"]] == ["discovery_failed"]
    # Additive: blocked[] still carries the Model.
    assert report["summary"]["models_blocked"] == 1


def test_scan_sets_clean_run_has_no_incomplete_models():
    report = json.loads(_scan(_scan_client([])).stdout)
    assert report["summary"]["models_incomplete"] == 0
    assert report["discovery_notes"] == []


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_apply_says_a_refusal_is_due_to_failed_discovery(mock_cls, _rp, tmp_path):
    mock_cls.return_value = _client([], fail_discovery=True)
    result = _apply(tmp_path)
    assert result.exit_code == 1 and "SET_BLOCKER" in result.stderr
    assert "discovery_failed" in result.stderr
    assert "Set discovery FAILED" in result.stderr


@patch("ts_cli.commands.migrate.resolve_profile", side_effect=lambda p: p or "def")
@patch("ts_cli.commands.migrate.ThoughtSpotClient")
def test_apply_with_a_confirmed_set_has_no_failed_discovery_line(mock_cls, _rp, tmp_path):
    mock_cls.return_value = _client([_COHORT_ROW])
    result = _apply(tmp_path)
    assert result.exit_code == 1 and "SET_BLOCKER" in result.stderr
    assert "Set discovery FAILED" not in result.stderr
