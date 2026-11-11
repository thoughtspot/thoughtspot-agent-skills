"""`ts tableau build-model --existing-guid` import step: import the merged Model
TML, drop a formula the import names (and anything added this batch that depends
on it), and retry. Moved out of commands/tableau.py (BL-089).
"""
from __future__ import annotations

import json

import typer


def _collect_cascade_victims(
    merged: dict, bad_name: str, err_detail: str
) -> tuple[list[str], dict[str, str]]:
    """Return the failed formula plus the transitive closure of formulas that
    reference it, with a drop reason for each (breadth-first to a fixpoint)."""
    to_drop = [bad_name]
    reasons = {bad_name: err_detail}
    seen = {bad_name}
    i = 0
    while i < len(to_drop):
        victim = to_drop[i]
        i += 1
        token = f"[formula_{victim}]"
        for fm in merged["model"].get("formulas", []):
            dep = fm["name"]
            if dep not in seen and token in fm.get("expr", ""):
                seen.add(dep)
                to_drop.append(dep)
                reasons[dep] = f"depends on dropped formula '{victim}'"
    return to_drop, reasons


# WARNING imported, as elsewhere in the repo (commands/dbt.py, migrate/apply_exec.py).
_IMPORT_SUCCESS = ("OK", "WARNING")
# SKIPPED: every new formula was dropped, the Model is unchanged and
# formulas_dropped_on_import says why; the skill parks them, so it is not a failure.
_IMPORT_EXIT_ZERO = (None, *_IMPORT_SUCCESS, "SKIPPED")


def _run_one_import_attempt(import_tml: dict, profile: str) -> tuple[str, list | None, str]:
    """Run one ``ts tml import``; import_result is None only when unparseable."""
    import subprocess

    tml_str = json.dumps(import_tml)
    import_proc = subprocess.run(
        ["ts", "tml", "import", "--profile", profile, "--policy", "ALL_OR_NONE"],
        input=json.dumps([tml_str]), capture_output=True, text=True)
    # Exits 1 on any per-item failure even under ALL_OR_NONE, so read the JSON.
    try:
        import_result = json.loads(import_proc.stdout)
        status = import_result[0]["response"]["status"]["status_code"]
    except (json.JSONDecodeError, LookupError, TypeError, KeyError):
        msg = f"Unparseable import response (exit {import_proc.returncode}): {import_proc.stdout[:200] or import_proc.stderr[:200]}"
        return "ERROR", None, msg
    if status == "OK":
        return status, import_result, ""
    return status, import_result, import_result[0]["response"]["status"].get("error_message", "")


def _record_import_success(result: dict, status: str, msg: str, guid: str) -> None:
    """OK or WARNING: set the GUID, and keep a WARNING's text for the report."""
    result["import_status"] = status
    result["updated_model_guid"] = guid
    if msg:
        result["import_warning"] = msg
    typer.echo(f"  Import: {status}" + (f" — {msg[:200]}" if msg else ""), err=True)


def _parsed_err_for_added_formula(parsed_err: tuple | None, added_names: set[str]) -> tuple | None:
    """Drop only a formula THIS batch added — a dependent may be the real cause."""
    if parsed_err is not None and parsed_err[0] not in added_names:
        return None
    return parsed_err


def _drop_cascade_victims(
    merged: dict, bad_name: str, err_detail: str, added_names: set[str],
    expr_by_fid: dict, original_by_name: dict, stats: dict, dropped_on_import: list[dict],
) -> None:
    """Drop ``bad_name`` and any added formula referencing it, this cycle only."""
    from ts_cli.tableau.build_model import remove_formula

    to_drop, reasons = _collect_cascade_victims(merged, bad_name, err_detail)
    to_drop = [v for v in to_drop if v in added_names]  # same added-only rule
    for victim in to_drop:
        dropped_on_import.append({
            "name": victim,
            "expr": expr_by_fid.get(f"formula_{victim}", ""),
            "error": reasons[victim],
            "original_tableau": original_by_name.get(victim, ""),
        })
        remove_formula(merged, victim)
        stats["added"] -= 1
    if len(to_drop) > 1:
        typer.echo(
            f"    ↳ cascade-dropped {len(to_drop) - 1} dependent formula(s)",
            err=True,
        )


def _import_with_retry(
    merged: dict,
    ds: dict,
    existing_guid: str,
    profile: str,
    max_retries: int,
    result: dict,
) -> None:
    """Import merged TML, dropping failing formulas and retrying (subprocess I/O).

    Mutates ``merged`` (formulas dropped on error), ``merged["_merge_stats"]``,
    and ``result`` (import_status / updated_model_guid / dropped list).
    """
    from ts_cli.tableau.build_model import extract_imported_guid, parse_import_error

    stats = merged["_merge_stats"]
    expr_by_fid = {f["id"]: f.get("expr", "") for f in merged["model"]["formulas"]}
    original_by_name = {c.get("caption", c.get("name", "")): c.get("formula", "")
                         for c in ds.get("calculated_fields", [])}
    dropped_on_import: list[dict] = []
    added_names = set(stats.get("added_names") or [])
    for _attempt in range(max_retries):
        import_tml = {k: v for k, v in merged.items() if not k.startswith("_")}
        status, import_result, msg = _run_one_import_attempt(import_tml, profile)
        if import_result is None:
            result["import_status"] = "ERROR"
            result["import_error"] = msg
            typer.echo(f"  Import: {result['import_error']}", err=True)
            break
        if status in _IMPORT_SUCCESS:
            guid = extract_imported_guid(import_result) or existing_guid
            _record_import_success(result, status, msg, guid)
            break
        parsed_err = _parsed_err_for_added_formula(parse_import_error(msg), added_names)
        if parsed_err is None:
            result["import_status"] = status
            result["import_error"] = msg
            typer.echo(f"  Import: {status} — {msg[:200]}", err=True)
            break
        bad_name, err_detail = parsed_err
        typer.echo(f"  Import error on '{bad_name}': {err_detail} — dropping", err=True)
        _drop_cascade_victims(
            merged, bad_name, err_detail, added_names, expr_by_fid, original_by_name, stats, dropped_on_import)
        if stats["added"] <= 0:
            typer.echo("  All new formulas dropped — nothing to import", err=True)
            result["import_status"] = "SKIPPED"
            result["updated_model_guid"] = existing_guid  # the Model is unchanged
            break
    else:
        result["import_status"] = "ERROR"
        result["import_error"] = "Max retry attempts exceeded"
    if dropped_on_import:
        result["formulas_dropped_on_import"] = dropped_on_import
        result["formulas_added"] = stats["added"]
