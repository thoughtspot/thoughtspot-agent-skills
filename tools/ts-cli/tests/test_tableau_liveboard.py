"""Unit tests for the deterministic Tableau liveboard/answer emission engine."""
from ts_cli.tableau import liveboard as lb


# ── helpers ──────────────────────────────────────────────────────────────────

def test_chart_type_for_mark_common():
    assert lb.chart_type_for_mark("Bar")[0] == "BAR"
    assert lb.chart_type_for_mark("line")[0] == "LINE"
    assert lb.chart_type_for_mark("Circle")[0] == "SCATTER"
    assert lb.chart_type_for_mark("Pie")[0] == "PIE"


def test_chart_type_for_mark_text_is_grid():
    ct, status, note = lb.chart_type_for_mark("text")
    assert ct == "GRID_TABLE" and status == "Migrated" and "PIVOT_TABLE" in note


def test_chart_type_for_mark_non_visual_skips():
    assert lb.chart_type_for_mark("filter")[0] is None
    assert lb.chart_type_for_mark("legend")[0] is None


def test_chart_type_for_mark_unknown_defaults_grid_approx():
    ct, status, _ = lb.chart_type_for_mark("sankeycustom")
    assert ct == "GRID_TABLE" and status == "Approximated"


def test_role_for_shelf():
    assert lb.role_for_shelf("columns", False) == "Category"
    assert lb.role_for_shelf("rows", False) == "Rows"
    assert lb.role_for_shelf("color", False) == "Series"
    assert lb.role_for_shelf("detail", False) == "Series"
    assert lb.role_for_shelf("anything", True) == "Values"  # measure → Values regardless


def test_leaf_name_strips_qualifiers():
    assert lb.leaf_name("[Datasource].[Order Date]") == "Order Date"
    assert lb.leaf_name("Orders::Sales") == "Sales"
    assert lb.leaf_name("[Region]") == "Region"


def test_auto_name():
    assert lb.auto_name(["Total Sales", "Region"], {"Total Sales"}) == "Total Sales by Region"
    assert lb.auto_name(["Region"], {"Total Sales"}) is None  # no measure → None


# ── build_answer: role-aware axis layout ────────────────────────────────────

def test_build_answer_cartesian_axis_from_roles():
    a = lb.build_answer("Sales by Region", "v1", "M", None,
                        cols=["Region", "Total Sales", "Segment"], chart_type="BAR",
                        measure_names={"Total Sales"},
                        roles=["Category", "Values", "Series"])
    ax = a["answer"]["chart"]["axis_configs"][0]
    assert ax["x"] == ["Region"]          # Category → x
    assert ax["y"] == ["Total Sales"]     # measure → y
    assert ax["color"] == ["Segment"]     # Series → color


def test_build_answer_pivot_needs_axis_configs():
    a = lb.build_answer("Matrix", "v2", "M", None,
                        cols=["Region", "Category", "Total Sales"], chart_type="PIVOT_TABLE",
                        measure_names={"Total Sales"},
                        roles=["Rows", "Columns", "Values"])
    ax = a["answer"]["chart"]["axis_configs"][0]
    assert ax["x"] == ["Region"]          # Rows → pivot rows (x)
    assert ax["y"] == ["Total Sales"]     # measure → values (y)
    assert ax["color"] == ["Category"]    # Columns → across-the-top (color)


def test_build_answer_kpi_y_only():
    a = lb.build_answer("KPI", "v3", "M", None, cols=["Total Sales"], chart_type="KPI",
                        measure_names={"Total Sales"}, roles=["Values"])
    assert a["answer"]["chart"]["axis_configs"][0] == {"y": ["Total Sales"]}


def test_build_answer_search_query_and_bucket_token():
    a = lb.build_answer("Trend", "v4", "M", None,
                        cols=["Month(Order Date)", "Total Sales"], chart_type="LINE",
                        measure_names={"Total Sales"}, roles=["Category", "Values"],
                        bucket_tokens={"Month(Order Date)": "[Order Date].MONTHLY"})
    assert a["answer"]["search_query"] == "[Order Date].MONTHLY [Total Sales]"


def test_build_answer_fqn_tables_ref():
    a = lb.build_answer("X", "v5", "M", "fqn-123", cols=["Total Sales"], chart_type="KPI",
                        measure_names={"Total Sales"})
    assert a["answer"]["tables"][0] == {"id": "M", "name": "M", "fqn": "fqn-123"}


