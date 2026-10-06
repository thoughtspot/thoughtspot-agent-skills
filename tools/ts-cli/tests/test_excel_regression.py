"""The 60-formula Excel regression set (BL-339) — the Excel translator's acceptance test.

Fixture: ``fixtures/excel_regression/``
- ``input.txt`` — ``id|name|intended class|formula``, a real workbook's calculated columns;
- ``proposed.json`` — the reviewed ThoughtSpot formulas, each VALIDATE_ONLY-clean on
  se-thoughtspot (2026-10-06), with the user's conventions: ``safe_divide`` for ratios, a ratio
  of totals for MEASUREs, row-level attributes, ``to_string`` inside ``concat``;
- ``columns.json`` — the column context (data types decide the ``to_string`` wrapping).

The translator must match ``proposed.json`` semantically (``excel_support.normalise``) for every
case except the ones in ``DIFFERS_BY_RULE``, each with the rule that justifies it.
"""
from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path

import pytest

from tests.excel_support import evaluate, normalise
from ts_cli.excel.to_excel import to_excel
from ts_cli.excel.translate import translate_excel
from ts_cli.formula_translate.catalog import is_known
from ts_cli.formula_translate.context import ColumnContext, parse_columns_json
from ts_cli.formula_translate.engine import translate
from ts_cli.excel.tsast import walk
from ts_cli.excel.helpers import from_text

FIXTURE = Path(__file__).parent / "fixtures" / "excel_regression"
CASES = [line.rstrip("\n").split("|", 3)
         for line in (FIXTURE / "input.txt").read_text().splitlines() if line.strip()]
PROPOSED = json.loads((FIXTURE / "proposed.json").read_text())
COLUMNS = (FIXTURE / "columns.json").read_text()

# id -> (the translator's output, the rule that makes it differ from proposed.json)
DIFFERS_BY_RULE = {
    "2.33": ("if ( [TABLE::IS_ACTIVE] = 0 ) then 'Churned' else 'Active'",
             "The review inverted the test (= 1 → 'Active') so a NULL gives 'Churned' on both "
             "sides. That assumes IS_ACTIVE is binary, which the formula does not say; the "
             "translator keeps the source's test and reports the blank-as-zero trap (E10) "
             "instead of guessing the column's domain."),
    "2.49": ("if ( [TABLE::QUARTER_LABEL] = concat ( 'Q' , to_string ( quarter_number ( "
             "today ( ) ) ) , ' ' , to_string ( year ( today ( ) ) ) ) ) then 1 else 0",
             "The review rewrote the label comparison as a date comparison on MONTH_END_DATE, "
             "a column the formula does not reference. A translator never introduces a "
             "column: it keeps the label comparison (ROUNDUP(MONTH(d)/3,0) → quarter_number, "
             "with the fiscal-calendar trap)."),
}


def _ctx() -> ColumnContext:
    return ColumnContext(parse_columns_json(COLUMNS), level=1)


def _run(case):
    cid, _name, role, src = case
    return translate_excel(src, _ctx(), role=role.lower())


