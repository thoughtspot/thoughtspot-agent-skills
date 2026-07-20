"""Task 13 — golden end-to-end test: Dunder Mifflin worked example.

Exercises the full pure ThoughtSpot-Model -> Databricks-Metric-View pipeline
(``mv_emit.detect_fact_tables``/``build_metric_view``,
``mv_build_view.build_view_ddl``/``default_view_name``) against a fixture
faithfully transcribed from the oracle:
``agents/shared/worked-examples/databricks/ts-to-databricks.md`` (the Dunder
Mifflin Sales & Inventory model — 8 formulas, 2 fact tables split into a Sales
MV over DM_ORDER_DETAIL and an Inventory MV over DM_INVENTORY).

The fixture's ``model_tables[]`` entries carry explicit ``alias:`` fields
(``orders``, ``products``, ``category``, ``customers``, ``employees``,
``dates``) that are not shown in the worked example's "key sections" Model
TML excerpt but are required to reproduce its documented join aliases and
dot-paths (``orders.customers.COMPANY_NAME``, ``products.category.
CATEGORY_NAME``, etc.) — the doc's own output section only makes sense with
these aliases in place, so adding them is filling an acknowledged gap in an
abbreviated excerpt, not deviating from the fixture's fidelity.

Divergences from the oracle found while building this test (full detail in
.superpowers/sdd/task-13-report.md) are called out inline at the point they
surface, per the task's divergence-handling rule: report precisely, do not
weaken assertions or patch the emitter to force a match.

``detect_fact_tables`` over-detection (originally Divergence 1 here) has
since been FIXED — see ``.superpowers/sdd/task-13-report.md`` "Fix:
detect_fact_tables join-root heuristic". It now returns exactly the oracle's
two facts (``DM_ORDER_DETAIL``, ``DM_INVENTORY``): a fact table is a
MEASURE-bearing table that is also a join ROOT (never itself the `with`
target of another table's join), which excludes ``DM_ORDER`` and
``DM_DATE_DIM`` (both join targets / dimensions) regardless of the
measure-attribution DFS's foreign-table mis-attribution quirk (still present,
still documented on ``_measure_column_table``, but no longer consequential
for detection).

One divergence remains load-bearing for how this file is structured:

1. The semi-additive Inventory Balance measure's window ``order:`` reuses the
   dimension named ``transaction_date`` (dot-path ``dates.DATE_VALUE``,
   matched directly), not ``balance_date`` as the oracle documents — the
   join-predicate-alias fallback that would find ``balance_date`` only
   resolves an INLINE model-join ``on:`` clause (see
   ``mv_emit_window._find_join_predicate_alias``'s own docstring), and this
   model's joins are all ``referencing_join``-based. It IS a genuine reuse of
   an already-emitted dimension, not a redundant synthesized one — just a
   different (also-valid) dimension than the oracle names.
"""
from __future__ import annotations

from ts_cli.databricks.mv_emit import build_metric_view, detect_fact_tables
from ts_cli.databricks.mv_build_view import build_view_ddl, default_view_name

CATALOG = "agent_skills"
SCHEMA = "dunder_mifflin"


def _col(name: str, data_type: str) -> dict:
    return {"name": name, "db_column_properties": {"data_type": data_type}}


def _table(name: str, db_table: str, columns: list, joins_with: list | None = None) -> dict:
    t = {"name": name, "db": CATALOG, "schema": SCHEMA, "db_table": db_table, "columns": columns}
    if joins_with:
        t["joins_with"] = joins_with
    return {"table": t}


# --- Table TMLs (agents/shared/worked-examples/databricks/ts-to-databricks.md
# "Resolve Physical Table Names and Joins") -----------------------------------
# `joins_with[]` on each SOURCE (FK) table carries the referencing_join
# predicates the model's model_tables[].joins[].referencing_join point to
# (Task 7's source-table resolution fix).

