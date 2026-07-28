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

    # Resolved and asserted, NOT passed as a raw name (BL-147). The comment that used to
    # sit here claimed `_org_auth_fields` made a name safe and that a wrong-Org read was
    # recoverable anyway. Both were wrong, and the second is the dangerous one: the audit
    # produces the file a human approves, so reading Primary while believing it read the
    # tenant hands someone a plausible mapping for the wrong objects.
    source_client = _org_client(source_profile, source_org)
    target_client = _org_client(target_profile, target_org)

    model_guids = list(model)
    if all_models:
        # Models this Org OWNS. Once the master has been published in -- which is the
        # normal state during a same-Org migration -- an unscoped sweep audits the master
        # against itself alongside the tenant's real Models.
        model_guids = [m["guid"] for m in discover.list_models(
            source_client, owner_org_id=discover.owning_org_id(source_client))]
    if not model_guids:
        _err("No models to audit. Pass --model <guid> (repeatable) or --all-models.")
        raise typer.Exit(code=1)

    try:
        report = run_audit(source_client, target_client, model_guids, out_dir,
                           source_owner_org_id=_target_exclusion(
                               source_client, source_profile, target_profile))
    except discover.AmbiguousModelName as exc:
        _refuse(str(exc))
    print(json.dumps(report, indent=2))
    ready = "READY" if report["overall_ready"] else "NEEDS MAPPING"
    _err(f"Audit complete: {len(report['models'])} model(s), overall {ready}. Files in {out_dir}")


def _refuse(detail: str) -> None:
    """Turn a refusal into a clean exit rather than a traceback. Never returns."""
    _err(f"Refused. {detail}")
    raise typer.Exit(code=1)


def _target_exclusion(source_client, source_profile: Optional[str],
                      target_profile: Optional[str]) -> Optional[int]:
    """Source Org id to exclude from target lookups, or `None` across clusters.

    Org ids are only meaningful within one cluster -- `Primary` is `0` on both -- so
    excluding by id across clusters would refuse a legitimate Primary-to-Primary target.
    Same test as `import_mode` uses for the write mode: profiles equal means one cluster.
    """
    from ts_cli.migrate import discover

    if source_profile != target_profile:
        return None
    return discover.owning_org_id(source_client)


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
        return discover.list_models(client, owner_org_id=discover.owning_org_id(client))

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
    owner = discover.owning_org_id(client)
    for identifier in [i for i in identifiers if i]:
        # A GUID resolves as-is; a name has to be looked up, and an unknown name is
        # reported rather than skipped -- a silently-dropped Model would understate the
        # blocker count, which is the one number this command exists to produce.
        if "-" in identifier and len(identifier) >= 32:
            resolved.append({"guid": identifier, "name": identifier})
            continue
        # This Org's OWN Model. A published master visible in the Org is not this tenant's
        # blocker, and counting it as one overstates the number the scan exists to produce.
        try:
            guid = discover.find_source_model(client, identifier, owner)
        except discover.AmbiguousModelName as exc:
            _refuse(str(exc))
        if not guid:
            _err(f"warning: no Model named '{identifier}' owned by this Org — not scanned")
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


def _org_client(profile: Optional[str], org: Optional[str]):
    """An org-scoped client whose session is CONFIRMED to be in that Org.

    **Every command in this group must go through here, reads included.**
    `auth/token/full` SILENTLY ignores a non-numeric `org_identifier` and falls back to
    the caller's default Org, so passing a name straight to `ThoughtSpotClient` reads the
    wrong Org while reporting success.

    `audit` used to do exactly that on the grounds that a wrong-Org read is recoverable.
    It is not, in the way that matters: the error surfaces only when a GUID happens to be
    missing. When it is not -- two Orgs with same-named Models, which is the normal shape
    of this migration -- the audit succeeds against the wrong Org and emits a plausible
    `column-mapping.csv` for objects that are not the tenant's. Someone then approves it.
    (BL-147.)
    """
    from ts_cli.commands.share import _resolve_org_id, assert_org_context

    resolved = resolve_profile(profile)
    if not org:
        return ThoughtSpotClient(resolved)
    org_id = _resolve_org_id(profile, org)
    client = ThoughtSpotClient(resolved, org=str(org_id))
    assert_org_context(client, org_id, org)
    return client


