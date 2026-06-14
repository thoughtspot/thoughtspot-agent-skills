#!/usr/bin/env python3
"""
check_consistency.py — verify cross-file consistency (skills tables, symlink steps, stage copy list).

Checks:
  1. README.md skills tables — every skill in agents/cli/, agents/claude/, and agents/coco-snowsight/ is listed
  2. SETUP.md symlink steps — every agents/cli/ and agents/claude/ skill has an ln -s step in its runtime's SETUP.md
  3. agents/coco-snowsight/SETUP.md stage copy list — every coco SKILL.md and agents/shared/ file is listed
  4. README.md structure section — scripts/ and every subdirectory of tools/ is mentioned
  5. agents/shared/CLAUDE.md coverage — every tracked file in agents/shared/ is listed there

Usage:
    python tools/validate/check_consistency.py
    python tools/validate/check_consistency.py --root /path/to/repo
    python tools/validate/check_consistency.py --root . --staged
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _get_staged_names(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return result.stdout.splitlines()


def _get_tracked_paths(repo_root: Path) -> set[str]:
    """Return set of repo-relative paths currently tracked by git (not gitignored)."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return set(result.stdout.splitlines())


def _staged_touches_agents_or_setup(staged: list[str]) -> bool:
    """Return True if staged files include anything that would affect cross-file consistency."""
    for f in staged:
        if (
            f.startswith("agents/")
            or f == "README.md"
            or f.endswith("SETUP.md")
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Check 1: README.md skills tables
# ---------------------------------------------------------------------------

def check_readme_skills(repo_root: Path) -> list[str]:
    """
    Every directory under agents/claude/ and agents/coco-snowsight/ that contains a tracked SKILL.md
    must appear in the README.md skills tables.
    Gitignored/untracked skill directories are skipped.
    """
    failures = []
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    tracked = _get_tracked_paths(repo_root)

    for runtime in ("claude", "cli", "coco-snowsight"):
        agent_dir = repo_root / "agents" / runtime
        if not agent_dir.is_dir():
            continue
        for skill_dir in sorted(agent_dir.iterdir()):
            skill_md_rel = f"agents/{runtime}/{skill_dir.name}/SKILL.md"
            if skill_md_rel not in tracked:
                continue
            skill_name = skill_dir.name
            # Check skill name appears somewhere in README (table row, backtick, or plain)
            if skill_name not in readme:
                failures.append(
                    f"README.md: skill 'agents/{runtime}/{skill_name}' not listed in skills table"
                )

    return failures


# ---------------------------------------------------------------------------
# Check 2: SETUP.md symlink steps (agents/cli/ + agents/claude/)
# ---------------------------------------------------------------------------

def check_claude_setup_symlinks(repo_root: Path) -> list[str]:
    """
    Every directory under agents/cli/ or agents/claude/ that contains a tracked
    SKILL.md must have a corresponding ln -s step in that runtime's SETUP.md
    (agents/cli/SETUP.md or agents/claude/SETUP.md respectively).
    Gitignored/untracked skill directories are skipped.
    """
    failures = []
    tracked = _get_tracked_paths(repo_root)

    for runtime in ("cli", "claude"):
        agent_dir = repo_root / "agents" / runtime
        if not agent_dir.is_dir():
            continue
        setup_path = agent_dir / "SETUP.md"
        if not setup_path.exists():
            failures.append(f"agents/{runtime}/SETUP.md not found")
            continue
        setup_text = setup_path.read_text(encoding="utf-8")

        for skill_dir in sorted(agent_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md_rel = f"agents/{runtime}/{skill_dir.name}/SKILL.md"
            if skill_md_rel not in tracked:
                continue
            skill_name = skill_dir.name
            # Look for ln -s line containing the skill directory name
            if "ln -s" not in setup_text or skill_name not in setup_text:
                failures.append(
                    f"agents/{runtime}/SETUP.md: no 'ln -s' step found for skill '{skill_name}'"
                )

    return failures


# ---------------------------------------------------------------------------
# Check 3: agents/coco-snowsight/SETUP.md stage copy list
# ---------------------------------------------------------------------------

def check_coco_setup_stage_copy(repo_root: Path) -> list[str]:
    """
    Every SKILL.md under agents/coco-snowsight/ and every non-CLAUDE.md file under
    agents/shared/ must appear in a 'snow stage copy' command in agents/coco-snowsight/SETUP.md.
    """
    failures = []
    setup_path = repo_root / "agents" / "coco-snowsight" / "SETUP.md"
    if not setup_path.exists():
        return ["agents/coco-snowsight/SETUP.md not found"]

    setup_text = setup_path.read_text(encoding="utf-8")

    # Check coco-snowsight SKILL.md files
    coco_dir = repo_root / "agents" / "coco-snowsight"
    for skill_dir in sorted(coco_dir.iterdir()):
        if not (skill_dir / "SKILL.md").exists():
            continue
        # The stage copy path uses the relative path from repo root
        rel_path = f"agents/coco-snowsight/{skill_dir.name}/SKILL.md"
        if rel_path not in setup_text:
            failures.append(
                f"agents/coco-snowsight/SETUP.md: no 'snow stage copy' found for '{rel_path}'"
            )

    # Check agents/shared/ files (exclude CLAUDE.md — internal docs, not staged to Snowflake)
    # Only check tracked files — gitignored content (e.g. Databricks files) is not deployed.
    tracked = _get_tracked_paths(repo_root)
    shared_dir = repo_root / "agents" / "shared"
    for shared_file in sorted(shared_dir.rglob("*.md")):
        if shared_file.name == "CLAUDE.md":
            continue
        rel_path = str(shared_file.relative_to(repo_root))
        if rel_path not in tracked:
            continue
        if rel_path not in setup_text:
            failures.append(
                f"agents/coco-snowsight/SETUP.md: no 'snow stage copy' found for '{rel_path}'"
            )

    return failures


# ---------------------------------------------------------------------------
# Check 4: README.md structure section mentions key tool subdirectories
# ---------------------------------------------------------------------------


def check_readme_structure(repo_root: Path) -> list[str]:
    """
    Every subdirectory under tools/ must be mentioned in README.md.
    If scripts/ exists at repo root, it must also be mentioned.
    Dynamic scan — no hardcoded list, so new tool directories are caught automatically.
    """
    failures = []
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    # scripts/ at repo root
    if (repo_root / "scripts").is_dir() and "scripts" not in readme:
        failures.append(
            "README.md: scripts/ directory exists but is not mentioned — "
            "add it to the Repository Structure section"
        )

    # Every subdirectory of tools/ — dynamic, no hardcoded list
    tools_dir = repo_root / "tools"
    if tools_dir.is_dir():
        for subdir in sorted(tools_dir.iterdir()):
            if not subdir.is_dir():
                continue
            if subdir.name.startswith(".") or subdir.name.startswith("__"):
                continue
            if subdir.name not in readme:
                failures.append(
                    f"README.md: tools/{subdir.name}/ exists but is not mentioned — "
                    f"add it to the Repository Structure section"
                )

    return failures


# ---------------------------------------------------------------------------
# Check 7: agents/shared/CLAUDE.md lists every tracked file in agents/shared/
# ---------------------------------------------------------------------------

def check_shared_claude_md(repo_root: Path) -> list[str]:
    """
    Every tracked file in agents/shared/ (excluding CLAUDE.md itself) must be
    mentioned by filename in agents/shared/CLAUDE.md's directory map.
    Catches schema or mapping files added without updating the directory listing.
    """
    claude_md_path = repo_root / "agents" / "shared" / "CLAUDE.md"
    if not claude_md_path.exists():
        return []  # No shared CLAUDE.md — skip (e.g. template projects)

    claude_text = claude_md_path.read_text(encoding="utf-8")
    tracked = _get_tracked_paths(repo_root)
    failures = []

    shared_dir = repo_root / "agents" / "shared"
    for f in sorted(shared_dir.rglob("*.md")):
        if f.name == "CLAUDE.md":
            continue
        rel_path = str(f.relative_to(repo_root))
        if rel_path not in tracked:
            continue
        if f.name not in claude_text:
            failures.append(
                f"agents/shared/CLAUDE.md: '{rel_path}' not in directory map — "
                f"add an entry for '{f.name}'"
            )

    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Verify cross-file consistency.")
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    parser.add_argument(
        "--staged", action="store_true",
        help="Skip the check entirely if no relevant files are staged",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    if args.staged:
        staged = _get_staged_names(repo_root)
        if not _staged_touches_agents_or_setup(staged):
            # No agents/ or SETUP.md files staged — consistency cannot have changed
            print("No agents/ or SETUP.md files staged — skipping consistency check.")
            return 0

    total_failures = 0

    checks = [
        ("README skills tables",         check_readme_skills),
        ("SETUP.md symlink steps",        check_claude_setup_symlinks),
        ("stage copy list",               check_coco_setup_stage_copy),
        ("README structure section",      check_readme_structure),
        ("shared/CLAUDE.md coverage",     check_shared_claude_md),
    ]

    for label, fn in checks:
        failures = fn(repo_root)
        if failures:
            for msg in failures:
                print(f"FAIL  {msg}")
            total_failures += len(failures)

    print()
    if total_failures:
        print(f"{total_failures} consistency issue(s) found.")
        return 1

    print("All consistency checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