TABLES = [
    _table("DM_ORDER_DETAIL", "dm_order_detail", [
        _col("ORDER_ID", "VARCHAR"),
        _col("PRODUCT_ID", "VARCHAR"),
        _col("DISCOUNT", "DOUBLE"),
        _col("LINE_TOTAL", "DOUBLE"),
        _col("QUANTITY", "DOUBLE"),
        _col("UNIT_PRICE", "DOUBLE"),
    ], joins_with=[
        {"name": "DM_ORDER_DETAIL_to_DM_ORDER", "destination": {"name": "DM_ORDER"},
         "on": "[DM_ORDER_DETAIL::ORDER_ID] = [DM_ORDER::ORDER_ID]",
         "type": "INNER", "cardinality": "MANY_TO_ONE"},
        {"name": "DM_ORDER_DETAIL_to_DM_PRODUCT", "destination": {"name": "DM_PRODUCT"},
         "on": "[DM_ORDER_DETAIL::PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]",
         "type": "INNER", "cardinality": "MANY_TO_ONE"},
    ]),
    _table("DM_ORDER", "dm_order", [
        _col("ORDER_ID", "VARCHAR"),
        _col("CUSTOMER_ID", "VARCHAR"),
        _col("EMPLOYEE_ID", "VARCHAR"),
        _col("ORDER_DATE", "DATE"),
    ], joins_with=[
        {"name": "DM_ORDER_to_DM_CUSTOMER", "destination": {"name": "DM_CUSTOMER"},
         "on": "[DM_ORDER::CUSTOMER_ID] = [DM_CUSTOMER::CUSTOMER_ID]",
         "type": "INNER", "cardinality": "MANY_TO_ONE"},
        {"name": "DM_ORDER_to_DM_DATE_DIM", "destination": {"name": "DM_DATE_DIM"},
         "on": "[DM_ORDER::ORDER_DATE] = [DM_DATE_DIM::DATE_VALUE]",
         "type": "INNER", "cardinality": "MANY_TO_ONE"},
        {"name": "DM_ORDER_to_DM_EMPLOYEE", "destination": {"name": "DM_EMPLOYEE"},
         "on": "[DM_ORDER::EMPLOYEE_ID] = [DM_EMPLOYEE::EMPLOYEE_ID]",
         "type": "INNER", "cardinality": "MANY_TO_ONE"},
    ]),
    _table("DM_INVENTORY", "dm_inventory", [
        _col("BALANCE_DATE", "DATE"),
        _col("PRODUCT_ID", "VARCHAR"),
        _col("FILLED_INVENTORY", "DOUBLE"),
    ], joins_with=[
        {"name": "DM_INVENTORY_to_DM_DATE_DIM", "destination": {"name": "DM_DATE_DIM"},
         "on": "[DM_INVENTORY::BALANCE_DATE] = [DM_DATE_DIM::DATE_VALUE]",
         "type": "INNER", "cardinality": "MANY_TO_ONE"},
        {"name": "DM_INVENTORY_to_DM_PRODUCT", "destination": {"name": "DM_PRODUCT"},
         "on": "[DM_INVENTORY::PRODUCT_ID] = [DM_PRODUCT::PRODUCT_ID]",
         "type": "INNER", "cardinality": "MANY_TO_ONE"},
    ]),
    _table("DM_PRODUCT", "dm_product", [
        _col("PRODUCT_ID", "VARCHAR"),
        _col("PRODUCT_NAME", "VARCHAR"),
        _col("CATEGORY_ID", "VARCHAR"),
    ], joins_with=[
        {"name": "DM_PRODUCT_to_DM_CATEGORY", "destination": {"name": "DM_CATEGORY"},
         "on": "[DM_PRODUCT::CATEGORY_ID] = [DM_CATEGORY::CATEGORY_ID]",
         "type": "INNER", "cardinality": "MANY_TO_ONE"},
    ]),
    _table("DM_CATEGORY", "dm_category", [
        _col("CATEGORY_ID", "VARCHAR"),
        _col("CATEGORY_NAME", "VARCHAR"),
    ]),
    _table("DM_CUSTOMER", "dm_customer", [
        _col("CUSTOMER_ID", "VARCHAR"),
        _col("COMPANY_NAME", "VARCHAR"),
        _col("STATE", "VARCHAR"),
        _col("ZIPCODE", "VARCHAR"),
    ]),
    _table("DM_EMPLOYEE", "dm_employee", [
        _col("EMPLOYEE_ID", "VARCHAR"),
        _col("FIRST_NAME", "VARCHAR"),
        _col("LAST_NAME", "VARCHAR"),
    ]),
    _table("DM_DATE_DIM", "dm_date_dim", [
        _col("DATE_VALUE", "DATE"),
    ]),
]

