"""D (Data Modeling): the inputs the legacy D-check tests use, and D_INPUTS."""
from __future__ import annotations

import copy

from ts_cli.audit.context import AuditContext, make_context

from .ai import demo_corpus_models
from .common import (metadata_duplicate_tables, model_role_playing_dimension,
                     models_divergent_column_types, models_overlapping_tables,
                     registry_empty_context, registry_populated_context)
from .perf import (build_join_chain, join_keys_composite, join_keys_integer,
                   join_keys_table_missing, join_keys_type_on_model_ignored,
                   join_keys_varchar, referencing_join_integer,
                   referencing_join_model_type_override, referencing_join_outer,
                   referencing_join_table_missing, referencing_join_varchar,
                   registry_wide_not_progressive)


# ── D: Data Modeling ────────────────────────────────────────────────────────
# The inputs the legacy D-check tests exercise checks_data.py with:
# test_checks_data.py, test_checks_data_trip.py, and the D halves of
# test_alias_and_join_names.py, test_checks_varchar_join_keys.py,
# test_referencing_joins.py and test_checks_registry.py (the last three build theirs in
# perf.py and common.py, shared with P). Those tests build their contexts here, so the
# D rules' examples and the equivalence test (tests/test_audit_equivalence.py) run over
# the very same inputs.

# test_checks_data.py's shapes

def build_data_model(name="Sales", guid="m-1", model_tables=None, columns=None,
                     formulas=None, properties=None) -> dict:
    """A model document as test_checks_data.py has always built it (one table T1 when
    none is given)."""
    model_tables, columns, formulas, properties = copy.deepcopy(
        (model_tables, columns, formulas, properties))
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "T1", "id": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
        },
    }


def build_data_join(name="j1", with_table="T2", type="INNER", on="col1 = col2",
                    cardinality=None) -> dict:
    j = {"name": name, "with": with_table, "type": type, "on": on}
    if cardinality:
        j["cardinality"] = cardinality
    return j


def build_data_col(name="Amount", column_type="MEASURE", table="T1", data_type="INT64",
                   aggregation=None, is_hidden=False, index_type=None,
                   db_column_name=None) -> dict:
    c = {
        "name": name,
        "column_id": f"{table}::{name}",
        "properties": {"column_type": column_type},
    }
    if aggregation:
        c["properties"]["aggregation"] = aggregation
    if is_hidden:
        c["properties"]["is_hidden"] = True
    if index_type:
        c["properties"]["index_type"] = index_type
    if db_column_name:
        c["db_column_name"] = db_column_name
    c["db_column_properties"] = {"data_type": data_type}
    return c


def build_data_tables(n: int) -> list:
    return [{"name": f"T{i}", "id": f"T{i}"} for i in range(n)]


def data_model_sixteen_tables() -> AuditContext:
    """16 tables: D1's tables measure is HIGH (> 15); nothing else is over a line."""
    return make_context(models=[build_data_model(model_tables=build_data_tables(16))])


def data_model_small() -> AuditContext:
    """5 tables, 10 columns: under every D1 line."""
    return make_context(models=[build_data_model(
        model_tables=build_data_tables(5), columns=[build_data_col(f"C{i}") for i in range(10)])])


def data_model_six_tables_not_progressive() -> AuditContext:
    return make_context(models=[build_data_model(
        model_tables=build_data_tables(6), properties={"join_progressive": False})])


def data_model_six_tables_progressive() -> AuditContext:
    return make_context(models=[build_data_model(
        model_tables=build_data_tables(6), properties={"join_progressive": True})])


def data_model_three_tables_not_progressive() -> AuditContext:
    return make_context(models=[build_data_model(
        model_tables=build_data_tables(3), properties={"join_progressive": False})])


def data_model_unjoined_table() -> AuditContext:
    """T1 joins T2; T3 joins nothing (D5 fires on T3)."""
    return make_context(models=[build_data_model(model_tables=[
        {"name": "T1", "id": "T1", "joins": [build_data_join(with_table="T2")]},
        {"name": "T2", "id": "T2"},
        {"name": "T3", "id": "T3"},
    ])])


def data_model_all_joined() -> AuditContext:
    return make_context(models=[build_data_model(model_tables=[
        {"name": "T1", "id": "T1", "joins": [build_data_join(with_table="T2")]},
        {"name": "T2", "id": "T2"},
    ])])


