"""Named fixture builders for audit catalog rules.

Each public function not named `build_*` takes no arguments and returns an
`AuditContext` (`build_*` helpers take arguments and build families of inputs). A rule's
`examples.fires.fixture` / `examples.silent.fixture` names one of them, and the engine
tests (`test_audit_engine.py`) build their inputs from them too. Everything here is
synthetic: invented names and guids, never exported TML from a real cluster.

Add a builder per shape a rule needs rather than parameterising an existing one — the
catalog refers to fixtures by name, so a name must keep meaning one input.
"""
from __future__ import annotations

import copy

from ts_cli.audit.context import AuditContext, make_context

MODEL_GUID = "00000000-0000-4000-8000-000000000001"


def _column(name: str, column_type: str = "ATTRIBUTE", **props) -> dict:
    return {"name": name, "column_id": f"FACT::{name}",
            "properties": {"column_type": column_type, **props}}


def _model(name: str, guid: str, columns: list, model_tables: list | None = None,
           **extra) -> dict:
    return {"guid": guid, "model": {"name": name, "columns": columns,
                                    "model_tables": model_tables or [], **extra}}


def _measures(total: int, with_context: int) -> list:
    """`total` visible measures M0..M<total-1>; the first `with_context` carry ai_context."""
    return [_column(f"M{i}", "MEASURE",
                    **({"ai_context": "additivity: additive"} if i < with_context else {}))
            for i in range(total)]


def _noise_columns() -> list:
    """Columns a measure-coverage rule must ignore: a hidden measure, an attribute."""
    return [_column("HIDDEN_M", "MEASURE", is_hidden=True), _column("REGION")]


# ── measure AI context (ratio mode) ─────────────────────────────────────────

def model_measures_with_ai_context() -> AuditContext:
    """8 of 10 visible measures carry ai_context (80%)."""
    return make_context(models=[_model("Sales", MODEL_GUID,
                                       _measures(10, 8) + _noise_columns())])


def model_measures_no_ai_context() -> AuditContext:
    """3 of 10 visible measures carry ai_context (30%); M3..M9 are missing it."""
    return make_context(models=[_model("Sales", MODEL_GUID,
                                       _measures(10, 3) + _noise_columns())])


def model_without_measures() -> AuditContext:
    """A model whose only measure is hidden: the population is empty."""
    return make_context(models=[_model("Lookup", MODEL_GUID, _noise_columns())])


# ── column sprawl (count mode) ──────────────────────────────────────────────

def model_76_columns() -> AuditContext:
    return make_context(models=[_model("Wide", MODEL_GUID,
                                       [_column(f"C{i}") for i in range(76)])])


def model_75_columns() -> AuditContext:
    return make_context(models=[_model("Wide", MODEL_GUID,
                                       [_column(f"C{i}") for i in range(75)])])


# ── per-column (each mode) ──────────────────────────────────────────────────

def model_id_columns() -> AuditContext:
    """Two indexed ID-like attributes, one DONT_INDEX ID, one plain attribute."""
    cols = [_column("customer_id"), _column("order_id"),
            _column("row_id", index_type="DONT_INDEX"), _column("Region")]
    return make_context(models=[_model("Orders", MODEL_GUID, cols)])


# ── model tables keyed by alias ─────────────────────────────────────────────

def model_role_playing_dimension() -> AuditContext:
    """DIM_DATE joined twice, as ORDER_DATE and SHIP_DATE; FACT has no alias."""
    tables = [
        {"name": "FACT", "fqn": "t-fact",
         "joins": [{"with": "ORDER_DATE", "on": "[FACT::OD] = [ORDER_DATE::D]"}]},
        {"name": "DIM_DATE", "alias": "ORDER_DATE", "fqn": "t-date"},
        {"name": "DIM_DATE", "alias": "SHIP_DATE", "fqn": "t-date"},
    ]
    return make_context(models=[_model("Orders", MODEL_GUID, [], tables)])


# ── AI instructions (data availability) ─────────────────────────────────────

def models_with_and_without_ai_instructions() -> AuditContext:
    """Two models without coaching; only the first has an ai_instructions entry."""
    looked_up = _model("Looked Up", "guid-looked-up", [_column("A")])
    not_fetched = _model("Not Fetched", "guid-not-fetched", [_column("A")])
    return make_context(models=[looked_up, not_fetched],
                        ai_instructions={"guid-looked-up": {"nl_instructions_info": []}})


# ── duplicates and divergence (group mode) ──────────────────────────────────

def _header(guid: str, name: str, source: str = "SF", kind: str = "ONE_TO_ONE_LOGICAL") -> dict:
    return {"metadata_header": {"id": guid, "name": name, "type": kind,
                                "dataSourceName": source}}


def metadata_duplicate_tables() -> AuditContext:
    """ORDERS on SF registered three times; CUSTOMERS once; ORDERS on PG once."""
    return make_context(metadata=[
        _header("t1", "ORDERS"), _header("t2", "CUSTOMERS"), _header("t3", "ORDERS"),
        _header("t4", "ORDERS", source="PG"), _header("t5", "ORDERS"),
    ])


def models_divergent_column_types() -> AuditContext:
    """REGION is an ATTRIBUTE in one model and a MEASURE in another; AMOUNT agrees."""
    m1 = _model("North", "g-north", [_column("REGION"), _column("AMOUNT", "MEASURE")])
    m2 = _model("South", "g-south", [_column("REGION", "MEASURE"), _column("AMOUNT", "MEASURE")])
    return make_context(models=[m1, m2])


# ── overlap (pairwise mode) ─────────────────────────────────────────────────

def _tables(*fqns: str) -> list:
    return [{"name": f.upper(), "fqn": f} for f in fqns]


def models_overlapping_tables() -> AuditContext:
    """A/B share 3 of 4 tables (0.75); A/C share 1 of 5 (0.2); B/D share nothing."""
    return make_context(models=[
        _model("A", "g-a", [], _tables("t1", "t2", "t3")),
        _model("B", "g-b", [], _tables("t1", "t2", "t3", "t4")),
        _model("C", "g-c", [], _tables("t1", "t8", "t9")),
        _model("D", "g-d", [], _tables("t7")),
    ])


# ── weighted score (composite mode) ─────────────────────────────────────────

def models_for_readiness_score() -> AuditContext:
    """Component values live on the model's `properties` so the test needs no derived field."""
    def scored(name: str, guid: str, coverage: float, coached: bool) -> dict:
        return _model(name, guid, [], properties={"coverage": coverage, "coached": coached})
    return make_context(models=[scored("Ready", "g-ready", 90.0, True),
                                scored("Partial", "g-partial", 50.0, True),
                                scored("Bare", "g-bare", 20.0, False)])


# ── A: AI readiness ─────────────────────────────────────────────────────────
# The inputs tests/test_checks_ai.py and tests/test_checks_ai_instructions_shape.py
# exercise the legacy A-checks with, named here so the A rules' examples and the
# equivalence test (tests/test_audit_equivalence.py) run over the very same contexts.
# `build_*` functions take arguments: they build families of inputs and are never
# named by a rule's example.

COACHED = {"nl_instructions_info": [
    {"instructions": ["Always filter by [Region] before aggregating"], "scope": "GLOBAL"}]}
AI_CONTEXT = "additivity: additive\ntime_basis: DM_DATE.Date\ngrain_keys: [T.ID]"


def build_ai_model(name="Sales", guid="m-1", columns=None, description="",
                   properties=None, **model) -> dict:
    """A model document as test_checks_ai.py has always built it."""
    return {"guid": guid, "model": {
        "name": name, "description": description, "model_tables": [{"name": "T1"}],
        "columns": columns or [], "formulas": [], "properties": properties or {}, **model}}


def build_ai_col(name="Amount", description="", synonyms=None) -> dict:
    """A column with `synonyms` at the root (hand-built; exported TML never does this)."""
    return {"name": name, "description": description, "synonyms": synonyms or []}


