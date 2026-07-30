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
  2 — the check could not run (git unavailable or refused); NOT a pass

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

# Rule 2 scope — the live, load-bearing surfaces where a stale id misdirects
# current work. docs/ is deliberately absent: specs and audit reports are
# point-in-time records, and forcing them to track later renumbering would be
# wrong. Widening this is a one-line change if it ever proves too narrow.
CITATION_SCOPE = ("agents", "tools", ".github")

# Built by repetition so the literal marker strings never appear in this file.
# A literal here would make this validator flag its own source, and its own tests.
MARK_OURS = "<" * 7
MARK_THEIRS = ">" * 7
MARK_SPLIT = "=" * 7

# Two deliberately different patterns, because the two rules need different
# precision. Do not unify them.
#
# HEADING_RE must capture the FULL id including any suffix, but stop before
# trailing punctuation so it doesn't fold "## BL-171:" into an id distinct from
# "BL-171" (which would let a genuine duplicate escape Rule 1 entirely). The
# archive really does hold BL-003, BL-003b, BL-003c and BL-003-UMBRELLA as four
# separate items — a bare `BL-\d+` capture prefix-matches all four to "BL-003"
# and manufactures a duplicate that isn't there — so the id chars must include
# letters and hyphens, not just digits. `[A-Za-z0-9-]+` gets both properties:
# it stays whole through a suffix, and it stops at the first space, colon,
# period, or em dash that follows the id in a real heading.
#
# ANY_BL_RE stays loose (numeric only) because it drives Rule 2 over PROSE, where
# `BL-[A-Za-z0-9-]+` over-captures: `tools/ts-cli/ts_cli/dependency/mutate.py`
# says "the pre-BL-083-PR2 behaviour", meaning BL-083's second PR, not an id. The
# loose pattern resolves that to BL-083, which is defined, and passes. Since
# defined_ids() applies this same loose pattern to the backlog text, both sides of
# the Rule 2 comparison agree.
HEADING_RE = re.compile(r"^## (BL-[A-Za-z0-9-]+)", re.M)
ANY_BL_RE = re.compile(r"BL-\d+")


def _read(root: Path, rel: str) -> str:
    """File contents, or "" when the file does not exist (the archive is optional)."""
    path = root / rel
    return path.read_text(encoding="utf-8") if path.exists() else ""


class GitUnavailable(RuntimeError):
    """git could not be run, or refused the request. Distinct from "found nothing"."""


def _git_lines(args: list[str], root: Path) -> list[str]:
    """Run git and return non-blank stdout lines.

    Exit-code handling is load-bearing. `git grep` exits **1** on "no matches",
    which is a clean empty result. Anything **above 1** is a real failure (128 =
    not a git repository or bad pathspec, 127 = git not on PATH). Treating those
    as "no matches" makes the gate pass VACUOUSLY — a validator that goes green
    because it could not run is exactly the silent-green failure this whole file
    exists to prevent, so it raises instead.
    """
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, cwd=root, check=False,
    )
    if result.returncode > 1:
        raise GitUnavailable(
            f"`git {' '.join(args)}` failed with exit {result.returncode}: "
            f"{result.stderr.strip() or '(no stderr)'}"
        )
    return [line for line in result.stdout.splitlines() if line.strip()]


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


def defined_ids(root: Path) -> set[str]:
    """Every BL id that resolves to something. Deliberately broader than
    section_headings(): the archive index and the priority-index tables list ids
    that no longer own a section, and a citation to one of those is still valid."""
    return set(ANY_BL_RE.findall(_read(root, BACKLOG_REL))) | set(
        ANY_BL_RE.findall(_read(root, ARCHIVE_REL))
    )


