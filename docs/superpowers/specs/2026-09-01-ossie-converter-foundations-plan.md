# Apache Ossie ThoughtSpot Converter — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `ossie_thoughtspot` package foundations — the modules both conversion directions import — as a standalone, fully tested pip distribution in a fork of `apache/ossie`.

**Architecture:** A dependency-free-except-PyYAML Python package under `converters/thoughtspot/`, mirroring the `converters/databricks` layout that upstream treats as the reference. This plan builds only the shared substrate: constants, a YAML-1.2 codec, structured issue reporting, the `custom_extensions` stash, identifier derivation, and key derivation. Neither conversion direction is implemented here — they are Plans C and D, and both import everything built below. Every module is pure and file-to-file; nothing calls a ThoughtSpot or Snowflake API.

**Tech Stack:** Python 3.10+, PyYAML>=6.0, pytest, hypothesis (Plan D only), `uv` for lockfile generation. No other runtime dependency — upstream's PR template requires PMC/IPMC approval for new third-party dependencies.

**Spec:** [2026-07-29-ossie-thoughtspot-converter-design.md](2026-07-29-ossie-thoughtspot-converter-design.md), whose Phase 3 sketch this plan supersedes.

> **Why an implementation plan is tracked under `specs/`.** `.gitignore` excludes
> `docs/superpowers/plans/` because plans are normally local working artifacts for work
> in *this* repo. This one describes work in **`apache/ossie`**, a repository this one
> does not contain, so there is no code here for it to be checked against and no other
> record of the decisions it makes. Tracked deliberately, 2026-09-01, so it survives a
> fresh clone and can be reviewed. The behavioural rules come from two documents that travel with it and must be read alongside:
- [../../ossie/ts-ossie-construct-mapping.md](../../ossie/ts-ossie-construct-mapping.md) — rules **ID1**–**ID4**, **X1**–**X9**, **KD1**–**KD3**, **R1**–**R11**, **NM1**–**NM6**
- [../../ossie/ts-ossie-function-mapping.md](../../ossie/ts-ossie-function-mapping.md) — rules **E1**–**E13**

Supporting evidence: [../../reviews/2026-07-29-ossie-converter-learnings.md](../../reviews/2026-07-29-ossie-converter-learnings.md) (**P1**–**P21**) and [../../reviews/2026-07-29-ossie-tpcds-fidelity.md](../../reviews/2026-07-29-ossie-tpcds-fidelity.md) (**F1**–**F21**).

---

## Scope: this is Plan A of four

The converter is too large for one plan and splits cleanly on dependency order. Each plan produces working, independently testable software.

| Plan | Scope | Depends on |
|---|---|---|
| **A — Foundations (this plan)** | package skeleton, CI, constants, YAML-1.2 codec, `ConverterIssue`, stash, identifiers, keys | — |
| **B — Expression translation** | the 146-row function map as code; `E1`–`E13`; both directions of expression rewriting | A |
| **C — `thoughtspot_to_ossie`** | Model + Table + SQL View TML → Ossie; `KD1`–`KD3` applied; issue emission | A, B |
| **D — `ossie_to_thoughtspot` + round-trip** | `R1`–`R11`; golden fixtures; TPC-DS pair; property-based round-trip | A, B, C |

**Do not start B, C or D from this plan.** Each gets its own plan written after its predecessor merges, so later plans can consume what the earlier ones actually built rather than what they intended to build.

---

## Global Constraints

Copied verbatim from the spec and the upstream contribution rules. Every task's requirements implicitly include this section.

- **Package name:** `apache-ossie-thoughtspot`. **Import name:** `ossie_thoughtspot`. **Directory:** `converters/thoughtspot/`. Vendor-named, not format-named — `#285`'s original `tml_to_ossie` / `ossie_to_tml` predates the OSI→Ossie rename and does not match the convention every other converter follows.
- **ASF license header on every new source file**, including tests and YAML fixtures. Copy the exact 17-line header from `converters/databricks/src/ossie_databricks/_common.py`. Upstream's PR checklist gates this.
- **No third-party dependency beyond `PyYAML>=6.0`** at runtime (P17). Adding one requires PMC/IPMC approval per the PR template. `pytest` and `hypothesis` are dev-only.
- **Ossie spec version:** `0.2.0.dev0`, pinned as `apache/ossie @ b5da5d6`. Accept by `major.minor` series rather than exact string — upstream's first release is proposed as **0.3.0**, not 0.2.0, so an exact-string pin will break on release.
- **Dialect label and vendor key are separate constants** (P6), never one shared string, even though both currently read `THOUGHTSPOT`.
- **`custom_extensions[].data` is a serialised JSON string, never a nested object** (P1, X2). `ossie-schema.json:73-76` types it `"string"` and `:66-80` sets `additionalProperties: false`.
- **`THOUGHTSPOT` is a registered Ossie dialect** as of apache/ossie#351, merged
  **2026-09-01** and approved by the project's ASF mentor. It is in the `Dialect` enum in
  `core-spec/ossie-schema.json`, in `SKIP_SQL_VALIDATION` in `validation/validate.py`, and in
  `OssieDialect` in `python/src/ossie/models.py`. Emit it. Per learnings **P8**, also emit an
  `ANSI_SQL` entry alongside wherever the expression is portable, so consumers that do not
  implement our dialect still get something executable — that is what `PORTABLE_DIALECT` is
  for. *(This constraint previously read "never emit a `THOUGHTSPOT` dialect entry until
  apache/ossie#351 merges", which was correct when written and is now inverted. Plans B–D
  inherit the new form.)*
- **Write every line fresh. Port nothing from `tools/ts-cli/` or any ThoughtSpot product.**
  Per Jean-Baptiste Onofré (Ossie mentor, IPMC) on `dev@ossie.apache.org`, 2026-08-31:
  *"the license has to be AL v2 and if the code is coming from another product, SGA and
  license change is required."* A Software Grant Agreement is a legal process, not a
  paperwork step, and it would convert an ordinary contribution into one needing corporate
  sign-off.

  **This bites hardest in Plan B**, where the temptation is concrete rather than
  hypothetical: `tools/ts-cli/ts_cli/formula_common.py` (478 lines) and `sv_translate.py`
  (999 lines) in the ThoughtSpot skills repo already implement working ThoughtSpot formula
  translation, and reaching for them is the obvious efficiency. They are ThoughtSpot-owned
  work in a ThoughtSpot-org repository, so porting them upstream is exactly the case JB
  describes.

  What may be used: the **mapping documents**, which are prose specifications of behaviour
  rather than code, and the **behaviour** they describe. What may not: source, structure
  copied closely enough to be a derivative, test fixtures taken from that repo, or the
  packaged JSON maps. A reviewer should be able to diff any module here against its
  `ts_cli` counterpart and see two independent implementations of one documented ruleset.
- **Python floor 3.10** — `converters/databricks` uses `str | None` syntax, and the repo's own tooling assumes 3.10+.

---

## File Structure

