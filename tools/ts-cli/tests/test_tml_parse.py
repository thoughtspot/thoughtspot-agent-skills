"""Unit tests for ts tml export --parse helpers.

Tests cover:
  - strip_nonprintable: removes non-printable chars, leaves valid content intact
  - detect_tml_type: identifies model/table/answer/worksheet from top-level key
  - parse_edoc: parses YAML and JSON edoc strings into dicts
  - Full pipeline: the combination produces the expected output shape
"""
import json

import pytest
import yaml

from ts_cli.commands.tml import detect_tml_type, parse_edoc, strip_nonprintable


# ---------------------------------------------------------------------------
# Fixtures — minimal but realistic edoc strings
# ---------------------------------------------------------------------------

MODEL_EDOC_YAML = """\
guid: 3b0de9da-8753-4def-b5a4-1be6b7f66991
model:
  name: TEST_SV_Dunder Mifflin Sales & Inventory
  model_tables:
  - name: DM_ORDER_DETAIL
    fqn: b1e360c4-d571-490f-bae2-e8dc7443c9fa
  formulas:
  - id: formula_Revenue
    name: Revenue
    expr: sum ( [DM_ORDER_DETAIL::LINE_TOTAL] )
  columns:
  - name: Revenue
    formula_id: formula_Revenue
    properties:
      column_type: MEASURE
      aggregation: SUM
"""

TABLE_EDOC_YAML = """\
guid: b1e360c4-d571-490f-bae2-e8dc7443c9fa
table:
  name: DM_ORDER_DETAIL
  db: DUNDERMIFFLIN
  schema: PUBLIC
  db_table: DM_ORDER_DETAIL
  columns:
  - name: LINE_TOTAL
    db_column_name: LINE_TOTAL
    properties:
      column_type: MEASURE
      aggregation: SUM
"""

ANSWER_EDOC_YAML = """\
guid: 03dc7ccb-74d6-4fbf-9449-e58e135d3964
answer:
  name: Answer Level Objects
  tables:
  - id: TEST_SV_Dunder Mifflin Sales & Inventory
    name: TEST_SV_Dunder Mifflin Sales & Inventory
    fqn: 3b0de9da-8753-4def-b5a4-1be6b7f66991
  formulas:
  - id: formula_Answer Formula
    name: Answer Formula
    expr: sum ( [Amount] ) / sum ( [Quantity] )
    was_auto_generated: false
  parameters:
  - id: e4f38863-78ac-459c-a1fa-245583b71d69
    name: Answer Paramerer
    data_type: INT64
    default_value: "10"
"""

WORKSHEET_EDOC_YAML = """\
guid: aaaa-bbbb-cccc
worksheet:
  name: Legacy Worksheet
  tables:
  - name: FACT_SALES
"""

MODEL_EDOC_JSON = json.dumps({
    "guid": "abc-123",
    "model": {"name": "JSON Model", "columns": []},
})


# ---------------------------------------------------------------------------
# strip_nonprintable
# ---------------------------------------------------------------------------

class TestStripNonprintable:
    def test_clean_string_unchanged(self):
        text = "guid: abc\nmodel:\n  name: Test\n"
        assert strip_nonprintable(text) == text

    def test_removes_null_byte(self):
        text = "clean\x00content"
        assert "\x00" not in strip_nonprintable(text)
        assert "cleancontent" == strip_nonprintable(text)

    def test_removes_control_chars(self):
        # BEL (07), BS (08), FF (0C), VT (0B) are non-printable
        text = "a\x07b\x08c\x0Bd"
        result = strip_nonprintable(text)
        assert result == "abcd"

    def test_preserves_tab_lf_cr(self):
        text = "col1\tcol2\nrow1\r\nrow2"
        result = strip_nonprintable(text)
        assert result == text

    def test_preserves_non_ascii_printable(self):
        # Non-breaking space (A0) and BMP chars should be kept
        text = "caf\u00e9 \u00a0 \u4e2d\u6587"
        result = strip_nonprintable(text)
        assert result == text

    def test_empty_string(self):
        assert strip_nonprintable("") == ""

    def test_only_nonprintable_becomes_empty(self):
        assert strip_nonprintable("\x00\x01\x02\x03") == ""


# ---------------------------------------------------------------------------
# detect_tml_type
# ---------------------------------------------------------------------------

class TestDetectTmlType:
    def test_model(self):
        assert detect_tml_type({"guid": "abc", "model": {}}) == "model"

    def test_table(self):
        assert detect_tml_type({"guid": "abc", "table": {}}) == "table"

    def test_answer(self):
        assert detect_tml_type({"guid": "abc", "answer": {}}) == "answer"

    def test_liveboard(self):
        assert detect_tml_type({"guid": "abc", "liveboard": {}}) == "liveboard"

    def test_worksheet(self):
        assert detect_tml_type({"guid": "abc", "worksheet": {}}) == "worksheet"

    def test_no_guid_key(self):
        assert detect_tml_type({"model": {"name": "x"}}) == "model"

    def test_unknown_type_returns_first_non_guid_key(self):
        result = detect_tml_type({"guid": "abc", "future_object": {}})
        assert result == "future_object"

    def test_empty_dict_returns_unknown(self):
        assert detect_tml_type({}) == "unknown"

    def test_only_guid_returns_unknown(self):
        assert detect_tml_type({"guid": "abc"}) == "unknown"