def _load_mapping_or_exit(plan_path):
    """Read the approved column-mapping.csv, or explain what to run first."""
    from ts_cli.migrate.mapping import read_mapping

    mapping_file = plan_path / "column-mapping.csv"
    if not mapping_file.exists():
        _err(f"No column-mapping.csv in {plan_path}. Run `ts migrate audit` first.")
        raise typer.Exit(code=1)
    return read_mapping(mapping_file)


def _validate_or_exit(source_client, rows, blocked, names) -> None:
    """Refuse the whole run if the mapping cannot be applied, listing EVERY problem.

    Mapping mistakes are systematic; surfacing them one round-trip at a time is how a
    migration window gets lost.
    """
    from ts_cli.migrate import discover
    from ts_cli.migrate.apply_plan import validate_apply

    owner = discover.owning_org_id(source_client)
    try:
        guids_by_name = {n: discover.find_source_model(source_client, n, owner)
                         for n in names}
    except discover.AmbiguousModelName as exc:
        _refuse(str(exc))
    problems = validate_apply(
        rows, blocked_model_guids=blocked,
        model_guids_by_name={k: v for k, v in guids_by_name.items() if v})
    if not problems:
        return
    _err("Refused. This mapping cannot be applied:")
    for problem in problems:
        _err(f"  - {problem}")
    raise typer.Exit(code=1)


