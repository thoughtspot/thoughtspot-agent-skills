#!/usr/bin/env python3
"""
check_orphan_references.py — flag reference files that nothing in the repo cites.

2026-07-11 audit finding 1.1: `agents/cli/ts-convert-from-snowflake-sv/references/
update-mode-spec.md` and its `ts-convert-to-snowflake-sv` twin were both headed
"Status: Approved spec — pending implementation" for Mode C long after Mode C
shipped (2026-05-05, v1.2.0 / v1.4.0) — dead design docs nobody would ever open
again, discovered only by a repo-wide grep during the audit sweep. This validator
makes that discovery permanent instead of relying on the next audit to notice.

Scope: every `agents/{cli,claude,coco-snowsight}/**/references/*.md` file (the
`**` also catches `agents/claude/references/*.md`, which sits directly under the
runtime root rather than under a per-skill directory).

"Cited" definition (robust, low false-positive): a reference file
`.../references/<name>.md` is cited if ANY other repo file — scanning `.md`,
`.py`, `.sh`, `.yml`, `.yaml`, `.json`, `.txt` under the repo root, excluding
`.git`, `.venv`, `venv`, `dist`, `build`, `node_modules`, `__pycache__` — contains
the substring `references/<name>.md`. That substring covers both citation shapes
in the wild: the full repo-relative path (`agents/cli/ts-audit/references/
check-catalog.md`) and any markdown/relative link ending the same way
(`](references/check-catalog.md)`, `](../references/check-catalog.md)`). The
file being checked never counts as its own citer.

This is deliberately biased toward NOT flagging: two skills that happen to reuse
a reference basename (e.g. multiple `coverage-matrix.md` files, one per
ts-convert-* skill) can cross-satisfy each other's substring search. That
trade-off is accepted — a validator that occasionally misses a genuine orphan is
safer than one that cries wolf on legitimate same-name references across
sibling skills.

ALLOWLIST (by basename): `open-items.md` — a repo-wide tracking convention used
by 11 files. They are legitimately uncited by design: `.claude/rules/*`,
CLAUDE.md, and `check_open_items.py` reference the *convention* generically, not
any individual file. Allowlist the basename so all 11 pass without per-file
exceptions (mirrors the ALLOWLIST convention-comment style in
`check_smoke_tests.py`).

NOT in scope: `agents/claude/references/direct-api-auth.md` is currently cited
by two (dead) SKILL.md table rows and so is not flagged today — but its retirement
is tracked separately as BL-109. This validator does not special-case it; it is
simply cited, like any other file that passes the substring check.

Exit codes:
  0 — every references/*.md file is either cited or allowlisted
  1 — at least one orphan found

Run manually:
    python3 tools/validate/check_orphan_references.py --root .
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RUNTIME_DIRS = ("cli", "claude", "coco-snowsight")

# Reference basenames exempt from the citation requirement — see module docstring.
ALLOWLIST_BASENAMES = {"open-items.md"}

# Directories never scanned for either reference files or citing text.
EXCLUDE_DIR_NAMES = {".git", ".venv", "venv", "dist", "build", "node_modules", "__pycache__"}

# Extensions scanned when looking for a citation of a reference file.
SEARCH_EXTENSIONS = {".md", ".py", ".sh", ".yml", ".yaml", ".json", ".txt"}


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)


def find_reference_files(repo_root: Path) -> list[Path]:
    """Every references/*.md file across the three skill runtimes.

    Uses rglob("references/*.md") per runtime root rather than a fixed-depth glob
    so it also matches agents/claude/references/*.md, which sits directly under
    the runtime root (no per-skill directory) rather than nested one level deeper
    like the cli/coco-snowsight skills.
    """
    files: list[Path] = []
    for runtime in RUNTIME_DIRS:
        runtime_root = repo_root / "agents" / runtime
        if not runtime_root.is_dir():
            continue
        for p in runtime_root.rglob("references/*.md"):
            if not _is_excluded(p.relative_to(repo_root)):
                files.append(p)
    return sorted(set(files))


def collect_search_files(repo_root: Path) -> list[Path]:
    """Every text file under repo_root eligible to contain a citation."""
    files: list[Path] = []
    for p in repo_root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in SEARCH_EXTENSIONS:
            continue
        if _is_excluded(p.relative_to(repo_root)):
            continue
        files.append(p)
    return files


def is_cited(target: Path, repo_root: Path, search_files: list[Path]) -> bool:
    """True if some OTHER file in search_files contains 'references/<name>.md'."""
    needle = f"references/{target.name}"
    for f in search_files:
        if f == target:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle in content:
            return True
    return False


def check(repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (orphan_messages, info_messages)."""
    reference_files = find_reference_files(repo_root)
    search_files = collect_search_files(repo_root)

    orphans: list[str] = []
    info: list[str] = []

    for ref in reference_files:
        rel = ref.relative_to(repo_root)
        if ref.name in ALLOWLIST_BASENAMES:
            info.append(f"SKIP  {rel}  (allowlisted basename: {ref.name})")
            continue
        if is_cited(ref, repo_root, search_files):
            info.append(f"PASS  {rel}  (cited)")
        else:
            orphans.append(
                f"FAIL  {rel}  →  not cited by any other repo file "
                f"(no 'references/{ref.name}' substring found outside itself)"
            )

    return orphans, info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    repo_root = Path(args.root).resolve()

    orphans, info = check(repo_root)

    for msg in info:
        print(msg)

    if orphans:
        print()
        for msg in orphans:
            print(msg)
        print()
        print(f"{len(orphans)} orphan reference file(s) found.")
        print(
            "A references/*.md file with no citation elsewhere in the repo is dead "
            "weight (audit finding 1.1) — either link it from the owning SKILL.md / "
            "a sibling doc, or delete it. If it is a repo-wide tracking convention "
            "file that is legitimately uncited by design, add its basename to "
            "ALLOWLIST_BASENAMES in this file with a justification."
        )
        return 1

    print()
    print(f"All {len(info)} reference file(s) are cited or allowlisted. No orphans found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
