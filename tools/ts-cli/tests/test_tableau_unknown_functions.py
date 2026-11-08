"""BL-460 — a Tableau function the converter has never seen must not pass through.

Before the generic survivor catch, a calc calling a function with no converter
mapping (CORR, VAR, QUARTER, GET_JSON_OBJECT, …) came out of ``translate_formulas``
VERBATIM in ``translated[]`` with no validation error. It then failed at import and
was parked with ThoughtSpot's error, never excluded with a reason: the 13.22 failure
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

    @pytest.mark.parametrize("fn", ["VAR", "LOG2", "CORR", "GROUP_CONCAT"])
    def test_any_case_is_caught(self, fn):
        """Tableau is case-insensitive: every spelling is the same call and gets the same
        verdict. `log2(` and `group_concat(` used to pass (a ThoughtSpot name, and the
        catalog's old `group_` prefix rule) while `LOG2(` / `GROUP_CONCAT(` were skipped."""
        args = "([Sales], [Profit])" if fn == "CORR" else "([Sales])"
        verdicts = {}
        for spelling in (fn, fn.lower(), fn.capitalize()):
            errors = _errors(spelling + args)
            assert errors, f"{spelling}{args} passed through"
            verdicts[spelling] = errors
        assert len({tuple(v) for v in verdicts.values()}) == 1, verdicts
        assert fn in verdicts[fn][0], verdicts[fn]

    def test_lower_case_mapped_functions_still_translate(self):
        for src, out in (("sum([x])", "sum ( [x])"), ("countd([x])", "unique count ( [x])"),
                         ("zn([x]) + 1", "[x] + 1"),  # a measure's ifnull(x, 0) is stripped
                         ("datediff('day', [a], [b])", "diff_days ( [b] , [a] )"),
                         ("if [x] > 1 then 'a' else 'b' end", "if ( [x] > 1 ) then 'a' else 'b'")):
            expr, errors, _ = translate_single(src)
            assert (expr, errors) == (out, []), src

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
        "RUNNING_SUM(SUM([Sales]))", "RUNNING_AVG(SUM([Sales]))", "RUNNING_MAX(SUM([x]))",
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
    """BL-460 re-review (blocker). A field name may hold `[` or a doubled `]]`. The
    scanners read such a name whole (formula_translate.refs.REF_GRAMMAR), but no resolver
    can: `_BRACKET` / `scope_columns` read a name with no bracket in it, so they resolved
    a PIECE of it — `[Revenue (net) [EUR]]]` came back TRANSLATED as
    `sum ( [Revenue (net) [FX::EUR]]])`. How ThoughtSpot escapes a bracket inside a
    reference is unverified, so such a name is refused: NEEDS_REVIEW in
    `ts formula translate`, a skip with a reason in the converter."""

    COLUMNS = ('{"Revenue (net) [EUR]": "ORDERS.Revenue (net) [EUR]", "EUR": "FX.EUR", '
               '"USD": "FX.USD", "%": "T.PCT", "Profit": "ORDERS.Profit", '
               '"Revenue (net)": "ORDERS.Revenue (net)"}')
    NAMES = ["[Revenue (net) [EUR]]]", "[Sales [USD]]]", "[Margin [%] (est)]",
             "[Profit]] Margin]"]

    def _translate(self, src, dialect):
        from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
        from ts_cli.formula_translate.engine import translate
        return translate(src, dialect, ColumnContext(parse_columns_json(self.COLUMNS), level=1))

    @pytest.mark.parametrize("dialect,template", [
        ("tableau", "SUM({})"), ("qlik", "Sum({})"), ("thoughtspot", "sum ( {} )"),
        ("dax", "SUM('Orders'{})"),
    ])
    @pytest.mark.parametrize("name", NAMES)
    def test_formula_translate_refuses_and_resolves_nothing(self, dialect, template, name):
        r = self._translate(template.format(name), dialect)
        assert r["status"] == "NEEDS_REVIEW" and r["formula"] is None, r
        assert r["references"] == [], r["references"]   # no piece of the name resolved
        assert any("bracket" in n for n in r["notes"]), r["notes"]

    def test_a_parenthesis_alone_still_resolves(self):
        r = self._translate("SUM([Revenue (net)])", "tableau")
        assert (r["status"], r["formula"]) == ("TRANSLATED", "sum ( [ORDERS::Revenue (net)])")

    def test_output_guard_backstop(self):
        from ts_cli.formula_translate.traps import output_guard
        assert "bracket" in output_guard("sum ( [T::Revenue (net) [EUR]]] )")
        assert output_guard("sum ( [T::Revenue (net)] )") is None

    @pytest.mark.parametrize("name,ch", [("[Revenue (net) [EUR]]]", "["),
                                         ("[Sales [USD]]]", "["),
                                         ("[Margin [%] (est)]", "["),
                                         ("[Profit]] Margin]", "]")])
    def test_converter_skips_with_the_reason(self, name, ch):
        scoped = {"Revenue (net) [EUR]": "ORDERS", "EUR": "FX", "USD": "FX", "%": "T",
                  "Profit": "ORDERS"}
        result = translate_formulas([_mk("F", f"SUM({name})")], scoped_columns=scoped)
        assert result["translated"] == [], result["translated"]
        reason = result["skipped"][0]["reason"]
        assert f"field name contains '{ch}' — reference it by hand" in reason, reason
        # and no function is read out of the name
        assert "untranslated Tableau function" not in reason, reason

    def test_converter_does_not_read_a_call_out_of_a_bracket_free_name(self):
        assert translate_single("SUM([Bob's (Sales) CORR (y)])")[1] == []


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


class TestCatalogFamilies:
    """BL-460 review: the catalog accepted any `cumulative_` / `moving_` / `group_`
    name. It now accepts the documented members only, shared with `ts formula
    translate`'s output guard."""

    def test_documented_members_are_known(self):
        from ts_cli.formula_translate.catalog import is_known
        for name in ("group_aggregate", "group_sum", "group_average", "group_count",
                     "group_max", "group_min", "group_unique_count", "group_stddev",
                     "group_variance", "cumulative_sum", "cumulative_average",
                     "cumulative_max", "cumulative_min", "moving_sum", "moving_average",
                     "moving_max", "moving_min"):
            assert is_known(name), name

    def test_disproved_and_invented_members_are_not(self):
        from ts_cli.formula_translate.catalog import is_known
        from ts_cli.formula_translate.traps import output_guard
        # cumulative_count / moving_count / moving_stddev: rejected live 2026-07-30
        for name in ("cumulative_count", "moving_count", "moving_stddev", "group_concat"):
            assert not is_known(name), name
            assert output_guard(f"{name} ( [T::a] )"), name


class TestDatetime:
    """BL-460 review: DATETIME has a documented, live-verified pass-through
    (tableau-formula-translation.md, verified 2026-06-15). The survivor catch took it
    out of the parked-formula fix cycle, so the converter now applies it."""

    def test_datetime_translates_to_the_documented_pass_through(self):
        expr, errors, _ = translate_single("DATETIME([Order Date])")
        assert errors == []
        assert expr == 'sql_date_time_op ( "TO_TIMESTAMP({0})" , [Order Date] )'

    def test_in_any_spelling_and_over_a_literal(self):
        expr, errors, _ = translate_single("datetime('2026-01-31 10:00:00')")
        assert errors == []
        assert expr == "sql_date_time_op ( \"TO_TIMESTAMP({0})\" , '2026-01-31 10:00:00' )"

    def test_wrong_arity_is_still_a_survivor(self):
        assert any("DATETIME" in e for e in _errors("DATETIME([a], [b])"))


class TestReviewNits:
    """BL-460 review nits 6(b)-(d)."""

    # (b) /* */ block comments (help.tableau.com Operators documents both styles)
    @pytest.mark.parametrize("src", ["SUM([x]) /* CORR(y) */",
                                     "/* line one\nline two */ SUM([x])"])
    def test_block_comment_is_stripped(self, src):
        assert translate_single(src)[:2] == ("sum ( [x])", [])

    @pytest.mark.parametrize("src,stripped", [
        ("[Bob's Sales] // note", "[Bob's Sales]"),     # the apostrophe opened a literal
        ("[http://site] + 1", "[http://site] + 1"),     # the // in a name was a comment
        ("'a /* b */ c' // x", "'a /* b */ c'"),
        ("'http://x' + [y]", "'http://x' + [y]"),
    ])
    def test_comments_never_inside_a_name_or_literal(self, src, stripped):
        from ts_cli.tableau.pre_transforms import strip_comments
        assert strip_comments(src) == stripped

    # (c) a forbidden pattern that matches at punctuation must not crash the dedupe
    def test_forbidden_pattern_at_punctuation_does_not_crash(self, monkeypatch):
        import re
        from ts_cli.tableau import validate
        monkeypatch.setattr(validate, "_FORBIDDEN_PATTERNS",
                            [(re.compile(r"=="), "'==' (use '=')")])
        assert validate.validate_output("[a] == 1") == ["Contains '==' (use '=')"]

    # (d) RUNNING_COUNT's form is answer-level only (coverage matrix #56, L17)
    def test_running_count_is_caught(self):
        assert any("RUNNING_COUNT" in e for e in _errors("RUNNING_COUNT(SUM([x]))"))
        out = classify_formulas([_mk("Run Count", "RUNNING_COUNT(SUM([x]))")])
        assert out["formulas"][0]["tier"] == "untranslatable"


class TestFormulaTranslateComments:
    """BL-460 re-review item 3: `ts formula translate`'s comment stripper read `//` and
    `/*` inside a `[field]` name as comments, for tableau, dax and qlik. It now uses the
    same reference- and literal-aware scan as the converter."""

    @staticmethod
    def _t(src, dialect):
        from ts_cli.formula_translate.engine import translate
        return translate(src, dialect)

    @pytest.mark.parametrize("dialect,src,names", [
        ("tableau", "SUM([http://site]) + 1", ["http://site"]),
        ("tableau", "SUM([a/*b]) + SUM([c*/d])", ["a/*b", "c*/d"]),
        ("qlik", "Sum([http://site]) + 1", ["http://site"]),
        ("qlik", "Sum([a/*b]) + Sum([c*/d])", ["a/*b", "c*/d"]),
        ("dax", "SUM('T'[http://site]) + 1", ["http://site"]),
    ])
    def test_a_marker_inside_a_name_is_not_a_comment(self, dialect, src, names):
        r = self._t(src, dialect)
        assert r["status"] != "NEEDS_REVIEW", r
        # DAX reports the source table-qualified ('T.http://site')
        sources = [ref["source"].split(".", 1)[-1] if dialect == "dax" else ref["source"]
                   for ref in r["references"]]
        assert sources == names, r["references"]
        assert "comments were removed before translating" not in r["notes"]

    @pytest.mark.parametrize("dialect,src", [
        ("tableau", "SUM([x]) // total"), ("tableau", "SUM([x]) /* it's [y] */"),
        ("qlik", "Sum([x]) // total"), ("dax", "SUM('T'[x]) -- total"),
        ("snowflake", "SUM(a) -- total"),
    ])
    def test_real_comments_are_still_stripped(self, dialect, src):
        r = self._t(src, dialect)
        assert r["status"] == "TRANSLATED", r
        assert "comments were removed before translating" in r["notes"]
        assert len(r["references"]) == 1, r["references"]

    def test_a_sql_subscript_literal_keeps_its_dashes(self):
        from ts_cli.formula_translate.engine import strip_comments
        assert strip_comments("v['a--b'] -- c", "snowflake") == ("v['a--b']", True)
