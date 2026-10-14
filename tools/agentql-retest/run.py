#!/usr/bin/env python3
"""Re-probe every documented AgentQL limitation and lesson claim, and report what moved.

    python3 tools/agentql-retest/run.py --profile <ts-profile> \\
        --model-single <guid of "DunderMifflin Sales"> --model-multi <guid of "Dunder Mifflin">
    python3 tools/agentql-retest/run.py --profile <ts-profile> --suite lessons

Two suites. `limitations` backs limitations.md and runs on the Dunder Mifflin demo Models.
`lessons` backs learning-path.md and runs on "(Sample) Retail - Apparel", which ships on
every cluster: it is found by exact name and author `system`, so it needs no GUID.

Exit codes: 0 every case AS_DOCUMENTED · 1 at least one CHANGED · 2 at least one ERROR
(an ERROR outranks a CHANGED: a run that could not see everything must not read as clean).
See README.md for how to act on a CHANGED.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from agentql_retest.cases import CASES, SAMPLE_MODEL  # noqa: E402
from agentql_retest.classify import AS_DOCUMENTED, CHANGED, CLI_ERROR, ERROR, classify, validate_cases  # noqa: E402


def call(cmd: str, sql: str, model: str, profile: str, timeout: int) -> dict:
    try:
        r = subprocess.run(["ts", "agentql", cmd, "--profile", profile, "-m", model, sql],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"status": CLI_ERROR, "errors": [{"message": f"{type(e).__name__}: {e}"}]}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"status": CLI_ERROR, "errors": [{"message": (r.stderr or r.stdout)[-600:]}]}


def resolve_sample_model(profile: str) -> tuple:
    """-> (guid, problem). Exact name AND author `system`: clusters carry many user copies."""
    r = subprocess.run(["ts", "metadata", "search", "--profile", profile, "--subtype", "WORKSHEET",
                        "--name", SAMPLE_MODEL], capture_output=True, text=True)
    try:
        hits = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None, f"metadata search failed: {(r.stderr or r.stdout)[-300:]}"
    return pick_sample_model(hits)


def pick_sample_model(hits) -> tuple:
    found = [h.get("metadata_header", {}) for h in hits or []]
    found = [h for h in found if h.get("name") == SAMPLE_MODEL and h.get("authorName") == "system"]
    if len(found) != 1:
        return None, (f"expected one {SAMPLE_MODEL!r} authored by system, found {len(found)}; "
                      "pass --model-apparel <guid>")
    return found[0]["id"], None


def run_case(case, models, profile, timeout):
    gen = call("generate-sql", case.sql, models[case.model], profile, timeout)
    fetch = None
    if case.runs_fetch and gen.get("status") == "SUCCESS":
        fetch = call("fetch-data", case.sql, models[case.model], profile, timeout)
    return case.id, {"gen": gen, "fetch": fetch}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True, help="ThoughtSpot profile name (ts profiles list)")
    ap.add_argument("--suite", choices=("all", "limitations", "lessons"), default="all")
    ap.add_argument("--model-single", help='GUID of the "DunderMifflin Sales" Model (limitations suite)')
    ap.add_argument("--model-multi", help='GUID of the "Dunder Mifflin" Model (limitations suite)')
    ap.add_argument("--model-apparel", help=f'GUID of "{SAMPLE_MODEL}" (lessons suite; found by name if omitted)')
    ap.add_argument("--only", nargs="*", default=[], help="case ids to run (their controls are added)")
    ap.add_argument("--out", help="write the raw per-case results and verdicts as JSON here")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=300, help="seconds per ts call")
    args = ap.parse_args()

    problems = validate_cases(CASES)
    if problems:
        print("case list is malformed:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2

    pool = [c for c in CASES if args.suite in ("all", c.suite)]
    todo = pool
    if args.only:
        want = set(args.only)
        unknown = want - {c.id for c in pool}
        if unknown:
            print(f"unknown case ids in suite {args.suite}: {sorted(unknown)}", file=sys.stderr)
            return 2
        suites = {c.suite for c in pool if c.id in want}
        want |= {c.id for c in pool if c.control and c.suite in suites}  # checks read the controls
        todo = [c for c in pool if c.id in want]

    models = {"single": args.model_single, "multi": args.model_multi, "apparel": args.model_apparel}
    if any(c.model == "apparel" for c in todo) and not models["apparel"]:
        models["apparel"], problem = resolve_sample_model(args.profile)
        if problem:
            print(problem, file=sys.stderr)
            return 2
        print(f"{SAMPLE_MODEL}: {models['apparel']}")
    missing = sorted({c.model for c in todo if not models[c.model]})
    if missing:
        print(f"--model-{' / --model-'.join(missing)} required for suite {args.suite} "
              "(or pass --suite lessons)", file=sys.stderr)
        return 2
    with ThreadPoolExecutor(args.workers) as ex:
        results = dict(ex.map(lambda c: run_case(c, models, args.profile, args.timeout), todo))

    verdicts = {}
    for c in todo:
        try:
            verdicts[c.id] = classify(c, results[c.id]["gen"], results[c.id]["fetch"], results)
        except Exception as e:  # a bespoke check tripping over an unexpected row shape
            verdicts[c.id] = (ERROR, [f"check raised {type(e).__name__}: {e}"])

    counts = {AS_DOCUMENTED: 0, CHANGED: 0, ERROR: 0}
    for c in todo:
        v, reasons = verdicts[c.id]
        counts[v] += 1
        if v != AS_DOCUMENTED or c.control:
            tag = "control" if c.control and v == AS_DOCUMENTED else v
            print(f"{tag:<13} {c.id:<28} {c.row}")
            if v != AS_DOCUMENTED:
                for r in reasons:
                    print(f"{'':<14}- {r}")
    print(f"\n{len(todo)} cases: {counts[AS_DOCUMENTED]} as documented, {counts[CHANGED]} changed, "
          f"{counts[ERROR]} error")

    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(
            {c.id: {"row": c.row, "sql": c.sql, "verdict": verdicts[c.id][0], "reasons": verdicts[c.id][1],
                    **results[c.id]} for c in todo}, indent=1))
        print(f"results: {args.out}")

    return 2 if counts[ERROR] else (1 if counts[CHANGED] else 0)


if __name__ == "__main__":
    sys.exit(main())
