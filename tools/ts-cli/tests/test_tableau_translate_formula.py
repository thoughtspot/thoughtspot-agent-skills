"""Unit tests for ts tableau translate-formula (T2) and ts tableau postprocess (T4).

Covers the pure-function invariants — no live cluster needed.
"""
import json
import os
import tempfile
import textwrap

import yaml

from ts_cli.commands.tableau_parse import (
    _translate_tableau_to_ts_functions,
    _translate_lod_expressions,
    _translate_total,
    _translate_formula_refs,
    _translate_param_refs,
    _ensure_trailing_else,
    _qualify_column_refs,
    _build_column_to_table_map,
    _load_table_map_file,
    qualify_parsed_formulas,
    _parse_summary,
    _compact_translation,
    _extract_parameters,
)
from ts_cli.commands.tableau_verify import classify
from ts_cli.commands.tableau_postprocess import (
    _norm_name,
    _norm_sql,
    load_name_mapping,
    save_name_mapping,
    fix_formula_column_refs,
    deduplicate_model_tml,
    local_cross_reference_check,
    fix_model_table_references,
    inject_model_obj_ids,
    strip_invalid_identifiers,
    _NoAliasDumper,
)


# ── translate-formula classification ─────────────────────────────────────────

def test_classify_translatable():
    tier, reason = classify("IF [Sales] > 100 THEN 'High' ELSE 'Low' END")
    assert tier == "translatable"
    assert reason == ""


def test_classify_untranslatable_lookup():
    tier, reason = classify("LOOKUP(SUM([Sales]), -1)")
    assert tier == "untranslatable"
    assert "LOOKUP" in reason.upper() or "lookup" in reason.lower() or reason != ""


def test_classify_query_time_window():
    tier, reason = classify("WINDOW_AVG(SUM([Sales]), -3, 0)")
    assert tier == "query_time"


# ── translate-formula translation ────────────────────────────────────────────

def test_translate_case_when():
    formula = "CASE WHEN [Status] = 'A' THEN 'Active' ELSE 'Inactive' END"
    result = _translate_tableau_to_ts_functions(formula)
    assert "if" in result.lower()
    assert "CASE" not in result
    assert "END" not in result


def test_translate_countd():
    result = _translate_tableau_to_ts_functions("COUNTD([Customer ID])")
    assert "unique count(" in result


def test_translate_str():
    result = _translate_tableau_to_ts_functions("STR([Amount])")
    assert "to_string(" in result


def test_translate_int():
    result = _translate_tableau_to_ts_functions("INT([Price])")
    assert "to_integer(" in result


def test_translate_formula_refs():
    ref_map = {"Calculation_123": "Profit Margin"}
    result = _translate_formula_refs("[Calculation_123] * 100", ref_map)
    assert "[formula_Profit Margin]" in result
    assert "Calculation_123" not in result


def test_translate_param_refs():
    param_map = {"Parameter_1": "Date Range"}
    result = _translate_param_refs("[Parameters].[Parameter_1]", param_map)
    assert "[Date Range]" in result
    assert "Parameter_1" not in result


def test_translate_end_preserved_in_bracket_refs():
    """END inside [Custom Date End] must not be stripped (T4 postprocess bug)."""
    formula = "IF [Send Date Filter] = 'Custom Range' THEN [Custom Date End] ELSE [Custom Date Start] END"
    result = _translate_tableau_to_ts_functions(formula)
    assert "[Custom Date End]" in result
    assert "[Custom Date Start]" in result
    assert "CASE" not in result


def test_translate_end_preserved_reporting_custom_end_date():
    formula = "[Reporting Custom End Date]"
    result = _translate_tableau_to_ts_functions(formula)
    assert result == "[Reporting Custom End Date]"


def test_translate_else_preserved_in_bracket_refs():
    """ELSE inside bracket refs like [Something Else] must not be lowercased."""
    formula = "IF [x] = 1 THEN [Something Else] ELSE 0 END"
    result = _translate_tableau_to_ts_functions(formula)
    assert "[Something Else]" in result


def test_translate_str_hash_format_stripped():
    """STR(x, '#') → to_string(x) — '#' is not a valid TS format."""
    result = _translate_tableau_to_ts_functions("STR([Amount], '#')")
    assert result == "to_string([Amount])"
    assert "'#'" not in result


def test_translate_str_date_format_preserved():
    """STR(x, 'yyyy-MM-dd') should keep the format arg."""
    result = _translate_tableau_to_ts_functions("STR([Date], 'yyyy-MM-dd')")
    assert "'yyyy-MM-dd'" in result


def test_translate_in_clause_to_curly_braces():
    """Tableau IN ('a', 'b') → ThoughtSpot in { 'a' , 'b' }."""
    formula = """[Status] IN ('Active', 'Pending')"""
    result = _translate_tableau_to_ts_functions(formula)
    assert "in {" in result
    assert "'Active'" in result
    assert "'Pending'" in result
    assert "IN (" not in result


def test_translate_not_in_not_broken():
    """NOT IN should not be mangled by the IN conversion."""
    formula = """NOT [Status] IN ('Deleted')"""
    result = _translate_tableau_to_ts_functions(formula)
    assert "in {" in result
    assert "'Deleted'" in result


def test_translate_not_in_native_syntax():
    """[col] NOT IN ('a','b') → [col] not in { 'a' , 'b' } (single operator)."""
    formula = "[Status] NOT IN ('Active', 'Pending')"
    result = _translate_tableau_to_ts_functions(formula)
    assert "not in {" in result
    assert "'Active'" in result
    assert "NOT IN (" not in result


def test_translate_cast_bool_strips_wrapper():
    """CAST(x AS BOOLEAN) → bare expression (to_bool doesn't exist in TS)."""
    result = _translate_tableau_to_ts_functions("CAST([Revenue] > 100 AS BOOLEAN)")
    assert "to_bool" not in result
    assert "[Revenue] > 100" in result


def test_translate_cast_date_col_ref_passthrough():
    """CAST([date_col] AS DATE) → [date_col] (no-op when source is already a column)."""
    result = _translate_tableau_to_ts_functions("CAST([Order Date] AS DATE)")
    assert result.strip() == "[Order Date]"
    assert "to_date" not in result


def test_translate_cast_date_string_wraps():
    """CAST('2024-01-15' AS DATE) → to_date('2024-01-15', '%Y-%m-%d')."""
    result = _translate_tableau_to_ts_functions("CAST('2024-01-15' AS DATE)")
    assert "to_date" in result
    assert "'%Y-%m-%d'" in result


