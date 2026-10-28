"""Tests for pr_ready.py — the local, CI-superset run behind scripts/pr-ready.sh.

What these pin, and why each matters:

- **Behind upstream main is not ready**, even with every check green: a branch
  that is behind was checked against code it will not merge onto.
- **Upstream is fetched every run.** A stale `<upstream>/main` already present
  locally would otherwise be compared against, and "behind" would read 0.
- **The fork's `main` is never the base.** Upstream is found by URL.
- **Nothing is posted unless the run is green**, and only after the path is printed.
- **CI-superset is checked, not claimed.** Every validator CI's `suite` job runs
  must be run here too (through the check list, the PR-only/every-PR list in
  pr_ready, or the scoped quality-gates gate), with the same args modulo the base
  ref; and the pytest invocations are read from the workflow, never copied.

No test touches the network or `gh`. Upstream is a local bare repo; the canonical
URL pattern is monkeypatched to match it (there is deliberately no production
override — an env var or flag that redirects the base would let a run "pass"
against the wrong code). Validator, pytest and gh execution are replaced.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

import checks
import pr_ready
import run_checks as rc
from test_checks_parity import _code_lines

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = REPO / ".github" / "workflows" / "validate.yml"


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


@pytest.fixture
def env(tmp_path, monkeypatch):
    """upstream bare repo U, a fork F of it, and a work clone of F with remote
    `upstream` -> U (added, never fetched: pr-ready must fetch it)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("PYTHONPATH", raising=False)
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
    posted = []
    monkeypatch.setattr(pr_ready, "_gh_comment",
                        lambda number, path: posted.append((number, path)) or 0)

    class Env:
        pass
    e = Env()
    e.tmp, e.seed, e.upstream, e.fork, e.work = tmp_path, seed, upstream, fork, work
    e.checks, e.commands, e.posted = checks_run, commands, posted
    return e


def _push_extra_commit(e, target, name):
    other = e.tmp / f"other-{name}"
    _git(e.tmp, "clone", "-q", str(target), str(other))
    _commit(other, name)
    _git(other, "push", "-q", "origin", "main")


def _main(e, *argv):
    return pr_ready.main(list(argv), repo_root=e.work, python="python3")


# ------------------------------------------------------------ the verdict ---

def test_pr_ready_passes_when_current_and_green(env, capsys):
    assert _main(env, "--no-review") == 0
    out = capsys.readouterr().out
    path = Path(_git(env.work, "rev-parse", "--absolute-git-dir")) / "pr-ready" / "evidence.md"
    assert str(path) in out, out
    text = path.read_text(encoding="utf-8")
    head = _git(env.work, "rev-parse", "HEAD")
    base = _git(env.work, "rev-parse", "upstream/main")
    assert head in text and base in text and "upstream/main" in text, text
    assert "DIRTY" not in text
    assert "NOT READY" not in text and "READY" in text


def test_pr_ready_refuses_when_behind(env, capsys):
    _push_extra_commit(env, env.upstream, "upstream-only.md")
    assert _main(env, "--no-review") == 1
    out = capsys.readouterr().out
    assert "behind" in out.lower(), out
    path = Path(_git(env.work, "rev-parse", "--absolute-git-dir")) / "pr-ready" / "evidence.md"
    assert "Behind upstream main: 1 commit" in path.read_text(encoding="utf-8")


def test_upstream_is_fetched_even_when_a_stale_ref_exists(env, capsys):
    _git(env.work, "fetch", "-q", "upstream")          # a ref exists ...
    _push_extra_commit(env, env.upstream, "later.md")  # ... and goes stale
    assert _main(env, "--no-review") == 1
    assert "behind" in capsys.readouterr().out.lower()


def test_the_forks_main_is_never_the_base(env, capsys):
    # The fork's main moving ahead must change nothing: origin is not upstream.
    _push_extra_commit(env, env.fork, "fork-only.md")
    _git(env.work, "fetch", "-q", "origin")
    assert _main(env, "--no-review") == 0
    base_args = [c for c in env.checks.calls if "--base" in c]
    assert base_args and all("--base upstream/main" in c for c in base_args), base_args


def test_a_failing_check_exits_1(env, capsys):
    env.checks.answers = {"check_tml.py": (1, "FAIL  broken.tml\n")}
    assert _main(env, "--no-review") == 1


def test_a_failing_pytest_exits_1(env, capsys):
    env.commands.answers = {"pytest agents/databricks/tests/": (1, "1 failed\n")}
    assert _main(env, "--no-review") == 1


def test_dirty_tree_is_marked(env, capsys):
    (env.work / "README.md").write_text("changed\n")
    assert _main(env, "--no-review") == 0
    path = Path(_git(env.work, "rev-parse", "--absolute-git-dir")) / "pr-ready" / "evidence.md"
    assert "DIRTY" in path.read_text(encoding="utf-8")


