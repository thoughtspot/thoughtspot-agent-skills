#!/usr/bin/env python3
"""
check_skill_versions.py — verify every SKILL.md has a ## Changelog section
with at least one valid semver entry.

Every skill must have:
  ## Changelog
  | Version | Date | Summary |
  |---|---|---|
  | X.Y.Z | YYYY-MM-DD | ... |

Usage:
    python tools/validate/check_skill_versions.py
    python tools/validate/check_skill_versions.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Matches a changelog table row: | version | date | summary |
ROW_RE = re.compile(
    r"^\|\s*(\d+\.\d+\.\d+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|.+\|"
)


def check_skill(skill_md: Path) -> list[str]:
    """Return a list of error strings for this SKILL.md, or [] if valid."""
    text = skill_md.read_text(encoding="utf-8")
    errors: list[str] = []

    if "## Changelog" not in text:
        errors.append("missing ## Changelog section")
        return errors

    # Find everything after ## Changelog
    changelog_body = text.split("## Changelog", 1)[1]

    rows = [line for line in changelog_body.splitlines() if ROW_RE.match(line.strip())]
    if not rows:
        errors.append("## Changelog has no valid version rows (expected | X.Y.Z | YYYY-MM-DD | ... |)")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check all SKILL.md files have a changelog.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    skills_dir = repo_root / "agents" / "claude"

    if not skills_dir.exists():
        print(f"ERROR: {skills_dir} not found — is --root pointing to the repo root?")
        return 1

    # Only check files tracked by git — untracked wip files are not yet shipped
    import subprocess
    result = subprocess.run(
        ["git", "ls-files", "agents/claude"],
        capture_output=True, text=True, cwd=repo_root
    )
    tracked = set(result.stdout.splitlines())

    skill_files = sorted(
        f for f in skills_dir.glob("*/SKILL.md")
        if str(f.relative_to(repo_root)) in tracked
    )
    if not skill_files:
        print(f"ERROR: no tracked SKILL.md files found under {skills_dir.relative_to(repo_root)}")
        return 1

    failed = 0
    for skill_md in skill_files:
        rel = skill_md.relative_to(repo_root)
        errors = check_skill(skill_md)
        if errors:
            for err in errors:
                print(f"FAIL  {rel}: {err}")
            failed += 1
        else:
            # Extract current version from first changelog row for display
            text = skill_md.read_text(encoding="utf-8")
            changelog_body = text.split("## Changelog", 1)[1]
            rows = [l.strip() for l in changelog_body.splitlines() if ROW_RE.match(l.strip())]
            version = rows[0].split("|")[1].strip() if rows else "?"
            print(f"PASS  {rel}: v{version}")

    if failed:
        print()
        print(f"{failed} skill(s) missing a valid changelog.")
        print("Add a ## Changelog section with at least one row: | X.Y.Z | YYYY-MM-DD | summary |")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