def dangling_citations(root: Path) -> dict[str, list[str]]:
    """Rule 2 — ids cited inside CITATION_SCOPE that resolve to nothing.

    Greps whole lines rather than using `git grep -o` so one line carrying two ids
    reports both, and so the path:lineno prefix is available for the message.
    """
    defined = defined_ids(root)
    found: dict[str, set[str]] = {}
    for line in _git_lines(
        ["grep", "-nI", "-e", r"BL-[0-9]\+", "--", *CITATION_SCOPE], root
    ):
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path, lineno, body = parts
        for bl_id in ANY_BL_RE.findall(body):
            if bl_id not in defined:
                found.setdefault(bl_id, set()).add(f"{path}:{lineno}")
    return {bl_id: sorted(places) for bl_id, places in sorted(found.items())}


def conflict_markers(root: Path) -> list[str]:
    """Rule 3 — tracked text files carrying git conflict markers.

    The split marker is only counted when the file also has an ours/theirs marker:
    a bare 7-equals line is a legal Markdown setext h1 underline and appears in
    real documents.
    """
    hits: list[str] = []
    for rel in _git_lines(["ls-files"], root):
        try:
            lines = (root / rel).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # binary, symlink, or gone — not a conflict-marker surface
        sides = [
            i + 1
            for i, line in enumerate(lines)
            if line.startswith(MARK_OURS) or line.startswith(MARK_THEIRS)
        ]
        if not sides:
            continue
        splits = [i + 1 for i, line in enumerate(lines) if line.rstrip() == MARK_SPLIT]
        hits.extend(f"{rel}:{n}" for n in sorted(sides + splits))
    return hits


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
        problems.append("  Citation count decides: keep the number for whichever item")
        problems.append("  is already cited elsewhere in the repo; renumber the other.")
        problems.append("  If neither (or both) are cited, keep main's and renumber")
        problems.append("  the incoming one.")

    both = cross_file_duplicates(root)
    if both:
        problems.append("BL id sectioned in BOTH backlog.md and backlog-archive.md — Rule 1:")
        problems.extend(f"  ✗ {bl_id}" for bl_id in both)

    # Both remaining rules shell out to git, so one guard covers both. Exit 2 means
    # "could not run", which must never read as clean — see the Exit codes block.
    try:
        dangling = dangling_citations(root)
        markers = conflict_markers(root)
    except GitUnavailable as exc:
        # Rule 1 may have already found real violations above (problems is
        # populated before this try block runs) — print them rather than
        # discarding them, so the operator sees BOTH "problems were found" and
        # "some rules could not run", not just the git error.
        if problems:
            print("\n" + "\n".join(problems))
            print()
            print(
                "The findings above were collected before the check below failed to "
                "run — some rules found problems, others could not run at all.",
                file=sys.stderr,
            )
        print(f"Backlog integrity check could not run: {exc}", file=sys.stderr)
        return 2

    if dangling:
        problems.append("BL id cited but never defined — Rule 2:")
        for bl_id, places in dangling.items():
            shown = ", ".join(places[:4])
            more = f" (+{len(places) - 4} more)" if len(places) > 4 else ""
            problems.append(f"  ✗ {bl_id} cited at {shown}{more}")
        problems.append("  Either the id was renumbered and a citation was missed,")
        problems.append("  or the backlog entry was deleted instead of archived.")

    if markers:
        problems.append("Git conflict marker(s) in tracked file(s) — Rule 3:")
        problems.extend(f"  ✗ {hit}" for hit in markers[:20])
        if len(markers) > 20:
            problems.append(f"  ... and {len(markers) - 20} more")

    if problems:
        print("\n" + "\n".join(problems))
        print()
        # Generic on purpose — this prints for a Rule 2 or Rule 3 hit too, where a
        # specific renumbering directive wouldn't apply. The citation-count decision
        # procedure itself lives in the Rule 1 block above (where it's relevant) and
        # in CLAUDE.md (in full); this is a pointer, not a restatement.
        print("For docs/backlog.md, never resolve a conflict by accepting both sides —")
        print("see CLAUDE.md ('Resolving conflicts...') for the full decision procedure.")
        return 1

    print(
        "Backlog integrity clean: no duplicate BL ids, no dangling citations, "
        "no conflict markers."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