def data_models_identical_tables() -> AuditContext:
    tables = [{"name": "T1", "fqn": "db.s.T1"}, {"name": "T2", "fqn": "db.s.T2"}]
    return make_context(models=[build_data_model(name="M1", guid="g1", model_tables=tables),
                                build_data_model(name="M2", guid="g2", model_tables=tables)])


def data_models_disjoint_tables() -> AuditContext:
    return make_context(models=[
        build_data_model(name="M1", guid="g1", model_tables=[{"name": "T1", "fqn": "db.s.T1"}]),
        build_data_model(name="M2", guid="g2", model_tables=[{"name": "T3", "fqn": "db.s.T3"}]),
    ])


def build_sql_passthrough_model(sql: int, plain: int) -> AuditContext:
    """`sql` formulas calling sql_int_aggregate_op, then `plain` ordinary ones."""
    formulas = [
        {"name": f"F{i}", "expr": f"sql_int_aggregate_op(SUM(col{i}))"}
        for i in range(sql)
    ] + [
        {"name": f"G{i}", "expr": f"sum([col{i}])"}
        for i in range(plain)
    ]
    return make_context(models=[build_data_model(formulas=formulas)])


def data_model_half_sql_passthrough() -> AuditContext:
    """5 of 10 formulas are SQL pass-through (50%): D9 fires LOW."""
    return build_sql_passthrough_model(5, 5)


def data_model_one_in_five_sql_passthrough() -> AuditContext:
    """1 of 5 formulas (exactly 20%): not over the line."""
    return build_sql_passthrough_model(1, 4)


# test_checks_data_trip.py's shapes (from the model TML schema: joins carry no `name`,
# model columns no `data_type` and no `db_column_name`)

def build_trip_col(display, table, col, column_type) -> dict:
    """A model `columns[]` entry: name + column_id + properties.column_type."""
    return {
        "name": display,
        "column_id": f"{table}::{col}",
        "properties": {"column_type": column_type},
    }


def build_fact_columns(table, measures=4, attributes=3) -> list:
    """`measures` MEASURE + `attributes` ATTRIBUTE columns on one table (more than 3
    MEASURE columns reads as a fact table)."""
    cols = [build_trip_col(f"{table} M{i}", table, f"M{i}", "MEASURE") for i in range(measures)]
    cols += [build_trip_col(f"{table} A{i}", table, f"A{i}", "ATTRIBUTE")
             for i in range(attributes)]
    return cols


def build_inline_join(with_table, on, jtype="INNER", cardinality="MANY_TO_ONE") -> dict:
    """Scenario B join — exactly the four keys real inline joins carry."""
    return {"with": with_table, "on": on, "type": jtype, "cardinality": cardinality}


def build_trip_data_model(name="Sales", guid="m-1", model_tables=None, columns=None) -> dict:
    model_tables, columns = copy.deepcopy((model_tables, columns))
    return {"guid": guid, "model": {
        "name": name,
        "model_tables": model_tables or [],
        "columns": columns or [],
        "formulas": [],
        "properties": {"join_progressive": True},
    }}


def build_table_entry(name, fqn, joins=None, alias=None) -> dict:
    entry = {"name": name, "fqn": fqn}
    if alias:
        entry["alias"] = alias
    if joins:
        entry["joins"] = copy.deepcopy(joins)
    return entry


def build_search_row(guid, name, subtype="ONE_TO_ONE_LOGICAL", connection="Snowflake Prod",
                     db="AGENT_SKILLS", schema="PUBLIC") -> dict:
    """A `/metadata/search` row with `include_headers` (what build_context stores)."""
    return {
        "metadata_id": guid,
        "metadata_name": name,
        "metadata_type": "LOGICAL_TABLE",
        "metadata_header": {
            "id": guid,
            "name": name,
            "type": subtype,
            "dataSourceName": connection,
            "databaseStripe": db,
            "schemaStripe": schema,
        },
    }


# D3 — join types

def build_join_type_ctx(jtype) -> AuditContext:
    return make_context(models=[build_trip_data_model(model_tables=[
        build_table_entry("ORDERS", "tbl-orders", joins=[build_inline_join(
            "CUSTOMER", "[ORDERS::CUST_ID] = [CUSTOMER::ID]", jtype=jtype)]),
        build_table_entry("CUSTOMER", "tbl-customer"),
    ])])


