"""Unit tests for `ts sisense build-liveboard --target-model` (ts_cli.sisense.target_model /
target_answers). Pure functions, no live cluster. Everything is synthetic: an "acme" clinic
Model with a case hub, two role aliases of one calendar and two role aliases of one site table.
"""
import json

import yaml

from ts_cli.sisense.target_answers import FULL_NUMBER_FORMAT, build_target_liveboard, tabber_hidden
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
    assert a["answer_columns"] == [{"name": "Visit Case Count", "custom_name": "# Cases",
                                    "format": FULL_NUMBER_FORMAT}]


def test_count_of_exposed_attribute_uses_unique_count_output_name():
    w = _w("w1", "Distinct cases", "indicator", [_f("[dim_case.source_pk]", "value", "measure", "count")])
    a = _answers(build_target_liveboard(_inv([w]), _target()))["Distinct cases"]
    assert a["search_query"] == "unique count [Case ID]"
    assert a["answer_columns"][0]["name"] == "Unique Number of Case ID"


def test_sum_measure_output_is_total_prefixed():
    w = _w("w1", "Cost", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")])
    a = _answers(build_target_liveboard(_inv([w]), _target()))["Cost"]
    assert a["search_query"] == "sum [Visit Cost]" and a["answer_columns"][0]["name"] == "Total Visit Cost"


def test_measures_show_full_values_and_attributes_keep_default_format():
    # Sisense shows 32,161 where ThoughtSpot's default shows 32.16K; customers reject the latter.
    w = _w("w1", "By site", "chart/column", [_f("[dim_site.name]", "categories"),
                                             _f("[fact_visit.cost]", "values", "measure", "sum")])
    cols = {c["name"]: c for c in _answers(build_target_liveboard(_inv([w]), _target()))["By site"]["answer_columns"]}
    assert cols["Total Visit Cost"]["format"]["numberFormatConfig"]["unit"] == "NONE"
    assert all("format" not in c for n, c in cols.items() if n != "Total Visit Cost")


def test_unbindable_count_is_needs_review_with_the_measure_to_add():
    w = _w("w1", "Stats", "indicator", [_f("[fact_case_stats.case_id_]", "value", "measure", "count")])
    res = build_target_liveboard(_inv([w]), _target())
    row = next(r for r in res["visual_rows"] if r["visual"] == "Stats")
    assert row["status"] == "NEEDS REVIEW" and "unique count ( [fact_case_stats::case_id_] )" in row["note"]


def test_widget_filters_become_search_filters_never_in_lists():
    w = _w("w1", "Open cases", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_member("[dim_case.status]", ["Open", "Pending"]), _exclude("[dim_case.source_pk]", ["T1", "T2"]),
            _range("[fact_visit.cost]", {"from": 0, "toNotEqual": 100})])
    target = _target()                       # cost as a numeric ATTRIBUTE: a row-level filter on it is exact
    next(c for c in target["model"]["columns"] if c["name"] == "Visit Cost")["properties"] = {"column_type": "ATTRIBUTE"}
    q = _answers(build_target_liveboard(_inv([w]), target))["Open cases"]["search_query"]
    assert "[Case Status] = 'Open' [Case Status] = 'Pending'" in q     # ThoughtSpot ORs same-column =
    assert "[Case ID] != 'T1' [Case ID] != 'T2'" in q                  # and ANDs same-column !=
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
    wk = _w("ww", "Visits (Monthly)", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months")] + m)
    tab = _w("wt", "Visits Over Time", "WidgetsTabber", [],
             tabber={"tabs": [{"title": "DAILY", "show": ["wd"]}, {"title": "MONTHLY", "show": ["ww"]}], "active": 1})
    head = _w("wr", "RICHTEXT_MAIN.TITLE", "richtexteditor", [], richtext={"html": "<b>Visit <i>Overview</i></b>", "bg_color": "#000"})
    return [head, tab, day, wk]


def test_tab_set_keeps_only_the_active_tab_and_strips_its_grain():
    widgets = _tabbed()
    assert tabber_hidden(widgets) == {"wd": "Visits Over Time"}
    res = build_target_liveboard(_inv(widgets), _target())
    assert list(_answers(res)) == ["Visits"]                           # "(Monthly)" stripped
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
    doc, tables = _load_tml(str(p))
    assert doc["model"]["model_tables"][0]["name"] == "fact_visit" and tables == []


def test_load_tml_reads_associated_tables_from_an_export(tmp_path):
    from ts_cli.commands.sisense import _load_tml
    table = "table:\n  name: dim_case\n  columns:\n  - name: Status Label\n    db_column_name: status\n"
    p = tmp_path / "export.json"
    p.write_text(json.dumps([{"edoc": table}, {"edoc": MODEL_TML}]), encoding="utf-8")
    doc, tables = _load_tml(str(p))
    assert doc["model"]["name"] == "Acme Clinic (Draft)" and tables[0]["table"]["name"] == "dim_case"


# --------------------------------------------------------------------------- review 2: failure paths
def _row(res, visual):
    return next(r for r in res["visual_rows"] if r["visual"] == visual)


def _chip_rows(res):
    return [r for r in res["visual_rows"] if r["visual"].startswith("filter chip")]


def _visits():
    return _w("w1", "Visits", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")])


def test_range_chip_carries_its_condition_but_is_needs_review_until_verified():
    res = build_target_liveboard(_inv([_visits()], [_range("[fact_visit.cost]", {"from": 10, "to": 50})]), _target())
    chip = res["liveboard"]["liveboard"]["filters"][0]
    assert chip["generic_filter"] == {"oper": "BW_INC", "values": [10, 50]}
    assert any("open-item #5" in r["note"] for r in _chip_rows(res))
    assert _row(res, "Visits")["status"] == "NEEDS REVIEW"

def test_relative_date_and_unknown_chips_are_needs_review_not_silently_unfiltered():
    rel = {"kind": "relative_date", "dim": "[Visit_Start_Date.date_day (Calendar)]", "operator": "last",
           "values": [{"count": 30}], "raw": {"last": {"count": 30, "offset": 0}}}
    odd = {"kind": "unknown", "dim": "[dim_case.status]", "operator": "or", "values": [], "raw": {"or": []}}
    res = build_target_liveboard(_inv([_visits()], [rel, odd]), _target())
    notes = [r["note"] for r in _chip_rows(res) if r["status"] == "NEEDS REVIEW"]
    assert any("relative_date condition is not carried" in n for n in notes)
    assert any("unknown condition is not carried" in n for n in notes)


def test_all_filter_is_no_condition_at_any_kind_or_level():
    every = {"kind": "unknown", "dim": "[Visit_Start_Date.date_day (Calendar)]", "operator": "all",
             "values": [], "raw": {"all": True, "level": "years"}, "level": "years"}
    res = build_target_liveboard(_inv([_visits()], [every]), _target())
    assert not _chip_rows(res) and "oper" not in res["liveboard"]["liveboard"]["filters"][0]


def test_widget_filter_at_a_coarser_date_level_is_needs_review_not_a_day_equality():
    year = dict(_member("[Visit_Start_Date.date_day (Calendar)]", ["2024-01-01T00:00:00"]), level="years")
    w = _w("w1", "Visits 2024", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")], [year])
    res = build_target_liveboard(_inv([w]), _target())
    row = _row(res, "Visits 2024")
    assert row["status"] == "NEEDS REVIEW" and "years periods" in row["note"]
    assert "2024-01-01" not in _answers(res)["Visits 2024"]["search_query"]


def _day_filter_widget(level="days"):
    day = dict(_member("[Visit_Start_Date.date_day (Calendar)]", ["2024-01-05T00:00:00"]),
               datatype="datetime", **({"level": level} if level else {}))
    return _w("w1", "Visits 5 Jan", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")], [day])


def test_date_value_filters_are_never_carried():
    # live-verified: search rejects '2026-02-01' and '2026-02-01T00:00:00' against a DATE column,
    # and no other date value form was verified, so a date filter's values are not carried
    for level in ("days", None, "hours", "years"):
        res = build_target_liveboard(_inv([_day_filter_widget(level)]), _target())
        row = _row(res, "Visits 5 Jan")
        assert row["status"] == "NEEDS REVIEW" and "date value" in row["note"], level
        assert "2024-01-05" not in _answers(res)["Visits 5 Jan"]["search_query"]


def test_chip_at_a_coarser_date_level_is_needs_review():
    year = dict(_member("[Visit_Start_Date.date_day (Calendar)]", ["2024-01-01T00:00:00"]), level="years")
    res = build_target_liveboard(_inv([_visits()], [year]), _target())
    assert any("years periods" in r["note"] for r in _chip_rows(res))
    assert "oper" not in res["liveboard"]["liveboard"]["filters"][0]


def test_second_aggregation_of_one_column_is_needs_review_not_dropped():
    w = _w("w1", "Cost", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum"),
                                       _f("[fact_visit.cost]", "value", "measure", "avg")])
    row = _row(build_target_liveboard(_inv([w]), _target()), "Cost")
    assert row["status"] == "NEEDS REVIEW" and "average [Visit Cost] is not carried" in row["note"]


def test_same_date_at_two_levels_is_needs_review():
    w = _w("w1", "By period", "pivot2", [_f("[Visit_Start_Date.date_day (Calendar)]", "rows", level="years"),
                                         _f("[Visit_Start_Date.date_day (Calendar)]", "rows", level="months"),
                                         _f("[fact_visit.case_id_]", "values", "measure", "count")])
    row = _row(build_target_liveboard(_inv([w]), _target()), "By period")
    assert row["status"] == "NEEDS REVIEW" and "[Visit Start Date].monthly is not carried" in row["note"]


def test_tab_set_that_is_not_time_grains_emits_every_tab():
    m = [_f("[fact_visit.case_id_]", "values", "measure", "count")]
    by_site = _w("ws", "By Site", "chart/column", [_f("[dim_site.name]", "categories")] + m)
    by_status = _w("wc", "By Status", "chart/column", [_f("[dim_case.status]", "categories")] + m)
    tab = _w("wt", "Breakdowns", "WidgetsTabber", [],
             tabber={"tabs": [{"title": "SITE", "show": ["ws"]}, {"title": "STATUS", "show": ["wc"]}], "active": 0})
    widgets = [tab, by_site, by_status]
    res = build_target_liveboard(_inv(widgets), _target())
    assert tabber_hidden(widgets) == {}
    assert set(_answers(res)) == {"By Site", "By Status"}
    assert not any(r["status"] == "Merged" for r in res["visual_rows"])
    assert "not a date-grain variant" in _row(res, "By Status")["note"]


def test_chip_binding_another_role_copy_than_a_tiles_own_path_is_flagged():
    # the site chip binds Case Site (it reaches both tiles), but the visit tile's own Sisense path
    # to dim_site is fact_visit.site_id_ -> Visit Site: the chip filters it by the case's site
    visits = _w("w1", "Open visits", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")])
    stats = _w("w2", "Visit total", "indicator", [_f("[fact_case_stats.visit_total]", "value", "measure", "sum")])
    res = build_target_liveboard(_inv([visits, stats], [_exclude("[dim_site.name]", ["Test Site"])]), _target())
    notes = [r["note"] for r in _chip_rows(res)]
    assert any("Open visits (the chip binds Case Site, but this widget reaches the table through Visit Site" in n
               for n in notes)
    assert not any("Visit total" in n for n in notes)              # its own path IS Case Site
    assert _row(res, "Open visits")["status"] == "NEEDS REVIEW"    # the tile row carries it too
    assert _row(res, "Visit total")["status"] == "Migrated"


def test_model_column_format_wins_over_the_full_value_default():
    target = _target()
    cost = next(c for c in target["model"]["columns"] if c["name"] == "Visit Cost")
    cost["properties"]["currency_type"] = {"iso_code": "USD"}
    w = _w("w1", "Cost", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")])
    col = _answers(build_target_liveboard(_inv([w]), target))["Cost"]["answer_columns"][0]
    assert "format" not in col


def test_drill_keeps_its_own_widget_filters_and_flags_extra_widgets():
    src = _w("w1", "Cases by Site", "pivot2",
             [_f("[dim_site.name]", "rows"), _f("[fact_visit.case_id_]", "values", "measure", "count")],
             drill_targets=["_drill_case_list"])
    drill = {"dashboard": {"title": "_drill_case_list"},
             "widgets": [_w("d1", "Case List", "pivot2", [_f("[dim_case.source_pk]", "rows")],
                            [_member("[dim_case.status]", ["Open"])]),
                         _w("d2", "Case Costs", "pivot2", [_f("[fact_visit.cost]", "values", "measure", "sum")])]}
    res = build_target_liveboard(_inv([src]), _target(), drills=[drill])
    assert "[Case Status] = 'Open'" in _answers(res)["Case List"]["search_query"]
    row = _row(res, "Case List")
    assert row["status"] == "NEEDS REVIEW" and "Case Costs" in row["note"]


def test_drill_dashboard_without_field_widgets_is_flagged():
    src = _w("w1", "Cases by Site", "pivot2",
             [_f("[dim_site.name]", "rows"), _f("[fact_visit.case_id_]", "values", "measure", "count")],
             drill_targets=["_drill_empty"])
    drill = {"dashboard": {"title": "_drill_empty"}, "widgets": [_w("d1", "Header", "richtexteditor", [])]}
    row = _row(build_target_liveboard(_inv([src]), _target(), drills=[drill]), "drill -> _drill_empty")
    assert row["status"] == "NEEDS REVIEW" and "no widget with fields" in row["note"]


def test_field_map_and_filter_map_typos_are_needs_review_not_import_failures():
    w = _w("w1", "Cost", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")],
           [_range("[Visit_Start_Date.id_]", {"from": 0})])
    ov = {"field_map": {"[fact_visit.cost]": "Visit Cots"}, "filter_map": {"[Visit_Start_Date.id_]": "[Visit Startd?] = true"}}
    row = _row(build_target_liveboard(_inv([w]), _target(), overrides=ov), "Cost")
    assert row["status"] == "NEEDS REVIEW"
    assert "'Visit Cots', which is not a column" in row["note"] and "names Visit Startd?" in row["note"]


def test_instance_the_facts_cannot_reach_is_refused():
    t = TargetModel(_target())
    inst, note = t.resolve_instance("dim_date", ["fact_case_stats"], RELATIONS)
    assert inst is None and "not reachable from the widget's facts" in note
    inst, note = t.resolve_instance("Visit_Start_Date", ["fact_case_stats"], RELATIONS)   # by name
    assert inst is None and "not reachable from the widget's facts" in note


def test_name_match_disagreeing_with_the_join_key_is_flagged():
    rels = RELATIONS + [_rel("fact_visit", "site_id_", "Case_Site", "id_")]
    inst, note = TargetModel(_target()).resolve_instance("Case_Site", ["fact_visit"], rels)
    assert inst is None and "relation joins through Visit Site" in note


def test_friendly_table_column_names_resolve_through_the_table_tml():
    target = _target()
    for c in target["model"]["columns"]:
        if c["name"] == "Case Status":
            c["column_id"] = "dim_case::Status Label"
    tables = [{"table": {"name": "dim_case", "columns": [{"name": "Status Label", "db_column_name": "status"}]}}]
    assert TargetModel(target).column("dim_case", "status") is None
    assert TargetModel(target, tables).column("dim_case", "status") == "Case Status"


def test_column_names_differing_only_in_case_and_underscores_resolve():
    target = _target()
    for c in target["model"]["columns"]:
        if c["name"] == "Case ID":
            c["column_id"] = "dim_case::Source PK"
    assert TargetModel(target).column("dim_case", "source_pk") == "Case ID"


# --------------------------------------------------------------------------- review 3: allowlist
def test_hidden_tab_with_different_filters_is_its_own_tile_not_merged():
    m = [_f("[fact_visit.case_id_]", "values", "measure", "count")]
    day = [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months")]
    this = _w("wy", "This Year", "chart/line", day + m, [_member("[dim_case.status]", ["Open"])])
    last = _w("wl", "Last Year", "chart/line", day + m, [_member("[dim_case.status]", ["Closed"])])
    tab = _w("wt", "Years", "WidgetsTabber", [],
             tabber={"tabs": [{"title": "THIS", "show": ["wy"]}, {"title": "LAST", "show": ["wl"]}], "active": 0})
    res = build_target_liveboard(_inv([tab, this, last]), _target())
    assert set(_answers(res)) == {"This Year", "Last Year"}
    assert not any(r["status"] == "Merged" for r in res["visual_rows"])


def test_hidden_tab_identical_to_the_shown_one_is_not_a_grain_variant():
    m = [_f("[fact_visit.case_id_]", "values", "measure", "count")]
    a = _w("wa", "A", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months")] + m)
    b = _w("wb", "B", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months")] + m)
    tab = _w("wt", "Same", "WidgetsTabber", [],
             tabber={"tabs": [{"title": "A", "show": ["wa"]}, {"title": "B", "show": ["wb"]}], "active": 0})
    assert tabber_hidden([tab, a, b]) == {}


def _rank(op, n, by_dim="[fact_visit.cost]", by_agg="sum"):
    raw = {op: n, "by": {"dim": by_dim, "agg": by_agg}}
    return {"kind": "top_n", "dim": "[dim_site.name]", "operator": op, "values": [n], "raw": raw}


def _ranked(rank):
    return _w("w1", "Sites", "chart/bar", [_f("[dim_site.name]", "categories"),
                                           _f("[fact_visit.cost]", "values", "measure", "sum")], [rank])


def test_top_and_bottom_n_rank_by_the_widgets_measure():
    top = _answers(build_target_liveboard(_inv([_ranked(_rank("top", 5))]), _target()))["Sites"]
    assert top["search_query"].endswith("top 5") and "bottom" not in top["search_query"]
    res = build_target_liveboard(_inv([_ranked(_rank("bottom", 5))]), _target())
    q = _answers(res)["Sites"]["search_query"]
    assert q.endswith("bottom 5") and "top" not in q and _row(res, "Sites")["status"] == "Migrated"


def test_ranking_by_another_measure_or_non_numeric_n_is_needs_review():
    other = _row(build_target_liveboard(_inv([_ranked(_rank("top", 5, by_agg="avg"))]), _target()), "Sites")
    assert other["status"] == "NEEDS REVIEW" and "not the widget's only measure" in other["note"]
    bad = _row(build_target_liveboard(_inv([_ranked(_rank("top", "ten"))]), _target()), "Sites")
    assert bad["status"] == "NEEDS REVIEW" and "not a whole number" in bad["note"]


def test_dashboard_level_ranking_is_needs_review_on_every_tile():
    res = build_target_liveboard(_inv([_visits()], [_rank("top", 3)]), _target())
    assert any(r["status"] == "NEEDS REVIEW" and "top/bottom" in r["note"] for r in _chip_rows(res))
    assert _row(res, "Visits")["status"] == "NEEDS REVIEW"


def test_display_name_fallback_binds_only_a_calculated_column_to_a_model_formula():
    # [fact_visit.Visit Case Count] is NOT a Sisense calculated column: no fallback, not exposed
    w = _w("w1", "Cases", "indicator", [_f("[fact_visit.Visit Case Count]", "value", "measure", "sum")])
    assert _row(build_target_liveboard(_inv([w]), _target()), "Cases")["status"] == "NEEDS REVIEW"
    inv = _inv([w])
    inv["tables"] = [dict(t, columns=[{"id": "Visit Case Count", "name": "Visit Case Count", "calculated": True}])
                     if t["jaql_name"] == "fact_visit" else t for t in inv["tables"]]
    row = _row(build_target_liveboard(inv, _target()), "Cases")
    # a calculated column found by name is a guess: reported until mapped, never carried silently
    assert row["status"] == "NEEDS REVIEW" and "by name only" in row["note"]
    mapped = build_target_liveboard(inv, _target(), overrides={"field_map": {"[fact_visit.Visit Case Count]": "Visit Case Count"}})
    assert _answers(mapped)["Cases"]["search_query"] == "[Visit Case Count]"


def test_display_name_fallback_never_binds_a_plain_model_column():
    target = _target()
    target["model"]["columns"].append({"name": "Revenue", "column_id": "fact_visit::net_revenue",
                                       "properties": {"column_type": "MEASURE", "aggregation": "SUM"}})
    inv = _inv([_w("w1", "Rev", "indicator", [_f("[fact_visit.Revenue]", "value", "measure", "sum")])])
    inv["tables"] = [dict(t, columns=[{"id": "Revenue", "name": "Revenue", "calculated": True}])
                     if t["jaql_name"] == "fact_visit" else t for t in inv["tables"]]
    row = _row(build_target_liveboard(inv, target), "Rev")
    assert row["status"] == "NEEDS REVIEW" and "not exposed" in row["note"]


def test_chip_on_a_drill_tables_own_filter_column_excludes_that_tile():
    src = _w("w1", "Cases by Site", "pivot2",
             [_f("[dim_site.name]", "rows"), _f("[fact_visit.case_id_]", "values", "measure", "count")],
             drill_targets=["_drill_case_list"])
    drill = {"dashboard": {"title": "_drill_case_list"},
             "widgets": [_w("d1", "Case List", "pivot2", [_f("[dim_case.source_pk]", "rows")],
                            [_member("[dim_case.status]", ["Open"])])]}
    res = build_target_liveboard(_inv([src], [_member("[dim_case.status]", ["Open", "Closed"])]), _target(),
                                 drills=[drill])
    lb = res["liveboard"]["liveboard"]
    vid = next(v["id"] for v in lb["visualizations"] if v.get("answer", {}).get("name") == "Case List")
    assert vid in lb["filters"][0]["excluded_visualizations"]
    no_obj_id = _target()
    no_obj_id.pop("obj_id")
    bare = build_target_liveboard(_inv([src]), no_obj_id, drills=[drill])
    # without an exported obj_id the drill table binds like every other tile (an obj_id derived
    # from the Model GUID), not by Model name alone
    assert _answers(bare)["Case List"]["tables"] == _answers(bare)["Cases by Site"]["tables"]
    assert _answers(bare)["Case List"]["tables"][0]["obj_id"].endswith("-11111111")


def test_disabled_filters_are_not_applied_and_are_reported():
    from ts_cli.sisense.parsing import parse_dashboard, parse_widget
    raw = {"oid": "w1", "title": "Visits", "type": "indicator", "metadata": {"panels": [
        {"name": "value", "items": [{"jaql": {"dim": "[fact_visit.case_id_]", "agg": "count", "title": "#"}}]},
        {"name": "filters", "items": [{"disabled": True, "jaql": {"dim": "[dim_case.status]",
                                                                   "filter": {"members": ["Open"]}}}]}]}}
    w = parse_widget(raw, [])
    assert w["filters"] == [] and w["disabled_filters"] == ["[dim_case.status]"]
    dash = parse_dashboard({"title": "D", "filters": [{"disabled": True, "jaql": {"dim": "[dim_case.status]",
                                                                               "filter": {"members": ["Open"]}}}]}, [])
    assert dash["filters"] == [] and dash["disabled_filters"] == ["[dim_case.status]"]
    res = build_target_liveboard(_inv([w], [])  | {"dashboard": dict(dash, layout=[])}, _target())
    assert "disabled widget filter" in _row(res, "Visits")["note"] and _row(res, "Visits")["status"] == "Migrated"
    assert any(r["status"] == "Skipped" and "disabled in Sisense" in r["note"] for r in _chip_rows(res))


def test_widget_ignoring_a_dashboard_filter_is_excluded_from_its_chip():
    ign = dict(_visits(), ignore={"all": False, "dimensions": ["[dim_case.status]"], "ids": []})
    res = build_target_liveboard(_inv([ign], [_member("[dim_case.status]", ["Open"])]), _target())
    lb = res["liveboard"]["liveboard"]
    assert lb["filters"][0]["excluded_visualizations"] == [lb["visualizations"][0]["id"]]
    assert _row(res, "Visits")["status"] == "Migrated"
    by_id = dict(_visits(), ignore={"all": False, "dimensions": [], "ids": ["f-1"]})
    chip = dict(_member("[dim_case.status]", ["Open"]), instanceids=["f-1"])
    lb2 = build_target_liveboard(_inv([by_id], [chip]), _target())["liveboard"]["liveboard"]
    assert lb2["filters"][0]["excluded_visualizations"] == [lb2["visualizations"][0]["id"]]


def test_highlight_mode_on_a_plotted_column_is_needs_review():
    w = _w("w1", "By status", "chart/column", [_f("[dim_case.status]", "categories"),
                                               _f("[fact_visit.case_id_]", "values", "measure", "count")],
           filters_mode="select")
    res = build_target_liveboard(_inv([w], [_member("[dim_case.status]", ["Open"])]), _target())
    assert _row(res, "By status")["status"] == "NEEDS REVIEW" and "Highlight" in _row(res, "By status")["note"]
    # a column the widget does not plot filters normally even in Highlight mode
    res2 = build_target_liveboard(_inv([dict(w, fields=[_f("[fact_visit.case_id_]", "value", "measure", "count")])],
                                       [_member("[dim_case.status]", ["Open"])]), _target())
    assert _row(res2, "By status")["status"] == "Migrated"


def test_mixed_bound_range_chip_and_unfiltered_chip_flag_their_tiles():
    res = build_target_liveboard(_inv([_visits()], [_range("[fact_visit.cost]", {"from": 10, "toNotEqual": 50})]),
                                 _target())
    assert any("one bound is inclusive" in r["note"] for r in _chip_rows(res))
    assert _row(res, "Visits")["status"] == "NEEDS REVIEW"
    rel = {"kind": "relative_date", "dim": "[Visit_Start_Date.date_day (Calendar)]", "operator": "last",
           "values": [{"count": 30}], "raw": {"last": {"count": 30}}}
    res2 = build_target_liveboard(_inv([_visits()], [rel]), _target())
    assert _row(res2, "Visits")["status"] == "NEEDS REVIEW" and "not carried exactly" in _row(res2, "Visits")["note"]


def test_chip_on_a_tile_whose_facts_or_path_cannot_be_determined_is_needs_review():
    two_facts = _w("w1", "Both", "pivot2", [_f("[fact_visit.cost]", "values", "measure", "sum"),
                                            _f("[fact_case_stats.visit_total]", "values", "measure", "sum")])
    res = build_target_liveboard(_inv([two_facts], [_member("[dim_case.status]", ["Open"])]), _target())
    assert _row(res, "Both")["status"] == "NEEDS REVIEW" and "could not be determined" in _row(res, "Both")["note"]


def test_aggregation_differing_from_a_model_formula_is_needs_review():
    # a hand-mapped formula is trusted; one found by name is checked against its aggregation too
    w = _w("w1", "Cases", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count"),
                                        _f("[fact_visit.case_id_]", "value", "measure", "avg")])
    res = build_target_liveboard(_inv([w]), _target())
    row = _row(res, "Cases")
    assert _answers(res)["Cases"]["search_query"] == "[Visit Case Count]"
    assert row["status"] == "NEEDS REVIEW"
    from ts_cli.sisense.target_answers import _Binder
    b = _Binder(_inv([w]), TargetModel(_target()), {})
    out = b._formula_measure("Visit Case Count", "[fact_visit.x]", "avg", "average")
    assert "which is a unique count" in out["note"]

def test_unread_settings_on_a_widget_or_filter_are_needs_review():
    w = dict(_visits(), unsupported=["jaql.someNewSetting"])
    assert "does not read" in _row(build_target_liveboard(_inv([w]), _target()), "Visits")["note"]
    odd = dict(_member("[dim_case.status]", ["Open"]), unsupported=["contains"])
    w2 = _w("w2", "Odd", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")], [odd])
    assert _row(build_target_liveboard(_inv([w2]), _target()), "Odd")["status"] == "NEEDS REVIEW"


def test_quick_function_secondary_value_and_percent_display_are_needs_review():
    qf = _w("w1", "Share", "chart/pie", [_f("[dim_site.name]", "categories"),
                                         dict(_f("[fact_visit.cost]", "values", "measure", "sum"), quick_function="Contribution")])
    assert "quick function" in _row(build_target_liveboard(_inv([qf]), _target()), "Share")["note"]
    sec = _w("w2", "KPI", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum"),
                                        _f("[fact_visit.case_id_]", "secondary", "measure", "count")])
    assert "secondary value" in _row(build_target_liveboard(_inv([sec]), _target()), "KPI")["note"]
    pct = _w("w3", "Pct", "indicator", [dict(_f("[fact_visit.cost]", "value", "measure", "sum"), percent=True)])
    assert "as a percent" in _row(build_target_liveboard(_inv([pct]), _target()), "Pct")["note"]


def test_weekly_bucket_with_a_sisense_week_start_is_needs_review():
    w = _w("w1", "Weekly", "chart/line", [dict(_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="weeks"),
                                               firstday="mon"),
                                          _f("[fact_visit.case_id_]", "values", "measure", "count")])
    assert "week start" in _row(build_target_liveboard(_inv([w]), _target()), "Weekly")["note"]


def test_backslash_in_a_filter_value_is_needs_review():
    w = _w("w1", "Odd", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_member("[dim_case.status]", ["a\\b"])])
    row = _row(build_target_liveboard(_inv([w]), _target()), "Odd")
    assert row["status"] == "NEEDS REVIEW" and "backslash" in row["note"]


def test_filter_map_with_no_column_is_needs_review():
    w = _w("w1", "Started", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_range("[Visit_Start_Date.id_]", {"from": 0})])
    row = _row(build_target_liveboard(_inv([w]), _target(),
                                      overrides={"filter_map": {"[Visit_Start_Date.id_]": "started = true"}}), "Started")
    assert row["status"] == "NEEDS REVIEW" and "names no [column]" in row["note"]


def test_db_column_lookup_is_case_insensitive_and_ambiguity_is_refused():
    target = _target()
    for c in target["model"]["columns"]:
        if c["name"] == "Case Status":
            c["column_id"] = "dim_case::Status Label"
    one = [{"table": {"name": "dim_case", "columns": [{"name": "Status Label", "db_column_name": "STATUS"}]}}]
    assert TargetModel(target, one).column("dim_case", "status") == "Case Status"
    two = [{"table": {"name": "dim_case", "columns": [{"name": "Status Label", "db_column_name": "STATUS"},
                                                      {"name": "Status 2", "db_column_name": "Status_"}]}}]
    assert TargetModel(target, two).column("dim_case", "status") is None


# --------------------------------------------------------------------------- adversarial review of round 3
def test_rank_on_a_dimension_that_is_not_the_widgets_only_dimension_is_needs_review():
    two_dims = _w("w1", "Sites", "chart/column", [_f("[dim_case.status]", "categories"), _f("[dim_site.name]", "break by"),
                                                  _f("[fact_visit.cost]", "values", "measure", "sum")], [_rank("top", 5)])
    other_dim = _w("w2", "Statuses", "chart/column", [_f("[dim_case.status]", "categories"),
                                                      _f("[fact_visit.cost]", "values", "measure", "sum")], [_rank("top", 5)])
    kpi = _w("w3", "Total", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")], [_rank("top", 5)])
    res = build_target_liveboard(_inv([two_dims, other_dim, kpi]), _target())
    for title in ("Sites", "Statuses", "Total"):
        row = _row(res, title)
        assert row["status"] == "NEEDS REVIEW" and "not the widget's only dimension" in row["note"], title
        assert "top 5" not in _answers(res)[title]["search_query"]
    zero = _row(build_target_liveboard(_inv([_ranked(_rank("top", 0))]), _target()), "Sites")
    assert zero["status"] == "NEEDS REVIEW" and "not a positive rank" in zero["note"]


def test_a_ranked_column_is_the_widgets_own_so_a_chip_on_it_excludes_the_tile():
    lb = build_target_liveboard(_inv([_ranked(_rank("top", 5))], [_member("[dim_site.name]", ["North"])]),
                                _target())["liveboard"]["liveboard"]
    assert lb["filters"][0]["excluded_visualizations"] == [lb["visualizations"][0]["id"]]


def test_role_copy_a_widget_with_no_fact_reaches_through_its_own_tables_is_needs_review():
    # Sisense joins dim_case to dim_site directly (Case Site); the fact's FK would pick Visit Site
    w = _w("w2", "Cases by site", "chart/column", [_f("[dim_site.name]", "categories"),
                                                   _f("[dim_case.source_pk]", "values", "measure", "count")])
    row = _row(build_target_liveboard(_inv([w]), _target()), "Cases by site")
    assert row["status"] == "NEEDS REVIEW" and "Sisense joins dim_site through Case Site" in row["note"]


def test_role_copy_reachable_directly_from_two_widget_tables_is_needs_review():
    w = _w("w1", "Tied", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_member("[dim_case.status]", ["Open"]), _exclude("[dim_site.name]", ["Test"])])
    row = _row(build_target_liveboard(_inv([w]), _target()), "Tied")
    assert row["status"] == "NEEDS REVIEW" and "cannot be decided" in row["note"]


def test_chip_on_a_role_copy_a_no_fact_tile_reaches_differently_is_needs_review():
    statuses = _w("w1", "Statuses", "pivot2", [_f("[dim_case.status]", "rows"),
                                               _f("[dim_case.source_pk]", "values", "measure", "count")])
    by_site = _w("w2", "Cost by site", "chart/column", [_f("[dim_site.name]", "categories"),
                                                         _f("[fact_visit.cost]", "values", "measure", "sum")])
    res = build_target_liveboard(_inv([statuses, by_site], [_member("[dim_site.name]", ["North"])]), _target())
    assert _row(res, "Statuses")["status"] == "NEEDS REVIEW"


def test_one_to_many_join_declared_on_the_dimension_side_keeps_the_fact_a_root():
    target = _target()
    tables = target["model"]["model_tables"]
    stats = next(t for t in tables if t["name"] == "fact_case_stats")
    stats.pop("joins")
    case = next(t for t in tables if t["name"] == "dim_case")
    case["joins"].append({"with": "fact_case_stats", "on": "[dim_case::id_] = [fact_case_stats::case_id_]",
                          "type": "LEFT_OUTER", "cardinality": "ONE_TO_MANY"})
    t = TargetModel(target)
    assert "fact_case_stats" in t.roots() and ("dim_case", "case_id_") in t.joins["fact_case_stats"]
    w = _w("w1", "Totals by site", "chart/column", [_f("[dim_site.name]", "categories"),
                                                     _f("[fact_case_stats.visit_total]", "values", "measure", "sum")])
    q = _answers(build_target_liveboard(_inv([w]), target))["Totals by site"]["search_query"]
    assert q == "[Case Site Name] sum [Case Visit Total]"


def test_drill_dashboards_own_filters_are_reported_not_applied():
    src = _w("w1", "Cases by Site", "pivot2",
             [_f("[dim_case.status]", "rows"), _f("[fact_visit.case_id_]", "values", "measure", "count")],
             drill_targets=["_drill"])
    drill = {"dashboard": {"title": "_drill", "filters": [_member("[dim_case.source_pk]", ["C1"])]},
             "widgets": [_w("d1", "Case List", "pivot2", [_f("[dim_case.source_pk]", "rows"),
                                                         _f("[fact_visit.cost]", "values", "measure", "sum")])]}
    res = build_target_liveboard(_inv([src]), _target(), drills=[drill])
    assert "C1" not in _answers(res)["Case List"]["search_query"]
    row = _row(res, "Case List")
    assert row["status"] == "NEEDS REVIEW" and "its own dashboard filters" in row["note"]


def test_source_filter_not_carried_to_the_drill_is_needs_review():
    rel = {"kind": "relative_date", "dim": "[Visit_Start_Date.date_day (Calendar)]", "operator": "last",
           "values": [{"count": 30}], "raw": {"last": {"count": 30}}}
    src = _w("w1", "Cases by Status", "pivot2",
             [_f("[dim_case.status]", "rows"), _f("[fact_visit.case_id_]", "values", "measure", "count")], [rel],
             drill_targets=["_drill"])
    drill = {"dashboard": {"title": "_drill"},
             "widgets": [_w("d1", "Case List", "pivot2", [_f("[dim_case.source_pk]", "rows")])]}
    row = _row(build_target_liveboard(_inv([src]), _target(), drills=[drill]), "Case List")
    # the source filter is bound in the drill widget's own context, and flagged there
    assert row["status"] == "NEEDS REVIEW" and "relative_date" in row["note"]


def test_two_filters_on_one_column_are_needs_review_not_ored():
    w = _w("w1", "Open", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_member("[dim_case.status]", ["Open", "Closed"]), _member("[dim_case.status]", ["Open"])])
    row = _row(build_target_liveboard(_inv([w]), _target()), "Open")
    assert row["status"] == "NEEDS REVIEW" and "2 filters on [Case Status]" in row["note"]


def test_hidden_tab_differing_in_any_setting_is_not_merged():
    m = _f("[fact_visit.cost]", "values", "measure", "sum")
    shown = _w("wm", "By month", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months"), m])
    for tweak in ({"fields": [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="years"),
                              dict(m, quick_function="RSUM")]},
                  {"fields": [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="years"), m],
                   "ignore": {"all": True, "dimensions": [], "ids": []}},
                  {"fields": [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="years"), m],
                   "filters_mode": "select"}):
        hidden = dict(_w("wy", "By year", "chart/line", []), **tweak)
        tab = _w("wt", "Trend", "WidgetsTabber", [],
                 tabber={"tabs": [{"title": "M", "show": ["wm"]}, {"title": "Y", "show": ["wy"]}], "active": 0})
        assert tabber_hidden([tab, shown, hidden]) == {}, tweak


def test_grain_of_a_tab_that_produced_no_tile_is_needs_review_not_merged():
    m = _f("[fact_visit.case_id_]", "values", "measure", "avg")       # avg of a key: not bindable
    d = "[dim_case.opened (Calendar)]"                                 # not exposed on the Model
    shown = _w("wm", "By month", "chart/line", [_f(d, "x-axis", level="months"), m])
    hidden = _w("wy", "By year", "chart/line", [_f(d, "x-axis", level="years"), m])
    tab = _w("wt", "Trend", "WidgetsTabber", [],
             tabber={"tabs": [{"title": "M", "show": ["wm"]}, {"title": "Y", "show": ["wy"]}], "active": 0})
    res = build_target_liveboard(_inv([tab, shown, hidden]), _target())
    assert _row(res, "By year")["status"] == "NEEDS REVIEW"


def test_table_tml_mapping_decides_and_never_falls_back_to_another_warehouse_column():
    tables = [{"table": {"name": "fact_visit", "columns": [{"name": "cost", "db_column_name": "GROSS_COST"},
                                                           {"name": "Net Cost", "db_column_name": "cost"}]}}]
    assert TargetModel(_target(), tables).column("fact_visit", "cost") is None


def test_unmapped_date_level_is_needs_review():
    w = _w("w1", "By minute", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="minutes"),
                                             _f("[fact_visit.cost]", "values", "measure", "sum")])
    row = _row(build_target_liveboard(_inv([w]), _target()), "By minute")
    assert row["status"] == "NEEDS REVIEW" and "no ThoughtSpot bucket" in row["note"]


