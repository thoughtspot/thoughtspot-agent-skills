"""Every performance check that was *imported* by a test but never *called* by one.

2026-09-22 audit finding 6.1: 27 of 51 checks are imported by a test and never
invoked. An import satisfies a coverage grep and exercises nothing — which is
exactly how `check_p6`/`check_d2` shipped structurally incapable of returning a
finding and went unnoticed for months (finding 14.1, fixed in PR #528). The nine
checks here are the `checks_perf` half of that list: `test_checks_perf.py` imports
`check_p2, p3, p5, p7, p9, p11, p14, p15, p17` on lines 2-4 and calls none of them.

Each check below gets a **trip** test (a realistic context that must produce a
finding) and a **clean** test (a realistic context that must produce none). Where a
check is reachable but wrong, the defect is pinned with `xfail(strict=True)` so that
fixing it turns the mark red rather than leaving a stale test: nothing here edits a
check.

Fixture shapes are taken from `agents/shared/schemas/thoughtspot-model-tml.md` and
`agents/shared/schemas/thoughtspot-table-tml.md` — in particular:

* `column_id` is `TABLE::COL`, using the `model_tables[]` `alias` when one is set;
* model columns carry **no** `data_type` (the model schema's currency anchor says so
  outright) — types live on the Table TML;
* `constraints:` is a **mapping** with a single `constraint:` list inside it, not a
  list at the top level (model schema, "## `constraints`");
* RLS lives at `table.rls_rules` as `{tables, table_paths, rules}`, and rule `expr`
  bracket refs use the **`table_paths` alias** — `[BANK_EMPLOYEES_1::COUNTRY]`
  (table schema, "### `rls_rules` fields");
* formula cross-references are written as the formula **id** — `[formula_<Name>]` —
  never the display name (model schema, "Formula cross-references: reference by id,
  not display name").
"""
from __future__ import annotations

import pytest

import audit_rule_fixtures as fx
from audit_run_rule import run_rule

# Every context below is a named builder in audit_rule_fixtures (perf.py and rls.py),
# whose legacy answers test_audit_pinned_findings.py pins. The `checks_perf.py:N`
# references below are to the legacy module (deleted when the rule catalog replaced them), which the P catalog
# rules reproduce.


# --------------------------------------------------------------------------
# P2 — row-level formulas recomputed on every query
# --------------------------------------------------------------------------
# A formula counts as row-level when no columns[] entry surfacing it declares an
# aggregation. Six trips LOW, eleven trips MEDIUM (one step down each, 2026-10).

def test_p2_trips_on_six_unaggregated_formulas():
    findings = run_rule(fx.perf_six_scalar_formulas(), "P2")
    assert len(findings) == 1
    assert findings[0].check_id == "P2"
    assert findings[0].severity == "LOW"
    assert findings[0].metric == 6


def test_p2_escalates_past_ten():
    assert run_rule(fx.perf_eleven_scalar_formulas(), "P2")[0].severity == "MEDIUM"


def test_p2_counts_row_level_formulas_whatever_the_column_aggregation():
    """The model schema says a column's `aggregation` applies on a row-level expr, so
    six `[A] - [B]` formulas are row-level whether or not their columns roll them up."""
    assert len(run_rule(fx.perf_six_aggregated_formulas(), "P2")) == 1


def test_p2_clean_when_the_formulas_aggregate():
    assert run_rule(fx.perf_aggregate_expr_formulas(), "P2") == []


def test_p2_clean_under_threshold():
    assert run_rule(fx.perf_five_scalar_formulas(), "P2") == []


# --------------------------------------------------------------------------
# P3 — model filters with no apply_on_tables
# --------------------------------------------------------------------------
# Model schema, filters[] fields: "apply_on_tables ... Absent -> filter is always
# applied (mandatory)." That absence is what P3 reports.

def test_p3_trips_on_a_filter_without_apply_on_tables():
    findings = run_rule(fx.perf_filters_one_mandatory(), "P3")
    assert len(findings) == 1
    assert findings[0].check_id == "P3"
    assert findings[0].metric == 1
    assert "1/2" in findings[0].detail