@app.command("apply")
def apply_migration(
    source_profile: Optional[str] = _source_profile,
    target_profile: Optional[str] = _target_profile,
    source_org: Optional[str] = typer.Option(None, "--source-org", help="Source Org (name or numeric id)."),
    target_org: Optional[str] = typer.Option(None, "--target-org", help="Target Org (name or numeric id)."),
    plan_dir: str = typer.Option(..., "--plan-dir", "-d", help="Directory holding column-mapping.csv; also receives backup/ and state.json."),
    sets_scan: Optional[str] = typer.Option(None, "--sets-scan", help="sets-scan.json from `ts migrate scan-sets`, to refuse Set-blocked Models."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the ordered plan and exit. Nothing is written."),
    resume: bool = typer.Option(False, "--resume", help="Skip steps the state ledger records as done."),
    allow_unfiltered_target: bool = typer.Option(
        False, "--allow-unfiltered-target",
        help="Repoint onto a published Model with NO row-level security. Only for a "
             "deliberately single-tenant target, or one segmented in the warehouse."),
) -> None:
    """Move one tenant's bespoke content onto the governed published Model.

    Runs the per-tenant half of the migration: backup, lift scaffolding, lift content,
    rename, repoint, and ordered cleanup. **Cutover is deliberately not included** --
    users move only once the Org has been verified in its final state, and until then
    the rollback is the untouched source Org.

    Always read `--dry-run` first: every step here is destructive in someone's Org.
    """
    import json as _json
    from pathlib import Path

    from ts_cli.migrate import apply_exec, classify, discover
    from ts_cli.migrate.apply_plan import (build_apply_plan, column_map,
                                           find_self_repoint, import_mode, new_ledger,
                                           pending_steps, record_completed,
                                           record_failure, render_plan)
    from ts_cli.migrate.sets_scan import blocked_model_guids

    plan_path = Path(plan_dir)
    rows = _load_mapping_or_exit(plan_path)

    blocked = set()
    if sets_scan:
        blocked = blocked_model_guids(_json.loads(Path(sets_scan).read_text()))

    source_client = _org_client(source_profile, source_org)
    target_client = _org_client(target_profile, target_org)

    names = sorted({r.model for r in rows})
    _validate_or_exit(source_client, rows, blocked, names)

    mode = import_mode(source_org, target_org, source_profile, target_profile)
    try:
        views, content, shielded, targets = _classify_scope(
            source_client, target_client, names,
            exclude_owner_org_id=_target_exclusion(source_client, source_profile,
                                                   target_profile))
    except discover.AmbiguousModelName as exc:
        _refuse(str(exc))
    if not targets:
        _err("No published Model in the target Org matches the source Model name(s), "
             "other than the source Model itself. Publish the master into the target Org "
             "before migrating content onto it.")
        raise typer.Exit(code=1)
    for name in find_self_repoint(targets):
        _err(f"Refused. '{name}': the migration target is the source Model itself. "
             f"Repointing content onto the object it is being moved off is a no-op that "
             f"reports success and moves nothing.")
        raise typer.Exit(code=1)

    plan = build_apply_plan({"source": source_org or "source",
                             "target": target_org or "target"},
                            views, content, column_map(rows), targets[0], mode,
                            shielded=shielded)
    if dry_run:
        print(render_plan(plan))
        _err("Dry run: nothing was changed.")
        return

    state_file = plan_path / "state.json"
    ledger = (_json.loads(state_file.read_text()) if (resume and state_file.exists())
              else new_ledger({"source": source_org, "target": target_org}))
    # Unscoped session for the segmentation check: an Org-scoped variable read returns
    # only that Org's value, which makes every target look SHARED.
    ctx = apply_exec.Ctx(source_client, target_client, plan_path, ledger,
                         allow_unfiltered=allow_unfiltered_target,
                         unscoped_client=_org_client(target_profile, None))

    for step in pending_steps(plan, ledger):
        name = step["step"]
        try:
            created = apply_exec.RUNNERS[name](ctx, step)
        except apply_exec.StepFailed as exc:
            record_failure(ledger, name, str(exc))
            state_file.write_text(_json.dumps(ledger, indent=2))
            _err(f"FAILED at '{name}':\n{exc}")
            _err(f"State written to {state_file}. Fix, then re-run with --resume.")
            raise typer.Exit(code=1)
        record_completed(ledger, name, created)
        state_file.write_text(_json.dumps(ledger, indent=2))
        _err(f"  {name}: done")

    print(_json.dumps(ledger, indent=2))
    _err("Migration complete. Verify the target Org as a REAL non-admin user, then cut "
         "users over.")


def _classify_scope(source_client, target_client, model_names, exclude_owner_org_id=None):
    """Split the scope into Views, chargeable content, SHIELDED content, and targets.

    Shielded content needs no column rewriting -- the View's exposed names do not change.
    It is returned separately rather than dropped, because in a new-Org run it still has
    to be MOVED, and omitting it is silent data loss.

    Both lookups are OWNERSHIP-AWARE, not name-only: in a same-Org run the tenant's Model
    and the published master share a name, so a bare lookup can return the master as the
    source or the source as the target (BL-152).
    """
    from ts_cli.migrate import classify, discover

    owner = discover.owning_org_id(source_client)
    views, content, shielded, targets = [], [], [], []
    for name in model_names:
        source_guid = discover.find_source_model(source_client, name, owner)
        target_guid = discover.find_target_model(
            target_client, name,
            exclude_owner_org_id=exclude_owner_org_id, exclude_guid=source_guid)
        if target_guid:
            targets.append({"guid": target_guid, "name": name,
                            "source_guid": source_guid})
        if not source_guid:
            continue
        deps = discover.dependents_through_views(source_client, source_guid)
        docs = discover.export_dependents(source_client, deps)
        refs = [classify.source_refs(d) for d in docs]
        kinds = {g: classify.kind_of(st) for g, st in discover.subtypes_by_guid(
            source_client, {r for rs in refs for r in rs}).items()}
        for dep, ref in zip(deps, refs):
            item = classify.classify_dependent(dep.get("guid", ""), dep.get("name", ""),
                                               dep.get("type", ""), ref, kinds)
            if kinds.get(item["guid"]) == classify.VIEW_BASED:
                views.append(item)          # the View itself: repoint it
            elif item["needs_rewrite"]:
                content.append(item)        # chargeable
            else:
                shielded.append(item)       # free to rewrite, but still has to move
    return views, content, shielded, targets


def _delete_in_order(client, ordered) -> List[str]:
    """Delete each labelled batch in turn, collecting problems rather than stopping.

    A rollback that aborts on the first refusal strands everything after it -- the same
    defect fixed in `ts publish rollback`.
    """
    failures: List[str] = []
    for label, guids in ordered:
        if not guids:
            continue
        resp = client.post("/api/rest/2.0/metadata/delete", raise_for_status=False,
                           json={"metadata": [{"identifier": g, "type": "LOGICAL_TABLE"}
                                              for g in guids]})
        if resp.status_code >= 300:
            failures.append(f"{label}: HTTP {resp.status_code} {resp.text[:200]}")
        else:
            _err(f"  deleted {len(guids)} {label}")
    return failures


@app.command("rollback")
def rollback_migration(
    target_profile: Optional[str] = _target_profile,
    target_org: Optional[str] = typer.Option(None, "--target-org", help="Target Org (name or numeric id)."),
    plan_dir: str = typer.Option(..., "--plan-dir", "-d", help="Plan directory holding state.json."),
    dry_run: bool = typer.Option(False, "--dry-run", help="List what would be deleted and exit."),
) -> None:
    """Undo an `apply` by deleting everything it created in the target Org.

    **The source Org is never touched** -- it is the real fallback, and `apply` leaves it
    untouched precisely so this command never has to restore anything into it.

    Deletes in the safe order (content, then Models, then Tables), because a Model with
    dependents refuses to delete. Objects already gone are not an error: a rollback has to
    be re-runnable, exactly like `ts publish rollback`.

    Before cutover the target Org holds nothing but this migration's output, so the
    blunter option is to delete the Org outright (`ts tenancy teardown`). Prefer that when
    the whole attempt is being abandoned; prefer this when only the content is.
    """
    import json as _json
    from pathlib import Path

    from ts_cli.migrate.apply_plan import STEP_LIFT_CONTENT, STEP_LIFT_SCAFFOLDING

    state_file = Path(plan_dir) / "state.json"
    if not state_file.exists():
        _err(f"No state.json in {plan_dir}. Nothing is known to have been created.")
        raise typer.Exit(code=1)
    ledger = _json.loads(state_file.read_text())
    created = ledger.get("created") or {}
    kinds = ledger.get("kinds") or {}

    content = sorted((created.get(STEP_LIFT_CONTENT) or {}).values())
    models = sorted(kinds.get("models") or [])
    tables = sorted(kinds.get("tables") or [])
    if not (content or models or tables):
        _err("The ledger records nothing created. Nothing to roll back.")
        return

    ordered = [("content", content), ("scaffolding Models", models),
               ("scaffolding Tables", tables)]
    if dry_run:
        for label, guids in ordered:
            print(f"{label}: {len(guids)}")
            for guid in guids:
                print(f"  {guid}")
        _err("Dry run: nothing was deleted.")
        return

    client = _org_client(target_profile, target_org)
    failures = _delete_in_order(client, ordered)
    if failures:
        _err("rollback INCOMPLETE:")
        for problem in failures:
            _err(f"  - {problem}")
        raise typer.Exit(code=1)
    ledger["rolled_back"] = True
    state_file.write_text(_json.dumps(ledger, indent=2))
    _err("Rollback complete. The source Org was never touched.")


@app.command("aliases")
def wave_aliases(
    profile: Optional[str] = typer.Option(None, "--profile", "-p",
                                          help="Profile holding the MASTER Model's cluster. "
                                               "Read in its default Org, because per-Org "
                                               "aliases live on the Primary Org's Model."),
    model: str = typer.Option(..., "--model", "-m",
                              help="The published master Model (GUID or exact name)."),
    target_org: List[str] = typer.Option(
        [], "--target-org",
        help="Org migrated in THIS wave, whose aliases are being added (repeatable)."),
    plan_dir: List[str] = typer.Option(
        [], "--plan-dir", "-d",
        help="Plan directory holding that Org's column-mapping.csv (repeatable, paired "
             "positionally with --target-org)."),
    expect_org: List[str] = typer.Option(
        [], "--expect-org",
        help="Org ALREADY cut over, whose aliases the export must still contain "
             "(repeatable). Refuses the wave if any is missing."),
    first_wave: bool = typer.Option(
        False, "--first-wave",
        help="Assert that NO Org has been cut over yet, so there is nothing to preserve. "
             "Required instead of --expect-org on the first wave."),
) -> None:
    """Assemble one WAVE's per-Org column aliases -- spec step 7.

    Emits the envelope `ts alias build --merge` consumes, so the whole step is:

    \b
      ts migrate aliases -m T2_PUBLISH_MODEL --target-org ORG2 -d ./plan \\
          --expect-org ORG1 -p prod | ts alias build --merge | ts alias import -p prod

    **Once per WAVE, never per tenant, and serialised.** Aliases live on the Primary Org's
    Model with no delta update until 26.10, so every append re-imports the whole document.
    Per tenant, tenant *k* pays for all *k* before it -- O(N^2) across a fleet -- and past
    5 MB each import goes async at 10-15 minutes. Two concurrent writes clobber each other.

    **Why this command rather than hand-writing the translations.** The aliases are the exact
    inverse of the rename `apply` performed, and that rename is already recorded in the
    approved `column-mapping.csv`. Deriving them removes a transcription step whose mistakes
    are silent: a misspelled column aliases nothing, and the tenant sees the physical name
    with no error anywhere.

    **The refusal that matters.** The import REPLACES the document, so an export that came
    back partial silently strips every already-cut-over Org it missed -- their users see
    `STRING_1` where they saw `Region`, with no error, because each entry left in the
    document is valid. `--expect-org` turns "check the export was complete" from something a
    human is asked to eyeball into an assertion. It is not optional: pass `--first-wave` to
    state explicitly that there is nothing to lose, because a check that defaults to off is
    not a check.

    Verify afterwards in **Search Data, an Answer, a Liveboard or Spotter** -- never the Data
    Management app, which does not render aliases at all and shows base names for everything.
    """
    from pathlib import Path

    from ts_cli.alias import merge_aliases, parse_export_response, translations_to_columns
    from ts_cli.migrate import aliases as wave
    from ts_cli.migrate.mapping import read_mapping

    if not target_org:
        _refuse("pass --target-org (repeatable) for the Org(s) migrated in this wave.")
    if len(plan_dir) != len(target_org):
        _refuse(f"{len(target_org)} --target-org but {len(plan_dir)} --plan-dir. Pass one "
                f"plan directory per Org, in the same order.")
    if bool(expect_org) == first_wave:
        _refuse("pass --expect-org for every Org already cut over, or --first-wave to state "
                "that none has been. Never both, and never neither: this is the check that "
                "stops a partial export wiping migrated tenants' aliases.")

    # The master Model is read in the profile's DEFAULT Org: per-Org aliases are stored on
    # the Primary Org's copy, not on the tenant-visible publication.
    client = _org_client(profile, None)
    resolved = model
    if "-" not in model or len(model) < 32:
        found = discover_alias_model(client, model)
        if not found:
            _refuse(f"no Model named '{model}' in this profile's default Org.")
        resolved = found

    envelope = parse_export_response(client.post(
        "/api/rest/2.0/metadata/tml/export", json={
            "metadata": [{"identifier": resolved, "type": "LOGICAL_TABLE"}],
            "export_associated": True, "export_fqn": True, "edoc_format": "YAML",
            "export_options": {"export_with_column_aliases": True},
        }).json() or [])

    existing = (envelope.get("existing_aliases") or {}).get("columns") or []

    translations: List[dict] = []
    for org, directory in zip(target_org, plan_dir):
        rows = read_mapping(Path(directory) / "column-mapping.csv")
        derived = wave.translations_from_mapping(rows, org)
        if not derived:
            _err(f"warning: {org} needs no aliases — every mapped column already matches")
        translations += derived

    merged = merge_aliases(existing, translations_to_columns(translations))
    problems = wave.wave_problems(existing, merged, expected_orgs=expect_org)
    if problems:
        _err("Refused. This wave must not be imported:")
        for problem in problems:
            _err(f"  - {problem}")
        raise typer.Exit(code=1)

    envelope["translations"] = translations
    print(json.dumps(envelope, indent=2))
    _err(f"{len(translations)} alias(es) for {', '.join(target_org)}; "
         f"{len(wave.orgs_present(existing))} Org(s) already present and preserved. "
         f"Pipe into `ts alias build --merge`.")


def discover_alias_model(client, name: str) -> Optional[str]:
    """The master Model by name, in this client's own Org. See `discover.find_source_model`."""
    from ts_cli.migrate import discover

    try:
        return discover.find_source_model(client, name, discover.owning_org_id(client))
    except discover.AmbiguousModelName as exc:
        _refuse(str(exc))
