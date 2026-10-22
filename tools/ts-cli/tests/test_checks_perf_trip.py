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
from ts_cli.audit.checks_perf import (
    check_p2, check_p3, check_p5, check_p7, check_p9, check_p11,
    check_p14, check_p15, check_p17,
)

# Every context below is a named builder in audit_rule_fixtures.py (the P section),
# so the P catalog rules' equivalence test runs over exactly these inputs.


# --------------------------------------------------------------------------
# P2 — scalar formula density
# --------------------------------------------------------------------------
# A formula counts as scalar when no columns[] entry surfacing it declares an
# aggregation. Six trips MEDIUM, eleven trips HIGH.

def test_p2_trips_on_six_unaggregated_formulas():
    findings = check_p2(fx.perf_six_scalar_formulas())
    assert len(findings) == 1
    assert findings[0].check_id == "P2"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].metric == 6


def test_p2_escalates_past_ten():
    assert check_p2(fx.perf_eleven_scalar_formulas())[0].severity == "HIGH"


def test_p2_clean_when_formulas_are_aggregated():
    """Same six formulas, each surfaced by an aggregating column: nothing to flag."""
    assert check_p2(fx.perf_six_aggregated_formulas()) == []


def test_p2_clean_under_threshold():
    assert check_p2(fx.perf_five_scalar_formulas()) == []


@pytest.mark.xfail(strict=True, reason=(
    "checks_perf.py:51-53 decides 'scalar' from whether the surfacing columns[] "
    "entry carries an `aggregation:` key, and never looks at `expr`. The model "
    "schema says that key is a no-op on an aggregate expr and APPLIES on a scalar "
    "one, so it does not discriminate -- it is wrong in both directions. Six "
    "`sum ( ... )` formulas are counted and reported as '6 scalar formulas (run at "
    "query time in TS engine)', and six genuinely row-level ones are excluded "
    "whenever their column declares an aggregation. Reported, not fixed."))
def test_p2_metric_counts_the_wrong_formulas():
    assert check_p2(fx.perf_aggregate_expr_formulas()) == [], \
        "sum ( ... ) is not a scalar formula"
    assert len(check_p2(fx.perf_six_aggregated_formulas())) == 1, \
        "[A] - [B] is scalar whether or not the column rolls it up"


# --------------------------------------------------------------------------
# P3 — model filters with no apply_on_tables
# --------------------------------------------------------------------------
# Model schema, filters[] fields: "apply_on_tables ... Absent -> filter is always
# applied (mandatory)." That absence is what P3 reports.

def test_p3_trips_on_a_filter_without_apply_on_tables():
    findings = check_p3(fx.perf_filters_one_mandatory())
    assert len(findings) == 1
    assert findings[0].check_id == "P3"
    assert findings[0].metric == 1
    assert "1/2" in findings[0].detail


def test_p3_clean_when_every_filter_is_table_scoped():
    assert check_p3(fx.perf_filters_all_scoped()) == []


def test_p3_clean_when_model_has_no_filters():
    assert check_p3(fx.perf_model_without_filters()) == []


# --------------------------------------------------------------------------
# P5 — no date constraints on a model with fact tables
# --------------------------------------------------------------------------
# "Fact table" = a model_tables[] entry with >3 MEASURE columns whose column_id
# prefix matches its name.

def test_p5_trips_on_an_unconstrained_fact_model():
    findings = check_p5(fx.perf_fact_model_unconstrained())
    assert len(findings) == 1
    assert findings[0].check_id == "P5"
    assert "ORDERS" in findings[0].detail


def test_p5_clean_when_no_table_looks_like_a_fact():
    """Three measures is not >3, so no fact table, so nothing to constrain."""
    assert check_p5(fx.perf_thin_fact_model()) == []


def test_p5_clean_when_the_model_has_no_tables():
    assert check_p5(fx.perf_fact_columns_without_tables()) == []


def test_p5_a_real_date_constraint_should_suppress_the_finding():
    assert check_p5(fx.perf_fact_model_date_window()) == []