```
converters/thoughtspot/
  README.md                              Direction statement + coverage matrix (P14, P21)
  pyproject.toml                         Package metadata; PyYAML floor; console script
  uv.lock                                Committed in the same PR as the first test (P13)
  src/ossie_thoughtspot/
    __init__.py                          Version, public re-exports
    constants.py                         VENDOR_KEY, DIALECT, STASH_VERSION, SPEC_SERIES
    _yaml.py                             YAML-1.2 Loader/Dumper pair (P7)
    issues.py                            ConverterIssue, Severity, IssueLog (P10)
    errors.py                            ConversionError
    stash.py                             custom_extensions read/write/merge (X1-X9, P9, P15)
    identifiers.py                       Normalisation + collision resolution (ID1-ID4)
    keys.py                              primary_key / unique_keys derivation (KD1-KD3)
  tests/
    conftest.py                          sys.path shim (P17)
    test_yaml.py  test_issues.py  test_stash.py  test_identifiers.py  test_keys.py
.github/workflows/converter-thoughtspot-ci.yml
```

Each module has one responsibility and no cross-imports except `stash.py` → `errors.py`/`constants.py` and `keys.py` → `issues.py`. `tml_to_ossie.py` and `ossie_to_thoughtspot.py` are deliberately absent — they are Plans C and D.

---

### Task 1: Package skeleton, CI, and the license-header fixture

**Files:**
- Create: `converters/thoughtspot/pyproject.toml`
- Create: `converters/thoughtspot/src/ossie_thoughtspot/__init__.py`
- Create: `converters/thoughtspot/tests/conftest.py`
- Create: `.github/workflows/converter-thoughtspot-ci.yml`
- Test: `converters/thoughtspot/tests/test_packaging.py`

**Interfaces:**
- Consumes: nothing
- Produces: `ossie_thoughtspot.__version__: str`; an importable package; a CI workflow keyed on `converters/thoughtspot/**`

**Why CI lands in this task, not later.** Finding F18 recorded that the databricks converter — upstream's best test suite — shipped with *no* CI workflow and no lockfile, so its tests ran only when a contributor remembered. That was closed upstream by PR #261, but the lesson is why P13 says the workflow and the lockfile go in the same PR as the first test. A test suite nothing invokes is not a gate.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/test_packaging.py
"""Packaging invariants that upstream's PR checklist gates."""
from pathlib import Path

import ossie_thoughtspot

ROOT = Path(__file__).resolve().parents[1]
LICENSE_MARKER = "Licensed to the Apache Software Foundation (ASF)"


def test_package_exposes_a_version():
    assert ossie_thoughtspot.__version__ == "0.1.0"


def test_every_source_file_carries_the_asf_header():
    sources = [
        *(ROOT / "src").rglob("*.py"),
        *(ROOT / "tests").rglob("*.py"),
    ]
    assert sources, "expected at least one source file"
    missing = [
        str(p.relative_to(ROOT))
        for p in sources
        if LICENSE_MARKER not in p.read_text(encoding="utf-8")
    ]
    assert missing == [], f"ASF header missing from: {missing}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd converters/thoughtspot && python -m pytest tests/test_packaging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ossie_thoughtspot'`

- [ ] **Step 3: Write the minimal implementation**

Create `converters/thoughtspot/tests/conftest.py` (P17 — the two-line `sys.path` shim, so tests run without an editable install):

```python
# <ASF header>
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
```

Create `converters/thoughtspot/src/ossie_thoughtspot/__init__.py`:

```python
# <ASF header>
"""Bidirectional converter between ThoughtSpot TML and the Apache Ossie semantic model."""

__version__ = "0.1.0"
```

Create `converters/thoughtspot/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "apache-ossie-thoughtspot"
version = "0.1.0"
description = "Convert between ThoughtSpot TML and the Apache Ossie semantic model"
requires-python = ">=3.10"
dependencies = ["PyYAML>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=7.0", "hypothesis>=6.0"]

[project.urls]
homepage = "https://ossie.apache.org/"

[tool.setuptools.packages.find]
where = ["src"]
```

**No `[project.scripts]` entry yet.** The console script points at `ossie_thoughtspot.cli:main`, and `cli.py` does not exist until Plan C. Declaring it here would make `pip install -e .` succeed and then `ossie-thoughtspot` fail at the import — a broken entry point that no test in this plan would catch.

Copy the ASF header verbatim into every new `.py` file. Take it from `converters/databricks/src/ossie_databricks/_common.py` lines 1-17 so it matches byte-for-byte.

Create `.github/workflows/converter-thoughtspot-ci.yml`, modelled on `converter-databricks-ci.yml`:

```yaml
# <ASF header, YAML comment form>
name: Converters ThoughtSpot CI
on:
  push:
    branches: [ "main" ]
    paths:
      - 'converters/thoughtspot/**'
      - '.github/workflows/converter-thoughtspot-ci.yml'
  pull_request:
    branches: [ "main" ]
    paths:
      - 'converters/thoughtspot/**'
      - '.github/workflows/converter-thoughtspot-ci.yml'

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        working-directory: converters/thoughtspot
        run: pip install -e ".[dev]"
      - name: Test
        working-directory: converters/thoughtspot
        run: python -m pytest tests/ -v
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd converters/thoughtspot && python -m pytest tests/ -v`
Expected: 2 passed

- [ ] **Step 5: Generate and commit the lockfile**

Run: `cd converters/thoughtspot && uv lock`
Expected: `uv.lock` created

- [ ] **Step 6: Commit**

```bash
git add converters/thoughtspot .github/workflows/converter-thoughtspot-ci.yml
git commit -m "feat(thoughtspot): package skeleton, CI workflow, and ASF header gate"
```

---

### Task 2: Constants

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/constants.py`
- Test: `converters/thoughtspot/tests/test_constants.py`

**Interfaces:**
- Consumes: nothing
- Produces: `VENDOR_KEY: str`, `DIALECT: str`, `FALLBACK_DIALECT: str`, `STASH_VERSION: int`, `SPEC_SERIES: str`, `DIALECT_IS_REGISTERED: bool`

**Why two constants that hold the same string.** P6. `VENDOR_KEY` is the `custom_extensions[].vendor_name` value; `DIALECT` is the expression-language dialect label. They are the same word today and are governed by different upstream processes — the vendor key needs no spec change (`Vendor` is `examples`-only, "any string value is accepted"), while the dialect is a closed enum awaiting apache/ossie#351. Sharing one constant would couple them and hide that difference the first time either moves.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/test_constants.py
# <ASF header>
from ossie_thoughtspot import constants


def test_vendor_key_and_dialect_are_distinct_constants():
    # P6: same value today, different upstream governance. Must not be one name.
    assert constants.VENDOR_KEY == "THOUGHTSPOT"
    assert constants.DIALECT == "THOUGHTSPOT"
    # Both names must exist independently, so a later divergence touches one call site.
    assert "VENDOR_KEY" in vars(constants)
    assert "DIALECT" in vars(constants)


def test_dialect_is_not_yet_registered_upstream():
    # apache/ossie#351 is open. Until it merges, emitting DIALECT fails schema validation.
    assert constants.DIALECT_IS_REGISTERED is False
    assert constants.FALLBACK_DIALECT == "ANSI_SQL"


def test_spec_series_is_major_minor_not_an_exact_version():
    # Upstream's first release is proposed as 0.3.0; an exact pin on 0.2.0.dev0 would break.
    assert constants.SPEC_SERIES == "0.2"
    assert constants.STASH_VERSION == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd converters/thoughtspot && python -m pytest tests/test_constants.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ossie_thoughtspot.constants'`

