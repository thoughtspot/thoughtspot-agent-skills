# Apache Ossie ThoughtSpot Converter — Expression Translation Implementation Plan (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the expression-translation catalog and emitters — the layer that maps every construct in the Ossie expression language onto a ThoughtSpot formula, and every ThoughtSpot-only function back onto Ossie constructs.

**Architecture:** A declarative catalog (data, not branching code) of all 146 specification constructs plus the reverse-direction inventory, consumed by a small set of emitters. The catalog's completeness is gated by a test that reads the *upstream* `core-spec/expression_language.md` and asserts one-to-one coverage — so a construct added upstream fails our build rather than being silently unsupported. No expression *parser* is built here; see Scope.

**Tech Stack:** Python 3.10+, PyYAML>=6.0 only. Consumes Plan A's `constants`, `issues` and `errors` modules.

**Spec:**
- [2026-07-29-ossie-thoughtspot-converter-design.md](2026-07-29-ossie-thoughtspot-converter-design.md) — the programme
- [2026-09-01-ossie-converter-foundations-plan.md](2026-09-01-ossie-converter-foundations-plan.md) — Plan A, whose Global Constraints still bind

**The normative ruleset**, which this plan implements and which must be read alongside it:
- [../../ossie/ts-ossie-function-mapping.md](../../ossie/ts-ossie-function-mapping.md) — the 146 rows, rules **E1**–**E13**, and the reverse-direction inventory. **This document is the specification for Plan B.** Every row in the catalog comes from it.
- [../../ossie/ts-ossie-construct-mapping.md](../../ossie/ts-ossie-construct-mapping.md) — rule **ID3** (identifier rewriting), which constrains what the emitters may assume.

---

## Scope: what this plan deliberately does not build

**No expression parser.** Translating `SUM(orders.amount)` into `sum ( [ORDERS::Amount] )` requires parsing the Ossie expression to find and rewrite identifiers (rule **ID3**). That is a different kind of work from the catalog, and it forces a dependency decision this plan should not make unilaterally:

- Plan A's Global Constraints allow **PyYAML only**; a new runtime dependency needs PMC/IPMC approval upstream.
- `converters/nvidia` already uses **sqlglot** inside a converter, with a documented degradation path (11 dialects tried, unparsable SQL carried verbatim). So there is precedent, and it is the obvious tool.
- Hand-rolling a SQL expression parser to avoid one dependency would be a poor trade.

**Therefore:** Plan B builds the catalog and the emitters, both of which take *already-parsed* pieces — a function name and its rendered arguments. The parser, and the sqlglot question, belong to a short Plan B2 raised on `dev@` first. This split is deliberate: it keeps the 146 rows of domain knowledge reviewable on their own, and it stops a dependency decision hiding inside a large diff.

**No conversion direction.** Plans C and D own those. Plan B is a library.

---

## Global Constraints

Plan A's constraints all still bind. Restated here because every task's requirements implicitly include this section, with the two that have changed marked:

- **Package `apache-ossie-thoughtspot`, import `ossie_thoughtspot`, directory `converters/thoughtspot/`.**
- **ASF licence header on every new source file**, byte-identical to `converters/databricks/src/ossie_databricks/_common.py` lines 1–16, blank line 17, then content. The automated gate now covers `pyproject.toml`, `.gitignore`, `README.md` and the CI YAML as well as `.py` files.
- **No runtime dependency beyond `PyYAML>=6.0`.** Adding one requires PMC/IPMC approval. This plan needs none.
- **Write every line fresh. Port nothing from `tools/ts-cli/` or any ThoughtSpot product.** Per Jean-Baptiste Onofré (Ossie mentor, IPMC) on `dev@ossie.apache.org`, 2026-08-31: *"the license has to be AL v2 and if the code is coming from another product, SGA and license change is required."* **This bites hardest in this plan.** `tools/ts-cli/ts_cli/formula_common.py` (478 lines) and `sv_translate.py` (999 lines) already implement ThoughtSpot formula translation, and reaching for them is the obvious efficiency. They are ThoughtSpot-owned work in a ThoughtSpot-org repository. The **mapping documents** are prose specifications and may be used freely; the **source** may not. A reviewer should be able to diff any module here against its `ts_cli` counterpart and see two independent implementations of one documented ruleset.
- **`THOUGHTSPOT` IS a registered dialect** — apache/ossie#351 merged 2026-09-01. `constants.DIALECT_IS_REGISTERED` is `True`. Emit it. Per learnings **P8**, also emit `constants.PORTABLE_DIALECT` (`ANSI_SQL`) alongside wherever the expression is portable. *(This constraint was inverted in Plan A and is now correct.)*
- **Python floor 3.10.**
- **Verification command:** `cd converters/thoughtspot && uv run --python 3.13 pytest tests/ -v`. The older `--extra dev` form no longer works — packaging moved to PEP 735 `[dependency-groups]`.
- **Environment:** system `python3` is 3.9.6 and fails on modern syntax. Always use `uv run --python 3.13`.