def build_tml_col(name, ctype="ATTRIBUTE", ai_context=None, synonyms=None, hidden=False,
                  desc=None) -> dict:
    """A column as exported Model TML writes it: synonyms/ai_context under properties."""
    props = {"column_type": ctype}
    if ai_context is not None:
        props["ai_context"] = ai_context
    if synonyms is not None:
        props["synonyms"] = synonyms
    if hidden:
        props["is_hidden"] = True
    col = {"name": name, "column_id": f"T::{name}", "properties": props}
    if desc:
        col["description"] = desc
    return col


def build_tml_ctx(*cols, name="M", assessment="spotter") -> AuditContext:
    return AuditContext(models=[{"guid": "g-1", "model": {"name": name, "columns": list(cols)}}],
                        assessment=assessment)


def build_described_columns(n_described: int, n: int = 100) -> AuditContext:
    """`n` root-style columns, the first `n_described` described (A1 bars)."""
    return make_context(models=[build_ai_model(columns=[
        build_ai_col(f"C{i}", description="d" if i < n_described else "")
        for i in range(n)])])


def build_synonym_columns(n_syn: int, n: int = 100) -> AuditContext:
    """`n` root-style columns, the first `n_syn` with synonyms (A2 bars)."""
    return make_context(models=[build_ai_model(columns=[
        build_ai_col(f"C{i}", synonyms=["s"] if i < n_syn else []) for i in range(n)])])


def build_tml_measures(covered: int, total: int = 10) -> AuditContext:
    """`total` visible measures, the first `covered` with ai_context (A6 bars)."""
    return build_tml_ctx(*[build_tml_col(f"M{i}", "MEASURE", AI_CONTEXT if i < covered else None)
                           for i in range(total)])


def ai_model_one_of_three_described() -> AuditContext:
    """1 of 3 columns described (33%): HIGH under spotter, MEDIUM under general."""
    return make_context(models=[build_ai_model(columns=[
        build_ai_col("A"), build_ai_col("B"), build_ai_col("C", description="has desc")])])


def ai_model_all_described() -> AuditContext:
    return make_context(models=[build_ai_model(columns=[
        build_ai_col("A", description="good"), build_ai_col("B", description="good")])])


def ai_model_without_columns() -> AuditContext:
    return make_context(models=[build_ai_model(columns=[])])


def ai_model_one_of_three_with_synonyms() -> AuditContext:
    """1 of 3 columns with synonyms (33%): HIGH under spotter, no finding under general."""
    return make_context(models=[build_ai_model(columns=[
        build_ai_col("A"), build_ai_col("B"), build_ai_col("C", synonyms=["revenue"])])])


def ai_model_all_with_synonyms() -> AuditContext:
    return make_context(models=[build_ai_model(columns=[
        build_ai_col("A", synonyms=["a"]), build_ai_col("B", synonyms=["b"])])])


def ai_model_uncoached() -> AuditContext:
    """Instructions looked up and empty; no description either."""
    return make_context(models=[build_ai_model(guid="m-1")], ai_instructions={"m-1": {}})


def ai_model_coached() -> AuditContext:
    return make_context(models=[build_ai_model(guid="m-1")], ai_instructions={"m-1": {
        "nl_instructions_info": [{"instructions": ["Some coaching text"], "scope": "GLOBAL"}]}})


def ai_model_instructions_not_fetched() -> AuditContext:
    """The instructions fetch failed: the model's guid is absent from ai_instructions."""
    return make_context(models=[build_ai_model(guid="m-1")], ai_instructions={})


def ai_model_without_description() -> AuditContext:
    return make_context(models=[build_ai_model(description="")])


def ai_model_described() -> AuditContext:
    return make_context(models=[build_ai_model(description="Sales data model")])


def ai_model_bare_columns() -> AuditContext:
    """Two undescribed, synonym-less columns, no description, no coaching: score 15."""
    return make_context(models=[build_ai_model(columns=[build_ai_col("A"), build_ai_col("B")],
                                               description="")])


def ai_model_ready() -> AuditContext:
    """Every readiness component at 100: score 100."""
    return make_context(
        models=[build_ai_model(columns=[
            build_ai_col("Amount", description="Total sale amount",
                         synonyms=["revenue", "sales"]),
            build_ai_col("Date", description="Transaction date", synonyms=["order date"]),
        ], description="Sales model")],
        ai_instructions={"m-1": {"nl_instructions_info": [
            {"instructions": ["coaching"], "scope": "GLOBAL"}]}})


def tml_measures_full_ai_context() -> AuditContext:
    return build_tml_ctx(build_tml_col("Revenue", "MEASURE", AI_CONTEXT),
                         build_tml_col("Qty", "MEASURE", AI_CONTEXT))


def tml_measures_no_ai_context() -> AuditContext:
    return build_tml_ctx(build_tml_col("Revenue", "MEASURE"), build_tml_col("Qty", "MEASURE"))


def tml_measures_partial_ai_context() -> AuditContext:
    """3 of 5 measures covered (60%)."""
    return build_tml_measures(3, 5)


def tml_measure_and_ten_ids() -> AuditContext:
    return build_tml_ctx(build_tml_col("Revenue", "MEASURE", AI_CONTEXT),
                         *[build_tml_col(f"ID{i}") for i in range(10)])


def tml_hidden_measure_uncovered() -> AuditContext:
    return build_tml_ctx(build_tml_col("Revenue", "MEASURE", AI_CONTEXT),
                         build_tml_col("Raw", "MEASURE", hidden=True))


def tml_measure_blank_ai_context() -> AuditContext:
    return build_tml_ctx(build_tml_col("Revenue", "MEASURE", "   "))


def tml_attribute_only() -> AuditContext:
    return build_tml_ctx(build_tml_col("Region"))


def tml_eight_measures_uncovered() -> AuditContext:
    """8 uncovered measures: the missing list shows 5, then "(+3 more)"."""
    return build_tml_measures(0, 8)


def tml_four_columns_with_synonyms() -> AuditContext:
    return build_tml_ctx(*[build_tml_col(f"C{i}", synonyms=["x"]) for i in range(4)])


def tml_four_columns_without_synonyms() -> AuditContext:
    return build_tml_ctx(*[build_tml_col(f"C{i}") for i in range(4)])


def tml_root_synonyms_column() -> AuditContext:
    return build_tml_ctx({"name": "C", "synonyms": ["x"],
                          "properties": {"column_type": "ATTRIBUTE"}})


def tml_described_column_with_synonyms() -> AuditContext:
    return build_tml_ctx(build_tml_col("C", synonyms=["x"], desc="d"))


def tml_described_column() -> AuditContext:
    return build_tml_ctx(build_tml_col("C", desc="d"))


def tml_value_shapes() -> AuditContext:
    """Value shapes the legacy text tests (`str(x or "").strip()`, `.upper()`) treat
    specially: a lower-case column_type, falsy non-string ai_context/description
    values (blank), structured ai_context (covered), non-mapping properties."""
    def col(name, props, **extra):
        return {"name": name, "column_id": f"T::{name}", "properties": props, **extra}
    return build_tml_ctx(
        col("lower", {"column_type": "measure", "ai_context": AI_CONTEXT}),
        col("Mixed", {"column_type": "Measure"}, description=0),
        col("false_ctx", {"column_type": "MEASURE", "ai_context": False}, description=False),
        col("zero_ctx", {"column_type": "MEASURE", "ai_context": 0}),
        col("empty_map", {"column_type": "MEASURE", "ai_context": {}}),
        col("structured", {"column_type": "MEASURE", "ai_context": {"additivity": "additive"}},
            description="d"),
        col("list_props", ["MEASURE"]),
        col("empty_props", []),
    )


def _instructions_model(**model) -> dict:
    base = {"name": "Sales", "columns": [
        {"name": "Amount", "column_id": "T::AMOUNT", "properties": {"column_type": "MEASURE"}}]}
    base.update(model)
    return {"guid": "m-1", "model": base}


