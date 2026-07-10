#!/usr/bin/env python3
"""Module-health gate: block *new or worsening* function complexity.

Why this exists
---------------
As the repo grows and more contributors touch it, the risk is not the handful of
already-complex engine functions (formula translation, TML linting) — it is
*new* god-functions creeping in unnoticed. A hard complexity ceiling applied to
the whole repo today would fail immediately on the known-complex functions; a
per-PR reviewer can't reliably catch complexity by eye.

So this is a **ratchet**, not a flat threshold:

- Any product function whose cyclomatic complexity exceeds ``CAP`` must be listed
  in ``module_health_baseline.json`` (the visible tech-debt registry).
- A function above ``CAP`` that is **not** baselined  -> FAIL (new complexity).
- A baselined function whose complexity **increased** past its recorded value
  -> FAIL (existing hotspot got worse).
- Everything else passes. Today's code passes because the baseline captures
  today's offenders; only regressions fail.

To re-baseline after an intentional change:  ``--update-baseline``.

Complexity is measured with `radon` (a library dependency). If radon is not
installed this check SOFT-SKIPS with a note (so a contributor's local commit is
never blocked by a missing dev tool); CI installs radon and enforces it.

Scope: product Python only — ``tools/ts-cli/ts_cli`` and ``agents/**`` — excluding
tests, smoke-tests, and this validator's own tree.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

CAP = 15  # cyclomatic complexity above this must be baselined (radon: >15 = high-C/D+)

BASELINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "module_health_baseline.json")

INCLUDE_ROOTS = ["tools/ts-cli/ts_cli", "agents"]
EXCLUDE_PARTS = ("/tests/", "/smoke-tests/", "/node_modules/", "/.git/")
# Deploy-time generated, gitignored (.gitignore), vendored copies of already-baselined
# ts_cli functions built by agents/databricks/build_mv_lib.py — not source to scan.
EXCLUDE_FILES = ("agents/databricks/notebooks/databricks_mv_lib.py",)


def _iter_py_files(root):
    for inc in INCLUDE_ROOTS:
        base = os.path.join(root, inc)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".py") or fn.startswith("test_"):
                    continue
                fp = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, root)
                if any(part in "/" + rel for part in EXCLUDE_PARTS):
                    continue
                if rel in EXCLUDE_FILES:
                    continue
                yield fp, rel


def _functions(root, only=None):
    """Yield (key, complexity) for every function/method in scope.

    key is "<relpath>::<qualname>" — stable across runs.
    """
    from radon.complexity import cc_visit
    for fp, rel in _iter_py_files(root):
        if only is not None and rel not in only:
            continue
        try:
            src = open(fp, encoding="utf-8").read()
            blocks = cc_visit(src)
        except Exception:
            continue
        for b in blocks:
            qual = ("%s.%s" % (b.classname, b.name)) if getattr(b, "classname", None) else b.name
            yield "%s::%s" % (rel, qual), b.complexity


def _load_baseline():
    if os.path.exists(BASELINE_PATH):
        with open(BASELINE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Complexity ratchet gate.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--staged", action="store_true",
                    help="only evaluate staged .py files (untouched legacy is skipped)")
    ap.add_argument("--update-baseline", action="store_true",
                    help="rewrite module_health_baseline.json from current state")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)

    try:
        import radon  # noqa: F401
    except ImportError:
        print("SKIP  module health: radon not installed (`pip install radon`); "
              "enforced in CI.")
        return 0

    if args.update_baseline:
        offenders = {k: c for k, c in _functions(root) if c > CAP}
        with open(BASELINE_PATH, "w", encoding="utf-8") as fh:
            json.dump(dict(sorted(offenders.items())), fh, indent=2)
            fh.write("\n")
        print("Wrote baseline: %d function(s) above CAP=%d" % (len(offenders), CAP))
        return 0

    only = None
    if args.staged:
        import subprocess
        out = subprocess.run(["git", "-C", root, "diff", "--cached", "--name-only",
                              "--diff-filter=ACM"], capture_output=True, text=True)
        only = {ln for ln in out.stdout.splitlines() if ln.endswith(".py")}
        if not only:
            return 0

    baseline = _load_baseline()
    new_violations, worsened = [], []
    for key, cc in _functions(root, only=only):
        if cc <= CAP:
            continue
        if key not in baseline:
            new_violations.append((key, cc))
        elif cc > baseline[key]:
            worsened.append((key, cc, baseline[key]))

    if not new_violations and not worsened:
        print("PASS  module health: no new/worsening complexity above CAP=%d "
              "(%d baselined)" % (CAP, len(baseline)))
        return 0

    print("FAIL  module health — cyclomatic complexity regressions:\n")
    for key, cc in sorted(new_violations, key=lambda x: -x[1]):
        print("  NEW      cc=%-3d %s" % (cc, key))
    for key, cc, was in sorted(worsened, key=lambda x: -x[1]):
        print("  WORSENED cc=%-3d (was %d) %s" % (cc, was, key))
    print("\nRefactor the function(s) below CAP=%d (extract helpers), or — if the added"
          "\ncomplexity is genuinely warranted — re-baseline with:"
          "\n  python3 tools/validate/check_module_health.py --root . --update-baseline"
          "\nand explain why in the PR." % CAP)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
