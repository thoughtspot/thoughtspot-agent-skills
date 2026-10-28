"""scripts/lib/python-bin.sh: the interpreter pre-commit and pr-ready run the checks with.

Without an override it takes the newest `python3.1x` on PATH that imports pytest, so
a CI-equivalent virtual environment built on 3.12 lost to any newer Python with
pytest anywhere on PATH (BL-436). `CHECKS_PYTHON` names the interpreter outright and
is honoured before that search. It fails closed: a value that does not run as a
Python 3.10+ that imports pytest stops the caller (exit 2) with a message naming the
variable, and never falls back to the search, which would run the checks on an
interpreter the user just said not to use.

The probe must PRINT a token. An exit-status-only probe accepted `true`, `:` or
`echo`, and pre-commit then read their exit 0 as PASS for every check, the secrets
and customer-reference gates included.

Each case sources the REAL library under `set -euo pipefail` with /bin/bash (3.2 on
macOS), on a PATH holding only stub interpreters, so nothing on the machine can be
picked by accident. A stub's `-c` runs the real probe code on this test's own Python
(with pytest hidden, or `sys.version_info` set to 3.9, where the case needs it), so
the library's probe is exercised, not imitated.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import evidence

REPO = Path(__file__).resolve().parents[3]
LIB = REPO / "scripts" / "lib" / "python-bin.sh"
PR_READY_SH = REPO / "scripts" / "pr-ready.sh"
REAL = sys.executable

_RUN = 'echo "RAN {name} $*"\nexit 0\n'
#: A Python 3.10+ with pytest: `-c` runs on the real interpreter; anything else is
#: recorded, so a test can see whether the stub was used to run the checks.
WITH_PYTEST = '#!/bin/sh\nif [ "$1" = "-c" ]; then exec "' + REAL + '" "$@"; fi\n' + _RUN
#: A Python without pytest (`import pytest` raises); `--version` answers 3.9.6.
WITHOUT_PYTEST = ('#!/bin/sh\n'
                  'if [ "$1" = "--version" ]; then echo "Python 3.9.6"; exit 0; fi\n'
                  'if [ "$1" = "-c" ]; then exec "' + REAL + '" -c '
                  '"import sys; sys.modules[\'pytest\'] = None; exec(sys.argv[1])" "$2"; fi\n'
                  + _RUN)
#: A Python 3.9 that has pytest.
OLD_WITH_PYTEST = ('#!/bin/sh\n'
                   'if [ "$1" = "-c" ]; then exec "' + REAL + '" -c '
                   '"import sys; sys.version_info = (3, 9, 6, \'final\', 0); exec(sys.argv[1])" '
                   '"$2"; fi\n' + _RUN)


def _stub(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body.replace("{name}", name))
    path.chmod(0o755)
    return path


def _source(bin_dir: Path, checks_python=None, cwd=None):
    env = {"PATH": str(bin_dir), "LIB": str(LIB)}
    if checks_python is not None:
        env["CHECKS_PYTHON"] = checks_python
    return subprocess.run(
        ["/bin/bash", "-c", 'set -euo pipefail; source "$LIB"; echo "PYTHON_BIN=$PYTHON_BIN"'],
        env=env, capture_output=True, text=True, cwd=cwd)


def _picked(result) -> str:
    lines = [l for l in result.stdout.splitlines() if l.startswith("PYTHON_BIN=")]
    assert len(lines) == 1, (result.stdout, result.stderr)
    return lines[0].split("=", 1)[1]


def test_unset_takes_the_newest_python_with_pytest(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.12", WITH_PYTEST)
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    result = _source(bin_dir)
    assert result.returncode == 0, result.stderr
    assert _picked(result) == "python3.14"
    assert result.stderr == ""


def test_override_wins_over_a_newer_python_with_pytest(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    venv_python = _stub(tmp_path / "venv" / "bin", "python3.12", WITH_PYTEST)
    result = _source(bin_dir, str(venv_python))
    assert result.returncode == 0, result.stderr
    assert _picked(result) == str(venv_python)


def test_override_by_command_name_resolves_on_path(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    _stub(bin_dir, "python3.12", WITH_PYTEST)
    result = _source(bin_dir, "python3.12")
    assert result.returncode == 0, result.stderr
    assert _picked(result) == str(bin_dir / "python3.12")


def test_relative_override_resolves_against_the_working_directory(tmp_path):
    # Both callers cd to the checkout root before sourcing, so that is what it means.
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    _stub(tmp_path / "root" / "venv" / "bin", "python3.12", WITH_PYTEST)
    result = _source(bin_dir, "venv/bin/python3.12", cwd=tmp_path / "root")
    assert result.returncode == 0, result.stderr
    assert _picked(result) == "venv/bin/python3.12"


def _assert_fails_closed(result):
    # 2, pr-ready's "could not start".
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert "PYTHON_BIN=" not in result.stdout, "the caller carried on after the error"
    assert "CHECKS_PYTHON" in result.stderr, result.stderr


def test_override_that_does_not_exist_fails_closed(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    _assert_fails_closed(_source(bin_dir, str(tmp_path / "no-such-venv" / "bin" / "python3.12")))


def test_override_without_pytest_fails_closed(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    bare = _stub(tmp_path / "bare", "python3.12", WITHOUT_PYTEST)
    result = _source(bin_dir, str(bare))
    _assert_fails_closed(result)
    assert "pytest" in result.stderr


def test_override_older_than_3_10_fails_closed(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    old = _stub(tmp_path / "old", "python3.9", OLD_WITH_PYTEST)
    result = _source(bin_dir, str(old))
    _assert_fails_closed(result)
    assert "3.10" in result.stderr, result.stderr


def test_override_that_only_exits_0_fails_closed(tmp_path):
    # The fail-open the token probe exists for: these exit 0 for any arguments, so an
    # exit-status probe took them for a Python with pytest, and every check "passed".
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    for value in ("true", ":", "echo", "/usr/bin/true"):
        if value.startswith("/") and not Path(value).exists():
            continue
        _assert_fails_closed(_source(bin_dir, value))


def test_override_that_is_not_executable_fails_closed(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    plain = tmp_path / "python3.12"
    plain.write_text("not a program\n")
    _assert_fails_closed(_source(bin_dir, str(plain)))


def test_empty_override_fails_closed(tmp_path):
    # Set but empty is a mistake (a variable that did not expand), not "unset".
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    _assert_fails_closed(_source(bin_dir, ""))


def test_bare_python3_fallback_names_the_remedy(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3", WITHOUT_PYTEST)
    result = _source(bin_dir)
    assert result.returncode == 0, result.stderr
    assert _picked(result) == "python3"
    out = result.stdout
    assert "Warning: no python3.10+ interpreter with pytest installed found on PATH" in out
    assert "CHECKS_PYTHON" in out and ".github/CONTRIBUTING.md" in out, out


# ------------------------------------------------------- scripts/pr-ready.sh ---

def _pr_ready_repo(tmp_path: Path) -> Path:
    """A throwaway checkout holding the real pr-ready.sh and python-bin.sh, with an
    earlier READY block on disk. Never the repo under test: the wrapper replaces its
    evidence file, and a test must not discard the developer's."""
    root = tmp_path / "repo"
    (root / "scripts" / "lib").mkdir(parents=True)
    shutil.copy2(PR_READY_SH, root / "scripts" / "pr-ready.sh")
    shutil.copy2(LIB, root / "scripts" / "lib" / "python-bin.sh")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True,
                   env={"PATH": _tool_path(), "HOME": str(tmp_path)})
    block = root / ".git" / "pr-ready" / "evidence.md"
    block.parent.mkdir()
    block.write_text("**pr-ready** head `abc` against `refs/remotes/upstream/main` at `def`\n"
                     "\n**READY**\n")
    return root


