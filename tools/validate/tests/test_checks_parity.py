"""Parity tests pinning `checks.py` to the two places that actually run checks.

`checks.CHECKS` is the list of validators CI's full-repo step runs on every PR,
and `checks.CI_SMOKES` the smoke suites its smoke step runs. CI reads both
through `run_checks.py`, so on the workflow side these tests pin the CALL, not a
list of lines: each step's shell body must be exactly the runner call (the
full-repo step may open with `set -e`) — no `|| true`, no `exit 0`, no
`set +e`, no `if false` wrapper, no extra args, no validator beside it — and
nothing around the step (`continue-on-error`, a new `if:`, a custom `shell:`,
`defaults`, the job's own `if:`) may stop it gating while the call stays put.

Pre-commit does not read the list yet, so it is pinned line by line:

- every `run_check "LABEL" "tools/validate/X.py ARGS"` in pre-commit is a `Check`
  carrying that label and those args, or is in `PRECOMMIT_ONLY` with a reason;
- every validator pre-commit runs OUTSIDE run_check is in `PRECOMMIT_UNMANAGED`;
- pre-commit args that differ from CI's are declared in `KNOWN_DRIFT`, so a
  difference is a recorded decision rather than an accident.

Every guard fails loud on a line it cannot parse rather than skipping it: a test
that silently ignores an unrecognised shape is exactly the drift it exists to
catch. There is deliberately no fallback for the old explicit-line workflow
form: a validator listed inline in the workflow again would bypass the list, so
that form now fails here rather than being compared against it.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import yaml

import checks

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"
PRECOMMIT = REPO_ROOT / "scripts" / "pre-commit.sh"
VALIDATE_DIR = REPO_ROOT / "tools" / "validate"

JOB = "suite"
# The suite job's own guard, as it is today: skip only on the weekly cron. A wider
# condition would skip every step below on PRs while each step still looks right.
JOB_GUARD = "github.event_name != 'schedule'"
FULL_REPO_STEP = "Run validators (full-repo mode)"
SMOKE_STEP = "Run credential-free smoke suites"
PYTEST_STEP = "Run unit + validator tests"
RUNNER_CI_CALL = "python3 tools/validate/run_checks.py --context ci --base origin/main"
RUNNER_SMOKES_CALL = "python3 tools/validate/run_checks.py --smokes"
# Each step's whole shell body, comments and blanks aside. `set -e` is harmless
# before a single command and is all the full-repo step may add.
STEP_BODIES = {
    FULL_REPO_STEP: ([RUNNER_CI_CALL], ["set -e", RUNNER_CI_CALL]),
    SMOKE_STEP: ([RUNNER_SMOKES_CALL],),
}
# The only step-level guard each step may carry: what it has today. A new `if:` or
# `continue-on-error` would let the step stop gating without any line changing.
STEP_GUARDS = {FULL_REPO_STEP: None, SMOKE_STEP: "${{ !cancelled() }}"}
# The only keys each step may have. `shell:` (e.g. `bash -c "exit 0" {0}`),
# `env:` or `working-directory:` could each change what the call does.
STEP_KEYS = {FULL_REPO_STEP: {"name", "run"}, SMOKE_STEP: {"name", "if", "run"}}

_RUN_CHECK = re.compile(
    r'\brun_check\s+"(?P<label>[^"]+)"\s+"tools/validate/(?P<script>[^"\s]+\.py)(?P<args>[^"]*)"'
)
_RUN_CHECK_WORD = re.compile(r"\brun_check\b")
_RUN_CHECK_DEF = re.compile(r"^\s*run_check\(\)")
# An unescaped validator path: grep patterns in the hook spell it `check_x\.py`,
# which this deliberately does not match.
_VALIDATOR_PATH = re.compile(r"tools/validate/(?P<script>[\w-]+\.py)")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job() -> dict:
    return _workflow()["jobs"][JOB]


def _step(name: str) -> dict:
    """The step called `name` in the `suite` job."""
    found = [s for s in _job().get("steps", []) if s.get("name") == name]
    assert len(found) == 1, f"expected exactly one step named {name!r} in job {JOB!r}, found {len(found)}"
    return found[0]


def _code_lines(run: str) -> list[str]:
    """Non-blank, non-comment lines of a shell body, stripped."""
    out = []
    for raw in run.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _precommit_code_lines() -> list[str]:
    return [
        line for line in PRECOMMIT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _precommit_run_checks() -> list[tuple[str, str, tuple[str, ...]]]:
    """(label, script, args) for each `run_check` call in pre-commit.sh.

    Every non-comment line mentioning run_check (other than its definition) must
    parse, whatever precedes it (`&&`, `then`, a tab), or the test fails.
    run_check splits its command with `read -r -a`, i.e. on whitespace, so a plain
    `split()` reproduces exactly the argv pre-commit passes.
    """
    parsed = []
    for line in _precommit_code_lines():
        if _RUN_CHECK_DEF.match(line):
            continue
        mentions = len(_RUN_CHECK_WORD.findall(line))
        if not mentions:
            continue
        matches = list(_RUN_CHECK.finditer(line))
        assert len(matches) == mentions, f"pre-commit run_check call not in the expected shape: {line.strip()}"
        for m in matches:
            parsed.append((m.group("label"), m.group("script"), tuple(m.group("args").split())))
    assert parsed, "found no run_check calls in pre-commit.sh — has the hook been restructured?"
    return parsed


def _precommit_unmanaged_scripts() -> list[str]:
    """Validators pre-commit invokes directly rather than through run_check."""
    found = []
    for line in _precommit_code_lines():
        if _RUN_CHECK_DEF.match(line):
            continue
        bare = _RUN_CHECK.sub("", line)
        found.extend(m.group("script") for m in _VALIDATOR_PATH.finditer(bare))
    return found


def _pytest_dirs(args: list[str]) -> set[str]:
    return {a.rstrip("/") for a in args if not a.startswith("-")}


# ── workflow side ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(STEP_GUARDS))
def test_step_cannot_be_neutralised(name):
    step = _step(name)
    assert "continue-on-error" not in step, f"{name!r} has continue-on-error"
    assert step.get("if") == STEP_GUARDS[name], (
        f"{name!r} has `if: {step.get('if')}`; expected {STEP_GUARDS[name]!r}"
    )
    assert set(step) == STEP_KEYS[name], (
        f"{name!r} has keys {sorted(step)}; expected exactly {sorted(STEP_KEYS[name])}"
    )


def test_suite_job_cannot_be_neutralised():
    job = _job()
    assert "continue-on-error" not in job, f"job {JOB!r} has continue-on-error"
    assert job.get("if") == JOB_GUARD, f"job {JOB!r} has `if: {job.get('if')}`; expected {JOB_GUARD!r}"
    # A default `shell:` at either level applies to every `run:` step without
    # appearing on the step itself.
    assert "defaults" not in job, f"job {JOB!r} has `defaults:`"
    assert "defaults" not in _workflow(), "the workflow has top-level `defaults:`"


@pytest.mark.parametrize("name", sorted(STEP_BODIES))
def test_step_body_is_exactly_the_runner_call(name):
    """CI reads the list through the runner, so there is nothing left to compare
    line by line — but only if the call is the step's whole body. Anything beside
    it (`|| true`, `exit 0`, `set +e`, an `if false; then` wrapper, an inline
    validator, `--only`) could keep the call present while the step stops gating
    or runs a different list."""
    lines = _code_lines(_step(name)["run"])
    assert lines in [list(b) for b in STEP_BODIES[name]], (
        f"{name!r} must be exactly one of {list(STEP_BODIES[name])} (comments aside); found {lines}"
    )


# ── pre-commit side ────────────────────────────────────────────────────────────


def test_every_precommit_run_check_is_listed():
    by_label = {c.precommit_label: c for c in checks.CHECKS if c.precommit_label}
    only = dict(checks.PRECOMMIT_ONLY)
    problems = []
    for label, script, args in _precommit_run_checks():
        if label in only:
            continue
        c = by_label.get(label)
        if c is None:
            problems.append(f"{label!r}: no Check has this precommit_label and it is not in PRECOMMIT_ONLY")
        elif c.script != script:
            problems.append(f"{label!r}: Check {c.id} runs {c.script}, pre-commit runs {script}")
        elif c.precommit_args != args:
            problems.append(f"{label!r}: Check {c.id} records precommit_args {c.precommit_args}, pre-commit passes {args}")
    assert not problems, "\n".join(problems)


def test_precommit_labels_in_the_list_exist_in_precommit():
    """A label the hook no longer runs is a stale claim of local coverage."""
    labels = {label for label, _, _ in _precommit_run_checks()}
    stale = [c.id for c in checks.CHECKS if c.precommit_label and c.precommit_label not in labels]
    stale += [label for label, _ in checks.PRECOMMIT_ONLY if label not in labels]
    assert not stale, f"labels not found in pre-commit.sh: {stale}"


def test_precommit_only_entries_have_reasons_and_are_not_also_checks():
    check_labels = {c.precommit_label for c in checks.CHECKS}
    for label, reason in checks.PRECOMMIT_ONLY:
        assert reason.strip(), f"PRECOMMIT_ONLY {label!r} has no reason"
        assert label not in check_labels, f"{label!r} is both a Check and PRECOMMIT_ONLY"


def test_precommit_unmanaged_invocations_are_declared():
    """Validators the hook runs outside run_check get no PASS/FAIL line and often
    `|| true`; each must be a recorded decision, and the record must not go stale."""
    found = set(_precommit_unmanaged_scripts())
    declared = {script for script, _ in checks.PRECOMMIT_UNMANAGED}
    for script, reason in checks.PRECOMMIT_UNMANAGED:
        assert reason.strip(), f"PRECOMMIT_UNMANAGED {script!r} has no reason"
    undeclared = sorted(found - declared)
    assert not undeclared, f"pre-commit runs validators outside run_check, undeclared in PRECOMMIT_UNMANAGED: {undeclared}"
    stale = sorted(declared - found)
    assert not stale, f"PRECOMMIT_UNMANAGED entries pre-commit no longer runs outside run_check: {stale}"


def test_arg_drift_is_declared():
    """Pre-commit args that differ from CI's must be a recorded decision, and a
    KNOWN_DRIFT entry must still describe real drift (or it is a stale excuse)."""
    declared = dict(checks.KNOWN_DRIFT)
    for subject, reason in checks.KNOWN_DRIFT:
        assert reason.strip(), f"KNOWN_DRIFT {subject!r} has no reason"
    drifted = {
        c.id for c in checks.CHECKS
        if c.precommit_args is not None and c.precommit_args != c.ci_args
    }
    undeclared = sorted(drifted - set(declared))
    assert not undeclared, f"pre-commit and CI pass different args, undeclared in KNOWN_DRIFT: {undeclared}"
    ids = {c.id for c in checks.CHECKS}
    stale = sorted(s for s in declared if s in ids and s not in drifted)
    assert not stale, f"KNOWN_DRIFT entries whose args no longer differ: {stale}"
    unknown = sorted(s for s in declared if s not in ids and s != "pytest")
    assert not unknown, f"KNOWN_DRIFT subjects that are neither a Check id nor `pytest`: {unknown}"


def test_pytest_drift_is_exactly_the_declared_one():
    """The `pytest` KNOWN_DRIFT entry is checked, not just written down: CI's first
    pytest invocation and pre-commit's "unit tests (ts-cli)" one differ by exactly
    tools/ossie-roundtrip/tests/. A new difference, or the gap closing, fails."""
    ci_cmds = [line for line in _code_lines(_step(PYTEST_STEP)["run"]) if line.startswith("pytest ")]
    assert ci_cmds, f"no pytest line in {PYTEST_STEP!r}"
    ci_dirs = _pytest_dirs(shlex.split(ci_cmds[0])[1:])

    pc_cmds = [line for line in _precommit_code_lines() if 'run_pytest "unit tests (ts-cli)"' in line]
    assert len(pc_cmds) == 1, f"expected one `run_pytest \"unit tests (ts-cli)\"` line, found {len(pc_cmds)}"
    pc_dirs = _pytest_dirs(shlex.split(pc_cmds[0])[2:])

    expected_gap = {"tools/ossie-roundtrip/tests"}
    assert "pytest" in dict(checks.KNOWN_DRIFT), "pytest drift exists but is not declared in KNOWN_DRIFT"
    assert ci_dirs - pc_dirs == expected_gap, f"CI-only pytest dirs {sorted(ci_dirs - pc_dirs)} != {sorted(expected_gap)}"
    assert pc_dirs - ci_dirs == set(), f"pre-commit-only pytest dirs: {sorted(pc_dirs - ci_dirs)}"


# ── the list itself ────────────────────────────────────────────────────────────


def test_ids_unique():
    ids = [c.id for c in checks.CHECKS]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})
    labels = [c.precommit_label for c in checks.CHECKS if c.precommit_label]
    assert len(labels) == len(set(labels))


def test_scripts_exist():
    missing = [c.script for c in checks.CHECKS if not (VALIDATE_DIR / c.script).is_file()]
    missing += [s for s, _ in checks.PRECOMMIT_UNMANAGED if not (VALIDATE_DIR / s).is_file()]
    assert not missing, f"script not found under tools/validate/: {missing}"
    smokes = REPO_ROOT / "tools" / "smoke-tests"
    missing = [s for s in checks.CI_SMOKES if not (smokes / f"{s}.py").is_file()]
    assert not missing, f"CI_SMOKES not found under tools/smoke-tests/: {missing}"


def test_local_args_swap_origin_main_for_base():
    for c in checks.CHECKS:
        assert c.local_args == tuple(a.replace("origin/main", "{base}") for a in c.ci_args), c.id
        assert "origin/main" not in " ".join(c.local_args), c.id


@pytest.mark.parametrize(
    "check_id, field, expected",
    [
        ("ossie-mapping-sync", "optional_prereq", "ossie-checkout"),
        ("quality-gates", "hard", False),
    ],
)
def test_declared_special_cases(check_id, field, expected):
    by_id = {c.id: c for c in checks.CHECKS}
    assert getattr(by_id[check_id], field) == expected


def test_only_declared_checks_are_soft_or_optional():
    soft = sorted(c.id for c in checks.CHECKS if not c.hard)
    optional = sorted(c.id for c in checks.CHECKS if c.optional_prereq)
    assert soft == ["quality-gates"]
    assert optional == ["ossie-mapping-sync"]