def test_partly_parsed_widget_and_unreadable_dashboard_filter_are_flagged():
    from ts_cli.sisense.parsing import parse_dashboard, parse_widget
    raw = {"oid": "w1", "title": "Odd", "type": "indicator", "metadata": {"panels": [
        {"name": "value", "items": [{"jaql": {"dim": "[fact_visit.cost]", "agg": "sum"}}]},
        {"name": "filters", "items": [{"jaql": {"dim": "[dim_case.status]", "filter": {"exclude": ["Closed"]}}}]}]}}
    w = parse_widget(raw, [])
    assert any(u.startswith("unreadable item") for u in w["unsupported"])
    dash = parse_dashboard({"title": "D", "filters": [{"jaql": {"dim": "[dim_case.status]", "filter": {"exclude": ["x"]}}}],
                            "layout": {"columns": [{"width": "auto", "cells": []}]}}, [])
    assert dash["unreadable_filters"] == ["[dim_case.status]"]
    res = build_target_liveboard(_inv([_visits()]) | {"dashboard": dict(dash, layout=[])}, _target())
    assert _row(res, "Visits")["status"] == "NEEDS REVIEW"


def test_null_members_and_contradictory_ranges_are_needs_review():
    null = _w("w1", "Null", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
              [_member("[dim_case.status]", [None, "Open"])])
    assert "null" in _row(build_target_liveboard(_inv([null]), _target()), "Null")["note"]
    both = _w("w2", "Both", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
              [_range("[fact_visit.cost]", {"equals": 10, "to": 5})])
    assert "no single meaning" in _row(build_target_liveboard(_inv([both]), _target()), "Both")["note"]


