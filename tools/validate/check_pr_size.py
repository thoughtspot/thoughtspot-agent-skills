#!/usr/bin/env python3
"""
check_pr_size.py — flag a large PR for a manual content review (warn-only in CI).

A PR that adds a lot of files or a lot of non-code material (images, sample workbooks,
example outputs, fixtures) is exactly where customer data hides: nobody reads 300
fixture files line by line, and `check_customer_references` only recognises links,
not names or data. This check does not judge the content; it makes the size VISIBLE
so a human decides whether to read it.

Thresholds (either one trips the flag):
  - more than MAX_ADDED_FILES files added by the PR;
  - more than MAX_ASSET_BYTES of added/modified non-code assets — files with an asset
    suffix (images, PDFs, office documents, BI workbooks, archives, data files) or any
    file under an examples / fixtures / samples / test-data directory.

Output: a GitHub Actions `::warning::` annotation (shown on the PR's checks page) plus
a plain summary in the log. Exit codes:
  0 — under both thresholds, or over a threshold with --warn (CI runs it this way)
  1 — over a threshold without --warn, OR --base was given and the diff could not be
      computed. A git
      failure is never reported as "small PR": that would be the silent pass the
      repo's gates refuse (see _git).

Usage:
    python3 tools/validate/check_pr_size.py --root . --base origin/main --warn
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

from _git import GitEnumerationError, git_status_paths

MAX_ADDED_FILES = 150
MAX_ASSET_BYTES = 2 * 1024 * 1024

ASSET_SUFFIXES = {
    # images
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".tif", ".tiff",
    # documents
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".odt", ".ods",
    # BI workbooks / bundles
    ".twb", ".twbx", ".tds", ".tdsx", ".hyper", ".qvf", ".pbix", ".pbit",
    # archives
    ".zip", ".tar", ".gz", ".tgz", ".7z",
    # data files
    ".csv", ".tsv", ".parquet", ".xml",
}

# A directory segment that marks its contents as example material, whatever the suffix.
_ASSET_DIR_RE = re.compile(
    r"^(?:examples?|fixtures?|samples?|test[-_]?data|worked[-_]examples)$", re.IGNORECASE
)


def is_asset(rel_path: str) -> bool:
    p = Path(rel_path)
    if p.suffix.lower() in ASSET_SUFFIXES:
        return True
    return any(_ASSET_DIR_RE.match(seg) for seg in p.parts[:-1])


def measure(repo_root: Path, base: str) -> tuple[int, int, list[tuple[str, int]]]:
    """Return (files added, asset bytes, largest assets) for ``base...HEAD``.

    Raises GitEnumerationError if the diff cannot be computed.
    """
    records = git_status_paths(["diff", f"{base}...HEAD"], repo_root)
    added = 0
    assets: list[tuple[str, int]] = []
    for _prefix, status, path in records:
        kind = status[:1]
        if kind in ("A", "C"):
            added += 1
        if kind in ("A", "C", "M", "R") and is_asset(path):
            f = repo_root / path
            if f.is_file():
                assets.append((path, f.stat().st_size))
    assets.sort(key=lambda a: a[1], reverse=True)
    return added, sum(size for _, size in assets), assets


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Flag a large PR for manual content review.")
    parser.add_argument("--root", default=".", help="Repo root (default: current dir)")
    parser.add_argument("--base", help="Base ref to diff against (e.g. origin/main). PR-only: "
                        "without it there is no PR to measure, and the check says it skipped")
    parser.add_argument("--warn", action="store_true",
                        help="Report over-threshold PRs as a warning and exit 0")
    args = parser.parse_args(argv)
    repo_root = Path(args.root).resolve()

    if not args.base:
        print("SKIP  no --base given: PR size is measured against a base ref (CI passes one).")
        return 0

    try:
        added, asset_bytes, assets = measure(repo_root, args.base)
    except GitEnumerationError as exc:
        print(f"FAIL  could not diff against {args.base}: {exc}")
        return 1

    reasons = []
    if added > MAX_ADDED_FILES:
        reasons.append(f"{added} files added (threshold {MAX_ADDED_FILES})")
    if asset_bytes > MAX_ASSET_BYTES:
        reasons.append(f"{_mb(asset_bytes)} of non-code assets (threshold {_mb(MAX_ASSET_BYTES)})")

    if not reasons:
        print(f"PR size OK: {added} file(s) added, {_mb(asset_bytes)} of non-code assets.")
        return 0

    summary = "; ".join(reasons)
    print(f"::warning title=Large PR - manual content review needed::{summary}. "
          "Read the examples, fixtures and images for customer names, tenant URLs and "
          "customer data before merging (.claude/rules/security.md).")
    print(f"LARGE PR: {summary}")
    if assets:
        print("Largest non-code assets:")
        for path, size in assets[:10]:
            print(f"  {_mb(size):>9}  {path}")
    print("This repo is public. A reviewer should read the non-code content, not just the code.")
    return 0 if args.warn else 1


if __name__ == "__main__":
    sys.exit(main())