---

## File Structure

```
converters/thoughtspot/
  src/ossie_thoughtspot/expressions/
    __init__.py          Public surface: translate_construct, translate_thoughtspot, CATALOG
    catalog.py           The 146 specification constructs as data. One entry per row.
    reverse.py           ThoughtSpot-only functions -> Ossie constructs (the §"Reverse direction" inventory)
    emit.py              Rendering: direct compositions, and sql_*_op passthroughs with the right variant
    _types.py            Construct, Classification, Variant — the small vocabulary the other three share
  tests/expressions/
    test_catalog_covers_the_spec.py    The self-maintaining gate — reads upstream expression_language.md
    test_catalog_aggregate.py  test_catalog_datetime.py  test_catalog_string.py
    test_catalog_math_conditional.py   test_catalog_operators.py  test_catalog_window.py
    test_emit.py  test_reverse.py
```

`catalog.py` will be large — 146 entries — and that is correct: it is a data table, not logic, and splitting it by family would make the coverage gate harder to read. The *tests* split by family so a reviewer can gate one family at a time.

---

### Task 1: The catalog vocabulary and the spec-coverage gate

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/expressions/__init__.py`
- Create: `converters/thoughtspot/src/ossie_thoughtspot/expressions/_types.py`
- Create: `converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py` (empty `CATALOG: dict` for now)
- Test: `converters/thoughtspot/tests/expressions/test_catalog_covers_the_spec.py`

**Interfaces:**
- Consumes: nothing from Plan A yet
- Produces: `Classification` (`DIRECT`/`PASSTHROUGH`/`UNMAPPABLE`), `Variant` (the `sql_*_op` family), `Construct` dataclass, `CATALOG: dict[str, Construct]`, and `spec_construct_names() -> set[str]`

**Do this task first and get it right.** It is the keystone: every later task adds rows that this gate checks. Built last, it would be a formality; built first, it tells each family task exactly what it still owes.

**Why the gate reads the upstream file.** `converters/nvidia` has the strongest test in the repo — `test_mapping_covers_the_specs_datatype_vocabulary` reads `core-spec/ossie-schema.json` and asserts the converter's map equals the spec's enum. Oracling against our own documentation only proves we are self-consistent. Reading `core-spec/expression_language.md` means a construct added upstream **fails our build** rather than silently going unsupported — which is exactly the "discovered, never listed" property the skills repo's angle-9 lesson demands.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/expressions/test_catalog_covers_the_spec.py
# <ASF header>
"""The catalog must cover the specification's construct inventory, one to one.

This test reads the UPSTREAM core-spec/expression_language.md rather than any
document of our own. Oracling against our own mapping notes would only prove we
are self-consistent; reading the spec means a construct added upstream fails this
build instead of silently going unsupported.
"""
from ossie_thoughtspot.expressions import CATALOG, spec_construct_names


def test_every_spec_construct_has_a_catalog_entry():
    missing = spec_construct_names() - set(CATALOG)
    assert missing == set(), f"constructs in the spec with no catalog entry: {sorted(missing)}"


def test_no_catalog_entry_invents_a_construct_the_spec_does_not_have():
    invented = set(CATALOG) - spec_construct_names()
    assert invented == set(), f"catalog entries not found in the spec: {sorted(invented)}"


def test_the_total_matches_the_mapping_document_census():
    # 146 is the figure the mapping document's coverage summary reports, arrived at
    # by rule E1 (one row per construct; argument vocabularies are not constructs).
    assert len(CATALOG) == 146
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd converters/thoughtspot && uv run --python 3.13 pytest tests/expressions/test_catalog_covers_the_spec.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ossie_thoughtspot.expressions'`

- [ ] **Step 3: Write `_types.py`**