def test_two_dashboard_filters_on_one_column_are_needs_review():
    res = build_target_liveboard(_inv([_visits()], [_member("[dim_case.status]", ["Open"]),
                                                   _exclude("[dim_case.status]", ["Closed"])]), _target())
    assert any("two dashboard filters" in r["note"] for r in _chip_rows(res))
    assert _row(res, "Visits")["status"] == "NEEDS REVIEW"


# --------------------------------------------------------------------------- adversarial review 2
def _plain_visit_site():
    """The fixture with the visit-role copy as the plain `dim_site` instance (no alias)."""
    target = _target()
    for mt in target["model"]["model_tables"]:
        if mt.get("alias") == "Visit Site":
            mt.pop("alias")
        for j in mt.get("joins") or []:
            if j["with"] == "Visit Site":
                j["with"] = "dim_site"
    for c in target["model"]["columns"]:
        if c.get("column_id") == "Visit Site::name":
            c.update(name="Site Name", column_id="dim_site::name")
    return target


def test_role_check_runs_when_one_copy_is_the_unaliased_base_table():
    w = _w("w1", "Cases by site", "chart/column", [_f("[dim_site.name]", "categories"),
                                                   _f("[dim_case.source_pk]", "values", "measure", "count")])
    row = _row(build_target_liveboard(_inv([w]), _plain_visit_site()), "Cases by site")
    assert row["status"] == "NEEDS REVIEW"
    tile = _w("w2", "Statuses", "pivot2", [_f("[dim_case.status]", "rows"),
                                          _f("[dim_case.source_pk]", "values", "measure", "count")])
    res = build_target_liveboard(_inv([tile], [_member("[dim_site.name]", ["North"])]), _plain_visit_site())
    assert _row(res, "Statuses")["status"] == "NEEDS REVIEW"


