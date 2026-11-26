"""pytest runs with the chosen interpreter's directory first on PATH (2026-11-26), so a
test that starts a shell calling a bare `python3` gets that interpreter and its packages,
not the system Python. Covers pr_ready's `_pytest_env` and the pre-commit hook's real
`run_pytest`, extracted from the hook."""
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_ready  # noqa: E402

HOOK = Path(__file__).resolve().parents[3] / "scripts" / "pre-commit.sh"


def _stub_dir(tmp_path: Path) -> Path:
    """A bin dir holding `pythonX` (reports which python3 a child shell finds) and
    `python3` (a marker)."""
    d = tmp_path / "venv-bin"
    d.mkdir()
    for name, body in (("pythonX", 'echo "FOUND=$(command -v python3)"\n'),
                       ("python3", "echo stub\n")):
        f = d / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    return d


def test_pr_ready_puts_the_interpreter_first_on_path(tmp_path, monkeypatch):
    d = _stub_dir(tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = pr_ready._pytest_env(str(d / "pythonX"))
    assert env["PATH"].split(os.pathsep)[0] == str(d)


def test_pr_ready_without_an_interpreter_leaves_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert pr_ready._pytest_env("")["PATH"] == "/usr/bin:/bin"


def test_pre_commit_run_pytest_puts_the_interpreter_first_on_path(tmp_path):
    d = _stub_dir(tmp_path)
    text = HOOK.read_text(encoding="utf-8")
    m = re.search(r"^run_pytest\(\) \{\n.*?^\}\n", text, re.S | re.M)
    assert m, "run_pytest not found in pre-commit.sh"
    script = ("FAILED=0\n_now_ms() { echo 0; }\n_record_duration() { :; }\n"
              + m.group(0) + 'run_pytest label\necho "$output"\n')
    r = subprocess.run(["bash", "-c", script],
                       env={"PATH": "/usr/bin:/bin", "PYTHON_BIN": str(d / "pythonX")},
                       capture_output=True, text=True)
    assert f"FOUND={d / 'python3'}" in r.stdout, r.stdout + r.stderr
