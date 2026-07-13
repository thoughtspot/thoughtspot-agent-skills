"""ts model — Model-level operations.

promote-formula: codify the mechanical formula-promotion merge from
ts-object-answer-promote Steps 8-10 (BL-066). Exports answer + model TML,
detects duplicates, maps column references, infers column_type, and emits
the merged Model TML as JSON to stdout.
"""
from __future__ import annotations

import json
import sys
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.commands.tml import parse_edoc, detect_tml_type
from ts_cli.promote import (
    build_merged_model,
    detect_duplicates,
    detect_param_duplicates,
    extract_answer_formulas,
    find_formula_dependencies,
    find_param_dependencies,
    map_references,
)

app = typer.Typer(help="Model-level operations.")

_profile_option = typer.Option(
    None, "--profile", "-p", envvar="TS_PROFILE",
    help="Profile name (default: first profile or TS_PROFILE env var)",
)


@app.command("promote-formula")
def promote_formula(
    answer_guid: str = typer.Option(
        ..., "--answer", "-a",
        help="Answer GUID — source of the formulas to promote",
    ),
    model_guid: str = typer.Option(
        ..., "--model", "-m",
        help="Model GUID — target to merge formulas into",
    ),
    profile: Optional[str] = _profile_option,
    formula_names: Optional[List[str]] = typer.Option(
        None, "--formula",
        help="Formula names to promote (repeatable). Omit for all.",
    ),
    all_formulas: bool = typer.Option(
        False, "--all",
        help="Promote all answer formulas (equivalent to omitting --formula).",
    ),
    duplicates: str = typer.Option(
        "skip", "--duplicates", "-d",
        help="Duplicate policy: 'skip' (default) or 'overwrite'.",
    ),
    include_auto: bool = typer.Option(
        False, "--include-auto",
        help="Include auto-generated formulas (was_auto_generated=true).",
    ),
    include_params: bool = typer.Option(
        True, "--include-params/--no-params",
        help="Auto-include parameters referenced by selected formulas (default: true).",
    ),
    include_deps: bool = typer.Option(
        True, "--include-deps/--no-deps",
        help="Auto-include unselected answer formulas that selected formulas depend on (default: true).",
    ),
) -> None:
    """Promote formulas from an Answer into a Model.

    Exports both TMLs, extracts answer formulas, detects duplicates against
    the model, maps column references, infers column_type (MEASURE/ATTRIBUTE),
    and emits a JSON result with the merged Model TML ready for import.

    \b
    Output JSON:
      added             — formulas merged into the model
      skipped           — formulas skipped (duplicates with --duplicates=skip)
      overwritten       — formulas that replaced existing model entries
      unresolved_refs   — column references that couldn't be auto-resolved
      params_added      — parameters co-promoted with formulas
      deps_added        — formula dependencies auto-included
      merged_tml_yaml   — the full merged Model TML (YAML string)

    \b
    Examples:
      ts model promote-formula --answer abc-123 --model def-456
      ts model promote-formula -a abc-123 -m def-456 --formula "Profit Margin"
      ts model promote-formula -a abc-123 -m def-456 --duplicates overwrite
      ts model promote-formula -a abc-123 -m def-456 --all --include-auto
    """
    if duplicates not in ("skip", "overwrite"):
        raise SystemExit("--duplicates must be 'skip' or 'overwrite'")

    prof = resolve_profile(profile)
    client = ThoughtSpotClient(prof)

    typer.echo("Exporting answer TML...", err=True)
    answer_export = _export_parsed(client, answer_guid)
    answer_tml = _find_by_type(answer_export, "answer")
    if not answer_tml:
        raise SystemExit(f"GUID {answer_guid} did not export an Answer TML.")

    typer.echo("Exporting model TML (with associated tables)...", err=True)
    model_export = _export_parsed(client, model_guid, associated=True)
    model_tml = _find_by_type(model_export, "model")
    if not model_tml:
        raise SystemExit(f"GUID {model_guid} did not export a Model TML.")

    model_guid_from_export = None
    for item in model_export:
        if item.get("type") == "model":
            model_guid_from_export = item.get("guid")
            break
    if model_guid_from_export and "guid" not in model_tml:
        model_tml["guid"] = model_guid_from_export

    extracted = extract_answer_formulas(answer_tml)
    all_answer_formulas = extracted["formulas"]
    answer_params = extracted["parameters"]

    if not all_answer_formulas:
        raise SystemExit(
            f"Answer {answer_guid} contains no formula definitions.\n"
            "This can happen when the answer uses only model columns with no "
            "custom formulas."
        )

    selected = _select_formulas(all_answer_formulas, formula_names, all_formulas, include_auto)

    if not selected:
        raise SystemExit("No formulas selected for promotion.")

    deps_added_names: list[str] = []
    if include_deps:
        deps = find_formula_dependencies(selected, all_answer_formulas)
        if deps:
            dep_names = [d["name"] for d in deps]
            typer.echo(f"Auto-including {len(deps)} formula dependencies: {', '.join(dep_names)}", err=True)
            selected.extend(deps)
            deps_added_names = dep_names

    params_to_promote: list[dict] = []
    if include_params:
        params_to_promote = find_param_dependencies(selected, answer_params)
        if params_to_promote:
            typer.echo(
                f"Auto-including {len(params_to_promote)} parameters: "
                f"{', '.join(p['name'] for p in params_to_promote)}",
                err=True,
            )

    dup_result = detect_duplicates(selected, model_tml, policy=duplicates)
    param_dup_result = detect_param_duplicates(params_to_promote, model_tml, policy=duplicates)

    to_add = dup_result["to_add"]
    to_overwrite = dup_result["to_overwrite"]
    skipped = dup_result["skipped"]
    params_add = param_dup_result["to_add"]
    params_overwrite = param_dup_result["to_overwrite"]

    if not to_add and not to_overwrite:
        result = {
            "added": [],
            "skipped": [{"name": f["name"], "reason": "duplicate"} for f in skipped],
            "overwritten": [],
            "unresolved_refs": [],
            "params_added": [],
            "deps_added": [],
            "merged_tml_yaml": None,
        }
        json.dump(result, sys.stdout, indent=2)
        typer.echo("", err=True)
        typer.echo("All selected formulas are duplicates — nothing to promote.", err=True)
        return

    all_to_merge = to_add + to_overwrite
    promoting_names = {f["name"] for f in all_to_merge}
    promoting_ids = {f.get("id", "") for f in all_to_merge}

    ref_results = map_references(
        all_to_merge, model_tml,
        promoting_names=promoting_names,
        promoting_ids=promoting_ids,
    )

    all_unresolved: list[dict] = []
    for r in ref_results:
        for token in r["unresolved"]:
            all_unresolved.append({"formula": r["name"], "ref": f"[{token}]"})

    merged = build_merged_model(
        model_tml, to_add, to_overwrite, ref_results,
        params_to_add=params_add,
        params_to_overwrite=params_overwrite,
    )

    result = {
        "added": merged["added"],
        "skipped": [{"name": f["name"], "reason": "duplicate"} for f in skipped],
        "overwritten": merged["overwritten"],
        "unresolved_refs": all_unresolved,
        "params_added": merged["params_added"],
        "params_overwritten": merged.get("params_overwritten", []),
        "deps_added": deps_added_names,
        "merged_tml_yaml": merged["merged_yaml"],
    }

    json.dump(result, sys.stdout, indent=2)

    added_count = len(merged["added"])
    overwritten_count = len(merged["overwritten"])
    skipped_count = len(skipped)
    unresolved_count = len(all_unresolved)
    typer.echo("", err=True)
    typer.echo(
        f"Done: {added_count} added, {overwritten_count} overwritten, "
        f"{skipped_count} skipped, {unresolved_count} unresolved refs.",
        err=True,
    )
    if all_unresolved:
        typer.echo(
            "Warning: unresolved references found — review 'unresolved_refs' in the output "
            "and resolve them before importing.",
            err=True,
        )