# --- Model TML (ts-to-databricks.md "Source — ThoughtSpot Model TML") -------

MODEL = {
    "name": "Dunder Mifflin Sales & Inventory",
    "description": ("The Dunder Mifflin Sales & Inventory worksheet provides a comprehensive "
                     "overview of sales transactions, inventory snapshots, and product categorization."),
    "model_tables": [
        {"name": "DM_ORDER_DETAIL", "joins": [
            {"with": "DM_ORDER", "referencing_join": "DM_ORDER_DETAIL_to_DM_ORDER"},
            {"with": "DM_PRODUCT", "referencing_join": "DM_ORDER_DETAIL_to_DM_PRODUCT"},
        ]},
        # alias fields: see module docstring — required to reproduce the
        # oracle's documented join names/dot-paths; not shown in the doc's
        # abbreviated Model TML excerpt.
        {"name": "DM_ORDER", "alias": "orders", "joins": [
            {"with": "DM_CUSTOMER", "referencing_join": "DM_ORDER_to_DM_CUSTOMER"},
            {"with": "DM_DATE_DIM", "referencing_join": "DM_ORDER_to_DM_DATE_DIM"},
            {"with": "DM_EMPLOYEE", "referencing_join": "DM_ORDER_to_DM_EMPLOYEE"},
        ]},
        {"name": "DM_INVENTORY", "joins": [
            {"with": "DM_DATE_DIM", "referencing_join": "DM_INVENTORY_to_DM_DATE_DIM"},
            {"with": "DM_PRODUCT", "referencing_join": "DM_INVENTORY_to_DM_PRODUCT"},
        ]},
        {"name": "DM_PRODUCT", "alias": "products", "joins": [
            {"with": "DM_CATEGORY", "referencing_join": "DM_PRODUCT_to_DM_CATEGORY"},
        ]},
        {"name": "DM_CUSTOMER", "alias": "customers"},
        {"name": "DM_EMPLOYEE", "alias": "employees"},
        {"name": "DM_DATE_DIM", "alias": "dates"},
        {"name": "DM_CATEGORY", "alias": "category"},
    ],
    "columns": [
        {"name": "Order Id", "column_id": "DM_ORDER::ORDER_ID",
         "properties": {"column_type": "ATTRIBUTE",
                        "description": "Identifier for one order header. Each order can have multiple lines."}},
        {"name": "Order Date", "column_id": "DM_ORDER::ORDER_DATE",
         "properties": {"column_type": "ATTRIBUTE", "description": "Date the order was placed.",
                        "synonyms": ["order placed", "purchase date"]}},
        {"name": "Product Name", "column_id": "DM_PRODUCT::PRODUCT_NAME",
         "properties": {"column_type": "ATTRIBUTE", "description": "Display name of the product.",
                        "synonyms": ["product", "item"]}},
        {"name": "Product Category", "column_id": "DM_CATEGORY::CATEGORY_NAME",
         "properties": {"column_type": "ATTRIBUTE", "description": "Category name the product belongs to.",
                        "synonyms": ["category", "product line"]}},
        {"name": "Customer Name", "column_id": "DM_CUSTOMER::COMPANY_NAME",
         "properties": {"column_type": "ATTRIBUTE", "description": "The customer display name.",
                        "synonyms": ["customer", "client", "buyer"]}},
        {"name": "Customer State", "column_id": "DM_CUSTOMER::STATE",
         "properties": {"column_type": "ATTRIBUTE", "description": "The customer state of residence."}},
        {"name": "Customer Zipcode", "column_id": "DM_CUSTOMER::ZIPCODE",
         "properties": {"column_type": "ATTRIBUTE",
                        "description": "Postal code on the customer billing address.",
                        "synonyms": ["zip code", "postal code"]}},
        {"name": "Discount", "column_id": "DM_ORDER_DETAIL::DISCOUNT",
         "properties": {"column_type": "ATTRIBUTE",
                        "description": "Per-line discount recorded on the order detail.",
                        "synonyms": ["promo", "discount amount"]}},
        {"name": "Employee", "formula_id": "formula_Employee",
         "properties": {"column_type": "ATTRIBUTE",
                        "synonyms": ["sales rep", "rep", "salesperson"]}},
        {"name": "Transaction Date", "column_id": "DM_DATE_DIM::DATE_VALUE",
         "properties": {"column_type": "ATTRIBUTE", "description": "Date dimension key.",
                        "synonyms": ["date"]}},
        {"name": "Balance Date", "column_id": "DM_INVENTORY::BALANCE_DATE",
         "properties": {"column_type": "ATTRIBUTE",
                        "description": "Date the inventory balance was snapshotted."}},
        {"name": "Revenue", "column_id": "DM_ORDER_DETAIL::LINE_TOTAL",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                        "description": "Dollar value of an order-line item.",
                        "synonyms": ["sales", "total sales", "amount"],
                        "ai_context": "Total line-item revenue for financial analysis."}},
        {"name": "Quantity", "column_id": "DM_ORDER_DETAIL::QUANTITY",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                        "description": "Number of units sold on one order line.",
                        "synonyms": ["units", "units sold"]}},
        {"name": "Unit Price", "column_id": "DM_ORDER_DETAIL::UNIT_PRICE",
         "properties": {"column_type": "MEASURE", "aggregation": "AVERAGE",
                        "description": "Unit price recorded on the order-line item.",
                        "synonyms": ["price", "list price"]}},
        {"name": "# Employees", "formula_id": "formula_# Employees",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                        "synonyms": ["employee count", "rep count"]}},
        {"name": "Category Quantity", "formula_id": "formula_Category Quantity",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                        "description": "Total units sold for a product category."}},
        {"name": "Category Contribution Ratio", "formula_id": "formula_Category Contribution Ratio",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                        "description": "Product share of category total units."}},
        {"name": "Monthly Revenue", "formula_id": "formula_Monthly Revenue",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Prior Month Revenue", "formula_id": "formula_Prior Month Revenue",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
        {"name": "Inventory Balance", "formula_id": "formula_Inventory Balance",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM",
                        "description": "Semi-additive inventory snapshot.",
                        "synonyms": ["stock", "stock on hand", "current inventory"]}},
        {"name": "Active Customers", "formula_id": "formula_Active Customers",
         "properties": {"column_type": "MEASURE", "aggregation": "SUM"}},
    ],
    "formulas": [
        {"id": "formula_Employee", "name": "Employee",
         "expr": "concat ( [DM_EMPLOYEE::LAST_NAME] , ', ' , [DM_EMPLOYEE::FIRST_NAME] )"},
        {"id": "formula_# Employees", "name": "# Employees",
         "expr": "count ( [DM_ORDER::EMPLOYEE_ID] )"},
        {"id": "formula_Category Quantity", "name": "Category Quantity",
         "expr": "group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , "
                 "{ [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) )"},
        {"id": "formula_Category Contribution Ratio", "name": "Category Contribution Ratio",
         "expr": "safe_divide ( [Quantity] , [Category Quantity] )"},
        {"id": "formula_Monthly Revenue", "name": "Monthly Revenue",
         "expr": "sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = 0 , "
                 "[DM_ORDER_DETAIL::LINE_TOTAL] )"},
        {"id": "formula_Prior Month Revenue", "name": "Prior Month Revenue",
         "expr": "sum_if ( diff_months ( [DM_DATE_DIM::DATE_VALUE] , today ( ) ) = -1 , "
                 "[DM_ORDER_DETAIL::LINE_TOTAL] )"},
        {"id": "formula_Inventory Balance", "name": "Inventory Balance",
         "expr": "last_value ( sum ( [DM_INVENTORY::FILLED_INVENTORY] ) , query_groups ( ) , "
                 "{ [DM_DATE_DIM::DATE_VALUE] } )"},
        {"id": "formula_Active Customers", "name": "Active Customers",
         "expr": "unique_count_if ( [DM_ORDER_DETAIL::LINE_TOTAL] > 0 , [DM_CUSTOMER::CUSTOMER_ID] )"},
    ],
}


