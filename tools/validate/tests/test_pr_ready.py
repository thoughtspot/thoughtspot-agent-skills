"""Tests for pr_ready.py — the local, CI-superset run behind scripts/pr-ready.sh.

What these pin, and why each matters:

- **Behind upstream main is not ready**, even with every check green: a branch
  that is behind was checked against code it will not merge onto.
- **Upstream is fetched every run, and named in full.** A stale `<upstream>/main`
  already present locally, or a local branch or tag CALLED `upstream/main` (git
  resolves those before the remote-tracking ref), would otherwise be the base, and
  "behind" would read 0.
- **The fork's `main` is never the base.** Upstream is found by URL.
- **A skipped test is never hidden under PASS**, and one skipped for a missing
  module is FAIL (CI installs it).
- **Nothing is posted unless the run is green, the tree clean, and the canonical
  repo's PR has the evidence's head**; always with `--repo`, after the path prints.
- **CI-superset is checked, not claimed.** Every line of every job in the workflow
  is run by pr-ready or is known plumbing; a new job, step or interpreter spelling
  fails (the reviewer's five workflow mutations are cases below).

No test touches the network or `gh`. Upstream is a local bare repo; the canonical
URL pattern is monkeypatched to match it (there is deliberately no production
override — an env var or flag that redirects the base would let a run "pass"
against the wrong code). Validator, pytest and gh execution are replaced.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import checks
import pr_ready
import run_checks as rc

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "validate.yml"
BASE = "refs/remotes/upstream/main"


# ---------------------------------------------------------------- helpers ---

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit(work, name, text="x\n"):
    (work / name).write_text(text)
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", f"add {name}")


class Recorder:
    """Stands in for an executor: records argv, answers by a substring match."""

    def __init__(self, answers=None):
        self.answers = answers or {}   # substring of the joined argv -> (code, output)
        self.calls = []

    def answer(self, argv):
        joined = " ".join(str(a) for a in argv)
        self.calls.append(joined)
        for key, (code, out) in self.answers.items():
            if key in joined:
                return code, out, 0.01
        return 0, "ok\n", 0.01


class FakeGh:
    """Stands in for pr_ready._gh: `pr view` answers `head`, `pr comment` succeeds."""

    def __init__(self):
        self.head = ""
        self.calls = []
        self.comment_code = 0

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            return 0, self.head + "\n", ""
        return self.comment_code, "https://example.invalid/comment\n", "boom" if self.comment_code else ""

    def comments(self):
        return [c for c in self.calls if c[:2] == ["pr", "comment"]]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """upstream bare repo U, a fork F of it, and a work clone of F with remote
    `upstream` -> U (added, never fetched: pr-ready must fetch it)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # main() writes PYTHONPATH into os.environ; setenv first so teardown restores
    # the original value (absent or not) rather than leaking ours to later tests.
    monkeypatch.setenv("PYTHONPATH", "placeholder")
    monkeypatch.delenv("PYTHONPATH")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    for key, value in (("user.email", "test@example.com"), ("user.name", "Test"),
                       ("init.defaultBranch", "main")):
        _git(tmp_path, "config", "--global", key, value)

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    (seed / ".github" / "workflows").mkdir(parents=True)
    shutil.copy2(WORKFLOW, seed / ".github" / "workflows" / "validate.yml")
    _commit(seed, "README.md")
    upstream = tmp_path / "upstream.git"
    fork = tmp_path / "fork.git"
    _git(tmp_path, "clone", "-q", "--bare", str(seed), str(upstream))
    _git(tmp_path, "clone", "-q", "--bare", str(upstream), str(fork))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(fork), str(work))
    upstream_url = f"file://{upstream}"
    _git(work, "remote", "add", "upstream", upstream_url)

    # The one test seam for "which remote is upstream": match the local bare repo.
    monkeypatch.setattr(rc, "_CANONICAL_URL_RE", re.compile(re.escape(upstream_url) + "$"))
    checks_run = Recorder()
    monkeypatch.setattr(rc, "_execute",
                        lambda python, script, args, root: checks_run.answer([script, *args]))
    commands = Recorder()
    monkeypatch.setattr(pr_ready, "_run_command", lambda argv, root: commands.answer(argv))
    gh = FakeGh()
    monkeypatch.setattr(pr_ready, "_gh", gh)

    class Env:
        pass
    e = Env()
    e.tmp, e.seed, e.upstream, e.fork, e.work = tmp_path, seed, upstream, fork, work
    e.checks, e.commands, e.gh = checks_run, commands, gh
    return e


