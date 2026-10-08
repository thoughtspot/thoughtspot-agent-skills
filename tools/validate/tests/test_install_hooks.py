"""Tests for scripts/install-hooks.sh — the pre-commit DISPATCHER (BL-193).

Each test builds a throwaway repo carrying a copy of the real installer plus a stub
scripts/pre-commit.sh, and proves one property:

- each worktree runs its OWN scripts/pre-commit.sh — including a worktree on an OLD
  commit that predates the installer (the core.hooksPath design ran NO hook there);
- core.hooksPath is never set, and an existing one (local or global) is refused;
- pre-push is never installed or touched;
- an existing non-dispatcher pre-commit hook is backed up, not lost;
- the installer works from a subdirectory (the relative --git-common-dir bug);
- --check verifies the dispatcher's CONTENT, not a config value.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
INSTALLER = REPO / "scripts" / "install-hooks.sh"


def _env(tmp_path: Path) -> dict:
    """Isolate global git config so a real ~/.gitconfig (or hooksPath) never leaks in."""
    env = dict(os.environ)
    gc = tmp_path / "global.gitconfig"
    gc.touch()
    env["GIT_CONFIG_GLOBAL"] = str(gc)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(args, cwd: Path, env: dict, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True, env=env)


def _stub(path: Path, tag: str, exit_code: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/usr/bin/env bash\necho 'HOOK-RAN {tag}'\nexit {exit_code}\n")
    path.chmod(0o755)


def _make_repo(root: Path, env: dict, with_installer: bool = True,
               with_commit_msg: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _stub(root / "scripts" / "pre-commit.sh", "main-copy")
    _stub(root / "scripts" / "pre-push.sh", "pre-push")
    if with_installer:
        shutil.copy2(INSTALLER, root / "scripts" / "install-hooks.sh")
    if with_commit_msg:
        # The REAL commit-msg script and gate, so the end-to-end test exercises them.
        shutil.copy2(REPO / "scripts" / "commit-msg.sh", root / "scripts" / "commit-msg.sh")
        (root / "tools" / "validate").mkdir(parents=True)
        for f in ("check_customer_references.py", "_git.py"):
            shutil.copy2(REPO / "tools" / "validate" / f, root / "tools" / "validate" / f)
    _git(["init", "-q", "-b", "main"], root, env)
    _git(["config", "user.email", "test@example.com"], root, env)
    _git(["config", "user.name", "Test"], root, env)
    _git(["add", "-A"], root, env)
    _git(["commit", "-q", "--no-verify", "-m", "init"], root, env)


def _install(cwd: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    script = cwd / "scripts" / "install-hooks.sh"
    if not script.exists():                       # running from a subdirectory
        script = Path(_git(["rev-parse", "--show-toplevel"], cwd, env).stdout.strip()) / "scripts" / "install-hooks.sh"
    return subprocess.run(["bash", str(script), *args], cwd=cwd, capture_output=True, text=True, env=env)


def _commit(cwd: Path, env: dict, name: str) -> subprocess.CompletedProcess:
    (cwd / name).write_text(name + "\n")
    _git(["add", name], cwd, env)
    return _git(["commit", "-q", "-m", name], cwd, env, check=False)


def test_check_fails_loudly_when_not_installed(tmp_path):
    env = _env(tmp_path)
    _make_repo(tmp_path / "r", env)
    result = _install(tmp_path / "r", env, "--check")
    assert result.returncode == 1
    assert "NOT installed" in result.stdout


def test_install_writes_dispatcher_and_never_sets_hooks_path(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    assert _install(repo, env).returncode == 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert "pre-commit dispatcher" in hook.read_text() and os.access(hook, os.X_OK)
    assert _git(["config", "--get", "core.hooksPath"], repo, env, check=False).stdout == ""
    assert _install(repo, env, "--check").returncode == 0


def test_pre_push_is_never_installed_or_touched(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    _install(repo, env)
    assert not (repo / ".git" / "hooks" / "pre-push").exists()
    existing = repo / ".git" / "hooks" / "pre-push"
    existing.write_text("#!/bin/sh\n# user's own\n")
    _install(repo, env)
    assert existing.read_text() == "#!/bin/sh\n# user's own\n"


def test_check_verifies_content_not_presence(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    _install(repo, env)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(hook.read_text() + "# tampered\n")
    assert _install(repo, env, "--check").returncode == 1


def test_existing_hook_is_backed_up(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    legacy = repo / ".git" / "hooks" / "pre-commit"
    legacy.symlink_to("../../scripts/pre-commit.sh")
    result = _install(repo, env)
    assert "Backed up" in result.stdout
    backups = list((repo / ".git" / "hooks").glob("pre-commit.backup-*"))
    assert len(backups) == 1 and backups[0].is_symlink()


def test_refuses_when_hooks_path_set_locally(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    _git(["config", "core.hooksPath", "somewhere"], repo, env)
    result = _install(repo, env)
    assert result.returncode == 1 and "REFUSING" in result.stdout
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()
    assert _install(repo, env, "--check").returncode == 1


def test_refuses_when_hooks_path_set_globally(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    _git(["config", "--global", "core.hooksPath", "/elsewhere"], repo, env)
    result = _install(repo, env)
    assert result.returncode == 1 and "REFUSING" in result.stdout


def test_install_from_subdirectory_targets_the_real_git_dir(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert _install(sub, env).returncode == 0
    assert (repo / ".git" / "hooks" / "pre-commit").is_file()
    assert not (sub / ".git").exists()
    assert _install(sub, env, "--check").returncode == 0


def test_commit_runs_the_hook(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    _install(repo, env)
    out = _commit(repo, env, "a.txt")
    assert out.returncode == 0 and "HOOK-RAN main-copy" in out.stdout + out.stderr


def test_worktree_runs_its_own_pre_commit(tmp_path):
    env = _env(tmp_path)
    main = tmp_path / "main"
    _make_repo(main, env)
    _install(main, env)
    wt = tmp_path / "wt"
    _git(["worktree", "add", "-q", "-b", "feature", str(wt)], main, env)
    _stub(wt / "scripts" / "pre-commit.sh", "worktree-copy")
    out = _commit(wt, env, "b.txt")
    combined = out.stdout + out.stderr
    assert "HOOK-RAN worktree-copy" in combined and "main-copy" not in combined


def test_worktree_on_old_commit_without_installer_runs_and_is_blocked_by_its_own_hook(tmp_path):
    """The regression the core.hooksPath design had: an older checkout ran NO hook."""
    env = _env(tmp_path)
    main = tmp_path / "main"
    # OLD commit: no installer, and a pre-commit.sh that blocks.
    _make_repo(main, env, with_installer=False)
    _stub(main / "scripts" / "pre-commit.sh", "old-copy", exit_code=1)
    _git(["commit", "-q", "--no-verify", "-am", "old hook blocks"], main, env)
    old_sha = _git(["rev-parse", "HEAD"], main, env).stdout.strip()
    # NEW commit: installer arrives, hook passes.
    shutil.copy2(INSTALLER, main / "scripts" / "install-hooks.sh")
    _stub(main / "scripts" / "pre-commit.sh", "new-copy", exit_code=0)
    _git(["add", "-A"], main, env)
    _git(["commit", "-q", "--no-verify", "-m", "new"], main, env)
    _install(main, env)

    wt = tmp_path / "old"
    _git(["worktree", "add", "-q", "-b", "old-branch", str(wt), old_sha], main, env)
    assert not (wt / "scripts" / "install-hooks.sh").exists()
    out = _commit(wt, env, "c.txt")
    combined = out.stdout + out.stderr
    assert out.returncode != 0, combined
    assert "HOOK-RAN old-copy" in combined and "new-copy" not in combined


def test_missing_pre_commit_script_fails_closed(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    _install(repo, env)
    (repo / "scripts" / "pre-commit.sh").unlink()
    out = _commit(repo, env, "d.txt")
    assert out.returncode != 0 and "not found" in out.stderr


# ── item 5: commit-msg dispatcher ────────────────────────────────────────────

def _j(*parts: str) -> str:
    return "".join(parts)


def test_install_writes_both_dispatchers(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    _install(repo, env)
    hooks = repo / ".git" / "hooks"
    assert "pre-commit dispatcher" in (hooks / "pre-commit").read_text()
    assert "commit-msg dispatcher" in (hooks / "commit-msg").read_text()
    assert os.access(hooks / "commit-msg", os.X_OK)


def test_check_fails_when_commit_msg_dispatcher_missing(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    _install(repo, env)
    (repo / ".git" / "hooks" / "commit-msg").unlink()
    result = _install(repo, env, "--check")
    assert result.returncode == 1 and "commit-msg" in result.stdout


def test_existing_commit_msg_hook_is_backed_up(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "r"
    _make_repo(repo, env)
    (repo / ".git" / "hooks" / "commit-msg").write_text("#!/bin/sh\n# user's own\n")
    result = _install(repo, env)
    assert "Backed up the existing commit-msg hook" in result.stdout
    assert len(list((repo / ".git" / "hooks").glob("commit-msg.backup-*"))) == 1


def test_commit_message_with_a_tenant_link_is_blocked(tmp_path):
    env = _env(tmp_path)
    env.pop("TS_CUSTOMER_DENYLIST", None)
    env["HOME"] = str(tmp_path)                      # no private denylist on this run
    repo = tmp_path / "r"
    _make_repo(repo, env, with_commit_msg=True)
    _install(repo, env)
    (repo / "a.txt").write_text("a\n")
    _git(["add", "a.txt"], repo, env)
    bad = _git(["commit", "-q", "-m", _j("fix per https://acme-corp.", "atlassian.net/wiki/x")],
               repo, env, check=False)
    assert bad.returncode != 0, bad.stdout + bad.stderr
    assert "commit message:1" in bad.stdout + bad.stderr
    ok = _git(["commit", "-q", "-m", "a clean message"], repo, env, check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_old_branch_without_commit_msg_script_still_commits(tmp_path):
    env = _env(tmp_path)
    main = tmp_path / "main"
    _make_repo(main, env)                            # no scripts/commit-msg.sh at all
    _install(main, env)
    out = _commit(main, env, "e.txt")
    assert out.returncode == 0, out.stdout + out.stderr


# ── round 3: `#` lines are part of an -m message; the -v diff is not ──────────

def _msg_repo(tmp_path):
    env = _env(tmp_path)
    env["HOME"] = str(tmp_path)                      # no private denylist on this run
    env.pop("TS_CUSTOMER_DENYLIST", None)
    repo = tmp_path / "r"
    _make_repo(repo, env, with_commit_msg=True)
    _install(repo, env)
    return repo, env


def test_hash_line_in_dash_m_message_is_scanned(tmp_path):
    repo, env = _msg_repo(tmp_path)
    (repo / "a.txt").write_text("a\n")
    _git(["add", "a.txt"], repo, env)
    bad = _git(["commit", "-q", "-m", _j("#591 see https://contoso.", "atlassian.net/wiki/x")],
               repo, env, check=False)
    assert bad.returncode != 0, bad.stdout + bad.stderr


def test_forged_scissors_in_dash_m_message_does_not_bypass(tmp_path):
    """Round 4 item 3, end to end: a scissors line supplied with -m is not git's."""
    repo, env = _msg_repo(tmp_path)
    (repo / "a.txt").write_text("a\n")
    _git(["add", "a.txt"], repo, env)
    bad = _git(["commit", "-q", "-m", "s",
                "-m", "; ------------------------ >8 ------------------------",
                "-m", _j("https://contoso.", "atlassian.net/wiki/x")], repo, env, check=False)
    assert bad.returncode != 0, bad.stdout + bad.stderr


