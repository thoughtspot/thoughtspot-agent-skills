"""ts databricks verify: does a converted Model return its Metric View's numbers? (BL-639)

Registered on `databricks.app` at import, as `load_databricks` registers on `load.app`,
so `commands/databricks.py` does not grow past the file-size nudge. The plan is pure and
lives in `ts_cli/databricks/mv_verify.py`, the comparison in `mv_verify_compare.py`. This
module only runs the queries: Databricks through `load_databricks._dbx_exec` (the
Statement Execution API via the `databricks` CLI), ThoughtSpot through the AgentQL
fetch-data call in `commands/spotql.py`, and the imported Model's TML export through
`formula_translate.validate.Validator.export_model`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from ts_cli.commands.databricks import app
from ts_cli.databricks import mv_verify as mv
from ts_cli.databricks import mv_verify_compare as cmp


# ---------------------------------------------------------------------------
# Executors (the tests replace these three)
# ---------------------------------------------------------------------------

def _run_databricks(cli_profile: str, warehouse_id: str, sql: str) -> dict:
    from ts_cli.commands.load_databricks import _dbx_exec
    return _dbx_exec(cli_profile, warehouse_id, sql)


def _run_agentql(sql: str, model_guid: str, profile: Optional[str]) -> dict:
    from ts_cli.commands.spotql import _FETCH_PATH, _run
    return _run(_FETCH_PATH, sql, model_guid, profile)


def _export_model(model_guid: str, profile: Optional[str]) -> dict:
    from ts_cli.client import ThoughtSpotClient, resolve_profile
    from ts_cli.formula_translate.validate import Validator
    model, _ = Validator(ThoughtSpotClient(resolve_profile(profile))).export_model(model_guid)
    return model


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def _fail(msg: str) -> None:
    typer.echo(msg, err=True)
    raise SystemExit(1)


def _read_json(path: str, label: str) -> Any:
    from ts_cli.io_helpers import load_json_file
    try:
        return load_json_file(path, label)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))


def _load_model_tml(path: str) -> dict:
    import yaml
    p = Path(path)
    if not p.is_file():
        _fail(f"--model-tml not found: {path}")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _fail(f"cannot read --model-tml {path}: {exc}")
    if not isinstance(doc, dict) or not isinstance(doc.get("model", doc), dict):
        _fail(f"--model-tml is not a Model TML document: {path}")
    return doc


def _zone(name: str):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        _fail(f"--cluster-tz: unknown time zone {name!r} (an IANA name such as "
              f"'UTC' or 'America/Los_Angeles')")


def _shapes(shapes_path: Optional[str], plan: dict) -> list[dict]:
    if not shapes_path:
        return mv.default_shapes(plan)
    try:
        return mv.parse_shapes(_read_json(shapes_path, "--shapes"), plan)
    except ValueError as exc:
        _fail(f"--shapes: {exc}")


# ---------------------------------------------------------------------------
# Running one shape
# ---------------------------------------------------------------------------

def _text(exc: BaseException) -> str:
    return (str(exc).strip() or type(exc).__name__)[:1000]


def _agentql_rows(sql: str, ctx: dict) -> tuple[Optional[list], Optional[str], bool]:
    """(rows, error, query_error). `query_error` is True when AgentQL answered with an
    error status, False for a transport or auth failure (not worth retrying)."""
    try:
        r = _run_agentql(sql, ctx["guid"], ctx["profile"])
    except (SystemExit, Exception) as exc:    # client, auth or network failure
        return None, _text(exc), False
    if r.get("status") != "SUCCESS":
        msg = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in r.get("errors") or [])
        return None, (msg or str(r.get("status")))[:1000], True
    rows = r.get("rows") or []
    if len(rows) >= cmp.AGENTQL_ROW_CAP:
        return None, (f"AgentQL returned {len(rows)} rows, its row cap, so the result may "
                      f"be cut short; narrow the shape"), False
    return rows, None, False


def _thoughtspot_blocks(shape: dict, ctx: dict) -> tuple[list, list, list, list]:
    """(blocks, queries, errors, notes). All measures go in one AgentQL query; when it
    fails with a query error, each measure runs alone, so one measure AgentQL cannot
    combine with others (SCAL-330560) does not hide the rest."""
    measures = ctx["plan"]["measures"]
    sql = mv.agentql_sql(ctx["model_name"], shape, measures, ctx["titles"])
    rows, err, query_error = _agentql_rows(sql, ctx)
    if err is None:
        return [{"measures": list(range(len(measures))), "rows": rows}], [sql], [], []
    if not query_error or len(measures) == 1:
        return [], [sql], [{"side": "thoughtspot", "error": err}], []
    blocks, queries, errors = [], [sql], []
    for i, m in enumerate(measures):
        q = mv.agentql_sql(ctx["model_name"], shape, [m], ctx["titles"])
        queries.append(q)
        rows_i, err_i, _ = _agentql_rows(q, ctx)
        if err_i is None:
            blocks.append({"measures": [i], "rows": rows_i})
        else:
            errors.append({"side": "thoughtspot", "measure": m["title"], "error": err_i})
    notes = [f"the query with every measure failed ({err}); each measure ran alone"]
    return blocks, queries, errors, notes


def _skip_reason(shape: dict, ctx: dict) -> Optional[str]:
    if shape.get("skipped"):
        return shape["skipped"]
    flag = shape.get("flag")
    kind = ctx["dim_kinds"].get(flag) if flag else None
    if kind not in (None, "boolean"):
        return f"{flag} is {kind} on Databricks, not BOOLEAN"
    return None


def _learn(shape: dict, specs: list, dbx_rows: list, ctx: dict) -> None:
    """Record each grouped dimension's kind, and a single dimension's values for the
    search filter."""
    for j, d in enumerate(shape["dims"]):
        ctx["dim_kinds"][d] = specs[j]["kind"]
    if len(shape["dims"]) == 1 and not shape["filter"] \
            and specs[0]["kind"] in mv.SEARCH_FILTER_KINDS:
        ctx["dim_values"][shape["dims"][0]] = (specs[0]["kind"], [r[0] for r in dbx_rows])


def _verify_shape(shape: dict, ctx: dict) -> dict:
    res: dict = {"label": shape["label"], "dims": shape["dims"], "filter": shape["filter"]}
    if shape.get("search_filter"):
        res["search_filter"] = True
    reason = _skip_reason(shape, ctx)
    if reason:
        res["skipped"] = reason
        return res
    measures = ctx["plan"]["measures"]
    n_dims = len(shape["dims"])
    res["databricks_sql"] = mv.databricks_sql(ctx["mv_fqn"], shape, measures)
    try:
        response = _run_databricks(ctx["cli_profile"], ctx["warehouse_id"],
                                   res["databricks_sql"])
        specs, dbx_rows = cmp.databricks_result(response, n_dims + len(measures))
    except (SystemExit, ValueError, OSError) as exc:
        res["errors"] = [{"side": "databricks", "error": _text(exc)}]
        return res
    _learn(shape, specs, dbx_rows, ctx)
    blocks, res["agentql"], errors, notes = _thoughtspot_blocks(shape, ctx)
    try:
        res.update(cmp.compare_shape(n_dims, specs, dbx_rows, blocks, measures, ctx["tz"]))
    except ValueError as exc:
        errors.append({"side": "thoughtspot", "error": _text(exc)})
    if errors:
        res["errors"] = errors
    if notes:
        res["notes"] = notes
    return res


def _progress(n: int, res: dict) -> None:
    status = res["status"].upper()
    if res["status"] == "skipped":
        detail = res["skipped"]
    elif res.get("errors"):
        detail = res["errors"][0]["error"][:200]
    else:
        detail = (f"rows {res['rows_databricks']}/{res['rows_thoughtspot']}, "
                  f"{res['mismatch_count']} mismatch(es)")
        if res.get("tolerance_accepted"):
            detail += f", {res['tolerance_accepted']} within tolerance"
    typer.echo(f"[{n}] {res['label']}: {status} ({detail})", err=True)


def _run_time_shapes(ctx: dict) -> list[dict]:
    """Default shapes that need the data first: the two filtered totals for a dimension
    Databricks reports as BOOLEAN that the name heuristic missed, and the search filter.
    When no dimension gives the search filter a value, a skipped entry says why."""
    dims = ctx["plan"]["dimensions"]
    extra = []
    for d in dims:
        if not d["flag"] and ctx["dim_kinds"].get(d["mv_name"]) == "boolean":
            extra.extend(mv.flag_filter_shapes(d))
    shape, reason = mv.search_filter_shape(dims, ctx["dim_values"])
    extra.append(shape or {"label": "search filter", "dims": [], "filter": None,
                           "search_filter": True, "skipped": f"not run: {reason}"})
    return extra


def _run_shapes(shapes: list[dict], ctx: dict, defaults: bool) -> list[dict]:
    """Run every shape in order; with the default shapes, then the run-time ones."""
    results: list[dict] = []
    queue = list(shapes)
    while queue:
        res = _verify_shape(queue.pop(0), ctx)
        res["status"] = cmp.shape_status(res)
        results.append(res)
        _progress(len(results), res)
        if defaults and not queue:
            defaults = False
            queue = _run_time_shapes(ctx)
    return results


def _search_filter_entry(results: list[dict]) -> Optional[dict]:
    """The search filter shape's label and status, or why it did not run."""
    entry = next((r for r in results if r.get("search_filter")), None)
    if entry is None:
        return None
    return {"label": entry["label"], "status": entry["status"],
            **({"reason": entry["skipped"]} if entry.get("skipped") else {})}