# ---------------------------------------------------------------------------
# parse_edoc — YAML
# ---------------------------------------------------------------------------

class TestParseEdocYaml:
    def test_parses_model(self):
        result = parse_edoc(MODEL_EDOC_YAML, "YAML")
        assert result["guid"] == "3b0de9da-8753-4def-b5a4-1be6b7f66991"
        assert result["model"]["name"] == "TEST_SV_Dunder Mifflin Sales & Inventory"
        assert result["model"]["formulas"][0]["id"] == "formula_Revenue"

    def test_parses_table(self):
        result = parse_edoc(TABLE_EDOC_YAML, "YAML")
        assert result["table"]["name"] == "DM_ORDER_DETAIL"

    def test_parses_answer_with_formulas_and_parameters(self):
        result = parse_edoc(ANSWER_EDOC_YAML, "YAML")
        assert result["answer"]["name"] == "Answer Level Objects"
        assert result["answer"]["tables"][0]["fqn"] == "3b0de9da-8753-4def-b5a4-1be6b7f66991"
        assert result["answer"]["formulas"][0]["name"] == "Answer Formula"
        assert result["answer"]["parameters"][0]["name"] == "Answer Paramerer"

    def test_default_format_is_yaml(self):
        """parse_edoc with no format arg should default to YAML."""
        result = parse_edoc(MODEL_EDOC_YAML)
        assert "model" in result

    def test_strips_nonprintable_before_parse(self):
        dirty = "guid: abc-123\x00\nmodel:\n  name: Clean\n"
        result = parse_edoc(dirty, "YAML")
        assert result["model"]["name"] == "Clean"

    def test_invalid_yaml_raises(self):
        with pytest.raises(yaml.YAMLError):
            parse_edoc("guid: [\nbad yaml", "YAML")


# ---------------------------------------------------------------------------
# parse_edoc — JSON
# ---------------------------------------------------------------------------

class TestParseEdocJson:
    def test_parses_json_edoc(self):
        result = parse_edoc(MODEL_EDOC_JSON, "JSON")
        assert result["guid"] == "abc-123"
        assert result["model"]["name"] == "JSON Model"

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_edoc("{bad json", "JSON")


# ---------------------------------------------------------------------------
# Full pipeline — parse_edoc + detect_tml_type
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Simulate what --parse does for each item in the export response."""

    def _run(self, edoc_yaml: str) -> dict:
        parsed = parse_edoc(edoc_yaml, "YAML")
        return {
            "type": detect_tml_type(parsed),
            "guid": parsed.get("guid", ""),
            "tml": parsed,
        }

    def test_model_pipeline(self):
        out = self._run(MODEL_EDOC_YAML)
        assert out["type"] == "model"
        assert out["guid"] == "3b0de9da-8753-4def-b5a4-1be6b7f66991"
        assert out["tml"]["model"]["name"] == "TEST_SV_Dunder Mifflin Sales & Inventory"

    def test_table_pipeline(self):
        out = self._run(TABLE_EDOC_YAML)
        assert out["type"] == "table"
        assert out["guid"] == "b1e360c4-d571-490f-bae2-e8dc7443c9fa"

    def test_answer_pipeline(self):
        out = self._run(ANSWER_EDOC_YAML)
        assert out["type"] == "answer"
        assert out["guid"] == "03dc7ccb-74d6-4fbf-9449-e58e135d3964"
        # Verify key Answer fields are accessible without extra parsing
        assert out["tml"]["answer"]["formulas"][0]["expr"] == "sum ( [Amount] ) / sum ( [Quantity] )"
        assert out["tml"]["answer"]["tables"][0]["fqn"] == "3b0de9da-8753-4def-b5a4-1be6b7f66991"

    def test_worksheet_pipeline(self):
        out = self._run(WORKSHEET_EDOC_YAML)
        assert out["type"] == "worksheet"
        assert out["guid"] == "aaaa-bbbb-cccc"

    def test_output_is_json_serialisable(self):
        """The pipeline output must round-trip through json.dumps without error."""
        out = self._run(MODEL_EDOC_YAML)
        serialised = json.dumps(out)
        restored = json.loads(serialised)
        assert restored["type"] == "model"

    def test_nonprintable_in_edoc_does_not_break_pipeline(self):
        dirty_model = MODEL_EDOC_YAML.replace("Revenue", "Rev\x00enue")
        out = self._run(dirty_model)
        assert out["type"] == "model"
        # Null byte stripped — formula name should be clean
        formula_name = out["tml"]["model"]["formulas"][0]["name"]
        assert "\x00" not in formula_name
