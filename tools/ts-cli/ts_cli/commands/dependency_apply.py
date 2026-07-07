"""ts dependency apply-change — the Step 9 destructive orchestrator (BL-083 PR2).

Split out of `ts_cli.commands.dependency` to keep that module under the file-size gate
(BL-070). Attaches the `apply-change` subcommand to the SAME `app` Typer group defined
in `dependency.py`, so `ts dependency apply-change` resolves exactly as before; `cli.py`
imports this module to run the `@app.command` registration.

Wires the pure decision logic (`ts_cli.dependency.apply`), the TML transforms
(`ts_cli.dependency.mutate`), and network I/O into the drift-check → delete →
dependent-fix → source → set-delete loop the SKILL previously spelled out as ~1,060
lines of inline pseudocode. Every deterministic decision (drift, obj_id derivation, the
import/verify outcome matrix, post-import verification, 9c ordering, the set-delete
consumer guard, chart-axis-role classification) comes from `apply.py`; this shell only
performs REST calls and records results. Shared YAML/import helpers (`_dump_tml_yaml`,
`_parse_import_status`) and the `app`/`_profile_option` objects are imported from
`dependency.py`.
"""
from __future__ import annotations

import json
import sys
from typing import Dict, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.commands.tml import parse_edoc
from ts_cli.commands.dependency import (
    app,
    _dump_tml_yaml,
    _parse_import_status,
    _profile_option,
)
from ts_cli.dependency.apply import (
    chart_role_for_answer,
    derive_target_obj_id,
    import_outcome,
    is_drift,
    is_success_outcome,
    set_delete_decision,
    sort_fixes,
    v2_type_for,
    verify_remove_applied,
    verify_repoint_applied,
)
from ts_cli.dependency.backup import delete_sort_key
from ts_cli.dependency.mutate import apply_remove, apply_repoint


# ---------------------------------------------------------------------------
# `ts dependency apply-change` — the destructive orchestrator (SKILL.md Step 9)
# ---------------------------------------------------------------------------
#
# BL-083 PR2. Wires the pure decision logic (ts_cli.dependency.apply), the TML
# transforms (ts_cli.dependency.mutate), and network I/O into the drift-check →
# delete → dependent-fix → source → set-delete loop the SKILL previously spelled out
# as ~600 lines of inline pseudocode. Every deterministic decision (drift, obj_id
# derivation, the import/verify outcome matrix, post-import verification, 9c ordering,
# the set-delete consumer guard, chart-axis-role classification) is imported from
# `apply.py`; this shell only performs REST calls and records results.
#
# CORRECTED EXECUTION ORDER (deviation from the SKILL's section bodies, documented
# per the repo's fix-latent-bug-and-say-so precedent): the SKILL's Step 9 *section
# bodies* run 9b (source) BEFORE 9c (dependents), but the SKILL's own overview
# (~line 892) and the error-14544 rationale stated three times ("Deleted columns have
# dependents" — TS rejects the SOURCE column removal while ANY dependent still
# references it, ~lines 681/892/1393) require dependents to be fixed FIRST and the
# source LAST. Running source-first would fail every REMOVE that has a live dependent.
# apply-change therefore executes: 9a deletes → dependents → source → 9d sets. This
# ordering is the #1 item to confirm during the mandatory live test (open-items #23).


