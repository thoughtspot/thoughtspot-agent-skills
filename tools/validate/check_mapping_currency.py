#!/usr/bin/env python3
"""
check_mapping_currency.py — soft-warn when a platform mapping file lacks a current
currency anchor (see .claude/rules/repo-audit.md, angle 13 "Product currency").

Cross-platform mappings encode assumptions about products that move (a function that
"can't" translate may gain a native equivalent; a construct may be deprecated; a new
chart library or semantic-view feature may appear). A validator can't know the product's
current state — but it CAN nudge when an assumption hasn't been re-checked in a while.

Each file under agents/shared/mappings/ should carry an anchor near the top:

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
MAPPINGS_DIR = "agents/shared/mappings"
STALE_MONTHS = 6
# ─────────────────────────────────────────────────────────────────────────────

# <!-- currency: snowflake — 2026-06 (Cortex Analyst GA) -->   (en/em dash or hyphen)
ANCHOR_RE = re.compile(
    r"<!--\s*currency:\s*(?P<platform>[^—–\-]+?)\s*[—–-]\s*(?P<year>\d{4})-(?P<month>\d{2})\b",
    re.IGNORECASE,
)


def _months_between(anchor: date, today: date) -> int:
    return (today.year - anchor.year) * 12 + (today.month - anchor.month)


def check_file(path: Path, today: date) -> str | None:
    """Return a warning string for a missing/stale anchor, else None."""
    try:
        # only need the head of the file — the anchor lives near the top
        head = "".join(path.read_text(encoding="utf-8").splitlines(keepends=True)[:15])
    except OSError:
        return None
    m = ANCHOR_RE.search(head)
    if not m:
        return "no currency anchor — add `<!-- currency: <platform> — YYYY-MM (context) -->` near the top"
    try:
        anchor = date(int(m.group("year")), int(m.group("month")), 1)
    except ValueError:
        return f"malformed currency anchor date: {m.group('year')}-{m.group('month')}"
    age = _months_between(anchor, today)
    if age > STALE_MONTHS:
        return f"currency anchor is {age} months old ({m.group('year')}-{m.group('month')}) — re-validate against the current product"
    return None


def _staged_mapping_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return [
        repo_root / f
        for f in result.stdout.splitlines()
        if f.startswith(MAPPINGS_DIR) and f.endswith(".md") and (repo_root / f).exists()
    ]


def _all_mapping_files(repo_root: Path) -> list[Path]:
    base = repo_root / MAPPINGS_DIR
    return sorted(base.rglob("*.md")) if base.is_dir() else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Nudge on stale platform mapping anchors.")
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument("--staged", action="store_true", help="Only staged mapping files")
    parser.add_argument("--check", action="store_true", help="Exit 1 if any issue (default: warn-only)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    today = date.today()
    files = _staged_mapping_files(repo_root) if args.staged else _all_mapping_files(repo_root)

    issues: list[tuple[Path, str]] = []
    for f in files:
        msg = check_file(f, today)
        if msg:
            issues.append((f.relative_to(repo_root), msg))

    if issues:
        print("  Mapping currency:")
        for rel, msg in issues:
            print(f"    • {rel}: {msg}")
        return 1 if args.check else 0

    if not args.staged:
        print(f"All {len(files)} mapping file(s) have a current currency anchor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
