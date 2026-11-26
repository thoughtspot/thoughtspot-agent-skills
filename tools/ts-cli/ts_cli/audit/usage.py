"""The `usage` conditional data: how much each Model was queried, read from ThoughtSpot.

ThoughtSpot keeps its own query history in the system Model "TS: AI and BI Stats". The
audit reads it with `searchdata`, only when a selected rule declares `usage` (H17), and
keeps GUIDs and counts per Model, with the name and id of each Org it was queried in,
never a Model name. Live-probed on the SE demo cluster,
2026-11-25 (ts-audit open-items #9):

* The system Model is found by its exact name (`metadata/search`); its TML export is
  refused, so its columns cannot be read from TML. The columns used here are `[Model ID]`
  (a GUID string, "" for a query on no Model), `[Queries]` (summed), `[User ID]` and
  `[TS Query Start Time]` (epoch seconds). There is no Model name column.
* `searchdata` answers its columns in an order of its own, not the query's
  (`[Model ID] [Queries] unique count [User ID] max [TS Query Start Time]` came back as
  Model ID, Maximum TS Query Start Time, Queries, Unique Number of User ID), so every
  value is read by its column name (`_columns`), never by position.
* The 180-day window is the keyword filter `[TS Query Start Time].'last 180 days'`. The
  same filter as a bare `last 180 days` is refused (400, "Invalid value token: last"),
  and `>= '<ISO date>'` was silently ignored (every row came back). A min or max of the
  time column asked for beside the keyword filter was dropped from the answer, so the
  last-used time is read by its own query over all history.
* The history ran from 2023-10-01 to the day before the probe: about a day's lag.
* Read from a non-primary Org, the answer is that Org's usage only; read from the
  Primary Org it holds every Org's (2026-11-25: of 6 top Model IDs no Primary Org object
  matched, 5 were Models in three other Orgs). The session's Org (`auth/session/user`
  `current_org`) is recorded with it.
* `[Org ID]` (a string, "0" for the Primary Org) and `[Org]` (its name) name the Org each
  query ran in. They are read by a fourth query of their own (ORG_QUERY), so a build
  that refuses them, or answers without them, leaves the rest of the usage readable:
  only `model_orgs` is None. Grouped by Org, 7 of 3,015 Model IDs came back under more
  than one Org, so a Model ID may carry several Orgs; each is kept with its own last
  query, and the per-Model counts come from the queries with no Org column, never a
  sum over Orgs.

`ctx.usage` is None when not fetched and when any of it could not be read (the Model
missing, refused, or a failed call: a warning names the status and path only); every
reader then says "Not read", never "unused". A final 401, a 429 or a `requests`
exception raised by a call aborts the run once, as the other conditional fetches do
(context._read_answer, context._abort_on_request_failure).

The helpers above the fetch are pure and standard-library only: H17's code rule imports
them, and the catalog gate imports the code rules under a bare Python with only PyYAML.
"""
from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List, Optional, Tuple

SYSTEM_MODEL_NAME = "TS: AI and BI Stats"
#: The window the query and user counts cover, in days.
WINDOW_DAYS = 180
SEARCHDATA_PATH = "/api/rest/2.0/searchdata"
SESSION_PATH = "/api/rest/2.0/auth/session/user"
METADATA_SEARCH_PATH = "/api/rest/2.0/metadata/search"

MODEL_ID = "Model ID"
LAST_QUERY = "Maximum TS Query Start Time"
FIRST_QUERY = "Minimum TS Query Start Time"
QUERIES = "Queries"
USERS = "Unique Number of User ID"
ORG_ID = "Org ID"
ORG_NAME = "Org"

#: (query string, the columns it must answer, by name) for each `searchdata` call.
HISTORY_QUERY = ("min [TS Query Start Time] max [TS Query Start Time]",
                 (FIRST_QUERY, LAST_QUERY))
LAST_USED_QUERY = ("[Model ID] max [TS Query Start Time]", (MODEL_ID, LAST_QUERY))
WINDOW_QUERY = ("[Model ID] [Queries] unique count [User ID] "
                f"[TS Query Start Time].'last {WINDOW_DAYS} days'",
                (MODEL_ID, QUERIES, USERS))
