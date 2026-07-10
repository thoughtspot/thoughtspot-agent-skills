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
