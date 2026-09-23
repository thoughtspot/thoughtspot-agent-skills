#!/usr/bin/env python3
"""
check_i7_gate.py — every conversion skill must carry the I7 untranslatable gate.

Invariant I7 (``agents/shared/schemas/ts-model-conversion-invariants.md``) requires
each conversion skill to instruct the model to open its formula-translation reference
*before* classifying an expression as untranslatable — "Do not decide from syntax
alone." The invariant states the gate "appears before the untranslatable
classification step in every skill".

It did not. The 2026-09-22 full audit (finding 9.3) found the gate present in **2 of
11** converters — ``ts-convert-from-tableau`` and the CoCo ``ts-convert-from-snowflake-sv``
mirror — while every other converter reached a step that surfaces skipped or
untranslatable expressions to the user with no instruction to check the reference
first. ``ts-convert-to-snowflake-sv`` referred to untranslatable expressions fifteen
times and cited I7 zero times. Nothing enforced the invariant anywhere, so the gap was
invisible between full audits.

The failure this causes is silent and lossy: an expression with a documented
ThoughtSpot equivalent is dropped from the converted model on syntax recognition
alone, and the user is asked to "proceed without them" with no signal that the
translation was available.

Rule, per converter ``SKILL.md``:

1. It cites exactly one ``*-formula-translation.md`` mapping (its source dialect).
2. It contains at least one blockquote gate carrying the ``MANDATORY (I7)`` marker.
3. That gate cites the same formula-translation mapping the skill uses.
4. That gate points back to ``ts-model-conversion-invariants.md``.

All four must hold in one gate block, so a marker in one place and a citation in
another does not pass. A skill may carry the gate more than once (``from-tableau``
carries it at both classification points); only one must be complete.

Scope is **discovered, never listed** — the glob is ``ts-convert-*`` across every
runtime in ``_dirs``, so a new converter is gated from its first commit. This is the
same principle as ``conversion-consistency-auditor``'s run-time discovery and
``_dirs.py`` itself: a hand-kept list is what let the gap reach 9 converters.

Exit codes:
  0 — every conversion skill carries a complete I7 gate
  1 — at least one is missing or incomplete

Run manually:
    python3 tools/validate/check_i7_gate.py --root .
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _dirs import ALL_RUNTIMES, runtime_globs  # noqa: E402

CONVERT_SUFFIX = "ts-convert-*/SKILL.md"

#: The gate marker. Matched case-sensitively — it is a literal convention, not prose.
MARKER = "MANDATORY (I7)"

#: A skill's source-dialect reference, e.g. `tableau-formula-translation.md`.
MAPPING_RE = re.compile(r"[\w.-]*/([\w-]+-formula-translation\.md)")

#: The invariants doc the gate must point back to.
INVARIANTS_DOC = "ts-model-conversion-invariants.md"


def blockquote_runs(lines: list[str]) -> list[tuple[int, str]]:
    """Contiguous runs of markdown blockquote lines, as (start_lineno, text)."""
    runs: list[tuple[int, str]] = []
    start: int | None = None
    buf: list[str] = []
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith(">"):
            if start is None:
                start = i
            buf.append(ln)
        elif start is not None:
            runs.append((start, "\n".join(buf)))
            start, buf = None, []
    if start is not None:
        runs.append((start, "\n".join(buf)))
    return runs


def cited_mapping(text: str) -> str | None:
    """The single formula-translation mapping this skill cites, if unambiguous."""
    names = {m.group(1) for m in MAPPING_RE.finditer(text)}
    return names.pop() if len(names) == 1 else None


def check_skill(path: Path, root: Path) -> list[str]:
    """Problems with one converter SKILL.md; empty means it passes."""
    rel = path.relative_to(root)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"  ✗ {rel}: unreadable ({exc})"]

    mapping = cited_mapping(text)
    if mapping is None:
        names = sorted({m.group(1) for m in MAPPING_RE.finditer(text)})
        detail = f"cites {len(names)}: {', '.join(names)}" if names else "cites none"
        return [
            f"  ✗ {rel}: no single formula-translation reference to gate against "
            f"({detail}). A converter must cite exactly one source-dialect mapping."
        ]

    gates = [(n, t) for n, t in blockquote_runs(text.splitlines()) if MARKER in t]
    if not gates:
        return [
            f"  ✗ {rel}: no `{MARKER}` gate. Add one before the step that classifies "
            f"or surfaces untranslatable/skipped expressions, citing {mapping}."
        ]

    for _lineno, gate in gates:
        if mapping in gate and INVARIANTS_DOC in gate:
            return []

    problems = []
    for lineno, gate in gates:
        missing = []
        if mapping not in gate:
            missing.append(f"does not cite {mapping}")
        if INVARIANTS_DOC not in gate:
            missing.append(f"does not reference {INVARIANTS_DOC}")
        problems.append(f"  ✗ {rel}:{lineno}: incomplete gate — {'; '.join(missing)}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    skills = sorted(runtime_globs(root, CONVERT_SUFFIX, ALL_RUNTIMES))
    failures: list[str] = []
    for path in skills:
        failures.extend(check_skill(path, root))

    if failures:
        print(f"\nI7 gate missing or incomplete in {len(failures)} conversion skill(s):\n")
        print("\n".join(failures))
        print()
        print("Invariant I7 requires every conversion skill to instruct the model to open")
        print("its formula-translation reference BEFORE classifying an expression as")
        print("untranslatable. Without it, expressions with documented ThoughtSpot")
        print("equivalents are dropped on syntax recognition alone.")
        print()
        print("The gate is a blockquote carrying the `MANDATORY (I7)` marker, citing the")
        print("skill's own mapping and the invariants doc. Worked example:")
        print("  agents/cli/ts-convert-from-tableau/SKILL.md (Step A3)")
        print()
        print("See agents/shared/schemas/ts-model-conversion-invariants.md (I7).")
        return 1

    print(f"I7 gate present in {len(skills)} conversion skill(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