def _plan_body(client: ThoughtSpotClient, entry: dict, *, include_obj_id: bool = False):
    """Return `(tml_body, err)` for one plan entry.

    If the entry carries an inline ``tml`` (required for FEEDBACK, which cannot be
    exported standalone — open-items #18), use it. Otherwise export the object fresh
    (export_fqn=True, YAML), so the mutation always runs against current state — the
    drift check has already confirmed the object is unchanged since Step 4. `tml_body`
    is the parsed doc with a single top-level type key (answer/model/liveboard/...).
    """
    inline = entry.get("tml")
    if isinstance(inline, dict) and inline:
        return inline, None
    guid = entry["guid"]
    body = {
        "metadata": [{"identifier": guid, "type": v2_type_for(entry.get("type", ""))}],
        "export_fqn": True,
        "export_associated": False,
        "formattype": "YAML",
    }
    if include_obj_id:
        body["export_options"] = {
            "include_obj_id": True, "include_obj_id_ref": True, "include_guid": False,
        }
    resp = client.post("/api/rest/2.0/metadata/tml/export", json=body, raise_for_status=False)
    if not resp.ok:
        return None, f"export HTTP {resp.status_code}: {resp.text[:150]}"
    try:
        data = resp.json()
    except ValueError:
        return None, "non-JSON export response"
    if not data:
        return None, "export returned no items"
    try:
        return parse_edoc(data[0].get("edoc", ""), "YAML"), None
    except Exception as exc:  # noqa: BLE001 — surface any parse failure as a plan error
        return None, f"edoc parse error: {exc}"


def _current_modified(client: ThoughtSpotClient, guid: str, v2_type: str):
    """Return `(found, modified_int, err)` from metadata/search for a drift check."""
    resp = client.post(
        "/api/rest/2.0/metadata/search",
        json={"metadata": [{"type": v2_type, "identifier": guid}],
              "record_size": 1, "record_offset": 0, "include_headers": True},
        raise_for_status=False,
    )
    if not resp.ok:
        return False, 0, f"HTTP {resp.status_code}: {resp.text[:120]}"
    try:
        data = resp.json()
    except ValueError:
        return False, 0, "non-JSON response"
    results = data if isinstance(data, list) else data.get("metadata", [])
    if not results:
        return False, 0, "not found"
    modified = int((results[0].get("metadata_header") or {}).get("modified", 0) or 0)
    return True, modified, None


def _drift_ok(client: ThoughtSpotClient, entry: dict) -> tuple:
    """Drift-check one entry. Returns `(ok, reason)`.

    `ok` is False (skip the object) when it drifted since the Step-4 snapshot OR the
    re-query failed / the object is gone — a failed re-query is treated as drift
    (fail safe), exactly as the SKILL's check_drift does.
    """
    snapshot = entry.get("modified_at") or 0
    found, current, err = _current_modified(client, entry["guid"], v2_type_for(entry.get("type", "")))
    if (not found) or err or is_drift(snapshot, current):
        reason = (f"DRIFT_DETECTED — modified at scan was {snapshot}, now {current}"
                  + (f"; query issue: {err}" if err else ""))
        return False, reason
    return True, ""


def _import_body(client: ThoughtSpotClient, tml_dict: dict, guid: str) -> tuple:
    """Import a mutated TML body in place (update the existing GUID; no create-new).
    Returns `(api_ok, api_error)`.
    """
    tml_yaml = _dump_tml_yaml(tml_dict, strip_guid=False, guid=guid)
    resp = client.post(
        "/api/rest/2.0/metadata/tml/import",
        json={"metadata_tmls": [tml_yaml], "import_policy": "ALL_OR_NONE", "create_new": False},
        raise_for_status=False,
    )
    ok, block = _parse_import_status(resp)
    if ok:
        return True, None
    return False, (block.get("status") or {}).get("error_message", "Unknown error")


def _verify_change(client: ThoughtSpotClient, entry: dict, operation: str, params: dict) -> tuple:
    """Re-export the object and run the pure post-import verification. Returns
    `(verified, detail)`. A failed re-export is a verification failure (never a silent
    pass), so `import_outcome` cannot mistake it for SUCCESS.
    """
    body_tml, err = _plan_body(
        client, {"guid": entry["guid"], "type": entry.get("type", "")}, include_obj_id=True,
    )
    if err:
        return False, f"verification re-export failed: {err}"
    body_str = json.dumps(body_tml)
    if operation == "REMOVE":
        return verify_remove_applied(body_str, params.get("columns_to_remove", []))
    if operation == "REPOINT":
        return verify_repoint_applied(
            body_str, params.get("target_guid"), params.get("target_obj_id"),
            params.get("column_gap", []),
        )
    return True, f"verification skipped for operation={operation}"


