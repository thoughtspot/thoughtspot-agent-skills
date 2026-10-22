"""H (Human Readiness): the inputs the legacy H-check tests use, and H_INPUTS.

The legacy H checks (checks_human.py) are exercised by test_checks_human.py,
test_checks_human_trip.py, and the H halves of test_dead_guards.py (H5),
test_unreachable_checks.py (H7), test_audit_context.py (H4/H5 over contexts
`build_context` assembles, Set lookups failing included) and test_audit_snapshot.py
(H5's order over a replayed context). Those tests build their contexts here, so the H
rules' examples and the equivalence test (tests/test_audit_equivalence.py) run over the
very same inputs.
"""
from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import yaml

from ts_cli.audit.context import AuditContext, make_context

from .ai import demo_corpus_models
from .common import registry_empty_context, registry_populated_context


# ── test_checks_human.py's shapes ───────────────────────────────────────────

def build_human_model(name="Sales", guid="m-1", columns=None, formulas=None,
                      model_tables=None) -> dict:
    """A model document as test_checks_human.py has always built it (one table T1
    when none is given)."""
    columns, formulas, model_tables = copy.deepcopy((columns, formulas, model_tables))
    return {"guid": guid, "model": {
        "name": name, "model_tables": model_tables or [{"name": "T1"}],
        "columns": columns or [], "formulas": formulas or [], "properties": {}}}


def build_human_col(name="Amount", description="", is_hidden=False, column_id=None) -> dict:
    c = {"name": name, "description": description, "properties": {}}
    if is_hidden:
        c["properties"]["is_hidden"] = True
    if column_id:
        c["column_id"] = column_id
    return c


def human_generic_names() -> AuditContext:
    """3 of 10 columns have anti-pattern names (col1, field_2, val): 30%."""
    names = ["col1", "field_2", "val", "Amount", "Revenue", "Date", "Customer",
             "Product", "Region", "Sales"]
    return make_context(models=[build_human_model(
        columns=[build_human_col(n) for n in names])])


def human_good_names() -> AuditContext:
    return make_context(models=[build_human_model(columns=[
        build_human_col("Amount"), build_human_col("Revenue"),
        build_human_col("Order Date")])])


def human_hidden_unreferenced() -> AuditContext:
    return make_context(models=[build_human_model(columns=[
        build_human_col("Amount", is_hidden=True, column_id="T1::Amount"),
        build_human_col("Revenue", column_id="T1::Revenue")], formulas=[])])


def human_hidden_referenced() -> AuditContext:
    return make_context(models=[build_human_model(
        columns=[build_human_col("Amount", is_hidden=True, column_id="T1::Amount"),
                 build_human_col("Revenue", column_id="T1::Revenue")],
        formulas=[{"name": "Total", "expr": "sum([Amount])"}])])


def human_model_no_dependents() -> AuditContext:
    return make_context(models=[build_human_model(guid="m-1")], dependents={})


def human_model_with_dependents() -> AuditContext:
    return make_context(models=[build_human_model(guid="m-1")],
                        dependents={"m-1": [{"guid": "a-1", "type": "ANSWER"}]})


def human_stale_column() -> AuditContext:
    return make_context(models=[build_human_model(columns=[
        build_human_col("DO NOT USE Amount"), build_human_col("Revenue")])])


def human_clean_names() -> AuditContext:
    return make_context(models=[build_human_model(columns=[
        build_human_col("Amount"), build_human_col("Revenue")])])


# ── test_checks_human_trip.py's shapes ──────────────────────────────────────
# GUIDs in the shapes the v2 API returns them.

HUMAN_MODEL_GUID = "0a1b2c3d-1111-4a5b-8c9d-000000000001"   # the Model TML's root `guid`
HUMAN_TABLE_FQN = "0a1b2c3d-2222-4a5b-8c9d-000000000002"    # model_tables[].fqn: a Table
HUMAN_SET_GUID = "0a1b2c3d-3333-4a5b-8c9d-000000000003"
HUMAN_ANSWER_1 = "0a1b2c3d-4444-4a5b-8c9d-000000000004"
HUMAN_ANSWER_2 = "0a1b2c3d-4444-4a5b-8c9d-000000000005"

HUMAN_GOOD_DESC = "Net revenue recognised per order line, in USD, excluding tax."
HUMAN_MARGIN = "( [Revenue] - [Cost] ) / [Revenue]"
HUMAN_MARGIN_SPACED = "( [Revenue] - [Cost] )   /  [Revenue]"   # same once normalised
HUMAN_NEW_RATE = "sum([Returns]) / sum([Orders])"


def build_trip_human_model(guid=HUMAN_MODEL_GUID, name="Retail Sales", columns=None,
                           formulas=None, model_tables=None) -> dict:
    """A Model TML per agents/shared/schemas/thoughtspot-model-tml.md."""
    columns, formulas, model_tables = copy.deepcopy((columns, formulas, model_tables))
    return {"guid": guid, "model": {
        "name": name,
        "model_tables": model_tables if model_tables is not None else [
            {"name": "SALES", "fqn": HUMAN_TABLE_FQN}],
        "columns": columns or [], "formulas": formulas or [], "properties": {}}}


