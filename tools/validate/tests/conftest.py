"""Put tools/validate on sys.path so tests can `import check_tml`, `import run_smoke_tests`,
etc. directly (mirrors the inline sys.path insert in test_check_tml.py)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _isolate_git_env(monkeypatch):
    """Strip inherited GIT_* env vars (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, ...).

    Several tests here `git init/add/commit` in tmp_path repos, and the checkers
    they exercise run their own git subprocesses. When this suite runs from a
    pre-commit hook — or any shell that exported GIT_DIR/GIT_WORK_TREE — those
    vars leak into every git call and point it at the REAL repo: `git init`
    rewrites its config (core.worktree → tmpdir, test identity) and
    `git add -A` mass-stages deletions of the actual working tree. Scrubbing
    os.environ per-test makes both subprocess helpers and in-process checker
    calls operate on tmp_path only.
    """
    for var in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(var, raising=False)
