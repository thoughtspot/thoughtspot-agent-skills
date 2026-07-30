"""Unit tests for ts_cli.qlik.functions — Qlik expression -> ThoughtSpot formula.

This file did not exist before BL-171, which is why four separate classes of
defect accumulated in `FUNCTION_MAP` unnoticed: bare non-existent string
functions, identity-mapped names that do not exist at all (`len`, `mid`),
fabricated date-truncation names (`date_trunc_*`), and wrong math spellings
(`ceiling`, `power`, `log`).

Every ThoughtSpot name asserted here is either in
`agents/shared/schemas/thoughtspot-formula-patterns.md` or was live-probed on
se-thoughtspot (2026-07-30, `ts tml import --policy VALIDATE_ONLY`, nothing
persisted). `_VERIFIED_CATALOG` below is the probe/catalog result set and
`test_every_mapped_name_exists_in_thoughtspot` is the guard that stops the
class recurring.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ts_cli.qlik.functions import (
    COMPOSITION_MAP,
    FUNCTION_MAP,
    PASSTHROUGH_MAP,
    translate,
)

_REPO = Path(__file__).resolve().parents[3]
_MAP_JSON = _REPO / "tools/ts-cli/ts_cli/qlik/data/qlik_ts_formula_map.json"
_MAP_MD = (_REPO / "agents/shared/mappings/qlik/"
           "qlik-thoughtspot-formula-translation.md")


def tr(expr: str) -> str:
    out, _review, _reason = translate(expr)
    return out


# Functions confirmed to exist in the ThoughtSpot formula parser: the catalog
# (thoughtspot-formula-patterns.md) plus the 2026-07-30 BL-171 probe pass.
#
# TWO CAVEATS, both deliberate and both temporary:
#
# 1. This is a HARDCODED COPY of the catalog, so it can itself drift from
#    `agents/shared/schemas/thoughtspot-formula-patterns.md`. The intended
#    permanent home is `check_formula_catalog.py`, extended to parse the
#    emitter maps out of `tools/ts-cli/ts_cli/**` and check them against the
#    real catalog (BL-171's "validator promotion"). That is **blocked on
#    BL-172** — the catalog scanner silently skips 82% of its input today, so
#    extending it before fixing it would just add a green light. Until then,
#    a name added here must be justified by the catalog or a live probe.
# 2. It records EXISTENCE only, never semantics. `month` is in this set and is
#    the wrong target for a numeric month (`month_number`); `day_of_week` is in
#    it and is the wrong target for a weekday NUMBER (`day_number_of_week`).
#    Both of those were real BL-171 defects that a name-existence check passes
#    happily — see TestSharedReferenceSync's FUNCTION_MAP<->JSON assertion,
#    which is what catches the wrong-meaning class.
_VERIFIED_CATALOG = {
    # aggregation
    "sum", "count", "unique count", "average", "min", "max", "median",
    "stddev", "variance", "greatest", "least",
    "sum_if", "count_if", "unique_count_if", "average_if", "min_if", "max_if",
    "stddev_if", "variance_if",
    "group_sum", "group_average", "group_count", "group_max", "group_min",
    "group_unique_count", "group_aggregate", "query_groups", "query_filters",
    # null / logic
    "isnull", "isnotnull", "ifnull", "nullif", "not", "and", "in", "between",
    "safe_divide",
    # math
    "round", "floor", "ceil", "abs", "pow", "mod", "sqrt", "ln", "log2",
    "log10", "exp", "sign",
    # string
    "concat", "substr", "left", "right", "strlen", "strpos", "contains",
    # type
    "to_integer", "to_double", "to_string", "to_bool", "to_date",
    # date
    "today", "now", "date", "time", "year", "year_name", "quarter_number",
    "month", "month_number", "day", "day_of_week", "day_number_of_week",
    "day_number_of_year", "hour_of_day", "week_number_of_year",
    "start_of_month", "start_of_quarter", "start_of_week", "start_of_year",
    "diff_days", "diff_months", "diff_years", "diff_time",
    "add_days", "add_weeks", "add_months", "add_years",
    # window
    "cumulative_sum", "cumulative_average", "moving_sum", "moving_average",
    "rank",
}

# Live-disproved names (2026-07-29 / 2026-07-30, se-thoughtspot): each is
# rejected with `Search did not find "<fn> ("`, error_code 14516.
_DISPROVED = (
    "trim (", "ltrim (", "rtrim (", "replace (", "starts_with (",
    "ends_with (", "upper (", "lower (", "len (", "mid (", "ceiling (",
    "power (", "log (", "day_of_month (", "date_trunc_month (",
    "date_trunc_year (", "date_trunc_quarter (", "date_trunc_week (",
    "quarter (", "hour (", "minute (", "second (", "unique_count (",
)


def _assert_clean(out: str) -> None:
    for bad in _DISPROVED:
        assert bad not in out, f"{out!r} emits the non-existent {bad!r}"


# A valid call per COMPOSITION_MAP marker (arities differ), used both to probe
# that markers never survive and to derive the emitted function name for the
# FUNCTION_MAP<->rows check. Completeness is asserted, so a new composition
# cannot be added without a probe.
_COMPOSITION_SAMPLE_ARGS = {
    "mid": ("Field", "2", "3"),
    "weekday": ("OrderDate",),
    "index": ("Email", "'@'"),
}


# ---------------------------------------------------------------------------
# The guard: every name the map can emit must exist
# ---------------------------------------------------------------------------

class TestMapIntegrity:
    def test_every_mapped_name_exists_in_thoughtspot(self):
        """No FUNCTION_MAP value may be a ThoughtSpot name that doesn't exist.

        A value is legal if it is a verified ThoughtSpot function, `None`
        (explicitly flagged as having no equivalent), or a PASSTHROUGH_MAP key
        (an intermediate marker the pass-through rewrite consumes before the
        formula is ever emitted)."""
        bad = {
            qlik: ts for qlik, ts in FUNCTION_MAP.items()
            if ts is not None
            and ts not in _VERIFIED_CATALOG
            and ts not in PASSTHROUGH_MAP
            and ts not in COMPOSITION_MAP
        }
        assert bad == {}, f"FUNCTION_MAP emits non-existent names: {bad}"

    def test_passthrough_markers_never_survive_translation(self):
        for name in PASSTHROUGH_MAP:
            arity = PASSTHROUGH_MAP[name][2]
            args = ", ".join(["Field"] + ["'x'"] * (arity - 1))
            out = tr(f"{name.capitalize()}({args})")
            assert "sql_string_op" in out
            _assert_clean(out)

    def test_composition_markers_never_survive_translation(self):
        assert COMPOSITION_MAP  # guard: an empty map would vacuously pass
        assert set(_COMPOSITION_SAMPLE_ARGS) == set(COMPOSITION_MAP), (
            "add a valid sample call for every composition marker, or this "
            "test silently stops covering it")
        for name, args in _COMPOSITION_SAMPLE_ARGS.items():
            out = tr(f"{name.capitalize()}({', '.join(args)})")
            assert f"{name}(" not in out, out
            _assert_clean(out)


class TestSharedReferenceSync:
    """The packaged JSON map and the shared markdown reference must agree.

    BL-170 corrected eleven rows in
    `agents/shared/mappings/qlik/qlik-thoughtspot-formula-translation.md` and
    left `qlik/data/qlik_ts_formula_map.json` — the file the CLI actually
    loads — on the pre-correction values, so `ts qlik` kept serving
    `trim(col)`, `starts_with(...)` and round-paren `in (...)` after the
    documentation said otherwise. This test is the gate on that drift."""

    def test_thoughtspot_column_and_status_match(self):
        rows = {r["#"]: r for r in json.loads(_MAP_JSON.read_text())}
        divergent = []
        checked = 0
        for line in _MAP_MD.read_text().splitlines():
            if not line.startswith("| "):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) < 5 or cells[0] not in rows:
                continue
            row = rows[cells[0]]
            checked += 1
            md_ts = cells[2].replace("`", "")
            if (md_ts != row["ThoughtSpot Equivalent"]
                    or cells[3] != row["status"]):
                divergent.append(
                    f"{cells[0]}: md={md_ts!r}/{cells[3]}  "
                    f"json={row['ThoughtSpot Equivalent']!r}/{row['status']}")
        assert checked > 150, f"only matched {checked} rows — parser drifted"
        assert divergent == [], "\n".join(divergent)

    # Rows the FUNCTION_MAP<->JSON assertion below cannot compare 1:1, each
    # with the reason. Kept explicit and small — a growing list is a smell.
    _MAP_SYNC_EXEMPT = {
        "A04": "Count(DISTINCT x) is handled in translate(), not the map",
        "A11": "Sum(TOTAL x) is Set Analysis -> group_aggregate",
        "A12": "Sum(TOTAL <dim> x) is Set Analysis -> group_aggregate",
        "CA01": "Sum(If(...)) -> sum_if is a nested-call rewrite",
        "CA02": "Avg(If(...)) -> average_if, as CA01",
        "CA03": "Count(If(...)) -> count_if, as CA01",
        "CA04": "Count(DISTINCT If(...)) -> unique_count_if, as CA01",
        "CA05": "Stdev(If(...)) -> stddev_if, as CA01",
        "CA06": "Variance(If(...)) -> variance_if, as CA01",
        "S27": "documents the 2-arg display form Num(expr, format); the CLI "
               "maps bare Num(expr) to to_double (numeric conversion)",
        "TC01": "Num(expr) display/format variant, as S27",
        "TC02": "Text(expr) variant row",
        "SA01": "Set Analysis (Sum({1} x)) — handled by _set_analysis, "
                "not the name map",
        "SA03": "Set Analysis, as SA01",
        "SA04": "Set Analysis, as SA01",
        "SA05": "Set Analysis, as SA01",
        "SA06": "Set Analysis, as SA01",
        # RangeSum is context-dependent — a row-level field sum in one usage, a
        # running total (with Above()) in another. The translator therefore
        # flags it (None) and these two rows document the manual patterns
        # rather than a rename. Note the consequence: neither row says "no
        # direct equivalent", so `audit()` counts them as translatable while
        # the translator flags them — an audit-optimism nuance, not an emitted
        # formula defect.
        "CU01": "RangeSum+Above running-total recipe, not a rename",
        "N16": "RangeSum across fields recipe, not a rename",
    }

    def test_function_map_agrees_with_the_packaged_rows(self):
        """The translator's `FUNCTION_MAP` and the mapping table must name the
        same ThoughtSpot function.

        The two are independent surfaces — `FUNCTION_MAP` drives translation,
        the table drives the skill's own reading and `lookup`/`classify`/
        `audit` — and BL-171 found them disagreeing on `Month` (map said
        `month_number`, the row said `month()` and called it numeric) and
        `Weekday`. Neither an existence check nor the markdown<->JSON check can
        see that class: every name involved exists, they just mean different
        things."""
        rows = json.loads(_MAP_JSON.read_text())
        problems = []
        compared = 0
        for row in rows:
            rid = row["#"]
            if rid in self._MAP_SYNC_EXEMPT:
                continue
            qlik = row["Qlik Sense Formula"]
            tok = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", qlik)
            if not tok:
                continue
            name = tok.group(1).lower()
            if name not in FUNCTION_MAP:
                continue
            expected = FUNCTION_MAP[name]
            ts = row["ThoughtSpot Equivalent"]
            compared += 1
            if expected is None:
                if "no direct equivalent" not in ts.lower():
                    problems.append(
                        f"{rid}: map flags {name!r} as having no equivalent, "
                        f"row says {ts!r}")
                continue
            if expected in PASSTHROUGH_MAP:
                if not ts.startswith("sql_"):
                    problems.append(
                        f"{rid}: map routes {name!r} to a pass-through, "
                        f"row says {ts!r}")
                continue
            if expected in COMPOSITION_MAP:
                # the composition's own output names the real function, so the
                # row cannot claim a different one
                emitted = COMPOSITION_MAP[expected](
                    list(_COMPOSITION_SAMPLE_ARGS[expected]))
                head = re.search(r"([a-z_][a-z0-9_]*)\s*\(", emitted).group(1)
                if head not in ts:
                    problems.append(
                        f"{rid}: map composes {name!r} via {head!r}, "
                        f"row says {ts!r}")
                continue
            head = re.match(r"\s*([a-z_][a-z0-9_ ]*?)\s*\(", ts)
            if not head or head.group(1) != expected:
                problems.append(
                    f"{rid}: map says {name!r} -> {expected!r}, "
                    f"row says {ts!r}")
        assert compared > 30, f"only compared {compared} rows — parser drifted"
        assert problems == [], "\n".join(problems)

    def test_no_row_names_a_disproved_function(self):
        """No mapping row may point at a ThoughtSpot function that does not
        exist. Templates inside sql_*_op are warehouse SQL, not ThoughtSpot
        formula syntax, so their contents are blanked before the check."""
        offenders = {}
        for row in json.loads(_MAP_JSON.read_text()):
            ts = row["ThoughtSpot Equivalent"]
            ts = re.sub(r'"[^"]*"', '""', ts)
            ts = re.sub(r"'[^']*'", "''", ts)
            for name in re.findall(r"([a-z_][a-z0-9_]*)\s*\(", ts):
                if name.startswith("sql_"):
                    continue
                if name + " (" in _DISPROVED or name in {
                        "len", "mid", "ceiling", "power", "log", "quarter",
                        "hour", "minute", "second", "day_of_month",
                        "date_trunc", "unique_count", "trim", "ltrim",
                        "rtrim", "replace", "upper", "lower", "starts_with",
                        "ends_with"}:
                    offenders.setdefault(name, []).append(row["#"])
        assert offenders == {}, f"rows name non-existent functions: {offenders}"


# ---------------------------------------------------------------------------
# Defect class 1 — bare non-existent string functions
# ---------------------------------------------------------------------------

class TestStringPassThroughs:
    def test_trim(self):
        assert tr("Trim(Name)") == "sql_string_op('TRIM({0})', Name)"

    def test_ltrim(self):
        assert tr("LTrim(Name)") == "sql_string_op('LTRIM({0})', Name)"

    def test_rtrim(self):
        assert tr("RTrim(Name)") == "sql_string_op('RTRIM({0})', Name)"

    def test_replace(self):
        assert tr("Replace(Name, 'a', 'b')") == \
            "sql_string_op('REPLACE({0}, {1}, {2})', Name, 'a', 'b')"

    def test_upper_still_passes_through(self):
        assert tr("Upper(Name)") == "sql_string_op('UPPER({0})', Name)"

    def test_lower_still_passes_through(self):
        assert tr("Lower(Name)") == "sql_string_op('LOWER({0})', Name)"

    def test_nested_trim_inside_upper(self):
        assert tr("Upper(Trim(Name))") == \
            "sql_string_op('UPPER({0})', sql_string_op('TRIM({0})', Name))"

    def test_trim_inside_if(self):
        out = tr("If(Trim(Name) = 'x', 1, 0)")
        assert out == \
            "if (sql_string_op('TRIM({0})', Name) = 'x') then 1 else 0"

    def test_replace_with_wrong_arity_is_flagged_for_review(self):
        """A 2-arg Replace has no 3-slot template to fill, so the call is left
        exactly as it was and the translation is flagged. The un-rewritten
        `replace(` DOES reach the emitted formula and WILL fail at import
        (error_code 14516) — that is the intended, loud outcome: the reviewer
        rewrites it. What must never happen is review=False."""
        out, review, reason = translate("Replace(Name, 'a')")
        assert review is True
        assert "Replace" in reason
        assert out == "replace(Name, 'a')"       # untouched, not downgraded
        assert "sql_string_op" not in out

    def test_marker_inside_a_string_literal_is_data_not_a_call(self):
        """`upper(x)` inside a literal is the *text being searched for*, not a
        function call. Rewriting it corrupted the formula into nested quotes
        while reporting review=False — a silent wrong answer."""
        out, review, _reason = translate("Replace(Name, 'upper(x)', 'y')")
        assert out == \
            "sql_string_op('REPLACE({0}, {1}, {2})', Name, 'upper(x)', 'y')"
        assert review is False

    def test_marker_inside_a_literal_alone_is_left_alone(self):
        out, review, _reason = translate("If(Name = 'trim(x)', 1, 0)")
        assert out == "if (Name = 'trim(x)') then 1 else 0"
        assert review is False


# ---------------------------------------------------------------------------
# Defect class 2 — identity-mapped names that do not exist at all
# ---------------------------------------------------------------------------

class TestIdentityMappedNames:
    def test_len_becomes_strlen(self):
        assert tr("Len(Name)") == "strlen(Name)"

    def test_mid_becomes_substr_with_the_index_offset(self):
        """Qlik Mid() is 1-indexed; ThoughtSpot substr() is ZERO-indexed
        (thoughtspot-formula-patterns.md String Functions, authoritative per
        CLAUDE.md). A bare mid->substr rename imports and returns strings
        shifted by one character — worse than the bare `mid ( )` it replaced,
        which at least failed loudly. Same offset the Tableau MID handler
        applies."""
        assert tr("Mid(Name, 2, 3)") == "substr(Name, 2 - 1, 3)"

    def test_mid_wrong_arity_is_flagged(self):
        _out, review, reason = translate("Mid(Name, 2)")
        assert review is True
        assert "Mid" in reason

    def test_mid_nested_in_trim_keeps_the_offset(self):
        assert tr("Trim(Mid(Name, 4, 2))") == \
            "sql_string_op('TRIM({0})', substr(Name, 4 - 1, 2))"

    def test_index_two_arg_becomes_strpos(self):
        """Qlik Index(str, sub) with the default n=1 is exactly strpos."""
        out, review, _reason = translate("Index(Email, '@')")
        assert out == "strpos(Email, '@')"
        assert review is False

    def test_index_nth_occurrence_is_flagged_not_passed_through(self):
        """Qlik Index(str, sub, n) has no ThoughtSpot equivalent. A bare rename
        passed the third argument through as `strpos(Email, '@', 2)` — a real
        function with the wrong arity — so the translation reported success and the
        *import* failed later (live-confirmed 2026-07-30: `Function strpos
        expects only 2 arguments.`). It must be flagged at translate time."""
        out, review, reason = translate("Index(Email, '@', 2)")
        assert review is True
        assert "Index" in reason
        assert out == "index(Email, '@', 2)"      # untouched, not downgraded
        assert "strpos" not in out


# ---------------------------------------------------------------------------
# Defect class 3 — fabricated date-truncation names
# ---------------------------------------------------------------------------

class TestDateFunctions:
    def test_monthstart(self):
        assert tr("MonthStart(OrderDate)") == "start_of_month(OrderDate)"

    def test_yearstart(self):
        assert tr("YearStart(OrderDate)") == "start_of_year(OrderDate)"

    def test_quarterstart(self):
        assert tr("QuarterStart(OrderDate)") == "start_of_quarter(OrderDate)"

    def test_weekstart(self):
        assert tr("WeekStart(OrderDate)") == "start_of_week(OrderDate)"

    def test_day(self):
        assert tr("Day(OrderDate)") == "day(OrderDate)"

    def test_weekday_shifts_the_origin(self):
        """Qlik Weekday() is a NUMBER from 0=Mon; `day_of_week` returns the day
        NAME and `day_number_of_week` numbers from 1=Mon. Renaming alone leaves
        every literal comparison off by one."""
        assert tr("Weekday(OrderDate)") == \
            "(day_number_of_week(OrderDate) - 1)"
        assert tr("Weekday(OrderDate) = 5") == \
            "(day_number_of_week(OrderDate) - 1) = 5"

    def test_month_number(self):
        assert tr("Month(OrderDate)") == "month_number(OrderDate)"


# ---------------------------------------------------------------------------
# Defect class 4 — wrong math spellings
# ---------------------------------------------------------------------------

class TestMathFunctions:
    def test_ceil(self):
        assert tr("Ceil(Amount)") == "ceil(Amount)"

    def test_pow(self):
        assert tr("Pow(Amount, 2)") == "pow(Amount, 2)"

    def test_log_is_natural_log(self):
        assert tr("Log(Amount)") == "ln(Amount)"

    def test_exp_is_native(self):
        # live-verified 2026-07-30: `exp ( )` imports (the qlik mapping doc's
        # "no direct equivalent / verify" row was wrong).
        assert tr("Exp(Amount)") == "exp(Amount)"


# ---------------------------------------------------------------------------
# Defect class 5 — `unique_count` (underscore) does not exist
# ---------------------------------------------------------------------------

class TestDistinctCount:
    def test_count_distinct_uses_the_space_spelling(self):
        assert tr("Count(DISTINCT CustomerId)") == "unique count(CustomerId)"
        _assert_clean(tr("Count(DISTINCT CustomerId)"))


# ---------------------------------------------------------------------------
# Defect class 6 — Qlik Concat() is an AGGREGATION, not row-level concat
# ---------------------------------------------------------------------------

class TestConcatSemantics:
    def test_concat_is_flagged_for_review(self):
        """Qlik `Concat()` joins values ACROSS rows (like GROUP_CONCAT);
        ThoughtSpot `concat()` joins within one row. Mapping the name silently
        produced a valid-but-wrong formula, which the module's own
        flag-don't-downgrade contract forbids (see S14 in
        qlik-thoughtspot-formula-translation.md)."""
        _out, review, reason = translate("Concat(Product, ', ')")
        assert review is True
        assert "Concat" in reason


# ---------------------------------------------------------------------------
# Regression sweep — nothing anywhere emits a disproved name
# ---------------------------------------------------------------------------

class TestNoDisprovedNameEverEmitted:
    def test_sweep(self):
        exprs = [
            "Trim(Name)", "LTrim(Name)", "RTrim(Name)", "Upper(Name)",
            "Lower(Name)", "Replace(Name, 'a', 'b')", "Len(Name)",
            "Mid(Name, 1, 2)", "Ceil(Amount)", "Pow(Amount, 2)",
            "Log(Amount)", "Day(OrderDate)", "MonthStart(OrderDate)",
            "YearStart(OrderDate)", "QuarterStart(OrderDate)",
            "WeekStart(OrderDate)", "Count(DISTINCT Id)",
            "If(Trim(Name) = 'x', Upper(Name), Lower(Name))",
            "Sum({<Region={'EMEA'}>} Revenue)",
            "Sum({1} Revenue)",
        ]
        for expr in exprs:
            _assert_clean(tr(expr))


# ---------------------------------------------------------------------------
# Untouched behaviour (guards against over-correction)
# ---------------------------------------------------------------------------

class TestUnchangedBehaviour:
    def test_sum(self):
        assert tr("Sum(Revenue)") == "sum(Revenue)"

    def test_average(self):
        assert tr("Avg(Revenue)") == "average(Revenue)"

    def test_set_analysis_total(self):
        assert tr("Sum({1} Revenue)") == \
            "group_aggregate(sum(Revenue), {}, {})"

    def test_set_analysis_equals(self):
        assert tr("Sum({<Region={'EMEA'}>} Revenue)") == \
            "sum(if (Region = 'EMEA') then Revenue else 0)"

    def test_unmapped_function_is_flagged(self):
        _out, review, reason = translate("Hash128(Name)")
        assert review is True
        assert "Hash128" in reason

    def test_flag_names_the_spelling_the_author_actually_wrote(self):
        """A reviewer greps their app for the name in the reason. `capitalize()`
        turned `LTrim` into `Ltrim`, which appears nowhere in their Qlik app."""
        _out, review, reason = translate("LTrim(Name, 2)")
        assert review is True
        assert "LTrim" in reason
        assert "Ltrim" not in reason

    def test_set_analysis_dollar_flagged(self):
        _out, review, _reason = translate("Sum({$<Region={'EMEA'}>} Revenue)")
        assert review is True
