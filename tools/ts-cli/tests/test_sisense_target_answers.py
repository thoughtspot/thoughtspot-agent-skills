"""Unit tests for `ts sisense build-liveboard --target-model` (ts_cli.sisense.target_model /
target_answers). Pure functions, no live cluster. Everything is synthetic: an "acme" clinic
Model with a case hub, two role aliases of one calendar and two role aliases of one site table.
"""
import json

import yaml

from ts_cli.sisense.target_answers import build_target_liveboard, tabber_hidden
from ts_cli.sisense.target_model import TargetModel, split_dim

# Raw TML text so the YAML 1.1 `on:` -> True trap is exercised exactly as an export loads.
MODEL_TML = """
guid: 11111111-2222-3333-4444-555555555555
obj_id: acme-custom-model-id
model:
  name: Acme Clinic (Draft)
  model_tables:
  - name: fact_visit
    joins:
    - with: dim_case
      on: "[fact_visit::case_id_] = [dim_case::id_]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - with: Visit Site
      on: "[fact_visit::site_id_] = [dim_site::id_]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - with: Visit Start Date
      on: "[fact_visit::date__start_id_] = [dim_date::id_]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
    - with: Visit End Date
      on: "[fact_visit::date__end_id_] = [dim_date::id_]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - name: fact_case_stats
    joins:
    - with: dim_case
      on: "[fact_case_stats::case_id_] = [dim_case::id_]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - name: dim_case
    joins:
    - with: Case Site
      on: "[dim_case::site_id_] = [dim_site::id_]"
      type: LEFT_OUTER
      cardinality: MANY_TO_ONE
  - name: dim_site
    alias: Visit Site
  - name: dim_site
    alias: Case Site
  - name: dim_date
    alias: Visit Start Date
  - name: dim_date
    alias: Visit End Date
  formulas:
  - id: formula_Visit Case Count
    name: Visit Case Count
    expr: "unique count ( [fact_visit::case_id_] )"
  - id: formula_Visit Started?
    name: Visit Started?
    expr: "if ( [Visit Start Date::id_] > 0 ) then true else false"
  columns:
  - name: Case ID
    column_id: dim_case::source_pk
    properties: {column_type: ATTRIBUTE}
  - name: Case Status
    column_id: dim_case::status
    properties: {column_type: ATTRIBUTE}
  - name: Visit Site Name
    column_id: Visit Site::name
    properties: {column_type: ATTRIBUTE}
  - name: Case Site Name
    column_id: Case Site::name
    properties: {column_type: ATTRIBUTE}
  - name: Visit Start Date
    column_id: Visit Start Date::date_day
    properties: {column_type: ATTRIBUTE}
  - name: Visit End Date
    column_id: Visit End Date::date_day
    properties: {column_type: ATTRIBUTE}
  - name: Visit Cost
    column_id: fact_visit::cost
    properties: {column_type: MEASURE, aggregation: SUM}
  - name: Visit Case Count
    formula_id: formula_Visit Case Count
    properties: {column_type: MEASURE}
  - name: Visit Started?
    formula_id: formula_Visit Started?
    properties: {column_type: ATTRIBUTE}
  - name: Case Visit Total
    column_id: fact_case_stats::visit_total
    properties: {column_type: MEASURE, aggregation: SUM}
"""


def _target():
    return yaml.safe_load(MODEL_TML)


def _rel(a, ac, b, bc):
    return {"endpoints": [{"table": a, "column": ac}, {"table": b, "column": bc}], "cardinality": "1:N"}


TABLES = [{"id": "fact_visit", "jaql_name": "fact_visit", "name": "Visits (Fact)"},
          {"id": "dim_case", "jaql_name": "dim_case", "name": "Case (Dim)"},
          {"id": "dim_site", "jaql_name": "dim_site", "name": "Site (Dim)"},
          {"id": "tq_opaque1", "jaql_name": "Visit_Start_Date", "name": "Visit Start Date (Dim)"},
          {"id": "fact_case_stats", "jaql_name": "fact_case_stats", "name": "Case Stats"}]
RELATIONS = [_rel("fact_visit", "case_id_", "dim_case", "id_"),
             _rel("fact_visit", "site_id_", "dim_site", "id_"),
             _rel("dim_case", "site_id_", "dim_site", "id_"),
             _rel("fact_visit", "date__start_id_", "tq_opaque1", "id_"),   # relation uses the opaque id
             _rel("fact_case_stats", "case_id_", "dim_case", "id_")]


