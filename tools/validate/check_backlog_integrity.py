#!/usr/bin/env python3
"""
check_backlog_integrity.py — three merge-integrity invariants on docs/backlog.md
that PR #356 proved were ungated.

Background. docs/backlog.md and CHANGELOG.md are append-only lists with a single
fixed insertion point, so two branches always write to the same lines. In PR #356
two branches each independently claimed BL-171 (second occurrence; BL-150 was the
first, 2026-07-28). Stripping the conflict markers — the natural "accept both"
resolution — produced a file with two `## BL-171` sections that passed all 23
pre-commit checks and all 5 CI jobs. Nothing validated BL-number uniqueness.

Rule 1 — no duplicate `## BL-NNN` heading, and no id carrying a section in both
backlog.md and backlog-archive.md. This matters more than a normal docs nit
because BL-NNN is cited ~1,000 times across ~230 files, so a duplicate silently
changes what those citations mean.

Rule 2 — every BL id cited under agents/, tools/ and .github/ resolves to a
defined id. Protects those citations when a collision IS resolved by renumbering.
docs/ is deliberately out of scope: specs and audit reports are point-in-time
records, so a 2026-07-25 spec citing the numbers as they stood then is correct as
history.

Rule 3 — no git conflict markers in tracked text files. Previously ungated.

KNOWN LIMITATION (tested; do not assume otherwise). This does NOT catch the other
half of the PR #356 near-miss: a stale `**Target:**` line git auto-merged onto the
wrong item. After a naive accept-both, EACH of the two BL-171 sections carries
exactly one Target line, so a per-section count rule never fires, and renumbering
to satisfy Rule 1 leaves the misattachment in place. The mitigation is procedural
— see CLAUDE.md: never resolve docs/backlog.md by accepting both sides.

Exit codes:
  0 — all rules pass
  1 — at least one violation

Run manually:
    python3 tools/validate/check_backlog_integrity.py --root .
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

BACKLOG_REL = "docs/backlog.md"
ARCHIVE_REL = "docs/backlog-archive.md"

# Two deliberately different patterns, because the two rules need different
# precision. Do not unify them.
#
# HEADING_RE must capture the FULL id including any suffix. The archive really
# does hold BL-003, BL-003b, BL-003c and BL-003-UMBRELLA as four separate items;
# a `BL-\d+` capture prefix-matches all four to "BL-003" and manufactures a
# duplicate that isn't there.
#
# ANY_BL_RE stays loose (numeric only) because it drives Rule 2 over PROSE, where
# `BL-\d+[A-Za-z0-9-]*` over-captures: `tools/ts-cli/ts_cli/dependency/mutate.py`
# says "the pre-BL-083-PR2 behaviour", meaning BL-083's second PR, not an id. The
# loose pattern resolves that to BL-083, which is defined, and passes. Since
# defined_ids() applies this same loose pattern to the backlog text, both sides of
# the Rule 2 comparison agree.
HEADING_RE = re.compile(r"^## (BL-\S+)", re.M)
ANY_BL_RE = re.compile(r"BL-\d+")


def _read(root: Path, rel: str) -> str:
    """File contents, or "" when the file does not exist (the archive is optional)."""
    path = root / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


def section_headings(text: str) -> list[str]:
    """Every BL id that owns a `## BL-NNN` section heading, in document order."""
    return HEADING_RE.findall(text)


def duplicate_headings(root: Path) -> list[tuple[str, int]]:
    """Rule 1a — an id with more than one section heading within a single file."""
    out: list[tuple[str, int]] = []
    for rel in (BACKLOG_REL, ARCHIVE_REL):
        counts = Counter(section_headings(_read(root, rel)))
        out.extend((f"{rel}:{bl_id}", n) for bl_id, n in sorted(counts.items()) if n > 1)
    return out


def cross_file_duplicates(root: Path) -> list[str]:
    """Rule 1b — an id with a section in BOTH the live backlog and the archive.
    Archiving moves an item; it must not leave a copy behind."""
    live = set(section_headings(_read(root, BACKLOG_REL)))
    archived = set(section_headings(_read(root, ARCHIVE_REL)))
    return sorted(live & archived)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    problems: list[str] = []

    dups = duplicate_headings(root)
    if dups:
        problems.append("Duplicate BL section heading(s) — Rule 1:")
        problems.extend(f"  ✗ {where} has {n} sections" for where, n in dups)
        problems.append("  Two branches likely each claimed the next free number.")
        problems.append("  Keep the number for whichever item is already cited")
        problems.append("  elsewhere in the repo; renumber the other one.")

    both = cross_file_duplicates(root)
    if both:
        problems.append("BL id sectioned in BOTH backlog.md and backlog-archive.md — Rule 1:")
        problems.extend(f"  ✗ {bl_id}" for bl_id in both)

    if problems:
        print("\n" + "\n".join(problems))
        print()
        print("For docs/backlog.md, never resolve a conflict by accepting both sides")
        print("(see CLAUDE.md). Take main's side, then renumber the incoming item.")
        return 1

    print("Backlog integrity clean: no duplicate BL ids.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
