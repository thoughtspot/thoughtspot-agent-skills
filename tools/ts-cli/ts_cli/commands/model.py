"""ts model — Model-level operations.

promote-formula: codify the mechanical formula-promotion merge from
ts-object-answer-promote Steps 8-10 (BL-066). Exports answer + model TML,
detects duplicates, maps column references, infers column_type, and emits
the merged Model TML as JSON to stdout.

dictionary: a data dictionary, one row per column (logic in ts_cli/model_dictionary.py).
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


def _dictionary_docs(models: List[str], files: List[str], directory: Optional[str],
                     profile: Optional[str]) -> list:
    """Parsed TML docs for `dictionary`: exported live (Models with their Tables) when
    --model is given, else read from --file/--dir. An export item that fails on its own
    (FORBIDDEN inside an HTTP 200) is reported on stderr and left out, never read as an
    empty Model."""
    from ts_cli.commands.tml import load_input_tmls
    from ts_cli.tml_common import export_item_doc

    if models:
        client = ThoughtSpotClient(resolve_profile(profile))
        resp = client.post("/api/rest/2.0/metadata/tml/export", json={
            "metadata": [{"identifier": g} for g in models],
            "export_associated": True, "formattype": "YAML"})
        docs = []
        for item in resp.json():
            doc, reason = export_item_doc(item)
            if reason:
                typer.echo(f"Warning: skipped — {reason}", err=True)
            elif doc:
                docs.append(doc)
        return docs
    return [parse_edoc(t) for t in load_input_tmls(files, directory)]


@app.command("dictionary")
def dictionary(
    models: List[str] = typer.Option(
        [], "--model", "-m", help="Model GUID to export live, with its Tables (repeatable)"),
    file: List[str] = typer.Option(
        [], "--file", help="Model / Table TML file (repeatable) — offline, no profile needed"),
    directory: Optional[str] = typer.Option(
        None, "--dir", help="Directory of Model / Table TML files — offline"),
    profile: Optional[str] = _profile_option,
    format: str = typer.Option("json", "--format", "-f", help="json (default), csv or xlsx"),
    out: Optional[str] = typer.Option(
        None, "--out", "-o", help="Write to this file (required for xlsx)"),
) -> None:
    """A data dictionary for one or more Models: one row per column.

    Each row carries the column's name, role, aggregation, data type and source
    table/column, its formula, description, synonyms, AI context, and whether it is
    indexed or hidden. The data type and warehouse column come from the Table TMLs:
    a Model column has no data type of its own, so a Model read without its Tables
    leaves that field blank. --model exports the Tables with it; with --file/--dir,
    include the Table TMLs alongside the Model.

    Output: JSON rows to stdout by default. `--format csv` writes CSV (to stdout, or
    --out), with a Model column so several Models fit one file. `--format xlsx` writes
    one worksheet per Model to --out and needs the optional extra:
    pip install 'thoughtspot-cli[xlsx]'.

    \b
      ts model dictionary --model <guid> --profile myprofile
      ts model dictionary --dir ./tml --format csv --out dictionary.csv
      ts model dictionary --model <g1> --model <g2> --format xlsx --out dictionary.xlsx
    """
    from ts_cli.model_dictionary import build_rows

    fmt = format.lower()
    _check_dictionary_args(fmt, out, models, file, directory)
    tables, model_docs = _split_docs(_dictionary_docs(models, file, directory, profile))
    per_model = [(d["model"].get("name", ""), build_rows(d, tables)) for d in model_docs]
    rows = [r for _, rs in per_model for r in rs]
    typer.echo(f"{len(model_docs)} Model(s), {len(rows)} column(s), "
               f"{len(tables)} Table/SQL View TML(s) for sources and types", err=True)
    _emit_dictionary(fmt, per_model, rows, out)


def _check_dictionary_args(fmt: str, out, models, file, directory) -> None:
    if fmt not in ("json", "csv", "xlsx"):
        raise SystemExit("--format must be json, csv or xlsx")
    if fmt == "xlsx" and not out:
        raise SystemExit("--format xlsx needs --out <file.xlsx>")
    if models and (file or directory):
        raise SystemExit("Use --model, or --file/--dir — not both")
    if not models and not file and not directory:
        raise SystemExit("Give --model <guid>, or --file/--dir with exported TML")


def _split_docs(docs: list) -> tuple:
    """(Table and SQL View bodies by name, Model docs). A Model column can sit on either."""
    tables = {body["name"]: body for d in docs if isinstance(d, dict)
              for body in (d.get("table"), d.get("sql_view"))
              if isinstance(body, dict) and body.get("name")}
    model_docs = [d for d in docs if isinstance(d, dict) and isinstance(d.get("model"), dict)]
    if not model_docs:
        raise SystemExit("No Model TML found in the input")
    return tables, model_docs


def _emit_dictionary(fmt: str, per_model: list, rows: list, out) -> None:
    from ts_cli.model_dictionary import to_csv, write_xlsx

    if fmt == "xlsx":
        try:
            write_xlsx(per_model, out)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        typer.echo(f"Written to {out}", err=True)
        return
    text = to_csv(rows) if fmt == "csv" else json.dumps(rows, indent=2) + "\n"
    if not out:
        sys.stdout.write(text)
        return
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    typer.echo(f"Written to {out}", err=True)
