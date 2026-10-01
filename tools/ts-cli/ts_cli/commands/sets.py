"""`ts sets` — reusable Set inventory and report (ts-object-set-manager). Read-only."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import typer

from ts_cli.client import resolve_profile
from ts_cli.sets.inventory import inventory_org, summarise
from ts_cli.sets.scope import select_models

app = typer.Typer(help="Reusable Set (cohort) inventory and report. Read-only.", no_args_is_help=True)

SCHEMA = "ts-sets-inventory/1"


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _client(profile: Optional[str], org: Optional[str]):
    """Org-scoped client whose session is CONFIRMED to be in that Org (see BL-147)."""
    from ts_cli.client import ThoughtSpotClient
    from ts_cli.commands.share import _client_for_org, assert_org_context
    if not org:
        return ThoughtSpotClient(resolve_profile(profile))
    client = _client_for_org(profile, org)
    assert_org_context(client, org, profile)
    return client


def _models_in(client) -> List[dict]:
    """Models the session's Org OWNS — visibility is not ownership (list_models docstring)."""
    from ts_cli.migrate.discover import list_models, owning_org_id
    return list_models(client, owner_org_id=owning_org_id(client))


def _dedupe(models: List[dict]) -> List[dict]:
    """First occurrence per guid, order preserved."""
    seen, out = set(), []
    for m in models:
        if m["guid"] not in seen:
            seen.add(m["guid"])
            out.append(m)
    return out


def _all_org_ids(profile: Optional[str]) -> List[str]:
    """Numeric ids (as strings, which `_client_for_org` accepts) of every ACTIVE Org,
    fully paginated via `ts orgs search`'s listing. Skipped Orgs are named on stderr."""
    from ts_cli.client import ThoughtSpotClient
    from ts_cli.commands.orgs import list_orgs
    rows = list_orgs(ThoughtSpotClient(resolve_profile(profile)))
    ids = []
    for o in rows:
        if o.get("status") == "ACTIVE" and o.get("orgId") is not None:
            ids.append(str(o["orgId"]))
        else:
            _err(f"skipping Org {o.get('orgName')!r} (id {o.get('orgId')}, "
                 f"status {o.get('status')})")
    return ids


def _clean_selectors(flag: str, values: List[str]) -> List[str]:
    out = [v.strip() for v in values]
    if any(not v for v in out):
        _err(f"{flag} was given an empty or whitespace-only value")
        raise typer.Exit(1)
    return out


def _resolve_plans(profile: Optional[str], orgs: List[Optional[str]], model: List[str],
                   contains: List[str]) -> List[tuple]:
    """(label, client, chosen Models) per Org. Errors (exit 1) before any scan when a
    selector matched in no Org."""
    plans, missed_all = [], []
    for o in orgs:
        client = _client(profile, o)
        chosen, missed = select_models(_dedupe(_models_in(client)), model=model,
                                       contains=contains)
        missed_all.append(set(missed))
        plans.append((o or "(default)", client, chosen))
    # a selector is unmatched only if it matched in no Org
    unmatched = set.intersection(*missed_all)
    if unmatched:
        _err("No Model matched: " + ", ".join(sorted(unmatched)))
        raise typer.Exit(1)
    return plans


def _emit(doc: dict, output: Optional[str]) -> None:
    text = json.dumps(doc, indent=2)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text, encoding="utf-8")
    print(text)


@app.command("inventory")
def inventory(
    model: List[str] = typer.Option([], "--model", help="Model GUID or exact name (repeatable)."),
    model_contains: List[str] = typer.Option([], "--model-contains", help="Case-insensitive substring of a Model name (repeatable)."),
    org: List[str] = typer.Option([], "--org", help="Org name or id; every Model it owns (repeatable)."),
    all_orgs: bool = typer.Option(False, "--all-orgs", help="Cluster scope: every ACTIVE Org in turn."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Resolve scope only; no Set scan."),
    output: Optional[str] = typer.Option(None, "-o", "--output", help="Write JSON here as well as stdout."),
    profile: Optional[str] = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE"),
) -> None:
    """Every reusable Set on the scoped Models, classified, with grant provenance.

    Output: JSON (schema ts-sets-inventory/1) on stdout; progress on stderr.

    Examples:

    \b
      ts sets inventory --model-contains DUNDER -p se
      ts sets inventory --org ORG1 --dry-run -p se
      ts sets inventory --all-orgs -o ./sets-inventory.json -p se
    """
    if not (model or model_contains or org or all_orgs):
        _err("No scope: pass --model, --model-contains, --org or --all-orgs")
        raise typer.Exit(1)
    model = _clean_selectors("--model", model)
    model_contains = _clean_selectors("--model-contains", model_contains)
    orgs: List[Optional[str]] = _all_org_ids(profile) if all_orgs else (list(org) or [None])
    if not orgs:
        _err("--all-orgs found no ACTIVE Org")
        raise typer.Exit(1)
    plans = _resolve_plans(profile, orgs, model, model_contains)
    scope = {"model": model, "model_contains": model_contains, "org": org, "all_orgs": all_orgs}
    if dry_run:
        n = sum(len(c) for _, _, c in plans)
        _err(f"{n} Model(s) in scope across {len(plans)} Org(s); rough estimate {max(1, n * 5)}s+")
        print(json.dumps({"schema": SCHEMA, "dry_run": True, "scope": scope,
                          "orgs": [{"org": label, "models": c} for label, _, c in plans]}, indent=2))
        return
    results = []
    for label, client, chosen in plans:
        _err(f"{label}: scanning {len(chosen)} Model(s)…")
        results.append(inventory_org(client, label, chosen))
    doc = {"schema": SCHEMA,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "profile": resolve_profile(profile), "scope": scope,
           "orgs": results, "summary": summarise(results)}
    _emit(doc, output)