def test_sisense_relation_the_model_does_not_join_is_needs_review():
    inv = _inv([_w("w1", "Totals by site", "chart/column", [_f("[dim_site.name]", "categories"),
                                                             _f("[fact_case_stats.visit_total]", "values", "measure", "sum")])])
    inv["relations"] = RELATIONS + [_rel("fact_case_stats", "site_id_", "dim_site", "id_")]
    row = _row(build_target_liveboard(inv, _target()), "Totals by site")
    assert row["status"] == "NEEDS REVIEW" and "fact_case_stats.site_id_" in row["note"]


def test_widget_spanning_two_facts_is_needs_review():
    two = _w("w1", "Both", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="years"),
                                          _f("[fact_visit.cost]", "values", "measure", "sum"),
                                          _f("[fact_case_stats.visit_total]", "values", "measure", "sum")])
    via_filter = _w("w2", "Stats", "pivot2", [_f("[dim_case.status]", "rows"),
                                               _f("[fact_case_stats.visit_total]", "values", "measure", "sum")],
                    [_range("[fact_visit.cost]", {"from": 100})])
    res = build_target_liveboard(_inv([two, via_filter]), _target())
    assert _row(res, "Both")["status"] == "NEEDS REVIEW" and "multi-fact" in _row(res, "Both")["note"]
    assert _row(res, "Stats")["status"] == "NEEDS REVIEW"          # (its cost filter is on a measure, too)