def test_p5_suppression_only_works_on_a_shape_no_export_produces():
    """Pinning the above: flatten the mapping by hand and the guard starts working."""
    # the constraint list without its mapping, which TML never is
    assert check_p5(fx.perf_fact_model_flattened_window()) == []


# --------------------------------------------------------------------------
# P7 — join depth
# --------------------------------------------------------------------------
# `joins[]` lives on the source (FK) entry; `with` names the target model_tables
# entry. A->B->C->D->E is depth 4.

def test_p7_trips_on_a_four_hop_chain():
    findings = check_p7(fx.perf_join_chain_four_hops())
    assert len(findings) == 1
    assert findings[0].check_id == "P7"
    assert findings[0].severity == "MEDIUM"
    assert findings[0].metric == 4


def test_p7_escalates_past_five_hops():
    findings = check_p7(fx.perf_join_chain_six_hops())
    assert findings[0].severity == "HIGH"
    assert findings[0].metric == 6


def test_p7_clean_on_a_star_schema():
    """One fact joined to two dimensions is depth 1 — the shape we want people to use."""
    assert check_p7(fx.perf_star_schema()) == []


def test_p7_clean_when_the_model_has_no_joins():
    assert check_p7(fx.perf_single_table()) == []


# --------------------------------------------------------------------------
# P9 — high-cardinality ID column indexed as ATTRIBUTE
# --------------------------------------------------------------------------
# The name pattern is snake_case-anchored (`_id|_guid|_uuid|...$`), so it only
# matches a model whose column display names are the physical names.

def test_p9_trips_on_an_indexed_id_attribute():
    findings = check_p9(fx.perf_indexed_id_attribute())
    assert len(findings) == 1
    assert findings[0].check_id == "P9"
    assert findings[0].object_name == "CUSTOMER_ID"


@pytest.mark.parametrize("name", fx.P9_ID_SUFFIXES)
def test_p9_trips_on_every_id_suffix_in_the_pattern(name):
    assert len(check_p9(fx.build_id_column(name, "PREFIX_ONLY"))) == 1


def test_p9_clean_on_a_measure():
    assert check_p9(fx.perf_id_measure()) == []


def test_p9_clean_on_a_non_id_attribute():
    assert check_p9(fx.perf_non_id_attribute()) == []


def test_p9_misses_a_friendly_display_name():
    """Not a bug so much as a blind spot worth recording.

    `_ID_PATTERN` anchors on an underscore, and `columns[].name` is the *display*
    name. A model built with friendly names -- the common case for anything a
    converter produced -- never matches, however the column is indexed.
    """
    assert check_p9(fx.perf_friendly_id_name()) == []


def test_p9_index_type_sense_is_inverted():
    """`index_type` absent means indexed; P9 used to test presence (BL-299, fixed)."""
    assert check_p9(fx.perf_id_attribute_not_indexed()) == [], \
        "DONT_INDEX means NOT indexed"
    assert len(check_p9(fx.perf_id_attribute_default_indexed())) == 1, \
        "an omitted index_type IS the indexed default"


# --------------------------------------------------------------------------
# P11 — indexed-column count on a Spotter-enabled model
# --------------------------------------------------------------------------

def test_p11_trips_past_thirty_indexed_columns():
    findings = check_p11(fx.perf_spotter_31_indexed())
    assert len(findings) == 1
    assert findings[0].check_id == "P11"
    assert findings[0].severity == "INFO"
    assert findings[0].metric == 31


def test_p11_clean_at_the_threshold():
    assert check_p11(fx.perf_spotter_30_indexed()) == []


def test_p11_clean_when_spotter_is_disabled():
    assert check_p11(fx.perf_spotter_disabled_31_indexed()) == []


def test_p11_clean_when_spotter_config_is_absent():
    assert check_p11(fx.perf_spotter_config_absent()) == []


def test_p11_index_type_sense_is_inverted():
    """P11 counted columns carrying the key, not indexed ones (BL-299, fixed)."""
    assert check_p11(fx.perf_spotter_31_not_indexed()) == [], \
        "DONT_INDEX means NOT indexed"
    assert len(check_p11(fx.perf_spotter_31_default_indexed())) == 1, \
        "an omitted index_type IS the indexed default"