```python
# <ASF header>
"""The small shared vocabulary the catalog, emitters and reverse map all use."""
from dataclasses import dataclass
from enum import Enum


class Classification(str, Enum):
    """How a specification construct reaches ThoughtSpot.

    DIRECT      a native ThoughtSpot equivalent exists, possibly as a documented
                composition of native functions (rule E2).
    PASSTHROUGH requires a sql_*_op pass-through: warehouse-dialect-specific, and
                opaque to ThoughtSpot's query planner.
    UNMAPPABLE  no representation; the converter raises an issue and preserves the
                construct in custom_extensions. Never a silent drop.
    """

    DIRECT = "direct"
    PASSTHROUGH = "passthrough"
    UNMAPPABLE = "unmappable"


class Variant(str, Enum):
    """The sql_*_op family. Rule E7: the variant fixes the emitted column's type AND
    its measure/attribute role. The scalar variants produce attributes; the
    *_aggregate_op variants produce measures. Emitting sql_int_op where
    sql_int_aggregate_op was needed yields a column that imports cleanly and then
    aggregates wrongly — worse than a rejected import.
    """

    BOOL = "sql_bool_op"
    DATE_TIME = "sql_date_time_op"
    DOUBLE = "sql_double_op"
    INT = "sql_int_op"
    NUMBER = "sql_number_op"
    STRING = "sql_string_op"
    INT_AGGREGATE = "sql_int_aggregate_op"
    NUMBER_AGGREGATE = "sql_number_aggregate_op"


@dataclass(frozen=True)
class Construct:
    """One row of the function-mapping document.

    `spec_name`   the construct as the specification writes it, e.g. "SUM(expr)".
    `template`    for DIRECT, the ThoughtSpot formula with {0}, {1}... placeholders;
                  for PASSTHROUGH, the SQL body passed to the variant; None if UNMAPPABLE.
    `variant`     required for PASSTHROUGH (rule E4), forbidden otherwise.
    `note`        the row's caveat, verbatim enough to be traceable to the document.
    """

    spec_name: str
    classification: Classification
    template: str | None = None
    variant: Variant | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.classification is Classification.PASSTHROUGH and self.variant is None:
            raise ValueError(f"{self.spec_name}: a passthrough row must name its variant (E4)")
        if self.classification is not Classification.PASSTHROUGH and self.variant is not None:
            raise ValueError(f"{self.spec_name}: only a passthrough row may name a variant")
        if self.classification is Classification.UNMAPPABLE and self.template is not None:
            raise ValueError(f"{self.spec_name}: an unmappable row has no template")
```

- [ ] **Step 4: Write `spec_construct_names()` in `catalog.py`**

Locate `core-spec/expression_language.md` by walking up from `__file__` to the repository root. Parse the construct inventory out of it. **Read the file first and choose your extraction against what is actually there** — the sections and table shapes are the source of truth, not this plan's description of them.

Two rules from the mapping document govern what counts, and the gate must honour both or it will report false gaps:

- **Rule E1** — argument vocabularies are *not* constructs. The `EXTRACT`/`DATE_PART` parts, `DATE_TRUNC` precisions, `DATEADD`/`DATEDIFF` parts, `TO_DATE`/`TO_CHAR` format tokens and `CAST` target types are arguments, and the mapping document marks each such sub-table *(not counted — arguments)*. Exclude them.
- The **informative tables** — the per-engine dialect variations and the Tableau / Looker Studio / DAX cross-reference — describe *other products'* spellings. Names appearing only there (`APPROX_QUANTILES`, `DATE_ADD`, `RUNNING_SUM`) are not Ossie constructs. Exclude them.

Write the exclusion logic so it keys off the document's own markers rather than a hardcoded name list — a hardcoded list is the failure mode this gate exists to prevent.

Leave `CATALOG: dict[str, Construct] = {}` empty. The two coverage tests will fail; that is correct and expected until Task 7.

- [ ] **Step 5: Confirm the gate reports the truth**

Run the test file. Expected: `test_every_spec_construct_has_a_catalog_entry` FAILS listing ~146 missing names; `test_no_catalog_entry_invents_a_construct` PASSES (nothing invented yet); the census test FAILS at 0.

**Read the list of missing names.** If it is not close to 146, or contains obvious argument-vocabulary entries like `YEAR`-as-a-date-part or `VARCHAR`-as-a-cast-target, the extraction is wrong — fix it now. A gate that miscounts is worse than none, because every later task will be measured against it.

- [ ] **Step 6: Mark the census test expected-to-fail until Task 7**

Add `@pytest.mark.xfail(reason="catalog is populated across Tasks 2-7", strict=True)` to the two failing tests. `strict=True` matters: when the catalog is complete they will XPASS and pytest will fail, forcing whoever finishes Task 7 to remove the markers rather than leaving a permanently-disabled gate.

- [ ] **Step 7: Commit**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/expressions converters/thoughtspot/tests/expressions
git commit -m "feat(thoughtspot): expression catalog vocabulary and spec-coverage gate"
```

---

### Task 2: Emitters

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/expressions/emit.py`
- Test: `converters/thoughtspot/tests/expressions/test_emit.py`

**Interfaces:**
- Consumes: `_types.Construct`, `_types.Variant`, `issues.IssueLog`, `issues.Severity`
- Produces: `emit_direct(construct, args) -> str`; `emit_passthrough(construct, args, log) -> str`; `emit_unmappable(construct, log) -> None`

**Built before the families** so each family task has something to render into and can assert on real output rather than on the catalog row alone.

The rules this implements, all from the mapping document:

