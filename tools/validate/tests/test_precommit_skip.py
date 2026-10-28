"""scripts/pre-commit.sh must report a skipped check as SKIP, never PASS.

A validator that cannot run (e.g. check_module_health without radon) exits 0 and
prints a line starting `SKIP`. `run_check` used to treat every exit 0 as PASS, so a
check that checked nothing read as green. The convention is the one
tools/validate/run_checks.py's classify() uses: exit 0 plus a line STARTING with
`SKIP` is a whole-check skip; an indented per-item `  SKIP ...` line is not.

This extracts the REAL `run_check` (and the timing helpers it calls) from the hook
with a sed range and drives it with a stub interpreter, so the test exercises the
shipped function rather than a copy of it.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRE_COMMIT = REPO / "scripts" / "pre-commit.sh"

# Function bodies close on a column-0 `}`; _now_ms is a one-liner.
_EXTRACT = (
    r"sed -n -e '/^_now_ms()/p' "
    r"-e '/^_record_duration() {/,/^}/p' "
    r"-e '/^run_check() {/,/^}/p' "
    r"-e '/^_summary_line() {/,/^}/p' "
)


def _run(tmp_path: Path, stub_body: str, labels: tuple[str, ...] = ("module health",),
         ) -> tuple[str, str]:
    stub = tmp_path / "fake-python"
    stub.write_text("#!/bin/sh\n" + stub_body)
    stub.chmod(0o755)
    calls = "".join(
        f'run_check "{label}" "tools/validate/check_{i}.py --root ."\n'
        for i, label in enumerate(labels)
    )
    script = (
        f'eval "$({_EXTRACT} "$HOOK")"\n'
        "SLOW_CHECK_S=3; SLOW_CHECKS=''; FAILED=0; SKIPPED=0; SKIPPED_LABELS=''\n"
        + calls
        + 'echo "FAILED=$FAILED"\n'
        "_summary_line\n"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": "/usr/bin:/bin", "HOOK": str(PRE_COMMIT), "PYTHON_BIN": str(stub)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout, result.stderr


def test_run_check_reports_skip(tmp_path):
    out, err = _run(tmp_path, "echo 'SKIP  x: tool missing'\nexit 0\n")
    assert "SKIP " in out, out + err
    assert "    SKIP  x: tool missing" in out, out
    assert "PASS" not in out, out
    assert "FAILED=0" in out, out


def test_indented_skip_line_is_not_a_whole_check_skip(tmp_path):
    out, _ = _run(tmp_path, "echo 'checked 3 files'\necho '  SKIP one item'\nexit 0\n")
    assert "PASS " in out, out
    assert "SKIP" not in out, out


def test_pass_still_surfaces_note_lines(tmp_path):
    out, _ = _run(tmp_path, "echo 'NOTE  did not check y'\nexit 0\n")
    assert "PASS " in out, out
    assert "    NOTE  did not check y" in out, out


def test_summary_names_skipped_checks(tmp_path):
    # check_0 skips, check_1 passes, check_2 skips: both skips are counted and named.
    body = 'case "$1" in *check_1.py) exit 0;; esac\necho "SKIP  tool missing"\nexit 0\n'
    out, _ = _run(tmp_path, body, labels=("module health", "secrets", "py redefinitions"))
    assert "All checks passed (2 skipped: module health, py redefinitions)." in out, out
    assert "FAILED=0" in out, out


def test_summary_unchanged_when_nothing_skipped(tmp_path):
    out, _ = _run(tmp_path, "exit 0\n")
    assert out.rstrip().endswith("All checks passed."), out
    assert "skipped" not in out, out


def test_hook_closes_with_the_summary_function():
    # The bare string must not come back: the closing line is _summary_line's to print.
    text = PRE_COMMIT.read_text()
    assert re.search(r"^_summary_line$", text, re.M), "hook no longer calls _summary_line"
    assert text.count('echo "All checks passed."') == 1, "a second unqualified pass line"
