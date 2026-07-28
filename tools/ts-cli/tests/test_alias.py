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
    assert de_grp["entries"][0]["alias"] == "Erlöse"


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


from ts_cli.alias import build_alias_tml, build_alias_csv, estimate_tml_size, _make_obj_id


def test_build_alias_tml_basic():
    columns = translations_to_columns([
        {"column": "Revenue", "locale": "de-DE", "alias": "Umsatz",
         "description": "Gesamtumsatz", "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
    ])
    tml = build_alias_tml("Sales Model", "MODEL_abc123", columns)
    assert "column_alias:" in tml
    assert "Sales Model" in tml
    assert "obj_id: Sales Model-MODEL_ab" in tml
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
    assert parsed["column_alias"]["model"]["obj_id"] == "Sales-MODEL_1"
    assert "fqn" not in parsed["column_alias"]["model"]
    assert parsed["column_alias"]["columns"][0]["name"] == "Revenue"


def test_make_obj_id_standard_guid():
    assert _make_obj_id("MyModel", "96edf61f-1bd9-49ed-ba6b-6aa7928a2b60") == "MyModel-96edf61f"


def test_make_obj_id_no_dashes():
    assert _make_obj_id("M", "abcdefgh") == "M-abcdefgh"


def test_build_alias_csv_basic():
    columns = translations_to_columns([
        {"column": "Revenue", "locale": "de-DE", "alias": "Umsatz",
         "description": "Gesamtumsatz", "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
        {"column": "Region", "locale": "de-DE", "alias": "Gebiet",
         "description": "", "org": "TS_WILDCARD_ALL",
         "group": "TS_WILDCARD_ALL"},
    ])
    csv_text = build_alias_csv(columns)
    lines = [l.strip() for l in csv_text.strip().splitlines()]
    assert lines[0] == '"Column","locale","alias","description","org_name","group_name"'
    assert len(lines) == 3
    assert '"Revenue"' in lines[1] or '"Revenue"' in lines[2]
    assert '"Umsatz"' in csv_text
    assert '"Gebiet"' in csv_text


def test_build_alias_csv_entries_structure():
    """CSV output correctly flattens the entries wrapper."""
    columns = [
        {"name": "COL_A", "locales": [
            {"name": "ja-JP", "orgs": [
                {"name": "TS_WILDCARD_ALL", "groups": [
                    {"name": "TS_WILDCARD_ALL", "entries": [
                        {"alias": "列A", "description": ""}
                    ]}
                ]}
            ]}
        ]}
    ]
    csv_text = build_alias_csv(columns)
    lines = csv_text.strip().split("\n")
    assert len(lines) == 2
    assert '"列A"' in lines[1]


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


# ---------------------------------------------------------------------------
# Overlapping alias scopes — ambiguity falls back to the BASE column name
# ---------------------------------------------------------------------------

from ts_cli.alias import WILDCARD_GROUP, find_scope_overlaps  # noqa: E402


def _cols(org_groups, column="STRING_1", locale="en-US", org="ORG2"):
    """One column with the given group names, each carrying an alias entry."""
    return [{"name": column, "locales": [{"name": locale, "orgs": [{
        "name": org,
        "groups": [{"name": g, "entries": [{"alias": "Segment"}]} for g in org_groups]}]}]}]


def test_wildcard_plus_a_group_is_an_overlap():
    """Learned live 2026-07-28: a user matching both pathways sees the BASE column name,
    not either alias. Nothing downstream catches it -- every entry is valid, the import
    returns OK, and the export looks right."""
    problems = find_scope_overlaps(_cols([WILDCARD_GROUP, "MIGTEST_VIEWERS"]))
    assert len(problems) == 1
    assert "BASE column name" in problems[0]
    assert "MIGTEST_VIEWERS" in problems[0]


def test_IDENTICAL_alias_values_are_still_an_overlap():
    """The trap I fell into: I assumed matching values made the duplicate harmless. Two
    pathways is two pathways, whatever they say."""
    cols = _cols([WILDCARD_GROUP, "G1"])
    for g in cols[0]["locales"][0]["orgs"][0]["groups"]:
        g["entries"] = [{"alias": "Segment"}]          # deliberately identical
    assert find_scope_overlaps(cols)


def test_wildcard_ALONE_is_fine():
    """The correct Org-wide shape."""
    assert find_scope_overlaps(_cols([WILDCARD_GROUP])) == []


def test_group_scopes_ALONE_are_fine():
    """Several groups without a wildcard cannot double-match a user via the wildcard. A
    user in two of those groups is a different problem the platform owns, not one this
    check can see from the document."""
    assert find_scope_overlaps(_cols(["G1", "G2"])) == []


def test_the_overlap_must_be_in_the_SAME_org_to_count():
    """A wildcard in one Org and a group scope in another are independent audiences."""
    cols = [{"name": "STRING_1", "locales": [{"name": "en-US", "orgs": [
        {"name": "ORG2", "groups": [{"name": WILDCARD_GROUP,
                                     "entries": [{"alias": "A"}]}]},
        {"name": "ORG3", "groups": [{"name": "G1", "entries": [{"alias": "B"}]}]}]}]}]
    assert find_scope_overlaps(cols) == []


def test_the_overlap_must_be_in_the_SAME_locale_to_count():
    cols = [{"name": "STRING_1", "locales": [
        {"name": "en-US", "orgs": [{"name": "ORG2", "groups": [
            {"name": WILDCARD_GROUP, "entries": [{"alias": "A"}]}]}]},
        {"name": "fr-FR", "orgs": [{"name": "ORG2", "groups": [
            {"name": "G1", "entries": [{"alias": "B"}]}]}]}]}]
    assert find_scope_overlaps(cols) == []


def test_a_group_with_NO_entries_is_not_a_pathway():
    """An empty group carries no alias, so it cannot make a user ambiguous."""
    cols = _cols([WILDCARD_GROUP, "G1"])
    cols[0]["locales"][0]["orgs"][0]["groups"][1]["entries"] = []
    assert find_scope_overlaps(cols) == []


def test_every_offending_column_is_reported_not_just_the_first():
    """Scope mistakes are systematic -- a wave that gets this wrong gets it wrong for
    every column it touched."""
    cols = _cols([WILDCARD_GROUP, "G1"]) + _cols([WILDCARD_GROUP, "G1"], column="DATE_1")
    assert len(find_scope_overlaps(cols)) == 2


def test_the_message_says_what_to_DO_not_just_what_is_wrong():
    problems = find_scope_overlaps(_cols([WILDCARD_GROUP, "G1"]))
    assert "never both for one column" in problems[0]


def test_empty_input_does_not_crash():
    assert find_scope_overlaps([]) == []
    assert find_scope_overlaps(None) == []
