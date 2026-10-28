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
     (`pytest_invocations`), never a hand copy, with `-rs --color=no` added so every
     skipped test is reported with its reason, and PYTEST_ADDOPTS dropped (CI sets
     none). A skip for a module that cannot be imported, or that lacks an attribute
     the test needs (too old), is a missing tool, so FAIL (CI installs it), and the
     run prints CI's suite-job installs (`SUITE_PIP_INSTALLS`) as the remedy; other
     skips are listed. If pytest's own skipped count cannot be read, or does not
     match the reported skips, that is FAIL too: unverifiable is not zero.
   The workflow is then classified (`ci_lines_not_reproduced`): every key of the
   workflow, of each job and of each step must be one the classifier understands
   (no `env`, `defaults`, `shell`, `working-directory`, job-level `uses`, ...); every
   action must be checkout or setup-python; every code line must be run here or be
   known plumbing (the PR-base fetch, CI's exact pip installs, print-only echoes,
   `exit 1` under the aggregate gate's own condition); and the scoped quality-gates
   step must match CI's shape line by line. Anything else — a new job, a new step,
   a `python` instead of `python3` — is a FAIL row (`ci-superset`);
   `tests/test_pr_ready.py` runs the same classifier on the committed workflow.
   **What it does not see:** a step's `if:` condition (pr-ready runs every step
   unconditionally, so a condition can only make CI run less than this), an
   action's `with:` inputs (the suite's Python is read from them for "Not
   reproduced locally", nothing more), and what the validators, scripts and tests
   the lines call actually do.
4. **pip-audit** runs when installed, as WARN: it audits this interpreter's
   environment, not the fresh install CI audits, so a hit here may be in a package
   the PR cannot affect and a pass here does not prove CI's.
5. **Evidence** goes to `<git-dir>/pr-ready/evidence.md` (see evidence.py),
   stating what CI does that this run did not reproduce. The first thing a run
   does, before it even reads its arguments, is replace that file with a NOT READY
   placeholder, so a run that stops early (an argument error included) never
   leaves an earlier READY block looking current; `--help` replaces it too.

`--post N` comments the evidence on PR N of the canonical repo (`--repo`, never
gh's default repo, which in a fork is the fork), and only when the run would exit
0, the tree is clean, PR N's head is the head SHA the evidence describes, and the
block passes the two scans the `pr-ready` skill runs before sharing one
(`check_secrets.py --file` and `check_customer_references.py --text-file`; a `WARN`
line is a hit). It posts after the path is printed. Nothing else is ever sent to
GitHub.

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
#: pytest's closing stats line under -q, e.g. `10 passed, 4 skipped in 1.2s (0:00:01)`.
_STATS_LINE = re.compile(
    r"^=*\s*(?=.*\b(?:passed|failed|skipped|error|errors|xfailed|xpassed|deselected|"
    r"no tests ran)\b).* in [\d.]+s(?: \([\d:.]+\))?\s*=*$")
_STATS_SKIPPED = re.compile(r"\b(\d+) skipped\b")
#: SGR escape sequences: FORCE_COLOR / PY_COLORS colour pytest's output even when piped.
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
#: Skip reasons that mean a Python module is missing or too old for the test (a module
#: lacking an attribute: CI pins a version that has it). A missing tool, so FAIL.
_MISSING_MODULE = re.compile(
    r"could not import|No module named|ModuleNotFoundError|ImportError"
    r"|module '[\w.]+' has no attribute")
#: Environment variables that change what pytest runs or how it reports. CI sets none.
_PYTEST_ENV_DROP = ("PYTEST_ADDOPTS",)

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
#: Where the one-time setup (a virtual environment, CHECKS_PYTHON) is written down.
CONTRIBUTING_GUIDE = ".github/CONTRIBUTING.md"
#: A check that exits 0 but prints a line starting with this is WARN, not PASS.
_WARN_LINES = {"pr-size": "LARGE PR:"}


# ----------------------------------------------------------------- workflow ---

def _workflow(repo_root: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is needed to read the CI workflow "
                           "(pip install pyyaml, as CI does). If this Python refuses "
                           "`pip install`, create a virtual environment, install CI's lines "
                           "into it with `uv pip install --python <venv>/bin/python` (or "
                           "`<venv>/bin/pip install`), and set CHECKS_PYTHON to its python: "
                           f"see {CONTRIBUTING_GUIDE}") from exc
    path = repo_root / WORKFLOW
    try:
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"cannot read {WORKFLOW}: {exc}") from exc
    if not isinstance(wf, dict) or not isinstance(wf.get("jobs"), dict):
        raise RuntimeError(f"{WORKFLOW} has no `jobs:` mapping")
    return wf


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


