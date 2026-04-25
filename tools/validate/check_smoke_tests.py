#!/usr/bin/env python3
"""
check_smoke_tests.py — verify every Claude skill has a smoke test.

Rule: every directory under agents/claude/ that contains a tracked SKILL.md must
have a corresponding tools/smoke-tests/smoke_<skill_name>.py file (also tracked),
unless the skill is on the allowlist.

The skill name is normalised: hyphens → underscores, plus an optional `ts_object_`
→ `ts_` shortening (e.g. `ts-object-model-builder` → `smoke_ts_model_builder.py`).

Skills on the allowlist (interactive / setup / out-of-scope for live testing)
are skipped:
  - ts-profile-thoughtspot, ts-profile-snowflake — credential setup; no API
    mutations to verify automatically without test credentials
  - ts-object-answer-promote — legacy gap; smoke test should be added in a
    follow-up PR. Remove from the allowlist when the smoke test lands.

Usage:
    python tools/validate/check_smoke_tests.py
    python tools/validate/check_smoke_tests.py --root /path/to/repo
    python tools/validate/check_smoke_tests.py --root . --staged
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


# Skills exempt from the smoke-test requirement.
# Add a comment for each entry explaining why; remove when the exemption no longer applies.
ALLOWLIST = {
    "ts-profile-thoughtspot",   # interactive credential setup — no API mutation flow to test
    "ts-profile-snowflake",     # interactive credential setup
    "ts-object-answer-promote", # legacy gap; backfill in a follow-up PR
}

# Skills whose smoke test uses an abbreviated filename rather than the default convention.
# Add an entry here when the smoke test name is shortened from the skill name.
NAME_ALIASES = {
    "ts-convert-to-snowflake-sv":   "tools/smoke-tests/smoke_ts_to_snowflake.py",
    "ts-convert-from-snowflake-sv": "tools/smoke-tests/smoke_ts_from_snowflake.py",
    "ts-object-model-builder":      "tools/smoke-tests/smoke_ts_model_builder.py",
}


def _get_tracked_paths(repo_root: Path) -> set[str]:
    """Return set of repo-relative paths currently tracked by git."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return set(result.stdout.splitlines())


def _get_staged_names(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=repo_root,
    )
    return result.stdout.splitlines()


def _staged_touches_skills_or_smoke(staged: list[str]) -> bool:
    """Return True if staged files include anything that would change a skill or smoke test."""
    for f in staged:
        if f.startswith("agents/claude/") or f.startswith("tools/smoke-tests/"):
            return True
    return False


def _candidate_smoke_paths(skill_name: str) -> list[str]:
    """
    Return the candidate smoke-test filenames for a skill.

    1. If the skill is in NAME_ALIASES, that exact path is the only candidate
    2. Otherwise the default convention: `tools/smoke-tests/smoke_<skill>.py`
       (with hyphens converted to underscores)
    """
    if skill_name in NAME_ALIASES:
        return [NAME_ALIASES[skill_name]]
    base = skill_name.replace("-", "_")
    return [f"tools/smoke-tests/smoke_{base}.py"]


def check(repo_root: Path, staged_only: bool = False) -> tuple[list[str], list[str]]:
    """Return (failures, info_messages)."""
    failures: list[str] = []
    info: list[str] = []

    if staged_only:
        staged = _get_staged_names(repo_root)
        if not _staged_touches_skills_or_smoke(staged):
            return failures, info  # no relevant changes; skip

    tracked = _get_tracked_paths(repo_root)

    claude_dir = repo_root / "agents" / "claude"
    if not claude_dir.is_dir():
        return failures, info

    for skill_dir in sorted(claude_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_name = skill_dir.name
        skill_md_rel = f"agents/claude/{skill_name}/SKILL.md"
        if skill_md_rel not in tracked:
            continue  # untracked / wip skill; not yet enforced

        if skill_name in ALLOWLIST:
            info.append(f"  SKIP  {skill_name}  (on allowlist)")
            continue

        candidates = _candidate_smoke_paths(skill_name)
        if any(c in tracked for c in candidates):
            matched = next(c for c in candidates if c in tracked)
            info.append(f"  PASS  {skill_name}  →  {matched}")
        else:
            failures.append(
                f"FAIL  {skill_name}  →  no smoke test found.  "
                f"Expected one of: {', '.join(candidates)}"
            )

    return failures, info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repo root (default: cwd)")
    parser.add_argument("--staged", action="store_true",
                        help="Only run if staged changes touch skills or smoke tests")
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    failures, info = check(repo_root, staged_only=args.staged)

    for msg in info:
        print(msg)

    if failures:
        print()
        for f in failures:
            print(f)
        print()
        print(f"{len(failures)} skill(s) missing a smoke test.")
        print()
        print("To fix:")
        print("  1. Create tools/smoke-tests/smoke_<skill_name>.py")
        print("  2. Use tools/smoke-tests/_common.py for shared auth + cleanup helpers")
        print("  3. Mirror an existing smoke test (e.g. smoke_ts_dependency_manager.py)")
        print()
        print("If the skill genuinely cannot be smoke-tested (interactive setup, etc.),")
        print("add it to ALLOWLIST in this file with a justification comment.")
        return 1

    print()
    print("All skills have smoke tests (or are on the allowlist).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
