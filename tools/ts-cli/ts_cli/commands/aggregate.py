"""ts aggregate — aggregate-model advisor (signatures/recommend/profile/generate/history).

All five subcommands are implemented. `signatures`/`recommend` (Task 7) work
purely from exported TML + the pure engine. `profile`/`history` (Task 8) add a
Snowflake connection for warehouse profiling and query-history mining, each
with a fully offline "manual mode" for dialects/setups without a live
connection. `generate` (Task 8) emits DDL + TML for one approved candidate —
it never imports; the skill gates each import separately.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
import yaml

from ts_cli.aggregate.lattice import generate_candidates
from ts_cli.aggregate.measures import build_rewrite_plans
from ts_cli.aggregate.scoring import greedy_select
from ts_cli.aggregate.signatures import column_kinds_from_model, extract_signatures
from ts_cli.tml_common import dump_tml_yaml

app = typer.Typer(
    help="Aggregate-model advisor: audit dependents, recommend and generate aggregate Models.",
    no_args_is_help=True,
)

# Dependent types worth turning into query signatures. Both the normalized
# label (ANSWER/LIVEBOARD, from `_collect_dependents`) and the raw v2 bucket
# name are accepted defensively.
_SIGNATURE_TYPES = frozenset({"ANSWER", "LIVEBOARD", "PINBOARD_ANSWER_BOOK",
                              "QUESTION_ANSWER_BOOK"})


def _signatures_summary(sigs: list) -> dict:
    partial = sum(1 for s in sigs if s.get("parse_status") == "partial")
    return {"signatures": len(sigs), "full": len(sigs) - partial, "partial": partial}


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)
    # Explicit flush: when a caller follows this with a SystemExit/typer.Exit,
    # Click's CliRunner(mix_stderr=False) only flushes sys.stdout in its
    # invoke() finally block (not sys.stderr) before reading the captured
    # stderr buffer — an unflushed diagnostic here would otherwise vanish from
    # `result.stderr` in tests (and risks being lost on a hard process exit
    # outside tests too).
    sys.stderr.flush()


def _export_tml(client, guid: str) -> dict:
    """Export one object's TML and parse its edoc.

    Uses `ts_cli.commands.tml.parse_edoc`, which strips non-printable
    characters before parsing — the same path `ts tml export --parse` and
    `ts audit` use — rather than a bare `yaml.safe_load`.
    """
    from ts_cli.commands.tml import parse_edoc
    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": guid}],
        "export_associated": False,
        "export_fqn": True,
        "formattype": "YAML",
    })
    return parse_edoc(resp.json()[0]["edoc"], "YAML")


def _filtered_dependents(client, model_guid: str) -> list:
    """Direct dependents of the primary Model, filtered to Answers/Liveboards.

    Reuses the alias-aware walk behind `ts metadata dependents` / `ts metadata
    report` (`_collect_dependents` in `ts_cli.commands.metadata`, itself built
    on the same `_build_dependents_payload` / `_normalize_dependents_response`
    pair those commands use) rather than hand-rolling a separate
    metadata/search call.
    """
    from ts_cli.commands.metadata import _collect_dependents
    return [d for d in _collect_dependents(client, model_guid)
            if d["type"].upper() in _SIGNATURE_TYPES]


def _export_all_signatures(client, dependents: list, kinds: dict) -> tuple:
    """Export TML for each dependent and extract signatures.

    A single dependent's export failing (deleted between the dependents walk
    and the export call, permission error, etc.) must not abort the whole
    run — skip it and count it. `client.post` raises `SystemExit` (not a
    plain `Exception`) on a non-2xx response, so both are caught here.
    """
    sigs, failures = [], 0
    for dep in dependents:
        try:
            doc = _export_tml(client, dep["guid"])
        except (Exception, SystemExit) as exc:  # noqa: BLE001 — skip-and-count per spec
            _err(f"export failed for {dep['guid']}: {exc}")
            failures += 1
            continue
        sigs.extend(extract_signatures(doc, kinds, dep["guid"], dep["name"]))
    return sigs, failures


def _write_signatures_jsonl(path: Path, sigs: list) -> None:
    with path.open("w") as fh:
        for s in sigs:
            fh.write(json.dumps(s) + "\n")


@app.command()
def signatures(
    model: str = typer.Option(..., help="Primary Model GUID"),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE"),
    out: str = typer.Option(..., help="Output directory"),
) -> None:
    """Export the Model + dependents and write signatures.jsonl.

    Output (stdout JSON): {"model_guid", "signatures", "full", "partial",
    "dependents", "export_failures"}. Writes `<out>/model.tml.yaml` and
    `<out>/signatures.jsonl`.
    """
    from ts_cli.client import ThoughtSpotClient, resolve_profile
    client = ThoughtSpotClient(resolve_profile(profile))
    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)

    model_tml = _export_tml(client, model)
    (outdir / "model.tml.yaml").write_text(dump_tml_yaml(model_tml))
    kinds = column_kinds_from_model(model_tml)

    dependents = _filtered_dependents(client, model)
    sigs, failures = _export_all_signatures(client, dependents, kinds)
    _write_signatures_jsonl(outdir / "signatures.jsonl", sigs)

    summary = _signatures_summary(sigs)
    summary.update({
        "model_guid": model,
        "dependents": len(dependents),
        "export_failures": failures,
    })
    print(json.dumps(summary, indent=2))


def _apply_weights(sigs: list, weights_path: Optional[str]) -> None:
    """Overwrite each signature's weight from a `history`-produced weights.json,
    keyed by `<source_guid>::<viz_name or ''>`. Signatures with no matching key
    keep their existing weight (default 1.0)."""
    if not weights_path:
        return
    wmap = json.loads(Path(weights_path).read_text())
    for s in sigs:
        key = f"{s['source_guid']}::{s.get('viz_name') or ''}"
        s["weight"] = float(wmap.get(key, s.get("weight", 1.0)))


def _candidate_key(c: dict) -> str:
    return json.dumps([c["dimensions"], c["date_column"], c["bucket"]])


def _merge_prior_agg_rows(candidates: list, prior_path: Path,
                          base_rows: Optional[int]) -> Optional[int]:
    """Carry `agg_rows` forward from an earlier `profile` run in candidates.json
    so re-running `recommend` (e.g. after `history` reweights signatures) doesn't
    lose prior profiling — matched by (dimensions, date_column, bucket), since
    candidate ids can shift between runs. Falls back to the prior run's
    base_rows when the caller didn't pass one."""
    if not prior_path.exists():
        return base_rows
    prev_payload = json.loads(prior_path.read_text())
    prev_by_key = {_candidate_key(p): p for p in prev_payload.get("candidates", [])}
    for c in candidates:
        prev = prev_by_key.get(_candidate_key(c))
        if prev is not None:
            c["agg_rows"] = prev.get("agg_rows")
    if base_rows is None:
        base_rows = prev_payload.get("base_rows")
    return base_rows


