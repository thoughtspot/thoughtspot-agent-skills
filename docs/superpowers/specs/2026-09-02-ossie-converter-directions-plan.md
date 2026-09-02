# Ossie ThoughtSpot Converter — Both Directions, End to End

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the `converters/thoughtspot/` package so it converts a ThoughtSpot Model TML document set to an Ossie semantic model and back, round-trips both ways, and ships a CLI — the deliverable the upstream PR proposes.

**Architecture:** Two pure, file-to-file conversion modules over the substrate Plans A and B already built. `tml_to_ossie` reads a 1+N TML document set (one Model, N Table/SQL View) and produces one Ossie semantic model, writing everything ThoughtSpot-only into `custom_extensions[THOUGHTSPOT]`. `ossie_to_thoughtspot` runs the inverse, satisfying the TML import invariants R1–R11. Expressions are **passed through under an honestly-tagged dialect**, not translated across dialects — this follows upstream practice exactly (see Global Constraint 9). A shallow formula tokenizer, not a parser, supplies the `(name, args)` decomposition that `translate_thoughtspot` and reference rewriting need. Nothing calls a network API.

**Tech Stack:** Python 3.10+, PyYAML>=6.0, pytest, hypothesis (test-only, final task). No new runtime dependency — upstream's PR template gates those on PMC/IPMC approval.

**Spec:** `/Users/damianwaldron/Dev/ts/thoughtspot-agent-skills/docs/superpowers/specs/2026-07-29-ossie-thoughtspot-converter-design.md`

**Mapping documents — the binding authority for every rule cited by id below.** Read the
section named in a task, not the whole file:

- Constructs, identifiers, stash, datatypes, R-rules:
  `/Users/damianwaldron/Dev/ts/thoughtspot-agent-skills/docs/ossie/ts-ossie-construct-mapping.md`
- Function/operator classification:
  `/Users/damianwaldron/Dev/ts/thoughtspot-agent-skills/docs/ossie/ts-ossie-function-mapping.md`

Paths are absolute because the code lives in a **different repository** from the mapping
documents (`~/Dev/ts/ossie` vs `~/Dev/ts/thoughtspot-agent-skills`). A relative path will
not resolve. This cost Plan B a whole task (ruling B3).

---

## Global Constraints

Every task's requirements implicitly include this section.

1. **Python floor 3.10.** No `match` statements guarded on 3.11+, no `Self`, no PEP-695 generics.
2. **Runtime dependencies: PyYAML>=6.0 and nothing else.** `hypothesis` and `pytest` are test-only. Adding any other runtime dependency requires PMC/IPMC approval upstream and is out of scope here.
3. **ASF licence header on every new file**, `.py`, `.yaml` fixture and workflow alike — copy the exact 16-line block from any existing file in the package.
4. **No network calls, no ThoughtSpot API, no Snowflake API.** File-to-file only. A test that needs a live instance does not belong in this package.
5. **Never port code from `~/Dev/ts/thoughtspot-agent-skills/tools/ts-cli/`.** Code from another product needs a Software Grant Agreement. `formula_common.py` and `sv_translate.py` are the tempting ones. The *mapping documents* are prose specifications and may be used freely; the Python may not, not even as a starting point to edit.
6. **No internal-process language in shipped files.** No "Task N", no "Plan A/B/C/D", no "the brief", no reference to `.superpowers/` or any planning workspace, in `src/`, `tests/`, `README.md`, fixtures or CI. This branch is proposed to an Apache project. Three successive sweeps were needed to clear this in Plan B; do not reintroduce it.
7. **Use YAML 1.2 semantics for every read and write** — `_yaml.py` already provides the codec. A column named `on`, `off`, `yes` or `no` must survive (rule R11). Never call `yaml.safe_load` or `yaml.safe_dump` directly.
8. **Every dropped or degraded construct raises an issue through `IssueLog`.** Silent loss is the one unacceptable failure. `emit_unmappable` and the `lossy→issue` verdicts in the mapping document are not advisory.
9. **Expressions pass through; they are not translated across dialects.** Always emit a `THOUGHTSPOT` dialect entry carrying the ThoughtSpot formula **verbatim, byte for byte as it appeared in the TML**. Emit an `ANSI_SQL` sibling only where it is free (a bare column reference) or where the catalog matches the whole expression outright. Never re-render one SQL dialect into another; no converter upstream does, and the specification says the default is to pass unknown values through. Do not add `sqlglot`.
10. **`custom_extensions` obeys X1–X9.** One `THOUGHTSPOT` entry per object, `data` is a JSON string, other vendors' entries pass through untouched, and no `guid`/`obj_id`/`fqn` ever enters the payload (X8).
11. **Nothing is invented.** A value that cannot be derived and was not stashed produces an issue, not a guess (X9). This explicitly forbids synthesising columns, calendars, datatypes for formulas, or a `to_columns` set that no key supports.

---

## What already exists — do not rebuild it

The package is at `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/`. 289 tests pass.
Run them with `cd /Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot && uv run --python 3.13 pytest tests/ -q`.

| Module | Public surface a task may use |
|---|---|
| `constants.py` | `VENDOR_KEY="THOUGHTSPOT"`, `DIALECT="THOUGHTSPOT"`, `PORTABLE_DIALECT="ANSI_SQL"`, `DIALECT_IS_REGISTERED=True`, `SPEC_SERIES="0.2"`, `STASH_VERSION=1` |
| `_yaml.py` | YAML 1.2 load/dump codec (narrowed boolean resolver) |
| `errors.py` | `ConversionError` |
| `issues.py` | `Severity`, `ConverterIssue`, `IssueLog` with `add(*, code, severity, message, object_ref, remedy=None)`, `extend`, `as_dicts`, `has_errors`, `count_by_severity` |
| `stash.py` | `read_stash(obj)`, `write_stash(obj, payload)`, `restore(payload, key, derived, *, witness, witness_key)` |
| `identifiers.py` | `normalise(display_name)`, `Allocator().allocate(display_name)`, `split_column_ref(ref)`, `format_column_ref(table, column)` |
| `keys.py` | `Relationship`, `derive_keys(...)` |
| `expressions/` | `CATALOG` (dict, 146 constructs), `Classification`, `Construct`, `Variant`, `emit_direct`, `emit_passthrough`, `emit_unmappable`, `REVERSE`, `translate_thoughtspot`, `thoughtspot_dialect_entry`, `portable_dialect_entry`, `custom_extensions_fragment`, `stash_runtime_parameter` |

**Three traps carried forward from Plan B**, all recorded there and all still live:

- **14 of 37 passthrough rows are exemplars.** They bake a caller-supplied value in as a literal while declaring a satisfiable arity — `PERCENTILE_CONT(0.75)`, `NTILE(4)`, `LAG` offset `1`, and others. An argument-count check passes and the wrong constant ships. **Rebuild these per occurrence; never `.format()` them.** (Tracked as BL-235 in the skills repo.)
- **~20 rows carry prose, not a substitutable template** — `CAST`, the `EXTRACT`/`DATE_TRUNC`/`DATEADD` family, both `CASE` forms, the unary row. They fail loud. Do not write a uniform `.format()` dispatcher off the type hint.
- **`thoughtspot_dialect_entry` reconstructs a call from `(name, args)` and loses the original whitespace.** It is correct for the sub-expression case it was built for. At the document level it is **wrong** — see Global Constraint 9 and Task 1.

## Decisions this plan makes that the mapping document deferred

The mapping document records several choices as "a Phase-3 converter decision". They are
settled here so no task author has to invent one. Each is binding.

| # | Question | Decision | Why |
|---|---|---|---|
| PD1 | R4-P3: which TML shape does an Ossie metric become — aggregate-in-expr (A) or scalar formula + column aggregation (B)? | **Pattern A always**, for a metric with no stash. A metric that *arrived* as pattern B round-trips back to B via the stash's `shape` key. | B moves the aggregation into a property, so a `TML → Ossie` reader must compose it back or the metric silently loses its aggregate. Reversibility beats idiom, and B's advantage is a query-time semantic we cannot verify offline. |
| PD2 | Implement `--synthesize-time-columns`? | **No.** Emit the issue with its ready-to-paste formula, as the document already specifies. | X9 forbids inventing columns; the upstream question of marking synthesised fields is genuinely open. The user is not stuck — the issue carries the remedy. |
| PD3 | Emit `properties.calendar`? | **Only from the stash, never synthesised.** `TML → Ossie` stashes the observed value verbatim and raises an issue naming the calendar. | The value vocabulary is unreconciled (BL-186 V1). The document says a converter must not emit it until it is. |
| PD4 | Branch on the unmerged apache/ossie#287? | **No.** Build against the schema on main, but isolate the five affected keys behind one module-level map so #287 becomes a change to that map. | A branch on an unmerged PR is untestable and doubles the surface. |
| PD5/PD6 | Translate expressions, or pass them through? | **Pass through under `THOUGHTSPOT`; portable sibling only where free.** No SQL parser, no `sqlglot`. | Global Constraint 9 — this is upstream practice verbatim, and the specification's stated default. |
| PD7 | Verbatim or reconstructed formula in the dialect entry? | **Verbatim, from the TML string.** | Upstream's round-trip bar is exact string equality. A reconstruction normalises whitespace and breaks it. |

**One consequence to keep in view for Task 14.** Because the verbatim entry is what the
return leg reads, a round-trip test can pass while translation is entirely broken. It
proves *preservation*, not *translation*. Task 14 asserts both, separately.

---

## File Structure

New modules, each with one responsibility:

| File | Responsibility |
|---|---|
| `src/ossie_thoughtspot/formula.py` | Shallow ThoughtSpot-formula tokenizer: outer call → `(name, args)`; find and rewrite `[TABLE::Column]` references. Not a parser. |
| `src/ossie_thoughtspot/datatypes.py` | The datatype map, both directions, plus the inference rule for a missing type. |
| `src/ossie_thoughtspot/tml.py` | TML document-set load/dump: the 1+N split, YAML 1.2, the R2/R9/R10/R11 serialisation invariants. Knows nothing about Ossie. |
| `src/ossie_thoughtspot/tml_to_ossie.py` | Forward direction. |
| `src/ossie_thoughtspot/ossie_to_thoughtspot.py` | Reverse direction. |
| `src/ossie_thoughtspot/cli.py` | `ossie-thoughtspot` console entry point. |

