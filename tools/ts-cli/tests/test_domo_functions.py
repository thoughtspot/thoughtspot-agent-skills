"""Domo Beast Mode translator — integrity of the function map, and the PR #440 review findings.

Every test here corresponds to a defect that shipped in the first revision of the
ts-convert-from-domo PR. The map-integrity test is the durable one: it cross-checks
every emitted ThoughtSpot name against the repo's live-verified catalog, so a future
edit cannot reintroduce a function that does not exist.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from ts_cli.domo.functions import (
    FUNCTION_MAP,
    PASSTHROUGH_MAP,
    _KNOWN_TS,
    translate,
)

_VALIDATE_DIR = str(pathlib.Path(__file__).resolve().parents[3] / "tools" / "validate")
_CATALOG = (pathlib.Path(__file__).resolve().parents[3]
            / "agents" / "shared" / "schemas" / "thoughtspot-formula-patterns.md")


def _catalog() -> tuple[set[str], set[str]]:
    if _VALIDATE_DIR not in sys.path:
        sys.path.insert(0, _VALIDATE_DIR)
    from check_formula_catalog import parse_catalog  # noqa: PLC0415
    return parse_catalog(_CATALOG.read_text(encoding="utf-8"))


class TestMapIntegrity:
    """BL-170/BL-171: never emit a ThoughtSpot function that does not exist."""

    def test_no_emitted_name_is_live_disproved(self):
        _valid, nonexistent = _catalog()
        emitted = {v for v in FUNCTION_MAP.values() if v} - set(PASSTHROUGH_MAP)
        offenders = sorted(emitted & nonexistent)
        assert not offenders, (
            f"FUNCTION_MAP emits {offenders}, which formula-patterns.md marks as "
            "non-existent in ThoughtSpot. Route them through PASSTHROUGH_MAP instead."
        )

    def test_markers_never_reach_known_ts(self):
        """A marker leaking into _KNOWN_TS would let it pass through unrewritten."""
        assert not (set(PASSTHROUGH_MAP) & _KNOWN_TS)

    def test_markers_never_survive_translation(self):
        for domo_name, marker in FUNCTION_MAP.items():
            if marker not in PASSTHROUGH_MAP:
                continue
            _op, _tmpl, arity = PASSTHROUGH_MAP[marker]
            args = ", ".join(["`col`"] + ["'x'"] * (arity - 1))
            out, _review, _reason = translate(f"{domo_name.upper()}({args})")
            assert marker not in out, f"marker {marker} leaked for {domo_name}"
            assert "sql_string_op" in out

    def test_unique_count_spelling_is_not_whitelisted(self):
        """`unique count` (space) is emitted; `unique_count` is rejected by the parser."""
        assert "unique_count" not in _KNOWN_TS
        _out, review, _ = translate("unique_count(`id`)")
        assert review is True


class TestPassthroughs:
    @pytest.mark.parametrize("expr,expected", [
        ("UPPER(`Region`)", "sql_string_op('UPPER({0})', [Region])"),
        ("LOWER(`Email`)", "sql_string_op('LOWER({0})', [Email])"),
        ("TRIM(`Name`)", "sql_string_op('TRIM({0})', [Name])"),
        ("LTRIM(`Name`)", "sql_string_op('LTRIM({0})', [Name])"),
        ("RTRIM(`Name`)", "sql_string_op('RTRIM({0})', [Name])"),
    ])
    def test_string_functions_become_sql_passthroughs(self, expr, expected):
        out, review, _reason = translate(expr)
        assert out == expected
        assert review is False, "a correct pass-through is Migrated, not NEEDS REVIEW"

    def test_replace_three_arg(self):
        out, review, _ = translate("REPLACE(`a`, 'x', 'y')")
        assert out == "sql_string_op('REPLACE({0}, {1}, {2})', [a], 'x', 'y')"
        assert review is False

    def test_nested_passthroughs(self):
        out, review, _ = translate("TRIM(REPLACE(`Product Name`, '-', ' '))")
        assert out.startswith("sql_string_op('TRIM({0})'")
        assert "REPLACE({0}, {1}, {2})" in out
        assert review is False


class TestSubstr:
    def test_substring_maps_to_substr_not_substring(self):
        """`substring` is not a ThoughtSpot function; `substr` is."""
        for expr in ("SUBSTRING(`s`, 1, 3)", "SUBSTR(`s`, 1, 3)"):
            out, review, _ = translate(expr)
            # whitespace inside the arg list passes through unchanged
            assert out == "substr([s], 1, 3)"
            assert review is False


class TestCase:
    def test_simple_form_case_is_flagged(self):
        """`CASE expr WHEN` has no `CASE WHEN` prefix but is equally untranslatable."""
        out, review, reason = translate("CASE `Status` WHEN 'A' THEN 1 ELSE 0 END")
        assert review is True
        assert "CASE" in out           # emitted verbatim, never a wrong substitute
        assert "CASE" in reason

    def test_searched_form_case_is_flagged(self):
        _out, review, _ = translate("CASE WHEN `Status` = 'A' THEN 1 ELSE 0 END")
        assert review is True

    @pytest.mark.parametrize("expr", [
        "RANK() OVER (PARTITION BY `region`)",
        "SUM(`Revenue`) OVER (PARTITION BY `region`)",
    ])
    def test_window_constructs_flagged(self, expr):
        assert translate(expr)[1] is True


class TestStillMigratedCorrectly:
    """Guard the other direction — the valid subset must stay unflagged."""

    @pytest.mark.parametrize("expr,expected", [
        ("SUM(`Revenue`)", "sum([Revenue])"),
        ("AVG(`Price`)", "average([Price])"),
        ("COUNT(DISTINCT `id`)", "unique count([id])"),
        ("CONCAT(`a`, `b`)", "concat([a], [b])"),
        ("LENGTH(`x`)", "strlen([x])"),
        ("POWER(`x`, 2)", "pow([x], 2)"),
        ("DATEDIFF(`b`, `a`)", "diff_days([b], [a])"),
    ])
    def test_valid_subset(self, expr, expected):
        out, review, _ = translate(expr)
        assert out == expected
        assert review is False
