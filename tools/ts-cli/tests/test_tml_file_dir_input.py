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

Covers the pure path-assembly functions (collect_tml_paths, read_tml_texts), the
combined load_input_tmls() decision function (including the stdin/--file ambiguity
guard), and CLI-level wiring via CliRunner with a mocked ThoughtSpotClient — no live
connection anywhere.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.commands.tml import (
    collect_tml_paths,
    read_tml_texts,
    load_input_tmls,
    order_and_filter_tml_paths,
    _stdin_has_piped_content,
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
# _stdin_has_piped_content — must never block on an idle open non-TTY stdin
# (BL-097: a background/script shell whose stdin is an open-but-empty pipe made
# the unconditional sys.stdin.read() hang forever; select() must short-circuit it)
# ---------------------------------------------------------------------------

class _PipeStdin:
    """Wrap the read end of a real OS pipe so isatty()/fileno() behave like a
    genuine redirected stdin — select() can poll it, unlike an io.StringIO."""

    def __init__(self, read_fd):
        self._f = os.fdopen(read_fd)

    def isatty(self):
        return False

    def fileno(self):
        return self._f.fileno()

    def read(self, *args):
        return self._f.read(*args)

    def close(self):
        self._f.close()


class TestStdinHasPipedContentNoHang:
    def _run_with_timeout(self, monkeypatch, read_fd, timeout=3.0):
        stdin = _PipeStdin(read_fd)
        monkeypatch.setattr(sys, "stdin", stdin)
        box = {}

        def worker():
            box["result"] = _stdin_has_piped_content()

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout)
        return t, box

    def test_open_pipe_no_data_returns_false_without_blocking(self, monkeypatch):
        """The BL-097 repro: writer end stays open, nothing written. The old
        unconditional read() blocked here forever; select() must return not-ready
        so the call completes promptly and reports 'no piped content'."""
        r, w = os.pipe()
        try:
            t, box = self._run_with_timeout(monkeypatch, r)
            assert not t.is_alive(), "read blocked on an idle open pipe (BL-097 regression)"
            assert box["result"] is False
        finally:
            os.close(w)

    def test_pipe_with_data_returns_true(self, monkeypatch):
        r, w = os.pipe()
        try:
            os.write(w, b"table:\n  name: A\n")
        finally:
            os.close(w)  # close writer so the read reaches EOF after the data
        t, box = self._run_with_timeout(monkeypatch, r)
        assert not t.is_alive()
        assert box["result"] is True

    def test_closed_pipe_eof_returns_false(self, monkeypatch):
        """A closed/empty pipe (e.g. `< /dev/null`) is readable but yields '' —
        that is 'no content', not a block."""
        r, w = os.pipe()
        os.close(w)  # immediate EOF, no data
        t, box = self._run_with_timeout(monkeypatch, r)
        assert not t.is_alive()
        assert box["result"] is False

    def test_tty_stdin_short_circuits_true_to_false(self, monkeypatch):
        class _TtyStdin(io.StringIO):
            def isatty(self):
                return True

        monkeypatch.setattr(sys, "stdin", _TtyStdin(""))
        assert _stdin_has_piped_content() is False

    def test_stringio_fallback_preserves_prior_behaviour(self, monkeypatch):
        """io.StringIO has no pollable fd, so select() raises UnsupportedOperation
        and we fall back to the prior blocking read — which is safe for an
        already-buffered in-memory stream and keeps the CliRunner tests valid."""
        monkeypatch.setattr(sys, "stdin", io.StringIO("some tml"))
        assert _stdin_has_piped_content() is True
        monkeypatch.setattr(sys, "stdin", io.StringIO(""))
        assert _stdin_has_piped_content() is False


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

    def test_lint_single_model_file_skips_cross_ref_check(self, tmp_path):
        # No table/sql_view TML in the batch — nothing to validate model_tables
        # against, so a model referencing an ungenerated table must NOT be flagged.
        f = tmp_path / "model.tml"
        f.write_text(
            "model:\n"
            "  name: MyModel\n"
            "  model_tables:\n"
            "  - name: SOME_TABLE\n"
        )
        result = runner.invoke(app, ["tml", "lint", "--file", str(f)])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["results"][0]["findings"] == []

    def test_lint_dir_catches_dangling_cross_reference(self, tmp_path):
        # A table.tml + a model.tml that references a table never generated —
        # the batch-level XREF check must catch it even though I1/I2/I4/I5/I8
        # (lint_tml) alone would not.
        (tmp_path / "orders.table.tml").write_text(
            "table:\n"
            "  name: ORDERS\n"
            "  columns:\n"
            "  - name: AMOUNT\n"
        )
        (tmp_path / "sales.model.tml").write_text(
            "model:\n"
            "  name: Sales\n"
            "  model_tables:\n"
            "  - name: ORDERS\n"
            "  - name: MISSING_TABLE\n"
            "  columns:\n"
            "  - name: Amount\n"
            "    column_id: ORDERS::AMOUNT\n"
        )
        result = runner.invoke(app, ["tml", "lint", "--dir", str(tmp_path)])
        assert result.exit_code != 0
        payload = json.loads(result.stdout)
        model_result = next(r for r in payload["results"] if r["name"] == "Sales")
        assert any(
            f.startswith("XREF:") and "MISSING_TABLE" in f
            for f in model_result["findings"]
        )

    def test_lint_dir_clean_model_and_table_together(self, tmp_path):
        (tmp_path / "orders.table.tml").write_text(
            "table:\n"
            "  name: ORDERS\n"
            "  columns:\n"
            "  - name: AMOUNT\n"
        )
        (tmp_path / "sales.model.tml").write_text(
            "model:\n"
            "  name: Sales\n"
            "  model_tables:\n"
            "  - name: ORDERS\n"
            "  columns:\n"
            "  - name: Amount\n"
            "    column_id: ORDERS::AMOUNT\n"
        )
        result = runner.invoke(app, ["tml", "lint", "--dir", str(tmp_path)])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["clean"] is True

    def test_lint_dir_renamed_column_resolves_via_db_column_name(self, tmp_path):
        # A model's physical column_id is TABLE::db_column_name, which can differ
        # from the display alias. The XREF check must index the table's
        # db_column_name too, else a renamed column trips a false finding.
        (tmp_path / "orders.table.tml").write_text(
            "table:\n"
            "  name: ORDERS\n"
            "  columns:\n"
            "  - name: Customer Name\n"
            "    db_column_name: CUST_NM\n"
        )
        (tmp_path / "sales.model.tml").write_text(
            "model:\n"
            "  name: Sales\n"
            "  model_tables:\n"
            "  - name: ORDERS\n"
            "  columns:\n"
            "  - name: Customer\n"
            "    column_id: ORDERS::CUST_NM\n"
        )
        result = runner.invoke(app, ["tml", "lint", "--dir", str(tmp_path)])
        assert result.exit_code == 0, result.stdout
        payload = json.loads(result.stdout)
        assert payload["clean"] is True