def _emit(report: dict, output: Optional[str]) -> None:
    if not output:
        typer.echo(json.dumps(report, indent=2, default=str))
        return
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    brief = {k: report[k] for k in ("status", "summary") if k in report}
    typer.echo(json.dumps({**brief, "report": str(out)}))


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

def _plan(parsed: dict, file_doc: dict, translated: Optional[dict], dry_run: bool,
          model_guid: Optional[str], profile: Optional[str]) -> tuple[dict, list, list]:
    """(plan, model differences, problems). Outside a dry run the plan is built from the
    imported Model's export, which is what AgentQL queries, and the TML file is diffed
    against it."""
    differences: list = []
    model_doc = file_doc
    if not dry_run:
        try:
            model_doc = _export_model(model_guid, profile)
        except (SystemExit, Exception) as exc:
            _fail(f"cannot export the imported Model {model_guid}: {_text(exc)}")
        differences = mv.model_differences(file_doc, model_doc)
    plan = mv.build_plan(parsed, model_doc, translated)
    return plan, differences, mv.plan_problems(plan) + differences


def _dry_run_report(head: dict, shapes: list, plan: dict, mv_fqn: str, titles: dict) -> dict:
    head["shapes"] = [{**s, "databricks_sql": mv.databricks_sql(mv_fqn, s, plan["measures"]),
                       "agentql": mv.agentql_sql(plan["model_name"], s, plan["measures"],
                                                 titles)} for s in shapes]
    return {"dry_run": True, **head}