def data_join_full_outer() -> AuditContext:
    """`OUTER` is ThoughtSpot's full outer join: D3 HIGH."""
    return build_join_type_ctx("OUTER")


def data_join_inner() -> AuditContext:
    return build_join_type_ctx("INNER")


# D6 — grain consistency

def build_grain_ctx(measures, attributes) -> AuditContext:
    cols = build_fact_columns("ORDERS", measures=measures, attributes=attributes)
    return make_context(models=[build_trip_data_model(
        model_tables=[build_table_entry("ORDERS", "tbl-orders")], columns=cols)])


def data_fact_table_mostly_attributes() -> AuditContext:
    """4 MEASURE + 3 ATTRIBUTE: a fact table 42.9% attributes (D6 fires)."""
    return build_grain_ctx(4, 3)


def data_fact_table_mostly_measures() -> AuditContext:
    """4 MEASURE + 2 ATTRIBUTE: 33% attributes."""
    return build_grain_ctx(4, 2)


def data_dimension_mostly_attributes() -> AuditContext:
    """1 MEASURE + 8 ATTRIBUTE: a dimension, which may be nearly all attributes."""
    return build_grain_ctx(1, 8)


# D8 — duplicate physical-table objects

def data_metadata_duplicate_table() -> AuditContext:
    return make_context(metadata=[build_search_row("tbl-1", "ORDERS"),
                                  build_search_row("tbl-2", "ORDERS")])


def data_metadata_same_name_other_schema() -> AuditContext:
    return make_context(metadata=[build_search_row("tbl-1", "ORDERS", schema="PUBLIC"),
                                  build_search_row("tbl-2", "ORDERS", schema="STAGING")])


def data_metadata_duplicate_models() -> AuditContext:
    """Two Models over the same tables are D7's business, not D8's."""
    return make_context(metadata=[build_search_row("m-1", "Sales", subtype="WORKSHEET"),
                                  build_search_row("m-2", "Sales", subtype="WORKSHEET")])


# D10 — zero-column tables

def data_model_zero_column_bridge_and_leaf() -> AuditContext:
    """ORDERS has columns and joins to BRIDGE; ORPHAN has neither."""
    return make_context(models=[build_trip_data_model(
        model_tables=[
            build_table_entry("ORDERS", "tbl-orders", joins=[build_inline_join(
                "BRIDGE", "[ORDERS::CUST_ID] = [BRIDGE::CUST_ID]")]),
            build_table_entry("BRIDGE", "tbl-bridge"),
            build_table_entry("ORPHAN", "tbl-orphan"),
        ],
        columns=build_fact_columns("ORDERS", measures=2, attributes=2))])


def data_model_zero_column_leaf() -> AuditContext:
    """ORDERS has columns; ORPHAN has none and joins nothing: a leaf (D10 MEDIUM)."""
    return make_context(models=[build_trip_data_model(
        model_tables=[build_table_entry("ORDERS", "tbl-orders"),
                      build_table_entry("ORPHAN", "tbl-orphan")],
        columns=build_fact_columns("ORDERS", measures=2, attributes=2))])


def data_model_every_table_has_columns() -> AuditContext:
    return make_context(models=[build_trip_data_model(
        model_tables=[
            build_table_entry("ORDERS", "tbl-orders", joins=[build_inline_join(
                "CUSTOMER", "[ORDERS::CUST_ID] = [CUSTOMER::ID]")]),
            build_table_entry("CUSTOMER", "tbl-customer"),
        ],
        columns=(build_fact_columns("ORDERS", measures=2, attributes=2)
                 + build_fact_columns("CUSTOMER", measures=0, attributes=3)))])


def data_model_aliased_table_with_columns() -> AuditContext:
    """LOT_DRUGS aliased LOT_DRUGS_1, whose columns carry the alias: legacy D10 (by
    name) still calls it zero-column (BL-305, the xfail in test_checks_data_trip.py)."""
    return make_context(models=[build_trip_data_model(
        model_tables=[build_table_entry("LOT_DRUGS", "tbl-lot", alias="LOT_DRUGS_1")],
        columns=[build_trip_col("Molecule", "LOT_DRUGS_1", "MOLECULE", "ATTRIBUTE")])])


# D11 — fan-out risk

