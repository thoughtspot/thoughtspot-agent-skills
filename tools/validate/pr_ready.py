#!/usr/bin/env python3
"""pr_ready.py — the local run behind `scripts/pr-ready.sh`: everything CI's `suite`
job checks on a pull request, against upstream main, with an evidence block.

Before this, "validators pass locally" in a PR meant whatever subset the author
remembered to run, against whatever `origin/main` happened to be — in a fork, the
fork's. CI then found the rest, one round trip at a time. This runs the same set
CI runs, the way CI runs it, and writes down what it ran:

1. **Upstream by URL, fetched every run.** `run_checks.resolve_upstream` finds
   the remote whose URL is the canonical repo (adding `upstream` in a fork clone);
   its `main` is fetched unconditionally, because a stale `<upstream>/main` left
   from an earlier fetch would make "behind" read 0 and every base-relative check
   compare against old code.
2. **Behind is not ready.** `git rev-list --count HEAD..<upstream>/main` > 0 exits
   1 even when every check passes: the branch was checked against code it will
   not merge onto.
3. **The CI-superset, checked rather than claimed**:
   - the check list (`checks.CHECKS`) with `--context local --base <upstream>/main`
     — a required check that SKIPs is FAIL here, an opt-in one without its
     prerequisite is NOT RUN (run_checks owns those rules);
   - CI's PR-only steps (`PR_CHECKS`) against `<upstream>/main`, and the two
     every-PR steps outside the check list (`EVERY_PR_CHECKS`);
   - the scoped quality-gates hard gate, triggered by the same path pattern CI's
     step greps for (`QUALITY_GATES_SOURCES`);
   - CI's credential-free smoke suites (`checks.CI_SMOKES`);
   - the pytest invocations, **read from the workflow's own step** each run
     (`pytest_invocations`), never a hand copy; a line in that step that is not a
     plain `pytest ...` call stops the run rather than being skipped.
   `tests/test_pr_ready.py` fails if CI's `suite` job runs a validator this does
   not, or with different args, or if the quality-gates pattern drifts.
4. **pip-audit** runs when installed, as WARN: it audits this interpreter's
   environment, not the fresh install CI audits, so a hit here may be in a package
   the PR cannot affect and a pass here does not prove CI's.
5. **Evidence** goes to `<git-dir>/pr-ready/evidence.md` (see evidence.py),
   stating what CI does that this run did not reproduce.

`--post N` comments the evidence on PR N with `gh`, and only when the run would
exit 0, after the path is printed. Nothing else is ever sent to GitHub.

The adversarial review is not run here — a script cannot dispatch an agent. The
`pr-ready` skill runs this with `--no-review`, then the reviewer, and appends the
findings to the evidence file. Without `--no-review` this prints a reminder.

PYTHONPATH is pinned to this checkout's `tools/ts-cli` for every subprocess, as
pre-commit does for pytest: in a worktree an editable install of ts_cli points
back at the original clone, so tests and validators would otherwise import
someone else's code.

Exit: 0 ready; 1 a hard FAIL, behind upstream, or a failed `--post`; 2 the run
could not start (no upstream, fetch failed, the workflow could not be read).

Must import and run on Python 3.9 (the system interpreter).
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evidence  # noqa: E402
import run_checks as rc  # noqa: E402
from checks import Check  # noqa: E402

REPO_ROOT = rc.REPO_ROOT
WORKFLOW = Path(".github/workflows/validate.yml")
SUITE_JOB = "suite"
MATRIX_JOB = "pytest-matrix"
PYTEST_STEP = "Run unit + validator tests"
QUALITY_GATES_STEP = "Quality gates catalog gate (PR only, scoped hard-fail)"
#: CI's `grep -qE` pattern in QUALITY_GATES_STEP (pinned to it by a test).
QUALITY_GATES_SOURCES = r"^(scripts/pre-commit\.sh|\.github/workflows/validate\.yml|tools/validate/.*\.py)$"
#: How the workflow spells the PR base in the steps below; `{base}` locally.
_CI_PR_BASE = "origin/${{ github.base_ref }}"

Result = rc.Result


def _gate(id: str, script: str, *local_args: str, hard: bool = True) -> Check:
    return Check(id=id, script=script,
                 ci_args=tuple(a.replace("{base}", _CI_PR_BASE) for a in local_args),
                 local_args=tuple(local_args), hard=hard)


# CI's PR-only steps, in workflow order (args as in validate.yml, base as {base}).
PR_CHECKS: Tuple[Check, ...] = (
    _gate("open-items-pr", "check_open_items.py", "--root", ".", "--base", "{base}"),
    _gate("changelog-pr", "suggest_repo_changelog.py", "--root", ".", "--check", "--base", "{base}"),
    _gate("dependency-types-pr", "suggest_dependency_types.py",
          "--root", ".", "--check", "--base", "{base}"),
    _gate("customer-references-pr", "check_customer_references.py",
          "--root", ".", "--range", "{base}..HEAD"),
    # Warn-only in CI: `--warn` exits 0 even over the threshold, so the LARGE PR
    # line is what makes it WARN here (see _WARN_LINES).
    _gate("pr-size", "check_pr_size.py", "--root", ".", "--base", "{base}", "--warn", hard=False),
)
# Hard steps CI runs on every PR, outside the check list.
EVERY_PR_CHECKS: Tuple[Check, ...] = (
    _gate("ci-gate-coverage", "check_ci_gate_coverage.py", "--root", "."),
    _gate("audit-workflow-permissions", "check_audit_workflow_permissions.py", "--root", "."),
)
QUALITY_GATES_PR = _gate("quality-gates-pr", "generate_quality_gates.py", "--root", ".", "--check")
#: A check that exits 0 but prints a line starting with this is WARN, not PASS.
_WARN_LINES = {"pr-size": "LARGE PR:"}


# ----------------------------------------------------------------- workflow ---

def _workflow(repo_root: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is needed to read the CI workflow "
                           "(pip install pyyaml, as CI does)") from exc
    path = repo_root / WORKFLOW
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"cannot read {WORKFLOW}: {exc}") from exc


def pytest_invocations(repo_root: Path) -> List[List[str]]:
    """The args of each `pytest ...` line in the suite job's pytest step, in order.

    Every code line in that step must be a plain `pytest` call: anything else is
    something CI runs that this would silently not, so it raises instead.
    """
    steps = (_workflow(repo_root).get("jobs", {}).get(SUITE_JOB, {}) or {}).get("steps", [])
    found = [s for s in steps if s.get("name") == PYTEST_STEP]
    if len(found) != 1:
        raise RuntimeError(f"expected one step {PYTEST_STEP!r} in job {SUITE_JOB!r} "
                           f"of {WORKFLOW}, found {len(found)}")
    invocations = []
    for raw in str(found[0].get("run", "")).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("pytest ") or line.endswith("\\"):
            raise RuntimeError(f"{PYTEST_STEP!r} has a line pr-ready cannot reproduce: {line!r}")
        invocations.append(shlex.split(line)[1:])
    if not invocations:
        raise RuntimeError(f"{PYTEST_STEP!r} in {WORKFLOW} has no pytest line")
    return invocations


def _matrix_versions(repo_root: Path) -> List[str]:
    try:
        job = _workflow(repo_root)["jobs"][MATRIX_JOB]
        return [str(v) for v in job["strategy"]["matrix"]["python-version"]]
    except (RuntimeError, KeyError, TypeError):
        return []


# ---------------------------------------------------------------- execution ---

def _run_command(argv: Sequence[str], repo_root: Path) -> Tuple[int, str, float]:
    """Run a non-validator command (pytest, pip-audit): (exit code, output, seconds)."""
    started = time.monotonic()
    proc = subprocess.run(list(argv), cwd=repo_root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or ""), \
        round(time.monotonic() - started, 2)


def _run_gate(check: Check, base: str, repo_root: Path, python: str,
              report: rc.Reporter) -> Result:
    # run_checks' own single-check path, so SKIP/WARN/promotion rules are its rules.
    result, output = rc._run_one(check, "local", base, repo_root, python)
    marker = _WARN_LINES.get(check.id)
    if marker and result["status"] == "PASS" \
            and any(line.startswith(marker) for line in output.splitlines()):
        result["status"] = "WARN"
    report(result, output)
    return result


def _quality_gates_gate(base: str, repo_root: Path, python: str,
                        report: rc.Reporter) -> Result:
    """CI's scoped hard gate: run only when the branch touches a catalog source."""
    diff = rc._git(repo_root, "diff", "--name-only", f"{base}...HEAD")
    if diff.returncode != 0:
        result = {"id": QUALITY_GATES_PR.id, "status": "FAIL", "seconds": 0.0,
                  "output_tail": f"git diff {base}...HEAD failed: {diff.stderr.strip()}"}
        report(result, str(result["output_tail"]))
        return result
    if any(re.match(QUALITY_GATES_SOURCES, f) for f in diff.stdout.splitlines()):
        return _run_gate(QUALITY_GATES_PR, base, repo_root, python, report)
    result = {"id": QUALITY_GATES_PR.id, "status": "NOT RUN", "seconds": 0.0,
              "output_tail": "", "reason": "the branch changes no quality-gates source of "
                                           "truth (CI skips this gate too)"}
    print(f"NOT RUN {QUALITY_GATES_PR.id} ({result['reason']})", flush=True)
    return result


