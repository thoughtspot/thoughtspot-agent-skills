#!/usr/bin/env python3
"""
check_skill_versions.py — verify every skill file across all runtimes has a
## Changelog section with at least one valid semver entry.

Covers:
  agents/claude/*/SKILL.md   — Claude Code skills
  agents/coco/*/SKILL.md     — Snowflake Cortex (CoCo) skills
  agents/cursor/rules/*.mdc  — Cursor AI rules

Every file must have:
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
import subprocess
import sys
from pathlib import Path

ROW_RE = re.compile(
    r"^\|\s*(\d+\.\d+\.\d+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|.+\|"
)


def check_skill(skill_file: Path) -> list[str]:
    """Return a list of error strings for this file, or [] if valid."""
    text = skill_file.read_text(encoding="utf-8")
    errors: list[str] = []

    if "## Changelog" not in text:
        errors.append("missing ## Changelog section")
        return errors

    changelog_body = text.split("## Changelog", 1)[1]
    rows = [line for line in changelog_body.splitlines() if ROW_RE.match(line.strip())]
    if not rows:
        errors.append("## Changelog has no valid version rows (expected | X.Y.Z | YYYY-MM-DD | ... |)")

    return errors


def get_tracked_files(repo_root: Path, path: str) -> set[str]:
    """Return git-tracked file paths under the given path (relative to repo root)."""
    result = subprocess.run(
        ["git", "ls-files", path],
        capture_output=True, text=True, cwd=repo_root,
    )
    return set(result.stdout.splitlines())


def collect_skill_files(repo_root: Path) -> list[Path]:
    """Return all tracked skill files across all runtimes."""
    files: list[Path] = []

    # Claude Code skills: agents/claude/*/SKILL.md
    tracked_claude = get_tracked_files(repo_root, "agents/claude")
    files += sorted(
        f for f in (repo_root / "agents" / "claude").glob("*/SKILL.md")
        if str(f.relative_to(repo_root)) in tracked_claude
    )

    # CoCo skills: agents/coco/*/SKILL.md
    tracked_coco = get_tracked_files(repo_root, "agents/coco")
    files += sorted(
        f for f in (repo_root / "agents" / "coco").glob("*/SKILL.md")
        if str(f.relative_to(repo_root)) in tracked_coco
    )

    # Cursor rules: agents/cursor/rules/*.mdc
    tracked_cursor = get_tracked_files(repo_root, "agents/cursor")
    files += sorted(
        f for f in (repo_root / "agents" / "cursor" / "rules").glob("*.mdc")
        if str(f.relative_to(repo_root)) in tracked_cursor
    )

    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check all skill files across all runtimes have a changelog."
    )
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    skill_files = collect_skill_files(repo_root)

    if not skill_files:
        print("ERROR: no tracked skill files found — is --root pointing to the repo root?")
        return 1

    failed = 0
    current_runtime = None

    for skill_file in skill_files:
        rel = skill_file.relative_to(repo_root)
        # Print a header when runtime changes
        runtime = rel.parts[1]  # agents/<runtime>/...
        if runtime != current_runtime:
            current_runtime = runtime
            print(f"\n  [{runtime}]")

        errors = check_skill(skill_file)
        if errors:
            for err in errors:
                print(f"  FAIL  {rel.name}: {err}")
            failed += 1
        else:
            text = skill_file.read_text(encoding="utf-8")
            changelog_body = text.split("## Changelog", 1)[1]
            rows = [l.strip() for l in changelog_body.splitlines() if ROW_RE.match(l.strip())]
            version = rows[0].split("|")[1].strip() if rows else "?"
            print(f"  PASS  {rel.name}: v{version}")

    print()
    if failed:
        print(f"{failed} skill file(s) missing a valid changelog.")
        print("Add a ## Changelog section with at least one row: | X.Y.Z | YYYY-MM-DD | summary |")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