Test files mirror them one-to-one, plus `tests/fixtures/` and the two round-trip suites.

`tml.py` deliberately has no Ossie vocabulary and `datatypes.py`/`formula.py` have neither
side's document model — so all three are unit-testable without a fixture.

---

### Task 1: `formula.py` — shallow ThoughtSpot-formula tokenizer

A tokenizer, deliberately **not** a parser. It answers three questions the rest of the
converter needs and nothing more: is this expression a single outer function call and if so
what are its name and arguments; where are its column references; and what does it look like
with those references rewritten.

**Files:**
- Create: `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/src/ossie_thoughtspot/formula.py`
- Test: `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/tests/test_formula.py`

**Interfaces:**
- Consumes: `identifiers.split_column_ref`, `identifiers.format_column_ref`.
- Produces, and later tasks depend on these exact signatures:

```python
def split_call(expression: str) -> tuple[str, list[str]] | None
def find_column_refs(expression: str) -> list[tuple[str, str]]
def find_parameter_refs(expression: str) -> list[str]
def rewrite_column_refs(expression: str, rename: Callable[[str, str], str]) -> str
def is_bare_column_ref(expression: str) -> tuple[str, str] | None
```

**Why a tokenizer is enough.** `translate_thoughtspot(name, args, …)` already takes a
decomposed call. Reference rewriting (ID3) needs reference positions. Nothing else in
either direction needs an expression tree, and building one would be the SQL-parser
decision that Global Constraint 9 rules out.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from ossie_thoughtspot.formula import (
    find_column_refs, find_parameter_refs, is_bare_column_ref,
    rewrite_column_refs, split_call,
)


class TestSplitCall:
    def test_simple_call(self):
        assert split_call("sum ( [ORDERS::Amount] )") == ("sum", ["[ORDERS::Amount]"])

    def test_no_space_before_paren(self):
        assert split_call("sum([ORDERS::Amount])") == ("sum", ["[ORDERS::Amount]"])

    def test_multiple_arguments(self):
        name, args = split_call("concat ( [A::x] , '-' , [A::y] )")
        assert name == "concat"
        assert args == ["[A::x]", "'-'", "[A::y]"]

    def test_nested_call_is_one_argument(self):
        name, args = split_call("sum ( if ( [A::x] > 0 ) then [A::x] else 0 )")
        assert name == "sum"
        assert args == ["if ( [A::x] > 0 ) then [A::x] else 0"]

    def test_comma_inside_nested_parens_does_not_split(self):
        name, args = split_call("round ( divide ( [A::x] , [A::y] ) , 2 )")
        assert args == ["divide ( [A::x] , [A::y] )", "2"]

    def test_comma_inside_a_quoted_literal_does_not_split(self):
        name, args = split_call("concat ( [A::x] , ', ' , [A::y] )")
        assert args == ["[A::x]", "', '", "[A::y]"]

    def test_brace_group_is_one_argument(self):
        # The documented window shape: braces are ThoughtSpot's grouping syntax
        # and no SQL parser handles them, which is half the reason we tokenize.
        name, args = split_call(
            "last_value ( sum ( [T::c] ) , query_groups ( ) , { [D::date] } )"
        )
        assert name == "last_value"
        assert args == ["sum ( [T::c] )", "query_groups ( )", "{ [D::date] }"]

    def test_empty_argument_list(self):
        assert split_call("query_groups ( )") == ("query_groups", [])

    def test_not_a_call_returns_none(self):
        assert split_call("[ORDERS::Amount]") is None
        assert split_call("42") is None

    def test_expression_that_merely_contains_a_call_is_not_a_single_call(self):
        # `sum(a) + 1` has a call in it but is not one — a caller that treated
        # it as `("sum", ["a"])` would silently drop the `+ 1`.
        assert split_call("sum ( [A::x] ) + 1") is None

    def test_two_calls_side_by_side_is_not_a_single_call(self):
        assert split_call("sum ( [A::x] ) / count ( [A::y] )") is None

    def test_unbalanced_parens_return_none_rather_than_raising(self):
        assert split_call("sum ( [A::x]") is None


class TestFindColumnRefs:
    def test_finds_each_reference_in_order(self):
        assert find_column_refs("[A::x] + [B::y]") == [("A", "x"), ("B", "y")]

    def test_keeps_duplicates(self):
        assert find_column_refs("[A::x] + [A::x]") == [("A", "x"), ("A", "x")]

    def test_ignores_a_parameter_reference(self):
        # `[Growth Rate]` has no `::` — it is a runtime parameter, not a column.
        assert find_column_refs("[A::x] * [Growth Rate]") == [("A", "x")]

    def test_no_references(self):
        assert find_column_refs("42") == []


class TestFindParameterRefs:
    def test_finds_bracketed_names_without_a_table_qualifier(self):
        assert find_parameter_refs("[A::x] * [Growth Rate]") == ["Growth Rate"]

    def test_returns_empty_when_every_reference_is_qualified(self):
        assert find_parameter_refs("[A::x] + [B::y]") == []


class TestIsBareColumnRef:
    def test_a_lone_reference(self):
        assert is_bare_column_ref("[ORDERS::Amount]") == ("ORDERS", "Amount")

    def test_surrounding_whitespace_is_tolerated(self):
        assert is_bare_column_ref("  [ORDERS::Amount]  ") == ("ORDERS", "Amount")

    def test_anything_more_is_not_bare(self):
        assert is_bare_column_ref("[ORDERS::Amount] + 1") is None
        assert is_bare_column_ref("sum ( [ORDERS::Amount] )") is None
        assert is_bare_column_ref("[Growth Rate]") is None


class TestRewriteColumnRefs:
    def test_rewrites_every_reference(self):
        out = rewrite_column_refs(
            "[A::x] + [B::y]", lambda t, c: f"{t.lower()}.{c.lower()}"
        )
        assert out == "a.x + b.y"

    def test_leaves_a_parameter_reference_untouched(self):
        out = rewrite_column_refs(
            "[A::x] * [Growth Rate]", lambda t, c: f"{t.lower()}.{c.lower()}"
        )
        assert out == "a.x * [Growth Rate]"

    def test_preserves_everything_between_references_byte_for_byte(self):
        src = "concat ( [A::x] ,   ', '  , [A::y] )"
        out = rewrite_column_refs(src, lambda t, c: f"{t}.{c}")
        assert out == "concat ( A.x ,   ', '  , A.y )"

    def test_rewriting_is_not_confused_by_a_bracket_inside_a_literal(self):
        src = "concat ( [A::x] , '[not::a::ref]' )"
        out = rewrite_column_refs(src, lambda t, c: f"{t}.{c}")
        assert out == "concat ( A.x , '[not::a::ref]' )"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot && uv run --python 3.13 pytest tests/test_formula.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'ossie_thoughtspot.formula'`.

- [ ] **Step 3: Implement the module**

Copy the ASF header from `identifiers.py`, then:

```python
"""A shallow tokenizer for ThoughtSpot formulas.

Deliberately not a parser. It answers only what the two conversion directions need: is an
expression a single outer call and what are its parts, where are its column references, and
what does it look like with those references rewritten. Building an expression tree would be
the SQL-parser decision this converter does not take — expressions pass through under a
tagged dialect rather than being translated across dialects, matching every other converter
in this repository and the specification's stated default.

Three ThoughtSpot syntax features drive the implementation and are why an off-the-shelf SQL
tokenizer is not usable here: column references are bracketed and doubly-colon-qualified
(`[TABLE::Column]`), grouping uses braces (`{ }`), and a bare bracketed name with no `::` is
a runtime parameter rather than a column.
"""
from __future__ import annotations

import re
from typing import Callable

