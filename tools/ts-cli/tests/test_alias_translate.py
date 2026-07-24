"""Tests for ts_cli.alias_translate — AI prompt building, response parsing,
locale config resolution, and AI batching.

Pure-function tests — no I/O, no live LLM or Snowflake connection required.
"""
import json

import pytest
import yaml

from ts_cli.alias_translate import (
    build_cortex_sql,
    build_translation_prompt,
    get_org_locales,
    group_translations_for_ai,
    parse_translation_response,
    resolve_locale_config,
)


def test_build_translation_prompt_basic():
    columns = [
        {"name": "Revenue", "description": "Total revenue amount"},
        {"name": "Region", "description": "Sales region"},
    ]
    prompt = build_translation_prompt(columns, "de-DE")
    assert "de-DE" in prompt
    assert "Revenue" in prompt
    assert "Region" in prompt
    assert "JSON" in prompt


def test_build_translation_prompt_with_context():
    columns = [{"name": "Region", "description": ""}]
    prompt = build_translation_prompt(
        columns, "fr-FR",
        source_context="These are org-specific aliases for a retail company",
    )
    assert "fr-FR" in prompt
    assert "retail" in prompt


def test_parse_translation_response_valid():
    response = json.dumps([
        {"name": "Revenue", "alias": "Umsatz", "description": "Gesamtumsatz"},
        {"name": "Region", "alias": "Gebiet", "description": None},
    ])
    result = parse_translation_response(
        response, ["Revenue", "Region"], "de-DE", "TS_WILDCARD_ALL", "TS_WILDCARD_ALL"
    )
    assert len(result) == 2
    assert result[0]["column"] == "Revenue"
    assert result[0]["alias"] == "Umsatz"
    assert result[0]["locale"] == "de-DE"
    assert result[0]["org"] == "TS_WILDCARD_ALL"


def test_parse_translation_response_with_markdown_fences():
    response = '```json\n[{"name": "Revenue", "alias": "Umsatz", "description": null}]\n```'
    result = parse_translation_response(
        response, ["Revenue"], "de-DE", "TS_WILDCARD_ALL", "TS_WILDCARD_ALL"
    )
    assert len(result) == 1
    assert result[0]["alias"] == "Umsatz"


def test_parse_translation_response_wrong_count():
    response = json.dumps([
        {"name": "Revenue", "alias": "Umsatz", "description": None},
    ])
    with pytest.raises(ValueError, match="Expected 2"):
        parse_translation_response(
            response, ["Revenue", "Region"], "de-DE", "TS_WILDCARD_ALL", "TS_WILDCARD_ALL"
        )


def test_parse_translation_response_wrong_column_name():
    response = json.dumps([
        {"name": "Fabricated", "alias": "Umsatz", "description": None},
    ])
    with pytest.raises(ValueError, match="Unknown column"):
        parse_translation_response(
            response, ["Revenue"], "de-DE", "TS_WILDCARD_ALL", "TS_WILDCARD_ALL"
        )


def test_resolve_locale_config_flag():
    result = resolve_locale_config(
        ai_locales=["de-DE", "fr-FR"],
        config_path=None,
        config_table=None,
        sf_cursor=None,
    )
    assert result == {"*": ["de-DE", "fr-FR"]}


def test_resolve_locale_config_yaml(tmp_path):
    config = tmp_path / "locales.yaml"
    config.write_text(yaml.dump({
        "default": ["de-DE", "fr-FR"],
        "orgs": {
            "Org 1": ["de-DE", "en-GB"],
            "Org 2": ["es-ES"],
        },
    }))
    result = resolve_locale_config(
        ai_locales=None,
        config_path=str(config),
        config_table=None,
        sf_cursor=None,
    )
    assert result["*"] == ["de-DE", "fr-FR"]
    assert result["Org 1"] == ["de-DE", "en-GB"]
    assert result["Org 2"] == ["es-ES"]


def test_resolve_locale_config_table():
    class FakeCursor:
        def execute(self, sql):
            self.sql = sql

        def fetchall(self):
            return [
                ("Org 1", "de-DE"),
                ("Org 1", "en-GB"),
                (None, "fr-FR"),
            ]

    cursor = FakeCursor()
    result = resolve_locale_config(
        ai_locales=None,
        config_path=None,
        config_table="LOCALE_CONFIG",
        sf_cursor=cursor,
    )
    assert result["Org 1"] == ["de-DE", "en-GB"]
    assert result["*"] == ["fr-FR"]
    assert "LOCALE_CONFIG" in cursor.sql


def test_resolve_locale_config_none():
    result = resolve_locale_config(None, None, None, None)
    assert result == {}


def test_group_translations_for_ai_global():
    translations = [
        {"column": "Revenue", "org": "TS_WILDCARD_ALL", "alias": "Revenue"},
        {"column": "Region", "org": "TS_WILDCARD_ALL", "alias": "Region"},
    ]
    config = {"*": ["de-DE", "fr-FR"]}
    batches = group_translations_for_ai(translations, config)
    assert len(batches) == 2
    orgs = {b[0] for b in batches}
    locales = {b[1] for b in batches}
    assert orgs == {"TS_WILDCARD_ALL"}
    assert locales == {"de-DE", "fr-FR"}
    assert len(batches[0][2]) == 2


def test_group_translations_for_ai_per_org():
    translations = [
        {"column": "string_1", "org": "Org 1", "alias": "Region"},
        {"column": "string_1", "org": "Org 2", "alias": "Client Name"},
    ]
    config = {"Org 1": ["de-DE", "fr-FR"], "Org 2": ["es-ES"]}
    batches = group_translations_for_ai(translations, config)
    assert len(batches) == 3  # Org 1 x 2 locales + Org 2 x 1 locale


def test_get_org_locales_default_fallback():
    config = {"*": ["de-DE"], "Org 1": ["fr-FR"]}
    assert get_org_locales("Org 1", config) == ["fr-FR"]
    assert get_org_locales("Org 99", config) == ["de-DE"]


def test_build_cortex_sql():
    sql = build_cortex_sql("Translate 'Revenue' to de-DE")
    assert "SNOWFLAKE.CORTEX.COMPLETE" in sql
    assert "llama3.1-70b" in sql
    assert "Translate" in sql
