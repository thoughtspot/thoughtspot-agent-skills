"""`RAWSQL_*` was documented untranslatable and known to no code (audit 13.20).

`tableau-formula-translation.md` lists `RAWSQL_*()` as untranslatable — "Direct
SQL passthrough — not portable across warehouses" — and the coverage matrix
records it as limitation L3 "Omit + log". But `grep -rn RAWSQL tools/ts-cli/`
returned nothing: no mapping, no `_UNMAPPED_FUNCTIONS` entry, no family regex.

Per the contract at the head of `_UNMAPPED_FUNCTIONS` — *"Formulas containing
them are skipped with a reason instead of failing at TML import, where the retry
loop silently drops them"* — a calc carrying one was emitted verbatim into model
TML, failed import, and vanished with no MIGRATION_LIMITATIONS entry. Silent
loss of a formula in a shipped conversion.

Same class as PARSE_WKT/NO_CUTOUTS (13.22) and MODEL_*/SCRIPT_* (13.25), over a
larger family with a stable prefix. Tableau documents 13: seven `RAWSQL_*` and
six `RAWSQLAGG_*` (there is no `RAWSQLAGG_SPATIAL`).
"""
import pytest

from ts_cli.tableau.validate import validate_output

SCALAR = ["RAWSQL_BOOL", "RAWSQL_DATE", "RAWSQL_DATETIME", "RAWSQL_INT",
          "RAWSQL_REAL", "RAWSQL_SPATIAL", "RAWSQL_STR"]
AGG = ["RAWSQLAGG_BOOL", "RAWSQLAGG_DATE", "RAWSQLAGG_DATETIME",
       "RAWSQLAGG_INT", "RAWSQLAGG_REAL", "RAWSQLAGG_STR"]


@pytest.mark.parametrize("fn", SCALAR + AGG)
def test_every_documented_passthrough_is_rejected(fn):
    errors = validate_output(f'{fn}("SUM(%1)", [Sales])')
    assert errors, f"{fn} passed validation and would be dropped at import"
    assert any(fn in e for e in errors), errors


def test_the_documented_family_is_thirteen():
    assert len(SCALAR) + len(AGG) == 13


def test_the_reason_names_the_function_and_says_why():
    errors = validate_output('RAWSQLAGG_REAL("SUM(%1)", [Sales])')
    joined = " ".join(errors)
    assert "RAWSQLAGG_REAL" in joined
    assert "pass" in joined.lower() or "sql" in joined.lower()


def test_case_and_spacing_do_not_evade_it():
    assert validate_output('rawsql_real ( "%1", [X] )')


def test_a_future_family_member_is_caught_by_the_prefix():
    """Enumerating 13 names would go stale; the prefix will not."""
    assert validate_output('RAWSQL_GEOGRAPHY("%1", [X])')


def test_an_ordinary_formula_still_passes():
    assert validate_output("sum ( [ORDERS::AMOUNT] )") == []


def test_a_column_merely_named_rawsql_is_not_a_call():
    """The pattern requires a call; a column reference must not trip it."""
    assert validate_output("sum ( [ORDERS::RAWSQL_NOTES] )") == []
