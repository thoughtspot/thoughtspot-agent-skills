"""Tests for _git — the shared git-enumeration layer (BL-218 / audit finding 4.2).

The bytes in these fixtures are not invented; they were captured from real `git`
output in a scratch repo containing a rename and a non-ASCII filename. That matters
because the whole class of bug being fixed here came from *assuming* a format:
callers assumed newline-separated unquoted paths, and git delivers octal-quoted ones
on one axis and variable-width records on the other.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _git import (  # noqa: E402
    GitEnumerationError, git_paths, git_status_paths, parse_name_status_z,
)


class TestParseNameStatusZ:
    def test_ordinary_records(self):
        out = parse_name_status_z("A\0a/added.md\0M\0a/plain.md\0")
        assert out == [("", "A", "a/added.md"), ("", "M", "a/plain.md")]

    def test_rename_yields_the_new_path(self):
        # R100\0old\0new\0 — three fields, not two.
        out = parse_name_status_z("R100\0a/old.md\0a/new.md\0")
        assert out == [("", "R100", "a/new.md")]

    def test_rename_does_not_desynchronise_following_records(self):
        """BL-218's stated reason for a dedicated parser.

        A naive pairwise split reads the rename's 3rd field as the NEXT record's
        status, and every record after it is mislabelled. Here that would make the
        second record ("M", "a/plain.md") come back as ("a/new.md", "M") — a status
        of "a/new.md" matches nothing, so the change is dropped silently.
        """
        out = parse_name_status_z("R100\0a/old.md\0a/new.md\0M\0a/plain.md\0A\0a/z.md\0")
        assert out == [("", "R100", "a/new.md"),
                       ("", "M", "a/plain.md"),
                       ("", "A", "a/z.md")]

    def test_copy_is_three_fields_too(self):
        out = parse_name_status_z("C75\0a/src.md\0a/copy.md\0M\0a/after.md\0")
        assert out == [("", "C75", "a/copy.md"), ("", "M", "a/after.md")]

    def test_non_ascii_path_survives_unquoted(self):
        """With -z git does not octal-quote, so the path arrives intact."""
        out = parse_name_status_z("A\0agents/cli/café.md\0")
        assert out == [("", "A", "agents/cli/café.md")]

    def test_git_log_prefix_carries_the_sha(self):
        """git glues the --pretty header to the first status letter with a newline."""
        log = ("\0" + "a" * 40 + "\nA\0agents/shared/x.md\0"
               "\0" + "b" * 40 + "\nM\0agents/shared/y.md\0")
        out = parse_name_status_z(log)
        assert out == [("a" * 40, "A", "agents/shared/x.md"),
                       ("b" * 40, "M", "agents/shared/y.md")]

    def test_empty_and_truncated_inputs_do_not_raise(self):
        assert parse_name_status_z("") == []
        assert parse_name_status_z("\0\0") == []
        assert parse_name_status_z("A\0") == []            # status with no path
        assert parse_name_status_z("R100\0only-old\0") == []  # rename missing new path


class TestAgainstRealGit:
    """End-to-end, because a hand-written fixture can drift from what git emits."""

    @staticmethod
    def _repo(tmp_path):
        run = lambda *a: subprocess.run(a, cwd=tmp_path, check=True,
                                        capture_output=True, text=True)
        run("git", "init", "-q", ".")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "plain.md").write_text("hello")
        (tmp_path / "a" / "torename.md").write_text("x")
        run("git", "add", "-A")
        run("git", "commit", "-qm", "base")
        return run

    def test_rename_to_a_non_ascii_name_is_reported(self, tmp_path):
        run = self._repo(tmp_path)
        run("git", "mv", "a/torename.md", "a/café.md")
        (tmp_path / "a" / "added.md").write_text("z")
        run("git", "add", "-A")

        records = git_status_paths(["diff", "--cached"], tmp_path)
        by_path = {path: status for _p, status, path in records}
        # The pre-BL-218 code dropped this path entirely: git quoted it and the
        # .exists()/split filter discarded it, so the gate reported PASS.
        assert "a/café.md" in by_path
        assert by_path["a/café.md"].startswith("R")
        assert by_path["a/added.md"] == "A"

    def test_plain_paths_still_enumerate(self, tmp_path):
        self._repo(tmp_path)
        assert "a/plain.md" in git_paths(["ls-files"], tmp_path)

    def test_failure_raises_instead_of_returning_empty(self, tmp_path):
        """An unrunnable git must never read as "nothing changed"."""
        try:
            git_status_paths(["diff", "--cached"], tmp_path / "not-a-repo")
        except (GitEnumerationError, FileNotFoundError, NotADirectoryError, OSError):
            return
        raise AssertionError("expected a raise, not a silent empty list")