# ── else injection ──────────────────────────────────────────────────────────

def test_ensure_trailing_else_noop_when_balanced():
    assert _ensure_trailing_else("if (x) then 1 else 0") == "if (x) then 1 else 0"


def test_ensure_trailing_else_adds_null():
    assert _ensure_trailing_else("if (x) then 1") == "if (x) then 1 else null"


def test_ensure_trailing_else_chained_if():
    f = "if (a) then 1 else if (b) then 2"
    assert _ensure_trailing_else(f) == f + " else null"


def test_ensure_trailing_else_ignores_brackets():
    """'if' inside [Something if] should not count."""
    f = "[Something if] + 1"
    assert _ensure_trailing_else(f) == f


def test_translate_if_then_end_no_else():
    """IF/THEN/END without ELSE should get 'else null' appended."""
    result = _translate_tableau_to_ts_functions("IF [Sales] > 100 THEN 'High' END")
    assert "else null" in result


def test_translate_if_elseif_end_no_final_else():
    """IF/ELSEIF/END chain without final ELSE should get 'else null'."""
    result = _translate_tableau_to_ts_functions(
        "IF [x] = 1 THEN 'a' ELSEIF [x] = 2 THEN 'b' END"
    )
    assert "else null" in result
    assert result.rstrip().endswith("else null")


def test_translate_case_when_no_else():
    """CASE WHEN without ELSE should get 'else null'."""
    result = _translate_tableau_to_ts_functions(
        "CASE WHEN [Status] = 'A' THEN 'Active' WHEN [Status] = 'B' THEN 'Inactive' END"
    )
    assert "else null" in result


def test_translate_case_when_with_else_no_extra_null():
    """CASE WHEN with ELSE should NOT get an extra 'else null'."""
    result = _translate_tableau_to_ts_functions(
        "CASE WHEN [Status] = 'A' THEN 'Active' ELSE 'Unknown' END"
    )
    assert "else null" not in result
    assert "'Unknown'" in result


# ── to_date 2-arg enforcement ──────────────────────────────────────────────

def test_translate_bare_to_date_gets_format():
    """to_date('2024-08-18') should become to_date('2024-08-18', 'yyyy-MM-dd')."""
    result = _translate_tableau_to_ts_functions("to_date('2024-08-18')")
    assert "'yyyy-MM-dd'" in result


def test_translate_to_date_already_2_args_untouched():
    """to_date('2024-08-18', 'yyyy-MM-dd') should not be modified."""
    result = _translate_tableau_to_ts_functions("to_date('2024-08-18', 'yyyy-MM-dd')")
    assert result.count("yyyy-MM-dd") == 1


def test_translate_to_date_with_expression():
    """to_date(concat(...)) should get format arg added."""
    result = _translate_tableau_to_ts_functions("to_date(concat([Year], '-01-01'))")
    assert "'yyyy-MM-dd'" in result


# ── Tier 1: simple renames ───────────────────────────────────────────────────

def test_translate_elseif():
    formula = "IF [x] = 1 THEN 'a' ELSEIF [x] = 2 THEN 'b' ELSE 'c' END"
    result = _translate_tableau_to_ts_functions(formula)
    assert "ELSEIF" not in result
    assert "else if" in result


def test_translate_month():
    result = _translate_tableau_to_ts_functions("MONTH([Order Date])")
    assert "month_number(" in result
    assert "MONTH" not in result


def test_translate_zn():
    result = _translate_tableau_to_ts_functions("ZN([Discount])")
    assert "ifnull" in result
    assert ", 0 )" in result
    assert "ZN" not in result


def test_translate_len():
    result = _translate_tableau_to_ts_functions("LEN([Name])")
    assert "strlen(" in result


def test_translate_find():
    result = _translate_tableau_to_ts_functions("FIND([Name], 'a')")
    assert "strpos(" in result


def test_translate_ceiling():
    result = _translate_tableau_to_ts_functions("CEILING([Revenue])")
    assert "ceil(" in result


def test_translate_log():
    result = _translate_tableau_to_ts_functions("LOG([Revenue])")
    assert "log10(" in result


def test_translate_power():
    result = _translate_tableau_to_ts_functions("POWER([Revenue], 3)")
    assert "pow(" in result


def test_translate_stdev():
    result = _translate_tableau_to_ts_functions("STDEV([Revenue])")
    assert "stddev(" in result


def test_translate_square():
    result = _translate_tableau_to_ts_functions("SQUARE([Tax])")
    assert "pow" in result
    assert ", 2 )" in result


def test_translate_iif():
    result = _translate_tableau_to_ts_functions("IIF([Revenue] > 1000, [Revenue], 0)")
    assert "if (" in result
    assert ") then" in result
    assert "else 0" in result
    assert "IIF" not in result


def test_translate_attr():
    result = _translate_tableau_to_ts_functions("ATTR([Region])")
    assert result.strip() == "[Region]"
    assert "ATTR" not in result


# ── Tier 2: date function unit dispatch ──────────────────────────────────────

def test_translate_datediff_day():
    result = _translate_tableau_to_ts_functions("DATEDIFF('day', [Start], [End])")
    assert "diff_days" in result
    assert "[Start]" in result
    assert "[End]" in result
    assert "DATEDIFF" not in result


def test_translate_datediff_month():
    result = _translate_tableau_to_ts_functions("DATEDIFF('month', [Start], [End])")
    assert "diff_months" in result


def test_translate_datediff_quarter():
    result = _translate_tableau_to_ts_functions("DATEDIFF('quarter', [Start], [End])")
    assert "diff_quarters" in result


def test_translate_datediff_year():
    result = _translate_tableau_to_ts_functions("DATEDIFF('year', [Start], [End])")
    assert "diff_years" in result


def test_translate_datediff_week():
    result = _translate_tableau_to_ts_functions("DATEDIFF('week', [Start], [End])")
    assert "diff_days" in result
    assert "/ 7" in result


def test_translate_datetrunc_month():
    result = _translate_tableau_to_ts_functions("DATETRUNC('month', [Order Date])")
    assert "start_of_month" in result
    assert "DATETRUNC" not in result


def test_translate_datetrunc_quarter():
    result = _translate_tableau_to_ts_functions("DATETRUNC('quarter', [Order Date])")
    assert "start_of_quarter" in result


