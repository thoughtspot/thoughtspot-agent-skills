#!/usr/bin/env python3
"""
check_references.py — verify all file paths referenced in SKILL.md, references/*.md,
and docs/**/*.md files exist.

Scans:
  - every SKILL.md in agents/cli/, agents/claude/, and agents/coco-snowsight/
  - every references/*.md under those same three skill runtimes
  - every docs/**/*.md file, excluding docs/audit/, docs/superpowers/, and any
    *backlog-archive* path (historical / generated content, not maintained links)

for markdown links [text](path) and maps runtime-specific path prefixes back to
repo paths before checking existence.

Path mappings (SKILL.md only — see "Per-file-class link resolution" below):
  Claude / CLI skills  (~/.claude/...):
    ~/.claude/shared/         → agents/shared/
    ~/.claude/mappings/       → agents/shared/mappings/
    ~/.claude/skills/         → agents/cli/ (or agents/claude/ for Claude-only skills)

  CoCo skills (relative ../../shared/...):
    ../../shared/             → agents/shared/   (from skill dir two levels deep)

Per-file-class link resolution:
  SKILL.md files keep the exact behaviour above (prefix maps first, else resolve
  relative to the SKILL.md's own directory) — unchanged from before this file's
  scope was extended.

  references/*.md files sit ONE level deeper than SKILL.md (agents/<runtime>/<skill>/
  references/foo.md vs agents/<runtime>/<skill>/SKILL.md), so the SKILL.md prefix
  maps — which are depth-sensitive shorthand written for SKILL.md's specific
  location (e.g. CoCo's "../../shared/" assumes exactly two levels up from the
  skill dir) — would misresolve a relative link from this deeper location. These
  files instead resolve plain relative links against their own directory (which is
  depth-correct by construction via Path.resolve()), while still honouring the
  ~/.claude/... prefixes (CLAUDE_PREFIX_MAP) since those are absolute-style
  shorthand that map straight to a repo path regardless of the caller's depth.

  docs/**/*.md files live outside agents/<runtime>/<skill>/ entirely, so none of
  the skill prefix maps apply. These resolve plain relative links against the
  docs file's own directory, same as references/*.md.

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

from _dirs import runtime_globs

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

def _prefix_map_for(skill_file: Path) -> dict:
    path_str = str(skill_file)
    if "agents/coco" in path_str:
        return COCO_PREFIX_MAP
    return CLAUDE_PREFIX_MAP


def _file_class(source_file: Path, repo_root: Path) -> str:
    """Classify a source .md file so resolve_path() applies the right base path.

    - "skill": agents/<runtime>/<skill>/SKILL.md — the original, depth-sensitive
      prefix-map behaviour applies (unchanged).
    - "reference": any references/*.md file (one level deeper than SKILL.md) —
      resolve relative links from the file's own directory instead.
    - "doc": anything under docs/ — also resolves relative to its own directory;
      none of the skill prefix maps are meaningful outside agents/.
    """
    try:
        rel_parts = source_file.relative_to(repo_root).parts
    except ValueError:
        rel_parts = source_file.parts

    if source_file.name == "SKILL.md":
        return "skill"
    if "references" in rel_parts:
        return "reference"
    if rel_parts and rel_parts[0] == "docs":
        return "doc"
    # Anything else falls back to the original skill-style resolution rather
    # than silently changing behaviour for an unanticipated file class.
    return "skill"


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

    file_class = _file_class(skill_file, repo_root)

    if file_class == "skill":
        prefix_map = _prefix_map_for(skill_file)
    else:
        # references/*.md and docs/**/*.md: only the absolute-style ~/.claude/...
        # shorthand is safe to apply regardless of depth. The CoCo "../../shared/"
        # convention is depth-sensitive and written for SKILL.md's location —
        # applying it here would misresolve a legit relative link from a deeper
        # (references/) or differently-rooted (docs/) file. See module docstring.
        prefix_map = CLAUDE_PREFIX_MAP

    # Apply prefix mappings (longest-prefix-first to avoid partial matches)
    resolved = path_part
    for prefix, replacement in sorted(prefix_map.items(), key=lambda x: -len(x[0])):
        if resolved.startswith(prefix):
            resolved = replacement + resolved[len(prefix):]
            return repo_root / resolved

    # Relative path — resolve from the source file's own directory. This is
    # depth-correct by construction (Path.resolve() walks the actual ../ segments),
    # which is why references/*.md and docs/*.md rely on it rather than a prefix map.
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


# docs/ subtrees excluded from validation entirely:
#   docs/audit/          — dated audit reports; historical snapshots, not maintained links
#   docs/superpowers/     — generated plan/spec scratch docs from the superpowers skill workflow
#   *backlog-archive*    — archived backlog content, not maintained
DOCS_EXCLUDED_PREFIXES = ("docs/audit/", "docs/superpowers/")


def _is_excluded_doc(doc_file: Path, repo_root: Path) -> bool:
    rel = str(doc_file.relative_to(repo_root))
    if rel.startswith(DOCS_EXCLUDED_PREFIXES):
        return True
    if "backlog-archive" in doc_file.name:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check SKILL.md / references/*.md / docs/**/*.md file references."
    )
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    skill_files = runtime_globs(repo_root, "*/SKILL.md")
    reference_files = runtime_globs(repo_root, "*/references/*.md")
    doc_files = [
        p for p in repo_root.glob("docs/**/*.md")
        if not _is_excluded_doc(p, repo_root)
    ]

    all_files = skill_files + reference_files + doc_files

    if not all_files:
        print("No SKILL.md / references / docs files found.")
        return 1

    tracked = _git_tracked(repo_root)

    total_broken = 0
    for skill_file in sorted(all_files):
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
