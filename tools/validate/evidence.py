"""evidence.py — render and write the evidence block `scripts/pr-ready.sh` produces.

A PR description used to say "validators pass locally" with nothing behind it: no
record of which checks ran, against which base, on which commit, or what was left
out. The evidence block is that record, written for pasting into the PR template
(or posting with `pr-ready.sh --post`). Because it is evidence, it must not
misdescribe what ran:

- **head and base SHAs**, plus a `DIRTY` marker when the work tree had
  uncommitted changes — the head SHA alone would then name code that is not what
  was checked;
- **every NOT RUN and SKIP with its reason**, so nothing reads as checked that
  was not (a required check that skipped is FAIL, and is listed here too);
- **what CI does that this run did not reproduce**, so the block does not claim
  more than it measured;
- **no machine-local paths.** The repo is public; a home directory names a
  person. Every `/Users/<name>`, `/home/<name>` and `C:\\Users\\<name>` in the
  rendered text is replaced by `~`, wherever it came from (a validator's output,
  an interpreter path, a review).

It is written to `<git-dir>/pr-ready/evidence.md`: inside the git dir, so never
tracked and never seen by `check_repo_hygiene`; per worktree, since each worktree
has its own git dir.

Must import and run on Python 3.9 (the system interpreter).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: The note run_checks puts first in a required check's output when it skipped
#: (locally that is FAIL); used here to list such a FAIL as the skip it was.
from run_checks import _PROMOTED as PROMOTED_PREFIX  # noqa: E402

Result = Dict[str, object]

_HOME_PATH = re.compile(r"(?:/Users|/home)/[^/\s`'\"|)]+|[A-Za-z]:\\Users\\[^\\\s`'\"|)]+")


def scrub(text: str) -> str:
    """Replace every home-directory prefix with `~`."""
    return _HOME_PATH.sub("~", text)


def _first_line(text: str, prefix: str = "") -> str:
    for line in str(text).splitlines():
        if line.startswith(prefix) and line.strip():
            return line.strip()
    return ""


def _blocking(results: Sequence[Result]) -> List[Result]:
    return [r for r in results if r["status"] == "FAIL"]


def _not_run_or_skipped(results: Sequence[Result]) -> List[str]:
    lines = []
    for r in results:
        status, tail = r["status"], str(r.get("output_tail", ""))
        if status == "NOT RUN":
            reason = r.get("reason") or f"prerequisite absent: {tail}"
            lines.append(f"- `{r['id']}` — NOT RUN: {reason}")
        elif status == "SKIP":
            reason = r.get("reason") or _first_line(tail, "SKIP") or "printed a SKIP line"
            lines.append(f"- `{r['id']}` — SKIP: {reason}")
        elif status == "FAIL" and tail.startswith(PROMOTED_PREFIX):
            reason = _first_line(tail, "SKIP") or "missing tool"
            lines.append(f"- `{r['id']}` — skipped (`{reason}`); required on every PR, "
                         "so counted as FAIL")
    return lines


def render(*, base_ref: str, base_sha: str, head_sha: str, dirty: bool, behind: int,
           checks: List[Result], smokes: List[Result], pytest: List[Result],
           not_reproduced: List[str], review: Optional[str]) -> str:
    """The evidence block as markdown. Sections, in order: header, behind count,
    results table, NOT RUN and SKIP, not reproduced locally, review."""
    everything = list(checks) + list(smokes) + list(pytest)
    failures = _blocking(everything)
    if failures or behind > 0:
        reasons = []
        if failures:
            reasons.append(f"{len(failures)} FAIL")
        if behind > 0:
            reasons.append(f"{behind} behind upstream main")
        verdict = f"NOT READY ({', '.join(reasons)})"
    else:
        verdict = "READY"

    out: List[str] = []
    dirty_note = (" — **DIRTY**: the work tree had uncommitted changes, so the head SHA "
                  "does not describe exactly what was checked") if dirty else ""
    out.append(f"**pr-ready** head `{head_sha}` against `{base_ref}` at `{base_sha}`{dirty_note}")
    out.append("")
    out.append(f"**{verdict}**")
    out.append("")
    noun = "commit" if behind == 1 else "commits"
    behind_note = f" — merge or rebase onto `{base_ref}` and re-run" if behind > 0 else ""
    out.append(f"Behind upstream main: {behind} {noun}{behind_note}")
    out.append("")

    out.append("## Results")
    out.append("")
    out.append("| Kind | Check | Status | Seconds |")
    out.append("|---|---|---|---|")
    for kind, results in (("check", checks), ("smoke", smokes), ("pytest", pytest)):
        for r in results:
            name = str(r["id"]).replace("|", "\\|")
            out.append(f"| {kind} | `{name}` | {r['status']} | {float(r['seconds']):.1f} |")
    out.append("")

    out.append("## NOT RUN and SKIP")
    out.append("")
    out.extend(_not_run_or_skipped(everything) or ["None."])
    out.append("")

    out.append("## Not reproduced locally")
    out.append("")
    out.extend(f"- {item}" for item in not_reproduced)
    if not not_reproduced:
        out.append("Nothing recorded.")
    out.append("")

    out.append("## Review")
    out.append("")
    if review is None:
        out.append("Not run. The `pr-ready` skill runs the reviewer agent and appends its "
                   "findings here.")
    else:
        out.append(review.rstrip("\n"))
    out.append("")
    return scrub("\n".join(out))


def evidence_path(repo_root: Path) -> Path:
    """`<git-dir>/pr-ready/evidence.md` for the checkout at `repo_root`."""
    proc = subprocess.run(["git", "rev-parse", "--absolute-git-dir"], cwd=repo_root,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse --absolute-git-dir failed: {proc.stderr.strip()}")
    return Path(proc.stdout.strip()) / "pr-ready" / "evidence.md"


def write(text: str, repo_root: Path) -> Path:
    """Write the block to `<git-dir>/pr-ready/evidence.md` and return the path."""
    path = evidence_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