def build_trip_human_col(name, description=None) -> dict:
    col = {"name": name, "column_id": f"SALES::{name.upper().replace(' ', '_')}",
           "properties": {"column_type": "ATTRIBUTE"}}
    if description is not None:
        col["description"] = description
    return col


def build_human_formula(name, expr) -> dict:
    return {"id": f"formula_{name}", "name": name, "expr": expr,
            "was_auto_generated": False}


def build_human_answer(guid, name, source_fqn=HUMAN_MODEL_GUID, source_name="Retail Sales",
                       formulas=None, tables=None) -> dict:
    """An Answer TML per agents/shared/schemas/thoughtspot-answer-tml.md:24-27.

    `tables[].fqn` is the GUID of the data source — the Model the answer was built on,
    or a Table when it was built straight off one."""
    formulas, tables = copy.deepcopy((formulas, tables))
    return {"guid": guid, "answer": {
        "name": name, "display_mode": "TABLE_MODE",
        "tables": tables if tables is not None else [
            {"id": source_name, "name": source_name, "fqn": source_fqn}],
        "search_query": "[Revenue] by [Region]",
        "answer_columns": [{"name": "Revenue"}, {"name": "Region"}],
        "formulas": formulas or []}}


def build_human_dep(guid, name, dep_type, source_guid) -> dict:
    """One row as `_normalize_dependents_response` (commands/metadata.py) emits it."""
    bucket = {"SET": "COHORT", "ANSWER": "QUESTION_ANSWER_BOOK",
              "LIVEBOARD": "PINBOARD_ANSWER_BOOK"}[dep_type]
    return {"source_guid": source_guid, "guid": guid, "name": name, "type": dep_type,
            "raw_bucket": bucket, "author_id": "u-1", "author_display_name": "Dana Ruiz"}


def _set_row() -> dict:
    return build_human_dep(HUMAN_SET_GUID, "FY24 Top Accounts", "SET", HUMAN_MODEL_GUID)


def human_description_short() -> AuditContext:
    return make_context(models=[build_trip_human_model(columns=[
        build_trip_human_col("Revenue", "Revenue."),
        build_trip_human_col("Region", HUMAN_GOOD_DESC)])])


def human_description_long() -> AuditContext:
    long_desc = "Gross merchandise value for the order line. " * 12   # 527 stripped
    return make_context(models=[build_trip_human_model(columns=[
        build_trip_human_col("GMV", long_desc)])])


def human_description_boilerplate() -> AuditContext:
    return make_context(models=[build_trip_human_model(columns=[
        build_trip_human_col("Revenue", "The total revenue recognised for this order line.")])])


def human_description_two_short() -> AuditContext:
    return make_context(models=[build_trip_human_model(columns=[
        build_trip_human_col("Revenue", "Revenue."), build_trip_human_col("Cost", "Cost."),
        build_trip_human_col("Region", HUMAN_GOOD_DESC)])])


def human_description_clean() -> AuditContext:
    return make_context(models=[build_trip_human_model(columns=[
        build_trip_human_col("Revenue", HUMAN_GOOD_DESC),
        build_trip_human_col("Region",
                             "Sales region the store is assigned to, per the FY24 map."),
        build_trip_human_col("Order Date"),      # no description: A1's remit, not H2's
        build_trip_human_col("Store", "")])])    # empty: skipped


def human_set_without_consumers() -> AuditContext:
    """The Set WAS looked up (its guid keys `dependents`) and has no consumers."""
    return make_context(models=[build_trip_human_model()],
                        dependents={HUMAN_MODEL_GUID: [_set_row()], HUMAN_SET_GUID: []})


def human_set_with_consumer() -> AuditContext:
    return make_context(models=[build_trip_human_model()], dependents={
        HUMAN_MODEL_GUID: [_set_row()],
        HUMAN_SET_GUID: [build_human_dep(HUMAN_ANSWER_1, "Top Accounts QBR", "ANSWER",
                                         HUMAN_SET_GUID)]})


def human_dependents_not_sets() -> AuditContext:
    return make_context(models=[build_trip_human_model()], dependents={HUMAN_MODEL_GUID: [
        build_human_dep(HUMAN_ANSWER_1, "Revenue by Region", "ANSWER", HUMAN_MODEL_GUID),
        build_human_dep(HUMAN_ANSWER_2, "Exec Liveboard", "LIVEBOARD", HUMAN_MODEL_GUID)]})


