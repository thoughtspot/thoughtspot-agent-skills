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
#: The real gh runner, captured before any fixture replaces it.
_REAL_GH = pr_ready._gh


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

    def __init__(self, answers=None, default="ok\n"):
        self.answers = answers or {}   # substring of the joined argv -> (code, output)
        self.default = default
        self.calls = []

    def answer(self, argv):
        joined = " ".join(str(a) for a in argv)
        self.calls.append(joined)
        for key, (code, out) in self.answers.items():
            if key in joined:
                return code, out, 0.01
        return 0, self.default, 0.01


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
    # pr-ready itself exports it when it runs this suite; the remedy text depends on it.
    monkeypatch.delenv("CHECKS_PYTHON", raising=False)
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
    # pytest's real closing line: without one the skip count is unverifiable (FAIL).
    commands = Recorder(default="..\n2 passed in 0.01s\n")
    monkeypatch.setattr(pr_ready, "_run_command", lambda argv, root, env=None: commands.answer(argv))
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
    assert all(c.endswith(" -rs --color=no") for c in pytests), pytests


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
        0, "..s\nSKIPPED [2] tools/b/test_y.py:20: $DATA not set\n2 passed, 2 skipped in 0.1s\n")}
    assert _main(env, "--no-review") == 0
    section = _evidence(env)[1].split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "tools/b/test_y.py:20: $DATA not set (x2)" in section, section
    assert "None." not in section


_COLOURED = ("\x1b[33m..s\x1b[0m\n"
             "\x1b[33mSKIPPED\x1b[0m [1] tools/a/test_x.py:10: No module named 'openpyxl'\n"
             "\x1b[32m1 passed\x1b[0m, \x1b[33m1 skipped\x1b[0m in 0.10s\n")


def test_coloured_skip_lines_are_still_read(env, capsys):
    # FORCE_COLOR / PY_COLORS colour SKIPPED even when piped; --color=no is passed,
    # and ANSI is stripped anyway, so a missing-module skip still FAILs.
    env.commands.answers = {"pytest agents/databricks/tests/": (0, _COLOURED)}
    assert _main(env, "--no-review") == 1
    assert "No module named 'openpyxl'" in _evidence(env)[1]


def test_skips_with_no_skip_report_are_unverifiable_not_zero(env, capsys):
    # e.g. PYTEST_ADDOPTS=--no-summary: the stats line says 4 skipped, -rs lists none.
    env.commands.answers = {"pytest agents/databricks/tests/": (0, "....ssss\n4 passed, 4 skipped in 0.2s\n")}
    assert _main(env, "--no-review") == 1
    section = _evidence(env)[1].split("## NOT RUN and SKIP", 1)[1].split("\n## ", 1)[0]
    assert "reported 4 skipped but its -rs report lists 0" in section, section


def test_a_skip_count_mismatch_is_fail(env, capsys):
    env.commands.answers = {"pytest agents/databricks/tests/": (
        0, "SKIPPED [1] a.py:1: $D unset\n3 passed, 2 skipped in 0.2s\n")}
    assert _main(env, "--no-review") == 1


def test_a_missing_stats_line_is_unverifiable(env, capsys):
    env.commands.answers = {"pytest agents/databricks/tests/": (0, "....\n")}
    assert _main(env, "--no-review") == 1
    assert "stats line was not found" in _evidence(env)[1]


def test_pytest_runs_without_pytest_addopts(env, monkeypatch, capsys):
    seen = []
    monkeypatch.setenv("PYTEST_ADDOPTS", "--no-summary -k nothing")
    monkeypatch.setattr(pr_ready, "_run_command",
                        lambda argv, root, env=None: seen.append(env) or (0, "1 passed in 0.1s\n", 0.0))
    assert _main(env, "--no-review") == 0
    pytest_envs = [e for e in seen if e is not None]
    assert pytest_envs and all("PYTEST_ADDOPTS" not in e for e in pytest_envs)


@pytest.mark.parametrize("reason, missing", [
    ("could not import 'radon': No module named 'radon'", True),
    ("""no 2020-12 jsonschema here: AttributeError("module 'jsonschema' has no attribute 'Draft202012Validator'")""", True),
    ("""x: ImportError('cannot import name Y')""", True),
    ("node is not installed", False),
    ("no Chrome here", False),
    ("$FORMULA_FIDELITY_DATA not set", False),
])
def test_which_skips_are_a_missing_tool(env, capsys, reason, missing):
    env.commands.answers = {"pytest agents/databricks/tests/": (
        0, f"SKIPPED [1] t.py:1: {reason}\n1 passed, 1 skipped in 0.1s\n")}
    assert _main(env, "--no-review") == (1 if missing else 0)
    text = _evidence(env)[1]
    if not missing:
        assert "CI's `ubuntu-latest` runner has node and Chrome" in text