def test_translate_datetrunc_week():
    result = _translate_tableau_to_ts_functions("DATETRUNC('week', [Order Date])")
    assert "start_of_week" in result


def test_translate_datetrunc_year():
    result = _translate_tableau_to_ts_functions("DATETRUNC('year', [Order Date])")
    assert "start_of_year" in result


def test_translate_datetrunc_day():
    result = _translate_tableau_to_ts_functions("DATETRUNC('day', [Order Date])")
    assert "date ( [Order Date] )" in result


def test_translate_dateadd_day():
    result = _translate_tableau_to_ts_functions("DATEADD('day', 7, [Order Date])")
    assert "add_days" in result
    assert "[Order Date]" in result
    assert "7" in result
    assert "DATEADD" not in result


def test_translate_dateadd_month():
    result = _translate_tableau_to_ts_functions("DATEADD('month', -6, [Order Date])")
    assert "add_months" in result
    assert "-6" in result


def test_translate_dateadd_year():
    result = _translate_tableau_to_ts_functions("DATEADD('year', 1, [Order Date])")
    assert "add_years" in result


def test_translate_dateadd_quarter():
    """DATEADD quarter falls back to add_months(d, n*3)."""
    result = _translate_tableau_to_ts_functions("DATEADD('quarter', 2, [Order Date])")
    assert "add_months" in result
    assert "* 3" in result


def test_translate_dateadd_week():
    result = _translate_tableau_to_ts_functions("DATEADD('week', 2, [Order Date])")
    assert "add_weeks" in result


def test_translate_dateadd_arg_order():
    """Tableau is (unit, n, d), ThoughtSpot is (d, n) — args must flip."""
    result = _translate_tableau_to_ts_functions("DATEADD('day', 30, [Ship Date])")
    ship_pos = result.index("[Ship Date]")
    thirty_pos = result.index("30")
    assert ship_pos < thirty_pos, "date arg must come before offset arg"


def test_translate_datepart_month():
    result = _translate_tableau_to_ts_functions("DATEPART('month', [Order Date])")
    assert "month_number" in result
    assert "DATEPART" not in result


def test_translate_datepart_year():
    result = _translate_tableau_to_ts_functions("DATEPART('year', [Order Date])")
    assert "year ( [Order Date] )" in result


def test_translate_datepart_weekday():
    result = _translate_tableau_to_ts_functions("DATEPART('weekday', [Order Date])")
    assert "day_of_week" in result


def test_translate_datepart_quarter():
    result = _translate_tableau_to_ts_functions("DATEPART('quarter', [Order Date])")
    assert "quarter_number" in result


def test_translate_datepart_dayofyear():
    result = _translate_tableau_to_ts_functions("DATEPART('dayofyear', [Order Date])")
    assert "day_number_of_year" in result


def test_translate_datepart_hour():
    result = _translate_tableau_to_ts_functions("DATEPART('hour', [Order Date])")
    assert "hour_of_day" in result


def test_translate_datename_month():
    result = _translate_tableau_to_ts_functions("DATENAME('month', [Order Date])")
    assert "month_number" in result


def test_translate_nested_date_functions():
    """Nested: DATEADD('month', 1, DATETRUNC('month', [Date]))"""
    formula = "DATEADD('month', 1, DATETRUNC('month', [Date]))"
    result = _translate_tableau_to_ts_functions(formula)
    assert "add_months" in result
    assert "start_of_month" in result
    assert "DATEADD" not in result
    assert "DATETRUNC" not in result


def test_translate_date_string_literal():
    """DATE('2024-08-18') -> to_date with 2 args."""
    result = _translate_tableau_to_ts_functions("DATE('2024-08-18')")
    assert "to_date" in result
    assert "'2024-08-18'" in result
    assert "'yyyy-MM-dd'" in result


def test_translate_date_column_ref():
    """DATE([col]) on a bare column ref -> pass through unchanged."""
    result = _translate_tableau_to_ts_functions("DATE([My Column])")
    assert result.strip() == "[My Column]"


def test_translate_date_does_not_match_lowercase():
    """Lowercase 'date (' from DATETRUNC('day') must not be re-matched."""
    result = _translate_tableau_to_ts_functions("DATETRUNC('day', [Order Date])")
    assert "date ( [Order Date] )" in result
    assert "to_date" not in result


def test_translate_dateparse():
    """DATEPARSE("yyyy-MM", [col]) -> to_date([col], 'yyyy-MM')."""
    result = _translate_tableau_to_ts_functions('DATEPARSE("yyyy-MM", [RUN_DATE])')
    assert "to_date" in result
    assert "[RUN_DATE]" in result
    assert "'yyyy-MM'" in result
    assert "DATEPARSE" not in result


def test_translate_dateparse_single_quoted():
    """DATEPARSE with single-quoted format."""
    result = _translate_tableau_to_ts_functions("DATEPARSE('yyyy-MM-dd', [Date Col])")
    assert "to_date" in result
    assert "'yyyy-MM-dd'" in result
    assert "[Date Col]" in result


def test_translate_nested_dateparse_in_lod():
    """DATEPARSE inside an LOD/MAX — the real formula from Customer Segments."""
    formula = "STR(DATEADD('month', -1, { MAX(DATEPARSE(\"yyyy-MM\", [SEGMENT_RUN_DATE])) }))"
    result = _translate_tableau_to_ts_functions(formula)
    assert "to_date" in result
    assert "'yyyy-MM'" in result
    assert "DATEPARSE" not in result
    assert "add_months" in result


# ── postprocess helpers ──────────────────────────────────────────────────────

def test_norm_name():
    assert _norm_name("Order Date") == "ORDERDATE"
    assert _norm_name("order_date") == "ORDERDATE"
    assert _norm_name("ORDER-DATE") == "ORDERDATE"


def test_norm_sql():
    assert _norm_sql("SELECT  *\n  FROM  T -- comment") == "select * from t"
    assert _norm_sql("SELECT /* block */ 1") == "select 1"


def test_name_mapping_round_trip():
    with tempfile.TemporaryDirectory() as tmpdir:
        mapping = {"formulas": {"Sales Ratio": "Sales Ratio"}, "columns": {}, "parameters": {}}
        save_name_mapping(tmpdir, mapping)
        loaded = load_name_mapping(tmpdir)
        assert loaded["formulas"]["Sales Ratio"] == "Sales Ratio"


