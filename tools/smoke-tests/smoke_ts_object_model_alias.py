"""Smoke test for ts-object-model-alias skill.

Tests the pure-function pipeline: CSV parse → translate → build → verify structure.
No live ThoughtSpot or Snowflake connection required.
"""
import json
import yaml
from ts_cli.alias import (
    SUPPORTED_LOCALES, validate_locales, parse_csv_aliases,
    translations_to_columns, merge_aliases, build_alias_tml,
    estimate_tml_size, parse_export_response,
)
from ts_cli.alias_translate import (
    build_translation_prompt, parse_translation_response,
    resolve_locale_config,
)


def test_full_pipeline_csv_to_tml():
    """Use case 2: CSV tenant renaming → TML."""
    csv_text = (
        "column_name,locale,alias,description,org_name,group_name\n"
        "string_1,,Region,,Org 1,\n"
        "string_1,,Client Name,,Org 2,\n"
        "string_2,,Revenue,Total revenue,Org 1,\n"
    )
    translations = parse_csv_aliases(csv_text)
    assert len(translations) == 3

    columns = translations_to_columns(translations)
    tml = build_alias_tml("Sales Model", "MODEL_abc123", columns)
    parsed = yaml.safe_load(tml)

    assert parsed["column_alias"]["model"]["name"] == "Sales Model"
    assert len(parsed["column_alias"]["columns"]) == 2

    size = estimate_tml_size(tml)
    assert size > 0
    assert size < 25 * 1024 * 1024


def test_merge_preserves_existing():
    """Merge adds new translations without losing existing ones."""
    existing = [
        {"name": "Revenue", "locales": [
            {"name": "de-DE", "orgs": [
                {"name": "TS_WILDCARD_ALL", "groups": [
                    {"name": "TS_WILDCARD_ALL", "alias": "Umsatz",
                     "description": "Gesamtumsatz"}
                ]}
            ]}
        ]}
    ]
    new = translations_to_columns([
        {"column": "Revenue", "locale": "fr-FR", "alias": "Revenu",
         "description": None, "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
    ])
    merged = merge_aliases(existing, new)
    rev = [c for c in merged if c["name"] == "Revenue"][0]
    locales = {loc["name"] for loc in rev["locales"]}
    assert "de-DE" in locales
    assert "fr-FR" in locales


def test_ai_prompt_roundtrip():
    """AI prompt builds, mock response parses correctly."""
    columns = [
        {"name": "Revenue", "description": "Total revenue"},
        {"name": "Region", "description": "Sales region"},
    ]
    prompt = build_translation_prompt(columns, "de-DE")
    assert "de-DE" in prompt

    mock_response = json.dumps([
        {"name": "Revenue", "alias": "Umsatz", "description": "Gesamtumsatz"},
        {"name": "Region", "alias": "Gebiet", "description": "Verkaufsgebiet"},
    ])
    result = parse_translation_response(
        mock_response, ["Revenue", "Region"],
        "de-DE", "TS_WILDCARD_ALL", "TS_WILDCARD_ALL",
    )
    assert len(result) == 2
    assert result[0]["locale"] == "de-DE"


if __name__ == "__main__":
    test_full_pipeline_csv_to_tml()
    test_merge_preserves_existing()
    test_ai_prompt_roundtrip()
    print("All smoke tests passed.")
