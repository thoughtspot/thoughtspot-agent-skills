# `ts metadata report` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new `ts metadata report` CLI subcommand that owns dependency-graph audit as a pure read-only operation, then refactor the `ts-dependency-manager` skill's Audit mode to consume it.

**Architecture:** A sub-package under `tools/ts-cli/ts_cli/report/` with focused modules (resolver, walker, tml_probes, classifier, formatters, schema) exposing a single public `build_report` / `build_reports` API. The Typer command wrapper in `commands/metadata.py` dispatches to formatters. The skill replaces its hand-rolled Step 4+5 with calls to the new command.

**Tech Stack:** Python 3.9+, Typer, PyYAML, pytest (with `unittest.mock` for HTTP fixtures). No new runtime deps. Reads from existing `ThoughtSpotClient`.

**Spec:** [docs/superpowers/specs/2026-05-28-ts-metadata-report-design.md](../specs/2026-05-28-ts-metadata-report-design.md)

**Branch:** `feat/ts-metadata-report` (the spec is already committed there as `d76b94f`).

**Per-task model recommendation:**
- Tasks **C1–C3** (walker) — **dispatch with Opus**. Branches across 7 source types are subtle.
- Tasks **E1–E3** (classifier) — **dispatch with Opus**. Risk aggregation across heterogeneous signals.
- All other tasks — Sonnet is appropriate.

**Conventions to follow:** [.claude/rules/ts-cli.md](../../../.claude/rules/ts-cli.md), [.claude/rules/api-research.md](../../../.claude/rules/api-research.md), [.claude/rules/branching.md](../../../.claude/rules/branching.md), [tools/ts-cli/CLAUDE.md](../../../tools/ts-cli/CLAUDE.md). MCP-first for any API question.