def _read_signatures_dir(d: Path) -> tuple:
    """Load model.tml.yaml + signatures.jsonl from a `signatures`-command
    output directory for `recommend`, failing with a clear diagnostic —
    rather than a bare FileNotFoundError traceback — when either file is
    missing (e.g. `signatures` was never run, or the wrong --dir was passed).
    """
    try:
        model_tml = yaml.safe_load((d / "model.tml.yaml").read_text())
        sigs = [json.loads(line) for line in
                (d / "signatures.jsonl").read_text().splitlines() if line.strip()]
    except FileNotFoundError as exc:
        _err(f"Missing expected file in {d}: {exc.filename}. "
             "Run `ts aggregate signatures` first to produce model.tml.yaml "
             "and signatures.jsonl.")
        raise typer.Exit(code=1) from None
    return model_tml, sigs


def _excluded_unprofiled(candidates: list, mode: str) -> list:
    """Candidate ids left out of cost-mode selection because they have no
    agg_rows yet (never profiled) — surfaced so the skill can tell the user to
    run `profile` before trusting the ranking. Empty in coverage mode, where
    every candidate is eligible regardless of profiling."""
    if mode != "cost":
        return []
    return [c["id"] for c in candidates if c.get("agg_rows") is None]


@app.command()
def recommend(
    dir: str = typer.Option(..., "--dir", help="Directory from `signatures`"),
    weights: Optional[str] = typer.Option(None, help="weights.json from `history`"),
    base_rows: Optional[int] = typer.Option(None),
    max_select: int = typer.Option(10),
) -> None:
    """Generate + rank aggregate candidates; writes candidates.json.

    Output (stdout JSON): {"mode", "selected", "curve", "candidates",
    "excluded_unprofiled"}. `excluded_unprofiled` lists candidate ids skipped
    from cost-mode selection because they have no `agg_rows` yet.
    """
    d = Path(dir)
    model_tml, sigs = _read_signatures_dir(d)
    _apply_weights(sigs, weights)

    plans = build_rewrite_plans(model_tml)
    candidates = generate_candidates(sigs, plans)

    prior_path = d / "candidates.json"
    base_rows = _merge_prior_agg_rows(candidates, prior_path, base_rows)

    result = greedy_select(candidates, sigs, base_rows=base_rows, max_select=max_select)
    excluded = _excluded_unprofiled(candidates, result["mode"])

    payload = {"base_rows": base_rows, "candidates": candidates, "selection": result}
    prior_path.write_text(json.dumps(payload, indent=2))

    print(json.dumps({
        "mode": result["mode"],
        "selected": result["selected"],
        "curve": result["curve"],
        "candidates": len(candidates),
        "excluded_unprofiled": excluded,
    }, indent=2))


