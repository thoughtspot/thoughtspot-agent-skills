"""Cross-datasource SQL View name disambiguation (SCAL-339750).

Tableau names an unnamed Custom SQL relation ``Custom SQL Query`` and only
guarantees that name is unique WITHIN a datasource. ``build-model`` emits every
datasource of a workbook into one output directory and one ThoughtSpot
namespace, so before this fix N datasources each produced a SQL View document
named ``Custom SQL Query`` and every model pointed at an ambiguous object.

These tests pin both halves: that colliding names are disambiguated, and that
the rename reaches every reference (``model_tables[].name``, ``column_id``,
join ``with``/``on``, formula expressions, and the SQL View TML itself).
"""
from ts_cli.model_builder import (
    _resolve_sqlview_refs,
    build_model_tml,
    build_sql_view_tml,
)
from ts_cli.tableau.build_model import disambiguate_sql_view_names


def _sql_view(name, columns, sql="SELECT 1"):
    """A ``columns`` entry is a physical name, or a ``(caption, physical)`` pair when
    the two differ — Tableau captions a column ``COL (Relation)`` where the same
    physical column is exposed by more than one Custom SQL query."""
    cols = []
    for c in columns:
        caption, phys = c if isinstance(c, tuple) else (c, c.lower())
        cols.append({"name": caption, "sql_output_column": phys,
                     "column_type": "ATTRIBUTE", "data_type": "VARCHAR"})
    return {"name": name, "sql_query": sql, "columns": cols}


def _ds(name, *, sql_views=(), tables=(), joins=(), columns=(), col_table_map=None):
    return {
        "name": name,
        "tables": [{"name": t} for t in tables],
        "sql_views": list(sql_views),
        "joins": [dict(j) for j in joins],
        "columns": [dict(c) for c in columns],
        "col_table_map": dict(col_table_map or {}),
        "calculated_fields": [],
        "calc_map": {},
        "sets": [],
    }


def _view_names(datasources):
    return [sv["name"] for ds in datasources for sv in ds["sql_views"]]


# ── 1. Two datasources, one Custom SQL Query each ──────────────────────────

def test_two_datasources_colliding_sql_view_names():
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["A"])]),
        _ds("DS2", sql_views=[_sql_view("Custom SQL Query", ["B"])]),
    ]
    disambiguate_sql_view_names(dss)
    # EVERY owner of a contested name is qualified — no owner keeps the bare
    # name, so neither name depends on which datasource came first.
    assert _view_names(dss) == ["Custom SQL Query (DS1)", "Custom SQL Query (DS2)"]


# ── 2. Three or more colliding views — every emitted name unique ───────────

def test_three_or_more_colliding_views_all_unique():
    dss = [
        _ds(f"DS{i}", sql_views=[_sql_view("Custom SQL Query", [f"C{i}"])])
        for i in range(1, 6)
    ]
    disambiguate_sql_view_names(dss)
    names = _view_names(dss)
    assert names == [
        "Custom SQL Query (DS1)",
        "Custom SQL Query (DS2)",
        "Custom SQL Query (DS3)",
        "Custom SQL Query (DS4)",
        "Custom SQL Query (DS5)",
    ]
    assert len(set(names)) == len(names)


def test_qualified_name_itself_colliding_gets_ordinal():
    # A datasource literally named so that "Base (DS2)" is already taken by a
    # real view — the ordinal fallback must kick in rather than collide again.
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["A"])]),
        _ds("DS2", sql_views=[_sql_view("Custom SQL Query", ["B"]),
                              _sql_view("Custom SQL Query (DS2)", ["C"])]),
    ]
    disambiguate_sql_view_names(dss)
    names = _view_names(dss)
    assert names == [
        "Custom SQL Query (DS1)",
        "Custom SQL Query (DS2 2)",   # "(DS2)" already belongs to a real view
        "Custom SQL Query (DS2)",
    ]
    assert len(set(names)) == len(names)


# ── 3/4. model_tables[].name and column_id follow the rename ───────────────