def _apply_one(client: ThoughtSpotClient, entry: dict, tml_dict: dict, operation: str,
               params: dict, results: dict, phase: str) -> str:
    """Import a mutated body, verify, record the outcome, and return the outcome str."""
    guid = entry["guid"]
    name = entry.get("name") or guid
    obj_type = entry.get("type", "")
    api_ok, api_err = _import_body(client, tml_dict, guid)
    verified, detail = _verify_change(client, entry, operation, params)
    outcome = import_outcome(api_ok, verified)
    record = {
        "guid": guid, "name": name, "type": obj_type, "phase": phase,
        "api_status": "OK" if api_ok else "ERROR", "api_error": api_err,
        "verified": verified, "verify_detail": detail, "outcome": outcome,
    }
    if is_success_outcome(outcome):
        if outcome == "SUCCESS_WITH_WARNING":
            record["warning"] = ("api returned ERROR but verification confirms the "
                                 "change applied (open-item #15)")
            print(f"  ⚠ {obj_type} {name} — api=ERROR, verified=True (open-item #15). "
                  f"err={str(api_err)[:120]}", file=sys.stderr)
        results["succeeded"].append(record)
        print(f"  ✓ {phase}: {name} ({outcome})", file=sys.stderr)
    else:
        record["error"] = (api_err if outcome == "FAIL_VERIFIED"
                           else f"api=OK but change not applied — {detail}")
        results["failed"].append(record)
        print(f"  ✗ {phase} failed: {name} — {outcome}: {record['error']}", file=sys.stderr)
    return outcome


def _mutate_body(body_tml: dict, entry: dict, operation: str, plan: dict, obj_ids: dict) -> dict:
    """Route a freshly-fetched TML body through the right mutate.py transform.

    REMOVE: dispatches on the body's top-level type. A standalone Answer whose removed
    column sits on a chart x/y axis (chart_role_for_answer / entry['action'] ==
    REMOVE_CHART) is converted to TABLE_MODE before the column is stripped, so it stays
    valid. Liveboards pass per-viz decisions (entry['viz_decisions']; default
    CONVERT_TO_TABLE). REPOINT: delegates to apply_repoint with obj_id-first matching.
    """
    cols = plan.get("columns_to_remove", [])
    if operation == "REPOINT":
        target = plan["target"]
        return apply_repoint(
            body_tml,
            source_guid=plan["source"]["guid"],
            target_guid=target["guid"],
            target_name=target["name"],
            column_gap=plan.get("column_gap", []),
            source_obj_id=obj_ids.get("source_obj_id"),
            target_obj_id=obj_ids.get("target_obj_id"),
        )
    # REMOVE
    if "liveboard" in body_tml:
        return apply_remove(
            body_tml, cols,
            source_guid=plan["source"]["guid"],
            viz_decisions=_parse_viz_decisions_map(entry.get("viz_decisions", {})),
        )
    if "answer" in body_tml:
        role = entry.get("action") or chart_role_for_answer(body_tml["answer"], cols)
        if role == "REMOVE_CHART":
            body_tml["answer"]["display_mode"] = "TABLE_MODE"
    return apply_remove(body_tml, cols)


def _parse_viz_decisions_map(raw: dict) -> Dict[str, str]:
    """Normalize a plan's per-viz decisions ({viz_id: 'convert'|'remove'|CONVERT_TO_TABLE|REMOVE})
    into the {viz_id: 'CONVERT_TO_TABLE'|'REMOVE'} shape apply_remove expects.
    """
    out: Dict[str, str] = {}
    for viz_id, val in (raw or {}).items():
        v = str(val).strip().lower()
        out[viz_id] = "REMOVE" if v in ("remove",) else "CONVERT_TO_TABLE"
    return out