def instructions_live_shape() -> AuditContext:
    """The live ai/instructions/get response shape, with one instruction (BL-292)."""
    return make_context(models=[_instructions_model()], ai_instructions={"m-1": COACHED})


def instructions_empty_info() -> AuditContext:
    return make_context(models=[_instructions_model()],
                        ai_instructions={"m-1": {"nl_instructions_info": []}})


def instructions_info_without_text() -> AuditContext:
    return make_context(models=[_instructions_model()], ai_instructions={
        "m-1": {"nl_instructions_info": [{"instructions": [], "scope": "GLOBAL"}]}})


def instructions_tml_only() -> AuditContext:
    """Coached through the TML `model_instructions` only; the API has none."""
    return make_context(
        models=[_instructions_model(model_instructions={"data_model_instructions":
                                                        "Use last 30 days"})],
        ai_instructions={"m-1": {"nl_instructions_info": []}})


def demo_corpus_models() -> AuditContext:
    """The models of ts_cli.audit.test_fixtures' demo corpus as model documents (name,
    description, tables; it carries no columns), every one looked up with no coaching."""
    from ts_cli.audit.test_fixtures import generate_test_data
    corpus = generate_test_data(model_count=8)["corpus"]["models"]
    docs = [{"guid": m["guid"], "model": {"name": m["name"], "description": m["description"],
                                          "model_tables": m["model_tables"]}}
            for m in corpus]
    return make_context(models=docs, ai_instructions={d["guid"]: {} for d in docs})


def tml_unnamed_measure() -> AuditContext:
    """A visible, uncovered measure with no `name` key: legacy A6 lists it as "?"."""
    return build_tml_ctx(build_tml_col("Revenue", "MEASURE", AI_CONTEXT),
                         {"column_id": "T::X", "properties": {"column_type": "MEASURE"}})


def ai_model_name_none() -> AuditContext:
    """A model whose `name` is present and None: findings carry object_name None."""
    return make_context(models=[build_ai_model(name=None, columns=[build_ai_col("A")])],
                        ai_instructions={"m-1": {}})


def ai_document_guid_none() -> AuditContext:
    """A model document whose `guid` is present and None: findings carry object_guid
    None, and its instructions entry is keyed None."""
    return make_context(models=[build_ai_model(guid=None, columns=[build_ai_col("A")])],
                        ai_instructions={None: {}})


# Every A input, for the equivalence test — listed by hand so another category's
# fixtures cannot join and a renamed one cannot drop out silently; the profile-bar
# families are swept across every value their legacy tests probe (and the boundaries).
AI_INPUTS = {fn.__name__: fn for fn in (
    ai_model_one_of_three_described, ai_model_all_described, ai_model_without_columns,
    ai_model_one_of_three_with_synonyms, ai_model_all_with_synonyms, ai_model_uncoached,
    ai_model_coached, ai_model_instructions_not_fetched, ai_model_without_description,
    ai_model_described, ai_model_bare_columns, ai_model_ready, ai_model_name_none,
    ai_document_guid_none,
    tml_measures_full_ai_context, tml_measures_no_ai_context,
    tml_measures_partial_ai_context, tml_measure_and_ten_ids, tml_hidden_measure_uncovered,
    tml_measure_blank_ai_context, tml_attribute_only, tml_eight_measures_uncovered,
    tml_four_columns_with_synonyms, tml_four_columns_without_synonyms,
    tml_root_synonyms_column, tml_described_column_with_synonyms, tml_described_column,
    tml_value_shapes, tml_unnamed_measure,
    instructions_live_shape, instructions_empty_info, instructions_info_without_text,
    instructions_tml_only,
    demo_corpus_models, models_with_and_without_ai_instructions,
    model_measures_with_ai_context, model_measures_no_ai_context, model_without_measures,
)}
AI_INPUTS.update({f"described_{n}_of_100": (lambda n=n: build_described_columns(n))
                  for n in range(101)})
AI_INPUTS.update({f"synonyms_{n}_of_100": (lambda n=n: build_synonym_columns(n))
                  for n in range(101)})
AI_INPUTS.update({f"measures_{c}_of_{t}": (lambda c=c, t=t: build_tml_measures(c, t))
                  for t in (1, 5, 10) for c in range(t + 1)})


# ── P: Performance ──────────────────────────────────────────────────────────
# The inputs the legacy P-check tests exercise checks_perf.py with: test_checks_perf.py,
# test_checks_perf_trip.py, and the P halves of test_checks_varchar_join_keys.py,
# test_referencing_joins.py, test_dead_guards.py, test_index_type_sense.py,
# test_unreachable_checks.py, test_checks_registry.py and test_checks_security_trip.py.
# Those tests build their contexts here, so the P rules' examples and the equivalence
# test (tests/test_audit_equivalence.py) run over the very same inputs.

# test_checks_perf.py's shapes

def build_perf_model(name="Sales", guid="m-1", columns=None, formulas=None,
                     model_tables=None, properties=None, filters=None,
                     constraints=None) -> dict:
    """A model document as test_checks_perf.py has always built it."""
    columns, formulas, model_tables, properties, filters, constraints = copy.deepcopy(
        (columns, formulas, model_tables, properties, filters, constraints))
    return {"guid": guid, "model": {
        "name": name, "model_tables": model_tables or [{"name": "T1"}],
        "columns": columns or [], "formulas": formulas or [],
        "properties": properties or {}, "filters": filters or [],
        "constraints": constraints or []}}


def build_perf_col(name="Amount", column_type="MEASURE", aggregation=None, index_type=None,
                   column_id=None, data_type="INT64") -> dict:
    col = {"name": name, "column_id": column_id or f"T1::{name}",
           "properties": {"column_type": column_type},
           "db_column_properties": {"data_type": data_type}}
    if aggregation:
        col["properties"]["aggregation"] = aggregation
    if index_type:
        col["properties"]["index_type"] = index_type
    return col


def build_perf_table(name="ORDERS", guid="t-1", rls_rules=None) -> dict:
    table = {"guid": guid, "table": {"name": name, "columns": []}}
    if rls_rules:
        table["table"]["rls_rules"] = rls_rules
    return table


def perf_metadata_sql_view() -> AuditContext:
    """One SQL_VIEW (P1 fires on it) beside one logical table."""
    return make_context(metadata=[
        {"metadata_header": {"type": "SQL_VIEW", "name": "V1", "id": "v-1"}},
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": "T1", "id": "t-1"}},
    ])


