"""ts aggregate — aggregate-model advisor (signatures/recommend/profile/generate/history).

`signatures` and `recommend` are implemented here (Task 7). `profile`, `generate`,
and `history` are registered as stubs (exit code 2) so the command group's shape
is stable for skill authoring; Task 8 fills in their bodies.
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
    model_tml = yaml.safe_load((d / "model.tml.yaml").read_text())
    sigs = [json.loads(line) for line in
            (d / "signatures.jsonl").read_text().splitlines() if line.strip()]
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


@app.command()
def profile() -> None:
    """Profile top candidates against the warehouse (Task 8)."""
    _err("`ts aggregate profile` is not implemented yet — see Task 8.")
    raise typer.Exit(code=2)


@app.command()
def generate() -> None:
    """Generate DDL + TML for an approved candidate (Task 8)."""
    _err("`ts aggregate generate` is not implemented yet — see Task 8.")
    raise typer.Exit(code=2)


@app.command()
def history() -> None:
    """Mine warehouse query history into signature weights (Task 8)."""
    _err("`ts aggregate history` is not implemented yet — see Task 8.")
    raise typer.Exit(code=2)