def human_rich_context() -> AuditContext:
    """A context fat enough to trip several human checks (H6's stub returns nothing)."""
    return make_context(
        models=[build_trip_human_model(
            columns=[build_trip_human_col("col1", "Bad.")],
            formulas=[build_human_formula("Margin", "[Revenue] - [Cost]")])],
        tables={HUMAN_TABLE_FQN: {"guid": HUMAN_TABLE_FQN,
                                  "table": {"name": "SALES", "columns": []}}},
        dependents={HUMAN_MODEL_GUID: [_set_row()]},
        answers=[build_human_answer(HUMAN_ANSWER_1, "West QBR", formulas=[
            build_human_formula("Margin", "[Revenue] - [Cost]")])],
        model_guids=[HUMAN_MODEL_GUID])


def human_no_answers() -> AuditContext:
    return make_context(models=[build_trip_human_model()], answers=[])


def human_answer_source_without_fqn() -> AuditContext:
    return make_context(models=[build_trip_human_model()], answers=[
        build_human_answer(HUMAN_ANSWER_1, "Revenue by Region",
                           tables=[{"id": "Retail Sales", "name": "Retail Sales"}])])


def _one_off_model() -> dict:
    return build_trip_human_model(formulas=[build_human_formula("Revenue LY",
                                                                "sum([Revenue])")])


def human_formula_in_two_answers() -> AuditContext:
    return make_context(models=[_one_off_model()], answers=[
        build_human_answer(HUMAN_ANSWER_1, "West QBR",
                           formulas=[build_human_formula("Margin", HUMAN_MARGIN)]),
        build_human_answer(HUMAN_ANSWER_2, "East QBR",
                           formulas=[build_human_formula("Margin", HUMAN_MARGIN_SPACED)])])


def human_formula_in_two_answers_same_text() -> AuditContext:
    return make_context(models=[_one_off_model()], answers=[
        build_human_answer(HUMAN_ANSWER_1, "West QBR",
                           formulas=[build_human_formula("Margin", HUMAN_MARGIN)]),
        build_human_answer(HUMAN_ANSWER_2, "East QBR",
                           formulas=[build_human_formula("Margin", HUMAN_MARGIN)])])


def human_formula_in_one_answer() -> AuditContext:
    return make_context(models=[_one_off_model()], answers=[build_human_answer(
        HUMAN_ANSWER_1, "West QBR", formulas=[build_human_formula("Margin", HUMAN_MARGIN)])])


def human_formula_on_model_and_two_answers() -> AuditContext:
    return make_context(
        models=[build_trip_human_model(formulas=[build_human_formula("Margin", HUMAN_MARGIN)])],
        answers=[build_human_answer(HUMAN_ANSWER_1, "West QBR",
                                    formulas=[build_human_formula("Margin", HUMAN_MARGIN)]),
                 build_human_answer(HUMAN_ANSWER_2, "East QBR",
                                    formulas=[build_human_formula("Margin", HUMAN_MARGIN)])])


def human_model_formula_without_answers() -> AuditContext:
    return make_context(models=[build_trip_human_model(formulas=[
        build_human_formula("Margin", HUMAN_MARGIN)])])


def human_formula_in_two_answers_model_without_formulas() -> AuditContext:
    return make_context(models=[build_trip_human_model()], answers=[
        build_human_answer(HUMAN_ANSWER_1, "West QBR",
                           formulas=[build_human_formula("Margin", HUMAN_MARGIN)]),
        build_human_answer(HUMAN_ANSWER_2, "East QBR",
                           formulas=[build_human_formula("Margin", HUMAN_MARGIN)])])


def human_answer_formula_duplicates_model() -> AuditContext:
    return make_context(
        models=[build_trip_human_model(formulas=[build_human_formula("Margin", HUMAN_MARGIN)])],
        answers=[build_human_answer(HUMAN_ANSWER_1, "West QBR", formulas=[
            build_human_formula("Margin %", HUMAN_MARGIN_SPACED)])])


def human_answer_formula_new() -> AuditContext:
    return make_context(
        models=[build_trip_human_model(formulas=[build_human_formula("Margin", HUMAN_MARGIN)])],
        answers=[build_human_answer(HUMAN_ANSWER_1, "West QBR", formulas=[
            build_human_formula("Return Rate", HUMAN_NEW_RATE)])])


# ── test_dead_guards.py (H5) and test_unreachable_checks.py (H7) ─────────────

def _guard_set_row() -> dict:
    return {"guid": "set-1", "type": "SET", "name": "FY24 Top Accounts"}


def guard_set_never_looked_up() -> AuditContext:
    """No `dependents` entry for the Set: "not looked up", never "no consumers"."""
    return make_context(dependents={"m-1": [_guard_set_row()]})


def guard_set_looked_up_no_consumers() -> AuditContext:
    return make_context(dependents={"m-1": [_guard_set_row()], "set-1": []})


def guard_set_looked_up_with_consumers() -> AuditContext:
    return make_context(dependents={"m-1": [_guard_set_row()], "set-1": [
        {"guid": "a-1", "type": "ANSWER", "name": "Uses the set"}]})


