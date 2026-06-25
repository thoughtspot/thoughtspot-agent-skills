#!/usr/bin/env python3
"""
check_mapping_currency.py — soft-warn when a shared mapping OR schema file lacks a
current currency anchor (see .claude/rules/repo-audit.md, angle 13 "Product currency").

Cross-platform mappings AND the platform schema files encode assumptions about products
that move (a function that "can't" translate may gain a native equivalent; a construct
may be deprecated; a new chart library or semantic-view feature may appear). A validator
can't know the product's current state — but it CAN nudge when an assumption hasn't been
re-checked in a while. The 2026-06-17 audit found every drift lived in an *anchorless
schema file*, so schemas are covered here too, not just mappings.

Each file under agents/shared/mappings/ and agents/shared/schemas/ should carry an
anchor near the top:

    <!-- currency: <platform> — <YYYY-MM> (<context>) -->

This is a NUDGE, never a block: external knowledge can't gate a PR. It warns when a
changed mapping has no anchor, or one older than STALE_MONTHS. The weekly external sweep
is what actually re-validates and bumps the anchors.

Usage:
    python3 tools/validate/check_mapping_currency.py --root .            # all mappings
    python3 tools/validate/check_mapping_currency.py --root . --staged   # staged only (pre-commit)
    python3 tools/validate/check_mapping_currency.py --root . --check    # exit 1 if any issue
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# ── CONFIG (repo-specific) ───────────────────────────────────────────────────
ANCHORED_DIRS = ("agents/shared/mappings", "agents/shared/schemas")
# Individual files (outside the dirs above) that also carry a currency anchor — e.g. a
# skill reference encoding external product behaviour that moves (SpotQL limitations).
ANCHORED_FILES = (
    "agents/cli/ts-object-model-spotql-query/references/limitations.md",
)
STALE_MONTHS = 6
# ─────────────────────────────────────────────────────────────────────────────

# <!-- currency: snowflake — 2026-06 (Cortex Analyst GA) -->   (en/em dash or hyphen)
ANCHOR_RE = re.compile(
    r"<!--\s*currency:\s*(?P<platform>[^—–\-]+?)\s*[—–-]\s*(?P<year>\d{4})-(?P<month>\d{2})\b",
    re.IGNORECASE,
)


def _months_between(anchor: date, today: date) -> int:
    return (today.year - anchor.year) * 12 + (today.month - anchor.month)


# A missing/malformed anchor is a presence failure (BLOCKING — a new shared file must
# carry one); a stale anchor is a soft nudge (external knowledge can't gate a PR, and
# staleness must not block unrelated PRs as anchors age).
BLOCKING_KINDS = {"missing", "malformed"}


def check_file(path: Path, today: date) -> tuple[str, str] | None:
    """Return (kind, message) for a missing/malformed/stale anchor, else None.
    kind ∈ {"missing", "malformed", "stale"}."""
    try:
        # only need the head of the file — the anchor lives near the top
        head = "".join(path.read_text(encoding="utf-8").splitlines(keepends=True)[:15])
    except OSError:
        return None
    m = ANCHOR_RE.search(head)
    if not m:
        return ("missing", "no currency anchor — add `<!-- currency: <platform> — YYYY-MM (context) -->` near the top")
    try:
        anchor = date(int(m.group("year")), int(m.group("month")), 1)
    except ValueError:
        return ("malformed", f"malformed currency anchor date: {m.group('year')}-{m.group('month')}")
    age = _months_between(anchor, today)
    if age > STALE_MONTHS:
        return ("stale", f"currency anchor is {age} months old ({m.group('year')}-{m.group('month')}) — re-validate against the current product")
    return None


def _is_anchored_path(rel: str) -> bool:
    if rel in ANCHORED_FILES:
        return True
    return rel.endswith(".md") and any(rel.startswith(d + "/") for d in ANCHORED_DIRS)


def _staged_anchored_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return [
        repo_root / f
        for f in result.stdout.splitlines()
        if _is_anchored_path(f) and (repo_root / f).exists()
    ]


def _all_anchored_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for d in ANCHORED_DIRS:
        base = repo_root / d
        if base.is_dir():
            files.extend(base.rglob("*.md"))
    for f in ANCHORED_FILES:
        p = repo_root / f
        if p.exists():
            files.append(p)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nudge on stale mapping/schema currency anchors.")
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument("--staged", action="store_true", help="Only staged mapping/schema files")
    parser.add_argument("--check", action="store_true", help="Exit 1 if any issue (default: warn-only)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    today = date.today()
    files = _staged_anchored_files(repo_root) if args.staged else _all_anchored_files(repo_root)

    issues: list[tuple[Path, str, str]] = []  # (rel, kind, msg)
    for f in files:
        res = check_file(f, today)
        if res:
            issues.append((f.relative_to(repo_root), res[0], res[1]))

    if issues:
        print("  Currency anchors:")
        for rel, kind, msg in issues:
            tag = "FAIL" if kind in BLOCKING_KINDS else "nudge"
            print(f"    • [{tag}] {rel}: {msg}")
        blocking = [i for i in issues if i[1] in BLOCKING_KINDS]
        # --check fails ONLY on presence (missing/malformed); staleness is always soft so
        # it never blocks an unrelated PR as anchors age.
        return 1 if (args.check and blocking) else 0

    if not args.staged:
        print(f"All {len(files)} anchored file(s) have a current currency anchor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
