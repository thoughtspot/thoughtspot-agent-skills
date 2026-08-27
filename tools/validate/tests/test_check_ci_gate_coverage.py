"""Tests for check_ci_gate_coverage — the audit-finding-7.1 gate.

The bug this encodes is worth restating, because the validator's value is
entirely in catching its recurrence. Branch protection requires ONE context,
`validate`. When that context was the job that ran the work, a second job
(`pytest-matrix`, four Python versions) reported failures that could not block a
merge. Making `validate` an aggregate over `needs:` fixed it — and created a new
invariant that nothing but this file enforces, since no other tool in the repo
reads job names at all.

`test_real_workflow_passes` is the one that would have caught the original bug:
it runs against the committed workflow, so if anyone adds an ungated job the
suite goes red rather than the catalog going quietly green.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[1] / "check_ci_gate_coverage.py"
REPO_ROOT = Path(__file__).resolve().parents[3]


def _repo(tmp_path, workflow: str):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "validate.yml").write_text(textwrap.dedent(workflow), encoding="utf-8")
    return tmp_path


def _run(root):
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(root)],
        capture_output=True, text=True,
    )


GOOD = """
    name: validate
    on: [pull_request]
    jobs:
      suite:
        if: github.event_name != 'schedule'
        runs-on: ubuntu-latest
        steps: [{run: echo hi}]
      pytest-matrix:
        if: github.event_name != 'schedule'
        runs-on: ubuntu-latest
        steps: [{run: echo hi}]
      validate:
        if: always() && github.event_name != 'schedule'
        needs: [suite, pytest-matrix]
        runs-on: ubuntu-latest
        steps: [{run: echo hi}]
      scheduled-audit:
        if: github.event_name == 'schedule'
        runs-on: ubuntu-latest
        steps: [{run: echo hi}]
"""


def test_well_formed_gate_passes(tmp_path):
    r = _run(_repo(tmp_path, GOOD))
    assert r.returncode == 0, r.stderr


def test_ungated_job_is_caught(tmp_path):
    """The finding-7.1 shape: a job that runs on PRs but is not in `needs:`."""
    wf = GOOD.replace("    needs: [suite, pytest-matrix]", "    needs: [suite]")
    r = _run(_repo(tmp_path, wf))
    assert r.returncode == 1
    assert "pytest-matrix" in r.stderr
    assert "cannot block a merge" in r.stderr


def test_new_job_added_without_gating_is_caught(tmp_path):
    """The recurrence path the prose rule could not enforce."""
    wf = GOOD + "      lint:\n        runs-on: ubuntu-latest\n        steps: [{run: echo hi}]\n"
    r = _run(_repo(tmp_path, wf))
    assert r.returncode == 1
    assert "`lint`" in r.stderr


def test_schedule_only_job_is_exempt(tmp_path):
    """`scheduled-audit` must NOT be required — gating it would make the gate skip."""
    r = _run(_repo(tmp_path, GOOD))
    assert r.returncode == 0
    assert "scheduled-audit" not in r.stderr


def test_missing_gate_job_is_caught(tmp_path):
    """Rename the gate and the required context never reports — PRs hang, not fail."""
    wf = GOOD.replace("      validate:", "      gate:")
    r = _run(_repo(tmp_path, wf))
    assert r.returncode == 1
    assert "never reports" in r.stderr


def test_always_removed_is_caught(tmp_path):
    """Without always(), a FAILED dependency skips the gate and the skip counts as pass."""
    wf = GOOD.replace("    if: always() && github.event_name != 'schedule'",
                      "    if: github.event_name != 'schedule'")
    r = _run(_repo(tmp_path, wf))
    assert r.returncode == 1
    assert "always()" in r.stderr


def test_not_cancelled_is_not_accepted_as_a_substitute(tmp_path):
    """GitHub's docs prefer !cancelled() generically; here it opens the hole.

    Written in the `${{ }}` form because a BARE `!cancelled()` is not valid YAML —
    `!` opens a tag. That is a real trap for anyone hand-editing the workflow, and
    the reason the fixture looks more verbose than the line it models.
    """
    wf = GOOD.replace("    if: always() && github.event_name != 'schedule'",
                      "    if: ${{ !cancelled() && github.event_name != 'schedule' }}")
    r = _run(_repo(tmp_path, wf))
    assert r.returncode == 1


def test_continue_on_error_masking_is_caught(tmp_path):
    """continue-on-error makes needs.<job>.result report success on failure."""
    wf = GOOD.replace(
        "      pytest-matrix:\n        if: github.event_name != 'schedule'",
        "      pytest-matrix:\n        continue-on-error: true\n        if: github.event_name != 'schedule'",
    )
    r = _run(_repo(tmp_path, wf))
    assert r.returncode == 1
    assert "continue-on-error" in r.stderr


def test_needs_a_job_that_does_not_exist(tmp_path):
    wf = GOOD.replace("    needs: [suite, pytest-matrix]", "    needs: [suite, pytest-matrix, ghost]")
    r = _run(_repo(tmp_path, wf))
    assert r.returncode == 1
    assert "ghost" in r.stderr


def test_scalar_needs_is_accepted(tmp_path):
    """`needs: suite` is legal YAML and must not crash the parser."""
    wf = """
    name: validate
    on: [pull_request]
    jobs:
      suite:
        runs-on: ubuntu-latest
        steps: [{run: echo hi}]
      validate:
        if: always()
        needs: suite
        runs-on: ubuntu-latest
        steps: [{run: echo hi}]
    """
    r = _run(_repo(tmp_path, wf))
    assert r.returncode == 0, r.stderr


def test_missing_workflow_exits_2_not_0(tmp_path):
    """A checker that goes green because it could not run is the failure mode."""
    r = _run(tmp_path)
    assert r.returncode == 2


def test_unparseable_yaml_exits_2_not_0(tmp_path):
    r = _run(_repo(tmp_path, "jobs:\n  - [unbalanced\n"))
    assert r.returncode == 2


def test_real_workflow_passes():
    """Against the committed workflow — this is what catches a real new job."""
    r = _run(REPO_ROOT)
    assert r.returncode == 0, r.stderr