def test_fixture_has_60_cases():
    assert len(CASES) == 60 and set(PROPOSED) == {c[0] for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_matches_reviewed_formula(case):
    r = _run(case)
    assert r.expr is not None, r.notes
    if case[0] in DIFFERS_BY_RULE:
        assert r.expr == DIFFERS_BY_RULE[case[0]][0]
        assert normalise(r.expr) != normalise(PROPOSED[case[0]]["formula"])
    else:
        assert normalise(r.expr) == normalise(PROPOSED[case[0]]["formula"]), r.expr


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_role_is_the_intended_class_or_explained(case):
    r = _run(case)
    assert r.role == case[2]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_only_catalogued_functions_and_guard_clean(case):
    """Every emitted function is in the output-guard catalog, and the full pipeline (output
    guard included) accepts it — no `nullif`, no unknown name."""
    r = _run(case)
    calls = {n["fn"] for n in walk(from_text(r.expr)) if n.get("node") == "call"}
    assert all(is_known(fn) for fn in calls if fn not in ("in", "between")), calls
    full = translate(case[3], "excel", _ctx(), role=case[2].lower())
    assert full["status"] != "NEEDS_REVIEW", full["notes"]
    assert "nullif" not in full["formula"]


def test_statuses():
    """IFERROR(…, "") ratios are APPROXIMATED (blank → 0); everything else TRANSLATED."""
    for case in CASES:
        r = _run(case)
        blank = 'IFERROR(' in case[3] and case[3].rstrip().endswith(',"")')
        assert r.status == ("APPROXIMATED" if blank else "TRANSLATED"), (case[0], r.traps)


def test_ratio_measures_are_ratios_of_totals():
    for case in CASES:
        r = _run(case)
        if case[2] == "MEASURE" and "IFERROR(" in case[3]:
            assert "safe_divide ( sum (" in r.expr and "sum ( safe_divide" not in r.expr
            assert any(t.startswith("ratio of totals") for t in r.traps)


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------

# TS → Excel → TS: the one case whose Excel form is not the translator's input shape.
ROUND_TRIP_EXCEPTIONS = {
    "2.5": "sum ( greatest ( 0 , a - b ) ): Excel's MAX collapses an array, so inside SUM the "
           "reverse writes greatest as an element-wise IF(0>=x,0,x); the forward translator "
           "keeps that IF rather than guessing greatest (they differ on NULLs).",
}


def _ts_round_trip(ts: str, role: str) -> str:
    excel = to_excel(ts)
    assert excel.formula is not None, excel.notes
    back = translate_excel(excel.formula, _ctx(), role=role)
    assert back.expr is not None, (excel.formula, back.notes)
    return back.expr


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_ts_excel_ts_round_trip_translator_output(case):
    ts = _run(case).expr
    back = _ts_round_trip(ts, case[2].lower())
    if case[0] in ROUND_TRIP_EXCEPTIONS:
        assert normalise(back) != normalise(ts)
    else:
        assert normalise(back) == normalise(ts), back


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_ts_excel_ts_round_trip_reviewed_formula(case):
    ts = PROPOSED[case[0]]["formula"]
    back = _ts_round_trip(ts, case[2].lower())
    if case[0] in ROUND_TRIP_EXCEPTIONS:
        assert normalise(back) != normalise(ts)
    else:
        assert normalise(back) == normalise(ts), back


TEXT_POOL = {
    "ACV_BAND": ["$150K-$500K", "500K+", "<$50k", "$50K-$150k"],
    "AI_ADOPTION_TIER": ["Power", "power", "Light", "None"],
    "PRICING_MODEL": ["Usage", "Seat + usage", "Seat", "Flat"],
    "REGION": ["EMEA", "emea", "AMER", "APJ"],
    "BILLING_FREQUENCY": ["Monthly", "Quarterly", "Annual", "Every year", "Semi-annual", "x"],
    "CURRENCY": ["USD", "usd", "EUR", "GBP"],
    "MONTH_NAME": ["January", "July", "December"],
    "HALF": ["H1", "H2", "h2"],
    "QUARTER_LABEL": ["Q4 2026", "Q3 2026", "q4 2026", "Q4 2025"],
}
TODAY = dt.date(2026, 10, 6)


def _rows(seed: int, n: int = 25) -> list:
    rnd = random.Random(seed)
    cols = json.loads(COLUMNS)
    rows = []
    for _ in range(n):
        row = {}
        for name, spec in cols.items():
            if name in TEXT_POOL:
                row[name] = rnd.choice(TEXT_POOL[name])
            elif spec["data_type"] == "DATE":
                row[name] = dt.date(2026, rnd.randint(1, 12), 1) + dt.timedelta(days=27)
            elif name.startswith("IS_"):
                row[name] = float(rnd.choice([0, 1]))
            elif spec["data_type"] == "INT64":
                row[name] = float(rnd.choice([1, 12, 24, 36, 2026, 49, 74, 80]))
            else:  # non-zero, so the documented zero-divisor difference is excluded
                row[name] = float(rnd.choice([-250, 1, 3, 40, 999, 12500, 0.5]))
        rows.append(row)
    return rows


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_excel_ts_excel_is_semantically_equivalent(case):
    """Excel → TS (row level, the role-preserving translation) → Excel evaluates to the same
    values as the original on sample rows. Zero divisors and blanks are excluded: those are
    the documented, trapped differences (IFERROR "" → 0; E10)."""
    ts = translate_excel(case[3], _ctx(), role="attribute").expr
    back = to_excel(ts).formula
    rows = _rows(sum(map(ord, case[0])))
    for row in rows:
        original = evaluate(case[3], row, rows, TODAY)
        assert evaluate(back, row, rows, TODAY) == original, (back, row)
