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

# One-time entries for pre-existing offenders: path -> justification.
# An allowlisted file skips the hard-fail (it still soft-warns). Every entry
# needs a backlog cross-reference; remove the entry when the file is split.
ALLOWLIST: dict[str, str] = {
    # 1069 lines: TableauClient (~437) + six commands. The BL-069 build_model_cmd
    # decomposition (PR #161) fixed its complexity (cc 95 -> 13) but helper
    # signatures/docstrings kept the line count above HARD_FAIL. Split candidate:
    # move TableauClient to ts_cli/tableau/client.py (BL-069 follow-ups).
    "tools/ts-cli/ts_cli/commands/tableau.py":
        "BL-069 follow-ups — TableauClient + commands; complexity already gated",
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

    fails, warns = [], []
    for rel in sorted(files):
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            n = sum(1 for _ in fh)
        if n > HARD_FAIL and rel not in ALLOWLIST:
            fails.append((rel, n))
        elif n > SOFT_WARN:
            warns.append((rel, n))

    for rel, n in warns:
        print("WARN  file size: %s is %d lines (>%d) — consider a module-per-concern "
              "split (see BL-069 for the pattern)" % (rel, n, SOFT_WARN))
    if fails:
        print("FAIL  file size — modules exceed %d lines:" % HARD_FAIL)
        for rel, n in fails:
            print("  %5d  %s" % (n, rel))
        print("\nSplit the module (see tools/ts-cli/CLAUDE.md architecture and the"
              "\nBL-069 refactor for the pattern), or — for a pre-existing offender —"
              "\nadd a one-time ALLOWLIST entry in tools/validate/check_file_size.py"
              "\nwith a backlog cross-reference.")
        return 1
    print("PASS  file size: %d module(s) checked, %d warning(s)" % (len(files), len(warns)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