def test_a_missing_module_fail_prints_cis_installs_as_the_remedy(env, capsys):
    # "Install what CI installs" is only a remedy if it says what that is, exactly.
    env.commands.answers = {"pytest agents/databricks/tests/": (0, _SKIPS)}
    assert _main(env, "--no-review") == 1
    err = capsys.readouterr().err
    assert pr_ready.SUITE_PIP_INSTALLS, "no remedy to print"
    for line in pr_ready.SUITE_PIP_INSTALLS:
        assert line in err, (line, err)
    # Named for the interpreter that ran, without the path to it (a home directory).
    assert "python3 -m pip" in err, err


def test_the_install_remedy_offers_the_virtual_environment_route(monkeypatch):
    # A uv- or Homebrew-managed Python refuses `pip install`; the remedy must not be a
    # dead end there (BL-436).
    monkeypatch.delenv("CHECKS_PYTHON", raising=False)
    text = "\n".join(pr_ready._install_remedy("/somewhere/bin/python3.12"))
    assert "CHECKS_PYTHON" in text and ".github/CONTRIBUTING.md" in text, text
    assert "uv pip install --python" in text, text
    assert "python3.12 -m pip install" in text, text
    assert "/somewhere" not in text, "the interpreter's path can name a home directory"


def test_the_install_remedy_targets_checks_python_when_it_is_set(monkeypatch):
    # The run used the interpreter the variable names: install into that one, named by
    # the variable (its value can be a home directory), and do not tell the user to
    # set what is already set.
    monkeypatch.setenv("CHECKS_PYTHON", "/somewhere/venv/bin/python3.12")
    text = "\n".join(pr_ready._install_remedy("/somewhere/venv/bin/python3.12"))
    assert '"$CHECKS_PYTHON" -m pip install' in text, text
    assert 'uv pip install --python "$CHECKS_PYTHON"' in text, text
    assert "set CHECKS_PYTHON" not in text.lower(), text
    assert "/somewhere" not in text, text
    for line in pr_ready.SUITE_PIP_INSTALLS:
        assert line in text, (line, text)


def _without_yaml(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_yaml)


def test_a_missing_pyyaml_names_the_virtual_environment_route(monkeypatch, tmp_path):
    monkeypatch.delenv("CHECKS_PYTHON", raising=False)
    _without_yaml(monkeypatch)
    with pytest.raises(RuntimeError) as caught:
        pr_ready._workflow(tmp_path)
    message = str(caught.value)
    assert "pip install pyyaml" in message
    assert "CHECKS_PYTHON" in message and ".github/CONTRIBUTING.md" in message, message


def test_a_missing_pyyaml_targets_checks_python_when_it_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("CHECKS_PYTHON", "/somewhere/venv/bin/python3.12")
    _without_yaml(monkeypatch)
    with pytest.raises(RuntimeError) as caught:
        pr_ready._workflow(tmp_path)
    message = str(caught.value)
    assert '"$CHECKS_PYTHON" -m pip install pyyaml' in message, message
    assert 'uv pip install --python "$CHECKS_PYTHON"' in message, message
    assert "set CHECKS_PYTHON" not in message.lower(), message
    assert "/somewhere" not in message, message


def test_no_install_remedy_without_a_missing_module(env, capsys):
    env.commands.answers = {"pytest agents/databricks/tests/": (
        0, "..s\nSKIPPED [1] tools/b/test_y.py:20: $DATA not set\n2 passed, 1 skipped in 0.1s\n")}
    assert _main(env, "--no-review") == 0
    assert "pip install" not in capsys.readouterr().err


def test_the_install_remedy_is_the_suite_jobs_installs_in_order():
    # Read from the workflow each time it is checked: a hand copy that drifted would
    # send a contributor to install the wrong thing.
    lines = [line for step in _suite_steps() for line in pr_ready._code_lines(step.get("run", ""))
             if line.startswith("pip install")]
    assert list(pr_ready.SUITE_PIP_INSTALLS) == lines
    assert set(pr_ready.SUITE_PIP_INSTALLS) <= pr_ready._PIP_INSTALLS


# -------------------------------------------------------- stale evidence ---

def test_a_run_that_cannot_start_replaces_an_earlier_ready_block(env, capsys):
    assert _main(env, "--no-review") == 0
    assert "**READY**" in _evidence(env)[1]
    wf = env.work / ".github" / "workflows" / "validate.yml"
    wf.write_text(wf.read_text() + "\n  bad: [unclosed\n")
    assert _main(env, "--no-review") == 2
    text = _evidence(env)[1]
    assert "**READY**" not in text and "NOT READY" in text, text