def test_rank_at_another_date_level_than_the_plotted_one_is_needs_review():
    d = "[Visit_Start_Date.date_day (Calendar)]"
    rank = dict(_rank("top", 3), dim=d, level="years")
    w = _w("w1", "Top years", "chart/column", [_f(d, "categories", level="months"),
                                               _f("[fact_visit.cost]", "values", "measure", "sum")], [rank])
    row = _row(build_target_liveboard(_inv([w]), _target()), "Top years")
    assert row["status"] == "NEEDS REVIEW" and "top 3" not in _answers(build_target_liveboard(_inv([w]), _target()))["Top years"]["search_query"]


def test_calculated_dimension_never_binds_a_measure_formula():
    target = _target()
    target["model"]["formulas"].append({"id": "formula_margin", "name": "margin", "expr": "sum ( [fact_visit::cost] )"})
    target["model"]["columns"].append({"name": "margin", "formula_id": "formula_margin",
                                       "properties": {"column_type": "MEASURE"}})
    inv = _inv([_w("w1", "By margin", "pivot2", [_f("[fact_visit.margin]", "rows"),
                                                  _f("[fact_visit.case_id_]", "values", "measure", "count")])])
    inv["tables"] = [dict(t, calculated_columns=["margin"]) if t["jaql_name"] == "fact_visit" else t for t in inv["tables"]]
    row = _row(build_target_liveboard(inv, target), "By margin")
    assert row["status"] == "NEEDS REVIEW" and "not exposed" in row["note"]