- [ ] **Step 3: Write the minimal implementation**

```python
# converters/thoughtspot/src/ossie_thoughtspot/constants.py
# <ASF header>
"""Vocabulary constants.

VENDOR_KEY and DIALECT hold the same string today and are deliberately separate
names (learnings report P6). They are governed differently upstream: the vendor
key needs no spec change because `Vendor` is an `examples` list that accepts any
string, while the dialect is a closed enum and is pending apache/ossie#351.
"""

#: `custom_extensions[].vendor_name` value for ThoughtSpot-owned entries.
VENDOR_KEY = "THOUGHTSPOT"

#: Expression-language dialect label. NOT yet a member of the Ossie Dialect enum.
DIALECT = "THOUGHTSPOT"

#: Flip to True only when apache/ossie#351 merges. Until then, emitting DIALECT
#: produces a hard schema-validation failure, so expressions ship under the
#: fallback with the real dialect preserved in the stash (the converters/nvidia
#: pattern).
DIALECT_IS_REGISTERED = False

#: Dialect used while DIALECT_IS_REGISTERED is False.
FALLBACK_DIALECT = "ANSI_SQL"

#: Ossie spec series this converter targets, matched on major.minor. Not an exact
#: version: upstream's first release is proposed as 0.3.0, not 0.2.0.
SPEC_SERIES = "0.2"

#: Shape version of the custom_extensions payload (rule X3). Bump when the
#: payload's shape changes, never for a value change.
STASH_VERSION = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd converters/thoughtspot && python -m pytest tests/test_constants.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/constants.py converters/thoughtspot/tests/test_constants.py
git commit -m "feat(thoughtspot): vocabulary constants with dialect registration flag"
```

---

### Task 3: YAML 1.2 codec

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/_yaml.py`
- Test: `converters/thoughtspot/tests/test_yaml.py`

**Interfaces:**
- Consumes: nothing
- Produces: `load(text: str) -> object`, `dump(data: object) -> str`

**Why this is its own module and not `yaml.safe_load`.** P7, and F8 in the fidelity report. PyYAML implements YAML **1.1**, where the bare scalars `on`, `off`, `yes`, `no`, `y`, `n` resolve to booleans. TML uses such tokens as ordinary strings — a column literally named `On` or a format token `y` — and a bare `yaml.safe_load` silently turns them into `True`/`False`. The round trip then writes back a boolean and the document is corrupted with no error anywhere. `converters/databricks/_common.py` solves this with a `_Yaml12Loader`; `converters/nvidia` does not, and uses bare `yaml.safe_load`.

Both halves are needed. A 1.2 loader alone still lets the dumper emit an unquoted `on`, which the *next* reader — possibly a 1.1 one — resolves as a boolean.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/test_yaml.py
# <ASF header>
import pytest

from ossie_thoughtspot import _yaml

YAML11_BOOL_TOKENS = ["on", "On", "ON", "off", "Off", "yes", "Yes", "no", "No", "y", "n"]


@pytest.mark.parametrize("token", YAML11_BOOL_TOKENS)
def test_yaml11_bool_tokens_load_as_strings(token):
    # PyYAML implements YAML 1.1 and would return True/False for these.
    assert _yaml.load(f"value: {token}") == {"value": token}


@pytest.mark.parametrize("literal,expected", [("true", True), ("True", True), ("false", False)])
def test_real_booleans_still_load_as_booleans(literal, expected):
    assert _yaml.load(f"value: {literal}") == {"value": expected}


@pytest.mark.parametrize("token", YAML11_BOOL_TOKENS)
def test_yaml11_bool_tokens_are_quoted_on_dump(token):
    # Unquoted, a YAML 1.1 reader downstream would resolve these back to booleans.
    assert _yaml.load(_yaml.dump({"value": token})) == {"value": token}
    assert f"'{token}'" in _yaml.dump({"value": token})


def test_ordinary_strings_are_not_gratuitously_quoted():
    assert _yaml.dump({"value": "Region"}).strip() == "value: Region"


def test_round_trip_preserves_key_order():
    src = {"z": 1, "a": 2, "m": 3}
    assert list(_yaml.load(_yaml.dump(src))) == ["z", "a", "m"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd converters/thoughtspot && python -m pytest tests/test_yaml.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ossie_thoughtspot._yaml'`

- [ ] **Step 3: Write the minimal implementation**

```python
# converters/thoughtspot/src/ossie_thoughtspot/_yaml.py
# <ASF header>
"""YAML 1.2 codec.

PyYAML implements YAML 1.1, in which `on`, `off`, `yes`, `no`, `y` and `n`
resolve to booleans. TML uses such tokens as ordinary strings, so a bare
`yaml.safe_load` corrupts them silently (learnings report P7, fidelity F8).

Both directions matter. The loader stops 1.1 bool tokens becoming booleans; the
dumper quotes them on the way out so the next reader — which may be a 1.1
implementation — cannot re-resolve them.
"""
import re

import yaml

#: YAML 1.2 core schema: only these spellings are booleans.
_YAML12_BOOL = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")

#: Bare scalars YAML 1.1 resolves as booleans and YAML 1.2 does not.
_YAML11_ONLY_BOOLS = frozenset(
    {"y", "Y", "yes", "Yes", "YES", "n", "N", "no", "No", "NO",
     "on", "On", "ON", "off", "Off", "OFF"}
)


class Yaml12Loader(yaml.SafeLoader):
    """SafeLoader with the YAML 1.1 boolean resolver narrowed to the 1.2 set."""


# Drop the inherited bool resolver outright, then reinstate the 1.2-only one.
# Mutating in place would affect SafeLoader itself, so rebuild the mapping.
Yaml12Loader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Yaml12Loader.add_implicit_resolver("tag:yaml.org,2002:bool", _YAML12_BOOL, list("tTfF"))


class Yaml12Dumper(yaml.SafeDumper):
    """SafeDumper that quotes strings a YAML 1.1 reader would take for booleans."""


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "'" if data in _YAML11_ONLY_BOOLS else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


Yaml12Dumper.add_representer(str, _represent_str)


def load(text: str) -> object:
    """Parse YAML text under YAML 1.2 boolean rules."""
    return yaml.load(text, Loader=Yaml12Loader)


def dump(data: object) -> str:
    """Serialise to YAML, preserving insertion order and quoting 1.1 bool tokens."""
    return yaml.dump(data, Dumper=Yaml12Dumper, sort_keys=False, default_flow_style=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd converters/thoughtspot && python -m pytest tests/test_yaml.py -v`