def _delete_one(client: ThoughtSpotClient, entry: dict, results: dict, phase: str) -> bool:
    """Delete one object via metadata/delete; on API failure re-query and treat a
    now-missing object as a success (matches SKILL.md 9a). Records into results.
    """
    guid = entry["guid"]
    name = entry.get("name") or guid
    skill_type = entry.get("type", "")
    v2t = v2_type_for(skill_type)
    resp = client.post(
        "/api/rest/2.0/metadata/delete",
        json={"metadata": [{"identifier": guid, "type": v2t}]},
        raise_for_status=False,
    )
    if resp.ok:
        results["deleted"].append({"guid": guid, "name": name, "type": skill_type, "phase": phase})
        print(f"  ✓ Deleted {skill_type}: {name}", file=sys.stderr)
        return True
    found, _, _ = _current_modified(client, guid, v2t)
    if not found:
        results["deleted"].append({"guid": guid, "name": name, "type": skill_type,
                                   "phase": phase, "verified_by": "post-query"})
        print(f"  ✓ Deleted {skill_type}: {name} (verified by post-query)", file=sys.stderr)
        return True
    err = f"HTTP {resp.status_code}: {resp.text[:150]}"
    results["failed"].append({"guid": guid, "name": name, "type": skill_type,
                              "phase": phase, "error": err})
    print(f"  ✗ Delete failed: {name} — {err}", file=sys.stderr)
    return False


def _probe_source_obj_id(client: ThoughtSpotClient, source: dict):
    """Detect the source's obj_id for a REPOINT (SKILL.md ~966). Returns the obj_id
    string or None (fqn-based repoint) if the build doesn't expose obj_id.
    """
    body_tml, err = _plan_body(client, {"guid": source["guid"], "type": source.get("type", "")},
                               include_obj_id=True)
    if err or not body_tml:
        return None
    section = body_tml.get("model") or body_tml.get("worksheet") or body_tml.get("table") or {}
    for tbl in section.get("model_tables", section.get("tables", [])):
        if tbl.get("obj_id"):
            return tbl["obj_id"]
    return body_tml.get("obj_id")