def perf_metadata_logical_only() -> AuditContext:
    return make_context(metadata=[
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": "T1", "id": "t-1"}}])


def perf_model_wide_not_progressive() -> AuditContext:
    """Six tables with join_progressive false (P4 fires)."""
    return make_context(models=[build_perf_model(
        model_tables=[{"name": f"T{i}"} for i in range(6)],
        properties={"join_progressive": False})])


def perf_model_wide_progressive() -> AuditContext:
    """Six tables with join_progressive true (P4 silent)."""
    return make_context(models=[build_perf_model(
        model_tables=[{"name": f"T{i}"} for i in range(6)],
        properties={"join_progressive": True})])


def perf_model_80_columns() -> AuditContext:
    return make_context(models=[build_perf_model(
        columns=[build_perf_col(f"C{i}") for i in range(80)])])


def perf_model_50_columns() -> AuditContext:
    return make_context(models=[build_perf_model(
        columns=[build_perf_col(f"C{i}") for i in range(50)])])


def perf_table_seven_rls_rules() -> AuditContext:
    rls = {"rules": [{"expr": f"[col{i}]"} for i in range(7)]}
    return make_context(tables={"db.s.T1": build_perf_table(rls_rules=rls)})


def perf_formula_six_nested_ifs() -> AuditContext:
    expr = "if(if(if(if(if(if([x]>0,1,0)>0,1,0)>0,1,0)>0,1,0)>0,1,0)>0,1,0)"
    return make_context(models=[build_perf_model(formulas=[{"name": "F1", "expr": expr}])])


def perf_column_count_distinct() -> AuditContext:
    return make_context(models=[build_perf_model(
        columns=[build_perf_col("Users", aggregation="COUNT_DISTINCT")])])


# test_checks_perf_trip.py's shapes (from the model and table TML schemas)

def build_trip_model(**model_body) -> dict:
    """A model TML document: `guid` at the root, everything else under `model:`.
    The body is deep-copied, so shared constants are never mutated through it (one
    deepcopy: an object listed twice stays one object)."""
    body = {"name": "Sales"}
    body.update(copy.deepcopy(model_body))
    return {"guid": "m-1", "model": body}


def build_trip_ctx(*models) -> AuditContext:
    return make_context(models=list(models))


def build_trip_measure(table, col) -> dict:
    return {"name": col.replace("_", " ").title(), "column_id": f"{table}::{col}",
            "properties": {"column_type": "MEASURE", "aggregation": "SUM"}}


def build_trip_attribute(table, col, **props) -> dict:
    return {"name": col, "column_id": f"{table}::{col}",
            "properties": {"column_type": "ATTRIBUTE", **props}}


def build_trip_join(with_table) -> dict:
    """An inline join — `type` and `cardinality` are required together."""
    return {"with": with_table, "on": f"[A::{with_table}_KEY] = [{with_table}::KEY]",
            "type": "INNER", "cardinality": "MANY_TO_ONE"}


TRIP_TABLE_FQN = "DUNDERMIFFLIN.PUBLIC.BANK_EMPLOYEES"


def build_trip_table(columns, rules=None) -> dict:
    columns, rules = copy.deepcopy((columns, rules))
    t = {"name": "BANK_EMPLOYEES", "db": "DUNDERMIFFLIN", "schema": "PUBLIC",
         "db_table": "BANK_EMPLOYEES", "columns": columns}
    if rules is not None:
        t["rls_rules"] = {
            "tables": [{"name": "BANK_EMPLOYEES"}],
            "table_paths": [{"id": "BANK_EMPLOYEES_1", "table": "BANK_EMPLOYEES",
                             "column": ["COUNTRY"]}],
            "rules": rules,
        }
    return {"guid": "t-1", "table": t}


def build_trip_table_ctx(columns, rules) -> AuditContext:
    return make_context(tables={TRIP_TABLE_FQN: build_trip_table(columns, rules)})


def build_trip_varchar(name, **props) -> dict:
    return {"name": name, "db_column_name": name,
            "properties": {"column_type": "ATTRIBUTE", **props},
            "db_column_properties": {"data_type": "VARCHAR"}}


# P2 — scalar formula density

def build_formula_model(n: int, aggregated: bool) -> dict:
    """`n` row-level formulas, each surfaced by a column that does (or does not)
    declare an aggregation."""
    return build_trip_model(
        formulas=[{"id": f"formula_Margin {i}", "name": f"Margin {i}",
                   "expr": "[ORDERS::AMOUNT] - [ORDERS::COST]"} for i in range(n)],
        columns=[{"name": f"Margin {i}", "formula_id": f"formula_Margin {i}",
                  "properties": {"column_type": "MEASURE",
                                 **({"aggregation": "SUM"} if aggregated else {})}}
                 for i in range(n)],
    )


def perf_six_scalar_formulas() -> AuditContext:
    """Six unaggregated formulas: P2 MEDIUM."""
    return build_trip_ctx(build_formula_model(6, aggregated=False))


def perf_eleven_scalar_formulas() -> AuditContext:
    """Eleven unaggregated formulas: P2 HIGH."""
    return build_trip_ctx(build_formula_model(11, aggregated=False))


def perf_six_aggregated_formulas() -> AuditContext:
    return build_trip_ctx(build_formula_model(6, aggregated=True))


def perf_five_scalar_formulas() -> AuditContext:
    return build_trip_ctx(build_formula_model(5, aggregated=False))


def perf_aggregate_expr_formulas() -> AuditContext:
    """Six `sum ( ... )` formulas whose columns declare no aggregation (counted as
    scalar: the legacy defect test_checks_perf_trip.py pins)."""
    return build_trip_ctx(build_trip_model(
        formulas=[{"id": f"formula_Rev {i}", "name": f"Rev {i}",
                   "expr": "sum ( [ORDERS::AMOUNT] )"} for i in range(6)],
        columns=[{"name": f"Rev {i}", "formula_id": f"formula_Rev {i}",
                  "properties": {"column_type": "MEASURE"}} for i in range(6)],
    ))


# P3 — model filters with no apply_on_tables

TRIP_MANDATORY_FILTER = {"column": ["Region"], "oper": "in", "values": ["APAC"]}
TRIP_SCOPED_FILTER = {"column": ["Quantity"], "oper": ">", "values": ["100"],
                      "apply_on_tables": ["Lineorder", "Supplier"]}


def perf_filters_one_mandatory() -> AuditContext:
    return build_trip_ctx(build_trip_model(filters=[TRIP_MANDATORY_FILTER,
                                                    TRIP_SCOPED_FILTER]))


def perf_filters_all_scoped() -> AuditContext:
    return build_trip_ctx(build_trip_model(filters=[TRIP_SCOPED_FILTER]))


def perf_model_without_filters() -> AuditContext:
    return build_trip_ctx(build_trip_model())


# P5 — no date constraints on a model with fact tables

TRIP_FACT_COLUMNS = [build_trip_measure("ORDERS", c)
                     for c in ("AMOUNT", "COST", "QUANTITY", "DISCOUNT")]
# The shape a live export produces: a mapping whose single key is `constraint`.
TRIP_REAL_CONSTRAINTS = {"constraint": [
    {"table": "ORDERS",
     "condition": [{"date_range_condition": {"column": "order date",
                                             "duration": 1, "bucket": "YEAR"}}]},
]}


def build_fact_model(constraints=None) -> dict:
    body = {"model_tables": [{"name": "ORDERS", "fqn": "t-orders"}],
            "columns": TRIP_FACT_COLUMNS}
    if constraints is not None:
        body["constraints"] = constraints
    return build_trip_model(**body)


def perf_fact_model_unconstrained() -> AuditContext:
    return build_trip_ctx(build_fact_model())


def perf_fact_model_date_window() -> AuditContext:
    return build_trip_ctx(build_fact_model(TRIP_REAL_CONSTRAINTS))


def perf_fact_model_flattened_window() -> AuditContext:
    """The constraint list without its mapping (a shape no export produces)."""
    return build_trip_ctx(build_fact_model(TRIP_REAL_CONSTRAINTS["constraint"]))


def perf_thin_fact_model() -> AuditContext:
    """Three measures is not >3, so no fact table."""
    return build_trip_ctx(build_trip_model(
        model_tables=[{"name": "ORDERS", "fqn": "t-orders"}],
        columns=TRIP_FACT_COLUMNS[:3]))


def build_aliased_fact_model(prefix: str) -> AuditContext:
    """ORDERS aliased as O, its four measures' column_ids prefixed `prefix`. Legacy P5
    matches fact tables by `name`, not alias (BL-305), so only "ORDERS::" reads as one."""
    return build_trip_ctx(build_trip_model(
        model_tables=[{"name": "ORDERS", "alias": "O", "fqn": "t-orders"}],
        columns=[build_trip_measure(prefix, c)
                 for c in ("AMOUNT", "COST", "QUANTITY", "DISCOUNT")]))


def perf_fact_alias_prefixed() -> AuditContext:
    """Alias-prefixed column_ids (as exported TML writes them): no P5 finding."""
    return build_aliased_fact_model("O")


def perf_fact_name_prefixed() -> AuditContext:
    """Name-prefixed column_ids under an alias: P5 fires, naming ORDERS."""
    return build_aliased_fact_model("ORDERS")


def perf_fact_columns_without_tables() -> AuditContext:
    return build_trip_ctx(build_trip_model(columns=TRIP_FACT_COLUMNS))


# P7 — join depth

def build_join_chain(names) -> AuditContext:
    """model_tables joined in a chain names[0] -> names[1] -> ..."""
    tables = [{"name": n, "fqn": f"t-{n}", "joins": [build_trip_join(nxt)]}
              for n, nxt in zip(names, names[1:])]
    tables.append({"name": names[-1], "fqn": f"t-{names[-1]}"})
    return build_trip_ctx(build_trip_model(model_tables=tables))


def perf_join_chain_four_hops() -> AuditContext:
    """A->B->C->D->E: depth 4, P7 MEDIUM."""
    return build_join_chain(["A", "B", "C", "D", "E"])


def perf_join_chain_six_hops() -> AuditContext:
    """A->...->G: depth 6, P7 HIGH."""
    return build_join_chain(["A", "B", "C", "D", "E", "F", "G"])


def perf_star_schema() -> AuditContext:
    return build_trip_ctx(build_trip_model(model_tables=[
        {"name": "A", "fqn": "t-a", "joins": [build_trip_join("DIM1"), build_trip_join("DIM2")]},
        {"name": "DIM1", "fqn": "t-d1"},
        {"name": "DIM2", "fqn": "t-d2"},
    ]))


def perf_single_table() -> AuditContext:
    return build_trip_ctx(build_trip_model(model_tables=[{"name": "A", "fqn": "t-a"}]))


# P9 — high-cardinality ID column indexed as ATTRIBUTE

P9_ID_SUFFIXES = ["ORDER_GUID", "SESSION_UUID", "ROW_ID", "TRANSACTION_ID", "SURROGATE_KEY"]


def build_id_column(name, index_type=None) -> AuditContext:
    props = {"index_type": index_type} if index_type else {}
    return build_trip_ctx(build_trip_model(
        columns=[build_trip_attribute("ORDERS", name, **props)]))


def perf_indexed_id_attribute() -> AuditContext:
    return build_id_column("CUSTOMER_ID", "DEFAULT")


def perf_id_attribute_default_indexed() -> AuditContext:
    """No index_type: indexed by default."""
    return build_id_column("CUSTOMER_ID")


def perf_id_attribute_not_indexed() -> AuditContext:
    return build_id_column("CUSTOMER_ID", "DONT_INDEX")


def perf_non_id_attribute() -> AuditContext:
    return build_id_column("REGION_NAME", "DEFAULT")


def perf_friendly_id_name() -> AuditContext:
    return build_id_column("Customer Id", "DEFAULT")


def perf_id_measure() -> AuditContext:
    return build_trip_ctx(build_trip_model(columns=[
        {"name": "ORDER_ID", "column_id": "ORDERS::ORDER_ID",
         "properties": {"column_type": "MEASURE", "aggregation": "COUNT",
                        "index_type": "DEFAULT"}}]))


# P11 — indexed-column count on a Spotter-enabled model

def build_spotter_columns(n, index_type=None, spotter=True) -> AuditContext:
    props = {"index_type": index_type} if index_type else {}
    return build_trip_ctx(build_trip_model(
        properties={"spotter_config": {"is_spotter_enabled": spotter}},
        columns=[build_trip_attribute("ORDERS", f"COL_{i}", **props) for i in range(n)]))


def perf_spotter_31_indexed() -> AuditContext:
    return build_spotter_columns(31, "DEFAULT")


def perf_spotter_30_indexed() -> AuditContext:
    return build_spotter_columns(30, "DEFAULT")


def perf_spotter_disabled_31_indexed() -> AuditContext:
    return build_spotter_columns(31, "DEFAULT", spotter=False)


def perf_spotter_31_not_indexed() -> AuditContext:
    return build_spotter_columns(31, "DONT_INDEX")


def perf_spotter_31_default_indexed() -> AuditContext:
    return build_spotter_columns(31)


def perf_spotter_config_absent() -> AuditContext:
    return build_trip_ctx(build_trip_model(columns=[
        build_trip_attribute("ORDERS", f"COL_{i}", index_type="DEFAULT") for i in range(31)]))


# P14 / P15 — RLS expressions and columns

TRIP_PLAIN_RULE = {"name": "Country rule", "expr": "ts_groups = [BANK_EMPLOYEES_1::COUNTRY]"}
TRIP_FUNC_RULE = {"name": "Country rule",
                  "expr": "upper ( [BANK_EMPLOYEES_1::COUNTRY] ) = ts_groups"}
P14_FUNCTION_EXPRS = [
    "trim ( [BANK_EMPLOYEES_1::COUNTRY] ) = ts_groups",
    "cast ( [BANK_EMPLOYEES_1::COUNTRY] as varchar ) = ts_groups",
    "concat ( [BANK_EMPLOYEES_1::COUNTRY] , 'x' ) = ts_groups",
    "if ( ts_groups = 'admin' , true , [BANK_EMPLOYEES_1::COUNTRY] = ts_groups )",
]


def build_rls_expr(expr) -> AuditContext:
    return build_trip_table_ctx([build_trip_varchar("COUNTRY")], [{"name": "R", "expr": expr}])


def perf_rls_function_rule() -> AuditContext:
    """upper(...) around the RLS column (P14 fires); COUNTRY is uncased VARCHAR (P15)."""
    return build_trip_table_ctx([build_trip_varchar("COUNTRY")], [TRIP_FUNC_RULE])


def perf_rls_plain_rule() -> AuditContext:
    """A bare comparison on an uncased VARCHAR column: P15 fires, P14 does not."""
    return build_trip_table_ctx([build_trip_varchar("COUNTRY")], [TRIP_PLAIN_RULE])


def perf_table_without_rls() -> AuditContext:
    return make_context(tables={TRIP_TABLE_FQN: build_trip_table([build_trip_varchar("COUNTRY")])})


def perf_rls_cased_varchar() -> AuditContext:
    return build_trip_table_ctx([build_trip_varchar("COUNTRY", value_casing="UPPER")],
                                [TRIP_PLAIN_RULE])


def perf_rls_integer_column() -> AuditContext:
    int_col = {"name": "COUNTRY_ID", "db_column_name": "COUNTRY_ID",
               "properties": {"column_type": "ATTRIBUTE"},
               "db_column_properties": {"data_type": "INT64"}}
    rule = {"name": "R", "expr": "ts_groups_int = [BANK_EMPLOYEES_1::COUNTRY_ID]"}
    return build_trip_table_ctx([int_col], [rule])


def perf_rls_type_on_model_ignored() -> AuditContext:
    """A model column claims INT64; the TABLE's VARCHAR is what counts."""
    lying_model = build_trip_model(columns=[
        {"name": "COUNTRY", "column_id": "BANK_EMPLOYEES::COUNTRY",
         "properties": {"column_type": "ATTRIBUTE"},
         "db_column_properties": {"data_type": "INT64"}}])
    return make_context(models=[lying_model], tables={
        TRIP_TABLE_FQN: build_trip_table([build_trip_varchar("COUNTRY")], [TRIP_PLAIN_RULE])})


#: Data types where `.upper()` and a case-insensitive match disagree: two ligatures
#: whose upper case is "ST" (legacy reads STRING), and a dotted capital I (not STRING).
P15_UNICODE_TYPES = ["\ufb06RING", "\ufb05RING", "STR\u0130NG"]


def build_rls_column_type(data_type) -> AuditContext:
    """An RLS rule on COUNTRY, an uncased column of `data_type`."""
    col = {"name": "COUNTRY", "db_column_name": "COUNTRY",
           "properties": {"column_type": "ATTRIBUTE"},
           "db_column_properties": {"data_type": data_type}}
    return build_trip_table_ctx([col], [TRIP_PLAIN_RULE])


def perf_rls_friendly_column_name() -> AuditContext:
    """Display name "Country" vs physical COUNTRY: the lookup misses (no P15)."""
    friendly = {"name": "Country", "db_column_name": "COUNTRY",
                "properties": {"column_type": "ATTRIBUTE"},
                "db_column_properties": {"data_type": "VARCHAR"}}
    return build_trip_table_ctx([friendly], [TRIP_PLAIN_RULE])


# P17 — formula cross-reference chain depth

TRIP_REAL_EXPORT_FORMULAS = [
    # From agents/shared/worked-examples/snowflake/ts-to-snowflake.md (an exported
    # DunderMifflin Model): a real cross-reference, id-style.
    {"id": "formula_Product to Category Contribution Ratio",
     "name": "Product to Category Contribution Ratio",
     "expr": "sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , "
             "{ [DM_INVENTORY::PRODUCT_ID] } , query_filters ( ) ) ) "
             "/ [formula_Category Quantity]"},
    {"id": "formula_Category Quantity", "name": "Category Quantity",
     "expr": "sum ( group_aggregate ( sum ( [DM_ORDER_DETAIL::QUANTITY] ) , "
             "{ [DM_CATEGORY::CATEGORY_NAME] } , query_filters ( ) ) )"},
]
CHAIN_NAMES = ["A", "B", "C", "D", "E"]


def build_ref_chain(id_refs: bool) -> list:
    """A -> B -> C -> D -> E, referenced by formula id or by display name."""
    def ref(name):
        return f"[formula_{name}]" if id_refs else f"[{name}]"
    return [{"id": f"formula_{n}", "name": n,
             "expr": (f"{ref(nxt)} * 2" if nxt else "sum ( [ORDERS::AMOUNT] )")}
            for n, nxt in zip(CHAIN_NAMES, CHAIN_NAMES[1:] + [None])]


def perf_formulas_real_export() -> AuditContext:
    return build_trip_ctx(build_trip_model(formulas=TRIP_REAL_EXPORT_FORMULAS))


def perf_formula_listed_twice() -> AuditContext:
    """One formula mapping listed twice (A -> B -> C -> D): legacy P17 reports A once."""
    a = build_formula("A", "[formula_B]")
    return build_trip_ctx(build_trip_model(formulas=[
        a, build_formula("B", "[formula_C]"), build_formula("C", "[formula_D]"),
        build_formula("D", "1"), a]))


def perf_filter_scalar_column() -> AuditContext:
    """Filters whose `column` is a scalar, not a list (hand-edited TML): P3 still
    counts them."""
    return build_trip_ctx(build_trip_model(filters=[
        {"column": 5, "oper": "in", "values": ["x"]},
        {"column": True, "oper": "in", "values": ["x"]},
        {"column": "Region", "oper": "in", "values": ["x"]}]))


def perf_display_ref_chain() -> AuditContext:
    """Depth 4 from A (P17 LOW), 3 from B (P17 INFO)."""
    return build_trip_ctx(build_trip_model(formulas=build_ref_chain(id_refs=False)))


def perf_id_ref_chain() -> AuditContext:
    return build_trip_ctx(build_trip_model(formulas=build_ref_chain(id_refs=True)))


# test_unreachable_checks.py's P17 shapes

def build_formula(name, expr) -> dict:
    return {"id": f"formula_{name}", "name": name, "expr": expr}


def build_formula_doc(formulas) -> dict:
    return {"guid": "m-1", "model": {"name": "S", "formulas": copy.deepcopy(formulas)}}


def refs_id_chain_four() -> AuditContext:
    return make_context(models=[build_formula_doc([
        build_formula("A", "[formula_B] + 1"), build_formula("B", "[formula_C] * 2"),
        build_formula("C", "[formula_D] - 3"), build_formula("D", "sum ( [T::X] )")])])


def refs_display_chain_four() -> AuditContext:
    return make_context(models=[build_formula_doc([
        {"id": "formula_A", "name": "A", "expr": "[B] + 1"},
        {"id": "formula_B", "name": "B", "expr": "[C] * 2"},
        {"id": "formula_C", "name": "C", "expr": "[D] - 3"},
        {"id": "formula_D", "name": "D", "expr": "sum ( [T::X] )"}])])


def refs_plain_columns() -> AuditContext:
    return make_context(models=[build_formula_doc([
        build_formula("A", "sum ( [ORDERS::AMOUNT] )"),
        build_formula("B", "sum ( [ORDERS::COST] )")])])


def refs_self_reference() -> AuditContext:
    return make_context(models=[build_formula_doc([build_formula("A", "[formula_A] + 1")])])


# test_checks_varchar_join_keys.py's shapes (P6 and D2)

JOIN_KEYS_TABLE_FQN = "tbl-orders"
JOIN_KEYS_VARCHAR_COLS = [
    {"name": "CUST_ID", "db_column_properties": {"data_type": "VARCHAR"}},
    {"name": "AMOUNT", "db_column_properties": {"data_type": "INT64"}},
]
JOIN_KEYS_COMPOSITE_ON = ("[ORDERS::CUST_ID] = [CUST::ID] and "
                          "[ORDERS::REGION] = [CUST::REGION]")
JOIN_KEYS_COMPOSITE_COLS = [
    {"name": "CUST_ID", "db_column_properties": {"data_type": "VARCHAR"}},
    {"name": "REGION", "db_column_properties": {"data_type": "TEXT"}},
]


def build_join_keys_table(cols) -> dict:
    return {"table": {"name": "ORDERS", "columns": copy.deepcopy(cols)}}


def build_join_keys_model(on, model_columns=None) -> dict:
    return {"guid": "m-1", "model": {
        "name": "Sales",
        "columns": copy.deepcopy(model_columns) or [
            {"name": "Cust Id", "column_id": "ORDERS::CUST_ID"},
            {"name": "Id", "column_id": "CUST::ID"},
        ],
        "model_tables": [{"name": "ORDERS", "fqn": JOIN_KEYS_TABLE_FQN,
                          "joins": [{"name": "j1", "on": on}]}],
    }}


def build_join_keys_ctx(on, table_cols) -> AuditContext:
    return make_context(models=[build_join_keys_model(on)],
                        tables={JOIN_KEYS_TABLE_FQN: build_join_keys_table(table_cols)})


def join_keys_varchar() -> AuditContext:
    """A bracketed VARCHAR join key (P6 fires)."""
    return build_join_keys_ctx("[ORDERS::CUST_ID] = [CUST::ID]", JOIN_KEYS_VARCHAR_COLS)


def join_keys_integer() -> AuditContext:
    return build_join_keys_ctx("[ORDERS::CUST_ID] = [CUST::ID]",
                               [{"name": "CUST_ID",
                                 "db_column_properties": {"data_type": "INT64"}}])


def join_keys_type_on_model_ignored() -> AuditContext:
    """A model column claims INT64; the TABLE's VARCHAR is what counts."""
    model = build_join_keys_model("[ORDERS::CUST_ID] = [CUST::ID]", model_columns=[
        {"name": "Cust Id", "column_id": "ORDERS::CUST_ID",
         "db_column_properties": {"data_type": "INT64"}}])
    return make_context(models=[model], tables={
        JOIN_KEYS_TABLE_FQN: build_join_keys_table(JOIN_KEYS_VARCHAR_COLS)})


def join_keys_composite() -> AuditContext:
    return build_join_keys_ctx(JOIN_KEYS_COMPOSITE_ON, JOIN_KEYS_COMPOSITE_COLS)


def join_keys_table_missing() -> AuditContext:
    return make_context(models=[build_join_keys_model("[ORDERS::CUST_ID] = [CUST::ID]")],
                        tables={})


# test_referencing_joins.py's shapes (P6, D2, D3)

REF_FACT_FQN, REF_DIM_FQN = "fact-guid", "dim-guid"


def build_referencing_tables(key_type="VARCHAR", join_type="INNER") -> dict:
    return {
        REF_FACT_FQN: {"guid": REF_FACT_FQN, "table": {
            "name": "BASKETS_FACT",
            "columns": [{"name": "PROMOTION_KEY",
                         "db_column_properties": {"data_type": key_type}}],
            "joins_with": [{
                "name": "FK_BASKETFACT_TO_PROMOTIONDIM",
                "destination": {"name": "PROMOTION_DIMENSION", "fqn": REF_DIM_FQN},
                "on": "[BASKETS_FACT::PROMOTION_KEY] = [PROMOTION_DIMENSION::PROMOTION_KEY]",
                "type": join_type}]}},
        REF_DIM_FQN: {"guid": REF_DIM_FQN, "table": {
            "name": "PROMOTION_DIMENSION",
            "columns": [{"name": "PROMOTION_KEY",
                         "db_column_properties": {"data_type": key_type}}]}},
    }


def build_referencing_model(inline_type=None) -> dict:
    join = {"with": "PROMOTION_DIMENSION", "referencing_join": "FK_BASKETFACT_TO_PROMOTIONDIM"}
    if inline_type:
        join["type"] = inline_type
    return {"guid": "m-1", "model": {
        "name": "Retail Sales",
        "columns": [],
        "model_tables": [
            {"name": "BASKETS_FACT", "fqn": REF_FACT_FQN, "joins": [join]},
            {"name": "PROMOTION_DIMENSION", "fqn": REF_DIM_FQN},
        ]}}


def build_referencing_ctx(inline_type=None, **table_kw) -> AuditContext:
    return make_context(models=[build_referencing_model(inline_type)],
                        tables=build_referencing_tables(**table_kw))


def referencing_join_varchar() -> AuditContext:
    """A referencing join whose (table-side) key is VARCHAR (P6 fires)."""
    return build_referencing_ctx()


def referencing_join_integer() -> AuditContext:
    return build_referencing_ctx(key_type="INT64")


def referencing_join_outer() -> AuditContext:
    return build_referencing_ctx(join_type="OUTER")


def referencing_join_model_type_override() -> AuditContext:
    return build_referencing_ctx(inline_type="LEFT_OUTER")


def referencing_join_table_missing() -> AuditContext:
    return make_context(models=[build_referencing_model()], tables={})


# test_dead_guards.py's P5 shapes

GUARD_REAL_CONSTRAINTS = {"constraint": [
    {"date_range_condition": {"column": "Order Date", "period": "LAST_N_DAYS", "n": 90}}]}


def build_guard_fact_model(constraints=None) -> dict:
    """A model with a fact table, so P5 has something to report on."""
    m = {"name": "Sales",
         "columns": [{"name": f"M{i}", "column_id": f"ORDERS::M{i}",
                      "properties": {"column_type": "MEASURE"}} for i in range(4)],
         "model_tables": [{"name": "ORDERS"}]}
    if constraints is not None:
        m["constraints"] = copy.deepcopy(constraints)
    return {"guid": "m-1", "model": m}


def guard_fact_model_unconstrained() -> AuditContext:
    return make_context(models=[build_guard_fact_model()])


def guard_fact_model_date_window() -> AuditContext:
    return make_context(models=[build_guard_fact_model(GUARD_REAL_CONSTRAINTS)])


def guard_fact_model_listed_window() -> AuditContext:
    return make_context(models=[build_guard_fact_model(
        [{"date_range_condition": {"column": "Order Date"}}])])


def guard_fact_model_other_constraint() -> AuditContext:
    return make_context(models=[build_guard_fact_model(
        {"constraint": [{"some_other_condition": {"column": "X"}}]})])


# test_index_type_sense.py's shapes (P9, P11, S2)

def build_index_col(name, ctype, index_type, column_id=None) -> dict:
    props = {"column_type": ctype}
    if index_type is not None:
        props["index_type"] = index_type
    return {"name": name, "column_id": column_id or f"T::{name}", "properties": props}


def build_index_model(cols, **model) -> dict:
    base = {"name": "M", "columns": cols}
    base.update(model)
    return {"guid": "m-1", "model": base}


def build_index_spotter_ctx(cols) -> AuditContext:
    return make_context(models=[build_index_model(
        cols, properties={"spotter_config": {"is_spotter_enabled": True}})])


def index_id_default_indexed() -> AuditContext:
    return make_context(models=[build_index_model(
        [build_index_col("CUSTOMER_ID", "ATTRIBUTE", None)])])


def index_id_not_indexed() -> AuditContext:
    return make_context(models=[build_index_model(
        [build_index_col("CUSTOMER_ID", "ATTRIBUTE", "DONT_INDEX")])])


def index_id_measure() -> AuditContext:
    return make_context(models=[build_index_model(
        [build_index_col("CUSTOMER_ID", "MEASURE", None)])])


def index_spotter_31_default() -> AuditContext:
    return build_index_spotter_ctx([build_index_col(f"C{i}", "ATTRIBUTE", None)
                                    for i in range(31)])


def index_spotter_31_not_indexed() -> AuditContext:
    return build_index_spotter_ctx([build_index_col(f"C{i}", "ATTRIBUTE", "DONT_INDEX")
                                    for i in range(31)])


def index_spotter_mixed() -> AuditContext:
    """31 indexed (by default) and 10 DONT_INDEX columns: 31 indexed."""
    return build_index_spotter_ctx(
        [build_index_col(f"A{i}", "ATTRIBUTE", None) for i in range(31)]
        + [build_index_col(f"B{i}", "ATTRIBUTE", "DONT_INDEX") for i in range(10)])


# test_checks_registry.py's shared-rule shape (P4 and D4)

def registry_wide_not_progressive() -> AuditContext:
    return make_context(models=[{"guid": "m-1", "model": {
        "name": "Wide", "model_tables": [{"name": f"T{i}"} for i in range(6)],
        "properties": {"join_progressive": False}}}])


# test_checks_security_trip.py's shapes (S2/S3/S8/S9; P14 and P15 on the clones)

SEC_TABLE_FQN = "AGENT_SKILLS.PUBLIC.CUSTOMERS"
# A table column carries its warehouse type; a model column does not.
SEC_TABLE_COLS = [
    {"name": "COUNTRY", "db_column_name": "COUNTRY",
     "properties": {"column_type": "ATTRIBUTE"},
     "db_column_properties": {"data_type": "VARCHAR"}},
    {"name": "REGION_ID", "db_column_name": "REGION_ID",
     "properties": {"column_type": "ATTRIBUTE"},
     "db_column_properties": {"data_type": "INT64"}},
]


def build_sec_rls(expr, path_column="COUNTRY") -> dict:
    """`rls_rules` in the nested mapping form the table schema documents."""
    return {
        "tables": [{"name": "CUSTOMERS"}],
        "table_paths": [{"id": "T_1", "table": "CUSTOMERS", "column": [path_column]}],
        "rules": [{"name": "tenant filter", "expr": expr}],
    }


def build_sec_table(rls_rules=None, columns=None, name="CUSTOMERS", guid="t-1") -> dict:
    t = {
        "name": name, "db": "AGENT_SKILLS", "schema": "PUBLIC",
        "db_table": "CUSTOMERS", "connection": {"name": "se-snowflake"},
        "columns": copy.deepcopy(SEC_TABLE_COLS if columns is None else columns),
    }
    if rls_rules:
        t["rls_rules"] = copy.deepcopy(rls_rules)
    return {"guid": guid, "table": t}


def sec_rls_cased_varchar() -> AuditContext:
    """An RLS column that is VARCHAR with value_casing: S8 fires, P15 does not."""
    cased = [{"name": "COUNTRY", "db_column_name": "COUNTRY",
              "properties": {"column_type": "ATTRIBUTE", "value_casing": "UPPER"},
              "db_column_properties": {"data_type": "VARCHAR"}}]
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(
        build_sec_rls("ts_groups = [T_1::COUNTRY]"), columns=cased)})