| Rule | Requirement |
|---|---|
| **E2** | A `direct` row may be a *composition* of native functions, not only a one-to-one rename. |
| **E4** | Every `passthrough` names its variant. |
| **E7** | The variant fixes the emitted column's type and its measure/attribute role. |
| **E8** | A pass-through carrying `PARTITION BY` is wrapped in `group_aggregate(... query_groups() + {[col]}, query_filters())`. |
| **E9** | No pass-through may carry a runtime parameter — raise an issue and emit a `THOUGHTSPOT` dialect entry only. |
| **E12** | An issue names the function, the object and the reason. Never a bare "untranslatable". |

- [ ] **Step 1: Write the failing tests**

```python
# <ASF header>
import pytest

from ossie_thoughtspot.expressions._types import Classification, Construct, Variant
from ossie_thoughtspot.expressions.emit import emit_direct, emit_passthrough, emit_unmappable
from ossie_thoughtspot.issues import IssueLog, Severity

SUM = Construct("SUM(expr)", Classification.DIRECT, template="sum ( {0} )")
STDDEV_POP = Construct(
    "STDDEV_POP(expr)", Classification.PASSTHROUGH,
    template="STDDEV_POP({0})", variant=Variant.NUMBER_AGGREGATE,
)


def test_emit_direct_substitutes_positionally():
    assert emit_direct(SUM, ["[ORDERS::Amount]"]) == "sum ( [ORDERS::Amount] )"


def test_emit_direct_rejects_an_argument_count_mismatch():
    # Silently dropping or reusing an argument would produce a formula that imports
    # and computes the wrong thing.
    with pytest.raises(ValueError, match="expects 1 argument"):
        emit_direct(SUM, ["a", "b"])


def test_emit_passthrough_wraps_the_body_in_its_variant():
    log = IssueLog()
    out = emit_passthrough(STDDEV_POP, ["[ORDERS::Amount]"], log)
    assert out == 'sql_number_aggregate_op ( "STDDEV_POP({0})" , [ORDERS::Amount] )'


def test_emit_passthrough_always_raises_a_warning_issue():
    # The mapping document requires every pass-through to surface, because it embeds
    # raw warehouse SQL and is opaque to ThoughtSpot's query planner.
    log = IssueLog()
    emit_passthrough(STDDEV_POP, ["[ORDERS::Amount]"], log)
    assert log.count_by_severity() == {"WARNING": 1}
    issue = log.as_dicts()[0]
    assert "STDDEV_POP" in issue["message"]          # E12: names the function
    assert issue["object_ref"]                        # E12: names the object


def test_emit_passthrough_refuses_a_runtime_parameter():
    # E9. A sql_*_op whose arguments include a ThoughtSpot parameter cannot resolve to
    # static SQL, so it is not portable in either direction.
    log = IssueLog()
    with pytest.raises(ValueError, match="runtime parameter"):
        emit_passthrough(STDDEV_POP, ["[Threshold Parameter]"], log, has_parameter=True)


def test_emit_unmappable_raises_an_issue_and_returns_nothing():
    c = Construct("EXISTS_IN(x)", Classification.UNMAPPABLE)
    log = IssueLog()
    assert emit_unmappable(c, log, object_ref="metric:Revenue") is None
    issue = log.as_dicts()[0]
    assert issue["severity"] == Severity.ERROR.value
    assert "EXISTS_IN" in issue["message"] and "metric:Revenue" == issue["object_ref"]
```

- [ ] **Step 2: Run to confirm failure.** Expected: `ModuleNotFoundError` on `expressions.emit`.

- [ ] **Step 3: Implement `emit.py`.** Write it from the tests and the rule table above. Two details the tests pin that are easy to get subtly wrong:

  - `emit_passthrough` renders the SQL body as a **quoted template string** followed by the arguments — `sql_number_aggregate_op ( "STDDEV_POP({0})" , [x] )` — not with the arguments substituted into the SQL. ThoughtSpot resolves the placeholders itself.
  - `emit_direct` **does** substitute positionally, and must reject a count mismatch rather than tolerate it.

- [ ] **Step 4: Run to confirm pass.**

