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
    table_name_map_for,
)
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
    # The published-datasource shape: the base side is bare, so no join.
    # The cast form used to read as column INT on a table named [ORDER_ID].
    ds = _rels(("INT([ORDER_ID])", "INT([ORDER_ID (Custom SQL Query6)])"),
               ("[ORDER_ID]", "[ORDER_ID (Custom SQL Query2)]"))
    joins, warnings = _extract_noodle_joins(ds, [], [{"name": "sqlproxy"}])
    assert joins == [] and warnings == []


def test_relationship_to_a_table_the_datasource_lacks_is_dropped_and_reported():
    ds = _rels(("[ID (Q1)]", "[ID (Q9)]"))
    joins, warnings = _extract_noodle_joins(ds, [{"name": "Q1"}], [])
    assert joins == []
    assert len(warnings) == 1 and "'Q9'" in warnings[0]


def test_cast_key_between_known_tables_joins_on_the_columns_and_says_so():
    ds = _rels(("INT([ID (Q1)])", "INT([ID (Q2)])"))
    joins, warnings = _extract_noodle_joins(ds, [{"name": "Q1"}, {"name": "Q2"}], [])
    assert [(j["left_table"], j["right_table"], j["keys"]) for j in joins] == [
        ("Q1", "Q2", [{"left": "ID", "right": "ID"}])]
    assert len(warnings) == 1 and "INT()" in warnings[0]


def test_plain_relationship_between_known_tables_is_unchanged():
    ds = _rels(("[ID (Q1)]", "[ID (Q2)]"))
    joins, warnings = _extract_noodle_joins(ds, [{"name": "Q1"}, {"name": "Q2"}], [])
    assert len(joins) == 1 and warnings == []


def test_nothing_to_check_against_drops_nothing():
    ds = _rels(("[ID (Q1)]", "[ID (Q2)]"))
    joins, _ = _extract_noodle_joins(ds, [], [])
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