def sec_rls_uncased_varchar() -> AuditContext:
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(
        build_sec_rls("ts_groups = [T_1::COUNTRY]"))})


def sec_rls_upper_function() -> AuditContext:
    return make_context(tables={SEC_TABLE_FQN: build_sec_table(
        build_sec_rls("UPPER([T_1::COUNTRY]) = ts_groups"))})


# Raw names and guids: present-and-None reaches the finding as None, absent as "".

def perf_names_none() -> AuditContext:
    """Every P scope with `name: None` / `guid: None` (or `id: None`), each firing."""
    model = build_perf_model(
        name=None, guid=None,
        model_tables=[{"name": f"T{i}"} for i in range(6)],
        columns=[build_perf_col(None, aggregation="COUNT_DISTINCT")]
        + [build_perf_col(f"C{i}") for i in range(80)],
        formulas=[{"name": None, "expr": "if(if(if(if([x],1,0),1,0),1,0),1,0) + [formula_B]"},
                  build_formula("B", "[formula_C] + 1"), build_formula("C", "[formula_D]"),
                  build_formula("D", "1")],
        filters=[TRIP_MANDATORY_FILTER])
    table = build_trip_table([build_trip_varchar("COUNTRY")],
                             [TRIP_FUNC_RULE] + [TRIP_PLAIN_RULE] * 4)
    table["guid"] = None
    table["table"]["name"] = None
    return make_context(models=[model], tables={TRIP_TABLE_FQN: table}, metadata=[
        {"metadata_header": {"type": "SQL_VIEW", "name": None, "id": None}}])


