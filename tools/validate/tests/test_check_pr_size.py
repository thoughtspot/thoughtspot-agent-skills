"""Tests for check_pr_size.py — the warn-only large-PR content flag."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import check_pr_size as cps

VALIDATE = Path(__file__).resolve().parents[1]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo_with_branch(root: Path) -> None:
    _git(["init", "-q", "-b", "main"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / "README.md").write_text("base\n")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "base"], root)
    _git(["checkout", "-q", "-b", "feature"], root)


def _commit_all(root: Path) -> None:
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "change"], root)


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATE / "check_pr_size.py"), "--root", str(root), "--base", "main", *extra],
        capture_output=True, text=True,
    )


def test_is_asset_by_suffix_and_directory():
    assert cps.is_asset("agents/cli/x/references/screenshot.png")
    assert cps.is_asset("docs/report.PDF")
    assert cps.is_asset("tools/x/tests/fixtures/model.yaml")
    assert cps.is_asset("agents/shared/worked-examples/snowflake/example.md")
    assert not cps.is_asset("tools/ts-cli/ts_cli/client.py")
    assert not cps.is_asset("agents/cli/x/SKILL.md")


def test_small_pr_passes(tmp_path):
    _repo_with_branch(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    _commit_all(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "PR size OK" in result.stdout


def test_many_added_files_flagged(tmp_path):
    _repo_with_branch(tmp_path)
    for i in range(cps.MAX_ADDED_FILES + 1):
        (tmp_path / f"f{i}.md").write_text(f"{i}\n")
    _commit_all(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "::warning title=Large PR" in result.stdout
    assert f"{cps.MAX_ADDED_FILES + 1} files added" in result.stdout


def test_large_assets_flagged_and_listed(tmp_path):
    _repo_with_branch(tmp_path)
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples" / "big.bin").write_bytes(b"\1" * (cps.MAX_ASSET_BYTES + 1))
    _commit_all(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "of non-code assets" in result.stdout
    assert "examples/big.bin" in result.stdout


def test_large_code_file_is_not_an_asset(tmp_path):
    _repo_with_branch(tmp_path)
    (tmp_path / "big.py").write_text("#" * (cps.MAX_ASSET_BYTES + 1))
    _commit_all(tmp_path)
    assert _run(tmp_path).returncode == 0


def test_warn_mode_never_fails_on_size(tmp_path):
    _repo_with_branch(tmp_path)
    (tmp_path / "shot.png").write_bytes(b"\1" * (cps.MAX_ASSET_BYTES + 1))
    _commit_all(tmp_path)
    result = _run(tmp_path, "--warn")
    assert result.returncode == 0
    assert "::warning title=Large PR" in result.stdout


def test_no_base_skips_explicitly(tmp_path):
    result = subprocess.run(
        [sys.executable, str(VALIDATE / "check_pr_size.py"), "--root", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout.startswith("SKIP")


def test_unresolvable_base_fails_even_in_warn_mode(tmp_path):
    _repo_with_branch(tmp_path)
    result = subprocess.run(
        [sys.executable, str(VALIDATE / "check_pr_size.py"), "--root", str(tmp_path),
         "--base", "no-such-ref", "--warn"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "could not diff" in result.stdout
