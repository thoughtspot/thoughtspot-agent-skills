#!/usr/bin/env python3
"""pr_ready.py — the local run behind `scripts/pr-ready.sh`: everything CI's
`validate` workflow checks on a pull request, against upstream main, with an
evidence block.

Before this, "validators pass locally" in a PR meant whatever subset the author
remembered to run, against whatever `origin/main` happened to be — in a fork, the
fork's. CI then found the rest, one round trip at a time. This runs the same set
CI runs, the way CI runs it, and writes down what it ran:

1. **Upstream by URL, fetched every run, named in full.** `run_checks.resolve_upstream`
   finds the remote whose URL is the canonical repo (adding `upstream` in a fork
   clone); its `main` is fetched unconditionally, because a stale ref left from an
   earlier fetch would make "behind" read 0 and every base-relative check compare
   against old code. The base is passed everywhere as `refs/remotes/<remote>/main`:
   the short `<remote>/main` loses to a local branch or tag of that name, which git
   resolves first.
2. **Behind is not ready.** `git rev-list --count HEAD..<base>` > 0 exits 1 even
   when every check passes: the branch was checked against code it will not merge
   onto.
3. **The CI-superset, checked rather than claimed**:
   - the check list (`checks.CHECKS`) with `--context local` — a required check
     that SKIPs is FAIL here, an opt-in one without its prerequisite is NOT RUN
     (run_checks owns those rules);
   - CI's PR-only steps (`PR_CHECKS`) against the base, and the two every-PR steps
     outside the check list (`EVERY_PR_CHECKS`);
   - the scoped quality-gates hard gate, triggered by the same path pattern CI's
     step greps for (`QUALITY_GATES_SOURCES`);
   - CI's credential-free smoke suites (`checks.CI_SMOKES`);
   - the pytest invocations, **read from the workflow's own step** each run
     (`pytest_invocations`), never a hand copy, with `-rs` added so every skipped
     test is reported with its reason. A skip for a module that cannot be imported
     is a missing tool, so FAIL (CI installs it); other skips are listed.
   Every code line of every job in the workflow is then classified
   (`ci_lines_not_reproduced`): run here, known plumbing (checkout, installs,
   fetches, the aggregate gate's result checks), or recorded in "Not reproduced
   locally" (pip-audit). Anything else — a new job, a new step, a `python` instead
   of `python3` — is a FAIL row (`ci-superset`), so the claim cannot go stale
   silently; `tests/test_pr_ready.py` runs the same classifier on the committed
   workflow.
4. **pip-audit** runs when installed, as WARN: it audits this interpreter's
   environment, not the fresh install CI audits, so a hit here may be in a package
   the PR cannot affect and a pass here does not prove CI's.
5. **Evidence** goes to `<git-dir>/pr-ready/evidence.md` (see evidence.py),
   stating what CI does that this run did not reproduce.

`--post N` comments the evidence on PR N of the canonical repo (`--repo`, never
gh's default repo, which in a fork is the fork), and only when the run would exit
0, the tree is clean, and PR N's head is the head SHA the evidence describes. It
posts after the path is printed. Nothing else is ever sent to GitHub.

The adversarial review is not run here — a script cannot dispatch an agent. The
`pr-ready` skill runs this with `--no-review`, then the reviewer, and appends the
findings to the evidence file. Without `--no-review` this prints a reminder.

PYTHONPATH is pinned to this checkout's `tools/ts-cli` for every subprocess, as
pre-commit does for pytest: in a worktree an editable install of ts_cli points
back at the original clone, so tests and validators would otherwise import
someone else's code.

Exit: 0 ready; 1 a hard FAIL, behind upstream, or a refused/failed `--post`; 2 the
run could not start (no upstream, fetch failed, the workflow could not be read).

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
#: Every job the workflow may have. A new one fails the CI-superset classification.
KNOWN_JOBS = ("suite", "pytest-matrix", "validate", "scheduled-audit")
#: A job with exactly this `if:` never runs on a pull request; its lines are not classified.
SCHEDULE_ONLY = "github.event_name == 'schedule'"
PYTEST_STEP = "Run unit + validator tests"
QUALITY_GATES_STEP = "Quality gates catalog gate (PR only, scoped hard-fail)"
#: CI's `grep -qE` pattern in QUALITY_GATES_STEP (pinned to it by a test).
QUALITY_GATES_SOURCES = r"^(scripts/pre-commit\.sh|\.github/workflows/validate\.yml|tools/validate/.*\.py)$"
#: How the workflow spells the PR base in the steps below; `{base}` locally.
_CI_PR_BASE = "origin/${{ github.base_ref }}"
#: The runner calls CI's full-repo and smoke steps make (test_checks_parity pins them).
_RUNNER_CALLS = ("python3 tools/validate/run_checks.py --context ci --base origin/main",
                 "python3 tools/validate/run_checks.py --smokes")
#: pytest reports `SKIPPED [n] path:line: reason` under -rs.
_SKIP_LINE = re.compile(r"^SKIPPED \[(\d+)\] (.+?): (.*)$")
#: Skip reasons that mean a module is missing: a missing tool, so FAIL.
_MISSING_MODULE = ("could not import", "No module named")

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


def _jobs(wf: dict) -> dict:
    return wf.get("jobs") or {}


def _code_lines(run: str) -> List[str]:
    """Non-blank, non-comment lines of a shell body, `\\` continuations joined."""
    out, pending = [], ""
    for raw in str(run).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1].rstrip() + " "
            continue
        out.append(pending + line)
        pending = ""
    if pending:
        out.append(pending.rstrip())
    return out


def pytest_invocations(repo_root: Path) -> List[List[str]]:
    """The args of each `pytest ...` line in the suite job's pytest step, in order.

    Every code line in that step must be a plain `pytest` call: anything else is
    something CI runs that this would silently not, so it raises instead.
    """
    steps = (_jobs(_workflow(repo_root)).get(SUITE_JOB) or {}).get("steps", [])
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


# Shell lines that set up or route a step but check nothing.
_PLUMBING = tuple(re.compile(p) for p in (
    r"set -e",
    r'git fetch --no-tags origin "\$\{\{ github\.base_ref \}\}"',
    r"pip install [^;&|`$<>]+",
    r"else",
    r"fi",
))
_QG_PLUMBING = tuple(re.compile(p) for p in (
    r'CHANGED=\$\(git diff --name-only "origin/\$\{\{ github\.base_ref \}\}"\.\.\.HEAD\)',
    r"if echo \"\$CHANGED\" \| grep -qE '" + re.escape(QUALITY_GATES_SOURCES) + r"'; then",
))
#: An `echo` that only prints: no pipe, chaining, substitution or redirection.
_ECHO = re.compile(r"echo [^|;&`<>]*")
_USES_PLUMBING = ("actions/checkout@", "actions/setup-python@")
_VALIDATOR_CALL = re.compile(r"^python3 (tools/validate/[\w-]+\.py)(.*)$")


def _line_reproduced(job: str, step: dict, line: str, pytest_args: List[List[str]]) -> bool:
    """Whether pr-ready runs `line`, or `line` is plumbing that checks nothing."""
    name = step.get("name", "")
    if any(p.fullmatch(line) for p in _PLUMBING):
        return True
    if _ECHO.fullmatch(line) and "$(" not in line:
        return True
    if job == "validate" and line == "exit 1":
        return True   # the aggregate gate failing on a dependency's result
    if name == QUALITY_GATES_STEP:
        if any(p.fullmatch(line) for p in _QG_PLUMBING):
            return True
        if line == "python3 tools/validate/" + QUALITY_GATES_PR.script + " " + \
                " ".join(QUALITY_GATES_PR.ci_args):
            return True
    if line in _RUNNER_CALLS:
        return True
    if line == "pip-audit":
        return True   # run when installed, and recorded under "Not reproduced locally"
    if name == PYTEST_STEP and line.startswith("pytest "):
        return shlex.split(line)[1:] in pytest_args
    m = _VALIDATOR_CALL.match(line)
    if m:
        script = Path(m.group(1)).name
        args = tuple(a.replace(_CI_PR_BASE, "{base}") for a in shlex.split(m.group(2)))
        return any(c.script == script and c.local_args == args
                   for c in PR_CHECKS + EVERY_PR_CHECKS)
    return False


def ci_lines_not_reproduced(repo_root: Path) -> List[str]:
    """Every workflow line (or job, or action) pr-ready neither runs nor knows is
    plumbing, as `job / step: line`. Empty means the CI-superset claim holds."""
    wf = _workflow(repo_root)
    pytest_args = pytest_invocations(repo_root)
    missing = []
    for job_name, job in _jobs(wf).items():
        job = job or {}
        if job_name not in KNOWN_JOBS:
            missing.append(f"job {job_name!r} (not one pr-ready knows)")
            continue
        if str(job.get("if", "")).strip() == SCHEDULE_ONLY:
            continue
        for step in job.get("steps") or []:
            label = f"{job_name} / {step.get('name') or step.get('uses') or '?'}"
            uses = step.get("uses")
            if uses and not str(uses).startswith(_USES_PLUMBING):
                missing.append(f"{label}: uses {uses}")
            for line in _code_lines(step.get("run", "")):
                if not _line_reproduced(job_name, step, line, pytest_args):
                    missing.append(f"{label}: {line}")
    return missing


def _matrix_versions(wf: dict) -> List[str]:
    try:
        return [str(v) for v in _jobs(wf)[MATRIX_JOB]["strategy"]["matrix"]["python-version"]]
    except (KeyError, TypeError):
        return []


def _suite_setting(wf: dict) -> Tuple[str, str]:
    """(runs-on, setup-python version) of the suite job, "" where not found."""
    job = _jobs(wf).get(SUITE_JOB) or {}
    version = ""
    for step in job.get("steps") or []:
        if str(step.get("uses", "")).startswith("actions/setup-python@"):
            version = str((step.get("with") or {}).get("python-version", ""))
    return str(job.get("runs-on", "")), version


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


def _ci_superset(repo_root: Path, report: rc.Reporter) -> Result:
    missing = ci_lines_not_reproduced(repo_root)
    tail = "\n".join(["FAIL  CI runs these and pr-ready does not:"] + missing) if missing else ""
    result = {"id": "ci-superset", "status": "FAIL" if missing else "PASS", "seconds": 0.0,
              "output_tail": tail}
    report(result, tail)
    return result


def _pip_audit_installed(python: str, repo_root: Path) -> bool:
    return _run_command([python, "-c", "import pip_audit"], repo_root)[0] == 0


def _pip_audit(python: str, repo_root: Path, report: rc.Reporter) -> Result:
    code, output, seconds = _run_command([python, "-m", "pip_audit"], repo_root)
    result = {"id": "pip-audit", "status": "PASS" if code == 0 else "WARN",
              "seconds": seconds, "output_tail": rc._tail(output)}
    report(result, output)
    return result


def _skips(output: str) -> List[str]:
    skips = []
    for line in output.splitlines():
        m = _SKIP_LINE.match(line.strip())
        if m:
            count = int(m.group(1))
            skips.append(f"{m.group(2)}: {m.group(3)}" + (f" (x{count})" if count > 1 else ""))
    return skips


def run_pytest(repo_root: Path, python: str, report: rc.Reporter) -> List[Result]:
    results = []
    for args in pytest_invocations(repo_root):
        # `-rs` only adds the skip report; what runs is CI's invocation.
        code, output, seconds = _run_command([python, "-m", "pytest", *args, "-rs"], repo_root)
        skips = _skips(output)
        missing = [s for s in skips if any(m in s for m in _MISSING_MODULE)]
        # Exit code, not the summary: a failing run's summary still contains "passed".
        status = "PASS" if code == 0 and not missing else "FAIL"
        result = {"id": "pytest " + " ".join(args), "status": status, "seconds": seconds,
                  "output_tail": rc._tail(output, rc._KEEP_PREFIXES + ("SKIPPED",)),
                  "skips": skips, "missing": missing}
        results.append(result)
        if missing and code == 0:
            output = ("FAIL  tests skipped for a missing module (CI installs it):\n"
                      + "\n".join(f"  {s}" for s in missing) + "\n" + output)
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
    try:
        wf = _workflow(repo_root)
    except RuntimeError:
        wf = {}
    versions = _matrix_versions(wf)
    runs_on, suite_python = _suite_setting(wf)
    local_python = platform.python_version()
    matrix = f"Python {', '.join(versions)}" if versions else "versions not read from the workflow"
    items = [
        f"CI's runner OS (`{runs_on or 'unknown'}`): this ran on {platform.system()} "
        f"{platform.release()}.",
        f"CI's pytest matrix ({matrix}): the pytest invocations ran once here, on "
        f"Python {local_python}.",
    ]
    if suite_python and not local_python.startswith(suite_python + "."):
        items.append(f"CI's suite job runs on Python {suite_python}; the checks, smokes and "
                     f"pytest here ran on Python {local_python}.")
    items += [
        "pytest ran as `python -m pytest`, which puts the repo root first on sys.path; CI "
        "runs the bare `pytest` script, which does not, so a test importing a top-level "
        "name can pass here and fail there. `-rs` was added to report skips.",
        "CI's fresh dependency install (`pip install -e tools/ts-cli[snowflake,qlik,xlsx]`): "
        "here the checks ran with this interpreter's packages, this checkout's "
        "`tools/ts-cli` first on PYTHONPATH.",
        "Files git ignores (caches, build output, local data) are visible to the whole-tree "
        "checks here and do not count as uncommitted changes; CI's checkout has none.",
        "Warnings and `::warning` annotations printed by a check that passed are not "
        "carried into this block; CI shows them in its log.",
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


# ------------------------------------------------------------------- --post ---

def _gh(args: Sequence[str]) -> Tuple[int, str, str]:
    """Run gh: (exit code, stdout, stderr). The only door to GitHub."""
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    except FileNotFoundError:
        return 127, "", "gh is not installed"
    return proc.returncode, proc.stdout, proc.stderr


def _post(number: int, path: Path, head_sha: str) -> Optional[str]:
    """Comment the evidence on the canonical repo's PR `number`; None on success,
    else why not. Refuses unless that PR's head is the SHA the evidence describes:
    `--repo` stops a fork's same-numbered PR receiving it, and the head check stops
    a stale block (or a typo'd number) landing on the wrong PR."""
    repo = rc.CANONICAL_REPO
    code, out, err = _gh(["pr", "view", str(number), "--repo", repo,
                          "--json", "headRefOid", "--jq", ".headRefOid"])
    if code != 0:
        return f"could not read PR #{number} on {repo}: {err.strip() or out.strip()}"
    pr_head = out.strip()
    if pr_head != head_sha:
        return (f"PR #{number} on {repo} has head {pr_head or '(none)'}, not {head_sha}, the "
                "head this evidence describes; push the branch (or fix the number) and re-run")
    code, out, err = _gh(["pr", "comment", str(number), "--repo", repo,
                          "--body-file", str(path)])
    if code != 0:
        return f"gh pr comment failed: {err.strip() or out.strip()}"
    return None


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
                        help="comment the evidence on this PR of the canonical repo with gh, "
                             "only if the run is green, the tree is clean and the PR's head "
                             "is this head")
    args = parser.parse_args(argv)
    python = python or sys.executable or "python3"

    try:
        remote = rc.resolve_upstream(repo_root)
        # In full: a local branch or tag named `<remote>/main` shadows the short name.
        base_ref = f"refs/remotes/{remote}/main"
        print(f"pr-ready: fetching {remote} main", flush=True)
        _git_out(repo_root, "fetch", "--quiet", "--no-tags", remote,
                 f"+refs/heads/main:{base_ref}")
        base_sha = _git_out(repo_root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
        head_sha = _git_out(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
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

    checks = [_ci_superset(repo_root, report)]
    checks += rc.run("local", base_ref, repo_root, python, report=report)
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
        refusal = None
        if code:
            refusal = "the run is not green"
        elif dirty:
            refusal = "the tree is dirty, so the head SHA does not describe what was checked"
        else:
            refusal = _post(args.post, path, head_sha)
        if refusal:
            print(f"pr-ready: not posting to PR #{args.post}: {refusal}", file=sys.stderr)
            code = 1
        else:
            print(f"pr-ready: posted the evidence to PR #{args.post} on {rc.CANONICAL_REPO}",
                  flush=True)
    if not args.no_review:
        print("pr-ready: the adversarial review is not run by this script; the pr-ready "
              "skill runs it and appends it to the evidence", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