def _f(dim, panel, kind="dimension", agg=None, title="", level=None):
    return {"kind": kind, "dim": dim, "agg": agg, "title": title, "formula": None, "level": level, "panel": panel}


def _w(oid, title, wtype, fields, filters=(), **extra):
    return dict({"oid": oid, "title": title, "wtype": wtype, "subtype": "", "fields": list(fields),
                 "filters": list(filters)}, **extra)


def _member(dim, vals):
    return {"kind": "member", "dim": dim, "operator": "members", "values": vals, "raw": {"members": vals}}


def _exclude(dim, vals):
    return {"kind": "exclude", "dim": dim, "operator": "exclude", "values": vals,
            "raw": {"exclude": {"members": vals}}}


def _range(dim, raw):
    return {"kind": "range", "dim": dim, "operator": "range", "values": [], "raw": raw}


def _inv(widgets, dash_filters=(), layout=None):
    return {"tables": TABLES, "relations": RELATIONS, "widgets": widgets,
            "dashboard": {"title": "Acme Visits", "filters": list(dash_filters), "layout": layout or []}}


def _answers(res):
    return {v["answer"]["name"]: v["answer"] for v in res["liveboard"]["liveboard"]["visualizations"] if "answer" in v}


# --------------------------------------------------------------------------- target model
def test_on_key_parsed_as_bool_is_still_read():
    t = TargetModel(_target())
    assert ("Visit Site", "site_id_") in t.joins["fact_visit"]      # `on:` came back as True
    assert t.obj_id == "acme-custom-model-id"


def test_split_dim_drops_date_hierarchy_tag():
    assert split_dim("[Visit_Start_Date.date_day (Calendar)]") == ("Visit_Start_Date", "date_day")


def test_role_alias_resolved_by_name_and_by_relation_fk():
    t = TargetModel(_target())
    assert t.resolve_instance("Visit_Start_Date", ["fact_visit"], RELATIONS)[0] == "Visit Start Date"
    # one base table, two aliases: the FK the Sisense relation uses picks the alias
    assert t.resolve_instance("dim_site", ["fact_visit"], RELATIONS)[0] == "Visit Site"
    assert t.resolve_instance("dim_site", ["fact_case_stats"], RELATIONS)[0] == "Case Site"


def test_unknown_table_is_reported_not_guessed():
    inst, note = TargetModel(_target()).resolve_instance("dim_missing", ["fact_visit"], RELATIONS)
    assert inst is None and "not in the target model" in note


# --------------------------------------------------------------------------- answers
def test_count_is_distinct_and_binds_hidden_key_to_model_formula():
    w = _w("w1", "Cases", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count", "# Cases")])
    a = _answers(build_target_liveboard(_inv([w]), _target()))["Cases"]
    assert a["search_query"] == "[Visit Case Count]"
    assert a["answer_columns"] == [{"name": "Visit Case Count", "custom_name": "# Cases"}]


def test_count_of_exposed_attribute_uses_unique_count_output_name():
    w = _w("w1", "Distinct cases", "indicator", [_f("[dim_case.source_pk]", "value", "measure", "count")])
    a = _answers(build_target_liveboard(_inv([w]), _target()))["Distinct cases"]
    assert a["search_query"] == "unique count [Case ID]"
    assert a["answer_columns"][0]["name"] == "Unique Number of Case ID"


def test_sum_measure_output_is_total_prefixed():
    w = _w("w1", "Cost", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")])
    a = _answers(build_target_liveboard(_inv([w]), _target()))["Cost"]
    assert a["search_query"] == "sum [Visit Cost]" and a["answer_columns"][0]["name"] == "Total Visit Cost"


def test_unbindable_count_is_needs_review_with_the_measure_to_add():
    w = _w("w1", "Stats", "indicator", [_f("[fact_case_stats.case_id_]", "value", "measure", "count")])
    res = build_target_liveboard(_inv([w]), _target())
    row = next(r for r in res["visual_rows"] if r["visual"] == "Stats")
    assert row["status"] == "NEEDS REVIEW" and "unique count ( [fact_case_stats::case_id_] )" in row["note"]


def test_widget_filters_become_search_filters_never_in_lists():
    w = _w("w1", "Open cases", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_member("[dim_case.status]", ["Open", "Pending"]), _exclude("[dim_site.name]", ["Test Site"]),
            _range("[fact_visit.cost]", {"from": 0, "toNotEqual": 100})])
    q = _answers(build_target_liveboard(_inv([w]), _target()))["Open cases"]["search_query"]
    assert "[Case Status] = 'Open' [Case Status] = 'Pending'" in q     # ThoughtSpot ORs same-column =
    assert "[Visit Site Name] != 'Test Site'" in q                     # and ANDs same-column !=
    assert "[Visit Cost] >= 0 [Visit Cost] < 100" in q
    assert " in (" not in q                                            # silently ignored by search


def test_filter_map_override_replaces_an_unexposed_key_filter():
    w = _w("w1", "Started", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_range("[Visit_Start_Date.id_]", {"from": 0})])
    inv = _inv([w])
    bare = build_target_liveboard(inv, _target())
    assert next(r for r in bare["visual_rows"] if r["visual"] == "Started")["status"] == "NEEDS REVIEW"
    res = build_target_liveboard(inv, _target(), overrides={"filter_map": {"[Visit_Start_Date.id_]": "[Visit Started?] = true"}})
    assert _answers(res)["Started"]["search_query"] == "[Visit Case Count] [Visit Started?] = true"


