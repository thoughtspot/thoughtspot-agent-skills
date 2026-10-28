#!/usr/bin/env python3
"""run_checks.py — run the PR check list (`checks.CHECKS`) and say what each result means.

CI's full-repo step and a contributor's local pre-PR run need the same list run
the same way, and before this they had neither: CI listed validators inline in
the workflow, and locally there was nothing to run. This runner is the one place
both call, so the verdict rules live here once:

- **PASS / FAIL** — the script's exit code.
- **SKIP** — the script exited 0 but printed a line starting `SKIP`, i.e. it
  checked nothing (`check_module_health` without radon does this). Exit 0 alone
  would read as PASS, which is the failure this classification exists to stop.
- **SKIP becomes FAIL locally** for a check every PR must pass: CI installs its
  tools, so a local SKIP there means the contributor's run checked less than CI
  will — "a missing tool is FAIL when the check is required for every PR". In
  CI it stays SKIP and does not fail the run, matching CI before this runner.
- **NOT RUN** — locally only, an opt-in check (`optional_prereq`) whose
  prerequisite is absent is listed but never executed and never FAIL. CI always
  executes such checks, so the script path is exercised and cannot rot.
- **WARN** — a soft check (`hard=False`) that failed. Never affects the exit code.

Every check runs even after a failure, and the exit code is 1 if anything is
FAIL at the end — CI's previous `|| rc=1` behaviour.

Upstream is found **by URL**, never by assuming `origin`: in a fork, `origin` is
the fork, and comparing against the fork's `main` would check the wrong base.

Must import and run on Python 3.9 (the system interpreter): no runtime `X | Y`
types, no `match`.

Usage:
    python3 tools/validate/run_checks.py --context ci --base origin/main
    python3 tools/validate/run_checks.py --context local           # resolves upstream
    python3 tools/validate/run_checks.py --smokes
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import CHECKS, CI_SMOKES, Check  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_DIR = Path("tools/validate")
SMOKE_DIR = Path("tools/smoke-tests")

CANONICAL_REPO = "thoughtspot/thoughtspot-agent-skills"
CANONICAL_URL = f"https://github.com/{CANONICAL_REPO}.git"
#: The ref CHECKS' `ci_args` hardcode; `--context ci` runs those args verbatim.
CI_BASE = "origin/main"
#: How many trailing lines of a check's output `output_tail` keeps, on top of
#: every line that reports a failure (see `_tail`).
TAIL_LINES = 40
#: Lines `output_tail` keeps wherever they fall: a validator often prints its
#: FAIL first and then a long run of PASS lines, which a plain tail would hide.
_KEEP_PREFIXES = ("FAIL", "ERROR", "Traceback")

_CANONICAL_URL_RE = re.compile(
    r"^(?:https://(?:[^@/]+@)?github\.com/"
    r"|ssh://git@github\.com(?::22)?/"
    r"|git@github\.com:)"
    + re.escape(CANONICAL_REPO)
    + r"(?:\.git)?/?$",
    re.IGNORECASE,
)

Result = Dict[str, object]


# ------------------------------------------------------------------ upstream ---

def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def resolve_upstream(repo_root: Path, *, add_if_missing: bool = True) -> str:
    """The remote whose fetch URL is the canonical repo, in https or ssh form.

    With none, add `upstream` pointing at the canonical https URL (a fork clone
    usually has only `origin` = the fork). It is not fetched here.
    """
    listed = _git(repo_root, "remote")
    if listed.returncode != 0:
        raise RuntimeError(f"git remote failed in {repo_root}: {listed.stderr.strip()}")
    names = listed.stdout.split()
    matches = []
    for name in names:
        url = _git(repo_root, "remote", "get-url", name).stdout.strip()
        if _CANONICAL_URL_RE.match(url):
            matches.append(name)
    if matches:
        # Several remotes can point at upstream; prefer the conventional names.
        for preferred in ("upstream", "origin"):
            if preferred in matches:
                return preferred
        return sorted(matches)[0]
    if not add_if_missing:
        raise RuntimeError(f"no git remote points at {CANONICAL_REPO}")
    if "upstream" in names:
        existing = _git(repo_root, "remote", "get-url", "upstream").stdout.strip()
        raise RuntimeError(
            f"remote 'upstream' exists but points at {existing!r}, not {CANONICAL_REPO}; "
            f"add a remote for {CANONICAL_URL}"
        )
    added = _git(repo_root, "remote", "add", "upstream", CANONICAL_URL)
    if added.returncode != 0:
        raise RuntimeError(f"could not add remote 'upstream': {added.stderr.strip()}")
    return "upstream"


# ------------------------------------------------------------------- prereqs ---

@contextlib.contextmanager
def _cwd(path: Path) -> Iterator[None]:
    before = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


def prereq_present(prereq: str, repo_root: Path) -> bool:
    """Whether an opt-in check's prerequisite exists on this machine.

    `ossie-checkout` asks the ossie check's own locator, so this cannot disagree
    with where the check itself would look. Its conventional locations are
    relative ("../ossie"), so they are read from the repo root, as the check is.
    """
    if prereq == "ossie-checkout":
        import check_ossie_mapping_sync as ossie
        with _cwd(repo_root):
            return ossie.find_upstream(None) is not None
    raise ValueError(f"unknown optional_prereq {prereq!r}")


# ------------------------------------------------------------------ classify ---

def classify(returncode: int, output: str) -> str:
    """FAIL on a non-zero exit; SKIP if any line starts `SKIP`; otherwise PASS."""
    if returncode != 0:
        return "FAIL"
    if any(line.startswith("SKIP") for line in output.splitlines()):
        return "SKIP"
    return "PASS"


def _tail(output: str, keep: Sequence[str] = _KEEP_PREFIXES) -> str:
    """The last TAIL_LINES lines, plus every earlier line starting with a `keep`
    prefix, in their original order; `...` marks each gap."""
    lines = output.rstrip("\n").splitlines()
    first_of_tail = max(0, len(lines) - TAIL_LINES)
    wanted = [i for i, ln in enumerate(lines[:first_of_tail]) if ln.startswith(tuple(keep))]
    wanted += range(first_of_tail, len(lines))
    out: List[str] = []
    previous = -1
    for i in wanted:
        if i != previous + 1:
            out.append("...")
        out.append(lines[i])
        previous = i
    return "\n".join(out)


def _execute(python: str, script: Path, args: Sequence[str], repo_root: Path):
    started = time.monotonic()
    # Lenient decoding: one undecodable byte from one validator must not abort the run.
    proc = subprocess.run([python, str(script), *args], cwd=repo_root,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output, round(time.monotonic() - started, 2)


def _args_for(check: Check, context: str, base: Optional[str]) -> List[str]:
    if context == "ci":
        return list(check.ci_args)
    if any("{base}" in a for a in check.local_args):
        if not base:
            raise ValueError(f"check {check.id!r} needs a base ref; pass --base")
        return [a.replace("{base}", base) for a in check.local_args]
    return list(check.local_args)


#: Reported once, above the check's own output, which carries the SKIP line itself.
_PROMOTED = "required on every PR, but skipped here (missing tool):"

#: `report(result, output)`: `output` is the check's FULL output (with the
#: promotion note prepended, if any), or "" for a check that was not executed.
Reporter = Callable[[Result, str], None]


def _run_one(check: Check, context: str, base: Optional[str], repo_root: Path,
             python: str):
    """(result, full output) for one check."""
    if context == "local" and check.optional_prereq is not None \
            and not prereq_present(check.optional_prereq, repo_root):
        return {"id": check.id, "status": "NOT RUN", "seconds": 0.0,
                "output_tail": check.optional_prereq}, ""

    code, output, seconds = _execute(python, VALIDATE_DIR / check.script,
                                     _args_for(check, context, base), repo_root)
    status = classify(code, output)
    tail = _tail(output)
    if status == "SKIP" and context == "local" and check.optional_prereq is None:
        status = "FAIL"
        tail = f"{_PROMOTED}\n{_tail(output, _KEEP_PREFIXES + ('SKIP',))}"
        output = f"{_PROMOTED}\n{output}"
    if status == "FAIL" and not check.hard:
        status = "WARN"
    return {"id": check.id, "status": status, "seconds": seconds, "output_tail": tail}, output


def run(context: str, base: Optional[str], repo_root: Path, python: str,
        report: Optional[Reporter] = None) -> List[Result]:
    """Run every check in CHECKS, in order, never stopping early.

    `context` is "ci" (CI's literal `ci_args`) or "local" (`local_args` with
    `{base}` substituted). `report`, if given, is called with each result and
    the check's full output as it lands, so a long run shows progress.
    """
    if context not in ("ci", "local"):
        raise ValueError(f"context must be 'ci' or 'local', not {context!r}")
    if context == "local":
        # Fail before running anything rather than half-way through.
        for check in CHECKS:
            _args_for(check, context, base)
    results = []
    for check in CHECKS:
        result, output = _run_one(check, context, base, repo_root, python)
        results.append(result)
        if report:
            report(result, output)
    return results


def run_smokes(repo_root: Path, python: str,
               report: Optional[Reporter] = None) -> List[Result]:
    """Run CI's credential-free smoke suites. Context-free: they take no args."""
    results = []
    for suite in CI_SMOKES:
        code, output, seconds = _execute(python, SMOKE_DIR / f"{suite}.py", (), repo_root)
        result = {"id": suite, "status": classify(code, output), "seconds": seconds,
                  "output_tail": _tail(output)}
        results.append(result)
        if report:
            report(result, output)
    return results


