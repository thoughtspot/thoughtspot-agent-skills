#!/usr/bin/env python3
"""File-size gate for ts-cli modules (BL-070).

Complements check_module_health.py: complexity and size are independent
signals — a module can be long-but-simple or short-but-gnarly. This gate
catches the monolith failure mode (tableau_translate.py reached 2,543 lines
before the BL-069 split).

Rules (product code under tools/ts-cli/ts_cli, excluding tests):
- lines > HARD_FAIL and not allowlisted  -> FAIL (exit 1)
- lines > SOFT_WARN                       -> WARN (printed nudge, exit 0)

--staged limits the scan to staged .py files (pre-commit); CI runs the full
scan with no flag.
"""
from __future__ import annotations

import argparse
import os
import subprocess

SOFT_WARN = 500
HARD_FAIL = 1000
SCAN_ROOT = "tools/ts-cli/ts_cli"

# RATCHET, not an allowlist: path -> (recorded line count, backlog reference).
#
# This was `path -> backlog_id`, which meant an exempt file could grow WITHOUT
# BOUND while the gate reported PASS -- the BL-069 monolith failure mode recurring
# inside the exemption meant to contain it. Verified via git history (2026-08-26
# audit, finding 4.3): `commands/tableau.py` was allowlisted at **1063** lines
# (a1b3b65, 2026-07-05) and had reached **1675** (+58%) with the gate green
# throughout, because nothing recorded what "allowlisted" was allowing.
#
# Now it records the measurement. Growth past the recorded value fails; shrinking
# is free and the number should be lowered as the file is split. Same shape as
# `check_module_health`'s baseline JSON, which is the pattern this repo already
# trusts for complexity.
RATCHET: dict[str, tuple[int, str]] = {
    # ts tableau command module grew past 1000 lines with the multi-table
    # build-model fixes (v0.35-0.36). Split into per-flow submodules tracked
    # in BL-089 (M10); ratcheted until then. Lower this number as it shrinks.
    "tools/ts-cli/ts_cli/commands/tableau.py": (1675, "BL-089"),
}


def _scan_files(root: str) -> list[str]:
    base = os.path.join(root, SCAN_ROOT)
    files: list[str] = []
    for dirpath, _dirs, fnames in os.walk(base):
        if "/tests" in dirpath.replace(os.sep, "/"):
            continue
        for fn in fnames:
            if fn.endswith(".py"):
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                files.append(rel.replace(os.sep, "/"))
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Line-count gate for ts_cli modules.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--staged", action="store_true",
                    help="only evaluate staged .py files (pre-commit mode)")
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
            print("PASS  file size: no staged ts_cli modules")
            return 0

    fails, warns, ratchet_fails = [], [], []
    for rel in sorted(files):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            n = sum(1 for _ in fh)
        if rel in RATCHET:
            recorded, ref = RATCHET[rel]
            if n > recorded:
                ratchet_fails.append((rel, n, recorded, ref))
            elif n > SOFT_WARN:
                warns.append((rel, n))
        elif n > HARD_FAIL:
            fails.append((rel, n))
        elif n > SOFT_WARN:
            warns.append((rel, n))

    if ratchet_fails:
        print("FAIL  file size — a ratcheted module GREW:")
        for rel, n, recorded, ref in ratchet_fails:
            print("  %s: %d lines, recorded %d (+%d)  [%s]" % (rel, n, recorded, n - recorded, ref))
        print("\nA ratchet entry is a debt ceiling, not a licence to grow. Either bring the"
              "\nfile back under its recorded size, or -- if the growth is genuinely"
              "\nwarranted -- raise the number in RATCHET and say why in the PR.")
        return 1

    for rel, n in warns:
        print("WARN  file size: %s is %d lines (>%d) — consider a module-per-concern "
              "split (see BL-069 for the pattern)" % (rel, n, SOFT_WARN))
    if fails:
        print("FAIL  file size — modules exceed %d lines:" % HARD_FAIL)
        for rel, n in fails:
            print("  %5d  %s" % (n, rel))
        print("\nSplit the module (see tools/ts-cli/CLAUDE.md architecture and the"
              "\nBL-069 refactor for the pattern), or — for a pre-existing offender —"
              "\nadd a RATCHET entry in tools/validate/check_file_size.py"
              "\nrecording its CURRENT size plus a backlog cross-reference.")
        return 1
    print("PASS  file size: %d module(s) checked, %d warning(s)" % (len(files), len(warns)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
