"""BL-460 — a Tableau function the converter has never seen must not pass through.

Before the generic survivor catch, a calc calling a function with no converter
mapping (CORR, VAR, QUARTER, GET_JSON_OBJECT, …) came out of ``translate_formulas``
VERBATIM in ``translated[]`` with no validation error. It then failed at import and
the retry loop dropped it, with no MIGRATION_LIMITATIONS entry: the 13.22 failure
class, found a third time by census (2026-08-26 13.22, 13.25, 2026-11-08 13.16/13.17).

The catch lives in ``tableau/validate.py`` (``_unknown_calls``) and asks the formula
catalog (``formula_translate.catalog.is_known``) whether each surviving call is a
ThoughtSpot function. All fixtures are synthetic.
"""
from __future__ import annotations

import pytest

from ts_cli.tableau.classify import classify_formulas
from ts_cli.tableau.validate import SPATIAL_FUNCTIONS, _UNMAPPED_FUNCTIONS, validate_output
from ts_cli.tableau.verify import verify_conversion
from ts_cli.tableau_translate import translate_formulas, translate_single

# caption -> Tableau calc. The functions named in BL-460 and the audit probes.
UNKNOWN = {
    "Corr Sales Profit": "CORR([Sales], [Profit])",
    "Covar Sample": "COVAR([Sales], [Profit])",
    "Covar Pop": "COVARP([Sales], [Profit])",
    "Var Sample": "VAR([Sales])",
    "Var Pop": "VARP([Sales])",
    "Stdev Pop": "STDEVP([Sales])",
    "Order Quarter": "QUARTER([Order Date])",
    "Log Two": "LOG2([Sales])",
    "Padding": "SPACE(3)",
    "Trim Left This": "LTRIM_THIS([Code], 'x')",
    "Trim Right This": "RTRIM_THIS([Code], 'x')",
    "Collected": "COLLECT([Geometry])",
    "P90 Sales": "PERCENTILE([Sales], 0.9)",
    "Json Id": "GET_JSON_OBJECT([Payload], '$.id')",
    "Url Host": "PARSE_URL([Url], 'HOST')",
    "Url Query": "PARSE_URL_QUERY([Url], 'q')",
    "Xml Value": "XPATH_STRING([Doc], '/a/b')",
    "Name List": "GROUP_CONCAT([Name])",
}


def _mk(caption: str, formula: str) -> dict:
    return {"caption": caption, "name": caption, "formula": formula,
            "role": "measure", "datatype": "real", "datasource": "t"}


def _fn(src: str) -> str:
    return src.split("(", 1)[0]


def _errors(src: str) -> list[str]:
    return translate_single(src)[1]


class TestReproduction:
    """Through the real translate path, each unknown function is skipped with a
    reason that names it; none reaches ``translated[]``."""

    def test_each_unknown_function_is_skipped_with_a_reason_naming_it(self):
        result = translate_formulas([_mk(c, f) for c, f in UNKNOWN.items()])
        translated = {t["name"]: t["expr"] for t in result["translated"]}
        skipped = {s["name"]: s["reason"] for s in result["skipped"]}

        leaked = {c: translated[c] for c in UNKNOWN if c in translated}
        assert not leaked, f"passed through verbatim: {leaked}"
        for caption, src in UNKNOWN.items():
            assert _fn(src) in skipped.get(caption, ""), (caption, skipped.get(caption))

    def test_nested_inside_a_translated_function(self):
        """The survivor is caught even when everything around it translated."""
        expr, errors, _ = translate_single("SUM(VAR([Sales])) / COUNTD([Customer])")
        assert any("VAR" in e for e in errors), (expr, errors)

    def test_any_case_is_caught(self):
        """Tableau is case-insensitive, so `var(` and `Corr(` are the same calls."""
        assert any("var" in e for e in _errors("var([Sales])"))
        assert any("Corr" in e for e in _errors("Corr([Sales], [Profit])"))

    def test_one_reason_per_function(self):
        """A function a specific check already names is not reported twice."""
        errs = _errors("DATEPART('minute', [Order Date])")
        assert errs == ["unmapped Tableau function: DATEPART"], errs
        assert len(validate_output("ROUND ( [x] , [n] )")) == 1
        assert len(_errors("CORR([a], [b]) + CORR([c], [d])")) == 1


