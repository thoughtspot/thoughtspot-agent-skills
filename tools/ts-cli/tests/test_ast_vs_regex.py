"""Head-to-head: regex translator vs Lark-AST translator.

Runs the SAME Tableau formulas through both `_translate_tableau_to_ts_functions`
(regex, in tableau.py) and `translate_ast` (Lark AST, in tableau_formula_ast.py),
normalizes cosmetic whitespace, and checks each against an expected result.

Two case sets:
  * CORE   — behaviors already covered by test_tableau_translate_formula.py
  * HARD   — deliberately difficult formulas (nested calls, quoted keywords,
             precedence, deep CASE) where regex string-substitution is prone to
             error and an AST should hold.

Run as a script for a side-by-side report:
    python -m pytest tests/test_ast_vs_regex.py -q          # assertions
    python tests/test_ast_vs_regex.py                       # printed report
"""
import re

from ts_cli.commands.tableau_parse import _translate_tableau_to_ts_functions as regex_translate
from ts_cli.commands.tableau_formula_ast import (
    translate_ast,
    translate_with_fallback,
    FormulaParseError,
)


def _norm(s):
    """Collapse cosmetic whitespace so comparison is about structure, not spacing."""
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([(),{}])\s*", r"\1", s)   # no spaces around ( ) , { }
    s = re.sub(r"\s*([<>=!]+)\s*", r" \1 ", s)  # single spaces around comparators
    return s.strip()


def _run_regex(f):
    try:
        return regex_translate(f), None
    except Exception as e:  # regex should never raise, but be safe
        return None, f"{type(e).__name__}: {e}"


def _run_ast(f):
    try:
        return translate_ast(f), None
    except FormulaParseError as e:
        return None, "parse-error"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _passes(out, err, case):
    """A translator passes a case if it produced the expected structure."""
    if err or out is None:
        return False
    n = _norm(out)
    if case.get("expect") is not None:
        return n == _norm(case["expect"])
    ok = all(_norm(c) in n for c in case.get("contains", []))
    ok = ok and all(_norm(x) not in n for x in case.get("excludes", []))
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# CORE — parity with existing translate-formula tests
# ─────────────────────────────────────────────────────────────────────────────

CORE = [
    {"f": "COUNTD([Customer ID])", "contains": ["unique count("], "tag": "rename"},
    {"f": "STR([Amount])", "contains": ["to_string("], "tag": "rename"},
    {"f": "INT([Price])", "contains": ["to_integer("], "tag": "rename"},
    {"f": "AVG([x])", "contains": ["average("], "tag": "rename"},
    {"f": "CASE WHEN [Status] = 'A' THEN 'Active' ELSE 'Inactive' END",
     "contains": ["if", "="], "excludes": ["CASE", "WHEN", "END"], "tag": "case"},
    {"f": "IF [Sales] > 100 THEN 'High' END",
     "contains": ["else null", "> 100"], "excludes": ["END"], "tag": "if-noelse"},
    {"f": "IF [x] = 1 THEN 'a' ELSEIF [x] = 2 THEN 'b' END",
     "contains": ["else if", "else null"], "excludes": ["ELSEIF", "END"], "tag": "elseif"},
    {"f": "STR([Amount], '#')", "expect": "to_string([Amount])", "tag": "str-hash"},
    {"f": "STR([Date], 'yyyy-MM-dd')", "contains": ["'yyyy-MM-dd'"], "tag": "str-fmt"},
    {"f": "[Status] IN ('Active', 'Pending')",
     "contains": ["in {", "'Active'", "'Pending'"], "excludes": ["IN ("], "tag": "in"},
    {"f": "[Status] NOT IN ('Active', 'Pending')",
     "contains": ["not in {"], "excludes": ["NOT IN ("], "tag": "not-in"},
    {"f": "DATEDIFF('day', [a], [b])", "contains": ["diff_days"], "tag": "datediff"},
    {"f": "DATEADD('month', 3, [d])", "contains": ["add_months"], "tag": "dateadd"},
    {"f": "CAST([Order Date] AS DATE)", "expect": "[Order Date]", "tag": "cast-date-col"},
    {"f": "CAST('2024-01-15' AS DATE)", "contains": ["to_date", "'%Y-%m-%d'"], "tag": "cast-date-str"},
    {"f": "CAST([Revenue] > 100 AS BOOLEAN)",
     "contains": ["[Revenue] > 100"], "excludes": ["to_bool"], "tag": "cast-bool"},
    {"f": "ZN([x])", "contains": ["ifnull(", ", 0"], "tag": "zn"},
    {"f": "IIF([x] > 0, 'p', 'n')", "contains": ["if(", "then 'p'", "else 'n'"], "tag": "iif"},
    {"f": "'A' + 'B'", "contains": ["concat("], "tag": "concat"},
    {"f": "{FIXED [Region] : SUM([Sales])}",
     "contains": ["group_aggregate", "{[Region]}"], "tag": "lod-fixed"},
]


