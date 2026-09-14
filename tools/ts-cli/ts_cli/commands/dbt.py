"""ts dbt — dbt connection management and TML generation.

Wraps ThoughtSpot's native dbt integration (POST /api/rest/2.0/dbt/*, 9.9.0.cl+):
create/update a dbt connection (DBT_CLOUD or ZIP_FILE import), list/delete
connections, and generate TML from dbt models (first import or resync).

All five create/update/generate endpoints take multipart/form-data — every
field (including plain strings) is sent through `files=` as a `(None, value)`
tuple so requests always multipart-encodes the body, per client.py's
multipart-aware `_auth_headers`.
"""
from __future__ import annotations

import json
import re
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests as _requests
import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.dbt.cloud_api import (
    fetch_artifact,
    latest_successful_run,
    resolve_dbt_profile,
    token_from_keychain,
)
from ts_cli.dbt.artifacts import load_local_manifest, resolve_artifact_zip
from ts_cli.dbt.inspect import group_manifest_models
from ts_cli.profile_ops import get_profile, load_platform_profiles

app = typer.Typer(help="dbt connection management and TML generation.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")

_IMPORT_TYPES = ("DBT_CLOUD", "ZIP_FILE")


def _normalize_import_type(import_type: str) -> str:
    value = import_type.upper()
    if value not in _IMPORT_TYPES:
        raise SystemExit(f"--import-type must be one of {_IMPORT_TYPES}, got {import_type!r}.")
    return value


def _read_access_token(
    access_token_env: Optional[str],
    dbt_profile: Optional[dict] = None,
) -> Optional[str]:
    """Read the dbt Cloud API token.

    Resolution order (same as ThoughtSpotClient's credential lookup):
      1. Shell env var named by the profile's token_env (DBT_CLOUD_TOKEN_{SLUG}) —
         populated at shell start by the ~/.zshenv line `ts profiles add` emits,
         which reads Keychain via /usr/bin/security, the one app the item trusts.
      2. OS credential store via keyring, when the profile carries
         keychain_service + keychain_account. Reading from Python is the slow
         path: the item's partition list only trusts /usr/bin/security, so an
         unsigned interpreter triggers the macOS keychain-password prompt on
         every call.
      3. Shell env var named by access_token_env.

    Matches .claude/rules/security.md: the token is never accepted as a literal
    flag value — it always stays in Keychain or the shell environment.
    """
    if dbt_profile:
        token_env = dbt_profile.get("token_env")
        if token_env and os.environ.get(token_env):
            return os.environ[token_env]
        service = dbt_profile.get("keychain_service")
        account = dbt_profile.get("keychain_account")
        if service and account:
            try:
                import keyring  # deferred — graceful if not installed
                value = keyring.get_password(service, account)
                if value:
                    return value
            except Exception:
                pass

    if not access_token_env:
        return None
    token = os.environ.get(access_token_env)
    if not token:
        raise SystemExit(f"Env var {access_token_env} is not set or empty.")
    return token


def _load_dbt_profile(name: Optional[str]) -> Optional[dict]:
    """Load a dbt-cloud profile by name, or None if name is not given."""
    if not name:
        return None
    p = get_profile("dbt-cloud", name)
    if p is None:
        raise SystemExit(f"dbt-cloud profile {name!r} not found. Run `ts profiles list --dbt-cloud`.")
    return p


def _multipart_fields(fields: Dict[str, Optional[str]]) -> Dict[str, Any]:
    """Build the `files=` dict for a dbt form request, dropping unset fields.

    Scalar fields are wrapped as (None, value) so requests multipart-encodes
    them alongside any binary file_content entry the caller adds afterward.
    """
    return {k: (None, str(v)) for k, v in fields.items() if v is not None}


def _read_zip_file(file: Optional[str]) -> Optional[Path]:
    """Resolve `--file` to an upload-ready ZIP.

    Accepts a ready-made `.zip`, or the `target/` directory (or project root,
    or either artifact) — in which case `manifest.json` + `catalog.json` are
    zipped for you. See `ts_cli/dbt/artifacts.py`.
    """
    return resolve_artifact_zip(file)