_PR_FETCH = 'git fetch --no-tags origin "${{ github.base_ref }}"'
#: Shell lines that set up a step but check nothing, anywhere in a run script.
_PLUMBING = frozenset({"set -e", _PR_FETCH})
#: The installs CI's suite job makes, in workflow order (a test pins them to it). The
#: remedy printed when a test is skipped for a missing module, and the prerequisite
#: the pr-ready skill quotes.
SUITE_PIP_INSTALLS: Tuple[str, ...] = (
    "pip install pytest pyyaml radon pip-audit jsonschema==4.25.1",
    "pip install -e tools/ts-cli",
    'pip install -e "tools/ts-cli[snowflake,qlik,xlsx]"',
)
#: The exact installs CI makes today, in any job (deliberate copies: a changed install
#: changes what the checks run with, so it must be looked at, not waved through).
_PIP_INSTALLS = frozenset(SUITE_PIP_INSTALLS + (
    "pip install pytest pyyaml jsonschema==4.25.1",   # the pytest-matrix job's subset
))
#: An `echo` that only prints: no pipe, chaining, substitution or redirection.
_ECHO = re.compile(r"echo [^|;&`<>]*")
_USES_PLUMBING = ("actions/checkout@", "actions/setup-python@")
#: The workflow, job and step keys the classifier understands. Anything else (`env`,
#: `defaults`, `shell`, `working-directory`, `continue-on-error`, a job-level `uses`
#: calling a reusable workflow, ...) can change what a line does, so it is unaccounted.
_WORKFLOW_KEYS = frozenset({"name", "on", True, "jobs"})   # YAML 1.1 reads `on` as True
_JOB_KEYS = frozenset({"if", "runs-on", "needs", "steps", "strategy"})
_STEP_KEYS = frozenset({"name", "uses", "with", "if", "run"})
#: The aggregate `validate` job's failure condition; `exit 1` is plumbing only under it.
_AGGREGATE_IF = ("contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled') "
                 "|| contains(needs.*.result, 'skipped')")


def _is_echo(line: str) -> bool:
    return bool(_ECHO.fullmatch(line)) and "$(" not in line


#: CI's scoped quality-gates step, line by line: the gate is hard ONLY when a source
#: changed. Pinned whole, so moving the gate (into `else`, or out of the `if`) is caught.
_QG_BODY = (
    lambda l: l == _PR_FETCH,
    lambda l: l == 'CHANGED=$(git diff --name-only "origin/${{ github.base_ref }}"...HEAD)',
    lambda l: l == "if echo \"$CHANGED\" | grep -qE '" + QUALITY_GATES_SOURCES + "'; then",
    _is_echo,
    lambda l: l == "python3 tools/validate/" + QUALITY_GATES_PR.script + " "
    + " ".join(QUALITY_GATES_PR.ci_args),
    lambda l: l == "else",
    _is_echo,
    lambda l: l == "fi",
)
_VALIDATOR_CALL = re.compile(r"^python3 (tools/validate/[\w-]+\.py)(.*)$")


def _line_reproduced(job: str, step: dict, line: str, pytest_args: List[List[str]]) -> bool:
    """Whether pr-ready runs `line`, or `line` is plumbing that checks nothing.
    (The quality-gates step is matched whole, by `_qg_step_matches`.)"""
    name = step.get("name", "")
    if line in _PLUMBING or line in _PIP_INSTALLS or _is_echo(line):
        return True
    if job == "validate" and line == "exit 1" and str(step.get("if", "")).strip() == _AGGREGATE_IF:
        return True   # the aggregate gate failing on a dependency's result
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
    missing = [f"workflow key {k!r}" for k in wf if k not in _WORKFLOW_KEYS]
    for job_name, job in _jobs(wf).items():
        job = job if isinstance(job, dict) else {}
        if job_name not in KNOWN_JOBS:
            missing.append(f"job {job_name!r} (not one pr-ready knows)")
            continue
        if str(job.get("if", "")).strip() == SCHEDULE_ONLY:
            continue
        missing += [f"{job_name}: job key {k!r}" for k in job if k not in _JOB_KEYS]
        for step in job.get("steps") or []:
            step = step if isinstance(step, dict) else {}
            label = f"{job_name} / {step.get('name') or step.get('uses') or '?'}"
            missing += [f"{label}: step key {k!r}" for k in step if k not in _STEP_KEYS]
            uses = step.get("uses")
            if uses and not str(uses).startswith(_USES_PLUMBING):
                missing.append(f"{label}: uses {uses}")
            lines = _code_lines(step.get("run", ""))
            if step.get("name") == QUALITY_GATES_STEP:
                if not _qg_step_matches(lines):
                    missing.append(f"{label}: the step is not CI's scoped gate as pr-ready runs "
                                   f"it: {' / '.join(lines)}")
                continue
            for line in lines:
                if not _line_reproduced(job_name, step, line, pytest_args):
                    missing.append(f"{label}: {line}")
    return missing