def test_count_formula_on_the_base_name_is_not_used_for_another_copy():
    target = _plain_visit_site()
    target["model"]["formulas"].append({"id": "formula_Visit Sites", "name": "Visit Sites",
                                        "expr": "unique count ( [dim_site::id_] )"})
    target["model"]["columns"].append({"name": "Visit Sites", "formula_id": "formula_Visit Sites",
                                       "properties": {"column_type": "MEASURE"}})
    t = TargetModel(target)
    assert t.count_measure("unique count", "dim_site", "id_") == "Visit Sites"
    assert t.count_measure("unique count", "Case Site", "id_") is None


def test_merged_grain_of_a_flagged_tile_is_needs_review_and_unmapped_levels_never_merge():
    m = _f("[fact_visit.cost]", "values", "measure", "sum")
    shown = _w("wm", "Cost (Monthly)", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months"), m],
               unsupported=["jaql.someNewSetting"])
    hidden = dict(shown, oid="wy", title="Cost (Yearly)",
                  fields=[_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="years"), m])
    tab = _w("wt", "Cost", "WidgetsTabber", [],
             tabber={"tabs": [{"title": "M", "show": ["wm"]}, {"title": "Y", "show": ["wy"]}], "active": 0})
    assert _row(build_target_liveboard(_inv([tab, shown, hidden]), _target()), "Cost (Yearly)")["status"] == "NEEDS REVIEW"
    minutes = dict(hidden, unsupported=None, fields=[_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="minutes"), m])
    assert tabber_hidden([tab, dict(shown, unsupported=None), minutes]) == {}


def test_filter_map_owns_its_sisense_column_and_counts_with_native_filters():
    w = _w("w1", "Open", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_member("[dim_case.status]", ["Open", "Pending"])])
    ov = {"filter_map": {"[dim_case.status]": "[Case ID] != 'X'"}}
    lb = build_target_liveboard(_inv([w], [_member("[dim_case.status]", ["Closed"])]), _target(),
                                overrides=ov)["liveboard"]["liveboard"]
    assert lb["filters"][0]["excluded_visualizations"] == [lb["visualizations"][0]["id"]]
    both = _w("w2", "Both", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
              [_range("[Visit_Start_Date.id_]", {"from": 0}), _member("[dim_case.status]", ["Open"])])
    ov2 = {"filter_map": {"[Visit_Start_Date.id_]": "[Case Status] = 'Escalated'"}}
    row = _row(build_target_liveboard(_inv([both]), _target(), overrides=ov2), "Both")
    assert row["status"] == "NEEDS REVIEW" and "2 filters on [Case Status]" in row["note"]


def test_measure_filter_and_unread_dashboard_filter_keys_are_needs_review():
    from ts_cli.sisense.parsing import parse_dashboard, parse_widget
    raw = {"oid": "w1", "title": "Big", "type": "indicator", "metadata": {"panels": [
        {"name": "value", "items": [{"jaql": {"dim": "[fact_visit.case_id_]", "agg": "count"}}]},
        {"name": "filters", "items": [{"jaql": {"dim": "[fact_visit.cost]", "agg": "sum", "filter": {"from": 100}}}]}]}}
    w = parse_widget(raw, [])
    assert w["filters"][0]["agg"] == "sum"
    assert "aggregate" in _row(build_target_liveboard(_inv([w]), _target()), "Big")["note"]
    dash = parse_dashboard({"title": "D", "filters": [{"jaql": {"dim": "[dim_case.status]", "somethingNew": 1,
                                                               "filter": {"members": ["Open"]}}}]}, [])
    assert dash["filters"][0]["unsupported"] == ["jaql.somethingNew"]


def test_unknown_filters_mode_and_drill_settings_are_needs_review():
    w = dict(_visits(), filters_mode="slice")
    res = build_target_liveboard(_inv([w], [_member("[dim_case.status]", ["Open"])]), _target())
    assert "'slice'" in _row(res, "Visits")["note"]
    src = _w("w1", "Cases by Status", "pivot2", [_f("[dim_case.status]", "rows"),
                                                 _f("[fact_visit.case_id_]", "values", "measure", "count")],
             drill_targets=["_drill"], drill_filter_settings=["includeDashFilterDims"])
    drill = {"dashboard": {"title": "_drill"}, "widgets": [_w("d1", "Case List", "pivot2", [_f("[dim_case.source_pk]", "rows")])]}
    row = _row(build_target_liveboard(_inv([src]), _target(), drills=[drill]), "Case List")
    assert row["status"] == "NEEDS REVIEW" and "includeDashFilterDims" in row["note"]