def _push_extra_commit(e, target, name):
    other = e.tmp / f"other-{name}"
    _git(e.tmp, "clone", "-q", str(target), str(other))
    _commit(other, name)
    _git(other, "push", "-q", "origin", "main")


def _main(e, *argv):
    return pr_ready.main(list(argv), repo_root=e.work, python="python3")


def _evidence(e):
    path = Path(_git(e.work, "rev-parse", "--absolute-git-dir")) / "pr-ready" / "evidence.md"
    return path, path.read_text(encoding="utf-8")


# ------------------------------------------------------------ the verdict ---

def test_pr_ready_passes_when_current_and_green(env, capsys):
    assert _main(env, "--no-review") == 0
    out = capsys.readouterr().out
    path, text = _evidence(env)
    assert str(path) in out, out
    head = _git(env.work, "rev-parse", "HEAD")
    base = _git(env.work, "rev-parse", BASE)
    assert head in text and base in text and BASE in text, text
    assert "DIRTY" not in text
    assert "NOT READY" not in text and "READY" in text


def test_pr_ready_refuses_when_behind(env, capsys):
    _push_extra_commit(env, env.upstream, "upstream-only.md")
    assert _main(env, "--no-review") == 1
    out = capsys.readouterr().out
    assert "behind" in out.lower(), out
    assert "Behind upstream main: 1 commit" in _evidence(env)[1]


def test_upstream_is_fetched_even_when_a_stale_ref_exists(env, capsys):
    _git(env.work, "fetch", "-q", "upstream")          # a ref exists ...
    _push_extra_commit(env, env.upstream, "later.md")  # ... and goes stale
    assert _main(env, "--no-review") == 1
    assert "behind" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("kind", ["branch", "tag"])
def test_a_local_ref_named_like_the_base_does_not_shadow_it(env, capsys, kind):
    # `git checkout -b upstream/main` or a tag of that name resolves BEFORE the
    # remote-tracking ref for the short name; the run must still see the real tip.
    _git(env.work, kind, "upstream/main", _git(env.work, "rev-parse", "HEAD"))
    _push_extra_commit(env, env.upstream, "upstream-only.md")
    assert _main(env, "--no-review") == 1
    real_tip = _git(env.upstream, "rev-parse", "main")
    assert real_tip in _evidence(env)[1]
    base_args = [c for c in env.checks.calls if "--base" in c]
    assert base_args and all(f"--base {BASE}" in c for c in base_args), base_args


def test_the_forks_main_is_never_the_base(env, capsys):
    # The fork's main moving ahead must change nothing: origin is not upstream.
    _push_extra_commit(env, env.fork, "fork-only.md")
    _git(env.work, "fetch", "-q", "origin")
    assert _main(env, "--no-review") == 0
    base_args = [c for c in env.checks.calls if "--base" in c]
    assert base_args and all(f"--base {BASE}" in c for c in base_args), base_args


def test_a_failing_check_exits_1(env, capsys):
    env.checks.answers = {"check_tml.py": (1, "FAIL  broken.tml\n")}
    assert _main(env, "--no-review") == 1


def test_a_failing_pytest_exits_1(env, capsys):
    env.commands.answers = {"pytest agents/databricks/tests/": (1, "1 failed\n")}
    assert _main(env, "--no-review") == 1