@app.command("apply-change")
def apply_change_cmd(
    profile: Optional[str] = _profile_option,
) -> None:
    """Apply a dependency REMOVE/REPOINT plan end-to-end (SKILL.md Step 9).

    Reads a plan JSON on stdin and orchestrates the destructive change: delete →
    dependent-fix → source → set-delete, with a per-object drift check, obj_id-first
    repointing, and post-import verification (open-item #15: TS can report ERROR while
    the change actually applied). A prior `ts dependency backup` is REQUIRED — pass its
    directory as `backup_dir` so rollback stays possible.

    \b
    Plan shape:
      {
        "operation": "REMOVE" | "REPOINT",
        "backup_dir": "/tmp/ts_dep_backup_...",     # required (rollback safety)
        "source":  {"guid","type","name","modified_at", "tml"?},
        "columns_to_remove": [...],                  # REMOVE
        "target":  {"guid","name"},                  # REPOINT
        "column_gap": [...],                          # REPOINT (optional)
        "source_obj_id": "...",                       # REPOINT (optional; else auto-probed)
        "fix":    [{"guid","type","name","modified_at",
                    "action"?,"viz_decisions"?,"tml"?}, ...],
        "delete": [{"guid","type","name","modified_at"}, ...],
        "sets":   [{"guid","name","action","in_use_by":[...]}, ...]
      }

    Execution order is deletes → dependents → source → sets. The source column removal
    runs LAST: TS error 14544 rejects it while any dependent still references the
    column (SKILL.md overview ~line 892).

    Output: a results JSON to stdout
    (`{"operation","source",...,"succeeded","failed","deleted","skipped"}`) — the data
    behind the Step 10 Change Report. Per-object progress goes to stderr. Exits non-zero
    only if the SOURCE object drifted since the scan (hard stop — nothing is changed).
    """
    plan = _load_plan()
    operation, source = _validate_plan(plan)
    client = ThoughtSpotClient(resolve_profile(profile))
    results: Dict[str, object] = {
        "operation": operation,
        "source": {"guid": source.get("guid"), "name": source.get("name"), "type": source.get("type")},
        "backup_dir": plan.get("backup_dir"),
        "succeeded": [], "failed": [], "deleted": [], "skipped": [],
    }
    obj_ids = _resolve_obj_ids(client, operation, plan)

    # Source-drift hard stop — abort the ENTIRE run if the source moved since Step 4.
    ok, reason = _drift_ok(client, {"guid": source["guid"], "type": source.get("type", ""),
                                    "modified_at": source.get("modified_at") or 0})
    if not ok:
        results["aborted"] = True
        results["abort_reason"] = (
            f"Source object drifted since the scan ({reason}) — aborting the entire run. "
            "No changes applied. Re-run the dependency plan (Steps 1-6) to rebuild it "
            "against current source state."
        )
        print(f"  ✗ ABORT — {results['abort_reason']}", file=sys.stderr)
        print(json.dumps(results))
        raise typer.Exit(code=1)

    verify_params = {
        "columns_to_remove": plan.get("columns_to_remove", []),
        "target_guid": (plan.get("target") or {}).get("guid"),
        "target_obj_id": obj_ids.get("target_obj_id"),
        "column_gap": plan.get("column_gap", []),
    }

    _run_deletes(client, plan, results)                                    # 9a
    _run_fixes(client, plan, operation, obj_ids, verify_params, results)   # dependents
    _run_source(client, source, plan, operation, obj_ids, verify_params, results)  # source LAST
    _run_set_deletes(client, plan, results)                               # 9d

    print(json.dumps(results))


def _load_plan() -> dict:
    """Read + basic-shape-validate the apply-change plan JSON from stdin."""
    try:
        plan = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON on stdin: {e}")
    if not isinstance(plan, dict):
        raise SystemExit("Plan must be a JSON object.")
    return plan


def _validate_plan(plan: dict) -> tuple:
    """Validate required plan fields; return `(operation, source)` or raise SystemExit."""
    operation = str(plan.get("operation", "")).strip().upper()
    if operation not in ("REMOVE", "REPOINT"):
        raise SystemExit(f"Plan 'operation' must be 'REMOVE' or 'REPOINT', got: {plan.get('operation')!r}")
    source = plan.get("source") or {}
    if not source.get("guid"):
        raise SystemExit("Plan must include a 'source' object with a 'guid'.")
    if not plan.get("backup_dir"):
        raise SystemExit("Plan must include 'backup_dir' (run `ts dependency backup` first — required for rollback).")
    if operation == "REMOVE" and not plan.get("columns_to_remove"):
        raise SystemExit("REMOVE plans must include a non-empty 'columns_to_remove'.")
    if operation == "REPOINT":
        target = plan.get("target") or {}
        if not target.get("guid") or not target.get("name"):
            raise SystemExit("REPOINT plans must include 'target' with 'guid' and 'name'.")
    return operation, source


def _resolve_obj_ids(client: ThoughtSpotClient, operation: str, plan: dict) -> Dict[str, Optional[str]]:
    """Detect obj_id support for a REPOINT (probe unless the plan supplies it)."""
    obj_ids: Dict[str, Optional[str]] = {"source_obj_id": None, "target_obj_id": None}
    if operation != "REPOINT":
        return obj_ids
    src_obj_id = plan.get("source_obj_id") or _probe_source_obj_id(client, plan.get("source") or {})
    if src_obj_id:
        obj_ids["source_obj_id"] = src_obj_id
        obj_ids["target_obj_id"] = derive_target_obj_id(plan["target"]["name"], plan["target"]["guid"])
        print(f"  obj_id detected — using obj_id-based repoint (source={src_obj_id})", file=sys.stderr)
    else:
        print("  obj_id not available — using fqn-based repoint", file=sys.stderr)
    return obj_ids


