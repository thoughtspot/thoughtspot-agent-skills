# tools/ts-cli/tests/test_csq_warehouse_binding.py
"""`--warehouse-columns`: keep `(Custom SQL Query N)` columns the target table has.

A published datasource that joins several Custom SQL queries server-side
disambiguates a repeated column with a suffix, so `LEVEL` and
`LEVEL (Custom SQL Query8)` are two columns with different data. When the
datasource is landed as one flattened table that keeps both names, stripping the
suffix collapses them and every formula reading the suffixed one silently reads
`LEVEL` instead. These tests pin:

- the default (no warehouse columns) is unchanged: strip and dedupe;
- with warehouse columns, a suffixed column present verbatim stays distinct and
  formula refs keep pointing at it;
- a suffixed ref the warehouse does NOT have is still stripped and still warned
  about, so the gate keeps firing for a genuine missing column.
"""
from __future__ import annotations

import json

import pytest
import yaml

from ts_cli.cli import app
from ts_cli.tableau.build_model import (
    collect_existing_model_context,
    live_suffixed_columns,
    parse_warehouse_columns,
    prepare_formulas_for_merge,
    strip_csq_suffixes,
    warehouse_columns_for,
)
from ts_cli.tableau.reconcile import (
    bound_suffixed_columns,
    clean_columns,
    has_unbound_suffixed_ref,
    strip_suffix_in_expr,
)
from ts_cli.tableau.validate import validate_pre_import

from runners import runner  # noqa: E402  (BL-139: one definition, see runners.py)

LEVEL8 = "LEVEL (Custom SQL Query8)"
SALES8 = "SALES (Custom SQL Query8)"


def _cols(*names):
    return [{"name": n, "db_column_name": n, "column_type": "ATTRIBUTE"} for n in names]


# --- bound_suffixed_columns -------------------------------------------------

def test_bound_only_suffixed_columns_present_in_warehouse():
    cols = _cols("LEVEL", LEVEL8, SALES8)
    bound = bound_suffixed_columns(cols, {"LEVEL", LEVEL8})
    assert bound == {LEVEL8.upper()}  # SALES8 absent from warehouse; LEVEL not suffixed


def test_bound_is_case_insensitive():
    bound = bound_suffixed_columns(_cols(LEVEL8), {LEVEL8.lower()})
    assert bound == {LEVEL8.upper()}


@pytest.mark.parametrize("wh", [None, set()])
def test_bound_empty_without_warehouse(wh):
    assert bound_suffixed_columns(_cols(LEVEL8), wh) == set()


# --- clean_columns ----------------------------------------------------------

def test_clean_columns_default_still_collapses_suffix():
    out = clean_columns(_cols("LEVEL", LEVEL8), "T")
    assert [c["db_column_name"] for c in out] == ["LEVEL"]


def test_clean_columns_keeps_bound_suffixed_column_distinct():
    out = clean_columns(_cols("LEVEL", LEVEL8, SALES8), "T", {LEVEL8.upper()})
    assert [c["db_column_name"] for c in out] == ["LEVEL", LEVEL8, "SALES"]
    kept = out[1]
    assert kept["name"] == LEVEL8 and kept["table"] == "T"


def test_clean_columns_two_queries_same_base_both_kept():
    # CUSTOMER_TYPE exists twice, from Query2 and Query5: binding keeps both,
    # so nothing has to guess which one the unsuffixed name meant.
    q2, q5 = "CUSTOMER_TYPE (Custom SQL Query2)", "CUSTOMER_TYPE (Custom SQL Query5)"
    out = clean_columns(_cols(q2, q5), "T", {q2.upper(), q5.upper()})
    assert [c["db_column_name"] for c in out] == [q2, q5]


# --- strip_suffix_in_expr / has_unbound_suffixed_ref -----------------------

def test_strip_default_unchanged():
    expr = f"[T::{LEVEL8}] = 'x' and [{SALES8}] > 0"
    assert strip_suffix_in_expr(expr) == "[T::LEVEL] = 'x' and [SALES] > 0"
    assert strip_suffix_in_expr(expr, set()) == strip_suffix_in_expr(expr)