def build_answer_source_ctx(answer_fqn) -> AuditContext:
    """H7: Model `mdl-1` on Table `tbl-1` (in the context), one Answer on `answer_fqn`."""
    model = {"guid": "mdl-1", "model": {
        "name": "Sales", "model_tables": [{"name": "ORDERS", "fqn": "tbl-1"}]}}
    answer = {"guid": "a-1", "answer": {"name": "A", "tables": [{"fqn": answer_fqn}]}}
    return make_context(models=[model], answers=[answer],
                        tables={"tbl-1": {"table": {"name": "ORDERS"}}})


def answer_on_table() -> AuditContext:
    return build_answer_source_ctx("tbl-1")


def answer_on_model() -> AuditContext:
    return build_answer_source_ctx("mdl-1")


def answer_on_unknown_object() -> AuditContext:
    return build_answer_source_ctx("something-else")


def answer_without_table_refs() -> AuditContext:
    return make_context(models=[], answers=[{"guid": "a-1", "answer": {"name": "A"}}])


# ── test_audit_context.py: contexts `build_context` assembles (Set lookups) ──
# The real build_context over a fake client, with Set discovery and the consumer
# lookup patched: what a live H run hands the checks, failed lookups included.

SETS_ONE = {"sets": {"m1": [{"guid": "s1", "name": "B"}]}, "incomplete": [], "notes": []}


def build_response(body, ok=True, status=200):
    r = MagicMock()
    r.ok, r.status_code = ok, status
    r.json.return_value = body
    return r


def build_sample_model(name="Sales", guid="m-1") -> dict:
    return {"guid": guid, "model": {"name": name, "model_tables": [
        {"name": "ORDERS", "id": "ORDERS"}], "columns": [], "formulas": [], "properties": {}}}


def build_client_with_one_model(guid, name="Sales"):
    """A client whose export returns one Model TML; every search returns []."""
    edoc = yaml.safe_dump(build_sample_model(name=name, guid=guid))

    def post(url, json=None, **_kw):
        if url.endswith("/metadata/tml/export"):
            return build_response([{"edoc": edoc}])
        return build_response([])

    client = MagicMock()
    client.post.side_effect = post
    return client


def build_client_with_set_dependents(guid, dep_rows):
    """Model export + a Set dependents lookup carrying BOTH inaccessible flags true —
    the admin shape observed live on the SE demo cluster 2026-10-02 (ruling R17)."""
    edoc = yaml.safe_dump(build_sample_model(name="Sales", guid=guid))

    def post(url, json=None, **_kw):
        if url.endswith("/metadata/tml/export"):
            return build_response([{"edoc": edoc}])
        md = (json or {}).get("metadata") or [{}]
        if url.endswith("/metadata/search") and md[0].get("type") == "LOGICAL_COLUMN":
            return build_response([{"metadata_id": "s1", "dependent_objects": {
                "hasInaccessibleDependents": True,
                "areInaccessibleDependentsReturned": True,
                "dependents": {"s1": dep_rows}}}])
        return build_response([])

    client = MagicMock()
    client.post.side_effect = post
    return client


def build_consumers(dependents=None, other_types=None, error=None) -> dict:
    """A `fetch_consumers` result."""
    return {"dependents": dependents or [], "liveboards": {}, "unreadable": [],
            "other_types": other_types or [], "error": error}


def build_h_context(discovered, consumers=None, client=None) -> AuditContext:
    """`build_context(client, ["m1"], ["H"])` with `discover_sets` returning
    `discovered` and — unless None, which runs the real lookup — `fetch_consumers`
    returning `consumers`."""
    from ts_cli.audit.context import build_context
    client = client or build_client_with_one_model("m1")
    with patch("ts_cli.audit.context.discover_sets", return_value=copy.deepcopy(discovered)):
        if consumers is None:
            return build_context(client, ["m1"], ["H"])
        with patch("ts_cli.audit.context.fetch_consumers",
                   return_value=copy.deepcopy(consumers)):
            return build_context(client, ["m1"], ["H"])


def built_set_without_consumers() -> AuditContext:
    return build_h_context(SETS_ONE, build_consumers())


def built_set_with_consumer() -> AuditContext:
    return build_h_context(SETS_ONE, build_consumers(dependents=[
        {"guid": "a1", "name": "Uses B", "type": "ANSWER", "author_id": "u"}]))


def built_set_lookup_failed() -> AuditContext:
    """The consumer lookup errored: the Set is not recorded, only a warning."""
    return build_h_context(SETS_ONE, build_consumers(error="dependents lookup failed"))


def built_set_consumed_only_by_a_set() -> AuditContext:
    """R14: a Set whose only dependent is another Set is not recorded (a warning)."""
    return build_h_context(SETS_ONE, build_consumers(
        other_types=[{"guid": "s2", "name": "C", "type": "SET"}]))


def built_set_lookup_empty_response() -> AuditContext:
    """The real fetch_consumers over an empty `[]` body: it errors, so not recorded."""
    return build_h_context(SETS_ONE)


