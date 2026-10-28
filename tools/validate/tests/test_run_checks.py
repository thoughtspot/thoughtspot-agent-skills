"""Tests for run_checks.py — the one runner CI and pr-ready share.

The runner is where a result becomes a verdict, so these pin the verdict rules:
a check that printed SKIP is never PASS; a check required on every PR whose tool
is missing is FAIL locally (CI has its tools, so there it stays SKIP); an opt-in
check whose prerequisite is absent locally is NOT RUN, never executed and never
FAIL; a soft check's failure is WARN. And they pin how upstream is found: by
URL, never by assuming `origin`, because in a fork `origin` is the fork.

No test here runs a real validator — subprocess.run is replaced with a recorder.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
import subprocess
from pathlib import Path

import pytest

import checks
import run_checks as rc
from checks import Check
from test_checks_parity import RUNNER_CI_CALL, RUNNER_SMOKES_CALL

CANON_HTTPS = "https://github.com/thoughtspot/thoughtspot-agent-skills.git"


# ---------------------------------------------------------------- helpers ---

class FakeRun:
    """Stands in for subprocess.run: records every argv and answers by script name."""

    def __init__(self, answers=None):
        self.answers = answers or {}   # script basename -> (returncode, stdout)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        code, out = self.answers.get(Path(argv[1]).name, (0, "ok\n"))
        return subprocess.CompletedProcess(argv, code, stdout=out, stderr="")

    def scripts(self):
        return [Path(a[1]).name for a, _ in self.calls]


def _fake(monkeypatch, answers=None):
    fake = FakeRun(answers)
    monkeypatch.setattr(rc.subprocess, "run", fake)
    return fake


def _check(id, *, hard=True, prereq=None, ci_args=("--root", ".")):
    return Check(
        id=id,
        script=f"check_{id}.py",
        ci_args=tuple(ci_args),
        local_args=tuple(a.replace("origin/main", "{base}") for a in ci_args),
        hard=hard,
        optional_prereq=prereq,
    )


def _by_id(results):
    return {r["id"]: r for r in results}


# The runner's exact `"{status:7} {id}"` line (NOT RUN adds its reason). A
# validator's own `PASS  file 0` (two spaces, then a space inside) never matches.
_STATUS_LINE = re.compile(
    r"^(?:(?:PASS|FAIL|WARN|SKIP) {4}\S+|NOT RUN \S+(?: \(prerequisite absent: [^)]+\))?)$")


def _status_lines(text):
    return [ln for ln in text.splitlines() if _STATUS_LINE.match(ln)]


def test_status_line_helper_ignores_validator_output():
    text = ("PASS    a\nPASS  file 0\nFAIL  x  ->  broken\nWARN    d\n"
            "NOT RUN opt (prerequisite absent: ossie-checkout)\nSKIP  thing: missing\n")
    assert _status_lines(text) == [
        "PASS    a", "WARN    d", "NOT RUN opt (prerequisite absent: ossie-checkout)"]


@pytest.fixture(autouse=True)
def _not_in_github_actions(monkeypatch):
    # main() formats for a CI log when GITHUB_ACTIONS=true, which is set in CI's
    # own pytest step; every test states the environment it means instead.
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # A developer's ~/.gitconfig can rewrite URLs (`url.*.insteadOf`), which would
    # change what `git remote get-url` prints; isolate from it.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    work = tmp_path / "repo"
    work.mkdir()
    _git(work, "init", "-q")
    return work


# --------------------------------------------------------------- classify ---

def test_classify_skip_line():
    assert rc.classify(0, "SKIP  module health: radon not installed") == "SKIP"
    assert rc.classify(0, "ok") == "PASS"
    assert rc.classify(1, "SKIP") == "FAIL"


def test_classify_skip_must_start_the_line():
    # "Skipping" in prose, or SKIP mid-line, is not the marker.
    assert rc.classify(0, "  nothing to do. Skipping.\nall SKIP here") == "PASS"
    assert rc.classify(0, "header\nSKIP  thing: tool missing\n") == "SKIP"


# -------------------------------------------------------- resolve_upstream ---

def test_resolve_upstream_prefers_canonical_url(repo):
    _git(repo, "remote", "add", "origin", "https://github.com/someone/fork.git")
    _git(repo, "remote", "add", "canon", "git@github.com:thoughtspot/thoughtspot-agent-skills.git")
    assert rc.resolve_upstream(repo) == "canon"


def test_resolve_upstream_adds_remote_when_only_fork(repo):
    _git(repo, "remote", "add", "origin", "https://github.com/someone/fork.git")
    assert rc.resolve_upstream(repo) == "upstream"
    assert _git(repo, "config", "--get", "remote.upstream.url") == CANON_HTTPS


@pytest.mark.parametrize("url", [
    "https://github.com/thoughtspot/thoughtspot-agent-skills",
    "https://github.com/ThoughtSpot/Thoughtspot-Agent-Skills.git",
    "git@github.com:thoughtspot/thoughtspot-agent-skills",
    "git@github.com:THOUGHTSPOT/thoughtspot-agent-skills.git",
    "https://someone@github.com/thoughtspot/thoughtspot-agent-skills.git",
    "ssh://git@github.com/thoughtspot/thoughtspot-agent-skills.git",
    "ssh://git@github.com:22/thoughtspot/thoughtspot-agent-skills.git",
])
def test_resolve_upstream_matches_https_and_ssh_any_case(repo, url):
    _git(repo, "remote", "add", "origin", url)
    assert rc.resolve_upstream(repo, add_if_missing=False) == "origin"


def test_resolve_upstream_rejects_a_lookalike_repo(repo):
    # A fork named the same under another owner, or a prefix-match, is not upstream.
    _git(repo, "remote", "add", "origin", "https://github.com/someone/thoughtspot-agent-skills.git")
    _git(repo, "remote", "add", "other", "https://github.com/thoughtspot/thoughtspot-agent-skills-old.git")
    with pytest.raises(RuntimeError):
        rc.resolve_upstream(repo, add_if_missing=False)


def test_resolve_upstream_raises_without_add(repo):
    _git(repo, "remote", "add", "origin", "https://github.com/someone/fork.git")
    with pytest.raises(RuntimeError):
        rc.resolve_upstream(repo, add_if_missing=False)
    assert "upstream" not in _git(repo, "remote").split()


def test_resolve_upstream_raises_when_upstream_name_is_taken(repo):
    # An existing non-canonical `upstream` must not be silently trusted or overwritten.
    _git(repo, "remote", "add", "upstream", "https://github.com/someone/else.git")
    with pytest.raises(RuntimeError, match="upstream") as err:
        rc.resolve_upstream(repo)
    # The message names the URL it found, so the reader can see why it was refused.
    assert "https://github.com/someone/else.git" in str(err.value)
    assert _git(repo, "config", "--get", "remote.upstream.url") == "https://github.com/someone/else.git"


# ---------------------------------------------------------- prereq_present ---

def test_prereq_present_reuses_the_ossie_checks_own_locator(monkeypatch, tmp_path):
    import check_ossie_mapping_sync as ossie
    monkeypatch.setattr(ossie, "find_upstream", lambda explicit: tmp_path / "doc.md")
    assert rc.prereq_present("ossie-checkout", tmp_path) is True
    monkeypatch.setattr(ossie, "find_upstream", lambda explicit: None)
    assert rc.prereq_present("ossie-checkout", tmp_path) is False


def test_prereq_present_resolves_relative_locations_against_repo_root(monkeypatch, tmp_path):
    # find_upstream's conventional paths are relative ("../ossie"); they must be
    # read from the repo root, not from wherever the runner happened to start.
    import check_ossie_mapping_sync as ossie
    seen = []
    monkeypatch.setattr(ossie, "find_upstream", lambda explicit: seen.append(Path.cwd()))
    rc.prereq_present("ossie-checkout", tmp_path)
    assert seen == [tmp_path.resolve()]
    assert Path.cwd() != tmp_path.resolve()


def test_every_optional_prereq_in_checks_is_known(tmp_path):
    # An unknown id would pass CI (which never asks) and crash every local run.
    prereqs = {c.optional_prereq for c in checks.CHECKS if c.optional_prereq}
    assert prereqs, "expected at least one opt-in check"
    for prereq in prereqs:
        assert rc.prereq_present(prereq, tmp_path) in (True, False)


def test_prereq_present_rejects_an_unknown_prereq(tmp_path):
    with pytest.raises(ValueError):
        rc.prereq_present("no-such-prereq", tmp_path)


# --------------------------------------------------------------------- run ---

def test_ci_context_runs_every_check_in_order_with_ci_args(monkeypatch, tmp_path):
    # The real list: CI must run ALL of it, in CI's order, with CI's exact args,
    # including the optional-prereq check (so it cannot rot unexercised).
    monkeypatch.setattr(rc, "prereq_present", lambda *a: pytest.fail("ci consulted a prereq"))
    fake = _fake(monkeypatch)
    results = rc.run("ci", "origin/main", tmp_path, "py")
    assert [r["id"] for r in results] == [c.id for c in checks.CHECKS]
    assert [a for a, _ in fake.calls] == [
        ["py", str(Path("tools/validate") / c.script), *c.ci_args] for c in checks.CHECKS
    ]
    assert all(kw["cwd"] == tmp_path for _, kw in fake.calls)


def test_ci_context_continues_past_a_hard_failure_and_exits_1(monkeypatch, tmp_path, capsys):
    fakes = (_check("a"), _check("b"), _check("c"), _check("d", hard=False))
    monkeypatch.setattr(rc, "CHECKS", fakes)
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    fake = _fake(monkeypatch, {"check_b.py": (1, "broken\n"), "check_d.py": (1, "stale\n")})
    code = rc.main(["--context", "ci", "--base", "origin/main"])
    assert fake.scripts() == ["check_a.py", "check_b.py", "check_c.py", "check_d.py"]
    assert code == 1
    assert _status_lines(capsys.readouterr().out) == [
        "PASS    a", "FAIL    b", "PASS    c", "WARN    d"]


def test_soft_failure_is_warn_not_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "CHECKS", (_check("a"), _check("soft", hard=False)))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch, {"check_soft.py": (1, "catalog stale\n")})
    results = rc.run("ci", "origin/main", tmp_path, "py")
    assert _by_id(results)["soft"]["status"] == "WARN"
    assert "catalog stale" in _by_id(results)["soft"]["output_tail"]
    assert rc.exit_code(results) == 0
    assert rc.main(["--context", "ci"]) == 0


def test_optional_check_not_run_when_prereq_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "CHECKS", (_check("a"), _check("opt", prereq="ossie-checkout")))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(rc, "prereq_present", lambda prereq, root: False)
    fake = _fake(monkeypatch)
    results = rc.run("local", "upstream/main", tmp_path, "py")
    assert _by_id(results)["opt"]["status"] == "NOT RUN"
    assert _by_id(results)["opt"]["output_tail"] == "ossie-checkout"
    assert fake.scripts() == ["check_a.py"]
    assert rc.exit_code(results) == 0
    assert rc.main(["--context", "local", "--base", "upstream/main"]) == 0


def test_optional_check_runs_locally_when_prereq_present(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "CHECKS", (_check("opt", prereq="ossie-checkout"),))
    monkeypatch.setattr(rc, "prereq_present", lambda prereq, root: True)
    fake = _fake(monkeypatch, {"check_opt.py": (1, "disagrees\n")})
    results = rc.run("local", "upstream/main", tmp_path, "py")
    assert fake.scripts() == ["check_opt.py"]
    assert results[0]["status"] == "FAIL"


def test_ci_context_executes_optional_check_and_keeps_its_skip(monkeypatch, tmp_path):
    # R9: CI always runs it; with no checkout the script SKIPs, which is not a failure.
    monkeypatch.setattr(rc, "CHECKS", (_check("opt", prereq="ossie-checkout"),))
    monkeypatch.setattr(rc, "prereq_present", lambda *a: pytest.fail("ci consulted a prereq"))
    _fake(monkeypatch, {"check_opt.py": (0, "SKIP  ossie mapping sync: no checkout\n")})
    results = rc.run("ci", "origin/main", tmp_path, "py")
    assert results[0]["status"] == "SKIP"
    assert rc.exit_code(results) == 0


def test_local_context_promotes_skip_to_fail_for_required_checks(monkeypatch, tmp_path):
    skip = "SKIP  module health: radon not installed (`pip install radon`); enforced in CI.\n"
    monkeypatch.setattr(rc, "CHECKS", (_check("module-health"),))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch, {"check_module-health.py": (0, skip)})

    local = rc.run("local", "upstream/main", tmp_path, "py")[0]
    assert local["status"] == "FAIL"
    assert "radon not installed" in local["output_tail"]
    assert local["output_tail"].count("required on every PR") == 1
    assert rc.main(["--context", "local", "--base", "upstream/main"]) == 1

    ci = rc.run("ci", "origin/main", tmp_path, "py")[0]
    assert ci["status"] == "SKIP"
    assert rc.main(["--context", "ci", "--base", "origin/main"]) == 0


def test_local_args_substitute_base(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "CHECKS", (
        _check("based", ci_args=("--root", ".", "--base", "origin/main")),
        _check("plain"),
    ))
    fake = _fake(monkeypatch)
    rc.run("local", "upstream/main", tmp_path, "py")
    assert fake.calls[0][0][2:] == ["--root", ".", "--base", "upstream/main"]
    assert fake.calls[1][0][2:] == ["--root", "."]


def test_local_context_needs_a_base_when_a_check_uses_one(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "CHECKS", (_check("based", ci_args=("--base", "origin/main")),))
    _fake(monkeypatch)
    with pytest.raises(ValueError):
        rc.run("local", None, tmp_path, "py")


def test_result_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "CHECKS", (_check("a"),))
    _fake(monkeypatch, {"check_a.py": (0, "\n".join(f"line {i}" for i in range(100)))})
    (r,) = rc.run("ci", "origin/main", tmp_path, "py")
    assert set(r) == {"id", "status", "seconds", "output_tail"}
    assert isinstance(r["seconds"], float)
    assert "line 99" in r["output_tail"] and "line 0\n" not in r["output_tail"]


# ------------------------------------------------- what the CLI shows a reader ---

def test_a_failure_line_outside_the_tail_is_kept(monkeypatch, tmp_path, capsys):
    # check_references prints its FAIL line first, then 170 PASS lines: a plain
    # tail would show only passes for a failed check.
    noisy = "FAIL  x  ->  broken link\n" + "".join(f"PASS  file {i}\n" for i in range(100))
    monkeypatch.setattr(rc, "CHECKS", (_check("refs"),))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch, {"check_refs.py": (1, noisy)})

    (r,) = rc.run("ci", "origin/main", tmp_path, "py")
    assert "FAIL  x  ->  broken link" in r["output_tail"]
    assert "PASS  file 99" in r["output_tail"]
    assert "PASS  file 0\n" not in r["output_tail"]

    for context in ("ci", "local"):
        assert rc.main(["--context", context, "--base", "origin/main"]) == 1
        printed = capsys.readouterr()
        shown = printed.out + printed.err
        assert "FAIL  x  ->  broken link" in shown
        assert "PASS  file 0" in shown   # a non-PASS result prints its FULL output


def test_tail_keeps_error_and_traceback_lines():
    out = "Traceback (most recent call last):\nERROR boom\n" + "x\n" * 200
    tail = rc._tail(out)
    assert "Traceback (most recent call last):" in tail and "ERROR boom" in tail


def test_ci_prints_pass_output_in_a_collapsed_group(monkeypatch, tmp_path, capsys):
    # check_customer_references emits GitHub annotations and exits 0; dropping a
    # PASS's output would silently drop them from CI.
    warning = "::warning title=Customer reference::possible tenant link in x.md"
    monkeypatch.setattr(rc, "CHECKS", (_check("refs"),))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch, {"check_refs.py": (0, warning + "\nall good\n")})
    assert rc.main(["--context", "ci"]) == 0
    out = capsys.readouterr().out.splitlines()
    start, end = out.index("::group::refs"), out.index("::endgroup::")
    assert start < out.index(warning) < end
    assert out.index("PASS    refs") < start


def test_local_does_not_print_pass_output(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rc, "CHECKS", (_check("a"),))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch, {"check_a.py": (0, "chatter\n")})
    assert rc.main(["--context", "local", "--base", "upstream/main"]) == 0
    printed = capsys.readouterr()
    assert "chatter" not in printed.out + printed.err
    assert "::group::" not in printed.out


def test_github_actions_formats_a_ci_log_even_without_ci_context(
        monkeypatch, tmp_path, capsys):
    # A bare `--smokes` in CI has no --context, so the Actions env decides: PASS
    # output folded in ::group:: on stdout, so annotations still register.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch, {f"{checks.CI_SMOKES[0]}.py": (0, "::warning::smoke note\n")})
    assert rc.main(["--smokes"]) == 0
    out = capsys.readouterr().out.splitlines()
    group = f"::group::{checks.CI_SMOKES[0]}"
    assert out.index(group) < out.index("::warning::smoke note") < out.index("::endgroup::")


def test_without_github_actions_a_bare_smokes_run_is_local_style(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch, {f"{checks.CI_SMOKES[0]}.py": (0, "::warning::smoke note\n")})
    assert rc.main(["--smokes"]) == 0
    printed = capsys.readouterr()
    assert "::group::" not in printed.out and "smoke note" not in printed.out + printed.err


def test_a_promoted_skip_prints_its_skip_line_once(monkeypatch, tmp_path, capsys):
    skip = "SKIP  module health: radon not installed (`pip install radon`); enforced in CI.\n"
    monkeypatch.setattr(rc, "CHECKS", (_check("module-health"),))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch, {"check_module-health.py": (0, skip)})
    assert rc.main(["--context", "local", "--base", "upstream/main"]) == 1
    printed = capsys.readouterr()
    shown = printed.out + printed.err
    assert shown.count("radon not installed") == 1
    assert "required on every PR" in shown


def test_not_run_reason_is_on_the_cli_line(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rc, "CHECKS", (_check("opt", prereq="ossie-checkout"),))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(rc, "prereq_present", lambda prereq, root: False)
    _fake(monkeypatch)
    assert rc.main(["--context", "local", "--base", "upstream/main"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "NOT RUN opt (prerequisite absent: ossie-checkout)"]


def test_undecodable_output_does_not_abort_the_run(tmp_path):
    # Real subprocess: one byte that is not UTF-8 must not raise UnicodeDecodeError.
    script = tmp_path / "bad.py"
    script.write_text("import sys\nsys.stdout.buffer.write(b'ok \\xff\\xfe end\\n')\n",
                      encoding="utf-8")
    code, output, _ = rc._execute(sys.executable, script, (), tmp_path)
    assert code == 0 and output.startswith("ok ") and output.rstrip().endswith("end")


# ------------------------------------------------------------------ smokes ---

def test_run_smokes_runs_every_ci_smoke(monkeypatch, tmp_path):
    fake = _fake(monkeypatch, {f"{checks.CI_SMOKES[1]}.py": (1, "boom\n")})
    results = rc.run_smokes(tmp_path, "py")
    assert [r["id"] for r in results] == list(checks.CI_SMOKES)
    assert [a for a, _ in fake.calls] == [
        ["py", str(Path("tools/smoke-tests") / f"{s}.py")] for s in checks.CI_SMOKES
    ]
    assert results[1]["status"] == "FAIL"
    assert rc.exit_code(results) == 1


def test_cli_smokes_continues_past_a_failure_and_exits_1(monkeypatch, tmp_path, capsys):
    # CI's smoke step is exactly `run_checks.py --smokes`, so this exit code is the
    # only thing that can turn the step red. A main() that ran the suites but
    # dropped their results would print every failure and still exit 0.
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    failing = checks.CI_SMOKES[1]
    fake = _fake(monkeypatch, {f"{failing}.py": (1, "boom\n")})
    code = rc.main(["--smokes"])
    assert [Path(a[1]).stem for a, _ in fake.calls] == list(checks.CI_SMOKES)
    assert code == 1
    assert _status_lines(capsys.readouterr().out) == [
        f"{'FAIL' if s == failing else 'PASS':7} {s}" for s in checks.CI_SMOKES]


# --------------------------------------------------------------------- CLI ---

def test_cli_accepts_the_invocations_ci_will_use(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch)
    for call in (RUNNER_CI_CALL, RUNNER_SMOKES_CALL):
        argv = shlex.split(call)
        assert argv[:2] == ["python3", "tools/validate/run_checks.py"]
        assert rc.main(argv[2:]) == 0
    out = capsys.readouterr().out
    assert "PASS    secrets" in out and f"PASS    {checks.CI_SMOKES[0]}" in out


def test_cli_requires_a_context_or_smokes():
    with pytest.raises(SystemExit):
        rc.main([])


def test_cli_ci_context_refuses_a_base_its_args_do_not_use(monkeypatch, tmp_path):
    # ci_args are CI's literal args (origin/main); a different --base would be ignored.
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch)
    with pytest.raises(SystemExit):
        rc.main(["--context", "ci", "--base", "upstream/main"])


def test_cli_writes_json(monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "CHECKS", (_check("a"),))
    monkeypatch.setattr(rc, "REPO_ROOT", tmp_path)
    _fake(monkeypatch)
    out = tmp_path / "r.json"
    assert rc.main(["--context", "ci", "--json", str(out)]) == 0
    data = json.loads(out.read_text())
    assert [r["id"] for r in data] == ["a"] and data[0]["status"] == "PASS"
