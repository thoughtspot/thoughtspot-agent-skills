"""Duplicate-column_id → formula promotion (TML invariant I8/I5), shared by the
from-Databricks and from-Snowflake Model builders (BL-132).

A source that references one physical column both as a raw measure and as an
aggregate metric (e.g. F_TIME_TO_RESOLVE + AVG(TIMETORESOLVE__C)) produces two
columns[] entries with an identical TABLE::col column_id — which ThoughtSpot
rejects on import ("columns should have unique column_id values"). The shared
helper keeps the first as a column_id entry and re-expresses the rest as
`fn ( [TABLE::col] )` aggregation formulas so every column_id stays unique.
"""
import pytest

from ts_cli.formula_common import promote_duplicate_column_ids
from ts_cli.databricks.mv_build_model import (
    build_columns_and_formulas as dbx_build,
)
from ts_cli.sv_build_model import build_columns_and_formulas as sv_build
from ts_cli.tml_lint import lint_tml


def _col_ids(columns):
    return [c["column_id"] for c in columns if "column_id" in c]


# ---------------------------------------------------------------------------
# The shared helper in isolation
# ---------------------------------------------------------------------------

class TestPromoteDuplicateColumnIds:
    def _measure_candidate(self, name, agg):
        return {"name": name,
                "entry": {"column_type": "MEASURE", "table": "SFCASE",
                          "column": "TIMETORESOLVE__C", "aggregation": agg},
                "src_name": name}

    def test_no_duplicates_is_noop(self):
        physical = [
            {"name": "A", "entry": {"column_type": "MEASURE", "table": "T",
                                    "column": "a", "aggregation": "SUM"}},
            {"name": "B", "entry": {"column_type": "MEASURE", "table": "T",
                                    "column": "b", "aggregation": "SUM"}},
        ]
        kept, formulas, promoted = promote_duplicate_column_ids(physical, [])
        assert kept == physical
        assert formulas == []
        assert promoted == []

    def test_second_measure_on_same_column_promoted(self):
        physical = [self._measure_candidate("Time To Resolve", "SUM"),
                    self._measure_candidate("Avg Time To Resolve", "AVERAGE")]
        kept, formulas, promoted = promote_duplicate_column_ids(physical, [])
        # first stays a physical column, second becomes an aggregation formula
        assert [c["name"] for c in kept] == ["Time To Resolve"]
        assert promoted == ["Avg Time To Resolve"]
        assert len(formulas) == 1
        assert formulas[0]["expr"] == "average ( [SFCASE::TIMETORESOLVE__C] )"
        # the promoted candidate carries formula-measure shape: expr + entry
        assert formulas[0]["entry"]["column_type"] == "MEASURE"
        # convention: formula-measure column aggregation is SUM (TS ignores it)
        assert formulas[0]["entry"]["aggregation"] == "SUM"

    def test_inputs_not_mutated(self):
        physical = [self._measure_candidate("Sum TTR", "SUM"),
                    self._measure_candidate("Max TTR", "MAX")]
        original_second_entry = dict(physical[1]["entry"])
        existing_formulas = [{"name": "F", "expr": "count ( 1 )", "entry": {}}]
        kept, formulas, _ = promote_duplicate_column_ids(physical, existing_formulas)
        # original lists/dicts untouched
        assert len(physical) == 2
        assert physical[1]["entry"] == original_second_entry
        assert existing_formulas == [{"name": "F", "expr": "count ( 1 )", "entry": {}}]
        # pre-existing formulas preserved, promotion appended
        assert formulas[0]["name"] == "F"
        assert formulas[-1]["name"] == "Max TTR"

    @pytest.mark.parametrize("agg,fn", [
        ("SUM", "sum"), ("AVERAGE", "average"), ("MIN", "min"), ("MAX", "max"),
        ("COUNT", "count"), ("MEDIAN", "median"), ("STDDEV", "stddev"),
        ("STD_DEVIATION", "stddev"), ("VARIANCE", "variance"),
        ("COUNT_DISTINCT", "unique count"),
    ])
    def test_aggregation_function_map(self, agg, fn):
        physical = [self._measure_candidate("First", "SUM"),
                    self._measure_candidate("Dup", agg)]
        _, formulas, _ = promote_duplicate_column_ids(physical, [])
        assert formulas[0]["expr"] == f"{fn} ( [SFCASE::TIMETORESOLVE__C] )"

    def test_unmapped_aggregation_left_in_place(self):
        # An aggregation with no formula-function mapping is not promoted —
        # the duplicate stays so `ts tml lint` I8 surfaces it (fail-loud),
        # rather than the builder emitting a silently-wrong formula.
        physical = [self._measure_candidate("First", "SUM"),
                    self._measure_candidate("Weird", "APPROX_PERCENTILE")]
        kept, formulas, promoted = promote_duplicate_column_ids(physical, [])
        assert [c["name"] for c in kept] == ["First", "Weird"]
        assert formulas == []
        assert promoted == []

    def test_attribute_duplicate_left_in_place(self):
        # Two dimensions on the same physical column is a modelling decision the
        # author must resolve — the helper does NOT silently promote it; the
        # duplicate stays so `ts tml lint` I8 surfaces it. Only aggregates
        # (which map cleanly to a formula function) are promoted.
        physical = [
            {"name": "Region", "entry": {"column_type": "ATTRIBUTE",
                                         "table": "T", "column": "region"}},
            {"name": "Sales Region", "entry": {"column_type": "ATTRIBUTE",
                                               "table": "T", "column": "region"}},
        ]
        kept, formulas, promoted = promote_duplicate_column_ids(physical, [])
        assert [c["name"] for c in kept] == ["Region", "Sales Region"]
        assert formulas == []
        assert promoted == []


