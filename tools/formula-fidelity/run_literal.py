#!/usr/bin/env python3
"""Formula fidelity M1: spreadsheet cases whose oracle is the value stored in the corpus.

Third-party corpora (LibreOffice ``.fods``, Apache POI ``.xls``/``.xlsx``) live in a data dir
OUTSIDE the repo (``--data-dir`` or ``$FORMULA_FIDELITY_DATA``; see README "M1"). The repo
holds only the manifest (ids + file + sha256 + locator), the redacted results, and this code.

Subcommands, in order:

    candidates  every formula cell in the corpus -> eligible / skipped, translated offline
                (writes <data-dir>/extracted/candidates.jsonl — full content, outside the repo)
    select      choose the M1 set from the candidates + the `formulas` cross-check
                (writes the committed manifest and aggregate selection counts)
    run         live: materialise the manifest, load the input fixture, import, query, compare
                (full run JSON -> <data-dir>/runs/; redacted results + report -> the repo)
    rebuild     re-classify a stored full run JSON (no queries)

The cross-check between ``candidates`` and ``select`` is ``crosscheck_formulas.py``, run in a
throwaway uv env (the ``formulas`` library is EUPL: a tool, never imported by ts_cli).
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import pathlib
import sys
from typing import Optional

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (HERE, REPO / "tools" / "ts-cli"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fidelity import builders, literal, redact, sources  # noqa: E402

LO_CATEGORIES = ("date_time", "text", "mathematical", "logical")
POI_FILES = ("poi/FormulaEvalTestData_Copy.xlsx",)
POI_SHEETS = ("EverythingTests",)


def _log(msg: str) -> None:
    print(f"  {msg}", file=sys.stderr, flush=True)


def translate_literal_case(case: dict, fixture: dict, ts_table: str) -> dict:
    from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
    from ts_cli.formula_translate.engine import translate

    ctx = ColumnContext(parse_columns_json(json.dumps(
        literal.column_context(case, fixture, ts_table))), level=1)
    try:
        r = translate(case["source_formula"], "excel", ctx, name=builders.formula_name(case["id"]))
    except Exception as exc:  # recorded, never a crash
        return {"status": "NEEDS_REVIEW", "formula": None, "notes": [f"{type(exc).__name__}: {exc}"]}
    keep = ("status", "classification", "formula", "role", "agentql_wrapper", "traps", "notes",
            "unresolved")
    return {k: r.get(k) for k in keep}


# =====================================================================================
# candidates
# =====================================================================================

def _lo_entries(data_dir: pathlib.Path, cache: literal.SourceCache):
    for cat in LO_CATEGORIES:
        for path in sorted((data_dir / "libreoffice" / cat).glob("*.fods")):
            rel = path.relative_to(data_dir).as_posix()
            sheets = cache.sheets(rel, None)
            sha = literal.sha256(path)
            for sname, sheet in sheets.items():
                for row in sources.lo_case_rows(sheet):
                    yield {"id": f"lo-{cat}-{path.stem}-{sname.lower()}-r{row}",
                           "source": "libreoffice", "path": rel, "sha256": sha,
                           "locator": {"sheet": sname, "row": row}, "category": cat}


def _poi_entries(data_dir: pathlib.Path, cache: literal.SourceCache):
    for rel in POI_FILES:
        path = data_dir / rel
        sheets = cache.sheets(rel, None)
        sha = literal.sha256(path)
        for sname in POI_SHEETS:
            for ref, cell in sorted(sheets.get(sname, {}).items(),
                                    key=lambda kv: (int("".join(filter(str.isdigit, kv[0]))), kv[0])):
                if cell.formula:
                    yield {"id": f"poi-{path.stem.lower()}-{sname.lower()}-{ref.lower()}",
                           "source": "poi", "path": rel, "sha256": sha,
                           "locator": {"sheet": sname, "cell": ref}, "category": "excel-cached"}


def cmd_candidates(args) -> int:
    data_dir = literal.resolve_data_dir(args.data_dir, REPO)
    cache = literal.SourceCache(data_dir)
    from ts_cli.excel.map_index import EXCEL_ROWS

    out_dir = data_dir / "extracted"
    out_dir.mkdir(exist_ok=True)
    skips = collections.Counter()
    stats = collections.Counter()
    rows = []
    fixture_stub = {"columns": []}
    for gen in (_lo_entries(data_dir, cache), _poi_entries(data_dir, cache)):
        for e in gen:
            stats[f"{e['source']}:formula_cells"] += 1
            raw = literal.extract(e, cache)
            if "skip" in raw:
                skips[f"{e['source']}:{raw['skip']}"] += 1
                continue
            unknown = [f for f in raw["functions"] if f not in EXCEL_ROWS]
            if unknown:
                skips[f"{e['source']}:function not in the Excel map"] += 1
                continue
            stats[f"{e['source']}:eligible"] += 1
            case = {"id": e["id"], "source_formula": raw["formula"],
                    "inputs": {i["letter"]: f"X_{i['letter']}" for i in raw["inputs"]}}
            fixture_stub["columns"] = [{"name": f"X_{i['letter']}",
                                        "ts_type": literal._SF_TYPES.get(i["kind"], ("", "DOUBLE"))[1]}
                                       for i in raw["inputs"]]
            tr = translate_literal_case(case, fixture_stub, "T")
            stats[f"{e['source']}:{tr['status']}"] += 1
            rows.append({**e, "functions": raw["functions"], "flags": raw["flags"],
                         "formula": raw["formula"], "inputs": raw["inputs"],
                         "tokens": raw["tokens"], "letters": raw["letters"],
                         "expected": raw["expected"], "tolerance": raw["tolerance"],
                         "translation": tr})
    (out_dir / "candidates.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    summary = {"stats": dict(sorted(stats.items())), "skips": dict(skips.most_common())}
    (out_dir / "candidates-summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


# =====================================================================================
# select
# =====================================================================================

def _rank(case_id: str) -> str:
    return hashlib.sha256(case_id.encode()).hexdigest()


def choose(rows: list[dict], crosscheck: dict[str, str], n_lo: int, n_poi: int,
           per_function: int = 6, max_errors: int = 12, max_blank: int = 10) -> list[dict]:
    """Deterministic, diverse pick: hash order, a cap per leading function, a cap on
    error-expected and blank-input cases, only cases the translator handled."""
    picked: list[dict] = []
    for source, n in (("libreoffice", n_lo), ("poi", n_poi)):
        per_fn: collections.Counter = collections.Counter()
        errs = blanks = 0
        pool = sorted((r for r in rows if r["source"] == source
                       and r["translation"]["status"] in ("TRANSLATED", "APPROXIMATED")),
                      key=lambda r: _rank(r["id"]))
        chosen = []
        for r in pool:
            if len(chosen) >= n:
                break
            lead = (r["functions"] or ["(operators)"])[0]
            if per_fn[lead] >= per_function:
                continue
            if "error-expected" in r["flags"]:
                if errs >= max_errors:
                    continue
                errs += 1
            if "blank-input" in r["flags"]:
                if blanks >= max_blank:
                    continue
                blanks += 1
            per_fn[lead] += 1
            chosen.append({**r, "crosscheck": crosscheck.get(r["id"], "unavailable")})
        picked += chosen
    return picked


def cmd_select(args) -> int:
    data_dir = literal.resolve_data_dir(args.data_dir, REPO)
    rows = [json.loads(line) for line in
            (data_dir / "extracted" / "candidates.jsonl").read_text().splitlines() if line]
    cc_path = data_dir / "extracted" / "crosscheck.json"
    cc = json.loads(cc_path.read_text()) if cc_path.exists() else {}
    status = {k: v["status"] for k, v in cc.items()}
    picked = choose(rows, status, args.n_lo, args.n_poi, args.per_function)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text("".join(literal.manifest_line(r) + "\n" for r in picked))
    summ = json.loads((data_dir / "extracted" / "candidates-summary.json").read_text())
    sel = {"date": _dt.date.today().isoformat(),
           "selected": dict(collections.Counter(r["source"] for r in picked)),
           "crosscheck": dict(collections.Counter(f"{r['source']}:{r['crosscheck']}" for r in picked)),
           "flags": dict(collections.Counter(f for r in picked for f in r["flags"])),
           "candidates": summ["stats"], "skipped": summ["skips"]}
    args.selection.write_text(json.dumps(sel, indent=1, sort_keys=True) + "\n")
    print(json.dumps(sel, indent=1, sort_keys=True))
    return 0


# =====================================================================================
# run / rebuild
# =====================================================================================

def _load(args):
    data_dir = literal.resolve_data_dir(args.data_dir, REPO)
    entries = literal.parse_manifest(args.manifest.read_text(), str(args.manifest))
    cache = literal.SourceCache(data_dir)
    cases, fixture, broken = literal.materialise(entries, cache)
    if broken:
        raise literal.DataError(f"{len(broken)} manifest entr(ies) no longer extract: "
                                + ", ".join(b["id"] for b in broken[:5]))
    return data_dir, entries, cases, fixture


def _outputs(args, data_dir, entries, cases, fixture, full_run: dict) -> None:
    from fidelity.compare import counts
    import run as m0

    m0.classify_all(full_run["cases"], cases, full_run["run"].get("aborted"))
    by_case = {c["id"]: c for c in cases}
    for it in full_run["cases"]:
        res = literal.classify_error_expected(by_case[it["id"]], it)
        if res is not None:
            it["result"] = res
    full_run["run"]["counts"] = counts([it["result"] for it in full_run["cases"]])
    disputed = [e for e in entries if e.get("crosscheck") == "disputed"]
    red = redact.redact_run(full_run, entries, disputed)
    leaks = redact.leaks_against_corpus(json.dumps(red), cases)
    if leaks:
        raise SystemExit(f"refusing to write: redacted results contain corpus text {leaks[:3]}")
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(red, indent=1, sort_keys=False) + "\n")
    _log(f"redacted results: {args.results}")
    if args.report:
        text = redact.build_report(red, args.title)
        leaks = redact.leaks_against_corpus(text, cases)
        if leaks:
            raise SystemExit(f"refusing to write report: corpus text {leaks[:3]}")
        prior = args.report.read_text() if args.report.exists() else ""
        args.report.write_text(redact.merge_report(prior, text))
        _log(f"report: {args.report}")
    print(json.dumps(red["run"]["summary"], indent=1), file=sys.stderr)


def cmd_run(args) -> int:
    import run as m0

    try:
        data_dir, entries, cases, fixture = _load(args)
    except literal.DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    scored = [c for c in cases if c.get("crosscheck") != "disputed"]
    if args.limit:
        scored = scored[: args.limit]
    stamp = _dt.date.today().isoformat()
    full_out = data_dir / "runs" / f"{stamp}-excel-m1-full.json"
    ns = argparse.Namespace(profile=args.profile, sf_profile=args.sf_profile,
                            connection=args.connection, database=args.database,
                            schema=args.schema, out=full_out, report=None,
                            fill_expected=False, cases=args.manifest)
    deps = m0.Deps(translate=translate_literal_case,
                   oracle=lambda wh, c, fx, fq: literal.literal_oracle(c))
    rc = m0.live_run(ns, scored, {literal.FIXTURE_NAME: fixture}, args.title, deps)
    full = json.loads(full_out.read_text())
    _outputs(args, data_dir, entries, scored, fixture, full)
    return rc


def cmd_rebuild(args) -> int:
    data_dir, entries, cases, fixture = _load(args)
    full = json.loads(args.full_run.read_text())
    ids = {it["id"] for it in full["cases"]}
    _outputs(args, data_dir, entries, [c for c in cases if c["id"] in ids], fixture, full)
    return 0


def _args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", help=f"corpus dir outside the repo (or ${literal.DATA_DIR_ENV})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("candidates")
    s = sub.add_parser("select")
    s.add_argument("--manifest", type=pathlib.Path, required=True)
    s.add_argument("--selection", type=pathlib.Path, required=True)
    s.add_argument("--n-lo", type=int, default=200)
    s.add_argument("--n-poi", type=int, default=50)
    s.add_argument("--per-function", type=int, default=6)
    for name in ("run", "rebuild"):
        r = sub.add_parser(name)
        r.add_argument("--manifest", type=pathlib.Path, required=True)
        r.add_argument("--results", type=pathlib.Path, required=True)
        r.add_argument("--report", type=pathlib.Path)
        r.add_argument("--title", default="Formula fidelity M1: Excel cases, literal oracle")
        if name == "run":
            r.add_argument("--profile", required=True)
            r.add_argument("--sf-profile", required=True)
            r.add_argument("--connection", default="APJ_TAB")
            r.add_argument("--database", default="AGENT_SKILLS")
            r.add_argument("--schema", default="PUBLIC")
            r.add_argument("--limit", type=int, default=0)
        else:
            r.add_argument("--full-run", type=pathlib.Path, required=True)
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = _args(argv)
    try:
        return {"candidates": cmd_candidates, "select": cmd_select, "run": cmd_run,
                "rebuild": cmd_rebuild}[args.cmd](args)
    except literal.DataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