Expected: 27 passed

- [ ] **Step 5: Commit**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/_yaml.py converters/thoughtspot/tests/test_yaml.py
git commit -m "feat(thoughtspot): YAML 1.2 codec so on/off/yes/no survive a round trip"
```

---

### Task 4: Structured issue reporting

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/errors.py`
- Create: `converters/thoughtspot/src/ossie_thoughtspot/issues.py`
- Test: `converters/thoughtspot/tests/test_issues.py`

**Interfaces:**
- Consumes: nothing
- Produces: `ConversionError(Exception)`; `Severity` (`INFO`/`WARNING`/`ERROR`); `ConverterIssue(code, severity, message, object_ref, remedy=None)`; `IssueLog` with `.add(...)`, `.extend(...)`, `.as_dicts() -> list[dict]`, `.has_errors() -> bool`, `.count_by_severity() -> dict[str, int]`

**Why this is a Task-4 concern and not an afterthought.** Discussion #325 — the MetricFlow/dbt-databricks converter feedback that reads as the community's de facto quality bar — treats a silent drop as a **contract violation**, not a documentation gap: it flags a lost `display_name` as *"contra the README's 'never silently drops a field'"*. So every declared loss must produce an issue object at conversion time, not merely a row in a coverage matrix. The same discussion also flags **warning noise** as a defect (*"dozens per model, all noise"*), which is why `Severity` exists and why `count_by_severity` is part of the interface — a caller must be able to summarise rather than print every line.

`NM2` now raises the stakes: table `rls_rules` is the mechanism ThoughtSpot customers are migrating onto, so its loss is **ERROR**, and the message must name every affected table.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/test_issues.py
# <ASF header>
import pytest

from ossie_thoughtspot.errors import ConversionError
from ossie_thoughtspot.issues import ConverterIssue, IssueLog, Severity


def test_issue_requires_an_object_reference():
    # An issue a reader cannot trace to an object is noise (#325).
    with pytest.raises(TypeError):
        ConverterIssue(code="TS001", severity=Severity.WARNING, message="something")


def test_as_dicts_is_json_serialisable_and_stable():
    log = IssueLog()
    log.add(
        code="TS_RLS_DROPPED",
        severity=Severity.ERROR,
        message="Row-level security rules dropped from 2 tables: ORDERS, CUSTOMERS",
        object_ref="model:Sales",
        remedy="Re-apply the rules in the target instance before use.",
    )
    assert log.as_dicts() == [
        {
            "code": "TS_RLS_DROPPED",
            "severity": "ERROR",
            "message": "Row-level security rules dropped from 2 tables: ORDERS, CUSTOMERS",
            "object_ref": "model:Sales",
            "remedy": "Re-apply the rules in the target instance before use.",
        }
    ]


def test_has_errors_distinguishes_severity():
    log = IssueLog()
    log.add(code="TS_X", severity=Severity.WARNING, message="m", object_ref="o")
    assert log.has_errors() is False
    log.add(code="TS_Y", severity=Severity.ERROR, message="m", object_ref="o")
    assert log.has_errors() is True


def test_count_by_severity_supports_summarising_instead_of_printing():
    # #325 treats a warning storm as a defect; a caller must be able to summarise.
    log = IssueLog()
    for i in range(30):
        log.add(code="TS_W", severity=Severity.WARNING, message=f"m{i}", object_ref=f"col{i}")
    log.add(code="TS_E", severity=Severity.ERROR, message="m", object_ref="o")
    assert log.count_by_severity() == {"ERROR": 1, "WARNING": 30}