def _load_tables_dir(tables_dir: str) -> dict:
    return {p.stem.replace(".tml", ""): yaml.safe_load(p.read_text())
            for p in Path(tables_dir).glob("*.yaml")}


def _read_candidates_context(dir_path: Path, tables_dir: str) -> tuple:
    """Load candidates.json + model.tml.yaml + Table TMLs + rewrite plans.

    Shared by `profile` and `generate` — both need the same on-disk context
    `recommend` produced.
    """
    payload = json.loads((dir_path / "candidates.json").read_text())
    model_tml = yaml.safe_load((dir_path / "model.tml.yaml").read_text())
    table_tmls = _load_tables_dir(tables_dir)
    plans = build_rewrite_plans(model_tml)
    return payload, model_tml, table_tmls, plans


def _snowflake_connection(profile_name: str, warehouse: Optional[str],
                          role: Optional[str]):
    """Connect to Snowflake for `profile`/`history`, reusing the profile loader
    and connector from `ts_cli.commands.load` — never re-implement Snowflake
    auth here.

    NOTE (Task 8 deviation from the task brief): the brief's illustrative code
    imports a `_connect_snowflake` helper from `ts_cli.commands.load`. No such
    function exists there — the real connector is `_connect_python(profile,
    warehouse, role)`, which takes an explicit warehouse/role rather than
    resolving them itself. This wrapper reproduces the same warehouse-
    resolution fallback `ts load snowflake` uses (CLI flag -> profile's
    `default_warehouse` -> hard error) so `aggregate profile`/`history` behave
    identically to `ts load snowflake` for the same profile.
    """
    from ts_cli.commands.load import _connect_python, load_snowflake_profile
    sf_profile = load_snowflake_profile(profile_name)
    wh = warehouse or sf_profile.get("default_warehouse", "")
    rl = role or sf_profile.get("default_role", "")
    if not wh:
        raise SystemExit(
            f"No warehouse specified for Snowflake profile '{profile_name}'. "
            "Use --warehouse or set default_warehouse in the profile."
        )
    return _connect_python(sf_profile, wh, rl)


def _ingest_profile_results(payload: dict, results_path: str) -> dict:
    r = json.loads(Path(results_path).read_text())
    for key in ("base_rows", "candidates"):
        if key not in r:
            raise SystemExit(
                f"Results JSON {results_path} is missing required key '{key}'. "
                'Expected {"base_rows": N, "candidates": {"cand_1": rows, ...}}.'
            )
    payload["base_rows"] = r["base_rows"]
    for c in payload["candidates"]:
        if c["id"] in r["candidates"]:
            c["agg_rows"] = int(r["candidates"][c["id"]])
    return {"ingested": len(r["candidates"])}


# ──────────────────────────────────────────────────────────────────────────────
# Task 18: SpotQL-first SQL generation (DDL + profiling), sqlgen as fallback.
#
# ThoughtSpot's own SQL generation resolves joins against the FULL semantic
# model, so it gets role-playing / ambiguous-path dimensions right where
# sqlgen.build_select's hand-rolled join walker can silently get them wrong
# (live-proven: it grouped revenue by inventory-balance month instead of
# order month). Both `generate` and `profile` therefore try
# build_spotql -> `ts spotql generate-sql` -> wrap first, and fall back to
# sqlgen.build_select only when SpotQL generation is unavailable or errors
# (network/profile issue, --no-spotql, or a rejected statement) — never a
# hard failure, since the SQL-gen endpoint being down must not block the
# whole advisor workflow. A fallback always emits a stderr note that
# role-playing/ambiguous-path dimensions may be wrong on that candidate.
# ──────────────────────────────────────────────────────────────────────────────

_SPOTQL_FALLBACK_NOTE = (
    "falling back to the built-in join walker. Role-playing/ambiguous-path "
    "dimensions may be wrong; verify manually (see the ts-object-model-"
    "aggregates skill's open-items.md)."
)


def _spotql_generate_sql(spotql: str, model_guid: str, ts_profile: Optional[str]) -> dict:
    """Call the existing `ts spotql generate-sql` client path — a local
    import (not a top-of-file one) so tests can monkeypatch
    `ts_cli.commands.spotql._run` directly, the same pattern this module
    already uses to reuse `_collect_dependents`/`_export_tml` from sibling
    command modules. Never reimplement the HTTP call here."""
    from ts_cli.commands.spotql import _GENERATE_PATH, _run
    return _run(_GENERATE_PATH, spotql, model_guid, ts_profile)


