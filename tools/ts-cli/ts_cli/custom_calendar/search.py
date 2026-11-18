"""Paging over `POST /api/rest/2.0/calendars/search`, shared by `ts calendar search` and
the audit's calendar fetch (`audit/context.py`).

Live-probed on the SE demo cluster on 2026-11-18 (ts-audit open-items #16): with no
`record_size` the endpoint returns the first 10 calendars only, and `record_size: -1`
returns none at all (it is not "all", as it is on `metadata/search`).
`record_offset` / `record_size` page as documented, and `connection_identifier` scopes
the search to one connection. So every caller pages, a full page at a time, until a
page comes back short (ts_cli.paged_search, which the connection fetch uses too).

Pure: the caller sends each request (`fetch_page`), so the paging is tested without a
client and each caller keeps its own error handling.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ts_cli.paged_search import PagedSearchError, search_pages

SEARCH_PATH = "/api/rest/2.0/calendars/search"
#: Calendars asked for per request. The probe paged 57 calendars in pages of 10 and 25.
PAGE_SIZE = 100


class CalendarSearchError(PagedSearchError):
    """The calendar search answered something that cannot be paged."""


def search_calendars(fetch_page: Callable[[Dict[str, Any]], Any],
                     connection: Optional[str] = None,
                     page_size: int = PAGE_SIZE) -> List[dict]:
    """Every registered calendar, or only `connection`'s (a name or id) when given.

    `fetch_page(body)` sends one request body and returns its decoded JSON. Pages with
    `record_offset` / `record_size` until a page holds fewer than `page_size`
    calendars; a calendar listed on two pages is kept once. Raises CalendarSearchError
    when a page is not a list of mappings, when a full page adds no calendar not already
    seen, or after paged_search.MAX_PAGES full pages."""
    body = {"connection_identifier": connection} if connection else {}
    return search_pages(fetch_page, body, page_size, id_key="calendar_id",
                        what="calendars/search", items="calendars",
                        error=CalendarSearchError)
