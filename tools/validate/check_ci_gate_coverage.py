#!/usr/bin/env python3
"""
check_ci_gate_coverage.py — the aggregate CI gate actually covers every job.

Background. Branch protection on `main` requires exactly ONE status check,
`validate`. Until 2026-08-27 that context was the job that ran the work, so a
second job — `pytest-matrix`, over Python 3.10/3.11/3.13/3.14 — reported
interpreter-specific failures that could not block a merge (audit finding 7.1:
"the gate exists but is advisory").

The fix made `validate` an aggregate: it runs nothing and declares
`needs: [suite, pytest-matrix]`, failing unless both succeeded. That closes 7.1
but creates a NEW invariant which, left as prose, is exactly the kind of
"we'll remember" the two-bucket rule exists to prevent:

    adding a job to validate.yml does not gate it —
    it must also be added to `validate`'s `needs:`

Nothing else in this repo reads job names. `generate_quality_gates.py::_parse_ci`
is a flat line scan that never opens `jobs:`, so a new ungated job would produce
a green catalog and a green PR.

Four rules, each a way the gate can be defeated:

  1. A job named `validate` exists. If it is renamed or deleted, the required
     context never reports — and a required check that never reports leaves the
     PR pending forever rather than failing loudly. The repo cannot see the
     branch-protection setting, so this is the only end it can hold.
  2. Every job that can run on a pull request is in `validate`'s `needs:`.
     Schedule-only jobs (`if: github.event_name == 'schedule'`) are exempt —
     they never run on a PR, so gating them would make `validate` skip.
  3. `validate`'s own condition keeps `always()`. Without it a FAILED dependency
     skips the job, and a skipped required check counts as satisfied — the
     original bug, one level up. GitHub's docs recommend `!cancelled()` over
     `always()` generically; here that advice is wrong, so the check pins it.
  4. No gated job sets `continue-on-error: true`. That makes `needs.<job>.result`
     report `success` even when the job failed — the one documented way to defeat
     this gate that the failure/cancelled/skipped condition cannot see.
     (github.com/orgs/community/discussions/45546)

Exit codes:
  0 — all rules pass
  1 — at least one violation
  2 — the check could not run (missing file, unparseable YAML); NOT a pass

Run manually:
    python3 tools/validate/check_ci_gate_coverage.py --root .
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    print("ERROR: PyYAML is required. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(2)

WORKFLOW_REL = ".github/workflows/validate.yml"

# The job branch protection requires. Changing this means changing the setting on
# GitHub too — which is off-repo, so the constant is deliberately not configurable.
GATE_JOB = "validate"

SCHEDULE_ONLY = "github.event_name == 'schedule'"


def _job_if(job: dict) -> str:
    """A job's `if:` as a string. YAML may parse a bare expression as bool/None."""
    return str(job.get("if", "") or "")


def check(root: Path) -> list[str]:
    """Return a list of human-readable failures; empty means pass."""
    path = root / WORKFLOW_REL
    if not path.exists():
        raise FileNotFoundError(f"{WORKFLOW_REL} not found under {root}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = (data or {}).get("jobs") or {}
    if not jobs:
        raise ValueError(f"{WORKFLOW_REL} defines no jobs")

    failures: list[str] = []

    # Rule 1 — the required context still exists.
    if GATE_JOB not in jobs:
        return [
            f"No job named `{GATE_JOB}` in {WORKFLOW_REL}. Branch protection requires that "
            f"exact context; without the job the check never reports and every PR hangs "
            f"'Expected'. Rename it back, or change the branch-protection setting FIRST."
        ]

    gate = jobs[GATE_JOB] or {}
    needs = gate.get("needs") or []
    if isinstance(needs, str):  # `needs: suite` is legal YAML
        needs = [needs]
    needs_set = set(needs)

    # Rule 2 — every PR-reachable job is gated.
    for name, job in jobs.items():
        if name == GATE_JOB:
            continue
        if SCHEDULE_ONLY in _job_if(job or {}):
            continue  # never runs on a PR; gating it would make `validate` skip
        if name not in needs_set:
            failures.append(
                f"Job `{name}` runs on pull requests but is not in `{GATE_JOB}`'s `needs:`, "
                f"so its failures cannot block a merge (audit finding 7.1). "
                f"Add it: `needs: [{', '.join(sorted(needs_set | {name}))}]`."
            )

    # Rule 3 — the condition still tolerates failed dependencies.
    if "always()" not in _job_if(gate):
        failures.append(
            f"`{GATE_JOB}`'s `if:` no longer contains `always()`. Without it a FAILED "
            f"dependency SKIPS this job, and a skipped required check counts as satisfied "
            f"— reinstating finding 7.1 one level up. `!cancelled()` is NOT a safe "
            f"substitute here: a cancelled run would skip the gate."
        )

    # Rule 4 — no gated job can mask its own failure.
    for name in sorted(needs_set):
        job = jobs.get(name)
        if job is None:
            failures.append(
                f"`{GATE_JOB}` needs `{name}`, which is not defined in {WORKFLOW_REL}."
            )
            continue
        if job.get("continue-on-error") is True:
            failures.append(
                f"Job `{name}` sets `continue-on-error: true`, which makes "
                f"`needs.{name}.result` report `success` even when it fails — defeating "
                f"`{GATE_JOB}` invisibly. Remove it, or drop the job from the gate."
            )

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repository root")
    args = ap.parse_args()

    try:
        failures = check(Path(args.root).resolve())
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if failures:
        print("CI gate coverage FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print("CI gate coverage clean: `validate` gates every pull-request job.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
