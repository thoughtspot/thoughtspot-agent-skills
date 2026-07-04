#!/usr/bin/env python3
"""
check_skill_cli_usage.py — keep CLI convert skills on `ts tableau build-model`,
not hand-rolled inline Python for TML formula assembly + import.

The 2026-06-27 Ads Commercial Dashboard migration took 1,389 tool calls (should
have been ~30-50) because SKILL.md Step 7 Phase 2 told the LLM to manually
orchestrate formula import with inline Python. That was replaced by a single
`ts tableau build-model --existing-guid` call. This guard prevents drift back to
the inline pattern — the same way `check_no_inline_tml_gate.py` guards the
completed grep→lint migration.

Rule: no `agents/cli/ts-convert-*/SKILL.md` may contain an inline Python heredoc
(`python3 -` or `python3 <<`) that assembles TML formula blocks for import. The
legitimate replacement calls `ts tableau build-model`.

Also guards the sibling drift this enabled (Task 10, Phase 4): SKILL.md steps
hand-assembling a `ts tml import`/`ts tml lint` payload with
`json.dumps([open(f).read() for f in ...])` instead of `--dir`/`--order`/
`--model-phase`/`--pattern`. The legitimate replacement is the directory-based
`ts tml import --dir ... --order tableau --model-phase base` form.

Exit codes:
  0 — no inline Python TML assembly in any CLI convert skill
  1 — at least one inline assembly pattern found

Run manually:
    python3 tools/validate/check_skill_cli_usage.py --root .
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Inline Python heredoc that builds TML formulas (or a payload) for import.
# Matches `python3 <<MARKER` anywhere on the line — including the common
# `python3 - > out.json <<'PY'` shape (stdin-script flag + output redirect
# before the heredoc marker), not just a bare `python3 <<` immediately —
# or a lone `python3 -` at end of line with no other content.
# Excludes read-wrappers (python3 -c "import json,pathlib;print(...)").
HEREDOC_RE = re.compile(r"python3\b.*<<|python3\s+-\s*$", re.MULTILINE)
FORMULA_ASSEMBLY_RE = re.compile(r"formulas?\s*[\[\]:{}]|formula_id|\"formulas\"")
# Inline Python heredoc that assembles a TML import payload by reading files
# directly (`json.dumps([open(f)...`) — the pattern `ts tml import --dir` /
# `--order` / `--model-phase` / `--pattern` replace (Task 10).
PAYLOAD_ASSEMBLY_RE = re.compile(r"json\.dumps\(\s*\[\s*open\(")
READ_WRAPPER_RE = re.compile(r'python3\s+-c\s+"import\s+(json|pathlib)')

CONVERT_GLOB = "agents/cli/ts-convert-*/SKILL.md"


def scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = text.splitlines()
    hits = []
    for i, ln in enumerate(lines):
        if HEREDOC_RE.search(ln) and not READ_WRAPPER_RE.search(ln):
            window = "\n".join(lines[max(0, i - 3):i + 15])
            if FORMULA_ASSEMBLY_RE.search(window) or PAYLOAD_ASSEMBLY_RE.search(window):
                hits.append((i + 1, ln.strip()[:80]))
    return hits


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
        print(f"\n{len(failures)} inline Python TML assembly pattern(s) found:\n")
        print("\n".join(failures))
        print()
        print("CLI convert skills must use `ts tableau build-model` for formula import,")
        print("not inline Python heredocs. See the build-model pipeline design doc.")
        return 1

    print(f"No inline Python TML assembly in {scanned} CLI convert skill(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
