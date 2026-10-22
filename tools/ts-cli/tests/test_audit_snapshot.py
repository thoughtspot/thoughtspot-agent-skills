"""Snapshot capture and replay for `ts audit run` (audit rule catalog).

A snapshot freezes the data an audit reads — the AuditContext — so two
engines can later be run over identical input. These tests pin the format
contract and prove a replay produces the same findings as the live run that
captured it.
"""
import datetime
import json
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from ts_cli.audit.context import AuditContext, build_context, make_context
from ts_cli.audit.snapshot import SnapshotError, read_snapshot, write_snapshot

runner = CliRunner()
ALL = ["A", "D", "H", "P", "S"]


def _full_context():
    return make_context(
        models=[{"guid": "m1", "model": {"name": "Sales", "model_tables": [
            {"name": "ORDERS", "fqn": "t1"}], "columns": [{"name": "Amount"}]}}],
        tables={"t1": {"guid": "t1", "table": {"name": "ORDERS", "columns": [
            {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}}]}}},
        dependents={"m1": [{"source_guid": "m1", "guid": "a1", "type": "ANSWER"}]},
        metadata=[{"metadata_id": "m1", "metadata_header": {"name": "Sales"}}],
        ai_instructions={"m1": {"nl_instructions_info": [
            {"instructions": ["Use net revenue"], "scope": "GLOBAL"}]}},
        answers=[{"guid": "a1", "answer": {"name": "Revenue by month"}}],
        model_guids=["m1"],
        warnings=["Set discovery partial for Sales: timeout"],
        assessment="spotter",
    )


# ── format contract ─────────────────────────────────────────────────────────

def test_snapshot_round_trip(tmp_path):
    ctx = _full_context()
    write_snapshot(ctx, tmp_path / "snap", ["A", "H"])
    got, angles = read_snapshot(tmp_path / "snap")
    assert isinstance(got, AuditContext)
    assert got == ctx
    assert angles == ["A", "H"]
    manifest = json.loads((tmp_path / "snap" / "manifest.json").read_text())
    assert manifest["format"] == 1
    assert manifest["angles"] == ["A", "H"]
    assert {"ts_cli_version", "created", "files"} <= set(manifest)
    for name in manifest["files"]:
        assert (tmp_path / "snap" / name).is_file()


def test_snapshot_round_trips_yaml_dates(tmp_path):
    """yaml.safe_load turns an unquoted 2024-01-31 into a date; JSON has no date."""
    ctx = make_context(models=[yaml.safe_load(
        "guid: m1\nmodel:\n  name: X\n  default: 2024-01-31\n  at: 2024-01-31 10:00:00\n")],
        model_guids=["m1"])
    assert isinstance(ctx.models[0]["model"]["default"], datetime.date)
    write_snapshot(ctx, tmp_path / "snap", ALL)
    got, _ = read_snapshot(tmp_path / "snap")
    assert got == ctx


def test_snapshot_preserves_mapping_order(tmp_path):
    """Checks iterate ctx dicts in insertion order (H5 walks ``dependents``), so
    finding order is part of what a replay must reproduce. Sorting keys on write
    reordered 45 of 5,091 H5 findings on a real 351-Model capture while ``==``
    — which ignores dict order — still called the round trip exact."""
    import audit_rule_fixtures as fx
    from audit_run_rule import run_rule
    ctx = fx.h5_sets_in_capture_order()   # three orphan Sets, in a non-sorted order
    write_snapshot(ctx, tmp_path / "snap", ALL)
    got, _ = read_snapshot(tmp_path / "snap")
    assert list(got.dependents) == ["m1", "s-z", "s-a", "s-m"]
    assert list(got.tables) == ["zz", "aa"] and list(got.tables["aa"]) == ["b", "a"]
    assert [f.object_guid for f in run_rule(got, "H5")] == [f.object_guid for f in run_rule(ctx, "H5")]


def test_snapshot_refuses_data_it_cannot_reproduce(tmp_path):
    """Non-string dict keys would come back as strings — refuse, never corrupt."""
    ctx = make_context(models=[{"guid": "m1", "model": {1: "a", 2: "b"}}])
    with pytest.raises(SnapshotError, match="models"):
        write_snapshot(ctx, tmp_path / "snap", ALL)