# ─────────────────────────────────────────────────────────────────────────────
# HARD — nested / adversarial formulas with a known-correct expected result
# ─────────────────────────────────────────────────────────────────────────────

HARD = [
    {
        "f": "IIF([x] > 0, IIF([y] > 0, 'both', 'xonly'), 'neither')",
        "expect": "if ( [x] > 0 ) then if ( [y] > 0 ) then 'both' else 'xonly' else 'neither'",
        "tag": "nested-iif",
    },
    {
        "f": 'IF [Status] = "END" THEN 1 ELSE 0 END',
        "expect": "if ([Status] = 'END') then 1 else 0",
        "tag": "quoted-keyword-END",
    },
    {
        "f": 'IF [Label] = "Cats AND Dogs" THEN 1 ELSE 0 END',
        "expect": "if ([Label] = 'Cats AND Dogs') then 1 else 0",
        "tag": "quoted-keyword-AND",
    },
    {
        "f": "IF [a] > 0 THEN CASE [b] WHEN 1 THEN 'one' ELSE 'other' END ELSE 'neg' END",
        "expect": "if ([a] > 0) then if ([b] = 1) then 'one' else 'other' else 'neg'",
        "tag": "case-inside-if",
    },
    {
        "f": "IIF([s] IN ('a', 'b'), 1, 0)",
        "expect": "if ( [s] in { 'a' , 'b' } ) then 1 else 0",
        "tag": "in-inside-iif",
    },
    {
        # Any valid grouping computes the same string; a flat concat is cleanest.
        "f": "'x=' + STR([x]) + ', y=' + STR([y])",
        "expect": "concat ( 'x=' , to_string ( [x] ) , ', y=' , to_string ( [y] ) )",
        "tag": "chained-concat-with-fn",
    },
    {
        "f": "DATEDIFF('day', [a], DATEADD('month', 1, [b]))",
        "expect": "diff_days ( [a] , add_months ( [b] , 1 ) )",
        "tag": "nested-date-fns",
    },
    {
        "f": "ZN(IIF([d] = 0, 0, [n] / [d]))",
        "expect": "ifnull ( if ( [d] = 0 ) then 0 else [n] / [d] , 0 )",
        "tag": "iif-inside-zn",
    },
]


def _evaluate(cases):
    rows = []
    for case in cases:
        f = case["f"]
        r_out, r_err = _run_regex(f)
        a_out, a_err = _run_ast(f)
        rows.append({
            "tag": case["tag"], "f": f,
            "regex_out": r_out, "regex_err": r_err, "regex_ok": _passes(r_out, r_err, case),
            "ast_out": a_out, "ast_err": a_err, "ast_ok": _passes(a_out, a_err, case),
        })
    return rows


# ── pytest assertions ────────────────────────────────────────────────────────

def test_ast_passes_all_core():
    rows = _evaluate(CORE)
    failed = [r["tag"] for r in rows if not r["ast_ok"]]
    assert not failed, f"AST failed CORE cases: {failed}\n" + _format(rows)


