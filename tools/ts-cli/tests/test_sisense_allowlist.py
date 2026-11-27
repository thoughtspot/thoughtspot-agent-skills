"""The Sisense-side allowlist (ts_cli.sisense.allowlist) and the filter-key combinations the
parser refuses: every level of a dashboard export, not only the panel items. Pure, synthetic."""
from ts_cli.sisense.allowlist import (dashboard_unsupported, datamodel_unsupported, drill_unsupported,
                                      relation_problem, script_problem, table_physical, table_unsupported,
                                      widget_info, widget_unsupported)
from ts_cli.sisense.parsing import _classify_filter, parse_inventory
from ts_cli.sisense.target_filters import is_all

from tests.test_sisense_target_answers import (_f, _inv, _row, _target, _w,
                                               build_target_liveboard)

_BEFOREQUERY = ("widget.on('beforequery', function (w, ev) { ev.query.metadata.push({jaql: "
                "{dim: '[dim_case.status]', filter: {members: ['Open']}}}); });")


def _widget(**extra):
    w = {"oid": "w1", "title": "Cost", "type": "indicator", "subtype": "indicator/numeric",
         "metadata": {"panels": [{"name": "value", "items": [{"jaql": {"dim": "[fact_visit.cost]", "agg": "sum"}}]}],
                      "ignore": {"all": False, "dimensions": [], "ids": []}},
         "options": {"dashboardFiltersMode": "filter", "selector": False}, "style": {}}
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(w.get(key), dict):
            w[key] = dict(w[key], **value)
        else:
            w[key] = value
    return w


# --------------------------------------------------------------------------- scripts
def test_a_script_with_code_is_refused_and_a_comment_only_one_is_not():
    assert script_problem(_BEFOREQUERY)
    assert script_problem("/* widget.on('beforequery', ...) */\n// nothing runs\n") is None
    assert script_problem("") is None and script_problem(None) is None


def test_comment_markers_inside_strings_cannot_empty_a_script():
    # naive stripping only ever removes MORE, and the string's opening quote survives
    assert script_problem('var u = "http://x"; widget.on("beforequery", f);')
    assert script_problem('"/*"; widget.on("beforequery", f); "*/"')


def test_widget_script_rewriting_the_query_makes_the_tile_needs_review():
    # review round 4, blocker 3: the script adds a filter Sisense applies and the tile would not
    bundle = {"dashboard": {"title": "Acme", "filters": []}, "widgets": [_widget(script=_BEFOREQUERY)]}
    inv = parse_inventory(bundle)
    assert "script" in inv["widgets"][0]["unsupported"]
    built = dict(_inv(inv["widgets"]), dashboard={"title": "Acme", "filters": []})
    row = _row(build_target_liveboard(built, _target()), "Cost")
    assert row["status"] == "NEEDS REVIEW" and "script" in row["note"]


