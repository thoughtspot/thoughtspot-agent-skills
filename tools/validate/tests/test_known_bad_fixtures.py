"""Known-bad fixtures: each high-value checker must exit non-zero on a file that
violates exactly the rule it owns (audit F8). A checker that silently stops detecting
its rule (it happened once — see CHANGELOG 2026-06-11) turns these from PASS to FAIL."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

VALIDATE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = VALIDATE.parents[1]


def _run(args, env=None):
    # sys.executable, NOT bare "python3": the validators must run under the same
    # interpreter as this test session. In CI, bare "python3" resolves to the
    # runner's system Python (no click/typer), which made the flag-cross-check
    # validator SKIP (exit 0) and this suite's non-zero assertion fail.
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, env=env)


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


def test_check_no_inline_requests_flags_bad_fixture(tmp_path):
    # check_no_inline_requests scans agents/cli/**/*.md and agents/claude/**/*.md.
    skill_dir = tmp_path / "agents" / "cli" / "ts-bad"
    skill_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "bad_inline_requests.md", skill_dir / "SKILL.md")
    res = _run([str(VALIDATE / "check_no_inline_requests.py"), "--root", str(tmp_path)])
    assert res.returncode != 0, res.stdout + res.stderr


def test_check_pagination_convention_flags_bad_fixture(tmp_path):
    # check_pagination_convention scans tools/ts-cli/ts_cli/**/*.py.
    commands_dir = tmp_path / "tools" / "ts-cli" / "ts_cli" / "commands"
    commands_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "bad_pagination.py", commands_dir / "widgets.py")
    res = _run([str(VALIDATE / "check_pagination_convention.py"), "--root", str(tmp_path)])
    assert res.returncode != 0, res.stdout + res.stderr


def test_check_slash_command_refs_flags_bad_reference():
    # check_slash_command_refs depends on `git ls-files` to know which SKILL.md
    # files exist, so a synthetic (non-git) tmp_path can't exercise it end to end —
    # run it against the real repo instead (same approach test_smoke_alias_sync.py
    # uses for check_smoke_tests, another git-tracking-dependent checker), with the
    # ALLOWLIST cleared so a known-planned phantom (ts-object-model-builder, audit
    # finding 1.1) is exercised as a genuine failure.
    import sys
    import check_slash_command_refs as scr

    repo_root = VALIDATE.parents[1]
    original_allowlist = dict(scr.ALLOWLIST)
    scr.ALLOWLIST = {}
    old_argv = sys.argv
    try:
        sys.argv = ["check_slash_command_refs.py", "--root", str(repo_root)]
        rc = scr.main()
    finally:
        scr.ALLOWLIST = original_allowlist
        sys.argv = old_argv
    assert rc != 0


def test_check_skill_naming_flags_bad_name(tmp_path):
    fixture = FIXTURES / "bad_skill_naming"
    shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)
    res = _run([str(VALIDATE / "check_skill_naming.py"), "--root", str(tmp_path)])
    assert res.returncode != 0, res.stdout + res.stderr
    assert "ts-wrong-family-name" in res.stdout, res.stdout


def test_check_runtime_coverage_flags_missing_mirror(tmp_path):
    fixture = FIXTURES / "bad_runtime_coverage"
    shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)
    res = _run([str(VALIDATE / "check_runtime_coverage.py"), "--root", str(tmp_path)])
    assert res.returncode != 0, res.stdout + res.stderr
    assert "ts-fake-skill" in res.stdout, res.stdout


def test_check_skill_versions_flags_missing_changelog(tmp_path):
    fixture = FIXTURES / "bad_skill_versions"
    shutil.copytree(fixture, tmp_path, dirs_exist_ok=True)
    res = _run([str(VALIDATE / "check_skill_versions.py"), "--root", str(tmp_path)])
    assert res.returncode != 0, res.stdout + res.stderr


def test_check_skill_flag_usage_flags_bad_fixture(tmp_path, capsys):
    # In-process, NOT a subprocess: the validator needs typer/click/ts_cli importable,
    # which is guaranteed for THIS interpreter (the ts-cli suite imports them in the
    # same session) but proved unreliable for a spawned interpreter on CI runners —
    # there the import failed, the validator soft-SKIPped (exit 0), and this test's
    # non-zero assertion failed for an environmental reason, not the rule under test.
    # --root stays the synthetic fixture tree so the SKILL.md scan is isolated while
    # the command introspection runs against the real ts_cli on sys.path.
    import sys
    import check_skill_flag_usage as cfu

    skill_dir = tmp_path / "agents" / "cli" / "ts-bad"
    skill_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "bad_skill_flag_usage.md", skill_dir / "SKILL.md")

    real_ts_cli = str(REPO_ROOT / "tools" / "ts-cli")
    if real_ts_cli not in sys.path:
        sys.path.insert(0, real_ts_cli)
    old_argv = sys.argv
    try:
        sys.argv = ["check_skill_flag_usage.py", "--root", str(tmp_path)]
        rc = cfu.main()
    finally:
        sys.argv = old_argv
    out = capsys.readouterr().out
    assert "SKIP" not in out, out  # import must succeed in-process — SKIP would mask the rule
    assert rc != 0, out