def built_set_hidden_dependents_none() -> AuditContext:
    """R17: inaccessible dependents returned, and there are none: an orphan."""
    return build_h_context(SETS_ONE, client=build_client_with_set_dependents("m1", {}))


def built_set_hidden_dependents_one() -> AuditContext:
    return build_h_context(SETS_ONE, client=build_client_with_set_dependents("m1", {
        "QUESTION_ANSWER_BOOK": [{"id": "a1", "name": "Uses B", "author": "u"}]}))


def built_set_discovery_incomplete() -> AuditContext:
    return build_h_context({"sets": {}, "incomplete": ["m1"], "notes": [
        {"kind": "discovery_failed", "object": "Sales (m1)",
         "detail": "cohort listing failed: 500"}]}, build_consumers())


def built_no_sets() -> AuditContext:
    return build_h_context({"sets": {}, "incomplete": [], "notes": []}, build_consumers())


def h4_model_with_answer_beside_sets() -> AuditContext:
    return make_context(models=[build_sample_model(guid="m1")], dependents={"m1": [
        {"guid": "s1", "type": "SET", "name": "B"},
        {"guid": "a1", "type": "ANSWER", "name": "Q"}]})


def h5_set_listed_by_several_sources() -> AuditContext:
    """R18: one Set under the Model AND each underlying Table's COHORT bucket."""
    row = {"type": "SET", "guid": "s1", "name": "B"}
    return make_context(dependents={"m1": [dict(row)], "t1": [dict(row)],
                                    "t2": [dict(row)], "s1": []})


def h5_sets_in_capture_order() -> AuditContext:
    """test_audit_snapshot.py: three looked-up orphan Sets, in a non-sorted order."""
    deps = {"m1": [{"guid": g, "name": g, "type": "SET"} for g in ("s-z", "s-a", "s-m")]}
    deps.update({"s-z": [], "s-a": [], "s-m": []})
    return make_context(dependents=deps, tables={"zz": {}, "aa": {"b": 1, "a": 2}})


def human_demo_corpus() -> AuditContext:
    """The demo corpus models (ts_cli.audit.test_fixtures) with the corpus' own
    dependents — every Model has Answers and Liveboards."""
    from ts_cli.audit.test_fixtures import generate_test_data
    ctx = demo_corpus_models()
    ctx.dependents = generate_test_data(model_count=8)["corpus"]["dependents"]
    return ctx


# ── edges: boundaries, names, None where lists are expected ─────────────────

def build_named_columns_model(*names, guid="m-1") -> AuditContext:
    """H1: one Model whose columns carry `names` (and nothing else)."""
    return make_context(models=[build_human_model(
        guid=guid, columns=[{"name": n, "properties": {}} for n in names])])


#: H1 name shapes against both regexes: case, a trailing newline (`$` matches before
#: it), Unicode digits and a dotless i (IGNORECASE as `re` applies it), near misses.
H1_NAME_SHAPES = [
    "col1", "COL12", "Col1\n", "col١", "col", "column1", "field_2", "field-3", "FIELD4",
    "fıeld5", "fieldx", "val", "VAL12", "value", "tmp_x", "TMP-y", "tmpx", "9lives",
    "ORDER_ID", "A__", "A_", "Order_Id", "ORDER ID", "ORDERID", "_A_B", "",
]


def human_h1_exactly_ten_percent() -> AuditContext:
    return build_named_columns_model("col1", *[f"Good {i}" for i in range(9)])


def human_h1_just_over_ten_percent() -> AuditContext:
    return build_named_columns_model("col1", "val", *[f"Good {i}" for i in range(17)])


def human_h1_all_anti_patterns() -> AuditContext:
    """Every name an anti-pattern: the detail lists the first five, nothing more."""
    return build_named_columns_model("col1", "col2", "val", "tmp_a", "9b", "FIELD_7",
                                     "ORDER_ID")


def build_description_model(*descriptions) -> AuditContext:
    """H2: one Model, column `C<i>` described by `descriptions[i]` (None: no key)."""
    cols = []
    for i, d in enumerate(descriptions):
        col = {"name": f"C{i}", "properties": {}}
        if d is not None:
            col["description"] = d
        cols.append(col)
    return make_context(models=[build_human_model(columns=cols)])


def human_h2_length_boundaries() -> AuditContext:
    return build_description_model("x" * 19, "x" * 20, "y" * 400, "y" * 401,
                                   "   ", "  " + "z" * 19 + "  ")


def human_h2_boilerplate_shapes() -> AuditContext:
    return build_description_model(
        "  The padded description of the column.  ", "this is a lower-case boilerplate.",
        "Column for the order identifier key.", "FIELD FOR the region of the store.",
        "A plain sentence long enough to pass.", "An order line identifier for joins.",
        "Them apples are counted in this one.", "Thermal reading in degrees Celsius.")


def human_h2_many_issues() -> AuditContext:
    """Four issues: the detail lists the first three; one column has no name."""
    ctx = build_description_model("short", "tiny", "The boilerplate opening is here.",
                                  "small")
    del ctx.models[0]["model"]["columns"][2]["name"]
    return ctx


