"""A (AI Readiness): the inputs the legacy A-check tests use, and AI_INPUTS."""
from __future__ import annotations

import copy

from ts_cli.audit.context import AuditContext, make_context

from .common import (model_measures_no_ai_context, model_measures_with_ai_context,
                     model_without_measures, models_with_and_without_ai_instructions)


# ── A: AI readiness ─────────────────────────────────────────────────────────
# The inputs tests/test_checks_ai.py and tests/test_checks_ai_instructions_shape.py
# exercise the legacy A-checks with, named here so the A rules' examples and the
# pinned-findings test (tests/test_audit_pinned_findings.py) run over the very same
# contexts.
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
    values (blank), structured ai_context (covered). A non-mapping `properties` is not
    here: it leaves the whole Model unjudged (BL-406 item 10), which would hide the rest;
    data_single_model_malformed_column and the run-level tests cover it."""
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
    )


def _instructions_model(**model) -> dict:
    base = {"name": "Sales", "columns": [
        {"name": "Amount", "column_id": "T::AMOUNT", "properties": {"column_type": "MEASURE"}}]}
    base.update(model)
    return {"guid": "m-1", "model": base}


def instructions_live_shape() -> AuditContext:
    """The live ai/instructions/get response shape, with one instruction (BL-292)."""
    return make_context(models=[_instructions_model()], ai_instructions={"m-1": copy.deepcopy(COACHED)})


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


# Every A input, for the pinned-findings test — listed by hand so another category's
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

