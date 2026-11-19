#!/usr/bin/env python3
"""smoke_ts_recipe_answer_period_comparison.py — live smoke for ts-recipe-answer-period-comparison.

Tier: Live (TS). Creates objects on the cluster, all named `ZZ_smoke_period_comparison_*`.

Runs the skill's path end to end, once per bucket form (reusable Set, Answer formula):

  1. auth;
  2. refuse to start if objects from an earlier run are still there (a re-run would
     otherwise make duplicates, and the asserts could read the wrong object);
  3. `ts recipe period-comparison` for Black Friday, `--years 2017-2019` by default
     (the years must hold data: a year with none gives no row);
  4. `ts tml import`, the reusable Set first. On an ambiguous failure (a client timeout,
     which `ts tml import` reports as "not retried"), wait, search by name, and retry
     only if the object is still missing — never a blind retry;
  5. export each Answer with `--fqn` and assert the round-trip facts of open item #7:
     the three measure formulas present, matched by `id`; the bucket absent from
     `search_query` and `answer_columns`; for the formula form, the bucket formula
     present; for the reusable-Set form, no `cohorts` key; `tables[].fqn` the Model;
  6. pin both Answers to a probe Liveboard and run `ts tml verify-render`, which proves
     each tile's query runs. It does not prove the chart draws: its blank-chart check is
     static (a chart with neither `axis_configs` nor `custom_chart_config`), and the
     generated chart always has `custom_chart_config`. Whether the chart draws is the
     user's UI check;
  7. delete everything it created (Liveboard, Answers, then the Set), plus any
     `ZZ_smoke_period_comparison_*` object a failed or timed-out import left behind
     (the start-of-run check proved none existed before), and confirm by search, unless
     `--no-cleanup`, which lists them instead.

It cannot see rows or SQL: no `ts` command returns a saved Answer's rows or SQL (BL-600),
so "one row per year", "no CROSS JOIN" and "the chart draws" are a UI check (passed on
2026-11-18, open items #4 and #7). Run with `--no-cleanup` to repeat that check, then
delete the objects it lists.

Usage:
    python3 tools/smoke-tests/smoke_ts_recipe_answer_period_comparison.py \\
        --ts-profile <profile> --model-guid <model-guid> --model-name "<Model name>" \\
        --date-column "Order Date" --measure-column "Amount" [--years 2017-2019] [--no-cleanup]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from _common import SmokeTestResult, run_ts, ts_auth_check  # noqa: E402

PREFIX = "ZZ_smoke_period_comparison_"
FORMS = ("reusable-set", "formula")
NAMES = {
    "reusable-set": {"answer": f"{PREFIX}set_answer", "bucket": f"{PREFIX}set"},
    "formula": {"answer": f"{PREFIX}formula_answer", "bucket": f"{PREFIX}bucket"},
}
LIVEBOARD = f"{PREFIX}liveboard"
MEASURE_IDS = (
    "formula_Average Black Friday Sales",
    "formula_Average Comparison Sales",
    "formula_Variance to Baseline",
)
# Words `ts tml import` / the client print when a create may or may not have landed.
AMBIGUOUS_MARKERS = ("not retried", "network error", "Timeout", "timed out")


def _fail(msg: str) -> None:
    # Explicit raise, not `assert`: `python -O` strips asserts and would pass silently.
    raise RuntimeError(msg)


def _ts(args: list[str], profile: str | None = None) -> subprocess.CompletedProcess:
    """Run `ts`; return the process whatever its exit code (run_ts raises on any)."""
    cmd = ["ts", *args] + (["--profile", profile] if profile else [])
    return subprocess.run(cmd, capture_output=True, text=True)


def _imported_guid(result: list | dict) -> str | None:
    items = result if isinstance(result, list) else [result]
    for item in items:
        resp = item.get("response", {})
        if resp.get("status", {}).get("status_code") not in ("OK", "WARNING"):
            continue
        objs = resp.get("object") or []
        guid = (objs[0].get("header", {}).get("id_guid") if objs else None) \
            or resp.get("header", {}).get("id_guid")
        if guid:
            return guid
    return None


# --- search by name (before any retry, and for cleanup) ---------------------

def _find_by_name(kind: str, name: str, profile: str, model_guid: str) -> list[str]:
    """GUIDs of every `kind` object named exactly `name` (case-insensitive)."""
    if kind == "SET":
        inv = run_ts(["sets", "inventory", "--model", model_guid], profile)
        guids = []
        for org in inv.get("orgs", []):
            for m in org.get("models", []):
                if m.get("discovery") != "COMPLETE":
                    _fail(f"Set discovery {m.get('discovery')} on the Model: an empty list "
                          "means unknown, not none — cannot tell whether the Set exists")
                guids += [s["guid"] for s in m.get("sets", [])
                          if s.get("name", "").lower() == name.lower()]
        return guids
    hits = run_ts(["metadata", "search", "--type", kind, "--name", name], profile)
    return [h["metadata_id"] for h in hits
            if (h.get("metadata_header", {}).get("name") or h.get("metadata_name", "")).lower()
            == name.lower()]


def _leftovers(profile: str, model_guid: str) -> dict[str, list[str]]:
    """GUIDs of every ANSWER, LIVEBOARD and Set whose name starts with PREFIX."""
    found = {}
    for kind in ("ANSWER", "LIVEBOARD"):
        # `_` is a LIKE wildcard, so the search can match more; keep true prefixes only.
        hits = run_ts(["metadata", "search", "--type", kind, "--name", f"{PREFIX}%"], profile)
        guids = [h["metadata_id"] for h in hits
                 if (h.get("metadata_header", {}).get("name") or h.get("metadata_name", ""))
                 .lower().startswith(PREFIX.lower())]
        if guids:
            found[kind] = guids
    sets = _find_by_name("SET", NAMES["reusable-set"]["bucket"], profile, model_guid)
    if sets:
        found["SET"] = sets
    return found


# --- import with search-before-retry ----------------------------------------

def _import(file: Path, kind: str, name: str, a, r: SmokeTestResult) -> str:
    """Import one file with --create-new; return the object's GUID.

    On an ambiguous failure, wait, search by name, and retry once only if the
    object is not there. A clear server-side rejection fails at once.
    """
    for attempt in (1, 2):
        proc = _ts(["tml", "import", "--file", str(file), "--policy", "ALL_OR_NONE",
                    "--create-new"], a.ts_profile)
        if proc.returncode == 0:
            guid = _imported_guid(json.loads(proc.stdout))
            if guid:
                return guid
            found = _find_by_name(kind, name, a.ts_profile, a.model_guid)
            if len(found) == 1:
                return found[0]
            _fail(f"import OK but no GUID in the response, and search found {found}")
        err = (proc.stderr or proc.stdout).strip()
        if not any(m in err for m in AMBIGUOUS_MARKERS):
            _fail(f"import rejected: {err[:600]}")
        r.info(f"import of {name} timed out (attempt {attempt}); waiting {a.retry_wait}s "
               "before searching by name")
        time.sleep(a.retry_wait)
        found = _find_by_name(kind, name, a.ts_profile, a.model_guid)
        if len(found) == 1:
            r.info(f"{name} was created on the server despite the timeout")
            return found[0]
        if len(found) > 1:
            _fail(f"{len(found)} objects named {name}: duplicates, clean up by hand")
        if attempt == 1:
            r.info(f"{name} not found after the wait; retrying once")
    _fail(f"{name}: timed out twice and is still not on the server")


# --- the steps --------------------------------------------------------------

def _generate(form: str, a, out_dir: Path) -> dict:
    names = NAMES[form]
    proc = _ts(["recipe", "period-comparison",
                "--model-name", a.model_name, "--model-guid", a.model_guid,
                "--date-column", a.date_column, "--measure-column", a.measure_column,
                "--event", "black-friday", "--years", a.years, "--bucket", form,
                "--name", names["answer"], "--set-name", names["bucket"],
                "-o", str(out_dir)])
    if proc.returncode == 2 and not proc.stdout.strip():
        _fail(f"usage error (exit 2, no JSON): {proc.stderr.strip()[:400]}")
    try:
        plan = json.loads(proc.stdout)
    except json.JSONDecodeError:
        _fail(f"exit {proc.returncode}, non-JSON stdout: {proc.stdout[:200]!r} "
              f"{proc.stderr.strip()[:300]}")
    if proc.returncode == 2:
        _fail(f"unexpected clash for Black Friday: {plan.get('clashes')}")
    if proc.returncode != 0:
        _fail(f"exit {proc.returncode}: {plan.get('error', plan)}")
    bounds = [int(y) for y in a.years.split("-")]
    want_years = list(range(bounds[0], bounds[-1] + 1))
    if [y["year"] for y in plan["years"]] != want_years:
        _fail(f"years {[y['year'] for y in plan['years']]}, expected {want_years}")
    if any(len(y["comparisons"]) != 6 for y in plan["years"]):
        _fail("expected 6 prior-week windows per year")
    want_files = 2 if form == "reusable-set" else 1
    if len(plan["files"]) != want_files:
        _fail(f"expected {want_files} file(s), got {plan['files']}")
    return plan


def _export_answer(guid: str, profile: str) -> dict:
    items = run_ts(["tml", "export", guid, "--fqn", "--parse"], profile)
    for item in items:
        if "answer" in (item.get("tml") or {}):
            return item["tml"]["answer"]
    _fail(f"export of {guid} has no answer document")


def _check_round_trip(form: str, answer: dict, a) -> None:
    bucket = NAMES[form]["bucket"]
    ids = {f.get("id") for f in answer.get("formulas", [])}
    missing = [i for i in MEASURE_IDS if i not in ids]
    if missing:
        _fail(f"measure formulas missing by id: {missing} (have {sorted(ids)})")
    if form == "formula" and f"formula_{bucket}" not in ids:
        _fail(f"bucket formula formula_{bucket} missing (have {sorted(ids)})")
    query = answer.get("search_query", "")
    if bucket.lower() in query.lower():
        _fail(f"bucket found in search_query: {query}")
    cols = [c.get("name", "") for c in answer.get("answer_columns", [])]
    if any(bucket.lower() == c.lower() for c in cols):
        _fail(f"bucket found in answer_columns: {cols}")
    if form == "reusable-set" and "cohorts" in answer:
        _fail(f"reusable-set Answer exported a cohorts key: {answer['cohorts']}")
    fqns = [t.get("fqn") for t in answer.get("tables", [])]
    if fqns != [a.model_guid]:
        _fail(f"tables[].fqn {fqns}, expected the Model GUID")


def _liveboard_tml(answer_files: list[Path]) -> tuple[str, list]:
    """Both Answers as tiles of one probe Liveboard, and the tiles' `tables[]` binding.

    Each tile embeds the generated Answer unchanged, so it binds the Model exactly as the
    saved Answer does: `tables[] = {id, name, fqn}`. That is the binding every probe
    Liveboard in open item #3 used, including the 300-window boards that rendered.
    Dumped as the generator dumps TML: no line wrapping, since a wrapped formula `expr`
    is invalid TML.
    """
    vizzes, tiles, bindings = [], [], []
    for i, path in enumerate(answer_files, start=1):
        answer = yaml.safe_load(path.read_text(encoding="utf-8"))["answer"]
        bindings.append(answer.get("tables", []))
        vizzes.append({"id": f"Viz_{i}", "answer": answer})
        tiles.append({"visualization_id": f"Viz_{i}", "x": 0, "y": (i - 1) * 8,
                      "height": 8, "width": 12})
    text = yaml.safe_dump({"liveboard": {"name": LIVEBOARD, "visualizations": vizzes,
                                         "layout": {"tiles": tiles}}},
                          sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=float("inf"))
    return text, bindings


def _verify_render(guid: str, profile: str, tiles: int) -> dict:
    proc = _ts(["tml", "verify-render", guid], profile)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        _fail(f"verify-render exit {proc.returncode}: {proc.stderr.strip()[:400]}")
    if not out.get("ok") or out.get("failing_tiles") or out.get("blank_chart_tiles"):
        _fail(f"verify-render: {json.dumps(out)[:800]}")
    if out.get("tiles_rendered") not in (None, tiles):
        _fail(f"verify-render rendered {out.get('tiles_rendered')} of {tiles} tiles")
    return out


def _to_remove(created: list[tuple[str, str, str]], a, r: SmokeTestResult) -> list:
    """Every object this run left: the ones it recorded, plus any prefixed object a failed
    or timed-out import created unrecorded. The start-of-run check proved none existed
    before, so every prefixed object found now is this run's."""
    items = list(created)
    known = {guid for _, _, guid in created}
    ok, left = r.step("search for unrecorded objects (name prefix)", _leftovers,
                      a.ts_profile, a.model_guid)
    for kind, guids in (left or {}).items():
        items += [(kind, "(unrecorded)", g) for g in guids if g not in known]
    return items