def test_a_crash_mid_run_leaves_not_ready(env, monkeypatch, capsys):
    assert _main(env, "--no-review") == 0
    def boom(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(rc, "run_smokes", boom)
    with pytest.raises(KeyboardInterrupt):
        _main(env, "--no-review")
    assert "NOT READY" in _evidence(env)[1]


@pytest.mark.parametrize("argv", [("--post", "0"), ("--post", "abc"), ("--no-such-flag",)])
def test_an_argument_error_replaces_an_earlier_ready_block(env, capsys, argv):
    # argparse exits 2 on a bad argument, before anything else in main() runs; the
    # placeholder must already be written by then.
    assert _main(env, "--no-review") == 0
    assert "**READY**" in _evidence(env)[1]
    with pytest.raises(SystemExit) as exc:
        _main(env, *argv)
    assert exc.value.code == 2
    text = _evidence(env)[1]
    assert "**READY**" not in text and "NOT READY" in text, text


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


def test_post_is_refused_when_gh_pr_view_fails(env, monkeypatch, capsys):
    calls = []
    def gh(args):
        calls.append(list(args))
        if args[:2] == ["pr", "view"]:
            return 1, "", "GraphQL: Could not resolve to a PullRequest with the number of 42."
        return 0, "posted", ""
    monkeypatch.setattr(pr_ready, "_gh", gh)
    assert _main(env, "--no-review", "--post", "42") == 1
    assert [c for c in calls if c[:2] == ["pr", "comment"]] == []
    assert "could not read PR #42" in capsys.readouterr().err


def test_post_is_refused_when_gh_is_absent(env, monkeypatch, capsys):
    # The real _gh, pointed at an executable that does not exist. (Not by emptying
    # PATH: inside a git hook `which git` can be macOS's /usr/bin/git shim, which
    # needs more of PATH than itself, and the pre-post re-check runs git.)
    monkeypatch.setattr(pr_ready, "_gh", _REAL_GH)
    monkeypatch.setattr(pr_ready, "GH", "gh-not-installed-for-this-test")
    assert _main(env, "--no-review", "--post", "42") == 1
    assert "gh is not installed" in capsys.readouterr().err


def test_post_is_refused_when_head_moves_during_the_run(env, monkeypatch, capsys):
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    original = rc.run_smokes
    def commit_meanwhile(*a, **k):
        _commit(env.work, "meanwhile.md")
        return original(*a, **k)
    monkeypatch.setattr(rc, "run_smokes", commit_meanwhile)
    assert _main(env, "--no-review", "--post", "42") == 1
    assert env.gh.calls == []
    assert "changed during the run" in capsys.readouterr().err


def test_post_is_refused_when_the_tree_changes_during_the_run(env, monkeypatch, capsys):
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    original = rc.run_smokes
    def edit_meanwhile(*a, **k):
        (env.work / "README.md").write_text("edited mid-run\n")
        return original(*a, **k)
    monkeypatch.setattr(rc, "run_smokes", edit_meanwhile)
    assert _main(env, "--no-review", "--post", "42") == 1
    assert env.gh.calls == []


def test_post_scans_the_block_with_both_scanners_before_posting(env, monkeypatch, capsys):
    # The block is about to become a public PR comment: the same two scans the
    # pr-ready skill runs before it shares one (Step 6), every line of the file.
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    scanned_before_comment = []
    def gh(args):
        if args[:2] == ["pr", "comment"]:
            scanned_before_comment.extend(env.checks.calls)
        return env.gh(args)
    monkeypatch.setattr(pr_ready, "_gh", gh)
    assert _main(env, "--no-review", "--post", "42") == 0
    path = str(_evidence(env)[0])
    assert len(env.gh.comments()) == 1
    assert any(c.endswith(f"check_secrets.py --file {path}") for c in scanned_before_comment)
    assert any(c.endswith(f"check_customer_references.py --text-file {path}")
               for c in scanned_before_comment)


@pytest.mark.parametrize("key, answer", [
    ("check_secrets.py --file", (1, "FAIL  evidence.md:12: [github-token] <redacted>\n")),
    ("check_customer_references.py --text-file", (1, "FAIL  evidence.md:9: [sharepoint] <redacted>\n")),
    # Exit 0 with a WARN line: a personal detail. The skill stops on it; so does --post.
    ("check_customer_references.py --text-file",
     (0, "WARN  evidence.md:3: [personal-email] <redacted>\nNo customer references.\n")),
])
def test_post_is_refused_when_a_scanner_finds_something(env, capsys, key, answer):
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    env.checks.answers = {key: answer}
    assert _main(env, "--no-review", "--post", "42") == 1
    assert env.gh.comments() == []
    err = capsys.readouterr().err
    assert "not posting" in err.lower() and key.split()[0] in err, err


def test_post_is_refused_when_a_scanner_cannot_run(env, monkeypatch, capsys):
    env.gh.head = _git(env.work, "rev-parse", "HEAD")
    original = rc._execute
    def execute(python, script, args, root):
        if "--file" in args or "--text-file" in args:
            raise FileNotFoundError("no interpreter")
        return original(python, script, args, root)
    monkeypatch.setattr(rc, "_execute", execute)
    assert _main(env, "--no-review", "--post", "42") == 1
    assert env.gh.comments() == []


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


_PYTEST_STEP_HEAD = "        if: ${{ !cancelled() }}\n        run: |\n          pytest tools/ts-cli/tests/"


@pytest.mark.parametrize("key", [
    "env:\n          PYTEST_ADDOPTS: \"-W error\"\n",
    "working-directory: tools\n",
    "shell: bash -c \"exit 0\" {0}\n",
    "continue-on-error: true\n",
])
def test_a_step_key_that_changes_what_runs_is_caught(tmp_path, key):
    orig = WORKFLOW.read_text(encoding="utf-8")
    assert _PYTEST_STEP_HEAD in orig
    text = orig.replace("        if: ${{ !cancelled() }}\n        run: |\n          pytest tools/ts-cli/tests/",
                        "        if: ${{ !cancelled() }}\n        " + key
                        + "        run: |\n          pytest tools/ts-cli/tests/", 1)
    assert text != orig
    assert _mutated(tmp_path, text)


@pytest.mark.parametrize("snippet", [
    "    uses: ./.github/workflows/extra-gates.yml\n",
    "    env:\n      FOO: bar\n",
    "    defaults:\n      run:\n        shell: bash -c \"exit 0\" {0}\n",
    "    continue-on-error: true\n",
])
def test_a_job_key_that_changes_what_runs_is_caught(tmp_path, snippet):
    orig = WORKFLOW.read_text(encoding="utf-8")
    head = "  pytest-matrix:\n    if: github.event_name != 'schedule'\n"
    assert head in orig
    assert _mutated(tmp_path, orig.replace(head, head + snippet, 1))


def test_a_workflow_level_env_is_caught(tmp_path):
    orig = WORKFLOW.read_text(encoding="utf-8")
    assert _mutated(tmp_path, orig.replace("jobs:\n", "env:\n  FOO: bar\n\njobs:\n", 1))


def test_the_quality_gates_gate_moved_into_else_is_caught(tmp_path):
    orig = WORKFLOW.read_text(encoding="utf-8")
    line = ('            echo "No quality-gates source of truth changed in this PR — '
            'skipping hard gate (soft-checked above)."\n')
    assert line in orig
    text = orig.replace(line, "            python3 tools/validate/generate_quality_gates.py --root . --check\n", 1)
    assert _mutated(tmp_path, text)


def test_else_and_fi_outside_the_quality_gates_step_are_caught(tmp_path):
    orig = WORKFLOW.read_text(encoding="utf-8")
    anchor = "          python3 tools/validate/check_ci_gate_coverage.py --root .\n"
    assert anchor in orig
    assert _mutated(tmp_path, orig.replace(anchor, anchor + "          fi\n", 1))


def test_a_new_conditional_exit_in_the_aggregate_job_is_caught(tmp_path):
    orig = WORKFLOW.read_text(encoding="utf-8")
    text = orig.replace("      - name: All gates green\n",
                        "      - name: Block drafts\n        if: github.event.pull_request.draft\n"
                        "        run: exit 1\n\n      - name: All gates green\n", 1)
    assert text != orig and _mutated(tmp_path, text)


def test_a_changed_pip_install_is_caught(tmp_path):
    orig = WORKFLOW.read_text(encoding="utf-8")
    text = orig.replace("pip install pytest pyyaml radon pip-audit jsonschema==4.25.1",
                        "pip install pytest pyyaml radon pip-audit jsonschema==4.25.1 && ./x.sh", 1)
    assert text != orig and _mutated(tmp_path, text)


def test_a_malformed_workflow_is_a_clear_error(tmp_path):
    orig = WORKFLOW.read_text(encoding="utf-8")
    with pytest.raises(RuntimeError, match="cannot read"):
        _mutated(tmp_path, orig + "\n  bad: [unclosed\n")


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
