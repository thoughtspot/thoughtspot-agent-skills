#!/usr/bin/env python3
"""Formula fidelity harness — does a translated formula return the RIGHT value?

``ts formula translate --validate execute`` proves a formula imports and returns *some*
rows. This proves it returns the *same* rows as the source system, case by case:

1. load the fixture table into the warehouse (scratch, run-stamped name)
2. oracle: run each source formula as a warehouse SELECT over the fixture → expected
3. translate each formula (the ``ts formula translate`` engine, ``--columns`` context)
4. register the Table in ThoughtSpot, VALIDATE_ONLY the Model (bisecting failures), import
   one scratch Model, query each formula with AgentQL (one formula per query)
5. compare per key, classify, and write a run JSON plus a markdown report that leads with
   silent wrong answers
6. teardown in ``finally``: Model, Table (confirmed absent by GUID and name), warehouse
   table (confirmed by SHOW TABLES)

Usage (see README.md):

    python -I tools/formula-fidelity/run.py --cases tools/formula-fidelity/cases/snowflake/m0.jsonl \\
        --profile se-thoughtspot --sf-profile "ThoughtSpot Partner (AP)" --connection APJ_TAB \\
        --report docs/reviews/2026-10-06-fidelity-m0-snowflake.md

    # offline: translate only, no cluster, no warehouse
    python -I tools/formula-fidelity/run.py --cases … --translate-only

    # re-classify a stored run against the current case file (e.g. new known_divergence tags)
    python -I tools/formula-fidelity/run.py --cases … --rebuild runs/<file>.json --report …

Exit codes: 0 run completed and cleaned up (whatever the verdicts), 1 completed but a
scratch object could not be confirmed deleted, 2 bad arguments or case files, 3 the run
aborted (even if cleanup succeeded). An interrupt or a client SystemExit is re-raised after
teardown and after the run JSON and report are written.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
import time
from typing import Optional

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (HERE, REPO / "tools" / "ts-cli"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fidelity import builders, cases as caselib  # noqa: E402
from fidelity.compare import classify_case, counts  # noqa: E402
from fidelity.report import build_report  # noqa: E402


def _args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cases", required=True, type=pathlib.Path)
    ap.add_argument("--profile", help="ThoughtSpot profile (ts profiles)")
    ap.add_argument("--sf-profile", help="Snowflake profile (python method)")
    ap.add_argument("--dbx-profile", help="Databricks profile with a SQL warehouse "
                    "(/ts-profile-databricks); needed when the fixture's warehouse is databricks")
    ap.add_argument("--dbx-cli-profile", help="opt-in: authenticate with this named "
                    "~/.databrickscfg profile instead of the Databricks profile's env var / OS "
                    "credential store (that file holds a plaintext secret; discouraged)")
    ap.add_argument("--connection", default="APJ_TAB", help="ThoughtSpot connection name")
    ap.add_argument("--database", default="AGENT_SKILLS")
    ap.add_argument("--schema", default="PUBLIC")
    ap.add_argument("--out", type=pathlib.Path, help="run JSON (default runs/<date>-<cases>.json)")
    ap.add_argument("--report", type=pathlib.Path, help="markdown report path")
    ap.add_argument("--title", default=None)
    ap.add_argument("--fill-expected", action="store_true",
                    help="write the oracle's values back into the case file's `expected`")
    ap.add_argument("--translate-only", action="store_true", help="offline: translate and print")
    ap.add_argument("--rebuild", type=pathlib.Path, help="re-classify a stored run JSON")
    return ap.parse_args(argv)


def translate_case(case: dict, fixture: dict, ts_table: str) -> dict:
    from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
    from ts_cli.formula_translate.engine import translate

    ctx = ColumnContext(parse_columns_json(json.dumps(builders.column_context(fixture, ts_table))),
                        level=1)
    try:
        r = translate(case["source_formula"], case["dialect"], ctx,
                      name=builders.formula_name(case["id"]))
    except Exception as exc:  # the engine raises only on empty input; record, never crash
        return {"status": "NEEDS_REVIEW", "formula": None, "notes": [f"{type(exc).__name__}: {exc}"]}
    keep = ("status", "classification", "formula", "role", "agentql_wrapper", "traps", "notes",
            "unresolved")
    return {k: r.get(k) for k in keep}


def classify_all(items: list[dict], cases: list[dict], aborted: Optional[str] = None) -> None:
    from fidelity.compare import RUN_FAILED

    by_id = {c["id"]: c for c in cases}
    for it in items:
        if aborted and not (it.get("oracle") or {}).get("sql"):
            case = by_id.get(it["id"], it)
            it.update({k: case[k] for k in ("source_formula", "role", "group_by",
                                            "known_divergence", "note") if k in case})
            it["result"] = {"id": it["id"], "verdict": RUN_FAILED, "rows": [],
                            "mismatch_kinds": [], "silent_wrong": False, "warned": False,
                            "stale_divergence": False,
                            "translation_status": (it.get("translation") or {}).get("status"),
                            "detail": f"not run — the run aborted ({aborted})"}
            continue
        case = by_id.get(it["id"], it)
        it.update({k: case[k] for k in ("source_formula", "role", "group_by", "known_divergence", "note")
                   if k in case})
        it["result"] = classify_case(case, it["oracle"], it.get("translation"),
                                     it.get("import_error"), it.get("actual"))


def _rel(p: pathlib.Path) -> str:
    # A path outside the repo is recorded by NAME only: run records are committed to a
    # public repo, and an absolute path carries the operator's home directory / user
    # name (scratch dirs encode it). The file's identity is its sha256, recorded beside.
    rp = p.resolve()
    return str(rp.relative_to(REPO)) if rp.is_relative_to(REPO) else f"<outside repo>/{p.name}"


def _write(run: dict, cases: list[dict], fixtures: dict, args, title: str) -> None:
    classify_all(run["cases"], cases, run["run"].get("aborted"))
    run["run"]["counts"] = counts([it["result"] for it in run["cases"]])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run, indent=1, ensure_ascii=False, default=str) + "\n")
    print(f"run JSON: {args.out}", file=sys.stderr)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(build_report(run, fixtures, title))
        print(f"report:   {args.report}", file=sys.stderr)


def main(argv=None) -> int:
    args = _args(argv)
    try:
        cases = caselib.load_cases(args.cases)
        fixtures = caselib.fixtures_for(cases, args.cases.parent)
    except caselib.CaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    title = args.title or f"Formula fidelity: {args.cases.parent.name}/{args.cases.name}"
    today = _dt.date.today().isoformat()
    args.out = args.out or HERE / "runs" / f"{today}-{args.cases.parent.name}-{args.cases.stem}.json"

    if args.rebuild:
        run = json.loads(args.rebuild.read_text())
        run["run"]["rebuild"] = {
            "date": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "cases_sha256": caselib.file_sha256(args.cases), "from": _rel(args.rebuild)}
        _write(run, cases, fixtures, args, title)
        return 0

    if args.translate_only:
        for c in cases:
            names = builders.object_names(fixtures[c["fixture"]]["name"], "OFFLINE")
            t = translate_case(c, fixtures[c["fixture"]], names["ts_table"])
            print(f"{c['id']:16} {t['status']:13} {c['source_formula']}  ->  {t.get('formula')}")
        return 0

    try:
        builders.check_identifier(args.database, "--database")
        builders.check_identifier(args.schema, "--schema")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if len(fixtures) != 1:
        print("error: one fixture per run in this version", file=sys.stderr)
        return 2
    wh_kind = builders.warehouse_of(next(iter(fixtures.values())))
    wh_profile = args.dbx_profile if wh_kind == "databricks" else args.sf_profile
    if not (args.profile and wh_profile):
        flag = "--dbx-profile" if wh_kind == "databricks" else "--sf-profile"
        print(f"error: a live run over a {wh_kind} fixture needs --profile and {flag}",
              file=sys.stderr)
        return 2
    return live_run(args, cases, fixtures, title)


EXIT_OK, EXIT_LEFTOVERS, EXIT_USAGE, EXIT_ABORTED = 0, 1, 2, 3


class Deps:
    """The live seams, injectable so tests can drive ``live_run`` with fakes."""

    def __init__(self, validator=None, warehouse=None, translate=None, now_ms=None, oracle=None):
        from fidelity import live

        self.live = live
        self.validator = validator or (lambda profile: live.ts_validator(profile))
        # (warehouse kind, profile) -> a session object. Default: Snowflake (M0, M1) or the
        # Databricks SQL warehouse (M2), chosen by the fixture's ``warehouse``.
        self.warehouse = warehouse or (
            lambda kind, profile, cli_profile=None: live.DatabricksWarehouse(profile, cli_profile)
            if kind == "databricks" else live.Warehouse(profile))
        self.translate = translate or translate_case
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        # (wh, case, fixture, fq_table) -> {"values": …}. Default: the warehouse runs the
        # source formula (M0). M1's literal oracle reads the value stored in the corpus.
        self.oracle = oracle or live.run_oracle


def _git_head() -> dict:
    """The commit the run's code came from, and whether the tree had local changes — so a
    run is attributable to code, not to a version string (review of #574)."""
    import subprocess

    here = pathlib.Path(__file__).resolve().parent
    try:
        sha = subprocess.run(["git", "-C", str(here), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip() or None
        dirty = bool(subprocess.run(["git", "-C", str(here), "status", "--porcelain",
                                     "--untracked-files=no"], capture_output=True, text=True,
                                    timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return {"sha": None, "dirty": None}
    return {"sha": sha, "dirty": dirty}


def live_run(args, cases: list[dict], fixtures: dict, title: str, deps: "Deps" = None) -> int:
    """One live run. Outputs (run JSON, report) are ALWAYS written, in ``finally``.

    Exit: 0 completed and clean; 1 completed but a scratch object could not be confirmed
    gone; 3 aborted (whatever the cleanup did). SystemExit / KeyboardInterrupt are
    re-raised after teardown and writing — the client raises SystemExit on auth failure.
    """
    deps = deps or Deps()
    live = deps.live
    try:
        from ts_cli import __version__ as ts_cli_version
    except ImportError:  # pragma: no cover
        ts_cli_version = "unknown"

    fixture = next(iter(fixtures.values()))
    wh_kind = builders.warehouse_of(fixture)
    wh_profile = getattr(args, "dbx_profile", None) if wh_kind == "databricks" else args.sf_profile
    stamp = builders.run_stamp()
    names = builders.object_names(fixture["name"], stamp)
    fq_table = builders.fq(args.database, args.schema, names["warehouse_table"], wh_kind)
    run_start_ms = deps.now_ms()
    t0 = time.monotonic()
    phases: dict[str, float] = {}
    meta = {"date": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "profile": args.profile, "connection": args.connection, "sf_profile": args.sf_profile,
            "warehouse": wh_kind, "dbx_profile": getattr(args, "dbx_profile", None),
            "warehouse_table": fq_table, "ts_table": names["ts_table"],
            "ts_model": names["ts_model"], "run_start_ms": run_start_ms,
            "cases_file": _rel(args.cases), "cases_sha256": caselib.file_sha256(args.cases),
            "translator_version": f"ts-cli {ts_cli_version}", "git": _git_head(),
            "phases": phases}
    items = [{"id": c["id"], "fixture": c["fixture"], "oracle": {}, "translation": None,
              "import_error": None, "actual": None} for c in cases]
    by_id = {it["id"]: it for it in items}
    run = {"run": meta, "cases": items}

    def lap(name: str, since: float) -> float:
        now = time.monotonic()
        phases[name] = round(now - since, 1)
        return now

    validator = wh = None
    created_ts: list[tuple[str, Optional[str]]] = []
    table_created = False
    # A CREATE that raised (a timeout, a dropped connection) may still have created the table.
    # It is reported, never dropped: the run cannot prove it made it.
    create_unconfirmed: list[dict] = []
    reraise: Optional[BaseException] = None
    try:
        validator = deps.validator(args.profile)
        meta["orphans"] = live.find_orphans(validator)
        cli_profile = getattr(args, "dbx_cli_profile", None)
        wh = deps.warehouse(wh_kind, wh_profile, cli_profile) if cli_profile \
            else deps.warehouse(wh_kind, wh_profile)
        meta["warehouse_auth"] = getattr(wh, "auth_source", None)
        meta["warehouse_orphans"] = live.find_warehouse_orphans(wh, args.database, args.schema)
        n_orph = len(meta["orphans"]) + len(meta["warehouse_orphans"])
        if n_orph:
            live.log(f"startup sweep: {n_orph} pre-existing ZZ_FIDELITY_* object(s) "
                     "(reported, not touched)")
        t = time.monotonic()
        for s in builders.session_sql(fixture):
            wh.execute(s)
        # What the session actually runs under, read back after setting it (run header).
        meta["session"] = {}
        for k, q in builders.session_readback_sql(fixture):
            try:
                meta["session"][k] = [list(map(str, r)) for r in wh.execute(q)]
            except Exception as exc:  # noqa: BLE001 — a readback failure is recorded, not fatal
                meta["session"][k] = f"readback failed: {type(exc).__name__}: {exc}"
        live.log(f"warehouse: creating {fq_table}")
        try:
            wh.execute(builders.create_table_sql(fixture, fq_table))
        except BaseException:
            create_unconfirmed.extend(_check_after_failed_create(
                wh, args.database, args.schema, names["warehouse_table"], fq_table, live))
            raise
        table_created = True
        wh.execute(builders.insert_rows_sql(fixture, fq_table))
        t = lap("load", t)

        for c in cases:
            by_id[c["id"]]["oracle"] = deps.oracle(wh, c, fixture, fq_table)
        t = lap("oracle", t)

        for c in cases:
            by_id[c["id"]]["translation"] = deps.translate(c, fixture, names["ts_table"])
        t = lap("translate", t)

        live.log(f"ThoughtSpot: importing Table {names['ts_table']}")
        tdoc = builders.table_tml(fixture, names, args.connection, args.database, args.schema)
        created_ts.append((names["ts_table"], None))
        tguid, err = live.import_object(validator, tdoc, names["ts_table"])
        if tguid:
            created_ts[-1] = (names["ts_table"], tguid)
        if err:
            raise RuntimeError(f"Table import failed: {err}")

        ok = [c for c in cases if by_id[c["id"]]["translation"]["status"] in
              ("TRANSLATED", "APPROXIMATED")]
        entries = {c["id"]: (builders.formula_name(c["id"]),
                             by_id[c["id"]]["translation"]["formula"],
                             by_id[c["id"]]["translation"]["role"]) for c in ok}

        def validate(ids):
            doc = builders.model_tml(fixture, names, [entries[i] for i in ids])
            return validator.validate_only(doc)

        ids = [c["id"] for c in ok]
        live.log(f"ThoughtSpot: VALIDATE_ONLY Model with {len(ids)} formulas")
        failures = live.bisect_failures(ids, validate)
        for i, e in failures.items():
            by_id[i]["import_error"] = e
        good = [i for i in ids if i not in failures]
        mdoc = builders.model_tml(fixture, names, [entries[i] for i in good])
        live.log(f"ThoughtSpot: importing Model {names['ts_model']} "
                 f"({len(good)} formulas, {len(failures)} rejected)")
        created_ts.insert(0, (names["ts_model"], None))
        mguid, err = live.import_object(validator, mdoc, names["ts_model"])
        if mguid:
            created_ts[0] = (names["ts_model"], mguid)
        if err:
            raise RuntimeError(f"Model import failed: {err}")
        t = lap("ts_import", t)

        for n, c in enumerate([c for c in cases if c["id"] in good], 1):
            tr = by_id[c["id"]]["translation"]
            key_col = caselib.key_column(c, fixture)
            live.log(f"[{n}/{len(good)}] {c['id']}")
            by_id[c["id"]]["actual"] = live.fetch_case(
                validator, names["ts_model"], mguid, builders.formula_name(c["id"]), key_col,
                c["role"], tr.get("agentql_wrapper"), builders.key_values(c, fixture))
        lap("agentql", t)
    except BaseException as exc:  # noqa: BLE001 — recorded, cleaned up, written, re-raised
        meta["aborted"] = f"{type(exc).__name__}: {exc}"
        live.log(f"RUN ABORTED: {meta['aborted']}")
        if not isinstance(exc, Exception):
            reraise = exc
    finally:
        t = time.monotonic()
        cleanup: dict = {"ts_confirmed_absent": True, "remaining": [], "not_owned": [],
                         "errors": []}
        # 1. ThoughtSpot — its own block, so a failure here never skips the warehouse.
        if created_ts:
            try:
                if validator is None:
                    raise RuntimeError("no ThoughtSpot client")
                res = live.teardown_ts(validator, created_ts, run_start_ms)
                intr = res.pop("interrupted", None)
                cleanup.update(res)
                if intr is not None and reraise is None:
                    reraise = intr
            except BaseException as exc:  # noqa: BLE001
                cleanup["ts_confirmed_absent"] = False
                cleanup["errors"].append(f"ThoughtSpot teardown: {type(exc).__name__}: {exc}")
                cleanup["remaining"].extend({"name": n, "guid": g, "unconfirmed": True}
                                            for n, g in created_ts)
                if not isinstance(exc, Exception) and reraise is None:
                    reraise = exc
        # 2. Warehouse — separately guarded.
        gone = True
        if table_created:
            try:
                wh.execute(f"DROP TABLE IF EXISTS {fq_table}")
                gone = not wh.table_exists(args.database, args.schema, names["warehouse_table"])
            except BaseException as exc:  # noqa: BLE001
                gone = False
                cleanup["errors"].append(f"warehouse teardown: {type(exc).__name__}: {exc}")
                if not isinstance(exc, Exception) and reraise is None:
                    reraise = exc
            if not gone:
                cleanup["remaining"].append({"name": fq_table, "guid": None, "warehouse": True})
                live.log(f"CLEANUP NOT CONFIRMED — warehouse table may remain: {fq_table}")
        if create_unconfirmed:
            gone = False
            cleanup["remaining"].extend(create_unconfirmed)
        cleanup["warehouse_confirmed_absent"] = gone
        if wh is not None:
            try:
                wh.close()
            except BaseException:  # noqa: BLE001
                pass
        lap("teardown", t)
        meta["cleanup"] = cleanup
        meta["runtime_s"] = round(time.monotonic() - t0, 1)
        # 3. Outputs — always written, even on an abort.
        try:
            cases = _finish_outputs(args, run, cases, fixtures, fixture, by_id, title)
        except BaseException as exc:  # noqa: BLE001
            live.log(f"writing outputs failed: {type(exc).__name__}: {exc}")
            if reraise is None:
                reraise = exc
    if reraise is not None:
        raise reraise
    if meta.get("aborted"):
        return EXIT_ABORTED
    return EXIT_LEFTOVERS if meta["cleanup"]["remaining"] else EXIT_OK


def _check_after_failed_create(wh, database: str, schema: str, table: str, fq_table: str,
                               live) -> list[dict]:
    """After CREATE TABLE raised: is the table there anyway? If so (or if the check itself
    fails), report it as possibly this run's — never drop it. Applies to every warehouse."""
    try:
        present = wh.table_exists(database, schema, table)
    except BaseException as exc:  # noqa: BLE001 — unknown is reported, not assumed absent
        live.log(f"CREATE failed and the existence check failed too ({type(exc).__name__}); "
                 f"check for {fq_table} by hand")
        return [{"name": fq_table, "guid": None, "warehouse": True,
                 "note": "CREATE raised; existence unknown — possibly ours, not dropped"}]
    if not present:
        return []
    live.log(f"CREATE raised but {fq_table} exists — possibly this run's, NOT dropped")
    return [{"name": fq_table, "guid": None, "warehouse": True,
             "note": "CREATE raised but the table exists — possibly ours, not dropped"}]


def _finish_outputs(args, run, cases, fixtures, fixture, by_id, title):
    meta = run["run"]
    # drift is computed against the case file AS IT WAS, before any write-back
    meta["oracle_drift"] = [c["id"] for c in cases if c.get("expected")
                            and (by_id[c["id"]]["oracle"] or {}).get("values")
                            and c["expected"].get("values") != by_id[c["id"]]["oracle"]["values"]]
    if args.fill_expected:
        if meta.get("aborted"):
            live_log("--fill-expected skipped: the run aborted")
            meta["fill_expected"] = "skipped (aborted)"
        else:
            exp = {c["id"]: {"key_column": caselib.key_column(c, fixture),
                             "values": by_id[c["id"]]["oracle"]["values"]}
                   for c in cases if (by_id[c["id"]]["oracle"] or {}).get("values")}
            args.cases.write_text(caselib.write_expected(cases, exp))
            meta["fill_expected"] = f"wrote {len(exp)} case(s)"
            meta["cases_sha256_after_fill"] = caselib.file_sha256(args.cases)
            cases = caselib.load_cases(args.cases)
    _write(run, cases, fixtures, args, title)
    if "counts" in meta:
        print(json.dumps(meta["counts"]), file=sys.stderr)
    return cases


def live_log(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