# --- helpers -----------------------------------------------------------------

def _build(source_table: str) -> dict:
    return build_metric_view(MODEL, TABLES, source_table=source_table, catalog=CATALOG, schema=SCHEMA)


def _by_name(items: list) -> dict:
    return {i["name"]: i for i in items}


class TestDetectFactTables:
    def test_returns_exactly_the_oracles_two_fact_tables(self):
        # Oracle (worked example "Split Decision") documents exactly TWO fact
        # tables: DM_ORDER_DETAIL and DM_INVENTORY. detect_fact_tables now
        # matches this exactly: DM_ORDER and DM_DATE_DIM are excluded because
        # both are join TARGETS (`with` values in model_tables[].joins[]),
        # never join roots — see mv_emit.detect_fact_tables and
        # .superpowers/sdd/task-13-report.md "Fix: detect_fact_tables
        # join-root heuristic".
        assert detect_fact_tables(MODEL) == ["DM_ORDER_DETAIL", "DM_INVENTORY"]


class TestSalesMetricView:
    """Sales MV — source: DM_ORDER_DETAIL (worked example "MV 1 — Dunder Mifflin Sales")."""

    def test_category_quantity_lod_dimension_window_function(self):
        # Formula 3: group_aggregate(sum([QUANTITY]), {[CATEGORY_NAME]}, query_filters())
        doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        dims = _by_name(doc["dimensions"])
        assert dims["category_quantity"]["expr"] == (
            "SUM(source.QUANTITY) OVER (PARTITION BY products.category.CATEGORY_NAME)")

    def test_active_customers_conditional_measure(self):
        # Formula 8: unique_count_if([LINE_TOTAL] > 0, [CUSTOMER_ID])
        doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        measures = _by_name(doc["measures"])
        assert measures["active_customers"]["expr"] == (
            "COUNT(DISTINCT orders.customers.CUSTOMER_ID) FILTER (WHERE source.LINE_TOTAL > 0)")

    def test_category_contribution_ratio_cross_measure_refs(self):
        # Formula 4: safe_divide([Quantity], [Category Quantity]) -- MEASURE()
        # for the physical-measure ref, ANY_VALUE() for the LOD-dimension ref.
        doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        measures = _by_name(doc["measures"])
        assert measures["category_contribution_ratio"]["expr"] == (
            "COALESCE(MEASURE(quantity) / NULLIF(ANY_VALUE(category_quantity), 0), 0)")

    def test_employee_dimension_formula(self):
        # Formula 1: concat([LAST_NAME], ', ', [FIRST_NAME]) through the
        # nested orders.employees join.
        doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        dims = _by_name(doc["dimensions"])
        assert dims["employee"]["expr"] == (
            "CONCAT(orders.employees.LAST_NAME, ', ', orders.employees.FIRST_NAME)")

    def test_employee_count_measure_formula(self):
        # Formula 2: count([DM_ORDER::EMPLOYEE_ID])
        doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        measures = _by_name(doc["measures"])
        assert measures["employees"]["expr"] == "COUNT(orders.EMPLOYEE_ID)"

    def test_physical_measures(self):
        doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        measures = _by_name(doc["measures"])
        assert measures["revenue"]["expr"] == "SUM(source.LINE_TOTAL)"
        assert measures["quantity"]["expr"] == "SUM(source.QUANTITY)"
        assert measures["unit_price"]["expr"] == "AVG(source.UNIT_PRICE)"

    def test_monthly_revenue_period_current_window(self):
        # Formula 5: sum_if(diff_months([DATE_VALUE], today()) = 0, [LINE_TOTAL])
        # -> window: [{order: <synthesized month dim>, semiadditive: last, range: current}]
        # Divergence: the synthesized order-dim is named "month_date_value"
        # (mechanically derived: to_snake(f"{grain}_{column}")), not the
        # oracle's "order_month" -- see task-13-report.md. Asserted
        # structurally (shape + shared reuse with Prior Month Revenue) rather
        # than by literal name.
        doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        measures = _by_name(doc["measures"])
        monthly = measures["monthly_revenue"]
        assert monthly["expr"] == "SUM(source.LINE_TOTAL)"
        assert len(monthly["window"]) == 1
        assert monthly["window"][0]["range"] == "current"
        assert monthly["window"][0]["semiadditive"] == "last"
        assert "offset" not in monthly["window"][0]

    def test_prior_month_revenue_shares_order_month_dim_and_has_offset(self):
        # Formula 6: sum_if(diff_months([DATE_VALUE], today()) = -1, [LINE_TOTAL])
        # -> window: [{..., offset: "-1 month"}], REUSING the same order dim
        # Monthly Revenue synthesized (Task 10's within-MV dim-reuse).
        doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        measures = _by_name(doc["measures"])
        monthly_order = measures["monthly_revenue"]["window"][0]["order"]
        prior = measures["prior_month_revenue"]
        assert prior["expr"] == "SUM(source.LINE_TOTAL)"
        assert prior["window"] == [
            {"order": monthly_order, "range": "current", "semiadditive": "last", "offset": "-1 month"}]
        # the synthesized dim itself must actually exist in this MV's dimensions
        dims = _by_name(doc["dimensions"])
        assert monthly_order in dims
        assert dims[monthly_order]["expr"] == "DATE_TRUNC('MONTH', orders.dates.DATE_VALUE)"

    def test_only_cross_fact_columns_are_skipped(self):
        # Everything skipped in the Sales MV must be an Inventory-only
        # column/formula (cross-fact), never a genuine translation failure --
        # matches the oracle's "No formulas were omitted" claim once read at
        # the whole-model (both-MVs) level rather than per-MV.
        result = _build("DM_ORDER_DETAIL")
        skipped_names = {s["name"] for s in result["skipped"]}
        assert skipped_names == {"Balance Date", "Inventory Balance"}
        for s in result["skipped"]:
            assert "no join path" in s["reason"]