def _cleanup(items: list[tuple[str, str, str]], a, r: SmokeTestResult) -> None:
    """Delete in reverse dependency order: Liveboard, Answers, then the Set."""
    order = {"LIVEBOARD": 0, "ANSWER": 1, "SET": 2}
    for kind, name, guid in sorted(items, key=lambda c: order[c[0]]):
        del_type = "LOGICAL_COLUMN" if kind == "SET" else kind
        r.step(f"delete {kind} {name}", run_ts,
               ["metadata", "delete", guid, "--type", del_type, "--ignore-missing"],
               a.ts_profile)

    def confirm():
        left = _leftovers(a.ts_profile, a.model_guid)
        if left:
            _fail(f"still on the cluster: {left}")
    r.step("confirm nothing left (search by name)", confirm)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ts-profile", required=True)
    ap.add_argument("--model-guid", required=True)
    ap.add_argument("--model-name", required=True, help="The Model's exact name")
    ap.add_argument("--date-column", required=True, help='e.g. "Order Date"')
    ap.add_argument("--measure-column", required=True, help='e.g. "Amount"')
    ap.add_argument("--years", default="2017-2019",
                    help="Years inside the Model's data (default 2017-2019)")
    ap.add_argument("--retry-wait", type=int, default=180,
                    help="Seconds to wait after an import timeout before searching (default 180)")
    ap.add_argument("--no-cleanup", action="store_true",
                    help="Keep the created objects (for the UI check), listing them")
    a = ap.parse_args()

    print("=" * 60)
    print("Smoke test: ts-recipe-answer-period-comparison")
    print("=" * 60)
    r = SmokeTestResult()
    ok, _ = r.step("auth", ts_auth_check, a.ts_profile)
    if not ok:
        return r.summary()
    ok, left = r.step("no objects left from an earlier run", _leftovers,
                      a.ts_profile, a.model_guid)
    if not ok:
        return r.summary()
    if left:
        r.failures.append(f"objects from an earlier run: {left}. Delete them first.")
        return r.summary()

    tmp = Path(tempfile.mkdtemp(prefix="smoke-period-comparison-"))
    created: list[tuple[str, str, str]] = []
    try:
        _run(a, r, tmp, created)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        items = _to_remove(created, a, r)
        if a.no_cleanup:
            r.info("--no-cleanup: kept these objects (delete them after the UI check):")
            for kind, name, guid in items:
                r.info(f"  {kind:9} {name}  {guid}")
        else:
            _cleanup(items, a, r)
    return r.summary()