- [ ] **Step 5: Add the E8 `group_aggregate` wrapper.** Write the failing test first: a passthrough carrying a `PARTITION BY` must come back wrapped as `group_aggregate ( <passthrough> , query_groups ( ) + { [partition_col] } , query_filters ( ) )`. Read the mapping document's E8 text for the exact shape before writing the expected string. Then implement.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(thoughtspot): expression emitters for direct, passthrough and unmappable"
```

---

### Tasks 3–8: populate the catalog, one family per task

The six tasks below are the same shape: transcribe one family's rows from
[`ts-ossie-function-mapping.md`](../../ossie/ts-ossie-function-mapping.md) into `CATALOG`, with a
test file asserting each row's classification, template and variant. They are separate tasks
because a reviewer can meaningfully reject one family while approving its neighbour.

**The mapping document is the specification. Transcribe from it; do not reason from the function
name.** Many rows were established by live probing against a real instance rather than by reading
documentation, and several are the opposite of what the name suggests. Where a `direct` row's
argument space is only partly covered, rule **E3** requires the row to name its fallback — carry
that into the `note`, because a later reader needs to know the row is conditional.

Per-family totals must reconcile to the document's census: **146 rows = 108 direct / 37
passthrough / 1 unmappable**.

---

### Task 3: Catalog — Aggregate functions and Type conversion

**Files:**
- Modify: `converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py`
- Test: `converters/thoughtspot/tests/expressions/test_catalog_aggregate.py`

**Interfaces:**
- Consumes: `_types.Construct`, `_types.Classification`, `_types.Variant` (Task 1)
- Produces: 20 new entries in `CATALOG` — **14 direct / 6 passthrough / 0 unmappable**

**Source:** the `Aggregate functions` and `Type conversion` section(s) of the function-mapping document, read in full including the prose above and below each table.

**What makes this family specific:** `COUNT(*)` has to pick a column it believes is non-null — the row says which and why. `STDDEV`/`VARIANCE` are sample-only in ThoughtSpot, so the population forms are passthrough.

- [ ] **Step 1: Read the family's section in full.** Prose included — several rows' classifications are only explicable from the surrounding text.

- [ ] **Step 2: Write the test file first.** One assertion per row, naming the construct, its expected `Classification`, and for every passthrough its `Variant`. Shape:

```python
# <ASF header>
from ossie_thoughtspot.expressions import CATALOG
from ossie_thoughtspot.expressions._types import Classification, Variant


def test_row_count_for_this_family():
    ours = [c for c in CATALOG.values() if c.spec_name in EXPECTED]
    assert len(ours) == 20


def test_classifications():
    for name, expected in EXPECTED.items():
        assert CATALOG[name].classification is expected, name
```

Define `EXPECTED` as an explicit dict of every construct in this family to its classification. Spell the construct names exactly as the specification spells them — the coverage gate matches on those strings.

- [ ] **Step 3: Run the tests; confirm every assertion fails** with `KeyError` on the missing catalog entries.

- [ ] **Step 4: Add this family's entries to `CATALOG`.**

- [ ] **Step 5: Run the family test AND `test_catalog_covers_the_spec.py`.** The coverage gate's "missing" list must shrink by **exactly 20**. If it shrinks by a different number, **stop and report** — either a row was missed, a name does not match the spec's spelling, or Task 1's extraction is wrong. All three are real findings, and guessing which is how a silent gap enters the catalog.

- [ ] **Step 6: Commit.**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py converters/thoughtspot/tests/expressions/test_catalog_aggregate.py
git commit -m "feat(thoughtspot): catalog entries for aggregate functions and type conversion"
```
---

### Task 4: Catalog — Date/time functions

**Files:**
- Modify: `converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py`
- Test: `converters/thoughtspot/tests/expressions/test_catalog_datetime.py`

**Interfaces:**
- Consumes: `_types.Construct`, `_types.Classification`, `_types.Variant` (Task 1)
- Produces: 24 new entries in `CATALOG` — **17 direct / 7 passthrough / 0 unmappable**

**Source:** the `Date/time functions` section(s) of the function-mapping document, read in full including the prose above and below each table.

**What makes this family specific:** The `EXTRACT`/`DATE_PART` parts, `DATE_TRUNC` precisions, `DATEADD`/`DATEDIFF` parts and `TO_DATE`/`TO_CHAR` format tokens are **arguments, not constructs** (rule E1) — they have their own sub-tables marked *(not counted)*. Do not add catalog entries for them. There is no native `date_trunc` and no `MINUTE`/`SECOND` extractor.

- [ ] **Step 1: Read the family's section in full.** Prose included — several rows' classifications are only explicable from the surrounding text.

- [ ] **Step 2: Write the test file first.** One assertion per row, naming the construct, its expected `Classification`, and for every passthrough its `Variant`. Shape:

```python
# <ASF header>
from ossie_thoughtspot.expressions import CATALOG
from ossie_thoughtspot.expressions._types import Classification, Variant


def test_row_count_for_this_family():
    ours = [c for c in CATALOG.values() if c.spec_name in EXPECTED]
    assert len(ours) == 24


def test_classifications():
    for name, expected in EXPECTED.items():
        assert CATALOG[name].classification is expected, name
```

Define `EXPECTED` as an explicit dict of every construct in this family to its classification. Spell the construct names exactly as the specification spells them — the coverage gate matches on those strings.

- [ ] **Step 3: Run the tests; confirm every assertion fails** with `KeyError` on the missing catalog entries.

- [ ] **Step 4: Add this family's entries to `CATALOG`.**