# ---------------------------------------------------------------------------
# order_and_filter_tml_paths + collect_tml_paths(patterns=...) (Task 9:
# TML ordering + phase-filter helpers, ts-convert-from-tableau codification)
# ---------------------------------------------------------------------------

class TestOrderAndFilterTmlPaths:
    def test_order_tableau_orders_by_type(self):
        paths = ["z.cohort.tml", "a.model.tml", "m.table.tml", "s.sql_view.tml", "b.liveboard.tml"]
        out = order_and_filter_tml_paths(paths, order="tableau")
        assert out == ["m.table.tml", "s.sql_view.tml", "a.model.tml", "z.cohort.tml", "b.liveboard.tml"]

    def test_model_phase_base_drops_phase1_plus(self):
        paths = ["x.phase0.model.tml", "x.phase1.model.tml", "x.phase2.model.tml", "y.model.tml"]
        out = order_and_filter_tml_paths(paths, model_phase="base")
        assert sorted(out) == ["x.phase0.model.tml", "y.model.tml"]

    def test_defaults_are_a_noop(self):
        paths = ["z.cohort.tml", "a.model.tml", "m.table.tml"]
        assert order_and_filter_tml_paths(paths) == paths


class TestCollectTmlPathsPatterns:
    def test_collect_patterns_filters(self, tmp_path):
        (tmp_path / "a.liveboard.tml").write_text("x")
        (tmp_path / "b.model.tml").write_text("x")
        got = collect_tml_paths([], str(tmp_path), patterns=["*.liveboard.tml"])
        assert [p.rsplit("/", 1)[-1] for p in got] == ["a.liveboard.tml"]

    def test_collect_patterns_none_preserves_existing_behaviour(self, tmp_path):
        (tmp_path / "a.tml").write_text("x")
        (tmp_path / "b.tml").write_text("x")
        got = collect_tml_paths([], str(tmp_path))
        assert [Path(p).name for p in got] == ["a.tml", "b.tml"]


# ---------------------------------------------------------------------------
# CLI-level wiring: --order/--model-phase/--pattern on `ts tml import`/`lint`
# (Task 10: threading order_and_filter_tml_paths/collect_tml_paths(patterns=)
# through the --file/--dir branch of load_input_tmls)
# ---------------------------------------------------------------------------

@patch("ts_cli.commands.tml.ThoughtSpotClient")
@patch("ts_cli.commands.tml.resolve_profile", return_value="test")
def test_import_dir_tableau_order_and_base_phase(mock_resolve, mock_client_cls, tmp_path):
    (tmp_path / "m.table.tml").write_text("table:\n  name: T\n")
    (tmp_path / "d.phase0.model.tml").write_text("model:\n  name: M0\n")
    (tmp_path / "d.phase1.model.tml").write_text("model:\n  name: M1\n")
    mock_client = MagicMock()
    mock_client.post.return_value.json.return_value = [
        {"response": {"status": {"status_code": "OK"}, "object": [{"header": {"id_guid": "g"}}]}}]
    mock_client_cls.return_value = mock_client
    result = runner.invoke(app, ["tml", "import", "--dir", str(tmp_path),
                                 "--order", "tableau", "--model-phase", "base",
                                 "--policy", "ALL_OR_NONE"])
    assert result.exit_code == 0, _all_output(result)
    body = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args[1]["json"]
    tmls = body["metadata_tmls"]
    assert "name: M1" not in "".join(tmls)          # phase1 dropped
    assert tmls[0].startswith("table:")              # table ordered first
    assert any("name: M0" in t for t in tmls)        # phase0 kept