def human_h3_join_edges() -> AuditContext:
    """H3's sole-join-carrier exemption, tables by NAME (not alias — kept):
    - D::K, hidden, the only D column, D joined: exempt;
    - F::X, hidden, joined F has a visible F::Y: reported;
    - D1::K on DIM aliased D1, which declares its join: D1 is not "joined" by name, so
      reported (the alias bug);
    - DIM_A::K on DIM aliased DIM_A, joined *with* DIM_A: exempt;
    - NOID (no column_id) hidden: key "" — not joined here, reported;
    - LONE::K hidden, LONE has no joins: reported."""
    tables = [{"name": "F", "joins": [{"with": "D"}, {"with": "DIM_A"}]}, {"name": "D"},
              {"name": "DIM", "alias": "D1", "joins": [{"with": "F"}]},
              {"name": "DIM", "alias": "DIM_A"}, {"name": "LONE", "joins": None}]
    cols = [build_human_col("K", is_hidden=True, column_id="D::K"),
            build_human_col("X", is_hidden=True, column_id="F::X"),
            build_human_col("Y", column_id="F::Y"),
            build_human_col("K1", is_hidden=True, column_id="D1::K"),
            build_human_col("KA", is_hidden=True, column_id="DIM_A::K"),
            build_human_col("NOID", is_hidden=True),
            build_human_col("LK", is_hidden=True, column_id="LONE::K")]
    return make_context(models=[build_human_model(columns=cols, model_tables=tables)])


def human_h3_formula_edges() -> AuditContext:
    """A hidden column referenced by display name, one surfacing a formula another
    formula references by NAME (exempt), one whose formula is referenced only by its
    id (reported: the id-ref is not `[name]`), and hidden values that are truthy but
    not `true`."""
    cols = [build_human_col("Amount", is_hidden=True, column_id="T1::Amount"),
            dict(build_human_col("Calc", is_hidden=True), formula_id="f_calc"),
            dict(build_human_col("ById", is_hidden=True), formula_id="formula_ById"),
            {"name": "Str", "column_id": "T1::Str", "properties": {"is_hidden": "yes"}},
            {"name": "Zero", "column_id": "T1::Zero", "properties": {"is_hidden": 0}},
            {"name": "NoProps", "column_id": "T1::NoProps", "properties": None}]
    formulas = [{"id": "f_calc", "name": "Calc", "expr": "[Amount] * 2"},
                {"id": "f_use", "name": "Use", "expr": "[Calc] + [formula_ById]"},
                {"id": "formula_ById", "name": "ById", "expr": "1"}]
    return make_context(models=[build_human_model(columns=cols, formulas=formulas)])


def human_h3_shared_column_object() -> AuditContext:
    """One hidden column dict listed twice as a joined table's only column: `cc is not
    c` skips both copies, so the exemption holds for each."""
    col = build_human_col("K", is_hidden=True, column_id="D::K")
    tables = [{"name": "F", "joins": [{"with": "D"}]}, {"name": "D"}]
    ctx = make_context(models=[build_human_model(model_tables=tables)])
    ctx.models[0]["model"]["columns"] = [col, col]
    return ctx


def human_h4_dependent_shapes() -> AuditContext:
    """Four Models: only Set rows (orphan), a Set and a Liveboard, no `guid` key (keys
    dependents by ""), and one never listed in dependents (orphan)."""
    models = [build_human_model(name="OnlySets", guid="m-sets"),
              build_human_model(name="SetAndBoard", guid="m-board"),
              build_human_model(name="NoGuid", guid="x"),
              build_human_model(name="Unlisted", guid="m-unlisted")]
    del models[2]["guid"]
    return make_context(models=models, dependents={
        "m-sets": [{"guid": "s1", "type": "SET", "name": "S"}],
        "m-board": [{"guid": "s1", "type": "SET", "name": "S"},
                    {"guid": "l1", "type": "LIVEBOARD", "name": "L"}],
        "": [{"guid": "a1", "type": "ANSWER", "name": "Q"}]})


def human_h5_set_shapes() -> AuditContext:
    """Sets with no `guid` / `name` keys, a Set consumed by another Set (the consumer is
    then a Set too, looked up and orphaned), one listed twice, one never looked up."""
    return make_context(dependents={
        "m1": [{"type": "SET"}, {"guid": "s1", "type": "SET", "name": "Parent"},
               {"guid": "s1", "type": "SET", "name": "Parent again"},
               {"guid": "s9", "type": "SET", "name": "Never looked up"},
               {"guid": "a1", "type": "ANSWER", "name": "Q"}],
        "": [],
        "s1": [{"guid": "s2", "type": "SET", "name": "Child"}],
        "s2": []})