- [ ] **Step 5: Run the family test AND `test_catalog_covers_the_spec.py`.** The coverage gate's "missing" list must shrink by **exactly 24**. If it shrinks by a different number, **stop and report** — either a row was missed, a name does not match the spec's spelling, or Task 1's extraction is wrong. All three are real findings, and guessing which is how a silent gap enters the catalog.

- [ ] **Step 6: Commit.**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py converters/thoughtspot/tests/expressions/test_catalog_datetime.py
git commit -m "feat(thoughtspot): catalog entries for date/time functions"
```
---

### Task 5: Catalog — String functions

**Files:**
- Modify: `converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py`
- Test: `converters/thoughtspot/tests/expressions/test_catalog_string.py`

**Interfaces:**
- Consumes: `_types.Construct`, `_types.Classification`, `_types.Variant` (Task 1)
- Produces: 21 new entries in `CATALOG` — **10 direct / 11 passthrough / 0 unmappable**

**Source:** the `String functions` section(s) of the function-mapping document, read in full including the prose above and below each table.

**What makes this family specific:** This family is over half passthrough and the reasons are counter-intuitive. `TRIM`, `LTRIM`, `RTRIM`, `REPLACE`, `LOWER`, `UPPER` are passthrough because ThoughtSpot has **no native `trim` at all** — live-verified 2026-07-29, and the document records the exact rejection message. `STARTSWITH`/`ENDSWITH` are **direct** despite having no native function, because the composition is exact and uses only native functions (E2). There is no regular-expression support of any kind.

- [ ] **Step 1: Read the family's section in full.** Prose included — several rows' classifications are only explicable from the surrounding text.

- [ ] **Step 2: Write the test file first.** One assertion per row, naming the construct, its expected `Classification`, and for every passthrough its `Variant`. Shape:

```python
# <ASF header>
from ossie_thoughtspot.expressions import CATALOG
from ossie_thoughtspot.expressions._types import Classification, Variant


def test_row_count_for_this_family():
    ours = [c for c in CATALOG.values() if c.spec_name in EXPECTED]
    assert len(ours) == 21


def test_classifications():
    for name, expected in EXPECTED.items():
        assert CATALOG[name].classification is expected, name
```

Define `EXPECTED` as an explicit dict of every construct in this family to its classification. Spell the construct names exactly as the specification spells them — the coverage gate matches on those strings.

- [ ] **Step 3: Run the tests; confirm every assertion fails** with `KeyError` on the missing catalog entries.

- [ ] **Step 4: Add this family's entries to `CATALOG`.**

- [ ] **Step 5: Run the family test AND `test_catalog_covers_the_spec.py`.** The coverage gate's "missing" list must shrink by **exactly 21**. If it shrinks by a different number, **stop and report** — either a row was missed, a name does not match the spec's spelling, or Task 1's extraction is wrong. All three are real findings, and guessing which is how a silent gap enters the catalog.

- [ ] **Step 6: Commit.**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py converters/thoughtspot/tests/expressions/test_catalog_string.py
git commit -m "feat(thoughtspot): catalog entries for string functions"
```
---

### Task 6: Catalog — Mathematical and Conditional functions

**Files:**
- Modify: `converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py`
- Test: `converters/thoughtspot/tests/expressions/test_catalog_math_conditional.py`

**Interfaces:**
- Consumes: `_types.Construct`, `_types.Classification`, `_types.Variant` (Task 1)
- Produces: 34 new entries in `CATALOG` — **32 direct / 2 passthrough / 0 unmappable**

**Source:** the `Mathematical functions` and `Conditional functions` section(s) of the function-mapping document, read in full including the prose above and below each table.

**What makes this family specific:** Nearly all direct, several by composition (E2): `SIGN` is an `if` chain, `RADIANS`/`DEGREES` are arithmetic, `PI` is a literal at the precision ThoughtSpot's own composites use. `CASE WHEN` becomes an `else if` chain and **the final `else` is mandatory and must be type-matched**. `atan2` is passthrough — it is quadrant-aware and defined where `x = 0`, so it is not a two-argument `atan`.

- [ ] **Step 1: Read the family's section in full.** Prose included — several rows' classifications are only explicable from the surrounding text.

- [ ] **Step 2: Write the test file first.** One assertion per row, naming the construct, its expected `Classification`, and for every passthrough its `Variant`. Shape:

```python
# <ASF header>
from ossie_thoughtspot.expressions import CATALOG
from ossie_thoughtspot.expressions._types import Classification, Variant


def test_row_count_for_this_family():
    ours = [c for c in CATALOG.values() if c.spec_name in EXPECTED]
    assert len(ours) == 34


def test_classifications():
    for name, expected in EXPECTED.items():
        assert CATALOG[name].classification is expected, name
```

Define `EXPECTED` as an explicit dict of every construct in this family to its classification. Spell the construct names exactly as the specification spells them — the coverage gate matches on those strings.

