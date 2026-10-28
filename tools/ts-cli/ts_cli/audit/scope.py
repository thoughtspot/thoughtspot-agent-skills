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

Hidden Tables are searched (a hidden Table still feeds a Model); hidden and incomplete
Models are not audited, as before this module existed. A search pages with offsets and
no sort, so a repeated row is dropped rather than audited twice.

The pure functions take rows and callables; `resolve_scope` is the only I/O.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

SEARCH = "/api/rest/2.0/metadata/search"
PAGE_SIZE = 500
#: Sources per dependents call. The payload asks for every dependent kind (Answers and
#: Liveboards included), so a batch of busy fact Tables is a large response; context.py's
#: identical query was cut from 25 to 15 for reliability (ts-audit 2.4.0).
DEPENDENTS_BATCH = 15
#: Seconds, as context.py allows its metadata searches.
TIMEOUT = 300
#: Views can stack; the cap and the visited set together guarantee termination.
MAX_VIEW_DEPTH = 4


def _header(row: dict) -> dict:
    return row.get("metadata_header") or {}


def select_models(rows: Iterable[dict]) -> Tuple[List[dict], int]:
    """Model search rows -> ([{guid, name}] for Models, count of legacy Worksheets)."""
    models, legacy, seen = [], 0, set()
    for row in rows:
        guid = _guid(row)
        if not guid or guid in seen:
            continue
        seen.add(guid)
        if is_model(row):
            models.append({"guid": guid,
                           "name": row.get("metadata_name") or _header(row).get("name", "")})
        else:
            legacy += 1
    return models, legacy


def _guid(row: dict) -> Optional[str]:
    return row.get("metadata_id") or _header(row).get("id")


def is_model(row: dict) -> bool:
    """A WORKSHEET-subtype row is a Model when its header says ``worksheetVersion: V2``."""
    return _header(row).get("worksheetVersion") == "V2"


def _norm(name: str) -> str:
    return (name or "").strip().casefold()


def tables_on_connections(rows: Iterable[dict],
                          connections: Iterable[str]) -> Tuple[List[str], Dict[str, int]]:
    """(GUIDs of the Table rows on a selected connection, Tables per connection as given).

    Case-insensitive, like `filter_by_connection`: a hand comparison was the old failure.
    The per-connection count is how a misspelt name shows: it matches no Table, where it
    used to vanish silently beside a name that did match.
    """
    connections = list(connections)
    by_norm = {_norm(c): c for c in connections}
    counts = {c: 0 for c in connections}
    tables, seen = [], set()
    for row in rows:
        guid, source = _guid(row), _header(row).get("dataSourceName")
        if not guid or guid in seen or source is None or _norm(source) not in by_norm:
            continue
        seen.add(guid)
        tables.append(guid)
        counts[by_norm[_norm(source)]] += 1
    return tables, counts


def models_reached(start: Iterable[str],
                   dependents_of: Callable[[List[str]], Dict[str, List[str]]],
                   model_guids: Set[str], max_depth: int = MAX_VIEW_DEPTH,
                   skip: Optional[Set[str]] = None) -> Tuple[Set[str], int]:
    """(Models among the LOGICAL_TABLE dependents of `start` through any Views, the
    number of Views left unexplored at the depth cap).

    Breadth-first, one `dependents_of` call per level. A dependent in `model_guids` is a
    Model in scope and is not followed (what sits on a Model is not a Model); one in
    `skip` (a legacy Worksheet) is neither counted nor followed; anything else is a View
    and is followed. Since the Model set is known, no per-object subtype lookup is needed.
    The first hop counts as a level, so `max_depth` 4 follows three stacked Views; what
    the cap cuts off is returned, never dropped silently.
    """
    skip = skip or set()
    seen = {g for g in start if g}
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
    return reached, len(frontier)


def inventory(models: List[dict], legacy: int, tables_by_connection: Dict[str, int],
              views_not_followed: int) -> dict:
    """What `ts audit run --dry-run` prints, and the skill shows as the inventory."""
    return {"models": models, "model_count": len(models), "legacy_worksheets_skipped": legacy,
            "connections": list(tables_by_connection), "tables_by_connection": tables_by_connection,
            "views_not_followed": views_not_followed}


def unmatched_connections(inv: dict) -> List[str]:
    """The connection names that matched no Table: a typo, or a connection with no Tables."""
    return [c for c, n in inv["tables_by_connection"].items() if n == 0]


def _search_all(client, metadata_filter: dict, include_hidden: bool = False) -> List[dict]:
    rows: List[dict] = []
    offset = 0
    while True:
        data = client.post(SEARCH, json={
            "metadata": [metadata_filter], "record_size": PAGE_SIZE, "record_offset": offset,
            "include_headers": True, "include_hidden_objects": include_hidden},
            timeout=TIMEOUT).json()
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
                guids[i:i + DEPENDENTS_BATCH], "LOGICAL_TABLE"), timeout=TIMEOUT)
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
        return inventory(models, legacy, {}, 0)
    legacy_guids = {_guid(r) for r in model_rows if not is_model(r)}
    table_rows = _search_all(client, {"type": "LOGICAL_TABLE",
                                      "subtypes": ["ONE_TO_ONE_LOGICAL", "SQL_VIEW"]},
                             include_hidden=True)
    tables, counts = tables_on_connections(table_rows, connections)
    reached, not_followed = models_reached(tables, _dependents_of(client),
                                           {m["guid"] for m in models}, skip=legacy_guids)
    return inventory([m for m in models if m["guid"] in reached], legacy, counts, not_followed)
