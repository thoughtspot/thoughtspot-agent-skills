#!/usr/bin/env python3
"""
check_runtime_coverage.py — validate cross-runtime skill coverage.

Cursor must mirror Claude. CoCo's divergences from Claude/Cursor must be
documented in EXPECTED_DIVERGENCES below.

For every skill present in agents/claude/, this validator confirms a Cursor
.mdc exists at agents/cursor/rules/<skill>.mdc. For every CoCo skill or
omission, EXPECTED_DIVERGENCES must explicitly list the (skill, runtime)
pair with a justification comment.

Exit codes:
  0 — coverage matches the rule
  1 — at least one missing mirror or undocumented divergence

Run manually:
    python3 tools/validate/check_runtime_coverage.py --root .

Pre-commit invokes this when any agents/{claude,coco}/<skill>/SKILL.md or
agents/cursor/rules/*.mdc is staged.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Documented intentional divergences from "Cursor mirrors Claude;
# CoCo follows the same set". Each entry must have a one-line justification
# comment so PR reviewers can sanity-check.
#
# Format: {(skill_name, runtime): "one-line reason"}
# Runtime is "cursor" or "coco". A skill that exists in claude but legitimately
# doesn't have a coco mirror gets ("<skill>", "coco") here.
# A skill that exists in coco but legitimately doesn't have a claude mirror
# gets ("<skill>", "claude") here.
EXPECTED_DIVERGENCES: dict[tuple[str, str], str] = {
    # --- CoCo divergences (skill exists in claude, not in coco) ---
    ("ts-dependency-manager", "coco"):
        "Graph walk + alias propagation too heavy for Snowsight stored-proc runtime",
    ("ts-object-answer-promote", "coco"):
        "Complex search-query / formula manipulation not supported in stored-proc model",
    ("ts-object-model-coach", "coco"):
        "Interactive coaching workflow doesn't fit Snowsight stored-proc execution model",
    ("ts-profile-snowflake", "coco"):
        "CoCo runs inside Snowflake — no Snowflake profile needed",

    # --- CoCo-only skills (skill exists in coco, not in claude/cursor) ---
    ("ts-setup-sv", "claude"):
        "CoCo-only: installs the stored procedures CoCo itself uses; no Claude equivalent needed",
    ("ts-setup-sv", "cursor"):
        "CoCo-only: installs the stored procedures CoCo itself uses; no Cursor equivalent needed",
}


def find_skills(root: Path) -> dict[str, set[str]]:
    """Return {skill_name: {runtime, ...}} for every skill seen across all
    three runtimes."""
    coverage: dict[str, set[str]] = {}

    for runtime in ("claude", "coco"):
        runtime_dir = root / "agents" / runtime
        if runtime_dir.is_dir():
            for child in runtime_dir.iterdir():
                if child.is_dir() and (child / "SKILL.md").is_file():
                    coverage.setdefault(child.name, set()).add(runtime)

    cursor_rules = root / "agents" / "cursor" / "rules"
    if cursor_rules.is_dir():
        for child in cursor_rules.glob("*.mdc"):
            coverage.setdefault(child.stem, set()).add("cursor")

    return coverage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every skill's per-runtime status")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    coverage = find_skills(root)

    if not coverage:
        print(f"No skills found under {root}/agents/. Nothing to check.")
        return 0

    failures: list[str] = []

    for skill_name in sorted(coverage):
        runtimes = coverage[skill_name]
        per_runtime_status: dict[str, str] = {}

        for runtime in ("claude", "cursor", "coco"):
            if runtime in runtimes:
                per_runtime_status[runtime] = "present"
            elif (skill_name, runtime) in EXPECTED_DIVERGENCES:
                per_runtime_status[runtime] = "expected-divergence"
            else:
                per_runtime_status[runtime] = "missing"

        # Cursor mirrors Claude — if claude has it, cursor must have it OR
        # it's an expected divergence.
        if per_runtime_status["claude"] == "present" and per_runtime_status["cursor"] == "missing":
            failures.append(
                f"  ✗ {skill_name}: present in claude but missing in cursor "
                f"(no EXPECTED_DIVERGENCES entry for ('{skill_name}', 'cursor'))"
            )

        # CoCo divergences must be documented either way:
        #   - skill in claude, not in coco → must be in EXPECTED_DIVERGENCES
        #   - skill in coco, not in claude → must be in EXPECTED_DIVERGENCES
        if per_runtime_status["claude"] == "present" and per_runtime_status["coco"] == "missing":
            failures.append(
                f"  ✗ {skill_name}: present in claude but missing in coco "
                f"(no EXPECTED_DIVERGENCES entry for ('{skill_name}', 'coco'))"
            )
        if per_runtime_status["coco"] == "present" and per_runtime_status["claude"] == "missing":
            failures.append(
                f"  ✗ {skill_name}: present in coco but missing in claude "
                f"(no EXPECTED_DIVERGENCES entry for ('{skill_name}', 'claude'))"
            )
        # Cursor-only skills are also a violation (cursor mirrors claude;
        # nothing should be cursor-only)
        if per_runtime_status["cursor"] == "present" and per_runtime_status["claude"] == "missing":
            failures.append(
                f"  ✗ {skill_name}: present in cursor but missing in claude "
                f"(Cursor mirrors Claude; cursor-only skills are not allowed)"
            )

        if args.verbose:
            cells = []
            for runtime in ("claude", "cursor", "coco"):
                status = per_runtime_status[runtime]
                if status == "present":
                    cells.append(f"{runtime}=✓")
                elif status == "expected-divergence":
                    cells.append(f"{runtime}=expected-skip")
                else:
                    cells.append(f"{runtime}=MISSING")
            print(f"  {skill_name:<40}  {'  '.join(cells)}")

    if failures:
        print(f"\n{len(failures)} runtime-coverage violation(s):\n")
        for f in failures:
            print(f)
        print()
        print("To fix any of these:")
        print("  1. Author the missing skill file in the relevant runtime")
        print("     (agents/claude/<skill>/SKILL.md, agents/cursor/rules/<skill>.mdc,")
        print("     or agents/coco/<skill>/SKILL.md), OR")
        print("  2. Document the divergence in EXPECTED_DIVERGENCES at the top of")
        print("     tools/validate/check_runtime_coverage.py with a one-line reason.")
        print("  3. See .claude/rules/runtime-coverage.md for the full convention.")
        return 1

    print(f"All {len(coverage)} skill(s) match the runtime-coverage rule.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