def test_name_mapping_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        loaded = load_name_mapping(tmpdir)
        assert loaded == {"formulas": {}, "columns": {}, "parameters": {}}


# ── postprocess: fix_formula_column_refs ─────────────────────────────────────

def test_fix_formula_column_refs_is_noop_preserving_qualification():
    """fix_formula_column_refs deliberately preserves TABLE::COL refs —
    qualified refs are always safe and avoid ambiguity error 14516."""
    with tempfile.TemporaryDirectory() as tmpdir:
        model_tml = {
            "model": {
                "name": "Test Model",
                "formulas": [
                    {"id": "formula_Margin", "name": "Margin", "expr": "[Orders::Revenue] - [Orders::Cost]"},
                ],
                "columns": [
                    {"column_id": "Orders::Revenue", "name": "Revenue"},
                    {"column_id": "Orders::Cost", "name": "Cost"},
                ],
                "model_tables": [{"name": "Orders"}],
            }
        }
        path = os.path.join(tmpdir, "test.model.tml")
        with open(path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)
        before = open(path).read()

        from pathlib import Path
        changed = fix_formula_column_refs(Path(path))
        assert not changed
        assert open(path).read() == before
        assert "Orders::Revenue" in before


# ── postprocess: deduplicate_model_tml ───────────────────────────────────────

