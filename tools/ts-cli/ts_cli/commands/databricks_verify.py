"""ts databricks verify: does a converted Model return its Metric View's numbers? (BL-639)

Registered on `databricks.app` at import, as `load_databricks` registers on `load.app`,
so `commands/databricks.py` does not grow past the file-size nudge. Planning and comparison
are pure and live in `ts_cli/databricks/mv_verify.py`. This module only runs the queries:
Databricks through `load_databricks._dbx_exec` (the Statement Execution API via the
`databricks` CLI), ThoughtSpot through the AgentQL fetch-data call in `commands/spotql.py`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from ts_cli.commands.databricks import app
from ts_cli.databricks import mv_verify as mv


# ---------------------------------------------------------------------------
# Executors (the tests replace these two)
# ---------------------------------------------------------------------------

def _run_databricks(cli_profile: str, warehouse_id: str, sql: str) -> dict:
    from ts_cli.commands.load_databricks import _dbx_exec
    return _dbx_exec(cli_profile, warehouse_id, sql)


def _run_agentql(sql: str, model_guid: str, profile: Optional[str]) -> dict:
    from ts_cli.commands.spotql import _FETCH_PATH, _run
    return _run(_FETCH_PATH, sql, model_guid, profile)


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
    if len(rows) >= mv.AGENTQL_ROW_CAP:
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


def _verify_shape(shape: dict, ctx: dict) -> dict:
    res: dict = {"label": shape["label"], "dims": shape["dims"], "filter": shape["filter"]}
    flag = shape.get("flag")
    kind = ctx["dim_kinds"].get(flag) if flag else None
    if kind not in (None, "boolean"):
        res["skipped"] = f"{flag} is {kind} on Databricks, not BOOLEAN"
        return res
    measures = ctx["plan"]["measures"]
    res["databricks_sql"] = mv.databricks_sql(ctx["mv_fqn"], shape, measures)
    try:
        response = _run_databricks(ctx["cli_profile"], ctx["warehouse_id"],
                                   res["databricks_sql"])
        kinds, dbx_rows = mv.databricks_result(response)
    except (SystemExit, ValueError, OSError) as exc:
        res["errors"] = [{"side": "databricks", "error": _text(exc)}]
        return res
    for j, d in enumerate(shape["dims"]):
        ctx["dim_kinds"][d] = kinds[j]
    if len(shape["dims"]) == 1 and not shape["filter"] and kinds[0] == "string":
        ctx["dim_values"][shape["dims"][0]] = [row[0] for row in dbx_rows]
    blocks, res["agentql"], errors, notes = _thoughtspot_blocks(shape, ctx)
    res.update(mv.compare_shape(len(shape["dims"]), kinds, dbx_rows, blocks, measures,
                                ctx["tz"]))
    if errors:
        res["errors"] = errors
    if notes:
        res["notes"] = notes
    return res


def _progress(n: int, res: dict) -> None:
    status = res["status"].upper()
    if res["status"] == "skipped":
        detail = res["skipped"]
    elif "rows_databricks" in res:
        detail = (f"rows {res['rows_databricks']}/{res['rows_thoughtspot']}, "
                  f"{res['mismatch_count']} mismatch(es)")
    else:
        detail = res["errors"][0]["error"][:200]
    typer.echo(f"[{n}] {res['label']}: {status} ({detail})", err=True)


def _run_time_shapes(ctx: dict) -> list[dict]:
    """Default shapes that need the data first: the two filtered totals for a dimension
    Databricks reports as BOOLEAN that the name heuristic missed, and the total filtered
    on one value of the first string dimension that has a usable one."""
    dims = ctx["plan"]["dimensions"]
    extra = []
    for d in dims:
        if not d["flag"] and ctx["dim_kinds"].get(d["mv_name"]) == "boolean":
            extra.extend(mv.flag_filter_shapes(d))
    for d in dims:
        value = mv.pick_filter_value(ctx["dim_values"].get(d["mv_name"]) or [])
        if value is not None:
            extra.append(mv.value_filter_shape(d, value))
            break
    return extra


def _run_shapes(shapes: list[dict], ctx: dict, defaults: bool) -> list[dict]:
    """Run every shape in order; with the default shapes, then the run-time ones."""
    results: list[dict] = []
    queue = list(shapes)
    while queue:
        res = _verify_shape(queue.pop(0), ctx)
        res["status"] = mv.shape_status(res)
        results.append(res)
        _progress(len(results), res)
        if defaults and not queue:
            defaults = False
            queue = _run_time_shapes(ctx)
    return results


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

@app.command("verify")
def verify_cmd(
    parsed_path: str = typer.Option(
        ..., "--parsed", "-p", help="parse-mv output JSON for the Metric View"),
    model_tml_path: str = typer.Option(
        ..., "--model-tml", help="The .model.tml build-model wrote (YAML, or exported JSON)"),
    mv_fqn: str = typer.Option(
        ..., "--mv-fqn", help="The Metric View, catalog.schema.view"),
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
    Model, and compares every cell. Default shapes: the total, each dimension the Model
    carries, each boolean flag filtered = true and = false, and the total filtered on one
    value of a string dimension (a search filter beside every measure). MV measures that
    are not Model columns are listed, not compared. Report JSON on stdout (or --output), one
    progress line per shape on stderr. Exit 0 when every compared cell matches, 1 on any
    mismatch, any query error, or unreadable input.
    """
    tz = _zone(cluster_tz)
    plan = mv.build_plan(_read_json(parsed_path, "--parsed"), _load_model_tml(model_tml_path))
    if not plan["measures"]:
        _fail("No Metric View measure is a Model column this check can query, so there "
              "is nothing to compare. Check that --model-tml is the Model built from "
              "--parsed.")
    shapes = _shapes(shapes_path, plan)
    titles = {d["mv_name"]: d["title"] for d in plan["dimensions"]}
    head = {"mv_fqn": mv_fqn, "model_name": plan["model_name"], "model_guid": model_guid,
            "cluster_tz": cluster_tz, **{k: v for k, v in plan.items() if k != "model_name"}}
    if dry_run:
        head["shapes"] = [{**s, "databricks_sql": mv.databricks_sql(mv_fqn, s, plan["measures"]),
                           "agentql": mv.agentql_sql(plan["model_name"], s, plan["measures"],
                                                     titles)} for s in shapes]
        _emit({"dry_run": True, **head}, output)
        return
    if not model_guid or not dbx_profile:
        _fail("--model-guid and --dbx-profile are required unless --dry-run")
    from ts_cli.commands.load_databricks import dbx_warehouse
    _, cli_profile, warehouse_id = dbx_warehouse(dbx_profile)
    ctx = {"plan": plan, "titles": titles, "mv_fqn": mv_fqn, "model_name": plan["model_name"],
           "guid": model_guid, "profile": profile, "cli_profile": cli_profile,
           "warehouse_id": warehouse_id, "tz": tz, "dim_kinds": {}, "dim_values": {}}
    results = _run_shapes(shapes, ctx, defaults=not shapes_path)
    report = {**mv.summarise(results), **head, "shapes": results}
    _emit(report, output)
    if report["status"] != "match":
        raise SystemExit(1)