def test_model_tables_and_column_id_follow_rename():
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["Alpha"])]),
        _ds("DS2", sql_views=[_sql_view("Custom SQL Query", ["Beta"])]),
    ]
    disambiguate_sql_view_names(dss)
    renamed = dss[1]["sql_views"]

    model = build_model_tml(
        model_name="M2", connection_name="CONN", tables=[], columns=[], joins=[],
        parameters=[], translated_formulas=[], sql_views=renamed,
    )["model"]

    assert [t["name"] for t in model["model_tables"]] == ["Custom SQL Query (DS2)"]
    assert [c["column_id"] for c in model["columns"]] == ["Custom SQL Query (DS2)::Beta"]
    # the SQL View TML the model points at carries the same name
    sv_tml = build_sql_view_tml(
        name=renamed[0]["name"], connection_name="CONN",
        sql_query=renamed[0]["sql_query"], columns=renamed[0]["columns"],
    )
    assert sv_tml["sql_view"]["name"] == "Custom SQL Query (DS2)"
    # ...and the other owner is qualified by ITS datasource, not left bare
    assert dss[0]["sql_views"][0]["name"] == "Custom SQL Query (DS1)"


# ── 5. Join `with` and `on` references follow the rename ───────────────────

def test_join_with_and_on_follow_rename():
    views = [_sql_view("Custom SQL Query", ["Id"]), _sql_view("Other View", ["Id"])]
    joins = [{"left_table": "Custom SQL Query", "right_table": "Other View",
              "type": "INNER", "cardinality": "MANY_TO_ONE",
              "keys": [{"left": "Id", "right": "Id"}]}]
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["Id"])]),
        _ds("DS2", sql_views=views, joins=joins),
    ]
    disambiguate_sql_view_names(dss)

    j = dss[1]["joins"][0]
    assert j["left_table"] == "Custom SQL Query (DS2)"
    assert j["right_table"] == "Other View"          # no collision — untouched

    model = build_model_tml(
        model_name="M", connection_name="CONN", tables=[], columns=[], joins=dss[1]["joins"],
        parameters=[], translated_formulas=[], sql_views=dss[1]["sql_views"],
    )["model"]
    mt = {t["name"]: t for t in model["model_tables"]}
    assert "Custom SQL Query (DS2)" in mt
    join = mt["Custom SQL Query (DS2)"]["joins"][0]
    assert join["with"] == "Other View"
    assert join["on"] == "[Custom SQL Query (DS2)::Id] = [Other View::Id]"


# ── 6. Formula expressions follow the rename ───────────────────────────────

def test_col_table_map_rename_drives_formula_refs():
    # The formula translator builds [Table::Column] refs from col_table_map, so
    # renaming that map is what makes translated formulas land on the new name.
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["Sales"])]),
        _ds("DS2",
            sql_views=[_sql_view("Custom SQL Query", ["Sales"])],
            col_table_map={"Sales": "Custom SQL Query", "Other": "Real Table"},
            columns=[{"name": "Sales", "table": "Custom SQL Query"}]),
    ]
    disambiguate_sql_view_names(dss)

    assert dss[1]["col_table_map"] == {"Sales": "Custom SQL Query (DS2)", "Other": "Real Table"}
    assert dss[1]["columns"][0]["table"] == "Custom SQL Query (DS2)"
    # DS1 kept the bare name, so its map must be untouched
    assert dss[0]["col_table_map"] == {}


def test_formula_expr_resolves_against_renamed_view():
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["Sales"])]),
        _ds("DS2", sql_views=[_sql_view("Custom SQL Query", ["Sales"])]),
    ]
    disambiguate_sql_view_names(dss)
    renamed = dss[1]["sql_views"][0]["name"]

    model = build_model_tml(
        model_name="M", connection_name="CONN", tables=[], columns=[], joins=[],
        parameters=[],
        translated_formulas=[{"name": "Total", "expr": f"sum ( [{renamed}::Sales] )"}],
        sql_views=dss[1]["sql_views"],
    )["model"]

    expr = model["formulas"][0]["expr"]
    assert expr == "sum ( [Custom SQL Query (DS2)::Sales] )"
    # the referenced column_id actually exists on the renamed view
    assert f"{renamed}::Sales" in {c.get("column_id") for c in model["columns"]}