class TestCatalogIsTheSource:
    """Whether a call is a ThoughtSpot function comes from the formula catalog,
    the one `ts formula translate` checks, not from a list in validate.py."""

    def test_exact_catalog_spelling_passes(self):
        # catalog table rows, EXTRAS and the family prefixes
        for out in ("variance ( [T::x] )", "log2 ( [T::x] )", "quarter_number ( [T::d] )",
                    "to_date ( [T::s] , 'yyyy-MM-dd' )", "cumulative_sum ( [T::x] , [T::d] )",
                    "group_aggregate ( sum ( [T::x] ) , { } , query_filters ( ) )",
                    'sql_double_aggregate_op ( "CORR({0}, {1})" , [T::a] , [T::b] )'):
            assert validate_output(out) == [], out

    def test_upper_case_spelling_of_a_catalog_name_is_a_survivor(self):
        """LOG2 stays flagged until log2 is live-checked (BL-460): the converter emits
        lower case, so an upper-case call is untranslated Tableau."""
        assert any("LOG2" in e for e in validate_output("LOG2 ( [T::x] )"))

    def test_catalog_nonexistent_names_are_survivors(self):
        # struck through in thoughtspot-formula-patterns.md
        for name in ("ltrim", "nullif", "starts_with"):
            assert any(name in e for e in validate_output(f"{name} ( [T::x] )")), name


class TestNoFalsePositives:
    """Every legitimate output stays clean: translated functions, operators,
    string literals, sql_*_op templates and column names holding a parenthesis."""

    TRANSLATED = [
        "ABS([x])", "ACOS([x])", "ATAN2([y], [x])", "AVG([x])", "ATTR([r])",
        "CEILING([x])", "CONTAINS([s], 'a')", "COT([x])", "COUNTD([x])",
        "DATEADD('month', 1, [d])", "DATEDIFF('day', [a], [b])", "DATENAME('month', [d])",
        "DATEPARSE('yyyy-MM-dd', [s])", "DATEPART('quarter', [d])", "DATETRUNC('week', [d])",
        "DEGREES([x])", "DIV([a], [b])", "ENDSWITH([s], 'x')", "EXP([x])", "FIND([s], 'x')",
        "FINDNTH([s], 'x', 2)", "FLOAT([x])", "IFNULL([x], 0)", "INT([x])",
        "ISMEMBEROF('Group A')", "ISOWEEK([d])", "ISOWEEKDAY([d])", "LEFT([s], 3)", "LEN([s])",
        "LOG([x])", "LOWER([s])", "LTRIM([s])", "MAX([a], [b])", "MEDIAN([x])",
        "MID([s], 2, 3)", "MONTH([d])", "NOW()", "PI()", "POWER([x], 2)", "RADIANS([x])",
        "REGEXP_EXTRACT([s], 'a(b)')", "REGEXP_MATCH([s], 'a')", "REPLACE([s], 'a', 'b')",
        "ROUND([x], 2)", "SIGN([x])", "SIN([x])", "SIZE()", "SQUARE([x])", "STDEV([x])",
        "STR([x])", "TODAY()", "TOTAL(SUM([x]))", "UPPER([s])", "USERNAME()", "WEEK([d])",
        "YEAR([d])", "ZN([x])",
        "{FIXED [Region] : SUM([Sales])}", "{INCLUDE [Region] : SUM([Sales])}",
        "{SUM([Sales])}", "SUM(IF [r] = 'a' THEN [x] ELSE 0 END)", "MAX([r] = 'a')",
        "CASE [r] WHEN 'a' THEN 1 ELSE 2 END", "IIF([x] > 1, 'a', 'b')",
        "IF [r] IN ('a', 'b') THEN 1 ELSE 0 END",
    ]

    @pytest.mark.parametrize("src", TRANSLATED)
    def test_translated_function_is_clean(self, src):
        expr, errors, _ = translate_single(src)
        assert errors == [], (src, expr, errors)

    def test_upper_case_operators_are_not_functions(self):
        src = "IF [x] > 1 AND ([y] < 2 OR NOT ([z] = 3)) THEN 'a' ELSE 'b' END"
        expr, errors, _ = translate_single(src)
        assert "NOT (" in expr and errors == [], (expr, errors)

    def test_column_names_holding_a_parenthesis(self):
        # VAR / CORR / AREA / UNION inside a [field] name are not calls. AREA was a
        # false positive of the named spatial list before BL-460 blanked references.
        for src in ("SUM([Area (sq ft)])", "SUM([VAR (x)]) + SUM([CORR(y)])",
                    "COUNTD([Union (members)])", "[Sales Table::QUARTER (fiscal)]"):
            assert _errors(src) == [], src

    def test_string_literals_holding_a_call(self):
        for src in ("IF [s] = 'CORR(x)' THEN 1 ELSE 0 END",
                    'IF [s] = "SPACE(1)" THEN 1 ELSE 0 END'):
            assert _errors(src) == [], src

    def test_sql_template_text_is_not_a_call(self):
        assert validate_output('sql_int_aggregate_op ( "COUNT(*) OVER ()" )') == []
        assert validate_output('sql_string_op ( "UPPER({0})" , [T::s] )') == []