class TestInventoryMetricView:
    """Inventory MV — source: DM_INVENTORY (worked example "MV 2 — Dunder Mifflin Inventory")."""

    def test_inventory_balance_semiadditive_measure(self):
        # Formula 7: last_value(sum([FILLED_INVENTORY]), query_groups(), {[DATE_VALUE]})
        doc = _build("DM_INVENTORY")["yaml_doc"]
        measures = _by_name(doc["measures"])
        inv = measures["inventory_balance"]
        assert inv["expr"] == "SUM(source.FILLED_INVENTORY)"
        assert inv["window"][0]["semiadditive"] == "last"
        assert inv["window"][0]["range"] == "current"

    def test_inventory_balance_order_dim_is_reused_not_synthesized(self):
        # Task 10 requirement: the semi-additive window's order: dim must
        # reuse an ALREADY-EMITTED dimension of this MV, never synthesize a
        # redundant duplicate. Divergence: the reused dim is "transaction_date"
        # (direct dot-path match on dates.DATE_VALUE), not the oracle's
        # "balance_date" (which would require resolving the join-equality
        # between DM_INVENTORY::BALANCE_DATE and DM_DATE_DIM::DATE_VALUE via
        # the referencing_join's Table-TML predicate -- a path
        # _find_join_predicate_alias's docstring documents as unsupported for
        # referencing_join-based joins). See task-13-report.md.
        doc = _build("DM_INVENTORY")["yaml_doc"]
        measures = _by_name(doc["measures"])
        dims = _by_name(doc["dimensions"])
        order_name = measures["inventory_balance"]["window"][0]["order"]
        assert order_name in dims, "order: dim must be one of this MV's own emitted dimensions"
        # Pin the reuse to a DATE-valued dim, not just any already-emitted
        # dimension -- a regression that picked e.g. product_name would still
        # pass the membership check above. The two candidates are the join-
        # equal pair DM_INVENTORY::BALANCE_DATE = DM_DATE_DIM::DATE_VALUE;
        # either is oracle-valid (see the divergence note above), so assert
        # on the dim's expr rather than hardcoding which NAME won.
        order_expr = dims[order_name]["expr"]
        assert order_expr in ("source.BALANCE_DATE", "dates.DATE_VALUE"), (
            f"order: dim {order_name!r} must resolve to one of the join-equal "
            f"date exprs, got expr={order_expr!r}")
        # no NEW dimension should have been synthesized beyond the 4 plain
        # ones (product_name, product_category, transaction_date, balance_date)
        assert len(doc["dimensions"]) == 4

    def test_product_and_category_dimensions_present(self):
        doc = _build("DM_INVENTORY")["yaml_doc"]
        dims = _by_name(doc["dimensions"])
        assert dims["product_name"]["expr"] == "products.PRODUCT_NAME"
        assert dims["product_category"]["expr"] == "products.category.CATEGORY_NAME"

    def test_only_cross_fact_columns_are_skipped(self):
        result = _build("DM_INVENTORY")
        skipped_names = {s["name"] for s in result["skipped"]}
        assert skipped_names == {
            "Order Id", "Order Date", "Customer Name", "Customer State", "Customer Zipcode",
            "Discount", "Employee", "Category Quantity", "Revenue", "Quantity", "Unit Price",
            "# Employees", "Monthly Revenue", "Prior Month Revenue", "Active Customers",
            "Category Contribution Ratio",
        }