# ---------------------------------------------------------------------------
# End-to-end through each builder — the fact-col + aggregate-on-same-col fixture
# ---------------------------------------------------------------------------

def _dbx_entry(name, agg, dn):
    return {"name": name, "role": "measure", "output_kind": "column",
            "column_type": "MEASURE", "table": "SFCASE",
            "column": "TIMETORESOLVE__C", "ts_expr": None, "aggregation": agg,
            "inlined_refs": [], "display_name": dn, "comment": None,
            "synonyms": [], "format": None, "annotations": []}


def _sv_entry(name, agg):
    return {"name": name, "output_kind": "column", "column_type": "MEASURE",
            "table": "SFCASE", "column": "TIMETORESOLVE__C", "aggregation": agg,
            "synonyms": [], "comment": None, "is_private": False}


class TestDatabricksBuilderPromotesDuplicate:
    def test_unique_column_ids_and_formula_emitted(self):
        translated = [_dbx_entry("F_TIME_TO_RESOLVE", "SUM", "Time To Resolve"),
                      _dbx_entry("AVG_TTR", "AVERAGE", "Avg Time To Resolve")]
        columns, formulas, _ = dbx_build(translated, None)
        ids = _col_ids(columns)
        assert len(ids) == len(set(ids)), f"duplicate column_id: {ids}"
        assert ids == ["SFCASE::TIMETORESOLVE__C"]
        assert [f["name"] for f in formulas] == ["Avg Time To Resolve"]
        assert formulas[0]["expr"] == "average ( [SFCASE::TIMETORESOLVE__C] )"

    def test_emitted_tml_passes_i8_lint(self):
        from ts_cli.databricks.mv_build_model import build_model_tml_dbx
        translated_doc = {
            "translated": [_dbx_entry("F_TIME_TO_RESOLVE", "SUM", "Time To Resolve"),
                           _dbx_entry("AVG_TTR", "AVERAGE", "Avg Time To Resolve")],
            "window_measures": [],
        }
        parsed = {"comment": None,
                  "joins": [],
                  "source": {"kind": "table_fqn", "raw": "cat.sch.SFCASE",
                             "parts": ["cat", "sch", "SFCASE"]}}
        tables = {"source": {"name": "SFCASE", "fqn": "g-sfcase"}}
        doc, _ = build_model_tml_dbx(model_name="M", parsed=parsed,
                                     translated_doc=translated_doc, tables=tables)
        findings = lint_tml(doc)
        assert not [f for f in findings if f.startswith("I8")], findings


class TestSnowflakeBuilderPromotesDuplicate:
    def test_unique_column_ids_and_formula_emitted(self):
        translated = [_sv_entry("F_TIME_TO_RESOLVE", "SUM"),
                      _sv_entry("AVG_TTR", "AVERAGE")]
        columns, formulas, _ = sv_build(translated)
        ids = _col_ids(columns)
        assert len(ids) == len(set(ids)), f"duplicate column_id: {ids}"
        assert ids == ["SFCASE::TIMETORESOLVE__C"]
        assert len(formulas) == 1
        assert formulas[0]["expr"] == "average ( [SFCASE::TIMETORESOLVE__C] )"