def test_formula_ref_resolves_when_caption_carries_the_pre_rename_relation():
    """A column captioned against the relation name — ``BEHAVIOR (Custom SQL Query2)``
    — must still resolve after the view is renamed. The caption records the name the
    column was collided against and does not follow the rename, so the emitted
    ``formulas[].expr`` ref and the emitted ``column_id`` have to be reconciled through
    the view's ``sql_output_column``, not through its current name."""
    dss = [
        _ds("Marketing", sql_views=[_sql_view("Custom SQL Query2", ["A"])]),
        _ds("Sales", sql_views=[
            _sql_view("Custom SQL Query2", [("BEHAVIOR (Custom SQL Query2)", "BEHAVIOR")])]),
    ]
    disambiguate_sql_view_names(dss)
    renamed = dss[1]["sql_views"][0]["name"]
    assert renamed == "Custom SQL Query2 (Sales)"

    model = build_model_tml(
        model_name="M", connection_name="CONN", tables=[], columns=[], joins=[],
        parameters=[],
        translated_formulas=[{"name": "Total", "expr": f"sum ( [{renamed}::BEHAVIOR] )"}],
        sql_views=dss[1]["sql_views"],
    )["model"]

    expr = model["formulas"][0]["expr"]
    column_ids = {c.get("column_id") for c in model["columns"]}
    assert expr == f"sum ( [{renamed}::BEHAVIOR (Custom SQL Query2)] )"
    assert expr[expr.index("[") + 1:expr.index("]")] in column_ids


def test_resolve_sqlview_refs_leaves_unresolvable_refs_alone():
    sv = _sql_view("V (DS)", [("BEHAVIOR (Custom SQL Query2)", "BEHAVIOR")])
    views = {sv["name"]: sv}
    # unknown view — untouched
    assert _resolve_sqlview_refs("[Other::BEHAVIOR]", views) == "[Other::BEHAVIOR]"
    # unknown column — untouched
    assert _resolve_sqlview_refs("[V (DS)::NOPE]", views) == "[V (DS)::NOPE]"
    # already the view's own column name — untouched
    ref = "[V (DS)::BEHAVIOR (Custom SQL Query2)]"
    assert _resolve_sqlview_refs(ref, views) == ref


# ── 7. Existing distinct names remain unchanged ────────────────────────────

def test_distinct_tableau_numbered_names_unchanged():
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["A"])]),
        _ds("DS2", sql_views=[_sql_view("Custom SQL Query1", ["B"])]),
        _ds("DS3", sql_views=[_sql_view("Custom SQL Query2", ["C"])]),
    ]
    disambiguate_sql_view_names(dss)
    assert _view_names(dss) == ["Custom SQL Query", "Custom SQL Query1", "Custom SQL Query2"]


# ── 8. Several views inside ONE datasource are untouched ───────────────────

def test_multiple_views_in_one_datasource_unchanged():
    dss = [_ds("DS1", sql_views=[
        _sql_view("Custom SQL Query", ["A"]),
        _sql_view("Custom SQL Query1", ["B"]),
        _sql_view("Custom SQL Query2", ["C"]),
    ])]
    disambiguate_sql_view_names(dss)
    assert _view_names(dss) == ["Custom SQL Query", "Custom SQL Query1", "Custom SQL Query2"]


def test_single_datasource_workbook_unchanged():
    dss = [_ds("Only", sql_views=[_sql_view("Custom SQL Query", ["A"])], tables=["Orders"])]
    disambiguate_sql_view_names(dss)
    assert _view_names(dss) == ["Custom SQL Query"]
    assert [t["name"] for t in dss[0]["tables"]] == ["Orders"]


# ── 9. SQL View colliding with a physical table ────────────────────────────

def test_sql_view_colliding_with_physical_table_renames_the_view():
    # Real shape from `Sales Performance (2).twb`: one datasource's SQL View is
    # called "Orders" and another datasource has a PHYSICAL table "Orders".
    dss = [
        _ds("SUPERSTORE SALES", sql_views=[_sql_view("Orders", ["Id"])],
            tables=["Returns.csv", "Users"]),
        _ds("Superstore Sales", tables=["Returns", "Orders", "Users"]),
    ]
    disambiguate_sql_view_names(dss)

    # the physical table keeps its name — it must match the warehouse object
    assert [t["name"] for t in dss[1]["tables"]] == ["Returns", "Orders", "Users"]
    # ...and the view is renamed even though only ONE datasource declares it
    assert _view_names(dss) == ["Orders (SUPERSTORE SALES)"]


