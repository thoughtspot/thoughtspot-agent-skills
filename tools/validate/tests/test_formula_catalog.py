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
