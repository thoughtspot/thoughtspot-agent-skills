"""The smoke runner must never pass an irreversible flag through to a smoke test.

run_smoke_tests.py is a pre-push gate whose per-skill args come from a gitignored
config file, so a destructive flag parked there would fire on every push with nothing
in the repo showing it (PR #505 review, finding 2)."""
import run_smoke_tests


def test_run_delete_is_refused_for_dependency_cleanup():
    assert run_smoke_tests.destructive_args(
        "ts-dependency-cleanup", ["--column-guid", "x", "--run-delete"]) == ["--run-delete"]


def test_equals_form_is_refused_too():
    assert run_smoke_tests.destructive_args(
        "ts-dependency-cleanup", ["--run-delete=1"]) == ["--run-delete=1"]


def test_non_destructive_args_pass():
    assert run_smoke_tests.destructive_args(
        "ts-dependency-cleanup", ["--column-guid", "x", "--max-cascade", "2"]) == []


def test_other_skills_unaffected():
    assert run_smoke_tests.destructive_args("ts-audit", ["--run-delete"]) == []


def test_every_destructive_flag_exists_in_its_smoke_test():
    """A renamed flag would make the refusal silently stop matching."""
    for skill, flags in run_smoke_tests.DESTRUCTIVE_FLAGS.items():
        src = run_smoke_tests._smoke_test_path(skill).read_text()
        for flag in flags:
            assert f'"{flag}"' in src, f"{skill}: {flag} not declared in its smoke test"
