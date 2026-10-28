"""scripts/lib/python-bin.sh: the interpreter pre-commit and pr-ready run the checks with.

Without an override it takes the newest `python3.1x` on PATH that imports pytest, so
a CI-equivalent virtual environment built on 3.12 lost to any newer Python with
pytest anywhere on PATH (BL-436). `CHECKS_PYTHON` names the interpreter outright and
is honoured before that search. It fails closed: a value that is not an executable
importing pytest stops the caller with a message naming the variable, and never
falls back to the search, which would run the checks on an interpreter the user
just said not to use.

Each case sources the REAL library under `set -euo pipefail` with /bin/bash (3.2 on
macOS), on a PATH holding only stub interpreters, so nothing on the machine can be
picked by accident.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
LIB = REPO / "scripts" / "lib" / "python-bin.sh"
PR_READY_SH = REPO / "scripts" / "pr-ready.sh"

#: Imports anything (pytest included), says what it is, and records that it ran.
WITH_PYTEST = '#!/bin/sh\necho "RAN {name} $*"\nexit 0\n'
#: A Python without pytest: `-c "import pytest"` fails; `--version` answers.
WITHOUT_PYTEST = ('#!/bin/sh\n'
                  'if [ "$1" = "--version" ]; then echo "Python 3.9.6"; exit 0; fi\n'
                  'if [ "$1" = "-c" ]; then exit 1; fi\n'
                  'echo "RAN {name} $*"\nexit 0\n')


def _stub(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body.format(name=name))
    path.chmod(0o755)
    return path


def _source(bin_dir: Path, checks_python=None):
    env = {"PATH": str(bin_dir), "LIB": str(LIB)}
    if checks_python is not None:
        env["CHECKS_PYTHON"] = checks_python
    return subprocess.run(
        ["/bin/bash", "-c", 'set -euo pipefail; source "$LIB"; echo "PYTHON_BIN=$PYTHON_BIN"'],
        env=env, capture_output=True, text=True)


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


def _assert_fails_closed(result):
    assert result.returncode != 0, result.stdout
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


def test_pr_ready_sh_stops_on_a_bad_override_and_runs_nothing(tmp_path):
    # The wrapper, end to end: a newer Python with pytest is first on PATH, and must
    # not be used in the override's place.
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3.14", WITH_PYTEST)
    git = subprocess.run(["/bin/sh", "-c", "command -v git"], capture_output=True,
                         text=True).stdout.strip()
    env = {"PATH": f"{bin_dir}:{Path(git).parent}:/usr/bin:/bin",
           "CHECKS_PYTHON": str(tmp_path / "missing" / "python3.12")}
    result = subprocess.run(["/bin/bash", str(PR_READY_SH), "--help"], cwd=REPO, env=env,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "RAN" not in result.stdout + result.stderr, "fell back to the search"
    assert "CHECKS_PYTHON" in result.stderr


def test_bare_python3_fallback_names_the_remedy(tmp_path):
    bin_dir = tmp_path / "bin"
    _stub(bin_dir, "python3", WITHOUT_PYTEST)
    result = _source(bin_dir)
    assert result.returncode == 0, result.stderr
    assert _picked(result) == "python3"
    out = result.stdout
    assert "Warning: no python3.10+ interpreter with pytest installed found on PATH" in out
    assert "CHECKS_PYTHON" in out and ".github/CONTRIBUTING.md" in out, out
