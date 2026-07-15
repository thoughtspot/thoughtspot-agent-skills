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
    source_org: Optional[int] = typer.Option(None, "--source-org", help="Source Org id (password/secret profiles only)."),
    target_org: Optional[int] = typer.Option(None, "--target-org", help="Target Org id (password/secret profiles only)."),
    model: List[str] = typer.Option([], "--model", "-m", help="Source Model GUID(s) to audit."),
    all_models: bool = typer.Option(False, "--all-models", help="Audit every Model in the source Org."),
    out_dir: str = typer.Option(..., "--out-dir", "-o", help="Directory for column-mapping.csv + audit report."),
) -> None:
    """Read-only audit: compare tenant Models/columns to the clean Org's published Models.

    Writes column-mapping.csv (review + fill gaps), audit-report.json, audit-report.md.
    """
    from ts_cli.migrate import discover, run_audit

    source_client = ThoughtSpotClient(resolve_profile(source_profile), org_id=source_org)
    target_client = ThoughtSpotClient(resolve_profile(target_profile), org_id=target_org)

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
