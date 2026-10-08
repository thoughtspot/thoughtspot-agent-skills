"""`ts dbt inspect` — what is in a dbt model directory, and which path to take.

Attaches to `commands/dbt.py`'s `app` (the `publish_planning.py` /
`share_planning.py` / `aggregate_rls.py` pattern) rather than living in it:
`commands/dbt.py` is already past the `check_file_size` warn line, and this is
a self-contained read.

Replaces the 31-line inline block `ts-convert-from-dbt` Step 8-pre asked the
LLM to write — a manifest download the block described only as a comment, plus
a hand-rolled scan whose predicates had to match `build-model`'s by hand. All
of the logic is in the pure `ts_cli.dbt.inspect`; this module is I/O only.
"""
from __future__ import annotations

import json
from typing import Optional

import typer

from ts_cli.commands.dbt import app, load_local_manifest
from ts_cli.dbt.cloud_api import fetch_artifact, latest_successful_run, resolve_dbt_profile
from ts_cli.dbt.inspect import inspect_manifest


@app.command("inspect")
def inspect_cmd(
    model_path: str = typer.Option(
        ..., "--model-path",
        help="Directory path in the manifest, e.g. models/staging/barbershop."),
    dbt_cloud_profile: Optional[str] = typer.Option(
        None, "--dbt-cloud-profile",
        help="dbt Cloud profile name (reads coordinates and token from the keychain)."),
    manifest_path: Optional[str] = typer.Option(
        None, "--manifest",
        help="Read a LOCAL manifest.json instead of downloading one: the file, a "
             "target/ directory, or a dbt project ZIP. No profile or token needed."),
    access_token_env: Optional[str] = typer.Option(
        None, "--access-token-env",
        help="Env var holding the dbt Cloud API token (alternative to --dbt-cloud-profile)."),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Re-download the manifest even if this run's copy is cached."),
) -> None:
    """Inspect one model directory in a compiled manifest and recommend Path N or Y.

    Read-only. Writes nothing, calls no ThoughtSpot API, and needs no
    ThoughtSpot profile.

    \\b
    stdout JSON:
      models[]             each model in the directory: name, alias, the
                           ThoughtSpot Table name it maps to, database, schema
      ts_join_tests[]      relationship tests carrying ts_join_* meta —
                           from/to/column/field plus the meta itself
      rls_models[]         models carrying model-level ts_rls_rules
      metricflow_metrics[] in-scope MetricFlow metrics (name, type, label)
      recommended_path     "Y" (assemble the Model client-side with
                           `ts dbt build-model`) or "N" (let ThoughtSpot's
                           `ts dbt generate-tml` do it)
      reasons[]            why — one line per signal that decided the verdict

    Path Y is recommended whenever the directory holds something only the
    client-side assembly preserves: a ts_join_* join graph (generate-tml
    would split the directory into one Model per FK-source table),
    model-level ts_rls_rules (the server-side sync does not read the tag), or
    MetricFlow metrics (only build-model turns them into Model formulas).

    These are read from the COMPILED manifest, not from schema.yml — a
    schema.yml edit needs a dbt job run (`ts dbt trigger-job`) before it shows
    up here.

    \\b
    Example:
      ts dbt inspect --dbt-cloud-profile barbershop \\
        --model-path models/staging/barbershop
    """
    if manifest_path:
        manifest = load_local_manifest(manifest_path)
        source = {"manifest": manifest_path}
    else:
        ctx = resolve_dbt_profile(dbt_cloud_profile, access_token_env=access_token_env)
        run_id = latest_successful_run(ctx)
        manifest = fetch_artifact(ctx, run_id, "manifest.json", use_cache=not no_cache)
        source = {"run_id": run_id}

    report = inspect_manifest(manifest, model_path)

    if not report["models"]:
        typer.echo(
            f"  No model nodes found under {model_path!r}. Check the path against "
            "`ts dbt list-models` — it must be the directory, not a model name.",
            err=True)

    typer.echo(
        f"  models: {len(report['models'])}   "
        f"ts_join_* tests: {len(report['ts_join_tests'])}   "
        f"ts_rls_rules: {len(report['rls_models'])}   "
        f"MetricFlow metrics: {len(report['metricflow_metrics'])}",
        err=True)
    typer.echo(f"  recommended path: {report['recommended_path']}", err=True)
    for reason in report["reasons"]:
        typer.echo(f"    - {reason}", err=True)

    print(json.dumps({**source, **report}, indent=2))