def _spotql_ddl_or_none(model_tml: dict, cand: dict, plans: dict, model_guid: str,
                        ts_profile: Optional[str], target: str, dialect: str,
                        materialization: str, warehouse: Optional[str]) -> Optional[str]:
    """Try the SpotQL-based DDL path for one candidate. Returns None on ANY
    failure (unavailable model_guid, a non-SUCCESS generate-sql status, or an
    exception/SystemExit from the client) so the caller falls back to
    sqlgen.build_select — SpotQL is the preferred path here, not a hard
    dependency, so this never raises."""
    if not model_guid:
        return None
    from ts_cli.aggregate.spotql_aggregate import build_spotql, wrap_as_ddl
    try:
        spotql, aliases = build_spotql(cand, plans, model_tml["model"]["name"])
        result = _spotql_generate_sql(spotql, model_guid, ts_profile)
        if result["status"] != "SUCCESS" or not result["executable_sql"]:
            _err(f"SpotQL generate-sql did not return SUCCESS for candidate "
                 f"{cand.get('id')} (status={result['status']}, "
                 f"errors={result['errors']}) — {_SPOTQL_FALLBACK_NOTE}")
            return None
        return wrap_as_ddl(result["executable_sql"], aliases, target, dialect,
                           materialization, warehouse=warehouse)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — best-effort path
        _err(f"SpotQL DDL generation raised {exc!r} for candidate "
             f"{cand.get('id')} — {_SPOTQL_FALLBACK_NOTE}")
        return None


def _spotql_profile_sql_or_none(model_tml: dict, cand: dict, plans: dict, model_guid: str,
                                ts_profile: Optional[str]) -> Optional[str]:
    """Same SpotQL-first attempt as `_spotql_ddl_or_none`, but for profiling:
    wraps the returned executable_sql (LIMIT stripped) in
    `SELECT COUNT(*) FROM (...) _agg` instead of DDL. Returns None on any
    failure so the caller falls back to sqlgen's build_select/build_profile_sql."""
    if not model_guid:
        return None
    from ts_cli.aggregate.spotql_aggregate import _strip_trailing_limit, build_spotql
    try:
        spotql, _aliases = build_spotql(cand, plans, model_tml["model"]["name"])
        result = _spotql_generate_sql(spotql, model_guid, ts_profile)
        if result["status"] != "SUCCESS" or not result["executable_sql"]:
            _err(f"SpotQL generate-sql did not return SUCCESS for candidate "
                 f"{cand.get('id')} (status={result['status']}) — "
                 f"{_SPOTQL_FALLBACK_NOTE}")
            return None
        inner = _strip_trailing_limit(result["executable_sql"])
        return f"SELECT COUNT(*) AS agg_rows FROM (\n{inner}\n) _agg"
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — best-effort path
        _err(f"SpotQL profiling SQL generation raised {exc!r} for candidate "
             f"{cand.get('id')} — {_SPOTQL_FALLBACK_NOTE}")
        return None


def _build_profile_statements(payload: dict, model_tml: dict, table_tmls: dict,
                              plans: dict, top_k: int, dialect: str,
                              model_guid: Optional[str] = None,
                              ts_profile: Optional[str] = None,
                              no_spotql: bool = False) -> tuple:
    """Base-count + per-candidate profiling SQL for the top-K candidates by
    coverage. Each candidate tries the SpotQL path first (only when
    `model_guid` is supplied and `no_spotql` is False — omitting `--model-guid`
    is the pre-Task-18 default and must never attempt a ThoughtSpot call),
    falling back to sqlgen.build_select. Candidates whose sqlgen SELECT can't
    be built deterministically either (`UnsupportedModelError`) are skipped,
    not fatal — the skill advises manual SQL for those instead."""
    from ts_cli.aggregate.sqlgen import (UnsupportedModelError, build_base_count_sql,
                                         build_profile_sql, build_select)
    ranked = sorted(payload["candidates"], key=lambda c: -len(c["covered"]))[:top_k]
    statements = [("__base__", build_base_count_sql(model_tml, table_tmls, dialect))]
    skipped = []
    for c in ranked:
        sql = None
        if model_guid and not no_spotql:
            sql = _spotql_profile_sql_or_none(model_tml, c, plans, model_guid, ts_profile)
        if sql is None:
            try:
                sql = build_profile_sql(build_select(model_tml, table_tmls, c, plans, dialect))
            except UnsupportedModelError as exc:
                skipped.append({"id": c["id"], "reason": str(exc)})
                _err(f"skipping {c['id']}: {exc}")
                continue
        statements.append((c["id"], sql))
    return statements, skipped


def _emit_profile_script(path: str, statements: list) -> None:
    script = "\n\n".join(f"-- {cid}\n{sql};" for cid, sql in statements)
    Path(path).write_text(script + "\n")


def _run_connected_profile(statements: list, snowflake_profile: str,
                           warehouse: Optional[str], role: Optional[str]) -> dict:
    conn = _snowflake_connection(snowflake_profile, warehouse, role)
    counts = {}
    for cid, sql in statements:
        cur = conn.cursor()
        cur.execute(sql)
        counts[cid] = int(cur.fetchone()[0])
    return counts


