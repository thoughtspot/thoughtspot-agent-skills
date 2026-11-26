"""BL-646: the BL-632 greedy-`else` class in the Tableau, Sisense and Qlik translators.

ThoughtSpot's `else` is greedy (live-verified 2026-11-26): `if ( c ) then a else b + 1`
adds 1 only on the else branch. A converted conditional that an operator follows is
grouped; one standing alone keeps its bare form, so the later passes that match on it
(agg(if …) → agg_if, ensure_else_clause) see the same text as before.
"""
import pytest

from ts_cli import tableau_translate
from ts_cli.qlik.functions import translate as qlik
from ts_cli.sisense.functions import translate_jaql as sisense


def tableau(expr: str, role: str = "measure") -> str:
    return tableau_translate.translate_single(expr, role=role)[0]


@pytest.mark.parametrize("src, want", [
    ("IIF([a] > 1, 1, 0) + 1", "( if ( [a] > 1 ) then 1 else 0 ) + 1"),
    ("IF [a] > 1 THEN 1 ELSE 0 END + 1", "( if ( [a] > 1 ) then 1 else 0 ) + 1"),
    ("CASE [b] WHEN 'x' THEN 1 ELSE 0 END * 2", "( if ( [b] = 'x' ) then 1 else 0 ) * 2"),
    ("IIF([a] > 1, 'x', 'y') = 'x'", "( if ( [a] > 1 ) then 'x' else 'y' ) = 'x'"),
    # Tableau returns NULL when no branch matches; a grouped block says so explicitly
    ("IF [a] > 1 THEN 1 END + 1", "( if ( [a] > 1 ) then 1 else null ) + 1"),
    ("CASE [b] WHEN 'x' THEN 1 END * 2", "( if ( [b] = 'x' ) then 1 else null ) * 2"),
    ("IF [a]>1 THEN 1 END + IF [b] THEN 2 END",
     "( if ( [a]>1 ) then 1 else null ) + if ( [b] ) then 2 else 0"),
])
def test_tableau_groups_a_conditional_an_operator_follows(src, want):
    assert tableau(src) == want


@pytest.mark.parametrize("src, want", [
    ("IIF([a]>1,1,0)", "if ( [a]>1 ) then 1 else 0"),
    ("SUM(IIF([a]>1,[s],0))", "sum_if ( [a]>1 , [s] )"),
    ("SUM(IF [a]>1 THEN [s] END) / SUM([s])", "sum_if ( [a]>1 , [s] ) / sum ( [s])"),
    ("IF [a] > 1 THEN IF [b] THEN 1 END END",
     "if ( [a] > 1 ) then if ( [b] ) then 1 else null else 0"),
])
def test_tableau_leaves_a_standalone_conditional_as_it_was(src, want):
    assert tableau(src) == want


def test_sisense_groups_a_conditional_an_operator_follows():
    assert sisense("IF([a] > 1, 1, 0) = 1")[0] == "( if ([a] > 1) then 1 else 0 ) = 1"
    assert sisense("IF([a]>1,1,0) + IF([b]>1,1,0)")[0] == \
        "( if ([a]>1) then 1 else 0 ) + if ([b]>1) then 1 else 0"
    assert sisense("SUM(IF([a] > 1, [b], 0))")[0] == "sum(if ([a] > 1) then [b] else 0)"


def test_qlik_refuses_an_if_call_that_does_not_span_the_expression():
    out, needs_review = qlik("If(a > 1, 1, 0) * Sum(b)")[:2]
    assert needs_review and out.count("(") == out.count(")"), out
    assert qlik("If(a > 1, 1, 0)")[:2] == ("if (a > 1) then 1 else 0", False)
