"""Unit tests for the `ts dependency` command I/O shell (mutate/backup/rollback,
BL-083 PR1). `mutate` needs no network; `backup`/`rollback` mock `ThoughtSpotClient`
per the pattern in test_tml_commands.py — no live connection required.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ts_cli.cli import app

try:
    runner = CliRunner(mix_stderr=False)
except TypeError:
    runner = CliRunner()


def _all_output(result):
    try:
        return (result.stdout or "") + (result.stderr or "")
    except ValueError:
        return result.output or ""


# ---------------------------------------------------------------------------
# ts dependency mutate
# ---------------------------------------------------------------------------

class TestMutateCommand:
    def test_remove_via_stdin(self):
        doc = {"answer": {"answer_columns": [{"name": "Revenue"}], "search_query": "[Revenue]"}}
        result = runner.invoke(
            app,
            ["dependency", "mutate", "--operation", "remove", "--remove-columns", "Revenue"],
            input=json.dumps(doc),
        )
        assert result.exit_code == 0, _all_output(result)
        mutated = json.loads(result.stdout)
        assert mutated["answer"]["answer_columns"] == []

    def test_remove_via_file(self, tmp_path):
        doc = {"model": {"columns": [{"name": "Revenue"}]}}
        p = tmp_path / "model.json"
        p.write_text(json.dumps(doc))
        result = runner.invoke(
            app,
            ["dependency", "mutate", "--operation", "remove", "--remove-columns", "Revenue",
             "--file", str(p)],
        )
        assert result.exit_code == 0, _all_output(result)
        mutated = json.loads(result.stdout)
        assert mutated["model"]["columns"] == []

    def test_unwraps_tml_export_parse_item_shape(self):
        item = {
            "type": "answer",
            "guid": "abc-123",
            "tml": {"answer": {"answer_columns": [{"name": "Revenue"}]}},
            "info": {"name": "x"},
        }
        result = runner.invoke(
            app,
            ["dependency", "mutate", "--operation", "remove", "--remove-columns", "Revenue"],
            input=json.dumps(item),
        )
        assert result.exit_code == 0, _all_output(result)
        mutated = json.loads(result.stdout)
        assert "answer" in mutated
        assert mutated["answer"]["answer_columns"] == []

    def test_repoint(self):
        doc = {"answer": {"tables": [{"fqn": "src-guid", "name": "Old"}]}}
        result = runner.invoke(
            app,
            ["dependency", "mutate", "--operation", "repoint",
             "--source-guid", "src-guid", "--target-guid", "tgt-guid",
             "--target-name", "New Model"],
            input=json.dumps(doc),
        )
        assert result.exit_code == 0, _all_output(result)
        mutated = json.loads(result.stdout)
        assert mutated["answer"]["tables"][0]["fqn"] == "tgt-guid"

    def test_repoint_requires_target_guid_and_name(self):
        doc = {"answer": {"tables": []}}
        result = runner.invoke(
            app, ["dependency", "mutate", "--operation", "repoint"], input=json.dumps(doc),
        )
        assert result.exit_code != 0

    def test_remove_requires_remove_columns(self):
        doc = {"answer": {"answer_columns": []}}
        result = runner.invoke(
            app, ["dependency", "mutate", "--operation", "remove"], input=json.dumps(doc),
        )
        assert result.exit_code != 0

    def test_invalid_operation_rejected(self):
        result = runner.invoke(
            app, ["dependency", "mutate", "--operation", "rename"], input="{}",
        )
        assert result.exit_code != 0

    def test_viz_decision_parsing(self):
        doc = {
            "liveboard": {
                "visualizations": [
                    {"id": "v1", "answer": {"tables": [{"fqn": "src-guid"}], "answer_columns": []}},
                ],
            }
        }
        result = runner.invoke(
            app,
            ["dependency", "mutate", "--operation", "remove", "--remove-columns", "Revenue",
             "--source-guid", "src-guid", "--viz-decision", "v1=remove"],
            input=json.dumps(doc),
        )
        assert result.exit_code == 0, _all_output(result)
        mutated = json.loads(result.stdout)
        assert mutated["liveboard"]["visualizations"] == []

    def test_invalid_viz_decision_value_rejected(self):
        doc = {"liveboard": {"visualizations": []}}
        result = runner.invoke(
            app,
            ["dependency", "mutate", "--operation", "remove", "--remove-columns", "Revenue",
             "--viz-decision", "v1=bogus"],
            input=json.dumps(doc),
        )
        assert result.exit_code != 0

    def test_invalid_json_input_rejected(self):
        result = runner.invoke(
            app, ["dependency", "mutate", "--operation", "remove", "--remove-columns", "X"],
            input="not json",
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# ts dependency backup
# ---------------------------------------------------------------------------

def _fake_export_response(guid: str, tml_type: str, name: str):
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = [
        {"edoc": f"guid: {guid}\n{tml_type}:\n  name: {name}\n", "info": {"name": name}}
    ]
    return resp


class TestBackupCommand:
    def test_backs_up_source_and_fix(self, tmp_path):
        plan = {
            "operation": "REMOVE",
            "source": {"guid": "src-1", "type": "MODEL", "name": "Orders Model"},
            "fix": [{"guid": "dep-1", "type": "ANSWER", "name": "Revenue Answer"}],
            "out_dir": str(tmp_path),
        }
        mock_client = MagicMock()
        mock_client.base_url = "https://example.thoughtspot.cloud"

        def fake_post(path, json=None, **kwargs):
            guid = json["metadata"][0]["identifier"]
            tmap = {"src-1": "model", "dep-1": "answer"}
            return _fake_export_response(guid, tmap[guid], f"Test_{guid}")

        mock_client.post.side_effect = fake_post

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            result = runner.invoke(app, ["dependency", "backup", "--profile", "test"],
                                   input=json.dumps(plan))

        assert result.exit_code == 0, _all_output(result)
        manifest = json.loads(result.stdout)
        assert manifest["fix_count"] == 1
        assert manifest["delete_count"] == 0
        assert len(manifest["objects"]) == 2
        backup_dir = os.path.dirname(manifest["objects"][0]["backup_file"])
        assert os.path.isfile(os.path.join(backup_dir, "manifest.json"))

    def test_aborts_and_writes_nothing_on_export_failure(self, tmp_path):
        plan = {
            "operation": "REMOVE",
            "source": {"guid": "src-1", "type": "MODEL", "name": "Orders Model"},
            "fix": [{"guid": "dep-1", "type": "ANSWER", "name": "Revenue Answer"}],
            "out_dir": str(tmp_path),
        }
        mock_client = MagicMock()
        mock_client.base_url = "https://example.thoughtspot.cloud"

        def fake_post(path, json=None, **kwargs):
            guid = json["metadata"][0]["identifier"]
            if guid == "dep-1":
                resp = MagicMock()
                resp.ok = False
                resp.status_code = 403
                resp.text = "forbidden"
                return resp
            return _fake_export_response(guid, "model", "Test_src-1")

        mock_client.post.side_effect = fake_post

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            result = runner.invoke(app, ["dependency", "backup", "--profile", "test"],
                                   input=json.dumps(plan))

        assert result.exit_code != 0
        # Nothing written — no backup directory created under out_dir.
        assert os.listdir(tmp_path) == []

    def test_requires_source_guid(self):
        plan = {"operation": "REMOVE", "source": {"type": "MODEL", "name": "x"}}
        result = runner.invoke(app, ["dependency", "backup"], input=json.dumps(plan))
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# ts dependency rollback
# ---------------------------------------------------------------------------

class TestRollbackCommand:
    def _make_backup(self, tmp_path):
        plan = {
            "operation": "REMOVE",
            "source": {"guid": "src-1", "type": "MODEL", "name": "Orders Model"},
            "fix": [{"guid": "dep-1", "type": "ANSWER", "name": "Revenue Answer"}],
            "delete": [{"guid": "del-1", "type": "LIVEBOARD", "name": "Old LB"}],
            "out_dir": str(tmp_path),
        }
        mock_client = MagicMock()
        mock_client.base_url = "https://example.thoughtspot.cloud"

        def fake_post(path, json=None, **kwargs):
            guid = json["metadata"][0]["identifier"]
            tmap = {"src-1": "model", "dep-1": "answer", "del-1": "liveboard"}
            return _fake_export_response(guid, tmap[guid], f"Test_{guid}")

        mock_client.post.side_effect = fake_post

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            result = runner.invoke(app, ["dependency", "backup", "--profile", "test"],
                                   input=json.dumps(plan))
        assert result.exit_code == 0, _all_output(result)
        manifest = json.loads(result.stdout)
        return os.path.dirname(manifest["objects"][0]["backup_file"])

    def _fake_import_client(self, new_guid="new-guid-123"):
        mock_client = MagicMock()

        def fake_post(path, json=None, **kwargs):
            resp = MagicMock()
            resp.ok = True
            resp.json.return_value = [{
                "response": {
                    "status": {"status_code": "OK"},
                    "object": [{"header": {"id_guid": new_guid}}],
                }
            }]
            return resp

        mock_client.post.side_effect = fake_post
        return mock_client

    def test_rolls_back_all_objects(self, tmp_path):
        backup_dir = self._make_backup(tmp_path)
        mock_client = self._fake_import_client()

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            result = runner.invoke(
                app, ["dependency", "rollback", "--backup-dir", backup_dir, "--profile", "test"],
            )

        assert result.exit_code == 0, _all_output(result)
        results = json.loads(result.stdout)
        assert len(results["succeeded"]) == 3
        assert results["failed"] == []
        assert results["new_guids"]["del-1"] == "new-guid-123"

    def test_rollback_picks_up_flat_shape_guid(self, tmp_path):
        # BL-099 #1 — ThoughtSpot Cloud also returns a FLAT response shape
        # (response.header.id_guid, no `object` list). Rollback must still
        # recover the new GUID for a DELETE-intent restore.
        backup_dir = self._make_backup(tmp_path)
        mock_client = MagicMock()

        def fake_post(path, json=None, **kwargs):
            resp = MagicMock()
            resp.ok = True
            resp.json.return_value = [{
                "response": {
                    "status": {"status_code": "OK"},
                    "header": {"id_guid": "new-guid"},
                }
            }]
            return resp

        mock_client.post.side_effect = fake_post

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            result = runner.invoke(
                app, ["dependency", "rollback", "--backup-dir", backup_dir, "--profile", "test"],
            )

        assert result.exit_code == 0, _all_output(result)
        results = json.loads(result.stdout)
        assert results["new_guids"]["del-1"] == "new-guid"

    def test_deleted_entry_serializes_without_duplicate_guid(self, tmp_path):
        # Regression test for the duplicate-`guid:` bug found during extraction
        # (see _dump_tml_yaml docstring): an Answer-type restore, in particular,
        # previously produced two `guid:` keys because yaml.dump sorts "answer"
        # before "guid" alphabetically.
        backup_dir = self._make_backup(tmp_path)
        mock_client = self._fake_import_client()

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            runner.invoke(
                app, ["dependency", "rollback", "--backup-dir", backup_dir, "--profile", "test"],
            )

        for call in mock_client.post.call_args_list:
            tml_yaml = call.kwargs["json"]["metadata_tmls"][0]
            assert tml_yaml.count("guid:") <= 1, f"duplicate guid: line in {tml_yaml!r}"

    def test_only_deletes_filter(self, tmp_path):
        backup_dir = self._make_backup(tmp_path)
        mock_client = self._fake_import_client()

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            result = runner.invoke(
                app, ["dependency", "rollback", "--backup-dir", backup_dir,
                      "--profile", "test", "--only", "deletes"],
            )

        results = json.loads(result.stdout)
        assert len(results["succeeded"]) == 1
        assert results["succeeded"][0]["guid"] == "del-1"

    def test_guid_filter(self, tmp_path):
        backup_dir = self._make_backup(tmp_path)
        mock_client = self._fake_import_client()

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            result = runner.invoke(
                app, ["dependency", "rollback", "--backup-dir", backup_dir,
                      "--profile", "test", "--guid", "dep-1"],
            )

        results = json.loads(result.stdout)
        assert len(results["succeeded"]) == 1
        assert results["succeeded"][0]["guid"] == "dep-1"

    def test_missing_manifest_exits_nonzero(self, tmp_path):
        result = runner.invoke(
            app, ["dependency", "rollback", "--backup-dir", str(tmp_path), "--profile", "test"],
        )
        assert result.exit_code != 0

    def test_invalid_only_value_rejected(self, tmp_path):
        result = runner.invoke(
            app, ["dependency", "rollback", "--backup-dir", str(tmp_path),
                  "--profile", "test", "--only", "bogus"],
        )
        assert result.exit_code != 0

    def test_import_failure_recorded_as_failed(self, tmp_path):
        backup_dir = self._make_backup(tmp_path)
        mock_client = MagicMock()

        def fake_post(path, json=None, **kwargs):
            resp = MagicMock()
            resp.ok = False
            resp.json.return_value = [{
                "response": {"status": {"status_code": "ERROR", "error_message": "boom"}}
            }]
            return resp

        mock_client.post.side_effect = fake_post

        with patch("ts_cli.commands.dependency.ThoughtSpotClient", return_value=mock_client), \
             patch("ts_cli.commands.dependency.resolve_profile", return_value="test"):
            result = runner.invoke(
                app, ["dependency", "rollback", "--backup-dir", backup_dir, "--profile", "test"],
            )

        assert result.exit_code == 0  # command completes; failures are reported in the JSON
        results = json.loads(result.stdout)
        assert len(results["failed"]) == 3
        assert results["succeeded"] == []


# ---------------------------------------------------------------------------
# ts dependency apply-change (BL-083 PR2) — the destructive orchestrator.
#
# A configurable fake ThoughtSpotClient dispatches by endpoint so the full
# drift → delete → dependent-fix → source → set-delete loop is exercised without
# a live instance. Mutation correctness itself is covered by test_dependency_mutate
# / test_dependency_apply; these tests assert ORCHESTRATION: ordering, drift skips,
# the import/verify outcome matrix, and the set-delete consumer guard.
# ---------------------------------------------------------------------------

import yaml as _yaml


class _FakeResp:
    def __init__(self, *, ok=True, status_code=200, json_data=None, text=""):
        self.ok = ok
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def _export_resp(tml_body):
    return _FakeResp(json_data=[{"edoc": _yaml.safe_dump(tml_body),
                                 "info": {"id": "g", "type": "MODEL"}}])


def _search_resp(modified):
    return _FakeResp(json_data=[{"metadata_header": {"modified": modified}}])


class _FakeClient:
    """Dispatch by endpoint. `exports` maps guid -> a TML body dict, OR a list of
    bodies popped left-to-right (first for the mutate-fetch, next for the verify
    re-export). `modifieds` maps guid -> the `modified` int returned by search
    (drift check); a guid absent from `modifieds` is reported as 'not found'."""
    base_url = "https://x"

    def __init__(self, *, exports, modifieds, import_ok=True, import_err=None,
                 delete_ok=True):
        self.exports = exports
        self.modifieds = modifieds
        self.import_ok = import_ok
        self.import_err = import_err
        self.delete_ok = delete_ok
        self.calls = []

    def _pop_export(self, guid):
        body = self.exports[guid]
        if isinstance(body, list):
            return body.pop(0) if len(body) > 1 else body[0]
        return body

    def post(self, path, json=None, **kwargs):
        self.calls.append((path, json))
        if path.endswith("/metadata/search"):
            guid = json["metadata"][0]["identifier"]
            if guid not in self.modifieds:
                return _FakeResp(json_data=[])
            return _search_resp(self.modifieds[guid])
        if path.endswith("/metadata/tml/export"):
            guid = json["metadata"][0]["identifier"]
            return _export_resp(self._pop_export(guid))
        if path.endswith("/metadata/tml/import"):
            status = ({"status_code": "OK"} if self.import_ok
                      else {"status_code": "ERROR", "error_message": self.import_err or "boom"})
            return _FakeResp(json_data=[{"response": {"status": status, "object": []}}])
        if path.endswith("/metadata/delete"):
            return _FakeResp(ok=self.delete_ok, status_code=200 if self.delete_ok else 500,
                             text="delete error")
        return _FakeResp(json_data={})


def _run_apply(plan, client):
    with patch("ts_cli.commands.dependency_apply.ThoughtSpotClient", return_value=client), \
         patch("ts_cli.commands.dependency_apply.resolve_profile", return_value="test"):
        return runner.invoke(
            app, ["dependency", "apply-change", "--profile", "test"],
            input=json.dumps(plan),
        )


class TestApplyChangeCommand:
    def _remove_plan(self, **over):
        plan = {
            "operation": "REMOVE",
            "backup_dir": "/tmp/ts_dep_backup_x",
            "source": {"guid": "src", "type": "MODEL", "name": "Orders Model", "modified_at": 100},
            "columns_to_remove": ["Legacy"],
            "fix": [{"guid": "a1", "type": "ANSWER", "name": "Rev by Region", "modified_at": 200}],
            "delete": [{"guid": "d1", "type": "ANSWER", "name": "Old Answer", "modified_at": 300}],
            "sets": [],
        }
        plan.update(over)
        return plan

    def test_remove_happy_path_order_and_results(self):
        client = _FakeClient(
            exports={
                "src": {"model": {"columns": [{"name": "Keep"}]}},
                "a1": {"answer": {"answer_columns": [{"name": "Keep"}]}},
            },
            modifieds={"src": 100, "a1": 200, "d1": 300},
        )
        result = _run_apply(self._remove_plan(), client)
        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert [d["guid"] for d in out["deleted"]] == ["d1"]
        succeeded_guids = [r["guid"] for r in out["succeeded"]]
        assert "a1" in succeeded_guids and "src" in succeeded_guids
        assert out["failed"] == [] and out["skipped"] == []
        # Dependents fixed BEFORE the source (error 14544 ordering).
        import_calls = [c for c in client.calls if c[0].endswith("/metadata/tml/import")]
        assert "guid: a1" in import_calls[0][1]["metadata_tmls"][0]
        assert "guid: src" in import_calls[1][1]["metadata_tmls"][0]

    def test_source_drift_aborts_entire_run(self):
        client = _FakeClient(
            exports={"src": {"model": {"columns": []}}},
            modifieds={"src": 999},  # != snapshot 100 -> drift
        )
        result = _run_apply(self._remove_plan(), client)
        assert result.exit_code == 1, _all_output(result)
        out = json.loads(result.stdout)
        assert out["aborted"] is True
        # Nothing was deleted or imported.
        assert not any(c[0].endswith("/metadata/tml/import") for c in client.calls)
        assert not any(c[0].endswith("/metadata/delete") for c in client.calls)

    def test_dependent_drift_is_skipped_source_still_applied(self):
        client = _FakeClient(
            exports={
                "src": {"model": {"columns": [{"name": "Keep"}]}},
                "a1": {"answer": {"answer_columns": [{"name": "Keep"}]}},
            },
            modifieds={"src": 100, "a1": 201, "d1": 300},  # a1 drifted
        )
        result = _run_apply(self._remove_plan(), client)
        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert [s["guid"] for s in out["skipped"]] == ["a1"]
        assert "src" in [r["guid"] for r in out["succeeded"]]

    def test_error_but_verified_is_success_with_warning(self):
        client = _FakeClient(
            exports={
                "src": {"model": {"columns": [{"name": "Keep"}]}},
                "a1": {"answer": {"answer_columns": [{"name": "Keep"}]}},
            },
            modifieds={"src": 100, "a1": 200, "d1": 300},
            import_ok=False, import_err="Invalid YAML/JSON syntax in file",
        )
        result = _run_apply(self._remove_plan(), client)
        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        outcomes = {r["guid"]: r["outcome"] for r in out["succeeded"]}
        assert outcomes["a1"] == "SUCCESS_WITH_WARNING"
        assert outcomes["src"] == "SUCCESS_WITH_WARNING"
        assert out["failed"] == []

    def test_set_delete_skipped_when_consumer_fix_fails(self):
        # a1's export keeps "Legacy" on both fetch and verify -> FAIL_SILENT (import
        # ok, change not verified). The set consumed by a1 must then be skipped.
        client = _FakeClient(
            exports={
                "src": {"model": {"columns": [{"name": "Keep"}]}},
                "a1": {"answer": {"answer_columns": [{"name": "Legacy"}]}},
            },
            modifieds={"src": 100, "a1": 200},
        )
        plan = self._remove_plan(
            delete=[],
            sets=[{"guid": "set1", "name": "Region Cohort", "action": "DELETE_SAFE",
                   "in_use_by": ["a1"]}],
        )
        result = _run_apply(plan, client)
        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert "a1" in [r["guid"] for r in out["failed"]]
        skipped = [s for s in out["skipped"] if s["guid"] == "set1"]
        assert skipped and "consumer" in skipped[0]["reason"].lower()
        # The set was never actually deleted.
        assert not any(c[0].endswith("/metadata/delete")
                       and c[1]["metadata"][0]["identifier"] == "set1"
                       for c in client.calls)

    def test_set_deleted_when_all_consumer_fixes_succeed(self):
        client = _FakeClient(
            exports={
                "src": {"model": {"columns": [{"name": "Keep"}]}},
                "a1": {"answer": {"answer_columns": [{"name": "Keep"}]}},
            },
            modifieds={"src": 100, "a1": 200},
        )
        plan = self._remove_plan(
            delete=[],
            sets=[{"guid": "set1", "name": "Region Cohort", "action": "DELETE_SAFE",
                   "in_use_by": ["a1"]}],
        )
        result = _run_apply(plan, client)
        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert "set1" in [d["guid"] for d in out["deleted"]]

    def test_delete_verified_by_post_query_when_api_errors(self):
        # delete API returns non-ok, but a re-query shows the object is gone -> deleted.
        client = _FakeClient(
            exports={"src": {"model": {"columns": [{"name": "Keep"}]}}},
            modifieds={"src": 100, "d1": 300},  # d1 present for drift check...
            delete_ok=False,
        )
        # After the delete "fails", the post-query for d1 must show it gone. Simulate by
        # removing d1 from modifieds via a wrapper that drops it after the delete call.
        orig_post = client.post

        def post_dropping_d1(path, json=None, **kwargs):
            resp = orig_post(path, json=json, **kwargs)
            if path.endswith("/metadata/delete") and json["metadata"][0]["identifier"] == "d1":
                client.modifieds.pop("d1", None)
            return resp

        client.post = post_dropping_d1
        result = _run_apply(self._remove_plan(fix=[]), client)
        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert "d1" in [d["guid"] for d in out["deleted"]]

    def test_repoint_uses_obj_id_when_available(self):
        target_guid = "tgtguid1abcdef"
        target_obj_id = "New Orders-tgtguid1"  # derive_target_obj_id("New Orders", guid)
        client = _FakeClient(
            exports={
                # src exported 3x: obj_id probe, source mutate-fetch, source verify.
                # The verify body must show the repointed obj_id so source verifies.
                "src": [
                    {"model": {"model_tables": [{"name": "Orders", "obj_id": "Orders-srcobj"}]}},
                    {"model": {"model_tables": [{"name": "Orders", "obj_id": "Orders-srcobj"}]}},
                    {"model": {"model_tables": [{"name": "Orders", "obj_id": target_obj_id}]}},
                ],
                # a1 references the source via obj_id; verify re-export shows the target.
                "a1": [
                    {"answer": {"tables": [{"obj_id": "Orders-srcobj", "fqn": "src"}]}},
                    {"answer": {"tables": [{"obj_id": target_obj_id}]}},
                ],
            },
            modifieds={"src": 100, "a1": 200},
        )
        plan = {
            "operation": "REPOINT",
            "backup_dir": "/tmp/ts_dep_backup_x",
            "source": {"guid": "src", "type": "MODEL", "name": "Orders Model", "modified_at": 100},
            "target": {"guid": target_guid, "name": "New Orders"},
            "column_gap": [],
            "fix": [{"guid": "a1", "type": "ANSWER", "name": "Rev", "modified_at": 200}],
            "delete": [], "sets": [],
        }
        result = _run_apply(plan, client)
        assert result.exit_code == 0, _all_output(result)
        out = json.loads(result.stdout)
        assert "a1" in [r["guid"] for r in out["succeeded"]]
        assert "src" in [r["guid"] for r in out["succeeded"]]
        # obj_id-based repoint actually rewrote a1's table to the target obj_id.
        a1_import = next(c for c in client.calls
                         if c[0].endswith("/metadata/tml/import")
                         and "guid: a1" in c[1]["metadata_tmls"][0])
        assert target_obj_id in a1_import[1]["metadata_tmls"][0]

    def test_requires_backup_dir(self):
        plan = self._remove_plan()
        del plan["backup_dir"]
        client = _FakeClient(exports={}, modifieds={})
        result = _run_apply(plan, client)
        assert result.exit_code != 0
        assert "backup_dir" in _all_output(result)

    def test_remove_requires_columns(self):
        plan = self._remove_plan(columns_to_remove=[])
        client = _FakeClient(exports={}, modifieds={})
        result = _run_apply(plan, client)
        assert result.exit_code != 0
        assert "columns_to_remove" in _all_output(result)

    def test_repoint_requires_target(self):
        plan = {
            "operation": "REPOINT",
            "backup_dir": "/tmp/x",
            "source": {"guid": "src", "type": "MODEL", "name": "M", "modified_at": 1},
            "fix": [], "delete": [], "sets": [],
        }
        client = _FakeClient(exports={}, modifieds={})
        result = _run_apply(plan, client)
        assert result.exit_code != 0
        assert "target" in _all_output(result).lower()

    def test_invalid_operation_rejected(self):
        client = _FakeClient(exports={}, modifieds={})
        result = _run_apply({"operation": "RENAME", "backup_dir": "/tmp/x",
                             "source": {"guid": "s"}}, client)
        assert result.exit_code != 0

    def test_feedback_inline_tml_is_used_not_exported(self):
        # A FEEDBACK fix entry carries inline tml (open-item #18: can't export standalone).
        client = _FakeClient(
            exports={
                "src": {"model": {"columns": [{"name": "Keep"}]}},
                # verify re-export of the feedback object (by guid) returns clean.
                "fb1": {"nls_feedback": {"feedback": []}},
            },
            modifieds={"src": 100, "fb1": 200},
        )
        plan = self._remove_plan(
            delete=[],
            fix=[{"guid": "fb1", "type": "FEEDBACK", "name": "Spotter FB", "modified_at": 200,
                  "tml": {"nls_feedback": {"feedback": [{"q": "revenue by Legacy"}]}}}],
        )
        result = _run_apply(plan, client)
        assert result.exit_code == 0, _all_output(result)
        # No export call was made to fetch fb1 for mutation (inline tml used); the only
        # export for fb1 is the verify re-export.
        fb_exports = [c for c in client.calls
                      if c[0].endswith("/metadata/tml/export")
                      and c[1]["metadata"][0]["identifier"] == "fb1"]
        assert len(fb_exports) == 1  # verify only