def test_dirty_tree_is_marked(env, capsys):
    (env.work / "README.md").write_text("changed\n")
    assert _main(env, "--no-review") == 0
    assert "DIRTY" in _evidence(env)[1]


def test_pr_only_checks_use_the_upstream_base(env, capsys):
    assert _main(env, "--no-review") == 0
    calls = env.checks.calls
    assert any(f"suggest_repo_changelog.py --root . --check --base {BASE}" in c for c in calls)
    assert any(f"check_open_items.py --root . --base {BASE}" in c for c in calls)
    assert any(f"check_pr_size.py --root . --base {BASE} --warn" in c for c in calls)
    assert any(f"check_customer_references.py --root . --range {BASE}..HEAD" in c for c in calls)
    assert any("check_ci_gate_coverage.py --root ." in c for c in calls)
    assert any("check_audit_workflow_permissions.py --root ." in c for c in calls)


def test_runs_the_check_list_smokes_and_workflow_pytest(env, capsys):
    assert _main(env, "--no-review") == 0
    scripts = {Path(c.split()[0]).name for c in env.checks.calls}
    assert {c.script for c in checks.CHECKS if c.optional_prereq is None} <= scripts
    assert {f"{s}.py" for s in checks.CI_SMOKES} <= scripts
    pytests = [c for c in env.commands.calls if " -m pytest " in c]
    assert len(pytests) == len(pr_ready.pytest_invocations(env.work)), pytests
    assert all(c.endswith(" -rs") for c in pytests), pytests


def test_pythonpath_is_pinned_to_this_checkout(env, capsys):
    assert _main(env, "--no-review") == 0
    assert os.environ["PYTHONPATH"].split(os.pathsep)[0] == str(env.work / "tools" / "ts-cli")


def test_cannot_start_message_does_not_offer_a_flag_pr_ready_lacks(env, monkeypatch, capsys):
    # No remote matches, and `upstream` is taken by another URL.
    monkeypatch.setattr(rc, "_CANONICAL_URL_RE", re.compile("^nothing-matches$"))
    assert _main(env, "--no-review") == 2
    err = capsys.readouterr().err
    assert "upstream" in err and "--base" not in err, err


# ------------------------------------------------------------ pytest skips ---

_SKIPS = ("....s.s\n"
          "SKIPPED [1] tools/a/test_x.py:10: could not import 'openpyxl': No module named 'openpyxl'\n"
          "SKIPPED [2] tools/b/test_y.py:20: $DATA not set\n"
          "10 passed, 3 skipped in 1.0s\n")


def test_a_skip_for_a_missing_module_is_fail_and_listed(env, capsys):
    env.commands.answers = {"pytest agents/databricks/tests/": (0, _SKIPS)}
    assert _main(env, "--no-review") == 1
    text = _evidence(env)[1]
    section = text.split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "tools/a/test_x.py:10: could not import 'openpyxl'" in section, section
    assert "missing module" in section and "counted as FAIL" in section, section
    assert "| pytest | `pytest agents/databricks/tests/ -q` | FAIL |" in text


def test_other_skips_are_listed_and_do_not_fail(env, capsys):
    env.commands.answers = {"pytest agents/databricks/tests/": (
        0, "..s\nSKIPPED [2] tools/b/test_y.py:20: $DATA not set\n2 passed, 2 skipped\n")}
    assert _main(env, "--no-review") == 0
    section = _evidence(env)[1].split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "tools/b/test_y.py:20: $DATA not set (x2)" in section, section
    assert "None." not in section


# ------------------------------------------------------------- --post ---

def test_post_happens_only_when_green_and_after_the_path(env, capsys):
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    assert _main(env, "--no-review", "--post", "42") == 0
    out = capsys.readouterr().out
    path = _evidence(env)[0]
    assert str(path) in out
    [comment] = env.gh.comments()
    assert comment == ["pr", "comment", "42", "--repo", rc.CANONICAL_REPO,
                       "--body-file", str(path)]
    view = env.gh.calls[0]
    assert view[:3] == ["pr", "view", "42"] and view[3:5] == ["--repo", rc.CANONICAL_REPO]