def human_h7_reference_shapes() -> AuditContext:
    """Answers on: two Tables at once; one Table twice; a Table known only through a
    model's `model_tables`; a Table known only through `ctx.tables`; a blank fqn; and a
    model table whose own fqn is blank (it names nothing)."""
    model = {"guid": "mdl-1", "model": {"name": "Sales", "model_tables": [
        {"name": "ORDERS", "fqn": "tbl-orders"}, {"name": "BLANK", "fqn": ""}]}}
    answers = [
        {"guid": "a-1", "answer": {"name": "Two", "tables": [{"fqn": "tbl-orders"},
                                                             {"fqn": "tbl-only-ctx"}]}},
        {"guid": "a-2", "answer": {"name": "Twice", "tables": [{"fqn": "tbl-orders"},
                                                               {"fqn": "tbl-orders"}]}},
        {"guid": "a-3", "answer": {"name": "Blank", "tables": [{"fqn": ""}, {}]}},
        {"answer": {"tables": [{"fqn": "tbl-only-ctx"}]}},
        {"guid": "a-5", "answer": {"name": "Model", "tables": [{"fqn": "mdl-1"}]}}]
    return make_context(models=[model], answers=answers,
                        tables={"tbl-only-ctx": {"table": {"name": "LINES"}}})


def build_formula_answers(model_formulas, *answer_formulas) -> AuditContext:
    """H8/H9: Model `M` with `model_formulas`; Answer `Q<i>` holding
    `answer_formulas[i]` (each a list of (name, expr) pairs; expr None: no key)."""
    def formulas(pairs):
        return [{"name": n, **({} if e is None else {"expr": e})} for n, e in pairs]
    answers = [{"guid": f"a-{i}", "answer": {"name": f"Q{i}", "formulas": formulas(fs)}}
               for i, fs in enumerate(answer_formulas)]
    return make_context(models=[build_human_model(name="M", formulas=formulas(model_formulas))],
                        answers=answers)


def human_h8_group_shapes() -> AuditContext:
    """One formula twice in one Answer (a group of two), one in four Answers (three
    listed), case and whitespace variants of one expression, blank and absent exprs
    (never grouped), and one already on the Model (H9's, not H8's)."""
    return build_formula_answers(
        [("On Model", "sum([On])")],
        [("A", "sum([X])"), ("A again", "sum([X])"), ("B", "SUM( [Y] )"),
         ("Blank", "  "), ("Absent", None), ("Twin", "sum([On])")],
        [("B2", "sum(\t[y])"), ("Four", "avg([Z])"), ("Blank", "")],
        [("Four", "avg([Z])"), ("Twin", "SUM([ON])")],
        [("Four", "  AVG([Z]) "), ("Absent", None)],
        [("Four", "avg([z])")])


def human_h9_match_shapes() -> AuditContext:
    """An absent Answer expr matches an absent Model expr (H9 has no blank guard); two
    Models share an expression under different names (the later name wins), matched by
    an Answer formula with no `name` key; whitespace inside an expression is collapsed,
    never removed (`COUNT( [K] )` is not `count([k])`)."""
    ctx = build_formula_answers(
        [("Empty", None), ("First", "count([K])")],
        [("NoExpr", None), ("Count", "COUNT( [K] )")],
        [("Again", "count([k])")])
    ctx.models.append(build_human_model(name="M2", guid="m-2", formulas=[
        {"name": "Second", "expr": "count([K])"}]))
    del ctx.answers[1]["answer"]["formulas"][0]["name"]
    return ctx


def human_h10_name_shapes() -> AuditContext:
    """Stale-pattern shapes on Model names, column names and descriptions: the safe
    list overrides, word boundaries, suffixes, a long description cut at 60, a column
    stale by name AND description."""
    long_desc = "Deprecated: this column will be removed once the new ledger is live. " * 2
    cols = [{"name": n, "properties": {}} for n in (
        "DO NOT USE Amount", "do_not_use", "Contest", "Test 2", "test_results count",
        "test_results_old", "TEST_COVERAGE backup",
        "Sales copy", "Sales copy2", "Region (2)", "copy of region", "zDEL flag",
        "TO_DELETE", "backup", "bak", "Archive", "Sales_old", "old-sales", "Holder",
        "Temp_x", "tmp_y", "Template", "OBSOLETE", "REMOVE ME", "Removed")]
    cols += [{"name": "Plain", "description": long_desc, "properties": {}},
             {"name": "tmp_both", "description": "Temporary staging copy", "properties": {}},
             {"name": "Fine", "description": "For testing only", "properties": {}},
             {"name": "Quiet", "description": None, "properties": {}},
             {"name": "Empty", "description": "", "properties": {}},
             {"description": "clone of Amount", "properties": {}}]
    models = [build_human_model(name=n, guid=f"m-{i}", columns=cols if i == 0 else [])
              for i, n in enumerate(("Sales (Backup)", "Copy of Sales", "Test Results",
                                     "test_automation suite", "test_suite tmp_1", "Sales",
                                     "Sales v2 old"))]
    return make_context(models=models)