def _qg_step_matches(lines: List[str]) -> bool:
    return len(lines) == len(_QG_BODY) and all(match(l) for match, l in zip(_QG_BODY, lines))


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

def _run_command(argv: Sequence[str], repo_root: Path,
                 env: Optional[dict] = None) -> Tuple[int, str, float]:
    """Run a non-validator command (pytest, pip-audit): (exit code, output, seconds)."""
    started = time.monotonic()
    proc = subprocess.run(list(argv), cwd=repo_root, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, env=env)
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


def _skips(clean: str) -> List[Tuple[int, str]]:
    """(count, "path:line: reason") for each `SKIPPED [n] ...` line."""
    found = []
    for line in clean.splitlines():
        m = _SKIP_LINE.match(line.strip())
        if m:
            found.append((int(m.group(1)), f"{m.group(2)}: {m.group(3)}"))
    return found


def _skip_problems(clean: str, listed: int) -> List[str]:
    """Why the skip list cannot be trusted, if it cannot. Fail closed: a missing
    stats line, or a skipped count the -rs report does not add up to (colour, a
    `--no-summary`, a reporting plugin), is unverifiable, never zero."""
    stats = [l.strip() for l in clean.splitlines() if _STATS_LINE.match(l.strip())]
    if not stats:
        return ["pytest's closing stats line was not found, so skipped tests cannot be counted"]
    m = _STATS_SKIPPED.search(stats[-1])
    reported = int(m.group(1)) if m else 0
    if reported != listed:
        return [f"pytest reported {reported} skipped but its -rs report lists {listed}, so "
                "skipped tests cannot be verified"]
    return []


def _pytest_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _PYTEST_ENV_DROP}


def _install_remedy(python: str) -> List[str]:
    """What to run so the missing modules are there: CI's suite-job installs, exactly.

    `pip` on PATH can belong to another interpreter than the one pr-ready picked, so
    the note names that one by its command name (its full path can be a home
    directory, which has no place in output that may be pasted)."""
    name = Path(python).name or "python3"
    return ([f"  Install what CI's suite job installs, from the repo root, for the "
             f"interpreter this run used (`{name} -m pip install ...` if `pip` is "
             f"another interpreter's):"]
            + [f"    {line}" for line in SUITE_PIP_INSTALLS]
            + ["  If that Python refuses `pip install` (externally-managed-environment), "
               "create a virtual environment, run the same lines with "
               "`uv pip install --python <venv>/bin/python` (or `<venv>/bin/pip install`) "
               "in place of `pip install`, and set CHECKS_PYTHON to that python: see "
               f"{CONTRIBUTING_GUIDE}."])


def run_pytest(repo_root: Path, python: str, report: rc.Reporter) -> List[Result]:
    results = []
    for args in pytest_invocations(repo_root):
        # `-rs --color=no` only change reporting (every skip, uncoloured even under
        # FORCE_COLOR / PY_COLORS); PYTEST_ADDOPTS is dropped, as CI sets none.
        code, output, seconds = _run_command(
            [python, "-m", "pytest", *args, "-rs", "--color=no"], repo_root, env=_pytest_env())
        clean = _ANSI.sub("", output)
        found = _skips(clean)
        skips = [text + (f" (x{n})" if n > 1 else "") for n, text in found]
        missing = [s for s in skips if _MISSING_MODULE.search(s)]
        problems = _skip_problems(clean, sum(n for n, _ in found))
        # Exit code, not the summary: a failing run's summary still contains "passed".
        status = "PASS" if code == 0 and not missing and not problems else "FAIL"
        result = {"id": "pytest " + " ".join(args), "status": status, "seconds": seconds,
                  "output_tail": rc._tail(clean, rc._KEEP_PREFIXES + ("SKIPPED",)),
                  "skips": skips, "missing": missing, "problems": problems}
        results.append(result)
        notes = [f"FAIL  {p}" for p in problems]
        if missing:
            notes.append("FAIL  tests skipped for a missing module (CI installs it):")
            notes += [f"  {s}" for s in missing]
            notes += _install_remedy(python)
        report(result, "\n".join(notes + [clean]) if notes else clean)
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
        "name can pass here and fail there. `-rs --color=no` was added to report every "
        "skip, and PYTEST_ADDOPTS (if set) was dropped, as CI sets none.",
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

