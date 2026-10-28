"""Tests for pr_tree.py — a PR head's files written as raw blobs for the read-only
reviewer. The PR must not decide what the reviewer sees: its own .gitattributes
(filters, export-subst, export-ignore) are not applied, symlinks are not written, and
nothing comes out executable."""
from __future__ import annotations

import os
import stat
import subprocess

import pytest

import pr_tree


def _git(repo, *args, **kw):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True, **kw).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    # A filter that would leave a mark if anything ran it (repo-local config, as a
    # hostile .gitattributes would pair with a maintainer's own filter definitions).
    marker = tmp_path / "FILTER-RAN"
    _git(r, "config", "filter.evil.smudge", f"touch {marker}; cat")
    _git(r, "config", "filter.evil.clean", "cat")
    (r / ".gitattributes").write_text("*.txt filter=evil\nsubst.md export-subst\n"
                                      "hidden.md export-ignore\n")
    (r / "a.txt").write_text("plain\n")
    (r / "subst.md").write_text("$Format:%H$\n")
    (r / "hidden.md").write_text("still here\n")
    (r / "dir").mkdir()
    (r / "dir" / "run.sh").write_text("#!/bin/sh\necho hi\n")
    os.chmod(r / "dir" / "run.sh", 0o755)
    os.symlink("/etc/hosts", r / "link")
    _git(r, "add", "-A")
    # A submodule entry, added by hand.
    _git(r, "update-index", "--add", "--cacheinfo", f"160000,{'a' * 40},sub")
    _git(r, "commit", "-qm", "c")
    return r, _git(r, "rev-parse", "HEAD"), marker


def test_extract_writes_raw_blobs_and_skips_links_and_submodules(repo, tmp_path):
    r, head, marker = repo
    out = tmp_path / "out"
    result = pr_tree.extract(r, head, out)
    assert sorted(result["written"]) == [".gitattributes", "a.txt", "dir/run.sh",
                                         "hidden.md", "subst.md"]
    assert sorted(result["skipped"]) == ["link (symlink)", "sub (submodule)"]
    assert (out / "subst.md").read_text() == "$Format:%H$\n"   # not expanded
    assert (out / "hidden.md").read_text() == "still here\n"   # not dropped
    assert (out / "a.txt").read_text() == "plain\n"
    assert not marker.exists(), "a filter driver ran"
    assert not (out / "link").exists() and not os.path.islink(out / "link")
    mode = stat.S_IMODE(os.stat(out / "dir" / "run.sh").st_mode)
    assert not mode & 0o111, oct(mode)


def test_extract_refuses_a_non_empty_output(repo, tmp_path):
    r, head, _ = repo
    out = tmp_path / "out"
    out.mkdir()
    (out / "x").write_text("x")
    with pytest.raises(pr_tree.TreeError, match="not empty"):
        pr_tree.extract(r, head, out)


@pytest.mark.parametrize("path", ["../x", "/etc/x", "a/../b", "a//b", "./a", "a\\b", ""])
def test_unsafe_paths_are_refused(path):
    assert not pr_tree.safe_path(path)


def test_ordinary_paths_are_safe():
    assert pr_tree.safe_path("tools/ts-cli/ts_cli/tml_lint.py")
    assert pr_tree.safe_path(".github/CODEOWNERS")


def test_cli_exit_codes(repo, tmp_path, monkeypatch):
    r, head, _ = repo
    monkeypatch.chdir(r)
    assert pr_tree.main([]) == 2
    assert pr_tree.main(["no-such-commit", str(tmp_path / "o1")]) == 1
    assert pr_tree.main([head, str(tmp_path / "o2")]) == 0
