# tools/ts-cli/tests/test_tml_file_dir_input.py
"""Unit tests for `ts tml import`/`ts tml lint` --file/--dir input (2026-07 audit
finding 11.1).

Two shipped skills (ts-convert-from-snowflake-sv SKILL.md:1568,
ts-convert-from-databricks-mv SKILL.md:1106) document:

    ts tml import --file {model_name}.model.tml --policy ALL_OR_NONE --profile {profile}

but `import_tml` was stdin-JSON-array only — that documented command failed with an
unknown-option error. This adds --file (repeatable) and --dir (non-recursive directory
scan) to both `ts tml import` and `ts tml lint`, reading raw TML text per file, while
keeping the original stdin JSON-array interface unchanged when neither is given.

Covers the pure path-assembly functions (collect_tml_paths, read_tml_texts,
load_tmls_from_args), the combined load_input_tmls() decision function (including the
stdin/--file ambiguity guard), and CLI-level wiring via CliRunner with a mocked
ThoughtSpotClient — no live connection anywhere.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.commands.tml import (
    collect_tml_paths,
    read_tml_texts,
    load_tmls_from_args,
    load_input_tmls,
)

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
# collect_tml_paths — pure path assembly (no file reads)
# ---------------------------------------------------------------------------

class TestCollectTmlPaths:
    def test_files_only_returned_verbatim_in_order(self):
        assert collect_tml_paths(["b.tml", "a.tml"], None) == ["b.tml", "a.tml"]

    def test_no_files_no_dir_returns_empty(self):
        assert collect_tml_paths([], None) == []

    def test_dir_expands_to_matching_files_sorted(self, tmp_path):
        (tmp_path / "b.tml").write_text("table:\n  name: B\n")
        (tmp_path / "a.tml").write_text("table:\n  name: A\n")
        (tmp_path / "notes.txt").write_text("ignore me")
        paths = collect_tml_paths([], str(tmp_path))
        names = [Path(p).name for p in paths]
        assert names == ["a.tml", "b.tml"]

    def test_dir_accepts_yaml_yml_json_extensions(self, tmp_path):
        (tmp_path / "one.yaml").write_text("model:\n  name: One\n")
        (tmp_path / "two.yml").write_text("model:\n  name: Two\n")
        (tmp_path / "three.json").write_text('{"model": {"name": "Three"}}')
        (tmp_path / "ignored.md").write_text("# not tml")
        paths = collect_tml_paths([], str(tmp_path))
        names = sorted(Path(p).name for p in paths)
        assert names == ["one.yaml", "three.json", "two.yml"]

    def test_dir_extension_match_case_insensitive(self, tmp_path):
        (tmp_path / "upper.TML").write_text("table:\n  name: X\n")
        paths = collect_tml_paths([], str(tmp_path))
        assert len(paths) == 1

    def test_dir_is_non_recursive(self, tmp_path):
        (tmp_path / "top.tml").write_text("table:\n  name: Top\n")
        sub = tmp_path / "nested"
        sub.mkdir()
        (sub / "deep.tml").write_text("table:\n  name: Deep\n")
        paths = collect_tml_paths([], str(tmp_path))
        names = [Path(p).name for p in paths]
        assert names == ["top.tml"]

    def test_files_come_before_dir_entries(self, tmp_path):
        (tmp_path / "z.tml").write_text("table:\n  name: Z\n")
        paths = collect_tml_paths(["explicit.tml"], str(tmp_path))
        assert Path(paths[0]).name == "explicit.tml"
        assert Path(paths[1]).name == "z.tml"

    def test_missing_dir_raises_system_exit(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        with pytest.raises(SystemExit):
            collect_tml_paths([], str(missing))

    def test_dir_pointing_at_a_file_raises_system_exit(self, tmp_path):
        f = tmp_path / "not-a-dir.tml"
        f.write_text("table:\n  name: X\n")
        with pytest.raises(SystemExit):
            collect_tml_paths([], str(f))

    def test_dir_with_no_matching_files_raises_system_exit(self, tmp_path):
        (tmp_path / "notes.txt").write_text("nothing here")
        with pytest.raises(SystemExit):
            collect_tml_paths([], str(tmp_path))


# ---------------------------------------------------------------------------
# read_tml_texts — raw file reads
# ---------------------------------------------------------------------------

class TestReadTmlTexts:
    def test_reads_raw_text_preserving_order(self, tmp_path):
        a = tmp_path / "a.tml"
        b = tmp_path / "b.tml"
        a.write_text("table:\n  name: A\n")
        b.write_text("table:\n  name: B\n")
        texts = read_tml_texts([str(a), str(b)])
        assert texts == ["table:\n  name: A\n", "table:\n  name: B\n"]

    def test_missing_file_raises_system_exit(self, tmp_path):
        with pytest.raises(SystemExit):
            read_tml_texts([str(tmp_path / "nope.tml")])

    def test_empty_list_returns_empty(self):
        assert read_tml_texts([]) == []


class TestLoadTmlsFromArgs:
    def test_full_pipeline_file_and_dir(self, tmp_path):
        explicit = tmp_path / "explicit.tml"
        explicit.write_text("table:\n  name: Explicit\n")
        dir_path = tmp_path / "batch"
        dir_path.mkdir()
        (dir_path / "one.tml").write_text("table:\n  name: One\n")
        texts = load_tmls_from_args([str(explicit)], str(dir_path))
        assert texts == ["table:\n  name: Explicit\n", "table:\n  name: One\n"]


# ---------------------------------------------------------------------------
# load_input_tmls — the combined decision function (stdin fallback + ambiguity guard)
# ---------------------------------------------------------------------------

class TestLoadInputTmlsStdinFallback:
    """When neither --file nor --dir is given, behaviour is byte-for-byte the
    original stdin-JSON-array interface — unchanged."""

    def test_stdin_json_array(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(["a", "b"])))
        assert load_input_tmls([], None) == ["a", "b"]

    def test_stdin_single_json_string(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps("solo")))
        assert load_input_tmls([], None) == ["solo"]

    def test_stdin_invalid_json_raises_system_exit(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
        with pytest.raises(SystemExit):
            load_input_tmls([], None)

    def test_stdin_non_list_non_string_raises_system_exit(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"not": "a list"})))
        with pytest.raises(SystemExit):
            load_input_tmls([], None)


class TestLoadInputTmlsFileMode:
    def test_file_mode_used_when_stdin_is_a_tty(self, tmp_path, monkeypatch):
        f = tmp_path / "a.tml"
        f.write_text("table:\n  name: A\n")

        class _TtyStdin(io.StringIO):
            def isatty(self):
                return True

        monkeypatch.setattr(sys, "stdin", _TtyStdin(""))
        assert load_input_tmls([str(f)], None) == ["table:\n  name: A\n"]

    def test_file_mode_used_when_stdin_is_empty_but_redirected(self, tmp_path, monkeypatch):
        """Redirected-but-empty stdin (e.g. /dev/null, or CliRunner's default empty
        stream) must not be treated as an ambiguity conflict."""
        f = tmp_path / "a.tml"
        f.write_text("table:\n  name: A\n")
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # non-tty, empty
        assert load_input_tmls([str(f)], None) == ["table:\n  name: A\n"]

    def test_dir_mode_works_without_file(self, tmp_path, monkeypatch):
        (tmp_path / "a.tml").write_text("table:\n  name: A\n")
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        assert load_input_tmls([], str(tmp_path)) == ["table:\n  name: A\n"]

    def test_ambiguous_file_and_piped_stdin_raises_system_exit(self, tmp_path, monkeypatch):
        f = tmp_path / "a.tml"
        f.write_text("table:\n  name: A\n")
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(["other"])))  # non-tty, non-empty
        with pytest.raises(SystemExit):
            load_input_tmls([str(f)], None)

    def test_ambiguous_dir_and_piped_stdin_raises_system_exit(self, tmp_path, monkeypatch):
        (tmp_path / "a.tml").write_text("table:\n  name: A\n")
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(["other"])))
        with pytest.raises(SystemExit):
            load_input_tmls([], str(tmp_path))

    def test_ambiguity_error_message_names_both_modes(self, tmp_path, monkeypatch):
        f = tmp_path / "a.tml"
        f.write_text("table:\n  name: A\n")
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(["other"])))
        with pytest.raises(SystemExit) as exc_info:
            load_input_tmls([str(f)], None)
        msg = str(exc_info.value)
        assert "stdin" in msg.lower()
        assert "--file" in msg or "--dir" in msg


# ---------------------------------------------------------------------------
# CLI-level wiring: ts tml import --file / --dir
# ---------------------------------------------------------------------------

class TestImportCliFileOption:
    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_import_file_reads_raw_text_and_sends_it(self, mock_resolve, mock_client_cls, tmp_path):
        f = tmp_path / "model.tml"
        f.write_text("model:\n  name: MyModel\n")
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            {"response": {"status": {"status_code": "OK"},
                          "object": [{"header": {"id_guid": "g-1"}}]}}
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["tml", "import", "--file", str(f), "--policy", "ALL_OR_NONE"])

        assert result.exit_code == 0, _all_output(result)
        body = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1]["json"]
        assert body["metadata_tmls"] == ["model:\n  name: MyModel\n"]
        assert body["import_policy"] == "ALL_OR_NONE"

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_import_file_repeatable(self, mock_resolve, mock_client_cls, tmp_path):
        a = tmp_path / "a.tml"
        b = tmp_path / "b.tml"
        a.write_text("table:\n  name: A\n")
        b.write_text("table:\n  name: B\n")
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            {"response": {"status": {"status_code": "OK"},
                          "object": [{"header": {"id_guid": "g-1"}}]}}
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["tml", "import", "--file", str(a), "--file", str(b)])

        assert result.exit_code == 0, _all_output(result)
        body = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1]["json"]
        assert body["metadata_tmls"] == ["table:\n  name: A\n", "table:\n  name: B\n"]

    @patch("ts_cli.commands.tml.ThoughtSpotClient")
    @patch("ts_cli.commands.tml.resolve_profile", return_value="test")
    def test_import_dir_imports_every_matching_file(self, mock_resolve, mock_client_cls, tmp_path):
        (tmp_path / "a.tml").write_text("table:\n  name: A\n")
        (tmp_path / "b.tml").write_text("table:\n  name: B\n")
        mock_client = MagicMock()
        mock_client.post.return_value.json.return_value = [
            {"response": {"status": {"status_code": "OK"},
                          "object": [{"header": {"id_guid": "g-1"}}]}}
        ]
        mock_client_cls.return_value = mock_client

        result = runner.invoke(app, ["tml", "import", "--dir", str(tmp_path)])

        assert result.exit_code == 0, _all_output(result)
        body = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1]["json"]
        assert body["metadata_tmls"] == ["table:\n  name: A\n", "table:\n  name: B\n"]

    def test_import_missing_file_exits_nonzero(self, tmp_path):
        result = runner.invoke(app, ["tml", "import", "--file", str(tmp_path / "nope.tml")])
        assert result.exit_code != 0

    def test_import_ambiguous_file_and_stdin_exits_nonzero(self, tmp_path):
        f = tmp_path / "a.tml"
        f.write_text("table:\n  name: A\n")
        result = runner.invoke(
            app, ["tml", "import", "--file", str(f)],
            input=json.dumps(["some other tml"]),
        )
        assert result.exit_code != 0


class TestLintCliFileOption:
    def test_lint_file_reports_clean_for_valid_model(self, tmp_path):
        f = tmp_path / "model.tml"
        f.write_text(
            "model:\n"
            "  name: MyModel\n"
        )
        result = runner.invoke(app, ["tml", "lint", "--file", str(f)])
        payload = json.loads(result.stdout)
        assert "results" in payload
        assert payload["results"][0]["type"] == "model"
        assert payload["results"][0]["name"] == "MyModel"

    def test_lint_dir_processes_every_file_in_sorted_order(self, tmp_path):
        (tmp_path / "a.tml").write_text("model:\n  name: A\n")
        (tmp_path / "b.tml").write_text("model:\n  name: B\n")
        result = runner.invoke(app, ["tml", "lint", "--dir", str(tmp_path)])
        payload = json.loads(result.stdout)
        names = [r["name"] for r in payload["results"]]
        assert names == ["A", "B"]

    def test_lint_missing_dir_exits_nonzero(self, tmp_path):
        result = runner.invoke(app, ["tml", "lint", "--dir", str(tmp_path / "nope")])
        assert result.exit_code != 0