def _run_deletes(client: ThoughtSpotClient, plan: dict, results: dict) -> None:
    """9a — delete `plan['delete']` objects, leaf-most types first, drift-checked."""
    for entry in sorted(plan.get("delete") or [], key=delete_sort_key):
        ok, reason = _drift_ok(client, entry)
        if not ok:
            results["skipped"].append({**_id_fields(entry), "phase": "delete", "reason": reason})
            print(f"  ⚠ Skip delete {entry.get('name')} — {reason}", file=sys.stderr)
            continue
        _delete_one(client, entry, results, phase="delete")


def _run_fixes(client: ThoughtSpotClient, plan: dict, operation: str,
               obj_ids: dict, verify_params: dict, results: dict) -> None:
    """Fix each dependent (terminal types first, Models last), drift-checked."""
    for entry in sort_fixes(plan.get("fix") or []):
        ok, reason = _drift_ok(client, entry)
        if not ok:
            results["skipped"].append({**_id_fields(entry), "phase": "fix", "reason": reason})
            print(f"  ⚠ Skip fix {entry.get('name')} — {reason}", file=sys.stderr)
            continue
        body_tml, err = _plan_body(client, entry, include_obj_id=(operation == "REPOINT"))
        if err:
            results["failed"].append({**_id_fields(entry), "phase": "fix",
                                      "error": f"could not fetch TML: {err}"})
            print(f"  ✗ fix failed: {entry.get('name')} — could not fetch TML: {err}", file=sys.stderr)
            continue
        mutated = _mutate_body(body_tml, entry, operation, plan, obj_ids)
        _apply_one(client, entry, mutated, operation, verify_params, results, phase="fix")


def _run_source(client: ThoughtSpotClient, source: dict, plan: dict, operation: str,
                obj_ids: dict, verify_params: dict, results: dict) -> None:
    """Apply the source change LAST (error 14544). No drift re-check — the hard-stop
    already confirmed the source is unchanged and nothing in this run touches it.
    """
    src_body, err = _plan_body(client, source, include_obj_id=(operation == "REPOINT"))
    if err:
        results["failed"].append({**_id_fields(source), "phase": "source",
                                  "error": f"could not fetch source TML: {err}"})
        print(f"  ✗ source fetch failed: {source.get('name')} — {err}", file=sys.stderr)
        return
    mutated_src = _mutate_body(src_body, source, operation, plan, obj_ids)
    _apply_one(client, source, mutated_src, operation, verify_params, results, phase="source")


def _run_set_deletes(client: ThoughtSpotClient, plan: dict, results: dict) -> None:
    """9d — delete reusable Sets, but only if every consumer fix succeeded."""
    failed_fix_guids = {r.get("guid") for r in results["failed"] if r.get("phase") == "fix"}
    for s in plan.get("sets") or []:
        if str(s.get("action", "")).upper() not in ("DELETE_SAFE", "DELETE_AFTER_DEPENDENTS"):
            continue
        should_delete, skip_reason = set_delete_decision(s, failed_fix_guids)
        if not should_delete:
            results["skipped"].append({"guid": s.get("guid"), "name": s.get("name"),
                                       "type": "SET", "phase": "set_delete", "reason": skip_reason})
            print(f"  ⚠ Skip delete set '{s.get('name')}' — {skip_reason}", file=sys.stderr)
            continue
        _delete_one(client, {"guid": s["guid"], "name": s.get("name"), "type": "SET"},
                    results, phase="set_delete")


def _id_fields(entry: dict) -> dict:
    """Pull the identifying fields from a plan entry for a results record."""
    return {"guid": entry.get("guid"), "name": entry.get("name") or entry.get("guid"),
            "type": entry.get("type", "")}