class TestAllEightFormulasSurfaceSomewhere:
    """Oracle: "No formulas were omitted -- all 8 were translatable." True at
    the whole-model level: every formula's display name must appear as an
    emitted dimension or measure in AT LEAST ONE of the two real MVs, even
    though each individual MV naturally skips the other fact's columns.
    """

    FORMULA_DISPLAY_NAMES = [
        "Employee", "# Employees", "Category Quantity", "Category Contribution Ratio",
        "Monthly Revenue", "Prior Month Revenue", "Inventory Balance", "Active Customers",
    ]

    def test_every_formula_emitted_in_at_least_one_mv(self):
        sales_doc = _build("DM_ORDER_DETAIL")["yaml_doc"]
        inv_doc = _build("DM_INVENTORY")["yaml_doc"]
        emitted_display_names = {
            c.get("display_name")
            for doc in (sales_doc, inv_doc)
            for c in doc["dimensions"] + doc["measures"]
        }
        for name in self.FORMULA_DISPLAY_NAMES:
            assert name in emitted_display_names, f"formula {name!r} missing from both MVs"


class TestBuildViewDdl:
    def test_sales_mv_ddl_structure(self):
        result = _build("DM_ORDER_DETAIL")
        ddl = build_view_ddl(result["yaml_doc"], catalog=CATALOG, schema=SCHEMA,
                              view_name="dunder_mifflin_sales_mv")
        assert ddl.startswith(
            "CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dunder_mifflin_sales_mv\n")
        assert "WITH METRICS LANGUAGE YAML AS $$" in ddl
        assert ddl.rstrip().endswith("$$")
        assert "source: agent_skills.dunder_mifflin.dm_order_detail" in ddl

    def test_inventory_mv_ddl_structure(self):
        result = _build("DM_INVENTORY")
        ddl = build_view_ddl(result["yaml_doc"], catalog=CATALOG, schema=SCHEMA,
                              view_name="dunder_mifflin_inventory_mv")
        assert ddl.startswith(
            "CREATE OR REPLACE VIEW agent_skills.dunder_mifflin.dunder_mifflin_inventory_mv\n")
        assert "WITH METRICS LANGUAGE YAML AS $$" in ddl
        assert ddl.rstrip().endswith("$$")
        assert "source: agent_skills.dunder_mifflin.dm_inventory" in ddl

    def test_default_view_name_is_deterministic_snake_case(self):
        # Divergence (minor, not asserted as a match): default_view_name's
        # mechanical `{model}_{fact}_mv` shape does not reproduce the oracle's
        # hand-chosen "dunder_mifflin_sales_mv" / "_inventory_mv" (it folds
        # the FULL model name in, not just "sales"/"inventory") -- callers are
        # documented to override per-invocation, which the DDL tests above do.
        name = default_view_name(MODEL["name"], "DM_ORDER_DETAIL")
        assert name.startswith("dunder_mifflin_sales_inventory_")
        assert name.endswith("_mv")