class TestDocumentedFamiliesAreNotUnknown:
    """RANK_* and RUNNING_* have a documented ThoughtSpot form the CLI does not
    convert (classify tiers them translatable; the parked-formula fix cycle applies
    the form). They are known to the converter, so the survivor catch leaves them."""

    @pytest.mark.parametrize("src", [
        "RUNNING_SUM(SUM([Sales]))", "RUNNING_AVG(SUM([Sales]))", "RUNNING_COUNT(SUM([x]))",
        "RANK_DENSE(SUM([Sales]))", "RANK_MODIFIED(SUM([Sales]))",
        "RANK_PERCENTILE(SUM([Sales]))", "RANK_UNIQUE(SUM([Sales]), 'desc')",
        "RANK(SUM([Sales]), 'asc')",
    ])
    def test_documented_family_member_is_not_flagged(self, src):
        assert _errors(src) == [], src

    def test_classify_tiers_are_unchanged(self):
        out = classify_formulas([_mk("Run", "RUNNING_SUM(SUM([Sales]))"),
                                 _mk("Dense", "RANK_DENSE(SUM([Sales]))")])
        tiers = {f["name"]: f["tier"] for f in out["formulas"]}
        assert tiers == {"Run": "cumulative", "Dense": "pass_through"}

    def test_an_unknown_member_of_either_family_is_flagged(self):
        assert any("RUNNING_FOO" in e for e in _errors("RUNNING_FOO(SUM([x]))"))
        rank_errs = _errors("RANK_FOO(SUM([x]))")
        assert len(rank_errs) == 1 and "rank variant" in rank_errs[0], rank_errs


class TestSpatialCensus:
    """BL-460's second half (finding 13.15): UNION is Tableau's 16th spatial
    function, and the census lives in ONE place."""

    def test_sixteen_including_union(self):
        assert len(SPATIAL_FUNCTIONS) == len(set(SPATIAL_FUNCTIONS)) == 16
        assert "UNION" in SPATIAL_FUNCTIONS and "UNION" in _UNMAPPED_FUNCTIONS

    def test_union_is_skipped_and_tiered_geospatial(self):
        assert _errors("UNION([Geometry])") == ["unmapped Tableau function: UNION"]
        out = classify_formulas([_mk("Merged", "UNION([Geometry])")])
        assert out["formulas"][0]["tier"] == "geospatial"


class TestReachesTheLimitationsChannel:
    """A flagged formula goes where every other untranslatable one goes: skipped[]
    with a reason, tiered untranslatable, so the report lists it as excluded."""

    def test_classify_reason_names_the_function(self):
        out = classify_formulas([_mk("Corr", "CORR([Sales], [Profit])")])
        f = out["formulas"][0]
        assert f["tier"] == "untranslatable" and "CORR" in f["reason"], f


