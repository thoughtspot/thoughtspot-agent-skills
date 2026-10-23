"""The engine is not quadratic in the size of the context.

H8/H9 compare every Answer formula with every Model formula. The legacy checks built the
Model-formula lookup once; the derived fields that replace them looked it up per Answer
formula, so a large cluster (8,000 Model formulas x 6,000 Answer formulas) took ~9.5s
against ~5ms. Context-wide and per-Model lookups are now computed once per run
(engine/memo.py) — these tests hold that, and that the memo changes no finding.
"""
import time

from ts_cli.audit.catalog_model import load_catalog
from ts_cli.audit.context import make_context
from ts_cli.audit.engine import memo
from ts_cli.audit.engine.run import run_rule, run_rules


def _context(models: int, formulas_per_model: int, answers: int, formulas_per_answer: int):
    """Model formulas `sum([c<m>_<j>])`; Answer formulas cycle through a few of those
    (H9 fires), a shared answer-only expression (H8 fires) and unique ones (neither)."""
    model_docs = []
    for m in range(models):
        formulas = [{"id": f"f{m}_{j}", "name": f"F{m}_{j}", "expr": f"sum ( [c{m}_{j}] )"}
                    for j in range(formulas_per_model)]
        model_docs.append({"guid": f"m{m}", "model": {
            "name": f"Model {m}", "formulas": formulas, "columns": [], "model_tables": []}})
    answer_docs = []
    for a in range(answers):
        formulas = []
        for j in range(formulas_per_answer):
            kind = j % 3
            expr = (f"  SUM (  [c{a % models}_{j}]  ) " if kind == 0 else
                    f"count ( [shared_{j}] )" if kind == 1 else f"max([own_{a}_{j}])")
            formulas.append({"name": f"A{a}_{j}", "expr": expr})
        answer_docs.append({"guid": f"a{a}", "answer": {
            "name": f"Answer {a}", "formulas": formulas, "tables": []}})
    return make_context(models=model_docs, answers=answer_docs)


def _ids_and_details(findings):
    return [(f.check_id, f.severity, f.object_name, f.object_guid, f.detail, f.metric)
            for f in findings]


def test_h8_h9_on_8k_model_and_6k_answer_formulas_run_in_under_a_second():
    ctx = _context(models=80, formulas_per_model=100, answers=600, formulas_per_answer=10)
    cat = load_catalog()
    start = time.perf_counter()
    found = run_rule(ctx, cat, "H8", "general") + run_rule(ctx, cat, "H9", "general")
    elapsed = time.perf_counter() - start
    assert {f.check_id for f in found} == {"H8", "H9"}  # both rules really ran
    assert elapsed < 1.0, f"H8+H9 took {elapsed:.2f}s — a lookup is recomputed per item"


def test_the_memo_changes_no_finding():
    """Every rule, memoised (a run) and not (each derived field computed per call)."""
    ctx = _context(models=6, formulas_per_model=12, answers=20, formulas_per_answer=6)
    cat = load_catalog()
    memoised = run_rules(ctx, cat, list(cat.categories), "general")
    plain = []
    for rule_id in cat.rules:
        with memo.disabled():
            plain += run_rule(ctx, cat, rule_id, "general")
    assert _ids_and_details(memoised) == _ids_and_details(plain)
    assert {"H8", "H9"} <= {f.check_id for f in memoised}


def test_a_memo_lives_for_one_run_only():
    """A context changed between two runs is read afresh: nothing is cached across runs."""
    ctx = _context(models=1, formulas_per_model=3, answers=2, formulas_per_answer=3)
    cat = load_catalog()
    before = run_rule(ctx, cat, "H9", "general")
    ctx.models[0]["model"]["formulas"] = []
    assert before and run_rule(ctx, cat, "H9", "general") == []