def test_snapshot_in_rejects_incompatible_or_partial(tmp_path):
    snap = tmp_path / "snap"
    with pytest.raises(SnapshotError, match="manifest.json"):
        read_snapshot(snap)

    write_snapshot(_full_context(), snap, ALL)
    manifest_path = snap / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    manifest_path.write_text(json.dumps(dict(manifest, format=2)))
    with pytest.raises(SnapshotError) as exc:
        read_snapshot(snap)
    assert "2" in str(exc.value) and "1" in str(exc.value)

    manifest_path.write_text(json.dumps(manifest))
    (snap / "answers.json").unlink()
    with pytest.raises(SnapshotError, match="answers.json"):
        read_snapshot(snap)


def test_snapshot_in_rejects_a_manifest_missing_a_context_field(tmp_path):
    snap = tmp_path / "snap"
    write_snapshot(_full_context(), snap, ALL)
    manifest = json.loads((snap / "manifest.json").read_text())
    manifest["files"] = [f for f in manifest["files"] if f != "tables.json"]
    (snap / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(SnapshotError, match="tables"):
        read_snapshot(snap)


# ── replay equals live ──────────────────────────────────────────────────────

def _resp(body):
    r = MagicMock()
    r.ok, r.status_code = True, 200
    r.json.return_value = body
    return r


def _fake_client():
    """One Model on one Table, no descriptions or synonyms: several checks fire."""
    model = {"guid": "m1", "model": {
        "name": "Sales",
        "model_tables": [{"name": "ORDERS", "fqn": "t1"}],
        "columns": [
            {"name": "Amount", "column_id": "ORDERS::AMOUNT",
             "properties": {"column_type": "MEASURE"}},
            {"name": "Region", "column_id": "ORDERS::REGION",
             "properties": {"column_type": "ATTRIBUTE"}},
        ],
    }}
    table = {"guid": "t1", "table": {"name": "ORDERS", "db": "D", "schema": "S",
                                     "db_table": "ORDERS", "columns": [
        {"name": "AMOUNT", "db_column_properties": {"data_type": "DOUBLE"}},
        {"name": "REGION", "db_column_properties": {"data_type": "VARCHAR"}}]}}
    edocs = [{"edoc": yaml.safe_dump(model)}, {"edoc": yaml.safe_dump(table)}]

    def post(url, json=None, **_kw):
        if url.endswith("/metadata/tml/export"):
            return _resp(edocs)
        if url.endswith("/ai/instructions/get"):
            return _resp({"nl_instructions_info": []})
        return _resp([])

    client = MagicMock()
    client.post.side_effect = post
    client.base_url = "https://example.thoughtspot.cloud"
    client._profile_name = "example"
    return client


_NO_SETS = {"sets": {}, "incomplete": [], "notes": []}


@patch("ts_cli.audit.context.discover_sets", return_value=_NO_SETS)
def test_run_audit_from_snapshot_matches_live(_disc, tmp_path):
    from ts_cli.audit import data_needs, run_audit
    live = run_audit(_fake_client(), ["m1"])
    assert live["findings"], "fixture must produce findings or the comparison is vacuous"

    write_snapshot(build_context(_fake_client(), ["m1"], data_needs(ALL)), tmp_path / "snap", ALL)
    ctx, angles = read_snapshot(tmp_path / "snap")
    replay = run_audit(None, ["ignored"], angles, ctx=ctx)

    assert replay["findings"] == live["findings"]
    assert replay["summary"] == live["summary"]


def test_run_audit_with_ctx_does_not_fetch_and_applies_assessment():
    from ts_cli.audit import run_audit
    client = MagicMock()
    ctx = make_context(model_guids=["m1"])
    run_audit(client, ["m1"], ["A"], "spotter", ctx=ctx)
    client.post.assert_not_called()
    assert ctx.assessment == "spotter"


# ── CLI ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def no_profiles(tmp_path, monkeypatch):
    import ts_cli.client as client_mod
    import ts_cli.commands.audit as audit_cmd
    monkeypatch.setattr(client_mod, "PROFILES_PATH", tmp_path / "absent.json")
    monkeypatch.delenv("TS_PROFILE", raising=False)

    def _boom(*_a, **_kw):
        raise AssertionError("a client was constructed for a snapshot replay")
    monkeypatch.setattr(audit_cmd, "ThoughtSpotClient", _boom)


def _app():
    from ts_cli.cli import app
    return app


def test_cli_snapshot_in_needs_no_profile(tmp_path, no_profiles):
    snap = tmp_path / "snap"
    write_snapshot(_full_context(), snap, ALL)
    out = tmp_path / "out.json"
    result = runner.invoke(_app(), ["audit", "run", "--snapshot-in", str(snap), "-o", str(out)])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert {"findings", "summary", "corpus"} <= set(data)
    assert data["corpus"]["angles_run"] == ALL


def test_cli_snapshot_in_defaults_to_captured_angles(tmp_path, no_profiles):
    snap = tmp_path / "snap"
    write_snapshot(_full_context(), snap, ["D", "P"])
    out = tmp_path / "out.json"
    result = runner.invoke(_app(), ["audit", "run", "--snapshot-in", str(snap), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text())["corpus"]["angles_run"] == ["D", "P"]


def test_cli_snapshot_in_rejects_an_angle_it_did_not_capture(tmp_path, no_profiles):
    snap = tmp_path / "snap"
    write_snapshot(_full_context(), snap, ["D", "P"])
    result = runner.invoke(_app(), ["audit", "run", "--snapshot-in", str(snap),
                                    "--angles", "D,H"])
    assert result.exit_code != 0
    assert "H" in result.output and "not captured" in result.output


def test_cli_snapshot_in_and_out_are_mutually_exclusive(tmp_path, no_profiles):
    result = runner.invoke(_app(), ["audit", "run", "--snapshot-in", str(tmp_path / "a"),
                                    "--snapshot-out", str(tmp_path / "b")])
    assert result.exit_code != 0
    assert "--snapshot-in" in result.output and "--snapshot-out" in result.output


def test_cli_models_required_without_snapshot_in(tmp_path, no_profiles):
    result = runner.invoke(_app(), ["audit", "run"])
    assert result.exit_code != 0
    assert "--models" in result.output


def test_cli_reports_a_bad_snapshot(tmp_path, no_profiles):
    result = runner.invoke(_app(), ["audit", "run", "--snapshot-in", str(tmp_path / "nope")])
    assert result.exit_code != 0
    assert "manifest.json" in result.output


@patch("ts_cli.audit.context.discover_sets", return_value=_NO_SETS)
def test_cli_snapshot_out_writes_then_audits(_disc, tmp_path, monkeypatch):
    import ts_cli.commands.audit as audit_cmd
    monkeypatch.setattr(audit_cmd, "resolve_profile", lambda p: "example")
    monkeypatch.setattr(audit_cmd, "ThoughtSpotClient", lambda _p: _fake_client())
    snap, live_out = tmp_path / "snap", tmp_path / "live.json"
    result = runner.invoke(_app(), ["audit", "run", "-m", "m1", "--angles", "A,D",
                                    "--snapshot-out", str(snap), "-o", str(live_out)])
    assert result.exit_code == 0, result.output
    ctx, angles = read_snapshot(snap)
    assert angles == ["A", "D"] and ctx.model_guids == ["m1"]

    monkeypatch.setattr(audit_cmd, "ThoughtSpotClient", None)
    replay_out = tmp_path / "replay.json"
    result = runner.invoke(_app(), ["audit", "run", "--snapshot-in", str(snap),
                                    "-o", str(replay_out)])
    assert result.exit_code == 0, result.output
    live, replay = json.loads(live_out.read_text()), json.loads(replay_out.read_text())
    assert live["findings"] and replay["findings"] == live["findings"]


# ── the captured assessment survives replay ─────────────────────────────────

def test_run_audit_with_ctx_keeps_its_assessment_when_none_is_given():
    from ts_cli.audit import run_audit
    ctx = make_context(model_guids=["m1"], assessment="spotter")
    result = run_audit(None, ["m1"], ["A"], ctx=ctx)
    assert ctx.assessment == "spotter"
    assert result["corpus"]["assessment"] == "Spotter-ready"


@patch("ts_cli.audit.context.discover_sets", return_value=_NO_SETS)
def test_cli_replay_keeps_the_captured_assessment(_disc, tmp_path, monkeypatch):
    """A spotter capture replayed with default flags must not fall back to general:
    the bar decides rule ids, severities and thresholds."""
    import ts_cli.commands.audit as audit_cmd
    monkeypatch.setattr(audit_cmd, "resolve_profile", lambda p: "example")
    monkeypatch.setattr(audit_cmd, "ThoughtSpotClient", lambda _p: _fake_client())
    snap, live_out = tmp_path / "snap", tmp_path / "live.json"
    result = runner.invoke(_app(), ["audit", "run", "-m", "m1", "--assessment", "spotter",
                                    "--snapshot-out", str(snap), "-o", str(live_out)])
    assert result.exit_code == 0, result.output
    assert read_snapshot(snap)[0].assessment == "spotter"

    monkeypatch.setattr(audit_cmd, "ThoughtSpotClient", None)
    replay_out, general_out = tmp_path / "replay.json", tmp_path / "general.json"
    result = runner.invoke(_app(), ["audit", "run", "--snapshot-in", str(snap),
                                    "-o", str(replay_out)])
    assert result.exit_code == 0, result.output
    live, replay = json.loads(live_out.read_text()), json.loads(replay_out.read_text())
    assert replay["findings"] == live["findings"]
    assert replay["corpus"]["assessment"] == live["corpus"]["assessment"] == "Spotter-ready"

    # An explicit flag still overrides the captured bar, and says so.
    result = runner.invoke(_app(), ["audit", "run", "--snapshot-in", str(snap),
                                    "--assessment", "general", "-o", str(general_out)])
    assert result.exit_code == 0, result.output
    assert "overrides" in result.output and "spotter" in result.output
    general = json.loads(general_out.read_text())
    assert general["corpus"]["assessment"] == "General"
    assert general["findings"] != live["findings"], "fixture must be bar-sensitive"


# ── where a snapshot may be written ─────────────────────────────────────────
# A snapshot is real exported TML under generic file names: never inside a git work
# tree (the repo is public), never over a directory that is not an earlier snapshot.

@pytest.mark.parametrize("git_entry", ["dir", "file"])  # a checkout, or a linked worktree
def test_snapshot_refuses_a_directory_inside_a_git_work_tree(tmp_path, git_entry):
    repo = tmp_path / "repo"
    repo.mkdir()
    if git_entry == "dir":
        (repo / ".git").mkdir()
    else:
        (repo / ".git").write_text("gitdir: /elsewhere\n")
    with pytest.raises(SnapshotError, match="inside the git work tree"):
        write_snapshot(_full_context(), repo / "snaps" / "new", ALL)
    assert not (repo / "snaps").exists()


def test_snapshot_refuses_a_non_empty_directory_that_is_not_a_snapshot(tmp_path):
    target = tmp_path / "work"
    target.mkdir()
    (target / "models.json").write_text("my own file")
    with pytest.raises(SnapshotError, match="not empty and holds no snapshot"):
        write_snapshot(_full_context(), target, ALL)
    assert (target / "models.json").read_text() == "my own file"


def test_snapshot_refuses_a_file_path(tmp_path):
    target = tmp_path / "a-file"
    target.write_text("x")
    with pytest.raises(SnapshotError, match="not a directory"):
        write_snapshot(_full_context(), target, ALL)


def test_snapshot_overwrites_an_earlier_snapshot_and_fills_an_empty_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    write_snapshot(_full_context(), empty, ALL)          # empty: allowed
    write_snapshot(_full_context(), empty, ["A"])        # an earlier snapshot: allowed
    assert read_snapshot(empty)[1] == ["A"]


def test_cli_snapshot_out_refuses_before_fetching(tmp_path, monkeypatch):
    """The refusal comes before the fetch (13 minutes on a large estate), not after."""
    import ts_cli.commands.audit as audit_cmd
    calls = []
    monkeypatch.setattr(audit_cmd, "resolve_profile", lambda p: "example")
    monkeypatch.setattr(audit_cmd, "ThoughtSpotClient", lambda _p: calls.append("client") or MagicMock())
    monkeypatch.setattr("ts_cli.audit.context.build_context",
                        lambda *a, **k: calls.append("fetch"))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    result = runner.invoke(_app(), ["audit", "run", "-m", "m1", "--snapshot-out",
                                    str(repo / "snap"), "-o", str(tmp_path / "out.json")])
    assert result.exit_code != 0
    assert "Cannot write snapshot" in result.output and "git work tree" in result.output
    assert "fetch" not in calls and not (repo / "snap").exists()