def perf_names_absent() -> AuditContext:
    """Every P scope with no `name` / `guid` (or `id`) key, each firing."""
    model = build_perf_model(
        model_tables=[{"name": f"T{i}"} for i in range(6)],
        columns=[{"column_id": "T1::X", "properties": {"column_type": "MEASURE",
                                                      "aggregation": "COUNT_DISTINCT"}}],
        formulas=[{"expr": "if(if(if(if([x],1,0),1,0),1,0),1,0) + [formula_B]"},
                  build_formula("B", "[formula_C] + 1"), build_formula("C", "[formula_D]"),
                  build_formula("D", "1")])
    del model["guid"], model["model"]["name"]
    table = build_trip_table([build_trip_varchar("COUNTRY")], [TRIP_FUNC_RULE] * 5)
    del table["guid"], table["table"]["name"]
    return make_context(models=[model], tables={TRIP_TABLE_FQN: table},
                        metadata=[{"type": "SQL_VIEW"}])


def perf_duplicate_formula_names() -> AuditContext:
    """Two formulas named A, both referencing the chain: legacy P17 keys its graph by
    name, so they report once (the later definition's references win)."""
    return make_context(models=[build_formula_doc([
        build_formula("A", "[formula_B]"), build_formula("B", "[formula_C]"),
        build_formula("C", "[formula_D]"), build_formula("D", "[formula_E]"),
        build_formula("E", "1"),
        {"id": "formula_A2", "name": "A", "expr": "[formula_C] + 1"},
        {"id": "formula_Z", "name": "Z", "expr": "1"},
        {"id": "formula_Z2", "name": "Z", "expr": "[formula_B] + [formula_Z]"},
    ])])


