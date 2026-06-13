"""The smoke runner and checker must share their allowlist/alias tables (audit F5).

When run_smoke_tests.py kept its own copy, it drifted from check_smoke_tests.py:
the runner aliased ts-object-model-builder to a smoke file that does not exist, and
Databricks skills were absent — so those smoke tests silently never ran. These tests
fail loudly if the tables diverge again, or if an alias points at a missing file.

NOTE (deviation from plan): the plan's draft asserted that every entry in ALLOWLIST
resolves to a smoke file. ALLOWLIST is the *exemption* list (skills that deliberately
have NO smoke test — interactive setup, etc.), so that assertion is inverted against the
real semantics. The meaningful F5 invariant is: every NAME_ALIASES target must exist, and
every skill the checker *requires* a smoke test for must resolve. Tested below."""
from pathlib import Path

import run_smoke_tests
import check_smoke_tests

REPO = Path(__file__).resolve().parents[3]


def test_runner_and_checker_share_constants():
    assert run_smoke_tests.ALLOWLIST is check_smoke_tests.ALLOWLIST
    assert run_smoke_tests.NAME_ALIASES is check_smoke_tests.NAME_ALIASES


def test_every_name_alias_target_exists():
    # The Databricks silent-SKIP bug (F5): an alias pointed at a nonexistent file.
    for skill, rel_path in run_smoke_tests.NAME_ALIASES.items():
        assert (REPO / rel_path).exists(), (
            f"{skill}: alias -> {rel_path} does not exist — this was the "
            "silent-SKIP bug (audit F5)")


def test_every_required_skill_resolves_to_a_smoke_file():
    # Any skill the checker does NOT exempt must resolve to a real smoke file in the runner.
    failures, info = check_smoke_tests.check(REPO, staged_only=False)
    assert not failures, failures
    required = []
    for line in info:
        # info lines look like "  PASS  <skill>  ->  <path>" or "  SKIP  <skill>  (on allowlist)"
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "PASS":
            required.append(parts[1])
    for skill in required:
        assert run_smoke_tests._smoke_test_path(skill) is not None, (
            f"{skill}: checker requires a smoke test but the runner cannot resolve it")