def test_physical_table_collision_renames_every_owner():
    dss = [
        _ds("DS1", sql_views=[_sql_view("Orders", ["A"])]),
        _ds("DS2", sql_views=[_sql_view("Orders", ["B"])]),
        _ds("DS3", tables=["Orders"]),
    ]
    disambiguate_sql_view_names(dss)
    assert _view_names(dss) == ["Orders (DS1)", "Orders (DS2)"]
    assert [t["name"] for t in dss[2]["tables"]] == ["Orders"]


# ── 9b. Physical table + SQL View sharing a name in the SAME datasource ────
#
# Ownership on col_table_map / columns[].table / joins is recorded as a bare
# relation NAME, so when one datasource holds both an "Orders" table and an
# "Orders" view those entries are ambiguous. A blind string rewrite repoints the
# TABLE's own columns and joins at the view. Tableau does not emit this shape (a
# relation name is unique within a datasource, across types — 0 of 3,815 raw
# datasources in the corpus), but the function is public, so the table must
# survive it intact.

def _ambiguous_ds():
    return _ds(
        "D",
        sql_views=[_sql_view("Orders", ["ViewCol"])],
        tables=["Orders", "Other"],
        columns=[{"name": "TableCol", "table": "Orders"},
                 {"name": "ViewCol", "table": "Orders"}],
        col_table_map={"TableCol": "Orders", "ViewCol": "Orders"},
        joins=[{"left_table": "Orders", "right_table": "Other",
                "keys": [{"left": "TableCol", "right": "b"}]},
               {"left_table": "Orders", "right_table": "Other",
                "keys": [{"left": "ViewCol", "right": "b"}]}],
    )


def test_same_datasource_table_and_view_physical_table_keeps_its_name():
    dss = [_ambiguous_ds()]
    disambiguate_sql_view_names(dss)
    assert [t["name"] for t in dss[0]["tables"]] == ["Orders", "Other"]


def test_same_datasource_table_and_view_the_view_is_renamed():
    dss = [_ambiguous_ds()]
    disambiguate_sql_view_names(dss)
    assert _view_names(dss) == ["Orders (D)"]


def test_same_datasource_physical_column_references_are_untouched():
    dss = [_ambiguous_ds()]
    disambiguate_sql_view_names(dss)
    ds = dss[0]
    assert ds["col_table_map"]["TableCol"] == "Orders"
    assert [c for c in ds["columns"] if c["name"] == "TableCol"][0]["table"] == "Orders"


def test_same_datasource_view_column_references_follow_the_rename():
    dss = [_ambiguous_ds()]
    disambiguate_sql_view_names(dss)
    ds = dss[0]
    assert ds["col_table_map"]["ViewCol"] == "Orders (D)"
    assert [c for c in ds["columns"] if c["name"] == "ViewCol"][0]["table"] == "Orders (D)"


def test_same_datasource_both_col_table_map_owners_are_preserved():
    dss = [_ambiguous_ds()]
    disambiguate_sql_view_names(dss)
    assert dss[0]["col_table_map"] == {"TableCol": "Orders", "ViewCol": "Orders (D)"}


def test_same_datasource_join_on_the_physical_table_is_untouched():
    dss = [_ambiguous_ds()]
    disambiguate_sql_view_names(dss)
    assert dss[0]["joins"][0]["left_table"] == "Orders"      # keyed on TableCol


def test_same_datasource_join_on_the_view_follows_the_rename():
    dss = [_ambiguous_ds()]
    disambiguate_sql_view_names(dss)
    assert dss[0]["joins"][1]["left_table"] == "Orders (D)"  # keyed on ViewCol


def test_same_datasource_ownership_matches_sql_output_column_too():
    # A reference may be written as the caption OR the remote name; both must
    # attribute to the view.
    # _sql_view() gives each column sql_output_column = name.lower(), so the
    # view's "ViewCol" is also reachable as "viewcol".
    dss = [_ds("D", sql_views=[_sql_view("Orders", ["ViewCol"])], tables=["Orders"],
               col_table_map={"viewcol": "Orders", "TableCol": "Orders"})]
    disambiguate_sql_view_names(dss)
    assert dss[0]["col_table_map"] == {"viewcol": "Orders (D)", "TableCol": "Orders"}