@app.command()
def profile(
    dir: str = typer.Option(..., "--dir"),
    tables_dir: str = typer.Option(
        ..., help="Directory of exported Table TMLs, <NAME>.tml.yaml per model_tables entry"),
    snowflake_profile: Optional[str] = typer.Option(
        None, "--snowflake-profile", help="Connected mode: profile from ts-profile-snowflake"),
    emit_sql: Optional[str] = typer.Option(
        None, help="Manual mode: write a numbered profiling script here instead of connecting"),
    results: Optional[str] = typer.Option(
        None, help='Manual mode: ingest {"base_rows": N, "candidates": {"cand_1": rows, ...}}'),
    top_k: int = typer.Option(10, "--top-k"),
    dialect: str = typer.Option("snowflake"),
    warehouse: Optional[str] = typer.Option(
        None, help="Connected mode: Snowflake warehouse (default: profile's default_warehouse)"),
    role: Optional[str] = typer.Option(
        None, help="Connected mode: Snowflake role (default: profile's default_role)"),
    model_guid: Optional[str] = typer.Option(
        None, "--model-guid",
        help="Primary Model GUID — enables SpotQL-based profiling SQL (Task 18): "
             "ThoughtSpot's own SQL generation resolves joins correctly on "
             "role-playing/ambiguous-path dimensions, where the built-in join "
             "walker can be wrong. Omit to always use the built-in walker "
             "(pre-Task-18 behaviour; no ThoughtSpot connection needed)."),
    ts_profile: Optional[str] = typer.Option(
        None, "--profile", "-p", envvar="TS_PROFILE",
        help="ThoughtSpot profile — used with --model-guid to call `ts spotql "
             "generate-sql`. Ignored if --model-guid is omitted."),
    no_spotql: bool = typer.Option(
        False, "--no-spotql",
        help="Even with --model-guid, use the built-in join walker directly."),
) -> None:
    """Measure base + per-candidate row counts (connected or manual mode).

    Three modes, mutually exclusive: `--results` ingests a manual profiling
    run's output; `--emit-sql` writes a numbered SQL script for manual
    execution; otherwise `--snowflake-profile` connects and profiles directly.
    Writes `agg_rows`/`base_rows` back into `<dir>/candidates.json`.

    Per-candidate profiling SQL prefers SpotQL (see `--model-guid` above),
    falling back to the built-in join walker when unavailable or `--no-spotql`
    is set; the base-row count is always a plain single-table count
    (sqlgen.build_base_count_sql), unaffected by this choice.
    """
    d = Path(dir)
    payload, model_tml, table_tmls, plans = _read_candidates_context(d, tables_dir)

    if results:
        summary = _ingest_profile_results(payload, results)
        (d / "candidates.json").write_text(json.dumps(payload, indent=2))
        print(json.dumps(summary))
        return

    statements, skipped = _build_profile_statements(
        payload, model_tml, table_tmls, plans, top_k, dialect,
        model_guid=model_guid, ts_profile=ts_profile, no_spotql=no_spotql)

    if emit_sql:
        _emit_profile_script(emit_sql, statements)
        print(json.dumps({"emitted": len(statements), "skipped": skipped,
                          "next": "run the script, then re-run with --results"}))
        return

    if not snowflake_profile:
        _err("Provide --snowflake-profile for connected mode, or --emit-sql for manual mode.")
        raise typer.Exit(code=1)

    counts = _run_connected_profile(statements, snowflake_profile, warehouse, role)
    payload["base_rows"] = counts.pop("__base__")
    for c in payload["candidates"]:
        if c["id"] in counts:
            c["agg_rows"] = counts[c["id"]]
    (d / "candidates.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps({"base_rows": payload["base_rows"], "profiled": len(counts),
                      "skipped": skipped}, indent=2))


def _colmap_from_model(model_tml: dict) -> dict:
    """Physical `TABLE.COL` (upper) -> Model display name, for matching
    warehouse query-history GROUP BY shapes back to signature dimensions.

    Every ThoughtSpot formula appears in model.columns[] with a formula_id
    and NO column_id (the physical-vs-formula column rule), so formula-backed
    columns are skipped here — they have no physical TABLE.COL shape to
    match a warehouse GROUP BY clause against, and iterating them
    unconditionally used to crash with a bare KeyError.
    """
    colmap = {}
    for c in model_tml["model"].get("columns", []) or []:
        if not c.get("column_id"):
            continue
        table, col = c["column_id"].split("::", 1)
        colmap[f"{table.upper()}.{col.upper()}"] = c["name"]
    return colmap


