"""scripts/pre-commit.sh's staged-file triggers must fire on a large staged list.

Each optional check sits behind a trigger that greps the staged paths. Written as
`if echo "$STAGED" | grep -q PATTERN; then`, a trigger fails silently once the list
is over the pipe buffer (~64 KiB, a few hundred paths in a large merge or rename):
grep -q exits at its first match, `echo` is still writing and takes SIGPIPE, and
under the hook's `set -euo pipefail` the pipeline's status is echo's 141, so the
`if` reads false and the check never runs, with nothing printed. The same class
`run_check` already avoids for SKIP lines (see test_precommit_skip.py).

These take every trigger line from the REAL hook, feed it a staged list of more
than 64 KiB whose first path matches it, and run it under the hook's own shell
options on /bin/bash (3.2 on macOS, the oldest bash the hook meets). The matching
path is found by grep reading a file, not a pipe, so the oracle cannot share the
bug.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PRE_COMMIT = REPO / "scripts" / "pre-commit.sh"
BASH = "/bin/bash"

#: A trigger: an `if` line whose condition greps the staged list (not the
#: `[ -z "$STAGED" ]` early exit).
_TRIGGER = re.compile(r"^\s*if (?P<cond>(?=.*\$STAGED)(?=.*\bgrep\b).*); then\s*$")
#: The grep inside a trigger: its flags and its single-quoted pattern.
_GREP = re.compile(r"grep -q(?P<ere>E?) '(?P<pattern>[^']+)'")
#: A path no trigger pattern matches, used to pad the list past the pipe buffer.
_FILLER = "zz-filler/not-a-trigger-path.txt"
#: Well past the ~64 KiB pipe buffer, so `echo | grep -q` misfires deterministically.
_MIN_BYTES = 1024 * 1024


def _triggers() -> list[tuple[int, str]]:
    lines = PRE_COMMIT.read_text(encoding="utf-8").splitlines()
    found = [(n, m.group("cond")) for n, line in enumerate(lines, 1)
             if (m := _TRIGGER.match(line))]
    assert len(found) >= 40, f"expected the hook's ~42 triggers, parsed {len(found)}"
    return found


def _tracked(tmp_path: Path) -> Path:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout
    path = tmp_path / "tracked.txt"
    path.write_text(out, encoding="utf-8")
    return path


def _first_match(cond: str, paths: Path) -> str:
    """The first line of `paths` the trigger's grep matches, read from a file."""
    m = _GREP.search(cond)
    assert m, f"trigger without a recognisable `grep -q 'PATTERN'`: {cond}"
    argv = ["grep", "-m1"] + (["-E"] if m.group("ere") else []) + ["-e", m.group("pattern"),
                                                                    str(paths)]
    proc = subprocess.run(argv, capture_output=True, text=True)
    return proc.stdout.strip()


def _fires(cond: str, staged_file: Path) -> str:
    # The hook's own options; STAGED holds the list exactly as `$(git diff ...)` would.
    script = ("set -euo pipefail\n"
              'STAGED="$(cat "$STAGED_FILE")"\n'
              "CURRENT_BRANCH=main\n"
              f"if {cond}; then echo FIRED; else echo QUIET; fi\n")
    proc = subprocess.run([BASH, "-c", script], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "STAGED_FILE": str(staged_file)})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.strip()


def test_no_trigger_pipes_the_staged_list():
    # Static half: any `... "$STAGED" | grep` is the misfiring shape, wherever it is.
    text = PRE_COMMIT.read_text(encoding="utf-8")
    piped = [line.strip() for line in text.splitlines()
             if re.search(r'"\$STAGED"\s*\|', line) and not line.lstrip().startswith("#")]
    assert not piped, "pipe-fed staged-list greps (SIGPIPE under pipefail):\n" + "\n".join(piped)


def test_every_trigger_fires_on_a_staged_list_over_64_kib(tmp_path):
    tracked = _tracked(tmp_path)
    filler_file = tmp_path / "filler.txt"
    filler_file.write_text(_FILLER + "\n", encoding="utf-8")
    filler = (_FILLER + "\n") * (_MIN_BYTES // (len(_FILLER) + 1) + 1)
    unmatched, quiet, exercised = [], [], 0
    for line_no, cond in _triggers():
        first = _first_match(cond, tracked)
        if not first:
            unmatched.append(f"line {line_no}: {cond}")
            continue
        # Only the first path matches, so a hit can only come from line 1.
        assert not _first_match(cond, filler_file), f"the filler matches line {line_no}"
        staged = tmp_path / f"staged-{line_no}.txt"
        staged.write_text(first + "\n" + filler, encoding="utf-8")
        assert staged.stat().st_size > 64 * 1024
        if _fires(cond, staged) != "FIRED":
            quiet.append(f"line {line_no} ({first}): {cond}")
        exercised += 1
    assert not quiet, "triggers that stayed quiet although the first staged path matches:\n" \
        + "\n".join(quiet)
    # A trigger no tracked path matches is not exercised here; there should be none.
    assert not unmatched, "triggers no tracked path matches:\n" + "\n".join(unmatched)
    assert exercised >= 40


def test_the_old_pipe_form_misfires_on_the_same_input(tmp_path):
    # The test input must be big enough to show the bug, or the test above proves
    # nothing: the pipe form goes quiet on it, the here-string form does not.
    staged = tmp_path / "staged.txt"
    staged.write_text("a.py\n" + (_FILLER + "\n") * (_MIN_BYTES // len(_FILLER)),
                      encoding="utf-8")
    assert _fires("echo \"$STAGED\" | grep -q '\\.py$'", staged) == "QUIET"
    assert _fires("grep -q '\\.py$' <<< \"$STAGED\"", staged) == "FIRED"


@pytest.mark.parametrize("staged_text", ["", "docs/x.txt\n"])
def test_a_trigger_stays_quiet_when_nothing_matches(tmp_path, staged_text):
    staged = tmp_path / "staged.txt"
    staged.write_text(staged_text, encoding="utf-8")
    assert _fires("grep -q '\\.py$' <<< \"$STAGED\"", staged) == "QUIET"
