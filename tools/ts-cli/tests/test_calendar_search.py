"""`POST /calendars/search` is read page by page (custom_calendar/search.py).

The live probe (ts-audit open-items #16, 2026-11-18): with no `record_size` the endpoint
answers the first 10 calendars only, and `record_size: -1` answers none. `ts calendar
search` sent neither, so it silently listed 10 of 57. The fake server below answers as
the probe did; no live ThoughtSpot connection anywhere.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ts_cli.commands.calendars import app
from ts_cli.custom_calendar.search import SEARCH_PATH, CalendarSearchError, search_calendars
from ts_cli.paged_search import MAX_PAGES, PagedSearchError, search_pages

runner = CliRunner()


def _calendars(n, connection="Warehouse A"):
    return [{"calendar_id": f"cal-{i}", "calendar_name": f"Calendar {i}",
             "connection_id": "conn-a", "connection_name": connection,
             "data_warehouse_type": "SNOWFLAKE", "author_name": "someone",
             "modification_time_in_millis": "0"} for i in range(n)]


class FakeServer:
    """Answers `calendars/search` as the probe observed: 10 by default, none for -1,
    a slice for an offset and size."""

    def __init__(self, calendars):
        self.calendars = calendars
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(dict(body))
        rows = [c for c in self.calendars
                if not body.get("connection_identifier")
                or body["connection_identifier"] in (c["connection_id"], c["connection_name"])]
        size = body.get("record_size", 10)
        if size == -1:
            return []
        offset = body.get("record_offset", 0)
        return rows[offset:offset + size]


def test_every_calendar_is_read_across_pages():
    server = FakeServer(_calendars(57))
    found = search_calendars(server, page_size=25)
    assert [c["calendar_id"] for c in found] == [f"cal-{i}" for i in range(57)]
    assert [b["record_offset"] for b in server.bodies] == [0, 25, 50]
    assert all(b["record_size"] == 25 for b in server.bodies)


def test_a_page_exactly_full_asks_once_more_and_stops_on_the_empty_page():
    server = FakeServer(_calendars(100))
    assert len(search_calendars(server)) == 100
    assert [b["record_offset"] for b in server.bodies] == [0, 100]


def test_no_calendars_is_one_request_and_an_empty_list():
    server = FakeServer([])
    assert search_calendars(server) == []
    assert len(server.bodies) == 1


def test_a_connection_scopes_every_page():
    server = FakeServer(_calendars(3) + [dict(c, connection_id="conn-b", connection_name="B",
                                              calendar_id="b" + c["calendar_id"])
                                         for c in _calendars(2)])
    found = search_calendars(server, connection="B")
    assert [c["calendar_id"] for c in found] == ["bcal-0", "bcal-1"]
    assert all(b["connection_identifier"] == "B" for b in server.bodies)


def test_a_calendar_listed_on_two_pages_is_kept_once():
    pages = iter([_calendars(2), _calendars(3)[1:], [{"calendar_id": "cal-9"}]])
    found = search_calendars(lambda body: next(pages), page_size=2)
    assert [c["calendar_id"] for c in found] == ["cal-0", "cal-1", "cal-2", "cal-9"]


@pytest.mark.parametrize("answer", [{"calendars": []}, None, "x", [["not", "a", "mapping"]]])
def test_an_answer_that_is_not_a_list_of_calendars_is_an_error(answer):
    with pytest.raises(CalendarSearchError, match="not a list of calendars"):
        search_calendars(lambda body: answer)


def test_a_server_that_ignores_the_offset_stops_rather_than_looping():
    """Every page the same full page: without the guard the loop never ends."""
    calls = []

    def same_page(body):
        calls.append(body)
        return _calendars(2)
    with pytest.raises(CalendarSearchError, match="did not advance"):
        search_calendars(same_page, page_size=2)
    assert len(calls) == 2


def test_the_page_ceiling_stops_an_endless_list(monkeypatch):
    monkeypatch.setattr("ts_cli.paged_search.MAX_PAGES", 3)
    counter = iter(range(10 ** 6))

    def endless(body):
        return [{"calendar_id": f"c{next(counter)}"} for _ in range(body["record_size"])]
    with pytest.raises(CalendarSearchError, match="after 3 requests"):
        search_calendars(endless, page_size=2)
    assert MAX_PAGES == 1000


def test_the_shared_pager_names_its_endpoint_and_keys_by_the_given_id():
    """The connection fetch pages through the same loop, by `id`, with its own body."""
    bodies = []

    def page(body):
        bodies.append(body)
        rows = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        return rows[body["record_offset"]:body["record_offset"] + body["record_size"]]
    found = search_pages(page, {"include_details": True}, page_size=2, what="connection/search",
                         items="connections")
    assert [c["id"] for c in found] == ["a", "b", "c"]
    assert bodies == [{"include_details": True, "record_offset": 0, "record_size": 2},
                      {"include_details": True, "record_offset": 2, "record_size": 2}]
    with pytest.raises(PagedSearchError, match="connection/search answered dict at offset 0, "
                                               "not a list of connections"):
        search_pages(lambda body: {}, what="connection/search", items="connections")
    assert issubclass(CalendarSearchError, PagedSearchError)


# ── `ts calendar search` ────────────────────────────────────────────────────

def _client(server):
    client = MagicMock()
    client.post.side_effect = lambda path, json=None, **kw: MagicMock(
        json=MagicMock(return_value=server(json)))
    return client


@patch("ts_cli.commands.calendars.resolve_profile", return_value="test")
@patch("ts_cli.commands.calendars.ThoughtSpotClient")
def test_cli_lists_every_calendar_not_the_first_ten(client_cls, _resolve):
    server = FakeServer(_calendars(57))
    client_cls.return_value = _client(server)
    result = runner.invoke(app, ["search"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)) == 57
    assert {c.args[0] for c in client_cls.return_value.post.call_args_list} == {SEARCH_PATH}
    assert all(b["record_size"] == 100 for b in server.bodies)


@patch("ts_cli.commands.calendars.resolve_profile", return_value="test")
@patch("ts_cli.commands.calendars.ThoughtSpotClient")
def test_cli_passes_the_connection(client_cls, _resolve):
    server = FakeServer(_calendars(4, connection="Snowflake Prod"))
    client_cls.return_value = _client(server)
    result = runner.invoke(app, ["search", "--connection", "Snowflake Prod"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)) == 4
    assert server.bodies[0]["connection_identifier"] == "Snowflake Prod"


@patch("ts_cli.commands.calendars.resolve_profile", return_value="test")
@patch("ts_cli.commands.calendars.ThoughtSpotClient")
def test_cli_reports_an_unpageable_answer_and_exits_1(client_cls, _resolve):
    client_cls.return_value = _client(lambda body: {"error": "no"})
    result = runner.invoke(app, ["search"])
    assert result.exit_code == 1
    assert "not a list of calendars" in result.output
