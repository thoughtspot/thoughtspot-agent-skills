#!/usr/bin/env python3
"""
check_skill_naming.py — validate skill directory names against the family
patterns documented in .claude/rules/skill-naming.md.

Walks agents/claude/<skill>/ and agents/coco/<skill>/ for any directory that
contains a SKILL.md, then checks the directory name matches one of the
documented family regexes (or is on the explicit ALLOWLIST).

Exit codes:
  0 — every skill matches a family or is allowlisted
  1 — at least one skill name violates the rule

Run manually:
    python3 tools/validate/check_skill_naming.py --root .

The pre-commit hook invokes this when `agents/{claude,coco}/**/SKILL.md` is
staged.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Each family: (regex, one-line description used in error output)
# Patterns must match the FULL directory name (use \A and \Z anchors implicitly
# via re.fullmatch).
FAMILY_PATTERNS: dict[str, tuple[re.Pattern, str]] = {
    "ts-object-*": (
        re.compile(r"ts-object-[a-z][a-z0-9]*-[a-z][a-z0-9]*(-[a-z][a-z0-9]*)*"),
        "single-object operation: ts-object-{type}-{verb}",
    ),
    "ts-profile-*": (
        re.compile(r"ts-profile-[a-z][a-z0-9]*"),
        "credential setup: ts-profile-{platform}",
    ),
    "ts-convert-*": (
        re.compile(r"ts-convert-(to|from)-[a-z][a-z0-9]*(-[a-z0-9]+)*"),
        "cross-platform conversion: ts-convert-{to|from}-{format}",
    ),
    "ts-dependency-*": (
        re.compile(r"ts-dependency-[a-z][a-z0-9]*"),
        "dependency-graph operation: ts-dependency-{verb}",
    ),
    "ts-variable-*": (
        re.compile(r"ts-variable-[a-z][a-z0-9]*"),
        "variable management: ts-variable-{specifier}",
    ),
    "ts-setup-*": (
        re.compile(r"ts-setup-[a-z][a-z0-9]*"),
        "toolset / proc installation: ts-setup-{specifier}",
    ),
}

# Skills that legitimately don't match any family. Each entry must include a
# justification comment. Mass-allowlisting is a smell — push back at PR review
# rather than adding entries here.
ALLOWLIST: set[str] = set()


def find_skills(root: Path) -> list[Path]:
    """Return every skill directory (one with a SKILL.md inside) under
    agents/claude/ and agents/coco/."""
    found: list[Path] = []
    for runtime in ("agents/claude", "agents/coco"):
        runtime_dir = root / runtime
        if not runtime_dir.is_dir():
            continue
        for child in sorted(runtime_dir.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                found.append(child)
    return found


def matched_family(name: str) -> str | None:
    """Return the family key (e.g. 'ts-object-*') if `name` matches one
    of the family regexes, else None."""
    for family, (pattern, _) in FAMILY_PATTERNS.items():
        if pattern.fullmatch(name):
            return family
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every skill + family match, even passing ones")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    skills = find_skills(root)
    if not skills:
        print(f"No skills found under {root}/agents/{{claude,coco}}/. Nothing to check.")
        return 0

    failures: list[tuple[str, Path]] = []
    for skill_dir in skills:
        name = skill_dir.name
        runtime = skill_dir.parent.name  # 'claude' or 'coco'
        if name in ALLOWLIST:
            if args.verbose:
                print(f"  OK   ({runtime}) {name} — allowlisted")
            continue
        family = matched_family(name)
        if family:
            if args.verbose:
                print(f"  OK   ({runtime}) {name} — matches {family}")
        else:
            failures.append((name, skill_dir))

    if failures:
        print(f"\n{len(failures)} skill(s) violate the naming convention:\n")
        for name, path in failures:
            print(f"  ✗ {path.relative_to(root)}")
            print(f"      Name {name!r} doesn't match any documented family.")
        print()
        print("Documented families (see .claude/rules/skill-naming.md):")
        for family, (_, desc) in FAMILY_PATTERNS.items():
            print(f"  {family:<22} {desc}")
        print()
        print("To fix:")
        print("  - Rename the skill to match an existing family, OR")
        print("  - Add a new family to .claude/rules/skill-naming.md AND this validator")
        print("    (FAMILY_PATTERNS dict), then explain in the PR why an existing")
        print("    family doesn't fit, OR")
        print("  - As a last resort, add the name to ALLOWLIST in this file with a")
        print("    justification comment (mass-allowlisting is a smell).")
        return 1

    print(f"All {len(skills)} skill name(s) match a documented family.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