- [ ] **Step 3: Run the tests; confirm every assertion fails** with `KeyError` on the missing catalog entries.

- [ ] **Step 4: Add this family's entries to `CATALOG`.**

- [ ] **Step 5: Run the family test AND `test_catalog_covers_the_spec.py`.** The coverage gate's "missing" list must shrink by **exactly 34**. If it shrinks by a different number, **stop and report** — either a row was missed, a name does not match the spec's spelling, or Task 1's extraction is wrong. All three are real findings, and guessing which is how a silent gap enters the catalog.

- [ ] **Step 6: Commit.**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py converters/thoughtspot/tests/expressions/test_catalog_math_conditional.py
git commit -m "feat(thoughtspot): catalog entries for mathematical and conditional functions"
```
---

### Task 7: Catalog — Operators and constructs

**Files:**
- Modify: `converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py`
- Test: `converters/thoughtspot/tests/expressions/test_catalog_operators.py`

**Interfaces:**
- Consumes: `_types.Construct`, `_types.Classification`, `_types.Variant` (Task 1)
- Produces: 33 new entries in `CATALOG` — **30 direct / 2 passthrough / 1 unmappable**

**Source:** the `Operators and constructs` section(s) of the function-mapping document, read in full including the prose above and below each table.

**What makes this family specific:** This family holds **the single `unmappable` row in all 146** — `EXISTS_IN()`, which the specification references but never defines, so it cannot be read let alone translated. It must be `Classification.UNMAPPABLE` with no template. `LIKE` is direct by pattern shape (prefix/suffix/contains compositions); `ILIKE` is passthrough because case-insensitive matching has no native form and the usual `lower` workaround is itself a passthrough.

- [ ] **Step 1: Read the family's section in full.** Prose included — several rows' classifications are only explicable from the surrounding text.

- [ ] **Step 2: Write the test file first.** One assertion per row, naming the construct, its expected `Classification`, and for every passthrough its `Variant`. Shape:

```python
# <ASF header>
from ossie_thoughtspot.expressions import CATALOG
from ossie_thoughtspot.expressions._types import Classification, Variant


def test_row_count_for_this_family():
    ours = [c for c in CATALOG.values() if c.spec_name in EXPECTED]
    assert len(ours) == 33


def test_classifications():
    for name, expected in EXPECTED.items():
        assert CATALOG[name].classification is expected, name
```

Define `EXPECTED` as an explicit dict of every construct in this family to its classification. Spell the construct names exactly as the specification spells them — the coverage gate matches on those strings.

- [ ] **Step 3: Run the tests; confirm every assertion fails** with `KeyError` on the missing catalog entries.

- [ ] **Step 4: Add this family's entries to `CATALOG`.**

- [ ] **Step 5: Run the family test AND `test_catalog_covers_the_spec.py`.** The coverage gate's "missing" list must shrink by **exactly 33**. If it shrinks by a different number, **stop and report** — either a row was missed, a name does not match the spec's spelling, or Task 1's extraction is wrong. All three are real findings, and guessing which is how a silent gap enters the catalog.

- [ ] **Step 6: Commit.**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py converters/thoughtspot/tests/expressions/test_catalog_operators.py
git commit -m "feat(thoughtspot): catalog entries for operators and constructs"
```
---

### Task 8: Catalog — Window functions

**Files:**
- Modify: `converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py`
- Test: `converters/thoughtspot/tests/expressions/test_catalog_window.py`

**Interfaces:**
- Consumes: `_types.Construct`, `_types.Classification`, `_types.Variant` (Task 1)
- Produces: 14 new entries in `CATALOG` — **5 direct / 9 passthrough / 0 unmappable**

**Source:** the `Window functions` section(s) of the function-mapping document, read in full including the prose above and below each table.

**What makes this family specific:** **The hardest family, and three rules govern it.** **E5** — a raw aggregate cannot be nested inside a ThoughtSpot window function. **E6** — the `ORDER BY` column must be a physical column reference, not a formula. **E13** — a ThoughtSpot window formula **cannot declare its own `PARTITION BY`**; there is no argument slot for one, in any spelling. That is why nine of fourteen rows are passthrough, and why `LAG`, `LEAD`, the `OVER` clause and window aggregation moved from `direct` to `passthrough` after 52 live probes in July. `rank`/`rank_percentile` have an arity fixed at exactly **two**, proven by rejection on a live instance. `PERCENT_RANK` is direct via `rank_percentile`, but `CUME_DIST` is **not** — `PERCENT_RANK` divides by *n − 1* and starts at 0. Do not restore a row to `direct` because the names look equivalent; the evidence is in the document's *Window rows live-confirmed — 2026-07-30* section.

- [ ] **Step 1: Read the family's section in full.** Prose included — several rows' classifications are only explicable from the surrounding text.