def test_p3_clean_when_every_filter_is_table_scoped():
    assert run_rule(fx.perf_filters_all_scoped(), "P3") == []


def test_p3_clean_when_model_has_no_filters():
    assert run_rule(fx.perf_model_without_filters(), "P3") == []


# --------------------------------------------------------------------------
# P5 — retired 2026-10 (a date limit on fact tables is a design choice)
# --------------------------------------------------------------------------

def test_p5_is_retired_and_silent_on_an_unconstrained_fact_model():
    assert run_rule(fx.perf_fact_model_unconstrained(), "P5") == []


# --------------------------------------------------------------------------
# P7 — join depth
# --------------------------------------------------------------------------
# `joins[]` lives on the source (FK) entry; `with` names the target model_tables
# entry. A->B->C->D->E is depth 4.

def test_p7_trips_on_a_four_hop_chain():
    findings = run_rule(fx.perf_join_chain_four_hops(), "P7")
    assert len(findings) == 1
    assert findings[0].check_id == "P7"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].metric == 4


def test_p7_escalates_past_five_hops():
    findings = run_rule(fx.perf_join_chain_six_hops(), "P7")
    assert findings[0].severity == "HIGH"
    assert findings[0].metric == 6


def test_p7_clean_on_a_star_schema():
    """One fact joined to two dimensions is depth 1 — the shape we want people to use."""
    assert run_rule(fx.perf_star_schema(), "P7") == []


def test_p7_clean_when_the_model_has_no_joins():
    assert run_rule(fx.perf_single_table(), "P7") == []


# --------------------------------------------------------------------------
# P9 — retired 2026-10 (search indexing is unrelated to query performance)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", fx.P9_ID_SUFFIXES)
def test_p9_is_retired_and_silent_on_every_id_suffix(name):
    assert run_rule(fx.build_id_column(name, "PREFIX_ONLY"), "P9") == []


# --------------------------------------------------------------------------
# P11 — indexed-column count on a Spotter-enabled model
# --------------------------------------------------------------------------

def test_p11_trips_past_thirty_indexed_columns():
    findings = run_rule(fx.perf_spotter_31_indexed(), "P11")
    assert len(findings) == 1
    assert findings[0].check_id == "P11"
    assert findings[0].severity == "INFO"
    assert findings[0].metric == 31


def test_p11_clean_at_the_threshold():
    assert run_rule(fx.perf_spotter_30_indexed(), "P11") == []


def test_p11_clean_when_spotter_is_disabled():
    assert run_rule(fx.perf_spotter_disabled_31_indexed(), "P11") == []


def test_p11_clean_when_spotter_config_is_absent():
    assert run_rule(fx.perf_spotter_config_absent(), "P11") == []


def test_p11_index_type_sense_is_inverted():
    """P11 counted columns carrying the key, not indexed ones (BL-299, fixed)."""
    assert run_rule(fx.perf_spotter_31_not_indexed(), "P11") == [], \
        "DONT_INDEX means NOT indexed"
    assert len(run_rule(fx.perf_spotter_31_default_indexed(), "P11")) == 1, \
        "an omitted index_type IS the indexed default"


# --------------------------------------------------------------------------
# P14 — RLS expression wrapped in a function
# --------------------------------------------------------------------------
# Live rule exprs look like `ts_groups = [BANK_EMPLOYEES_1::COUNTRY]` (table
# schema). Wrapping either side in upper()/trim()/cast() is what P14 reports.

def test_p14_trips_on_a_function_wrapped_rls_expression():
    findings = run_rule(fx.perf_rls_function_rule(), "P14")
    assert len(findings) == 1
    assert findings[0].check_id == "P14"
    assert findings[0].object_name == "BANK_EMPLOYEES"
    assert "upper" in findings[0].detail


@pytest.mark.parametrize("expr", fx.P14_FUNCTION_EXPRS)
def test_p14_trips_on_each_function_in_the_pattern(expr):
    assert len(run_rule(fx.build_rls_expr(expr), "P14")) == 1


def test_p14_clean_on_a_bare_column_comparison():
    assert run_rule(fx.perf_rls_plain_rule(), "P14") == []


