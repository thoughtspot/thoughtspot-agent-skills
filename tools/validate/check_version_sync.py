#!/usr/bin/env python3
"""
check_version_sync.py — verify the ts-cli version is consistent AND novel.

Two independent invariants:

1. **Internal consistency** (always checked, no git needed)
   `ts_cli/__init__.py` `__version__` must equal `pyproject.toml` `version`, and
   `CHANGELOG.md` must not name the same ts-cli release twice.

2. **Novelty** (only with `--base`, needs git)
   If the branch changes shipped ts-cli code, its version must not already be
   published — not `<base>`'s `pyproject.toml` version, and not any release
   already marked in `<base>`'s `CHANGELOG.md`.

Why novelty needs its own rule (BL-274): two branches that bump to the *same*
version change the same two lines to the same value, so a three-way merge sees an
identical change on both sides and auto-merges with **no conflict at all**, and
consistency still holds because the collision preserves it perfectly. Agreeing on
the same wrong value is invisible to both git and to rule 1. Demonstrated twice:
#511 vs #512 (both 0.139.0) and #484 vs #516 (both 0.141.0).

`--base` is opt-in because it needs `origin/main`, which pre-commit and a
`git archive` export do not have; CI passes it (`fetch-depth: 0`). When `--base`
IS passed and the base cannot be read, that is a FAIL rather than a skip — a gate
that silently no-ops when it cannot see its input is decorative.

Not implemented: BL-274 also proposed checking the new version against `git tag`.
This repo has zero tags, so that source is vacuous; the `CHANGELOG.md` release
markers are the only durable record of what has shipped.

Usage:
    python tools/validate/check_version_sync.py
    python tools/validate/check_version_sync.py --root /path/to/repo
    python tools/validate/check_version_sync.py --base origin/main   # CI
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from _novelty import BaseUnavailable, read_at, resolve_base

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

# Only the `bump ts-cli to vX.Y.Z` form marks a release. Prose naming a version
# ("shipped in ts-cli v0.9.0") appears 100+ times on main, so a looser pattern
# would manufacture duplicates out of ordinary cross-references.
_BUMP_RE = re.compile(r"bump ts-cli to v(\d+\.\d+\.\d+)")

# The shipped package. Deliberately narrower than `tools/ts-cli/`: a branch that
# only touches `tools/ts-cli/tests/` releases nothing and must not be forced to
# invent a version number to land.
_TS_CLI_PACKAGE = "tools/ts-cli/ts_cli"


def read_init_version(init_file: Path) -> str | None:
    content = init_file.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    return m.group(1) if m else None


def parse_pyproject_version(content: str) -> str | None:
    """`[project] version` from pyproject.toml text."""
    if tomllib is not None:
        try:
            data = tomllib.loads(content)
            return data.get("project", {}).get("version")
        except Exception:
            pass
    # Fallback: section-anchored scan, used whenever neither tomllib (3.11+) nor
    # tomli is importable — which is the ONLY path under a bare `python3` on a 3.9
    # interpreter, and both pre-commit.sh and CI invoke this as bare `python3`.
    #
    # A plain `^version\s*=` MULTILINE search is table-blind: it returns the first
    # column-0 `version =` anywhere in the file. That is correct today only because
    # `[build-system]` happens to use `requires =`. Reproduced both directions
    # (2026-08-26 audit, finding 4.4): a `[tool.poetry] version` above `[project]`
    # yields a mismatch that does not exist, and a `[project]` with no version at
    # all silently adopts some other table's — a false PASS on a version gate.
    return _version_in_project_table(content)


def read_pyproject_version(pyproject_file: Path) -> str | None:
    return parse_pyproject_version(pyproject_file.read_text(encoding="utf-8"))


def _version_in_project_table(content: str) -> str | None:
    """`version` from the `[project]` table only, ignoring every other table.

    Deliberately not a general TOML parser — it needs one key from one table. Stops
    at the next `[section]` header so a key in a later table can never leak in.
    """
    in_project = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            # `[project]` exactly — not `[project.optional-dependencies]`, which is a
            # different table and must not satisfy the lookup.
            in_project = stripped == "[project]"
            continue
        if not in_project:
            continue
        m = re.match(r'version\s*=\s*["\']([^"\']+)["\']', stripped)
        if m:
            return m.group(1)
    return None


def changelog_bump_versions(content: str) -> list[str]:
    """Every ts-cli release marked in CHANGELOG text, in document order."""
    return [m.group(1) for m in _BUMP_RE.finditer(content)]


def duplicate_bump_versions(content: str) -> list[str]:
    """Versions marked as released more than once — the post-merge collision shape."""
    seen: set[str] = set()
    dupes: set[str] = set()
    for v in changelog_bump_versions(content):
        if v in seen:
            dupes.add(v)
        seen.add(v)
    return sorted(dupes)


def novelty_violations(
    *,
    branch_version: str,
    base_pyproject: str | None,
    base_changelog: str | None,
    ts_cli_changed: bool,
) -> list[str]:
    """Messages for every way ``branch_version`` fails to be an unreleased version.

    ``base_pyproject``/``base_changelog`` are the *base* revision's file contents,
    or None when they could not be read — which is itself a violation, because the
    caller asked for this check and we cannot answer it.
    """
    if base_pyproject is None or base_changelog is None:
        return [
            "could not read the base revision's pyproject.toml / CHANGELOG.md. "
            "Novelty was requested via --base but cannot be determined; refusing "
            "to pass rather than skip silently."
        ]

    if not ts_cli_changed:
        # Nothing is being released, so reusing the base's version is correct.
        return []

    out: list[str] = []
    base_version = parse_pyproject_version(base_pyproject)
    if base_version == branch_version:
        out.append(
            f"version {branch_version} is already the version on the base revision. "
            f"Two branches bumping to the same value merge without a conflict and "
            f"keep __init__.py/pyproject.toml consistent, so nothing else catches it."
        )
    released = changelog_bump_versions(base_changelog)
    if branch_version in released and base_version != branch_version:
        out.append(
            f"version {branch_version} is already marked as released in the base "
            f"revision's CHANGELOG.md."
        )
    return out


def _git(args: list[str], root: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def ts_cli_changed_against(base: str, root: Path) -> bool:
    """Does this branch change shipped ts-cli code relative to ``base``?

    Counts uncommitted work as well as committed. Run locally before the first
    commit, ``HEAD`` can still equal ``base`` while the package is already
    edited, and answering "novelty n/a" there is the same false confidence this
    check exists to prevent — found by running this gate against its own PR. CI
    checks out a clean tree, so the second probe only ever adds local accuracy.
    """
    committed = _git(["diff", "--name-only", f"{base}...HEAD", "--", _TS_CLI_PACKAGE], root)
    if committed and committed.strip():
        return True
    dirty = _git(["status", "--porcelain", "--", _TS_CLI_PACKAGE], root)
    return bool(dirty and dirty.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ts-cli version sync and novelty.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    parser.add_argument(
        "--base", default=None,
        help="Also require the version to be unreleased, compared against this "
             "revision (e.g. --base origin/main). Needs git; CI passes it. "
             "Omitted for pre-commit and for non-git exports.",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    init_file = repo_root / "tools/ts-cli/ts_cli/__init__.py"
    pyproject_file = repo_root / "tools/ts-cli/pyproject.toml"
    changelog_file = repo_root / "CHANGELOG.md"

    if not init_file.exists():
        print(f"ERROR: {init_file} not found")
        return 1
    if not pyproject_file.exists():
        print(f"ERROR: {pyproject_file} not found")
        return 1

    init_ver = read_init_version(init_file)
    pyproject_ver = read_pyproject_version(pyproject_file)

    if init_ver is None:
        print(f"ERROR: could not parse __version__ from {init_file.relative_to(repo_root)}")
        return 1
    if pyproject_ver is None:
        print(f"ERROR: could not parse version from {pyproject_file.relative_to(repo_root)}")
        return 1

    if init_ver != pyproject_ver:
        print("FAIL  version mismatch:")
        print(f"        ts_cli/__init__.py  : {init_ver}")
        print(f"        pyproject.toml      : {pyproject_ver}")
        print()
        print("Bump both to the same version before committing.")
        return 1

    # Rule 1b — the same release named twice. No git needed, so this runs always;
    # it is what catches a correctly-bumped PR whose changelog line was duplicated,
    # and the merged state of two colliding PRs.
    if changelog_file.exists():
        dupes = duplicate_bump_versions(changelog_file.read_text(encoding="utf-8"))
        if dupes:
            print("FAIL  CHANGELOG.md marks the same ts-cli release more than once:")
            for v in dupes:
                print(f"        v{v}")
            print()
            print("One `bump ts-cli to vX.Y.Z` line per release.")
            return 1

    # Rule 2 — novelty.
    if args.base:
        base = args.base
        # Resolve-or-fail lives in `_novelty` so this and check_backlog_integrity
        # cannot drift apart; each maps the failure to its own exit code.
        try:
            resolve_base(repo_root, base)
        except BaseUnavailable as exc:
            print(f"FAIL  version novelty: {exc}")
            return 1
        ts_cli_changed = ts_cli_changed_against(base, repo_root)
        violations = novelty_violations(
            branch_version=pyproject_ver,
            base_pyproject=read_at(repo_root, base, "tools/ts-cli/pyproject.toml"),
            base_changelog=read_at(repo_root, base, "CHANGELOG.md"),
            ts_cli_changed=ts_cli_changed,
        )
        if violations:
            print(f"FAIL  version novelty ({pyproject_ver} against {base}):")
            for m in violations:
                print(f"        {m}")
            print()
            print("Bump to an unreleased version, and move the CHANGELOG line with it.")
            return 1
        # Say which of the two it is. "novel" and "nothing to release" are different
        # facts, and reporting the first when the second is true is the false
        # confidence a version gate exists to avoid.
        if ts_cli_changed:
            print(f"PASS  version sync + novelty: {init_ver} (unreleased against {base})")
        else:
            print(f"PASS  version sync: {init_ver} "
                  f"(novelty n/a — no {_TS_CLI_PACKAGE} change against {base})")
        return 0

    print(f"PASS  version sync: {init_ver}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
