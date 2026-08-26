#!/usr/bin/env python3
"""
suggest_dependency_types.py — soft pre-commit nudge for the ts-dependency-manager skill.

If a contributor stages changes to:
  - agents/cli/ts-dependency-manager/SKILL.md, OR
  - agents/cli/ts-dependency-manager/references/open-items.md

without also staging:
  - agents/cli/ts-dependency-manager/references/dependency-types.md

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

from _git import git_paths, git_status_paths


SKILL_DIR_REL = "agents/cli/ts-dependency-manager"
TRIGGER_PATHS = (
    f"{SKILL_DIR_REL}/SKILL.md",
    f"{SKILL_DIR_REL}/references/open-items.md",
)
TARGET_PATH = f"{SKILL_DIR_REL}/references/dependency-types.md"


def get_staged_files(repo_root: Path, base: str | None = None) -> list[str]:
    """Changed paths. Default: staged. With `base`, the paths a PR introduces.

    NUL-split via _git — see audit 4.2 (quoted paths were dropped silently).
    """
    if base:
        # Server-side: nothing is staged in CI, so compare the PR against its base.
        return [path for _p, _s, path in git_status_paths(["diff", f"{base}...HEAD"], repo_root)]
    return git_paths(["diff", "--cached", "--name-only", "--diff-filter=ACM"], repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Soft prompt to update dependency-types.md when its companion files change.",
    )
    parser.add_argument("--root", default=".", help="Repo root directory (default: current dir)")
    parser.add_argument("--check", action="store_true",
                        help="Gate mode: exit 1 if a trigger file changed without the "
                             "companion. Works in non-TTY (CI).")
    parser.add_argument("--base", default=None,
                        help="With --check: compare against this ref instead of the "
                             "index, for CI where nothing is staged.")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()

    # Gate mode: the server-side half. Until 2026-08-26 this rule existed only as an
    # interactive prompt with no exit-code capture and no CI counterpart, so it was
    # bypassable three ways — ignore the prompt, --no-verify, or commit without a TTY
    # (audit finding 7.2). Every other co-change rule in the repo has a hard half.
    if args.check:
        changed = get_staged_files(repo_root, base=args.base)
        triggered = [p for p in changed if p in TRIGGER_PATHS]
        if not triggered or TARGET_PATH in changed:
            return 0
        if not (repo_root / TARGET_PATH).exists():
            return 0        # pre-1.0 wip: the companion does not exist yet
        print("  ts-dependency-manager: companion doc not updated.")
        for p in triggered:
            print(f"    changed: {p}")
        print(f"    missing: {TARGET_PATH}")
        print()
        print("  CLAUDE.md's change-impact map requires these to move together: that file")
        print("  holds the status table, hierarchy and sample output for every dependency")
        print("  type. If this change genuinely needs no doc update, say so in the PR and")
        print("  include a trivial touch, or relax the rule in CLAUDE.md deliberately.")
        return 1

    # Non-interactive environments (GUI git clients) — skip the PROMPT silently.
    # The change impact map in CLAUDE.md is the human reviewer's checklist, and
    # --check above is the enforcing half.
    if not sys.stdin.isatty():
        return 0

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