def test_strip_keeps_bound_refs_qualified_and_bare():
    bound = {LEVEL8.upper()}
    expr = f"[T::{LEVEL8}] = 'x' and [{LEVEL8}] <> '' and [{SALES8}] > 0"
    assert strip_suffix_in_expr(expr, bound) == (
        f"[T::{LEVEL8}] = 'x' and [{LEVEL8}] <> '' and [SALES] > 0"
    )


def test_has_unbound_suffixed_ref():
    bound = {LEVEL8.upper()}
    assert has_unbound_suffixed_ref(f"[T::{LEVEL8}]") is True        # no binding: old test
    assert has_unbound_suffixed_ref(f"[T::{LEVEL8}]", bound) is False
    assert has_unbound_suffixed_ref(f"[T::{LEVEL8}] + [{SALES8}]", bound) is True


# --- validate_pre_import: the gate still fires for a genuine missing column --

def _warnings(expr, bound=None):
    issues = validate_pre_import([{"name": "F", "expr": expr}], {"LEVEL"}, {"F"}, bound)
    return [w for i in issues for w in i["warnings"]]


def test_validate_silent_for_bound_suffixed_ref():
    assert "Unresolved Custom SQL Query alias" not in _warnings(
        f"if ( [T::{LEVEL8}] = 'x' ) then 1 else 0", {LEVEL8.upper()},
    )


def test_validate_still_fires_for_unbound_suffixed_ref():
    assert "Unresolved Custom SQL Query alias" in _warnings(
        f"if ( [T::{SALES8}] > 0 ) then 1 else 0", {LEVEL8.upper()},
    )


# --- parse_warehouse_columns / warehouse_columns_for -----------------------

def test_parse_warehouse_columns_shapes():
    assert parse_warehouse_columns(["A", LEVEL8]) == {"": {"A", LEVEL8}}
    assert parse_warehouse_columns({"columns": [{"name": "A"}, {"name": "B", "type_name": "INT"}]}) == {"": {"A", "B"}}
    assert parse_warehouse_columns({"t1": ["A"], "t2": [{"name": "B"}]}) == {"t1": {"A"}, "t2": {"B"}}


@pytest.mark.parametrize("bad", ["x", 3, {"t": "A"}, [1], [{"nam": "A"}]])
def test_parse_warehouse_columns_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_warehouse_columns(bad)


def test_warehouse_columns_for_prefers_table_then_unkeyed():
    wh = {"t1": {"A"}, "": {"Z"}}
    assert warehouse_columns_for(wh, "t1") == {"A"}
    assert warehouse_columns_for(wh, "other") == {"Z"}
    assert warehouse_columns_for({}, "t1") == set()


# --- merge mode reads the binding off the live model ------------------------

def test_strip_csq_suffixes_keep():
    formulas = [{"name": "A", "expr": f"[T::{LEVEL8}] + [{SALES8}]"}]
    assert strip_csq_suffixes(formulas, {LEVEL8}) == 1
    assert formulas[0]["expr"] == f"[T::{LEVEL8}] + [SALES]"


def test_merge_keeps_suffix_when_model_has_the_column():
    existing = {"model": {
        "model_tables": [{"name": "T"}],
        "columns": [
            {"name": "LEVEL", "column_id": "T::LEVEL"},
            {"name": LEVEL8, "column_id": f"T::{LEVEL8}"},
        ],
        "formulas": [], "parameters": [],
    }}
    ctx = collect_existing_model_context(existing)
    formulas = [{"name": "F", "expr": f"if ( [T::{LEVEL8}] = 'x' ) then 1 else 0"}]
    dicts, _ = prepare_formulas_for_merge(formulas, ctx)
    assert f"[T::{LEVEL8}]" in dicts[0]["expr"]


def test_merge_still_strips_when_model_lacks_the_column():
    existing = {"model": {
        "model_tables": [{"name": "T"}],
        "columns": [{"name": "LEVEL", "column_id": "T::LEVEL"}],
        "formulas": [], "parameters": [],
    }}
    ctx = collect_existing_model_context(existing)
    formulas = [{"name": "F", "expr": f"if ( [T::{LEVEL8}] = 'x' ) then 1 else 0"}]
    dicts, _ = prepare_formulas_for_merge(formulas, ctx)
    assert "Custom SQL Query" not in dicts[0]["expr"]
    assert "[T::LEVEL]" in dicts[0]["expr"]