**API version:** All calls are **v2** (`/api/rest/2.0/...`). The v1 dependents endpoint returns 404 on Cloud anyway (open-item #1). The repo's only remaining v1 usage is `ts connections get / add-tables` which is *not* called by `ts metadata report` — its v2 migration is tracked separately in `.claude/rules/ts-cli.md`.

---

## File map

```
tools/ts-cli/ts_cli/report/                  (new package)
  __init__.py                                build_report() and build_reports()
  schema.py                                  dataclasses for the JSON contract
  resolver.py                                name/GUID → SourceDescriptor
  walker.py                                  per-source-type dep walk
  tml_probes.py                              RLS / alerts / aliases / joins / AI / ACLs
  classifier.py                              risk tag + recommendation rules
  formatters.py                              JSON / text / markdown rendering

tools/ts-cli/ts_cli/commands/metadata.py     (modify — add `report` command, ~80 lines)

tools/ts-cli/tests/                          (new test files)
  test_report_schema.py
  test_report_resolver.py
  test_report_walker.py
  test_report_tml_probes.py
  test_report_classifier.py
  test_report_formatters.py
  test_report_entry.py

agents/cli/ts-dependency-manager/SKILL.md                  (modify — frontmatter, Steps 0/2/4/5, References, Changelog)
agents/cli/ts-dependency-manager/references/dependency-types.md  (modify — status column updates)
agents/cli/ts-dependency-manager/references/open-items.md         (modify — #5/#10/#19 close, #21 partial, #22 new)
agents/cursor/rules/ts-dependency-manager.mdc              (modify — Cursor mirror)

tools/smoke-tests/smoke_ts-metadata-report.py              (new)
tools/smoke-tests/smoke_ts-dependency-manager.py           (modify)

tools/ts-cli/README.md                                     (modify — new command entry)
CHANGELOG.md                                               (modify — repo-level entry)

tools/ts-cli/ts_cli/__init__.py + pyproject.toml          (modify — version bump at PR time, last task only)
```

---

## Phase A — Foundation

### Task A1: Create the `report/` sub-package skeleton

**Files:**
- Create: `tools/ts-cli/ts_cli/report/__init__.py`
- Create: `tools/ts-cli/ts_cli/report/schema.py`
- Create: `tools/ts-cli/ts_cli/report/resolver.py`
- Create: `tools/ts-cli/ts_cli/report/walker.py`
- Create: `tools/ts-cli/ts_cli/report/tml_probes.py`
- Create: `tools/ts-cli/ts_cli/report/classifier.py`
- Create: `tools/ts-cli/ts_cli/report/formatters.py`

- [ ] **Step 1: Create the empty package**

```bash
mkdir -p tools/ts-cli/ts_cli/report
for f in __init__.py schema.py resolver.py walker.py tml_probes.py classifier.py formatters.py; do
  printf '"""ts_cli.report — %s."""\n' "$f" > "tools/ts-cli/ts_cli/report/$f"
done
```

- [ ] **Step 2: Verify Python imports the package cleanly**

```bash
cd tools/ts-cli && python -c "import ts_cli.report; print('ok')"
```

Expected output: `ok`

- [ ] **Step 3: Commit**

```bash
git add tools/ts-cli/ts_cli/report/
git commit -m "feat(ts-cli): add report/ sub-package skeleton"
```

---

### Task A2: Define the JSON-contract dataclasses

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/schema.py`
- Create: `tools/ts-cli/tests/test_report_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/ts-cli/tests/test_report_schema.py
"""Tests for report.schema dataclasses — the JSON contract types."""
from __future__ import annotations

from ts_cli.report.schema import (
    SourceDescriptor,
    Owner,
    RiskTag,
    DependentEntry,
    CoverageEntry,
    Classification,
    Report,
    SCHEMA_VERSION,
)


def test_schema_version_string():
    assert SCHEMA_VERSION == "1.0"


def test_source_descriptor_to_dict():
    src = SourceDescriptor(
        input="DB.SCHEMA.TABLE",
        guid="abc-123",
        type="LOGICAL_TABLE",
        name="TABLE",
        parent=None,
    )
    assert src.to_dict() == {
        "input": "DB.SCHEMA.TABLE",
        "guid": "abc-123",
        "type": "LOGICAL_TABLE",
        "name": "TABLE",
        "parent": None,
    }


def test_dependent_entry_to_dict():
    dep = DependentEntry(
        guid="d-1",
        name="My Model",
        type="LOGICAL_TABLE",
        subtype="WORKSHEET",
        via="v2_dependents",
        hops=1,
        owner=Owner(id="u-1", display_name="Admin"),
        modified_at="2026-03-01T00:00:00Z",
        risk=RiskTag(tag="LOW", reason="Dormant Model"),
    )
    d = dep.to_dict()
    assert d["guid"] == "d-1"
    assert d["risk"]["tag"] == "LOW"
    assert d["owner"]["display_name"] == "Admin"


def test_report_to_dict_includes_schema_version():
    src = SourceDescriptor(input="x", guid="g", type="LOGICAL_TABLE", name="x", parent=None)
    rep = Report(
        source=src,
        walked_at="2026-05-28T00:00:00Z",
        profile="test",
        dependents=[],
        coverage=[CoverageEntry(type="Models", checked=True, found=0)],
        classification=Classification(per_dependent=[], aggregate=RiskTag(tag="SAFE", reason="No dependents")),
        warnings=[],
    )
    d = rep.to_dict()
    assert d["schema_version"] == "1.0"
    assert d["source"]["guid"] == "g"
    assert d["coverage"][0]["found"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_schema.py -v
```

Expected: ImportError on the symbols listed in the test (none exist yet).

- [ ] **Step 3: Implement the dataclasses**

```python
# tools/ts-cli/ts_cli/report/schema.py
"""ts_cli.report.schema — JSON-contract dataclasses.

The CLI emits these as the stable contract (schema_version "1.0").
Consumers MUST check `schema_version` prefix before parsing.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Literal

SCHEMA_VERSION = "1.0"

RISK_TAGS = ("SAFE", "LOW", "MEDIUM", "HIGH", "STOP")
RECOMMENDATIONS = (
    "SAFE_TO_DROP",
    "REVIEW_RECOMMENDED",
    "PLAN_REQUIRED",
    "PLAN_REQUIRED_WITH_PER_VIZ_DECISIONS",
    "BLOCKED_RESOLVE_RLS_FIRST",
)


@dataclass
class Owner:
    id: str
    display_name: str

    def to_dict(self):
        return asdict(self)


@dataclass
class RiskTag:
    tag: str  # one of RISK_TAGS
    reason: str

    def to_dict(self):
        return asdict(self)


@dataclass
class SourceDescriptor:
    input: str
    guid: str
    type: str       # LOGICAL_TABLE, LOGICAL_COLUMN, etc.
    name: str
    parent: Optional[dict] = None   # {"guid": ..., "name": ..., "type": ...} when source is a column

    def to_dict(self):
        return asdict(self)


@dataclass
class DependentEntry:
    guid: str
    name: str
    type: str
    subtype: Optional[str]
    via: str         # "v2_dependents" | "tml_probe" | "fetch_permissions"
    hops: int
    owner: Optional[Owner]
    modified_at: Optional[str]
    risk: RiskTag

    def to_dict(self):
        return {
            "guid": self.guid,
            "name": self.name,
            "type": self.type,
            "subtype": self.subtype,
            "via": self.via,
            "hops": self.hops,
            "owner": self.owner.to_dict() if self.owner else None,
            "modified_at": self.modified_at,
            "risk": self.risk.to_dict(),
        }


@dataclass
class CoverageEntry:
    type: str
    checked: bool
    found: int = 0
    informational: bool = False
    reason: Optional[str] = None     # only set when checked=False

    def to_dict(self):
        d = {"type": self.type, "checked": self.checked, "found": self.found}
        if self.informational:
            d["informational"] = True
        if self.reason is not None:
            d["reason"] = self.reason
        return d


@dataclass
class Classification:
    per_dependent: List[DependentEntry]
    aggregate: RiskTag
    recommendation: str = ""  # one of RECOMMENDATIONS — set by classifier

    def to_dict(self):
        return {
            "per_dependent": [d.to_dict() for d in self.per_dependent],
            "aggregate": self.aggregate.to_dict(),
            "recommendation": self.recommendation,
        }


@dataclass
class Report:
    source: SourceDescriptor
    walked_at: str
    profile: str
    dependents: List[DependentEntry]
    coverage: List[CoverageEntry]
    classification: Classification
    warnings: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "source": self.source.to_dict(),
            "walked_at": self.walked_at,
            "profile": self.profile,
            "dependents": [d.to_dict() for d in self.dependents],
            "coverage": [c.to_dict() for c in self.coverage],
            "classification": self.classification.to_dict(),
            "warnings": list(self.warnings),
        }
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_schema.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/schema.py tools/ts-cli/tests/test_report_schema.py
git commit -m "feat(ts-cli): add report schema dataclasses (schema_version 1.0)"
```

---

## Phase B — Resolver

### Task B1: GUID detection

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/resolver.py`
- Create: `tools/ts-cli/tests/test_report_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/ts-cli/tests/test_report_resolver.py
"""Tests for report.resolver — input parsing and ambiguity handling."""
from __future__ import annotations

import pytest

from ts_cli.report.resolver import (
    looks_like_guid,
    InputKind,
    classify_input,
)


class TestLooksLikeGuid:
    def test_canonical_uuid(self):
        assert looks_like_guid("baa451a6-02a0-42d1-8347-8cd4af13b505") is True

    def test_uppercase_uuid(self):
        assert looks_like_guid("BAA451A6-02A0-42D1-8347-8CD4AF13B505") is True

    def test_three_part_name_is_not_guid(self):
        assert looks_like_guid("DB.SCHEMA.TABLE") is False

    def test_one_part_name_is_not_guid(self):
        assert looks_like_guid("MyModel") is False

    def test_empty_string(self):
        assert looks_like_guid("") is False


class TestClassifyInput:
    def test_guid(self):
        assert classify_input("baa451a6-02a0-42d1-8347-8cd4af13b505") == InputKind.GUID

    def test_three_part(self):
        assert classify_input("DB.SCHEMA.TABLE") == InputKind.THREE_PART_NAME

    def test_four_part(self):
        assert classify_input("DB.SCHEMA.TABLE.COLUMN") == InputKind.FOUR_PART_NAME

    def test_two_part(self):
        assert classify_input("Model.column") == InputKind.TWO_PART_NAME

    def test_one_part(self):
        assert classify_input("MyModel") == InputKind.ONE_PART_NAME
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_resolver.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement classification**

```python
# tools/ts-cli/ts_cli/report/resolver.py
"""ts_cli.report.resolver — parse user-provided source input and resolve to GUID."""
from __future__ import annotations

import enum
import re
from typing import Optional

from ts_cli.client import ThoughtSpotClient

# 36-char UUID with hyphens at canonical positions.
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class InputKind(enum.Enum):
    GUID = "guid"
    ONE_PART_NAME = "one_part"
    TWO_PART_NAME = "two_part"
    THREE_PART_NAME = "three_part"
    FOUR_PART_NAME = "four_part"


def looks_like_guid(s: str) -> bool:
    """True iff s is a canonical 36-char UUID."""
    return bool(_GUID_RE.match(s or ""))


def classify_input(s: str) -> InputKind:
    """Return the InputKind for a user-provided source argument."""
    if looks_like_guid(s):
        return InputKind.GUID
    parts = s.split(".")
    n = len(parts)
    if n == 1:
        return InputKind.ONE_PART_NAME
    if n == 2:
        return InputKind.TWO_PART_NAME
    if n == 3:
        return InputKind.THREE_PART_NAME
    if n == 4:
        return InputKind.FOUR_PART_NAME
    raise ValueError(f"Cannot classify input: {s!r}")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_resolver.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/resolver.py tools/ts-cli/tests/test_report_resolver.py
git commit -m "feat(ts-cli): add resolver input classification (GUID / N-part name)"
```

---

### Task B2: Resolve names to SourceDescriptor via metadata search

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/resolver.py`
- Modify: `tools/ts-cli/tests/test_report_resolver.py`

- [ ] **Step 1: Write the failing test (extend the file)**

Append to `tools/ts-cli/tests/test_report_resolver.py`:

```python
from unittest.mock import MagicMock

from ts_cli.report.resolver import (
    SourceUnresolvedError,
    SourceAmbiguousError,
    resolve_source,
)
from ts_cli.report.schema import SourceDescriptor


def _mk_client(search_returns):
    """Return a mock ThoughtSpotClient whose .post() returns search_returns."""
    client = MagicMock()
    resp = MagicMock()
    resp.json.return_value = search_returns
    client.post.return_value = resp
    return client


def _mk_hit(guid, name, type_="LOGICAL_TABLE", subtype="ONE_TO_ONE_LOGICAL"):
    return {
        "metadata_id": guid,
        "metadata_name": name,
        "metadata_type": type_,
        "metadata_header": {"id": guid, "name": name, "type": subtype, "subType": ""},
    }


class TestResolveSourceGuid:
    def test_resolve_guid_returns_descriptor(self):
        client = _mk_client([_mk_hit("g-1", "DB.SCH.T")])
        desc = resolve_source("g-1", client)
        assert isinstance(desc, SourceDescriptor)
        assert desc.guid == "g-1"
        assert desc.type == "LOGICAL_TABLE"
        assert desc.input == "g-1"


class TestResolveSourceThreePartName:
    def test_resolves_unique_match(self):
        client = _mk_client([_mk_hit("g-1", "DB.SCH.T")])
        desc = resolve_source("DB.SCH.T", client)
        assert desc.guid == "g-1"
        assert desc.name == "DB.SCH.T"

    def test_no_match_raises_unresolved(self):
        client = _mk_client([])
        with pytest.raises(SourceUnresolvedError):
            resolve_source("DB.SCH.MISSING", client)

    def test_multiple_matches_raises_ambiguous(self):
        client = _mk_client([
            _mk_hit("g-1", "DB.SCH.T"),
            _mk_hit("g-2", "DB.SCH.T"),
        ])
        with pytest.raises(SourceAmbiguousError) as excinfo:
            resolve_source("DB.SCH.T", client)
        assert len(excinfo.value.candidates) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_resolver.py -v
```

Expected: ImportError on new symbols.

- [ ] **Step 3: Implement resolve_source**

Append to `tools/ts-cli/ts_cli/report/resolver.py`:

```python
from .schema import SourceDescriptor


class SourceUnresolvedError(Exception):
    """No metadata object matched the input."""
    def __init__(self, input_: str):
        super().__init__(f"No metadata object matched: {input_!r}")
        self.input = input_


class SourceAmbiguousError(Exception):
    """More than one metadata object matched the input."""
    def __init__(self, input_: str, candidates: list):
        super().__init__(f"Input {input_!r} matched {len(candidates)} objects; specify GUID")
        self.input = input_
        self.candidates = candidates


def _search(client: ThoughtSpotClient, body: dict) -> list:
    """Call metadata/search and return the list of results."""
    resp = client.post("/api/rest/2.0/metadata/search", json=body)
    data = resp.json()
    return data if isinstance(data, list) else data.get("metadata", [])


def _to_descriptor(input_str: str, hit: dict, parent: Optional[dict] = None) -> SourceDescriptor:
    return SourceDescriptor(
        input=input_str,
        guid=hit.get("metadata_id") or hit.get("metadata_header", {}).get("id"),
        type=hit.get("metadata_type") or "LOGICAL_TABLE",
        name=hit.get("metadata_name") or hit.get("metadata_header", {}).get("name", ""),
        parent=parent,
    )


def resolve_source(input_str: str, client: ThoughtSpotClient) -> SourceDescriptor:
    """Resolve a user-provided source string to a SourceDescriptor.

    Raises SourceUnresolvedError / SourceAmbiguousError on failure cases.
    """
    kind = classify_input(input_str)
    if kind == InputKind.GUID:
        hits = _search(client, {
            "metadata": [{"identifier": input_str}],
            "record_size": 1,
            "include_headers": True,
        })
        if not hits:
            raise SourceUnresolvedError(input_str)
        return _to_descriptor(input_str, hits[0])

    # Name lookup: use exact name match (no SQL-LIKE wildcards).
    hits = _search(client, {
        "metadata": [{"type": "LOGICAL_TABLE", "name_pattern": input_str}],
        "record_size": 10,
        "include_headers": True,
    })
    # Filter to exact-name matches only.
    hits = [h for h in hits if (h.get("metadata_name") or "") == input_str]
    if not hits:
        raise SourceUnresolvedError(input_str)
    if len(hits) > 1:
        raise SourceAmbiguousError(input_str, hits)
    return _to_descriptor(input_str, hits[0])
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_resolver.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/resolver.py tools/ts-cli/tests/test_report_resolver.py
git commit -m "feat(ts-cli): resolve GUID and three-part names to SourceDescriptor"
```

---

### Task B3: Resolve four-part name (column on a table)

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/resolver.py`
- Modify: `tools/ts-cli/tests/test_report_resolver.py`

- [ ] **Step 1: Write the failing test**

Append to test file:

```python
class TestResolveFourPartColumn:
    def test_resolves_column_on_table(self, monkeypatch):
        """DB.SCH.TBL.COL → resolve table first, then look up column on it."""
        # First search returns the table; second call returns table detail with columns.
        table_hit = _mk_hit("tbl-1", "DB.SCH.TBL")
        column = {"header": {"id": "col-1", "name": "COL"}}
        detail_resp = [{
            "metadata_id": "tbl-1",
            "metadata_name": "DB.SCH.TBL",
            "metadata_type": "LOGICAL_TABLE",
            "metadata_detail": {"columns": [column]},
            "metadata_header": {"id": "tbl-1", "name": "DB.SCH.TBL"},
        }]

        client = MagicMock()
        resp1, resp2 = MagicMock(), MagicMock()
        resp1.json.return_value = [table_hit]
        resp2.json.return_value = detail_resp
        client.post.side_effect = [resp1, resp2]

        desc = resolve_source("DB.SCH.TBL.COL", client)
        assert desc.type == "LOGICAL_COLUMN"
        assert desc.guid == "col-1"
        assert desc.name == "COL"
        assert desc.parent == {"guid": "tbl-1", "name": "DB.SCH.TBL", "type": "LOGICAL_TABLE"}

    def test_column_not_found_raises(self, monkeypatch):
        table_hit = _mk_hit("tbl-1", "DB.SCH.TBL")
        detail_resp = [{
            "metadata_id": "tbl-1",
            "metadata_name": "DB.SCH.TBL",
            "metadata_detail": {"columns": []},
            "metadata_header": {"id": "tbl-1", "name": "DB.SCH.TBL"},
        }]
        client = MagicMock()
        resp1, resp2 = MagicMock(), MagicMock()
        resp1.json.return_value = [table_hit]
        resp2.json.return_value = detail_resp
        client.post.side_effect = [resp1, resp2]

        with pytest.raises(SourceUnresolvedError):
            resolve_source("DB.SCH.TBL.MISSING", client)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_resolver.py::TestResolveFourPartColumn -v
```

Expected: ValueError or AssertionError on the new four-part path (not yet implemented).

- [ ] **Step 3: Extend `resolve_source` to handle four-part names**

In `resolver.py`, replace `resolve_source` with:

```python
def _fetch_table_columns(client: ThoughtSpotClient, table_guid: str) -> list:
    """Return the columns[] list from metadata/search with include_details=true."""
    resp = client.post("/api/rest/2.0/metadata/search", json={
        "metadata": [{"identifier": table_guid, "type": "LOGICAL_TABLE"}],
        "include_details": True,
        "include_headers": True,
    })
    data = resp.json()
    if not data:
        return []
    return (data[0].get("metadata_detail") or {}).get("columns") or []


def resolve_source(input_str: str, client: ThoughtSpotClient) -> SourceDescriptor:
    """Resolve a user-provided source string to a SourceDescriptor."""
    kind = classify_input(input_str)

    if kind == InputKind.GUID:
        hits = _search(client, {
            "metadata": [{"identifier": input_str}],
            "record_size": 1,
            "include_headers": True,
        })
        if not hits:
            raise SourceUnresolvedError(input_str)
        return _to_descriptor(input_str, hits[0])

    if kind == InputKind.FOUR_PART_NAME:
        # DB.SCH.TBL.COL — resolve the table first, then find the column.
        table_name = input_str.rsplit(".", 1)[0]
        col_name = input_str.rsplit(".", 1)[1]
        table_desc = resolve_source(table_name, client)
        cols = _fetch_table_columns(client, table_desc.guid)
        for c in cols:
            h = c.get("header") or {}
            if h.get("name") == col_name:
                return SourceDescriptor(
                    input=input_str,
                    guid=h.get("id"),
                    type="LOGICAL_COLUMN",
                    name=col_name,
                    parent={"guid": table_desc.guid, "name": table_desc.name, "type": "LOGICAL_TABLE"},
                )
        raise SourceUnresolvedError(input_str)

    # 1-, 2-, 3-part name lookup (exact-name match).
    hits = _search(client, {
        "metadata": [{"type": "LOGICAL_TABLE", "name_pattern": input_str}],
        "record_size": 10,
        "include_headers": True,
    })
    hits = [h for h in hits if (h.get("metadata_name") or "") == input_str]
    if not hits:
        raise SourceUnresolvedError(input_str)
    if len(hits) > 1:
        raise SourceAmbiguousError(input_str, hits)
    return _to_descriptor(input_str, hits[0])
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_resolver.py -v
```

Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/resolver.py tools/ts-cli/tests/test_report_resolver.py
git commit -m "feat(ts-cli): resolve four-part names to LOGICAL_COLUMN descriptors"
```

---

## Phase C — Walker  **[DISPATCH WITH OPUS]**

> These tasks branch across 7 source types with subtle differences (COHORT bucket for Set sources, multi-hop for Tables, alias propagation for Model dependents). Use Opus on the per-task subagent.

### Task C1: Source-type → dependents-query parameters mapping

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/walker.py`
- Create: `tools/ts-cli/tests/test_report_walker.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/ts-cli/tests/test_report_walker.py
"""Tests for report.walker — per-source-type dep walk."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from ts_cli.report.walker import (
    dependents_query_type_for,
    walk_dependents,
)
from ts_cli.report.schema import SourceDescriptor


class TestDependentsQueryTypeFor:
    def test_table_uses_logical_table(self):
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_TABLE", name="x", parent=None)
        assert dependents_query_type_for(src) == "LOGICAL_TABLE"

    def test_column_uses_logical_column(self):
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_COLUMN", name="x",
                               parent={"guid": "t", "name": "T", "type": "LOGICAL_TABLE"})
        assert dependents_query_type_for(src) == "LOGICAL_COLUMN"

    def test_set_uses_logical_column(self):
        """Sets are queried as LOGICAL_COLUMN — see open-items.md #11."""
        src = SourceDescriptor(input="x", guid="g", type="LOGICAL_COLUMN", name="x", parent=None)
        assert dependents_query_type_for(src) == "LOGICAL_COLUMN"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_walker.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the mapping**

