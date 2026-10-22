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


# Every A input above, for the equivalence test: the named builders, the families
# swept across every value their legacy tests probe (and the boundaries between).
AI_INPUTS = {
    **{name: fn for name, fn in list(globals().items())
       if name.startswith(("ai_model_", "tml_", "instructions_")) and callable(fn)},
    "demo_corpus_models": demo_corpus_models,
    "models_with_and_without_ai_instructions": models_with_and_without_ai_instructions,
    "model_measures_with_ai_context": model_measures_with_ai_context,
    "model_measures_no_ai_context": model_measures_no_ai_context,
    "model_without_measures": model_without_measures,
    **{f"described_{n}_of_100": (lambda n=n: build_described_columns(n)) for n in range(101)},
    **{f"synonyms_{n}_of_100": (lambda n=n: build_synonym_columns(n)) for n in range(101)},
    **{f"measures_{c}_of_{t}": (lambda c=c, t=t: build_tml_measures(c, t))
       for t in (1, 5, 10) for c in range(t + 1)},
}
