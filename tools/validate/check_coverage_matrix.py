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


BACKLOG: dict[str, str] = {
    "ts-convert-from-databricks-mv": "backlog — add after Tableau matrix ships",
    "ts-convert-to-snowflake-sv": "backlog — add after Tableau matrix ships",
    "ts-convert-to-databricks-mv": "backlog — add after Tableau matrix ships",
}

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


def validate_matrix(matrix_path: Path) -> list[str]:
    """Check the coverage matrix has the required sections and format. Return errors."""
    errors: list[str] = []
    try:
        content = matrix_path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"Cannot read {matrix_path}: {e}"]

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
            f"(blank = verified; only populate for Partial/Documented/Needs verification)"
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

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument(
        "--verbose", action="store_true", help="Print passing skills too"
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    skills = find_convert_skills(root)
    if not skills:
        print("No ts-convert-* skills found. Nothing to check.")
        return 0

    failures: list[tuple[str, str]] = []

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
