"""Single source of truth for enumerating files from git.

Before this module (2026-08-26 full-audit finding 4.2) ten validators each rolled
their own ``subprocess.run(["git", "ls-files"], ...)`` or ``git diff --cached
--name-only``, split the output with ``.splitlines()``, and filtered on
``(repo_root / f).exists()``. That shape has two independent fail-open defects, and
every copy had both:

**1. Octal-quoted paths are silently dropped.** Git quotes any path containing
non-ASCII or special characters, so ``café.md`` comes back as the 22-character
string ``"agents/cli/caf\\303\\251.md"`` — quotes included. The constructed path
does not exist, the ``.exists()`` filter drops it, and the caller sees a shorter
list with no warning. For ``check_secrets`` that means a staged credential in a
non-ASCII filename passes the pre-commit gate AND the CI ``--all`` backstop, both
exit 0. Reproduced before this module was written.

**2. A failing git invocation reads as "nothing to check".** None of the copies
checked ``returncode``. Not a repo, ``index.lock`` contention, git absent from
PATH — all yield empty stdout, which every caller interprets as an empty file list
and reports PASS.

Both are fixed here rather than in ten places:

* ``-z`` makes git emit NUL-separated, **never-quoted** paths.
* ``check=True`` turns a git failure into a loud exception instead of a silent pass.

The repo's own rule is that a gate must never go green because it could not run
(``.claude/rules/repo-audit.md``). A validator that swallows both of these is
exactly that failure, so do not reintroduce a local copy — ``check_patterns`` has a
rule that fails on new raw call sites. Same principle as :mod:`_dirs`, which exists
because ~18 validators each hardcoded the runtime directory list (BL-110).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, List, Sequence


class GitEnumerationError(RuntimeError):
    """git could not be run, or exited non-zero.

    Raised rather than returning an empty list: an empty list is
    indistinguishable from "the repo has no matching files", which is what let a
    failed invocation read as PASS in every pre-existing copy.
    """


def git_paths(args: Sequence[str], repo_root: Path) -> List[str]:
    """Run ``git <args>`` in ``repo_root`` and return NUL-split repo-relative paths.

    ``args`` must NOT include ``-z``; it is appended here so every caller gets
    unquoted output. Empty trailing field from the trailing NUL is discarded.

    Raises :class:`GitEnumerationError` if git is missing or exits non-zero.
    """
    try:
        result = subprocess.run(
            ["git", *args, "-z"],
            capture_output=True, text=True, cwd=repo_root, check=True,
        )
    except FileNotFoundError as exc:  # git not on PATH
        raise GitEnumerationError(f"git not found: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        # Cap stderr: git prints its full usage block on an argument error, which
        # buries the one line that matters in ~120 lines of option help.
        detail = " ".join((exc.stderr or "").split())[:200]
        raise GitEnumerationError(
            f"git {' '.join(args)} failed in {repo_root} "
            f"(exit {exc.returncode}): {detail}"
        ) from exc
    return [p for p in result.stdout.split("\0") if p]


def staged_files(repo_root: Path, *, diff_filter: str = "ACM") -> List[Path]:
    """Absolute paths of staged added/copied/modified files that exist on disk.

    The ``.exists()`` filter is kept deliberately — a staged deletion or a path
    that vanished between staging and now is genuinely not readable — but it can
    no longer mask a quoting bug, because the paths are unquoted.
    """
    rels = git_paths(["diff", "--cached", "--name-only", f"--diff-filter={diff_filter}"], repo_root)
    return [repo_root / r for r in rels if (repo_root / r).exists()]


def tracked_files(repo_root: Path, paths: Iterable[str] = ()) -> List[Path]:
    """Absolute paths of tracked files that exist on disk, optionally path-scoped."""
    rels = git_paths(["ls-files", *paths], repo_root)
    return [repo_root / r for r in rels if (repo_root / r).exists()]


def tracked_relpaths(repo_root: Path, paths: Iterable[str] = ()) -> List[str]:
    """Repo-relative tracked paths, unfiltered by existence.

    For callers that compare against git's own view (e.g. ignored-but-tracked
    queries) rather than reading the files.
    """
    return git_paths(["ls-files", *paths], repo_root)


class _GitOut:
    """Minimal stand-in exposing ``.stdout`` for call sites that already had a
    ``result = subprocess.run(...)`` / ``result.stdout.splitlines()`` shape.

    Keeps those diffs to one line each while still routing through
    :func:`git_paths`, so they get NUL-splitting and fail-loud without a
    restructure. New code should call :func:`git_paths` directly.
    """

    __slots__ = ("stdout",)

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def parse_name_status_z(text: str) -> List[tuple[str, str, str]]:
    """Parse ``--name-status -z`` output into ``(prefix, status, path)`` triples.

    ``--name-status`` is the one git enumeration :func:`git_paths` cannot serve,
    because a record is a status *and* a path rather than a bare path — and the
    record width is not constant:

    * ordinary change -- ``A\\0path\\0``            (2 fields)
    * rename or copy  -- ``R100\\0old\\0new\\0``     (3 fields)

    That asymmetry is the whole reason this is a separate function. A naive
    pairwise split desynchronises on the first rename and then silently mislabels
    every subsequent record — reading the *next* record's status letter as a path
    and its path as a status. Verified against real git output, not inferred.

    ``path`` is the **new** path for a rename or copy, which is what every caller
    wants ("what does the tree look like now"); the old path is dropped.

    ``prefix`` exists for ``git log --name-status -z --pretty=format:...``, where
    git emits the commit header glued to the following status letter by a newline
    (``"<sha>\\nA"``). Callers that need commit boundaries count non-empty
    prefixes; for ``git diff`` the prefix is always ``""``.
    """
    records: List[tuple[str, str, str]] = []
    fields = text.split("\0")
    i = 0
    while i < len(fields):
        raw = fields[i]
        if not raw:
            i += 1                      # separator run between commits
            continue
        prefix, _, status = raw.rpartition("\n")
        # R/C are the only statuses that carry a second path.
        width = 2 if status[:1] in ("R", "C") else 1
        if i + width >= len(fields):
            break                       # truncated trailing record
        path = fields[i + width]
        if not path:
            # A status with no path (truncated output). Emitting it would hand the
            # caller an empty path that silently matches no rule.
            break
        records.append((prefix, status, path))
        i += width + 1
    return records


def git_status_paths(args: Sequence[str], repo_root: Path) -> List[tuple[str, str, str]]:
    """Run ``git <args> --name-status -z`` and return parsed records.

    Same fail-loud contract as :func:`git_paths`: a git failure raises rather than
    returning an empty list that reads as "nothing changed".
    """
    try:
        result = subprocess.run(
            ["git", *args, "--name-status", "-z"],
            capture_output=True, text=True, cwd=repo_root, check=True,
        )
    except FileNotFoundError as exc:
        raise GitEnumerationError(f"git not found: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = " ".join((exc.stderr or "").split())[:200]
        raise GitEnumerationError(
            f"git {' '.join(args)} --name-status failed in {repo_root} "
            f"(exit {exc.returncode}): {detail}"
        ) from exc
    return parse_name_status_z(result.stdout)