def test_cross_datasource_table_collision_still_rewrites_unconditionally():
    # The real corpus shape (wb36): the physical table lives in ANOTHER
    # datasource, so nothing in the view's own datasource is ambiguous and the
    # rewrite stays unconditional — a view column absent from sql_views[] (the
    # parse does not always list every one) must still follow the rename.
    dss = [
        _ds("SUPERSTORE SALES", sql_views=[_sql_view("Orders", ["ViewCol"])],
            col_table_map={"Unlisted": "Orders"},
            columns=[{"name": "Unlisted", "table": "Orders"}]),
        _ds("Superstore Sales", tables=["Orders"]),
    ]
    disambiguate_sql_view_names(dss)
    assert _view_names(dss) == ["Orders (SUPERSTORE SALES)"]
    assert dss[0]["col_table_map"] == {"Unlisted": "Orders (SUPERSTORE SALES)"}
    assert dss[0]["columns"][0]["table"] == "Orders (SUPERSTORE SALES)"
    assert [t["name"] for t in dss[1]["tables"]] == ["Orders"]


def test_collision_detection_is_case_insensitive():
    # ThoughtSpot is case-insensitive on object names, so a case-only
    # difference is still ambiguous and must be disambiguated.
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["A"])]),
        _ds("DS2", sql_views=[_sql_view("CUSTOM SQL QUERY", ["B"])]),
    ]
    disambiguate_sql_view_names(dss)
    names = _view_names(dss)
    # each owner keeps ITS OWN spelling, qualified by its own datasource
    assert names == ["Custom SQL Query (DS1)", "CUSTOM SQL QUERY (DS2)"]
    assert len({n.lower() for n in names}) == len(names)


# ── 3. Stability against unrelated datasource churn ────────────────────────
#
# The property the "qualify every owner" rule exists for: a contested view's
# name depends only on (its own name, its own datasource), so editing the
# workbook elsewhere cannot rename it. Under the previous first-owner-wins rule
# every one of these assertions failed — inserting a datasource ahead of Goals
# moved the bare name to the newcomer and renamed Goals.

def _named(datasources):
    """{datasource name: its single view's emitted name}."""
    return {ds["name"]: ds["sql_views"][0]["name"] for ds in datasources if ds["sql_views"]}


def _workbook(*ds_names):
    return [_ds(n, sql_views=[_sql_view("Custom SQL Query", ["C"])]) for n in ds_names]


def test_inserting_an_unrelated_datasource_does_not_rename_existing_views():
    v1 = _named(disambiguate_sql_view_names(_workbook("Goals", "Daily")))
    v2 = _named(disambiguate_sql_view_names(_workbook("Alpha", "Goals", "Daily")))
    assert v1["Goals"] == v2["Goals"] == "Custom SQL Query (Goals)"
    assert v1["Daily"] == v2["Daily"] == "Custom SQL Query (Daily)"
    assert v2["Alpha"] == "Custom SQL Query (Alpha)"


def test_removing_an_unrelated_datasource_does_not_rename_survivors():
    before = _named(disambiguate_sql_view_names(_workbook("Alpha", "Goals", "Daily")))
    after = _named(disambiguate_sql_view_names(_workbook("Alpha", "Daily")))
    assert before["Alpha"] == after["Alpha"] == "Custom SQL Query (Alpha)"
    assert before["Daily"] == after["Daily"] == "Custom SQL Query (Daily)"


def test_reordering_datasources_does_not_change_any_name():
    a = _named(disambiguate_sql_view_names(_workbook("Goals", "Daily", "Region")))
    b = _named(disambiguate_sql_view_names(_workbook("Region", "Goals", "Daily")))
    assert a == b


def test_name_is_a_function_of_view_and_its_own_datasource_only():
    # The same (view name, datasource name) pair in two differently-shaped
    # workbooks must produce the same emitted name.
    small = _named(disambiguate_sql_view_names(_workbook("Goals", "Daily")))
    large = _named(disambiguate_sql_view_names(
        _workbook("Zeta", "Goals", "Beta", "Daily", "Alpha")))
    assert small["Goals"] == large["Goals"] == "Custom SQL Query (Goals)"


