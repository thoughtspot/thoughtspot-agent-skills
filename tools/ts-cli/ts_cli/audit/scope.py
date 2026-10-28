"""Which Models an audit covers: every Model, optionally narrowed to connections.

This was ts-audit skill prose the LLM carried out by hand (Step 3); it is code so the
scope is the same every run. Two facts drive it, both verified on the SE demo cluster
2026-10-28:

- A Model is a WORKSHEET-subtype result with ``metadata_header.worksheetVersion == "V2"``;
  a result without it is a legacy Worksheet, which the audit does not cover.
- A Model's search result rarely names a connection (28 of 2,190), so a connection scope
  goes through the Tables: Tables whose ``dataSourceName`` matches, then the Models that
  depend on them, directly or through a View. A Model is in scope when ANY of its Tables
  is on a selected connection.

The pure functions take rows and callables; `resolve_scope` is the only I/O.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

SEARCH = "/api/rest/2.0/metadata/search"
PAGE_SIZE = 500
#: Sources per dependents call: a batch keeps a whole-estate scope to a few calls.
DEPENDENTS_BATCH = 100
#: Views can stack; the cap and the visited set together guarantee termination.
MAX_VIEW_DEPTH = 4


def _header(row: dict) -> dict:
    return row.get("metadata_header") or {}


def select_models(rows: Iterable[dict]) -> Tuple[List[dict], int]:
    """Model search rows -> ([{guid, name}] for Models, count of legacy Worksheets)."""
    models, legacy = [], 0
    for row in rows:
        h = _header(row)
        if h.get("worksheetVersion") == "V2":
            models.append({"guid": row.get("metadata_id") or h.get("id"),
                           "name": row.get("metadata_name") or h.get("name", "")})
        else:
            legacy += 1
    return models, legacy


def _norm(name: str) -> str:
    return (name or "").strip().casefold()


def tables_on_connections(rows: Iterable[dict], connections: Iterable[str]) -> List[str]:
    """GUIDs of the Table rows whose ``dataSourceName`` is a selected connection.

    Case-insensitive, like `filter_by_connection`: a hand comparison was the old failure.
    """
    wanted = {_norm(c) for c in connections}
    return [row.get("metadata_id") or _header(row).get("id") for row in rows
            if _header(row).get("dataSourceName") is not None
            and _norm(_header(row)["dataSourceName"]) in wanted]


def models_reached(start: Iterable[str],
                   dependents_of: Callable[[List[str]], Dict[str, List[str]]],
                   model_guids: Set[str], max_depth: int = MAX_VIEW_DEPTH,
                   skip: Optional[Set[str]] = None) -> Set[str]:
    """Models among the LOGICAL_TABLE dependents of `start`, through any Views.

    Breadth-first, one `dependents_of` call per level. A dependent in `model_guids` is a
    Model in scope and is not followed (what sits on a Model is not a Model); one in
    `skip` (a legacy Worksheet) is neither counted nor followed; anything else is a View
    and is followed. Since the Model set is known, no per-object subtype lookup is needed.
    """
    skip = skip or set()
    seen = set(start)
    frontier = sorted(seen)
    reached: Set[str] = set()
    for _ in range(max_depth):
        if not frontier:
            break
        nxt = []
        for deps in dependents_of(frontier).values():
            for dep in deps:
                if not dep or dep in seen:
                    continue
                seen.add(dep)
                if dep in model_guids:
                    reached.add(dep)
                elif dep not in skip:
                    nxt.append(dep)
        frontier = sorted(nxt)
    return reached


def inventory(models: List[dict], legacy: int, connections: List[str],
              tables_on_connections: Optional[int]) -> dict:
    """What `ts audit run --dry-run` prints, and the skill shows as the inventory."""
    return {"models": models, "model_count": len(models), "legacy_worksheets_skipped": legacy,
            "connections": connections, "tables_on_connections": tables_on_connections}


def _search_all(client, metadata_filter: dict) -> List[dict]:
    rows: List[dict] = []
    offset = 0
    while True:
        data = client.post(SEARCH, json={
            "metadata": [metadata_filter], "record_size": PAGE_SIZE, "record_offset": offset,
            "include_headers": True}).json()
        page = data if isinstance(data, list) else data.get("metadata", [])
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _dependents_of(client) -> Callable[[List[str]], Dict[str, List[str]]]:
    from ts_cli.commands.metadata import (_build_dependents_payload,
                                          _normalize_dependents_response)

    def fetch(guids: List[str]) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {g: [] for g in guids}
        for i in range(0, len(guids), DEPENDENTS_BATCH):
            resp = client.post(SEARCH, json=_build_dependents_payload(
                guids[i:i + DEPENDENTS_BATCH], "LOGICAL_TABLE"))
            for row in _normalize_dependents_response(resp.json()):
                if row["type"] == "LOGICAL_TABLE":
                    out.setdefault(row["source_guid"], []).append(row["guid"])
        return out
    return fetch


def resolve_scope(client, connections: Optional[List[str]] = None) -> dict:
    """Every Model the user can see, narrowed to `connections` when given."""
    model_rows = _search_all(client, {"type": "LOGICAL_TABLE", "subtypes": ["WORKSHEET"]})
    models, legacy = select_models(model_rows)
    if not connections:
        return inventory(models, legacy, [], None)
    legacy_guids = {r.get("metadata_id") for r in model_rows
                    if _header(r).get("worksheetVersion") != "V2"}
    table_rows = _search_all(client, {"type": "LOGICAL_TABLE",
                                      "subtypes": ["ONE_TO_ONE_LOGICAL", "SQL_VIEW"]})
    tables = tables_on_connections(table_rows, connections)
    reached = models_reached(tables, _dependents_of(client), {m["guid"] for m in models},
                             skip=legacy_guids)
    return inventory([m for m in models if m["guid"] in reached], legacy,
                     list(connections), len(tables))
