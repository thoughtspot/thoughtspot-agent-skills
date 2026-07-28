#!/usr/bin/env python3
"""check_skill_context_cost.py — gate the per-invocation context cost of skills.

A SKILL.md is loaded into the model's context on every invocation, so its size
is a recurring token tax on every user of the skill (BL-128). This gate makes
that cost visible and stops silent growth — the same monolith failure mode
check_file_size.py catches for ts-cli modules, measured in estimated tokens
(chars / 4) instead of lines.

Rules (every SKILL.md across all runtimes):
- est. tokens > HARD_FAIL and not allowlisted -> FAIL (exit 1)
- est. tokens > SOFT_WARN                     -> WARN (printed nudge, exit 0)

Calibration (2026-07-28): median skill ~4.9k est. tokens, p90 ~15k. The lean
converter model (powerbi/qlik/sisense, which defer to shared mappings) sits
under 3k. The remedy for an oversized skill is the BL-128 extraction pattern:
move templates, rule tables, and report formats to references/*.md, keep the
procedural spine inline (PR #314 cut tableau ~34% this way, no logic change).

--staged limits the scan to staged SKILL.md files (pre-commit); CI runs the
full scan with no flag.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess

SOFT_WARN = 12_000
HARD_FAIL = 25_000
CHARS_PER_TOKEN = 4
SKILL_GLOBS = (
    "agents/cli/*/SKILL.md",
    "agents/claude/*/SKILL.md",
    "agents/coco-snowsight/*/SKILL.md",
)

# One-time entries for pre-existing offenders: path -> backlog justification.
# An allowlisted file skips the hard-fail (it still soft-warns). Remove the
# entry when the skill is slimmed below HARD_FAIL.
ALLOWLIST: dict[str, str] = {
    # ~57k est. tokens at gate introduction — by far the largest skill. The
    # BL-128 extraction (references/ split) is the tracked remedy.
    "agents/cli/ts-convert-from-tableau/SKILL.md": "BL-128",
}


def _est_tokens(path: str) -> int:
    return os.path.getsize(path) // CHARS_PER_TOKEN


def _scan_files(root: str) -> list[str]:
    files: list[str] = []
    for pattern in SKILL_GLOBS:
        for path in glob.glob(os.path.join(root, pattern)):
            files.append(os.path.relpath(path, root).replace(os.sep, "/"))
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Estimated-token gate for SKILL.md files.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--staged", action="store_true",
                    help="only evaluate staged SKILL.md files (pre-commit mode)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    files = _scan_files(root)
    if args.staged:
        out = subprocess.run(
            ["git", "-C", root, "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True,
        )
        staged = set(out.stdout.splitlines())
        files = [f for f in files if f in staged]
        if not files:
            print("PASS  skill context cost: no staged SKILL.md files")
            return 0

    fails, warns = [], []
    for rel in sorted(files):
        tokens = _est_tokens(os.path.join(root, rel))
        if tokens > HARD_FAIL and rel not in ALLOWLIST:
            fails.append((rel, tokens))
        elif tokens > SOFT_WARN:
            warns.append((rel, tokens))

    for rel, tokens in warns:
        print("WARN  skill context cost: %s is ~%s est. tokens (>%s) — every "
              "invocation pays this; extract templates/tables to references/ "
              "(BL-128 pattern)" % (rel, f"{tokens:,}", f"{SOFT_WARN:,}"))
    if fails:
        print("FAIL  skill context cost — SKILL.md files exceed ~%s est. tokens:"
              % f"{HARD_FAIL:,}")
        for rel, tokens in fails:
            print("  %8s  %s" % (f"{tokens:,}", rel))
        print("\nEvery skill invocation loads the whole SKILL.md into context."
              "\nApply the BL-128 extraction: move templates, rule tables, and report"
              "\nformats into references/*.md and keep the procedural spine inline"
              "\n(see PR #314 for the pattern), or — for a pre-existing offender —"
              "\nadd a one-time ALLOWLIST entry in tools/validate/check_skill_context_cost.py"
              "\nwith a backlog cross-reference.")
        return 1
    print("PASS  skill context cost: %d skill(s) checked, %d warning(s)"
          % (len(files), len(warns)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
