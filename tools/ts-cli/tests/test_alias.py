"""Tests for ts_cli.alias — locale validation, CSV parsing, merge, TML assembly.

Pure-function tests — no I/O, no live ThoughtSpot connection required.
"""
import yaml

from ts_cli.alias import SUPPORTED_LOCALES, validate_locales


def test_supported_locales_count():
    assert len(SUPPORTED_LOCALES) == 27
    assert "de-DE" in SUPPORTED_LOCALES
    assert "zh-HANT" in SUPPORTED_LOCALES
    assert "xx-YY" not in SUPPORTED_LOCALES


def test_validate_locales_valid():
    result = validate_locales(["de-DE", "fr-FR", "ja-JP"])
    assert result == ["de-DE", "fr-FR", "ja-JP"]


def test_validate_locales_invalid(capsys):
    import pytest
    with pytest.raises(SystemExit):
        validate_locales(["de-DE", "xx-YY"])


from ts_cli.alias import parse_csv_aliases


def test_parse_csv_basic():
    csv_text = (
        "column_name,locale,alias,description,org_name,group_name\n"
        "Revenue,de-DE,Umsatz,Gesamtumsatz,,\n"
        "Region,,,Region Name,Org 1,\n"
    )
    result = parse_csv_aliases(csv_text)
    assert len(result) == 2
    assert result[0] == {
        "column": "Revenue", "locale": "de-DE", "alias": "Umsatz",
        "description": "Gesamtumsatz", "org": "TS_WILDCARD_ALL", "group": "TS_WILDCARD_ALL",
    }
    assert result[1]["org"] == "Org 1"
    assert result[1]["locale"] == "TS_WILDCARD_ALL"


def test_parse_csv_model_filter():
    csv_text = (
        "model_name,column_name,locale,alias,description,org_name,group_name\n"
        "Sales Model,Revenue,de-DE,Umsatz,,,\n"
        "Other Model,Cost,de-DE,Kosten,,,\n"
    )
    result = parse_csv_aliases(csv_text, model_name="Sales Model")
    assert len(result) == 1
    assert result[0]["column"] == "Revenue"


def test_parse_csv_empty():
    csv_text = "column_name,locale,alias,description\n"
    result = parse_csv_aliases(csv_text)
    assert result == []


from ts_cli.alias import merge_aliases, translations_to_columns


def _existing_columns():
    """Simulates column_alias.columns from an existing export."""
    return [
        {
            "name": "Revenue",
            "locales": [
                {
                    "name": "de-DE",
                    "orgs": [
                        {
                            "name": "TS_WILDCARD_ALL",
                            "groups": [
                                {"name": "TS_WILDCARD_ALL", "alias": "Umsatz",
                                 "description": "Gesamtumsatz"}
                            ]
                        }
                    ]
                }
            ]
        }
    ]