def test_pr_only_checks_use_the_upstream_base(env, capsys):
    assert _main(env, "--no-review") == 0
    calls = env.checks.calls
    assert any("suggest_repo_changelog.py --root . --check --base upstream/main" in c for c in calls)
    assert any("check_open_items.py --root . --base upstream/main" in c for c in calls)
    assert any("check_pr_size.py --root . --base upstream/main --warn" in c for c in calls)
    assert any("check_customer_references.py --root . --range upstream/main..HEAD" in c for c in calls)
    assert any("check_ci_gate_coverage.py --root ." in c for c in calls)
    assert any("check_audit_workflow_permissions.py --root ." in c for c in calls)


def test_runs_the_check_list_smokes_and_workflow_pytest(env, capsys):
    assert _main(env, "--no-review") == 0
    scripts = {Path(c.split()[0]).name for c in env.checks.calls}
    assert {c.script for c in checks.CHECKS if c.optional_prereq is None} <= scripts
    assert {f"{s}.py" for s in checks.CI_SMOKES} <= scripts
    pytests = [c for c in env.commands.calls if " -m pytest " in c]
    assert len(pytests) == len(pr_ready.pytest_invocations(env.work)), pytests


# ------------------------------------------------------------- --post ---

def test_post_happens_only_when_green_and_after_the_path(env, capsys):
    assert _main(env, "--no-review", "--post", "42") == 0
    out = capsys.readouterr().out
    assert len(env.posted) == 1
    number, path = env.posted[0]
    assert number == 42 and str(path) in out


def test_post_is_refused_when_not_green(env, capsys):
    _push_extra_commit(env, env.upstream, "upstream-only.md")
    assert _main(env, "--no-review", "--post", "42") == 1
    assert env.posted == []
    assert "not posting" in capsys.readouterr().err.lower()


def test_a_failed_post_fails_the_run(env, monkeypatch, capsys):
    monkeypatch.setattr(pr_ready, "_gh_comment", lambda number, path: 1)
    assert _main(env, "--no-review", "--post", "42") == 1


# ------------------------------------------------ derived from validate.yml ---

def _suite_steps():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["suite"]["steps"]


def _joined_lines(run):
    """Code lines with `\\` continuations joined."""
    out, pending = [], ""
    for line in _code_lines(run):
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        out.append(pending + line)
        pending = ""
    return out


def test_pytest_invocations_are_the_workflows():
    step = [s for s in _suite_steps() if s.get("name") == pr_ready.PYTEST_STEP]
    assert len(step) == 1
    expected = [shlex.split(l)[1:] for l in _code_lines(step[0]["run"]) if l.startswith("pytest ")]
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


_VALIDATOR_CALL = re.compile(r"^python3 (tools/validate/[\w-]+\.py)(.*)$")


def test_every_validator_the_suite_job_runs_is_run_by_pr_ready():
    """The CI-superset claim, checked: each `python3 tools/validate/X.py ...` line in
    the suite job maps to something pr-ready runs, with the same args once
    `origin/${{ github.base_ref }}` is read as the base."""
    mine = {(c.script, c.local_args) for c in pr_ready.PR_CHECKS + pr_ready.EVERY_PR_CHECKS}
    seen, unaccounted = set(), []
    for step in _suite_steps():
        for line in _joined_lines(step.get("run", "")):
            m = _VALIDATOR_CALL.match(line)
            if not m:
                continue
            script = Path(m.group(1)).name
            if script == "run_checks.py":
                continue   # CHECKS / CI_SMOKES: pr-ready runs both through run_checks
            if step["name"] == pr_ready.QUALITY_GATES_STEP and script == "generate_quality_gates.py":
                continue   # the scoped gate, pinned by the next test
            args = tuple(a.replace("origin/${{ github.base_ref }}", "{base}")
                         for a in shlex.split(m.group(2)))
            if (script, args) in mine:
                seen.add((script, args))
            else:
                unaccounted.append(f"{step['name']}: {line}")
    assert not unaccounted, f"CI runs these and pr-ready does not: {unaccounted}"
    assert seen == mine, f"pr-ready runs these and CI does not: {sorted(mine - seen)}"


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
    env.checks.answers = {}
    assert _main(env, "--no-review") == 0
    gates = [c for c in env.checks.calls if "generate_quality_gates.py" in c]
    assert len(gates) == 2, gates   # the soft CHECKS entry and the scoped hard gate


def test_scoped_quality_gates_failure_is_hard(env, capsys):
    (env.work / "tools" / "validate").mkdir(parents=True)
    _commit(env.work, "tools/validate/check_new.py")
    env.checks.answers = {"generate_quality_gates.py": (1, "FAIL  stale\n")}
    assert _main(env, "--no-review") == 1