def test_post_is_refused_when_not_green(env, capsys):
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    _push_extra_commit(env, env.upstream, "upstream-only.md")
    assert _main(env, "--no-review", "--post", "42") == 1
    assert env.gh.calls == []
    assert "not posting" in capsys.readouterr().err.lower()


def test_post_is_refused_on_a_dirty_tree(env, capsys):
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    (env.work / "README.md").write_text("changed\n")
    assert _main(env, "--no-review", "--post", "42") == 1
    assert env.gh.calls == []
    assert "dirty" in capsys.readouterr().err.lower()


def test_post_is_refused_when_the_prs_head_is_not_this_head(env, capsys):
    env.gh.head = "f" * 40     # e.g. a fork's same-numbered PR, or an unpushed branch
    assert _main(env, "--no-review", "--post", "42") == 1
    assert env.gh.comments() == []
    assert "not posting" in capsys.readouterr().err.lower()


def test_a_failed_post_fails_the_run(env, capsys):
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    env.gh.comment_code = 1
    assert _main(env, "--no-review", "--post", "42") == 1


# ------------------------------------------------ derived from validate.yml ---

def _suite_steps():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["suite"]["steps"]


def test_pytest_invocations_are_the_workflows():
    step = [s for s in _suite_steps() if s.get("name") == pr_ready.PYTEST_STEP]
    assert len(step) == 1
    import shlex
    expected = [shlex.split(l)[1:] for l in pr_ready._code_lines(step[0]["run"])
                if l.startswith("pytest ")]
    assert expected and pr_ready.pytest_invocations(REPO) == expected


def test_a_pytest_step_with_a_line_pr_ready_cannot_reproduce_is_refused(tmp_path):
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in wf["jobs"]["suite"]["steps"]:
        if step.get("name") == pr_ready.PYTEST_STEP:
            step["run"] += "python3 -m something_else\n"
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "validate.yml").write_text(yaml.safe_dump(wf))
    with pytest.raises(RuntimeError, match="something_else"):
        pr_ready.pytest_invocations(tmp_path)


def test_every_line_ci_runs_is_reproduced_or_plumbing():
    """The CI-superset claim on the committed workflow: nothing unaccounted."""
    assert pr_ready.ci_lines_not_reproduced(REPO) == []


def test_every_gate_pr_ready_runs_is_one_ci_runs():
    """The other direction: an entry in PR_CHECKS / EVERY_PR_CHECKS that CI does not
    run would be a gate CI never enforces, presented as if it did."""
    import shlex
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    in_ci = set()
    for job in wf["jobs"].values():
        for step in job.get("steps") or []:
            for line in pr_ready._code_lines(step.get("run", "")):
                m = pr_ready._VALIDATOR_CALL.match(line)
                if m:
                    in_ci.add((Path(m.group(1)).name, tuple(
                        a.replace(pr_ready._CI_PR_BASE, "{base}") for a in shlex.split(m.group(2)))))
    mine = {(c.script, c.local_args) for c in pr_ready.PR_CHECKS + pr_ready.EVERY_PR_CHECKS}
    assert mine <= in_ci, sorted(mine - in_ci)


_ANCHOR = "      - name: Check the CI gate covers every job\n"
_MUTATIONS = {
    "mypy": "      - name: Type check\n        run: |\n          python3 -m mypy tools/ts-cli/ts_cli\n\n",
    "python-not-python3": ("      - name: New gate\n        run: |\n"
                           "          python tools/validate/check_new_gate.py --root .\n\n"),
    "smoke-direct": ("      - name: Extra smoke\n        run: |\n"
                     "          python3 tools/smoke-tests/smoke_ts_extra.py\n\n"),
    "bash-script": "      - name: PR content check\n        run: |\n          bash scripts/check-something.sh\n\n",
    "new-action": "      - name: Lint\n        uses: some/linter@v1\n\n",
    "echo-pipe": ("      - name: Sneaky\n        run: |\n"
                  "          echo x | python3 tools/validate/check_new_gate.py\n\n"),
}