def test_a_clean_drill_table_is_approximated_not_migrated():
    src = _w("w1", "Cases by Status", "pivot2", [_f("[dim_case.status]", "rows"),
                                                 _f("[fact_visit.case_id_]", "values", "measure", "count")],
             drill_targets=["_drill"])
    drill = {"dashboard": {"title": "_drill"}, "widgets": [_w("d1", "Case List", "pivot2", [_f("[dim_case.source_pk]", "rows")])]}
    assert _row(build_target_liveboard(_inv([src]), _target(), drills=[drill]), "Case List")["status"] == "Approximated"


def test_hundred_percent_stack_is_needs_review_on_both_paths():
    from ts_cli.sisense.answers import chart_type_for
    for wt, st in (("chart/area", "area/stacked100"), ("chart/column", "column/stackedcolumn100")):
        assert chart_type_for(wt, st)[1] == "NEEDS REVIEW"
    assert chart_type_for("chart/column", "column/stackedcolumn") == ("STACKED_COLUMN", "Migrated", "stacked subtype")


def test_weeks_without_a_sisense_week_start_and_non_text_members_are_needs_review():
    w = _w("w1", "Weekly", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="weeks"),
                                          _f("[fact_visit.case_id_]", "values", "measure", "count")])
    assert "week start" in _row(build_target_liveboard(_inv([w]), _target()), "Weekly")["note"]
    odd = _w("w2", "Odd", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
             [_member("[dim_case.status]", [True])])
    assert "boolean or decimal" in _row(build_target_liveboard(_inv([odd]), _target()), "Odd")["note"]


