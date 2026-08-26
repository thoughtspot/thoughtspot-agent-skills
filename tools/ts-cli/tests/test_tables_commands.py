

class TestSubstringNamePatternPaging:
    """Finding 14.5 — a paged substring search can omit the exact match.

    `name_pattern` is a SUBSTRING match (the repo documents it as such and passes
    `%{keyword}%`). With `record_size: 10`, a name that is a substring of many others
    ("Sales") need not appear in the returned page at all — the exact-name post-filter
    then finds nothing, `_find_table` returns None, and the caller **creates a duplicate
    table** instead of updating it. Silent, and unrecoverable without manual cleanup.
    """

    class _Client:
        """Records the request so the page size can be asserted; returns a realistic
        substring result set in which the exact match is NOT in the first ten rows."""

        def __init__(self):
            self.requests = []

        def post(self, path, json=None, **kw):
            self.requests.append(json)
            size = (json or {}).get("record_size")
            rows = [
                {"metadata_id": f"g{i}", "metadata_name": f"Sales {i}",
                 "metadata_header": {"dataSourceName": "SNOW"}}
                for i in range(1, 13)
            ]
            # The exact match sits at position 13 — beyond a 10-row page.
            rows.append({"metadata_id": "exact", "metadata_name": "Sales",
                         "metadata_header": {"dataSourceName": "SNOW"}})
            payload = rows if size == -1 else rows[:10]

            class R:
                status_code = 200

                @staticmethod
                def json():
                    return payload

            return R()

    def test_requests_every_row_not_a_page(self):
        from ts_cli.commands.tables import _find_guid_by_name as _find_table
        client = self._Client()
        _find_table(client, "Sales", "SNOW")
        assert client.requests[0]["record_size"] == -1, (
            "a paged substring search can omit the exact match; -1 is the codebase's "
            "own convention (metadata.py:358, connections.py:139, share.py:356)"
        )

    def test_finds_an_exact_match_beyond_the_first_page(self):
        from ts_cli.commands.tables import _find_guid_by_name as _find_table
        assert _find_table(self._Client(), "Sales", "SNOW") == "exact"

    def test_connection_still_scopes_the_result(self):
        """-1 widens the page, not the matching rule."""
        from ts_cli.commands.tables import _find_guid_by_name as _find_table
        assert _find_table(self._Client(), "Sales", "OTHER_CONN") is None

    def test_a_lookup_failure_is_reported_not_swallowed(self, capsys):
        from ts_cli.commands.tables import _find_guid_by_name as _find_table

        class Boom:
            def post(self, *a, **kw):
                raise RuntimeError("network gone")

        assert _find_table(Boom(), "Sales", "SNOW") is None
        err = capsys.readouterr().err
        assert "warning: table lookup" in err and "may create a duplicate" in err
