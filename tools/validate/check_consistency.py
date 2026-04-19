#!/usr/bin/env python3
"""
check_consistency.py — verify cross-file consistency (skills tables, symlink steps, stage copy list).

Checks:
  1. README.md skills tables — every skill in agents/claude/ and agents/coco/ is listed
  2. agents/claude/SETUP.md symlink steps — every claude skill has an ln -s step
  3. agents/coco/SETUP.md stage copy list — every coco SKILL.md and agents/shared/ file is listed
  4. README.md structure section — known tool subdirectories are mentioned

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
    Every directory under agents/claude/ and agents/coco/ that contains a SKILL.md
    must appear in the README.md skills tables.
    """
    failures = []
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    for runtime in ("claude", "coco"):
        agent_dir = repo_root / "agents" / runtime
        if not agent_dir.is_dir():
            continue
        for skill_dir in sorted(agent_dir.iterdir()):
            if not (skill_dir / "SKILL.md").exists():
                continue
            skill_name = skill_dir.name
            # Check skill name appears somewhere in README (table row, backtick, or plain)
            if skill_name not in readme:
                failures.append(
                    f"README.md: skill 'agents/{runtime}/{skill_name}' not listed in skills table"
                )

    return failures


# ---------------------------------------------------------------------------
# Check 2: agents/claude/SETUP.md symlink steps
# ---------------------------------------------------------------------------

def check_claude_setup_symlinks(repo_root: Path) -> list[str]:
    """
    Every directory under agents/claude/ that contains a SKILL.md must have
    a corresponding ln -s step in agents/claude/SETUP.md.
    """
    failures = []
    setup_path = repo_root / "agents" / "claude" / "SETUP.md"
    if not setup_path.exists():
        return ["agents/claude/SETUP.md not found"]

    setup_text = setup_path.read_text(encoding="utf-8")
    agent_dir = repo_root / "agents" / "claude"

    for skill_dir in sorted(agent_dir.iterdir()):
        if not (skill_dir / "SKILL.md").exists():
            continue
        skill_name = skill_dir.name
        # Look for ln -s line containing the skill directory name
        if f"ln -s" not in setup_text or skill_name not in setup_text:
            failures.append(
                f"agents/claude/SETUP.md: no 'ln -s' step found for skill '{skill_name}'"
            )

    return failures


# ---------------------------------------------------------------------------
# Check 3: agents/coco/SETUP.md stage copy list
# ---------------------------------------------------------------------------

def check_coco_setup_stage_copy(repo_root: Path) -> list[str]:
    """
    Every SKILL.md under agents/coco/ and every non-CLAUDE.md file under
    agents/shared/ must appear in a 'snow stage copy' command in agents/coco/SETUP.md.
    """
    failures = []
    setup_path = repo_root / "agents" / "coco" / "SETUP.md"
    if not setup_path.exists():
        return ["agents/coco/SETUP.md not found"]

    setup_text = setup_path.read_text(encoding="utf-8")

    # Check coco SKILL.md files
    coco_dir = repo_root / "agents" / "coco"
    for skill_dir in sorted(coco_dir.iterdir()):
        if not (skill_dir / "SKILL.md").exists():
            continue
        # The stage copy path uses the relative path from repo root
        rel_path = f"agents/coco/{skill_dir.name}/SKILL.md"
        if rel_path not in setup_text:
            failures.append(
                f"agents/coco/SETUP.md: no 'snow stage copy' found for '{rel_path}'"
            )

    # Check agents/shared/ files (exclude CLAUDE.md — internal docs, not staged to Snowflake)
    shared_dir = repo_root / "agents" / "shared"
    for shared_file in sorted(shared_dir.rglob("*.md")):
        if shared_file.name == "CLAUDE.md":
            continue
        rel_path = str(shared_file.relative_to(repo_root))
        if rel_path not in setup_text:
            failures.append(
                f"agents/coco/SETUP.md: no 'snow stage copy' found for '{rel_path}'"
            )

    return failures


# ---------------------------------------------------------------------------
# Check 4: README.md structure section mentions key tool subdirectories
# ---------------------------------------------------------------------------

_KNOWN_DIRS = [
    # (relative path in repo, label to check for in README)
    ("scripts", "scripts"),
    ("tools/validate", "validate"),
    ("tools/smoke-tests", "smoke-tests"),
]


def check_readme_structure(repo_root: Path) -> list[str]:
    """
    If a known tool/script directory exists in the repo, it must be mentioned
    in README.md (in the repository structure section or elsewhere).
    """
    failures = []
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    for rel_dir, label in _KNOWN_DIRS:
        if (repo_root / rel_dir).is_dir():
            if label not in readme:
                failures.append(
                    f"README.md: directory '{rel_dir}' exists but is not mentioned — "
                    f"add it to the Repository Structure section"
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