def _run(a, r: SmokeTestResult, tmp: Path, created: list) -> None:
    answers: dict[str, str] = {}
    answer_files: list[Path] = []
    for form in FORMS:
        names = NAMES[form]
        out_dir = tmp / form
        ok, plan = r.step(f"[{form}] generate", _generate, form, a, out_dir)
        if not ok:
            continue
        files = [Path(f) for f in plan["files"]]
        if form == "reusable-set":
            cohort = next(f for f in files if f.name.endswith(".cohort.tml"))
            ok, set_guid = r.step(f"[{form}] import the Set first", _import,
                                  cohort, "SET", names["bucket"], a, r)
            if not ok:
                continue
            created.append(("SET", names["bucket"], set_guid))
        answer_file = next(f for f in files if f.name.endswith(".answer.tml"))
        ok, guid = r.step(f"[{form}] import the Answer", _import,
                          answer_file, "ANSWER", names["answer"], a, r)
        if not ok:
            continue
        created.append(("ANSWER", names["answer"], guid))
        answers[form] = guid
        answer_files.append(answer_file)
        ok, exported = r.step(f"[{form}] export (--fqn)", _export_answer, guid, a.ts_profile)
        if ok:
            r.step(f"[{form}] round trip: formulas by id, bucket out of the search",
                   _check_round_trip, form, exported, a)

    if len(answers) != len(FORMS):
        r.info("skipping the render check: not every Answer imported")
        return
    lb_text, bindings = _liveboard_tml(answer_files)
    keys = sorted({k for tables in bindings for t in tables for k in t})
    r.info(f"tile binding: the generated Answers' tables[] unchanged, keys {keys}")
    lb_file = tmp / f"{LIVEBOARD}.liveboard.tml"
    lb_file.write_text(lb_text, encoding="utf-8")
    ok, lb_guid = r.step("import the probe Liveboard (both Answers)", _import,
                         lb_file, "LIVEBOARD", LIVEBOARD, a, r)
    if not ok:
        return
    created.append(("LIVEBOARD", LIVEBOARD, lb_guid))
    ok, out = r.step("verify-render: every tile's query runs", _verify_render,
                     lb_guid, a.ts_profile, len(answer_files))
    if ok:
        r.info(f"tiles rendered: {out.get('tiles_rendered')}")
    for form, guid in answers.items():
        r.info(f"{form}: Answer {NAMES[form]['answer']}  {guid}")


if __name__ == "__main__":
    sys.exit(main())
