#!/usr/bin/env python3
"""
check_runtime_coverage.py — validate cross-runtime skill coverage.

CoCo Snowsight divergences from Claude/CLI must be documented in
EXPECTED_DIVERGENCES below.

For every skill present in agents/cli/ (the canonical CLI skill location;
agents/claude/ is the Claude-only annex), this validator confirms:
  - A CoCo Snowsight skill exists at agents/coco-snowsight/<skill>/SKILL.md (or is documented)

Exit codes:
  0 — coverage matches the rule
  1 — at least one missing mirror or undocumented divergence

Run manually:
    python3 tools/validate/check_runtime_coverage.py --root .

Pre-commit invokes this when any agents/{claude,cli,coco-snowsight}/<skill>/SKILL.md
is staged.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Documented intentional divergences from the coverage rule.
# Each entry must have a one-line justification comment so PR reviewers can sanity-check.
#
# Format: {(skill_name, runtime): "one-line reason"}
# Runtime is "cli" or "coco-snowsight".
# A skill that exists in claude but legitimately doesn't have a mirror gets
# ("<skill>", "<runtime>") here.
EXPECTED_DIVERGENCES: dict[tuple[str, str], str] = {
    # --- CoCo Snowsight divergences (skill exists in claude, not in coco-snowsight) ---
    ("ts-object-model-spotql-query", "coco-snowsight"):
        "SpotQL query loop + ts CLI execution not available in Snowsight stored-proc runtime",
    ("ts-variable-timezone", "coco-snowsight"):
        "REST v2 template/variables endpoint not available in Snowsight stored-proc runtime",
    ("ts-audit", "coco-snowsight"):
        "Cluster-wide TML scan + analysis too heavy for Snowsight stored-proc runtime",
    ("ts-dependency-manager", "coco-snowsight"):
        "Graph walk + alias propagation too heavy for Snowsight stored-proc runtime",
    ("ts-object-answer-promote", "coco-snowsight"):
        "Complex search-query / formula manipulation not supported in stored-proc model",
    ("ts-object-model-coach", "coco-snowsight"):
        "Interactive coaching workflow doesn't fit Snowsight stored-proc execution model",
    ("ts-profile-snowflake", "coco-snowsight"):
        "CoCo Snowsight runs inside Snowflake — no Snowflake profile needed",
    ("ts-profile-databricks", "coco-snowsight"):
        "CoCo Snowsight runs inside Snowflake — no Databricks profile needed",
    ("ts-convert-from-databricks-mv", "coco-snowsight"):
        "Databricks MV skills use Databricks CLI — not available in Snowsight runtime",
    ("ts-convert-to-databricks-mv", "coco-snowsight"):
        "Databricks MV skills use Databricks CLI — not available in Snowsight runtime",

    # --- CLI divergences (skill exists in claude, not in cli) ---
    ("ts-profile-snowflake", "cli"):
        "Cortex Code manages Snowflake connections natively; Claude-only skill",

    # --- CoCo-only skills (skill exists in coco-snowsight, not in claude/cli) ---
    ("ts-setup-sv", "claude"):
        "Snowsight-only: installs the stored procedures Snowsight runtime uses",
    ("ts-setup-sv", "cli"):
        "Snowsight-only: CLI uses ts CLI directly, no stored procedures needed",

    # --- Tableau migration (CLI skill; no CoCo equivalent — TWB parsing needs shell + LLM) ---
    ("ts-convert-from-tableau", "coco-snowsight"):
        "TWB XML parsing and TML generation require shell access and LLM reasoning; not supported in stored-proc runtime",
    ("ts-profile-tableau", "coco-snowsight"):
        "Tableau Server not accessible from Snowsight stored-proc runtime",
}


def find_skills(root: Path) -> dict[str, set[str]]:
    """Return {skill_name: {runtime, ...}} for every skill seen across all
    runtimes."""
    coverage: dict[str, set[str]] = {}

    for runtime in ("claude", "cli", "coco-snowsight"):
        runtime_dir = root / "agents" / runtime
        if runtime_dir.is_dir():
            for child in runtime_dir.iterdir():
                if child.is_dir() and (child / "SKILL.md").is_file():
                    coverage.setdefault(child.name, set()).add(runtime)

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

        for runtime in ("claude", "cli", "coco-snowsight"):
            if runtime in runtimes:
                per_runtime_status[runtime] = "present"
            elif (skill_name, runtime) in EXPECTED_DIVERGENCES:
                per_runtime_status[runtime] = "expected-divergence"
            else:
                per_runtime_status[runtime] = "missing"

        # CLI is the canonical source. A skill in cli satisfies the "claude"
        # requirement (since cli serves both Claude Code and Cortex Code CLI).
        effectively_in_claude = (
            per_runtime_status["claude"] == "present" or
            per_runtime_status["cli"] == "present"
        )

        # CoCo Snowsight: if skill is in cli (or claude), snowsight should have
        # it or have a documented divergence.
        if effectively_in_claude and per_runtime_status["coco-snowsight"] == "missing":
            failures.append(
                f"  ✗ {skill_name}: present in cli/claude but missing in coco-snowsight "
                f"(no EXPECTED_DIVERGENCES entry for ('{skill_name}', 'coco-snowsight'))"
            )

        # Skills in coco-snowsight that don't exist in cli or claude need documentation.
        if (per_runtime_status["coco-snowsight"] == "present" and
                not effectively_in_claude and
                (skill_name, "claude") not in EXPECTED_DIVERGENCES):
            failures.append(
                f"  ✗ {skill_name}: present in coco-snowsight but missing in cli/claude "
                f"(no EXPECTED_DIVERGENCES entry for ('{skill_name}', 'claude'))"
            )

        if args.verbose:
            cells = []
            for runtime in ("claude", "cli", "coco-snowsight"):
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
        print("     (agents/cli/<skill>/SKILL.md, agents/claude/<skill>/SKILL.md,")
        print("     or agents/coco-snowsight/<skill>/SKILL.md), OR")
        print("  2. Document the divergence in EXPECTED_DIVERGENCES at the top of")
        print("     tools/validate/check_runtime_coverage.py with a one-line reason.")
        print("  3. See .claude/rules/runtime-coverage.md for the full convention.")
        return 1

    print(f"All {len(coverage)} skill(s) match the runtime-coverage rule.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
