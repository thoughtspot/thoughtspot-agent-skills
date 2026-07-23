"""Tests for ts_cli.sv_build_model — Snowflake SV model TML assembly."""
from __future__ import annotations

import copy
import pytest

from ts_cli.sv_build_model import (
    build_columns_and_formulas,
    build_description,
    build_model_tables,
    build_model_tml_sv,
    display_title,
    normalize_tables,
    strip_formulas,
    _build_join_on,
    _check_no_duplicate_display_names,
    _column_props,
    _detect_fact_tables,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _translated_basic():
    """3 dims (1 formula), 1 fact, 2 metrics (1 physical, 1 formula)."""
    return [
        {"name": "CUSTOMER_ID", "role": "dimension", "output_kind": "column",
         "column_type": "ATTRIBUTE", "table": "CUSTOMERS", "column": "CUSTOMER_ID",
         "ts_expr": None, "aggregation": None, "comment": None,
         "synonyms": [], "is_private": False, "annotations": []},
        {"name": "CUSTOMER_NAME", "role": "dimension", "output_kind": "column",
         "column_type": "ATTRIBUTE", "table": "CUSTOMERS", "column": "CUSTOMER_NAME",
         "ts_expr": None, "aggregation": None, "comment": "Full name",
         "synonyms": ["Client Name", "Account"], "is_private": False,
         "annotations": []},
        {"name": "DAYS_ACTIVE", "role": "dimension", "output_kind": "formula",
         "column_type": "ATTRIBUTE", "table": None, "column": None,
         "ts_expr": "diff_days ( today () , [CUSTOMERS::CREATED_AT] )",
         "aggregation": None, "comment": None, "synonyms": [],
         "is_private": False, "annotations": []},
        {"name": "ORDER_DATE", "role": "fact", "output_kind": "column",
         "column_type": "ATTRIBUTE", "table": "ORDERS", "column": "ORDER_DATE",
         "ts_expr": None, "aggregation": None, "comment": None,
         "synonyms": [], "is_private": False, "annotations": []},
        {"name": "TOTAL_AMOUNT", "role": "metric", "output_kind": "column",
         "column_type": "MEASURE", "table": "ORDERS", "column": "AMOUNT",
         "ts_expr": None, "aggregation": "SUM", "comment": "Revenue",
         "synonyms": ["Revenue", "Sales"], "is_private": False,
         "annotations": []},
        {"name": "AVG_ORDER", "role": "metric", "output_kind": "formula",
         "column_type": "MEASURE", "table": None, "column": None,
         "ts_expr": "average ( [ORDERS::AMOUNT] )", "aggregation": None,
         "comment": None, "synonyms": [], "is_private": False,
         "annotations": []},
    ]


def _parsed_basic():
    return {
        "view_name": "DB.SCHEMA.SALES_SV",
        "name": "SALES_SV",
        "comment": "Sales analytics",
        "tables": [
            {"fqn": "DB.S.ORDERS", "name": "ORDERS", "alias": "ORDERS",
             "primary_key": ["ORDER_ID"]},
            {"fqn": "DB.S.CUSTOMERS", "name": "CUSTOMERS", "alias": "CUSTOMERS",
             "primary_key": ["CUSTOMER_ID"]},
        ],
        "relationships": [
            {"name": "ORDERS_TO_CUSTOMERS",
             "from_table": "ORDERS", "from_cols": ["CUSTOMER_ID"],
             "to_table": "CUSTOMERS", "to_cols": ["CUSTOMER_ID"],
             "join_style": "equi"},
        ],
        "dimensions": [], "metrics": [], "facts": [],
    }


def _tables_basic():
    return {
        "ORDERS": {"name": "ORDERS", "fqn": "guid-orders"},
        "CUSTOMERS": {"name": "CUSTOMERS", "fqn": "guid-customers"},
    }


def _parsed_range():
    return {
        "view_name": "DB.S.EVENTS_SV",
        "name": "EVENTS_SV",
        "comment": None,
        "tables": [
            {"fqn": "DB.S.EVENTS", "name": "EVENTS", "alias": "EVENTS",
             "primary_key": ["EVENT_ID"]},
            {"fqn": "DB.S.DATE_BRIDGE", "name": "DATE_BRIDGE",
             "alias": "DATE_BRIDGE", "primary_key": ["BRIDGE_ID"],
             "range_constraint": {"name": "RC1", "start": "UTC_START",
                                  "end": "UTC_END"}},
        ],
        "relationships": [
            {"name": "EVENTS_TO_BRIDGE",
             "from_table": "EVENTS", "from_cols": ["EVENT_TS"],
             "to_table": "DATE_BRIDGE",
             "to_cols": ["UTC_START", "UTC_END"],
             "join_style": "range"},
        ],
        "dimensions": [], "metrics": [], "facts": [],
    }


def _parsed_asof():
    return {
        "view_name": "DB.S.TRADES_SV",
        "name": "TRADES_SV",
        "comment": None,
        "tables": [
            {"fqn": "DB.S.TRADES", "name": "TRADES", "alias": "TRADES",
             "primary_key": ["TRADE_ID"]},
            {"fqn": "DB.S.RATES", "name": "RATES", "alias": "RATES",
             "primary_key": ["RATE_ID"]},
        ],
        "relationships": [
            {"name": "TRADES_TO_RATES",
             "from_table": "TRADES",
             "from_cols": ["SYMBOL", "TRADE_TS"],
             "to_table": "RATES",
             "to_cols": ["SYMBOL", "RATE_TS"],
             "join_style": "asof"},
        ],
        "dimensions": [], "metrics": [], "facts": [],
    }


# ---------------------------------------------------------------------------
# display_title
# ---------------------------------------------------------------------------

class TestDisplayTitle:
    def test_title_case(self):
        assert display_title({"name": "ORDER_DATE"}) == "Order Date"

    def test_synonym_wins(self):
        assert display_title(
            {"name": "ORDER_DATE", "synonyms": ["Date of Order", "Alt"]}
        ) == "Date of Order"

    def test_empty_synonyms_fallback(self):
        assert display_title({"name": "AMOUNT", "synonyms": []}) == "Amount"


# ---------------------------------------------------------------------------
# normalize_tables
# ---------------------------------------------------------------------------

class TestNormalizeTables:
    def test_string_values(self):
        assert normalize_tables({"A": "TableA"}) == {"A": "TableA"}

    def test_dict_values(self):
        assert normalize_tables(
            {"A": {"name": "TableA", "fqn": "g1"}}
        ) == {"A": "TableA"}


# ---------------------------------------------------------------------------
# _column_props
# ---------------------------------------------------------------------------

class TestColumnProps:
    def test_attribute(self):
        entry = {"column_type": "ATTRIBUTE", "comment": None, "synonyms": []}
        assert _column_props(entry, is_formula=False) == {
            "column_type": "ATTRIBUTE"}

    def test_measure_column(self):
        entry = {"column_type": "MEASURE", "aggregation": "SUM",
                 "comment": None, "synonyms": []}
        props = _column_props(entry, is_formula=False)
        assert props["aggregation"] == "SUM"
        assert "index_type" not in props

    def test_measure_formula(self):
        entry = {"column_type": "MEASURE", "aggregation": None,
                 "comment": None, "synonyms": []}
        props = _column_props(entry, is_formula=True)
        assert props["aggregation"] == "SUM"
        assert props["index_type"] == "DONT_INDEX"

    def test_private(self):
        entry = {"column_type": "ATTRIBUTE", "comment": None, "synonyms": [],
                 "is_private": True}
        props = _column_props(entry, is_formula=False)
        assert props["index_type"] == "DONT_INDEX"

    def test_description(self):
        entry = {"column_type": "ATTRIBUTE", "comment": "desc",
                 "synonyms": []}
        props = _column_props(entry, is_formula=False)
        assert props["description"] == "desc"

    def test_synonyms_skip_first(self):
        entry = {"column_type": "ATTRIBUTE", "comment": None,
                 "synonyms": ["Display", "Alt1", "Alt2"]}
        props = _column_props(entry, is_formula=False)
        assert props["synonyms"] == ["Alt1", "Alt2"]
        assert props["synonym_type"] == "USER_DEFINED"

    def test_single_synonym_no_remaining(self):
        entry = {"column_type": "ATTRIBUTE", "comment": None,
                 "synonyms": ["Display"]}
        props = _column_props(entry, is_formula=False)
        assert "synonyms" not in props


# ---------------------------------------------------------------------------
# _detect_fact_tables
# ---------------------------------------------------------------------------

class TestDetectFactTables:
    def test_simple(self):
        rels = [
            {"from_table": "ORDERS", "to_table": "CUSTOMERS"},
            {"from_table": "ORDERS", "to_table": "PRODUCTS"},
        ]
        assert _detect_fact_tables(rels) == {"ORDERS"}

    def test_chain(self):
        rels = [
            {"from_table": "ORDERS", "to_table": "CUSTOMERS"},
            {"from_table": "CUSTOMERS", "to_table": "REGIONS"},
        ]
        assert _detect_fact_tables(rels) == {"ORDERS"}

    def test_no_relationships(self):
        assert _detect_fact_tables([]) == set()


# ---------------------------------------------------------------------------
# _build_join_on
# ---------------------------------------------------------------------------

class TestBuildJoinOn:
    def test_equi(self):
        rel = {"from_table": "ORDERS", "from_cols": ["CUSTOMER_ID"],
               "to_table": "CUSTOMERS", "to_cols": ["CUSTOMER_ID"],
               "join_style": "equi"}
        flat = {"ORDERS": "ORDERS", "CUSTOMERS": "CUSTOMERS"}
        assert _build_join_on(rel, flat) == (
            "[ORDERS::CUSTOMER_ID] = [CUSTOMERS::CUSTOMER_ID]")

    def test_equi_multi_col(self):
        rel = {"from_table": "A", "from_cols": ["C1", "C2"],
               "to_table": "B", "to_cols": ["C1", "C2"],
               "join_style": "equi"}
        flat = {"A": "TA", "B": "TB"}
        assert _build_join_on(rel, flat) == (
            "[TA::C1] = [TB::C1] and [TA::C2] = [TB::C2]")

    def test_range(self):
        rel = {"from_table": "EVENTS", "from_cols": ["EVENT_TS"],
               "to_table": "BRIDGE", "to_cols": ["UTC_START", "UTC_END"],
               "join_style": "range"}
        flat = {"EVENTS": "EVENTS", "BRIDGE": "DATE_BRIDGE"}
        assert _build_join_on(rel, flat) == (
            "[EVENTS::EVENT_TS] >= [DATE_BRIDGE::UTC_START] and "
            "[EVENTS::EVENT_TS] < [DATE_BRIDGE::UTC_END]")

    def test_asof(self):
        rel = {"from_table": "TRADES", "from_cols": ["SYMBOL", "TRADE_TS"],
               "to_table": "RATES", "to_cols": ["SYMBOL", "RATE_TS"],
               "join_style": "asof"}
        flat = {"TRADES": "TRADES", "RATES": "RATES"}
        result = _build_join_on(rel, flat)
        assert "[TRADES::SYMBOL] = [RATES::SYMBOL]" in result
        assert "[TRADES::TRADE_TS] >= [RATES::RATE_TS]" in result


# ---------------------------------------------------------------------------
# build_model_tables
# ---------------------------------------------------------------------------

class TestBuildModelTables:
    def test_basic(self):
        parsed = _parsed_basic()
        tables = _tables_basic()
        mt = build_model_tables(parsed, tables)
        assert len(mt) == 2
        fact = mt[0]
        assert fact["name"] == "ORDERS"
        assert fact["fqn"] == "guid-orders"
        assert len(fact["joins"]) == 1
        join = fact["joins"][0]
        assert join["with"] == "CUSTOMERS"
        assert join["type"] == "LEFT_OUTER"
        assert join["cardinality"] == "MANY_TO_ONE"
        dim = mt[1]
        assert dim["name"] == "CUSTOMERS"
        assert "joins" not in dim

    def test_range_join(self):
        parsed = _parsed_range()
        tables = {"EVENTS": "EVENTS", "DATE_BRIDGE": "DATE_BRIDGE"}
        mt = build_model_tables(parsed, tables)
        join = mt[0]["joins"][0]
        assert ">=" in join["on"]
        assert "<" in join["on"]

    def test_asof_join(self):
        parsed = _parsed_asof()
        tables = {"TRADES": "TRADES", "RATES": "RATES"}
        mt = build_model_tables(parsed, tables)
        join = mt[0]["joins"][0]
        assert ">=" in join["on"]
        assert "= [RATES::SYMBOL]" in join["on"]

    def test_missing_alias_raises(self):
        parsed = _parsed_basic()
        tables = {"ORDERS": "ORDERS"}  # missing CUSTOMERS
        with pytest.raises(ValueError, match="CUSTOMERS"):
            build_model_tables(parsed, tables)


# ---------------------------------------------------------------------------
# Role-playing (aliased) dimensions — a reused physical table
# ---------------------------------------------------------------------------

def _parsed_roleplay():
    """A fact CASE that joins ACCOUNT twice (base + ON_BEHALF_ACCOUNT role) and
    USER twice (OWNER + RESOLVED_BY roles) — the physical table is reused."""
    return {
        "tables": [
            {"alias": "CASE", "name": "CASE"},
            {"alias": "ACCOUNT", "name": "ACCOUNT"},
            {"alias": "ON_BEHALF_ACCOUNT", "name": "ACCOUNT"},
            {"alias": "OWNER", "name": "USER"},
            {"alias": "RESOLVED_BY", "name": "USER"},
        ],
        "relationships": [
            {"name": "C_ACC", "from_table": "CASE", "from_cols": ["ACCOUNTID"],
             "to_table": "ACCOUNT", "to_cols": ["ID"], "join_style": "equi"},
            {"name": "C_OBO", "from_table": "CASE", "from_cols": ["ON_BEHALF_OF"],
             "to_table": "ON_BEHALF_ACCOUNT", "to_cols": ["ID"], "join_style": "equi"},
            {"name": "C_OWN", "from_table": "CASE", "from_cols": ["OWNERID"],
             "to_table": "OWNER", "to_cols": ["ID"], "join_style": "equi"},
            {"name": "C_RES", "from_table": "CASE", "from_cols": ["RESOLVEDBYID"],
             "to_table": "RESOLVED_BY", "to_cols": ["ID"], "join_style": "equi"},
        ],
    }


class TestRolePlayingAliases:
    def test_node_id_map(self):
        from ts_cli.sv_translate import build_node_id_map
        node_of = build_node_id_map(_parsed_roleplay())
        # single-use physical table -> physical name is the node id
        assert node_of["CASE"] == "CASE"
        # base instance whose alias equals the physical name -> physical name
        assert node_of["ACCOUNT"] == "ACCOUNT"
        # reused physical table, alias differs -> alias is the node id
        assert node_of["ON_BEHALF_ACCOUNT"] == "ON_BEHALF_ACCOUNT"
        assert node_of["OWNER"] == "OWNER"
        assert node_of["RESOLVED_BY"] == "RESOLVED_BY"

    def test_model_tables_emit_alias_not_id(self):
        parsed = _parsed_roleplay()
        tables = {t["alias"]: t["name"] for t in parsed["tables"]}
        mt = build_model_tables(parsed, tables)
        by = {(e["name"], e.get("alias")): e for e in mt}
        # base ACCOUNT: id == name, no alias
        base = next(e for e in mt if e["name"] == "ACCOUNT" and "alias" not in e)
        assert base.get("id") == "ACCOUNT"
        # role-play ACCOUNT: alias set, name is physical, NO id (I4: id must == name)
        obo = by[("ACCOUNT", "ON_BEHALF_ACCOUNT")]
        assert "id" not in obo
        assert obo["name"] == "ACCOUNT"
        # both USER roles present as distinct aliased entries over one physical table
        assert ("USER", "OWNER") in by
        assert ("USER", "RESOLVED_BY") in by
        assert "id" not in by[("USER", "OWNER")]

    def test_joins_reference_alias(self):
        parsed = _parsed_roleplay()
        tables = {t["alias"]: t["name"] for t in parsed["tables"]}
        mt = build_model_tables(parsed, tables)
        fact = next(e for e in mt if e["name"] == "CASE")
        withs = {j["with"] for j in fact["joins"]}
        # each role-play join targets the alias, never the bare physical name twice
        assert withs == {"ACCOUNT", "ON_BEHALF_ACCOUNT", "OWNER", "RESOLVED_BY"}
        obo = next(j for j in fact["joins"] if j["with"] == "ON_BEHALF_ACCOUNT")
        assert obo["on"] == "[CASE::ON_BEHALF_OF] = [ON_BEHALF_ACCOUNT::ID]"


# ---------------------------------------------------------------------------
# build_columns_and_formulas
# ---------------------------------------------------------------------------

class TestBuildColumnsAndFormulas:
    def test_basic(self):
        translated = _translated_basic()
        columns, formulas, renames = build_columns_and_formulas(translated)

        phys = [c for c in columns if "column_id" in c]
        form = [c for c in columns if "formula_id" in c]
        assert len(phys) == 4  # 2 dims + 1 fact + 1 metric
        assert len(form) == 2  # 1 dim formula + 1 metric formula
        assert len(formulas) == 2

    def test_synonym_as_display_name(self):
        translated = _translated_basic()
        columns, _, _ = build_columns_and_formulas(translated)
        name_col = next(c for c in columns
                        if "column_id" in c
                        and c["column_id"] == "CUSTOMERS::CUSTOMER_NAME")
        assert name_col["name"] == "Client Name"

    def test_remaining_synonyms_in_props(self):
        translated = _translated_basic()
        columns, _, _ = build_columns_and_formulas(translated)
        name_col = next(c for c in columns
                        if "column_id" in c
                        and c["column_id"] == "CUSTOMERS::CUSTOMER_NAME")
        assert name_col["properties"]["synonyms"] == ["Account"]

    def test_measure_column(self):
        translated = _translated_basic()
        columns, _, _ = build_columns_and_formulas(translated)
        amount_col = next(c for c in columns
                          if "column_id" in c
                          and c["column_id"] == "ORDERS::AMOUNT")
        assert amount_col["name"] == "Revenue"
        assert amount_col["properties"]["aggregation"] == "SUM"

    def test_measure_formula(self):
        translated = _translated_basic()
        columns, formulas, _ = build_columns_and_formulas(translated)
        avg_formula = next(f for f in formulas
                           if f["name"] == "Avg Order")
        assert "average" in avg_formula["expr"]
        avg_col = next(c for c in columns
                       if c.get("formula_id") == avg_formula["id"])
        assert avg_col["properties"]["column_type"] == "MEASURE"
        assert avg_col["properties"]["index_type"] == "DONT_INDEX"

    def test_attribute_formula(self):
        translated = _translated_basic()
        _, formulas, _ = build_columns_and_formulas(translated)
        days_formula = next(f for f in formulas
                            if f["name"] == "Days Active")
        assert days_formula["properties"]["column_type"] == "ATTRIBUTE"

    def test_private_column(self):
        translated = [
            {"name": "INTERNAL_ID", "role": "dimension",
             "output_kind": "column", "column_type": "ATTRIBUTE",
             "table": "T", "column": "INTERNAL_ID", "ts_expr": None,
             "aggregation": None, "comment": None, "synonyms": [],
             "is_private": True, "annotations": []},
        ]
        columns, _, _ = build_columns_and_formulas(translated)
        assert columns[0]["properties"]["index_type"] == "DONT_INDEX"


# ---------------------------------------------------------------------------
# _check_no_duplicate_display_names
# ---------------------------------------------------------------------------

class TestCheckNoDuplicates:
    def test_clean(self):
        _check_no_duplicate_display_names(
            [{"name": "A"}, {"name": "B"}])

    def test_dupe_raises(self):
        with pytest.raises(ValueError, match="duplicate"):
            _check_no_duplicate_display_names(
                [{"name": "A"}, {"name": "A"}])


# ---------------------------------------------------------------------------
# build_description
# ---------------------------------------------------------------------------

class TestBuildDescription:
    def test_with_comment_and_fqn(self):
        desc = build_description("Sales data", "DB.S.SALES_SV")
        assert "Sales data" in desc
        assert "DB.S.SALES_SV" in desc

    def test_fqn_only(self):
        desc = build_description(None, "DB.S.SALES_SV")
        assert "DB.S.SALES_SV" in desc

    def test_neither(self):
        desc = build_description(None, None)
        assert "Snowflake Semantic View" in desc


# ---------------------------------------------------------------------------
# strip_formulas
# ---------------------------------------------------------------------------

class TestStripFormulas:
    def test_removes_formulas(self):
        doc = {
            "model": {
                "name": "Test",
                "formulas": [{"id": "formula_X", "name": "X", "expr": "1+1"}],
                "columns": [
                    {"name": "Col A", "column_id": "T::A",
                     "properties": {"column_type": "ATTRIBUTE"}},
                    {"name": "X", "formula_id": "formula_X",
                     "properties": {"column_type": "MEASURE"}},
                ],
            }
        }
        stripped = strip_formulas(doc)
        assert "formulas" not in stripped["model"]
        assert len(stripped["model"]["columns"]) == 1
        assert stripped["model"]["columns"][0]["name"] == "Col A"
        # original not mutated
        assert len(doc["model"]["formulas"]) == 1
        assert len(doc["model"]["columns"]) == 2

    def test_no_formulas_passthrough(self):
        doc = {
            "model": {
                "name": "Test",
                "columns": [
                    {"name": "A", "column_id": "T::A",
                     "properties": {"column_type": "ATTRIBUTE"}},
                ],
            }
        }
        stripped = strip_formulas(doc)
        assert len(stripped["model"]["columns"]) == 1


# ---------------------------------------------------------------------------
# build_model_tml_sv — full integration
# ---------------------------------------------------------------------------

class TestBuildModelTmlSv:
    def test_full_assembly(self):
        parsed = _parsed_basic()
        translated_doc = {
            "translated": _translated_basic(),
            "skipped": [],
            "stats": {"total": 6, "translated": 6, "skipped": 0},
        }
        tables = _tables_basic()

        doc, info = build_model_tml_sv(
            model_name="Sales Model", parsed=parsed,
            translated_doc=translated_doc, tables=tables,
            sv_fqn="DB.SCHEMA.SALES_SV", spotter_enabled=True)

        model = doc["model"]
        assert model["name"] == "Sales Model"
        assert "DB.SCHEMA.SALES_SV" in model["description"]
        assert model["properties"]["spotter_config"]["is_spotter_enabled"]

        assert len(model["model_tables"]) == 2
        assert model["model_tables"][0]["name"] == "ORDERS"
        assert model["model_tables"][0]["joins"][0]["with"] == "CUSTOMERS"

        assert info["formula_count"] == 2
        assert len(info["attributes"]) == 4  # 3 dims + 1 fact
        assert len(info["measures"]) == 2

    def test_with_existing_guid(self):
        parsed = _parsed_basic()
        translated_doc = {
            "translated": _translated_basic(),
            "skipped": [], "stats": {},
        }
        tables = _tables_basic()
        doc, _ = build_model_tml_sv(
            model_name="M", parsed=parsed, translated_doc=translated_doc,
            tables=tables, existing_guid="abc-123")
        assert doc["guid"] == "abc-123"
        assert "model" in doc

    def test_no_guid_by_default(self):
        parsed = _parsed_basic()
        translated_doc = {
            "translated": _translated_basic(),
            "skipped": [], "stats": {},
        }
        tables = _tables_basic()
        doc, _ = build_model_tml_sv(
            model_name="M", parsed=parsed, translated_doc=translated_doc,
            tables=tables)
        assert "guid" not in doc

    def test_no_relationships(self):
        parsed = {
            "name": "SINGLE_TABLE_SV", "comment": None,
            "tables": [
                {"fqn": "DB.S.T", "name": "T", "alias": "T",
                 "primary_key": ["ID"]},
            ],
            "relationships": [],
            "dimensions": [], "metrics": [], "facts": [],
        }
        translated_doc = {
            "translated": [
                {"name": "ID", "role": "dimension", "output_kind": "column",
                 "column_type": "ATTRIBUTE", "table": "T", "column": "ID",
                 "ts_expr": None, "aggregation": None, "comment": None,
                 "synonyms": [], "is_private": False, "annotations": []},
            ],
            "skipped": [], "stats": {},
        }
        tables = {"T": "T"}
        doc, info = build_model_tml_sv(
            model_name="M", parsed=parsed, translated_doc=translated_doc,
            tables=tables)
        mt = doc["model"]["model_tables"]
        assert len(mt) == 1
        assert "joins" not in mt[0]
        assert "id" not in mt[0]


# ---------------------------------------------------------------------------
# sv_parse.py name fix — verify the fix
# ---------------------------------------------------------------------------

class TestParseTableName:
    def test_fqn_table_has_name(self):
        from ts_cli.sv_parse import _parse_table_entry
        entry = _parse_table_entry("BIRD.FINANCIAL_SV.TRANS")
        assert entry["name"] == "TRANS"
        assert entry["alias"] == "TRANS"

    def test_explicit_alias_has_name(self):
        from ts_cli.sv_parse import _parse_table_entry
        entry = _parse_table_entry('ORDER_TBL as BIRD.FINANCIAL_SV."ORDER"')
        assert entry["alias"] == "ORDER_TBL"
        assert entry["name"] == "ORDER"

    def test_quoted_table_name(self):
        from ts_cli.sv_parse import _parse_table_entry
        entry = _parse_table_entry('DB.SCHEMA."My Table"')
        assert entry["name"] == "My Table"

    def test_subquery_has_name(self):
        from ts_cli.sv_parse import _parse_table_entry
        entry = _parse_table_entry("ALIAS as (SELECT 1 AS x)")
        assert entry["name"] == "ALIAS"
        assert entry["is_subquery"] is True