class TestVerifyGate:
    """CLAUDE.md: a deliberate change to what reaches the TML must be taught to
    ts_cli/tableau/verify.py. verify replays translate_formulas through classify, so
    a calc the catch skips is an expected absence, and the gate must still fire for
    a genuine drop."""

    @staticmethod
    def _parsed(*calcs):
        return {"name": "Orders", "tables": [{"name": "ORDERS", "db_table": "db.s.ORDERS"}],
                "sql_views": [], "columns": [], "joins": [], "orphan_calcs": [],
                "calc_map": {},
                "calculated_fields": [{"name": n, "caption": n, "formula": f,
                                       "role": "measure", "datatype": "real",
                                       "internal_name": n} for n, f in calcs]}

    @staticmethod
    def _model(*formula_names):
        return {"model": {"name": "Orders", "model_tables": [{"name": "ORDERS"}],
                          "formulas": [{"id": f"formula_{n}", "name": n,
                                        "expr": "sum ( [ORDERS::AMOUNT] )"}
                                       for n in formula_names],
                          "columns": [{"name": n, "formula_id": f"formula_{n}",
                                       "properties": {"column_type": "MEASURE",
                                                      "aggregation": "SUM"}}
                                      for n in formula_names]}}

    @staticmethod
    def _structural_errors(report):
        structural = next(c for c in report["checks"] if c["name"] == "structural")
        return " ".join(f["message"] for f in structural["findings"]
                        if f["severity"] == "ERROR")

    def test_skipped_unknown_function_is_not_a_drop(self):
        parsed = self._parsed(("Total Amount", "SUM([Amount])"),
                              ("Corr Amount", "CORR([Amount], [Qty])"))
        report = verify_conversion(parsed, self._model("Total Amount"))
        assert "Corr Amount" not in self._structural_errors(report)
        assert report["ok"] is True, report
        # ... and it is counted where every untranslatable formula is
        limitation = next(c for c in report["checks"] if c["name"] == "limitation_coverage")
        assert limitation["stats"]["untranslatable_names"] == ["Corr Amount"]

    def test_gate_still_fires_for_a_genuine_drop(self):
        parsed = self._parsed(("Total Amount", "SUM([Amount])"),
                              ("Corr Amount", "CORR([Amount], [Qty])"))
        report = verify_conversion(parsed, self._model())
        errors = self._structural_errors(report)
        assert "Total Amount" in errors and "Corr Amount" not in errors, errors
        assert report["ok"] is False


class TestFieldNamesHoldingBrackets:
    """BL-460 review: a field name is free text and may hold `[` as well as `(`. One
    reference grammar (formula_translate.refs.REF_GRAMMAR: `[` allowed inside, `]`
    doubled) is used by validate, classify and `ts formula translate`'s guard."""

    @pytest.mark.parametrize("src", [
        "SUM([Revenue (net) [EUR]]])",
        "SUM([Bob's [x] (Sales)])",
        "COUNTD([Orders [CORR (y)]]])",
    ])
    def test_converter_does_not_read_a_call_out_of_the_name(self, src):
        expr, errors, _ = translate_single(src)
        assert errors == [], (src, expr, errors)

    def test_formula_translate_guard_does_not_either(self):
        from ts_cli.formula_translate.traps import output_guard
        assert output_guard("sum ( [T::Revenue (net) [EUR]]] )") is None


class TestClassifyReadsCodeNotNames:
    """BL-460 review: classify's tier regexes read comments-stripped text with literals
    and references blanked, the same masking validate uses."""

    @staticmethod
    def _tier(formula):
        return classify_formulas([_mk("F", formula)])["formulas"][0]["tier"]

    @pytest.mark.parametrize("formula,tier", [
        ("SUM([RUNNING_SUM (legacy)])", "native"),              # field name, was cumulative
        ("IF [s] = 'RANK(' THEN 1 ELSE 0 END", "native"),       # literal, was pass_through
        ("SUM([x]) // was RUNNING_SUM([x])", "native"),         # comment, was cumulative
        ("CORR([Area (sq ft)], [x])", "untranslatable"),        # field name, was geospatial
    ])
    def test_names_literals_and_comments_do_not_decide_a_tier(self, formula, tier):
        assert self._tier(formula) == tier

    def test_every_window_member_is_window_ambiguous(self):
        # WINDOW_CORR and WINDOW_STDEVP were outside the hand list: plain "untranslatable"
        for f in ("WINDOW_CORR(SUM([a]), SUM([b]))", "WINDOW_STDEVP(SUM([a]))",
                  "WINDOW_SUM(SUM([a]))"):
            assert self._tier(f) == "window_ambiguous", f

    def test_collect_is_geospatial(self):
        assert self._tier("COLLECT([Geometry])") == "geospatial"

    def test_parameter_reference_still_tiers(self):
        assert self._tier("SUM([Sales]) * [Parameters].[Rate]") == "parameter_ref"
