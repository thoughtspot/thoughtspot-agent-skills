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
# Item headers come in two styles across the repo: `## Item 4 — …` and `## #4 — …`.
# The original regex only matched `## Item N`, so it silently ignored 6 of 7 files.
_ITEM_HEADER = re.compile(r'^##\s+(#?\s*(?:Item\s+)?\d+[^\n]*)', re.MULTILINE)
_PLACEHOLDER = re.compile(r'\[Record result here\]')

# Status markers meaning "not verified before ship". Matched as whole tokens anywhere in
# the item's section — the repo uses several formats (`**Status:** UNTESTED`,
# `Status: NOT IMPLEMENTED`, `— NEEDS VERIFICATION`, `… UNVERIFIED`).
_UNRESOLVED_MARKERS = ["UNTESTED", "NEEDS VERIFICATION", "UNVERIFIED", "NOT IMPLEMENTED"]
_MARKER_RE = re.compile(
    r'(?<![A-Za-z])(' + '|'.join(re.escape(m) for m in _UNRESOLVED_MARKERS) + r')(?![A-Za-z])'
)

# Resolved-by-decision convention: the repo's open-items status vocabulary (documented
# legend, e.g. agents/cli/ts-convert-from-looker/references/open-items.md:4) is
# `OPEN | VERIFIED | DEFERRED | WONT-FIX`. A `NOT IMPLEMENTED` item is a deliberate,
# documented non-goal — not a shipped-unverified gap — when its section carries an
# explicit decision qualifier: a `(LOW)` / `— LOW` / `LOW priority` annotation, an
# explicit `WONT-FIX`/`WONTFIX` or `DEFERRED` status, or a `**Workaround:**` line (a
# documented workaround is itself evidence the decision not to build was made on
# purpose). Any ONE of these qualifiers is sufficient — they are not required in
# combination. See from-snowflake-sv items #2-#5 (audit 2026-07-11 / PR #210 finding)
# for the motivating case: `NOT IMPLEMENTED (LOW)` + `**Workaround:**` was previously
# a false-positive FAIL.
#
# This exception applies ONLY to the `NOT IMPLEMENTED` marker. A bare `NOT IMPLEMENTED`
# with none of these qualifiers is still a genuine unresolved gap and must stay flagged
# — that is the validator's actual purpose. `UNTESTED` / `NEEDS VERIFICATION` /
# `UNVERIFIED` are unaffected; those always mean "not yet verified," never "decided
# not to do."
_RESOLVED_DECISION_MARKERS = [
    r'\(LOW\)',              # "NOT IMPLEMENTED (LOW)"
    r'—\s*LOW\b',            # "— LOW" / "— LOW priority" (em-dash form)
    r'\bLOW priority\b',     # "LOW priority" without a preceding em-dash
    r'WONT-FIX',
    r'WONTFIX',
    r'DEFERRED',
    r'\*\*Workaround:\*\*',  # a documented workaround = the decision was made
]
_RESOLVED_DECISION_RE = re.compile('|'.join(_RESOLVED_DECISION_MARKERS))


def check_open_items_file(path: Path) -> list[tuple[str, str]]:
    """
    Return list of (item_title, reason) for unresolved items.

    Unresolved = the section contains an unresolved status marker
    (UNTESTED / NEEDS VERIFICATION / UNVERIFIED / NOT IMPLEMENTED) or the
    `[Record result here]` placeholder. Handles both `## Item N` and `## #N` headers.

    Exception: `NOT IMPLEMENTED` is resolved-by-decision (not unresolved) when the
    section also carries a decision qualifier — see `_RESOLVED_DECISION_MARKERS`.
    A bare `NOT IMPLEMENTED` with no qualifier is still flagged.
    """
    content = path.read_text(encoding="utf-8")

    splits = list(_ITEM_HEADER.finditer(content))
    if not splits:
        return []

    unresolved = []
    for i, match in enumerate(splits):
        title = " ".join(match.group(1).split())  # normalise whitespace
        start = match.start()
        end = splits[i + 1].start() if i + 1 < len(splits) else len(content)
        section = content[start:end]

        marker = _MARKER_RE.search(section)
        if marker:
            marker_text = marker.group(1)
            # A qualified "NOT IMPLEMENTED" (LOW / WONT-FIX / DEFERRED / has a
            # Workaround) is a deliberate non-goal, not an unresolved gap — skip it.
            # Other markers (UNTESTED, NEEDS VERIFICATION, UNVERIFIED) always flag.
            if marker_text == "NOT IMPLEMENTED" and _RESOLVED_DECISION_RE.search(section):
                continue
            unresolved.append((title, f"Status: {marker_text}"))
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
        repo_root.glob("agents/cli/*/references/open-items.md")
    ) + sorted(
        repo_root.glob("agents/claude/*/references/open-items.md")
    ) + sorted(
        repo_root.glob("agents/coco-snowsight/*/references/open-items.md")
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