def test_uncontested_name_is_left_alone_even_beside_other_datasources():
    # Stability must not be bought by qualifying names nobody contests.
    dss = [
        _ds("Goals", sql_views=[_sql_view("Custom SQL Query", ["A"])]),
        _ds("Daily", sql_views=[_sql_view("Revenue Query", ["B"])]),
        _ds("Region", sql_views=[_sql_view("Other Query", ["C"])]),
    ]
    disambiguate_sql_view_names(dss)
    assert _view_names(dss) == ["Custom SQL Query", "Revenue Query", "Other Query"]


# ── 10. Determinism + the uniqueness invariant ─────────────────────────────

def test_repeated_runs_produce_identical_names():
    def build():
        return [
            _ds("Goals", sql_views=[_sql_view("Custom SQL Query", ["A"])]),
            _ds("Daily Rollup", sql_views=[_sql_view("Custom SQL Query", ["B"])]),
            _ds("Region Goals", sql_views=[_sql_view("Custom SQL Query", ["C"])]),
        ]
    first = _view_names(disambiguate_sql_view_names(build()))
    for _ in range(3):
        assert _view_names(disambiguate_sql_view_names(build())) == first
    assert first == [
        "Custom SQL Query (Goals)",
        "Custom SQL Query (Daily Rollup)",
        "Custom SQL Query (Region Goals)",
    ]


def test_rerunning_on_already_disambiguated_input_is_a_no_op():
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["A"])]),
        _ds("DS2", sql_views=[_sql_view("Custom SQL Query", ["B"])]),
    ]
    disambiguate_sql_view_names(dss)
    once = _view_names(dss)
    disambiguate_sql_view_names(dss)
    assert _view_names(dss) == once


def test_emitted_object_names_are_unique_across_the_workbook():
    # The invariant the whole fix exists to hold: every emitted SQL View name,
    # plus every physical table name, is distinct across the workbook.
    dss = [
        _ds("Goals", sql_views=[_sql_view("Custom SQL Query", ["A"])], tables=["Orders"]),
        _ds("Daily Rollup", sql_views=[_sql_view("Custom SQL Query", ["B"])]),
        _ds("Region Goals", sql_views=[_sql_view("Custom SQL Query", ["C"]),
                                       _sql_view("Orders", ["D"])]),
    ]
    disambiguate_sql_view_names(dss)
    emitted = _view_names(dss) + [t["name"] for ds in dss for t in ds["tables"]]
    assert len({n.lower() for n in emitted}) == len(emitted), emitted


def test_sql_body_and_output_columns_are_never_rewritten():
    sql = "select * from analytics_gold.gold_retail_hourly_goals"
    dss = [
        _ds("DS1", sql_views=[_sql_view("Custom SQL Query", ["A"], sql=sql)]),
        _ds("DS2", sql_views=[_sql_view("Custom SQL Query", ["Shopify"], sql=sql)]),
    ]
    disambiguate_sql_view_names(dss)
    renamed = dss[1]["sql_views"][0]
    assert renamed["name"] == "Custom SQL Query (DS2)"
    assert renamed["sql_query"] == sql
    assert [c["sql_output_column"] for c in renamed["columns"]] == ["shopify"]
    assert [c["name"] for c in renamed["columns"]] == ["Shopify"]


# ── Facade re-export — the path production actually imports through ────────

def test_facade_reexport_resolves_to_same_callable():
    # `commands/tableau.py` imports this from `ts_cli.model_builder`, which
    # serves it via a PEP 562 module `__getattr__` (a top-level import there
    # would be a two-way circular import). Every other test in this file
    # imports `ts_cli.tableau.build_model` directly, so without this assertion
    # dropping the name from that shim leaves the whole suite green while
    # `ts tableau build-model` fails at import time.
    from ts_cli.model_builder import disambiguate_sql_view_names as facade
    assert facade is disambiguate_sql_view_names


# ── 12. MERGE mode must not disambiguate (SCAL-339750) ─────────────────────
#
# Disambiguation exists because GENERATE emits every datasource into one output
# directory and one ThoughtSpot namespace. MERGE emits nothing there — it adds
# formulas to a model that already exists — so the incoming names have to match
# that model, and a rename computed from the workbook cannot know them.

