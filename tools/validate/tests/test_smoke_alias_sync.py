"""The smoke runner and checker must share their allowlist/alias tables (audit F5).

When run_smoke_tests.py kept its own copy, it drifted from check_smoke_tests.py:
the runner aliased ts-object-model-builder to a smoke file that does not exist, and
Databricks skills were absent — so those smoke tests silently never ran. These tests
fail loudly if the tables diverge again, or if an alias points at a missing file.

NOTE (deviation from plan): the plan's draft asserted that every entry in ALLOWLIST
resolves to a smoke file. ALLOWLIST is the *exemption* list (skills that deliberately
have NO smoke test — interactive setup, etc.), so that assertion is inverted against the
real semantics. The meaningful F5 invariant is: every NAME_ALIASES target must exist, and
every skill the checker *requires* a smoke test for must resolve. Tested below.

Audit 6.1 added a second drift class in the same family: REQUIRED_EXTRA_ARGS (in
run_smoke_tests.py) is a hand-maintained table of each smoke test's own required=True
CLI flags. ts-object-model-spotql-query's smoke test declared --model-guid/--spotql as
required with no matching REQUIRED_EXTRA_ARGS entry — on an unconfigured machine,
argparse's exit code 2 read as a push-blocking FAIL instead of a graceful SKIP.
test_required_extra_args_covers_every_smoke_tests_required_flags below parses every
smoke_*.py file's argparse required=True flags and asserts each is covered, so this
drift class can't recur silently."""
import ast
from pathlib import Path

import run_smoke_tests
import check_smoke_tests

REPO = Path(__file__).resolve().parents[3]
SMOKE_DIR = REPO / "tools" / "smoke-tests"


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


def _required_argparse_flags(py_file: Path) -> set[str]:
    """Statically find `parser.add_argument("--flag", required=True, ...)` calls.

    Deliberately does NOT follow `argparse.add_mutually_exclusive_group(required=True)`
    sub-groups (e.g. ts-dependency-manager's --model-guid/--model-name,
    ts-object-model-coach's same pattern) — which of the OR'd flags to require in
    REQUIRED_EXTRA_ARGS is a policy choice (the smoke README recommends --model-guid for
    stable, unambiguous identification), not something mechanically derivable from the
    AST. Those skills already have correct, hand-picked entries.
    """
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.startswith("--")):
            continue
        for kw in node.keywords:
            if (kw.arg == "required" and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True):
                flags.add(node.args[0].value)
    return flags


def test_required_extra_args_covers_every_smoke_tests_required_flags():
    """Every smoke_*.py's own required=True flags (beyond --ts-profile) must be a subset
    of that skill's REQUIRED_EXTRA_ARGS entry — otherwise an unconfigured machine gets
    argparse's exit code 2, which run_smoke_tests.py reads as a push-blocking FAIL
    instead of a graceful SKIP (audit 6.1)."""
    failures, info = check_smoke_tests.check(REPO, staged_only=False)
    assert not failures, failures

    skills_requiring_smoke_tests = [
        line.split()[1] for line in info
        if len(line.split()) >= 2 and line.split()[0] == "PASS"
    ]

    for skill in skills_requiring_smoke_tests:
        smoke_path = run_smoke_tests._smoke_test_path(skill)
        assert smoke_path is not None, f"{skill}: no resolvable smoke test"

        declared_required = _required_argparse_flags(smoke_path) - {"--ts-profile"}
        configured = set(run_smoke_tests.REQUIRED_EXTRA_ARGS.get(skill, []))
        missing = declared_required - configured

        assert not missing, (
            f"{skill}: smoke test {smoke_path.name} declares required flag(s) "
            f"{sorted(missing)} with no matching REQUIRED_EXTRA_ARGS entry — add "
            f"them to run_smoke_tests.REQUIRED_EXTRA_ARGS['{skill}']")