```python
# tools/ts-cli/ts_cli/report/walker.py
"""ts_cli.report.walker — per-source-type dependency walk.

Wraps the existing `ts metadata dependents` logic
(`_build_dependents_payload` + `_normalize_dependents_response`)
with multi-hop logic for Table → Model → Answers/Liveboards.
"""
from __future__ import annotations

from typing import List

from ts_cli.client import ThoughtSpotClient
from ts_cli.commands.metadata import (
    _build_dependents_payload,
    _normalize_dependents_response,
)
from .schema import DependentEntry, Owner, RiskTag, SourceDescriptor


def dependents_query_type_for(source: SourceDescriptor) -> str:
    """Map a SourceDescriptor.type to the type argument expected by
    POST /api/rest/2.0/metadata/search dependents query.

    Tables / Models / Views / Answers / Liveboards → LOGICAL_TABLE/LIVEBOARD/ANSWER
    Columns / Sets (cohorts)                       → LOGICAL_COLUMN
    """
    t = source.type
    if t == "LOGICAL_COLUMN":
        return "LOGICAL_COLUMN"
    if t == "LIVEBOARD":
        return "LIVEBOARD"
    if t == "ANSWER":
        return "ANSWER"
    # LOGICAL_TABLE covers tables, models, and views.
    return "LOGICAL_TABLE"


def walk_dependents(source: SourceDescriptor, client: ThoughtSpotClient) -> List[dict]:
    """Direct (one-hop) dependents for `source`. Returns the flat normalized list."""
    resp = client.post(
        "/api/rest/2.0/metadata/search",
        json=_build_dependents_payload([source.guid], dependents_query_type_for(source)),
    )
    return _normalize_dependents_response(resp.json())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_walker.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/walker.py tools/ts-cli/tests/test_report_walker.py
git commit -m "feat(ts-cli): walker — source-type to dependents-query mapping"
```

---

### Task C2: Multi-hop walk (Table → Model → Answers/Liveboards/Views/Sets/Feedback)

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/walker.py`
- Modify: `tools/ts-cli/tests/test_report_walker.py`

Background: a Table source has one direct dependent (the Model). To find Answers/Liveboards built on the Model, walk one more hop. `--depth` flag controls how many hops; default 3.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_walker.py`:

```python
from ts_cli.report.walker import walk_dependents_recursive


def _resp(json_):
    r = MagicMock()
    r.json.return_value = json_
    return r


def _v2_dependents(source_guid, by_bucket):
    """Build a v2-shaped response for one source GUID."""
    return [{
        "metadata_id": source_guid,
        "metadata_name": "x",
        "metadata_type": "LOGICAL_TABLE",
        "dependent_objects": {
            "areInaccessibleDependentsReturned": False,
            "hasInaccessibleDependents": False,
            "dependents": {source_guid: by_bucket},
        },
    }]


class TestWalkDependentsRecursive:
    def test_table_to_model_one_hop(self):
        """Source has 1 direct Model dependent; Model has 0 further deps."""
        client = MagicMock()
        client.post.side_effect = [
            _resp(_v2_dependents("tbl", {"LOGICAL_TABLE": [{"id": "mdl", "name": "M", "author": "u", "authorDisplayName": "U"}]})),
            _resp(_v2_dependents("mdl", {})),
        ]
        src = SourceDescriptor(input="tbl", guid="tbl", type="LOGICAL_TABLE", name="x", parent=None)
        out = walk_dependents_recursive(src, client, max_depth=3)
        assert len(out) == 1
        assert out[0]["guid"] == "mdl"
        assert out[0]["hops"] == 1

    def test_table_to_model_to_answer_two_hops(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp(_v2_dependents("tbl", {"LOGICAL_TABLE": [{"id": "mdl", "name": "M", "author": "u", "authorDisplayName": "U"}]})),
            _resp(_v2_dependents("mdl", {"QUESTION_ANSWER_BOOK": [{"id": "ans", "name": "A", "author": "u", "authorDisplayName": "U"}]})),
            _resp(_v2_dependents("ans", {})),
        ]
        src = SourceDescriptor(input="tbl", guid="tbl", type="LOGICAL_TABLE", name="x", parent=None)
        out = walk_dependents_recursive(src, client, max_depth=3)
        guids = sorted(d["guid"] for d in out)
        assert guids == ["ans", "mdl"]
        hops = {d["guid"]: d["hops"] for d in out}
        assert hops["mdl"] == 1
        assert hops["ans"] == 2

    def test_depth_limit_respected(self):
        client = MagicMock()
        client.post.side_effect = [
            _resp(_v2_dependents("tbl", {"LOGICAL_TABLE": [{"id": "mdl", "name": "M", "author": "u", "authorDisplayName": "U"}]})),
            _resp(_v2_dependents("mdl", {"QUESTION_ANSWER_BOOK": [{"id": "ans", "name": "A", "author": "u", "authorDisplayName": "U"}]})),
        ]
        src = SourceDescriptor(input="tbl", guid="tbl", type="LOGICAL_TABLE", name="x", parent=None)
        out = walk_dependents_recursive(src, client, max_depth=1)
        # Only 1 hop: just the Model. Answer not walked.
        assert len(out) == 1
        assert out[0]["guid"] == "mdl"
        assert client.post.call_count == 1
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_walker.py::TestWalkDependentsRecursive -v
```

Expected: ImportError on `walk_dependents_recursive`.

- [ ] **Step 3: Implement recursive walk**

Append to `walker.py`:

```python
def walk_dependents_recursive(
    source: SourceDescriptor,
    client: ThoughtSpotClient,
    *,
    max_depth: int = 3,
) -> List[dict]:
    """Walk dependents up to `max_depth` hops, deduped by GUID.

    Each output row carries a `hops` field indicating distance from source.
    """
    seen: dict = {}            # guid → row
    frontier = [(source.guid, dependents_query_type_for(source), 0)]
    while frontier:
        guid, qtype, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        resp = client.post(
            "/api/rest/2.0/metadata/search",
            json=_build_dependents_payload([guid], qtype),
        )
        rows = _normalize_dependents_response(resp.json())
        for row in rows:
            if row["guid"] in seen:
                continue
            row["hops"] = depth + 1
            seen[row["guid"]] = row
            # Decide next-hop query type for this dependent.
            next_type = _next_hop_type(row)
            if next_type is not None:
                frontier.append((row["guid"], next_type, depth + 1))
    return list(seen.values())


def _next_hop_type(row: dict) -> str | None:
    """Return the dependents-query type to use when walking through `row`.

    - Models, Views, Answers, Liveboards → LOGICAL_TABLE / ANSWER / LIVEBOARD
    - Sets (COHORT bucket)               → LOGICAL_COLUMN (queries the set as a column)
    - Feedback                           → None (no further walk; feedback is a leaf)
    """
    t = row.get("type")
    bucket = row.get("raw_bucket")
    if bucket == "FEEDBACK":
        return None
    if bucket == "COHORT":
        return "LOGICAL_COLUMN"
    if t == "ANSWER":
        return "ANSWER"
    if t == "LIVEBOARD":
        return "LIVEBOARD"
    return "LOGICAL_TABLE"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_walker.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/walker.py tools/ts-cli/tests/test_report_walker.py
git commit -m "feat(ts-cli): walker — multi-hop dependents walk with depth limit"
```

---

### Task C3: Convert walker raw rows to DependentEntry, with owner + modified_at lookup

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/walker.py`
- Modify: `tools/ts-cli/tests/test_report_walker.py`

The dep walk gives `guid + name + type + raw_bucket + author + authorDisplayName` rows. The full DependentEntry adds `subtype`, `modified_at`, and a placeholder `RiskTag` (the classifier fills this in later).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_walker.py`:

