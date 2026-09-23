#!/usr/bin/env python3
"""
check_i7_gate.py — every conversion skill must carry the I7 untranslatable gate.

Invariant I7 (``agents/shared/schemas/ts-model-conversion-invariants.md``) requires
each conversion skill to instruct the model to open its formula-translation reference
*before* classifying an expression as untranslatable — "do not decide from syntax
alone."

The 2026-09-22 full audit (finding 9.3) found the **marker convention** carried by 2
of 11 converters. That is narrower than "9 skills gave no such instruction", and the
distinction matters: ``ts-convert-to-snowflake-sv`` and its CoCo mirror already held a
strong prose gate ("Do **not** classify a formula as untranslatable based on function
name recognition alone") plus a "Looks untranslatable / Actually translatable as"
table, and ``from-looker`` stated the rule and checklisted it. What none of them had
was a *machine-checkable* marker, so no gate could tell a skill that instructs the
model from one that does not — and the omission was invisible between full audits.

Rule, per converter ``SKILL.md``:

1. Its source dialect is derived from its directory name (``ts-convert-{from,to}-X``)
   and resolved to the one mapping under ``agents/shared/mappings/`` that serves X.
2. It contains at least one blockquote gate carrying the ``MANDATORY (I7)`` marker.
3. That gate cites **that dialect's** formula-translation mapping — not a sibling's.
4. That gate points back to ``ts-model-conversion-invariants.md``.

All of 2-4 must hold in one blockquote, so a marker in one place and a citation in
another does not pass.

Scope is **discovered, never listed** — the glob is ``ts-convert-*`` across every
runtime in ``_dirs``, and the dialect→mapping resolution is by name match, so a new
converter is gated from its first commit with no edit here. Same principle as
``conversion-consistency-auditor``'s run-time discovery and ``_dirs.py`` itself.

What this does NOT check, stated so the gate does not advertise more than it has:

* **Proximity.** Finding 9.3 asked for the marker "within N lines of the untranslatable
  classification step". Converters word that step too differently for a regex to find
  it without itself failing open, so this checks *presence in the procedure body* and
  excludes only the ``## Changelog`` tail. A gate in the wrong section of the procedure
  passes. BL-285 tracks the proximity refinement.
* **Semantics.** A blockquote carrying the marker but saying the opposite ("decide from
  syntax alone, it is faster") passes. No text check can settle that; review does.

``agents/databricks/`` (the Genie runtime) is deliberately out of scope — it sits
outside the mirror/coverage tooling by design (``.claude/rules/runtime-coverage.md``),
so its two converters are ungated here. BL-286 tracks that gap.

Exit codes:
  0 — every conversion skill carries a complete I7 gate
  1 — at least one is missing or incomplete, or the scope came back empty

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

#: The gate marker. Matched literally — it is a convention, not prose. Kept in step
#: with the "Required gate" block in ts-model-conversion-invariants.md (I7).
MARKER = "MANDATORY (I7)"

#: The invariants doc the gate must point back to.
INVARIANTS_DOC = "ts-model-conversion-invariants.md"

#: ``ts-convert-from-databricks-mv`` -> ``databricks``. The ``-sv``/``-mv`` tail names
#: the artifact (semantic view / metric view), not the dialect.
DIALECT_RE = re.compile(r"^ts-convert-(?:from|to)-(.+?)(?:-(?:sv|mv))?$")

FENCE_RE = re.compile(r"^\s*(```|~~~)")
COMMENT_OPEN, COMMENT_CLOSE = "<!--", "-->"


def strip_noncontent(text: str) -> str:
    """Blank out fenced code blocks and HTML comments, preserving line numbering.

    A marker shown as an *example* inside a fence, or parked in a comment, is not an
    instruction to the model and must not satisfy the gate.
    """
    out, in_fence, in_comment = [], False, False
    for line in text.splitlines():
        if in_comment:
            out.append("")
            if COMMENT_CLOSE in line:
                in_comment = False
            continue
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        if COMMENT_OPEN in line and COMMENT_CLOSE not in line:
            in_comment = True
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def procedure_body(text: str) -> str:
    """The skill's procedure — everything above ``## Changelog``.

    Changelog rows quote gates and cite sibling mappings routinely; scanning them
    would let a historical note satisfy a live gate.
    """
    m = re.search(r"^##+\s+Changelog\s*$", text, re.M)
    return text[: m.start()] if m else text


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


def dialect_of(skill_dir: str) -> str | None:
    """``ts-convert-from-qlik`` -> ``qlik``."""
    m = DIALECT_RE.match(skill_dir)
    return m.group(1) if m else None


def mapping_for_dialect(root: Path, dialect: str) -> str | None:
    """The ``*-formula-translation.md`` filename serving this dialect, by name match.

    Mapping directories are either the bare dialect (``qlik``, ``tableau``) or
    ``ts-``-prefixed (``ts-snowflake``, ``ts-databricks``). Resolved by discovery so a
    new dialect needs no edit here.
    """
    mappings = root / "agents" / "shared" / "mappings"
    for candidate in (dialect, f"ts-{dialect}"):
        d = mappings / candidate
        if d.is_dir():
            files = sorted(d.glob("*-formula-translation.md"))
            if len(files) == 1:
                return files[0].name
    return None


def check_skill(path: Path, root: Path) -> list[str]:
    """Problems with one converter SKILL.md; empty means it passes."""
    rel = path.relative_to(root)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"  ✗ {rel}: unreadable ({exc})"]

    skill_dir = path.parent.name
    dialect = dialect_of(skill_dir)
    if dialect is None:
        return [f"  ✗ {rel}: cannot derive a source dialect from directory {skill_dir!r}"]

    mapping = mapping_for_dialect(root, dialect)
    if mapping is None:
        return [
            f"  ✗ {rel}: no formula-translation mapping found for dialect {dialect!r} "
            f"(looked in agents/shared/mappings/{dialect}/ and /ts-{dialect}/). "
            f"A converter needs one before it can be gated."
        ]

    body = procedure_body(strip_noncontent(raw))
    gates = [(n, t) for n, t in blockquote_runs(body.splitlines()) if MARKER in t]
    if not gates:
        return [
            f"  ✗ {rel}: no `{MARKER}` gate in the procedure body. Add one before the "
            f"step that classifies or surfaces untranslatable/skipped expressions, "
            f"citing {mapping}."
        ]

    for _lineno, gate in gates:
        if mapping in gate and INVARIANTS_DOC in gate:
            return []

    problems = []
    for lineno, gate in gates:
        missing = []
        if mapping not in gate:
            missing.append(f"does not cite {mapping} (this skill's dialect is {dialect})")
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
    if not skills:
        print(f"\nNo ts-convert-* skills found under {root}.")
        print("This gate discovers its own scope, so an empty result means the layout")
        print("moved or --root is wrong — not that every converter passes.")
        return 1

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
        print("The gate is a blockquote carrying the `MANDATORY (I7)` marker, citing this")
        print("skill's own dialect mapping and the invariants doc. Worked example:")
        print("  agents/cli/ts-convert-from-tableau/SKILL.md (Step A3)")
        print()
        print("See agents/shared/schemas/ts-model-conversion-invariants.md (I7).")
        return 1

    print(f"I7 gate present in {len(skills)} conversion skill(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