def test_ast_passes_all_hard():
    rows = _evaluate(HARD)
    failed = [r["tag"] for r in rows if not r["ast_ok"]]
    assert not failed, f"AST failed HARD cases: {failed}\n" + _format(rows)


def test_ast_at_least_matches_regex_on_hard():
    """The whole point: AST must not be worse than regex on the hard set."""
    rows = _evaluate(HARD)
    regex_score = sum(r["regex_ok"] for r in rows)
    ast_score = sum(r["ast_ok"] for r in rows)
    assert ast_score >= regex_score, (
        f"AST ({ast_score}) scored below regex ({regex_score}) on HARD\n" + _format(rows)
    )


# ── report ───────────────────────────────────────────────────────────────────

def _format(rows):
    lines = []
    for r in rows:
        rg = "PASS" if r["regex_ok"] else "FAIL"
        ax = "PASS" if r["ast_ok"] else "FAIL"
        lines.append(f"  [{r['tag']}] regex={rg} ast={ax}")
        if not r["regex_ok"]:
            lines.append(f"      regex: {r['regex_err'] or r['regex_out']}")
        if not r["ast_ok"]:
            lines.append(f"      ast:   {r['ast_err'] or r['ast_out']}")
    return "\n".join(lines)


# ── closed grammar gaps + fallback ───────────────────────────────────────────

def test_ast_handles_line_comment():
    out = translate_ast("// growth\n[Revenue] - [Cost]")
    assert _norm(out) == _norm("[Revenue] - [Cost]")


def test_ast_handles_block_comment():
    out = translate_ast("/* note */ [a] * [b]")
    assert _norm(out) == _norm("[a] * [b]")


def test_ast_handles_date_literal():
    out = translate_ast("IF [Order Date] > #2024-01-01# THEN 1 ELSE 0 END")
    n = _norm(out)
    assert "to_date('2024-01-01', 'yyyy-MM-dd')".replace(" ", "") in n.replace(" ", "")
    assert "#" not in n


def test_ast_handles_datetime_literal():
    out = translate_ast("IF [ts] > #2024-01-01 12:30:00# THEN 1 ELSE 0 END")
    assert "HH:mm:ss" in out and "#" not in out


def test_ast_handles_modulo():
    out = translate_ast("IF [x] % 2 = 0 THEN 'even' ELSE 'odd' END")
    # Tableau '%' is modulo; ThoughtSpot has no '%' operator — it uses mod().
    assert "mod (" in out
    assert "%" not in out


def test_fallback_used_on_unparseable():
    calls = []
    out = translate_with_fallback("SUM([x]", on_fallback=lambda f, r: calls.append((f, r)))
    assert calls, "expected a fallback to be recorded"
    assert _norm(out) == _norm("sum([x]")   # regex pipeline result


def test_no_fallback_on_normal_formula():
    calls = []
    out = translate_with_fallback("IIF([x] > 0, 'p', 'n')", on_fallback=lambda f, r: calls.append(f))
    assert not calls, "normal formula should not fall back"
    assert "if" in out.lower()


def _report():
    for label, cases in (("CORE", CORE), ("HARD", HARD)):
        rows = _evaluate(cases)
        rg = sum(r["regex_ok"] for r in rows)
        ax = sum(r["ast_ok"] for r in rows)
        n = len(rows)
        print(f"\n{'='*78}\n{label}: regex {rg}/{n}   ast {ax}/{n}\n{'='*78}")
        for r in rows:
            mark = "  " if r["regex_ok"] == r["ast_ok"] else "* "
            print(f"{mark}[{r['tag']}]  regex={'✓' if r['regex_ok'] else '✗'}  ast={'✓' if r['ast_ok'] else '✗'}")
            print(f"    in:    {r['f']}")
            print(f"    regex: {r['regex_err'] or r['regex_out']}")
            print(f"    ast:   {r['ast_err'] or r['ast_out']}")


if __name__ == "__main__":
    _report()