_CALL_HEAD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*(?:\s+[A-Za-z_][A-Za-z0-9_]*)*)\s*\(")
_BRACKETED = re.compile(r"\[([^\]]*)\]")
_CLOSERS = {"(": ")", "[": "]", "{": "}"}
_QUOTES = ("'", '"')


def _scan(text: str):
    """Yield `(index, char, depth, in_quote)` with depth counted before the char is applied.

    One pass shared by every function here so that quoting and nesting are treated
    identically everywhere — a divergence between two hand-rolled scanners is exactly the
    kind of bug that would surface as a mis-split argument list months later.
    """
    depth = 0
    quote: str | None = None
    for i, ch in enumerate(text):
        if quote is not None:
            yield i, ch, depth, True
            if ch == quote:
                quote = None
            continue
        if ch in _QUOTES:
            quote = ch
            yield i, ch, depth, True
            continue
        if ch in _CLOSERS:
            yield i, ch, depth, False
            depth += 1
            continue
        if ch in (")", "]", "}"):
            depth -= 1
            yield i, ch, depth, False
            continue
        yield i, ch, depth, False


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for i, ch, depth, in_quote in _scan(text):
        if ch == "," and depth == 0 and not in_quote:
            parts.append(text[start:i].strip())
            start = i + 1
    tail = text[start:].strip()
    if tail or parts:
        parts.append(tail)
    return parts


def split_call(expression: str) -> tuple[str, list[str]] | None:
    """`sum ( [A::x] , 2 )` -> `("sum", ["[A::x]", "2"])`; `None` if not a single outer call.

    Returns `None` — never a partial answer — for anything that merely *contains* a call,
    such as `sum ( [A::x] ) + 1`. A caller that received `("sum", ["[A::x]"])` for that
    input would silently drop the `+ 1`, which is precisely the class of silent loss this
    converter exists to prevent.
    """
    text = expression.strip()
    head = _CALL_HEAD.match(text)
    if head is None:
        return None
    open_at = head.end() - 1
    close_at = None
    for i, ch, depth, in_quote in _scan(text[open_at:]):
        if ch == ")" and depth == 0 and not in_quote:
            close_at = open_at + i
            break
    if close_at is None:
        return None
    if close_at != len(text) - 1:
        return None
    inner = text[open_at + 1 : close_at].strip()
    if not inner:
        return head.group(1), []
    return head.group(1), _split_top_level_commas(inner)


def _bracketed_spans(expression: str) -> list[tuple[int, int, str]]:
    """Every `[...]` span that is not inside a quoted literal, as `(start, end, body)`."""
    quoted = {i for i, _ch, _d, in_quote in _scan(expression) if in_quote}
    return [
        (m.start(), m.end(), m.group(1))
        for m in _BRACKETED.finditer(expression)
        if m.start() not in quoted
    ]


def find_column_refs(expression: str) -> list[tuple[str, str]]:
    """Every `[TABLE::Column]` reference, in order, duplicates kept.

    A bracketed name with no `::` is a runtime parameter, not a column — see
    `find_parameter_refs`.
    """
    return [
        (body.split("::", 1)[0], body.split("::", 1)[1])
        for _s, _e, body in _bracketed_spans(expression)
        if "::" in body
    ]


def find_parameter_refs(expression: str) -> list[str]:
    """Every bracketed name with no table qualifier — a ThoughtSpot runtime parameter.

    Ossie has no equivalent, so an expression carrying one is not portable and the caller
    raises an issue rather than emitting a portable sibling.
    """
    return [body for _s, _e, body in _bracketed_spans(expression) if "::" not in body]


def is_bare_column_ref(expression: str) -> tuple[str, str] | None:
    """`(table, column)` when the whole expression is one column reference, else `None`.

    The common case by a wide margin: most fields are physical columns, and this is what
    lets those fields carry a portable sibling for free.
    """
    text = expression.strip()
    spans = _bracketed_spans(text)
    if len(spans) != 1:
        return None
    start, end, body = spans[0]
    if start != 0 or end != len(text) or "::" not in body:
        return None
    table, column = body.split("::", 1)
    return table, column


def rewrite_column_refs(
    expression: str, rename: Callable[[str, str], str]
) -> str:
    """Replace each `[TABLE::Column]` with `rename(table, column)`, byte-preserving elsewhere.

    Everything between references — whitespace, literals, operators — is copied verbatim, so
    an expression whose references are unchanged is returned unchanged. Parameter references
    and bracketed text inside quoted literals are left alone.
    """
    out: list[str] = []
    cursor = 0
    for start, end, body in _bracketed_spans(expression):
        if "::" not in body:
            continue
        table, column = body.split("::", 1)
        out.append(expression[cursor:start])
        out.append(rename(table, column))
        cursor = end
    out.append(expression[cursor:])
    return "".join(out)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot && uv run --python 3.13 pytest tests/test_formula.py -q`
Expected: all pass.

- [ ] **Step 5: Confirm the whole suite still passes**

Run: `cd /Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot && uv run --python 3.13 pytest tests/ -q`
Expected: 289 prior + the new ones.

- [ ] **Step 6: Commit**

```bash
cd /Users/damianwaldron/Dev/ts/ossie
git add converters/thoughtspot/src/ossie_thoughtspot/formula.py converters/thoughtspot/tests/test_formula.py
git commit -m "feat(thoughtspot): shallow formula tokenizer for reference rewriting and call splitting"
```

---

### Task 2: `datatypes.py` — the bidirectional datatype map

**Files:**
- Create: `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/src/ossie_thoughtspot/datatypes.py`
- Test: `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/tests/test_datatypes.py`

**Read first:** the *Datatype map* section of the construct-mapping document (absolute path
in the header). Its table is the specification for this module; transcribe it, do not
reinvent it.

**Interfaces — later tasks depend on these exact signatures:**

```python
OSSIE_DATATYPES: frozenset[str]              # the closed 10-value Ossie enum
def to_tml(datatype: str | None, *, boolean_spelling: str = "BOOLEAN",
           float_spelling: str = "DOUBLE") -> str
def to_ossie(tml_type: str) -> str | None
def declared_loss(datatype: str) -> str | None
```

**The three things that make this more than a dict.**

1. **The map is not injective.** `Decimal` and `Float` both become `DOUBLE`; `Time`,
   `DateTimeTz` and `Opaque` collapse into types that do not carry them. Those are
   **declared losses** — `declared_loss` names each so the caller can raise the issue
   rather than each caller rediscovering which are lossy.
2. **Two types have a connection-dependent spelling.** `BOOLEAN`/`BOOL` and
   `DOUBLE`/`FLOAT`. The chosen spelling is stashed by the forward direction so the return
   trip re-emits the same one; the parameters exist for that.
3. **`Ossie → TML` may not omit the type.** Every Table column needs
   `db_column_properties.data_type` or ThoughtSpot rejects the import with `Compulsory
   Field table->columns->db_column_properties is not populated`. A field with no
   `datatype` therefore gets one inferred — `INT64` per the document's guidance — and
   `to_tml(None)` returns it rather than raising.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from ossie_thoughtspot.datatypes import (
    OSSIE_DATATYPES, declared_loss, to_ossie, to_tml,
)


class TestToTml:
    @pytest.mark.parametrize("datatype,expected", [
        ("String", "VARCHAR"), ("Integer", "INT64"), ("Decimal", "DOUBLE"),
        ("Float", "DOUBLE"), ("Boolean", "BOOLEAN"), ("Date", "DATE"),
        ("Time", "VARCHAR"), ("DateTime", "DATE_TIME"),
        ("DateTimeTz", "DATE_TIME"), ("Opaque", "VARCHAR"),
    ])
    def test_every_ossie_datatype_maps(self, datatype, expected):
        assert to_tml(datatype) == expected

    def test_the_map_covers_the_whole_enum(self):
        # A datatype added to the Ossie enum must fail here, not silently
        # convert to nothing.
        for datatype in OSSIE_DATATYPES:
            assert to_tml(datatype)

    def test_missing_datatype_infers_rather_than_raising(self):
        # Ossie makes datatype optional; TML makes db_column_properties compulsory.
        assert to_tml(None) == "INT64"

    def test_connection_spellings_are_selectable(self):
        assert to_tml("Boolean", boolean_spelling="BOOL") == "BOOL"
        assert to_tml("Float", float_spelling="FLOAT") == "FLOAT"

    def test_the_float_spelling_does_not_leak_into_decimal(self):
        # Decimal is DOUBLE on every connection — only Float is BigQuery-sensitive.
        assert to_tml("Decimal", float_spelling="FLOAT") == "DOUBLE"

    def test_an_unknown_datatype_raises(self):
        with pytest.raises(ValueError, match="Nonsense"):
            to_tml("Nonsense")


class TestToOssie:
    @pytest.mark.parametrize("tml_type,expected", [
        ("VARCHAR", "String"), ("INT64", "Integer"), ("DOUBLE", "Decimal"),
        ("FLOAT", "Float"), ("BOOL", "Boolean"), ("BOOLEAN", "Boolean"),
        ("DATE", "Date"), ("DATE_TIME", "DateTime"),
    ])
    def test_known_tml_types(self, tml_type, expected):
        assert to_ossie(tml_type) == expected

    def test_an_unknown_tml_type_returns_none_rather_than_guessing(self):
        # datatype is optional in Ossie, so omitting it is a legitimate answer
        # and strictly better than inventing one.
        assert to_ossie("GEOGRAPHY") is None

    def test_sql_type_names_are_not_accepted(self):
        # ThoughtSpot rejects these itself: "DataType BIGINT does not match CDW DataType".
        assert to_ossie("BIGINT") is None


class TestDeclaredLoss:
    @pytest.mark.parametrize("datatype", ["Float", "Time", "DateTimeTz", "Opaque"])
    def test_the_four_lossy_types_are_named(self, datatype):
        assert declared_loss(datatype)

    @pytest.mark.parametrize("datatype", ["String", "Integer", "Decimal",
                                          "Boolean", "Date", "DateTime"])
    def test_the_lossless_types_are_not(self, datatype):
        assert declared_loss(datatype) is None

    def test_round_trip_is_exact_for_every_non_lossy_type(self):
        # The property that makes `declared_loss` trustworthy: if it says a type
        # is lossless, TML -> Ossie -> TML really does return the same value.
        for datatype in OSSIE_DATATYPES:
            if declared_loss(datatype) is None:
                assert to_ossie(to_tml(datatype)) == datatype
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot && uv run --python 3.13 pytest tests/test_datatypes.py -q`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

ASF header, then:

```python
"""The ThoughtSpot <-> Ossie datatype map, transcribed from the construct-mapping document.

Three properties of the map shape this module's surface. It is **not injective** — Decimal
and Float both become DOUBLE, and Time, DateTimeTz and Opaque collapse into types that
cannot carry them — so `declared_loss` names the types whose round trip is lossy in one
place rather than leaving each caller to rediscover them. Two types have a
**connection-dependent spelling** (BOOLEAN/BOOL, DOUBLE/FLOAT), which the forward direction
records so the return trip re-emits the same one. And `datatype` is **optional in Ossie but
compulsory in TML** — ThoughtSpot rejects a table whose column has no
`db_column_properties`, so `to_tml(None)` infers rather than raising.
"""
from __future__ import annotations

#: The closed Ossie datatype enum (core specification).
OSSIE_DATATYPES = frozenset({
    "String", "Integer", "Decimal", "Float", "Boolean",
    "Date", "Time", "DateTime", "DateTimeTz", "Opaque",
})

#: Ossie datatype -> the TML `data_type` written for it.
_TO_TML = {
    "String": "VARCHAR",
    "Integer": "INT64",
    "Decimal": "DOUBLE",
    "Float": "DOUBLE",
    "Boolean": "BOOLEAN",
    "Date": "DATE",
    "Time": "VARCHAR",
    "DateTime": "DATE_TIME",
    "DateTimeTz": "DATE_TIME",
    "Opaque": "VARCHAR",
}

#: TML `data_type` -> the Ossie datatype emitted for it. Deliberately not the inverse of
#: `_TO_TML`: DOUBLE comes back as Decimal and VARCHAR as String, which is what makes the
#: types in `_DECLARED_LOSS` lossy.
_TO_OSSIE = {
    "VARCHAR": "String",
    "INT64": "Integer",
    "DOUBLE": "Decimal",
    "FLOAT": "Float",
    "BOOL": "Boolean",
    "BOOLEAN": "Boolean",
    "DATE": "Date",
    "DATE_TIME": "DateTime",
}

#: Types whose `Ossie -> TML -> Ossie` trip cannot return the original, and why. Per rule X9
#: none of these can be rescued by the stash: the stash is written from a TML document, and
#: TML never held the distinction in the first place.
_DECLARED_LOSS = {
    "Float": "ThoughtSpot has one approximate numeric type, so Float and Decimal both "
             "become DOUBLE and return as Decimal.",
    "Time": "ThoughtSpot has no time-of-day column type; the value becomes VARCHAR.",
    "DateTimeTz": "ThoughtSpot has no offset-aware column type; the value becomes "
                  "DATE_TIME and returns as DateTime.",
    "Opaque": "Opaque is Ossie's marker for a type outside the portable vocabulary; it "
              "becomes VARCHAR and returns as String.",
}

#: What a column with no declared datatype becomes. The Table TML reference advises
#: preferring INT64 and letting ThoughtSpot report a mismatch, over omitting the block.
_INFERRED = "INT64"


def to_tml(datatype: str | None, *, boolean_spelling: str = "BOOLEAN",
           float_spelling: str = "DOUBLE") -> str:
    """The TML `data_type` for an Ossie datatype. `None` infers rather than raising."""
    if datatype is None:
        return _INFERRED
    if datatype not in _TO_TML:
        raise ValueError(f"{datatype!r} is not an Ossie datatype")
    if datatype == "Boolean":
        return boolean_spelling
    if datatype == "Float":
        return float_spelling
    return _TO_TML[datatype]


def to_ossie(tml_type: str) -> str | None:
    """The Ossie datatype for a TML `data_type`, or `None` when there is no mapping.

    `None` is a legitimate answer, not a failure: `datatype` is optional in Ossie, so
    omitting it is strictly better than inventing one for a type outside the map.
    """
    return _TO_OSSIE.get(tml_type)


def declared_loss(datatype: str) -> str | None:
    """Why this datatype's round trip is lossy, or `None` when it is exact."""
    return _DECLARED_LOSS.get(datatype)
```

- [ ] **Step 4: Run the tests** — all pass.
- [ ] **Step 5: Run the whole suite** — no regressions.
- [ ] **Step 6: Commit**

```bash
cd /Users/damianwaldron/Dev/ts/ossie
git add converters/thoughtspot/src/ossie_thoughtspot/datatypes.py converters/thoughtspot/tests/test_datatypes.py
git commit -m "feat(thoughtspot): bidirectional datatype map with declared losses named"
```

---

### Task 3: `tml.py` — the TML document set

TML's structural half, with no Ossie vocabulary in it at all: loading a 1+N document set,
and serialising one back under the invariants that make it importable.

**Files:**
- Create: `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/src/ossie_thoughtspot/tml.py`
- Test: `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/tests/test_tml.py`

**Read first:** rules **R1, R2, R5, R9, R10, R11** in the *Reverse-direction rules* section
of the construct-mapping document.

**Interfaces:**

```python
@dataclass(frozen=True)
class TmlDocument:
    kind: str                      # "model" | "table" | "sql_view"
    body: dict                     # the contents under the kind key
    guid: str | None               # as read; never written back (R2)
    source: str | None = None      # a path or label, for issue messages

@dataclass(frozen=True)
class DocumentSet:
    model: TmlDocument
    tables: tuple[TmlDocument, ...]
    def table_by_name(self, name: str) -> TmlDocument | None

def load_document(text: str, *, source: str | None = None) -> TmlDocument
def load_document_set(texts: Sequence[tuple[str, str]]) -> DocumentSet
def dump_document(document: TmlDocument) -> str
def dump_document_set(document_set: DocumentSet) -> list[tuple[str, str]]
def block_scalar(text: str) -> str        # marks a value for `>-` emission (R9)
```

**Four invariants this module owns**, so that no later task has to remember them:

- **R2 — `guid` is read but never written.** It goes at the *document root*, never nested.
  A nested `guid:` is silently ignored and ThoughtSpot creates a duplicate object, which is
  the most common cause of "my update created a second model". Generated TML omits it
  entirely.
- **R9 — a formula `expr` containing `{ }` must be a `>-` block scalar** or the YAML fails
  to parse. `block_scalar` marks such a value; the dumper honours the mark.
- **R10 — tables are emitted before the model.** The Model references each table by name,
  so ordering is load-bearing, and `dump_document_set` returns them in that order.
- **R11 — YAML 1.2 throughout.** Delegated to `_yaml`; the test below pins it so a future
  change to that module cannot silently reintroduce 1.1 boolean coercion here.

**Note on R5.** The `'on':` quoting that R5 requires is already produced by `_yaml`'s dumper,
which quotes every YAML-1.1-only boolean token including `on` — as a key as well as a value.
A test below pins that, because it is currently a happy accident of another module and the
next reader should be told rather than left to discover it.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from ossie_thoughtspot import _yaml
from ossie_thoughtspot.errors import ConversionError
from ossie_thoughtspot.tml import (
    DocumentSet, TmlDocument, block_scalar, dump_document,
    dump_document_set, load_document, load_document_set,
)

TABLE = """\
guid: tbl-orders-001
table:
  name: ORDERS
  db: SALES
  schema: PUBLIC
  columns:
  - name: AMOUNT
    db_column_name: AMOUNT
    properties:
      column_type: MEASURE
    db_column_properties:
      data_type: DOUBLE
"""

MODEL = """\
guid: model-001
model:
  name: Sales
  model_tables:
  - name: ORDERS
  formulas:
  - id: formula_Revenue
    name: Revenue
    expr: sum ( [ORDERS::AMOUNT] )
  columns:
  - name: Revenue
    formula_id: formula_Revenue
    properties:
      column_type: MEASURE
"""


class TestLoad:
    def test_detects_a_table_document(self):
        doc = load_document(TABLE)
        assert doc.kind == "table"
        assert doc.body["name"] == "ORDERS"
        assert doc.guid == "tbl-orders-001"

    def test_detects_a_model_document(self):
        assert load_document(MODEL).kind == "model"

    def test_a_document_with_no_recognised_root_key_raises(self):
        with pytest.raises(ConversionError, match="not a TML document"):
            load_document("answer:\n  name: Nope\n")

    def test_a_document_with_two_root_kinds_raises(self):
        with pytest.raises(ConversionError, match="more than one"):
            load_document("table:\n  name: A\nmodel:\n  name: B\n")

    def test_yaml_1_1_boolean_tokens_survive_as_strings(self):
        # R11. A column really can be called `on`.
        doc = load_document("table:\n  name: T\n  columns:\n  - name: 'on'\n")
        assert doc.body["columns"][0]["name"] == "on"


class TestLoadDocumentSet:
    def test_splits_the_model_from_the_tables(self):
        ds = load_document_set([("orders.table.tml", TABLE), ("sales.model.tml", MODEL)])
        assert ds.model.body["name"] == "Sales"
        assert [t.body["name"] for t in ds.tables] == ["ORDERS"]

    def test_order_of_input_does_not_matter(self):
        ds = load_document_set([("sales.model.tml", MODEL), ("orders.table.tml", TABLE)])
        assert ds.model.body["name"] == "Sales"

    def test_table_lookup_by_name(self):
        ds = load_document_set([("o", TABLE), ("m", MODEL)])
        assert ds.table_by_name("ORDERS").body["db"] == "SALES"
        assert ds.table_by_name("MISSING") is None

    def test_no_model_raises(self):
        with pytest.raises(ConversionError, match="no model document"):
            load_document_set([("o", TABLE)])

    def test_two_models_raise(self):
        with pytest.raises(ConversionError, match="more than one model"):
            load_document_set([("m1", MODEL), ("m2", MODEL)])


class TestDump:
    def test_guid_is_never_written(self):
        # R2 — the single most consequential invariant in this module.
        out = dump_document(load_document(TABLE))
        assert "guid" not in out
        assert "tbl-orders-001" not in out

    def test_the_kind_key_is_the_document_root(self):
        out = dump_document(load_document(TABLE))
        assert out.startswith("table:")

    def test_a_brace_expression_is_written_as_a_block_scalar(self):
        # R9 — a plain scalar here fails to parse on re-read.
        doc = TmlDocument(kind="model", body={
            "name": "M",
            "formulas": [{"id": "formula_X", "name": "X",
                          "expr": block_scalar("last_value ( sum ( [T::c] ) , { [D::d] } )")}],
        }, guid=None)
        out = dump_document(doc)
        assert ">-" in out
        assert _yaml.load(out)["model"]["formulas"][0]["expr"].strip() == (
            "last_value ( sum ( [T::c] ) , { [D::d] } )"
        )

    def test_an_on_key_is_quoted(self):
        # R5 — `on` is a YAML 1.1 reserved word; unquoted it becomes True.
        doc = TmlDocument(kind="table", body={
            "name": "T",
            "joins_with": [{"name": "j", "on": "[A::x] = [B::y]",
                            "type": "INNER", "cardinality": "MANY_TO_ONE"}],
        }, guid=None)
        out = dump_document(doc)
        assert "'on':" in out
        assert _yaml.load(out)["table"]["joins_with"][0]["on"] == "[A::x] = [B::y]"

    def test_round_trips_through_load(self):
        doc = load_document(TABLE)
        assert load_document(dump_document(doc)).body == doc.body


class TestDumpDocumentSet:
    def test_tables_come_before_the_model(self):
        # R10 — the model references tables by name, so they must exist first.
        ds = load_document_set([("m", MODEL), ("o", TABLE)])
        names = [name for name, _text in dump_document_set(ds)]
        assert names == ["ORDERS.table.tml", "Sales.model.tml"]

    def test_every_emitted_document_reloads(self):
        ds = load_document_set([("o", TABLE), ("m", MODEL)])
        for _name, text in dump_document_set(ds):
            load_document(text)
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**

ASF header, then:

```python
"""TML's structural half: the 1+N document set, and the serialisation invariants.

Deliberately holds no Ossie vocabulary — it is the ThoughtSpot file format and nothing else,
which is what makes it unit-testable without a fixture from the other side.

Four invariants live here so no caller has to carry them. `guid` is read and never written
(R2): it belongs at the document root, and a nested one is *silently ignored* while
ThoughtSpot creates a duplicate object. A formula expression containing braces is emitted as
a `>-` block scalar (R9) or the YAML will not parse on re-read. Tables are emitted before the
model (R10), which references them by name. And everything goes through the YAML 1.2 codec
(R11) so a column named `on` survives.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import yaml

from . import _yaml
from .errors import ConversionError

#: The TML root keys this converter handles. Ossie's scope is the semantic model, so
#: answers, liveboards and the rest are not merely unsupported but out of scope.
_KINDS = ("model", "table", "sql_view")

#: Filename suffix per kind, matching ThoughtSpot's own export convention.
_SUFFIX = {"model": "model.tml", "table": "table.tml", "sql_view": "sql_view.tml"}


class _BlockScalar(str):
    """A string the dumper must emit as a folded block scalar. See `block_scalar`."""


def _represent_block(dumper: yaml.SafeDumper, data: _BlockScalar) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style=">")


yaml.add_representer(_BlockScalar, _represent_block, Dumper=_yaml.Yaml12Dumper)


def block_scalar(text: str) -> str:
    """Mark `text` for `>-` emission (R9). Returns a `str`, so callers need not care."""
    return _BlockScalar(text)


@dataclass(frozen=True)
class TmlDocument:
    kind: str
    body: dict
    guid: str | None
    source: str | None = None


@dataclass(frozen=True)
class DocumentSet:
    model: TmlDocument
    tables: tuple[TmlDocument, ...]

    def table_by_name(self, name: str) -> TmlDocument | None:
        """The table or SQL view whose `name` matches, or `None`.

        Model `model_tables[]` entries reference a table by this name (or by an `alias`
        that the caller resolves first), so this is the join between the two documents.
        """
        for table in self.tables:
            if table.body.get("name") == name:
                return table
        return None


def load_document(text: str, *, source: str | None = None) -> TmlDocument:
    """Parse one TML document. Raises `ConversionError` rather than a bare YAML error."""
    data = _yaml.load(text)
    if not isinstance(data, dict):
        raise ConversionError(f"{source or '<input>'} is not a TML document: expected a mapping")
    present = [kind for kind in _KINDS if kind in data]
    if not present:
        raise ConversionError(
            f"{source or '<input>'} is not a TML document this converter handles: "
            f"expected one of {', '.join(_KINDS)} at the root"
        )
    if len(present) > 1:
        raise ConversionError(
            f"{source or '<input>'} declares more than one root kind ({', '.join(present)})"
        )
    kind = present[0]
    body = data[kind]
    if not isinstance(body, dict):
        raise ConversionError(f"{source or '<input>'}: {kind} must be a mapping")
    return TmlDocument(kind=kind, body=body, guid=data.get("guid"), source=source)


def load_document_set(texts: Sequence[tuple[str, str]]) -> DocumentSet:
    """Load `(source, text)` pairs into exactly one model plus its tables, in any order."""
    documents = [load_document(text, source=source) for source, text in texts]
    models = [d for d in documents if d.kind == "model"]
    tables = tuple(d for d in documents if d.kind in ("table", "sql_view"))
    if not models:
        raise ConversionError("the document set contains no model document")
    if len(models) > 1:
        names = ", ".join(str(m.body.get("name")) for m in models)
        raise ConversionError(f"the document set contains more than one model document: {names}")
    return DocumentSet(model=models[0], tables=tables)


def dump_document(document: TmlDocument) -> str:
    """Serialise one document. `guid` is omitted unconditionally (R2)."""
    return _yaml.dump({document.kind: document.body})


def dump_document_set(document_set: DocumentSet) -> list[tuple[str, str]]:
    """`(filename, text)` for every document, tables first (R10)."""
    out = [
        (f"{table.body.get('name', 'table')}.{_SUFFIX[table.kind]}", dump_document(table))
        for table in document_set.tables
    ]
    model = document_set.model
    out.append((f"{model.body.get('name', 'model')}.{_SUFFIX['model']}", dump_document(model)))
    return out
```

- [ ] **Step 4: Run the tests** — all pass.
- [ ] **Step 5: Run the whole suite** — no regressions.
- [ ] **Step 6: Commit**

```bash
cd /Users/damianwaldron/Dev/ts/ossie
git add converters/thoughtspot/src/ossie_thoughtspot/tml.py converters/thoughtspot/tests/test_tml.py
git commit -m "feat(thoughtspot): TML document set with the R2/R9/R10/R11 serialisation invariants"
```

---

## A note on the remaining tasks

Tasks 1–3 gave complete implementations because they are self-contained and their exact
shape matters to everything downstream. Tasks 4 onward specify **exact signatures and
complete tests**, plus the implementation of anything subtle, and leave mechanical assembly
to the implementer.

**The tests are the binding contract.** Where a task's prose and its tests disagree, the
tests win and the discrepancy is reported — this was settled in the previous plan after an
interface block and its tests specified three different signatures.

---

### Task 4: `tml_to_ossie` — fields and expression emission

The forward direction's hardest half, and the one where a mistake is silent rather than
loud. Converts a Model `columns[]` entry into an Ossie field, including the dialect entries.

**Files:**
- Create: `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/src/ossie_thoughtspot/tml_to_ossie.py`
- Test: `/Users/damianwaldron/Dev/ts/ossie/converters/thoughtspot/tests/test_tml_to_ossie_fields.py`

**Read first:** *Field and metric level → Fields*, and *Expression handling*, in the
construct-mapping document. Rules **ID1, ID3, X9**.

**Interfaces:**

```python
def expression_entries(
    expr: str, resolve: Callable[[str, str], str | None], log: IssueLog, *,
    object_ref: str,
) -> list[dict[str, str]]
def convert_field(
    column: dict, table_lookup: Callable[[str], dict | None],
    resolve: Callable[[str, str], str | None], log: IssueLog,
) -> dict | None
```

**The four rules that make this subtle.**

1. **The `THOUGHTSPOT` entry carries the formula verbatim** — the exact `expr` string from
   the TML, not a reconstruction (Global Constraint 9, PD7). Upstream's round-trip bar is
   exact string equality.
2. **A portable `ANSI_SQL` sibling is emitted only when it is free or certain**: a bare
   column reference, or an expression the catalog matches whole. Never a guess.
3. **`ID1` splits the name.** `field.name` is the normalised identifier; the exact display
   name goes in `field.label`. Do not put the display name in `name`.
4. **A computed field must be attributed to a dataset** — the one all its references
   resolve to. When they span two or more there is no correct answer, so the converter
   raises an issue and stashes the formula in `unattributed_formulas`. **It does not
   guess**, and it does not pick the first.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from ossie_thoughtspot.issues import IssueLog
from ossie_thoughtspot.tml_to_ossie import convert_field, expression_entries

def _resolve(table, column):
    """Test resolver: every reference lands in dataset `orders` unless prefixed OTHER."""
    return None if table == "MISSING" else f"{table.lower()}.{column.lower()}"


class TestExpressionEntries:
    def test_a_bare_reference_gets_both_dialects(self):
        log = IssueLog()
        out = expression_entries("[ORDERS::Amount]", _resolve, log, object_ref="f")
        assert out == [
            {"dialect": "THOUGHTSPOT", "expression": "[ORDERS::Amount]"},
            {"dialect": "ANSI_SQL", "expression": "orders.amount"},
        ]
        assert log.as_dicts() == []

    def test_the_thoughtspot_entry_is_byte_for_byte_the_input(self):
        # PD7. A reconstruction would normalise this to `sum ( [ORDERS::Amount] )`
        # and break upstream's exact-string round-trip bar.
        log = IssueLog()
        out = expression_entries("sum([ORDERS::Amount])", _resolve, log, object_ref="f")
        assert out[0] == {"dialect": "THOUGHTSPOT", "expression": "sum([ORDERS::Amount])"}

    def test_a_computed_expression_gets_a_thoughtspot_entry_and_an_issue(self):
        log = IssueLog()
        out = expression_entries(
            "sum ( [ORDERS::Amount] ) / count ( [ORDERS::Id] )", _resolve, log, object_ref="f"
        )
        assert [e["dialect"] for e in out] == ["THOUGHTSPOT"]
        assert len(log.as_dicts()) == 1

    def test_a_parameter_reference_blocks_the_portable_sibling(self):
        # A runtime parameter has no Ossie equivalent, so the expression is not portable
        # however simple it looks.
        log = IssueLog()
        out = expression_entries("[ORDERS::Amount] * [Growth Rate]", _resolve, log, object_ref="f")
        assert [e["dialect"] for e in out] == ["THOUGHTSPOT"]
        assert any("parameter" in i["message"].lower() for i in log.as_dicts())

    def test_an_unresolvable_reference_blocks_the_portable_sibling(self):
        log = IssueLog()
        out = expression_entries("[MISSING::Col]", _resolve, log, object_ref="f")
        assert [e["dialect"] for e in out] == ["THOUGHTSPOT"]
        assert log.as_dicts()

    def test_the_thoughtspot_entry_is_always_present(self):
        # The invariant the whole round trip rests on: whatever else happens,
        # the original survives.
        log = IssueLog()
        for expr in ["[A::x]", "sum ( [A::x] )", "gibberish ( (", "[Param]"]:
            out = expression_entries(expr, _resolve, log, object_ref="f")
            assert out[0]["dialect"] == "THOUGHTSPOT"
            assert out[0]["expression"] == expr


class TestConvertField:
    def _table(self, name):
        return {"ORDERS": {"name": "ORDERS", "columns": [
            {"name": "AMOUNT", "db_column_name": "AMOUNT",
             "db_column_properties": {"data_type": "DOUBLE"}},
        ]}}.get(name)

    def test_a_physical_column_becomes_a_field(self):
        log = IssueLog()
        field = convert_field(
            {"name": "Order Amount", "column_id": "ORDERS::AMOUNT",
             "properties": {"column_type": "ATTRIBUTE"}},
            self._table, _resolve, log,
        )
        assert field["name"] == "order_amount"      # ID1 normalised
        assert field["label"] == "Order Amount"      # ID1 exact display name
        assert field["datatype"] == "Decimal"        # DOUBLE -> Decimal

    def test_description_round_trips_without_a_stash(self):
        log = IssueLog()
        field = convert_field(
            {"name": "Amount", "column_id": "ORDERS::AMOUNT", "description": "How much",
             "properties": {"column_type": "ATTRIBUTE"}},
            self._table, _resolve, log,
        )
        assert field["description"] == "How much"

    def test_synonyms_become_ai_context(self):
        log = IssueLog()
        field = convert_field(
            {"name": "Amount", "column_id": "ORDERS::AMOUNT",
             "properties": {"column_type": "ATTRIBUTE", "synonyms": ["total", "value"],
                            "synonym_type": "USER_DEFINED"}},
            self._table, _resolve, log,
        )
        assert field["ai_context"]["synonyms"] == ["total", "value"]

    def test_a_measure_column_is_not_a_field(self):
        # MEASURE columns become metrics, handled in the next task.
        log = IssueLog()
        assert convert_field(
            {"name": "Amount", "column_id": "ORDERS::AMOUNT",
             "properties": {"column_type": "MEASURE"}},
            self._table, _resolve, log,
        ) is None

    def test_is_time_is_omitted_when_the_type_already_implies_it(self):
        # The specification says is_time defaults from the datatype, so writing it
        # for a Date column is noise.
        log = IssueLog()
        table = lambda n: {"name": "ORDERS", "columns": [
            {"name": "DT", "db_column_name": "DT",
             "db_column_properties": {"data_type": "DATE"}}]}
        field = convert_field(
            {"name": "Order Date", "column_id": "ORDERS::DT",
             "properties": {"column_type": "ATTRIBUTE"}},
            table, _resolve, log,
        )
        assert "dimension" not in field or "is_time" not in field.get("dimension", {})

    def test_a_missing_physical_column_raises_an_issue_and_omits_the_datatype(self):
        log = IssueLog()
        field = convert_field(
            {"name": "Ghost", "column_id": "ORDERS::NOPE",
             "properties": {"column_type": "ATTRIBUTE"}},
            self._table, _resolve, log,
        )
        assert "datatype" not in field
        assert log.as_dicts()
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement.** The subtle parts, written out:

```python
def expression_entries(expr, resolve, log, *, object_ref):
    """Dialect entries for one ThoughtSpot expression: verbatim first, portable if certain.

    The THOUGHTSPOT entry is the input string unchanged — never a reconstruction from
    `(name, args)`. Upstream's round-trip assertion is exact string equality, and the return
    leg reads this entry, so preserving it byte for byte is what makes the round trip exact
    regardless of how well the portable sibling turned out.
    """
    entries = [{"dialect": DIALECT, "expression": expr}]

    parameters = formula.find_parameter_refs(expr)
    if parameters:
        log.add(code="TS-EXPR-PARAM", severity=Severity.WARNING,
                message=(f"expression references the ThoughtSpot runtime parameter(s) "
                         f"{', '.join(parameters)}, which have no Ossie equivalent; "
                         f"no portable expression is emitted"),
                object_ref=object_ref)
        return entries

    bare = formula.is_bare_column_ref(expr)
    if bare is not None:
        target = resolve(*bare)
        if target is None:
            log.add(code="TS-EXPR-UNRESOLVED", severity=Severity.WARNING,
                    message=f"reference {formula.format_column_ref(*bare)} resolves to no "
                            f"dataset field; no portable expression is emitted",
                    object_ref=object_ref)
            return entries
        entries.append({"dialect": PORTABLE_DIALECT, "expression": target})
        return entries

    # Anything else: the catalog does not give a whole-expression match without an
    # expression tree, and building one is the SQL-parser decision this converter does not
    # take. Record the non-portability rather than emitting a guess.
    log.add(code="TS-EXPR-THOUGHTSPOT-ONLY", severity=Severity.INFO,
            message="expression is emitted in the THOUGHTSPOT dialect only; a consumer that "
                    "does not implement it will not be able to evaluate this field",
            object_ref=object_ref)
    return entries
```

`convert_field` then: skip `column_type == "MEASURE"`; derive `name` via
`identifiers.normalise` and `label` from the verbatim `name` (ID1); build `expression` from
`expression_entries`; look the physical column up through `table_lookup` for
`db_column_properties.data_type` and map it with `datatypes.to_ossie`; carry `description`
straight across; fold `properties.synonyms` into `ai_context.synonyms` and
`properties.ai_context` into the string form. Emit `dimension.is_time` **only** when it
differs from the type-derived default — which, given a type-derived role, is never, so in
practice omit it.

- [ ] **Step 4–5: Tests pass; whole suite green.**
- [ ] **Step 6: Commit** — `feat(thoughtspot): convert TML columns to Ossie fields with verbatim dialect entries`

---

### Task 5: `tml_to_ossie` — metrics and aggregation composition

**Files:** modify `tml_to_ossie.py`; create `tests/test_tml_to_ossie_metrics.py`.

**Read first:** *Field and metric level → Metrics* in the construct-mapping document,
especially the aggregation row. Rule **R4**.

**Interfaces:**

```python
def convert_metric(
    column: dict, formulas: dict[str, dict],
    resolve: Callable[[str, str], str | None], log: IssueLog,
) -> dict | None
```

**The one genuinely tricky rule, and it is easy to get backwards.** A Model `columns[]`
entry can be a metric in two shapes, and the column-level `aggregation` means different
things in each:

| Shape | `aggregation` | What the metric expression is |
|---|---|---|
| `column_id` + `aggregation: SUM` | load-bearing | `SUM(dataset.field)` |
| `formula_id` → a **scalar** `expr` + `aggregation: AVERAGE` | **load-bearing** | `AVG(<translated scalar expr>)` — the two compose |
| `formula_id` → an **aggregate** `expr` (`sum ( … )`) + any `aggregation` | a no-op | the expression as-is |

Getting the second row wrong silently drops the aggregate: the metric becomes a per-row
scalar and every number it produces is wrong while the model still imports. An earlier
revision of the mapping document stated the no-op case universally and was corrected —
do not reintroduce it.

Detect "aggregate expr" by testing whether `formula.split_call(expr)` yields a name in the
aggregate set (`sum`, `count`, `unique count`, `average`, `avg`, `min`, `max`, `stddev`,
`variance`, and the catalog's aggregate rows). A `None` from `split_call` — an expression
that is not a single outer call, like `[A::x] - [B::y]` — is by definition scalar.

**Tests to write** (each pins one row of that table, plus the fallout):

- `test_physical_column_with_aggregation_becomes_an_aggregate_metric` — `SUM(orders.amount)`.
- `test_scalar_formula_composes_with_the_column_aggregation` — expr `[A::x] - [A::y]`,
  `aggregation: AVERAGE` → the Ossie expression carries `AVG(...)`, **not** the bare scalar.
  Assert on the `ANSI_SQL` entry where one is emitted, and on an issue otherwise.
- `test_aggregate_formula_ignores_the_column_aggregation` — expr `sum ( [A::x] )` with
  `aggregation: MAX` → the expression stays `sum ( [A::x] )` and no `MAX` appears.
- `test_count_distinct_maps_to_count_distinct` — TML `COUNT_DISTINCT` → `COUNT(DISTINCT …)`.
- `test_none_aggregation_means_no_aggregate`.
- `test_std_deviation_and_variance_map` — TML `STD_DEVIATION`/`VARIANCE` → `STDDEV`/`VARIANCE`.
- `test_the_thoughtspot_entry_is_the_verbatim_formula_expr` — same invariant as Task 4.
- `test_a_metric_name_that_normalises_differently_stashes_the_exact_name` — metrics have no
  `label`, so the exact display name goes to the stash (returned for the caller to merge).
- `test_datatype_is_emitted_only_for_a_bare_aggregate_over_a_typed_column` — `COUNT` and
  `COUNT(DISTINCT …)` give `Integer`; otherwise the column's mapped type; otherwise omitted.
- `test_a_formula_id_with_no_matching_formulas_entry_raises_an_issue` rather than a KeyError.

The aggregation enum map, written once as a module constant:

```python
#: TML column aggregation -> the Ossie aggregate applied to the column expression.
#: `NONE` means the column carries no aggregate at all, which is distinct from absent.
_AGGREGATION = {
    "SUM": "SUM", "COUNT": "COUNT", "AVERAGE": "AVG", "MIN": "MIN", "MAX": "MAX",
    "COUNT_DISTINCT": "COUNT_DISTINCT", "STD_DEVIATION": "STDDEV", "VARIANCE": "VARIANCE",
    "NONE": None,
}
```

- [ ] Steps 1–6 as in Task 4. Commit: `feat(thoughtspot): convert TML measures to Ossie metrics, composing column aggregations`

---

### Task 6: `tml_to_ossie` — datasets, relationships, stash, and `convert()`

Completes the forward direction and gives it its public entry point.

**Files:** modify `tml_to_ossie.py`; create `tests/test_tml_to_ossie.py`.

**Read first:** *Semantic model level*, *Dataset level*, *Relationship level* (including
*Non-equality joins* and *Key derivation and `to_columns` coverage*), and the
`custom_extensions[THOUGHTSPOT]` *Protocol* section. Rules **KD1–KD3, X1–X9**.

**Interfaces — the public surface of the module:**

```python
@dataclass(frozen=True)
class OssieConversion:
    model: dict            # the Ossie document, ready to dump
    issues: IssueLog

def convert(document_set: DocumentSet) -> OssieConversion
```

**On the name.** The two directions each return a result object, and calling both
`Conversion` would collide the moment anything imports them together — the CLI does exactly
that in Task 10. They are `OssieConversion` (this task) and `TmlConversion` (Task 9).

**What `convert` must do, in order.** Build the dataset list from `model_tables[]`, pairing
each with its Table document for `source` (`db.schema.name`) and physical columns. Build a
resolver closure mapping `(TABLE, Column) → "dataset.field"` across the whole model — this
is what Tasks 4 and 5 take as `resolve`, and it cannot exist until every dataset is known,
which is why it lives here. Convert fields and metrics. Convert joins to relationships,
deriving `primary_key`/`unique_keys` per **KD1** — *only* relationships whose condition is
wholly equality pairs qualify, because anything else does not establish a key. Attribute
each computed field to the dataset its references resolve to, or stash it as unattributed.
Write one `custom_extensions[THOUGHTSPOT]` entry per object with `write_stash`, merging the
fragments the field and metric converters returned. Return everything plus the issue log.

**Tests to write:**

- `test_a_minimal_document_set_converts` — the shape from the mapping document's *Worked shape*.
- `test_dataset_source_is_db_schema_table`.
- `test_an_alias_is_used_for_the_reference_prefix_when_present` — `model_tables[].alias`
  overrides `name` in `column_id` prefixes; getting this wrong breaks every reference in
  an aliased model.
- `test_an_equality_join_derives_a_primary_key` (KD1 positive).
- `test_a_non_equality_join_derives_no_key_and_stashes_the_condition` (KD1 negative — the
  defect this rule was written to fix, where a fabricated key made the output look richer
  and was wrong).
- `test_a_composite_equality_join_derives_a_composite_key`.
- `test_a_multi_dataset_formula_is_not_attributed_and_raises_an_issue` — and appears in
  `unattributed_formulas` in the model-scope stash.
- `test_other_vendors_custom_extensions_pass_through_untouched` (X7).
- `test_no_guid_obj_id_or_fqn_appears_anywhere_in_the_output` (X8) — assert over the whole
  serialised document, not just the stash, because a stray `fqn` in a join or table
  reference is the same leak.
- `test_an_empty_payload_writes_no_stash_entry` (X6).
- `test_the_output_validates_against_the_upstream_schema` — load
  `/Users/damianwaldron/Dev/ts/ossie/core-spec/ossie-schema.json` and validate. Skip with
  `pytest.importorskip("jsonschema")` so the package keeps its single runtime dependency
  while still getting the check wherever `jsonschema` is available.

- [ ] Steps 1–6. Commit: `feat(thoughtspot): complete the TML -> Ossie direction with keys, stash and entry point`

---

### Task 7: `ossie_to_thoughtspot` — the Table documents

The reverse direction starts with the N in "1+N", because the Model references the tables
by name and cannot be built before they exist.

**Files:**
- Create: `src/ossie_thoughtspot/ossie_to_thoughtspot.py`
- Test: `tests/test_ossie_to_thoughtspot_tables.py`

**Read first:** rules **R1, R6, R10** and the *Datatype map*'s closing reverse-direction rule.

**Interfaces:**

```python
def build_table(dataset: dict, log: IssueLog) -> TmlDocument
```

**The three rules with teeth:**

- **R1 — `db_column_name` on every column, always, even when it equals `name`.** Some
  instances reject the import without it. There is no case where omitting it is correct.
- **Every column needs `db_column_properties.data_type`.** ThoughtSpot raises `Compulsory
  Field table->columns->db_column_properties is not populated`. A field with no `datatype`
  gets `datatypes.to_tml(None)`.
- **`source` splits into `db` / `schema` / `name`.** A `source` that is a query, not a
  three-part name, is a SQL View rather than a Table — emit `kind="sql_view"` and raise an
  issue if the shape is neither.

**Tests:** every column carries `db_column_name`; a `datatype`-less field still gets a
`data_type`; each of the four `declared_loss` types raises an issue naming the loss; a
three-part source splits correctly; a two-part or one-part source raises an issue rather
than producing a malformed table; a query source produces a `sql_view` document; the
`BOOLEAN`/`BOOL` and `DOUBLE`/`FLOAT` spelling is taken from the stash when present and
defaults otherwise; the emitted document reloads through `tml.load_document`.

- [ ] Steps 1–6. Commit: `feat(thoughtspot): build Table TML documents from Ossie datasets`

---

### Task 8: `ossie_to_thoughtspot` — the Model document

**Files:** modify `ossie_to_thoughtspot.py`; create `tests/test_ossie_to_thoughtspot_model.py`.

**Read first:** rules **R3, R4, R6, R7, R8, R9**, plus PD1 in this plan.

**Interfaces:**

```python
def build_model(semantic_model: dict, tables: Sequence[TmlDocument],
                log: IssueLog) -> TmlDocument
def to_thoughtspot_expression(entries: Sequence[dict],
                              resolve_field: Callable[[str], tuple[str, str] | None],
                              log: IssueLog, *, object_ref: str) -> str | None
```

**The parameter is deliberately not called `resolve`.** Task 4's `resolve` maps
`(TABLE, Column) -> "dataset.field"`; this one maps `"dataset.field" -> (TABLE, Column)`.
They are inverses with the same arity, so a mixed-up argument would type-check, run, and
produce references that are wrong in a way no test outside this module would catch. The
names differ so the mistake is visible at the call site.

**The rules, each of which came from a real import failure:**

- **R3** — every formula is one `formulas[]` entry (`id`, `name`, `expr`) **plus** one
  `columns[]` entry referencing it by `formula_id`. A `formulas[]` entry never carries
  `aggregation:`. Formula cross-references use the id form `[formula_<Name>]`, never the
  display-name form — a display-name reference fails on first import because ThoughtSpot
  parses it as search tokens.
- **R4 + PD1** — a metric is **always** a formula, never a physical `column_id` plus an
  aggregation. Emit pattern A (aggregate-in-expr) unless the stash's `shape` says the model
  arrived as pattern B.
- **R6** — `column_id` is `TABLE::Column`; no two `columns[]` entries may share one, and
  display names must be unique across `columns[]` *and* `formulas[]` (ID4). Use
  `identifiers.Allocator` for that — it exists for this.
- **R7** — `column_type` and `synonyms` go **under `properties:`**. A bare `column_type`
  raises `No enum constant ColumnTypeEnum`; a root-level `synonyms:` is *silently dropped*.
  Set `synonym_type: USER_DEFINED` whenever synonyms are present.
- **R8** — never set `is_hidden: true` or `was_auto_generated: true`.
- **R9** — wrap any `expr` containing braces with `tml.block_scalar`.

**Dialect selection (`to_thoughtspot_expression`), the mirror of Task 4.** Prefer the
`THOUGHTSPOT` entry and use it **verbatim**, rewriting only its references — this is what
makes a document we produced return exactly. Otherwise take `ANSI_SQL`, and translate only
what the catalog matches structurally; anything else raises an issue and returns `None`
(the caller then stashes rather than guessing). Never re-render one SQL dialect into
another. Mirrors the reference converter's `pick_expression`, which reads its own dialect
first and `ANSI_SQL` only as a fallback.

**Tests:** the R3 pairing exists for every formula and the ids match exactly; a
`formulas[]` entry never has `aggregation`; a cross-reference uses `[formula_Name]`; two
fields whose display names collide get distinct allocated names (ID4); `column_type` and
`synonyms` land under `properties`; `is_hidden` is never emitted; a brace expression is a
block scalar; a `THOUGHTSPOT` entry is used verbatim with references rewritten; an
`ANSI_SQL`-only entry the catalog cannot match raises an issue and is stashed rather than
guessed; a metric emits as a formula and never as `column_id` + `aggregation`.

- [ ] Steps 1–6. Commit: `feat(thoughtspot): build the Model TML document under the R3-R9 import invariants`

---

### Task 9: `ossie_to_thoughtspot` — joins, stash restore, and `convert()`

**Files:** modify `ossie_to_thoughtspot.py`; create `tests/test_ossie_to_thoughtspot.py`.

**Read first:** rule **R5**, the *Non-equality joins* section, and **X5** (stash-if-present-
and-still-current-else-derive).

**Interfaces:**

```python
@dataclass(frozen=True)
class TmlConversion:
    documents: DocumentSet
    issues: IssueLog

def convert(ossie_document: dict) -> TmlConversion
```

**R5, in full, because every clause is a separate import failure:** inline joins live inside
the **source (FK)** `model_tables[]` entry, never at model top level — at top level the
import fails with `destination is missing`. The condition key is quoted `'on':` (`on` is a
YAML 1.1 reserved word; `tml.py` already handles this). `type` and `cardinality` are both
required. `with:` must equal the target entry's `name` exactly. A source `FULL OUTER` or
`FULL_OUTER` becomes `OUTER` in **both** the model inline join and the Table `joins_with[]`
entry — ThoughtSpot accepts only `INNER`, `LEFT_OUTER`, `RIGHT_OUTER`, `OUTER`, and `OUTER`
*is* its full outer join, so this is a semantics-preserving rename and never a loss.

**X5 is the rule most likely to be implemented wrong**, because the obvious reading is
"use the stash if it is there". It is not. A user who edits the Ossie document — retargets
a relationship, rewrites a metric expression — leaves a stash describing the document *as it
was*, and a plain stash-if-present rule silently discards their edit. So each stashed value
that shadows a derivable one is stored alongside the Ossie value it came from, and reused
**only when the two still agree**; otherwise it is dropped and the value re-derived. That is
what `stash.restore(payload, key, derived, *, witness, witness_key)` implements — use it,
do not hand-roll the comparison.

**Tests:** an inline join sits in the source entry, not at top level; `'on'` survives a
reload as a string; `FULL OUTER` and `FULL_OUTER` both become `OUTER` in both places; a
missing `type` or `cardinality` is an error, not a silent omission; a stash whose witness
still matches is used; a stash whose witness has changed is **dropped and re-derived**, with
an issue recording it; a document with no stash at all converts (a hand-authored Ossie file
must work); other vendors' extensions survive; the full set reloads through
`tml.load_document_set`; and no `guid` appears in any emitted document (R2).

- [ ] Steps 1–6. Commit: `feat(thoughtspot): complete the Ossie -> TML direction with joins and stale-stash detection`

---

### Task 10: `cli.py` — the console entry point

**Files:** create `src/ossie_thoughtspot/cli.py`, `tests/test_cli.py`; modify `pyproject.toml`.

Mirror the shape of the other converters' CLIs. `argparse` only — no new dependency.

```
ossie-thoughtspot to-ossie   <tml-file>... -o <out.yaml>  [--issues <issues.json>]
ossie-thoughtspot to-tml     <ossie.yaml>  -o <out-dir>   [--issues <issues.json>]
```

**Contract:**

- Structured output to the named file; **issues as JSON**, to `--issues` when given and to
  stderr otherwise. Never interleave issues with document output.
- **Exit code 1 when the issue log `has_errors()`**, 0 otherwise. Warnings and info do not
  fail the run — a conversion with declared losses is a successful conversion that reported
  them, and treating it as a failure would push users toward `|| true`.
- `to-tml` writes one file per document into the output directory, named by
  `dump_document_set` (tables first).
- **Add the `[project.scripts]` entry in the same task.** Plan A deliberately left it out
  because `cli:main` did not exist and a declared-but-broken entry point is worse than none.
  It exists now, so declare it here — and the test below is what proves the two agree.

**Tests:** `to-ossie` on the fixture set writes a loadable Ossie document; `to-tml` writes
the expected filenames; issues land in `--issues` as JSON and not in the document; exit 1 on
an error-severity issue and 0 on warnings only; `--help` works for both subcommands; and the
console-script entry point resolves — import `ossie_thoughtspot.cli` and assert `main` is
callable, so a typo in `pyproject.toml` fails a test rather than a user's install.

- [ ] Steps 1–6. Commit: `feat(thoughtspot): CLI entry point for both directions`

---

### Task 11: the TPC-DS fixture pair

**Files:** create `tests/fixtures/tpcds/*.table.tml`, `tests/fixtures/tpcds/*.model.tml`,
`tests/fixtures/tpcds/expected.ossie.yaml`; and `tests/fixtures/minimal/` likewise.

**Why TPC-DS specifically.** `/Users/damianwaldron/Dev/ts/ossie/examples/tpcds_semantic_model.yaml`
is the model every other converter round-trips — 5 datasets, 31 fields, 4 relationships,
5 metrics. Matching it makes this converter comparable to its siblings rather than tested
against a shape only it has seen. Read that file first and mirror its dataset, field,
relationship and metric names exactly.

**Author the TML from scratch.** Do not copy TML from anywhere. These fixtures are
contributed under Apache terms and their provenance must be clean — this was raised
explicitly in the upstream issue thread and is the reason the licensing question was
settled before any code was written.

**The fixture set must exercise, deliberately, at least one of each:** a physical
attribute; a computed attribute formula; a metric that is a bare aggregate; a metric whose
formula is scalar with a column-level aggregation (the composition case from Task 5); a
composite-key relationship (`store_sales` has one); a non-equality join condition, so the
KD1 negative path is covered by a fixture and not only a unit test; a column whose name is
a YAML 1.1 boolean token (`on`), so R11 is exercised end to end; and a brace-carrying window
formula, so R9 is exercised end to end.

The last two are the ones a fixture author naturally omits, and they are exactly the two
whose failure mode is silent corruption rather than an error.

**Tests:** the TML fixtures all load; `expected.ossie.yaml` validates against
`core-spec/ossie-schema.json` (importorskip `jsonschema`); `tml_to_ossie.convert` on the
fixture set equals `expected.ossie.yaml`.

- [ ] Steps 1–6. Commit: `test(thoughtspot): TPC-DS and minimal fixture pairs`

---

### Task 12: round-trip tests — and the trap in them

**Files:** create `tests/test_roundtrip.py`.

**Both directions:** `TML → Ossie → TML` and `Ossie → TML → Ossie`, over both fixture sets.

**The trap, stated plainly because it is the whole reason this task has prose.** The return
leg reads the `THOUGHTSPOT` dialect entry, which holds the original formula verbatim. So a
round-trip test **can pass while expression translation is completely broken** — it proves
*preservation*, not *translation*. That is the same self-consistency that made this project's
passthrough-arity sweep green and useless (BL-235 in the skills repo).

**So assert the two separately:**

1. **Preservation** — `TML → Ossie → TML` reproduces the original documents. Compare parsed
   structures, not text, but hold expressions to **exact string equality**, which is
   upstream's bar and is achievable precisely because nothing reformats them.
2. **Translation** — assert directly on the `ANSI_SQL` siblings: for the fixture's physical
   fields, the portable expression is the expected `dataset.field`; for the fixture's
   known-unportable formula, there is no `ANSI_SQL` entry and there *is* an issue. These
   assertions fail if translation regresses even though preservation still passes.

**Also assert:** `Ossie → TML → Ossie` returns the input for everything the datatype map
calls lossless, and for each of the four `declared_loss` types the round trip differs **and
an issue said so in advance** — a declared loss that is not reported is the failure, not the
loss itself.

- [ ] Steps 1–6. Commit: `test(thoughtspot): round-trip both directions, asserting preservation and translation separately`

---

### Task 13: property-based round-trip

**Files:** create `tests/test_roundtrip_properties.py`; add `hypothesis` to the test extra.

Follow the reference converter's `test_roundtrip_properties.py`. Generate small but valid
Ossie models — dataset and field names drawn from a strategy that **deliberately includes**
the awkward cases: YAML 1.1 boolean tokens (`on`, `off`, `yes`, `no`), names differing only
after `normalise` (so ID4's allocator is exercised), names with non-ASCII characters (NFKD
folding), and names containing `::` (which `split_column_ref` must reject rather than
mis-split).

Property: `ossie → tml → ossie` is the identity on everything the datatype map calls
lossless, and every difference elsewhere is covered by a reported issue.

Keep `max_examples` modest (the default is fine) and set a deadline generous enough for CI.
`hypothesis` is a **test-only** dependency and must not enter `[project.dependencies]`.

- [ ] Steps 1–6. Commit: `test(thoughtspot): property-based round-trip over adversarial identifiers`

---

### Task 14: README, packaging, CI

**Files:** modify `README.md`, `pyproject.toml`, `uv.lock`,
`/Users/damianwaldron/Dev/ts/ossie/.github/workflows/converter-thoughtspot-ci.yml`,
`/Users/damianwaldron/Dev/ts/ossie/converters/README.md`,
`/Users/damianwaldron/Dev/ts/ossie/core-spec/spec.md`.

- **README** — document both directions, the CLI, the `custom_extensions[THOUGHTSPOT]`
  payload, and, in a section of its own, **what is not translated and why**: expressions
  pass through under the `THOUGHTSPOT` dialect, a portable sibling appears only where it is
  certain, and no SQL dialect is re-rendered into another. State it as the deliberate choice
  it is, with the specification's pass-through default as the reason. A reviewer who
  discovers this by reading the code will read it as a gap.
- **`pyproject.toml`** — the `[project.scripts]` entry from Task 10, the `hypothesis` test
  extra, and a regenerated `uv.lock`.
- **CI** — extend the existing workflow to run the new suites on the supported Python
  matrix. Keep it offline.
- **`converters/README.md`** — add the THOUGHTSPOT vendor row.
- **`core-spec/spec.md`** — add THOUGHTSPOT to the well-known `custom_extensions` vendor
  examples table. This is a one-row documentation touch, not a specification change: the
  `vendor_name` field is free-form, so no dev@ vote is required. (Contrast the `Dialect`
  enum, which *was* a specification change and went through its own PR.)

**Verify before committing:** the full suite on the lowest and highest supported Python;
`pip install -e .` followed by `ossie-thoughtspot --help`; the built wheel's metadata still
declares PyYAML alone; and a final case-insensitive sweep of `src/`, `tests/`, `README.md`
and the fixtures for internal-process language (Global Constraint 6).

- [ ] Steps 1–6. Commit: `docs(thoughtspot): README, packaging and CI for the bidirectional converter`

---

## Open items this plan does not resolve

| Item | Why it is not blocking |
|---|---|
| **BL-186 V1** — is the literal `calendar` a sentinel or a real name? | PD3: the property is written only from the stash, never synthesised. Emission stays blocked until the vocabulary is reconciled. |
| **apache/ossie#287** — extended metadata | PD4: five stash keys sit behind one map; if #287 merges, that map changes. |
| **BL-235** — passthrough arity has no document-vs-code guard | Affects the catalog, not either direction. The exemplar rule is honoured here by rebuilding per occurrence. |
| **BL-230** — `normalise` is NFKD-folded but still ASCII-only | Task 13's strategy will exercise it; a non-ASCII name that survives folding raises an issue rather than corrupting. |
| **Live TML verification** | The design spec asks for the fixtures to be imported once against a real instance before the upstream PR. That is a post-build step needing the user's instance, not a task here, and upstream CI stays offline either way. |

## Success criteria

1. Both directions convert the TPC-DS fixture set, and the output validates against `core-spec/ossie-schema.json`.
2. Round-trip passes in both directions, with preservation and translation asserted separately.
3. The property-based suite passes over adversarial identifiers.
4. `ossie-thoughtspot --help` works from a clean `pip install -e .`, and the wheel declares PyYAML alone.
5. Every declared loss is reported as an issue before it happens; nothing is dropped silently.
6. No internal-process language anywhere in the shipped tree.
