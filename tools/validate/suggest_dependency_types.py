#!/usr/bin/env python3
"""
suggest_dependency_types.py — soft pre-commit nudge for the ts-dependency-manager skill.

If a contributor stages changes to:
  - agents/claude/ts-dependency-manager/SKILL.md, OR
  - agents/claude/ts-dependency-manager/references/open-items.md

without also staging:
  - agents/claude/ts-dependency-manager/references/dependency-types.md

we prompt them to confirm whether dependency-types.md needs an update too. The status
table, hierarchy diagram, and sample output in dependency-types.md are the canonical
summary of "what the skill checks and how" — when SKILL.md's Step 4 walking changes,
or when an open-items.md entry moves between status values (Partial → Implementable),
the dependency-types.md content typically also changes.

This is a SOFT NUDGE only:
  - exits 0 always (never blocks the commit)
  - silent in non-TTY environments (CI, GUI git clients)
  - silent when dependency-types.md is also staged

The reviewer's authoritative checklist is the change impact map in CLAUDE.md.

Usage:
    python tools/validate/suggest_dependency_types.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SKILL_DIR_REL = "agents/claude/ts-dependency-manager"
TRIGGER_PATHS = (
    f"{SKILL_DIR_REL}/SKILL.md",
    f"{SKILL_DIR_REL}/references/open-items.md",
)
TARGET_PATH = f"{SKILL_DIR_REL}/references/dependency-types.md"


def get_staged_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return result.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Soft prompt to update dependency-types.md when its companion files change.",
    )
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    args = parser.parse_args()

    # Non-interactive environments (CI, GUI git clients) — skip silently.
    # The change impact map in CLAUDE.md is the human reviewer's checklist.
    if not sys.stdin.isatty():
        return 0

    repo_root = Path(args.root).resolve()
    staged = get_staged_files(repo_root)

    triggered_by = [p for p in staged if p in TRIGGER_PATHS]
    target_already_staged = TARGET_PATH in staged

    # Nothing relevant staged, or target is also staged — exit silently
    if not triggered_by or target_already_staged:
        return 0

    target_path_abs = repo_root / TARGET_PATH

    # If dependency-types.md doesn't exist yet (skill is in pre-1.0 wip and the file
    # hasn't been added), don't pester the contributor — silent exit.
    if not target_path_abs.exists():
        return 0

    print()
    print("  ts-dependency-manager — dependency-types.md reminder")
    print("  ────────────────────────────────────────────────────")
    print("  You staged changes to:")
    for p in triggered_by:
        print(f"    • {p}")
    print()
    print(f"  references/dependency-types.md is NOT staged.")
    print()
    print("  That file holds the status table, hierarchy diagram, and sample output for")
    print("  every dependency type the skill considers. If your change moves a dep type")
    print("  between status values (Partial → Implementable, etc.), changes the Step 4")
    print("  walking order, or alters what the impact report shows, dependency-types.md")
    print("  needs to be updated too.")
    print()
    print(f"  File path: {TARGET_PATH}")
    print()
    print("  [C]ontinue commit (no doc update needed)")
    print("  [S]top so I can update dependency-types.md first")
    print()
    print("  Choice [C/S]: ", end="", flush=True)

    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 0  # treat as continue — don't block

    if choice == "s":
        print()
        print("  Commit not aborted by this script (we never block).")
        print(f"  Edit {TARGET_PATH}, re-stage it, then re-run the commit.")
        print()
        # Still exit 0 — the contributor can always `git commit --no-verify` anyway,
        # and the pre-commit hook explicitly treats this script as a soft nudge.
        return 0

    # default / "c" / anything else → silent continue
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
