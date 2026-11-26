"""Widget measures -> Answer formulas: measured values, ignored dashboard filters, tile
filters shadowed by a Liveboard filter, KPI axis, pivot flattening, disabled items.

Pure functions, synthetic bundles (an order-lines table). Each behaviour here was
verified by importing the generated TML on a cluster and reading every tile back
(numbers reconciled with direct SQL); these tests pin the emitted shapes.
"""
from ts_cli.sisense.answers import build_liveboard_result
from ts_cli.sisense.functions import translate_jaql
from ts_cli.sisense.parsing import parse_inventory
from ts_cli.sisense.scope import Scope, filter_condition, search_filter_tokens

COLS = ["Order Id", "Status", "Region", "Amount", "Flag", "Customer"]
MEAS = {"Amount"}
ID = "[Orders.Order Id]"


def _ctx(**extra):
    ctx = {"[K]": {"dim": ID, "datatype": "numeric"}}
    ctx.update(extra)
    return ctx


def _status(members, key="[S]"):
    return {key: {"dim": "[Orders.Status]", "datatype": "text",
                  "filter": {"explicit": True, "multiSelection": True, "members": members}}}


# --------------------------------------------------------------------------- #
# Measured values (the 2026-11-19 "copied verbatim" bug)
# --------------------------------------------------------------------------- #
def test_measured_value_becomes_group_aggregate_over_conditional():
    out, status, note = translate_jaql("(count([K]),[S])", _ctx(**_status(["SHIPPED"])))
    assert out == ("group_aggregate ( unique_count_if ( [Status] = 'SHIPPED' , [Order Id] ) , "
                   "query_groups ( ) , query_filters ( ) - { [Status] } )")
    assert status == "Migrated" and "measured value" in note


def test_measured_value_ratio_keeps_plain_denominator():
    out, _, _ = translate_jaql("(count([K]),[S])/(count([K]))", _ctx(**_status(["A", "B"])),
                               Scope(groups="{ }"))
    assert out.startswith("group_aggregate ( unique_count_if ( [Status] in { 'A' , 'B' } ,")
    assert out.endswith("/(unique count([Order Id]))")
    assert "(count(" not in out                      # no Sisense tuple left behind


def test_measured_value_numeric_member_is_bare():
    ctx = _ctx(**{"[F]": {"dim": "[Orders.Flag]", "datatype": "numeric",
                          "filter": {"members": ["1"]}}},
               **{"[A]": {"dim": "[Orders.Amount]", "datatype": "numeric"}})
    out, _, _ = translate_jaql("(sum([A]),[F])", ctx, Scope(groups="{ }"))
    assert "sum_if ( [Flag] = 1 , [Amount] )" in out


def test_measured_value_on_date_members_needs_review():
    ctx = _ctx(**{"[D]": {"dim": "[Orders.Day]", "datatype": "datetime",
                          "filter": {"members": ["2026-01-01T00:00:00"]}}})
    out, status, note = translate_jaql("(count([K]),[D])", ctx)
    assert out is None and status == "NEEDS REVIEW" and "date" in note


def test_count_in_formula_is_distinct():
    assert translate_jaql("count([K])", _ctx())[0] == "unique count([Order Id])"


# --------------------------------------------------------------------------- #
# Conditions and search tokens
# --------------------------------------------------------------------------- #
def test_filter_condition_shapes():
    assert filter_condition("[S]", {"members": ["a"]}) == ("[S] = 'a'", "")
    assert filter_condition("[S]", {"exclude": {"members": ["a", "b"]}}) == \
        ("not ( [S] in { 'a' , 'b' } )", "")
    assert filter_condition("[N]", {"from": 1, "toNotEqual": 5}) == ("[N] >= 1 and [N] < 5", "")
    assert filter_condition("[S]", {"all": True}) == (None, "")
    assert filter_condition("[S]", {"last": {"count": 1}})[1]


def test_search_tokens():
    assert search_filter_tokens("[S]", {"members": ["a", "b"]}) == ("[S] = 'a' 'b'", "")
    assert search_filter_tokens("[S]", {"exclude": {"members": ["a"]}}) == ("[S] != 'a'", "")
    assert search_filter_tokens("[S]", {"members": ["it's"]})[0] is None   # no escape in search


# --------------------------------------------------------------------------- #
# Whole-widget behaviour through build_liveboard_result
# --------------------------------------------------------------------------- #
def _count_item(title, **jaql):
    return {"jaql": dict({"title": title, "formula": "count([K])",
                          "context": {"[K]": {"dim": ID, "datatype": "numeric"}}}, **jaql)}


def _indicator(title, ignore=None, filters=()):
    return {"oid": title, "type": "indicator", "title": "", "metadata": {
        "ignore": ignore or {"dimensions": [], "ids": [], "all": False},
        "panels": [{"name": "value", "items": [_count_item(title)]},
                   {"name": "secondary", "items": []},
                   {"name": "filters", "items": list(filters)}]}}


def _bundle(widgets):
    return {"dashboard": {"title": "Orders", "filters": [
        {"instanceid": "F-STATUS", "jaql": {"dim": "[Orders.Status]", "datatype": "text",
                                            "filter": {"all": True}}},
        {"instanceid": "F-REGION", "jaql": {"dim": "[Orders.Region]", "datatype": "text",
                                            "filter": {"all": True}}}]},
        "widgets": widgets}


