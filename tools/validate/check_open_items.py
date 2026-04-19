#!/usr/bin/env python3
"""
check_open_items.py — flag unresolved items in references/open-items.md files.

An item is "unresolved" if its Finding section still reads "UNTESTED" or contains
the placeholder "[Record result here]".

Usage:
    python tools/validate/check_open_items.py
    python tools/validate/check_open_items.py --root /path/to/repo
    python tools/validate/check_open_items.py --warn  # exit 0 but report (pre-commit safe)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Patterns that indicate an unresolved item
_STATUS_UNTESTED = re.compile(r'\*\*Status:\*\*\s+UNTESTED', re.MULTILINE)
_PLACEHOLDER = re.compile(r'\[Record result here\]')
_ITEM_HEADER = re.compile(r'^## (Item \d+[^\n]*)', re.MULTILINE)


def check_open_items_file(path: Path) -> list[tuple[str, str]]:
    """
    Return list of (item_title, reason) for unresolved items.
    reason is 'Status: UNTESTED' or 'Finding not recorded'.
    """
    content = path.read_text(encoding="utf-8")

    # Split into sections at each ## Item N header
    splits = list(_ITEM_HEADER.finditer(content))
    if not splits:
        return []

    unresolved = []
    for i, match in enumerate(splits):
        title = match.group(1).strip()
        start = match.start()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(content)
        section = content[start:end]

        if _STATUS_UNTESTED.search(section):
            unresolved.append((title, "Status: UNTESTED"))
        elif _PLACEHOLDER.search(section):
            unresolved.append((title, "Finding not recorded"))

    return unresolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flag unresolved items in references/open-items.md files."
    )
    parser.add_argument("--root", default=".", help="Repo root (default: current dir)")
    parser.add_argument(
        "--warn",
        action="store_true",
        help="Exit 0 even if unresolved items found (prints WARN, not FAIL). "
             "Use in pre-commit so pre-existing items don't block commits.",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    open_items_files = sorted(
        repo_root.glob("agents/claude/*/references/open-items.md")
    )

    if not open_items_files:
        print("No open-items.md files found.")
        return 0

    total_unresolved = 0

    for f in open_items_files:
        rel = f.relative_to(repo_root)
        unresolved = check_open_items_file(f)
        if unresolved:
            level = "WARN" if args.warn else "FAIL"
            for title, reason in unresolved:
                print(f"{level}  {rel}  →  {title}  [{reason}]")
            total_unresolved += len(unresolved)
        else:
            print(f"PASS  {rel}  (all items resolved)")

    print()
    if total_unresolved:
        msg = f"{total_unresolved} unresolved open item(s) found."
        if args.warn:
            print(f"WARN: {msg}")
            print(
                "These items require live-instance verification before the skill ships. "
                "See references/open-items.md for test procedures."
            )
            return 0
        else:
            print(msg)
            print(
                "Resolve items by running the test procedures and recording findings "
                "in the 'Finding:' section, then change Status from UNTESTED to VERIFIED."
            )
            return 1

    print("All open items resolved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
