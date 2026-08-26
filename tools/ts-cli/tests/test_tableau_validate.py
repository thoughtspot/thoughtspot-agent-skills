

class TestFunctionCensusCompleteness:
    """Findings 13.22 / 13.25 / 13.26 / 13.27 — the fail-loud contract.

    `tableau-formula-translation.md` L42-56 states that unmapped functions are
    "rejected at translate time instead of being passed through untranslated". Four
    families violated it: two of Tableau's fifteen spatial functions, all ten
    analytics-extension functions, hex-binning, and any unknown RANK_* member. Each
    was emitted verbatim into model TML and failed import opaquely.

    The lesson these encode is that a NAMED LIST goes stale when the vendor adds a
    member — so the MODEL_/SCRIPT_/RANK_ families are matched by regex, mirroring the
    existing _WINDOW_TABLECALC_RE.
    """

    @staticmethod
    def _errs(expr):
        from ts_cli.tableau.validate import validate_output
        return validate_output(expr)

    def test_all_fifteen_spatial_functions_are_rejected(self):
        spatial = ["MAKEPOINT", "MAKELINE", "BUFFER", "OUTLINE", "PARSE_WKT",
                   "DISTANCE", "AREA", "LENGTH", "INTERSECTS", "SHAPETYPE",
                   "DIFFERENCE", "INTERSECTION", "SYMDIFFERENCE", "VALIDATE",
                   "NO_CUTOUTS"]
        assert len(spatial) == 15
        for fn in spatial:
            assert self._errs(f"{fn}([a],[b])"), f"{fn} passed through untranslated"

    def test_the_two_that_were_missing(self):
        """PARSE_WKT and NO_CUTOUTS specifically — the 13-vs-15 gap."""
        for fn in ("PARSE_WKT", "NO_CUTOUTS"):
            assert any(fn in e for e in self._errs(f"{fn}([g])"))

    def test_spatial_census_matches_between_the_two_code_sites(self):
        """validate.py and classify.py each held their own copy; they drifted."""
        from ts_cli.tableau import classify, validate
        geo_in_classify = {
            f for f in ("MAKEPOINT", "MAKELINE", "BUFFER", "OUTLINE", "PARSE_WKT",
                        "DISTANCE", "AREA", "LENGTH", "INTERSECTS", "SHAPETYPE",
                        "DIFFERENCE", "INTERSECTION", "SYMDIFFERENCE", "VALIDATE",
                        "NO_CUTOUTS")
            if classify._GEO_RE.search(f"{f}([a])")
        }
        assert len(geo_in_classify) == 15, sorted(geo_in_classify)
        for f in geo_in_classify:
            assert f in validate._UNMAPPED_FUNCTIONS, f"{f} in classify but not validate"

    def test_analytics_extension_family_is_caught_generically(self):
        for fn in ("MODEL_PERCENTILE", "MODEL_QUANTILE", "MODEL_EXTENSION_REAL",
                   "MODEL_EXTENSION_STR", "MODEL_EXTENSION_INT", "MODEL_EXTENSION_BOOL",
                   "SCRIPT_REAL", "SCRIPT_STR", "SCRIPT_INT", "SCRIPT_BOOL"):
            errs = self._errs(f"{fn}(0.5, SUM([x]))")
            assert errs and any("analytics-extension" in e for e in errs), fn

    def test_a_future_family_member_is_caught_without_a_code_edit(self):
        """The point of a regex over a list."""
        assert self._errs("MODEL_SOMETHING_NEW(SUM([x]))")
        assert self._errs("SCRIPT_FUTURE(SUM([x]))")

    def test_hexbin_is_rejected(self):
        for fn in ("HEXBINX", "HEXBINY"):
            assert self._errs(f"{fn}([lon],[lat])"), fn

    def test_documented_rank_variants_pass_and_unknown_ones_do_not(self):
        from ts_cli.tableau.validate import validate_output
        for fn in ("RANK", "RANK_UNIQUE", "RANK_DENSE", "RANK_MODIFIED",
                   "RANK_PERCENTILE"):
            errs = [e for e in validate_output(f"{fn}(SUM([x]))")
                    if "rank variant" in e]
            assert not errs, f"{fn} has a documented disposition and must not be flagged"
        assert any("rank variant" in e for e in validate_output("RANK_FOOBAR(SUM([x]))"))

    def test_atan2_and_div_now_translate(self):
        from ts_cli.tableau.functions import map_functions
        assert map_functions("ATAN2([y],[x])") == 'sql_double_op ( "ATAN2({0}, {1})" , [y] , [x] )'
        # DIV is integer division; the divisor guard is mandatory in this repo.
        assert map_functions("DIV([a],[b])") == "floor ( safe_divide ( [a] , [b] ) )"

    def test_wrong_arity_is_left_in_place(self):
        """Documented limit, not an oversight.

        Every arity-sensitive handler in functions.py leaves a non-matching call
        untouched (UPPER/LEFT/RIGHT/MID all behave this way). ATAN2/DIV cannot be added
        to _UNMAPPED_FUNCTIONS to catch the leftover, because that scan runs on the raw
        expression and would match the function name inside the emitted
        `sql_double_op ( "ATAN2({0}, {1})" ...)` template.
        """
        from ts_cli.tableau.functions import map_functions
        assert map_functions("ATAN2([y])") == "ATAN2([y])"