def test_deduplicate_removes_duplicate_formula_ids():
    with tempfile.TemporaryDirectory() as tmpdir:
        model_tml = {
            "model": {
                "name": "Test",
                "formulas": [
                    {"id": "formula_A", "name": "A", "expr": "1+1"},
                    {"id": "formula_A", "name": "A", "expr": "1+1"},
                    {"id": "formula_B", "name": "B", "expr": "2+2"},
                ],
                "columns": [
                    {"name": "A", "formula_id": "formula_A"},
                    {"name": "A", "formula_id": "formula_A"},
                    {"name": "B", "formula_id": "formula_B"},
                ],
            }
        }
        path = os.path.join(tmpdir, "test.model.tml")
        with open(path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        changed = deduplicate_model_tml(Path(path))
        assert changed

        with open(path) as f:
            result = yaml.safe_load(f)
        assert len(result["model"]["formulas"]) == 2
        assert len(result["model"]["columns"]) == 2


def test_deduplicate_removes_empty_model_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        model_tml = {
            "model": {
                "name": "Test",
                "model_tables": [
                    {"name": "Orders"},
                    {"name": ""},
                    {"name": "Orders"},
                    {"name": "Products"},
                ],
            }
        }
        path = os.path.join(tmpdir, "test.model.tml")
        with open(path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        changed = deduplicate_model_tml(Path(path))
        assert changed

        with open(path) as f:
            result = yaml.safe_load(f)
        names = [t["name"] for t in result["model"]["model_tables"]]
        assert names == ["Orders", "Products"]


# ── postprocess: local_cross_reference_check ─────────────────────────────────

def test_cross_ref_check_catches_missing_table():
    with tempfile.TemporaryDirectory() as tmpdir:
        table_tml = {"table": {"name": "Orders", "columns": [{"name": "id"}]}}
        model_tml = {
            "model": {
                "name": "TestModel",
                "model_tables": [{"name": "Orders"}, {"name": "MissingTable"}],
                "columns": [],
            }
        }

        table_path = os.path.join(tmpdir, "orders.table.tml")
        model_path = os.path.join(tmpdir, "test.model.tml")
        with open(table_path, "w") as f:
            yaml.dump(table_tml, f, Dumper=_NoAliasDumper)
        with open(model_path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        errors = local_cross_reference_check([Path(table_path), Path(model_path)])
        assert len(errors) == 1
        assert "MissingTable" in errors[0]


def test_cross_ref_check_passes_when_valid():
    with tempfile.TemporaryDirectory() as tmpdir:
        table_tml = {"table": {"name": "Orders", "columns": [{"name": "id"}, {"name": "amount"}]}}
        model_tml = {
            "model": {
                "name": "TestModel",
                "model_tables": [{"name": "Orders"}],
                "columns": [{"name": "id", "column_id": "Orders::id"}],
            }
        }

        table_path = os.path.join(tmpdir, "orders.table.tml")
        model_path = os.path.join(tmpdir, "test.model.tml")
        with open(table_path, "w") as f:
            yaml.dump(table_tml, f, Dumper=_NoAliasDumper)
        with open(model_path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        errors = local_cross_reference_check([Path(table_path), Path(model_path)])
        assert errors == []


# ── postprocess: fix_model_table_references ──────────────────────────────────

def test_fix_model_table_references_aligns_names():
    with tempfile.TemporaryDirectory() as tmpdir:
        table_tml = {"table": {"name": "Customer Orders", "columns": [{"name": "order_id"}]}}
        model_tml = {
            "model": {
                "name": "TestModel",
                "model_tables": [{"name": "CUSTOMERORDERS"}],
                "columns": [{"name": "oid", "column_id": "CUSTOMERORDERS::ORDERID"}],
            }
        }

        table_path = os.path.join(tmpdir, "orders.table.tml")
        model_path = os.path.join(tmpdir, "test.model.tml")
        with open(table_path, "w") as f:
            yaml.dump(table_tml, f, Dumper=_NoAliasDumper)
        with open(model_path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        changed = fix_model_table_references(Path(model_path), tmpdir)
        assert changed

        with open(model_path) as f:
            result = yaml.safe_load(f)
        assert result["model"]["model_tables"][0]["name"] == "Customer Orders"
        assert result["model"]["columns"][0]["column_id"] == "Customer Orders::order_id"


# ── postprocess: inject_model_obj_ids ────────────────────────────────────────

def test_inject_obj_ids_adds_guid_and_table_refs():
    with tempfile.TemporaryDirectory() as tmpdir:
        table_tml = {"obj_id": "orders-abc123", "table": {"name": "Orders", "columns": []}}
        model_tml = {
            "model": {
                "name": "TestModel",
                "model_tables": [{"name": "Orders"}],
            }
        }

        table_path = os.path.join(tmpdir, "orders.table.tml")
        model_path = os.path.join(tmpdir, "test.model.tml")
        with open(table_path, "w") as f:
            yaml.dump(table_tml, f, Dumper=_NoAliasDumper)
        with open(model_path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        changed = inject_model_obj_ids(Path(model_path), tmpdir)
        assert changed

        with open(model_path) as f:
            result = yaml.safe_load(f)
        assert "guid" in result
        assert result["model"]["model_tables"][0]["obj_id"] == "orders-abc123"


# ── postprocess: strip_invalid_identifiers ─────────────────────────────────

def test_strip_removes_root_guid():
    with tempfile.TemporaryDirectory() as tmpdir:
        model_tml = {
            "guid": "abc-123",
            "model": {
                "name": "Test",
                "model_tables": [{"name": "Orders"}],
            },
        }
        path = os.path.join(tmpdir, "test.model.tml")
        with open(path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        changed = strip_invalid_identifiers(Path(path))
        assert changed

        with open(path) as f:
            result = yaml.safe_load(f)
        assert "guid" not in result


def test_strip_removes_fqn_from_model_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        model_tml = {
            "model": {
                "name": "Test",
                "model_tables": [
                    {"name": "Orders", "fqn": "dead-beef-1234"},
                    {"name": "Products"},
                ],
            },
        }
        path = os.path.join(tmpdir, "test.model.tml")
        with open(path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        changed = strip_invalid_identifiers(Path(path))
        assert changed

        with open(path) as f:
            result = yaml.safe_load(f)
        for tbl in result["model"]["model_tables"]:
            assert "fqn" not in tbl


def test_strip_removes_nested_guid():
    """guid inside model: block should also be stripped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        model_tml = {
            "model": {
                "guid": "nested-bad",
                "name": "Test",
                "model_tables": [{"name": "Orders"}],
            },
        }
        path = os.path.join(tmpdir, "test.model.tml")
        with open(path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        changed = strip_invalid_identifiers(Path(path))
        assert changed

        with open(path) as f:
            result = yaml.safe_load(f)
        assert "guid" not in result.get("model", {})


def test_strip_noop_when_clean():
    """No changes when TML has no guid or fqn issues."""
    with tempfile.TemporaryDirectory() as tmpdir:
        model_tml = {
            "model": {
                "name": "Test",
                "model_tables": [{"name": "Orders"}],
            },
        }
        path = os.path.join(tmpdir, "test.model.tml")
        with open(path, "w") as f:
            yaml.dump(model_tml, f, Dumper=_NoAliasDumper)

        from pathlib import Path
        changed = strip_invalid_identifiers(Path(path))
        assert not changed


# ── qualify column refs ────────────────────────────────────────────────────────

class TestQualifyColumnRefs:

    def test_bare_column_gets_qualified(self):
        formula = "diff_days ( [Order Date] , [Commit Date] )"
        col_to_table = {"Order Date": "LINEORDER", "Commit Date": "LINEORDER"}
        table_map = {"LINEORDER": "LINEORDER_1"}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert result == "diff_days ( [LINEORDER_1::Order Date] , [LINEORDER_1::Commit Date] )"
        assert unresolved == []

    def test_formula_ref_left_untouched(self):
        formula = "[formula_Profit] / [Revenue]"
        col_to_table = {"Revenue": "LINEORDER"}
        table_map = {"LINEORDER": "LINEORDER_1"}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert "[formula_Profit]" in result
        assert "[LINEORDER_1::Revenue]" in result
        assert unresolved == []

    def test_already_qualified_left_untouched(self):
        formula = "[LINEORDER_1::Revenue] + [LINEORDER_1::Tax]"
        col_to_table = {}
        table_map = {}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert result == formula
        assert unresolved == []

    def test_unresolved_column_reported(self):
        formula = "sum ( [Unknown Column] )"
        col_to_table = {}
        table_map = {}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert "[Unknown Column]" in result
        assert "Unknown Column" in unresolved

    def test_mixed_tables(self):
        formula = "diff_days ( [Order Date] , [Ship Date] )"
        col_to_table = {"Order Date": "LINEORDER", "Ship Date": "SHIPPING"}
        table_map = {"LINEORDER": "LINEORDER_1", "SHIPPING": "SHIPPING_1"}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert "[LINEORDER_1::Order Date]" in result
        assert "[SHIPPING_1::Ship Date]" in result
        assert unresolved == []

    def test_formula_and_table_refs_together(self):
        formula = "[formula_Margin] * [Revenue] + [formula_Tax_Rate]"
        col_to_table = {"Revenue": "LINEORDER"}
        table_map = {"LINEORDER": "SALES"}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert "[formula_Margin]" in result
        assert "[formula_Tax_Rate]" in result
        assert "[SALES::Revenue]" in result
        assert unresolved == []

    def test_empty_formula(self):
        result, unresolved = _qualify_column_refs("", {}, {})
        assert result == ""
        assert unresolved == []

    def test_no_bracket_refs(self):
        formula = "1 + 2 * 3"
        result, unresolved = _qualify_column_refs(formula, {}, {})
        assert result == formula
        assert unresolved == []

    def test_table_map_partial_match(self):
        """column_mappings may use relation_name like 'Extract.LINEORDER'
        while table_map has just 'LINEORDER'."""
        formula = "sum ( [Revenue] )"
        col_to_table = {"Revenue": "Extract.LINEORDER"}
        table_map = {"LINEORDER": "LINEORDER_1"}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert "[LINEORDER_1::Revenue]" in result
        assert unresolved == []

    def test_multiple_unresolved(self):
        formula = "[ColA] + [ColB] + [ColC]"
        col_to_table = {"ColA": "T1"}
        table_map = {"T1": "TABLE_1"}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert "[TABLE_1::ColA]" in result
        assert "ColB" in unresolved
        assert "ColC" in unresolved

    def test_string_literals_not_affected(self):
        formula = "if ( [Region] = 'Asia' ) then 'Found' else 'Not Found'"
        col_to_table = {"Region": "CUSTOMER"}
        table_map = {"CUSTOMER": "CUSTOMER_1"}
        result, unresolved = _qualify_column_refs(formula, col_to_table, table_map)
        assert "[CUSTOMER_1::Region]" in result
        assert "'Asia'" in result
        assert "'Found'" in result
        assert unresolved == []


class TestBuildColumnToTableMap:

    def test_from_physical_columns(self):
        ds = {
            "physical_columns": [
                {"name": "ORDER_DATE", "local_name": "Order Date", "parent_table": "LINEORDER"},
                {"name": "REVENUE", "local_name": "Revenue", "parent_table": "LINEORDER"},
            ],
            "column_roles": {
                "Order Date": {"caption": "Order Date"},
                "Revenue": {"caption": "Revenue"},
            },
            "column_mappings": {},
            "tables": [],
        }
        result = _build_column_to_table_map(ds)
        assert result.get("Order Date") == "LINEORDER"
        assert result.get("Revenue") == "LINEORDER"

    def test_from_column_mappings(self):
        ds = {
            "physical_columns": [],
            "column_roles": {
                "usr.Region": {"caption": "Region"},
            },
            "column_mappings": {
                "usr.Region": "[CUSTOMER].[REGION]",
            },
            "tables": [],
        }
        result = _build_column_to_table_map(ds)
        assert result.get("Region") == "CUSTOMER"

    def test_caption_resolved_via_roles(self):
        ds = {
            "physical_columns": [
                {"name": "CUST_REGION", "local_name": "internal_col", "parent_table": "CUSTOMER"},
            ],
            "column_roles": {
                "internal_col": {"caption": "Customer Region"},
            },
            "column_mappings": {},
            "tables": [],
        }
        result = _build_column_to_table_map(ds)
        assert result.get("Customer Region") == "CUSTOMER"


class TestQualifyParsedFormulas:

    def test_end_to_end(self):
        parsed = {
            "datasources": [
                {
                    "is_parameters": False,
                    "physical_columns": [
                        {"name": "ORDER_DATE", "local_name": "Order Date", "parent_table": "LINEORDER"},
                        {"name": "REVENUE", "local_name": "Revenue", "parent_table": "LINEORDER"},
                        {"name": "REGION", "local_name": "Region", "parent_table": "CUSTOMER"},
                    ],
                    "column_roles": {
                        "Order Date": {"caption": "Order Date"},
                        "Revenue": {"caption": "Revenue"},
                        "Region": {"caption": "Region"},
                    },
                    "column_mappings": {},
                    "tables": [],
                    "calculated_fields": [
                        {
                            "caption": "Days Old",
                            "level": 0,
                            "formula": "diff_days ( [Order Date] , today() )",
                            "formula_raw": "DATEDIFF('day', [Order Date], TODAY())",
                        },
                        {
                            "caption": "Regional Revenue",
                            "level": 0,
                            "formula": "if ( [Region] = 'Asia' ) then [Revenue] else 0",
                            "formula_raw": "IIF([Region] = 'Asia', [Revenue], 0)",
                        },
                    ],
                }
            ],
        }
        table_map = {"LINEORDER": "LINEORDER_1", "CUSTOMER": "CUSTOMER_1"}
        result = qualify_parsed_formulas(parsed, table_map)

        assert result["summary"]["total"] == 2
        assert result["summary"]["fully_resolved"] == 2
        assert result["summary"]["partially_resolved"] == 0

        f0 = result["formulas"][0]
        assert f0["caption"] == "Days Old"
        assert "[LINEORDER_1::Order Date]" in f0["qualified"]
        assert f0["fully_resolved"] is True

        f1 = result["formulas"][1]
        assert "[CUSTOMER_1::Region]" in f1["qualified"]
        assert "[LINEORDER_1::Revenue]" in f1["qualified"]

    def test_skips_parameter_datasources(self):
        parsed = {
            "datasources": [
                {
                    "is_parameters": True,
                    "calculated_fields": [
                        {"caption": "Param1", "formula": "[X]", "formula_raw": "[X]", "level": 0}
                    ],
                    "physical_columns": [],
                    "column_roles": {},
                    "column_mappings": {},
                    "tables": [],
                }
            ],
        }
        result = qualify_parsed_formulas(parsed, {})
        assert result["summary"]["total"] == 0

    def test_calc_field_refs_preserved(self):
        parsed = {
            "datasources": [
                {
                    "is_parameters": False,
                    "physical_columns": [
                        {"name": "REVENUE", "local_name": "Revenue", "parent_table": "LINEORDER"},
                    ],
                    "column_roles": {
                        "Revenue": {"caption": "Revenue"},
                    },
                    "column_mappings": {},
                    "tables": [],
                    "calculated_fields": [
                        {
                            "caption": "Margin",
                            "level": 1,
                            "formula": "[formula_Profit] / [Revenue]",
                            "formula_raw": "[Calculation_1] / [Revenue]",
                        },
                    ],
                }
            ],
        }
        table_map = {"LINEORDER": "LINEORDER_1"}
        result = qualify_parsed_formulas(parsed, table_map)
        f = result["formulas"][0]
        assert "[formula_Profit]" in f["qualified"]
        assert "[LINEORDER_1::Revenue]" in f["qualified"]
        assert f["fully_resolved"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Compact-output builders (--out modes): must preserve cross-refs, param refs,
# and multi-level dependency order.
# ─────────────────────────────────────────────────────────────────────────────

def _sample_parsed():
    """Parsed shape with a parameter datasource + multi-level, cross-referencing formulas."""
    return {
        "datasources": [
            {
                "name": "Sales",
                "type": "live",
                "tables": [{"name": "ORDERS"}],
                "custom_sql_sources": [],
                "joins": [],
                "calculated_fields": [
                    {"caption": "Base", "level": 0},
                    {"caption": "Derived", "level": 1},
                ],
            },
            {
                "name": "Parameters",
                "is_parameters": True,
                "parameters": [
                    {"caption": "Threshold", "internal_name": "p1",
                     "datatype": "integer", "domain_type": "range"},
                ],
            },
        ],
        "dashboards": [{"name": "Overview"}],
        "worksheets": [{"name": "S1"}],
    }


def test_parse_summary_is_compact_and_complete():
    parsed = _sample_parsed()
    parsed["_summary"] = None  # ignored by summary builder
    summary = _parse_summary(parsed, "/tmp/parsed.json")
    assert summary["out_file"] == "/tmp/parsed.json"
    # counts exclude the parameters datasource from data-datasource totals
    assert summary["counts"]["datasources"] == 1
    assert summary["counts"]["calculated_fields"] == 2
    assert summary["counts"]["parameters"] == 1
    assert summary["dashboards"] == ["Overview"]
    # per-datasource breakdown only lists the data datasource
    assert [d["name"] for d in summary["datasources"]] == ["Sales"]


def test_extract_parameters_flattens_param_datasource():
    params = _extract_parameters(_sample_parsed())
    assert len(params) == 1
    assert params[0]["caption"] == "Threshold"
    assert params[0]["datatype"] == "integer"


def test_compact_translation_keeps_judgment_full_and_reference_for_all():
    parsed = _sample_parsed()
    output = {
        "formulas": [
            {"caption": "Base", "level": 0, "original": "SUM([x])",
             "translated": "sum ( [x] )", "tier": "translatable",
             "deterministic": True, "reason": ""},
            {"caption": "Derived", "level": 1,
             "original": "{FIXED [r] : AVG([x])}",
             "translated": "", "tier": "lod", "deterministic": False,
             "reason": "LOD — needs judgment"},
        ],
        "summary": {"total": 2, "translatable": 1, "query_time": 0, "untranslatable": 0},
    }
    compact = _compact_translation(output, parsed, "/tmp/translated.json")

    # judgment carries ONLY the non-deterministic formula, in full (with reason)
    assert len(compact["judgment"]) == 1
    assert compact["judgment"][0]["caption"] == "Derived"
    assert compact["judgment"][0]["reason"] == "LOD — needs judgment"
    assert "original" in compact["judgment"][0]

    # reference table covers EVERY formula (cross-ref resolution)
    assert len(compact["reference"]) == 2
    ref = {r["caption"]: r for r in compact["reference"]}
    assert ref["Base"]["translated"] == "sum ( [x] )"
    assert set(ref) == {"Base", "Derived"}

    # parameter refs preserved
    assert [p["caption"] for p in compact["parameters"]] == ["Threshold"]

    # summary augmented with judgment count + out_file
    assert compact["summary"]["judgment"] == 1
    assert compact["summary"]["out_file"] == "/tmp/translated.json"


def test_compact_translation_reference_is_level_ordered():
    parsed = _sample_parsed()
    output = {
        "formulas": [
            {"caption": "L2b", "level": 2, "translated": "b", "tier": "translatable", "deterministic": True},
            {"caption": "L0", "level": 0, "translated": "z", "tier": "translatable", "deterministic": True},
            {"caption": "L2a", "level": 2, "translated": "a", "tier": "translatable", "deterministic": True},
            {"caption": "L1", "level": 1, "translated": "y", "tier": "translatable", "deterministic": True},
        ],
        "summary": {"total": 4},
    }
    ref = _compact_translation(output, parsed, "/tmp/t.json")["reference"]
    # ascending by (level, caption) so multi-level dependency order holds
    assert [(r["level"], r["caption"]) for r in ref] == [
        (0, "L0"), (1, "L1"), (2, "L2a"), (2, "L2b"),
    ]


# ---------------------------------------------------------------------------
# LOD expression translation (_translate_lod_expressions)
# ---------------------------------------------------------------------------

def test_lod_fixed_with_dims():
    assert _translate_lod_expressions('{FIXED [Region] : SUM([Sales])}') == \
        'group_aggregate(SUM([Sales]), {[Region]}, {})'


def test_lod_fixed_multi_dims():
    assert _translate_lod_expressions('{FIXED [A], [B] : AVG([C])}') == \
        'group_aggregate(AVG([C]), {[A], [B]}, {})'


def test_lod_fixed_no_dims():
    assert _translate_lod_expressions('{ FIXED : MAX([X]) }') == \
        'group_aggregate(MAX([X]), {}, {})'


def test_lod_bare_aggregate():
    assert _translate_lod_expressions('{MAX([X])}') == \
        'group_aggregate(MAX([X]), {}, {})'


def test_lod_bare_countd():
    assert _translate_lod_expressions('{COUNTD([ID])}') == \
        'group_aggregate(COUNTD([ID]), {}, {})'


def test_lod_include():
    assert _translate_lod_expressions('{INCLUDE [D] : SUM([X])}') == \
        'group_aggregate(SUM([X]), query_groups() + {[D]}, query_filters())'


def test_lod_exclude():
    assert _translate_lod_expressions('{EXCLUDE [D] : SUM([X])}') == \
        'group_aggregate(SUM([X]), query_groups() - {[D]}, query_filters())'


def test_lod_nested():
    result = _translate_lod_expressions('{FIXED [A] : {FIXED : SUM([X])}}')
    assert 'group_aggregate(group_aggregate(SUM([X]), {}, {}), {[A]}, {})' == result


def test_lod_with_conditional():
    inp = '{FIXED : SUM(IF [X] > 0 THEN [Y] ELSE 0 END)}'
    result = _translate_lod_expressions(inp)
    assert result == 'group_aggregate(SUM(IF [X] > 0 THEN [Y] ELSE 0 END), {}, {})'


def test_lod_not_matched_set_literal():
    assert _translate_lod_expressions('{1, 2, 3}') == '{1, 2, 3}'


def test_lod_no_braces_passthrough():
    assert _translate_lod_expressions('SUM([Sales])') == 'SUM([Sales])'


def test_lod_empty_string():
    assert _translate_lod_expressions('') == ''


def test_lod_none():
    assert _translate_lod_expressions(None) is None


def test_lod_case_insensitive():
    assert _translate_lod_expressions('{ fixed [R] : sum([S]) }') == \
        'group_aggregate(sum([S]), {[R]}, {})'


def test_lod_in_larger_expression():
    inp = 'SUM([A]) / {FIXED : SUM([A])}'
    result = _translate_lod_expressions(inp)
    assert result == 'SUM([A]) / group_aggregate(SUM([A]), {}, {})'


# ---------------------------------------------------------------------------
# TOTAL translation (_translate_total)
# ---------------------------------------------------------------------------

def test_total_basic():
    assert _translate_total('TOTAL(SUM([X]))') == \
        'group_aggregate(SUM([X]), {}, query_filters())'


def test_total_in_division():
    result = _translate_total('SUM([X]) / TOTAL(SUM([X]))')
    assert result == 'SUM([X]) / group_aggregate(SUM([X]), {}, query_filters())'


def test_total_case_insensitive():
    assert _translate_total('Total(AVG([Y]))') == \
        'group_aggregate(AVG([Y]), {}, query_filters())'


def test_total_no_match():
    assert _translate_total('SUM([X])') == 'SUM([X])'


def test_total_empty():
    assert _translate_total('') == ''


def test_total_none():
    assert _translate_total(None) is None


def test_total_not_preceded_by_alpha():
    assert _translate_total('xTOTAL(SUM([X]))') == 'xTOTAL(SUM([X]))'


# ── ISNULL ─────────────────────────────────────────────────────────────

def test_isnull_simple():
    assert _translate_tableau_to_ts_functions('ISNULL([col])') == 'isnull([col])'


def test_isnull_case_insensitive():
    assert _translate_tableau_to_ts_functions('IsNull([col])') == 'isnull([col])'


# ── CONTAINS ───────────────────────────────────────────────────────────

def test_contains_simple():
    assert _translate_tableau_to_ts_functions('CONTAINS([Name], "test")') == "contains([Name], 'test')"


def test_contains_case_insensitive():
    assert _translate_tableau_to_ts_functions('Contains([X], "abc")') == "contains([X], 'abc')"


# ── LEFT → substr with 0-based index ──────────────────────────────────

def test_left_to_substr():
    assert _translate_tableau_to_ts_functions('LEFT([Name], 3)') == 'substr ( [Name] , 0 , 3 )'


def test_left_case_insensitive():
    assert _translate_tableau_to_ts_functions('Left([X], 5)') == 'substr ( [X] , 0 , 5 )'


# ── RIGHT → substr(s, strlen(s)-n, n) ────────────────────────────────

def test_right_to_substr():
    assert _translate_tableau_to_ts_functions('RIGHT([Name], 2)') == 'substr ( [Name] , strlen ( [Name] ) - 2 , 2 )'


# ── MID → substr(s, start-1, len) ────────────────────────────────────

def test_mid_to_substr():
    assert _translate_tableau_to_ts_functions('MID([Name], 2, 4)') == 'substr ( [Name] , 2 - 1 , 4 )'


# ── UPPER → sql_string_op passthrough ─────────────────────────────────

def test_upper_passthrough():
    result = _translate_tableau_to_ts_functions('UPPER([Name])')
    assert 'sql_string_op' in result
    assert 'upper' in result
    assert '[Name]' in result


# ── LOWER → sql_string_op passthrough ─────────────────────────────────

def test_lower_passthrough():
    result = _translate_tableau_to_ts_functions('LOWER([Name])')
    assert 'sql_string_op' in result
    assert 'lower' in result
    assert '[Name]' in result


# ── TRIM → sql_string_op passthrough ──────────────────────────────────

def test_trim_passthrough():
    result = _translate_tableau_to_ts_functions('TRIM([Name])')
    assert 'sql_string_op' in result
    assert 'trim' in result
    assert '[Name]' in result


# ── REPLACE → sql_string_op passthrough ───────────────────────────────

def test_replace_passthrough():
    result = _translate_tableau_to_ts_functions("REPLACE([Name], '_', ' ')")
    assert 'sql_string_op' in result
    assert 'replace' in result
    assert '[Name]' in result


# ── String + → concat() ──────────────────────────────────────────────

def test_string_plus_to_concat():
    result = _translate_tableau_to_ts_functions("[First] + ' ' + [Last]")
    assert result == "concat ( [First] , ' ' , [Last] )"


def test_numeric_plus_untouched():
    result = _translate_tableau_to_ts_functions('1 + 2 + 3')
    assert '+' in result


# ── CASE with nested IF...END ─────────────────────────────────────────

def test_case_with_nested_if():
    formula = "CASE WHEN [X] > 0 THEN IF [Y] > 0 THEN 'a' ELSE 'b' END ELSE 'c' END"
    result = _translate_tableau_to_ts_functions(formula)
    assert 'WHEN' not in result
    assert 'CASE' not in result


# ── formula_names skipping in _qualify_column_refs ─────────────────────

class TestQualifyFormulaNames:

    def test_formula_caption_skipped(self):
        formula = "[Profit Margin] * [Revenue]"
        col_to_table = {"Revenue": "SALES"}
        table_map = {"SALES": "SALES_TBL"}
        formula_names = {"Profit Margin"}
        result, unresolved = _qualify_column_refs(
            formula, col_to_table, table_map, formula_names=formula_names,
        )
        assert "[Profit Margin]" in result
        assert "[SALES_TBL::Revenue]" in result
        assert unresolved == []

    def test_formula_caption_not_in_unresolved(self):
        formula = "[CalcA] + [CalcB] + [PhysCol]"
        col_to_table = {"PhysCol": "T1"}
        table_map = {"T1": "TABLE_1"}
        formula_names = {"CalcA", "CalcB"}
        result, unresolved = _qualify_column_refs(
            formula, col_to_table, table_map, formula_names=formula_names,
        )
        assert "[CalcA]" in result
        assert "[CalcB]" in result
        assert "[TABLE_1::PhysCol]" in result
        assert unresolved == []

    def test_empty_formula_names_backward_compat(self):
        formula = "[Unknown] + [Revenue]"
        col_to_table = {"Revenue": "SALES"}
        table_map = {"SALES": "SALES_TBL"}
        result, unresolved = _qualify_column_refs(
            formula, col_to_table, table_map,
        )
        assert "[SALES_TBL::Revenue]" in result
        assert "Unknown" in unresolved


# ── _load_table_map_file ──────────────────────────────────────────────

class TestLoadTableMapFile:

    def test_dash_separator(self, tmp_path):
        f = tmp_path / "map.txt"
        f.write_text("DB.SCHEMA.ORDERS - VW_ORDERS_RPT\nDB.CUSTOMERS - VW_CUSTOMERS\n")
        result = _load_table_map_file(str(f))
        assert result == {"ORDERS": "VW_ORDERS_RPT", "CUSTOMERS": "VW_CUSTOMERS"}

    def test_colon_separator(self, tmp_path):
        f = tmp_path / "map.txt"
        f.write_text("LINEORDER : LINEORDER_TARGET\n")
        result = _load_table_map_file(str(f))
        assert result == {"LINEORDER": "LINEORDER_TARGET"}

    def test_comments_and_blanks_skipped(self, tmp_path):
        f = tmp_path / "map.txt"
        f.write_text("# comment\n\nDB.TBL - TARGET\n")
        result = _load_table_map_file(str(f))
        assert result == {"TBL": "TARGET"}

    def test_multi_segment_both_sides_extracts_last(self, tmp_path):
        f = tmp_path / "map.txt"
        f.write_text("PRD_DL.DATA_SCIENCE.CAMPAIGNS - STG.RPT.VW_CAMPAIGNS_RPT\n")
        result = _load_table_map_file(str(f))
        assert result == {"CAMPAIGNS": "VW_CAMPAIGNS_RPT"}
