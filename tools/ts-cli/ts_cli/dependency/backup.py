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
#
# A SQL View sits on a connection exactly as a Table does — Models are built on it, it
# is built on nothing in ThoughtSpot — so it shares the Table's rank. Unranked, it
# restored LAST (rollback_sort_key's -1), after the Models that need it (PR #666
# review, B3). `PINBOARD` is the pre-Liveboard TML key `detect_tml_type` can return.
DELETE_ORDER: Dict[str, int] = {
    "LIVEBOARD": 0,
    "PINBOARD": 0,
    "ANSWER": 1,
    "SET": 2,
    "COHORT": 2,
    "VIEW": 3,
    "MODEL": 4,
    "WORKSHEET": 4,
    "TABLE": 5,
    "SQL_VIEW": 5,
}


def delete_sort_key(obj: Dict[str, Any]) -> int:
    """Sort key for the Step 9a delete loop — `obj["type"]` (case-insensitive)
    looked up in `DELETE_ORDER`; unknown types sort last (9)."""
    return DELETE_ORDER.get(str(obj.get("type", "")).upper(), 9)


# v2 `--type` values expected by `ts metadata delete` (SKILL.md ~1093-1102).
V2_TYPE_MAP: Dict[str, str] = {
    "ANSWER": "ANSWER",
    "LIVEBOARD": "LIVEBOARD",
    "PINBOARD": "LIVEBOARD",
    "MODEL": "LOGICAL_TABLE",
    "WORKSHEET": "LOGICAL_TABLE",
    "VIEW": "LOGICAL_TABLE",
    "TABLE": "LOGICAL_TABLE",
    "SQL_VIEW": "LOGICAL_TABLE",
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
    """Restore-order key: the object's `DELETE_ORDER` rank (case-insensitive).

    Rollback restores ROOT-first (the reverse of the leaf-first delete/apply order), so
    entries are sorted by this key DESCENDING in `rollback_order`. A connection Table
    (rank 5) therefore restores before the Models that reference it (4), before Views
    (3), Sets (2), Answers (1), and Liveboards (0). Unknown types get -1 (restore last).
    """
    return DELETE_ORDER.get(str(entry.get("type", "")).upper(), -1)


def rollback_order(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return `entries` in restore order: source/roots BEFORE their dependents.

    This is the reverse of the leaf-first delete/apply order. A dependent can only be
    re-imported once the object it references exists again — restoring a Model whose
    `column_id` is `DM_PRODUCT::PRODUCT_DESCRIPTION` requires the DM_PRODUCT table to
    already carry that column. Sorts by `rollback_sort_key` DESCENDING (tables first);
    stable within a tier so equal-rank entries keep manifest order. Does not mutate
    `entries`.

    Fixes the live-found rollback bug (open-items #25): the previous order restored
    dependents before the source table, so a column-removal rollback failed on the
    first pass with "Unable to create model column(s) … <table>::<col>" and only
    completed after a second run (once the table had been restored last).
    """
    return sorted(entries, key=rollback_sort_key, reverse=True)


def order_by_references(entries: List[Dict[str, Any]], texts: Dict[str, str]) -> List[Dict[str, Any]]:
    """Refine `rollback_order` so every entry restores after the entries its TML names.

    Type rank alone is not enough: a Model built on a View ranks above it and would
    restore first, still naming the View's deleted GUID (PR #666 follow-up review). An
    entry depends on another when its backup text (`texts[guid]`) contains that entry's
    GUID. Ties and cycles fall back to `rollback_order`. Does not mutate `entries`.
    """
    pending = rollback_order(entries)
    deps = {id(e): {o.get("guid") for o in entries
                    if o is not e and o.get("guid") and o["guid"] in texts.get(e.get("guid") or "", "")}
            for e in pending}
    placed: List[Dict[str, Any]] = []
    done: set = set()
    while pending:
        nxt = next((e for e in pending if deps[id(e)] <= done), pending[0])
        pending.remove(nxt)
        placed.append(nxt)
        done.add(nxt.get("guid"))
    return placed


def remap_guids(text: str, new_guids: Dict[str, str]) -> str:
    """Replace every original GUID in `text` with the GUID its object was restored under.

    A restored DELETE gets a new GUID, but the backups of its dependents were exported
    with `export_fqn=True`, so they still name the ORIGINAL one — an Answer restored
    after its Model pointed at a GUID that no longer exists (PR #666 review, B3).
    `rollback_order` restores referenced objects first, so by the time a dependent is
    imported every GUID it references that was re-created is already in `new_guids`.

    Plain substring replacement is safe here: a GUID is a 36-character 8-4-4-4-12 hex
    value, so one cannot occur inside another or inside ordinary TML text.
    """
    for old, new in new_guids.items():
        if old and new:
            text = text.replace(old, new)
    return text


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