# ── build_answer_explicit: overrides capture-and-replay ─────────────────────

_GUID_CCC = [{"key": "basic", "dimensions": [
    {"key": "x-axis", "axes": [{"type": "FLAT", "column": "11111111-1111-1111-1111-111111111111"}]},
    {"key": "y-axis-column", "axes": [{"type": "MERGED", "columns": ["22222222-2222-2222-2222-222222222222"]}]},
]}]

_NAME_CCC = [{"key": "basic", "dimensions": [
    {"key": "x-axis", "axes": [{"type": "FLAT", "column": "Order Date"}]},
    {"key": "y-axis-column", "axes": [{"type": "MERGED", "columns": ["Total Sales"]}]},
]}]


def test_build_answer_explicit_format_and_viz_style_always_pass_through():
    ov = {
        "search": "[Order Date] [Total Sales] [Profit Ratio]",
        "columns": ["Order Date", "Total Sales", "Profit Ratio"],
        "ts_chart": "ADVANCED_LINE_COLUMN",
        "formats": {"Profit Ratio": {"category": "PERCENTAGE"}},
        "viz_style": '{"overrides": {}}',
    }
    a = lb.build_answer_explicit("Combo", "v6", "M", None, ov)
    chart = a["answer"]["chart"]
    assert chart["type"] == "ADVANCED_LINE_COLUMN"
    assert chart["viz_style"] == '{"overrides": {}}'
    pr = [c for c in a["answer"]["answer_columns"] if c["name"] == "Profit Ratio"][0]
    assert pr["format"] == {"category": "PERCENTAGE"}


def test_guid_based_custom_chart_config_is_replayed():
    ov = {"search": "[x]", "columns": ["x"], "ts_chart": "ADVANCED_LINE_COLUMN",
          "custom_chart_config": _GUID_CCC}
    chart = lb.build_answer_explicit("c", "v", "M", None, ov)["answer"]["chart"]
    assert chart["custom_chart_config"] == _GUID_CCC  # real captured config → replayed


def test_display_name_custom_chart_config_is_dropped():
    # display-name config would error `Invalid GUID string` on import → drop it, keep the type
    ov = {"search": "[x]", "columns": ["x"], "ts_chart": "ADVANCED_LINE_COLUMN",
          "custom_chart_config": _NAME_CCC}
    chart = lb.build_answer_explicit("c", "v", "M", None, ov)["answer"]["chart"]
    assert "custom_chart_config" not in chart
    assert chart["type"] == "ADVANCED_LINE_COLUMN"  # auto-resolves line vs column


def test_bucketed_date_uses_resolved_output_name():
    # [Date].monthly → the OUTPUT column is Month(Date); refs must use that, search uses token
    a = lb.build_answer("Trend", "v", "M", None,
                        cols=["Date", "Sales"], chart_type="LINE",
                        measure_names={"Sales"}, roles=["Category", "Values"],
                        bucket_tokens={"Date": "[Date].monthly"})
    ans = a["answer"]
    assert ans["search_query"] == "[Date].monthly [Sales]"
    assert {c["column_id"] for c in ans["chart"]["chart_columns"]} == {"Month(Date)", "Sales"}
    assert ans["chart"]["axis_configs"][0]["x"] == ["Month(Date)"]
    assert ans["table"]["ordered_column_ids"] == ["Month(Date)", "Sales"]


def test_advanced_line_column_gets_axis_configs():
    a = lb.build_answer("Combo", "v", "M", None,
                        cols=["Region", "Sales", "Margin"], chart_type="ADVANCED_LINE_COLUMN",
                        measure_names={"Sales", "Margin"}, roles=["Category", "Values", "Values"])
    ax = a["answer"]["chart"]["axis_configs"][0]
    assert ax["x"] == ["Region"] and ax["y"] == ["Sales", "Margin"]


def test_bucket_label_mapping():
    assert lb._bucket_label("[Order Date].monthly") == "Month"
    assert lb._bucket_label("[d].quarterly") == "Quarter"
    assert lb._bucket_label("[d]") is None
    assert lb._output_name("Order Date", {"Order Date": "[Order Date].yearly"}) == "Year(Order Date)"


# ── build_liveboard: tab assembly + tile layout ─────────────────────────────

