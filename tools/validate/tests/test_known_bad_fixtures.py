"""Known-bad fixtures: each high-value checker must exit non-zero on a file that
violates exactly the rule it owns (audit F8). A checker that silently stops detecting
its rule (it happened once — see CHANGELOG 2026-06-11) turns these from PASS to FAIL."""
import shutil
import subprocess
from pathlib import Path

VALIDATE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run(args):
    return subprocess.run(["python3", *args], capture_output=True, text=True)


def test_check_tml_flags_bad_tml():
    res = _run([str(VALIDATE / "check_tml.py"), "--from-md",
                str(FIXTURES / "bad_tml.md")])
    assert res.returncode != 0, res.stdout + res.stderr


def test_check_patterns_flags_bad_pattern(tmp_path):
    # check_patterns skips any path containing 'validate'; copy the fixture into a
    # clean tmp root so the full-repo scan actually inspects it.
    shutil.copy(FIXTURES / "bad_pattern.md", tmp_path / "bad_pattern.md")
    res = _run([str(VALIDATE / "check_patterns.py"), "--root", str(tmp_path)])
    assert res.returncode != 0, res.stdout + res.stderr


def test_check_references_flags_bad_reference(tmp_path):
    # check_references scans agents/<runtime>/<skill>/SKILL.md — build that layout.
    skill_dir = tmp_path / "agents" / "cli" / "ts-bad"
    skill_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "bad_reference.md", skill_dir / "SKILL.md")
    res = _run([str(VALIDATE / "check_references.py"), "--root", str(tmp_path)])
    assert res.returncode != 0, res.stdout + res.stderr