def test_live_suffixed_columns_reads_the_models_suffixed_columns():
    existing = {"model": {
        "model_tables": [{"name": "T"}],
        "columns": [
            {"name": "LEVEL", "column_id": "T::LEVEL"},
            {"name": LEVEL8, "column_id": f"T::{LEVEL8}"},
            {"name": "Sales", "formula_id": "formula_Sales"},
        ],
        "formulas": [], "parameters": [],
    }}
    assert live_suffixed_columns(existing) == {LEVEL8.upper()}


def test_merge_mode_validation_silent_for_live_suffixed_column():
    # merge mode passes the live model's suffixed columns as the bound set,
    # so a ref to one is not an unresolved alias; an absent one still is
    existing = {"model": {
        "model_tables": [{"name": "T"}],
        "columns": [{"name": LEVEL8, "column_id": f"T::{LEVEL8}"}],
        "formulas": [], "parameters": [],
    }}
    bound = live_suffixed_columns(existing)
    assert not has_unbound_suffixed_ref(f"[T::{LEVEL8}] = 'x'", bound)
    assert has_unbound_suffixed_ref(f"[T::{SALES8}] > 0", bound)


# --- end to end through `ts tableau build-model` ----------------------------

TWB = f"""<?xml version='1.0'?>
<workbook>
  <datasource name='federated.a' caption='Orders'>
    <relation name='ORDERS' type='table' table='[db].[s].[ORDERS]'/>
    <column name='[LEVEL]' datatype='string' role='dimension'/>
    <column name='[{LEVEL8}]' datatype='string' role='dimension'/>
    <column name='[SALES]' datatype='real' role='measure'/>
    <column name='[Is Campaign]' datatype='integer' role='measure' caption='Is Campaign'>
      <calculation class='tableau' formula="IF [{LEVEL8}] = 'campaign' THEN 1 ELSE 0 END"/>
    </column>
  </datasource>
</workbook>
"""


def _build(tmp_path, extra):
    twb = tmp_path / "wb.twb"
    twb.write_text(TWB)
    out = tmp_path / "out"
    out.mkdir()
    res = runner.invoke(
        app,
        ["tableau", "build-model", str(twb), "--connection", "CONN",
         "--output-dir", str(out), *extra],
    )
    assert res.exit_code == 0, res.stdout + res.stderr
    table = yaml.safe_load(next(out.glob("*.table.tml")).read_text())["table"]
    model_file = next(p for p in out.glob("*.model.tml") if ".phase0." not in p.name)
    model = yaml.safe_load(model_file.read_text())["model"]
    return out, table, model


def test_build_model_default_collapses_suffixed_column(tmp_path):
    _, table, model = _build(tmp_path, [])
    assert sorted(c["db_column_name"] for c in table["columns"]) == ["LEVEL", "SALES"]
    expr = next(f["expr"] for f in model["formulas"] if f["name"] == "Is Campaign")
    assert "Custom SQL Query" not in expr


def test_build_model_with_warehouse_columns_binds_suffixed_column(tmp_path):
    wh = tmp_path / "wh.json"
    wh.write_text(json.dumps({"ORDERS": ["LEVEL", LEVEL8, "SALES"]}))
    out, table, model = _build(tmp_path, ["--warehouse-columns", str(wh)])
    assert sorted(c["db_column_name"] for c in table["columns"]) == ["LEVEL", LEVEL8, "SALES"]
    expr = next(f["expr"] for f in model["formulas"] if f["name"] == "Is Campaign")
    assert LEVEL8 in expr
    lint = runner.invoke(app, ["tml", "lint", "--dir", str(out)])
    assert json.loads(lint.stdout)["clean"] is True, lint.stdout


