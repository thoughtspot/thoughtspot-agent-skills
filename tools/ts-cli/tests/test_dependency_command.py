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