def _pip_audit_installed(python: str, repo_root: Path) -> bool:
    return _run_command([python, "-c", "import pip_audit"], repo_root)[0] == 0


def _pip_audit(python: str, repo_root: Path, report: rc.Reporter) -> Result:
    code, output, seconds = _run_command([python, "-m", "pip_audit"], repo_root)
    result = {"id": "pip-audit", "status": "PASS" if code == 0 else "WARN",
              "seconds": seconds, "output_tail": rc._tail(output)}
    report(result, output)
    return result


def run_pytest(repo_root: Path, python: str, report: rc.Reporter) -> List[Result]:
    results = []
    for args in pytest_invocations(repo_root):
        code, output, seconds = _run_command([python, "-m", "pytest", *args], repo_root)
        # Exit code only: a failing run's summary still contains "passed".
        result = {"id": "pytest " + " ".join(args), "status": "PASS" if code == 0 else "FAIL",
                  "seconds": seconds, "output_tail": rc._tail(output)}
        results.append(result)
        report(result, output)
    return results


def _denylist_state() -> str:
    try:
        import check_customer_references as ccr
        return "configured on this machine" if ccr.denylist_path().is_file() \
            else "not configured on this machine"
    except Exception:  # noqa: BLE001 — a note in the evidence must not stop the run
        return "state unknown"