def test_p14_clean_when_the_table_has_no_rls():
    assert run_rule(fx.perf_table_without_rls(), "P14") == []


# --------------------------------------------------------------------------
# P15 — VARCHAR RLS column with no value_casing
# --------------------------------------------------------------------------
# P15 reads db_column_properties.data_type off ctx.tables, which is where the
# type actually lives -- the opposite of the P6/D2 defect (finding 14.1), where
# the same key was read off the MODEL, whose columns carry no data type. The
# tests below pin that: a model-side data_type must not influence the result.

def test_p15_trips_on_an_uncased_varchar_rls_column():
    findings = run_rule(fx.perf_rls_plain_rule(), "P15")
    assert len(findings) == 1
    assert findings[0].check_id == "P15"
    assert findings[0].object_name == "COUNTRY"


def test_p15_clean_when_value_casing_is_set():
    assert run_rule(fx.perf_rls_cased_varchar(), "P15") == []


def test_p15_clean_on_an_integer_rls_column():
    assert run_rule(fx.perf_rls_integer_column(), "P15") == []


def test_p15_clean_when_the_table_has_no_rls():
    assert run_rule(fx.perf_table_without_rls(), "P15") == []


def test_p15_reads_the_type_off_the_table_not_a_model():
    """A model in the context must not be able to supply (or fake) the type.

    This is the check the audit asked about by name: P15 touches
    `db_column_properties` the way the two broken checks did, but it iterates
    `ctx.tables`, so it reads the key on the object that actually carries it.
    """
    # the model column claims INT64 — a lie, and ignored
    assert len(run_rule(fx.perf_rls_type_on_model_ignored(), "P15")) == 1, \
        "the TABLE's VARCHAR is what counts"


def test_p15_misses_a_column_whose_display_name_differs_from_the_physical_one():
    """Blind spot worth recording, not a fixture problem.

    checks_perf.py:303 keys the lookup on `columns[].name`, but an RLS expr
    references the *physical* column through the table_paths alias. The table
    schema requires `db_column_name` precisely because the two can differ; when
    they do, the lookup misses and the column is silently passed.
    """
    assert run_rule(fx.perf_rls_friendly_column_name(), "P15") == []


# --------------------------------------------------------------------------
# P17 — formula cross-reference chain depth  (CANNOT TRIP on real TML)
# --------------------------------------------------------------------------
# checks_perf.py:351  formula_names = {f.get("name", "") for f in formulas}
# checks_perf.py:357  cross_refs = [r for r in refs if r in formula_names ...]
#
# Real TML references a formula by its **id**, and the id is by construction
# "formula_" + name. So the token pulled out of the expr is "formula_Category
# Quantity" while the set holds "Category Quantity" — the two can never be equal,
# for any model, and the graph is always empty.
#
# The only shape that DOES match is a bare display-name ref, which the model
# schema records as failing on first import ("Search did not find ..."). Since
# the audit only ever sees TML exported from an instance, every model it reads
# imported successfully, so no model it reads can carry that shape.

def test_p17_returns_nothing_for_a_real_exported_cross_reference():
    """Minimal reproduction against TML copied out of a live export."""
    assert run_rule(fx.perf_formulas_real_export(), "P17") == []


def test_p17_only_fires_on_the_shape_that_fails_import():
    """The same chain with display-name refs does trip it — and cannot be imported.

    This is what makes P17 unreachable rather than merely under-tuned: the one
    input shape it recognises is the shape ThoughtSpot rejects, so no exported
    model can ever carry it.
    """
    findings = run_rule(fx.perf_display_ref_chain(), "P17")
    assert [(f.object_name, f.metric) for f in findings] == [("A", 4), ("B", 3)]


def test_p17_should_see_the_chain_a_real_model_actually_carries():
    findings = run_rule(fx.perf_id_ref_chain(), "P17")
    assert [(f.object_name, f.metric) for f in findings] == [("A", 4), ("B", 3)]

# NOTE: the H7/P17 defect-characterization tests that lived here were removed
# when BL-300/BL-301 were fixed — they asserted the broken behaviour by design
# and their names encoded it. The corrected behaviour is covered by
# tools/ts-cli/tests/test_unreachable_checks.py.
