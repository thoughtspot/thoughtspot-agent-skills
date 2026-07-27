from __future__ import annotations

import json
import sys
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Migrate tenant content between ThoughtSpot Orgs.")

_source_profile = typer.Option(None, "--source-profile", envvar="TS_PROFILE",
                               help="Profile for the source (old tenant) Org.")
_target_profile = typer.Option(None, "--target-profile",
                               help="Profile for the target (clean) Org.")


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.stderr.flush()


@app.command("audit")
def audit(
    source_profile: Optional[str] = _source_profile,
    target_profile: Optional[str] = _target_profile,
    source_org: Optional[str] = typer.Option(None, "--source-org", help="Source Org (name or numeric id)."),
    target_org: Optional[str] = typer.Option(None, "--target-org", help="Target Org (name or numeric id)."),
    model: List[str] = typer.Option([], "--model", "-m", help="Source Model GUID(s) to audit."),
    all_models: bool = typer.Option(False, "--all-models", help="Audit every Model in the source Org."),
    out_dir: str = typer.Option(..., "--out-dir", "-o", help="Directory for column-mapping.csv + audit report."),
) -> None:
    """Read-only audit: compare tenant Models/columns to the clean Org's published Models.

    Writes column-mapping.csv (review + fill gaps), audit-report.json, audit-report.md.
    """
    from ts_cli.migrate import discover, run_audit

    # Org scoping uses the client's own `org` keyword, which landed on main (PR #346) with
    # a live-verified detail this branch's earlier version did not have: `auth/token/full`
    # SILENTLY IGNORES a non-numeric `org_identifier` and falls back to the caller's default
    # Org. `_org_auth_fields` resolves that, so a name is safe to pass here.
    #
    # Resolving a name to its numeric id and asserting the session afterwards is what
    # `ts share`'s `_resolve_org_id` / `assert_org_context` do; `apply` (Phase 2) must use
    # them before any WRITE, because migrating a tenant's content into the wrong Org while
    # reporting success is this command's worst failure mode. `audit` is read-only, so a
    # wrong-Org read is recoverable and the assertion is deferred rather than skipped.
    source_client = ThoughtSpotClient(resolve_profile(source_profile), org=source_org)
    target_client = ThoughtSpotClient(resolve_profile(target_profile), org=target_org)

    model_guids = list(model)
    if all_models:
        model_guids = [m["guid"] for m in discover.list_models(source_client)]
    if not model_guids:
        _err("No models to audit. Pass --model <guid> (repeatable) or --all-models.")
        raise typer.Exit(code=1)

    report = run_audit(source_client, target_client, model_guids, out_dir)
    print(json.dumps(report, indent=2))
    ready = "READY" if report["overall_ready"] else "NEEDS MAPPING"
    _err(f"Audit complete: {len(report['models'])} model(s), overall {ready}. Files in {out_dir}")


def _owning_org_id(client) -> Optional[int]:
    """Numeric id of the Org this client's session is actually in.

    Read back from the session rather than assumed from the `--source-org` argument,
    because `auth/token/full` silently ignores a non-numeric org identifier and falls back
    to the caller's default Org. Attributing a scan to the Org that was ASKED for rather
    than the one it ran in would mislabel every blocked Model in the report.
    """
    try:
        current = (client.get("/api/rest/2.0/auth/session/user").json()
                   or {}).get("current_org") or {}
        return current.get("id")
    except (Exception, SystemExit):
        return None


def _resolve_scan_models(client, model: List[str], all_models: bool,
                         models_file: Optional[str],
                         models_table: Optional[str], sf_profile: Optional[str]) -> List[dict]:
    """`[{"guid","name"}]` for the Models to scan, from whichever scoping form was used.

    `--all-models` is the fleet case; the manifest forms let a targeted list of
    migration-candidate Models be scanned without sweeping every Model on the cluster.
    """
    from ts_cli.migrate import discover

    if all_models:
        # Restrict to Models this Org OWNS. Without it a Primary-owned Model is counted
        # once per tenant Org and reported as each tenant's blocker -- observed live.
        return discover.list_models(client, owner_org_id=_owning_org_id(client))

    identifiers = list(model)
    if models_file:
        import csv
        from pathlib import Path
        with open(Path(models_file), newline="") as handle:
            identifiers += [(r.get("identifier") or r.get("model") or "").strip()
                            for r in csv.DictReader(handle)]
    if models_table:
        from ts_cli.commands.load import get_sf_cursor        # lazy: Snowflake is optional
        cursor = get_sf_cursor(sf_profile)
        cursor.execute(f"SELECT identifier FROM {models_table}")
        identifiers += [str(row[0]).strip() for row in cursor.fetchall()]

    resolved: List[dict] = []
    for identifier in [i for i in identifiers if i]:
        # A GUID resolves as-is; a name has to be looked up, and an unknown name is
        # reported rather than skipped -- a silently-dropped Model would understate the
        # blocker count, which is the one number this command exists to produce.
        if "-" in identifier and len(identifier) >= 32:
            resolved.append({"guid": identifier, "name": identifier})
            continue
        guid = discover.find_model_by_name(client, identifier)
        if not guid:
            _err(f"warning: no Model named '{identifier}' — not scanned")
            continue
        resolved.append({"guid": guid, "name": identifier})
    return resolved