def _tool_path() -> str:
    git = shutil.which("git")
    assert git, "git is needed for these tests"
    return f"{Path(git).parent}:/usr/bin:/bin"


def test_pr_ready_sh_stops_on_a_bad_override_and_replaces_the_evidence(tmp_path):
    # A newer Python with pytest is first on PATH and must not be used in the
    # override's place; and an earlier READY block must not survive a run that could
    # not start, so the placeholder is written before the interpreter is chosen.
    root = _pr_ready_repo(tmp_path)
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    env = {"PATH": f"{bin_dir}:{_tool_path()}", "HOME": str(tmp_path),
           "CHECKS_PYTHON": str(tmp_path / "missing" / "python3.12")}
    result = subprocess.run(["/bin/bash", "scripts/pr-ready.sh", "--no-review"], cwd=root,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert "RAN" not in result.stdout + result.stderr, "fell back to the search"
    assert "CHECKS_PYTHON" in result.stderr
    text = (root / ".git" / "pr-ready" / "evidence.md").read_text(encoding="utf-8")
    # The same bytes pr_ready.py writes first, so every reader treats it alike.
    assert text == evidence.UNFINISHED, text
    assert evidence.header(text) is None


def test_pr_ready_sh_placeholder_is_what_pr_ready_py_writes():
    # A drifted copy would be read differently by evidence.py and the skill.
    assert evidence.UNFINISHED.rstrip("\n") in PR_READY_SH.read_text(encoding="utf-8")