def _query_history_rows(conn, tables: str, days: int) -> list:
    table_list = [t.strip() for t in tables.split(",") if t.strip()]
    if not table_list:
        # An empty --tables (e.g. ",  ,") would otherwise build "AND ()", a
        # SQL syntax error the warehouse rejects with a cryptic message.
        _err("No table names supplied via --tables (all entries were empty after "
             "trimming). Pass one or more comma-separated physical table names.")
        raise typer.Exit(code=1)
    like = " OR ".join("query_text ILIKE %s" for _ in table_list)
    sql = ("SELECT query_text FROM snowflake.account_usage.query_history "
           f"WHERE start_time >= DATEADD('day', -{int(days)}, CURRENT_TIMESTAMP()) "
           f"AND query_type = 'SELECT' AND ({like}) LIMIT 10000")
    cur = conn.cursor()
    cur.execute(sql, [f"%{t}%" for t in table_list])
    return [{"query_text": r[0]} for r in cur.fetchall()]


@app.command()
def history(
    dir: str = typer.Option(..., "--dir"),
    snowflake_profile: str = typer.Option(..., "--snowflake-profile"),
    tables: str = typer.Option(..., help="Comma-separated physical table names"),
    days: int = typer.Option(30),
    warehouse: Optional[str] = typer.Option(
        None, help="Snowflake warehouse (default: profile's default_warehouse)"),
    role: Optional[str] = typer.Option(
        None, help="Snowflake role (default: profile's default_role)"),
) -> None:
    """Mine Snowflake QUERY_HISTORY into signature weights (weights.json)."""
    from ts_cli.aggregate.history import match_history
    d = Path(dir)
    sigs = [json.loads(line) for line in
            (d / "signatures.jsonl").read_text().splitlines() if line.strip()]
    model_tml = yaml.safe_load((d / "model.tml.yaml").read_text())
    colmap = _colmap_from_model(model_tml)

    conn = _snowflake_connection(snowflake_profile, warehouse, role)
    rows = _query_history_rows(conn, tables, days)
    weights = match_history(rows, sigs, colmap)
    (d / "weights.json").write_text(json.dumps(weights, indent=2))
    print(json.dumps({"history_rows": len(rows), "weighted_signatures": len(weights)}))


def _read_generate_context(dir_path: Path, candidate: str, tables_dir: str) -> tuple:
    """Same on-disk context as `_read_candidates_context`, narrowed to the one
    approved candidate `generate` acts on."""
    payload, model_tml, table_tmls, plans = _read_candidates_context(dir_path, tables_dir)
    cand = next((c for c in payload["candidates"] if c["id"] == candidate), None)
    if cand is None:
        raise SystemExit(f"Candidate '{candidate}' not found in {dir_path / 'candidates.json'}")
    return cand, model_tml, table_tmls, plans


def _aggregate_name(model_tml: dict, cand: dict, agg_name: Optional[str]) -> str:
    root = model_tml["model"]["model_tables"][0]["name"]
    grain = "_".join([cand["bucket"] or ""] + cand["dimensions"]).strip("_")
    return agg_name or f"{root}_AGG_{grain}".upper()[:120]


def _require_warehouse_for_dynamic_table(dialect: str, materialization: str,
                                         warehouse: Optional[str]) -> None:
    """Snowflake dynamic tables require an assigned warehouse — `CREATE DYNAMIC
    TABLE ... TARGET_LAG = ...` fails at execution time with no WAREHOUSE
    clause. Task 5 review carry-forward: fail clearly here rather than let
    sqlgen silently emit DDL that only breaks when someone runs it."""
    from ts_cli.aggregate.sqlgen import resolve_materialization
    resolved = resolve_materialization(dialect, materialization)
    if dialect == "snowflake" and resolved == "dynamic" and not warehouse:
        raise SystemExit(
            "--warehouse is required to create a Snowflake dynamic table "
            "(TARGET_LAG needs an assigned warehouse to refresh from). Pass "
            "--warehouse, or use --materialization ctas for a plain "
            "CREATE TABLE AS instead."
        )


def _fallback_ddl_or_exit(model_tml: dict, table_tmls: dict, cand: dict, plans: dict,
                          dialect: str, target: str, materialization: str,
                          warehouse: Optional[str], candidate_id: str) -> str:
    """The pre-Task-18 sqlgen.build_select-based DDL path — used when SpotQL
    generation is unavailable/erroring or --no-spotql was passed. Its
    hand-rolled join walker can be wrong on role-playing/ambiguous-path
    dimensions (the bug Task 18's SpotQL-first default path fixes); this
    remains only as the documented fallback. Exits cleanly (never a bare
    traceback) on either an unresolvable SELECT or a rejected DDL shape
    (e.g. the Snowflake materialized-view join guard)."""
    from ts_cli.aggregate.sqlgen import UnsupportedModelError, build_ddl, build_select
    try:
        select_sql = build_select(model_tml, table_tmls, cand, plans, dialect)
    except UnsupportedModelError as exc:
        _err(f"cannot generate SQL for {candidate_id}: {exc}")
        _err("This candidate needs manual SQL authoring — see `ts aggregate profile --emit-sql`.")
        raise typer.Exit(code=1)
    try:
        return build_ddl(select_sql, target, dialect, materialization, warehouse=warehouse)
    except UnsupportedModelError as exc:
        _err(f"cannot generate DDL for {candidate_id}: {exc}")
        raise typer.Exit(code=1)