def test_verbose_diff_with_custom_comment_char_is_not_scanned(tmp_path):
    repo, env = _msg_repo(tmp_path)
    (repo / "notes.md").write_text(_j("https://contoso.", "atlassian.net/wiki/x\n"))
    _git(["add", "notes.md"], repo, env)
    _git(["commit", "-q", "--no-verify", "-m", "base"], repo, env)
    (repo / "notes.md").write_text("removed\n")
    _git(["add", "notes.md"], repo, env)
    editor = tmp_path / "editor.sh"
    editor.write_text('#!/bin/sh\nprintf "clean subject\\n" | cat - "$1" > "$1.new" && mv "$1.new" "$1"\n')
    editor.chmod(0o755)
    env["GIT_EDITOR"] = str(editor)
    out = _git(["-c", "core.commentChar=;", "commit", "-v"], repo, env, check=False)
    assert out.returncode == 0, out.stdout + out.stderr


def test_two_installs_in_the_same_second_keep_both_backups(tmp_path):
    """Round 3 item 10: backups were named by a one-second timestamp, so a second install
    in the same second overwrote the first backup. A fixed `date` makes that deterministic."""
    env = _env(tmp_path)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "date").write_text("#!/bin/sh\necho 20260101000000\n")
    (bindir / "date").chmod(0o755)
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    repo = tmp_path / "r"
    _make_repo(repo, env)
    hook = repo / ".git" / "hooks" / "pre-commit"
    for content in ("#!/bin/sh\n# first user hook\n", "#!/bin/sh\n# second user hook\n"):
        if hook.exists():
            hook.unlink()
        hook.write_text(content)
        assert _install(repo, env).returncode == 0
    backups = sorted((repo / ".git" / "hooks").glob("pre-commit.backup-*"))
    assert len(backups) == 2, backups
    assert {b.read_text() for b in backups} == {"#!/bin/sh\n# first user hook\n",
                                                  "#!/bin/sh\n# second user hook\n"}
