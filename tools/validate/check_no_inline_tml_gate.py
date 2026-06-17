#!/usr/bin/env python3
"""
check_no_inline_tml_gate.py — keep the CLI convert skills on `ts tml lint`, not a
hand-rolled invariant grep gate.

The 2026-06-12 "pre-import validation gate" pattern (a copy-pasted block running
`grep -nE '^\\s*aggregation:\\s*COUNT_DISTINCT' <file>` and asking the model to eyeball
I1/I4 by hand) was migrated to the parser-based `ts tml lint` command on 2026-06-17 (audit
angle 11). This guard prevents drift back to the hand-rolled gate — the same way
`check_no_v1_endpoints.py` guards the completed v1→v2 migration.

Rule: no `agents/cli/ts-convert-*/SKILL.md` may contain a shell `grep` that inspects an
`aggregation:` key. That is the fingerprint of the manual gate; the legitimate replacement
calls `ts tml lint`. (CoCo skills are out of scope — they run in Snowsight and cannot
invoke the `ts` CLI, so they keep their own stored-procedure checks.)

Exit codes:
  0 — no inline TML-invariant grep gate in any CLI convert skill
  1 — at least one hand-rolled gate found

Run manually:
    python3 tools/validate/check_no_inline_tml_gate.py --root .
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# A shell grep that inspects an `aggregation:` key — the manual gate's fingerprint.
# Matches e.g.  grep -nE '^\s*aggregation:\s*COUNT_DISTINCT' <file>
GATE_RE = re.compile(r"\bgrep\b[^\n]*aggregation\s*:")

CONVERT_GLOB = "agents/cli/ts-convert-*/SKILL.md"


def scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [(i, ln.strip()[:80]) for i, ln in enumerate(lines, 1) if GATE_RE.search(ln)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    failures: list[str] = []
    scanned = 0
    for path in sorted(root.glob(CONVERT_GLOB)):
        scanned += 1
        for lineno, snippet in scan_file(path):
            failures.append(f"  ✗ {path.relative_to(root)}:{lineno}: {snippet!r}")

    if failures:
        print(f"\n{len(failures)} hand-rolled TML-invariant grep gate(s) found:\n")
        print("\n".join(failures))
        print()
        print("CLI convert skills must gate imports with `ts tml lint` (parser-based,")
        print("covers I1/I2/I4/I5/I8), not a hand-written grep. See .claude/rules/ts-cli.md")
        print("and agents/shared/schemas/ts-model-conversion-invariants.md.")
        return 1

    print(f"No inline TML-invariant grep gate in {scanned} CLI convert skill(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
