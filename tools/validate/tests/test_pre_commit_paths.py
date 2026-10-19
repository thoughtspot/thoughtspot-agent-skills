"""scripts/pre-commit.sh must work when the repository path contains a space.

`run_check` used to expand its command unquoted (`"$PYTHON_BIN" $cmd`) with `--root $REPO_ROOT`
inside, so `/path/with space/repo` reached every validator as two arguments. This runs
the REAL pre-commit.sh in a throwaway repo under a directory with a space in its name,
with every validator it calls replaced by a stub that fails unless `--root` names an
existing directory.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRE_COMMIT = REPO / "scripts" / "pre-commit.sh"

STUB = '''import os, sys
a = sys.argv[1:]
if "--root" in a:
    i = a.index("--root")
    if i + 1 >= len(a) or not os.path.isdir(a[i + 1]):
        print("STUB-BAD-ROOT", a)
        sys.exit(3)
sys.exit(0)
'''


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_pre_commit_runs_from_a_path_with_a_space(tmp_path):
    root = tmp_path / "dir with space" / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(PRE_COMMIT, root / "scripts" / "pre-commit.sh")
    validators = set(re.findall(r"tools/validate/[A-Za-z0-9_]+\.py", PRE_COMMIT.read_text()))
    assert len(validators) > 20, "expected the real hook's validator list"
    for v in validators:
        f = root / v
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(STUB)
    # run_pytest targets: give each a trivial passing test (distinct names, no packages).
    for i, d in enumerate(sorted(set(re.findall(r"\b((?:tools|agents)/[\w./-]*tests)/",
                                                PRE_COMMIT.read_text())))):
        (root / d).mkdir(parents=True, exist_ok=True)
        (root / d / f"test_stub_{i}.py").write_text("def test_ok():\n    pass\n")
    _git(["init", "-q", "-b", "feature"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / "README.md").write_text("hello\n")
    _git(["add", "-A"], root)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(["bash", "scripts/pre-commit.sh"], cwd=root, env=env,
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    out = result.stdout + result.stderr
    assert "STUB-BAD-ROOT" not in out, out
    assert result.returncode == 0, out