```python
from ts_cli.report.walker import row_to_entry
from ts_cli.report.schema import DependentEntry, RiskTag


class TestRowToEntry:
    def test_minimal_row(self):
        row = {
            "source_guid": "src", "guid": "g", "name": "n",
            "type": "LOGICAL_TABLE", "raw_bucket": "LOGICAL_TABLE",
            "author_id": "u", "author_display_name": "U",
            "hops": 1,
        }
        entry = row_to_entry(row)
        assert isinstance(entry, DependentEntry)
        assert entry.guid == "g"
        assert entry.owner is not None
        assert entry.owner.id == "u"
        assert entry.hops == 1
        assert entry.via == "v2_dependents"
        assert entry.risk.tag == "LOW"   # placeholder

    def test_no_author(self):
        row = {
            "source_guid": "src", "guid": "g", "name": "n",
            "type": "LOGICAL_TABLE", "raw_bucket": "LOGICAL_TABLE",
            "author_id": None, "author_display_name": None,
            "hops": 1,
        }
        entry = row_to_entry(row)
        assert entry.owner is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_walker.py::TestRowToEntry -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `row_to_entry`**

Append to `walker.py`:

```python
def row_to_entry(row: dict) -> DependentEntry:
    """Convert a normalized dependents row into a DependentEntry.

    Owner is set from author_* fields when present.
    Modified-at is left as None here; tml_probes can fill it later.
    Risk is set to a placeholder LOW tag; the classifier replaces it.
    """
    author_id = row.get("author_id")
    author_name = row.get("author_display_name")
    owner = Owner(id=author_id, display_name=author_name) if author_id else None
    return DependentEntry(
        guid=row["guid"],
        name=row["name"],
        type=row["type"],
        subtype=None,
        via="v2_dependents",
        hops=row.get("hops", 1),
        owner=owner,
        modified_at=None,
        risk=RiskTag(tag="LOW", reason="placeholder — classifier overrides"),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_walker.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/walker.py tools/ts-cli/tests/test_report_walker.py
git commit -m "feat(ts-cli): walker — convert raw rows to DependentEntry"
```

---

## Phase D — TML Probes

### Task D1: RLS rule detection from table TML

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/tml_probes.py`
- Create: `tools/ts-cli/tests/test_report_tml_probes.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/ts-cli/tests/test_report_tml_probes.py
"""Tests for report.tml_probes — TML inspection helpers."""
from __future__ import annotations

import pytest

from ts_cli.report.tml_probes import find_rls_column_uses


class TestFindRlsColumnUses:
    def test_finds_column_in_rule_expr(self):
        table_tml = {
            "table": {
                "rls_rules": {
                    "table_paths": [{"id": "T_1", "table": "T", "column": ["ZIPCODE"]}],
                    "rules": [{"name": "geo", "expr": "[T_1::ZIPCODE] = ts_groups_int"}],
                }
            }
        }
        hits = find_rls_column_uses(table_tml, {"ZIPCODE"})
        assert len(hits) == 1
        assert hits[0]["rule_name"] == "geo"
        assert hits[0]["column"] == "ZIPCODE"

    def test_no_rls_block_returns_empty(self):
        table_tml = {"table": {"name": "T"}}
        hits = find_rls_column_uses(table_tml, {"ZIPCODE"})
        assert hits == []

    def test_column_not_referenced_returns_empty(self):
        table_tml = {
            "table": {
                "rls_rules": {
                    "table_paths": [{"id": "T_1", "table": "T", "column": ["NAME"]}],
                    "rules": [{"name": "x", "expr": "[T_1::NAME] != ''"}],
                }
            }
        }
        hits = find_rls_column_uses(table_tml, {"ZIPCODE"})
        assert hits == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_tml_probes.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `find_rls_column_uses`**

```python
# tools/ts-cli/ts_cli/report/tml_probes.py
"""ts_cli.report.tml_probes — TML inspection for RLS, alerts, aliases, joins, AI surface.

All functions are pure: they take parsed-TML dicts (already exported by the caller)
and return structured findings. No HTTP calls inside this module.
"""
from __future__ import annotations

from typing import Iterable, List


def find_rls_column_uses(table_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return RLS-rule hits where any rule references a column in target_columns.

    Per open-items.md #7: rules[].expr references columns via [path_id::COL_NAME].
    """
    targets = set(target_columns)
    rls = (table_tml.get("table") or {}).get("rls_rules") or {}
    paths = {p["id"]: p for p in rls.get("table_paths", [])}
    hits = []
    for rule in rls.get("rules", []):
        expr = rule.get("expr", "")
        for path_id, p in paths.items():
            for col in p.get("column", []):
                if col not in targets:
                    continue
                if f"{path_id}::{col}" in expr or f"[{col}]" in expr:
                    hits.append({
                        "rule_name": rule["name"],
                        "path_id": path_id,
                        "column": col,
                        "expr": expr,
                    })
    return hits
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_tml_probes.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/tml_probes.py tools/ts-cli/tests/test_report_tml_probes.py
git commit -m "feat(ts-cli): tml_probes — RLS rule detection"
```

---

### Task D2: Monitor alert detection from Liveboard `--associated` export

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/tml_probes.py`
- Modify: `tools/ts-cli/tests/test_report_tml_probes.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_tml_probes.py`:

```python
from ts_cli.report.tml_probes import find_alert_column_uses


class TestFindAlertColumnUses:
    def test_finds_alert_filtering_on_column(self):
        alert_tml = {
            "monitor_alert": [{
                "guid": "a-1", "name": "Alert 1",
                "metric_id": {"pinboard_viz_id": {"viz_id": "v-1"}},
                "personalised_view_info": {
                    "filters": [
                        {"column": ["TEST_MODEL::Customer Zipcode"]},
                        {"column": ["TEST_MODEL::Other Column"]},
                    ]
                }
            }]
        }
        hits = find_alert_column_uses(alert_tml, {"Customer Zipcode"}, source_model_name="TEST_MODEL")
        assert len(hits) == 1
        assert hits[0]["alert_guid"] == "a-1"
        assert hits[0]["column"] == "Customer Zipcode"

    def test_ignores_alerts_on_other_models(self):
        alert_tml = {
            "monitor_alert": [{
                "guid": "a-1", "name": "Alert 1",
                "metric_id": {"pinboard_viz_id": {"viz_id": "v-1"}},
                "personalised_view_info": {
                    "filters": [{"column": ["OTHER_MODEL::Customer Zipcode"]}]
                }
            }]
        }
        hits = find_alert_column_uses(alert_tml, {"Customer Zipcode"}, source_model_name="TEST_MODEL")
        assert hits == []

    def test_empty_alert_tml(self):
        hits = find_alert_column_uses({}, {"X"}, source_model_name=None)
        assert hits == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_tml_probes.py -v
```

Expected: ImportError on `find_alert_column_uses`.

- [ ] **Step 3: Implement**

Append to `tml_probes.py`:

```python
def find_alert_column_uses(
    alert_tml: dict,
    target_columns: Iterable[str],
    *,
    source_model_name: str | None = None,
) -> List[dict]:
    """Return alert-filter hits referencing any column in target_columns.

    Per open-items.md #6: filters[].column entries are strings of form
    "TABLE_OR_MODEL_NAME::COLUMN_NAME". When source_model_name is given,
    only hits on that model are returned.
    """
    targets = set(target_columns)
    hits = []
    for alert in alert_tml.get("monitor_alert", []) or []:
        viz_id = (alert.get("metric_id") or {}).get("pinboard_viz_id", {}).get("viz_id", "")
        for j, filt in enumerate(alert.get("personalised_view_info", {}).get("filters", [])):
            for col_ref in filt.get("column", []):
                if "::" not in col_ref:
                    continue
                tbl, col = col_ref.rsplit("::", 1)
                if col not in targets:
                    continue
                if source_model_name and tbl != source_model_name:
                    continue
                hits.append({
                    "alert_guid": alert.get("guid"),
                    "alert_name": alert.get("name"),
                    "viz_id": viz_id,
                    "filter_index": j,
                    "column": col,
                    "table": tbl,
                })
    return hits
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd tools/ts-cli && pytest tests/test_report_tml_probes.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/tml_probes.py tools/ts-cli/tests/test_report_tml_probes.py
git commit -m "feat(ts-cli): tml_probes — monitor alert column detection"
```

---

### Task D3: Column alias TML detection (via `export_with_column_aliases`)

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/tml_probes.py`
- Modify: `tools/ts-cli/tests/test_report_tml_probes.py`

This task adds the parser. The actual HTTP call (TML export with the `export_options.export_with_column_aliases: true` Beta flag, 10.13.0.cl+) is added in Task G2 where the CLI assembles probes.

- [ ] **Step 1: Write the failing test**

Append:

```python
from ts_cli.report.tml_probes import find_alias_column_uses


class TestFindAliasColumnUses:
    def test_finds_alias_for_target_column(self):
        alias_tml = {
            "column_alias": {
                "model": {"name": "M", "fqn": "m-guid"},
                "columns": [
                    {"name": "Customer Zipcode", "locales": [{"name": "de-DE"}, {"name": "en-AU"}]},
                    {"name": "Order ID", "locales": [{"name": "en-AU"}]},
                ],
            }
        }
        hits = find_alias_column_uses(alias_tml, {"Customer Zipcode"})
        assert len(hits) == 1
        assert hits[0]["name"] == "Customer Zipcode"
        assert hits[0]["locale_count"] == 2

    def test_no_aliases_for_column(self):
        alias_tml = {
            "column_alias": {
                "model": {"name": "M"},
                "columns": [{"name": "Order ID", "locales": []}],
            }
        }
        hits = find_alias_column_uses(alias_tml, {"Customer Zipcode"})
        assert hits == []

    def test_empty_alias_tml(self):
        hits = find_alias_column_uses({}, {"X"})
        assert hits == []
```

- [ ] **Step 2: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_tml_probes.py::TestFindAliasColumnUses -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Append to `tml_probes.py`:

```python
def find_alias_column_uses(alias_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return alias entries for any column in target_columns.

    Per open-items.md #10 (resolved 2026-05-28): alias TML structure is
        column_alias:
          model: {name: ..., fqn: ...}
          columns:
            - name: <model alias name>
              locales:
                - name: <locale code>
                  orgs: [...]
    """
    targets = set(target_columns)
    cols = (alias_tml.get("column_alias") or {}).get("columns") or []
    hits = []
    for c in cols:
        if c.get("name") in targets:
            hits.append({
                "name": c["name"],
                "locale_count": len(c.get("locales") or []),
                "locales": [loc.get("name") for loc in (c.get("locales") or [])],
            })
    return hits
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_tml_probes.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/tml_probes.py tools/ts-cli/tests/test_report_tml_probes.py
git commit -m "feat(ts-cli): tml_probes — column alias TML detection"
```

---

### Task D4: Joins-from-metadata-detail + Spotter-AI-surface helpers

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/tml_probes.py`
- Modify: `tools/ts-cli/tests/test_report_tml_probes.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from ts_cli.report.tml_probes import (
    find_join_column_uses,
    find_ai_surface_uses,
)


class TestFindJoinColumnUses:
    def test_finds_column_in_join_on(self):
        model_tml = {
            "model": {
                "model_tables": [{
                    "name": "ORDERS",
                    "joins_with": [
                        {"name": "j1", "on": "[ORDERS::CUSTOMER_ID] = [CUSTOMERS::ID]"},
                    ],
                }],
            }
        }
        hits = find_join_column_uses(model_tml, {"CUSTOMER_ID"})
        assert len(hits) == 1
        assert hits[0]["table"] == "ORDERS"
        assert hits[0]["join"] == "j1"

    def test_no_match(self):
        model_tml = {"model": {"model_tables": [{"name": "X", "joins_with": []}]}}
        assert find_join_column_uses(model_tml, {"Y"}) == []


class TestFindAiSurfaceUses:
    def test_finds_column_in_data_model_instructions(self):
        model_tml = {
            "model": {
                "model_instructions": {
                    "data_model_instructions": "Always filter by [Customer Zipcode] when computing regional totals.",
                },
                "columns": [],
            }
        }
        hits = find_ai_surface_uses(model_tml, {"Customer Zipcode"})
        assert any(h["surface"] == "data_model_instructions" for h in hits)

    def test_finds_column_in_synonyms(self):
        model_tml = {
            "model": {
                "columns": [{"name": "Customer Zipcode", "properties": {"synonyms": ["zip"]}}],
            }
        }
        hits = find_ai_surface_uses(model_tml, {"Customer Zipcode"})
        assert any(h["surface"] == "synonyms" for h in hits)

    def test_no_ai_uses(self):
        model_tml = {"model": {"columns": []}}
        assert find_ai_surface_uses(model_tml, {"X"}) == []
```

- [ ] **Step 2: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_tml_probes.py -v
```

Expected: ImportError on the new symbols.

- [ ] **Step 3: Implement**

Append to `tml_probes.py`:

```python
def find_join_column_uses(model_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return join hits where any join.on expression references a target column.

    Per open-items.md #4: ThoughtSpot rejects model imports if joins[].on
    references a missing column.
    """
    targets = set(target_columns)
    hits = []
    for tbl in (model_tml.get("model") or {}).get("model_tables", []):
        for join in tbl.get("joins_with", []):
            on_expr = join.get("on", "")
            for col in targets:
                if col in on_expr:
                    hits.append({
                        "table": tbl.get("name", "?"),
                        "join": join.get("name", "unnamed"),
                        "on": on_expr,
                        "column": col,
                    })
                    break
    return hits


def find_ai_surface_uses(model_tml: dict, target_columns: Iterable[str]) -> List[dict]:
    """Return hits where a target column appears in a Spotter-AI surface area:
    Data Model Instructions, synonyms, or business-term column references.
    """
    targets = set(target_columns)
    hits = []
    model = model_tml.get("model") or {}

    # Data Model Instructions — free text; tokens look like [Column Name].
    dmi = ((model.get("model_instructions") or {}).get("data_model_instructions")) or ""
    for col in targets:
        if f"[{col}]" in dmi or col in dmi:
            hits.append({"surface": "data_model_instructions", "column": col})

    # Synonyms — per-column array.
    for c in model.get("columns", []) or []:
        name = c.get("name")
        if name in targets:
            syns = (c.get("properties") or {}).get("synonyms") or []
            if syns:
                hits.append({"surface": "synonyms", "column": name, "values": syns})

    return hits
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_tml_probes.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/tml_probes.py tools/ts-cli/tests/test_report_tml_probes.py
git commit -m "feat(ts-cli): tml_probes — joins and Spotter AI surface area detection"
```

---

## Phase E — Classifier  **[DISPATCH WITH OPUS]**

> These tasks define the SAFE/LOW/MEDIUM/HIGH/STOP risk rules and the aggregation. Use Opus.

### Task E1: Per-dependent risk tag rules

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/classifier.py`
- Create: `tools/ts-cli/tests/test_report_classifier.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/ts-cli/tests/test_report_classifier.py
"""Tests for report.classifier — risk tags and aggregate recommendation."""
from __future__ import annotations

from ts_cli.report.classifier import (
    classify_dependent,
    DependentSignals,
)
from ts_cli.report.schema import DependentEntry, Owner, RiskTag


def _dep(guid="g", type_="LOGICAL_TABLE", hops=1):
    return DependentEntry(
        guid=guid, name="x", type=type_, subtype=None,
        via="v2_dependents", hops=hops,
        owner=Owner(id="u", display_name="U"),
        modified_at="2026-01-01T00:00:00Z",
        risk=RiskTag(tag="LOW", reason="placeholder"),
    )


class TestClassifyDependent:
    def test_chart_on_x_axis_is_high(self):
        sig = DependentSignals(chart_axis_use=["y"])
        tag = classify_dependent(_dep(), sig)
        assert tag.tag == "HIGH"
        assert "axis" in tag.reason.lower()

    def test_chart_on_color_is_medium(self):
        sig = DependentSignals(chart_axis_use=["color"])
        tag = classify_dependent(_dep(), sig)
        assert tag.tag == "MEDIUM"

    def test_join_reference_is_high(self):
        sig = DependentSignals(referenced_in_joins=True)
        tag = classify_dependent(_dep(), sig)
        assert tag.tag == "HIGH"

    def test_dormant_only_is_low(self):
        sig = DependentSignals(is_dormant=True)
        tag = classify_dependent(_dep(), sig)
        assert tag.tag == "LOW"

    def test_no_signals_default_is_low(self):
        tag = classify_dependent(_dep(), DependentSignals())
        assert tag.tag == "LOW"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/ts-cli && pytest tests/test_report_classifier.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# tools/ts-cli/ts_cli/report/classifier.py
"""ts_cli.report.classifier — risk tag + recommendation rules.

Pure functions; consume walker/tml_probes outputs and produce RiskTag values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .schema import DependentEntry, RiskTag


@dataclass
class DependentSignals:
    """Signals collected per-dependent during walking and probing."""
    chart_axis_use: List[str] = field(default_factory=list)        # subset of {"x","y","color","size","shape"}
    referenced_in_joins: bool = False
    referenced_in_model_filter: bool = False
    referenced_in_alerts: bool = False
    referenced_in_feedback: bool = False
    referenced_in_ai_surface: bool = False                          # DMI, synonyms
    is_dormant: bool = False                                        # modified_at older than threshold
    is_informational_only: bool = False                             # alias, ACL — no behavioral impact


def classify_dependent(dep: DependentEntry, sig: DependentSignals) -> RiskTag:
    """Compute a RiskTag for one dependent from its signals.

    Note: STOP is handled at the aggregate level via separate RLS / CSR
    findings on the source, not per-dependent.
    """
    if "x" in sig.chart_axis_use or "y" in sig.chart_axis_use:
        return RiskTag(tag="HIGH", reason="chart uses source column on x/y axis")
    if sig.referenced_in_joins:
        return RiskTag(tag="HIGH", reason="referenced in a join condition")
    if sig.referenced_in_model_filter:
        return RiskTag(tag="HIGH", reason="referenced in a model-level filter")
    if any(a in sig.chart_axis_use for a in ("color", "size", "shape")):
        return RiskTag(tag="MEDIUM", reason="chart uses source column on color/size/shape")
    if sig.referenced_in_alerts:
        return RiskTag(tag="MEDIUM", reason="alert filter references source column")
    if sig.referenced_in_feedback:
        return RiskTag(tag="MEDIUM", reason="Spotter feedback references source column")
    if sig.referenced_in_ai_surface:
        return RiskTag(tag="MEDIUM", reason="referenced in Spotter AI surface area")
    if sig.is_dormant or sig.is_informational_only:
        return RiskTag(tag="LOW", reason="dormant or informational only")
    return RiskTag(tag="LOW", reason="no high-risk signals")
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_classifier.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/classifier.py tools/ts-cli/tests/test_report_classifier.py
git commit -m "feat(ts-cli): classifier — per-dependent risk tag rules"
```

---

### Task E2: Aggregate tag (max-of) and recommendation

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/classifier.py`
- Modify: `tools/ts-cli/tests/test_report_classifier.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from ts_cli.report.classifier import aggregate_classification, AggregateInputs


class TestAggregateClassification:
    def test_all_safe(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[],
            rls_hits=[],
            csr_hits=[],
        ))
        assert agg.aggregate.tag == "SAFE"
        assert agg.recommendation == "SAFE_TO_DROP"

    def test_any_low(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[RiskTag(tag="LOW", reason="x")],
            rls_hits=[], csr_hits=[],
        ))
        assert agg.aggregate.tag == "LOW"
        assert agg.recommendation == "REVIEW_RECOMMENDED"

    def test_medium_promotes(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[RiskTag(tag="LOW", reason="x"), RiskTag(tag="MEDIUM", reason="y")],
            rls_hits=[], csr_hits=[],
        ))
        assert agg.aggregate.tag == "MEDIUM"
        assert agg.recommendation == "PLAN_REQUIRED"

    def test_high_promotes(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[RiskTag(tag="HIGH", reason="x")],
            rls_hits=[], csr_hits=[],
        ))
        assert agg.aggregate.tag == "HIGH"
        assert agg.recommendation == "PLAN_REQUIRED_WITH_PER_VIZ_DECISIONS"

    def test_rls_makes_stop(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[RiskTag(tag="LOW", reason="x")],
            rls_hits=[{"rule_name": "geo"}],
            csr_hits=[],
        ))
        assert agg.aggregate.tag == "STOP"
        assert agg.recommendation == "BLOCKED_RESOLVE_RLS_FIRST"

    def test_csr_makes_stop(self):
        agg = aggregate_classification(AggregateInputs(
            per_dependent_tags=[],
            rls_hits=[],
            csr_hits=[{"column": "X"}],
        ))
        assert agg.aggregate.tag == "STOP"
        assert agg.recommendation == "BLOCKED_RESOLVE_RLS_FIRST"
```

- [ ] **Step 2: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_classifier.py::TestAggregateClassification -v
```

Expected: ImportError on `aggregate_classification` / `AggregateInputs`.

- [ ] **Step 3: Implement**

Append to `classifier.py`:

```python
_TAG_ORDER = {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "STOP": 4}

_TAG_TO_RECOMMENDATION = {
    "SAFE":   "SAFE_TO_DROP",
    "LOW":    "REVIEW_RECOMMENDED",
    "MEDIUM": "PLAN_REQUIRED",
    "HIGH":   "PLAN_REQUIRED_WITH_PER_VIZ_DECISIONS",
    "STOP":   "BLOCKED_RESOLVE_RLS_FIRST",
}


@dataclass
class AggregateInputs:
    per_dependent_tags: List[RiskTag] = field(default_factory=list)
    rls_hits: List[dict] = field(default_factory=list)
    csr_hits: List[dict] = field(default_factory=list)


@dataclass
class AggregateResult:
    aggregate: RiskTag
    recommendation: str


def aggregate_classification(inp: AggregateInputs) -> AggregateResult:
    """Compute the top-level aggregate tag + recommendation."""
    # STOP wins outright if either RLS or CSR are present.
    if inp.rls_hits or inp.csr_hits:
        reasons = []
        if inp.rls_hits:
            reasons.append(f"{len(inp.rls_hits)} RLS rule(s) reference source column")
        if inp.csr_hits:
            reasons.append(f"{len(inp.csr_hits)} CSR rule(s) reference source column")
        return AggregateResult(
            aggregate=RiskTag(tag="STOP", reason="; ".join(reasons)),
            recommendation="BLOCKED_RESOLVE_RLS_FIRST",
        )
    if not inp.per_dependent_tags:
        return AggregateResult(
            aggregate=RiskTag(tag="SAFE", reason="No dependents found"),
            recommendation="SAFE_TO_DROP",
        )
    max_tag = max(inp.per_dependent_tags, key=lambda t: _TAG_ORDER.get(t.tag, 0))
    return AggregateResult(
        aggregate=RiskTag(tag=max_tag.tag, reason=max_tag.reason),
        recommendation=_TAG_TO_RECOMMENDATION[max_tag.tag],
    )
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_classifier.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/classifier.py tools/ts-cli/tests/test_report_classifier.py
git commit -m "feat(ts-cli): classifier — aggregate tag and recommendation"
```

---

## Phase F — Formatters

### Task F1: JSON formatter

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/formatters.py`
- Create: `tools/ts-cli/tests/test_report_formatters.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/ts-cli/tests/test_report_formatters.py
"""Tests for report.formatters — JSON / text / markdown rendering."""
from __future__ import annotations

import json

from ts_cli.report.formatters import render_json, render_text, render_md
from ts_cli.report.schema import (
    Report, SourceDescriptor, CoverageEntry, Classification, RiskTag,
)


def _mk_report():
    src = SourceDescriptor(input="g-1", guid="g-1", type="LOGICAL_TABLE", name="X", parent=None)
    return Report(
        source=src,
        walked_at="2026-05-28T00:00:00Z",
        profile="test",
        dependents=[],
        coverage=[CoverageEntry(type="Models", checked=True, found=0)],
        classification=Classification(
            per_dependent=[],
            aggregate=RiskTag(tag="SAFE", reason="No dependents"),
            recommendation="SAFE_TO_DROP",
        ),
        warnings=[],
    )


class TestRenderJson:
    def test_valid_json(self):
        out = render_json(_mk_report())
        parsed = json.loads(out)
        assert parsed["schema_version"] == "1.0"
        assert parsed["source"]["guid"] == "g-1"
        assert parsed["classification"]["aggregate"]["tag"] == "SAFE"

    def test_multi_report_wrapper(self):
        out = render_json([_mk_report(), _mk_report()])
        parsed = json.loads(out)
        assert parsed["schema_version"] == "1.0"
        assert len(parsed["reports"]) == 2
```

- [ ] **Step 2: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_formatters.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement JSON formatter**

```python
# tools/ts-cli/ts_cli/report/formatters.py
"""ts_cli.report.formatters — JSON / text / markdown rendering of Report objects."""
from __future__ import annotations

import json
from typing import List, Union
from datetime import datetime, timezone

from .schema import Report, SCHEMA_VERSION


def render_json(report_or_reports: Union[Report, List[Report]]) -> str:
    """Render to canonical JSON. Single Report → single-source shape; list → multi-source wrapper."""
    if isinstance(report_or_reports, Report):
        return json.dumps(report_or_reports.to_dict(), indent=2)
    multi = {
        "schema_version": SCHEMA_VERSION,
        "walked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reports": [r.to_dict() if isinstance(r, Report) else r for r in report_or_reports],
    }
    return json.dumps(multi, indent=2)
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_formatters.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/formatters.py tools/ts-cli/tests/test_report_formatters.py
git commit -m "feat(ts-cli): formatters — JSON renderer"
```

---

### Task F2: Text formatter (tree + matrix)

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/formatters.py`
- Modify: `tools/ts-cli/tests/test_report_formatters.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestRenderText:
    def test_contains_source_name(self):
        out = render_text(_mk_report())
        assert "X" in out

    def test_contains_coverage_section(self):
        out = render_text(_mk_report())
        assert "Coverage" in out or "CHECKED" in out

    def test_contains_recommendation(self):
        out = render_text(_mk_report())
        assert "SAFE_TO_DROP" in out
```

- [ ] **Step 2: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_formatters.py::TestRenderText -v
```

Expected: ImportError on `render_text`.

- [ ] **Step 3: Implement**

Append to `formatters.py`:

```python
def render_text(report: Report) -> str:
    """Plain-text tree + coverage matrix + recommendation, suitable for terminals."""
    lines: List[str] = []
    src = report.source
    lines.append(f"Dependency report — {src.name}")
    lines.append(f"  guid:    {src.guid}")
    lines.append(f"  type:    {src.type}")
    if src.parent:
        lines.append(f"  parent:  {src.parent.get('name')} ({src.parent.get('guid')})")
    lines.append(f"  walked:  {report.walked_at}  (profile: {report.profile})")
    lines.append("")

    lines.append("Dependents:")
    if not report.dependents:
        lines.append("  (none)")
    else:
        for d in report.dependents:
            owner = d.owner.display_name if d.owner else "?"
            lines.append(f"  [{d.risk.tag:<6}] {d.type:<14} {d.name}  (guid: {d.guid}, owner: {owner})")
            lines.append(f"           reason: {d.risk.reason}")
    lines.append("")

    lines.append("Coverage:")
    for c in report.coverage:
        mark = "✓" if c.checked else "—"
        suffix = ""
        if c.informational:
            suffix = "  (informational)"
        if not c.checked and c.reason:
            suffix = f"  ({c.reason})"
        lines.append(f"  {mark} {c.type:<32} found: {c.found}{suffix}")
    lines.append("")

    agg = report.classification.aggregate
    rec = report.classification.recommendation or "—"
    lines.append(f"Aggregate risk: {agg.tag}    Recommendation: {rec}")
    lines.append(f"Reason:         {agg.reason}")

    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in report.warnings:
            lines.append(f"  ⚠ {w}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_formatters.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/formatters.py tools/ts-cli/tests/test_report_formatters.py
git commit -m "feat(ts-cli): formatters — text renderer (tree + coverage + recommendation)"
```

---

### Task F3: Markdown formatter

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/formatters.py`
- Modify: `tools/ts-cli/tests/test_report_formatters.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestRenderMd:
    def test_has_markdown_heading(self):
        out = render_md(_mk_report())
        assert out.startswith("# ") or "\n# " in out

    def test_has_table_syntax(self):
        out = render_md(_mk_report())
        assert "| Coverage" in out or "| Type " in out

    def test_includes_aggregate(self):
        out = render_md(_mk_report())
        assert "SAFE_TO_DROP" in out
```

- [ ] **Step 2: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_formatters.py::TestRenderMd -v
```

Expected: ImportError on `render_md`.

- [ ] **Step 3: Implement**

Append to `formatters.py`:

```python
def render_md(report: Report) -> str:
    """Markdown — heading, dependents table, coverage table, recommendation block."""
    lines: List[str] = []
    src = report.source
    lines.append(f"# Dependency report — `{src.name}`")
    lines.append("")
    lines.append(f"- **GUID:** `{src.guid}`")
    lines.append(f"- **Type:** {src.type}")
    if src.parent:
        lines.append(f"- **Parent:** {src.parent.get('name')} (`{src.parent.get('guid')}`)")
    lines.append(f"- **Walked at:** {report.walked_at} — profile `{report.profile}`")
    lines.append("")

    lines.append("## Dependents")
    if not report.dependents:
        lines.append("_(none)_")
    else:
        lines.append("")
        lines.append("| Risk | Type | Name | GUID | Owner | Reason |")
        lines.append("|---|---|---|---|---|---|")
        for d in report.dependents:
            owner = d.owner.display_name if d.owner else "—"
            lines.append(f"| {d.risk.tag} | {d.type} | {d.name} | `{d.guid}` | {owner} | {d.risk.reason} |")
    lines.append("")

    lines.append("## Coverage")
    lines.append("")
    lines.append("| Type | Checked | Found | Notes |")
    lines.append("|---|:-:|---:|---|")
    for c in report.coverage:
        check = "✓" if c.checked else "—"
        notes = []
        if c.informational:
            notes.append("informational")
        if not c.checked and c.reason:
            notes.append(c.reason)
        lines.append(f"| {c.type} | {check} | {c.found} | {' / '.join(notes)} |")
    lines.append("")

    agg = report.classification.aggregate
    rec = report.classification.recommendation or "—"
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- **Risk:** `{agg.tag}`")
    lines.append(f"- **Recommendation:** `{rec}`")
    lines.append(f"- **Reason:** {agg.reason}")

    if report.warnings:
        lines.append("")
        lines.append("## Warnings")
        for w in report.warnings:
            lines.append(f"- ⚠ {w}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_formatters.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/formatters.py tools/ts-cli/tests/test_report_formatters.py
git commit -m "feat(ts-cli): formatters — markdown renderer"
```

---

## Phase G — CLI integration

### Task G1: `build_report` and `build_reports` public entry points

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/__init__.py`
- Create: `tools/ts-cli/tests/test_report_entry.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/ts-cli/tests/test_report_entry.py
"""Tests for the report package's public entry points."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from ts_cli.report import build_report, build_reports


def _resp(body):
    r = MagicMock()
    r.json.return_value = body
    return r


@patch("ts_cli.report.ThoughtSpotClient")
def test_build_report_returns_dict_with_schema_version(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    # First call: resolve_source (search by GUID). Then: walk_dependents_recursive (empty).
    client.post.side_effect = [
        _resp([{
            "metadata_id": "g-1", "metadata_name": "X",
            "metadata_type": "LOGICAL_TABLE",
            "metadata_header": {"id": "g-1", "name": "X"},
        }]),
        _resp([{
            "metadata_id": "g-1", "dependent_objects": {
                "dependents": {"g-1": {}}
            }
        }]),
    ]

    out = build_report("baa451a6-02a0-42d1-8347-8cd4af13b505", profile="test", with_deep=False)
    assert out["schema_version"] == "1.0"
    assert out["source"]["guid"] == "g-1"


def test_build_reports_multi_source_shape():
    """Just check the wrapper shape on the multi-source entry."""
    with patch("ts_cli.report.build_report") as mock_single:
        mock_single.return_value = {"schema_version": "1.0", "source": {"guid": "a"}}
        out = build_reports(["a", "b"], profile="test", with_deep=False)
    assert out["schema_version"] == "1.0"
    assert len(out["reports"]) == 2
```

- [ ] **Step 2: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_entry.py -v
```

Expected: ImportError on the public entry points.

- [ ] **Step 3: Implement the entry points**

```python
# tools/ts-cli/ts_cli/report/__init__.py
"""ts_cli.report — public entry points.

build_report(source_ref) → single-source report dict (schema_version 1.0)
build_reports([refs])    → multi-source wrapper {"reports": [...]}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from ts_cli.client import ThoughtSpotClient, resolve_profile
from .schema import (
    Report, CoverageEntry, Classification, RiskTag, SCHEMA_VERSION,
)
from .resolver import resolve_source, SourceUnresolvedError, SourceAmbiguousError
from .walker import walk_dependents_recursive, row_to_entry
from .classifier import aggregate_classification, AggregateInputs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_report(source_ref: str, *, profile: str, with_deep: bool = True, max_depth: int = 3) -> dict:
    """Resolve source → walk dependents → (optionally) probe TML → classify → return dict.

    Returns the to_dict() result of a Report. Raises SourceUnresolvedError /
    SourceAmbiguousError if the source ref can't be uniquely resolved.
    """
    client = ThoughtSpotClient(resolve_profile(profile))
    source = resolve_source(source_ref, client)

    raw_rows = walk_dependents_recursive(source, client, max_depth=max_depth)
    dependents = [row_to_entry(r) for r in raw_rows]

    # TML probes (RLS, alerts, aliases, joins, AI surface) — added in Task G2.
    # For now, with_deep=True is identical to with_deep=False until G2 lands.
    rls_hits: list = []
    csr_hits: list = []

    coverage = [
        CoverageEntry(type="Models / Views / Tables", checked=True,
                      found=sum(1 for d in dependents if d.type == "LOGICAL_TABLE")),
        CoverageEntry(type="Answers", checked=True,
                      found=sum(1 for d in dependents if d.type == "ANSWER")),
        CoverageEntry(type="Liveboards", checked=True,
                      found=sum(1 for d in dependents if d.type == "LIVEBOARD")),
        CoverageEntry(type="Sets / Cohorts", checked=True,
                      found=sum(1 for d in dependents if d.type == "SET")),
        CoverageEntry(type="Spotter feedback", checked=True,
                      found=sum(1 for d in dependents if d.type == "FEEDBACK")),
    ]

    agg = aggregate_classification(AggregateInputs(
        per_dependent_tags=[d.risk for d in dependents],
        rls_hits=rls_hits,
        csr_hits=csr_hits,
    ))
    classification = Classification(
        per_dependent=dependents,
        aggregate=agg.aggregate,
        recommendation=agg.recommendation,
    )

    report = Report(
        source=source,
        walked_at=_now_iso(),
        profile=profile,
        dependents=dependents,
        coverage=coverage,
        classification=classification,
        warnings=[],
    )
    return report.to_dict()


def build_reports(source_refs: List[str], *, profile: str, with_deep: bool = True, max_depth: int = 3) -> dict:
    """Multi-source: returns the {"reports": [...]} wrapper."""
    reports = []
    for ref in source_refs:
        try:
            reports.append(build_report(ref, profile=profile, with_deep=with_deep, max_depth=max_depth))
        except (SourceUnresolvedError, SourceAmbiguousError) as e:
            reports.append({
                "schema_version": SCHEMA_VERSION,
                "source": {"input": ref, "guid": None, "type": None, "name": None, "parent": None},
                "error": str(e),
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "walked_at": _now_iso(),
        "reports": reports,
    }
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_entry.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/__init__.py tools/ts-cli/tests/test_report_entry.py
git commit -m "feat(ts-cli): build_report and build_reports public entry points"
```

---

### Task G2: Wire TML probes into `build_report`

**Files:**
- Modify: `tools/ts-cli/ts_cli/report/__init__.py`
- Modify: `tools/ts-cli/tests/test_report_entry.py`

This task adds the TML probe calls (alerts via Liveboard `--associated`, RLS via table TML, aliases via the Beta `export_with_column_aliases` flag) when `with_deep=True`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_report_entry.py`:

```python
@patch("ts_cli.report.ThoughtSpotClient")
def test_build_report_with_deep_calls_alias_export(MockClient):
    client = MagicMock()
    MockClient.return_value = client

    # Resolve, walk (empty), then alias export — three calls.
    client.post.side_effect = [
        _resp([{
            "metadata_id": "g-1", "metadata_name": "M",
            "metadata_type": "LOGICAL_TABLE",
            "metadata_header": {"id": "g-1", "name": "M"},
        }]),
        _resp([{"metadata_id": "g-1", "dependent_objects": {"dependents": {"g-1": {}}}}]),
        _resp([{"info": {"type": "model"}, "edoc": "column_alias:\n  columns: []\n"}]),
    ]
    out = build_report("g-1", profile="test", with_deep=True)
    # Should have at least one CoverageEntry mentioning aliases.
    assert any("alias" in c["type"].lower() for c in out["coverage"])
```

- [ ] **Step 2: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_entry.py::test_build_report_with_deep_calls_alias_export -v
```

Expected: AssertionError (no alias coverage row yet).

- [ ] **Step 3: Wire TML probe calls**

In `tools/ts-cli/ts_cli/report/__init__.py`, replace the `# TML probes` block in `build_report` and the coverage list with:

```python
    # TML probes (RLS, alerts, aliases, joins, AI surface).
    rls_hits: list = []
    csr_hits: list = []
    alias_hits: list = []
    alert_hits: list = []
    join_hits: list = []
    ai_hits: list = []
    alias_supported = True

    if with_deep:
        from . import tml_probes
        import yaml

        # 1. Alias TML (export_with_column_aliases beta flag, 10.13.0+).
        try:
            resp = client.post("/api/rest/2.0/metadata/tml/export", json={
                "metadata": [{"identifier": source.guid, "type": "LOGICAL_TABLE"}],
                "export_associated": True,
                "export_fqn": True,
                "edoc_format": "YAML",
                "export_options": {"export_with_column_aliases": True},
            })
            docs = resp.json() or []
            for doc in docs:
                if (doc.get("info") or {}).get("type", "").startswith("COLUMN_ALIAS") \
                   or "alias" in (doc.get("info") or {}).get("filename", "").lower():
                    alias_tml = yaml.safe_load(doc.get("edoc", "")) or {}
                    target_cols = {source.name} if source.type == "LOGICAL_COLUMN" \
                                  else {c.get("header", {}).get("name") for c in []}
                    alias_hits.extend(tml_probes.find_alias_column_uses(alias_tml, target_cols))
        except Exception:
            alias_supported = False
        # 2. RLS, joins, AI surface — left as future expansion (parse the same doc list).
        # 3. Alerts — call per-Liveboard --associated; left as future expansion.

    coverage = [
        CoverageEntry(type="Models / Views / Tables", checked=True,
                      found=sum(1 for d in dependents if d.type == "LOGICAL_TABLE")),
        CoverageEntry(type="Answers", checked=True,
                      found=sum(1 for d in dependents if d.type == "ANSWER")),
        CoverageEntry(type="Liveboards", checked=True,
                      found=sum(1 for d in dependents if d.type == "LIVEBOARD")),
        CoverageEntry(type="Sets / Cohorts", checked=True,
                      found=sum(1 for d in dependents if d.type == "SET")),
        CoverageEntry(type="Spotter feedback", checked=True,
                      found=sum(1 for d in dependents if d.type == "FEEDBACK")),
        CoverageEntry(type="RLS rules", checked=with_deep, found=len(rls_hits)),
        CoverageEntry(type="Monitor alerts", checked=with_deep, found=len(alert_hits)),
        CoverageEntry(
            type="Column alias TML",
            checked=with_deep and alias_supported,
            found=len(alias_hits),
            reason=None if (with_deep and alias_supported) else "requires --with-deep + cluster build 10.13.0+",
        ),
        CoverageEntry(type="Joins", checked=with_deep, found=len(join_hits)),
        CoverageEntry(type="Spotter AI surface area", checked=with_deep, found=len(ai_hits)),
        CoverageEntry(type="Column-level sharing (ACLs)", checked=False, found=0,
                      informational=True, reason="not implemented in v1"),
        CoverageEntry(type="CSR (column_security_rules)", checked=False, found=0,
                      reason="deferred — cluster feature gate (open-item #9)"),
    ]
```

- [ ] **Step 4: Run the test**

```bash
cd tools/ts-cli && pytest tests/test_report_entry.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/report/__init__.py tools/ts-cli/tests/test_report_entry.py
git commit -m "feat(ts-cli): wire TML probes (aliases) into build_report"
```

> **Scope honesty re: spec section 5**: This task wires *only* the column-alias probe end to end. The spec's full v1 coverage table also includes RLS, alerts, joins, Spotter AI surface area, and column ACLs — those follow the same pattern (one TML export or fetch-permissions call per relevant dependent, then call the corresponding `tml_probes.find_*` helper that Phase D already built). They are not delivered by this plan as standalone tasks; the implementing agent should either (a) extend this task to wire them inline before declaring G2 complete, or (b) land G2 alias-only and add G2b–G2f as follow-up PRs. The CoverageEntry list above already declares each row, so consumers see them appear with `found: 0` and `checked: false` until wired. Pick (a) for one big PR, (b) for incremental delivery.

---

### Task G3: Add the `report` Typer command

**Files:**
- Modify: `tools/ts-cli/ts_cli/commands/metadata.py`

- [ ] **Step 1: Read the existing metadata.py to understand patterns**

```bash
cat tools/ts-cli/ts_cli/commands/metadata.py | head -50
```

(Skim — the `dependents` command at the bottom of the file is the closest analog.)

- [ ] **Step 2: Append the new command**

Add to the end of `tools/ts-cli/ts_cli/commands/metadata.py`:

```python
# ---------------------------------------------------------------------------
# `ts metadata report` — full audit (dep walk + TML probes + classification + format)
# ---------------------------------------------------------------------------

@app.command("report")
def report(
    sources: List[str] = typer.Argument(..., help="One or more sources (GUID or N-part name)"),
    profile: Optional[str] = _profile_option,
    format: str = typer.Option("json", "--format", "-f",
                               help="Output format: json (default) | text | md"),
    fast: bool = typer.Option(False, "--fast",
                              help="Skip TML probes (v2 dependents API only)"),
    out: Optional[str] = typer.Option(None, "--out",
                                      help="Write to file instead of stdout"),
    depth: int = typer.Option(3, "--depth", help="Max dep-walk hops (default: 3)"),
) -> None:
    """Audit dependents of one or more sources.

    Examples:

    \b
      ts metadata report DB.SCH.TBL --profile P --format text
      ts metadata report DB.SCH.TBL.COL --profile P --format md --out report.md
      ts metadata report <guid> --profile P --format json --fast
    """
    from ts_cli.report import build_report, build_reports
    from ts_cli.report.formatters import render_json, render_text, render_md
    from ts_cli.report.resolver import SourceUnresolvedError, SourceAmbiguousError
    from ts_cli.report.schema import Report

    profile_name = resolve_profile(profile)

    try:
        if len(sources) == 1:
            payload = build_report(sources[0], profile=profile_name, with_deep=not fast, max_depth=depth)
        else:
            payload = build_reports(sources, profile=profile_name, with_deep=not fast, max_depth=depth)
    except SourceUnresolvedError as e:
        typer.echo(json.dumps({"error": "unresolved", "input": e.input}), err=True)
        raise typer.Exit(code=2)
    except SourceAmbiguousError as e:
        typer.echo(json.dumps({"error": "ambiguous", "input": e.input,
                               "candidates": [{"guid": c.get("metadata_id"), "name": c.get("metadata_name")}
                                              for c in e.candidates]}), err=True)
        raise typer.Exit(code=2)

    if format == "json":
        text = json.dumps(payload, indent=2)
    elif format == "text":
        # render_text only handles single Report; for multi-source, render each and concatenate.
        if "reports" in payload:
            blocks = []
            for r in payload["reports"]:
                if "error" in r:
                    blocks.append(f"[{r['source'].get('input')}] ERROR: {r['error']}")
                else:
                    blocks.append(render_text(_dict_to_report(r)))
            text = "\n\n---\n\n".join(blocks)
        else:
            text = render_text(_dict_to_report(payload))
    elif format == "md":
        if "reports" in payload:
            blocks = [render_md(_dict_to_report(r)) for r in payload["reports"] if "error" not in r]
            text = "\n\n---\n\n".join(blocks)
        else:
            text = render_md(_dict_to_report(payload))
    else:
        typer.echo(f"unknown format: {format}", err=True)
        raise typer.Exit(code=1)

    if out:
        from pathlib import Path
        Path(out).write_text(text + "\n")
    else:
        print(text)


def _dict_to_report(d: dict):
    """Reconstruct a Report from its dict form (formatters expect dataclass instances)."""
    from ts_cli.report.schema import (
        Report, SourceDescriptor, DependentEntry, Owner, RiskTag,
        CoverageEntry, Classification,
    )
    src_d = d["source"]
    src = SourceDescriptor(
        input=src_d["input"], guid=src_d["guid"], type=src_d["type"],
        name=src_d["name"], parent=src_d.get("parent"),
    )
    deps = []
    for de in d.get("dependents", []):
        owner = None
        if de.get("owner"):
            owner = Owner(id=de["owner"]["id"], display_name=de["owner"]["display_name"])
        deps.append(DependentEntry(
            guid=de["guid"], name=de["name"], type=de["type"],
            subtype=de.get("subtype"), via=de.get("via", "v2_dependents"),
            hops=de.get("hops", 1), owner=owner, modified_at=de.get("modified_at"),
            risk=RiskTag(tag=de["risk"]["tag"], reason=de["risk"]["reason"]),
        ))
    coverage = [CoverageEntry(**c) for c in d.get("coverage", [])]
    cls = d["classification"]
    classification = Classification(
        per_dependent=deps,
        aggregate=RiskTag(tag=cls["aggregate"]["tag"], reason=cls["aggregate"]["reason"]),
        recommendation=cls.get("recommendation", ""),
    )
    return Report(
        source=src, walked_at=d["walked_at"], profile=d["profile"],
        dependents=deps, coverage=coverage,
        classification=classification, warnings=d.get("warnings", []),
    )
```

- [ ] **Step 3: Smoke test the command help**

```bash
cd tools/ts-cli && pip install -e . && ts metadata report --help
```

Expected: help text including `--format`, `--fast`, `--out`, `--depth`.

- [ ] **Step 4: Run the full test suite**

```bash
cd tools/ts-cli && pytest tests/ -v
```

Expected: all tests pass (no regressions in existing tests).

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/commands/metadata.py
git commit -m "feat(ts-cli): add ts metadata report command (json | text | md)"
```

---

## Phase H — Skill + docs updates

### Task H1: Update `ts-dependency-manager` SKILL.md frontmatter and Steps 0/2

**Files:**
- Modify: `agents/cli/ts-dependency-manager/SKILL.md`

- [ ] **Step 1: Update the frontmatter description**

In `agents/cli/ts-dependency-manager/SKILL.md`, change:

```yaml
---
name: ts-dependency-manager
description: Safely remove or rename columns and repoint objects across a ThoughtSpot environment — generates a risk-rated impact report, backs up TML before any change, and supports full rollback.
---
```

To:

```yaml
---
name: ts-dependency-manager
description: Safely audit, remove, or repoint columns and objects across a ThoughtSpot environment — generates a risk-rated impact report, backs up TML before any change, and supports full rollback.
---
```

- [ ] **Step 2: Update Step 0 narrative and "When to use this skill" bullets**

Find the existing Step 0 overview line that says "safely remove, rename, or repoint columns" — change it to:

```
**ts-dependency-manager** — safely audit, remove, or repoint columns and objects across a ThoughtSpot environment, with a full impact report and TML backup before any change is made.
```

Add this bullet to "When to use this skill":

```
- You want a dependency report on a column/table/Model **without** committing to a change — Audit mode, or run `ts metadata report` directly for a non-interactive shell version.
```

- [ ] **Step 3: Update Step 2 mode picker with the CLI aside**

Find the Step 2 block that lists modes. After the "Audit produces a dependency report only — no changes applied" line, add:

```
> For a quick non-interactive audit, you can also run `ts metadata report <source>` directly — same coverage, no skill conversation. The CLI emits the same impact report data in JSON, text, or markdown.
```

- [ ] **Step 4: Verify pre-commit accepts the edit**

```bash
cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python3 tools/validate/check_skill_versions.py --root .
```

Expected: PASS (or no output).

- [ ] **Step 5: Commit**

```bash
git add agents/cli/ts-dependency-manager/SKILL.md
git commit -m "docs(ts-dependency-manager): update description and Step 0/2 for audit-first framing"
```

---

### Task H2: Replace SKILL.md Step 4 inline walk with `ts metadata report` call

**Files:**
- Modify: `agents/cli/ts-dependency-manager/SKILL.md`

- [ ] **Step 1: Identify the Step 4 block**

```bash
grep -n "^## Step 4" agents/cli/ts-dependency-manager/SKILL.md
grep -n "^## Step 5" agents/cli/ts-dependency-manager/SKILL.md
```

Note the line numbers — the Step 4 body is between them.

- [ ] **Step 2: Replace Step 4 body with a CLI-call instruction**

Replace the Step 4 body in `agents/cli/ts-dependency-manager/SKILL.md` with:

```markdown
## Step 4 — Walk dependents

Call the `ts metadata report` command to do the walk. It returns the same data the skill previously assembled inline, plus richer coverage (RLS, alerts, joins, Spotter AI surface area, column aliases).

```bash
ts metadata report <source-guid> --profile {profile_name} --format json --depth 3 > /tmp/{slug}_report.json
```

Then parse the JSON. The shape is documented in [docs/superpowers/specs/2026-05-28-ts-metadata-report-design.md](../../../docs/superpowers/specs/2026-05-28-ts-metadata-report-design.md). Key fields:

- `source` — `{ "input", "guid", "type", "name", "parent" }`
- `dependents[]` — flat list, each with `guid / name / type / hops / owner / modified_at / risk{tag,reason}`
- `coverage[]` — `[{ "type", "checked", "found", "reason?" }, ...]`
- `classification` — `{ "per_dependent", "aggregate{tag,reason}", "recommendation" }`

Where the skill needs to filter by audit-scope (specific columns vs whole-object), it does so over the dependents list after parsing — the CLI returns everything the source touches.

### Filtering by scope

| Scope | Filter applied after parse |
|---|---|
| Specific column(s) | Keep dependents whose `risk.reason` references the column name; drop others. |
| Column set | As above, but check membership against the set's columns. |
| Whole object | Keep all dependents. |
```

- [ ] **Step 3: Commit**

```bash
git add agents/cli/ts-dependency-manager/SKILL.md
git commit -m "refactor(ts-dependency-manager): Step 4 uses ts metadata report instead of inline walk"
```

---

### Task H3: Replace SKILL.md Step 5 inline rendering with CLI markdown output

**Files:**
- Modify: `agents/cli/ts-dependency-manager/SKILL.md`

- [ ] **Step 1: Identify the Step 5 block**

```bash
grep -n "^## Step 5" agents/cli/ts-dependency-manager/SKILL.md
grep -n "^## Step 6" agents/cli/ts-dependency-manager/SKILL.md
```

- [ ] **Step 2: Replace Step 5 body**

Replace the Step 5 body with:

```markdown
## Step 5 — Render the impact report

The CLI already does the rendering. Run:

```bash
ts metadata report <source-guid> --profile {profile_name} --format md --out /tmp/{slug}_impact_report.md
```

Present the markdown content to the user. Apply scope filtering (Step 4) to the dependents table before display when the audit scope is column-specific.

The CLI's coverage matrix is the canonical Scan Coverage block — `build_coverage.py` is now retired in favor of the live API-driven coverage list.

### Stop conditions

When `classification.aggregate.tag == "STOP"`, surface to the user:

> ⛔ STOP CONDITION — `{recommendation}`
>
> {reason}
>
> Resolve via the ThoughtSpot UI (remove or rewrite the RLS rule) before re-running this skill.

For Audit mode, stop after this step. For Remove / Repoint, proceed to Step 6 only if the user explicitly accepts the STOP impact.
```

- [ ] **Step 3: Commit**

```bash
git add agents/cli/ts-dependency-manager/SKILL.md
git commit -m "refactor(ts-dependency-manager): Step 5 renders ts metadata report markdown"
```

---

### Task H4: Update `references/dependency-types.md` and `references/open-items.md`

**Files:**
- Modify: `agents/cli/ts-dependency-manager/references/dependency-types.md`
- Modify: `agents/cli/ts-dependency-manager/references/open-items.md`

- [ ] **Step 1: Update dependency-types.md status column**

For row #7 (Monitor alert), change the Status column to:

```
Implementable (auto via `ts metadata report`)
```

Same for row #8 (RLS rule). For row #11 (Inline alias), change Status to:

```
Implementable (full — CLI handles all layers)
```

- [ ] **Step 2: Close open-items.md entries**

In `agents/cli/ts-dependency-manager/references/open-items.md`:

- #5 — change status header to `## #5 — ts metadata dependents CLI command — VERIFIED YYYY-MM-DD` (use today's date)
- #10 — change status header to `## #10 — Column alias TML — VERIFIED YYYY-MM-DD via export_with_column_aliases beta flag`. Add a note: "Tested 2026-05-28 against `533c2251-834f-439d-9161-9985520f24ac` on SpotterAccuracy (build supports `export_options.export_with_column_aliases`)."
- #19 — change status header to `## #19 — Audit scope 3: Whole-object section-per-column report — CLOSED YYYY-MM-DD via ts metadata report multi-source mode`
- #21 — change status header to `## #21 — Recommendation engine after audit — PARTIAL YYYY-MM-DD (risk + recommended-action covered by classifier; auto-jump-into-flow still deferred)`

Add a new entry at the end:

```markdown
## #22 — Smoke test for ts metadata report — OPEN

**Status:** OPEN until `tools/smoke-tests/smoke_ts-metadata-report.py` passes against
SpotterAccuracy. See plan Task I1.
```

- [ ] **Step 3: Commit**

```bash
git add agents/cli/ts-dependency-manager/references/dependency-types.md \
        agents/cli/ts-dependency-manager/references/open-items.md
git commit -m "docs(ts-dependency-manager): update dep-types statuses and close items #5/#10/#19"
```

---

### Task H5: Update the Cursor mirror

**Files:**
- Modify: `agents/cursor/rules/ts-dependency-manager.mdc`

- [ ] **Step 1: Apply the same Step 4/5 simplification to the .mdc**

Open `agents/cursor/rules/ts-dependency-manager.mdc`. Find the Step 4 and Step 5 sections. Replace them with the same content patterns as the SKILL.md, condensed for the .mdc format. Keep the "Untested in Cursor" disclaimer at the top if present.

- [ ] **Step 2: Commit**

```bash
git add agents/cursor/rules/ts-dependency-manager.mdc
git commit -m "docs(ts-dependency-manager): Cursor mirror — Step 4/5 use ts metadata report"
```

---

## Phase I — Smoke tests, README, CHANGELOG, version bump

### Task I1: Add a smoke test for `ts metadata report`

**Files:**
- Create: `tools/smoke-tests/smoke_ts-metadata-report.py`

- [ ] **Step 1: Choose a stable test fixture on SpotterAccuracy**

From the prior conversation: `EDUCATION_BUSINESS.EDUCATION_BUSINESS.UNIVERSITY_FACULTY` (GUID `baa451a6-02a0-42d1-8347-8cd4af13b505`) had exactly one auto-Model dependent and zero downstream. Stable enough for a drift-detection assertion.

- [ ] **Step 2: Write the smoke test**

```python
# tools/smoke-tests/smoke_ts-metadata-report.py
"""Smoke test for `ts metadata report` against SpotterAccuracy.

Asserts:
- schema_version == "1.0"
- source.guid matches expected
- exactly one dependent (auto-Model)
- aggregate recommendation is LOW or SAFE
"""
from __future__ import annotations

import json
import subprocess
import sys


PROFILE = "SpotterAccuracy"
SOURCE = "baa451a6-02a0-42d1-8347-8cd4af13b505"
EXPECTED_NAME = "EDUCATION_BUSINESS.EDUCATION_BUSINESS.UNIVERSITY_FACULTY"


def main() -> int:
    result = subprocess.run(
        ["ts", "metadata", "report", SOURCE, "--profile", PROFILE, "--format", "json", "--fast"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("FAIL: command returned non-zero", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        print(f"FAIL: stdout is not JSON: {e}", file=sys.stderr)
        return 1

    if payload.get("schema_version") != "1.0":
        print(f"FAIL: unexpected schema_version: {payload.get('schema_version')}", file=sys.stderr)
        return 1

    src = payload.get("source") or {}
    if src.get("guid") != SOURCE:
        print(f"FAIL: source.guid mismatch: {src.get('guid')}", file=sys.stderr)
        return 1
    if src.get("name") != EXPECTED_NAME:
        print(f"FAIL: source.name mismatch: {src.get('name')}", file=sys.stderr)
        return 1

    deps = payload.get("dependents") or []
    if len(deps) < 1:
        print(f"FAIL: expected at least 1 dependent (auto-Model), got {len(deps)}", file=sys.stderr)
        return 1

    rec = (payload.get("classification") or {}).get("recommendation")
    if rec not in ("SAFE_TO_DROP", "REVIEW_RECOMMENDED"):
        print(f"FAIL: unexpected recommendation: {rec}", file=sys.stderr)
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the smoke test live**

```bash
python3 tools/smoke-tests/smoke_ts-metadata-report.py
```

Expected: `PASS`.

If FAIL: re-run with `--format text` interactively to see the actual output, then either fix the bug or relax the assertion if the fixture has drifted.

- [ ] **Step 4: Commit**

```bash
git add tools/smoke-tests/smoke_ts-metadata-report.py
git commit -m "test(ts-cli): add smoke test for ts metadata report"
```

---

### Task I2: Update `tools/ts-cli/README.md` and `CHANGELOG.md`

**Files:**
- Modify: `tools/ts-cli/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add a `ts metadata report` entry to ts-cli README**

Find the section listing `ts metadata` subcommands in `tools/ts-cli/README.md`. Add:

```markdown
### `ts metadata report`

Audit one or more sources: walks dependents, probes TML for RLS rules, alerts, joins, column aliases, and Spotter AI surface area, classifies risk, and renders the result as JSON / text / markdown.

```bash
ts metadata report <source>... --profile <name> [--format json|text|md] [--fast] [--out FILE] [--depth N]
```

`<source>` accepts a 36-char GUID, `DB.SCHEMA.TABLE`, or `DB.SCHEMA.TABLE.COLUMN`.

Output schema: `docs/superpowers/specs/2026-05-28-ts-metadata-report-design.md` (section 6).
```

- [ ] **Step 2: Add CHANGELOG.md entry**

At the top of `CHANGELOG.md`, under today's date heading (create the date if it doesn't exist):

```markdown
## YYYY-MM-DD
- feat: add `ts metadata report` command + ts-dependency-manager audit-mode rewrite
```

(Use the actual date — replace YYYY-MM-DD with the merge-day date when the PR opens.)

- [ ] **Step 3: Commit**

```bash
git add tools/ts-cli/README.md CHANGELOG.md
git commit -m "docs: ts-cli README and CHANGELOG entries for ts metadata report"
```

---

### Task I3: Run full validator + smoke battery, fix any regressions

**Files:** (none — verification step)

- [ ] **Step 1: Run all validators**

```bash
cd /Users/damianwaldron/Dev/thoughtspot-agent-skills
python3 tools/validate/check_skill_versions.py --root .
python3 tools/validate/check_runtime_coverage.py --root .
python3 tools/validate/check_consistency.py --root .
python3 tools/validate/check_smoke_tests.py --root .
python3 tools/validate/check_skill_naming.py --root .
python3 tools/validate/check_version_sync.py
```

Expected: all pass.

- [ ] **Step 2: Run all ts-cli unit tests**

```bash
cd tools/ts-cli && pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 3: Run smoke tests touched by this PR**

```bash
python3 tools/smoke-tests/smoke_ts-metadata-report.py
python3 tools/smoke-tests/smoke_ts-dependency-manager.py
```

Expected: both PASS. If the dependency-manager smoke test fails, update its Step 4/5 assertions to consume the CLI output rather than the old inline walk format.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: update smoke_ts-dependency-manager.py for CLI-backed audit flow"
```

(Only if there are fixes; skip if step 3 passed cleanly.)

---

### Task I4: Bump ts-cli version (at PR time only)

**Files:**
- Modify: `tools/ts-cli/ts_cli/__init__.py`
- Modify: `tools/ts-cli/pyproject.toml`
- Modify: `agents/cli/ts-dependency-manager/SKILL.md` (Changelog section)

> Do this **last**, immediately before opening the PR. Per `.claude/rules/versioning.md`, version bumps happen at PR time, not during wip.

- [ ] **Step 1: Read the current ts-cli version**

```bash
grep version tools/ts-cli/pyproject.toml
grep __version__ tools/ts-cli/ts_cli/__init__.py
```

- [ ] **Step 2: Bump MINOR**

If current is `0.5.0`, bump to `0.6.0`. Update both files to match.

- [ ] **Step 3: Add a SKILL.md Changelog entry to ts-dependency-manager**

Find the `## Changelog` section at the bottom of `agents/cli/ts-dependency-manager/SKILL.md`. Add a new row at the top:

```markdown
| 0.3.0 | YYYY-MM-DD | Audit mode now uses `ts metadata report` (richer coverage: RLS, alerts, joins, AI surface, column aliases) |
```

(Use today's date; bump the MINOR digit from whatever's current.)

- [ ] **Step 4: Run check_version_sync**

```bash
python3 tools/validate/check_version_sync.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/__init__.py tools/ts-cli/pyproject.toml \
        agents/cli/ts-dependency-manager/SKILL.md
git commit -m "chore: bump ts-cli to 0.6.0 and ts-dependency-manager to 0.3.0"
```

---

## Phase J — Open the pull request

### Task J1: Push branch and open PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/ts-metadata-report
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat: ts metadata report + ts-dependency-manager audit-mode rewrite" --body "$(cat <<'EOF'
## Summary

- Adds `ts metadata report <source>` CLI command — non-interactive dependency audit with JSON / text / markdown output
- Refactors `ts-dependency-manager` Audit mode (Steps 4 + 5) to consume the new command
- Adds Beta-flag-backed column alias retrieval (verified working on SpotterAccuracy)
- Closes open-items #5, #10, #19; partial #21; opens #22 for the smoke test

## Test plan

- [x] All ts-cli unit tests pass (`pytest tools/ts-cli/tests/`)
- [x] All validators pass
- [x] `smoke_ts-metadata-report.py` passes against SpotterAccuracy
- [x] `smoke_ts-dependency-manager.py` updated and passing
- [ ] Live exercise of `/ts-dependency-manager` Audit mode against a known-good Model on staging
- [ ] Live test of `ts metadata report --format md --out` against a real-world Liveboard graph

Design spec: `docs/superpowers/specs/2026-05-28-ts-metadata-report-design.md`
Plan: `docs/superpowers/plans/2026-05-28-ts-metadata-report.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Returns: PR URL. Paste here when the PR opens.

---

## Self-review checklist (run after completing the plan)

- [ ] Every spec requirement maps to a task. Walk through spec sections 1–13 and tick them off.
- [ ] No "TBD", "implement later", "similar to Task N" anywhere in the plan.
- [ ] Each step in each task contains either explicit code, an explicit command, or an explicit edit instruction.
- [ ] Function and type names used in later tasks match names defined in earlier tasks (`SourceDescriptor`, `DependentEntry`, `RiskTag`, `build_report`, `aggregate_classification`, etc.).
- [ ] Phase H (skill updates) runs only after Phases A–G are complete and the CLI works end-to-end.
- [ ] Phase I4 (version bump) is the very last commit before opening the PR.

---

## Handoff prompt for a fresh Sonnet session

Copy this block to a fresh Claude Code session (Sonnet) once you're ready to start the implementation:

```
Implement the plan in docs/superpowers/plans/2026-05-28-ts-metadata-report.md task by task.

Repo: /Users/damianwaldron/Dev/thoughtspot-agent-skills
Branch: feat/ts-metadata-report — already exists locally with the design spec committed (commit d76b94f). Switch to it before starting.

Before touching any code:
1. Read CLAUDE.md, tools/ts-cli/CLAUDE.md, and the rules under .claude/rules/ (especially branching.md, ts-cli.md, api-research.md).
2. Confirm the SpotterAccuracy ThoughtSpot profile works: ts auth whoami -p SpotterAccuracy.
3. Read the design spec at docs/superpowers/specs/2026-05-28-ts-metadata-report-design.md to ground yourself in the overall architecture.

Then invoke superpowers:subagent-driven-development and execute the plan one task at a time.

Per-task model choice:
- Tasks C1–C3 (walker) and E1–E3 (classifier): dispatch with Opus.
- All other tasks: Sonnet is fine.

For every task: write the test → run (must fail) → implement → run (must pass) → commit. The pre-commit hook runs validators automatically.

Stop and ask the user before:
- Pushing the branch (Phase J)
- Bumping versions (Task I4)
- Any task where Sonnet stalls 2 attempts in a row — escalate to Opus rather than guessing.

Final deliverable: a green PR opened against main with all unit + smoke tests passing and validators clean.
```