def exit_code(results: Sequence[Result]) -> int:
    """1 if any result is FAIL. WARN, SKIP and NOT RUN never fail the run."""
    return 1 if any(r["status"] == "FAIL" for r in results) else 0


# ----------------------------------------------------------------------- CLI ---

def _reporter(ci_log: bool) -> Reporter:
    """Print one status line per check, then what a reader needs of its output.

    Non-PASS results print their FULL output: a validator's FAIL line can be
    anywhere in it. In a CI log (`ci_log`) everything goes to stdout unindented,
    so GitHub workflow commands (`::warning ...`) still register, and a PASS's
    output is printed too, folded into a `::group::` — validators emit
    annotations and soft warnings while exiting 0, and CI showed those before
    this runner existed. Locally stdout carries only status lines; non-PASS
    output goes to stderr, indented, and a PASS stays quiet.
    """
    def report(result: Result, output: str) -> None:
        status, check_id = result["status"], result["id"]
        if status == "NOT RUN":
            print(f"{status:7} {check_id} (prerequisite absent: {result['output_tail']})",
                  flush=True)
            return
        print(f"{status:7} {check_id}", flush=True)
        body = output.rstrip("\n")
        if not body:
            return
        if ci_log:
            if status == "PASS":
                print(f"::group::{check_id}\n{body}\n::endgroup::", flush=True)
            else:
                print(body, flush=True)
        elif status != "PASS":
            for line in body.splitlines():
                print(f"    {line}", file=sys.stderr)
            sys.stderr.flush()
    return report