def _write_table_artifacts(outdir: Path, cand: dict, plans: dict, model_tml: dict,
                          db: str, schema: str, name: str, connection_name: str) -> None:
    from ts_cli.aggregate.generate import build_aggregate_table_spec
    from ts_cli.commands.tables import _build_table_tml
    spec = build_aggregate_table_spec(cand, plans, model_tml, db=db, schema=schema,
                                      table_name=name, connection_name=connection_name)
    (outdir / "table_spec.json").write_text(json.dumps(spec, indent=2))
    (outdir / "table.tml.yaml").write_text(_build_table_tml(spec))


def _write_model_artifact(outdir: Path, cand: dict, plans: dict, model_tml: dict,
                         name: str, connection_name: str) -> str:
    from ts_cli.aggregate.generate import build_aggregate_model_tml
    model_name = f"{model_tml['model']['name']} ({name})"
    agg_model = build_aggregate_model_tml(cand, plans, model_tml, agg_table_name=name,
                                          model_name=model_name,
                                          connection_name=connection_name)
    (outdir / "agg_model.tml.yaml").write_text(dump_tml_yaml(agg_model))
    return model_name


def _new_entry_date_grains(cand: dict) -> list:
    """The just-generated aggregate's date grains for `_patch_and_write_primary`'s
    new entry: `cand["date_grains"]` (Task 15 multi-date) when present, falling
    back to a 1-item list from the single-date `date_column`/`bucket` compat
    shim (Task 14) otherwise — same fallback pattern as generate.py's
    `_cand_date_grains`/`_entry_date_grains` (deliberately duplicated per that
    module's docstring, to keep each module's date-grain reading
    self-contained)."""
    grains = cand.get("date_grains")
    if grains is not None:
        return grains
    col = cand.get("date_column")
    return [{"column": col, "bucket": cand.get("bucket")}] if col else []


def _patch_and_write_primary(outdir: Path, model_guid: str, profile: Optional[str],
                            model_name: str, cand: dict,
                            agg_model_guid: Optional[str] = None) -> None:
    """Export the primary Model fresh (never reuse a cached copy — the patch
    must never clobber concurrent edits made since `signatures` last ran) and
    write the aggregated_models-patched TML. Reuses `_export_tml` (same
    non-printable-safe edoc parsing `signatures` uses) rather than hand-rolling
    the export + yaml.safe_load `client.post` and json.loads(edoc) the task
    brief's illustrative code used.

    Task 16 fix: the primary's EXISTING `aggregated_models` entries carry
    `date_aggregation_info` (the real live-TML shape), never `date_grains`/
    `date_column` — feeding them into `patch_association` unconverted reads no
    grains at all and silently strips their date association on re-patch.
    `date_aggregation_info_to_grains` (the inverse of `patch_association`'s
    emission mapping) reconstructs each existing entry's `date_grains` first,
    so re-patching preserves it byte-for-byte instead of stripping it. The new
    entry threads the just-generated aggregate's full multi-date list via
    `_new_entry_date_grains`, so a multi-date candidate's association is no
    longer collapsed to the single-date shim.

    Task 17 (Part B): the new entry's `id` must be the aggregate Model's GUID,
    not its display name — a live 26.x cluster confirmed the aggregate Model
    and its backing Table share a name, so a name-based id is ambiguous
    (`DUPLICATE_OBJECT_FOUND`). `agg_model_guid` only exists once the aggregate
    Model TML has actually been imported, which happens after `generate` first
    writes `agg_model.tml.yaml` — so the skill re-invokes `generate`
    (`--agg-model-guid <guid>`) once it has the GUID, to regenerate
    `primary_patched.tml.yaml` keyed correctly before importing it. When
    `agg_model_guid` is omitted (e.g. the first, pre-import pass, or a caller
    that hasn't been updated), fall back to `model_name` and warn on stderr —
    keeps this function usable standalone without forcing GUID-first ordering,
    but flags the ambiguity risk rather than silently accepting it."""
    from ts_cli.aggregate.generate import date_aggregation_info_to_grains, patch_association
    from ts_cli.client import ThoughtSpotClient, resolve_profile
    client = ThoughtSpotClient(resolve_profile(profile))
    primary = _export_tml(client, model_guid)
    existing = [
        {"id": e["id"], "date_grains": date_aggregation_info_to_grains(e),
         "projected_rows": None}
        for e in primary["model"].get("aggregated_models", []) or []
        if isinstance(e, dict)
    ]
    entry_id = agg_model_guid
    if not entry_id:
        _err(
            f"--agg-model-guid not provided; using name '{model_name}' as the "
            "aggregated_models id. This can be ambiguous — the aggregate Model "
            "and its backing Table share a name, so a name-based id can "
            "collide (DUPLICATE_OBJECT_FOUND). Import the aggregate Model TML "
            "first, then re-run with --agg-model-guid <the returned GUID>."
        )
        entry_id = model_name
    entries = existing + [{"id": entry_id, "date_grains": _new_entry_date_grains(cand),
                           "projected_rows": cand.get("agg_rows")}]
    patched = patch_association(primary, entries)
    (outdir / "primary_patched.tml.yaml").write_text(dump_tml_yaml(patched))