def _answers(widgets):
    inv = parse_inventory(_bundle(widgets))
    res = build_liveboard_result(inv, "Orders Model", None, COLS, MEAS, {})
    return {a["answer"]["name"]: a["answer"] for a in res["answers"]}, res["visual_rows"]


def test_indicator_formula_is_a_kpi_with_y_axis():
    ans, rows = _answers([_indicator("Total Orders")])
    a = ans["Total Orders"]                          # untitled widget named after its value
    assert a["chart"]["type"] == "KPI"
    assert a["chart"]["axis_configs"] == [{"y": ["Total Orders"]}]   # "Index: 0" without it
    assert a["formulas"] == [{"id": "formula_Total Orders", "name": "Total Orders",
                              "expr": "unique count([Order Id])"}]
    assert rows[0]["status"] == "Migrated"


def test_ignored_dashboard_filter_drops_it_from_query_filters():
    ans, _ = _answers([_indicator("All Statuses",
                                  {"dimensions": [], "ids": ["F-STATUS"], "all": False})])
    assert ans["All Statuses"]["formulas"][0]["expr"] == (
        "group_aggregate ( unique count ( [Order Id] ) , { } , "
        "query_filters ( ) - { [Status] } )")


def test_ignore_all_drops_every_query_filter():
    ans, _ = _answers([_indicator("Everything", {"dimensions": [], "ids": [], "all": True})])
    assert ans["Everything"]["formulas"][0]["expr"] == \
        "group_aggregate ( unique count ( [Order Id] ) , { } , { } )"


def test_tile_filter_on_liveboard_filter_column_becomes_condition():
    f = {"jaql": {"dim": "[Orders.Status]", "datatype": "text", "title": "Status",
                  "filter": {"members": ["SHIPPED"]}}}
    ans, rows = _answers([_indicator("Shipped", filters=[f])])
    a = ans["Shipped"]
    assert a["formulas"][0]["expr"] == "unique_count_if ( [Status] = 'SHIPPED' , [Order Id] )"
    assert "Status" not in a["search_query"].replace("[Shipped]", "")   # not a search filter
    assert "folded into the measures" in rows[0]["note"]


def test_tile_filter_on_other_column_stays_in_search():
    f = {"jaql": {"dim": "[Orders.Customer]", "datatype": "text", "title": "Customer",
                  "filter": {"members": ["Acme"]}}}
    ans, _ = _answers([_indicator("Acme Orders", filters=[f])])
    a = ans["Acme Orders"]
    assert a["search_query"] == "[Acme Orders] [Customer] = 'Acme'"
    assert a["formulas"][0]["expr"] == "unique count([Order Id])"


def _pivot(columns_item=None, rows=("Customer",)):
    panels = [{"name": "rows", "items": [
        {"jaql": {"dim": f"[Orders.{r}]", "datatype": "text", "title": r}} for r in rows]},
        {"name": "values", "items": [_count_item("Orders")]}]
    if columns_item:
        panels.append({"name": "columns", "items": [columns_item]})
    return {"oid": "p", "type": "pivot2", "title": "Pivot", "metadata": {"panels": panels}}


def test_pivot_without_columns_panel_is_a_table_mode_grid():
    ans, rows = _answers([_pivot()])
    a = ans["Pivot"]
    assert a["chart"]["type"] == "GRID_TABLE"
    assert a["display_mode"] == "TABLE_MODE"   # CHART_MODE grid returns no data on a Liveboard
    assert "flat GRID_TABLE" in rows[0]["note"]


def test_pivot_columns_with_members_flattened_to_conditional_measures():
    col = {"jaql": {"dim": "[Orders.Status]", "datatype": "text", "title": "Status",
                    "filter": {"members": ["OPEN", "SHIPPED"]}}}
    ans, _ = _answers([_pivot(col)])
    a = ans["Pivot"]
    assert a["chart"]["type"] == "GRID_TABLE"
    assert [f["name"] for f in a["formulas"]] == ["OPEN", "SHIPPED"]
    # Status also has a Liveboard filter here, so the pivot's member list is folded into
    # the measures too (a search filter on it would be replaced by the Liveboard filter).
    assert a["formulas"][1]["expr"] == ("unique_count_if ( ( [Status] in { 'OPEN' , 'SHIPPED' } )"
                                        " and ( [Status] = 'SHIPPED' ) , [Order Id] )")
    assert a["search_query"] == "[Customer] [OPEN] [SHIPPED]"


def test_pivot_columns_without_members_kept_and_flagged():
    col = {"jaql": {"dim": "[Orders.Status]", "datatype": "text", "title": "Status"}}
    ans, rows = _answers([_pivot(col)])
    assert ans["Pivot"]["chart"]["type"] == "PIVOT_TABLE"
    assert "too many results" in rows[0]["note"]


def test_disabled_items_are_not_converted():
    w = _pivot(rows=("Customer", "Order Id"))
    w["metadata"]["panels"][0]["items"][1]["disabled"] = True   # hidden row changes grain
    inv = parse_inventory(_bundle([w]))
    assert [f["title"] for f in inv["widgets"][0]["fields"]] == ["Customer", "Orders"]
    assert inv["widgets"][0]["disabled_items"] == 1


def test_formula_named_like_model_column_is_renamed():
    ans, _ = _answers([_indicator("Status")])
    assert ans["Status"]["formulas"][0]["name"] == "Status Value"