def perf_unnamed_formulas_with_references() -> AuditContext:
    """Two formulas named "" (one by an absent key) that reference a chain: legacy
    P17 merges them under the name ""."""
    return make_context(models=[build_formula_doc([
        {"id": "formula_x", "name": "", "expr": "[formula_B]"},
        {"expr": "[formula_C] * [B]"},
        build_formula("B", "[formula_C]"), build_formula("C", "[formula_D]"),
        build_formula("D", "[formula_E]"), build_formula("E", "1"),
    ])])


# Every P input, for the equivalence test — listed by hand (see AI_INPUTS).
P_INPUTS = {fn.__name__: fn for fn in (
    perf_metadata_sql_view, perf_metadata_logical_only, perf_model_wide_not_progressive,
    perf_model_wide_progressive, perf_fact_alias_prefixed, perf_fact_name_prefixed,
    perf_formula_listed_twice, perf_filter_scalar_column,
    perf_model_80_columns, perf_model_50_columns, perf_table_seven_rls_rules,
    perf_formula_six_nested_ifs, perf_column_count_distinct,
    perf_six_scalar_formulas, perf_eleven_scalar_formulas, perf_six_aggregated_formulas,
    perf_five_scalar_formulas, perf_aggregate_expr_formulas,
    perf_filters_one_mandatory, perf_filters_all_scoped, perf_model_without_filters,
    perf_fact_model_unconstrained, perf_fact_model_date_window,
    perf_fact_model_flattened_window, perf_thin_fact_model, perf_fact_columns_without_tables,
    perf_join_chain_four_hops, perf_join_chain_six_hops, perf_star_schema, perf_single_table,
    perf_indexed_id_attribute, perf_id_attribute_default_indexed,
    perf_id_attribute_not_indexed, perf_non_id_attribute, perf_friendly_id_name,
    perf_id_measure,
    perf_spotter_31_indexed, perf_spotter_30_indexed, perf_spotter_disabled_31_indexed,
    perf_spotter_31_not_indexed, perf_spotter_31_default_indexed, perf_spotter_config_absent,
    perf_rls_function_rule, perf_rls_plain_rule, perf_table_without_rls,
    perf_rls_cased_varchar, perf_rls_integer_column, perf_rls_type_on_model_ignored,
    perf_rls_friendly_column_name,
    perf_formulas_real_export, perf_display_ref_chain, perf_id_ref_chain,
    refs_id_chain_four, refs_display_chain_four, refs_plain_columns, refs_self_reference,
    join_keys_varchar, join_keys_integer, join_keys_type_on_model_ignored,
    join_keys_composite, join_keys_table_missing,
    referencing_join_varchar, referencing_join_integer, referencing_join_outer,
    referencing_join_model_type_override, referencing_join_table_missing,
    guard_fact_model_unconstrained, guard_fact_model_date_window,
    guard_fact_model_listed_window, guard_fact_model_other_constraint,
    index_id_default_indexed, index_id_not_indexed, index_id_measure,
    index_spotter_31_default, index_spotter_31_not_indexed, index_spotter_mixed,
    registry_wide_not_progressive,
    sec_rls_cased_varchar, sec_rls_uncased_varchar, sec_rls_upper_function,
    perf_names_none, perf_names_absent, perf_duplicate_formula_names,
    perf_unnamed_formulas_with_references,
    demo_corpus_models, model_76_columns, model_75_columns, model_id_columns,
    model_role_playing_dimension,
)}
P_INPUTS.update({f"scalar_formulas_{n}_{'agg' if agg else 'raw'}":
                 (lambda n=n, agg=agg: build_trip_ctx(build_formula_model(n, agg)))
                 for n in (0, 5, 6, 10, 11) for agg in (False, True)})
