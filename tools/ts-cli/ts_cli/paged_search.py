"""Paging a v2 `*/search` endpoint with `record_offset` / `record_size` until a page
comes back short. Shared by `ts calendar search` and the audit's calendar and
connection fetches (`audit/context.py`).

Live-probed on the SE demo cluster on 2026-11-18 (ts-audit open-items #16, #17):
`calendars/search` answers its first 10 when no `record_size` is sent and none at all
for `record_size: -1`, so a caller must page; `connection/search` answered 200
connections to `record_size: 200`.

Pure: the caller sends each request (`fetch_page`), so the paging is tested without a
client and each caller keeps its own error handling.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

#: A ceiling on requests, so a server that ignored `record_offset` and answered every
#: page in full with new ids could not be read for ever: 1,000 pages.
MAX_PAGES = 1000


class PagedSearchError(ValueError):
    """A search answered something that cannot be paged."""


def _key(item: dict, id_key: str) -> str:
    """What tells two items apart: the id, else the whole entry."""
    value = item.get(id_key)
    return value if isinstance(value, str) and value else json.dumps(item, sort_keys=True,
                                                                     default=str)


def search_pages(fetch_page: Callable[[Dict[str, Any]], Any], body: Optional[dict] = None,
                 page_size: int = 100, id_key: str = "id", what: str = "search",
                 items: str = "items", error: type = PagedSearchError) -> List[dict]:
    """Every item `fetch_page` pages through: each request is `body` plus
    `record_offset` / `record_size`; paging stops at a page holding fewer than
    `page_size` items. An item listed on two pages (same `id_key`) is kept once.

    Raises `error` (a PagedSearchError) when a page is not a list of mappings, when a
    full page adds no item not already seen (a server ignoring `record_offset` would
    otherwise be read for ever), or after MAX_PAGES full pages. `what` names the
    endpoint and `items` the things listed, in those messages."""
    found: List[dict] = []
    seen: set = set()
    offset = 0
    pages = 0
    while True:
        request = dict(body or {}, record_offset=offset, record_size=page_size)
        page = fetch_page(request)
        if not isinstance(page, list) or not all(isinstance(i, dict) for i in page):
            raise error(f"{what} answered {type(page).__name__} at offset {offset}, "
                        f"not a list of {items}")
        fresh = [i for i in page if _key(i, id_key) not in seen]
        for item in fresh:
            seen.add(_key(item, id_key))
            found.append(item)
        if len(page) < page_size:
            return found
        pages += 1
        if not fresh:
            raise error(f"{what} repeated a full page at offset {offset}: paging did not "
                        "advance, so the list cannot be read whole")
        if pages >= MAX_PAGES:
            raise error(f"{what} still answered full pages after {MAX_PAGES} requests")
        offset += page_size