def test_layout_widths_stay_inside_the_grid():
    ws = [_w(f"w{i}", f"V{i}", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")]) for i in range(8)]
    layout = [{"col": 0, "items": [{"oid": f"w{i}", "width_pct": 20, "height_px": 100, "col_pct": 33.3} for i in range(5)]},
              {"col": 1, "items": [{"oid": "w5", "width_pct": 100, "height_px": 100, "col_pct": 30}]},
              {"col": 2, "items": [{"oid": "w6", "width_pct": 100, "height_px": 100, "col_pct": 40}]}]
    tiles = build_target_liveboard(_inv(ws, layout=layout), _target())["liveboard"]["liveboard"]["layout"]["tiles"]
    assert all(t["width"] >= 1 and t["x"] + t["width"] <= 12 for t in tiles)


def test_malformed_widget_settings_flag_the_widget_instead_of_crashing():
    from ts_cli.sisense.parsing import parse_widget
    raw = {"oid": "w1", "title": "Odd", "type": "indicator", "metadata": {"ignore": "all", "panels": [
        {"name": "value", "items": [{"jaql": {"dim": "[fact_visit.cost]", "agg": "sum"}}]}]}}
    w = parse_widget(raw, [])
    assert any(u.startswith("unreadable setting") for u in w["unsupported"])


# --------------------------------------------------------------------------- adversarial review 3
def test_dimension_bound_to_a_model_measure_column_is_needs_review():
    for wtype, fields in (("pivot2", [_f("[fact_visit.cost]", "rows"), _f("[fact_visit.case_id_]", "values", "measure", "count")]),
                          ("tablewidget", [_f("[dim_case.source_pk]", "columns"), _f("[fact_visit.cost]", "columns")])):
        row = _row(build_target_liveboard(_inv([_w("w1", "T", wtype, fields)]), _target()), "T")
        assert row["status"] == "NEEDS REVIEW" and "is a measure" in row["note"], wtype


def _no_dim_join_model():
    """fact_visit joins dim_case and dim_site; dim_case does NOT join dim_site (Sisense does)."""
    target = _plain_visit_site()
    for mt in target["model"]["model_tables"]:
        if mt["name"] == "dim_case":
            mt["joins"] = [j for j in mt.get("joins") or [] if j["with"] != "Case Site"]
    target["model"]["model_tables"] = [mt for mt in target["model"]["model_tables"] if mt.get("alias") != "Case Site"]
    target["model"]["columns"] = [c for c in target["model"]["columns"] if not c.get("column_id", "").startswith("Case Site::")]
    return target


def test_widget_or_chip_with_no_fact_relating_dimensions_sisense_joins_directly_is_needs_review():
    target = _no_dim_join_model()
    sites = _w("w1", "Sites", "tablewidget", [_f("[dim_site.name]", "columns")])
    w_filter = dict(sites, filters=[_member("[dim_case.status]", ["Open"])])
    assert _row(build_target_liveboard(_inv([w_filter]), target), "Sites")["status"] == "NEEDS REVIEW"
    chip = build_target_liveboard(_inv([sites], [_member("[dim_case.status]", ["Open"])]), target)
    assert _row(chip, "Sites")["status"] == "NEEDS REVIEW"
    counted = _w("w2", "Statuses per site", "pivot2", [_f("[dim_site.name]", "rows"),
                                                       _f("[dim_case.status]", "values", "measure", "count")])
    assert _row(build_target_liveboard(_inv([counted]), target), "Statuses per site")["status"] == "NEEDS REVIEW"
    # the aliased fixture: a chip on a dimension-only tile is caught too
    res = build_target_liveboard(_inv([sites], [_member("[dim_case.status]", ["Open"])]), _target())
    assert _row(res, "Sites")["status"] == "NEEDS REVIEW"


def test_relation_that_is_not_one_column_to_one_column_is_needs_review():
    inv = _inv([_w("w1", "Cost by site", "chart/column", [_f("[dim_site.name]", "categories"),
                                                          _f("[fact_visit.cost]", "values", "measure", "sum")])])
    inv["relations"] = RELATIONS + [{"endpoints": [{"table": "fact_visit", "column": "site_id_"},
                                                   {"table": "dim_site", "column": "id_"},
                                                   {"table": "dim_case", "column": "site_id_"}]}]
    row = _row(build_target_liveboard(inv, _target()), "Cost by site")
    assert row["status"] == "NEEDS REVIEW" and "not one column to one column" in row["note"]


def test_drill_binds_source_filters_in_the_drill_widgets_own_context():
    src = _w("w1", "Totals", "pivot2", [_f("[dim_case.status]", "rows"),
                                        _f("[fact_case_stats.visit_total]", "values", "measure", "sum")],
             [_member("[dim_site.name]", ["North"])], drill_targets=["_drill"])
    drill = {"dashboard": {"title": "_drill"},
             "widgets": [_w("d1", "Visits", "pivot2", [_f("[Visit_Start_Date.date_day (Calendar)]", "rows", level="days"),
                                                     _f("[fact_visit.cost]", "values", "measure", "sum")])]}
    q = _answers(build_target_liveboard(_inv([src]), _target(), drills=[drill]))["Visits"]["search_query"]
    assert "[Visit Site Name] = 'North'" in q and "Case Site Name" not in q


def test_boxplot_and_unknown_widget_types_are_needs_review():
    from ts_cli.sisense.answers import chart_type_for
    assert chart_type_for("chart/boxplot", "")[1] == "NEEDS REVIEW"
    assert chart_type_for("histogramwidget", "")[1] == "NEEDS REVIEW"


def test_ranked_tab_is_never_a_grain_variant():
    d = "[Visit_Start_Date.date_day (Calendar)]"
    rank = dict(_rank("top", 5), dim=d, level="months")
    shown = _w("wm", "M", "chart/line", [_f(d, "x-axis", level="months"), _f("[fact_visit.cost]", "values", "measure", "sum")], [rank])
    hidden = dict(shown, oid="wd", title="D", fields=[_f(d, "x-axis", level="days"), _f("[fact_visit.cost]", "values", "measure", "sum")])
    tab = _w("wt", "T", "WidgetsTabber", [], tabber={"tabs": [{"title": "M", "show": ["wm"]}, {"title": "D", "show": ["wd"]}], "active": 0})
    assert tabber_hidden([tab, shown, hidden]) == {}


def test_hidden_tab_with_its_own_drill_is_not_merged():
    d = "[Visit_Start_Date.date_day (Calendar)]"
    m = _f("[fact_visit.cost]", "values", "measure", "sum")
    shown = _w("wm", "M", "chart/line", [_f(d, "x-axis", level="months"), m])
    hidden = dict(_w("wd", "D", "chart/line", [_f(d, "x-axis", level="days"), m]), drill_targets=["_drill"])
    tab = _w("wt", "T", "WidgetsTabber", [], tabber={"tabs": [{"title": "M", "show": ["wm"]}, {"title": "D", "show": ["wd"]}], "active": 0})
    assert tabber_hidden([tab, shown, hidden]) == {}


def test_source_ranking_and_unreadable_drill_filters_are_needs_review():
    src = _ranked(_rank("top", 3))
    src["drill_targets"] = ["_drill"]
    drill = {"dashboard": {"title": "_drill", "unreadable_filters": ["[dim_case.status]"]},
             "widgets": [_w("d1", "Case List", "pivot2", [_f("[dim_case.source_pk]", "rows")])]}
    row = _row(build_target_liveboard(_inv([src]), _target(), drills=[drill]), "Case List")
    assert row["status"] == "NEEDS REVIEW" and "(ranking)" in row["note"] and "(unreadable)" in row["note"]


def test_too_many_subcells_for_a_narrow_column_stay_inside_the_grid():
    ws = [_w(f"w{i}", f"V{i}", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")]) for i in range(5)]
    layout = [{"col": 0, "items": [{"oid": "w0", "width_pct": 100, "height_px": 100, "col_pct": 83.4}]},
              {"col": 1, "items": [{"oid": f"w{i}", "width_pct": 25, "height_px": 100, "col_pct": 16.6} for i in range(1, 5)]}]
    tiles = build_target_liveboard(_inv(ws, layout=layout), _target())["liveboard"]["liveboard"]["layout"]["tiles"]
    assert all(t["width"] >= 1 and t["x"] + t["width"] <= 12 for t in tiles)


def test_missing_table_tmls_are_reported():
    res = build_target_liveboard(_inv([_visits()]), _target())
    assert any(r["visual"] == "(target model Tables)" and r["status"] == "NEEDS REVIEW" for r in res["visual_rows"])
    with_tables = build_target_liveboard(_inv([_visits()]), _target(), tables=[{"table": {"name": "x", "columns": []}}])
    assert not any(r["visual"] == "(target model Tables)" for r in with_tables["visual_rows"])



# --------------------------------------------------------------------------- adversarial review 4
def test_field_map_chooses_the_column_but_every_path_check_still_runs():
    pairs = _w("w1", "Pairs", "tablewidget", [_f("[dim_case.status]", "rows"), _f("[dim_site.name]", "rows")])
    row = _row(build_target_liveboard(_inv([pairs]), _target(), overrides={"field_map": {"[dim_site.name]": "Visit Site Name"}}),
               "Pairs")
    assert row["status"] == "NEEDS REVIEW"


def test_chip_with_field_map_is_still_checked_per_tile():
    wv = _w("wv", "Visit cost by status", "chart/column", [_f("[dim_case.status]", "categories"),
                                                         _f("[fact_visit.cost]", "values", "measure", "sum")])
    ws = _w("ws", "Stats by status", "chart/column", [_f("[dim_case.status]", "categories"),
                                                      _f("[fact_case_stats.visit_total]", "values", "measure", "sum")])
    res = build_target_liveboard(_inv([wv, ws], [_member("[dim_site.name]", ["North"])]), _target(),
                                 overrides={"field_map": {"[dim_site.name]": "Case Site Name"}})
    assert _row(res, "Visit cost by status")["status"] == "NEEDS REVIEW"


def test_formula_built_from_formulas_of_two_facts_spans_both():
    target = _target()
    target["model"]["formulas"] += [{"id": "formula_A", "name": "A", "expr": "sum ( [fact_visit::cost] )"},
                                    {"id": "formula_B", "name": "B", "expr": "sum ( [fact_case_stats::visit_total] )"},
                                    {"id": "formula_Combined", "name": "Combined", "expr": "[formula_A] + [formula_B]"}]
    target["model"]["columns"] += [{"name": n, "formula_id": f"formula_{n}", "properties": {"column_type": "MEASURE"}}
                                   for n in ("A", "B", "Combined")]
    assert TargetModel(target).instances_of["Combined"] == {"fact_visit", "fact_case_stats"}
    w = _w("w1", "Combined", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months"),
                                            _f("[fact_visit.combined]", "values", "measure", "sum")])
    row = _row(build_target_liveboard(_inv([w]), target, overrides={"field_map": {"[fact_visit.combined]": "Combined"}}),
               "Combined")
    assert row["status"] == "NEEDS REVIEW" and "multi-fact" in row["note"]


def test_two_sisense_facts_linking_a_no_fact_widget_is_a_tie_and_needs_review():
    inv = _inv([_w("w1", "Status by start", "tablewidget", [_f("[dim_case.status]", "rows"),
                                                           _f("[Visit_Start_Date.date_day (Calendar)]", "rows", level="months")])])
    inv["relations"] = RELATIONS + [_rel("fact_appt", "case_id_", "dim_case", "id_"),
                                    _rel("fact_appt", "date_id_", "Visit_Start_Date", "id_")]
    assert _row(build_target_liveboard(inv, _target()), "Status by start")["status"] == "NEEDS REVIEW"


def test_row_filter_on_a_measure_column_and_chip_on_one_are_needs_review():
    w = _w("w1", "Big", "chart/column", [_f("[dim_case.status]", "categories"),
                                         _f("[fact_visit.cost]", "values", "measure", "sum")],
           [_range("[fact_visit.cost]", {"from": 100})])
    assert "a Model measure" in _row(build_target_liveboard(_inv([w]), _target()), "Big")["note"]
    res = build_target_liveboard(_inv([_visits()], [_member("[fact_visit.cost]", ["100"])]), _target())
    assert _row(res, "Visits")["status"] == "NEEDS REVIEW"


def test_chip_on_a_multi_endpoint_relation_table_is_needs_review():
    inv = _inv([_w("w1", "Total", "indicator", [_f("[fact_case_stats.visit_total]", "value", "measure", "sum")])],
               [_member("[dim_site.name]", ["North"])])
    inv["relations"] = [RELATIONS[0], RELATIONS[3], RELATIONS[4],
                        {"endpoints": [{"table": "dim_case", "column": "site_id_"}, {"table": "dim_site", "column": "id_"},
                                       {"table": "fact_appt", "column": "site_id_"}]}]
    res = build_target_liveboard(inv, _target())
    assert _row(res, "Total")["status"] == "NEEDS REVIEW"


def test_additive_measure_on_a_non_fact_table_across_a_join_is_needs_review():
    target = _target()
    target["model"]["columns"].append({"name": "Case Value", "column_id": "dim_case::value",
                                       "properties": {"column_type": "MEASURE", "aggregation": "SUM"}})
    w = _w("w1", "Value by month", "chart/line", [_f("[Visit_Start_Date.date_day (Calendar)]", "x-axis", level="months"),
                                                  _f("[dim_case.value]", "values", "measure", "sum")])
    assert _row(build_target_liveboard(_inv([w]), target), "Value by month")["status"] == "NEEDS REVIEW"


def test_chip_and_widget_filter_on_different_dims_bound_to_one_column_is_needs_review():
    w = _w("w1", "Open", "indicator", [_f("[fact_visit.case_id_]", "value", "measure", "count")],
           [_member("[dim_case.status]", ["Open"])])
    res = build_target_liveboard(_inv([w], [_member("[dim_case.status_code]", ["Closed"])]), _target(),
                                 overrides={"field_map": {"[dim_case.status_code]": "Case Status"}})
    assert _row(res, "Open")["status"] == "NEEDS REVIEW"


def test_widget_on_another_data_source_and_parse_warnings_are_needs_review():
    inv = _inv([dict(_visits(), datasource="OtherCube")])
    inv["dashboard"]["datasource"] = "Acme"
    inv["warnings"] = ["A relation had no resolvable endpoints; skipped."]
    res = build_target_liveboard(inv, _target())
    assert "OtherCube" in _row(res, "Visits")["note"] and _row(res, "Visits")["status"] == "NEEDS REVIEW"
    assert any(r["visual"] == "(parse warning)" for r in res["visual_rows"])
