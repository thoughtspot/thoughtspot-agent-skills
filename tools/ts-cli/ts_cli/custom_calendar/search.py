"""Paging over `POST /api/rest/2.0/calendars/search`, shared by `ts calendar search` and
the audit's calendar fetch (`audit/context.py`).

Live-probed on the SE demo cluster on 2026-11-18 (ts-audit open-items #16): with no
`record_size` the endpoint returns the first 10 calendars only, and `record_size: -1`
returns none at all (it is not "all", as it is on `metadata/search`).
`record_offset` / `record_size` page as documented, and `connection_identifier` scopes
the search to one connection. So every caller pages, a full page at a time, until a
page comes back short.

Pure: the caller sends each request (`fetch_page`), so the paging is tested without a
client and each caller keeps its own error handling.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

SEARCH_PATH = "/api/rest/2.0/calendars/search"
#: Calendars asked for per request. The probe paged 57 calendars in pages of 10 and 25.
PAGE_SIZE = 100
#: A ceiling on requests, so a server that ignored `record_offset` and answered every
#: page in full with new ids could not page for ever: 1,000 pages of 100.
MAX_PAGES = 1000


class CalendarSearchError(ValueError):
    """The calendar search answered something that cannot be paged."""


def _key(calendar: dict) -> str:
    """What tells two calendars apart: the id, else the whole entry."""
    cid = calendar.get("calendar_id")
    return cid if isinstance(cid, str) and cid else json.dumps(calendar, sort_keys=True,
                                                               default=str)


def search_calendars(fetch_page: Callable[[Dict[str, Any]], Any],
                     connection: Optional[str] = None,
                     page_size: int = PAGE_SIZE) -> List[dict]:
    """Every registered calendar, or only `connection`'s (a name or id) when given.

    `fetch_page(body)` sends one request body and returns its decoded JSON. Requests
    `record_offset` / `record_size` pages until one holds fewer than `page_size`
    calendars. A calendar listed on two pages is kept once.

    Raises CalendarSearchError when a page is not a list of mappings, when a full page
    adds no calendar not already seen (a server ignoring `record_offset` would
    otherwise be read for ever), or after MAX_PAGES full pages."""
    found: List[dict] = []
    seen: set = set()
    offset = 0
    pages = 0
    while True:
        body: Dict[str, Any] = {"record_offset": offset, "record_size": page_size}
        if connection:
            body["connection_identifier"] = connection
        page = fetch_page(body)
        if not isinstance(page, list) or not all(isinstance(c, dict) for c in page):
            raise CalendarSearchError(
                f"calendars/search answered {type(page).__name__} at offset {offset}, "
                "not a list of calendars")
        fresh = [c for c in page if _key(c) not in seen]
        for calendar in fresh:
            seen.add(_key(calendar))
            found.append(calendar)
        if len(page) < page_size:
            return found
        pages += 1
        if not fresh:
            raise CalendarSearchError(
                f"calendars/search repeated a full page at offset {offset}: paging did "
                "not advance, so the list cannot be read whole")
        if pages >= MAX_PAGES:
            raise CalendarSearchError(
                f"calendars/search still answered full pages after {MAX_PAGES} requests")
        offset += page_size