def build_fanout_ctx(target, target_columns, cardinality="ONE_TO_MANY") -> AuditContext:
    return make_context(models=[build_trip_data_model(
        model_tables=[
            build_table_entry("ORDERS", "tbl-orders", joins=[build_inline_join(
                target, f"[ORDERS::ID] = [{target}::ORDER_ID]",
                jtype="INNER", cardinality=cardinality)]),
            build_table_entry(target, "tbl-target"),
        ],
        columns=build_fact_columns("ORDERS") + target_columns)])


def build_dimension_columns(table="CUSTOMER") -> list:
    return [build_trip_col(f"Cust A{i}", table, f"A{i}", "ATTRIBUTE") for i in range(4)]


def data_fanout_fact_to_fact() -> AuditContext:
    """ORDERS -> SHIPMENTS ONE_TO_MANY, both fact tables: D11 MEDIUM."""
    return build_fanout_ctx("SHIPMENTS", build_fact_columns("SHIPMENTS"))


def data_fanout_fact_to_dimension() -> AuditContext:
    return build_fanout_ctx("CUSTOMER", build_dimension_columns())


def data_fanout_many_to_one() -> AuditContext:
    """MANY_TO_ONE cannot fan out."""
    return build_fanout_ctx("CUSTOMER", build_fact_columns("CUSTOMER"),
                            cardinality="MANY_TO_ONE")


def data_fanout_many_to_many_dimension() -> AuditContext:
    """MANY_TO_MANY to a dimension: INFO, worded ONE_TO_MANY (the xfail in
    test_checks_data_trip.py)."""
    return build_fanout_ctx("CUSTOMER", build_dimension_columns(), cardinality="MANY_TO_MANY")


# D12 — conformed dimension divergence

def build_two_models(type_a, type_b) -> AuditContext:
    return make_context(models=[
        build_trip_data_model(name="Sales", guid="m-1",
                              model_tables=[build_table_entry("ORDERS", "tbl-orders")],
                              columns=[build_trip_col("Discount", "ORDERS", "DISCOUNT", type_a)]),
        build_trip_data_model(name="Returns", guid="m-2",
                              model_tables=[build_table_entry("RETURNS", "tbl-returns")],
                              columns=[build_trip_col("Discount", "RETURNS", "DISCOUNT", type_b)]),
    ])


def data_models_divergent_column_type() -> AuditContext:
    """Discount is a MEASURE in Sales and an ATTRIBUTE in Returns: D12 fires."""
    return build_two_models("MEASURE", "ATTRIBUTE")


def data_models_consistent_column_type() -> AuditContext:
    return build_two_models("MEASURE", "MEASURE")


def data_model_single_discount() -> AuditContext:
    return make_context(models=[build_trip_data_model(
        model_tables=[build_table_entry("ORDERS", "tbl-orders")],
        columns=[build_trip_col("Discount", "ORDERS", "DISCOUNT", "MEASURE")])])


# test_alias_and_join_names.py's D shapes (BL-305)

def data_model_aliased_role_playing() -> AuditContext:
    """One physical table joined twice, the second under an alias (SHIP_TO), whose
    three columns carry the alias."""
    return make_context(models=[{"guid": "m-1", "model": {
        "name": "Sales",
        "columns": (
            [{"name": f"M{i}", "column_id": f"ORDERS::M{i}",
              "properties": {"column_type": "MEASURE"}} for i in range(4)]
            + [{"name": f"A{i}", "column_id": f"SHIP_TO::A{i}",
                "properties": {"column_type": "ATTRIBUTE"}} for i in range(3)]
        ),
        "model_tables": [
            {"name": "ORDERS", "joins": [{"with": "SHIP_TO",
                                          "on": "[ORDERS::M0] = [SHIP_TO::A0]",
                                          "type": "INNER", "cardinality": "MANY_TO_ONE"}]},
            {"name": "CUSTOMERS", "alias": "SHIP_TO"},
        ],
    }}])


def data_model_anonymous_outer_join() -> AuditContext:
    """An OUTER join with no `name`: D3 reports it under its synthesised label."""
    return make_context(models=[{"guid": "m-1", "model": {
        "name": "S", "columns": [], "model_tables": [
            {"name": "ORDERS", "joins": [{"with": "RETURNS", "type": "OUTER"}]}]}}])