def human_names_none() -> AuditContext:
    """`name` / `guid` present and None wherever no legacy H check would raise on it
    (a None column or Model name meets a regex there): a Model guid, a Set's guid and
    name, an Answer's guid and name, and formula names."""
    model = build_human_model(name="M", guid="g", formulas=[{"name": None, "expr": "1 + 1"}])
    model["guid"] = None
    answer = {"guid": None, "answer": {"name": None, "tables": [{"fqn": "tbl"}],
                                       "formulas": [{"name": None, "expr": "1 + 1"}]}}
    return make_context(models=[model], answers=[answer],
                        tables={"tbl": {"table": {"name": "T"}}},
                        dependents={"m": [{"guid": None, "name": None, "type": "SET"}],
                                    None: []})


def human_names_absent() -> AuditContext:
    """No `name` / `guid` keys anywhere the H checks read them."""
    model = {"model": {"model_tables": [{"joins": [{}]}], "columns": [
        {"properties": {"is_hidden": True}, "description": "short"}],
        "formulas": [{"expr": "x"}]}}
    answers = [{"answer": {"tables": [{"fqn": "t"}], "formulas": [{"expr": "x"}]}},
               {"answer": {"formulas": [{"expr": "y"}]}},
               {"answer": {"formulas": [{"expr": "y"}]}}]
    return make_context(models=[model], answers=answers, tables={"t": {}},
                        dependents={"": [{"type": "SET"}]})


def human_lists_none() -> AuditContext:
    """`columns`, `formulas`, `model_tables`, `joins`, `tables`, `properties` None or
    empty; a document with no `model` / `answer` key."""
    return make_context(
        models=[{"guid": "g-1", "model": {"name": "Nones", "model_tables": None,
                                          "columns": None, "formulas": None,
                                          "properties": None}},
                {"guid": "g-2", "model": {"name": "Empty", "model_tables": [
                    {"name": "A", "joins": None}, {"name": "B", "joins": []}],
                    "columns": [{"name": "c", "properties": None}], "formulas": []}},
                {"guid": "g-3"}, {"guid": "g-4", "model": {}}],
        answers=[{"guid": "a-1", "answer": {"name": "N", "tables": None, "formulas": None}},
                 {"guid": "a-2"}],
        dependents={"g-1": []})


# Every H input, for the equivalence test — listed by hand (see AI_INPUTS).
H_INPUTS = {fn.__name__: fn for fn in (
    human_generic_names, human_good_names, human_hidden_unreferenced,
    human_hidden_referenced, human_model_no_dependents, human_model_with_dependents,
    human_stale_column, human_clean_names,
    human_description_short, human_description_long, human_description_boilerplate,
    human_description_two_short, human_description_clean, human_set_without_consumers,
    human_set_with_consumer, human_dependents_not_sets, human_rich_context,
    human_no_answers, human_answer_source_without_fqn, human_formula_in_two_answers,
    human_formula_in_two_answers_same_text, human_formula_in_one_answer,
    human_formula_on_model_and_two_answers,
    human_model_formula_without_answers, human_formula_in_two_answers_model_without_formulas,
    human_answer_formula_duplicates_model, human_answer_formula_new,
    guard_set_never_looked_up, guard_set_looked_up_no_consumers,
    guard_set_looked_up_with_consumers, answer_on_table, answer_on_model,
    answer_on_unknown_object, answer_without_table_refs,
    built_set_without_consumers, built_set_with_consumer, built_set_lookup_failed,
    built_set_consumed_only_by_a_set, built_set_lookup_empty_response,
    built_set_hidden_dependents_none, built_set_hidden_dependents_one,
    built_set_discovery_incomplete, built_no_sets, h4_model_with_answer_beside_sets,
    h5_set_listed_by_several_sources, h5_sets_in_capture_order, human_demo_corpus,
    human_h1_exactly_ten_percent, human_h1_just_over_ten_percent,
    human_h1_all_anti_patterns, human_h2_length_boundaries, human_h2_boilerplate_shapes,
    human_h2_many_issues, human_h3_join_edges, human_h3_formula_edges,
    human_h3_shared_column_object, human_h4_dependent_shapes, human_h5_set_shapes,
    human_h7_reference_shapes, human_h8_group_shapes, human_h9_match_shapes,
    human_h10_name_shapes, human_names_none, human_names_absent, human_lists_none,
    # the generic engine inputs and the all-category registry contexts (common.py)
    registry_empty_context, registry_populated_context,
)}
H_INPUTS.update({f"h1_name_{i}": (lambda n=n: build_named_columns_model(n))
                 for i, n in enumerate(H1_NAME_SHAPES)})
H_INPUTS.update({f"h1_all_shapes_{k}": (lambda k=k: build_named_columns_model(
                 *H1_NAME_SHAPES[:k])) for k in (5, 10, 15, len(H1_NAME_SHAPES))})
H_INPUTS.update({f"h2_length_{n}": (lambda n=n: build_description_model("d" * n))
                 for n in (1, 19, 20, 21, 399, 400, 401)})
