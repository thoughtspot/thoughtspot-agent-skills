"""Parity tests pinning `checks.py` to the two places that actually run checks.

`checks.CHECKS` is meant to be the one list of validators a PR must pass. It only
earns that title if it cannot drift from what CI and pre-commit really run, so
these tests read the committed `.github/workflows/validate.yml` and
`scripts/pre-commit.sh` and fail on any line the list does not account for:

- every `python3 tools/validate/X.py ARGS` in CI's full-repo step is exactly one
  `Check` (script + args + hard/soft), and every `Check` is in that step;
- every `run_check "LABEL" "tools/validate/X.py ARGS"` in pre-commit is a `Check`
  carrying that label and those args, or is in `PRECOMMIT_ONLY` with a reason;
- pre-commit args that differ from CI's are declared in `KNOWN_DRIFT`, so a
  difference is a recorded decision rather than an accident;
- `CI_SMOKES` is the workflow's smoke loop.

Once CI calls `run_checks.py` instead of listing validators, the workflow side of
these tests switches to asserting that call, because the list is then the source.
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

FULL_REPO_STEP = "Run validators (full-repo mode)"
SMOKE_STEP = "Run credential-free smoke suites"
RUNNER_CI_CALL = "python3 tools/validate/run_checks.py --context ci --base origin/main"
RUNNER_SMOKES_CALL = "python3 tools/validate/run_checks.py --smokes"

_CI_LINE = re.compile(r"^python3 tools/validate/(?P<script>\S+\.py)(?P<rest>.*)$")
_RUN_CHECK = re.compile(
    r'^\s*run_check\s+"(?P<label>[^"]+)"\s+"tools/validate/(?P<script>[^"\s]+\.py)(?P<args>[^"]*)"'
)


def _step_run(name: str) -> str:
    """The `run:` script of the workflow step called `name` (any job)."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    found = [
        step["run"]
        for job in doc["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == name
    ]
    assert len(found) == 1, f"expected exactly one step named {name!r}, found {len(found)}"
    return found[0]


def _ci_validator_lines(run: str) -> list[tuple[str, tuple[str, ...], bool]]:
    """(script, args, hard) for each `python3 tools/validate/...` line.

    The trailing shell is not an argument: `|| rc=1` is a hard check (it fails the
    step at the end), `|| echo "WARN ..."` is a soft one (it never does).
    """
    out = []
    for raw in run.splitlines():
        line = raw.strip()
        m = _CI_LINE.match(line)
        if not m:
            continue
        rest = m.group("rest")
        hard = True
        if "||" in rest:
            rest, suffix = rest.split("||", 1)
            hard = not suffix.strip().startswith("echo")
        out.append((m.group("script"), tuple(shlex.split(rest)), hard))
    return out


def _precommit_run_checks() -> list[tuple[str, str, tuple[str, ...]]]:
    """(label, script, args) for each `run_check` call in pre-commit.sh.

    run_check splits its command with `read -r -a`, i.e. on whitespace, so a plain
    `split()` reproduces exactly the argv pre-commit passes.
    """
    text = PRECOMMIT.read_text(encoding="utf-8")
    calls = [
        line for line in text.splitlines()
        if line.strip().startswith("run_check ") and not line.strip().startswith("run_check()")
    ]
    parsed = []
    for line in calls:
        m = _RUN_CHECK.match(line)
        assert m, f"pre-commit run_check line not in the expected shape: {line.strip()}"
        parsed.append((m.group("label"), m.group("script"), tuple(m.group("args").split())))
    assert parsed, "found no run_check calls in pre-commit.sh — has the hook been restructured?"
    return parsed


# ── workflow side ──────────────────────────────────────────────────────────────


def test_every_ci_validator_line_is_listed():
    run = _step_run(FULL_REPO_STEP)
    if "tools/validate/run_checks.py" in run:
        # CI reads the list itself, so there is nothing left to compare line by line.
        assert RUNNER_CI_CALL in run, f"full-repo step calls run_checks.py without {RUNNER_CI_CALL!r}"
        return

    ci_lines = _ci_validator_lines(run)
    assert ci_lines, f"no validator lines found in {FULL_REPO_STEP!r}"
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
    run = _step_run(SMOKE_STEP)
    if "tools/validate/run_checks.py" in run:
        assert RUNNER_SMOKES_CALL in run, f"smoke step calls run_checks.py without {RUNNER_SMOKES_CALL!r}"
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
    unknown = sorted(s for s in declared if s not in ids and not s.startswith("pytest"))
    assert not unknown, f"KNOWN_DRIFT subjects that are neither a Check id nor a pytest invocation: {unknown}"


# ── the list itself ────────────────────────────────────────────────────────────


def test_ids_unique():
    ids = [c.id for c in checks.CHECKS]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})
    labels = [c.precommit_label for c in checks.CHECKS if c.precommit_label]
    assert len(labels) == len(set(labels))


def test_scripts_exist():
    missing = [c.script for c in checks.CHECKS if not (VALIDATE_DIR / c.script).is_file()]
    assert not missing, f"Check.script not found under tools/validate/: {missing}"
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
