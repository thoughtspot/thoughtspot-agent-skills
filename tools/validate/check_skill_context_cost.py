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

# RATCHET, not an allowlist: path -> (recorded est. tokens, backlog reference).
#
# This was `path -> backlog_id`, so an exempt skill could grow without bound while
# the gate reported PASS -- and it had: the comment below recorded "~34.4k" while
# the file measured **34,804** est. tokens, so it had already drifted past its own
# note with nothing to catch it (2026-08-26 audit, finding 4.3; identical shape to
# the check_file_size allowlist fixed in the same change).
#
# Now it records the measurement. Growth past the recorded value fails; shrinking is
# free and the number should be lowered as the skill is slimmed.
RATCHET: dict[str, tuple[int, str]] = {
    # ~57k est. tokens at gate introduction; the BL-128 round-1 extraction (PR #314)
    # cut it to ~57.2k, and the round-2 extraction (2026-07-28) cut it further to
    # ~34.4k est. tokens by archiving changelog history and moving more report
    # templates/tables/algorithm detail to references/ — still over the 25k
    # hard-fail line. A round-3 pass on Steps 4.5/5b/6/7's remaining
    # prompt-and-command-heavy spines is the tracked remedy to clear it.
    "agents/cli/ts-convert-from-tableau/SKILL.md": (34_804, "BL-128"),
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

    fails, warns, ratchet_fails = [], [], []
    for rel in sorted(files):
        tokens = _est_tokens(os.path.join(root, rel))
        if rel in RATCHET:
            recorded, ref = RATCHET[rel]
            if tokens > recorded:
                ratchet_fails.append((rel, tokens, recorded, ref))
            elif tokens > SOFT_WARN:
                warns.append((rel, tokens))
        elif tokens > HARD_FAIL:
            fails.append((rel, tokens))
        elif tokens > SOFT_WARN:
            warns.append((rel, tokens))

    if ratchet_fails:
        print("FAIL  skill context cost — a ratcheted skill GREW:")
        for rel, tokens, recorded, ref in ratchet_fails:
            print("  %s: ~%s est. tokens, recorded ~%s (+%s)  [%s]"
                  % (rel, f"{tokens:,}", f"{recorded:,}", f"{tokens - recorded:,}", ref))
        print("\nA ratchet entry is a debt ceiling, not a licence to grow. Bring the skill"
              "\nback under its recorded size (BL-128 extraction pattern), or -- if the"
              "\ngrowth is genuinely warranted -- raise the number in RATCHET and say why.")
        return 1

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
              "\nadd a RATCHET entry in tools/validate/check_skill_context_cost.py"
              "\nrecording its CURRENT est. tokens plus a backlog cross-reference.")
        return 1
    print("PASS  skill context cost: %d skill(s) checked, %d warning(s)"
          % (len(files), len(warns)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
