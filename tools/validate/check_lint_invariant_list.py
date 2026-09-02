#!/usr/bin/env python3
"""
check_lint_invariant_list.py — the lint rule set is enumerated ONCE, and correctly.

`ts tml lint`'s rule set was restated in 11 places across skills, READMEs, CLAUDE.md
files, a validator's own output and two docstrings. Being hand-maintained, it drifted:
I14 was missing from several sites for weeks, and when I15 landed (BL-232) it was
missing from eight. None of that changed behaviour — every caller runs `lint_tml`,
which runs every rule — but a skill telling a reader the gate covers
`I1/I2/I4/I5/I8/I12/I13` understates it, and the reader's next move is to hand-write
the check the gate already does.

So this validator enforces two things:

1. **CORRECTNESS** — the enumeration in `tml_lint.py`'s docstrings matches the rules
   the module actually emits, derived from its source (every `"I<N>: ..."` finding
   string plus the `_check_*` helpers). A new rule with no docstring entry fails here.

2. **SINGULARITY** — no OTHER file enumerates the list. This is the half that stops
   the drift recurring: the fix for a stale copy is to delete the copy, not to update
   it. Prose should name the concept ("the model invariants") and link to the
   canonical doc.

Historical records are exempt: a backlog entry describing what the set was on a past
date is correct as written and must not be rewritten.

Usage:
    python tools/validate/check_lint_invariant_list.py
    python tools/validate/check_lint_invariant_list.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The one file allowed to enumerate the rule set.
CANONICAL = Path("tools/ts-cli/ts_cli/tml_lint.py")

# Files whose enumerations are historical statements about a past state — correct as
# written on their date, and rewriting them would falsify the record.
EXEMPT = {
    Path("docs/backlog.md"),
    Path("docs/backlog-archive.md"),
    Path("CHANGELOG.md"),
    Path("tools/validate/check_lint_invariant_list.py"),  # this file's own docstring
}

# Same, by shape rather than exact path.
EXEMPT_PATTERNS = (
    "docs/audit/",            # dated audit reports
    "changelog-archive",      # archived changelog
    "open-items.md",          # dated findings records
    "/tests/",                # test docstrings naming their own coverage
)

SEARCH_GLOBS = ("**/*.md", "**/*.py")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache"}

# An enumeration is 4+ invariant ids joined by "/". The threshold is a heuristic and
# deliberately loose: naming two or three specific rules is a legitimate
# cross-reference ("I4/I5/I8 belong to lint_tml — call both" in mv_tml.py names where
# responsibility sits), whereas listing four or more is copying the set. If a future
# cross-reference legitimately names four rules, widen the exemptions rather than
# lowering the bar — the check exists to stop COPIES, not mentions.
ENUM_RE = re.compile(r"\bI\d+(?:/I\d+){3,}\b")

# A skill's `## Changelog` row: historical, inside an otherwise-live file.
CHANGELOG_ROW_RE = re.compile(r"^\|\s*\d+\.\d+\.\d+\s*\|\s*\d{4}-\d{2}-\d{2}\s*\|")

# The explicit canonical declaration inside the linter's module docstring.
MARKER_RE = re.compile(r"CANONICAL-RULE-SET:\s*(I\d+(?:/I\d+)*)")

# A finding string emitted by the linter, e.g. f"I15: column '{label}' ..."
EMITTED_RE = re.compile(r'["\']I(\d+):')


def _iter_files(root: Path):
    for glob in SEARCH_GLOBS:
        for p in root.glob(glob):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.is_file():
                yield p


def emitted_rules(canonical: Path) -> set[str]:
    """Rule ids the linter actually emits, read from its source."""
    src = canonical.read_text(encoding="utf-8")
    return {f"I{n}" for n in EMITTED_RE.findall(src)}


def declared_rules(canonical: Path) -> tuple[int, set[str]] | None:
    """The CANONICAL-RULE-SET marker's ids, with its line number.

    An explicit marker rather than "every enumeration in the file": the canonical
    file legitimately contains meaningful SUBSET statements ("most of these
    (I1/I2/I4/I5) are invariants VALIDATE_ONLY does NOT catch"), and a rule that
    every enumeration must be complete flags those as stale when they are correct.
    Guessing which enumeration is authoritative is exactly the ambiguity the marker
    removes.
    """
    for lineno, line in enumerate(canonical.read_text(encoding="utf-8").splitlines(), 1):
        m = MARKER_RE.search(line)
        if m:
            return lineno, set(m.group(1).split("/"))
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    canonical = root / CANONICAL
    if not canonical.is_file():
        print(f"FAIL  lint invariant list: canonical file missing: {CANONICAL}")
        return 1

    problems: list[str] = []

    # 1. correctness
    emitted = emitted_rules(canonical)
    if not emitted:
        problems.append(
            f"{CANONICAL}: found no emitted 'I<N>:' finding strings — the extraction "
            f"pattern is stale, so this check is not actually verifying anything")
    declared = declared_rules(canonical)
    if declared is None:
        problems.append(
            f"{CANONICAL}: no CANONICAL-RULE-SET marker found — it is the ONE place the "
            f"rule set is declared, and this check has nothing to verify without it")
    for lineno, ids in ([declared] if declared else []):
        missing = sorted(emitted - ids, key=lambda s: int(s[1:]))
        if missing:
            problems.append(
                f"{CANONICAL}:{lineno}: enumeration omits {', '.join(missing)}, which "
                f"the module does emit — it understates the gate, and a reader's next "
                f"move is to hand-write a check that already exists")
        extra = sorted(ids - emitted, key=lambda s: int(s[1:]))
        if extra:
            problems.append(
                f"{CANONICAL}:{lineno}: enumeration lists {', '.join(extra)}, which the "
                f"module emits no finding for — it overstates the gate")

    # 2. singularity
    for path in _iter_files(root):
        rel = path.relative_to(root)
        if rel == CANONICAL or rel in EXEMPT:
            continue
        if any(pat in rel.as_posix() for pat in EXEMPT_PATTERNS):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if CHANGELOG_ROW_RE.match(line.strip()):
                continue  # a dated changelog row states what was true then
            if ENUM_RE.search(line):
                problems.append(
                    f"{rel}:{lineno}: restates the lint rule set. Delete the copy — "
                    f"name the concept ('the model invariants') and link to "
                    f"agents/shared/schemas/ts-model-conversion-invariants.md. The set "
                    f"is enumerated once, in {CANONICAL}.")

    if problems:
        print("FAIL  lint invariant list:")
        for p in problems:
            print(f"   {p}")
        return 1

    print(f"PASS  lint invariant list: {len(emitted)} rule(s) enumerated once "
          f"({', '.join(sorted(emitted, key=lambda s: int(s[1:])))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