@app.command()
def generate(
    dir: str = typer.Option(..., "--dir"),
    candidate: str = typer.Option(..., help="Candidate id, e.g. cand_3"),
    model_guid: str = typer.Option(...),
    tables_dir: str = typer.Option(...),
    db: str = typer.Option(...),
    schema: str = typer.Option(...),
    connection_name: str = typer.Option(...),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE"),
    dialect: str = typer.Option("snowflake"),
    materialization: str = typer.Option("auto"),
    warehouse: Optional[str] = typer.Option(None),
    agg_name: Optional[str] = typer.Option(
        None, help="Override aggregate table/model base name"),
    out_dir: Optional[str] = typer.Option(None),
    agg_model_guid: Optional[str] = typer.Option(
        None, "--agg-model-guid",
        help="Aggregate Model's GUID, once known (import agg_model.tml.yaml first "
             "and pass its returned GUID here). Used as the aggregated_models "
             "association id in primary_patched.tml.yaml instead of the aggregate "
             "Model's display name, which is ambiguous — it collides with the "
             "equally-named backing Table (DUPLICATE_OBJECT_FOUND on a live "
             "cluster). Omit on the first, pre-import pass; a stderr warning "
             "flags the name-based fallback."),
    no_spotql: bool = typer.Option(
        False, "--no-spotql",
        help="Skip ThoughtSpot SpotQL SQL generation (Task 18's default path) "
             "and use the built-in join walker directly. That walker can be "
             "wrong on role-playing/ambiguous-path dimensions — use only when "
             "SpotQL generate-sql is known unavailable for this Model/profile."),
) -> None:
    """Emit DDL + Table TML + aggregate Model TML + patched primary TML.

    Never imports — writes `ddl.sql`, `table_spec.json`, `table.tml.yaml`,
    `agg_model.tml.yaml`, `primary_patched.tml.yaml` to `<out-dir>` (default
    `<dir>/<candidate>`). The skill gates each import separately.

    DDL SELECT source (Task 18): by default, builds a SpotQL statement for
    the candidate's grain and asks ThoughtSpot to compile it against the
    primary Model (`--model-guid`/`--profile`, reusing `ts spotql
    generate-sql`'s client path) — ThoughtSpot resolves joins against the
    full semantic model, so this is correct on role-playing/ambiguous-path
    dimensions where the built-in join walker (sqlgen.build_select) can be
    wrong. Falls back to that walker automatically if SpotQL generation is
    unavailable or errors, or always with `--no-spotql`; a fallback always
    prints a stderr note that the result may be wrong on such dimensions.
    """
    d = Path(dir)
    outdir = Path(out_dir or (d / candidate))
    outdir.mkdir(parents=True, exist_ok=True)

    cand, model_tml, table_tmls, plans = _read_generate_context(d, candidate, tables_dir)
    name = _aggregate_name(model_tml, cand, agg_name)
    target = f"{db}.{schema}.{name}"
    # Applies regardless of DDL source (SpotQL-wrapped or sqlgen fallback) —
    # neither wrap_as_ddl nor sqlgen.build_ddl enforces this on its own.
    _require_warehouse_for_dynamic_table(dialect, materialization, warehouse)

    ddl_text = None
    if not no_spotql:
        ddl_text = _spotql_ddl_or_none(model_tml, cand, plans, model_guid, profile,
                                       target, dialect, materialization, warehouse)
    if ddl_text is None:
        ddl_text = _fallback_ddl_or_exit(model_tml, table_tmls, cand, plans, dialect,
                                         target, materialization, warehouse, candidate)
    (outdir / "ddl.sql").write_text(ddl_text + ";\n")
    _write_table_artifacts(outdir, cand, plans, model_tml, db, schema, name, connection_name)
    model_name = _write_model_artifact(outdir, cand, plans, model_tml, name, connection_name)
    _patch_and_write_primary(outdir, model_guid, profile, model_name, cand, agg_model_guid)

    print(json.dumps({"candidate": candidate, "aggregate_name": name,
                      "files": sorted(p.name for p in outdir.iterdir())}, indent=2))
