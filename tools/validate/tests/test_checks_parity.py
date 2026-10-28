"""Parity tests pinning `checks.py` to the two places that actually run checks.

`checks.CHECKS` is meant to be the list of validators CI's full-repo step runs on
every PR. It only earns that title if it cannot drift from what CI and pre-commit
really run, so these tests read the committed `.github/workflows/validate.yml` and
`scripts/pre-commit.sh` and fail on any line the list does not account for:

- every `python3 tools/validate/X.py ARGS` in CI's full-repo step is exactly one
  `Check` (script + args + hard/soft), and every `Check` is in that step;
- every `run_check "LABEL" "tools/validate/X.py ARGS"` in pre-commit is a `Check`
  carrying that label and those args, or is in `PRECOMMIT_ONLY` with a reason;
- every validator pre-commit runs OUTSIDE run_check is in `PRECOMMIT_UNMANAGED`;
- pre-commit args that differ from CI's are declared in `KNOWN_DRIFT`, so a
  difference is a recorded decision rather than an accident;
- `CI_SMOKES` is the workflow's smoke loop.

Every guard fails loud on a line it cannot parse rather than skipping it: a test
that silently ignores an unrecognised shape is exactly the drift it exists to
catch. Once CI calls `run_checks.py` instead of listing validators, the workflow
side switches to asserting that call — exactly, with nothing else beside it and
nothing (`continue-on-error`, a new `if:`) able to neutralise the step.
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
FULL_REPO_STEP = "Run validators (full-repo mode)"
SMOKE_STEP = "Run credential-free smoke suites"
PYTEST_STEP = "Run unit + validator tests"
RUNNER_CI_CALL = "python3 tools/validate/run_checks.py --context ci --base origin/main"
RUNNER_SMOKES_CALL = "python3 tools/validate/run_checks.py --smokes"
# The only step-level guard each step may carry: what it has today. A new `if:` or
# `continue-on-error` would let the step stop gating without any line changing.
STEP_GUARDS = {FULL_REPO_STEP: None, SMOKE_STEP: "${{ !cancelled() }}"}

_CI_LINE = re.compile(r"^python3 tools/validate/(?P<script>\S+\.py)(?P<rest>.*)$")
_RUN_CHECK = re.compile(
    r'\brun_check\s+"(?P<label>[^"]+)"\s+"tools/validate/(?P<script>[^"\s]+\.py)(?P<args>[^"]*)"'
)
_RUN_CHECK_WORD = re.compile(r"\brun_check\b")
_RUN_CHECK_DEF = re.compile(r"^\s*run_check\(\)")
# An unescaped validator path: grep patterns in the hook spell it `check_x\.py`,
# which this deliberately does not match.
_VALIDATOR_PATH = re.compile(r"tools/validate/(?P<script>[\w-]+\.py)")


def _job() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"][JOB]


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


def _uses_runner(lines: list[str]) -> bool:
    return any("tools/validate/run_checks.py" in line for line in lines)


def _assert_exact_runner_call(lines: list[str], expected: str, step: str) -> None:
    """In runner form the step's ONLY tools/validate/ line must be `expected`, verbatim:
    no `|| true`, no `--only`, no extra args, no unlisted validator beside it."""
    validator_lines = [line for line in lines if "tools/validate/" in line]
    assert validator_lines == [expected], (
        f"{step!r} must call exactly {expected!r} and no other tools/validate/ script; "
        f"found {validator_lines}"
    )


def _ci_validator_lines(lines: list[str]) -> list[tuple[str, tuple[str, ...], bool]]:
    """(script, args, hard) for each `python3 tools/validate/...` line.

    The trailing shell is not an argument. `|| rc=1` is a hard check (it fails the
    step at the end); `|| echo ...` is a soft one (it never does). Any other shape —
    no suffix, `|| true`, `|| :`, another interpreter spelling — fails, because the
    test could not otherwise say whether the line gates.
    """
    out = []
    for line in lines:
        if "tools/validate/" not in line:
            continue
        m = _CI_LINE.match(line)
        assert m, f"unrecognised validator line in {FULL_REPO_STEP!r}: {line}"
        rest = m.group("rest")
        assert "||" in rest, f"validator line must end `|| rc=1` (hard) or `|| echo ...` (soft): {line}"
        rest, suffix = rest.split("||", 1)
        suffix = suffix.strip()
        if suffix == "rc=1":
            hard = True
        elif suffix.startswith("echo"):
            hard = False
        else:
            raise AssertionError(f"validator line suffix must be `|| rc=1` or `|| echo ...`, got `|| {suffix}`: {line}")
        out.append((m.group("script"), tuple(shlex.split(rest)), hard))
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
    assert "continue-on-error" not in _job(), f"job {JOB!r} has continue-on-error"


def test_every_ci_validator_line_is_listed():
    lines = _code_lines(_step(FULL_REPO_STEP)["run"])
    if _uses_runner(lines):
        # CI reads the list itself, so there is nothing left to compare line by line.
        _assert_exact_runner_call(lines, RUNNER_CI_CALL, FULL_REPO_STEP)
        return

    ci_lines = _ci_validator_lines(lines)
    assert ci_lines, f"no validator lines found in {FULL_REPO_STEP!r}"
    # `|| rc=1` only gates because the step ends by exiting with it.
    assert lines[-1] == "exit $rc", f"{FULL_REPO_STEP!r} must end with `exit $rc`, ends with {lines[-1]!r}"
    listed = {(c.script, c.ci_args): c for c in checks.CHECKS}

    missing = [(s, a) for s, a, _ in ci_lines if (s, a) not in listed]
    assert not missing, f"CI runs validators that checks.CHECKS does not list: {missing}"

    ci_keys = [(s, a) for s, a, _ in ci_lines]
    dupes = sorted({k for k in ci_keys if ci_keys.count(k) > 1})
    assert not dupes, f"CI runs the same validator line twice: {dupes}"

    extra = [c.id for c in checks.CHECKS if (c.script, c.ci_args) not in set(ci_keys)]
    assert not extra, f"checks.CHECKS lists validators CI's full-repo step does not run: {extra}"

    wrong_hard = [
        (s, hard) for s, a, hard in ci_lines if listed[(s, a)].hard != hard
    ]
    assert not wrong_hard, f"Check.hard disagrees with CI's `|| rc=1` / `|| echo` form: {wrong_hard}"


def test_ci_smokes_match_workflow():
    run = _step(SMOKE_STEP)["run"]
    lines = _code_lines(run)
    if _uses_runner(lines):
        _assert_exact_runner_call(lines, RUNNER_SMOKES_CALL, SMOKE_STEP)
        return
    joined = run.replace("\\\n", " ")
    m = re.search(r"for s in (?P<suites>.*?);\s*do", joined, re.S)
    assert m, f"no `for s in ...; do` loop in {SMOKE_STEP!r}"
    workflow_suites = tuple(m.group("suites").split())
    assert workflow_suites == checks.CI_SMOKES, (
        f"CI_SMOKES {checks.CI_SMOKES} != workflow loop {workflow_suites}"
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