def test_build_model_rejects_malformed_warehouse_columns(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(TWB)
    wh = tmp_path / "wh.json"
    wh.write_text(json.dumps({"ORDERS": "LEVEL"}))
    res = runner.invoke(
        app,
        ["tableau", "build-model", str(twb), "--connection", "CONN",
         "--output-dir", str(tmp_path / "o"), "--warehouse-columns", str(wh)],
    )
    assert res.exit_code == 1


# --- review round: equal captions, wiring branches, sqlproxy + name map -----

def test_clean_columns_bound_column_sharing_a_caption_takes_its_own_name():
    # Tableau lets LEVEL and LEVEL (Custom SQL Query8) share the caption
    # "Level"; two equal names would collapse both Table columns onto one
    # warehouse column, so the bound one is named by its full suffixed name.
    for order in ((0, 1), (1, 0)):
        cols = [
            {"name": "Level", "db_column_name": "LEVEL", "column_type": "ATTRIBUTE"},
            {"name": "Level", "db_column_name": LEVEL8, "column_type": "ATTRIBUTE"},
        ]
        out = clean_columns([cols[i] for i in order], "ORDERS", {LEVEL8.upper()})
        by_db = {c["db_column_name"]: c["name"] for c in out}
        assert by_db == {"LEVEL": "Level", LEVEL8: LEVEL8}


def test_clean_columns_bound_column_keeps_a_distinct_caption():
    cols = [
        {"name": "Level", "db_column_name": "LEVEL", "column_type": "ATTRIBUTE"},
        {"name": "Level 8", "db_column_name": LEVEL8, "column_type": "ATTRIBUTE"},
    ]
    out = clean_columns(cols, "ORDERS", {LEVEL8.upper()})
    assert {c["db_column_name"]: c["name"] for c in out} == {"LEVEL": "Level", LEVEL8: "Level 8"}


def _ds(tables, cols):
    return {"tables": [{"name": t} for t in tables], "columns": _cols(*cols)}


def test_resolve_bound_merge_mode_reads_the_live_model():
    from ts_cli.tableau.build_model import resolve_bound_suffixed
    existing = {"model": {
        "model_tables": [{"name": "T"}],
        "columns": [{"name": LEVEL8, "column_id": f"T::{LEVEL8}"}],
        "formulas": [], "parameters": [],
    }}
    # merge mode ignores the warehouse list and reads the model
    bound, msg = resolve_bound_suffixed(_ds(["T"], ["LEVEL", SALES8]), {"T": [SALES8]}, existing)
    assert bound == {LEVEL8.upper()} and msg is None


def test_resolve_bound_multi_table_datasource_binds_nothing():
    from ts_cli.tableau.build_model import resolve_bound_suffixed
    bound, msg = resolve_bound_suffixed(
        _ds(["A", "B"], ["LEVEL", LEVEL8]), {"": ["LEVEL", LEVEL8]}, None)
    assert bound == set() and msg is None


def test_resolve_bound_single_table_binds_and_reports():
    from ts_cli.tableau.build_model import resolve_bound_suffixed
    bound, msg = resolve_bound_suffixed(
        _ds(["T"], ["LEVEL", LEVEL8]), {"T": ["LEVEL", LEVEL8]}, None)
    assert bound == {LEVEL8.upper()}
    assert "1 suffixed column(s) kept" in msg and "of T" in msg


def test_resolve_bound_key_miss_binds_nothing():
    from ts_cli.tableau.build_model import resolve_bound_suffixed
    bound, msg = resolve_bound_suffixed(
        _ds(["T"], ["LEVEL", LEVEL8]), {"OTHER": ["LEVEL", LEVEL8]}, None)
    assert bound == set() and "0 suffixed column(s) kept" in msg


def test_warehouse_columns_ignored_with_existing_guid(tmp_path):
    from ts_cli.commands.tableau import _load_warehouse_columns
    wh = tmp_path / "wh.json"
    wh.write_text(json.dumps({"ORDERS": ["LEVEL", LEVEL8]}))
    assert _load_warehouse_columns(str(wh), "some-guid") == {}
    assert _load_warehouse_columns(str(wh), None) == {"ORDERS": {"LEVEL", LEVEL8}}


def test_build_model_equal_captions_stay_two_columns_and_lint_clean(tmp_path):
    twb = tmp_path / "wb.twb"
    twb.write_text(TWB.replace(
        "<column name='[LEVEL]' datatype='string' role='dimension'/>",
        "<column name='[LEVEL]' datatype='string' role='dimension' caption='Level'/>",
    ).replace(
        f"<column name='[{LEVEL8}]' datatype='string' role='dimension'/>",
        f"<column name='[{LEVEL8}]' datatype='string' role='dimension' caption='Level'/>",
    ))
    wh = tmp_path / "wh.json"
    wh.write_text(json.dumps({"ORDERS": ["LEVEL", LEVEL8, "SALES"]}))
    out = tmp_path / "out"
    res = runner.invoke(app, ["tableau", "build-model", str(twb), "--connection", "CONN",
                              "--output-dir", str(out), "--warehouse-columns", str(wh)])
    assert res.exit_code == 0, res.stdout + res.stderr
    table = yaml.safe_load(next(out.glob("*.table.tml")).read_text())["table"]
    assert sorted(c["db_column_name"] for c in table["columns"]) == ["LEVEL", LEVEL8, "SALES"]
    assert len({c["name"] for c in table["columns"]}) == 3
    lint = runner.invoke(app, ["tml", "lint", "--dir", str(out)])
    assert json.loads(lint.stdout)["clean"] is True, lint.stdout


SQLPROXY_TWB = f"""<?xml version='1.0'?>
<workbook>
  <datasource name='sqlproxy.a' caption='Campaigns'>
    <connection class='sqlproxy' dbname='Campaigns'>
      <relation name='sqlproxy' type='table' table='[sqlproxy]'/>
      <metadata-records>
        <metadata-record class='column'>
          <remote-name>LEVEL</remote-name><local-name>[LEVEL]</local-name>
          <parent-name>[sqlproxy]</parent-name><local-type>string</local-type>
        </metadata-record>
        <metadata-record class='column'>
          <remote-name>{LEVEL8}</remote-name><local-name>[{LEVEL8}]</local-name>
          <parent-name>[sqlproxy]</parent-name><local-type>string</local-type>
        </metadata-record>
        <metadata-record class='column'>
          <remote-name>SALES</remote-name><local-name>[SALES]</local-name>
          <parent-name>[sqlproxy]</parent-name><local-type>real</local-type>
        </metadata-record>
      </metadata-records>
    </connection>
    <column name='[LEVEL]' datatype='string' role='dimension'/>
    <column name='[{LEVEL8}]' datatype='string' role='dimension'/>
    <column name='[SALES]' datatype='real' role='measure'/>
    <column name='[Is Campaign]' datatype='integer' role='measure' caption='Is Campaign'>
      <calculation class='tableau' formula="IF [{LEVEL8}] = 'campaign' THEN 1 ELSE 0 END"/>
    </column>
  </datasource>
</workbook>
"""


@pytest.mark.parametrize("key,bound", [("CAMPAIGN_FLAT", True), ("sqlproxy", False)])
def test_build_model_sqlproxy_keyed_by_mapped_table_name(tmp_path, key, bound):
    # the warehouse file is keyed by the table name AFTER --table-name-map;
    # the pre-map name binds nothing and the ref is stripped and warned
    twb = tmp_path / "wb.twb"
    twb.write_text(SQLPROXY_TWB)
    name_map = tmp_path / "map.json"
    name_map.write_text(json.dumps({"sqlproxy": "CAMPAIGN_FLAT"}))
    wh = tmp_path / "wh.json"
    wh.write_text(json.dumps({key: ["LEVEL", LEVEL8, "SALES"]}))
    out = tmp_path / "out"
    res = runner.invoke(app, ["tableau", "build-model", str(twb), "--connection", "CONN",
                              "--output-dir", str(out), "--table-name-map", str(name_map),
                              "--warehouse-columns", str(wh)])
    assert res.exit_code == 0, res.stdout + res.stderr
    table = yaml.safe_load(next(out.glob("*.table.tml")).read_text())["table"]
    model_file = next(p for p in out.glob("*.model.tml") if ".phase0." not in p.name)
    model = yaml.safe_load(model_file.read_text())["model"]
    expr = next(f["expr"] for f in model["formulas"] if f["name"] == "Is Campaign")
    dbs = sorted(c["db_column_name"] for c in table["columns"])
    if bound:
        assert table["name"] == "CAMPAIGN_FLAT"
        assert dbs == ["LEVEL", LEVEL8, "SALES"]
        assert f"[CAMPAIGN_FLAT::{LEVEL8}]" in expr
        assert "Validation warnings" not in res.stderr
        lint = runner.invoke(app, ["tml", "lint", "--dir", str(out)])
        assert json.loads(lint.stdout)["clean"] is True, lint.stdout
    else:
        assert dbs == ["LEVEL", "SALES"]
        assert "Custom SQL Query" not in expr
        assert "Validation warnings" in res.stderr
