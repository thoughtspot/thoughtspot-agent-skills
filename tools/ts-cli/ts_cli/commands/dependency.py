"""ts dependency — backup / mutate / rollback engine for ts-dependency-manager (BL-083).

I/O shell over the pure helpers in `ts_cli.dependency` (mutate.py / backup.py). Extracted
from `agents/cli/ts-dependency-manager/SKILL.md` Steps 7 (backup), 9 (mutate), and 11
(rollback) — see those modules' docstrings for the full extraction rationale. Mirrors the
pure-module + thin-command-shell pattern in `ts_cli/snowflake_ops.py` +
`ts_cli/commands/snowflake.py`.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import typer
import yaml

from ts_cli.client import ThoughtSpotClient, resolve_profile
from ts_cli.commands.tml import detect_tml_type, parse_edoc
from ts_cli.dependency.backup import (
    build_manifest,
    backup_filename,
    restore_policy_for,
    rollback_order,
)
from ts_cli.dependency.mutate import apply_remove, apply_repoint
from ts_cli.tml_common import extract_imported_guid

app = typer.Typer(help="ThoughtSpot dependency backup / mutate / rollback / apply-change (BL-083).")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


# ---------------------------------------------------------------------------
# `ts dependency mutate` — pure transform, no network
# ---------------------------------------------------------------------------

def _read_tml_doc(file: Optional[str]) -> dict:
    """Read one TML doc from --file or stdin.

    Accepts either a raw `{...tml...}` object (a bare `answer:`/`model:`/etc. body
    at the top level) OR a `ts tml export --parse` array element shape
    `{"type": ..., "guid": ..., "tml": {...}, "info": {...}}` — in the latter case
    the `tml` key is unwrapped automatically.
    """
    if file:
        p = Path(file)
        if not p.is_file():
            raise SystemExit(f"--file path does not exist or is not a file: {file}")
        raw = p.read_text()
    else:
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON input: {e}")

    if isinstance(data, dict) and isinstance(data.get("tml"), dict):
        return data["tml"]
    if isinstance(data, dict):
        return data
    raise SystemExit(
        "Input must be a JSON object — either a bare TML doc or a "
        "`ts tml export --parse` item (`{\"tml\": {...}, ...}`)."
    )


def _parse_viz_decisions(pairs: List[str]) -> Dict[str, str]:
    decisions: Dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(
                f"--viz-decision must be of the form viz_id=convert|remove, got: {pair!r}"
            )
        viz_id, raw_decision = pair.split("=", 1)
        d = raw_decision.strip().lower()
        if d in ("convert", "convert_to_table"):
            decisions[viz_id] = "CONVERT_TO_TABLE"
        elif d == "remove":
            decisions[viz_id] = "REMOVE"
        else:
            raise SystemExit(
                f"--viz-decision value must be 'convert' or 'remove', got: {raw_decision!r}"
            )
    return decisions


def _split_csv(value: Optional[str]) -> List[str]:
    return [c.strip() for c in (value or "").split(",") if c.strip()]


@app.command("mutate")
def mutate_cmd(
    operation: str = typer.Option(..., "--operation", help="remove | repoint"),
    file: Optional[str] = typer.Option(
        None, "--file", help="Path to a JSON TML doc. Reads stdin if omitted.",
    ),
    remove_columns: Optional[str] = typer.Option(
        None, "--remove-columns",
        help="Comma-separated column names to remove (required for --operation remove).",
    ),
    source_guid: Optional[str] = typer.Option(
        None, "--source-guid", help="Source object GUID (fqn match / liveboard viz scoping).",
    ),
    target_guid: Optional[str] = typer.Option(
        None, "--target-guid", help="Target object GUID (required for --operation repoint).",
    ),
    target_name: Optional[str] = typer.Option(
        None, "--target-name", help="Target object display name (required for --operation repoint).",
    ),
    column_gap: Optional[str] = typer.Option(
        None, "--column-gap",
        help="Comma-separated columns present on the source but absent on the repoint "
             "target — removed from the repointed object same as REMOVE (operation=repoint).",
    ),
    source_obj_id: Optional[str] = typer.Option(
        None, "--source-obj-id", help="Source obj_id (preferred over --source-guid when present).",
    ),
    target_obj_id: Optional[str] = typer.Option(
        None, "--target-obj-id", help="Target obj_id (preferred over --target-guid when present).",
    ),
    viz_decision: List[str] = typer.Option(
        [], "--viz-decision",
        help="Repeatable viz_id=convert|remove — per-visualization decision for a "
             "liveboard REMOVE where the viz's chart axis uses the removed column. "
             "Default (any viz not listed): convert.",
    ),
) -> None:
    """Apply a REMOVE or REPOINT mutation to one parsed TML document.

    PURE transform — no network calls. Reads exactly one TML doc from --file or
    stdin (either a bare TML body or a `ts tml export --parse` item; see
    `_read_tml_doc`), applies `ts_cli.dependency.apply_remove` /
    `apply_repoint`, and prints the mutated doc as JSON to stdout. The result still
    needs to be serialized back to a TML YAML string and imported via
    `ts tml import` — that wiring is the calling skill's job, not this command's.

    Examples:

    \b
      ts dependency mutate --operation remove --file answer.json \\
        --remove-columns "Revenue,Cost" > answer_fixed.json

      ts tml export abc-123 --fqn --parse | jq '.[0]' \\
        | ts dependency mutate --operation repoint \\
            --source-guid abc-123 --target-guid def-456 --target-name "New Model" \\
            --column-gap "Legacy Col"

      ts dependency mutate --operation remove --file liveboard.json \\
        --remove-columns Region --source-guid abc-123 \\
        --viz-decision viz1=remove --viz-decision viz2=convert
    """
    op = operation.strip().upper()
    if op not in ("REMOVE", "REPOINT"):
        raise SystemExit(f"--operation must be 'remove' or 'repoint', got: {operation!r}")

    doc = _read_tml_doc(file)
    decisions = _parse_viz_decisions(viz_decision)

    if op == "REMOVE":
        cols = _split_csv(remove_columns)
        if not cols:
            raise SystemExit("--remove-columns is required (non-empty) for --operation remove.")
        mutated = apply_remove(doc, cols, source_guid=source_guid, viz_decisions=decisions)
        print(f"  REMOVE applied — {len(cols)} column(s): {cols}", file=sys.stderr)
    else:
        if not target_guid or not target_name:
            raise SystemExit("--target-guid and --target-name are required for --operation repoint.")
        gap = _split_csv(column_gap)
        mutated = apply_repoint(
            doc,
            source_guid=source_guid,
            target_guid=target_guid,
            target_name=target_name,
            column_gap=gap,
            source_obj_id=source_obj_id,
            target_obj_id=target_obj_id,
        )
        print(
            f"  REPOINT applied — target={target_name!r} ({target_guid}); column_gap={gap}",
            file=sys.stderr,
        )

    print(json.dumps(mutated))


# ---------------------------------------------------------------------------
# `ts dependency backup` — export + save TML for source + fix[] + delete[]
# ---------------------------------------------------------------------------

def _export_one(client: ThoughtSpotClient, obj: dict) -> List[dict]:
    """Export TML for one plan entry (source/fix/delete) and parse each returned
    edoc. Returns the parsed items (`type`/`guid`/`tml`/`info` dicts). Raises
    SystemExit on export or parse failure — safe to call before any backup file
    has been written, per `backup_cmd`'s all-or-nothing contract.
    """
    guid = obj["guid"]
    resp = client.post(
        "/api/rest/2.0/metadata/tml/export",
        json={
            "metadata": [{"identifier": guid}],
            "export_fqn": True,
            "export_associated": False,
            "formattype": "YAML",
        },
        raise_for_status=False,
    )
    if not resp.ok:
        raise SystemExit(
            f"Backup FAILED for '{obj.get('name', guid)}' ({guid}) — "
            f"intent={obj.get('intent')}. No changes have been applied and no "
            f"backup files were written. HTTP {resp.status_code}: {resp.text[:300]}"
        )
    data = resp.json()
    items = []
    for item in data:
        edoc = item.get("edoc", "")
        info = item.get("info", {})
        try:
            parsed = parse_edoc(edoc, "YAML")
        except Exception as exc:
            raise SystemExit(
                f"Backup FAILED to parse TML for '{obj.get('name', guid)}' ({guid}): {exc}. "
                "No changes have been applied and no backup files were written."
            )
        items.append({
            "type": detect_tml_type(parsed),
            "guid": parsed.get("guid", guid),
            "tml": parsed,
            "info": info,
        })
    return items


def _write_backup_files(backup_dir: str, exported: List[tuple], manifest: dict) -> None:
    """Write one JSON file per exported item under `backup_dir` and append a
    matching entry to `manifest["objects"]` (mutated in place). Called only
    after every export in `exported` has already succeeded.
    """
    for obj, items in exported:
        for item in items:
            fname = backup_filename(item["type"], item["guid"], obj.get("name", item["guid"]))
            backup_file = os.path.join(backup_dir, fname)
            with open(backup_file, "w") as f:
                json.dump(item, f, indent=2)
            manifest["objects"].append({
                "guid": item["guid"],
                "name": obj.get("name"),
                "type": item["type"],
                "intent": obj.get("intent", "FIX"),
                "backup_file": backup_file,
            })


@app.command("backup")
def backup_cmd(
    profile: Optional[str] = _profile_option,
) -> None:
    """Back up TML for a source object and its fix/delete dependents (SKILL.md Step 7).

    Reads a plan JSON on stdin:

    \b
      {
        "operation": "REMOVE" | "REPOINT",
        "source": {"guid": "...", "type": "MODEL", "name": "..."},
        "fix":    [{"guid": "...", "type": "ANSWER", "name": "..."}, ...],
        "delete": [{"guid": "...", "type": "LIVEBOARD", "name": "..."}, ...],
        "out_dir": "/tmp"
      }

    `fix`/`delete`/`out_dir` are optional (default: `[]`/`[]`/`"/tmp"`). Exports the
    TML for the source object plus every object in `fix`/`delete` the SAME way
    `ts tml export --parse` does (export_fqn=True, export_associated=False,
    formattype YAML).

    All exports are collected in memory FIRST. Only if every export succeeds are
    backup files written — if ANY export fails, the command aborts with a non-zero
    exit and a clear message, and writes NOTHING (no partial backup directory is
    left behind to be mistaken for a complete one).

    Output: the manifest JSON to stdout. The backup directory path and per-object
    counts go to stderr.

    Example:

    \b
      echo '{"operation": "REMOVE", "source": {"guid": "abc-123", "type": "MODEL", "name": "Orders Model"},
             "fix": [{"guid": "def-456", "type": "ANSWER", "name": "Revenue by Region"}]}' \\
        | ts dependency backup --profile prod
    """
    try:
        plan = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON on stdin: {e}")

    if not isinstance(plan, dict):
        raise SystemExit("Plan must be a JSON object.")

    source = plan.get("source") or {}
    if not source.get("guid"):
        raise SystemExit("Plan must include a 'source' object with a 'guid'.")

    fix_list = plan.get("fix") or []
    delete_list = plan.get("delete") or []

    to_backup = (
        [{**source, "intent": "FIX_SOURCE"}]
        + [{**d, "intent": "FIX"} for d in fix_list]
        + [{**d, "intent": "DELETE"} for d in delete_list]
    )

    resolved_profile = resolve_profile(profile)
    client = ThoughtSpotClient(resolved_profile)

    print(
        f"  {len(to_backup)} object(s) to export "
        f"(1 source + {len(fix_list)} fix + {len(delete_list)} delete)",
        file=sys.stderr,
    )

    # Collect ALL exports first — nothing is written to disk until every export
    # (and every edoc parse) has succeeded.
    exported: List[tuple] = [(obj, _export_one(client, obj)) for obj in to_backup]

    # Every export succeeded — now (and only now) write files.
    out_dir_base = plan.get("out_dir") or "/tmp"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(out_dir_base, f"ts_dep_backup_{timestamp}")
    os.makedirs(backup_dir, exist_ok=True)

    manifest = build_manifest(
        created=timestamp,
        profile=resolved_profile,
        base_url=client.base_url,
        operation=plan.get("operation", ""),
        source={"guid": source.get("guid"), "name": source.get("name"), "type": source.get("type")},
        fix_count=len(fix_list),
        delete_count=len(delete_list),
    )

    _write_backup_files(backup_dir, exported, manifest)

    manifest_path = os.path.join(backup_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Backed up {len(manifest['objects'])} file(s) to {backup_dir}", file=sys.stderr)
    print(json.dumps(manifest))


# ---------------------------------------------------------------------------
# `ts dependency rollback` — restore from a backup directory
# ---------------------------------------------------------------------------

# SKILL.md's import_tml() helper (~1158-1189) registers a custom string representer
# on the DEFAULT yaml.Dumper via `yaml.add_representer`, which is global process
# state. We get the identical serialization behaviour without that global side
# effect by subclassing Dumper and registering on the subclass only — other CLI
# commands' yaml.dump() calls (tables.py, tml.py) are unaffected either way.
def _str_representer(dumper: "yaml.Dumper", data: str):
    if "\n" in data or ("{" in data and "}" in data):
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=">")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


class _DependencyYamlDumper(yaml.Dumper):
    pass


_DependencyYamlDumper.add_representer(str, _str_representer)


def _dump_tml_yaml(tml_dict: dict, *, strip_guid: bool, guid: Optional[str]) -> str:
    """Serialize a TML dict to YAML for import, matching SKILL.md's `import_tml()`
    guid handling (~1178-1182): `create_new=True` strips any existing `guid:` line
    so ThoughtSpot assigns a new one; otherwise a `guid:` line is added if the dict
    doesn't already carry one.

    Deviation from the SKILL.md snippet (documented per this repo's fix-and-say-so
    precedent, e.g. `snowflake_ops.normalise_expr`): SKILL.md's `import_tml()` decides
    whether to prepend `guid:` by checking `tml_yaml.strip().startswith("guid:")`
    AFTER dumping. `yaml.dump()` defaults to `sort_keys=True`, so that check is only
    reliable when the OTHER top-level key sorts after "guid" alphabetically — true
    for model/table/view/worksheet/liveboard, but FALSE for "answer" (a < g). For an
    Answer TML dict that already has a `guid` key, the dump sorts `answer:` before
    `guid:`, the startswith check fails, and the original snippet prepends a SECOND
    `guid:` line — invalid YAML (duplicate mapping key) that breaks Answer rollback.
    This version checks `"guid" in tml_dict` directly, before serialization, which is
    order-independent and correct for every TML type.
    """
    tml_yaml = yaml.dump(
        tml_dict, Dumper=_DependencyYamlDumper, allow_unicode=True, default_flow_style=False,
    )
    if strip_guid:
        tml_yaml = re.sub(r"^guid:\s*\S+\s*\n", "", tml_yaml, count=1, flags=re.MULTILINE)
    elif "guid" not in tml_dict and guid:
        tml_yaml = f"guid: {guid}\n" + tml_yaml
    return tml_yaml


def _parse_import_status(resp) -> tuple:
    """Parse a `tml/import` response into `(ok, response_block)`.

    Normalizes the array-of-one vs bare-dict response shapes into a single
    `response_block` dict (the `"response"` key: `status` + `object`). `ok` is
    True when `response_block["status"]["status_code"] == "OK"`.
    """
    try:
        data = resp.json()
    except ValueError:
        data = {}
    item = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    response_block = item.get("response", {}) if isinstance(item, dict) else {}
    status = response_block.get("status", {})
    ok = status.get("status_code") == "OK"
    return ok, response_block


def _rollback_one_entry(client: ThoughtSpotClient, entry: dict, results: Dict[str, object]) -> None:
    """Restore one manifest entry and record the outcome into `results`
    (`succeeded`/`failed`/`new_guids`, mutated in place). Progress goes to stderr.

    For an entry with `intent == "DELETE"`, re-imports the backed-up TML with
    `create_new=True` and the `guid:` line stripped — the object no longer exists
    at its original GUID, so ThoughtSpot assigns a new one. Any other entry is
    updated in place (`create_new=False`) at its original GUID.
    """
    name = entry.get("name")
    backup_file = entry.get("backup_file")
    if not backup_file or not os.path.isfile(backup_file):
        results["failed"].append({"name": name, "guid": entry.get("guid"),
                                  "error": f"backup file missing: {backup_file}"})
        print(f"  ✗ Rollback failed: {name} — backup file missing", file=sys.stderr)
        return

    with open(backup_file) as f:
        backup_item = json.load(f)

    was_deleted = entry.get("intent") == "DELETE"
    policy = restore_policy_for(backup_item.get("type", ""))
    tml_dict = dict(backup_item.get("tml") or {})
    if was_deleted:
        tml_dict.pop("guid", None)

    tml_yaml = _dump_tml_yaml(tml_dict, strip_guid=was_deleted, guid=entry.get("guid"))

    resp = client.post(
        "/api/rest/2.0/metadata/tml/import",
        json={
            "metadata_tmls": [tml_yaml],
            "import_policy": policy,
            "create_new": was_deleted,
        },
        raise_for_status=False,
    )
    ok, response_block = _parse_import_status(resp)

    if ok:
        new_guid = extract_imported_guid([{"response": response_block}])
        label = name
        if was_deleted and new_guid:
            label = f"{name} (new GUID: {new_guid})"
            results["new_guids"][entry.get("guid")] = new_guid
        results["succeeded"].append({"guid": entry.get("guid"), "name": name, "label": label})
        print(f"  ✓ Rolled back: {label}", file=sys.stderr)
    else:
        status = response_block.get("status", {})
        err = status.get("error_message", "Unknown error")
        results["failed"].append({"name": name, "guid": entry.get("guid"), "error": err})
        print(f"  ✗ Rollback failed: {name} — {err}", file=sys.stderr)


@app.command("rollback")
def rollback_cmd(
    backup_dir: str = typer.Option(..., "--backup-dir", help="Backup directory containing manifest.json."),
    guid: List[str] = typer.Option(
        [], "--guid",
        help="Restrict rollback to these GUID(s) (repeatable). Default: every object in the manifest.",
    ),
    only: str = typer.Option(
        "all", "--only", help="Which objects to restore: updates | deletes | all.",
    ),
    profile: Optional[str] = _profile_option,
) -> None:
    """Roll back a ts-dependency-manager mutation run from a Step-7 backup (SKILL.md Step 11).

    Reads `manifest.json` from `--backup-dir`, restores entries in `rollback_order`
    (dependents before source). For an entry with `intent == "DELETE"`, re-imports
    the backed-up TML with `create_new=True` and the `guid:` line stripped — the
    object no longer exists at its original GUID, so ThoughtSpot assigns a new one.
    Any other entry is updated in place (`create_new=False`) at its original GUID.

    Output: `{"succeeded": [...], "failed": [...], "new_guids": {old_guid: new_guid}}`
    to stdout. Per-object progress goes to stderr. `new_guids` lets the caller
    surface a GUID-remap table for any restored DELETE — other objects that
    referenced the ORIGINAL guid remain broken and need manual reattachment.

    Example:

    \b
      ts dependency rollback --backup-dir /tmp/ts_dep_backup_20260704_120000 --profile prod
      ts dependency rollback --backup-dir /tmp/ts_dep_backup_20260704_120000 --only deletes
    """
    only_norm = only.strip().lower()
    if only_norm not in ("updates", "deletes", "all"):
        raise SystemExit(f"--only must be one of: updates, deletes, all. Got: {only!r}")

    manifest_path = os.path.join(backup_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        raise SystemExit(f"No manifest.json found in {backup_dir}")
    with open(manifest_path) as f:
        manifest = json.load(f)

    guid_filter = set(guid) if guid else None

    def _wanted(entry: dict) -> bool:
        if guid_filter is not None and entry.get("guid") not in guid_filter:
            return False
        is_delete = entry.get("intent") == "DELETE"
        if only_norm == "updates":
            return not is_delete
        if only_norm == "deletes":
            return is_delete
        return True

    entries = [e for e in manifest.get("objects", []) if _wanted(e)]
    ordered = rollback_order(entries)

    resolved_profile = resolve_profile(profile)
    client = ThoughtSpotClient(resolved_profile)

    results: Dict[str, object] = {"succeeded": [], "failed": [], "new_guids": {}}

    for entry in ordered:
        _rollback_one_entry(client, entry, results)

    print(json.dumps(results))
