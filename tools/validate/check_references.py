#!/usr/bin/env python3
"""
check_references.py — verify all file paths referenced in SKILL.md and .mdc files exist.

Scans every SKILL.md in agents/cli/, agents/claude/, and agents/coco-snowsight/,
and every .mdc in agents/cursor/rules/, for markdown links [text](path) and maps
runtime-specific path prefixes back to repo paths before checking existence.

Path mappings:
  Claude / CLI skills  (~/.claude/...):
    ~/.claude/shared/         → agents/shared/
    ~/.claude/mappings/       → agents/shared/mappings/
    ~/.claude/skills/         → agents/cli/ (or agents/claude/ for Claude-only skills)

  CoCo skills (relative ../../shared/...):
    ../../shared/             → agents/shared/   (from skill dir two levels deep)

  Cursor rules  (~/.cursor/...):
    ~/.cursor/shared/         → agents/shared/
    ~/.cursor/shared/mappings/ → agents/shared/mappings/
    ~/.cursor/rules/          → agents/cursor/rules/

Usage:
    python tools/validate/check_references.py
    python tools/validate/check_references.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

LINK_PATTERN = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

# Links whose targets exist locally but are deliberately untracked / gitignored at
# HEAD — dead links for cloners. Tracked as acknowledged debt so the checker lands
# green; remove in Plan 6 (verification-auditability) once these docs are committed
# or the links are dropped.
KNOWN_UNTRACKED_DEBT: set[str] = set()  # remove in Plan 6 (verification-auditability)

# Maps path prefixes used at runtime to repo-relative paths
CLAUDE_PREFIX_MAP = {
    "~/.claude/shared/": "agents/shared/",
    "~/.claude/mappings/": "agents/shared/mappings/",
    "~/.claude/skills/": "agents/cli/",
}

COCO_PREFIX_MAP = {
    "../../shared/": "agents/shared/",
}

CURSOR_PREFIX_MAP = {
    "~/.cursor/shared/mappings/": "agents/shared/mappings/",
    "~/.cursor/shared/": "agents/shared/",
    "~/.cursor/rules/": "agents/cursor/rules/",
}


def _prefix_map_for(skill_file: Path) -> dict:
    path_str = str(skill_file)
    if "agents/coco" in path_str:
        return COCO_PREFIX_MAP
    if "agents/cursor" in path_str:
        return CURSOR_PREFIX_MAP
    return CLAUDE_PREFIX_MAP


def resolve_path(link_target: str, skill_file: Path, repo_root: Path) -> Path | None:
    """Resolve a markdown link target to a repo-absolute path. Returns None if unresolvable."""
    # Skip HTTP links, anchors, and empty paths
    if link_target.startswith(("http://", "https://", "#", "mailto:")) or not link_target.strip():
        return None

    # Strip fragment from path
    path_part = link_target.split("#")[0]
    if not path_part:
        return None

    # Skip template placeholders — link targets that contain {var} tokens are
    # emitted-output examples (e.g. MIGRATION_REPORT.md rows: [name]({link})),
    # not real repo paths.
    if "{" in path_part or "}" in path_part:
        return None

    prefix_map = _prefix_map_for(skill_file)

    # Apply prefix mappings (longest-prefix-first to avoid partial matches)
    resolved = path_part
    for prefix, replacement in sorted(prefix_map.items(), key=lambda x: -len(x[0])):
        if resolved.startswith(prefix):
            resolved = replacement + resolved[len(prefix):]
            return repo_root / resolved

    # Relative path — resolve from the skill file's directory
    if not resolved.startswith("/"):
        return (skill_file.parent / resolved).resolve()

    # Absolute path starting with / — unusual, skip
    return None


def _git_tracked(repo_root: Path) -> set[str]:
    """Repo-relative paths currently tracked by git."""
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=repo_root,
    )
    return set(result.stdout.splitlines())


def check_skill_file(
    skill_file: Path, repo_root: Path, tracked: set[str] | None = None
) -> list[tuple[int, str, str]]:
    """Return list of (line_num, link_target, resolved_path) for broken references.

    Two failure modes:
      - target does not exist on disk (classic broken link)
      - target exists but is untracked/gitignored while the source file IS tracked —
        a dead link for anyone who clones the repo (audit 4.1)
    """
    broken = []
    src_rel = str(skill_file.relative_to(repo_root)) if skill_file.is_absolute() else str(skill_file)
    src_tracked = tracked is not None and src_rel in tracked
    content = skill_file.read_text(encoding="utf-8")
    for line_num, line in enumerate(content.splitlines(), 1):
        for _text, target in LINK_PATTERN.findall(line):
            resolved = resolve_path(target, skill_file, repo_root)
            if resolved is None:
                continue
            if not resolved.exists():
                rel_resolved = resolved.relative_to(repo_root) if resolved.is_absolute() else resolved
                broken.append((line_num, target, str(rel_resolved)))
                continue
            # Exists on disk — but is it tracked? Only enforce when the source is tracked
            # (untracked source files are WIP and not yet cloners' concern).
            if tracked is not None and src_tracked and resolved.is_absolute():
                try:
                    rel_resolved = str(resolved.relative_to(repo_root))
                except ValueError:
                    continue  # outside repo — not our concern
                if rel_resolved not in tracked and rel_resolved not in KNOWN_UNTRACKED_DEBT:
                    broken.append((line_num, target, rel_resolved + "  [untracked]"))
    return broken


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SKILL.md and .mdc file references.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    skill_files = (
        list(repo_root.glob("agents/cli/*/SKILL.md")) +
        list(repo_root.glob("agents/claude/*/SKILL.md")) +
        list(repo_root.glob("agents/coco-snowsight/*/SKILL.md")) +
        list(repo_root.glob("agents/cursor/rules/*.mdc"))
    )

    if not skill_files:
        print("No SKILL.md or .mdc files found.")
        return 1

    tracked = _git_tracked(repo_root)

    total_broken = 0
    for skill_file in sorted(skill_files):
        rel = skill_file.relative_to(repo_root)
        broken = check_skill_file(skill_file, repo_root, tracked)
        if broken:
            for line_num, target, resolved in broken:
                if resolved.endswith("[untracked]"):
                    clean = resolved.removesuffix("  [untracked]")
                    print(f"FAIL  {rel}:{line_num}  →  {target}  "
                          f"(resolved: {clean})  link target exists locally but is "
                          "untracked/gitignored — dead link for cloners")
                else:
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