# ── edges and sweeps (not from a legacy test; each pins a legacy reading) ────

def build_star_model(k: int) -> AuditContext:
    """F joined to D0..D<k-1>: k joins, k + 1 tables, join depth 1."""
    tables = [{"name": "F", "fqn": "t-F", "joins": [
        build_inline_join(f"D{i}", f"[F::K{i}] = [D{i}::K]") for i in range(k)]}]
    tables += [{"name": f"D{i}", "fqn": f"t-D{i}"} for i in range(k)]
    return make_context(models=[build_data_model(model_tables=tables)])


def build_sized_model(tables=1, columns=0, formulas=0) -> AuditContext:
    return make_context(models=[build_data_model(
        model_tables=build_data_tables(tables) if tables else None,
        columns=[build_data_col(f"C{i}") for i in range(columns)],
        formulas=[{"name": f"F{i}", "expr": "1"} for i in range(formulas)])])


#: Join types around D3's three: case, unknown and empty spellings.
JOIN_TYPES = ["OUTER", "LEFT_OUTER", "RIGHT_OUTER", "INNER", "outer", "Left_Outer",
              "FULL_OUTER", "", None]

#: Cardinalities around D11's substring test.
CARDINALITIES = ["ONE_TO_MANY", "MANY_TO_MANY", "one_to_many", "Many_To_Many",
                 "MANY_TO_ONE", "ONE_TO_ONE", "X_ONE_TO_MANY_X", "", None]


def data_join_type_absent() -> AuditContext:
    """An inline join with no `type` key at all."""
    return make_context(models=[build_trip_data_model(model_tables=[
        build_table_entry("ORDERS", "tbl-orders", joins=[
            {"with": "CUSTOMER", "on": "[ORDERS::K] = [CUSTOMER::K]"}]),
        build_table_entry("CUSTOMER", "tbl-customer")])])


def data_model_aliased_fact() -> AuditContext:
    """ORDERS aliased O, 4 MEASURE + 4 ATTRIBUTE columns carrying the alias, joined
    ONE_TO_MANY from a fact by its alias: D6 sees the fact (by alias); D10 calls it a
    zero-column leaf and D11 an unknown end (both by name, BL-305)."""
    cols = (build_fact_columns("O", measures=4, attributes=4)
            + build_fact_columns("SHIP", measures=4, attributes=0))
    return make_context(models=[build_trip_data_model(
        model_tables=[
            build_table_entry("SHIPMENTS", "tbl-ship", alias="SHIP", joins=[
                build_inline_join("O", "[SHIP::M0] = [O::M0]", cardinality="ONE_TO_MANY")]),
            build_table_entry("ORDERS", "tbl-orders", alias="O")],
        columns=cols)])


def data_model_join_edges() -> AuditContext:
    """D5/D10 join-graph edges: a join declared on an alias, a join `with` a table the
    model does not list, a `joins: None`, and a column_id without "::"."""
    return make_context(models=[build_trip_data_model(
        model_tables=[
            build_table_entry("ORDERS", "tbl-orders", alias="ORD", joins=[
                build_inline_join("CUST", "[ORD::C] = [CUST::C]")]),
            {"name": "CUSTOMER", "alias": "CUST", "fqn": "tbl-cust"},
            {"name": "GEO", "fqn": "tbl-geo", "joins": None},
            build_table_entry("DATES", "tbl-dates", joins=[
                build_inline_join("CALENDAR", "[DATES::D] = [CALENDAR::D]")]),
            {"name": "ORD", "fqn": "tbl-ord-name"},
        ],
        columns=[build_trip_col("Amount", "ORD", "AMOUNT", "MEASURE"),
                 {"name": "Loose", "column_id": "LOOSE", "properties": {"column_type": "ATTRIBUTE"}},
                 {"name": "No Id", "properties": {"column_type": "ATTRIBUTE"}}])])