@app.command("create")
def create_connection(
    connection_name: str = typer.Option(
        ..., "--connection-name",
        help="Display name of the EXISTING ThoughtSpot warehouse connection the dbt project "
             "builds into (e.g. 'se snowflake') — not a new label. See `ts connections list`."),
    database_name: str = typer.Option(
        ..., "--database-name",
        help="Database on that connection the dbt models are materialised in."),
    import_type: str = typer.Option("DBT_CLOUD", "--import-type",
                                     help="DBT_CLOUD (dbt Cloud API) or ZIP_FILE (dbt Core manifest+catalog)."),
    dbt_url: Optional[str] = typer.Option(None, "--dbt-url", help="dbt Cloud URL (required for DBT_CLOUD)."),
    account_id: Optional[str] = typer.Option(None, "--account-id", help="dbt Cloud account ID (required for DBT_CLOUD)."),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="dbt Cloud project ID (required for DBT_CLOUD)."),
    dbt_env_id: Optional[str] = typer.Option(None, "--dbt-env-id", help="dbt Cloud environment ID."),
    project_name: Optional[str] = typer.Option(None, "--project-name", help="Name of the dbt project."),
    access_token_env: Optional[str] = typer.Option(
        None, "--access-token-env",
        help="Env var holding the dbt Cloud API token (required for DBT_CLOUD). "
             "Never pass the token value directly."),
    dbt_cloud_profile: Optional[str] = typer.Option(
        None, "--dbt-cloud-profile",
        help="dbt-cloud profile name (from `ts profiles add --platform dbt-cloud`). "
             "Resolves the token from the OS credential store — alternative to --access-token-env."),
    file: Optional[str] = typer.Option(
        None, "--file", help="dbt Core artifacts to upload: the `target/` directory (manifest.json + catalog.json are zipped for you), either artifact, or a ready-made .zip. Required for --import-type ZIP_FILE."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Create a dbt connection object (POST /api/rest/2.0/dbt/dbt-connection)."""
    import_type = _normalize_import_type(import_type)
    dbt_prof = _load_dbt_profile(dbt_cloud_profile)
    access_token = _read_access_token(access_token_env, dbt_prof)
    zip_path = _read_zip_file(file)

    if import_type == "DBT_CLOUD" and not access_token:
        raise SystemExit(
            "--access-token-env or --dbt-cloud-profile is required when --import-type is DBT_CLOUD."
        )
    if import_type == "ZIP_FILE" and not zip_path:
        raise SystemExit("--file is required when --import-type is ZIP_FILE.")

    form = _multipart_fields({
        "connection_name": connection_name,
        "database_name": database_name,
        "import_type": import_type,
        "access_token": access_token,
        "dbt_url": dbt_url,
        "account_id": account_id,
        "project_id": project_id,
        "dbt_env_id": dbt_env_id,
        "project_name": project_name,
    })
    client = ThoughtSpotClient(resolve_profile(profile))
    if zip_path:
        with open(zip_path, "rb") as fh:
            form["file_content"] = (zip_path.name, fh, "application/zip")
            resp = client.post("/api/rest/2.0/dbt/dbt-connection", files=form)
    else:
        resp = client.post("/api/rest/2.0/dbt/dbt-connection", files=form)
    print(json.dumps(resp.json()))


@app.command("update")
def update_connection(
    connection_id: str = typer.Option(..., "--connection-id", help="dbt_connection_identifier to update."),
    connection_name: Optional[str] = typer.Option(None, "--connection-name"),
    database_name: Optional[str] = typer.Option(None, "--database-name"),
    import_type: Optional[str] = typer.Option(None, "--import-type", help="DBT_CLOUD or ZIP_FILE."),
    dbt_url: Optional[str] = typer.Option(None, "--dbt-url"),
    account_id: Optional[str] = typer.Option(None, "--account-id"),
    project_id: Optional[str] = typer.Option(None, "--project-id"),
    dbt_env_id: Optional[str] = typer.Option(None, "--dbt-env-id"),
    project_name: Optional[str] = typer.Option(None, "--project-name"),
    access_token_env: Optional[str] = typer.Option(
        None, "--access-token-env", help="Env var holding the dbt Cloud API token."),
    dbt_cloud_profile: Optional[str] = typer.Option(
        None, "--dbt-cloud-profile",
        help="dbt-cloud profile name. Resolves the token from the OS credential store."),
    file: Optional[str] = typer.Option(
        None, "--file",
        help="dbt Core artifacts to upload: the `target/` directory (manifest.json + catalog.json are zipped for you), either artifact, or a ready-made .zip. Pass refreshed artifacts to update the connection's copy."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Update a dbt connection object (POST /api/rest/2.0/dbt/update-dbt-connection)."""
    normalized_import_type = _normalize_import_type(import_type) if import_type else None
    dbt_prof = _load_dbt_profile(dbt_cloud_profile)
    access_token = _read_access_token(access_token_env, dbt_prof)
    zip_path = _read_zip_file(file)

    form = _multipart_fields({
        "dbt_connection_identifier": connection_id,
        "connection_name": connection_name,
        "database_name": database_name,
        "import_type": normalized_import_type,
        "access_token": access_token,
        "dbt_url": dbt_url,
        "account_id": account_id,
        "project_id": project_id,
        "dbt_env_id": dbt_env_id,
        "project_name": project_name,
    })
    client = ThoughtSpotClient(resolve_profile(profile))
    if zip_path:
        with open(zip_path, "rb") as fh:
            form["file_content"] = (zip_path.name, fh, "application/zip")
            resp = client.post("/api/rest/2.0/dbt/update-dbt-connection", files=form)
    else:
        resp = client.post("/api/rest/2.0/dbt/update-dbt-connection", files=form)
    if resp.text.strip():
        print(json.dumps(resp.json()))


@app.command("list")
def list_connections(profile: Optional[str] = _profile_option) -> None:
    """List dbt connection objects for the current user/org (POST /api/rest/2.0/dbt/search)."""
    client = ThoughtSpotClient(resolve_profile(profile))
    resp = client.post("/api/rest/2.0/dbt/search", json={})
    print(json.dumps(resp.json()))


@app.command("delete")
def delete_connection(
    connection_id: str = typer.Option(..., "--connection-id", help="dbt_connection_identifier to delete."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Delete a dbt connection object (POST /api/rest/2.0/dbt/{id}/delete).

    Output: empty on success (HTTP 204). Raises on error.
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    client.post(f"/api/rest/2.0/dbt/{connection_id}/delete", json={})


def _generate(
    path: str,
    connection_id: str,
    file: Optional[str],
    include_semantic_report: Optional[bool],
    profile: Optional[str],
    extra_fields: Optional[Dict[str, Optional[str]]] = None,
) -> None:
    zip_path = _read_zip_file(file)
    fields: Dict[str, Optional[str]] = {"dbt_connection_identifier": connection_id}
    if extra_fields:
        fields.update(extra_fields)
    fields["include_semantic_report"] = (
        ("true" if include_semantic_report else "false") if include_semantic_report is not None else None
    )
    form: Dict[str, Any] = _multipart_fields(fields)
    client = ThoughtSpotClient(resolve_profile(profile))
    if zip_path:
        with open(zip_path, "rb") as fh:
            form["file_content"] = (zip_path.name, fh, "application/zip")
            resp = client.post(path, files=form)
    else:
        resp = client.post(path, files=form)
    print(json.dumps(resp.json()))


@app.command("generate-tml")
def generate_tml(
    connection_id: str = typer.Option(..., "--connection-id", help="dbt_connection_identifier to generate TML for."),
    model_tables: str = typer.Option(
        ..., "--model-tables",
        help="JSON array grouping dbt models by directory. Each entry covers all models "
             "whose original_file_path shares the same parent directory. "
             "model_name=last dir segment, model_path=directory (not .sql file), "
             "tables=uppercase warehouse table names for all models in that dir. "
             'E.g. \'[{"model_name": "core", "model_path": "models/marts/core", '
             '"tables": ["DIM_CUSTOMERS", "FCT_ORDERS"]}]\'.'),
    import_worksheets: str = typer.Option(
        "ALL", "--import-worksheets", help="Which worksheet TML to import: ALL, NONE, or SELECTED."),
    worksheets: Optional[str] = typer.Option(
        None, "--worksheets",
        help="JSON array of worksheet names to import. Required when --import-worksheets is SELECTED, "
             'e.g. \'["orders_worksheet"]\'.'),
    file: Optional[str] = typer.Option(
        None, "--file",
        help="dbt Core artifacts to upload: the `target/` directory (manifest.json + catalog.json are zipped for you), either artifact, or a ready-made .zip. Required if the connection's import_type is ZIP_FILE."),
    include_semantic_report: Optional[bool] = typer.Option(
        None, "--include-semantic-report/--no-include-semantic-report",
        help="Include a per-model import/skip breakdown. Snowflake and Databricks connections only."),
    profile: Optional[str] = _profile_option,
) -> None:
    """First-import TML generation (POST /api/rest/2.0/dbt/generate-tml).

    Generates and imports Table/Worksheet TML for the dbt models and tables
    named in --model-tables. Use `generate-sync-tml` to resync an existing import.
    """
    normalized_import_worksheets = import_worksheets.upper()
    if normalized_import_worksheets not in ("ALL", "NONE", "SELECTED"):
        raise SystemExit(
            f"--import-worksheets must be one of ALL, NONE, SELECTED, got {import_worksheets!r}.")
    if normalized_import_worksheets == "SELECTED" and not worksheets:
        raise SystemExit("--worksheets is required when --import-worksheets is SELECTED.")
    _generate(
        "/api/rest/2.0/dbt/generate-tml", connection_id, file, include_semantic_report, profile,
        extra_fields={
            "model_tables": model_tables,
            "import_worksheets": normalized_import_worksheets,
            "worksheets": worksheets,
        },
    )


@app.command("generate-sync-tml")
def generate_sync_tml(
    connection_id: str = typer.Option(..., "--connection-id", help="dbt_connection_identifier to resync."),
    file: Optional[str] = typer.Option(
        None, "--file",
        help="dbt Core artifacts to upload: the `target/` directory (manifest.json + catalog.json are zipped for you), either artifact, or a ready-made .zip. Required if the connection's import_type is ZIP_FILE."),
    include_semantic_report: Optional[bool] = typer.Option(
        None, "--include-semantic-report/--no-include-semantic-report",
        help="Include a per-model import/skip breakdown. Snowflake and Databricks connections only."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Resync TML generation (POST /api/rest/2.0/dbt/generate-sync-tml).

    Resynchronizes the existing Table/Model/Worksheet TML for the dbt
    connection object against the current state of the dbt project.
    """
    _generate("/api/rest/2.0/dbt/generate-sync-tml", connection_id, file, include_semantic_report, profile)


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — testable without a dbt Cloud connection)
# ---------------------------------------------------------------------------

def _group_manifest_models(manifest: dict, use_alias: bool = True) -> list:
    """Deprecated alias — the implementation moved to `ts_cli.dbt.inspect`.

    Kept so existing import sites and tests are unchanged; new callers should
    import :func:`ts_cli.dbt.inspect.group_manifest_models` directly.
    """
    return group_manifest_models(manifest, use_alias=use_alias)


# ---------------------------------------------------------------------------
# ts dbt list-models
# ---------------------------------------------------------------------------

def _token_from_keychain(slug: str) -> Optional[str]:
    """Deprecated alias — moved to `ts_cli.dbt.cloud_api.token_from_keychain`."""
    return token_from_keychain(slug)


@app.command("list-models")
def list_models(
    dbt_cloud_profile: Optional[str] = typer.Option(
        None, "--dbt-cloud-profile",
        help="dbt Cloud profile name (reads account-id, project-id, dbt-env-id, "
             "dbt-url, and token directly from keychain — no env var needed)."),
    manifest_path: Optional[str] = typer.Option(
        None, "--manifest",
        help="Read a LOCAL manifest.json instead of downloading one: the file, a "
             "target/ directory, or a dbt project ZIP. The ZIP_FILE path — no dbt "
             "Cloud profile or token needed."),
    use_alias: bool = typer.Option(
        True, "--alias/--no-alias",
        help="Emit each model's `alias` (what dbt materialises, and the only name "
             "ThoughtSpot matches) rather than its file name. Default: --alias. "
             "Use --no-alias only for a project whose manifest aliases are wrong."),
    account_id: Optional[str] = typer.Option(None, "--account-id", help="dbt Cloud account ID (override)."),
    project_id: Optional[str] = typer.Option(None, "--project-id", help="dbt Cloud project ID (override)."),
    access_token_env: Optional[str] = typer.Option(
        None, "--access-token-env",
        help="Env var holding the dbt Cloud API token (alternative to --dbt-cloud-profile)."),
    dbt_env_id: Optional[str] = typer.Option(None, "--dbt-env-id", help="dbt Cloud environment ID (override)."),
    dbt_url: Optional[str] = typer.Option(None, "--dbt-url", help="dbt Cloud base URL (override)."),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Re-download the manifest even if this run's copy is cached."),
) -> None:
    """Print --model-tables JSON for a dbt project's model directories.

    Groups every model node by its parent directory and emits a JSON array
    ready to paste as --model-tables for `ts dbt generate-tml`.

    Source of the manifest:
      --manifest <path>      a local file / target dir / project ZIP (offline)
      --dbt-cloud-profile    the latest SUCCESSFUL run's artifact (token from
                             the OS keychain — preferred)
      --access-token-env     same, with the token from the named env var

    Table names come from each model's `alias` (see --alias): a project that
    sets `alias:` materialises under that name, and passing the file name
    instead fails `generate-tml` with a 400 listing tables that "do not exist".
    """
    if manifest_path:
        manifest = load_local_manifest(manifest_path)
        source = manifest_path
    else:
        ctx = resolve_dbt_profile(
            dbt_cloud_profile, account_id=account_id, project_id=project_id,
            dbt_env_id=dbt_env_id, dbt_url=dbt_url, access_token_env=access_token_env)
        run_id = latest_successful_run(ctx)
        manifest = fetch_artifact(ctx, run_id, "manifest.json", use_cache=not no_cache)
        source = f"run {run_id}"

    model_tables = group_manifest_models(manifest, use_alias=use_alias)
    if not model_tables:
        raise SystemExit(f"No model nodes found in manifest ({source}).")

    print(json.dumps(model_tables, indent=2))


def _resolve_table_guids(
    client: Any,
    locations: Dict[str, dict],
    table_names: "list[str]",
) -> Dict[str, str]:
    """Resolve ThoughtSpot Table names to GUIDs, disambiguating duplicates.

    For each name: POST metadata/search (type LOGICAL_TABLE). One exact-name
    hit → its GUID. Several hits (the Org already holds a same-named Table,
    e.g. a raw source table alongside the dbt view) → export each candidate's
    TML and keep the one whose ``db``/``schema``/``db_table`` match the
    manifest's ``database``/``schema``/``alias`` for that model. Still
    ambiguous → SystemExit listing the candidates. No hit → warn on stderr
    and leave the name unresolved (the caller falls back to a name-only ref).
    """
    import sys
    import yaml as _yaml

    resolved: Dict[str, str] = {}
    for name in table_names:
        resp = client.post(
            "/api/rest/2.0/metadata/search",
            json={
                "metadata": [{"identifier": name, "type": "LOGICAL_TABLE"}],
                "record_size": -1,
            },
        )
        hits = resp.json() if isinstance(resp.json(), list) else []
        cands = [
            h["metadata_id"] for h in hits
            if (h.get("metadata_header") or {}).get("name", "").upper() == name.upper()
            and h.get("metadata_id")
        ]
        if not cands:
            print(f"  Warning: no LOGICAL_TABLE named {name!r} found — "
                  "model_tables ref left name-only.", file=sys.stderr)
            continue
        if len(cands) == 1:
            resolved[name] = cands[0]
            continue

        loc = locations.get(name.upper()) or {}
        want = tuple((loc.get(k) or "").upper() for k in ("database", "schema", "db_table"))
        export = client.post(
            "/api/rest/2.0/metadata/tml/export",
            json={
                "metadata": [{"identifier": g, "type": "LOGICAL_TABLE"} for g in cands],
                "export_fqn": False,
                "export_associated_objects": "NONE",
            },
        )
        items = export.json() if isinstance(export.json(), list) else []
        seen: Dict[str, tuple] = {}
        for item in items:
            edoc = item.get("edoc")
            guid = (item.get("info") or {}).get("id")
            if not edoc or not guid:
                continue
            tbl = (_yaml.safe_load(edoc) or {}).get("table") or {}
            seen[guid] = tuple(
                (tbl.get(k) or "").upper() for k in ("db", "schema", "db_table"))
        matches = [g for g, have in seen.items() if have == want]
        if len(matches) == 1:
            resolved[name] = matches[0]
            print(f"  {name}: {len(cands)} same-named Tables — picked "
                  f"{matches[0]} ({'.'.join(want)})", file=sys.stderr)
            continue
        listing = "\n".join(f"    {g}  {'.'.join(have) or '(no location)'}" for g, have in seen.items())
        raise SystemExit(
            f"Found {len(cands)} LOGICAL_TABLE objects named {name!r} and "
            f"{'none' if not matches else len(matches)} match the manifest location "
            f"{'.'.join(want)}:\n{listing}\n"
            "Delete or rename the stale duplicates, or make sure `ts dbt generate-tml` "
            "imported this Table from the same warehouse location the dbt job built."
        )
    return resolved


@app.command("build-model")
def build_model(
    dbt_cloud_profile: Optional[str] = typer.Option(
        None, "--dbt-cloud-profile",
        help="dbt Cloud profile name (reads account-id, project-id, dbt-env-id, "
             "dbt-url, and token from keychain)."),
    model_path: str = typer.Option(
        ..., "--model-path",
        help="Directory path in the manifest, e.g. models/staging/barbershop."),
    model_name: str = typer.Option(
        ..., "--model-name",
        help="Name for the ThoughtSpot Model, e.g. BARBERSHOP_OPERATIONS."),
    pretty_names: bool = typer.Option(
        False, "--pretty-names",
        help="Title-case column display names and replace underscores with spaces "
             "(APPOINTMENT_DATETIME -> 'Appointment Datetime'; ID stays upper-case). "
             "A column's ts_display_name meta tag always overrides. column_id is unchanged."),
    model_guid: Optional[str] = typer.Option(
        None, "--model-guid",
        help="Update this existing Model in place (sets guid in the TML and imports "
             "with create_new=false) instead of creating a new Model."),
    metrics: bool = typer.Option(
        True, "--metrics/--no-metrics",
        help="Translate MetricFlow metrics (manifest semantic_models/metrics, dbt v2 "
             "spec) into Model formulas — simple, ratio and derived types. A metric "
             "whose label matches a ts_formula column supersedes it. Unmapped metrics "
             "are listed on stderr, never dropped silently. --no-metrics skips this."),
    no_cache: bool = typer.Option(
        False, "--no-cache",
        help="Re-download manifest.json/catalog.json even if this run's copies are cached."),
    profile: Optional[str] = _profile_option,
) -> None:
    """Build and import a unified Model TML from dbt Cloud job artifacts.

    Downloads manifest.json + catalog.json from the latest successful run,
    reads ts_join_* relationship tests to assemble a single unified Model TML
    (plus MetricFlow metrics as formulas, unless --no-metrics), and imports it
    via POST /api/rest/2.0/metadata/tml/import.

    Run after `ts dbt generate-tml --import-worksheets NONE` has created the
    Table objects — this step assembles the Model that joins them.
    """
    import sys
    import yaml as _yaml
    from ts_cli.dbt_build_export import (
        apply_table_fqns,
        build_model_tml_from_manifest,
        extract_model_rls_from_manifest,
        find_display_name_collisions,
        manifest_table_locations,
    )

    if not dbt_cloud_profile:
        raise SystemExit("--dbt-cloud-profile is required.")

    ctx = resolve_dbt_profile(dbt_cloud_profile)
    run_id = latest_successful_run(ctx)
    manifest = fetch_artifact(ctx, run_id, "manifest.json", use_cache=not no_cache)
    catalog = fetch_artifact(ctx, run_id, "catalog.json", use_cache=not no_cache)

    model_tml = build_model_tml_from_manifest(
        manifest, catalog, model_path, model_name,
        pretty_names=pretty_names, metrics=metrics)
    excluded = model_tml.pop("_excluded_columns", [])
    if excluded:
        print(f"  ts_column_exclude: {len(excluded)} column(s) left out of the Model — "
              + ", ".join(excluded), file=sys.stderr)
    inferred = model_tml.pop("_inferred_columns", [])
    if inferred:
        print(f"  {len(inferred)} column(s) without ts_* meta typed from catalog.json "
              "(numeric → measure/sum, else attribute): " + ", ".join(inferred[:12])
              + (" …" if len(inferred) > 12 else ""), file=sys.stderr)
    for rn in model_tml.pop("_inferred_renames", []):
        print(f"  {rn['column_id']}: display name {rn['from']!r} collides with a metric formula — "
              f"column renamed to {rn['to']!r} (declare the column with ts_display_name to choose)",
              file=sys.stderr)
    mf = model_tml.pop("_metrics_report", None)
    if mf:
        if mf["formulas"]:
            print(f"  MetricFlow: {len(mf['formulas'])} metric(s) translated to formulas — "
                  + ", ".join(f["name"] for f in mf["formulas"]), file=sys.stderr)
        if mf["superseded"]:
            print(f"  MetricFlow: {len(mf['superseded'])} ts_formula column(s) superseded by a "
                  "same-named metric — " + ", ".join(mf["superseded"]), file=sys.stderr)
        for u in mf["unmapped"]:
            print(f"  MetricFlow: metric {u['metric']!r} ({u['type']}) NOT translated — "
                  f"{u['reason']}", file=sys.stderr)
        for ej in mf.get("entity_joins") or []:
            print(f"  MetricFlow: join {ej['source']} → {ej['target']} derived from entity "
                  f"{ej['entity']!r} (no ts_join_* relationships test covers this pair; "
                  "LEFT_OUTER / MANY_TO_ONE)", file=sys.stderr)
    if model_guid:
        # guid belongs at the document root (see thoughtspot-model-tml.md), not under model:
        model_tml = {"guid": model_guid, **model_tml}

    # ThoughtSpot rejects the whole import (ALL_OR_NONE) when two columns share a
    # display name, case-insensitively — typically a ts_display_name that lands on
    # the prettified name of a sibling column. Catch it here with the physical
    # refs, which the API's "Multiple columns with the same name found" doesn't give.
    collisions = find_display_name_collisions(model_tml)
    if collisions:
        listing = "\n".join(f"  {name!r}: {', '.join(refs)}" for name, refs in collisions)
        raise SystemExit(
            "Display-name collision — ThoughtSpot compares Model column names "
            f"case-insensitively:\n{listing}\n"
            "Give one of each pair a distinct ts_display_name in schema.yml, "
            "re-run the dbt job, then re-run build-model.")

    # Pin every model_tables[] ref with an fqn. A name-only ref imports fine in
    # a clean Org but fails (error 14502) as soon as a same-named Table exists —
    # common when the raw source tables were registered before the dbt views.
    client = ThoughtSpotClient(resolve_profile(profile))
    table_guids = _resolve_table_guids(
        client,
        manifest_table_locations(manifest),
        [e["name"] for e in model_tml["model"]["model_tables"]],
    )
    apply_table_fqns(model_tml, table_guids)
    tml_yaml = _yaml.dump(model_tml, sort_keys=False, allow_unicode=True)

    resp = client.post(
        "/api/rest/2.0/metadata/tml/import",
        json={
            "metadata_tmls": [tml_yaml],
            "import_policy": "ALL_OR_NONE",
            "create_new": not model_guid,
        },
    )
    print(json.dumps(resp.json()))
    import_objects = resp.json() if isinstance(resp.json(), list) else []
    failed = [
        o for o in import_objects
        if ((o.get("response") or {}).get("status") or {}).get("status_code") == "ERROR"]
    if failed:
        msg = ((failed[0].get("response") or {}).get("status") or {}).get("error_message", "")
        raise SystemExit(f"Model import failed: {msg[:500]}")

    # Apply ts_rls_rules to Table TMLs (model-level config.meta tag).
    # ThoughtSpot's server-side generate-tml does not process this tag; the CLI
    # handles it by exporting each affected Table TML, patching in rls_rules, and
    # re-importing.
    rls_by_table = extract_model_rls_from_manifest(manifest, model_path)
    for table_name, rls_block in rls_by_table.items():
        print(f"Applying ts_rls_rules to {table_name}...", file=sys.stderr)
        export_resp = client.post(
            "/api/rest/2.0/metadata/tml/export",
            json={
                # GUID when resolved — a name identifier 409s (DUPLICATE_OBJECT_FOUND)
                # whenever the Org holds another Table with this name.
                "metadata": [{"identifier": table_guids.get(table_name, table_name),
                              "type": "LOGICAL_TABLE"}],
                "export_fqn": False,
                "export_associated_objects": "NONE",
            },
        )
        items = export_resp.json() if isinstance(export_resp.json(), list) else []
        if not items or not items[0].get("edoc"):
            print(
                f"  Warning: could not export Table TML for {table_name} "
                f"({export_resp.status_code}) — ts_rls_rules skipped.",
                file=sys.stderr,
            )
            continue
        table_tml_dict = _yaml.safe_load(items[0]["edoc"])
        table_tml_dict.setdefault("table", {})["rls_rules"] = rls_block
        patched_tml = _yaml.dump(table_tml_dict, sort_keys=False, allow_unicode=True)
        rls_resp = client.post(
            "/api/rest/2.0/metadata/tml/import",
            json={
                "metadata_tmls": [patched_tml],
                "import_policy": "ALL_OR_NONE",
                "create_new": False,
            },
        )
        rls_objects = rls_resp.json() if isinstance(rls_resp.json(), list) else []
        status = (rls_objects[0] if rls_objects else {}).get("response", {}).get(
            "status", {}
        ).get("status_code", "unknown")
        print(f"  {table_name}: RLS import status = {status}", file=sys.stderr)


# ---------------------------------------------------------------------------
# ts dbt trigger-job
# ---------------------------------------------------------------------------

_RUN_STATUS_TERMINAL = {10: "Success", 20: "Error", 30: "Cancelled"}
_RUN_STATUS_LABELS = {1: "Queued", 2: "Starting", 3: "Running", **_RUN_STATUS_TERMINAL}
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_LOG_NOISE_RE = re.compile(r"Sending event:|Observability Metric:|Resource report:")


def failed_step_log_excerpt(run_steps: list, max_lines: int = 40) -> str:
    """Human-readable excerpt of the first failed dbt Cloud run step's log.

    Pure function over the ``run_steps`` list of a
    ``GET /runs/{id}/?include_related=["run_steps"]`` response. Picks the first
    step whose status is Error/Cancelled, strips ANSI colour codes and tracking
    noise, and returns the step name plus the last ``max_lines`` non-empty log
    lines — enough to see e.g. every ``Invalid name …`` line that precedes a
    ``Semantic Manifest validation failed`` parsing error. Empty string when no
    step failed or the step carries no log text.
    """
    for step in run_steps or []:
        status = step.get("status")
        label = step.get("status_humanized") or _RUN_STATUS_LABELS.get(status, "")
        if status not in (20, 30) and label not in ("Error", "Cancelled"):
            continue
        raw = step.get("logs") or step.get("debug_logs") or ""
        lines = [
            _ANSI_RE.sub("", ln).rstrip()
            for ln in raw.splitlines()
            if ln.strip() and not _LOG_NOISE_RE.search(ln)
        ]
        if not lines:
            return f"Failed step: {step.get('name', '?')} (no log text returned)"
        tail = lines[-max_lines:]
        return f"Failed step: {step.get('name', '?')}\n" + "\n".join(tail)
    return ""


@app.command("trigger-job")
def trigger_job(
    dbt_cloud_profile: Optional[str] = typer.Option(
        None, "--dbt-cloud-profile",
        help="dbt Cloud profile name (reads account-id, project-id, dbt-url, "
             "and token from keychain)."),
    job_id: Optional[int] = typer.Option(
        None, "--job-id",
        help="dbt Cloud job ID to trigger. Omit to list available jobs and exit."),
    wait: bool = typer.Option(
        True, "--wait/--no-wait",
        help="Wait for the run to complete before returning (default: True)."),
    poll_interval: int = typer.Option(
        15, "--poll-interval",
        help="Seconds between status polls when --wait (default: 15)."),
    cause: str = typer.Option(
        "triggered by ts-cli", "--cause",
        help="Human-readable cause string attached to the run."),
) -> None:
    """Trigger a dbt Cloud job run and wait for completion.

    When --job-id is omitted, lists available jobs for the profile's project
    as JSON and exits — re-run with --job-id {id} to trigger one.

    Run before ts dbt generate-tml or ts dbt build-model to ensure the latest
    schema.yml changes (description, ts_ai_context, etc.) are compiled into
    the manifest and catalog artifacts.
    """
    import time

    if not dbt_cloud_profile:
        raise SystemExit("--dbt-cloud-profile is required.")

    ctx = resolve_dbt_profile(dbt_cloud_profile)
    account_id, project_id, base = ctx.account_id, ctx.project_id, ctx.base
    headers = ctx.headers

    # List-only mode: no --job-id supplied
    if job_id is None:
        jobs_resp = _requests.get(
            f"{base}/api/v2/accounts/{account_id}/jobs/",
            headers=headers, params={"project_id": project_id})
        if not jobs_resp.ok:
            raise SystemExit(
                f"dbt Cloud API error listing jobs ({jobs_resp.status_code}): "
                f"{jobs_resp.text}")
        jobs = jobs_resp.json().get("data", [])
        if not jobs:
            raise SystemExit(f"No jobs found for project {project_id}.")

        # Fetch the most recent successful run per job (one extra call)
        runs_resp = _requests.get(
            f"{base}/api/v2/accounts/{account_id}/runs/",
            headers=headers,
            params={"project_id": project_id, "order_by": "-created_at", "limit": "100"})
        last_success: Dict[int, str] = {}
        if runs_resp.ok:
            for run in runs_resp.json().get("data", []):
                if run.get("status") != 10:
                    continue
                jid = run.get("job_definition_id")
                if jid and jid not in last_success:
                    last_success[jid] = run.get("finished_at") or run.get("created_at") or ""

        print(json.dumps(
            [{"id": j["id"], "name": j.get("name", ""),
              "description": j.get("description", ""),
              "last_successful_run": last_success.get(j["id"], None)}
             for j in jobs],
            indent=2,
        ))
        typer.echo("\nRe-run with --job-id {id} to trigger one of the jobs above.", err=True)
        return

    # Trigger the run
    trigger_resp = _requests.post(
        f"{base}/api/v2/accounts/{account_id}/jobs/{job_id}/run/",
        headers=headers,
        json={"cause": cause})
    if not trigger_resp.ok:
        raise SystemExit(
            f"Failed to trigger job {job_id} ({trigger_resp.status_code}): "
            f"{trigger_resp.text}")
    run_data = trigger_resp.json().get("data", {})
    run_id = run_data.get("id")
    typer.echo(f"Triggered run {run_id} for job {job_id}.", err=True)

    if not wait:
        print(json.dumps({"run_id": run_id, "job_id": job_id, "status": "triggered"}))
        return

    # Poll until terminal state
    typer.echo(
        f"Waiting for run {run_id} to complete (polling every {poll_interval}s)...",
        err=True)
    while True:
        time.sleep(poll_interval)
        poll_resp = _requests.get(
            f"{base}/api/v2/accounts/{account_id}/runs/{run_id}/",
            headers=headers)
        if not poll_resp.ok:
            raise SystemExit(
                f"Error polling run {run_id} ({poll_resp.status_code}): {poll_resp.text}")
        run_info = poll_resp.json().get("data", {})
        status = run_info.get("status")
        label = _RUN_STATUS_LABELS.get(status, str(status))
        typer.echo(f"  Run {run_id}: {label}", err=True)
        if status in _RUN_STATUS_TERMINAL:
            if status != 10:
                # One more call for the step logs — the poll response has none.
                steps_resp = _requests.get(
                    f"{base}/api/v2/accounts/{account_id}/runs/{run_id}/",
                    headers=headers, params={"include_related": '["run_steps"]'})
                excerpt = ""
                if steps_resp.ok:
                    excerpt = failed_step_log_excerpt(
                        (steps_resp.json().get("data") or {}).get("run_steps") or [])
                if excerpt:
                    typer.echo(excerpt, err=True)
                raise SystemExit(
                    f"Run {run_id} ended with status {label!r}. "
                    + ("See the failed-step log above." if excerpt
                       else "Check dbt Cloud for details before proceeding."))
            print(json.dumps({
                "run_id": run_id,
                "job_id": job_id,
                "status": label,
                "finished_at": run_info.get("finished_at"),
            }))
            return
