"""Pure planning logic behind `ts share` — object and column grants.

No I/O, so every rule here is unit-testable without a live instance. The command
layer (`ts_cli/commands/share.py`) is the thin wrapper, mirroring how
`publish_plan.py` sits under `commands/publish.py`.

The load-bearing rule is exclusivity. Sharing a TABLE grants access to every one of
its columns (verified live 2026-07-26), so a table grant and a column grant for the
same (org, table, group) are not additive in a safe way -- the table grant silently
defeats the column grants. A manifest carrying both is refused rather than reconciled.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

SHARE_MODES: Tuple[str, ...] = ("READ_ONLY", "MODIFY", "NO_ACCESS")

# The types a caller may name in a manifest. LOGICAL_COLUMN is deliberately absent:
# a column grant is expressed as a `column_name` on its LOGICAL_TABLE row, and the
# LOGICAL_COLUMN metadata_type is synthesised when the plan is built.
GRANTABLE_TYPES: Tuple[str, ...] = ("LOGICAL_TABLE", "LIVEBOARD", "ANSWER")

# Mirrors the `ts alias` / `ts publish` convention: one manifest table, emitted by
# --init-table. The unit is (org, object, group, share_mode) with an optional column,
# so one table covers both granularities.
SHARE_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS TS_SHARE_GRANTS (\n"
    "    org_name          VARCHAR NOT NULL,\n"
    "    object_identifier VARCHAR NOT NULL,\n"
    "    object_type       VARCHAR NOT NULL,   -- LOGICAL_TABLE | LIVEBOARD | ANSWER\n"
    "    column_name       VARCHAR,            -- blank = object grant; set = column grant\n"
    "    group_name        VARCHAR NOT NULL,\n"
    "    share_mode        VARCHAR NOT NULL,   -- READ_ONLY | MODIFY | NO_ACCESS\n"
    "    updated_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),\n"
    "    PRIMARY KEY (org_name, object_identifier, column_name, group_name)\n"
    ");"
)

_GRANT_KEYS = ("org_name", "object_identifier", "object_type", "column_name",
               "group_name", "share_mode")


class GrantConflictError(ValueError):
    """A manifest mixes table-level and column-level grants for one (org, table, group)."""


def _lower_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    """Case-insensitive column access, so a CSV header and a Snowflake
    (upper-cased) column name parse identically."""
    return {str(k).strip().lower(): v for k, v in (row or {}).items()}


def _text(row: Dict[str, Any], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def parse_grant_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Parse a grant manifest into normalised rows.

    Columns: ``org_name``, ``object_identifier``, ``object_type``, ``group_name``,
    ``share_mode`` (all required) and ``column_name`` (optional; blank means the
    grant is on the object itself).

    Enum-valued fields (``object_type``, ``share_mode``) are upper-cased; identifier
    fields (org, object, column, group) keep the operator's casing, because they are
    matched against real names on the instance.

    Fully blank rows are skipped so a trailing CSV newline is harmless. A partially
    filled row is an error: silently dropping a grant is how data ends up either
    exposed or invisible with no trace of why.

    Two rows with the same primary key and the same ``share_mode`` de-duplicate. Two
    with the same key and *different* modes are refused -- picking one would be a
    coin-flip over who can see tenant data.
    """
    parsed: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    for raw in rows or ():
        row = _lower_keys(raw)
        values = {key: _text(row, key) for key in _GRANT_KEYS}
        if not any(values.values()):
            continue

        for field in ("org_name", "object_identifier", "group_name"):
            if not values[field]:
                raise ValueError(f"Grant row is missing {field}: {raw!r}")

        obj_type = values["object_type"].upper() or "LOGICAL_TABLE"
        if obj_type not in GRANTABLE_TYPES:
            raise ValueError(
                f"object_type '{values['object_type']}' cannot be shared by this command. "
                f"Expected one of: {', '.join(GRANTABLE_TYPES)}. Row: {raw!r}")

        share_mode = values["share_mode"].upper()
        if share_mode not in SHARE_MODES:
            raise ValueError(
                f"share_mode '{values['share_mode']}' is not valid. Expected one of: "
                f"{', '.join(SHARE_MODES)}. Row: {raw!r}")

        if values["column_name"] and obj_type != "LOGICAL_TABLE":
            raise ValueError(
                f"column_name is only meaningful on a LOGICAL_TABLE row; got "
                f"object_type '{obj_type}'. Row: {raw!r}")

        grant = {
            "org_name": values["org_name"],
            "object_identifier": values["object_identifier"],
            "object_type": obj_type,
            "column_name": values["column_name"],
            "group_name": values["group_name"],
            "share_mode": share_mode,
        }
        key = (grant["org_name"], grant["object_identifier"],
               grant["column_name"], grant["group_name"])
        existing = parsed.get(key)
        if existing and existing["share_mode"] != share_mode:
            target = (f"column '{grant['column_name']}' of " if grant["column_name"] else "")
            raise ValueError(
                f"Grant manifest has conflicting share_mode for {target}"
                f"'{grant['object_identifier']}' / group '{grant['group_name']}' in org "
                f"'{grant['org_name']}': {existing['share_mode']} and {share_mode}. "
                f"Remove one -- guessing which the operator meant is not safe here.")
        parsed[key] = grant
    return list(parsed.values())


