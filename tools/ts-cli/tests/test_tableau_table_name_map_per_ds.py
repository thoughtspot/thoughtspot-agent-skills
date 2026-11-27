"""--table-name-map keyed by datasource, display name vs db_table, and
logical-relationship keys wrapped in a function.

Two published (sqlproxy) datasources both parse to one table named
`sqlproxy`, so a flat map cannot send them to different ThoughtSpot tables.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from ts_cli.cli import app
from ts_cli.tableau.build_model import (
    apply_table_name_map,
    resolve_table_name_maps,
    table_name_map_conflicts,
    table_name_map_for,
)
from ts_cli.tableau.verify import verify_conversion
from ts_cli.tableau.noodle_joins import _extract_noodle_joins, _relationship_operand

DS_A = "orders_a | Project : Data Sources"
DS_B = "orders_b | Project : Data Sources"


# --- resolve_table_name_maps -------------------------------------------------

def test_flat_map_applies_to_every_datasource():
    maps = resolve_table_name_maps({"sqlproxy": "ORDERS"}, [DS_A, DS_B])
    assert table_name_map_for(maps, DS_A) == {"sqlproxy": "ORDERS"}
    assert table_name_map_for(maps, DS_B) == {"sqlproxy": "ORDERS"}


def test_per_datasource_entries_send_each_datasource_to_its_own_table():
    maps = resolve_table_name_maps(
        {DS_A: {"sqlproxy": "ORDERS_A"}, DS_B: {"sqlproxy": "ORDERS_B"}}, [DS_A, DS_B])
    assert table_name_map_for(maps, DS_A) == {"sqlproxy": "ORDERS_A"}
    assert table_name_map_for(maps, DS_B) == {"sqlproxy": "ORDERS_B"}


def test_per_datasource_entry_overrides_the_flat_one():
    maps = resolve_table_name_maps(
        {"sqlproxy": "ORDERS", "dim": "DIM", DS_B: {"sqlproxy": "ORDERS_B"}}, [DS_A, DS_B])
    assert table_name_map_for(maps, DS_A) == {"sqlproxy": "ORDERS", "dim": "DIM"}
    assert table_name_map_for(maps, DS_B) == {"sqlproxy": "ORDERS_B", "dim": "DIM"}


def test_datasource_without_an_entry_gets_an_empty_map_not_none():
    maps = resolve_table_name_maps({DS_A: {"sqlproxy": "ORDERS_A"}}, [DS_A, DS_B])
    assert table_name_map_for(maps, DS_B) == {}


def test_no_map_at_all_is_none():
    assert table_name_map_for({}, DS_A) is None


def test_object_target_is_a_flat_entry_not_a_datasource():
    maps = resolve_table_name_maps(
        {"sqlproxy": {"name": "Orders", "db_table": "ORDERS"}}, [DS_A])
    assert table_name_map_for(maps, DS_A) == {
        "sqlproxy": {"name": "Orders", "db_table": "ORDERS"}}


@pytest.mark.parametrize("raw, message", [
    ({"no such datasource": {"sqlproxy": "X"}}, "not a datasource in this workbook"),
    ({DS_A: {"sqlproxy": 3}}, "bad target"),
    ({"sqlproxy": {"name": "X", "schema": "Y"}}, "not a datasource"),
    ({"sqlproxy": ""}, "a target is a table name"),
    (["sqlproxy"], "expected a JSON object"),
])
def test_malformed_map_is_refused(raw, message):
    with pytest.raises(ValueError, match=message):
        resolve_table_name_maps(raw, [DS_A, DS_B])


# --- apply_table_name_map with a display name ---------------------------------

def _ds():
    return {
        "name": DS_A,
        "tables": [{"name": "sqlproxy", "db_table": "sqlproxy"}],
        "joins": [{"left_table": "sqlproxy", "right_table": "dim"}],
        "columns": [{"name": "ID", "table": "sqlproxy"}],
    }


def test_object_target_sets_name_and_db_table_separately():
    new_ds, scoped = apply_table_name_map(
        _ds(), {"ID": "sqlproxy"}, {"sqlproxy": {"name": "Orders", "db_table": "ORDERS"}})
    assert new_ds["tables"][0] == {"name": "Orders", "db_table": "ORDERS"}
    # Joins, columns and scopes reference the ThoughtSpot table, i.e. its name.
    assert new_ds["joins"][0]["left_table"] == "Orders"
    assert new_ds["columns"][0]["table"] == "Orders"
    assert scoped == {"ID": "Orders"}


def test_name_only_target_keeps_the_parsed_db_table():
    ds = _ds()
    ds["tables"][0]["db_table"] = "db.s.ORDERS"
    new_ds, _ = apply_table_name_map(ds, {}, {"sqlproxy": {"name": "Orders"}})
    assert new_ds["tables"][0] == {"name": "Orders", "db_table": "db.s.ORDERS"}


def test_string_target_still_sets_both():
    new_ds, _ = apply_table_name_map(_ds(), {}, {"sqlproxy": "ORDERS"})
    assert new_ds["tables"][0] == {"name": "ORDERS", "db_table": "ORDERS"}


# --- logical relationships ----------------------------------------------------

@pytest.mark.parametrize("op, expected", [
    ("[ID (Custom SQL Query2)]", ("ID", "Custom SQL Query2", None)),
    ("[ID]", ("ID", None, None)),
    ("INT([ID])", ("ID", None, "INT")),
    ("INT([ID (Custom SQL Query6)])", ("ID", "Custom SQL Query6", "INT")),
    ("[A] + [B]", ("[A] + [B]", None, None)),
    ("[A]]B (Q1)]", ("A]]B", "Q1", None)),
    ("INT(STR([ID (Q1)]))", ("INT(STR([ID (Q1)]))", None, None)),
])
def test_relationship_operand(op, expected):
    assert _relationship_operand(op) == expected


def _rels(*pairs):
    xml = "<datasource><object-graph><relationships>" + "".join(
        f"<relationship><expression op='='><expression op='{a}'/>"
        f"<expression op='{b}'/></expression></relationship>" for a, b in pairs
    ) + "</relationships></object-graph></datasource>"
    return ET.fromstring(xml)


def test_cast_key_to_the_base_table_invents_no_join():
    # The published-datasource shape: flattened to sqlproxy, so neither
    # relationship has a table to join, and each is reported.
    # The cast form used to read as column INT on a table named [ORDER_ID].
    ds = _rels(("INT([ORDER_ID])", "INT([ORDER_ID (Custom SQL Query6)])"),
               ("[ORDER_ID]", "[ORDER_ID (Custom SQL Query2)]"))
    joins, warnings, reviews = _extract_noodle_joins(ds, [], [{"name": "sqlproxy"}])
    assert joins == []
    assert len(warnings) == 2
    assert "'Custom SQL Query6'" in warnings[0] and "'Custom SQL Query2'" in warnings[1]


@pytest.mark.parametrize("left, right", [
    ("[Region]", "[Region (People)]"),
    ('DATETRUNC(&quot;month&quot;, [TS (Q1)])', "[M (Q2)]"),
    ("INT(STR([ID (Q1)]))", "[ID (Q2)]"),
])
def test_relationship_whose_table_cannot_be_read_is_skipped_with_a_warning(left, right):
    # A skipped relationship leaves a table unjoined, which import rejects;
    # the warning says which relationship was lost (BL-278).
    joins, warnings, reviews = _extract_noodle_joins(_rels((left, right)), [], [])
    assert joins == []
    assert len(warnings) == 1 and "cannot be read" in warnings[0] and "BL-278" in warnings[0]


def test_escaped_bracket_in_a_column_name_still_joins():
    joins, warnings, reviews = _extract_noodle_joins(_rels(("[A]]B (Q1)]", "[A]]B (Q2)]")), [], [])
    assert [(j["left_table"], j["right_table"]) for j in joins] == [("Q1", "Q2")]
    assert warnings == []


def test_relationship_to_a_table_the_datasource_lacks_is_dropped_and_reported():
    ds = _rels(("[ID (Q1)]", "[ID (Q9)]"))
    joins, warnings, reviews = _extract_noodle_joins(ds, [{"name": "Q1"}], [])
    assert joins == []
    assert len(warnings) == 1 and "'Q9'" in warnings[0]


def test_cast_key_between_known_tables_joins_on_the_columns_and_says_so():
    ds = _rels(("INT([ID (Q1)])", "INT([ID (Q2)])"))
    joins, warnings, reviews = _extract_noodle_joins(ds, [{"name": "Q1"}, {"name": "Q2"}], [])
    assert [(j["left_table"], j["right_table"], j["keys"]) for j in joins] == [
        ("Q1", "Q2", [{"left": "ID", "right": "ID"}])]
    # A review note, not a skip: the join exists and needs approval before import.
    assert warnings == []
    assert len(reviews) == 1 and "INT()" in reviews[0]
    assert "different rows" in reviews[0] and "review" in reviews[0]


def _rel_xml(cond: str):
    return ET.fromstring(
        "<datasource><object-graph><relationships><relationship>" + cond
        + "</relationship></relationships></object-graph></datasource>")


@pytest.mark.parametrize("cond, op", [
    ("<expression op='AND'><expression op='='><expression op='[ID (Q1)]'/>"
     "<expression op='[ID (Q2)]'/></expression><expression op='='>"
     "<expression op='[K (Q1)]'/><expression op='[K (Q2)]'/></expression></expression>", "AND"),
    ("<expression op='&lt;='><expression op='[ID (Q1)]'/>"
     "<expression op='[ID (Q2)]'/></expression>", "<="),
])
def test_relationship_that_is_not_one_equality_is_skipped_with_a_warning(cond, op):
    joins, warnings, reviews = _extract_noodle_joins(_rel_xml(cond), [], [])
    assert joins == [] and reviews == []
    assert len(warnings) == 1 and repr(op) in warnings[0] and "BL-278" in warnings[0]


def test_plain_relationship_between_known_tables_is_unchanged():
    ds = _rels(("[ID (Q1)]", "[ID (Q2)]"))
    joins, warnings, reviews = _extract_noodle_joins(ds, [{"name": "Q1"}, {"name": "Q2"}], [])
    assert len(joins) == 1 and warnings == []


def test_nothing_to_check_against_drops_nothing():
    ds = _rels(("[ID (Q1)]", "[ID (Q2)]"))
    joins, _, _ = _extract_noodle_joins(ds, [], [])
    assert len(joins) == 1


# --- build-model end to end: two sqlproxy datasources, one map ----------------

def _sqlproxy_ds(caption: str, name: str, cols: list[str]) -> str:
    records = "".join(
        f"<metadata-record class='column'><remote-name>{c}</remote-name>"
        f"<local-name>[{c}]</local-name><parent-name>[sqlproxy]</parent-name>"
        f"<local-type>{'real' if c == 'SALES' else 'string'}</local-type>"
        f"<aggregation>{'Sum' if c == 'SALES' else 'Count'}</aggregation>"
        "</metadata-record>" for c in cols)
    return (
        f"<datasource caption='{caption}' inline='true' name='{name}' version='18.1'>"
        "<connection class='sqlproxy' dbname='x' server='localhost'>"
        "<relation name='sqlproxy' table='[sqlproxy]' type='table'/>"
        f"<metadata-records>{records}</metadata-records></connection>"
        + "".join(f"<column datatype='{'real' if c == 'SALES' else 'string'}' "
                  f"name='[{c}]' role='{'measure' if c == 'SALES' else 'dimension'}' "
                  f"type='{'quantitative' if c == 'SALES' else 'nominal'}'/>" for c in cols)
        + "</datasource>")


def _twb(tmp_path: Path) -> Path:
    twb = tmp_path / "two_published.twb"
    twb.write_text(
        "<?xml version='1.0' encoding='utf-8' ?><workbook version='18.1'><datasources>"
        + _sqlproxy_ds(DS_A, "sqlproxy.aaa", ["ORDER_ID", "SALES"])
        + _sqlproxy_ds(DS_B, "sqlproxy.bbb", ["ORDER_ID", "REGION"])
        + "</datasources></workbook>")
    return twb


def test_build_model_sends_two_sqlproxy_datasources_to_their_own_tables(tmp_path):
    tmap = tmp_path / "map.json"
    tmap.write_text(json.dumps({
        DS_A: {"sqlproxy": {"name": "Orders A", "db_table": "ORDERS_A"}},
        DS_B: {"sqlproxy": "ORDERS_B"},
    }))
    out = tmp_path / "out"
    res = CliRunner().invoke(app, [
        "tableau", "build-model", str(_twb(tmp_path)), "--connection", "CONN",
        "--table-name-map", str(tmap), "--output-dir", str(out)])
    assert res.exit_code == 0, res.stdout + res.stderr

    tables = {}
    for f in out.glob("*.table.tml"):
        t = yaml.safe_load(f.read_text())["table"]
        tables[t["name"]] = t
    assert {n: t["db_table"] for n, t in tables.items()} == {
        "Orders A": "ORDERS_A", "ORDERS_B": "ORDERS_B"}
    assert {c["name"] for c in tables["Orders A"]["columns"]} == {"ORDER_ID", "SALES"}
    assert {c["name"] for c in tables["ORDERS_B"]["columns"]} == {"ORDER_ID", "REGION"}

    for f in out.glob("*.model.tml"):
        model = yaml.safe_load(f.read_text())["model"]
        names = {t["name"] for t in model["model_tables"]}
        assert names in ({"Orders A"}, {"ORDERS_B"})
        assert all(c["column_id"].split("::")[0] in names
                   for c in model["columns"] if "column_id" in c)


def test_build_model_reports_a_datasource_the_map_does_not_cover(tmp_path):
    tmap = tmp_path / "map.json"
    tmap.write_text(json.dumps({DS_A: {"sqlproxy": "ORDERS_A"}}))
    res = CliRunner().invoke(app, [
        "tableau", "build-model", str(_twb(tmp_path)), "--connection", "CONN",
        "--table-name-map", str(tmap), "--output-dir", str(tmp_path / "o"), "--dry-run"])
    assert res.exit_code == 0, res.stdout + res.stderr
    assert "0 of 1 table(s) mapped" in res.stderr


def test_build_model_refuses_a_map_naming_an_unknown_datasource(tmp_path):
    tmap = tmp_path / "map.json"
    tmap.write_text(json.dumps({"orders_c": {"sqlproxy": "ORDERS_C"}}))
    res = CliRunner().invoke(app, [
        "tableau", "build-model", str(_twb(tmp_path)), "--connection", "CONN",
        "--table-name-map", str(tmap), "--output-dir", str(tmp_path / "o"), "--dry-run"])
    assert res.exit_code == 1
    assert "not a datasource in this workbook" in res.stderr


def test_parse_writes_a_dropped_relationship_to_join_warnings(tmp_path):
    rels = ("<object-graph><relationships><relationship><expression op='='>"
            "<expression op='INT([ORDER_ID])'/>"
            "<expression op='INT([ORDER_ID (Custom SQL Query6)])'/>"
            "</expression></relationship></relationships></object-graph>")
    twb = tmp_path / "rel.twb"
    twb.write_text(
        "<?xml version='1.0' encoding='utf-8' ?><workbook version='18.1'><datasources>"
        + _sqlproxy_ds(DS_A, "sqlproxy.aaa", ["ORDER_ID", "SALES"]).replace(
            "</datasource>", rels + "</datasource>")
        + "</datasources></workbook>")
    out = tmp_path / "parsed.json"
    res = CliRunner().invoke(app, ["tableau", "parse", str(twb), "-o", str(out)])
    assert res.exit_code == 0, res.stdout + res.stderr
    ds = json.loads(out.read_text())["datasources"][0]
    assert ds["joins"] == []
    assert any("'Custom SQL Query6'" in str(w) for w in ds["join_warnings"])
    assert ds["join_reviews"] == []


def test_a_join_made_without_its_wrapper_reaches_validation_warnings_as_join_review():
    from ts_cli.tableau.build_model import join_warning_entries
    ds = {"name": "D", "join_warnings": ["skipped x"], "join_reviews": ["joined y"]}
    assert join_warning_entries(ds) == [
        {"kind": "join", "name": "D", "warnings": ["skipped x"]},
        {"kind": "join_review", "name": "D", "warnings": ["joined y"]}]
    assert join_warning_entries({"name": "D"}) == []


# --- one ThoughtSpot table per physical table ---------------------------------

def _two_ds(table_a="sqlproxy", table_b="sqlproxy"):
    return [{"name": DS_A, "tables": [{"name": table_a, "db_table": table_a}]},
            {"name": DS_B, "tables": [{"name": table_b, "db_table": table_b}]}]


@pytest.mark.parametrize("raw", [
    # one display name over two physical tables
    {DS_A: {"sqlproxy": {"name": "Orders", "db_table": "ORDERS_EU"}},
     DS_B: {"sqlproxy": {"name": "Orders", "db_table": "ORDERS_US"}}},
    # two names that slug to one file
    {DS_A: {"sqlproxy": {"name": "Orders A", "db_table": "ORDERS_A"}},
     DS_B: {"sqlproxy": "ORDERS_A_"}},
])
def test_two_physical_tables_under_one_table_name_conflict(raw):
    maps = resolve_table_name_maps(raw, [DS_A, DS_B])
    problems = table_name_map_conflicts(_two_ds(), maps)
    assert len(problems) == 1 and DS_A in problems[0] and DS_B in problems[0]


def test_display_name_equal_to_another_datasources_unmapped_table_conflicts():
    maps = resolve_table_name_maps(
        {DS_A: {"sqlproxy": {"name": "ORDERS", "db_table": "ORDERS_V2"}}}, [DS_A, DS_B])
    assert table_name_map_conflicts(_two_ds(table_b="ORDERS"), maps)


def test_physical_names_differing_only_in_case_conflict():
    # Some warehouses (BigQuery, quoted identifiers) tell orders and ORDERS apart.
    maps = resolve_table_name_maps(
        {DS_A: {"sqlproxy": {"name": "Orders", "db_table": "ORDERS"}},
         DS_B: {"sqlproxy": {"name": "Orders", "db_table": "orders"}}}, [DS_A, DS_B])
    problems = table_name_map_conflicts(_two_ds(), maps)
    assert len(problems) == 1 and "case" in problems[0]


@pytest.mark.parametrize("raw", [
    {DS_A: {"sqlproxy": {"name": "Orders", "db_table": "ORDERS"}},
     DS_B: {"sqlproxy": {"name": "Orders", "db_table": "DB.SCHEMA.ORDERS"}}},  # one table
    {DS_A: {"sqlproxy": "ORDERS_A"}, DS_B: {"sqlproxy": "ORDERS_B"}},
    {DS_A: {"sqlproxy": {"name": "注文", "db_table": "ORDERS_A"}},
     DS_B: {"sqlproxy": {"name": "返品", "db_table": "ORDERS_B"}}},
])
def test_one_name_per_physical_table_is_no_conflict(raw):
    maps = resolve_table_name_maps(raw, [DS_A, DS_B])
    assert table_name_map_conflicts(_two_ds(), maps) == []


def test_bare_map_target_over_a_qualified_parse_table_is_one_table():
    # A published datasource mapped to ORDERS beside a direct one on
    # [ANALYTICS].[PUBLIC].[ORDERS]: the Table TML gets db_table ORDERS for both.
    ds = _two_ds(table_b="ORDERS")
    ds[1]["tables"][0]["db_table"] = "ANALYTICS.PUBLIC.ORDERS"
    maps = resolve_table_name_maps({"sqlproxy": "ORDERS"}, [DS_A, DS_B])
    assert table_name_map_conflicts(ds, maps) == []


def test_non_latin_names_get_distinct_files_and_obj_ids():
    from ts_cli.tableau.build_model import table_file_slug
    from ts_cli.tableau.tables import _slug
    assert table_file_slug("注文") != table_file_slug("返品")
    assert _slug("注文") != _slug("返品")
    assert table_file_slug("Orders A") == "orders_a" and _slug("Orders A") == "orders-a"


def test_unmapped_tables_sharing_a_name_are_not_checked():
    # The existing cross-datasource column merge; the map did not cause it.
    ds = _two_ds()
    ds[1]["tables"][0]["db_table"] = "OTHER"
    assert table_name_map_conflicts(ds, resolve_table_name_maps({}, [DS_A, DS_B])) == []


def test_build_model_refuses_one_display_name_over_two_physical_tables(tmp_path):
    tmap = tmp_path / "map.json"
    tmap.write_text(json.dumps({
        DS_A: {"sqlproxy": {"name": "Orders", "db_table": "ORDERS_EU"}},
        DS_B: {"sqlproxy": {"name": "Orders", "db_table": "ORDERS_US"}},
    }))
    out = tmp_path / "out"
    res = CliRunner().invoke(app, [
        "tableau", "build-model", str(_twb(tmp_path)), "--connection", "CONN",
        "--table-name-map", str(tmap), "--output-dir", str(out)])
    assert res.exit_code == 1
    assert "two physical tables to one ThoughtSpot table (orders.table.tml)" in res.stderr
    assert not list(out.glob("*.tml"))
    # One datasource at a time is refused too: the check reads every datasource.
    res = CliRunner().invoke(app, [
        "tableau", "build-model", str(_twb(tmp_path)), "--connection", "CONN",
        "--table-name-map", str(tmap), "--output-dir", str(out), "--datasource", DS_A])
    assert res.exit_code == 1 and not list(out.glob("*.tml"))


# --- ts tableau verify reads the map -------------------------------------------

def _parsed_one(table="sqlproxy"):
    return {"datasources": [{"name": DS_A, "tables": [{"name": table, "db_table": table}],
                             "columns": [], "joins": [], "calculated_fields": []}]}


def _model(*names):
    return {"model": {"name": "orders_a", "model_tables": [{"name": n} for n in names],
                      "columns": [], "formulas": []}}


def _table_errors(report):
    structural = next(c for c in report["checks"] if c["name"] == "structural")
    return [f["message"] for f in structural["findings"] if f["severity"] == "ERROR"]


def test_verify_reads_a_mapped_table_as_renamed_not_dropped():
    maps = resolve_table_name_maps(
        {DS_A: {"sqlproxy": {"name": "Orders A", "db_table": "ORDERS_A"}}}, [DS_A])
    assert any("sqlproxy" in m for m in _table_errors(
        verify_conversion(_parsed_one(), _model("Orders A"))))
    assert not _table_errors(verify_conversion(_parsed_one(), _model("Orders A"), name_maps=maps))


def test_verify_with_a_map_still_fires_on_a_genuine_drop():
    maps = resolve_table_name_maps(
        {DS_A: {"sqlproxy": {"name": "Orders A", "db_table": "ORDERS_A"}}}, [DS_A])
    errors = _table_errors(verify_conversion(_parsed_one(), _model("Something Else"), name_maps=maps))
    assert any("Orders A" in m for m in errors)


def test_verify_cli_accepts_the_table_name_map(tmp_path):
    parsed = tmp_path / "parsed.json"
    parsed.write_text(json.dumps(_parsed_one()))
    model = tmp_path / "m.model.tml"
    model.write_text(yaml.safe_dump(_model("Orders A")))
    tmap = tmp_path / "map.json"
    tmap.write_text(json.dumps({DS_A: {"sqlproxy": {"name": "Orders A", "db_table": "ORDERS_A"}}}))
    args = ["tableau", "verify", "--parse", str(parsed), "--model", str(model)]
    assert CliRunner().invoke(app, args).exit_code == 1
    res = CliRunner().invoke(app, args + ["--table-name-map", str(tmap)])
    assert res.exit_code == 0, res.stdout + res.stderr
    assert "dropped" not in res.stdout
