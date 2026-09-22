#!/usr/bin/env python3
"""
check_coverage_matrix.py — verify every conversion skill has a coverage matrix.

Rule: every `ts-convert-*` skill under agents/cli/ must have a
`references/coverage-matrix.md` file documenting what the converter maps
and what it doesn't.

The validator checks:
  1. Existence of the file
  2. Required sections (Mapped Constructs, Unmapped Constructs/Limitations)
  3. Minimum table row count
  4. Format consistency (Notes column convention, no stale patterns)

Skills on the BACKLOG set are exempt — they need a coverage matrix but
don't have one yet. Each entry must include a target date or PR reference.

Exit codes:
  0 — every conversion skill has a valid coverage matrix (or is on backlog)
  1 — at least one conversion skill is missing or has an invalid matrix

Run manually:
    python3 tools/validate/check_coverage_matrix.py --root .

The pre-commit hook invokes this when `agents/cli/ts-convert-*/` files are staged.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _novelty import (
    BaseUnavailable,
    merge_base_with_head,
    novel_id_collisions,
    read_at,
    resolve_base,
)


# Skills that need a coverage matrix but don't have one yet. Each justification
# MUST carry a target date (YYYY-MM-DD) or a PR/backlog reference (#NNN / BL-NNN)
# so the exemption is traceable and can be chased down — a dateless "backlog"
# note never expires and quietly rots (repo audit finding). Enforced by
# _bad_backlog_justifications() below.
BACKLOG: dict[str, str] = {}

# A valid justification mentions an ISO date or a #NNN / BL-NNN reference.
_BACKLOG_REF_RE = re.compile(r"\d{4}-\d{2}-\d{2}|#\d+|BL-\d+")


def _bad_backlog_justifications() -> list[str]:
    """Return error strings for BACKLOG entries whose justification is dateless /
    unreferenced. Keeps deferred coverage matrices from becoming permanent."""
    return [
        f"BACKLOG['{name}'] justification has no target date or #NNN/BL-NNN reference: "
        f"{just!r}"
        for name, just in BACKLOG.items()
        if not _BACKLOG_REF_RE.search(just)
    ]

BANNED_COLUMN_NAMES = re.compile(
    r"^\|\s*#\s*\|[^|]*\|[^|]*\|\s*(Verified|Verified Against)\s*\|",
    re.MULTILINE,
)

BANNED_SECTIONS = re.compile(
    r"^##\s+(Test\s+Workbooks|Test\s+Semantic\s+Views)\s*$",
    re.MULTILINE,
)

LAST_VERIFIED_LINE = re.compile(
    r"^Last\s+verified:",
    re.MULTILINE,
)


def find_convert_skills(root: Path) -> list[tuple[str, Path]]:
    """Return (skill_name, skill_dir) for every ts-convert-* skill."""
    found: list[tuple[str, Path]] = []
    cli_dir = root / "agents" / "cli"
    if not cli_dir.is_dir():
        return found
    for child in sorted(cli_dir.iterdir()):
        if (
            child.is_dir()
            and child.name.startswith("ts-convert-")
            and (child / "SKILL.md").is_file()
        ):
            found.append((child.name, child))
    return found


# Every table in these matrices leads with an `| # |` column, and the ids are
# stable rather than positional — 131 sits between 2 and 3 in the tableau matrix.
# Two families share the namespace: bare numbers for constructs, `L<N>`/`U<N>`
# for limitations and unmapped constructs. They are distinct strings, so one set
# per file is correct.
_ID_ROW_RE = re.compile(r"^\|\s*([A-Z]{0,2}\d+)\s*\|", re.MULTILINE)


def matrix_ids(content: str) -> list[str]:
    """Every leading-column id in a coverage matrix, in document order."""
    return _ID_ROW_RE.findall(content)


def duplicate_matrix_ids(content: str) -> list[str]:
    """Ids appearing on more than one row of one matrix, sorted.

    Needs no git, so it runs on every commit — and it is what catches the MERGED
    state of two branches that each appended the same next-free id. There are
    zero duplicates across all nine matrices today, so this can be strict from
    the start (unlike open-items, where five legitimate same-number pairs block
    the equivalent rule — see BL-282).
    """
    seen: set[str] = set()
    dupes: set[str] = set()
    for i in matrix_ids(content):
        (dupes if i in seen else seen).add(i)
    return sorted(dupes)


def matrix_novelty_violations(root: Path, base: str, matrices: list[Path]) -> list[str]:
    """Ids this branch INTRODUCES that are already used on the base, per matrix.

    Ids are scoped per matrix: every skill numbers its own constructs from 1, so
    a repo-wide set would collide on nearly every id.
    """
    resolve_base(root, base)
    merge_base = merge_base_with_head(root, base)

    out: list[str] = []
    for path in matrices:
        rel = str(path.relative_to(root))
        head = set(matrix_ids(path.read_text(encoding="utf-8")))
        at_mb = set(matrix_ids(read_at(root, merge_base, rel)))
        at_base = set(matrix_ids(read_at(root, base, rel)))
        for bad in novel_id_collisions(head, at_mb, at_base):
            out.append(f"{rel}: {bad}")
    return out


def validate_matrix(matrix_path: Path) -> list[str]:
    """Check the coverage matrix has the required sections and format. Return errors."""
    errors: list[str] = []
    try:
        content = matrix_path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"Cannot read {matrix_path}: {e}"]

    for dup in duplicate_matrix_ids(content):
        errors.append(
            f"id `{dup}` appears on more than one row — two branches likely each "
            f"took the same next-free number; nothing conflicts in git because the "
            f"rows land in different tables"
        )

    if not re.search(r"##\s+Mapped\s+Constructs", content):
        errors.append("Missing '## Mapped Constructs' section")
    if not (
        re.search(r"##\s+Unmapped\s+Constructs", content)
        or re.search(r"##\s+Limitations", content)
    ):
        errors.append(
            "Missing '## Unmapped Constructs' or '## Limitations' section"
        )

    mapped_tables = len(re.findall(r"^\|[^|]+\|[^|]+\|[^|]+\|", content, re.MULTILINE))
    if mapped_tables < 5:
        errors.append(
            f"Only {mapped_tables} table rows found — expected at least 5 "
            f"(mapped + unmapped constructs)"
        )

    # --- Format consistency checks ---

    m = BANNED_COLUMN_NAMES.search(content)
    if m:
        errors.append(
            f"Column header '{m.group(1).strip()}' found — rename to 'Notes' "
            f"(blank = verified; only populate for Partial/Not verified/Needs verification)"
        )

    m = BANNED_SECTIONS.search(content)
    if m:
        errors.append(
            f"Section '## {m.group(1)}' found — test details belong in "
            f"open-items.md or commit history, not the coverage matrix"
        )

    if LAST_VERIFIED_LINE.search(content):
        errors.append(
            "'Last verified:' line found — remove date stamps from coverage matrix"
        )

    if re.search(r"~~[^~]+~~", content):
        errors.append(
            "Struck-through text (~~...~~) found — remove reclassified items "
            "and merge into the appropriate Mapped section"
        )

    if re.search(r"\|\s*Documented\s*\|", content):
        errors.append(
            "'Documented' found in Notes column — use 'Not verified' instead"
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument(
        "--verbose", action="store_true", help="Print passing skills too"
    )
    parser.add_argument(
        "--base", default=None,
        help="Also require every matrix id this branch introduces to be unused on "
             "this revision (e.g. --base origin/main). Needs git; CI passes it.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    skills = find_convert_skills(root)
    if not skills:
        print("No ts-convert-* skills found. Nothing to check.")
        return 0

    failures: list[tuple[str, str]] = []

    # Self-check the exemption list before anything else: every BACKLOG entry must
    # be traceable (dated or referenced), or the whole validator fails.
    for msg in _bad_backlog_justifications():
        failures.append(("(BACKLOG)", msg))

    if args.base:
        present = [
            skill_dir / "references" / "coverage-matrix.md"
            for name, skill_dir in skills
            if name not in BACKLOG
            and (skill_dir / "references" / "coverage-matrix.md").exists()
        ]
        try:
            collisions = matrix_novelty_violations(root, args.base, present)
        except BaseUnavailable as exc:
            print(f"FAIL  coverage-matrix id novelty: {exc}")
            return 1
        for hit in collisions:
            failures.append(("(NOVELTY)", f"id introduced here but already used on "
                                          f"{args.base} — {hit}"))

    for name, skill_dir in skills:
        matrix_path = skill_dir / "references" / "coverage-matrix.md"

        if name in BACKLOG:
            if args.verbose:
                print(f"  OK   {name} — backlogged ({BACKLOG[name]})")
            continue

        if not matrix_path.is_file():
            failures.append((name, f"Missing {matrix_path.relative_to(root)}"))
            continue

        errors = validate_matrix(matrix_path)
        if errors:
            for err in errors:
                failures.append((name, err))
        elif args.verbose:
            print(f"  OK   {name} — coverage matrix valid")

    if failures:
        print(f"\n{len(failures)} issue(s) with coverage matrices:\n")
        for name, msg in failures:
            print(f"  ✗ {name}: {msg}")
        print()
        print("Every ts-convert-* skill must have references/coverage-matrix.md with:")
        print("  - A '## Mapped Constructs' section with table rows")
        print("  - An '## Unmapped Constructs' or '## Limitations' section")
        print("  - 'Notes' as the last column header (not 'Verified' or 'Verified Against')")
        print("  - 'Not verified' (not 'Documented') for items not live-tested")
        print("  - No 'Last verified:' date line, '## Test Workbooks', or struck-through text")
        print()
        print("To defer: add the skill to BACKLOG in this file with a justification.")
        return 1

    passing = len(skills) - len([n for n, _ in skills if n in BACKLOG])
    backlogged = len([n for n, _ in skills if n in BACKLOG])
    msg = f"All {passing} conversion skill(s) have valid coverage matrices."
    if backlogged:
        msg += f" ({backlogged} backlogged)"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