def test_dashboard_script_flags_every_tile():
    raw = {"title": "Acme", "filters": [], "script": "dashboard.on('widgetbeforequery', function (d, a) {});"}
    assert dashboard_unsupported(raw) == ["script"]
    inv = _inv([_w("w1", "Cost", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")])])
    inv["dashboard"]["unsupported"] = ["script"]
    res = build_target_liveboard(inv, _target())
    assert _row(res, "Cost")["status"] == "NEEDS REVIEW"
    assert _row(res, "(dashboard settings)")["status"] == "NEEDS REVIEW"


# --------------------------------------------------------------------------- levels
def test_presentation_keys_pass_and_unknown_keys_are_reported_at_every_level():
    assert widget_unsupported(_widget(desc="x", lastOpened="t", viewState={"activeTab": "design"})) == []
    out = widget_unsupported(_widget(newSetting=1, options={"newOption": 1}, style={"newStyle": 1},
                                     metadata={"newMeta": 1}))
    assert {"newSetting", "options.newOption", "style.newStyle", "metadata.newMeta"} <= set(out)
    assert dashboard_unsupported({"title": "A", "desc": "", "settings": {}, "newKey": 1}) == ["newKey"]


def test_number_changing_style_keys_pass_only_at_their_default():
    assert widget_unsupported(_widget(style={"dataLimits": {"categoriesCapacity": 100000, "seriesCapacity": 50},
                                             "rowsGrandTotal": False})) == []
    w = _widget(style={"dataLimits": {"seriesCapacity": 50}})
    assert widget_unsupported(w) == [] and widget_info(w) == []   # no series plotted: the cap cuts nothing
    w["metadata"]["panels"][0]["name"] = "values"
    w["metadata"]["panels"].append({"name": "break by", "items": [{"jaql": {"dim": "[d.c]"}}]})
    w["type"] = "chart/bar"
    assert widget_unsupported(w) == [] and "at most 50 break-by series" in widget_info(w)[0]
    out = widget_unsupported(_widget(style={"dataLimits": {"seriesCapacity": 5}, "rowsGrandTotal": True,
                                            "columnsGrandTotal": True,
                                            "convolution": {"enabled": True, "independentSlicesCount": 7}}))
    assert any(u.startswith("style.rowsGrandTotal=") for u in out)
    assert any(u.startswith("style.columnsGrandTotal=") for u in out)
    assert any(u.startswith("style.convolution") for u in out)
    assert widget_unsupported(_widget(style={"convolution": {"enabled": False}})) == []


def test_metadata_defaults_and_unknown_panels():
    assert widget_unsupported(_widget(metadata={"usedFormulasMapping": {}})) == []
    assert any(u.startswith("metadata.usedFormulasMapping=") for u in
               widget_unsupported(_widget(metadata={"usedFormulasMapping": {"a": "b"}})))
    w = _widget()
    w["metadata"]["panels"].append({"name": "trend", "items": []})
    assert "panel 'trend'" in widget_unsupported(w)


def test_show_nulls_and_selection_and_plugins():
    assert widget_unsupported(_widget(showNulls={}, selection=None)) == []
    assert any(u.startswith("showNulls=") for u in widget_unsupported(_widget(showNulls={"Status": False})))
    assert any(u.startswith("showNulls=") for u in widget_unsupported(_widget(showNulls={"Status": True})))
    assert any(u.startswith("selection=") for u in widget_unsupported(_widget(selection={"a": 1})))
    assert any(u.startswith("custom=") for u in widget_unsupported(_widget(custom={"barcolumnchart": {}})))


def test_drill_target_is_read_only_when_it_names_the_widgets_own_drill():
    drill = {"dashboardIds": [{"oid": "d1", "dashboardTitle": "_drill"}]}
    same = _widget(options={"drillTarget": {"oid": "d1", "caption": "_drill"}}, drillToDashboardConfig=drill)
    other = _widget(options={"drillTarget": {"oid": "d2", "caption": "_other"}}, drillToDashboardConfig=drill)
    assert widget_unsupported(same) == []
    assert any(u.startswith("options.drillTarget=") for u in widget_unsupported(other))
    assert widget_unsupported(_widget(options={"drillTarget": "dummy"})) == []


# --------------------------------------------------------------------------- data model
def test_table_physical_reads_simple_import_queries_and_refuses_anything_more():
    base = {"type": "base", "name": "fact_visit", "schemaName": "clinic"}
    assert table_physical(base) == ("clinic.fact_visit", None)
    assert table_physical(dict(base, configOptions={"importQuery": "select * from reporting.dim_date"})) == \
        ("reporting.dim_date", None)
    for q in ("select * from reporting.dim_date where id_ > 0", "select a, b from reporting.t",
              "select e.id from reporting.f e join reporting.d d on e.d = d.id"):
        physical, problem = table_physical(dict(base, configOptions={"importQuery": q}))
        assert physical is None and "import query" in problem
    assert table_physical(dict(base, type="custom"))[0] is None


def test_table_transformations_other_than_added_columns_are_reported():
    t = {"name": "f", "tupleTransformations": [{"type": "add-column"}, {"type": "dont-import"}, {"type": "filter"}],
         "configOptions": {"importQuery": "", "rowLimit": 5}}
    assert table_unsupported(t) == ["tupleTransformations[filter]", "configOptions.rowLimit"]


def test_relation_join_type_other_than_default_flags_every_tile():
    assert relation_problem({"type": None}) is None
    assert "LEFT" in relation_problem({"type": "LEFT"})
    inv = _inv([_w("w1", "Cost", "indicator", [_f("[fact_visit.cost]", "value", "measure", "sum")])])
    inv["relations"] = inv["relations"] + [dict(inv["relations"][0], problem=relation_problem({"type": "LEFT"}))]
    assert _row(build_target_liveboard(inv, _target()), "Cost")["status"] == "NEEDS REVIEW"


# --------------------------------------------------------------------------- filter combinations
def test_all_beside_a_condition_is_refused_not_read_as_no_condition():
    # review round 4, should-fix 5: {"all": true, "members": ["Open"]} was read as no condition
    sf = _classify_filter({"dim": "[dim_case.status]", "filter": {"all": True, "members": ["Open"]}})
    assert any(u.startswith("combination(all") for u in sf["unsupported"]) and not is_all(sf)


def test_two_condition_kinds_and_explicit_values_are_checked():
    two = _classify_filter({"dim": "[d.c]", "filter": {"members": ["a"], "exclude": {"members": ["b"]}}})
    assert any(u.startswith("combination(") for u in two["unsupported"])
    odd = _classify_filter({"dim": "[d.c]", "filter": {"members": ["a"], "explicit": False}})
    assert "explicit=False" in odd["unsupported"]
    fine = [_classify_filter({"dim": "[d.c]", "filter": f}) for f in
            ({"members": ["a"], "explicit": True, "multiSelection": True},
             {"exclude": {"members": ["b"]}, "explicit": False, "isCondition": True},
             {"all": True, "explicit": False, "multiSelection": True})]
    assert all(not sf.get("unsupported") for sf in fine)


def test_a_malformed_setting_is_reported_without_costing_the_widget_its_fields():
    for bad in ({"options": "x"}, {"drillToDashboardConfig": [1]}, {"metadata": {"panels": [], "ignore": {}}, "style": 3}):
        w = _widget(**bad) if "metadata" not in bad else dict(_widget(), style=3)
        inv = parse_inventory({"dashboard": {"title": "A", "filters": []}, "widgets": [w]})
        assert inv["widgets"][0]["fields"] and inv["widgets"][0].get("unsupported"), bad


def test_malformed_table_settings_are_reported_not_raised():
    for t in ({"type": "base", "name": "f", "configOptions": "x"},
              {"type": "base", "name": "f", "configOptions": {"importQuery": 5}}):
        physical, problem = table_physical(t)
        assert physical is None and problem
    bundle = {"datamodel": {"datasets": [{"database": "acme", "schema": {"tables": [
        {"type": "base", "name": "f", "configOptions": "x", "columns": []}]}}]}}
    assert parse_inventory(bundle)["tables"][0]["physical_problem"]


def test_the_dataset_database_prefixes_the_physical_name():
    assert table_physical({"type": "base", "name": "f", "schemaName": "s"}, "acme") == ("acme.s.f", None)
    assert table_physical({"type": "base", "name": "f", "configOptions": {"importQuery": "select * from r.t"}},
                          "acme") == ("acme.r.t", None)


# --------------------------------------------------------------------------- self-review of round 4's fixes
def test_a_comment_ended_by_any_javascript_line_terminator_does_not_hide_code():
    for end in ("\r", " ", " "):
        assert script_problem("// note" + end + _BEFOREQUERY), repr(end)


def test_a_table_whose_id_differs_from_its_name_has_no_known_source():
    physical, problem = table_physical({"type": "base", "id": "fact_visit_raw", "name": "fact_visit", "schemaName": "s"})
    assert physical is None and "fact_visit_raw" in problem
    assert table_physical({"type": "base", "id": "tq_x1", "name": "fact_visit", "schemaName": "s"}) == ("s.fact_visit", None)
    assert table_physical({"type": "base", "id": "f", "name": "f", "schemaName": "s"}) == ("s.f", None)


def test_an_accumulating_build_and_an_upsert_column_are_reported():
    assert table_unsupported({"name": "f", "buildBehavior": {"type": "sync", "accumulativeConfig": None}}) == []
    assert any(u.startswith("buildBehavior=") for u in
               table_unsupported({"name": "f", "buildBehavior": {"type": "accumulative", "accumulativeConfig": {}}}))
    assert any("isUpsertBy" in u for u in table_unsupported({"name": "f", "columns": [{"name": "c", "isUpsertBy": True}]}))


def test_data_model_dataset_relation_and_drill_levels_are_allowlisted():
    assert datamodel_unsupported({"title": "m", "relationType": "direct", "fiscal": "system",
                                  "datasets": [{"type": "live", "modelingTransformations": []}]}) == []
    out = datamodel_unsupported({"fiscal": "custom", "relationType": "other", "newKey": 1,
                                 "datasets": [{"modelingTransformations": [{"type": "x"}]}]})
    assert {"newKey"} <= set(out) and any(u.startswith("fiscal=") for u in out)
    assert any(u.startswith("dataset.modelingTransformations=") for u in out)
    assert relation_problem({"type": None, "columns": [{"table": "a", "column": "c", "isDropped": None}]}) is None
    assert "isDisabled" in relation_problem({"type": None, "isDisabled": True, "columns": []})
    assert drill_unsupported({"dashboardIds": [], "sameCubeRestriction": True, "forceZeroInsteadNull": False}) == []
    assert any(u.startswith("forceZeroInsteadNull=") for u in drill_unsupported({"forceZeroInsteadNull": True}))


def test_a_members_value_that_is_not_a_list_is_refused_not_split_into_characters():
    sf = _classify_filter({"dim": "[d.c]", "filter": {"members": "Open", "explicit": True}})
    assert sf["values"] == [] and "members (not a list)" in sf["unsupported"]


def test_panels_of_an_unlisted_widget_type_are_reported():
    assert "panels of widget type chart/polar (not read)" in widget_unsupported(_widget(type="chart/polar"))


def test_a_drill_dashboards_own_settings_make_its_table_needs_review():
    src = _w("w1", "Cases", "pivot2", [_f("[dim_case.status]", "rows"),
                                       _f("[fact_visit.cost]", "values", "measure", "sum")], drill_targets=["Detail"])
    detail = {"dashboard": {"title": "Detail", "filters": [], "unsupported": ["script"]},
              "widgets": [_w("d1", "Case list", "tablewidget", [_f("[dim_case.status]", "columns")])]}
    row = _row(build_target_liveboard(_inv([src]), _target(), drills=[detail]), "Case list")
    assert row["status"] == "NEEDS REVIEW" and "script" in row["note"]
    detail["dashboard"] = {"title": "Detail", "filters": [], "filter_settings": ["filterRelations"]}
    assert "filterRelations" in _row(build_target_liveboard(_inv([src]), _target(), drills=[detail]), "Case list")["note"]


def test_data_limits_are_read_by_shape():
    assert widget_unsupported(_widget(style={"dataLimits": {"categoriesCapacity": 100000, "seriesCapacity": 50}})) == []
    for limits in ({"categoriesCapacity": 3}, {"seriesCapacity": 5}, {"rowsCapacity": 2},
                   {"categoriesCapacity": "3"}, {"seriesCapacity": True}, 7):
        assert any(u.startswith("style.dataLimits") for u in widget_unsupported(_widget(style={"dataLimits": limits}))), limits


def test_the_dataset_database_goes_only_before_a_schema_and_table():
    assert table_physical({"type": "base", "id": "v", "name": "v"}, "clinic") == ("v", None)
    assert table_physical({"type": "base", "name": "f", "configOptions": {"importQuery": "select * from v"}},
                          "clinic") == ("v", None)