def _local_base(repo_root: Path) -> str:
    """`refs/remotes/<upstream>/main`, fetched if absent (not refreshed if present;
    pr-ready always fetches). In full, because the short `<upstream>/main` resolves
    to a local branch or tag of that name first, which would silently be the base."""
    remote = resolve_upstream(repo_root)
    ref = f"refs/remotes/{remote}/main"
    if _git(repo_root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode != 0:
        print(f"run_checks: fetching {remote} main", file=sys.stderr)
        fetched = _git(repo_root, "fetch", "--quiet", "--no-tags", remote,
                       f"+refs/heads/main:{ref}")
        if fetched.returncode != 0:
            raise RuntimeError(f"could not fetch {remote} main: {fetched.stderr.strip()}")
    sha = _git(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()
    print(f"run_checks: base is {ref} ({sha})", file=sys.stderr)
    return ref


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--context", choices=("ci", "local"),
                        help="ci: CI's literal args; local: base-relative args, "
                             "opt-in checks NOT RUN without their prerequisite")
    parser.add_argument("--base", help="base ref for base-relative checks "
                                       "(ci: must be origin/main; local: default <upstream>/main)")
    parser.add_argument("--smokes", action="store_true",
                        help="run CI's credential-free smoke suites")
    parser.add_argument("--json", metavar="PATH", help="also write the results as JSON")
    args = parser.parse_args(argv)

    if not args.context and not args.smokes:
        parser.error("pass --context and/or --smokes")
    if args.context == "ci" and args.base not in (None, CI_BASE):
        parser.error(f"--context ci runs CI's literal args, which use {CI_BASE}; "
                     f"use --context local for another base")

    python = sys.executable or "python3"
    # Smokes run with no --context in CI, so the Actions env decides there.
    report = _reporter(args.context == "ci" or os.environ.get("GITHUB_ACTIONS") == "true")
    results: List[Result] = []
    try:
        if args.context:
            base = args.base
            if args.context == "local" and base is None:
                try:
                    base = _local_base(REPO_ROOT)
                except RuntimeError as exc:
                    # Only this CLI has --base; resolve_upstream's callers word their own hint.
                    raise RuntimeError(f"{exc} (or pass --base explicitly)") from exc
            results += run(args.context, base, REPO_ROOT, python, report=report)
        if args.smokes:
            results += run_smokes(REPO_ROOT, python, report=report)
    except (RuntimeError, ValueError) as exc:
        print(f"run_checks: {exc}", file=sys.stderr)
        return 2

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
