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

Exit codes: 0 run completed (whatever the verdicts), 1 a scratch object could not be
confirmed deleted, 2 bad arguments or case files.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
import time

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


def classify_all(items: list[dict], cases: list[dict]) -> None:
    by_id = {c["id"]: c for c in cases}
    for it in items:
        case = by_id.get(it["id"], it)
        it.update({k: case[k] for k in ("source_formula", "role", "group_by", "known_divergence", "note")
                   if k in case})
        it["result"] = classify_case(case, it["oracle"], it.get("translation"),
                                     it.get("import_error"), it.get("actual"))


def _rel(p: pathlib.Path) -> str:
    rp = p.resolve()
    return str(rp.relative_to(REPO)) if rp.is_relative_to(REPO) else str(p)


def _write(run: dict, cases: list[dict], fixtures: dict, args, title: str) -> None:
    classify_all(run["cases"], cases)
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
        _write(run, cases, fixtures, args, title)
        return 0

    if args.translate_only:
        for c in cases:
            names = builders.object_names(fixtures[c["fixture"]]["name"], "OFFLINE")
            t = translate_case(c, fixtures[c["fixture"]], names["ts_table"])
            print(f"{c['id']:16} {t['status']:13} {c['source_formula']}  ->  {t.get('formula')}")
        return 0

    if not (args.profile and args.sf_profile):
        print("error: a live run needs --profile and --sf-profile", file=sys.stderr)
        return 2
    if len(fixtures) != 1:
        print("error: one fixture per run in this version", file=sys.stderr)
        return 2
    return live_run(args, cases, fixtures, title)


def live_run(args, cases: list[dict], fixtures: dict, title: str) -> int:
    from fidelity import live
    from ts_cli import __version__ as ts_cli_version

    fixture = next(iter(fixtures.values()))
    stamp = builders.run_stamp()
    names = builders.object_names(fixture["name"], stamp)
    fq_table = builders.fq(args.database, args.schema, names["warehouse_table"])
    t0 = time.monotonic()
    phases: dict[str, float] = {}
    meta = {"date": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "profile": args.profile, "connection": args.connection, "sf_profile": args.sf_profile,
            "warehouse_table": fq_table, "ts_table": names["ts_table"],
            "ts_model": names["ts_model"], "cases_file": _rel(args.cases),
            "cases_sha256": caselib.file_sha256(args.cases),
            "translator_version": f"ts-cli {ts_cli_version}", "phases": phases}
    items = [{"id": c["id"], "fixture": c["fixture"], "oracle": {}, "translation": None,
              "import_error": None, "actual": None} for c in cases]
    by_id = {it["id"]: it for it in items}
    run = {"run": meta, "cases": items}

    def lap(name: str, since: float) -> float:
        now = time.monotonic()
        phases[name] = round(now - since, 1)
        return now

    validator = live.ts_validator(args.profile)
    meta["orphans"] = live.find_orphans(validator)
    if meta["orphans"]:
        live.log(f"startup sweep: {len(meta['orphans'])} pre-existing ZZ_FIDELITY_* object(s) "
                 "(reported, not touched)")
    wh = live.Warehouse(args.sf_profile)
    created_ts: list[tuple[str, str]] = []
    table_created = False
    cleanup: dict = {}
    try:
        t = time.monotonic()
        for s in builders.session_sql(fixture):
            wh.execute(s)
        live.log(f"warehouse: creating {fq_table}")
        wh.execute(builders.create_table_sql(fixture, fq_table))
        table_created = True
        wh.execute(builders.insert_rows_sql(fixture, fq_table))
        t = lap("load", t)

        for c in cases:
            by_id[c["id"]]["oracle"] = live.run_oracle(wh, c, fixture, fq_table)
        t = lap("oracle", t)

        for c in cases:
            by_id[c["id"]]["translation"] = translate_case(c, fixture, names["ts_table"])
        t = lap("translate", t)

        live.log(f"ThoughtSpot: importing Table {names['ts_table']}")
        tdoc = builders.table_tml(fixture, names, args.connection, args.database, args.schema)
        created_ts.append((names["ts_table"], None))
        tguid, err = live.import_object(validator, tdoc, names["ts_table"])
        if err:
            raise RuntimeError(f"Table import failed: {err}")
        created_ts[-1] = (names["ts_table"], tguid)

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
        if err:
            raise RuntimeError(f"Model import failed: {err}")
        created_ts[0] = (names["ts_model"], mguid)
        t = lap("ts_import", t)

        for n, c in enumerate([c for c in cases if c["id"] in good], 1):
            tr = by_id[c["id"]]["translation"]
            key_col = caselib.key_column(c, fixture)
            live.log(f"[{n}/{len(good)}] {c['id']}")
            by_id[c["id"]]["actual"] = live.fetch_case(
                validator, names["ts_model"], mguid, builders.formula_name(c["id"]), key_col,
                c["role"], tr.get("agentql_wrapper"), builders.key_values(c, fixture))
        lap("agentql", t)
    except Exception as exc:
        meta["aborted"] = f"{type(exc).__name__}: {exc}"
        live.log(f"RUN ABORTED: {meta['aborted']}")
    finally:
        t = time.monotonic()
        cleanup = live.teardown_ts(validator, created_ts) if created_ts else \
            {"ts_confirmed_absent": True, "remaining": []}
        if table_created:
            try:
                wh.execute(f"DROP TABLE IF EXISTS {fq_table}")
            except Exception as exc:
                live.log(f"warehouse DROP failed: {exc}")
        try:
            gone = not wh.table_exists(args.database, args.schema, names["warehouse_table"])
        except Exception as exc:
            gone = False
            live.log(f"warehouse absence check failed: {exc}")
        if not gone:
            cleanup.setdefault("remaining", []).append(fq_table)
            live.log(f"CLEANUP FAILED — warehouse table still present: {fq_table}")
        cleanup["warehouse_confirmed_absent"] = gone
        wh.close()
        lap("teardown", t)
        meta["cleanup"] = cleanup
        meta["runtime_s"] = round(time.monotonic() - t0, 1)

    if args.fill_expected:
        exp = {it["id"]: {"key_column": caselib.key_column(c, fixture),
                          "values": it["oracle"].get("values")}
               for c, it in zip(cases, items)}
        args.cases.write_text(caselib.write_expected(cases, exp))
        cases = caselib.load_cases(args.cases)
    drift = [c["id"] for c in cases if c.get("expected") and
             c["expected"].get("values") != by_id[c["id"]]["oracle"].get("values")]
    meta["oracle_drift"] = drift
    _write(run, cases, fixtures, args, title)
    print(json.dumps(meta["counts"]), file=sys.stderr)
    return 0 if not cleanup.get("remaining") else 1


if __name__ == "__main__":
    sys.exit(main())
