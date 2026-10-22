"""Two checks that could not report what they exist to find (BL-300, BL-301).

P17 (formula cross-reference depth) matched references by **display name**. Real
TML writes a cross-reference as the formula's **id**, and the schema fixes that id
as ``"formula_" + name`` — so the token never equalled a name and the graph was
always empty. The one shape it did recognise, a bare display-name ref, is recorded
as *failing on first import*, so no model the audit can see could carry it.

H7 (answers bypassing the model layer) compared two disjoint GUID namespaces:
``model_tables[].fqn`` is a **Table** guid, ``answer.tables[].fqn`` is the **Model**
the answer was built on. Its condition was `not in`, so every healthy answer was
reported as bypassing, and an answer built straight off a table — the object it
exists to find — was silently excused.
"""
import audit_rule_fixtures as fx
from ts_cli.audit.checks_human import check_h7
from ts_cli.audit.checks_perf import check_p17
from ts_cli.audit.context import make_context


# ── P17 — cross-references are by id ───────────────────────────────────────

# The P17 contexts are named builders in audit_rule_fixtures.py (refs_*), so the P17
# catalog rule's equivalence test runs over exactly these inputs.

def test_p17_follows_a_real_id_reference_chain():
    """The shape every exported model actually carries."""
    findings = check_p17(fx.refs_id_chain_four())
    assert findings, "a 4-deep id-ref chain must be seen"
    assert max(f.metric for f in findings) >= 3


def test_p17_still_follows_a_display_name_chain():
    """Tolerated for a hand-built model, even though it fails on import."""
    assert check_p17(fx.refs_display_chain_four())


def test_p17_ignores_a_plain_column_reference():
    assert check_p17(fx.refs_plain_columns()) == []


def test_p17_does_not_count_a_self_reference():
    assert check_p17(fx.refs_self_reference()) == []


# ── H7 — a Table guid is the bypass, a Model guid is healthy ───────────────

TABLE_GUID, MODEL_GUID = "tbl-1", "mdl-1"


def _ctx(answer_fqn):
    model = {"guid": MODEL_GUID, "model": {
        "name": "Sales", "model_tables": [{"name": "ORDERS", "fqn": TABLE_GUID}]}}
    answer = {"guid": "a-1", "answer": {"name": "A", "tables": [{"fqn": answer_fqn}]}}
    return make_context(models=[model], answers=[answer],
                        tables={TABLE_GUID: {"table": {"name": "ORDERS"}}})


def test_h7_flags_an_answer_built_straight_off_a_table():
    """The object the check exists to find."""
    findings = check_h7(_ctx(TABLE_GUID))
    assert len(findings) == 1
    assert "bypassing the model layer" in findings[0].detail


def test_h7_leaves_a_healthy_answer_alone():
    """Built on the Model — the whole point of having a model layer."""
    assert check_h7(_ctx(MODEL_GUID)) == []


def test_h7_is_silent_on_an_object_it_cannot_resolve():
    """Unknown is not the same as bypassing."""
    assert check_h7(_ctx("something-else")) == []


def test_h7_ignores_an_answer_with_no_table_refs():
    ctx = make_context(models=[], answers=[{"guid": "a-1", "answer": {"name": "A"}}])
    assert check_h7(ctx) == []