@app.command("scan-sets")
def scan_sets(
    source_profile: Optional[str] = _source_profile,
    source_org: List[str] = typer.Option([], "--source-org",
                                         help="Org to scan (name or numeric id, repeatable). "
                                              "Omit for the profile's default Org."),
    model: List[str] = typer.Option([], "--model", "-m",
                                    help="Model GUID or exact name (repeatable)."),
    all_models: bool = typer.Option(False, "--all-models",
                                    help="Scan every Model in each Org."),
    models_file: Optional[str] = typer.Option(None, "--models-file",
                                              help="CSV manifest with an `identifier` column."),
    models_table: Optional[str] = typer.Option(None, "--models-table",
                                               help="Snowflake table with the same column."),
    sf_profile: Optional[str] = typer.Option(None, "--sf-profile",
                                             help="Snowflake profile for --models-table."),
    out_dir: Optional[str] = typer.Option(None, "--out-dir", "-o",
                                          help="Write sets-scan.json + sets-scan.md here."),
) -> None:
    """Phase 0: which tenants are blocked by Sets, and by which objects.

    **Read-only, and needs no target Org**, so it runs before any clean Org exists. Before
    planning a wave — or committing to build Phase 2 at all — the programme needs one
    number: how many tenants actually use Sets. That decides whether Sets support gates
    the whole programme or is a tail of stragglers.

    A Set creates a `COHORT_*` `LOGICAL_COLUMN` owned by the Model, which blocks
    publishing that Model **and every Answer and Liveboard on it, used or not**. The
    column is invisible in TML, so this scans `metadata/search` — a TML inspection would
    report a clean Model that is in fact blocked, and a lift-and-shift would drop the Set
    silently rather than fail.

    Examples:

    \b
      ts migrate scan-sets --all-models --source-profile prod
      ts migrate scan-sets --source-org ORG1 --source-org ORG2 --all-models -o ./scan/
      ts migrate scan-sets --models-file candidates.csv --source-profile prod
    """
    from pathlib import Path

    # Reuse `ts share`'s Org helpers rather than building a client from a raw name.
    # `auth/token/full` SILENTLY IGNORES a non-numeric `org_identifier` and falls back to
    # the caller's default Org, so passing "ORG1" straight through scans Primary while
    # reporting it as ORG1. `_client_for_org` resolves the name to a numeric id and
    # `assert_org_context` reads the session back before we trust it. Observed live
    # 2026-07-27: without this, --source-org ORG1 --source-org ORG2 scanned Primary twice.
    from ts_cli.commands.share import _client_for_org, assert_org_context
    from ts_cli.migrate import discover, sets_scan

    orgs: List[Optional[str]] = list(source_org) or [None]
    blocked: List[dict] = []
    scanned_models = 0

    for org in orgs:
        label = org or "(default)"
        client = _client_for_org(source_profile, org)
        if org:
            # Defence in depth: refuse to report a scan under an Org name it did not
            # actually run in. A mislabelled blocker count is worse than no count.
            assert_org_context(client, org, source_profile)
        models = _resolve_scan_models(client, model, all_models, models_file,
                                      models_table, sf_profile)
        if not models:
            _err(f"{label}: no Models in scope — pass --model, --all-models, or a manifest")
            continue
        scanned_models += len(models)

        # ONE LOGICAL_COLUMN search per Org, sliced per Model. The scan's justification is
        # being cheap enough to run fleet-wide, so it must not scale with Model count.
        rows = discover.all_cohort_column_rows(client)
        by_owner = sets_scan.extract_cohort_columns(rows, [m["guid"] for m in models])

        for entry in models:
            cohort = by_owner.get(entry["guid"])
            if not cohort:
                continue
            dependents: List[dict] = []
            for column in cohort:
                dependents += sets_scan.normalise_dependents(
                    discover.column_dependents(client, column["guid"]))
            blocked.append(sets_scan.build_blocked_entry(
                label, entry["name"], entry["guid"], cohort,
                sets_scan.normalise_dependents(dependents)))
        _err(f"{label}: scanned {len(models)} model(s)")

    report = sets_scan.build_scan_report([o or "(default)" for o in orgs],
                                         scanned_models, blocked)
    print(json.dumps(report, indent=2))

    if out_dir:
        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)
        (target / "sets-scan.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (target / "sets-scan.md").write_text(sets_scan.render_scan_markdown(report),
                                             encoding="utf-8")
        _err(f"Wrote sets-scan.json + sets-scan.md to {out_dir}")

    summary = report["summary"]
    _err(f"Sets scan: {summary['models_blocked']} of {scanned_models} model(s) blocked "
         f"across {summary['orgs_blocked']} Org(s); "
         f"{summary['objects_affected']} Answer(s)/Liveboard(s) affected.")