def data_models_overlap_edges() -> AuditContext:
    """D7: fqn absent (its name stands in), an explicit `fqn: None`, a table with
    neither (""), exactly half shared (0.5 is not over the line), an empty model."""
    def m(name, guid, tables):
        return build_trip_data_model(name=name, guid=guid, model_tables=tables)
    return make_context(models=[
        m("ByName", "g-1", [{"name": "T1"}, {"name": "T2", "fqn": "f2"}]),
        m("ByFqn", "g-2", [{"name": "X", "fqn": "T1"}, {"name": "Y", "fqn": "f2"}]),
        m("NoneFqn", "g-3", [{"name": "T1", "fqn": None}, {"name": "Y", "fqn": "f2"}]),
        m("Half", "g-4", [{"name": "T1"}, {"name": "T2", "fqn": "f2"}, {"fqn": "f3"},
                          {"fqn": "f4"}]),
        m("Blank", "g-5", [{}, {"name": "T2", "fqn": "f2"}]),
        {"guid": "g-6", "model": {"name": "Empty", "model_tables": []}},
        m("NoneToo", "g-7", [{"name": "Q", "fqn": None}, {"name": "Y", "fqn": "f2"}]),
    ])


def data_metadata_edges() -> AuditContext:
    """D8: flat rows (no metadata_header), absent stripes ("") grouping with explicit
    "", None apart from "", a SQL_VIEW beside a Table on one physical table, an absent
    id, and a WORKSHEET that never counts."""
    def row(guid, name, kind="ONE_TO_ONE_LOGICAL", **header):
        h = {"id": guid, "name": name, "type": kind, **header}
        return {"metadata_header": {k: v for k, v in h.items() if v != "<absent>"}}
    return make_context(metadata=[
        row("a1", "ORDERS", dataSourceName="SF", databaseStripe="DB", schemaStripe="S"),
        row("a2", "ORDERS", "SQL_VIEW", dataSourceName="SF", databaseStripe="DB",
            schemaStripe="S"),
        row("<absent>", "ORDERS", dataSourceName="SF", databaseStripe="DB", schemaStripe="S"),
        {"id": "b1", "name": "LINES", "type": "ONE_TO_ONE_LOGICAL"},
        {"id": "b2", "name": "LINES", "type": "ONE_TO_ONE_LOGICAL", "dataSourceName": ""},
        row("c1", "ITEMS", dataSourceName=None),
        row("c2", "ITEMS", dataSourceName=""),
        row("d1", "SALES", "WORKSHEET"),
        row("d2", "SALES", "WORKSHEET"),
    ])


def data_model_sql_passthrough_spellings() -> AuditContext:
    """D9: every function in any case, a near miss, a formula with no `expr`."""
    formulas = [{"name": "A", "expr": "SQL_STRING_AGGREGATE_OP('x')"},
                {"name": "B", "expr": "sql_bool_aggregate_op('y')"},
                {"name": "C", "expr": "sql_date_aggregate_op('z')"},
                {"name": "D"}, {"name": "E", "expr": "Sql_Int_Aggregate_Op(1)"}]
    return make_context(models=[build_data_model(formulas=formulas)])


def data_models_column_type_edges() -> AuditContext:
    """D12: db_column_name over name; one model naming a column twice with different
    types (the later wins); two models sharing a name; a blank type skipped; a
    column with neither name."""
    def col(name, ctype, db=None, **kw):
        c = {"name": name, "properties": {"column_type": ctype}, **kw}
        if db:
            c["db_column_name"] = db
        return c
    return make_context(models=[
        build_trip_data_model(name="A", guid="g-a", columns=[
            col("Region", "ATTRIBUTE", db="REGION"), col("Amount", "MEASURE"),
            col("Amount", "ATTRIBUTE"), col("Blank", ""), {"properties": {"column_type": "MEASURE"}}]),
        build_trip_data_model(name="B", guid="g-b", columns=[
            col("Region Name", "MEASURE", db="REGION"), col("Amount", "ATTRIBUTE"),
            col("Blank", "MEASURE"), {"properties": {"column_type": "ATTRIBUTE"}}]),
        build_trip_data_model(name="A", guid="g-a2", columns=[col("Region", "MEASURE",
                                                                  db="REGION")]),
        build_trip_data_model(name="C", guid="g-c", columns=[col("Amount", "ATTRIBUTE")]),
    ])


# Raw names and guids: present-and-None reaches the finding as None, absent as "".