def _export_parsed(
    client: ThoughtSpotClient,
    guid: str,
    *,
    associated: bool = False,
) -> list[dict]:
    """Export TML for a GUID and return parsed results."""
    body: dict = {
        "metadata": [{"identifier": guid}],
        "export_fqn": True,
    }
    if associated:
        body["export_associated"] = True

    resp = client.post("/api/rest/2.0/metadata/tml/export", json=body)

    results = []
    for item in resp.json():
        edoc = item.get("edoc", "")
        if not edoc:
            continue
        parsed = parse_edoc(edoc)
        tml_type = detect_tml_type(parsed)
        info = item.get("info", {})
        results.append({
            "type": tml_type,
            "guid": info.get("id", info.get("name", "")),
            "tml": parsed,
            "info": info,
        })
    return results


def _find_by_type(items: list[dict], tml_type: str) -> Optional[dict]:
    """Find the first item matching the given TML type."""
    for item in items:
        if item.get("type") == tml_type:
            return item["tml"]
    return None


def _select_formulas(
    all_formulas: list[dict],
    names: Optional[List[str]],
    all_flag: bool,
    include_auto: bool,
) -> list[dict]:
    """Select formulas by name or all, filtering auto-generated unless opted in."""
    if names:
        name_set = set(names)
        selected = [f for f in all_formulas if f["name"] in name_set]
        missing = name_set - {f["name"] for f in selected}
        if missing:
            raise SystemExit(f"Formula(s) not found in answer: {', '.join(sorted(missing))}")
        return selected

    if not include_auto:
        return [f for f in all_formulas if not f.get("was_auto_generated")]
    return list(all_formulas)