def test_date_level_becomes_bucket_and_output_name():
    w = _w("w1", "Visits over time", "chart/line",
           [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="weeks"),
            _f("[fact_visit.case_id_]", "values", "measure", "count")])
    a = _answers(build_target_liveboard(_inv([w]), _target()))["Visits over time"]
    assert a["search_query"].startswith("[Visit Start Date].weekly")
    assert a["chart"]["axis_configs"][0]["x"] == ["Week(Visit Start Date)"]


def test_target_obj_id_is_used_for_the_binding():
    w = _w("w1", "Cases", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")])
    a = _answers(build_target_liveboard(_inv([w]), _target()))["Cases"]
    assert a["tables"] == [{"id": "Acme Clinic (Draft)", "name": "Acme Clinic (Draft)", "obj_id": "acme-custom-model-id"}]


# --------------------------------------------------------------------------- tabs, notes, layout
def _tabbed():
    m = [_f("[fact_visit.case_id_]", "values", "measure", "count")]
    day = _w("wd", "Visits (Daily)", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="days")] + m)
    wk = _w("ww", "Visits (Weekly)", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="weeks")] + m)
    tab = _w("wt", "Visits Over Time", "WidgetsTabber", [],
             tabber={"tabs": [{"title": "DAILY", "show": ["wd"]}, {"title": "WEEKLY", "show": ["ww"]}], "active": 1})
    head = _w("wr", "RICHTEXT_MAIN.TITLE", "richtexteditor", [], richtext={"html": "<b>Visit <i>Overview</i></b>", "bg_color": "#000"})
    return [head, tab, day, wk]


def test_tab_set_keeps_only_the_active_tab_and_strips_its_grain():
    widgets = _tabbed()
    assert tabber_hidden(widgets) == {"wd": "Visits Over Time"}
    res = build_target_liveboard(_inv(widgets), _target())
    assert list(_answers(res)) == ["Visits"]                           # "(Weekly)" stripped
    assert any(r["status"] == "Merged" and r["visual"] == "Visits (Daily)" for r in res["visual_rows"])


def test_richtext_and_tab_titles_become_note_tiles():
    res = build_target_liveboard(_inv(_tabbed()), _target())
    notes = [v["note_tile"]["html_parsed_string"] for v in res["liveboard"]["liveboard"]["visualizations"] if "note_tile" in v]
    assert any("Visit Overview" in n for n in notes) and any("Visits Over Time" in n for n in notes)


def test_layout_rows_fill_twelve_columns():
    layout = [{"col": 0, "items": [{"oid": "wr", "width_pct": 100, "height_px": 100, "col_pct": 100}]},
              {"col": 0, "items": [{"oid": "wd", "width_pct": 66.6, "height_px": 380, "col_pct": 100},
                                   {"oid": "ww", "width_pct": 33.3, "height_px": 380, "col_pct": 100}]}]
    res = build_target_liveboard(_inv(_tabbed(), layout=layout), _target())
    tiles = res["liveboard"]["liveboard"]["layout"]["tiles"]
    assert all(t["x"] + t["width"] <= 12 for t in tiles)
    chart = next(t for t in tiles if t["height"] > 1)
    assert chart["width"] == 12                    # the hidden Daily tab gave its width to Weekly


