#!/usr/bin/env python3
"""File-size gate for ts-cli modules and the audit report's JS (BL-070, BL-503).

Complements check_module_health.py: complexity and size are independent
signals — a module can be long-but-simple or short-but-gnarly. This gate
catches the monolith failure mode (tableau_translate.py reached 2,543 lines
before the BL-069 split).

Rules (product code under tools/ts-cli/ts_cli, excluding tests — `.py` modules and,
since BL-503, the audit report's `.js` parts, which the report now grows by adding):
- lines > HARD_FAIL and not allowlisted  -> FAIL (exit 1)
- lines > SOFT_WARN                       -> WARN (printed nudge, exit 0)
- a top-level JS `function` longer than JS_FUNCTION_FAIL lines -> FAIL, unless
  ratcheted in JS_FUNCTION_RATCHET; longer than JS_FUNCTION_WARN -> WARN. (The Python
  side's function-level gate is check_module_health's complexity ratchet; the report's
  JS has no complexity tool here, so length stands in for it. It sees only a
  `function name(` declaration at column 0, closed by the next column-0 `}` — the
  report's style; a function expression, an arrow, a method in `registerView({...})` or
  an indented declaration is not measured, and a mis-indented `}` cuts one short.)

--staged limits the scan to staged files (pre-commit); CI runs the full scan with no
flag.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent))
from _git import git_paths  # noqa: E402

SOFT_WARN = 500
HARD_FAIL = 1000
SCAN_ROOT = "tools/ts-cli/ts_cli"
SCANNED_SUFFIXES = (".py", ".js")
JS_FUNCTION_WARN = 150
JS_FUNCTION_FAIL = 250

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
    # 1569 as of ts-cli v0.203.1: the import-retry step moved to
    # tableau/import_retry.py (down from 1698).
    "tools/ts-cli/ts_cli/commands/tableau.py": (1569, "BL-089"),
    # The report's largest view: past SOFT_WARN when the gate reached JS (BL-503).
    # Split it into per-tab files when it is next changed; lower this as it shrinks.
    "tools/ts-cli/ts_cli/audit/report/views/objectmap.js": (756, "BL-520"),
}

# The same ratchet for top-level JS functions: (path, function name) -> (recorded
# length in lines, backlog reference). Both were past JS_FUNCTION_FAIL when the gate
# arrived (BL-503); BL-520 splits them. Lower these as they shrink.
JS_FUNCTION_RATCHET: dict[tuple[str, str], tuple[int, str]] = {
    ("tools/ts-cli/ts_cli/audit/report/views/crossmodel.js", "buildCrossModel"):
        (332, "BL-520"),
    ("tools/ts-cli/ts_cli/audit/report/views/scorecard.js", "buildScorecard"):
        (302, "BL-520"),
}

_JS_FUNCTION = re.compile(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")


def js_function_lengths(text: str) -> list[tuple[str, int, int]]:
    """`(name, first line, length in lines)` for each top-level `function` declaration
    (one starting at column 0), in order. It ends at the first later line that starts
    with `}` at column 0 — the report's style — or on its own line when that line closes
    every brace it opens (braces in strings included, so `"}"` on that line can end it
    early); one never closed runs to the end of the file. Inside a function only a
    column-0 `}` line ends it, so a brace in a string there is never mistaken for it."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out = []
    for i, line in enumerate(lines):
        m = _JS_FUNCTION.match(line)
        if not m:
            continue
        if line.rstrip().endswith("}") and line.count("{") <= line.count("}"):
            out.append((m.group(1), i + 1, 1))
            continue
        end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("}")),
                   len(lines) - 1)
        out.append((m.group(1), i + 1, end - i + 1))
    return out


def _js_function_findings(root: str, rel: str) -> tuple[list, list]:
    """(fails, warns) for one JS file's top-level functions."""
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        text = fh.read()
    fails, warns = [], []
    for name, start, n in js_function_lengths(text):
        recorded = JS_FUNCTION_RATCHET.get((rel, name))
        if recorded is not None:
            if n > recorded[0]:
                fails.append((rel, name, n, "recorded %d, %s" % recorded))
            elif n > JS_FUNCTION_WARN:
                warns.append((rel, name, n))
        elif n > JS_FUNCTION_FAIL:
            fails.append((rel, name, n, "limit %d" % JS_FUNCTION_FAIL))
        elif n > JS_FUNCTION_WARN:
            warns.append((rel, name, n))
    return fails, warns


def _scan_files(root: str) -> list[str]:
    base = os.path.join(root, SCAN_ROOT)
    files: list[str] = []
    for dirpath, _dirs, fnames in os.walk(base):
        if "/tests" in dirpath.replace(os.sep, "/"):
            continue
        for fn in fnames:
            if fn.endswith(SCANNED_SUFFIXES):
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                files.append(rel.replace(os.sep, "/"))
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Line-count gate for ts_cli modules.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--staged", action="store_true",
                    help="only evaluate staged files (pre-commit mode)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    files = _scan_files(root)
    if args.staged:
        # Via _git: a failing git invocation raises instead of yielding an
        # empty list, which this gate would have read as "nothing staged" and
        # reported PASS (audit 4.1).
        staged = set(git_paths(
            ["-C", root, "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            _P(root)))
        files = [f for f in files if f in staged]
        if not files:
            print("PASS  file size: no staged ts_cli modules")
            return 0

    fails, warns, ratchet_fails = [], [], []
    func_fails, func_warns = [], []
    for rel in sorted(files):
        if rel.endswith(".js"):
            ff, fw = _js_function_findings(root, rel)
            func_fails += ff
            func_warns += fw
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
    for rel, name, n in func_warns:
        print("WARN  file size: %s function %s is %d lines (>%d) — split it into helpers"
              % (rel, name, n, JS_FUNCTION_WARN))
    if func_fails:
        print("FAIL  file size — JS functions too long:")
        for rel, name, n, why in func_fails:
            print("  %s: function %s is %d lines (%s)" % (rel, name, n, why))
        print("\nSplit the function into helpers, or — for a pre-existing offender — add a"
              "\nJS_FUNCTION_RATCHET entry recording its CURRENT length plus a backlog id.")
        return 1
    if fails:
        print("FAIL  file size — modules exceed %d lines:" % HARD_FAIL)
        for rel, n in fails:
            print("  %5d  %s" % (n, rel))
        print("\nSplit the module (see tools/ts-cli/CLAUDE.md architecture and the"
              "\nBL-069 refactor for the pattern), or — for a pre-existing offender —"
              "\nadd a RATCHET entry in tools/validate/check_file_size.py"
              "\nrecording its CURRENT size plus a backlog cross-reference.")
        return 1
    print("PASS  file size: %d module(s) checked, %d warning(s)"
          % (len(files), len(warns) + len(func_warns)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