def data_names_none() -> AuditContext:
    """Every D scope with `name: None` / `guid: None` (or `id: None`), each firing."""
    cols = build_fact_columns("ORDERS", measures=4, attributes=4) + [
        {"name": None, "db_column_name": None, "properties": {"column_type": "MEASURE"}}]
    model = build_data_model(
        name=None, guid=None, columns=cols,
        model_tables=[{"name": "ORDERS", "joins": [build_inline_join(
            None, "[ORDERS::A] = [X::A] and [ORDERS::B] = [X::B]", jtype="OUTER",
            cardinality="ONE_TO_MANY")]},
            {"name": None, "fqn": "t-none"}, {"name": "Z"}] + build_data_tables(13),
        formulas=[{"name": None, "expr": "sql_int_aggregate_op(1)"}])
    twin = build_data_model(name="Twin", guid="g-twin", model_tables=model["model"]["model_tables"],
                            columns=[{"name": None, "properties": {"column_type": "ATTRIBUTE"}}])
    return make_context(models=[model, twin], metadata=[
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": None, "id": None}},
        {"metadata_header": {"type": "SQL_VIEW", "name": None, "id": "x"}}])


def data_names_absent() -> AuditContext:
    """Every D scope with no `name` / `guid` (or `id`) key, each firing."""
    cols = build_fact_columns("ORDERS", measures=4, attributes=4) + [
        {"properties": {"column_type": "MEASURE"}}]
    model = build_data_model(
        columns=cols,
        model_tables=[{"name": "ORDERS", "joins": [build_inline_join(
            "X", "[ORDERS::A] = [X::A] and [ORDERS::B] = [X::B]", jtype="OUTER",
            cardinality="ONE_TO_MANY")]}, {"fqn": "t-anon"}, {"name": "Z"}]
        + build_data_tables(13),
        formulas=[{"expr": "sql_int_aggregate_op(1)"}])
    del model["guid"], model["model"]["name"]
    twin = build_data_model(name="Twin", guid="g-twin", model_tables=model["model"]["model_tables"],
                            columns=[{"properties": {"column_type": "ATTRIBUTE"}}])
    return make_context(models=[model, twin], metadata=[{"type": "SQL_VIEW"},
                                                         {"type": "SQL_VIEW"}])


def data_lists_none() -> AuditContext:
    """`model_tables`, `columns`, `formulas`, `joins`, `properties` None or empty, and
    a model document with no `model` key."""
    return make_context(models=[
        {"guid": "g-1", "model": {"name": "Nones", "model_tables": None, "columns": None,
                                  "formulas": None, "properties": None}},
        {"guid": "g-2", "model": {"name": "Joins None", "model_tables": [
            {"name": "A", "joins": None}, {"name": "B", "joins": []}], "columns": [],
            "formulas": [], "properties": {}}},
        {"guid": "g-3"},
        {"guid": "g-4", "model": {}},
    ])


def data_single_model_malformed_column() -> AuditContext:
    """One Model with a column whose `properties` is a list: legacy D12 reads no
    column with fewer than two Models, so this must not raise (it would in D12's
    loop)."""
    return make_context(models=[
        {"guid": "g-1", "model": {"name": "One", "model_tables": [], "columns": [
            {"name": "list_props", "column_id": "T::list_props", "properties": ["MEASURE"]}]}}])


#: Scalar pairs Python treats as equal though their types differ: legacy D7's set
#: intersection and D8's dict grouping merge them, so the engine must too.
EQUAL_SCALARS = [(1, True), (1, 1.0), (0, False)]


def build_overlap_scalar_pair(a, b) -> AuditContext:
    """D7: two Models whose table sets are {a, "s"} and {b, "s"}."""
    return make_context(models=[
        build_trip_data_model(name="A", guid="g-a", model_tables=[{"fqn": a}, {"fqn": "s"}]),
        build_trip_data_model(name="B", guid="g-b", model_tables=[{"fqn": b}, {"fqn": "s"}])])


def build_duplicate_scalar_pair(key, a, b) -> AuditContext:
    """D8: two Table headers equal but for `key`, which is `a` on one and `b` on the
    other."""
    def row(guid, value):
        header = {"id": guid, "name": "ORDERS", "type": "ONE_TO_ONE_LOGICAL",
                  "dataSourceName": "SF", "databaseStripe": "DB", "schemaStripe": "S"}
        header[key] = value
        return {"metadata_header": header}
    return make_context(metadata=[row("t-1", a), row("t-2", b)])


