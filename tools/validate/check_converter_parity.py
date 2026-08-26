"""check_converter_parity.py — assert every converter adopts the shared correctness set.

The TML-correctness fixes that every converter needs live in
``ts_cli/formula_common.py``, whose docstring says plainly: *"Never fork these into
a platform module; import them."* Adoption was nonetheless partial and unenforced,
and the cost came due in PR #440 (``ts-convert-from-domo``): it copied the Qlik
converter's structure but omitted its pass-through map, so it emitted
``upper([Region])`` and ``trim([Name])`` — functions that do **not** exist in
ThoughtSpot (BL-170/BL-171, live-disproved) — and reported them as ``Migrated``.
Formulas rejected at import with error_code 14516, presented as a clean conversion.
Nothing in the repo asserted otherwise, so it landed looking green (BL-217).

This validator is the automated-check bucket for that class.

Scope is **discovered, never listed.** Converter platforms come from globbing
``agents/cli/ts-convert-*`` — the naming rule (``.claude/rules/skill-naming.md``,
family 3) guarantees ``ts-convert-{to|from}-{platform}``, so a new converter is in
scope from its first commit. Each platform resolves to a code location **by
convention** (``ts_cli/<platform>/``); only genuinely irregular names need an entry
in ``PLATFORM_CODE_OVERRIDES``. A platform that resolves to nothing and has no
override is a hard failure telling the author to add one — the point being that a
new converter cannot be *silently* skipped, which is exactly how a missed edit in
the pre-BL-110 validators reported PASS.

Requirements are **shape-conditional** — derived from what a package actually does,
not asserted of everything:

  A. Maps a source function onto one of the six function names that do **not** exist
     in ThoughtSpot (``upper``, ``lower``, ``trim``, ``ltrim``, ``rtrim``, ``replace``
     — live-disproved, BL-170/BL-171) -> that name must be *routed* to a
     ``sql_*_op`` pass-through, not emitted bare.
  B. Emits formulas -> must use ``resolve_name_collisions`` **and**
     ``fix_double_aggregation``.

A catches #440's ``upper([Region])`` regression; B catches its formula-id collision
regression. Both were verified against #440's actual pre-review commit — see
``tools/validate/tests/test_check_converter_parity.py``.

**Requirement A is deliberately phrased as a forbidden OUTPUT, not as helper
adoption**, and that distinction is the whole design. The first cut of this
validator asserted "emits ``sql_*_op`` -> must import ``wrap_passthrough_calls``"
and **passed on the broken #440 tree**: the bug is that the converter emitted *no*
pass-through at all, so an absence-triggered rule could never fire. A rule keyed on
the presence of the correct behaviour cannot detect its absence. Checking for the
wrong output instead fires on exactly the shape that shipped.

Routing is what makes an intermediate ``upper`` legitimate: Qlik and PowerBI both
map ``upper -> upper``, then rewrite it because ``upper`` is a *key* in their
pass-through map. That is correct and must not be flagged, so A only fails when the
name is mapped and **not** routed.

Deliberately **not** yet enforced: I3 (``index_type: DONT_INDEX`` on computed
measures) and ``validate_tml_invariants``. Only the Databricks converter runs the
latter, and it does so as a CLI command rather than in-package, so a useful check
needs a different signal than an import. Encoding ~12 more divergences nobody reads
would weaken the ones here. Tracked as the remaining half of BL-217.

Exit codes:
  0 — every converter satisfies the requirements its shape triggers
  1 — at least one unadopted helper, or an unresolvable platform

Run manually:
    python3 tools/validate/check_converter_parity.py --root .
    python3 tools/validate/check_converter_parity.py --root . --verbose
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CONVERTER_SKILL_GLOB = "ts-convert-*"
SKILL_NAME_RE = re.compile(r"^ts-convert-(?:to|from)-(?P<platform>[a-z0-9][a-z0-9-]*)$")

# Platforms whose code location does not follow `ts_cli/<platform>/`.
# A value of None means "no CLI module by design" — the converter is documented in
# the shared mappings and driven agentically, so there is no import to assert.
PLATFORM_CODE_OVERRIDES: dict[str, tuple[str, ...] | None] = {
    # The Databricks Metric View converter drops the artifact suffix in code.
    "databricks-mv": ("ts_cli/databricks/*.py",),
    # The Snowflake Semantic View converter is a module prefix, not a package.
    "snowflake-sv": ("ts_cli/sv_*.py",),
    # Looker is mapping-only: `ts-convert-from-looker` translates against
    # agents/shared/mappings/ and ships no ts_cli module to check.
    "looker": None,
}

# Documented intentional divergences. Each entry needs a one-line justification so a
# reviewer can sanity-check it — same convention as check_runtime_coverage.py.
#
# Format: {(platform, helper): "one-line reason"}
#
# These encode the state as of 2026-08-26 so the gate exists BEFORE the cleanup
# (BL-217's stated ordering). Retiring an entry is a small reviewable PR; adding one
# should be rare and argued.
EXPECTED_DIVERGENCES: dict[tuple[str, str], str] = {
    # --- Requirement A: pass-throughs not built with the shared helper ---
    # One fix, four mechanisms. This is the drift BL-217 exists to retire; each of
    # these is a consolidation target, not a permanent exemption.
    ("tableau", "wrap_passthrough_calls"):
        "Hand-rolled `_ARG_HANDLERS` lambdas in tableau/functions.py. Not a "
        "like-for-like move: the list also does arity-dependent COMPOSITIONS "
        "(LEFT/RIGHT/MID/STARTSWITH/ENDSWITH) that wrap_passthrough_calls cannot "
        "express, so consolidation must split composition from pass-through first.",
    ("databricks-mv", "wrap_passthrough_calls"):
        "Uses its own `_PASS_THROUGH_HINT` map in databricks/mv_sql.py — a third "
        "mechanism for the same fix, found while landing this validator (the BL-217 "
        "write-up recorded three, not four). Consolidation target.",
    ("snowflake-sv", "wrap_passthrough_calls"):
        "Emits pass-throughs from its own SQL->TS translation path in sv_translate.py "
        "rather than via the shared wrapper. Consolidation target.",

    # --- Requirement B: formula-column helpers not adopted ---
    # These two are the same gap #440 reintroduced: two source objects sharing a
    # measure name collide on `formula_<name>` and BOTH formulas are dropped,
    # leaving a dangling formula_id.
    ("powerbi", "resolve_name_collisions"):
        "Gap, not a design choice — PowerBI emits formula columns and can collide "
        "exactly as #440 did. Close it (BL-217 part 2).",
    ("powerbi", "fix_double_aggregation"):
        "Gap, not a design choice — same reasoning as resolve_name_collisions above.",
    ("qlik", "resolve_name_collisions"):
        "Gap, not a design choice — Qlik emits formula columns; #440 copied this "
        "converter's structure and inherited the same gap. Close it (BL-217 part 2).",
    ("qlik", "fix_double_aggregation"):
        "Gap, not a design choice — same reasoning as resolve_name_collisions above.",
}

# Requirement A — function names that do NOT exist in ThoughtSpot. Live-disproved on
# se-thoughtspot 2026-07-29/30 (BL-170, BL-171): an import rejects them with
# error_code 14516. A converter may use one as an intermediate marker, but must route
# it to a sql_*_op pass-through before emission.
NONEXISTENT_TS_FUNCTIONS = ("upper", "lower", "trim", "ltrim", "rtrim", "replace")

# `"upper": "upper"` — a mapping whose VALUE is a forbidden bare name.
def _mapped_as_value_re(fn: str) -> re.Pattern[str]:
    return re.compile(r":\s*[\"']" + fn + r"[\"']")

# `"upper": ("sql_string_op", "UPPER({0})", 1)` — the name is routed, so the mapping
# above is an intermediate marker rather than an emitted function.
def _routed_re(fn: str) -> re.Pattern[str]:
    return re.compile(r"[\"']" + fn + r"[\"']\s*:\s*\(\s*[\"']sql_\w+_op")

# Requirement B — signals that a package emits formulas at all. `formula_id` alone is
# too narrow: #440's broken tree emitted formulas without ever using that spelling.
FORMULA_EMISSION_MARKERS = ("formula_id", "formulas", "formula_")
FORMULA_COLUMN_HELPERS = ("resolve_name_collisions", "fix_double_aggregation")


def discover_platforms(root: Path) -> list[str]:
    """Platform tokens from agents/cli/ts-convert-*, deduped.

    Both directions of a symmetric pair (to-/from-) share one platform and one code
    location, so `snowflake-sv` appears once even though two skills reference it.
    """
    skills_dir = root / "agents" / "cli"
    platforms: set[str] = set()
    for path in sorted(skills_dir.glob(CONVERTER_SKILL_GLOB)):
        if not path.is_dir():
            continue
        match = SKILL_NAME_RE.match(path.name)
        if match:
            platforms.add(match.group("platform"))
    return sorted(platforms)


def resolve_code_files(root: Path, platform: str) -> tuple[list[Path], bool]:
    """Return (files, resolved). `resolved` is False only when nothing matched and
    no override explains it — the case that must fail loudly."""
    if platform in PLATFORM_CODE_OVERRIDES:
        patterns = PLATFORM_CODE_OVERRIDES[platform]
        if patterns is None:
            return [], True          # documented as having no CLI module
        files: list[Path] = []
        for pattern in patterns:
            files.extend(sorted((root / "tools" / "ts-cli").glob(pattern)))
        return files, bool(files)

    # Convention: ts_cli/<platform>/*.py
    pkg = root / "tools" / "ts-cli" / "ts_cli" / platform.replace("-", "_")
    if pkg.is_dir():
        return sorted(pkg.glob("*.py")), True
    return [], False


def read_all(files: list[Path]) -> str:
    chunks = []
    for path in files:
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(chunks)


def check_platform(platform: str, files: list[Path]) -> tuple[list[str], list[str]]:
    """Return (failures, notes) for one platform."""
    failures: list[str] = []
    notes: list[str] = []

    if not files:
        notes.append("no CLI module (documented) — nothing to assert")
        return failures, notes

    source = read_all(files)

    def require(helper: str, because: str) -> None:
        if helper in source:
            notes.append(f"{helper}: adopted")
        elif (platform, helper) in EXPECTED_DIVERGENCES:
            notes.append(f"{helper}: expected-divergence")
        else:
            failures.append(
                f"{platform}: {because}, so it must use "
                f"formula_common.{helper} — not found in "
                f"{files[0].parent.relative_to(files[0].parents[3])}/. "
                f"Import the shared helper (formula_common says: never fork these), "
                f"or add a justified entry to EXPECTED_DIVERGENCES."
            )

    # Requirement A — a forbidden name mapped but not routed to a pass-through
    for fn in NONEXISTENT_TS_FUNCTIONS:
        if not _mapped_as_value_re(fn).search(source):
            continue
        if _routed_re(fn).search(source):
            notes.append(f"{fn}: mapped, routed to sql_*_op — OK")
        elif (platform, f"emits:{fn}") in EXPECTED_DIVERGENCES:
            notes.append(f"{fn}: expected-divergence")
        else:
            failures.append(
                f"{platform}: maps a source function to `{fn}`, which is NOT a "
                f"ThoughtSpot function (BL-170/BL-171, live-disproved — an import "
                f"rejects it with error_code 14516), and does not route it to a "
                f"sql_*_op pass-through. Emitted formulas will be rejected at import "
                f"while the migration report calls them Migrated. Add `{fn}` to the "
                f"package's pass-through map (see qlik/functions.py PASSTHROUGH_MAP) "
                f"and rewrite via formula_common.wrap_passthrough_calls."
            )

    # Requirement B — formula emission needs the collision/aggregation helpers
    if any(marker in source for marker in FORMULA_EMISSION_MARKERS):
        for helper in FORMULA_COLUMN_HELPERS:
            require(helper, "emits formulas")
    else:
        notes.append("no formula emission — formula-helper requirement N/A")

    return failures, notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every platform's per-requirement status")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    platforms = discover_platforms(root)

    if not platforms:
        print(f"No ts-convert-* skills found under {root}/agents/cli/. Nothing to check.")
        return 0

    failures: list[str] = []

    for platform in platforms:
        files, resolved = resolve_code_files(root, platform)
        if not resolved:
            failures.append(
                f"{platform}: cannot locate its CLI code. Expected "
                f"tools/ts-cli/ts_cli/{platform.replace('-', '_')}/. Add an entry to "
                f"PLATFORM_CODE_OVERRIDES in this file — map it to the real path, or "
                f"to None if the converter ships no CLI module by design. "
                f"(Failing loudly here is deliberate: a new converter must not be "
                f"silently skipped.)"
            )
            continue

        platform_failures, notes = check_platform(platform, files)
        failures.extend(platform_failures)

        if args.verbose:
            print(f"  {platform}:")
            for note in notes:
                print(f"      {note}")

    if failures:
        print("FAIL  converter parity — a converter emits a non-existent ThoughtSpot\n      function, or skips a shared correctness helper:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    divergences = len(EXPECTED_DIVERGENCES)
    print(f"PASS  converter parity: {len(platforms)} converter platform(s) checked, "
          f"{divergences} documented divergence(s) outstanding (BL-217 part 2).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
