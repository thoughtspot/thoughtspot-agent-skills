#!/usr/bin/env python3
"""
check_references.py — verify all file paths referenced in SKILL.md files exist in the repo.

Scans every SKILL.md in agents/claude/ and agents/coco/ for markdown links [text](path)
and maps runtime-specific path prefixes back to repo paths before checking existence.

Path mappings:
  Claude skills  (~/.claude/...):
    ~/.claude/shared/         → agents/shared/
    ~/.claude/mappings/       → agents/shared/mappings/
    ~/.claude/skills/         → agents/claude/

  CoCo skills (relative ../../shared/...):
    ../../shared/             → agents/shared/   (from skill dir two levels deep)

Usage:
    python tools/validate/check_references.py
    python tools/validate/check_references.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

# Maps path prefixes used at runtime to repo-relative paths
CLAUDE_PREFIX_MAP = {
    "~/.claude/shared/": "agents/shared/",
    "~/.claude/mappings/": "agents/shared/mappings/",
    "~/.claude/skills/": "agents/claude/",
}

COCO_PREFIX_MAP = {
    "../../shared/": "agents/shared/",
}


def resolve_path(link_target: str, skill_file: Path, repo_root: Path) -> Path | None:
    """Resolve a markdown link target to a repo-absolute path. Returns None if unresolvable."""
    # Skip HTTP links, anchors, and empty paths
    if link_target.startswith(("http://", "https://", "#", "mailto:")) or not link_target.strip():
        return None

    # Strip fragment from path
    path_part = link_target.split("#")[0]
    if not path_part:
        return None

    runtime = "coco" if "agents/coco" in str(skill_file) else "claude"
    prefix_map = COCO_PREFIX_MAP if runtime == "coco" else CLAUDE_PREFIX_MAP

    # Apply prefix mappings
    resolved = path_part
    for prefix, replacement in prefix_map.items():
        if resolved.startswith(prefix):
            resolved = replacement + resolved[len(prefix):]
            return repo_root / resolved

    # Relative path — resolve from the skill file's directory
    if not resolved.startswith("/"):
        return (skill_file.parent / resolved).resolve()

    # Absolute path starting with / — unusual, skip
    return None


def check_skill_file(skill_file: Path, repo_root: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_num, link_target, resolved_path) for broken references."""
    broken = []
    content = skill_file.read_text(encoding="utf-8")
    for line_num, line in enumerate(content.splitlines(), 1):
        for _text, target in LINK_PATTERN.findall(line):
            resolved = resolve_path(target, skill_file, repo_root)
            if resolved is None:
                continue
            if not resolved.exists():
                rel_resolved = resolved.relative_to(repo_root) if resolved.is_absolute() else resolved
                broken.append((line_num, target, str(rel_resolved)))
    return broken


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SKILL.md file references.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    skill_files = list(repo_root.glob("agents/claude/*/SKILL.md")) + \
                  list(repo_root.glob("agents/coco/*/SKILL.md"))

    if not skill_files:
        print("No SKILL.md files found.")
        return 1

    total_broken = 0
    for skill_file in sorted(skill_files):
        rel = skill_file.relative_to(repo_root)
        broken = check_skill_file(skill_file, repo_root)
        if broken:
            for line_num, target, resolved in broken:
                print(f"FAIL  {rel}:{line_num}  →  {target}  (resolved: {resolved})")
                total_broken += 1
        else:
            print(f"PASS  {rel}")

    print()
    if total_broken:
        print(f"{total_broken} broken reference(s) found.")
        return 1
    else:
        print("All references resolved.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