@app.command("verify")
def verify_cmd(
    parsed_path: str = typer.Option(
        ..., "--parsed", "-p", help="parse-mv output JSON for the Metric View"),
    model_tml_path: str = typer.Option(
        ..., "--model-tml", help="The .model.tml build-model wrote (YAML, or exported JSON)"),
    mv_fqn: str = typer.Option(
        ..., "--mv-fqn", help="The Metric View, catalog.schema.view"),
    translated_path: Optional[str] = typer.Option(
        None, "--translated", "-t",
        help="translate-formulas output: an MV entry it skipped is reported, not failed"),
    model_guid: Optional[str] = typer.Option(
        None, "--model-guid", help="GUID of the imported Model (not needed with --dry-run)"),
    profile: Optional[str] = typer.Option(
        None, "--profile", envvar="TS_PROFILE", help="ThoughtSpot profile"),
    dbx_profile: Optional[str] = typer.Option(
        None, "--dbx-profile",
        help="Databricks profile name in ~/.claude/databricks-profiles.json "
             "(not needed with --dry-run)"),
    cluster_tz: str = typer.Option(
        "UTC", "--cluster-tz",
        help="IANA time zone of the ThoughtSpot cluster: AgentQL returns a DATE as epoch "
             "seconds at midnight in it"),
    shapes_path: Optional[str] = typer.Option(
        None, "--shapes",
        help='JSON list of {"label", "dims": [MV dimension names], "filter": '
             '[MV dimension, SQL literal] | null} replacing the default shapes'),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Write the report JSON here instead of stdout"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print both queries for every shape and run nothing"),
) -> None:
    """Check that a Model converted from a Databricks Metric View returns the same numbers.

    Runs each query shape on both sides, MEASURE() on the Metric View and AgentQL on the
    imported Model, and compares every cell by its Databricks type. Default shapes: the
    total, each dimension the Model carries, each boolean flag filtered = true and =
    false, and a search filter on one dimension value. Report JSON on stdout (or
    --output), one progress line per shape on stderr. Exit 0 only when the status is
    match; 1 on a mismatch, a query error, an MV entry the Model lacks or types wrongly,
    no non-NULL cell compared, no search filter run, or unreadable input.
    """
    tz = _zone(cluster_tz)
    if not dry_run and (not model_guid or not dbx_profile):
        _fail("--model-guid and --dbx-profile are required unless --dry-run")
    translated = _read_json(translated_path, "--translated") if translated_path else None
    plan, differences, problems = _plan(
        _read_json(parsed_path, "--parsed"), _load_model_tml(model_tml_path), translated,
        dry_run, model_guid, profile)
    if not plan["measures"]:
        _fail("No Metric View measure is a Model column this check can query, so there "
              "is nothing to compare. Check that --model-tml is the Model built from "
              "--parsed." + "".join(f"\n  - {p}" for p in problems))
    shapes = _shapes(shapes_path, plan)
    titles = {d["mv_name"]: d["title"] for d in plan["dimensions"]}
    head = {"mv_fqn": mv_fqn, "model_name": plan["model_name"], "model_guid": model_guid,
            "cluster_tz": cluster_tz, "problems": problems, "model_differences": differences,
            **{k: v for k, v in plan.items() if k != "model_name"}}
    if dry_run:
        _emit(_dry_run_report(head, shapes, plan, mv_fqn, titles), output)
        return
    from ts_cli.commands.load_databricks import dbx_warehouse
    _, cli_profile, warehouse_id = dbx_warehouse(dbx_profile)
    ctx = {"plan": plan, "titles": titles, "mv_fqn": mv_fqn, "model_name": plan["model_name"],
           "guid": model_guid, "profile": profile, "cli_profile": cli_profile,
           "warehouse_id": warehouse_id, "tz": tz, "dim_kinds": {}, "dim_values": {}}
    results = _run_shapes(shapes, ctx, defaults=not shapes_path)
    report = {**cmp.summarise(results, problems, filter_required=not shapes_path), **head,
              "search_filter": _search_filter_entry(results),
              "shapes": results}
    for p in problems:
        typer.echo(f"PROBLEM: {p}", err=True)
    _emit(report, output)
    if report["status"] != "match":
        raise SystemExit(1)
