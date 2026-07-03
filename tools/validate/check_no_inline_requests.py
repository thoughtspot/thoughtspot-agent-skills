#!/usr/bin/env python3
"""
check_no_inline_requests.py — fail if a Claude/CLI skill's code fences instruct the
`requests`/`urllib` anti-pattern instead of the `ts` CLI (.claude/rules/ts-cli.md,
"Claude skills use `ts`, never `requests`").

2026-07-03 audit finding 5.2: adjacent validators cover v1 endpoint literals in Python
(check_no_v1_endpoints.py), inline TML formula assembly (check_skill_cli_usage.py), and
the anti-pattern registry in check_patterns.py has a narrower, line-level `requests.*`
regex — but nothing dedicated scans SKILL.md **code fences** for the full anti-pattern
surface: `import requests`, `requests.<verb>(`, and direct `urllib` calls that hit a
ThoughtSpot v2 REST path. The gap let ts-dependency-manager SKILL.md carry a stale
"call v2 directly" instruction from 2026-05-11 to 2026-07-03 unnoticed (audit 5.1).

Why code fences only (not full-file prose): SKILL.md files legitimately *describe* the
anti-pattern in prose (e.g. this very validator's rationale, or a skill's own "don't do
this" callout) without ever putting it in a runnable fence. Restricting the scan to
fenced code blocks keeps that prose from tripping the check while still catching the
one place code that will actually be executed lives.

Documented exceptions (`.claude/rules/ts-cli.md`, "Exceptions — direct API calls are
legitimate in"):
  - `references/open-items.md` — self-contained test scripts verifying unverified API
    behaviour before a CLI command exists. Temporary scaffolding, not skill logic.
  - `agents/coco-snowsight/` — CoCo runs inside Snowsight with no `ts` CLI available;
    it uses stored procedures instead. Out of scope for this validator's scan roots
    anyway (only agents/cli/ and agents/claude/ are scanned), but excluded explicitly
    here too in case the scan roots ever widen.

Exit codes:
  0 — no inline `requests`/`urllib`-to-v2 anti-pattern in any scanned code fence
  1 — at least one anti-pattern found

Run manually:
    python3 tools/validate/check_no_inline_requests.py --root .
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Runtimes that use the `ts` CLI at runtime — the anti-pattern applies to these only.
# agents/coco-snowsight/ is deliberately excluded (see module docstring).
SCAN_ROOTS = ("agents/cli", "agents/claude")

# Reference files that are legitimate scratch/test-script surfaces per ts-cli.md.
EXEMPT_FILENAMES = ("open-items.md",)
EXEMPT_PATH_SEGMENTS = ("coco-snowsight",)

IMPORT_REQUESTS_RE = re.compile(r'(?:^|\s)import\s+requests\b')
REQUESTS_CALL_RE = re.compile(
    r'\brequests\.(get|post|put|delete|patch|head|request|Session)\s*\('
)
URLLIB_CALL_RE = re.compile(r'\burllib\.request\.|(?<!\.)\burlopen\s*\(')
V2_ENDPOINT_MARKER = "/api/rest/2.0/"


def _is_exempt(rel_path: Path) -> bool:
    if rel_path.name in EXEMPT_FILENAMES:
        return True
    return any(seg in rel_path.parts for seg in EXEMPT_PATH_SEGMENTS)


def _iter_fenced_blocks(text: str) -> list[list[tuple[int, str]]]:
    """Return a list of fenced code blocks, each a list of (lineno, line) tuples.

    Tracks ``` fence toggles the same way check_patterns.py does — a bare ``` line
    (with or without a language tag) opens or closes a block.
    """
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    in_block = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            if in_block:
                blocks.append(current)
                current = []
                in_block = False
            else:
                in_block = True
            continue
        if in_block:
            current.append((lineno, line))
    return blocks


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, reason) for each anti-pattern hit inside a code fence.

    Empty list = clean.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    hits: list[tuple[int, str]] = []
    for block in _iter_fenced_blocks(text):
        block_text = "\n".join(line for _, line in block)
        has_v2_marker = V2_ENDPOINT_MARKER in block_text

        for lineno, line in block:
            if IMPORT_REQUESTS_RE.search(line):
                hits.append((lineno, f"import requests → {line.strip()[:80]!r}"))
                continue
            m = REQUESTS_CALL_RE.search(line)
            if m:
                hits.append((lineno, f"requests.{m.group(1)}(...) → {line.strip()[:80]!r}"))
                continue
            if URLLIB_CALL_RE.search(line) and has_v2_marker:
                hits.append(
                    (lineno,
                     f"urllib direct call to a ThoughtSpot v2 endpoint → {line.strip()[:80]!r}")
                )
    return hits


def iter_skill_md_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_root in SCAN_ROOTS:
        base = root / scan_root
        if base.is_dir():
            files.extend(sorted(base.rglob("*.md")))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args()
    root = Path(args.root).resolve()

    failures: list[str] = []
    scanned = 0
    for path in iter_skill_md_files(root):
        rel = path.relative_to(root)
        if _is_exempt(rel):
            continue
        scanned += 1
        for lineno, reason in scan_file(path):
            failures.append(f"  ✗ {rel}:{lineno}: {reason}")

    if failures:
        print(f"\n{len(failures)} inline requests/urllib anti-pattern(s) found:\n")
        print("\n".join(failures))
        print()
        print("Claude skills use the `ts` CLI, never direct `requests`/`urllib` calls")
        print("(.claude/rules/ts-cli.md). If the CLI doesn't yet have this operation,")
        print("write a test script in references/open-items.md instead, then add a")
        print("`ts` command per '.claude/rules/ts-cli.md#when-a-skill-needs-an-api-call'.")
        return 1

    print(f"No inline requests/urllib anti-pattern in {scanned} skill doc(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