def not_reproduced(repo_root: Path, base_ref: str, dirty: bool,
                   pip_audit_installed: bool) -> List[str]:
    versions = _matrix_versions(repo_root)
    matrix = f"Python {', '.join(versions)}" if versions else "versions not read from the workflow"
    items = [
        f"CI's pytest matrix ({matrix}): the pytest invocations ran once here, on "
        f"Python {platform.python_version()}.",
        "CI's fresh dependency install (`pip install -e tools/ts-cli[snowflake,qlik,xlsx]`): "
        "here the checks ran with this interpreter's packages, this checkout's "
        "`tools/ts-cli` first on PYTHONPATH.",
    ]
    if pip_audit_installed:
        items.append("pip-audit: audited this interpreter's environment (WARN, never "
                     "blocking), not the install CI audits; CI's run is hard.")
    else:
        items.append("pip-audit: not installed for this interpreter, so not run; CI runs it "
                     "as a hard gate.")
    items.append(f"The private customer-name denylist ({_denylist_state()}): the "
                 "customer-references checks read it here when configured; CI never has it.")
    if dirty:
        items.append(f"Uncommitted changes: the PR-scoped checks diff `{base_ref}...HEAD`, "
                     "commits only, as CI does; the whole-tree checks also saw the "
                     "uncommitted changes.")
    return items


def _gh_comment(number: int, path: Path) -> int:
    try:
        return subprocess.run(["gh", "pr", "comment", str(number), "--body-file", str(path)]
                              ).returncode
    except FileNotFoundError:
        print("pr-ready: gh is not installed; cannot --post", file=sys.stderr)
        return 127


# ----------------------------------------------------------------------- CLI ---