def test_build_liveboard_fallback_two_per_row():
    items = [{"answer": {"name": f"a{i}"}, "tile": None} for i in range(3)]
    lb_tml = lb.build_liveboard("Report", [("Tab1", items)])
    tiles = lb_tml["liveboard"]["layout"]["tabs"][0]["tiles"]
    assert (tiles[0]["x"], tiles[0]["y"]) == (0, 0)
    assert (tiles[1]["x"], tiles[1]["y"]) == (6, 0)
    assert (tiles[2]["x"], tiles[2]["y"]) == (0, 8)   # wraps to next row
    assert len(lb_tml["liveboard"]["visualizations"]) == 3


def test_build_liveboard_uses_provided_tile():
    items = [{"answer": {"name": "a"}, "tile": {"x": 0, "y": 0, "width": 12, "height": 4}}]
    lb_tml = lb.build_liveboard("R", [("Tab1", items)])
    assert lb_tml["liveboard"]["layout"]["tabs"][0]["tiles"][0]["width"] == 12


def test_build_liveboard_drops_empty_tab():
    lb_tml = lb.build_liveboard("R", [("Empty", []), ("Full", [{"answer": {"name": "a"}}])])
    tab_names = [t["name"] for t in lb_tml["liveboard"]["layout"]["tabs"]]
    assert tab_names == ["Full"]


# ── build_from_spec: end-to-end orchestration ───────────────────────────────

def _spec(**over):
    base = {
        "report_name": "Sales Report", "model_name": "Sales Model",
        "measure_names": ["Total Sales"],
        "dashboards": [{"name": "Overview", "visuals": [
            {"mark": "bar", "fields": [
                {"name": "Region", "shelf": "columns", "measure": False},
                {"name": "Total Sales", "measure": True}]}]}],
    }
    base.update(over)
    return base


def test_build_from_spec_happy_path():
    r = lb.build_from_spec(_spec())
    assert r["liveboard"] is not None
    assert r["visual_rows"][0]["ts_chart"] == "BAR"
    assert r["visual_rows"][0]["status"] == "Migrated"
    # auto-named '<measure> by <attr>'
    assert r["answers"][0]["answer"]["name"] == "Total Sales by Region"


def test_build_from_spec_tooltip_dashboard_dropped():
    spec = _spec(dashboards=[{"name": "TT", "tooltip": True, "visuals": []}])
    r = lb.build_from_spec(spec)
    assert r["liveboard"] is None
    assert r["page_rows"][0]["status"] == "NEEDS REVIEW"


def test_build_from_spec_chart_floor_flags_not_downgrades():
    # SCATTER needs 2 measures; only 1 present → flagged NEEDS REVIEW, type kept as SCATTER.
    spec = _spec(dashboards=[{"name": "P", "visuals": [
        {"mark": "circle", "fields": [
            {"name": "Region", "shelf": "columns", "measure": False},
            {"name": "Total Sales", "measure": True}]}]}])
    r = lb.build_from_spec(spec)
    row = r["visual_rows"][0]
    assert row["ts_chart"] == "SCATTER"        # not downgraded
    assert row["status"] == "NEEDS REVIEW"
    assert "needs 2 measure" in row["note"]


def test_build_from_spec_skips_filter_zone():
    spec = _spec(dashboards=[{"name": "P", "visuals": [{"mark": "filter", "fields": []}]}])
    r = lb.build_from_spec(spec)
    assert r["liveboard"] is None
    assert r["visual_rows"][0]["ts_chart"] == "(skipped)"


def test_build_from_spec_override_and_extra_visual():
    spec = _spec(
        dashboards=[{"name": "Overview", "visuals": [
            {"mark": "bar", "title": "Custom",
             "override": {"search": "[Region] [Total Sales]", "columns": ["Region", "Total Sales"],
                          "ts_chart": "COLUMN"}}]}],
        extra_visuals=[{"page": "Overview", "name": "Added KPI", "search": "[Total Sales]",
                        "columns": ["Total Sales"], "ts_chart": "KPI"}],
    )
    r = lb.build_from_spec(spec)
    names = [a["answer"]["name"] for a in r["answers"]]
    assert "Custom" in names and "Added KPI" in names
    assert any(row["note"] == "added tile" or "added" in row["note"] for row in r["visual_rows"])