- [ ] **Step 2: Write the test file first.** One assertion per row, naming the construct, its expected `Classification`, and for every passthrough its `Variant`. Shape:

```python
# <ASF header>
from ossie_thoughtspot.expressions import CATALOG
from ossie_thoughtspot.expressions._types import Classification, Variant


def test_row_count_for_this_family():
    ours = [c for c in CATALOG.values() if c.spec_name in EXPECTED]
    assert len(ours) == 14


def test_classifications():
    for name, expected in EXPECTED.items():
        assert CATALOG[name].classification is expected, name
```

Define `EXPECTED` as an explicit dict of every construct in this family to its classification. Spell the construct names exactly as the specification spells them — the coverage gate matches on those strings.

- [ ] **Step 3: Run the tests; confirm every assertion fails** with `KeyError` on the missing catalog entries.

- [ ] **Step 4: Add this family's entries to `CATALOG`.**

- [ ] **Step 5: Run the family test AND `test_catalog_covers_the_spec.py`.** The coverage gate's "missing" list must shrink by **exactly 14**. If it shrinks by a different number, **stop and report** — either a row was missed, a name does not match the spec's spelling, or Task 1's extraction is wrong. All three are real findings, and guessing which is how a silent gap enters the catalog.

- [ ] **Step 6: Commit.**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/expressions/catalog.py converters/thoughtspot/tests/expressions/test_catalog_window.py
git commit -m "feat(thoughtspot): catalog entries for window functions"
```
---

**Task 8 additionally** removes the two `@pytest.mark.xfail` markers from
`test_catalog_covers_the_spec.py`, since the catalog is complete only at that point. They are
`strict=True`, so leaving them in place fails the build — deliberately, so the gate cannot be
left permanently disabled.

### Task 9: The reverse-direction inventory

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/expressions/reverse.py`
- Test: `converters/thoughtspot/tests/expressions/test_reverse.py`

**Interfaces:**
- Consumes: `_types`, `issues`
- Produces: `REVERSE: dict[str, ReverseConstruct]`; `translate_thoughtspot(name, args, log) -> str | None`

This is the other half of a bidirectional converter: the ThoughtSpot functions with **no counterpart in the specification**. Source is the mapping document's *Reverse direction (ThoughtSpot → Ossie)* section.

**Rule E10 governs the whole task — prefer composition over the stash.** Most of ThoughtSpot's apparently-proprietary functions are sugar over constructs the specification already blesses:

- `sum_if` → `SUM(CASE WHEN … )`, which the specification blesses explicitly
- `safe_divide` → `COALESCE(a / NULLIF(b, 0), 0)`
- `group_sum` over a fixed grain → `SUM(x) OVER (PARTITION BY attr)`

The stash is for what genuinely has no expression — which the document establishes is a short list dominated by *runtime* concepts (parameters, display and calendar settings), not by missing maths.

**Rule E11** — a stashed expression still emits a `THOUGHTSPOT` dialect entry. Now that #351 has merged this is straightforwardly correct, where under Plan A it would have failed schema validation.

- [ ] **Step 1:** Read the reverse-direction section in full — all three sub-sections (conditional aggregates and arithmetic helpers; window, LOD and semi-additive functions; runtime, display and calendar concepts).
- [ ] **Step 2:** Write the test file first, one assertion per function: does it compose, or does it stash? For composers, assert the emitted Ossie expression. Run; confirm failure.
- [ ] **Step 3:** Implement `reverse.py`.
- [ ] **Step 4:** Run the full suite.
- [ ] **Step 5:** Commit.

---

## Definition of done

- [ ] `uv run --python 3.13 pytest tests/ -v` passes on 3.10 and 3.13
- [ ] `test_catalog_covers_the_spec.py` passes with **no `xfail` markers remaining**
- [ ] `len(CATALOG) == 146`, and the per-classification totals match the mapping document's census: **108 direct / 37 passthrough / 1 unmappable**
- [ ] Every ASF header in place; the packaging header test still passes
- [ ] No runtime dependency beyond `PyYAML>=6.0`
- [ ] No module imports `tml_to_ossie` or `ossie_to_thoughtspot` — they do not exist yet

## Open items this plan does not resolve

| Item | Effect |
|---|---|
| **The expression parser and the sqlglot question** | Blocks Plans C and D from using this catalog on real expressions. Raise on `dev@` first, citing nvidia's precedent |
| **BL-186 V1** — is the literal `calendar` a sentinel or a real name? | Gates the fiscal-calendar rows' emission in Plan C |
| **apache/ossie#287** — extended metadata | Would move `display_format` and `default_aggregation` to first-class fields, affecting the reverse-direction inventory's *display concepts* sub-section |
| **BL-230** — `normalise` diacritic policy | Unchanged by this plan; the catalog does not touch identifiers |