#: Each Model's Org(s), with the last query in each, over all history.
ORG_QUERY = ("[Model ID] [Org ID] [Org] max [TS Query Start Time]",
             (MODEL_ID, ORG_ID, ORG_NAME, LAST_QUERY))

#: The id ThoughtSpot gives the Primary Org.
PRIMARY_ORG_ID = 0
_DAY = 86400


# ── pure helpers (H17 and the report read these) ────────────────────────────

def days_since(fetched_at: Any, when: Any) -> Optional[int]:
    """Whole days from `when` to `fetched_at` (both epoch seconds), never below 0; None
    when either is not a number."""
    if not (_number(fetched_at) and _number(when)):
        return None
    return max(0, int((fetched_at - when) // _DAY))


def iso_date(when: Any) -> str:
    """`when` (epoch seconds) as a UTC date, YYYY-MM-DD; "" when it is not a number."""
    if not _number(when):
        return ""
    return datetime.datetime.fromtimestamp(when, tz=datetime.timezone.utc).date().isoformat()


def org_label(usage: Optional[dict]) -> str:
    """How a finding or the report names the Org whose usage was read."""
    org = (usage or {}).get("org") or {}
    name, oid = org.get("name"), org.get("id")
    if isinstance(name, str) and name:
        return f"the Org '{name}'"
    if oid is not None:
        return f"the Org with id {oid}"
    return "the audit's Org (its name could not be read)"


def usage_scope(usage: Optional[dict]) -> Tuple[str, int]:
    """Whose usage a reading is, as `(kind, Orgs it names)`; the report's usage.js
    `usageScope` mirrors it, so a finding and the page agree:

    * "all": read from the Primary Org and naming more than one Org — every Org's usage;
    * "many": read from another Org (or an unread one) yet naming more than one;
    * "hedge": read from the Primary Org with its Orgs not read, or taken before they
      were (ts-cli 0.223.0), so which Orgs it covers is not known;
    * "org": otherwise, the usage of the Org it was read in."""
    usage = usage or {}
    model_orgs, org_read = _model_orgs_of(usage)
    count = len({o["id"] for rows in (model_orgs or {}).values() for o in rows})
    primary = is_primary(usage)
    if count > 1:
        return ("all" if primary else "many"), count
    if primary and org_read is not True:
        return "hedge", count
    return "org", count


def usage_label(usage: Optional[dict]) -> str:
    """Whose usage a reading is, in words (usage_scope): "usage of all Orgs, read from
    the Primary Org", "usage of 3 Orgs, read from the Org 'X'", "usage read from the
    Primary Org; which Orgs it covers was not read" or "usage of the Org 'X'"."""
    kind, count = usage_scope(usage)
    if kind == "all":
        return "usage of all Orgs, read from the Primary Org"
    if kind == "many":
        return f"usage of {count} Orgs, read from {org_label(usage)}"
    if kind == "hedge":
        return "usage read from the Primary Org; which Orgs it covers was not read"
    return f"usage of {org_label(usage)}"


def model_usage(usage: dict, guid: str) -> Dict[str, Any]:
    """One Model's reading: `last_used` (epoch seconds, or None), `days` since it (None
    when never queried or not recorded), `queries` and `users` over the window, and
    `never` — True when the history holds no row for it."""
    row = (usage.get("models") or {}).get(guid)
    if not isinstance(row, dict):
        return {"last_used": None, "days": None, "queries": 0, "users": 0, "never": True}
    last = row.get("last_used")
    return {"last_used": last if _number(last) else None,
            "days": days_since(usage.get("fetched_at"), last),
            "queries": row.get("queries_180d") or 0, "users": row.get("users_180d") or 0,
            "never": False}


def usage_readable(usage: Optional[dict]) -> bool:
    """Usage was read and its history has a known start: an empty history (no first
    query time) says nothing about any Model, so it reads as not read."""
    if not isinstance(usage, dict):
        return False
    return _number((usage.get("history") or {}).get("start"))


def idle_reading(usage: dict, guid: str, idle_days: float,
                 created_ms: Any = None) -> Tuple[Optional[int], Optional[str]]:
    """H17: `(days since last use, wording)` for a Model with no query in `idle_days`
    days or more, `(None, wording)` for one the history holds no row for when the
    history covers at least `idle_days` days before the usage was read, and `(None,
    None)` otherwise — a recent query, a row with no query time recorded, a history too
    short to say, a never-queried Model created less than `idle_days` days before the
    read (`created_ms`, its metadata header's `created`, epoch milliseconds; when absent
    the never-queried test applies as before), or usage not readable (usage_readable).
    The age test covers only the never-queried case: a Model the history holds is judged
    by its last query alone."""
    if not usage_readable(usage):
        return None, None
    reading = model_usage(usage, guid)
    if reading["never"]:
        start = usage["history"]["start"]
        fetched = usage.get("fetched_at")
        if not _number(fetched) or start > fetched - idle_days * _DAY:
            return None, None
        if _number(created_ms) and created_ms / 1000 > fetched - idle_days * _DAY:
            return None, None
        return None, ("No query in the usage history ThoughtSpot holds, which starts on "
                      f"{iso_date(start)}")
    days = reading["days"]
    if days is None or days < idle_days:
        return None, None
    return days, f"No query in {days} days; last queried on {iso_date(reading['last_used'])}"


def is_primary(usage: Optional[dict]) -> Optional[bool]:
    """Whether the usage is the Primary Org's (id 0); None when the Org was not read."""
    oid = ((usage or {}).get("org") or {}).get("id")
    if oid is None:
        return None
    return str(oid) == str(PRIMARY_ORG_ID)


def corpus_model_usage(usage: dict, guid: str) -> Dict[str, Any]:
    """One audited Model's usage for the audit JSON (`corpus.models[].usage`)."""
    r = model_usage(usage, guid)
    return {"last_used": r["last_used"], "days": r["days"], "queries_180d": r["queries"],
            "users_180d": r["users"], "never": r["never"]}


def corpus_usage(usage: Optional[dict], audited: Any) -> Optional[dict]:
    """The usage reading for the audit JSON (`corpus.usage`), None when it was not read
    (usage_readable): `history_days`, the whole days the history covers before the read,
    the Org, whether it is the Primary Org, the window, when it was read, the history's
    span, the rows dropped for a blank Model ID, and `gone` — each Model ID that matches
    no object the user can see now and is not audited, most queried first, or None when
    that could not be listed. With them, the Orgs (corpus_orgs): `org_read`, `orgs`, and
    each `gone` entry's `orgs`. GUIDs, counts and Org names only: the system Model has no
    Model names."""
    if not usage_readable(usage):
        return None
    model_orgs, org_read = _model_orgs_of(usage)
    gone = None
    if isinstance(usage.get("not_visible"), list):
        gone = [dict(corpus_model_usage(usage, g), guid=g)
                for g in usage["not_visible"] if g not in audited]
        for g in gone:
            del g["never"]
            g["orgs"] = None if model_orgs is None else \
                [dict(o) for o in model_orgs.get(g["guid"], [])]
        gone.sort(key=lambda g: (-g["queries_180d"], -(g["last_used"] or 0), g["guid"]))
    return {"org": usage.get("org"), "primary": is_primary(usage),
            "window_days": usage.get("window_days"), "fetched_at": usage.get("fetched_at"),
            "history": usage.get("history"),
            "history_days": days_since(usage.get("fetched_at"), usage["history"]["start"]),
            "blank_rows": usage.get("blank_rows", 0), "gone": gone,
            "org_read": org_read, "orgs": corpus_orgs(model_orgs)}


def _model_orgs_of(usage: dict) -> Tuple[Optional[Dict[str, list]], Optional[bool]]:
    """`(model_orgs, org_read)`: each Model ID's Orgs and whether they were read — True
    read, False fetched and not read (`model_orgs` None), None for a reading taken before
    the Orgs were (ts-cli 0.223.0, a replayed snapshot), whose IDs then carry no Org: `{}`,
    so each reads as "Org not recorded"."""
    if "model_orgs" not in usage:
        return {}, None
    model_orgs = usage["model_orgs"]
    if not isinstance(model_orgs, dict):
        return None, False
    return model_orgs, True


def corpus_orgs(model_orgs: Optional[Dict[str, list]]) -> Optional[List[dict]]:
    """Each Org the usage names, as `{id, name, models}` (`models`: the used Model IDs
    queried in it), the most first; None when the Orgs were not read. A Model ID queried
    in two Orgs counts in both."""
    if model_orgs is None:
        return None
    orgs: Dict[str, dict] = {}
    for rows in model_orgs.values():
        for row in rows:
            org = orgs.setdefault(row["id"], {"id": row["id"], "name": row.get("name"),
                                              "models": 0})
            org["models"] += 1
    return sorted(orgs.values(), key=lambda o: (-o["models"], _org_sort(o["id"])))


def _org_sort(oid: str) -> Tuple[int, Any]:
    return (0, int(oid)) if oid.isdigit() else (1, oid)


def idle_days_of(ran: Dict[str, Any]) -> Optional[float]:
    """The idle days the run's usage rules judged by (their `idle_days` parameter, the
    smallest when several), or None when none ran: the report compares it with
    `history_days` to say when a history was too short for "never queried"."""
    days = [r.parameters["idle_days"] for r in (ran or {}).values()
            if "usage" in (r.requires or []) and "idle_days" in (r.parameters or {})]
    return min(days) if days else None


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ── reading a searchdata answer ─────────────────────────────────────────────

class NotRead(Exception):
    """Usage could not be read; the message says why (a status and path, never a body)."""


def _table(answer: Any, what: str) -> Tuple[list, list, dict]:
    """`(column names, rows, the table)` of a `searchdata` COMPACT answer; NotRead when
    it is not one table with column names and rows."""
    contents = answer.get("contents") if isinstance(answer, dict) else None
    if not isinstance(contents, list) or len(contents) != 1 or not isinstance(contents[0], dict):
        raise NotRead(f"{what}: the answer is not one table of contents")
    table = contents[0]
    names, rows = table.get("column_names"), table.get("data_rows")
    if not isinstance(names, list) or not isinstance(rows, list):
        raise NotRead(f"{what}: the answer has no column names or rows")
    return names, rows, table


def _columns(answer: Any, wanted: Tuple[str, ...], what: str) -> List[Dict[str, Any]]:
    """The rows of a `searchdata` COMPACT answer as `{column name: value}` for the
    `wanted` columns, matched by name (case aside), never by position. NotRead when the
    answer is not that shape (_table), lacks a wanted column, or holds fewer rows than it
    says are available (a partial answer must not read as complete)."""
    names, rows, table = _table(answer, what)
    index = {n.casefold(): i for i, n in enumerate(names) if isinstance(n, str)}
    missing = [w for w in wanted if w.casefold() not in index]
    if missing:
        raise NotRead(f"{what}: the answer has no column {', '.join(missing)}")
    available = table.get("available_data_row_count")
    if _number(available) and available > len(rows):
        raise NotRead(f"{what}: the answer holds {len(rows)} of {int(available)} rows")
    if not all(isinstance(row, list) and len(row) == len(names) for row in rows):
        raise NotRead(f"{what}: a row does not match the column names")
    return [{w: row[index[w.casefold()]] for w in wanted} for row in rows]


def _epoch(value: Any) -> Optional[int]:
    return int(value) if _number(value) else None


def _count(value: Any) -> int:
    return int(value) if _number(value) else 0


def merge_rows(last_used: List[dict], window: List[dict]) -> Tuple[Dict[str, dict], int]:
    """`({Model GUID: {last_used, queries_180d, users_180d}}, rows dropped)`: the
    all-history last-query rows and the window's counts, by Model ID. A row with a
    blank or non-string Model ID (a query on no Model) is dropped; the count is of the
    all-history rows dropped, since the window's are the same IDs again."""
    models: Dict[str, dict] = {}
    blank = 0

    def entry(row: dict, count: bool) -> Optional[dict]:
        nonlocal blank
        guid = row.get(MODEL_ID)
        if not isinstance(guid, str) or not guid.strip():
            blank += 1 if count else 0
            return None
        return models.setdefault(guid.strip(), {"last_used": None, "queries_180d": 0,
                                                "users_180d": 0})
    for row in last_used:
        found = entry(row, True)
        if found is not None:
            found["last_used"] = _epoch(row.get(LAST_QUERY))
    for row in window:
        found = entry(row, False)
        if found is not None:
            found["queries_180d"] = _count(row.get(QUERIES))
            found["users_180d"] = _count(row.get(USERS))
    return models, blank


def merge_orgs(rows: List[dict]) -> Dict[str, List[dict]]:
    """`{Model GUID: [{id, name, last_used}, ...]}` from ORG_QUERY's rows: each Org a
    Model ID was queried in, by Org id (a string), with the last query there, ordered by
    Org id. A Model ID in several Orgs keeps one entry per Org, never merged. A row with
    a blank Model ID or a blank Org id is dropped, so a Model ID with no Org recorded is
    absent. Two rows for one Model and Org id (the Org renamed) are one entry, with the
    later query and the name beside it."""
    found: Dict[str, Dict[str, dict]] = {}
    for row in rows:
        guid, oid = row.get(MODEL_ID), _org_id(row.get(ORG_ID))
        if not isinstance(guid, str) or not guid.strip() or oid is None:
            continue
        name = row.get(ORG_NAME)
        entry = {"id": oid, "name": name if isinstance(name, str) and name else None,
                 "last_used": _epoch(row.get(LAST_QUERY))}
        orgs = found.setdefault(guid.strip(), {})
        held = orgs.get(oid)
        if held is None or (entry["last_used"] or 0) > (held["last_used"] or 0):
            orgs[oid] = entry
    return {g: [orgs[k] for k in sorted(orgs, key=_org_sort)] for g, orgs in found.items()}


def _org_id(value: Any) -> Optional[str]:
    """An Org id as a string ("7"; a whole float 7.0 too), None when blank or not one."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value).strip() or None


# ── the fetch ───────────────────────────────────────────────────────────────

def fetch_usage(client: Any, warnings: list) -> Optional[dict]:
    """Per-Model usage from the system Model (module docstring), or None with a warning
    when any of it could not be read:

        {"org": {"id", "name"}, "window_days": 180, "fetched_at": <epoch seconds>,
         "history": {"start", "end"}, "blank_rows": <rows with no Model ID>,
         "models": {<guid>: {"last_used", "queries_180d", "users_180d"}},
         "model_orgs": {<guid>: [{"id", "name", "last_used"}, ...]} or None,
         "not_visible": [<guid>, ...] or None}

    `not_visible` lists the Model IDs that match no Model, Table or View the user can
    see in this Org now (deleted, in another Org, or not shared with them); None, with a warning, when
    that search failed, which leaves the rest readable. `model_orgs` is each Model ID's
    Orgs (merge_orgs); None, with a warning, when ORG_QUERY was refused or answered
    without the Org columns, which leaves the rest readable too."""
    from ts_cli.audit.context import _log
    _log("Fetching usage...")
    try:
        guid = _system_model(client)
        org = _current_org(client, warnings)
        history = _query(client, guid, *HISTORY_QUERY)
        last_used = _query(client, guid, *LAST_USED_QUERY)
        window = _query(client, guid, *WINDOW_QUERY)
    except NotRead as exc:
        msg = f"Usage was not read, so no Model's usage is known: {exc}"
        _log(f"Warning: {msg}")
        warnings.append(msg)
        return None
    models, blank = merge_rows(last_used, window)
    span = history[0] if history else {}
    if not _number(span.get(FIRST_QUERY)):
        msg = ("Usage was not read, so no Model's usage is known: the usage history "
               "holds no query")
        _log(f"Warning: {msg}")
        warnings.append(msg)
        return None
    return {"org": org, "window_days": WINDOW_DAYS, "fetched_at": int(time.time()),
            "history": {"start": _epoch(span.get(FIRST_QUERY)),
                        "end": _epoch(span.get(LAST_QUERY))},
            "blank_rows": blank, "models": models,
            "model_orgs": _read_orgs(client, guid, warnings),
            "not_visible": _not_visible(client, models, warnings)}


def _call(client: Any, method: str, path: str, body: Optional[dict] = None) -> Any:
    """One request, its answer decoded by context._read_answer with the response body
    kept out of every line; NotRead with the status and path for a refusal."""
    import requests
    from ts_cli.audit.context import _abort_on_request_failure, _read_answer
    try:
        if method == "GET":
            resp = client.get(path, raise_for_status=False)
        else:
            resp = client.post(path, json=body, raise_for_status=False)
    except requests.RequestException as exc:
        _abort_on_request_failure(exc, f"Usage read ({method} {path})")
    answer, reason = _read_answer(resp, path, body=False, method=method)
    if reason is not None:
        raise NotRead(reason)
    return answer


def _system_model(client: Any) -> str:
    """The GUID of the one LOGICAL_TABLE named exactly SYSTEM_MODEL_NAME (`record_size: -1`,
    every match: on `metadata/search` -1 is all)."""
    found = _call(client, "POST", METADATA_SEARCH_PATH, {
        "metadata": [{"type": "LOGICAL_TABLE", "name_pattern": SYSTEM_MODEL_NAME}],
        "include_hidden_objects": True, "record_size": -1})
    if not isinstance(found, list):
        raise NotRead(f"the search for {SYSTEM_MODEL_NAME} answered no list")
    ids = sorted({r.get("metadata_id") for r in found if isinstance(r, dict)
                  and r.get("metadata_name") == SYSTEM_MODEL_NAME
                  and isinstance(r.get("metadata_id"), str)})
    if not ids:
        raise NotRead(f"the system Model {SYSTEM_MODEL_NAME} was not found, or this user "
                      "cannot see it")
    if len(ids) > 1:
        raise NotRead(f"{len(ids)} objects are named {SYSTEM_MODEL_NAME}, so which holds "
                      "the usage is not known")
    return ids[0]


def _current_org(client: Any, warnings: list) -> Dict[str, Any]:
    """`{id, name}` of the session's Org; both None, with a warning, when the session
    cannot be read (the usage is still the session's Org's, only unnamed)."""
    from ts_cli.audit.context import _log
    try:
        session = _call(client, "GET", SESSION_PATH)
    except NotRead as exc:
        msg = f"The current Org was not read, so the usage is not labelled with it: {exc}"
        _log(f"Warning: {msg}")
        warnings.append(msg)
        return {"id": None, "name": None}
    org = session.get("current_org") if isinstance(session, dict) else None
    org = org if isinstance(org, dict) else {}
    oid, name = org.get("id"), org.get("name")
    return {"id": oid if _number(oid) or isinstance(oid, str) else None,
            "name": name if isinstance(name, str) else None}


def _query(client: Any, guid: str, query: str, wanted: Tuple[str, ...]) -> List[dict]:
    answer = _call(client, "POST", SEARCHDATA_PATH, {
        "query_string": query, "logical_table_identifier": guid,
        "data_format": "COMPACT", "record_size": -1})
    return _columns(answer, wanted, f"searchdata '{query}'")


def _read_orgs(client: Any, guid: str, warnings: list) -> Optional[Dict[str, List[dict]]]:
    """Each used Model ID's Orgs (ORG_QUERY, merge_orgs); None, with a warning naming
    the status and path or the missing column, when they could not be read."""
    from ts_cli.audit.context import _log
    try:
        return merge_orgs(_query(client, guid, *ORG_QUERY))
    except NotRead as exc:
        msg = ("The Org each used Model was queried in was not read, so the Cleanup view "
               f"does not split the used Models by Org: {exc}")
        _log(f"Warning: {msg}")
        warnings.append(msg)
        return None


def _not_visible(client: Any, models: Dict[str, dict], warnings: list) -> Optional[List[str]]:
    """The Model IDs in `models` that match no LOGICAL_TABLE the user can see (a paged
    `metadata/search`, hidden objects included, each row reduced to its id); None, with
    a warning, when the search failed (context._paged_fetch)."""
    from ts_cli.audit.context import _paged_fetch
    from ts_cli.paged_search import search_pages
    body = {"metadata": [{"type": "LOGICAL_TABLE"}], "include_hidden_objects": True}

    def ids(page: Any) -> Any:
        if not isinstance(page, list) or not all(isinstance(r, dict) for r in page):
            return page  # the pager refuses it
        return [{"id": r.get("metadata_id")} for r in page]

    def search(fetch_page: Any) -> list:
        return search_pages(lambda b: ids(fetch_page(b)), body, 500, id_key="id",
                            what="metadata/search", items="objects")
    found = _paged_fetch(client, METADATA_SEARCH_PATH, "Visible object",
                         "used Models not found in this Org", warnings, search, with_body=False)
    if found is None:
        return None
    visible = {f["id"] for f in found if isinstance(f.get("id"), str)}
    return sorted(g for g in models if g not in visible)
