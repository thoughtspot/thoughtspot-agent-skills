"""ts_cli.dependency.backup — pure helpers behind `ts dependency backup`/`rollback`.

Extracted from `agents/cli/ts-dependency-manager/SKILL.md` Step 7 (TML Backup, ~lines
727-860), Step 9a (delete ordering + v2 type map, ~lines 1067-1145), and Step 11
(Rollback, ~lines 2038-2141) as part of BL-083 PR1. Pure functions only — no I/O, no
network. The I/O shell (export/import over the network, file writes, manifest.json
reads) lives in `ts_cli.commands.dependency`.
"""
from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Backup file naming (SKILL.md ~834)
# ---------------------------------------------------------------------------

def backup_filename(obj_type: str, guid: str, name: str) -> str:
    """Return the backup filename for one exported object.

    Matches SKILL.md's Step 7 naming exactly: `{type}_{guid}_{safe_name}.json`, where
    `safe_name` replaces path separators with underscores and is truncated to 60
    characters (long object names would otherwise produce unwieldy — or on some
    filesystems, invalid — filenames).
    """
    safe = name.replace("/", "_").replace("\\", "_")[:60]
    return f"{obj_type}_{guid}_{safe}.json"


# ---------------------------------------------------------------------------
# Delete ordering (SKILL.md ~1079-1101, Step 9a)
# ---------------------------------------------------------------------------

# Delete order: terminal types first, then non-terminal (Sets, Models/Views, source
# last). Sets are intentionally placed before Models/Views — a Set's parent Model
# still needs to exist so the Set's TML can be backed up earlier in Step 7. Sets
# delete cleanly even while their Model is still present, since the cascade is
# one-directional.
DELETE_ORDER: Dict[str, int] = {
    "LIVEBOARD": 0,
    "ANSWER": 1,
    "SET": 2,
    "COHORT": 2,
    "VIEW": 3,
    "MODEL": 4,
    "WORKSHEET": 4,
    "TABLE": 5,
}


def delete_sort_key(obj: Dict[str, Any]) -> int:
    """Sort key for the Step 9a delete loop — `obj["type"]` (case-insensitive)
    looked up in `DELETE_ORDER`; unknown types sort last (9)."""
    return DELETE_ORDER.get(str(obj.get("type", "")).upper(), 9)


# v2 `--type` values expected by `ts metadata delete` (SKILL.md ~1093-1102).
V2_TYPE_MAP: Dict[str, str] = {
    "ANSWER": "ANSWER",
    "LIVEBOARD": "LIVEBOARD",
    "MODEL": "LOGICAL_TABLE",
    "WORKSHEET": "LOGICAL_TABLE",
    "VIEW": "LOGICAL_TABLE",
    "TABLE": "LOGICAL_TABLE",
    "SET": "LOGICAL_COLUMN",
    "COHORT": "LOGICAL_COLUMN",
}


# ---------------------------------------------------------------------------
# Rollback ordering + restore policy (SKILL.md ~2087-2100, Step 11)
# ---------------------------------------------------------------------------

def restore_policy_for(tml_type: str) -> str:
    """Import policy to use when restoring a backed-up object.

    Matches SKILL.md's `restore_policy` dict: connection tables use PARTIAL
    (best-effort — a table restore tolerates partial column failures); everything
    else (model, answer, liveboard, view, worksheet, ...) uses ALL_OR_NONE.
    """
    return "PARTIAL" if str(tml_type).lower() == "table" else "ALL_OR_NONE"


def rollback_sort_key(entry: Dict[str, Any]) -> int:
    """Sort key used to build rollback order: table entries sort first (0), every
    other type sorts after (1). Matches SKILL.md ~2098:
    `entries.sort(key=lambda e: 0 if e["type"] == "table" else 1)`.
    """
    return 0 if entry.get("type") == "table" else 1


def rollback_order(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return `entries` in restore order: dependents before source.

    Matches SKILL.md ~2098-2100 exactly — sort ascending by `rollback_sort_key`
    (tables first, everything else after) and then iterate in REVERSE. Since a
    connection Table is the typical REPOINT/REMOVE source and everything else is a
    dependent, this restores dependents (key=1, sorted first in the reversed list)
    before the source table (key=0, restored last). Does not mutate `entries`.
    """
    return list(reversed(sorted(entries, key=rollback_sort_key)))


# ---------------------------------------------------------------------------
# Manifest skeleton (SKILL.md ~803-812, Step 7)
# ---------------------------------------------------------------------------

def build_manifest(
    *,
    created: str,
    profile: str,
    base_url: str,
    operation: str,
    source: Dict[str, Any],
    fix_count: int,
    delete_count: int,
) -> Dict[str, Any]:
    """Return the manifest.json skeleton for a backup run, with an empty `objects`
    list — the caller appends one entry per backed-up object as exports complete.
    """
    return {
        "created": created,
        "profile": profile,
        "base_url": base_url,
        "operation": operation,
        "source_object": source,
        "fix_count": fix_count,
        "delete_count": delete_count,
        "objects": [],
    }