def test_merge_new_locale():
    existing = _existing_columns()
    new_translations = [
        {"column": "Revenue", "locale": "fr-FR", "alias": "Revenu",
         "description": "Revenu total", "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
    ]
    new_cols = translations_to_columns(new_translations)
    merged = merge_aliases(existing, new_cols)
    rev = [c for c in merged if c["name"] == "Revenue"][0]
    locale_names = {loc["name"] for loc in rev["locales"]}
    assert locale_names == {"de-DE", "fr-FR"}


def test_merge_overwrite_existing():
    existing = _existing_columns()
    new_translations = [
        {"column": "Revenue", "locale": "de-DE", "alias": "Erlöse",
         "description": "Total Erlöse", "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
    ]
    new_cols = translations_to_columns(new_translations)
    merged = merge_aliases(existing, new_cols)
    rev = [c for c in merged if c["name"] == "Revenue"][0]
    de_locale = [loc for loc in rev["locales"] if loc["name"] == "de-DE"][0]
    de_org = de_locale["orgs"][0]
    de_grp = de_org["groups"][0]
    assert de_grp["alias"] == "Erlöse"


def test_merge_preserves_unmatched():
    existing = _existing_columns()
    new_translations = [
        {"column": "Region", "locale": "de-DE", "alias": "Gebiet",
         "description": None, "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
    ]
    new_cols = translations_to_columns(new_translations)
    merged = merge_aliases(existing, new_cols)
    names = {c["name"] for c in merged}
    assert names == {"Revenue", "Region"}


def test_translations_to_columns_org_scoped():
    translations = [
        {"column": "string_1", "locale": "TS_WILDCARD_ALL", "alias": "Region",
         "description": None, "org": "Org 1", "group": "TS_WILDCARD_ALL"},
        {"column": "string_1", "locale": "TS_WILDCARD_ALL", "alias": "Client Name",
         "description": None, "org": "Org 2", "group": "TS_WILDCARD_ALL"},
    ]
    cols = translations_to_columns(translations)
    assert len(cols) == 1
    s1 = cols[0]
    assert s1["name"] == "string_1"
    locale = s1["locales"][0]
    assert locale["name"] == "TS_WILDCARD_ALL"
    org_names = {o["name"] for o in locale["orgs"]}
    assert org_names == {"Org 1", "Org 2"}


from ts_cli.alias import build_alias_tml, estimate_tml_size


def test_build_alias_tml_basic():
    columns = translations_to_columns([
        {"column": "Revenue", "locale": "de-DE", "alias": "Umsatz",
         "description": "Gesamtumsatz", "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
    ])
    tml = build_alias_tml("Sales Model", "MODEL_abc123", columns)
    assert "column_alias:" in tml
    assert "Sales Model" in tml
    assert "MODEL_abc123" in tml
    assert "Umsatz" in tml


def test_build_alias_tml_roundtrip_structure():
    columns = translations_to_columns([
        {"column": "Revenue", "locale": "de-DE", "alias": "Umsatz",
         "description": None, "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
    ])
    tml = build_alias_tml("Sales", "MODEL_1", columns)
    parsed = yaml.safe_load(tml)
    assert "column_alias" in parsed
    assert parsed["column_alias"]["model"]["name"] == "Sales"
    assert parsed["column_alias"]["columns"][0]["name"] == "Revenue"


def test_estimate_tml_size():
    tml = "column_alias:\n  model:\n    name: Test\n"
    size = estimate_tml_size(tml)
    assert size == len(tml.encode("utf-8"))


from ts_cli.alias import parse_export_response


def test_parse_export_response_with_aliases():
    edocs = [
        {
            "info": {"type": "LOGICAL_TABLE", "subType": "ONE_TO_ONE_LOGICAL",
                     "id": "guid-123", "name": "Sales Model"},
            "edoc": yaml.dump({
                "model": {
                    "name": "Sales Model",
                    "model_tables": [
                        {"name": "FACT", "columns": [
                            {"name": "Revenue", "description": "Total rev",
                             "column_type": "MEASURE"},
                            {"name": "Region", "description": "",
                             "column_type": "ATTRIBUTE"},
                        ]}
                    ],
                    "formulas": [],
                    "columns": [
                        {"name": "Revenue", "description": "Total rev",
                         "column_type": "MEASURE"},
                        {"name": "Region", "column_type": "ATTRIBUTE"},
                    ],
                }
            }),
        },
        {
            "info": {"type": "COLUMN_ALIAS", "id": "alias-456",
                     "filename": "Sales Model_alias.yaml"},
            "edoc": yaml.dump({
                "column_alias": {
                    "model": {"name": "Sales Model", "fqn": "MODEL_abc123"},
                    "columns": [
                        {"name": "Revenue", "locales": [
                            {"name": "de-DE", "orgs": [
                                {"name": "TS_WILDCARD_ALL", "groups": [
                                    {"name": "TS_WILDCARD_ALL", "alias": "Umsatz",
                                     "description": "Gesamtumsatz"}
                                ]}
                            ]}
                        ]}
                    ]
                }
            }),
        },
    ]
    result = parse_export_response(edocs)
    assert result["model"]["guid"] == "guid-123"
    assert result["model"]["name"] == "Sales Model"
    assert len(result["columns"]) == 2
    assert result["existing_aliases"] is not None
    assert result["existing_aliases"]["columns"][0]["name"] == "Revenue"


def test_parse_export_response_no_aliases():
    edocs = [
        {
            "info": {"type": "LOGICAL_TABLE", "subType": "ONE_TO_ONE_LOGICAL",
                     "id": "guid-123", "name": "Sales Model"},
            "edoc": yaml.dump({
                "model": {
                    "name": "Sales Model",
                    "columns": [
                        {"name": "Revenue", "column_type": "MEASURE"},
                    ],
                    "model_tables": [],
                    "formulas": [],
                }
            }),
        },
    ]
    result = parse_export_response(edocs)
    assert result["existing_aliases"] is None
