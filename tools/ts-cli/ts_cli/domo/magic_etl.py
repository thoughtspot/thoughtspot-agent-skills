"""Parse a Domo Magic ETL dataflow export into base tables + a join graph.

A Magic ETL export (`{contentType, data:{actions:[...]}}`) is a deterministic data
pipeline: `LoadFromVault` = a source dataset, `MergeJoin` = a join (keys + type),
`Metadata`/`Alter Columns` = column renames, `PublishToVault` = the output dataset.

This maps cleanly to a ThoughtSpot Model's join graph — far better than inferring
joins by shared column name. Join *side* resolution (which base table owns each
key) is best-effort without column schemas, so every derived join is flagged for
review (family discipline: never a silent wrong-but-valid join).
"""
from __future__ import annotations

from typing import Any, Optional


def _actions(etl: dict) -> list[dict]:
    data = etl.get("data", etl)
    return data.get("actions", []) if isinstance(data, dict) else []


def _base_tables(actions: list[dict]) -> dict[str, dict]:
    """Base tables (LoadFromVault) keyed by action id.

    An action with no `id` is skipped rather than raising: every other path in this
    module is best-effort on a malformed export, and a bare KeyError here crashed the
    whole conversion instead of degrading with a note.
    """
    out: dict[str, dict] = {}
    for a in actions:
        if a.get("type") != "LoadFromVault":
            continue
        aid = a.get("id")
        if not aid:
            continue
        out[aid] = {
            "name": a.get("name", aid),
            "dataSourceId": a.get("dataSourceId"),
            "renames": [],
        }
    return out


def _base_of(aid: Optional[str], by_id: dict, seen: Optional[set] = None) -> Optional[str]:
    """Resolve an action id to its primary base LoadFromVault (follow step1/dep)."""
    seen = seen if seen is not None else set()
    if not aid or aid in seen:
        return None
    seen.add(aid)
    a = by_id.get(aid)
    if not a:
        return None
    t = a.get("type")
    if t == "LoadFromVault":
        return aid
    if t == "Metadata":
        dep = (a.get("dependsOn", {}).get("0") or {}).get("actionId")
        return _base_of(dep, by_id, seen)
    if t == "MergeJoin":
        return _base_of(a.get("step1"), by_id, seen)
    return None


def _apply_renames(actions: list[dict], tables: dict, by_id: dict) -> None:
    """Attach Metadata / Alter Columns renames to their base table, in place."""
    for a in actions:
        if a.get("type") != "Metadata":
            continue
        base = _base_of((a.get("dependsOn", {}).get("0") or {}).get("actionId"), by_id)
        if base not in tables:
            continue
        tables[base]["renames"].extend([
            {"from": f.get("name"), "to": f.get("rename"), "type": f.get("type")}
            for f in a.get("fields", []) if f.get("rename") and not f.get("remove")
        ])


def _join_from_action(a: dict, tables: dict, by_id: dict) -> tuple[Optional[dict], Optional[str]]:
    """Return (join, note) for one MergeJoin — exactly one of the pair is set."""
    lt = tables.get(_base_of(a.get("step1"), by_id), {}).get("name")
    rt = tables.get(_base_of(a.get("step2"), by_id), {}).get("name")
    if not lt or not rt:
        return None, f"join '{a.get('name')}' could not resolve to base tables — skipped"
    if lt == rt:
        return None, f"join '{a.get('name')}' resolved both sides to '{lt}' — skipped"
    keys = [{"left": l, "right": r}
            for l, r in zip(a.get("keys1", []) or [], a.get("keys2", []) or [])]
    jtype = (a.get("joinType", "LEFT OUTER") or "LEFT OUTER").upper().replace(" ", "_")
    return {
        "left_table": lt, "right_table": rt, "type": jtype, "keys": keys,
        "domo_relationship": a.get("relationshipType"),
        "domo_join": a.get("name"),
        "review": True,  # side/cardinality inferred without column schemas
    }, None


def _output_name(actions: list[dict]) -> Optional[str]:
    output = None
    for a in actions:
        if a.get("type") == "PublishToVault":
            output = a.get("name") or (a.get("dataSource", {}) or {}).get("name")
    return output


def parse_etl(etl: dict) -> dict:
    """Return {tables:[{name,dataSourceId,renames}], joins:[...], output, notes}."""
    actions = [a for a in _actions(etl) if isinstance(a, dict)]
    by_id = {a.get("id"): a for a in actions}

    tables = _base_tables(actions)
    skipped = sum(1 for a in actions
                  if a.get("type") == "LoadFromVault" and not a.get("id"))
    _apply_renames(actions, tables, by_id)

    joins: list[dict] = []
    notes: list[str] = []
    for a in actions:
        if a.get("type") != "MergeJoin":
            continue
        join, note = _join_from_action(a, tables, by_id)
        if join is not None:
            joins.append(join)
        else:
            notes.append(note)

    if skipped:
        notes.append(f"{skipped} LoadFromVault action(s) had no 'id' and were skipped")
    return {
        "tables": list(tables.values()),
        "joins": joins,
        "output": _output_name(actions),
        "notes": notes,
    }