def test_conversion_error_is_distinct_from_an_issue():
    # A malformed stash is a hard error (X4), not a loggable issue.
    assert issubclass(ConversionError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd converters/thoughtspot && python -m pytest tests/test_issues.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ossie_thoughtspot.errors'`

- [ ] **Step 3: Write the minimal implementation**

```python
# converters/thoughtspot/src/ossie_thoughtspot/errors.py
# <ASF header>
"""Hard failures. Distinct from ConverterIssue, which records a survivable loss."""


class ConversionError(Exception):
    """Raised when the converter cannot proceed — e.g. a malformed stash (rule X4)."""
```

```python
# converters/thoughtspot/src/ossie_thoughtspot/issues.py
# <ASF header>
"""Structured, never-silent loss reporting.

Discussion apache/ossie#325 treats a silently dropped field as a contract
violation rather than a documentation gap, so every declared loss produces an
issue here at conversion time. The same discussion treats a warning storm as a
defect, which is why severity is first-class and why callers can summarise via
count_by_severity() instead of printing every line.
"""
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ConverterIssue:
    """One declared loss or degradation, traceable to a specific object.

    object_ref is mandatory: an issue a reader cannot trace to an object cannot
    be acted on, which is the complaint #325 raises about warning noise.
    """

    code: str
    severity: Severity
    message: str
    object_ref: str
    remedy: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "object_ref": self.object_ref,
            "remedy": self.remedy,
        }


@dataclass
class IssueLog:
    """Ordered collection of issues raised during one conversion."""

    issues: list[ConverterIssue] = field(default_factory=list)

    def add(
        self,
        *,
        code: str,
        severity: Severity,
        message: str,
        object_ref: str,
        remedy: str | None = None,
    ) -> None:
        self.issues.append(
            ConverterIssue(
                code=code,
                severity=severity,
                message=message,
                object_ref=object_ref,
                remedy=remedy,
            )
        )

    def extend(self, other: "IssueLog") -> None:
        self.issues.extend(other.issues)

    def as_dicts(self) -> list[dict[str, str | None]]:
        return [i.as_dict() for i in self.issues]

    def has_errors(self) -> bool:
        return any(i.severity is Severity.ERROR for i in self.issues)

    def count_by_severity(self) -> dict[str, int]:
        return dict(Counter(i.severity.value for i in self.issues))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd converters/thoughtspot && python -m pytest tests/test_issues.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/errors.py converters/thoughtspot/src/ossie_thoughtspot/issues.py converters/thoughtspot/tests/test_issues.py
git commit -m "feat(thoughtspot): structured never-silent issue reporting"
```

---

### Task 5: The `custom_extensions` stash

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/stash.py`
- Test: `converters/thoughtspot/tests/test_stash.py`

**Interfaces:**
- Consumes: `constants.VENDOR_KEY`, `constants.STASH_VERSION`, `errors.ConversionError`
- Produces: `read_stash(obj: dict) -> dict`; `write_stash(obj: dict, payload: dict) -> dict`; `restore(payload: dict, key: str, derived, *, witness=None, witness_key=None)`

**The rules this implements**, from the construct mapping:

| Rule | Requirement |
|---|---|
| **X1** | One entry per object, `vendor_name: THOUGHTSPOT`. Merge into an existing entry rather than appending a second. |
| **X2** | `data` is a JSON **string**, never a nested object. Compare parsed, never raw. |
| **X3** | `_v` is an integer shape version. |
| **X4** | Malformed JSON raises `ConversionError` naming the object — never a bare `json` traceback. |
| **X5** | Restoration is **stash-if-present-and-still-current-else-derive**. |
| **X6** | Write nothing when the payload would be empty. |
| **X7** | Foreign-vendor entries pass through untouched. |
| **X8** | No `guid`, `obj_id` or `fqn` under any key. |

**X5 is the subtle one and the reason `restore()` takes a witness.** A plain stash-if-present rule silently discards a user's edit: someone changes an expression in the Ossie document, the stash still describes the old one, and the converter prefers the stash. `converters/nvidia` guards this — `_expression_matches` compares the live value against a recorded copy before reusing the preserved form. `witness` is the live value; `witness_key` names where the recorded copy lives in the payload. When they disagree, the stash is dropped for that key and the derived value wins.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/test_stash.py
# <ASF header>
import json

import pytest

from ossie_thoughtspot import stash
from ossie_thoughtspot.constants import STASH_VERSION, VENDOR_KEY
from ossie_thoughtspot.errors import ConversionError


def test_write_stash_serialises_data_as_a_json_string_not_an_object():
    # X2: ossie-schema.json types `data` as "string".
    obj = stash.write_stash({}, {"join_type": "LEFT_OUTER"})
    entry = obj["custom_extensions"][0]
    assert entry["vendor_name"] == VENDOR_KEY
    assert isinstance(entry["data"], str)
    assert json.loads(entry["data"])["join_type"] == "LEFT_OUTER"


def test_write_stash_stamps_the_shape_version():
    obj = stash.write_stash({}, {"k": "v"})
    assert json.loads(obj["custom_extensions"][0]["data"])["_v"] == STASH_VERSION


def test_write_stash_writes_nothing_for_an_empty_payload():
    # X6: a converted document stays clean where ThoughtSpot added nothing.
    assert stash.write_stash({}, {}) == {}


def test_write_stash_merges_into_the_existing_own_entry():
    # X1: one entry per object, merged — never a second THOUGHTSPOT entry.
    obj = stash.write_stash({}, {"a": 1})
    obj = stash.write_stash(obj, {"b": 2})
    own = [e for e in obj["custom_extensions"] if e["vendor_name"] == VENDOR_KEY]
    assert len(own) == 1
    assert json.loads(own[0]["data"])["a"] == 1
    assert json.loads(own[0]["data"])["b"] == 2


def test_foreign_vendor_entries_pass_through_untouched():
    # X7.
    obj = {"custom_extensions": [{"vendor_name": "DATABRICKS", "data": '{"x": 1}'}]}
    out = stash.write_stash(obj, {"a": 1})
    foreign = [e for e in out["custom_extensions"] if e["vendor_name"] == "DATABRICKS"]
    assert foreign == [{"vendor_name": "DATABRICKS", "data": '{"x": 1}'}]


def test_write_stash_refuses_identity_keys():
    # X8: a portable document must not carry instance-local identity.
    for key in ("guid", "obj_id", "fqn"):
        with pytest.raises(ConversionError, match=key):
            stash.write_stash({}, {key: "abc-123"})


def test_read_stash_raises_a_named_error_on_malformed_json():
    # X4: never a bare json traceback.
    obj = {"name": "orders", "custom_extensions": [{"vendor_name": VENDOR_KEY, "data": "{not json"}]}
    with pytest.raises(ConversionError, match="orders"):
        stash.read_stash(obj)


def test_read_stash_returns_empty_when_there_is_no_own_entry():
    assert stash.read_stash({"custom_extensions": [{"vendor_name": "OMNI", "data": "{}"}]}) == {}


def test_restore_prefers_the_stash_when_the_witness_still_agrees():
    # X5, positive case.
    payload = {"on_expression": "a = b", "ossie_expression": "a = b"}
    assert stash.restore(payload, "on_expression", "DERIVED",
                         witness="a = b", witness_key="ossie_expression") == "a = b"


def test_restore_rederives_when_the_witness_has_changed():
    # X5, the case a plain stash-if-present rule gets wrong: the user edited the
    # Ossie document, so the stashed copy is stale and must not win.
    payload = {"on_expression": "a = b", "ossie_expression": "a = b"}
    assert stash.restore(payload, "on_expression", "DERIVED",
                         witness="a = c", witness_key="ossie_expression") == "DERIVED"


def test_restore_falls_back_to_derived_when_the_key_is_absent():
    assert stash.restore({}, "on_expression", "DERIVED") == "DERIVED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd converters/thoughtspot && python -m pytest tests/test_stash.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ossie_thoughtspot.stash'`

- [ ] **Step 3: Write the minimal implementation**

```python
# converters/thoughtspot/src/ossie_thoughtspot/stash.py
# <ASF header>
"""custom_extensions[THOUGHTSPOT] payload handling — rules X1-X9.

The stash lives in the *Ossie* document, so it is written on the way in and read
on the way out. Rule X9 follows from that: it can only carry what TML contains.
"""
import json
from typing import Any

from .constants import STASH_VERSION, VENDOR_KEY
from .errors import ConversionError

#: X8 — instance-local identity never travels in a portable document.
_FORBIDDEN_KEYS = frozenset({"guid", "obj_id", "fqn"})


def _object_label(obj: dict) -> str:
    return str(obj.get("name", "<unnamed>"))


def read_stash(obj: dict) -> dict[str, Any]:
    """Return this object's parsed THOUGHTSPOT payload, or {} if it has none."""
    for entry in obj.get("custom_extensions") or []:
        if entry.get("vendor_name") != VENDOR_KEY:
            continue
        raw = entry.get("data")
        if raw is None:
            return {}
        if not isinstance(raw, str):
            # X2: `data` is typed as a string; a nested object is a spec violation.
            raise ConversionError(
                f"custom_extensions data for {_object_label(obj)!r} is "
                f"{type(raw).__name__}, expected a JSON string"
            )
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            # X4: name the object; never surface a bare json traceback.
            raise ConversionError(
                f"malformed THOUGHTSPOT custom_extensions payload on "
                f"{_object_label(obj)!r}: {exc}"
            ) from exc
    return {}


def write_stash(obj: dict, payload: dict[str, Any]) -> dict:
    """Merge `payload` into this object's THOUGHTSPOT entry, returning a new dict.

    Foreign-vendor entries are preserved untouched (X7). An empty resulting
    payload writes nothing at all (X6).
    """
    forbidden = _FORBIDDEN_KEYS & set(payload)
    if forbidden:
        # X8.
        raise ConversionError(
            f"refusing to stash instance-local identity key(s) "
            f"{sorted(forbidden)} on {_object_label(obj)!r}"
        )

    merged = {**read_stash(obj), **payload}
    if not merged:
        return dict(obj)

    merged["_v"] = STASH_VERSION  # X3
    others = [e for e in obj.get("custom_extensions") or [] if e.get("vendor_name") != VENDOR_KEY]
    out = dict(obj)
    # X1: exactly one own entry, merged rather than appended.
    out["custom_extensions"] = [
        *others,
        {"vendor_name": VENDOR_KEY, "data": json.dumps(merged, sort_keys=True)},
    ]
    return out


def restore(
    payload: dict[str, Any],
    key: str,
    derived: Any,
    *,
    witness: Any = None,
    witness_key: str | None = None,
) -> Any:
    """Rule X5 — stash-if-present-and-still-current-else-derive.

    `witness` is the live Ossie value and `witness_key` names the copy recorded
    alongside the stashed value. When they disagree the Ossie document has been
    edited since the stash was written, so the stash is stale for this key and
    `derived` wins. Without a witness this degrades to stash-if-present, which is
    correct only for values nothing downstream can edit.
    """
    if key not in payload:
        return derived
    if witness_key is not None and payload.get(witness_key) != witness:
        return derived
    return payload[key]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd converters/thoughtspot && python -m pytest tests/test_stash.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/stash.py converters/thoughtspot/tests/test_stash.py
git commit -m "feat(thoughtspot): custom_extensions stash with staleness-guarded restore"
```

---

### Task 6: Identifier derivation

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/identifiers.py`
- Test: `converters/thoughtspot/tests/test_identifiers.py`

**Interfaces:**
- Consumes: nothing
- Produces: `normalise(display_name: str) -> str`; `Allocator` with `.allocate(display_name: str) -> str`; `split_column_ref(ref: str) -> tuple[str, str]`; `format_column_ref(table: str, column: str) -> str`

**The rules this implements:**

- **ID1** — `field.name` is a normalised identifier; the exact display name goes in `field.label`. *Watch item: if apache/ossie#287 merges, the display name's home becomes `display_label` and `label` reverts to categorisation. Plan C consumes whichever has landed; this task only produces the normalised identifier and returns the original unchanged for the caller to place.*
- **ID2** — normalisation collides (`Order Date` and `Order-Date` both → `order_date`), and Ossie resolves regular identifiers **case-insensitively** (`expression_language.md:77`) while `validate.py` only rejects exact-string duplicates. So the allocator must fold case when detecting a collision, and resolve with a numeric suffix.
- **ID3** — `[TABLE::Column]` ↔ `dataset.field`, rewritten never passed through.
- **ID4** — ThoughtSpot requires display-name uniqueness across `columns[]` *and* `formulas[]` in one Model, which is stricter than Ossie's per-dataset field uniqueness. Plan D enforces this on the reverse leg; this task provides the allocator it uses.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/test_identifiers.py
# <ASF header>
import pytest

from ossie_thoughtspot import identifiers


@pytest.mark.parametrize("display,expected", [
    ("Order Date", "order_date"),
    ("Order-Date", "order_date"),
    ("Total Sales (AUD)", "total_sales_aud"),
    ("  Leading and trailing  ", "leading_and_trailing"),
    ("Multiple   spaces", "multiple_spaces"),
    ("Already_snake", "already_snake"),
    ("2024 Revenue", "n_2024_revenue"),
])
def test_normalise(display, expected):
    assert identifiers.normalise(display) == expected


def test_normalise_rejects_a_name_that_normalises_to_nothing():
    with pytest.raises(ValueError, match="normalises to an empty identifier"):
        identifiers.normalise("!!!")


def test_allocator_resolves_a_collision_with_a_numeric_suffix():
    # ID2: two distinct display names folding onto one identifier.
    alloc = identifiers.Allocator()
    assert alloc.allocate("Order Date") == "order_date"
    assert alloc.allocate("Order-Date") == "order_date_2"
    assert alloc.allocate("Order.Date") == "order_date_3"


def test_allocator_folds_case_when_detecting_collisions():
    # ID2: Ossie resolves regular identifiers case-insensitively, so a case-only
    # difference is ambiguous even though validate.py would accept it.
    alloc = identifiers.Allocator()
    assert alloc.allocate("Region") == "region"
    assert alloc.allocate("REGION") == "region_2"


def test_split_and_format_column_refs_round_trip():
    # ID3.
    assert identifiers.split_column_ref("[ORDERS::Order Date]") == ("ORDERS", "Order Date")
    assert identifiers.format_column_ref("ORDERS", "Order Date") == "[ORDERS::Order Date]"


def test_split_column_ref_rejects_a_malformed_reference():
    with pytest.raises(ValueError, match="not a ThoughtSpot column reference"):
        identifiers.split_column_ref("ORDERS::Order Date")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd converters/thoughtspot && python -m pytest tests/test_identifiers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ossie_thoughtspot.identifiers'`

- [ ] **Step 3: Write the minimal implementation**

```python
# converters/thoughtspot/src/ossie_thoughtspot/identifiers.py
# <ASF header>
"""Identifier derivation and column-reference rewriting — rules ID1-ID4.

ThoughtSpot has one `name` per column, serving as display name, search token and
cross-document key at once (gap G2). Ossie splits identifier from label, so the
identifier has to be derived — and derivation collides.
"""
import re

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_COLUMN_REF = re.compile(r"^\[(?P<table>[^\]:]+)::(?P<column>[^\]]+)\]$")


def normalise(display_name: str) -> str:
    """Fold a ThoughtSpot display name to an Ossie identifier (rule ID1)."""
    folded = _NON_ALNUM.sub("_", display_name.strip().lower()).strip("_")
    if not folded:
        raise ValueError(f"{display_name!r} normalises to an empty identifier")
    if folded[0].isdigit():
        # A leading digit is not a valid identifier in most consumers' grammars.
        folded = f"n_{folded}"
    return folded


class Allocator:
    """Allocates unique identifiers, resolving collisions with a numeric suffix.

    Collision detection folds case, because Ossie resolves regular identifiers
    case-insensitively (`core-spec/expression_language.md:77`) even though
    `validation/validate.py` only rejects exact-string duplicates. Detecting on
    the exact string would emit a document that validates and is still ambiguous.
    """

    def __init__(self) -> None:
        self._taken: set[str] = set()

    def allocate(self, display_name: str) -> str:
        base = normalise(display_name)
        candidate, suffix = base, 1
        while candidate.casefold() in self._taken:
            suffix += 1
            candidate = f"{base}_{suffix}"
        self._taken.add(candidate.casefold())
        return candidate


def split_column_ref(ref: str) -> tuple[str, str]:
    """`[TABLE::Column]` -> `("TABLE", "Column")` (rule ID3)."""
    match = _COLUMN_REF.match(ref.strip())
    if match is None:
        raise ValueError(f"{ref!r} is not a ThoughtSpot column reference")
    return match.group("table"), match.group("column")


def format_column_ref(table: str, column: str) -> str:
    """`("TABLE", "Column")` -> `[TABLE::Column]` (rule ID3)."""
    return f"[{table}::{column}]"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd converters/thoughtspot && python -m pytest tests/test_identifiers.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/identifiers.py converters/thoughtspot/tests/test_identifiers.py
git commit -m "feat(thoughtspot): identifier normalisation with case-folded collision resolution"
```

---

### Task 7: Key derivation

**Files:**
- Create: `converters/thoughtspot/src/ossie_thoughtspot/keys.py`
- Test: `converters/thoughtspot/tests/test_keys.py`

**Interfaces:**
- Consumes: `issues.IssueLog`, `issues.Severity`
- Produces: `Relationship` (dataclass: `name`, `to_dataset`, `to_columns`, `cardinality`, `has_residual_predicates`); `derive_keys(dataset_name, relationships, log) -> tuple[list[str] | None, list[list[str]]]`

**Why this module exists at all.** TML has no key declaration (gap **G3**), so every key in our Ossie output is manufactured. Upstream PR #330 now warns when a relationship's `to_columns` does not cover a declared key, and upstream issue #301 is literally *"`_build_relationships` emits relationships whose `to_columns` is not a key"* — another vendor hitting this first. Getting the derivation wrong is not cosmetic: `converters/databricks` (`ossie_to_metric_view.py:420`) reads a declared key plus `to_columns` and emits `rely: {at_most_one_match: true}`, so a fabricated key becomes another vendor's wrong numbers.

**KD1** — a relationship qualifies as key evidence only if its condition is *wholly* its equality pairs. A residual-predicate join (an FK equality narrowed by an effective-date window) is to-one *because of the narrowing*; its equality columns alone are not unique. `MANY_TO_MANY` is excluded for the same reason.
**KD2** — a relationship excluded by KD1 will trip #330's warning, and that warning is correct. Raise an issue naming the relationship rather than widening the key to silence it.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/test_keys.py
# <ASF header>
from ossie_thoughtspot.issues import IssueLog, Severity
from ossie_thoughtspot.keys import Relationship, derive_keys


def rel(name, to_columns, cardinality="MANY_TO_ONE", residual=False):
    return Relationship(
        name=name,
        to_dataset="customers",
        to_columns=to_columns,
        cardinality=cardinality,
        has_residual_predicates=residual,
    )


def test_single_qualifying_relationship_yields_a_primary_key():
    log = IssueLog()
    pk, uniques = derive_keys("customers", [rel("r1", ["customer_id"])], log)
    assert pk == ["customer_id"]
    assert uniques == [["customer_id"]]
    assert log.as_dicts() == []


def test_disagreeing_qualifying_relationships_yield_unique_keys_and_no_primary_key():
    # Choosing one would be a guess; both are real join targets.
    log = IssueLog()
    pk, uniques = derive_keys(
        "customers", [rel("by_id", ["customer_id"]), rel("by_email", ["email"])], log
    )
    assert pk is None
    assert sorted(uniques) == [["customer_id"], ["email"]]


def test_residual_predicate_relationship_is_not_key_evidence():
    # KD1: the equality columns alone are not unique — the narrowing makes it to-one.
    log = IssueLog()
    pk, uniques = derive_keys("customers", [rel("asof", ["ccy"], residual=True)], log)
    assert pk is None
    assert uniques == []


def test_many_to_many_is_not_key_evidence():
    log = IssueLog()
    pk, uniques = derive_keys("customers", [rel("bridge", ["c_id"], cardinality="MANY_TO_MANY")], log)
    assert pk is None
    assert uniques == []


def test_a_disqualified_sibling_raises_an_issue_naming_it():
    # KD2: the #330 warning it will trip is correct; explain it, do not silence it.
    log = IssueLog()
    pk, uniques = derive_keys(
        "customers", [rel("by_id", ["customer_id"]), rel("asof", ["ccy"], residual=True)], log
    )
    assert pk == ["customer_id"]
    issues = log.as_dicts()
    assert len(issues) == 1
    assert issues[0]["severity"] == Severity.WARNING.value
    assert "asof" in issues[0]["message"]


def test_column_order_within_a_composite_key_is_preserved():
    log = IssueLog()
    pk, _ = derive_keys("customers", [rel("r", ["region", "customer_id"])], log)
    assert pk == ["region", "customer_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd converters/thoughtspot && python -m pytest tests/test_keys.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ossie_thoughtspot.keys'`

- [ ] **Step 3: Write the minimal implementation**

```python
# converters/thoughtspot/src/ossie_thoughtspot/keys.py
# <ASF header>
"""primary_key / unique_keys derivation — rules KD1-KD3.

TML declares no keys (gap G3), so every key we emit is manufactured from the
join graph. Upstream PR #330 checks that a relationship's to_columns covers a
declared key, and converters/databricks turns a declared key into a
`rely.at_most_one_match` join hint — so a fabricated key becomes another
vendor's wrong numbers, not just a cosmetic error in ours.
"""
from dataclasses import dataclass

from .issues import IssueLog, Severity

_TO_ONE = frozenset({"MANY_TO_ONE", "ONE_TO_ONE"})


@dataclass(frozen=True)
class Relationship:
    """The subset of a relationship that key derivation needs."""

    name: str
    to_dataset: str
    to_columns: tuple[str, ...] | list[str]
    cardinality: str
    has_residual_predicates: bool


def _qualifies(rel: Relationship) -> bool:
    """KD1 — key evidence requires a to-one join whose condition is wholly equality."""
    return rel.cardinality in _TO_ONE and not rel.has_residual_predicates


def derive_keys(
    dataset_name: str, relationships: list[Relationship], log: IssueLog
) -> tuple[list[str] | None, list[list[str]]]:
    """Return (primary_key, unique_keys) for one dataset.

    primary_key is emitted only when the qualifying relationships agree on a
    single column set — where they disagree, choosing one is a guess, so the
    candidates go to unique_keys and no primary key is declared.
    """
    inbound = [r for r in relationships if r.to_dataset == dataset_name]
    qualifying = [r for r in inbound if _qualifies(r)]

    seen: list[list[str]] = []
    for rel in qualifying:
        cols = list(rel.to_columns)
        if cols and cols not in seen:
            seen.append(cols)

    # KD2 — a disqualified sibling will trip upstream's key-coverage warning.
    # That warning is correct. Explain it rather than widening the key to silence it.
    if seen:
        for rel in inbound:
            if _qualifies(rel):
                continue
            reason = (
                "its condition carries residual (non-equality) predicates"
                if rel.has_residual_predicates
                else f"its cardinality is {rel.cardinality}"
            )
            log.add(
                code="TS_KEY_COVERAGE",
                severity=Severity.WARNING,
                message=(
                    f"Relationship {rel.name!r} targets {dataset_name!r} on columns that are "
                    f"not a declared key, because {reason}. Ossie validation will report a "
                    f"to_columns coverage warning for it."
                ),
                object_ref=f"relationship:{rel.name}",
                remedy=(
                    "Expected. The relationship is genuinely not a key join; declaring a key "
                    "to silence the warning would assert uniqueness that does not hold."
                ),
            )

    primary_key = seen[0] if len(seen) == 1 else None
    return primary_key, seen
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd converters/thoughtspot && python -m pytest tests/test_keys.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add converters/thoughtspot/src/ossie_thoughtspot/keys.py converters/thoughtspot/tests/test_keys.py
git commit -m "feat(thoughtspot): key derivation that refuses to manufacture false keys"
```

---

### Task 8: README with the coverage matrix

**Files:**
- Create: `converters/thoughtspot/README.md`
- Test: `converters/thoughtspot/tests/test_readme.py`

**Interfaces:**
- Consumes: nothing
- Produces: a README stating direction and enumerating losses (P14, P21)

**Why a test on a README.** P21 says the limitations belong in a mapped/unmapped **coverage matrix**, not a prose list, and P16 says every checked-in artefact should be consumed by an assertion. The test is deliberately weak — it checks structure, not wording — because a test that asserts prose becomes a chore that gets deleted. It exists so the matrix cannot quietly disappear.

- [ ] **Step 1: Write the failing test**

```python
# converters/thoughtspot/tests/test_readme.py
# <ASF header>
import re
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_declares_both_directions():
    text = README.read_text(encoding="utf-8")
    assert "ThoughtSpot TML -> Ossie" in text or "ThoughtSpot TML → Ossie" in text
    assert "Ossie -> ThoughtSpot TML" in text or "Ossie → ThoughtSpot TML" in text


def test_readme_carries_a_coverage_matrix_with_rows():
    # P21: a matrix, not a prose limitations list.
    text = README.read_text(encoding="utf-8")
    assert "## Coverage matrix" in text
    body = text.split("## Coverage matrix", 1)[1]
    rows = re.findall(r"^\| *L\d+ *\|", body, flags=re.MULTILINE)
    assert len(rows) >= 1, "coverage matrix has no L-numbered limitation rows"


def test_readme_states_the_dialect_caveat():
    # The THOUGHTSPOT dialect is not registered until apache/ossie#351 merges.
    assert "351" in README.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd converters/thoughtspot && python -m pytest tests/test_readme.py -v`
Expected: FAIL with `FileNotFoundError`

- [ ] **Step 3: Write the minimal implementation**

Create `converters/thoughtspot/README.md` with the ASF header in HTML-comment form, then:

```markdown
# Apache Ossie ThoughtSpot Converter

Converts between **ThoughtSpot TML** and the Apache Ossie semantic model, in both
directions:

- **ThoughtSpot TML → Ossie** — reads a Model TML document plus the Table and SQL View
  documents it references, and emits one Ossie semantic model.
- **Ossie → ThoughtSpot TML** — reads one Ossie semantic model and emits the corresponding
  set of TML documents.

A single Ossie semantic model corresponds to **1 + N TML documents**, not one file: one
`model:` document plus one `table:` or `sql_view:` document per dataset. The converter reads
and writes the set.

File-to-file only. Nothing here calls a ThoughtSpot API.

## Status

Foundations only. Neither conversion direction is implemented yet.

**The `THOUGHTSPOT` dialect is not yet registered upstream** — see apache/ossie#351. Until
that merges, expressions are emitted under `ANSI_SQL` with the real dialect preserved in the
`custom_extensions` stash, because the `Dialect` enum is closed and a `THOUGHTSPOT` entry
fails schema validation.

## Coverage matrix

Every construct this converter does not carry, with its consequence. Each row raises a
structured `ConverterIssue` at conversion time — nothing is dropped silently.

| # | Construct | Limitation | Consequence |
|---|---|---|---|
| L1 | Object identity (`guid`, `obj_id`, `fqn`) | Not carried — instance-local by construction | A round-tripped document imports as a new object |
| L2 | Row-level security (`rls_rules`) | Not carried — rule expressions name instance-local groups | **ERROR severity.** Table RLS is ThoughtSpot's primary security mechanism; rules must be re-applied in the target |
| L3 | Presentation artifacts (Answers, Liveboards, charts) | Out of scope — Ossie models semantics, not visualisations | No loss to the semantic model |
| L4 | Spotter coaching objects | Separate object types; `ai_context.examples` is not interchangeable | Coaching must be re-created in the target |
| L5 | Aggregate-model associations (`aggregated_models`) | Entries are GUIDs of other Models — instance-local | Query routing is silently disabled; the issue is the only signal |
| L6 | Worksheets, Views, Sets, Alerts, Model Aliases | Predecessors or layers, not models | Convert the Model the alias points at instead |

## Rules

The full construct and expression mappings live in the ThoughtSpot skills repository and are
the normative source for this converter's behaviour. Rule identifiers referenced in the code
(`ID1`-`ID4`, `X1`-`X9`, `KD1`-`KD3`, `R1`-`R11`, `E1`-`E13`, `NM1`-`NM6`) are defined there.

**Before declaring any expression untranslatable, consult the function mapping.** Many window
and LOD constructs have exact native equivalents; declaring one untranslatable without
checking is an error (invariant I7).

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd converters/thoughtspot && python -m pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add converters/thoughtspot/README.md converters/thoughtspot/tests/test_readme.py
git commit -m "docs(thoughtspot): README with direction statement and coverage matrix"
```

---

## Definition of done for Plan A

- [ ] `python -m pytest tests/ -v` passes on Python 3.10 and 3.12
- [ ] `converter-thoughtspot-ci.yml` runs green on the fork
- [ ] Every `.py` and `README.md` carries the ASF header (gated by `test_packaging.py`)
- [ ] `uv.lock` committed
- [ ] No runtime dependency beyond `PyYAML>=6.0`
- [ ] No module imports `tml_to_ossie` or `ossie_to_thoughtspot` — they do not exist yet

## Open items this plan does not resolve

| Item | Effect on later plans |
|---|---|
| **BL-186 V1** — is the literal `calendar` a default sentinel or a real calendar name? One `GET /api/rest/2.0/calendars/…` read | Gates calendar emission in Plan C. Not needed for Plan A or B |
| **BL-186 V2** — does a non-`iso_code` `currency_type` survive a round trip? | Gates two `currency_type` forms in Plan D |
| **G8** — the documented temporal `data_type` set cites our own mapping table as though it were the product enum | Affects the datatype map in Plan C |
| ~~**apache/ossie#351** — the `THOUGHTSPOT` dialect~~ | **CLOSED 2026-09-01 — merged upstream.** `DIALECT_IS_REGISTERED` is now `True` and `FALLBACK_DIALECT` was renamed `PORTABLE_DIALECT`, since `ANSI_SQL`'s role changed from *instead of* to *alongside* (P8). Plan B no longer branches on it |
| **apache/ossie#287** — extended metadata | Would move five stash keys to first-class fields. Plan C and D branch on it |
| **Where the converter lives** — main repo or a per-vendor repo, asked on `dev@` 2026-08-31 | Changes the path in every task, nothing else |