def _mutated(tmp_path, text):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "validate.yml").write_text(text)
    return pr_ready.ci_lines_not_reproduced(tmp_path)


@pytest.mark.parametrize("which", sorted(_MUTATIONS))
def test_a_new_step_ci_runs_is_caught(tmp_path, which):
    orig = WORKFLOW.read_text(encoding="utf-8")
    assert _ANCHOR in orig
    assert _mutated(tmp_path, orig.replace(_ANCHOR, _MUTATIONS[which] + _ANCHOR, 1))


def test_a_new_job_is_caught(tmp_path):
    orig = WORKFLOW.read_text(encoding="utf-8")
    text = orig.replace("  validate:\n", "  lint:\n    if: github.event_name != 'schedule'\n"
                        "    runs-on: ubuntu-latest\n    steps:\n"
                        "      - run: python3 tools/validate/check_lint_new.py --root .\n\n"
                        "  validate:\n", 1)
    text = text.replace("needs: [suite, pytest-matrix]", "needs: [suite, pytest-matrix, lint]")
    assert any("lint" in m for m in _mutated(tmp_path, text))


def test_changed_args_on_a_pr_gate_are_caught(tmp_path):
    orig = WORKFLOW.read_text(encoding="utf-8")
    text = orig.replace("check_pr_size.py --root . --base", "check_pr_size.py --root . --all --base", 1)
    assert text != orig and _mutated(tmp_path, text)


def test_a_matrix_pytest_line_differing_from_the_suites_is_caught(tmp_path):
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in wf["jobs"]["pytest-matrix"]["steps"]:
        if step.get("name") == pr_ready.PYTEST_STEP:
            step["run"] += "pytest tools/extra/tests/ -q\n"
    assert _mutated(tmp_path, yaml.safe_dump(wf))


def test_a_ci_superset_gap_is_a_fail_row(env, capsys, monkeypatch):
    monkeypatch.setattr(pr_ready, "ci_lines_not_reproduced", lambda root: ["suite / X: mypy"])
    assert _main(env, "--no-review") == 1
    assert "| check | `ci-superset` | FAIL |" in _evidence(env)[1]


def test_the_scoped_quality_gates_pattern_is_the_workflows():
    step = [s for s in _suite_steps() if s.get("name") == pr_ready.QUALITY_GATES_STEP]
    assert len(step) == 1
    m = re.search(r"grep -qE '([^']+)'", step[0]["run"])
    assert m and m.group(1) == pr_ready.QUALITY_GATES_SOURCES


def test_quality_gates_scoped_gate_runs_only_when_a_source_changed(env, capsys):
    assert _main(env, "--no-review") == 0
    gates = [c for c in env.checks.calls if "generate_quality_gates.py" in c]
    assert len(gates) == 1, gates   # only the soft CHECKS entry
    # Touch a source of truth on the branch: the hard gate now runs.
    (env.work / "tools" / "validate").mkdir(parents=True)
    _commit(env.work, "tools/validate/check_new.py")
    env.checks.calls.clear()
    assert _main(env, "--no-review") == 0
    gates = [c for c in env.checks.calls if "generate_quality_gates.py" in c]
    assert len(gates) == 2, gates   # the soft CHECKS entry and the scoped hard gate


def test_scoped_quality_gates_failure_is_hard(env, capsys):
    (env.work / "tools" / "validate").mkdir(parents=True)
    _commit(env.work, "tools/validate/check_new.py")
    env.checks.answers = {"generate_quality_gates.py": (1, "FAIL  stale\n")}
    assert _main(env, "--no-review") == 1