import yaml  # noqa: E402

from ts_cli.cli import app  # noqa: E402
from runners import runner  # noqa: E402  (BL-139: one definition, see runners.py)


def _csq_ds_xml(caption, view_name):
    return f"""
  <datasource caption='{caption}'>
    <connection>
      <relation name='{view_name}' type='text'>SELECT id, sales FROM db.sch.t</relation>
      <metadata-records>
        <metadata-record class='column'><remote-name>id</remote-name><local-name>[id]</local-name><local-type>integer</local-type><parent-name>[{view_name}]</parent-name></metadata-record>
        <metadata-record class='column'><remote-name>sales</remote-name><local-name>[sales]</local-name><local-type>real</local-type><parent-name>[{view_name}]</parent-name></metadata-record>
      </metadata-records>
    </connection>
    <column name='[sales]' caption='Sales' datatype='real' role='measure'/>
  </datasource>"""


def _twb(tmp_path, *datasource_xml):
    twb = tmp_path / "wb.twb"
    twb.write_text("<?xml version='1.0'?>\n<workbook><datasources>"
                   + "".join(datasource_xml) + "</datasources></workbook>\n")
    return twb


def _capture_merge_ds(monkeypatch):
    """Run merge mode without a live instance: stub the model export and capture the
    datasource `_merge_flow` is handed."""
    from ts_cli.commands import tableau as tableau_cmd
    seen = {}

    monkeypatch.setattr(tableau_cmd, "_export_model_tml",
                        lambda guid, profile: {"model": {"model_tables": [], "columns": []}})

    def fake_merge_flow(*, ds, **kwargs):
        seen["ds"] = ds
        return {"datasource": ds["name"], "formulas_added": 0}

    monkeypatch.setattr(tableau_cmd, "_merge_flow", fake_merge_flow)
    return seen


def test_merge_mode_leaves_colliding_sql_view_names_unrenamed(tmp_path, monkeypatch):
    seen = _capture_merge_ds(monkeypatch)
    twb = _twb(tmp_path, _csq_ds_xml("Marketing", "Custom SQL Query"),
               _csq_ds_xml("Sales", "Custom SQL Query"))

    result = runner.invoke(app, [
        "tableau", "build-model", str(twb), "--existing-guid", "GUID-1",
        "--profile", "p", "--output-dir", str(tmp_path / "out"), "--dry-run",
    ])
    assert result.exit_code == 0, result.stdout + result.stderr

    ds = seen["ds"]
    assert [sv["name"] for sv in ds["sql_views"]] == ["Custom SQL Query"]
    assert "Custom SQL Query" in set(ds["col_table_map"].values())
    assert not any("(" in t for t in ds["col_table_map"].values())


def test_generate_mode_still_disambiguates_colliding_sql_view_names(tmp_path):
    twb = _twb(tmp_path, _csq_ds_xml("Marketing", "Custom SQL Query"),
               _csq_ds_xml("Sales", "Custom SQL Query"))
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = runner.invoke(app, [
        "tableau", "build-model", str(twb), "--connection", "CONN",
        "--output-dir", str(out_dir), "--database", "DB", "--schema", "PUBLIC",
    ])
    assert result.exit_code == 0, result.stdout + result.stderr

    names = sorted(yaml.safe_load(p.read_text())["sql_view"]["name"]
                   for p in out_dir.glob("*.sql_view.tml"))
    assert names == ["Custom SQL Query (Marketing)", "Custom SQL Query (Sales)"]


def test_merge_mode_uncontested_sql_view_name_is_unchanged(tmp_path, monkeypatch):
    """The guard must not alter the no-collision case, which was already correct."""
    seen = _capture_merge_ds(monkeypatch)
    twb = _twb(tmp_path, _csq_ds_xml("Sales", "Orders Query"))

    result = runner.invoke(app, [
        "tableau", "build-model", str(twb), "--existing-guid", "GUID-1",
        "--profile", "p", "--output-dir", str(tmp_path / "out"), "--dry-run",
    ])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert [sv["name"] for sv in seen["ds"]["sql_views"]] == ["Orders Query"]
