"""Relocation tests — ts_cli.tml_common is the canonical home; old paths are shims."""


class TestDumpTmlYaml:
    def test_new_home_importable(self):
        from ts_cli.tml_common import dump_tml_yaml
        out = dump_tml_yaml({"model": {"formulas": [{"expr": "sum([T::A])"}]}})
        assert '"sum([T::A])"' in out  # formula quoting still applied

    def test_old_paths_are_same_object(self):
        from ts_cli.tml_common import dump_tml_yaml as canonical
        from ts_cli.tableau.yaml_out import dump_tml_yaml as via_yaml_out
        from ts_cli.tableau_translate import dump_tml_yaml as via_translate
        assert via_yaml_out is canonical
        assert via_translate is canonical


class TestExtractImportedGuid:
    def test_new_home_handles_both_shapes(self):
        from ts_cli.tml_common import extract_imported_guid
        nested = [{"response": {"object": [{"header": {"id_guid": "g-nested"}}]}}]
        flat = [{"response": {"header": {"id_guid": "g-flat"},
                              "status": {"status_code": "OK"}}}]
        assert extract_imported_guid(nested) == "g-nested"
        assert extract_imported_guid(flat) == "g-flat"
        assert extract_imported_guid([]) is None

    def test_old_path_is_same_object(self):
        from ts_cli.tml_common import extract_imported_guid as canonical
        from ts_cli.tableau.build_model import extract_imported_guid as via_tableau
        assert via_tableau is canonical


class TestFlatShapeSites:
    """BL-099 #1 — each site wraps its single response item and calls the helper."""

    def test_single_item_wrap_flat(self):
        from ts_cli.tml_common import extract_imported_guid
        item = {"response": {"header": {"id_guid": "g1"},
                             "status": {"status_code": "OK"}}}
        assert extract_imported_guid([item]) == "g1"

    def test_response_block_wrap(self):
        # dependency.py rollback holds only the response block — wrap it back
        from ts_cli.tml_common import extract_imported_guid
        response_block = {"object": [], "header": {"id_guid": "g2"},
                          "status": {"status_code": "OK"}}
        assert extract_imported_guid([{"response": response_block}]) == "g2"


class TestTmlImportFailures:
    """Live-observed 2026-07-27: `import` returns HTTP 200 even when an item failed,
    so a caller checking only `resp.ok` reports success having changed nothing."""

    def test_a_success_response_has_no_failures(self):
        from ts_cli.tml_common import tml_import_failures
        result = [{"request_index": 0,
                  "response": {"status": {"status_code": "OK"},
                              "object": [{"header": {"id_guid": "g-1"}}]}}]
        assert tml_import_failures(result) == []

    def test_a_single_failed_item_is_reported(self):
        # The exact body observed importing a CSR document into an Org lacking the
        # referenced table.
        from ts_cli.tml_common import tml_import_failures
        result = [{"request_index": 0,
                  "response": {"status": {
                      "error_message": "Referenced table with name T2_PUBLISH not "
                                       "found.",
                      "status_code": "ERROR", "error_code": 14502}}}]
        failures = tml_import_failures(result)
        assert failures == [{"request_index": 0, "status_code": "ERROR",
                            "error_code": 14502,
                            "error_message": "Referenced table with name T2_PUBLISH "
                                            "not found."}]

    def test_only_the_failed_item_is_reported_among_several(self):
        from ts_cli.tml_common import tml_import_failures
        result = [
            {"request_index": 0, "response": {"status": {"status_code": "OK"}}},
            {"request_index": 1, "response": {"status": {
                "status_code": "ERROR", "error_code": 14502,
                "error_message": "Referenced table with name T3 not found."}}},
            {"request_index": 2, "response": {"status": {"status_code": "OK"}}},
        ]
        failures = tml_import_failures(result)
        assert len(failures) == 1
        assert failures[0]["request_index"] == 1

    def test_falls_back_to_list_position_when_request_index_is_absent(self):
        from ts_cli.tml_common import tml_import_failures
        result = [{"response": {"status": {"status_code": "ERROR",
                                          "error_code": 1, "error_message": "x"}}}]
        assert tml_import_failures(result)[0]["request_index"] == 0

    def test_a_missing_status_is_not_treated_as_a_failure(self):
        # No positive evidence of failure -- defaulting to "failed" here would flag
        # any response shape that simply omits status, which is not what was observed.
        from ts_cli.tml_common import tml_import_failures
        assert tml_import_failures([{"response": {}}]) == []
        assert tml_import_failures([{"response": {"status": {}}}]) == []

    def test_tolerates_junk_input(self):
        from ts_cli.tml_common import tml_import_failures
        assert tml_import_failures(None) == []
        assert tml_import_failures([]) == []
        assert tml_import_failures({"not": "a list"}) == []
        assert tml_import_failures(["not a dict", 42, None]) == []
        assert tml_import_failures([{"response": "not a dict"}]) == []
        assert tml_import_failures([{"response": {"status": "not a dict"}}]) == []