def find_exclusivity_conflicts(grants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find (org, table, group) triples carrying BOTH a table grant and column grants.

    Sharing the table grants every column, so the two are not additive: the table
    grant defeats the column grants and column security stops meaning anything. The
    check ignores ``share_mode`` deliberately -- including NO_ACCESS. Whether a
    table-level NO_ACCESS also clears existing column grants is unverified, so a
    revoke-then-grant sequence cannot be ordered safely inside one manifest; it
    belongs in two runs.

    Returns one entry per conflicting triple, sorted for a stable message.
    """
    tables: Dict[Tuple[str, str, str], List[str]] = {}
    columns: Dict[Tuple[str, str, str], List[str]] = {}
    for grant in grants or ():
        if grant.get("object_type") != "LOGICAL_TABLE":
            continue
        key = (grant["org_name"], grant["object_identifier"], grant["group_name"])
        if grant.get("column_name"):
            columns.setdefault(key, []).append(grant["column_name"])
        else:
            tables.setdefault(key, []).append(grant["share_mode"])

    conflicts: List[Dict[str, Any]] = []
    for key in sorted(set(tables) & set(columns)):
        org, obj, group = key
        conflicts.append({
            "org_name": org,
            "object_identifier": obj,
            "group_name": group,
            "table_share_modes": sorted(set(tables[key])),
            "column_names": sorted(set(columns[key])),
        })
    return conflicts


def format_conflicts(conflicts: List[Dict[str, Any]]) -> str:
    """Render conflicts as an operator-facing refusal that names the fix."""
    lines = [
        "Refusing to apply: the manifest mixes table-level and column-level grants.",
        "Sharing a table grants every column in it, so a table grant silently defeats "
        "the column grants beside it and column security stops applying.",
        "",
    ]
    for conflict in conflicts:
        lines.append(
            f"  org '{conflict['org_name']}' / table '{conflict['object_identifier']}' / "
            f"group '{conflict['group_name']}': table grant "
            f"({', '.join(conflict['table_share_modes'])}) alongside column grant(s) on "
            f"{', '.join(conflict['column_names'])}")
    lines += [
        "",
        "Pick one granularity per (org, table, group): grant at table level when the table "
        "has no secured columns, and at column level only -- never both -- when it does. "
        "To change granularity, run the revoke and the grant as two separate applies.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plan assembly -- the `ts share apply` engine
# ---------------------------------------------------------------------------

def _step_key(grant: Dict[str, Any]) -> Tuple[str, str]:
    """(org, metadata_type) -- the two axes a single share call cannot span.

    One call carries one metadata_type and runs in one Org's context, because
    groups are per-Org.
    """
    metadata_type = "LOGICAL_COLUMN" if grant.get("column_name") else grant["object_type"]
    return grant["org_name"], metadata_type


def _target(grant: Dict[str, Any]) -> Tuple[str, str]:
    """(guid, human label) for the thing being granted, with the guid required.

    A missing guid means resolution did not run or did not find the object. Building
    a payload around an empty identifier would share nothing while reporting success.
    """
    if grant.get("column_name"):
        guid = str(grant.get("column_guid") or "")
        if not guid:
            raise ValueError(
                f"Grant for column '{grant['column_name']}' of "
                f"'{grant['object_identifier']}' has no column_guid. Run "
                f"`ts share resolve` so column names are resolved to GUIDs.")
        return guid, f"{grant['object_identifier']}.{grant['column_name']}"
    guid = str(grant.get("object_guid") or "")
    if not guid:
        raise ValueError(
            f"Grant for '{grant['object_identifier']}' has no object_guid. Run "
            f"`ts share resolve` so object names are resolved to GUIDs.")
    return guid, str(grant["object_identifier"])


def build_share_steps(grants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Batch resolved grants into the fewest safe `security/metadata/share` calls.

    One call takes one ``metadata_type``, many ``metadata_identifiers`` and one
    ``permissions`` list that applies to ALL of those identifiers. So objects batch
    together only when their principal/share_mode set is identical -- otherwise a
    batch would hand one object's audience access to another's data.

    Everything is sorted -- steps, identifiers within a step, and principals within a
    step -- so the same set of grants always yields the same plan whatever order the
    manifest listed them in. That is what makes a --dry-run plan diffable between runs.
    """
    # (org, metadata_type) -> guid -> {"label": str, "pairs": {(group, mode)}}
    targets: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = {}
    for grant in grants or ():
        key = _step_key(grant)
        guid, label = _target(grant)
        entry = targets.setdefault(key, {}).setdefault(guid, {"label": label, "pairs": set()})
        entry["pairs"].add((grant["group_name"], grant["share_mode"]))

    steps: List[Dict[str, Any]] = []
    for (org, metadata_type) in sorted(targets):
        # Group the objects of this (org, type) by their audience, so objects sharing
        # an identical principal set travel in one call and nothing else does.
        by_audience: Dict[Tuple[Tuple[str, str], ...], List[Tuple[str, str]]] = {}
        for guid, entry in targets[(org, metadata_type)].items():
            audience = tuple(sorted(entry["pairs"]))
            by_audience.setdefault(audience, []).append((guid, entry["label"]))

        for audience in sorted(by_audience):
            members = sorted(by_audience[audience])
            steps.append({
                "org_name": org,
                "metadata_type": metadata_type,
                "metadata_identifiers": [guid for guid, _ in members],
                "permissions": [
                    {"principal": {"type": "USER_GROUP", "identifier": group},
                     "share_mode": mode}
                    for group, mode in audience
                ],
                "labels": [label for _, label in members],
            })
    return steps


# ---------------------------------------------------------------------------
# Read-back -- the `ts share status` normaliser
# ---------------------------------------------------------------------------

def _str(value: Any) -> str:
    """Missing or null field to an empty string, without a branch at each call site."""
    return "" if value is None else str(value)


def _dicts(container: Any, key: str) -> List[Dict[str, Any]]:
    """The dict members of ``container[key]``, tolerating a missing or odd shape.

    A read-back must not fail louder than the write it is checking, so anything
    unexpected is skipped rather than raised on.
    """
    if not isinstance(container, dict):
        return []
    return [item for item in (container.get(key) or []) if isinstance(item, dict)]


def _permission_row(entry: Dict[str, Any], info: Dict[str, Any],
                    principal: Dict[str, Any]) -> Dict[str, Any]:
    """One (object, principal) row from the three nesting levels it spans."""
    return {
        "guid": _str(entry.get("metadata_id")),
        "name": _str(entry.get("metadata_name")),
        "type": _str(entry.get("metadata_type")),
        "principal_type": _str(info.get("principal_type")),
        "principal_id": _str(principal.get("principal_id")),
        "principal_name": _str(principal.get("principal_name")),
        "permission": _str(principal.get("permission")),
        "shared_permission": _str(principal.get("shared_permission")),
    }


def permission_rows(details: Any) -> List[Dict[str, Any]]:
    """Flatten a `security/metadata/fetch-permissions` response into flat rows.

    The response nests three levels deep (object -> principal type -> principal), which
    is awkward to eyeball or diff. One row per (object, principal) is what an operator
    actually reads, and what a before/after comparison needs.

    ``permission`` is the EFFECTIVE access (privileges included); ``shared_permission``
    is what sharing itself granted. When checking whether `ts share` did its job, read
    ``shared_permission`` -- an admin group shows MODIFY under ``permission`` whether or
    not anything was ever shared with it.

    Accepts either the ``{"metadata_permission_details": [...]}`` envelope or a bare list.
    """
    if isinstance(details, list):
        entries = [item for item in details if isinstance(item, dict)]
    else:
        entries = _dicts(details, "metadata_permission_details")

    return [
        _permission_row(entry, info, principal)
        for entry in entries
        for info in _dicts(entry, "principal_permission_info")
        for principal in _dicts(info, "principal_permissions")
    ]