def _pr_number(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("PR number must be positive")
    return value


def _git_out(repo_root: Path, *args: str) -> str:
    proc = rc._git(repo_root, *args)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _pin_pythonpath(repo_root: Path) -> None:
    ts_cli = str(repo_root / "tools" / "ts-cli")
    current = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = f"{ts_cli}{os.pathsep}{current}" if current else ts_cli


def main(argv: Optional[Sequence[str]] = None, *, repo_root: Path = REPO_ROOT,
         python: Optional[str] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/pr-ready.sh",
        description="Run CI's pull-request checks locally against upstream main and "
                    "write an evidence block.")
    parser.add_argument("--no-review", action="store_true",
                        help="do not print the reminder that the review is the pr-ready "
                             "skill's job (the skill passes this)")
    parser.add_argument("--post", type=_pr_number, metavar="PR_NUMBER",
                        help="comment the evidence on this PR with gh, only if the run is green")
    args = parser.parse_args(argv)
    python = python or sys.executable or "python3"

    try:
        remote = rc.resolve_upstream(repo_root)
        base_ref = f"{remote}/main"
        print(f"pr-ready: fetching {remote} main", flush=True)
        _git_out(repo_root, "fetch", "--quiet", "--no-tags", remote,
                 f"+refs/heads/main:refs/remotes/{remote}/main")
        base_sha = _git_out(repo_root, "rev-parse", base_ref)
        head_sha = _git_out(repo_root, "rev-parse", "HEAD")
        dirty = bool(_git_out(repo_root, "status", "--porcelain"))
        behind = int(_git_out(repo_root, "rev-list", "--count", f"HEAD..{base_ref}"))
        pytest_invocations(repo_root)   # fail before running anything, not after
    except (RuntimeError, ValueError) as exc:
        print(f"pr-ready: {exc}", file=sys.stderr)
        return 2

    print(f"pr-ready: base is {base_ref} ({base_sha}); head {head_sha}"
          + (" with uncommitted changes (DIRTY)" if dirty else ""), flush=True)
    if behind:
        print(f"pr-ready: the branch is {behind} commit(s) behind {base_ref} — it will not "
              "be ready until it is current; checks run anyway", flush=True)
    _pin_pythonpath(repo_root)
    report = rc._reporter(False)

    checks = rc.run("local", base_ref, repo_root, python, report=report)
    for check in PR_CHECKS + EVERY_PR_CHECKS:
        checks.append(_run_gate(check, base_ref, repo_root, python, report))
    checks.append(_quality_gates_gate(base_ref, repo_root, python, report))
    audit_installed = _pip_audit_installed(python, repo_root)
    if audit_installed:
        checks.append(_pip_audit(python, repo_root, report))
    smokes = rc.run_smokes(repo_root, python, report=report)
    pytests = run_pytest(repo_root, python, report)

    text = evidence.render(base_ref=base_ref, base_sha=base_sha, head_sha=head_sha,
                           dirty=dirty, behind=behind, checks=checks, smokes=smokes,
                           pytest=pytests,
                           not_reproduced=not_reproduced(repo_root, base_ref, dirty,
                                                         audit_installed),
                           review=None)
    path = evidence.write(text, repo_root)

    failed = [str(r["id"]) for r in checks + smokes + pytests if r["status"] == "FAIL"]
    code = 1 if failed or behind else 0
    if failed:
        print(f"pr-ready: NOT READY — FAIL: {', '.join(failed)}", flush=True)
    if behind:
        print(f"pr-ready: NOT READY — {behind} commit(s) behind {base_ref}", flush=True)
    if not code:
        print("pr-ready: READY" + (" (DIRTY: commit, then re-run for evidence that "
                                   "matches the head SHA)" if dirty else ""), flush=True)
    print(f"pr-ready: evidence written to {path}", flush=True)

    if args.post is not None:
        if code:
            print(f"pr-ready: not posting to PR #{args.post}: the run is not green",
                  file=sys.stderr)
        elif _gh_comment(args.post, path) != 0:
            print(f"pr-ready: posting to PR #{args.post} failed", file=sys.stderr)
            code = 1
        else:
            print(f"pr-ready: posted the evidence to PR #{args.post}", flush=True)
    if not args.no_review:
        print("pr-ready: the adversarial review is not run by this script; the pr-ready "
              "skill runs it and appends it to the evidence", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