# --------------------------------------------------------------------------
# P14 — RLS expression wrapped in a function
# --------------------------------------------------------------------------
# Live rule exprs look like `ts_groups = [BANK_EMPLOYEES_1::COUNTRY]` (table
# schema). Wrapping either side in upper()/trim()/cast() is what P14 reports.

def test_p14_trips_on_a_function_wrapped_rls_expression():
    findings = check_p14(fx.perf_rls_function_rule())
    assert len(findings) == 1
    assert findings[0].check_id == "P14"
    assert findings[0].object_name == "BANK_EMPLOYEES"
    assert "upper" in findings[0].detail


@pytest.mark.parametrize("expr", fx.P14_FUNCTION_EXPRS)
def test_p14_trips_on_each_function_in_the_pattern(expr):
    assert len(check_p14(fx.build_rls_expr(expr))) == 1


def test_p14_clean_on_a_bare_column_comparison():
    assert check_p14(fx.perf_rls_plain_rule()) == []


def test_p14_clean_when_the_table_has_no_rls():
    assert check_p14(fx.perf_table_without_rls()) == []


# --------------------------------------------------------------------------
# P15 — VARCHAR RLS column with no value_casing
# --------------------------------------------------------------------------
# P15 reads db_column_properties.data_type off ctx.tables, which is where the
# type actually lives -- the opposite of the P6/D2 defect (finding 14.1), where
# the same key was read off the MODEL, whose columns carry no data type. The
# tests below pin that: a model-side data_type must not influence the result.

def test_p15_trips_on_an_uncased_varchar_rls_column():
    findings = check_p15(fx.perf_rls_plain_rule())
    assert len(findings) == 1
    assert findings[0].check_id == "P15"
    assert findings[0].object_name == "COUNTRY"


def test_p15_clean_when_value_casing_is_set():
    assert check_p15(fx.perf_rls_cased_varchar()) == []


def test_p15_clean_on_an_integer_rls_column():
    assert check_p15(fx.perf_rls_integer_column()) == []


def test_p15_clean_when_the_table_has_no_rls():
    assert check_p15(fx.perf_table_without_rls()) == []


def test_p15_reads_the_type_off_the_table_not_a_model():
    """A model in the context must not be able to supply (or fake) the type.

    This is the check the audit asked about by name: P15 touches
    `db_column_properties` the way the two broken checks did, but it iterates
    `ctx.tables`, so it reads the key on the object that actually carries it.
    """
    # the model column claims INT64 — a lie, and ignored
    assert len(check_p15(fx.perf_rls_type_on_model_ignored())) == 1, \
        "the TABLE's VARCHAR is what counts"


def test_p15_misses_a_column_whose_display_name_differs_from_the_physical_one():
    """Blind spot worth recording, not a fixture problem.

    checks_perf.py:303 keys the lookup on `columns[].name`, but an RLS expr
    references the *physical* column through the table_paths alias. The table
    schema requires `db_column_name` precisely because the two can differ; when
    they do, the lookup misses and the column is silently passed.
    """
    assert check_p15(fx.perf_rls_friendly_column_name()) == []


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
    assert check_p17(fx.perf_formulas_real_export()) == []


def test_p17_only_fires_on_the_shape_that_fails_import():
    """The same chain with display-name refs does trip it — and cannot be imported.

    This is what makes P17 unreachable rather than merely under-tuned: the one
    input shape it recognises is the shape ThoughtSpot rejects, so no exported
    model can ever carry it.
    """
    findings = check_p17(fx.perf_display_ref_chain())
    assert [(f.object_name, f.metric) for f in findings] == [("A", 4), ("B", 3)]


def test_p17_should_see_the_chain_a_real_model_actually_carries():
    findings = check_p17(fx.perf_id_ref_chain())
    assert [(f.object_name, f.metric) for f in findings] == [("A", 4), ("B", 3)]

# NOTE: the H7/P17 defect-characterization tests that lived here were removed
# when BL-300/BL-301 were fixed — they asserted the broken behaviour by design
# and their names encoded it. The corrected behaviour is covered by
# tools/ts-cli/tests/test_unreachable_checks.py.