P_INPUTS.update({f"id_suffix_{name}": (lambda name=name: build_id_column(name, "PREFIX_ONLY"))
                 for name in P9_ID_SUFFIXES})
P_INPUTS.update({f"spotter_{n}_{idx or 'omitted'}":
                 (lambda n=n, idx=idx: build_spotter_columns(n, idx))
                 for n in (30, 31) for idx in (None, "DEFAULT", "DONT_INDEX")})
P_INPUTS.update({f"rls_column_type_{i}": (lambda t=t: build_rls_column_type(t))
                 for i, t in enumerate(P15_UNICODE_TYPES + ["varchar", "Text", "INT64", ""])})
P_INPUTS.update({f"rls_function_{i}": (lambda e=e: build_rls_expr(e))
                 for i, e in enumerate(P14_FUNCTION_EXPRS)})
P_INPUTS.update({f"join_chain_{n}_tables": (lambda n=n: build_join_chain(
                 [chr(ord("A") + i) for i in range(n)])) for n in range(1, 9)})
P_INPUTS.update({f"rls_rules_{n}": (lambda n=n: make_context(tables={"db.s.T1": build_perf_table(
                 rls_rules={"rules": [{"expr": f"[col{i}]"} for i in range(n)]})}))
                 for n in range(0, 9)})
