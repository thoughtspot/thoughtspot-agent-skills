"""Unit tests for check_formula_catalog — formula cross-check validator."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_formula_catalog  # noqa: E402

SAMPLE_CATALOG = """\
## Math Functions

| Function | Syntax | Notes |
|---|---|---|
| `pow` | `pow ( [x] , [n] )` | |
| `abs` | `abs ( [x] )` | |
| `safe_divide` | `safe_divide ( [a] , [b] )` | Returns 0 on zero divisor |

## String Functions

| Function | Syntax | Notes |
|---|---|---|
| `concat` | `concat ( [a] , [b] , ... )` | N arguments supported |
| ~~`upper`~~ | — | **Does not exist** |
| ~~`lower`~~ | — | **Does not exist** |
| `trim` | `trim ( [x] )` | |

## Date Functions

| Function | Syntax | Notes |
|---|---|---|
| `today` | `today ()` | Current date |
| `hour_of_day` | `hour_of_day ( [date] )` | Hour of the day |
| ~~`date_trunc`~~ | — | **Does not exist** |
"""


def test_parse_valid_functions():
    valid, nonexistent = check_formula_catalog.parse_catalog(SAMPLE_CATALOG)
    assert "pow" in valid
    assert "abs" in valid
    assert "safe_divide" in valid
    assert "concat" in valid
    assert "trim" in valid
    assert "today" in valid
    assert "hour_of_day" in valid
    assert "upper" not in valid
    assert "lower" not in valid
    assert "date_trunc" not in valid


def test_parse_nonexistent_functions():
    valid, nonexistent = check_formula_catalog.parse_catalog(SAMPLE_CATALOG)
    assert "upper" in nonexistent
    assert "lower" in nonexistent
    assert "date_trunc" in nonexistent
    assert "pow" not in nonexistent


# ── Mapping file scanning ────────────────────────────────────────────────────

SAMPLE_MAPPING_WITH_ERROR = """\
## Scalar Functions

### String Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `concat(a, b)` | `CONCAT(a, b)` | |
| `upper(s)` | `UPPER(s)` | |
| `trim(s)` | `TRIM(s)` | |
"""

SAMPLE_MAPPING_STRIKETHROUGH = """\
### String Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `concat(a, b)` | `CONCAT(a, b)` | |
| ~~`upper(s)`~~ | `UPPER(s)` | Not a native TS function |
| `trim(s)` | `TRIM(s)` | |
"""

SAMPLE_MAPPING_UNKNOWN = """\
### Date Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `today()` | `CURRENT_DATE()` | |
| `frobnicate(x)` | `FROB(x)` | |
"""

SAMPLE_MAPPING_COMPLEX = """\
## Window Functions

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `cumulative_sum(m, attr)` | `SUM(m) OVER (ORDER BY attr)` | |
| `group_aggregate(sum(m), {attr})` | subquery | |
"""

SAMPLE_MAPPING_SQL_OP = """\
### Pass-through

| ThoughtSpot | Databricks SQL | Notes |
|---|---|---|
| `sql_string_op("UPPER({0})", s)` | `UPPER(s)` | |
"""

SAMPLE_SNOWFLAKE_BIDI = """\
### String Functions

| ThoughtSpot → Snowflake | Snowflake → ThoughtSpot |
|---|---|
| `upper ( [x] )` → `UPPER(x)` | `UPPER(x)` → `upper ( [x] )` |
| `concat ( [a] , [b] )` → `CONCAT(a, b)` | `CONCAT(a, b)` → `concat ( [a] , [b] )` |
"""


def test_error_on_nonexistent_usage():
    valid, nonexistent = check_formula_catalog.parse_catalog(SAMPLE_CATALOG)
    errors, warnings = check_formula_catalog.scan_mapping(
        SAMPLE_MAPPING_WITH_ERROR, "test-mapping.md", valid, nonexistent,
    )
    assert any("upper" in e and "ERROR" in e for e in errors), errors


def test_no_error_on_strikethrough_usage():
    valid, nonexistent = check_formula_catalog.parse_catalog(SAMPLE_CATALOG)
    errors, warnings = check_formula_catalog.scan_mapping(
        SAMPLE_MAPPING_STRIKETHROUGH, "test-mapping.md", valid, nonexistent,
    )
    assert not any("upper" in e for e in errors), errors


def test_warning_on_unknown_function():
    valid, nonexistent = check_formula_catalog.parse_catalog(SAMPLE_CATALOG)
    errors, warnings = check_formula_catalog.scan_mapping(
        SAMPLE_MAPPING_UNKNOWN, "test-mapping.md", valid, nonexistent,
    )
    assert not errors, errors
    assert any("frobnicate" in w for w in warnings), warnings


def test_complex_patterns_not_warned():
    valid, nonexistent = check_formula_catalog.parse_catalog(SAMPLE_CATALOG)
    errors, warnings = check_formula_catalog.scan_mapping(
        SAMPLE_MAPPING_COMPLEX, "test-mapping.md", valid, nonexistent,
    )
    assert not errors, errors
    assert not any("cumulative_sum" in w for w in warnings), warnings
    assert not any("group_aggregate" in w for w in warnings), warnings


def test_sql_op_templates_skipped():
    valid, nonexistent = check_formula_catalog.parse_catalog(SAMPLE_CATALOG)
    errors, warnings = check_formula_catalog.scan_mapping(
        SAMPLE_MAPPING_SQL_OP, "test-mapping.md", valid, nonexistent,
    )
    assert not errors, errors


def test_snowflake_bidi_nonexistent_caught():
    valid, nonexistent = check_formula_catalog.parse_catalog(SAMPLE_CATALOG)
    errors, warnings = check_formula_catalog.scan_mapping(
        SAMPLE_SNOWFLAKE_BIDI, "test-snowflake.md", valid, nonexistent,
    )
    assert any("upper" in e and "ERROR" in e for e in errors), errors
    assert not any("concat" in e for e in errors), errors