# Every D input, for the equivalence test — listed by hand (see AI_INPUTS).
D_INPUTS = {fn.__name__: fn for fn in (
    data_model_sixteen_tables, data_model_small, data_model_six_tables_not_progressive,
    data_model_six_tables_progressive, data_model_three_tables_not_progressive,
    data_model_unjoined_table, data_model_all_joined, data_models_identical_tables,
    data_models_disjoint_tables, data_model_half_sql_passthrough,
    data_model_one_in_five_sql_passthrough,
    data_join_full_outer, data_join_inner, data_fact_table_mostly_attributes,
    data_fact_table_mostly_measures, data_dimension_mostly_attributes,
    data_metadata_duplicate_table, data_metadata_same_name_other_schema,
    data_metadata_duplicate_models, data_model_zero_column_bridge_and_leaf,
    data_model_zero_column_leaf, data_model_every_table_has_columns,
    data_model_aliased_table_with_columns, data_fanout_fact_to_fact,
    data_fanout_fact_to_dimension, data_fanout_many_to_one,
    data_fanout_many_to_many_dimension, data_models_divergent_column_type,
    data_models_consistent_column_type, data_model_single_discount,
    data_model_aliased_role_playing, data_model_anonymous_outer_join,
    data_join_type_absent, data_model_aliased_fact, data_model_join_edges,
    data_models_overlap_edges, data_metadata_edges, data_model_sql_passthrough_spellings,
    data_models_column_type_edges, data_names_none, data_names_absent, data_lists_none,
    data_single_model_malformed_column,
    # shared with P (perf.py) and the generic engine inputs (common.py)
    join_keys_varchar, join_keys_integer, join_keys_type_on_model_ignored,
    join_keys_composite, join_keys_table_missing,
    referencing_join_varchar, referencing_join_integer, referencing_join_outer,
    referencing_join_model_type_override, referencing_join_table_missing,
    registry_wide_not_progressive, registry_empty_context, registry_populated_context,
    metadata_duplicate_tables, models_divergent_column_types, models_overlapping_tables,
    model_role_playing_dimension, demo_corpus_models,
)}
D_INPUTS.update({f"join_type_{i}": (lambda t=t: build_join_type_ctx(t))
                 for i, t in enumerate(JOIN_TYPES)})
D_INPUTS.update({f"fanout_{kind}_{i}": (lambda c=c, cols=cols: build_fanout_ctx(
                 "TARGET", cols("TARGET"), cardinality=c))
                 for i, c in enumerate(CARDINALITIES)
                 for kind, cols in (("fact", build_fact_columns),
                                    ("dim", build_dimension_columns))})
D_INPUTS.update({f"grain_{m}_{a}": (lambda m=m, a=a: build_grain_ctx(m, a))
                 for m, a in ((4, 3), (4, 2), (6, 4), (4, 0), (5, 4), (0, 3), (1, 8))})
D_INPUTS.update({f"sql_passthrough_{s}_{p}": (lambda s=s, p=p: build_sql_passthrough_model(s, p))
                 for s, p in ((0, 0), (0, 3), (1, 4), (1, 3), (2, 7), (1, 0), (5, 5))})
D_INPUTS.update({f"sized_tables_{n}": (lambda n=n: build_sized_model(tables=n))
                 for n in (0, 1, 2, 5, 6, 10, 11, 15, 16)})
D_INPUTS.update({f"sized_columns_{n}": (lambda n=n: build_sized_model(columns=n))
                 for n in (50, 51, 75, 76)})
D_INPUTS.update({f"sized_formulas_{n}": (lambda n=n: build_sized_model(formulas=n))
                 for n in (30, 31, 50, 51)})
D_INPUTS.update({f"star_{k}": (lambda k=k: build_star_model(k)) for k in (8, 9, 12, 13)})
D_INPUTS.update({f"chain_{n}_tables": (lambda n=n: build_join_chain(
                 [chr(ord("A") + i) for i in range(n)])) for n in (4, 5, 6, 7)})
D_INPUTS.update({f"overlap_scalars_{a!r}_{b!r}":
                 (lambda a=a, b=b: build_overlap_scalar_pair(a, b)) for a, b in EQUAL_SCALARS})
D_INPUTS.update({f"duplicate_{key}_{a!r}_{b!r}":
                 (lambda key=key, a=a, b=b: build_duplicate_scalar_pair(key, a, b))
                 for key, (a, b) in (("name", (1, True)), ("name", (1, 1.0)),
                                     ("schemaStripe", (0, False)))})
