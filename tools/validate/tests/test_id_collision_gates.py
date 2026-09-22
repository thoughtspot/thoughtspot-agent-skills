"""Unit tests for the coverage-matrix and lint-invariant id collision rules.

Both are the BL-274/BL-279 shape: a resource allocated as "highest + 1", two
branches taking the same value, and a validator whose rule is a set operation
that a collision preserves. Each gets both halves — a within-tree duplicate rule
that needs no git and catches the MERGED state, and a `--base` novelty rule that
catches it one branch earlier.

Unlike open-items (BL-282), a strict within-tree rule ships immediately for both:
there are zero duplicate ids across all nine coverage matrices, and `tml_lint.py`
attributes each `I<N>` to exactly one function.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_coverage_matrix as ccm  # noqa: E402
import check_lint_invariant_list as clil  # noqa: E402


# --- coverage matrices -----------------------------------------------------

MATRIX = """## Mapped Constructs

| # | Construct | Equivalent | Notes |
|---|---|---|---|
| 1 | first | x | |
| 131 | out-of-order id | x | |
| 2 | second | x | |

## Limitations

| # | Limitation | Why | Handling |
|---|---|---|---|
| L1 | a limit | reason | omit |
| U3 | unmapped | reason | log |
"""


def test_matrix_ids_reads_the_leading_column_only():
    # Ids are stable, not positional — 131 sits between 2 and 3 in the real
    # tableau matrix — and two families share the namespace.
    assert ccm.matrix_ids(MATRIX) == ["1", "131", "2", "L1", "U3"]


def test_matrix_ids_ignores_separator_rows_and_prose():
    text = "|---|---|\n\nSee row 42 for context.\n| 7 | real | x | |\n"
    assert ccm.matrix_ids(text) == ["7"]


def test_duplicate_matrix_id_is_flagged():
    # The merged state: two branches each appended `| 137 |`, in different tables.
    doubled = MATRIX.replace("| 2 | second | x | |", "| 2 | second | x | |\n| 131 | branch B | x | |")
    assert ccm.duplicate_matrix_ids(doubled) == ["131"]


def test_distinct_families_do_not_collide():
    # `1` and `L1` and `U1` are three different ids, not one.
    text = "| 1 | a | x | |\n| L1 | b | x | |\n| U1 | c | x | |\n"
    assert ccm.duplicate_matrix_ids(text) == []


def test_clean_matrix_has_no_duplicates():
    assert ccm.duplicate_matrix_ids(MATRIX) == []


# --- lint invariants -------------------------------------------------------

def test_emissions_are_attributed_to_their_function():
    src = (
        'def _check_a(m):\n    return ["I16: first defect"]\n\n\n'
        'def _check_b(m):\n    return ["I17: second defect"]\n'
    )
    assert clil.emissions_by_function(src) == {"I16": {"_check_a"}, "I17": {"_check_b"}}


def test_one_id_from_two_functions_is_flagged():
    # Two branches each add a rule, wire it into a different block, and both bump
    # the CANONICAL-RULE-SET marker identically — so git merges it silently.
    src = (
        'def _check_a(m):\n    return ["I16: tile has no title"]\n\n\n'
        'def _check_b(m):\n    return ["I16: empty synonyms list"]\n'
    )
    assert clil.duplicate_emitters(src) == [("I16", ["_check_a", "_check_b"])]


def test_one_function_emitting_its_own_id_twice_is_fine():
    # A rule legitimately emits its own id from several branches of its logic —
    # attribution is per function, not per emission, so this must not fire.
    src = (
        'def _check_a(m):\n'
        '    if m:\n        return ["I16: case one"]\n'
        '    return ["I16: case two"]\n'
    )
    assert clil.duplicate_emitters(src) == []


def test_fstring_emissions_are_seen():
    # Real findings are f-strings: f"I15: column '{label}' ..."
    src = 'def _check_a(m):\n    label = "x"\n    return [f"I15: column {label} misplaced"]\n'
    assert clil.emissions_by_function(src) == {"I15": {"_check_a"}}


def test_clean_source_has_no_duplicate_emitters():
    src = 'def _check_a(m):\n    return ["I1: a"]\n\n\ndef _check_b(m):\n    return ["I2: b"]\n'
    assert clil.duplicate_emitters(src) == []