# --------------------------------------------------------------------------- drills
def test_drill_becomes_details_table_with_shared_source_filters():
    src = _w("w1", "Cases by Site", "pivot2",
             [_f("[dim_site.name]", "rows"), _f("[fact_visit.case_id_]", "values", "measure", "count")],
             [_member("[dim_case.status]", ["Open"])], drill_targets=["_drill_case_list"])
    drill = {"dashboard": {"title": "_drill_case_list"},
             "widgets": [_w("d1", "Case List", "pivot2", [_f("[dim_case.source_pk]", "rows"), _f("[dim_case.status]", "rows")])]}
    res = build_target_liveboard(_inv([src]), _target(), drills=[drill])
    a = _answers(res)["Case List"]
    assert a["search_query"] == "[Case ID] [Case Status] [Case Status] = 'Open'"
    assert a["display_mode"] == "TABLE_MODE" and "right-click" in a["description"].lower()


def test_missing_drill_dashboard_is_flagged():
    src = _w("w1", "Cases by Site", "pivot2",
             [_f("[dim_site.name]", "rows"), _f("[fact_visit.case_id_]", "values", "measure", "count")],
             drill_targets=["_drill_case_list"])
    rows = build_target_liveboard(_inv([src]), _target())["visual_rows"]
    assert any(r["status"] == "NEEDS REVIEW" and "--drill" in r["note"] for r in rows)


# --------------------------------------------------------------------------- chips
def test_chip_format_exclusion_and_reach():
    visits = _w("w1", "Open visits", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
                [_member("[dim_case.status]", ["Open"])])
    stats = _w("w2", "Visit total", "indicator", [_f("[fact_case_stats.visit_total]", "value", "measure", "sum")])
    res = build_target_liveboard(_inv([visits, stats], [_member("[dim_case.status]", ["Open", "Closed"]),
                                                       _exclude("[dim_site.name]", ["Test Site"])]), _target())
    lb = res["liveboard"]["liveboard"]
    chips = {c["column"][0]: c for c in lb["filters"]}
    vid = next(v["id"] for v in lb["visualizations"] if v.get("answer", {}).get("name") == "Open visits")
    assert (chips["Case Status"]["oper"], chips["Case Status"]["values"]) == ("in", ["Open", "Closed"])
    assert chips["Case Status"]["excluded_visualizations"] == [vid]       # the tile sets it itself
    # dim_site plays two roles; Case Site reaches both tiles' facts, Visit Site only one
    assert chips["Case Site Name"]["oper"] == "not in"
    assert "generic_filter" not in chips["Case Site Name"]


def test_chip_tie_breaks_on_shortest_join_path():
    visits = _w("w1", "Visits", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")])
    res = build_target_liveboard(_inv([visits], [_exclude("[dim_site.name]", ["Test Site"])]), _target())
    # both aliases reach fact_visit; Visit Site is one hop, Case Site two -> Visit Site
    assert res["liveboard"]["liveboard"]["filters"][0]["column"] == ["Visit Site Name"]


def test_chip_on_unexposed_column_is_needs_review():
    visits = _w("w1", "Visits", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")])
    res = build_target_liveboard(_inv([visits], [_member("[dim_case.priority]", ["High"])]), _target())
    assert any(r["visual"].startswith("filter chip") and r["status"] == "NEEDS REVIEW" for r in res["visual_rows"])
    assert "filters" not in res["liveboard"]["liveboard"]


def test_load_tml_accepts_export_json_with_surrogate_pairs(tmp_path):
    from ts_cli.commands.sisense import _load_tml
    edoc = MODEL_TML.replace("Acme Clinic (Draft)", "Acme Clinic \U0001F3E5 (Draft)")
    p = tmp_path / "export.json"
    p.write_text(json.dumps([{"edoc": edoc, "info": {}}]), encoding="utf-8")   # ensure_ascii -> \\ud83c\\udfe5
    doc = _load_tml(str(p))
    assert doc["model"]["model_tables"][0]["name"] == "fact_visit"