#: The gh executable (a constant so a test can name one that does not exist).
GH = "gh"


def _gh(args: Sequence[str]) -> Tuple[int, str, str]:
    """Run gh: (exit code, stdout, stderr). The only door to GitHub."""
    try:
        proc = subprocess.run([GH, *args], capture_output=True, text=True)
    except FileNotFoundError:
        return 127, "", "gh is not installed"
    return proc.returncode, proc.stdout, proc.stderr


#: The scans the pr-ready skill runs on a block before it is shared (its Step 6), each
#: over every line of the file: (script, its single-file option).
_BLOCK_SCANS = (("check_secrets.py", "--file"), ("check_customer_references.py", "--text-file"))


def _scan_block(path: Path, repo_root: Path, python: str) -> Optional[str]:
    """None when both scanners pass the block; else why it must not be posted.

    A hit is a non-zero exit, or a `WARN` line: the customer-reference scanner reports
    a personal detail that way and still exits 0. A scanner that cannot run refuses
    too, since an unscanned block is not one to publish."""
    for script, option in _BLOCK_SCANS:
        try:
            code, output, _ = rc._execute(python, rc.VALIDATE_DIR / script,
                                          (option, str(path)), repo_root)
        except OSError as exc:
            return f"{script} could not scan the block: {exc}"
        warned = any(line.startswith("WARN") for line in output.splitlines())
        if code != 0 or warned:
            found = f"exit {code}" + (", a WARN line" if warned else "")
            return (f"{script} {option} found something in the block ({found}); fix it at "
                    f"its source and re-run:\n{output.rstrip()}")
    return None


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


def _try_post(number: int, *, exit_code: int, dirty: bool, head_sha: str, path: Path,
              repo_root: Path, python: str) -> Optional[str]:
    """Post the block to PR `number`: None once posted, else why it was not."""
    if exit_code:
        return "the run is not green"
    if dirty:
        return "the tree is dirty, so the head SHA does not describe what was checked"
    # The run takes minutes: a commit or an edit made meanwhile would make the block
    # describe code that is no longer what is there.
    now_head = rc._git(repo_root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    now_dirty = rc._git(repo_root, "status", "--porcelain").stdout.strip()
    if now_head != head_sha or now_dirty:
        return "the head or the work tree changed during the run; re-run on the final state"
    # Scanned last, just before it leaves the machine.
    return _scan_block(path, repo_root, python) or _post(number, path, head_sha)


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
    # Replace any earlier block first, before even the arguments are read: a run that
    # stops early (an argument error, exit 2, a crash, Ctrl-C) must not leave a
    # previous READY block looking current. `--help` replaces it too.
    try:
        evidence.write(evidence.UNFINISHED, repo_root)
    except (RuntimeError, OSError) as exc:
        print(f"pr-ready: cannot replace the evidence file: {exc}", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(
        prog="scripts/pr-ready.sh",
        description="Run CI's pull-request checks locally against upstream main and "
                    "write an evidence block.")
    parser.add_argument("--no-review", action="store_true",
                        help="do not print the reminder that the review is the pr-ready "
                             "skill's job (the skill passes this)")
    parser.add_argument("--post", type=_pr_number, metavar="PR_NUMBER",
                        help="comment the evidence on this PR of the canonical repo with gh, "
                             "only if the run is green, the tree is clean, the PR's head "
                             "is this head and the block passes the secrets and "
                             "customer-reference scans")
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
        refusal = _try_post(args.post, exit_code=code, dirty=dirty, head_sha=head_sha,
                            path=path, repo_root=repo_root, python=python)
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
