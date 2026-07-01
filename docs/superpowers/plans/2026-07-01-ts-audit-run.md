# `ts audit run` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify all 51 ts-audit checks as deterministic Python in a `ts audit run` CLI command that outputs a structured JSON report.

**Architecture:** Module-per-angle with a thin runner. Eight files in a new `tools/ts-cli/ts_cli/audit/` package: findings dataclass, context builder, five angle modules (ai, data, human, perf, security), and a runner. A CLI command in `commands/audit.py` wires the Typer interface.

**Tech Stack:** Python 3.9+, typer, requests (via existing ThoughtSpotClient), dataclasses, re, itertools, json.

## Global Constraints

- All output JSON to stdout, diagnostics to stderr — matching every other ts-cli command.
- No new dependencies in `pyproject.toml`. All imports are stdlib + existing deps.
- Follow the `_profile_option` + `ThoughtSpotClient(resolve_profile(profile))` pattern from existing commands.
- Version bump: `__init__.py` and `pyproject.toml` from `0.21.0` to `0.22.0`.
- Tests must not require a live ThoughtSpot connection — fixture-based only.
- Every Finding must include `check_id`, `angle`, `severity`, `object_type`, `object_name`, `object_guid`, `detail`. `metric` and `threshold` are optional (None for boolean checks).
- Severity values: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO` — exactly these strings.
- Each check module exports an `ALL_CHECKS` list of functions.
- Check functions return `[]` when nothing triggers — no findings means passing.
- Checks never call APIs — they only read from `AuditContext`.

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `tools/ts-cli/ts_cli/audit/__init__.py` | `run_audit()` entry point, angle dispatch |
| Create | `tools/ts-cli/ts_cli/audit/findings.py` | `Finding` dataclass, `build_summary()` |
| Create | `tools/ts-cli/ts_cli/audit/context.py` | `AuditContext` dataclass, `build_context()` |
| Create | `tools/ts-cli/ts_cli/audit/checks_ai.py` | A1–A5 checks |
| Create | `tools/ts-cli/ts_cli/audit/checks_data.py` | D1–D12 checks |
| Create | `tools/ts-cli/ts_cli/audit/checks_human.py` | H1–H10 checks |
| Create | `tools/ts-cli/ts_cli/audit/checks_perf.py` | P1–P18 checks |
| Create | `tools/ts-cli/ts_cli/audit/checks_security.py` | S1–S10 checks |
| Create | `tools/ts-cli/ts_cli/commands/audit.py` | `ts audit run` Typer command |
| Modify | `tools/ts-cli/ts_cli/cli.py` | Register `audit` command group |
| Modify | `tools/ts-cli/ts_cli/__init__.py` | Version bump to 0.22.0 |
| Modify | `tools/ts-cli/pyproject.toml` | Version bump to 0.22.0 |
| Create | `tools/ts-cli/tests/test_audit_findings.py` | Tests for Finding + summary |
| Create | `tools/ts-cli/tests/test_audit_context.py` | Tests for AuditContext |
| Create | `tools/ts-cli/tests/test_checks_ai.py` | Tests for A1–A5 |
| Create | `tools/ts-cli/tests/test_checks_data.py` | Tests for D1–D12 |
| Create | `tools/ts-cli/tests/test_checks_human.py` | Tests for H1–H10 |
| Create | `tools/ts-cli/tests/test_checks_perf.py` | Tests for P1–P18 |
| Create | `tools/ts-cli/tests/test_checks_security.py` | Tests for S1–S10 |

---

### Task 1: Finding Dataclass and Summary Builder

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/__init__.py` (empty for now — just makes it a package)
- Create: `tools/ts-cli/ts_cli/audit/findings.py`
- Create: `tools/ts-cli/tests/test_audit_findings.py`

**Interfaces:**
- Consumes: nothing (foundation task)
- Produces: `Finding` dataclass used by every check module (Tasks 3–7) and the runner (Task 8). `build_summary(findings: list[Finding], checks_run: int, models_count: int, tables_count: int) -> dict` used by the runner.

- [ ] **Step 1: Write the test file**

```python
# tools/ts-cli/tests/test_audit_findings.py
from ts_cli.audit.findings import Finding, build_summary


def test_finding_to_dict_includes_all_fields():
    f = Finding(
        check_id="D1", angle="data_modeling", severity="HIGH",
        object_type="model", object_name="Sales", object_guid="abc-123",
        detail="16 tables exceed threshold", metric=16,
        threshold={"green": 10, "yellow": 15},
    )
    d = f.to_dict()
    assert d["check_id"] == "D1"
    assert d["angle"] == "data_modeling"
    assert d["severity"] == "HIGH"
    assert d["object_type"] == "model"
    assert d["object_name"] == "Sales"
    assert d["object_guid"] == "abc-123"
    assert d["detail"] == "16 tables exceed threshold"
    assert d["metric"] == 16
    assert d["threshold"] == {"green": 10, "yellow": 15}


def test_finding_to_dict_none_metric():
    f = Finding(
        check_id="A3", angle="ai", severity="HIGH",
        object_type="model", object_name="Sales", object_guid="abc-123",
        detail="AI context missing", metric=None, threshold=None,
    )
    d = f.to_dict()
    assert d["metric"] is None
    assert d["threshold"] is None


def test_build_summary_counts_by_severity():
    findings = [
        Finding("D1", "data_modeling", "HIGH", "model", "A", "g1", "x", 1, None),
        Finding("D2", "data_modeling", "MEDIUM", "model", "A", "g1", "x", 1, None),
        Finding("A1", "ai", "HIGH", "model", "A", "g1", "x", 1, None),
    ]
    s = build_summary(findings, checks_run=10, models_count=2, tables_count=5)
    assert s["by_severity"]["HIGH"] == 2
    assert s["by_severity"]["MEDIUM"] == 1
    assert s["by_severity"]["LOW"] == 0
    assert s["by_angle"]["data_modeling"] == 2
    assert s["by_angle"]["ai"] == 1
    assert s["objects_scanned"]["models"] == 2
    assert s["objects_scanned"]["tables"] == 5
    assert s["checks_run"] == 10


def test_build_summary_empty_findings():
    s = build_summary([], checks_run=5, models_count=1, tables_count=3)
    assert all(v == 0 for v in s["by_severity"].values())
    assert all(v == 0 for v in s["by_angle"].values())
    assert s["checks_run"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/ts-cli && python -m pytest tests/test_audit_findings.py -v`
Expected: FAIL (ModuleNotFoundError — module doesn't exist yet)

- [ ] **Step 3: Create the audit package and findings module**

```python
# tools/ts-cli/ts_cli/audit/__init__.py
```

```python
# tools/ts-cli/ts_cli/audit/findings.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union


@dataclass
class Finding:
    check_id: str
    angle: str
    severity: str
    object_type: str
    object_name: str
    object_guid: str
    detail: str
    metric: Optional[Union[int, float]] = None
    threshold: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "angle": self.angle,
            "severity": self.severity,
            "object_type": self.object_type,
            "object_name": self.object_name,
            "object_guid": self.object_guid,
            "detail": self.detail,
            "metric": self.metric,
            "threshold": self.threshold,
        }


_SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
_ANGLES = ["ai", "data_modeling", "human", "performance", "security"]


def build_summary(
    findings: list[Finding],
    checks_run: int,
    models_count: int,
    tables_count: int,
) -> dict:
    by_severity = {s: 0 for s in _SEVERITIES}
    by_angle = {a: 0 for a in _ANGLES}
    for f in findings:
        if f.severity in by_severity:
            by_severity[f.severity] += 1
        if f.angle in by_angle:
            by_angle[f.angle] += 1
    return {
        "by_severity": by_severity,
        "by_angle": by_angle,
        "objects_scanned": {"models": models_count, "tables": tables_count},
        "checks_run": checks_run,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/ts-cli && python -m pytest tests/test_audit_findings.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/__init__.py tools/ts-cli/ts_cli/audit/findings.py tools/ts-cli/tests/test_audit_findings.py
git commit -m "feat(audit): add Finding dataclass and summary builder"
```

---

### Task 2: AuditContext Data Layer

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/context.py`
- Create: `tools/ts-cli/tests/test_audit_context.py`

**Interfaces:**
- Consumes: `ThoughtSpotClient` from `ts_cli.client` (existing — `.post()` method)
- Produces: `AuditContext` dataclass used by all check modules (Tasks 3–7). `build_context(client: ThoughtSpotClient, model_guids: list[str], angles: list[str]) -> AuditContext` used by the runner (Task 8). Also `make_context(**kwargs) -> AuditContext` test helper used by all test files (Tasks 3–7).

- [ ] **Step 1: Write the test file**

```python
# tools/ts-cli/tests/test_audit_context.py
from ts_cli.audit.context import AuditContext, make_context


def _sample_model(name="Sales", guid="m-1", tables=None, columns=None,
                  formulas=None, model_tables=None, properties=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "ORDERS", "id": "ORDERS"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
        },
    }


def test_make_context_defaults():
    ctx = make_context()
    assert ctx.models == []
    assert ctx.tables == {}
    assert ctx.dependents == {}
    assert ctx.metadata == []
    assert ctx.ai_instructions == {}
    assert ctx.answers == []
    assert ctx.model_guids == []


def test_make_context_with_model():
    m = _sample_model()
    ctx = make_context(models=[m])
    assert len(ctx.models) == 1
    assert ctx.models[0]["model"]["name"] == "Sales"


def test_guid_for_extracts_root_guid():
    m = _sample_model(guid="abc-123")
    ctx = make_context(models=[m])
    assert ctx.guid_for(m) == "abc-123"


def test_guid_for_missing_returns_empty():
    m = {"model": {"name": "X"}}
    ctx = make_context(models=[m])
    assert ctx.guid_for(m) == ""


def test_tables_for_model():
    m = _sample_model(model_tables=[
        {"name": "ORDERS", "fqn": "db.schema.ORDERS"},
        {"name": "ITEMS", "fqn": "db.schema.ITEMS"},
    ])
    ctx = make_context(
        models=[m],
        tables={
            "db.schema.ORDERS": {"table": {"name": "ORDERS"}},
            "db.schema.ITEMS": {"table": {"name": "ITEMS"}},
            "db.schema.OTHER": {"table": {"name": "OTHER"}},
        },
    )
    result = ctx.tables_for_model(m)
    assert len(result) == 2
    names = {t["table"]["name"] for t in result}
    assert names == {"ORDERS", "ITEMS"}


def test_tables_for_model_missing_fqn():
    m = _sample_model(model_tables=[{"name": "ORDERS"}])
    ctx = make_context(models=[m], tables={})
    assert ctx.tables_for_model(m) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/ts-cli && python -m pytest tests/test_audit_context.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write the context module**

```python
# tools/ts-cli/ts_cli/audit/context.py
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from ts_cli.commands.tml import parse_edoc, detect_tml_type


@dataclass
class AuditContext:
    models: list[dict] = field(default_factory=list)
    tables: dict[str, dict] = field(default_factory=dict)
    dependents: dict[str, list] = field(default_factory=dict)
    metadata: list[dict] = field(default_factory=list)
    ai_instructions: dict[str, dict] = field(default_factory=dict)
    answers: list[dict] = field(default_factory=list)
    model_guids: list[str] = field(default_factory=list)

    def guid_for(self, tml: dict) -> str:
        return tml.get("guid", "")

    def tables_for_model(self, model: dict) -> list[dict]:
        result = []
        for mt in (model.get("model", {}).get("model_tables") or []):
            fqn = mt.get("fqn", "")
            if fqn and fqn in self.tables:
                result.append(self.tables[fqn])
        return result


def make_context(
    models: Optional[list[dict]] = None,
    tables: Optional[dict[str, dict]] = None,
    dependents: Optional[dict[str, list]] = None,
    metadata: Optional[list[dict]] = None,
    ai_instructions: Optional[dict[str, dict]] = None,
    answers: Optional[list[dict]] = None,
    model_guids: Optional[list[str]] = None,
) -> AuditContext:
    return AuditContext(
        models=models or [],
        tables=tables or {},
        dependents=dependents or {},
        metadata=metadata or [],
        ai_instructions=ai_instructions or {},
        answers=answers or [],
        model_guids=model_guids or [],
    )


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_context(
    client: Any,
    model_guids: list[str],
    angles: list[str],
) -> AuditContext:
    models: list[dict] = []
    tables: dict[str, dict] = {}
    dependents: dict[str, list] = {}
    ai_instructions: dict[str, dict] = {}
    answers: list[dict] = []

    # Step 1: Export model + associated table TMLs
    _log(f"Exporting TML for {len(model_guids)} model(s)...")
    resp = client.post("/api/rest/2.0/metadata/tml/export", json={
        "metadata": [{"identifier": g} for g in model_guids],
        "export_fqn": True,
        "export_associated": True,
        "formattype": "YAML",
    })
    for item in resp.json():
        edoc = item.get("edoc", "")
        parsed = parse_edoc(edoc, "YAML")
        tml_type = detect_tml_type(parsed)
        if tml_type == "model":
            models.append(parsed)
        elif tml_type == "table":
            fqn = (parsed.get("table", {}).get("db") or "") + "." + \
                  (parsed.get("table", {}).get("schema") or "") + "." + \
                  (parsed.get("table", {}).get("db_table") or "")
            tables[fqn] = parsed

    # Step 2: Metadata search for object inventory
    _log("Searching metadata inventory...")
    metadata_results: list[dict] = []
    offset = 0
    while True:
        resp = client.post("/api/rest/2.0/metadata/search", json={
            "metadata": [{"type": "LOGICAL_TABLE"}],
            "record_size": 200,
            "record_offset": offset,
            "include_headers": True,
            "include_hidden_objects": True,
        })
        data = resp.json()
        page = data if isinstance(data, list) else data.get("metadata", [])
        if not page:
            break
        metadata_results.extend(page)
        if len(page) < 200:
            break
        offset += 200

    # Step 3: Dependents for each model
    _log("Fetching dependents...")
    all_guids = model_guids.copy()
    for m in models:
        for mt in (m.get("model", {}).get("model_tables") or []):
            fqn = mt.get("fqn", "")
            for t in tables.values():
                if t.get("guid"):
                    all_guids.append(t["guid"])
    seen = set()
    unique_guids = [g for g in all_guids if g not in seen and not seen.add(g)]

    if unique_guids:
        resp = client.post("/api/rest/2.0/metadata/search", json={
            "metadata": [{"identifier": g, "type": "LOGICAL_TABLE"} for g in unique_guids],
            "include_dependent_objects": True,
            "dependent_object_version": "V2",
        })
        from ts_cli.commands.metadata import _normalize_dependents_response
        dep_rows = _normalize_dependents_response(resp.json())
        for row in dep_rows:
            src = row["source_guid"]
            dependents.setdefault(src, []).append(row)

    # Step 4: AI instructions (only if angle A requested)
    if "A" in angles:
        _log("Fetching AI instructions...")
        for guid in model_guids:
            try:
                resp = client.post("/api/rest/2.0/ai/instructions/get", json={
                    "metadata_identifier": guid,
                })
                ai_instructions[guid] = resp.json()
            except Exception:
                ai_instructions[guid] = {}

    # Step 5: Answer TMLs (only if angle H requested and dependents exist)
    if "H" in angles:
        answer_guids = set()
        for deps in dependents.values():
            for d in deps:
                if d.get("type") == "ANSWER" and d.get("guid"):
                    answer_guids.add(d["guid"])
        if answer_guids:
            _log(f"Exporting {len(answer_guids)} answer TML(s)...")
            guid_list = list(answer_guids)
            resp = client.post("/api/rest/2.0/metadata/tml/export", json={
                "metadata": [{"identifier": g} for g in guid_list],
                "export_fqn": True,
                "formattype": "YAML",
            })
            for item in resp.json():
                edoc = item.get("edoc", "")
                parsed = parse_edoc(edoc, "YAML")
                if detect_tml_type(parsed) == "answer":
                    answers.append(parsed)

    _log(f"Context ready: {len(models)} model(s), {len(tables)} table(s), "
         f"{len(answers)} answer(s)")

    return AuditContext(
        models=models,
        tables=tables,
        dependents=dependents,
        metadata=metadata_results,
        ai_instructions=ai_instructions,
        answers=answers,
        model_guids=model_guids,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/ts-cli && python -m pytest tests/test_audit_context.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/context.py tools/ts-cli/tests/test_audit_context.py
git commit -m "feat(audit): add AuditContext data layer and build_context()"
```

---

### Task 3: AI Readiness Checks (A1–A5)

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/checks_ai.py`
- Create: `tools/ts-cli/tests/test_checks_ai.py`

**Interfaces:**
- Consumes: `Finding` from `ts_cli.audit.findings` (`Finding(check_id, angle, severity, object_type, object_name, object_guid, detail, metric, threshold)`). `AuditContext` from `ts_cli.audit.context` (`ctx.models`, `ctx.ai_instructions`, `ctx.guid_for(tml)`). `make_context()` from `ts_cli.audit.context` for tests.
- Produces: `ALL_CHECKS: list[callable]` — list of check functions, each with signature `(ctx: AuditContext) -> list[Finding]`. Used by the runner (Task 8) to discover and execute checks.

- [ ] **Step 1: Write the test file**

```python
# tools/ts-cli/tests/test_checks_ai.py
from ts_cli.audit.checks_ai import check_a1, check_a2, check_a3, check_a4, check_a5, ALL_CHECKS
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", columns=None, description="", properties=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "description": description,
            "model_tables": [{"name": "T1"}],
            "columns": columns or [],
            "formulas": [],
            "properties": properties or {},
        },
    }


def _col(name="Amount", description="", synonyms=None):
    return {"name": name, "description": description, "synonyms": synonyms or []}


# --- A1: Description coverage ---

def test_a1_flags_low_coverage():
    cols = [_col("A"), _col("B"), _col("C", description="has desc")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_a1(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"
    assert findings[0].check_id == "A1"


def test_a1_passes_high_coverage():
    cols = [_col("A", description="good"), _col("B", description="good")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_a1(ctx) == []


def test_a1_empty_columns():
    ctx = make_context(models=[_model(columns=[])])
    assert check_a1(ctx) == []


# --- A2: Synonym coverage ---

def test_a2_flags_low_coverage():
    cols = [_col("A"), _col("B"), _col("C", synonyms=["revenue"])]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_a2(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "A2"


def test_a2_passes_high_coverage():
    cols = [_col("A", synonyms=["a"]), _col("B", synonyms=["b"])]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_a2(ctx) == []


# --- A3: AI context presence ---

def test_a3_flags_missing_instructions():
    ctx = make_context(models=[_model(guid="m-1")], ai_instructions={})
    findings = check_a3(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_a3_passes_with_instructions():
    ctx = make_context(
        models=[_model(guid="m-1")],
        ai_instructions={"m-1": {"instructions": "Some coaching text"}},
    )
    assert check_a3(ctx) == []


# --- A4: Model description ---

def test_a4_flags_missing_description():
    ctx = make_context(models=[_model(description="")])
    findings = check_a4(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "MEDIUM"


def test_a4_passes_with_description():
    ctx = make_context(models=[_model(description="Sales data model")])
    assert check_a4(ctx) == []


# --- A5: Spotter readiness composite ---

def test_a5_flags_not_ready():
    cols = [_col("A"), _col("B")]  # no descriptions, no synonyms
    ctx = make_context(models=[_model(columns=cols, description="")])
    findings = check_a5(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "A5"


def test_a5_passes_ready():
    cols = [
        _col("Amount", description="Total sale amount", synonyms=["revenue", "sales"]),
        _col("Date", description="Transaction date", synonyms=["order date"]),
    ]
    ctx = make_context(
        models=[_model(columns=cols, description="Sales model")],
        ai_instructions={"m-1": {"instructions": "coaching"}},
    )
    findings = check_a5(ctx)
    assert findings == [] or findings[0].severity == "INFO"


# --- ALL_CHECKS ---

def test_all_checks_has_five_entries():
    assert len(ALL_CHECKS) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_ai.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write the checks module**

```python
# tools/ts-cli/ts_cli/audit/checks_ai.py
from __future__ import annotations

import re

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "ai"

# H1 anti-patterns (reused by A5 for name quality component)
_NAME_ANTI = re.compile(
    r"^col\d+$|^field[-_]?\d+$|^val\d*$|^tmp[-_]|^\d|^[A-Z_]+$",
    re.IGNORECASE,
)


def check_a1(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        if not cols:
            continue
        described = sum(1 for c in cols if (c.get("description") or "").strip())
        pct = (described / len(cols)) * 100
        if pct >= 80:
            continue
        severity = "HIGH" if pct < 50 else "MEDIUM"
        findings.append(Finding(
            check_id="A1", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"{described}/{len(cols)} columns have descriptions ({pct:.0f}%)",
            metric=round(pct, 1),
            threshold={"green": 80, "yellow": 50},
        ))
    return findings


def check_a2(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        if not cols:
            continue
        with_syn = sum(1 for c in cols if (c.get("synonyms") or []))
        pct = (with_syn / len(cols)) * 100
        if pct >= 50:
            continue
        severity = "HIGH" if pct < 25 else "MEDIUM"
        findings.append(Finding(
            check_id="A2", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"{with_syn}/{len(cols)} columns have synonyms ({pct:.0f}%)",
            metric=round(pct, 1),
            threshold={"green": 50, "yellow": 25},
        ))
    return findings


def check_a3(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        guid = ctx.guid_for(model)
        instr = ctx.ai_instructions.get(guid, {})
        has_instructions = bool(
            instr.get("instructions")
            or (m.get("model_instructions", {}).get("data_model_instructions") or "").strip()
        )
        if not has_instructions:
            findings.append(Finding(
                check_id="A3", angle=_ANGLE, severity="HIGH",
                object_type="model", object_name=m.get("name", ""),
                object_guid=guid,
                detail="No AI/Spotter coaching instructions configured",
            ))
    return findings


def check_a4(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        desc = (m.get("description") or "").strip()
        if not desc:
            findings.append(Finding(
                check_id="A4", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail="Model has no description",
            ))
    return findings


def check_a5(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        total = len(cols) if cols else 1
        desc_pct = (sum(1 for c in cols if (c.get("description") or "").strip()) / total) * 100
        syn_pct = (sum(1 for c in cols if (c.get("synonyms") or [])) / total) * 100
        has_ai = bool(
            ctx.ai_instructions.get(ctx.guid_for(model), {}).get("instructions")
            or (m.get("model_instructions", {}).get("data_model_instructions") or "").strip()
        )
        has_desc = bool((m.get("description") or "").strip())
        anti = sum(1 for c in cols if _NAME_ANTI.match(c.get("name", "")))
        name_quality = ((total - anti) / total) * 100 if total else 100
        score = (
            desc_pct * 0.30
            + (100 if has_ai else 0) * 0.25
            + syn_pct * 0.15
            + (100 if has_desc else 0) * 0.15
            + name_quality * 0.15
        )
        if score >= 80:
            continue
        severity = "HIGH" if score < 50 else "MEDIUM"
        findings.append(Finding(
            check_id="A5", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"Spotter readiness score {score:.0f}/100 (Ready >= 80)",
            metric=round(score, 1),
            threshold={"ready": 80, "needs_work": 50},
        ))
    return findings


ALL_CHECKS = [check_a1, check_a2, check_a3, check_a4, check_a5]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_ai.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/checks_ai.py tools/ts-cli/tests/test_checks_ai.py
git commit -m "feat(audit): add AI readiness checks A1-A5"
```

---

### Task 4: Data Modeling Checks (D1–D12)

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/checks_data.py`
- Create: `tools/ts-cli/tests/test_checks_data.py`

**Interfaces:**
- Consumes: `Finding` from `ts_cli.audit.findings`. `AuditContext` and `make_context()` from `ts_cli.audit.context`. Same signatures as Task 3.
- Produces: `ALL_CHECKS: list[callable]` — 12 check functions (D1–D12).

- [ ] **Step 1: Write the test file**

```python
# tools/ts-cli/tests/test_checks_data.py
from ts_cli.audit.checks_data import (
    check_d1, check_d2, check_d3, check_d4, check_d5, check_d6,
    check_d7, check_d8, check_d9, check_d10, check_d11, check_d12,
    ALL_CHECKS,
)
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", model_tables=None, columns=None,
           formulas=None, properties=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "T1", "id": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
        },
    }


def _join(name="j1", with_table="T2", type="INNER", on="col1 = col2", cardinality=None):
    j = {"name": name, "with": with_table, "type": type, "on": on}
    if cardinality:
        j["cardinality"] = cardinality
    return j


def _col(name="Amount", column_type="MEASURE", table="T1", data_type="INT64",
         aggregation=None, is_hidden=False, index_type=None, db_column_name=None):
    c = {
        "name": name,
        "column_id": f"{table}::{name}",
        "properties": {"column_type": column_type},
    }
    if aggregation:
        c["properties"]["aggregation"] = aggregation
    if is_hidden:
        c["properties"]["is_hidden"] = True
    if index_type:
        c["properties"]["index_type"] = index_type
    if db_column_name:
        c["db_column_name"] = db_column_name
    c["db_column_properties"] = {"data_type": data_type}
    return c


# --- D1: Model complexity ---

def test_d1_flags_excess_tables():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(16)]
    ctx = make_context(models=[_model(model_tables=tables)])
    findings = check_d1(ctx)
    assert any(f.check_id == "D1" and f.severity == "HIGH" and "table" in f.detail.lower()
               for f in findings)


def test_d1_passes_small_model():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(5)]
    cols = [_col(f"C{i}") for i in range(10)]
    ctx = make_context(models=[_model(model_tables=tables, columns=cols)])
    findings = check_d1(ctx)
    assert not any("table" in f.detail.lower() for f in findings)


# --- D4: Progressive joins ---

def test_d4_flags_non_progressive():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(6)]
    ctx = make_context(models=[_model(model_tables=tables,
                                       properties={"join_progressive": False})])
    findings = check_d4(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_d4_passes_progressive():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(6)]
    ctx = make_context(models=[_model(model_tables=tables,
                                       properties={"join_progressive": True})])
    assert check_d4(ctx) == []


def test_d4_passes_small_model():
    tables = [{"name": f"T{i}", "id": f"T{i}"} for i in range(3)]
    ctx = make_context(models=[_model(model_tables=tables,
                                       properties={"join_progressive": False})])
    assert check_d4(ctx) == []


# --- D5: Orphan tables ---

def test_d5_flags_unjoined_table():
    tables = [
        {"name": "T1", "id": "T1", "joins": [_join(with_table="T2")]},
        {"name": "T2", "id": "T2"},
        {"name": "T3", "id": "T3"},
    ]
    ctx = make_context(models=[_model(model_tables=tables)])
    findings = check_d5(ctx)
    assert any(f.check_id == "D5" and "T3" in f.detail for f in findings)


def test_d5_passes_all_joined():
    tables = [
        {"name": "T1", "id": "T1", "joins": [_join(with_table="T2")]},
        {"name": "T2", "id": "T2"},
    ]
    ctx = make_context(models=[_model(model_tables=tables)])
    assert check_d5(ctx) == []


# --- D7: Model overlap ---

def test_d7_flags_identical_table_sets():
    m1 = _model(name="M1", guid="g1",
                model_tables=[{"name": "T1", "fqn": "db.s.T1"}, {"name": "T2", "fqn": "db.s.T2"}])
    m2 = _model(name="M2", guid="g2",
                model_tables=[{"name": "T1", "fqn": "db.s.T1"}, {"name": "T2", "fqn": "db.s.T2"}])
    ctx = make_context(models=[m1, m2])
    findings = check_d7(ctx)
    assert any(f.check_id == "D7" and f.severity == "HIGH" for f in findings)


def test_d7_passes_disjoint_models():
    m1 = _model(name="M1", guid="g1",
                model_tables=[{"name": "T1", "fqn": "db.s.T1"}])
    m2 = _model(name="M2", guid="g2",
                model_tables=[{"name": "T3", "fqn": "db.s.T3"}])
    ctx = make_context(models=[m1, m2])
    assert check_d7(ctx) == []


# --- D9: SQL pass-through ---

def test_d9_flags_high_sql_ratio():
    formulas = [
        {"name": f"F{i}", "expr": f"sql_int_aggregate_op(SUM(col{i}))"}
        for i in range(5)
    ] + [
        {"name": f"G{i}", "expr": f"sum([col{i}])"}
        for i in range(5)
    ]
    ctx = make_context(models=[_model(formulas=formulas)])
    findings = check_d9(ctx)
    assert any(f.check_id == "D9" for f in findings)


# --- ALL_CHECKS ---

def test_all_checks_has_twelve_entries():
    assert len(ALL_CHECKS) == 12
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_data.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write the checks module**

```python
# tools/ts-cli/ts_cli/audit/checks_data.py
from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "data_modeling"
_SQL_PASSTHROUGH = re.compile(r"sql_(int|string|bool)_aggregate_op", re.IGNORECASE)


def check_d1(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        name = m.get("name", "")
        guid = ctx.guid_for(model)
        mt = m.get("model_tables") or []
        cols = m.get("columns") or []
        formulas = m.get("formulas") or []
        joins_count = sum(len(t.get("joins") or []) for t in mt)
        max_depth = _join_depth(mt)
        for label, val, green, yellow in [
            ("tables", len(mt), 10, 15),
            ("columns", len(cols), 50, 75),
            ("joins", joins_count, 8, 12),
            ("join depth", max_depth, 3, 5),
            ("formulas", len(formulas), 30, 50),
        ]:
            if val <= green:
                continue
            severity = "HIGH" if val > yellow else "MEDIUM"
            findings.append(Finding(
                check_id="D1", angle=_ANGLE, severity=severity,
                object_type="model", object_name=name, object_guid=guid,
                detail=f"{val} {label} (>{yellow} HIGH, >{green} MEDIUM)",
                metric=val, threshold={"green": green, "yellow": yellow},
            ))
    return findings


def _join_depth(model_tables: list[dict]) -> int:
    graph: dict[str, list[str]] = {}
    for t in model_tables:
        tn = t.get("name", "")
        for j in (t.get("joins") or []):
            graph.setdefault(tn, []).append(j.get("with", ""))
    if not graph:
        return 0
    max_d = 0
    for start in graph:
        visited: set[str] = set()
        stack = [(start, 0)]
        while stack:
            node, depth = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            max_d = max(max_d, depth)
            for nb in graph.get(node, []):
                stack.append((nb, depth + 1))
    return max_d


def check_d2(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        name = m.get("name", "")
        guid = ctx.guid_for(model)
        col_types = {}
        for c in (m.get("columns") or []):
            cid = c.get("column_id", "")
            dt = (c.get("db_column_properties") or {}).get("data_type", "")
            col_types[cid] = dt
        for mt in (m.get("model_tables") or []):
            for j in (mt.get("joins") or []):
                on_str = j.get("on", "")
                parts = [p.strip() for p in on_str.replace("=", ",").split(",") if p.strip()]
                varchar_keys = [p for p in parts if col_types.get(p, "").upper() in ("VARCHAR", "CHAR", "STRING", "TEXT")]
                if varchar_keys:
                    findings.append(Finding(
                        check_id="D2", angle=_ANGLE, severity="HIGH",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=guid,
                        detail=f"VARCHAR join key(s): {', '.join(varchar_keys)} — 2-5x slower than integer",
                        metric=len(varchar_keys),
                    ))
                if len(parts) > 2:
                    findings.append(Finding(
                        check_id="D2", angle=_ANGLE, severity="MEDIUM",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=guid,
                        detail=f"Multi-column join ({len(parts)//2} keys) — consider a surrogate key",
                        metric=len(parts) // 2,
                    ))
    return findings


def check_d3(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        guid = ctx.guid_for(model)
        for mt in (m.get("model_tables") or []):
            for j in (mt.get("joins") or []):
                jtype = (j.get("type") or "").upper()
                if jtype == "OUTER":
                    findings.append(Finding(
                        check_id="D3", angle=_ANGLE, severity="HIGH",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=guid,
                        detail="FULL OUTER join causes performance issues",
                    ))
                elif jtype in ("LEFT_OUTER", "RIGHT_OUTER"):
                    findings.append(Finding(
                        check_id="D3", angle=_ANGLE, severity="INFO",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=guid,
                        detail=f"{jtype} join — may indicate data discrepancies",
                    ))
    return findings


def check_d4(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mt = m.get("model_tables") or []
        props = m.get("properties") or {}
        if len(mt) > 5 and not props.get("join_progressive", False):
            findings.append(Finding(
                check_id="D4", angle=_ANGLE, severity="HIGH",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"join_progressive is false on model with {len(mt)} tables (>5)",
                metric=len(mt), threshold={"min_tables_for_flag": 5},
            ))
    return findings


def check_d5(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mt = m.get("model_tables") or []
        if len(mt) <= 1:
            continue
        joined: set[str] = set()
        for t in mt:
            for j in (t.get("joins") or []):
                joined.add(t.get("name", ""))
                joined.add(j.get("with", ""))
        for t in mt:
            tname = t.get("name", "")
            if tname not in joined:
                findings.append(Finding(
                    check_id="D5", angle=_ANGLE, severity="HIGH",
                    object_type="table", object_name=tname,
                    object_guid=ctx.guid_for(model),
                    detail=f"Table '{tname}' has no joins — Cartesian product risk",
                ))
    return findings


def _table_role(columns: list[dict], table_name: str) -> str:
    table_cols = [c for c in columns
                  if (c.get("column_id") or "").split("::")[0] == table_name]
    if not table_cols:
        return "unknown"
    measures = sum(1 for c in table_cols
                   if (c.get("properties") or {}).get("column_type") == "MEASURE")
    return "fact" if measures > 3 else "dimension"


def check_d6(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        for mt in (m.get("model_tables") or []):
            tname = mt.get("name", "")
            table_cols = [c for c in cols
                          if (c.get("column_id") or "").split("::")[0] == tname]
            if not table_cols:
                continue
            attrs = sum(1 for c in table_cols
                        if (c.get("properties") or {}).get("column_type") == "ATTRIBUTE")
            role = _table_role(cols, tname)
            if role == "fact" and len(table_cols) > 0 and (attrs / len(table_cols)) > 0.4:
                findings.append(Finding(
                    check_id="D6", angle=_ANGLE, severity="LOW",
                    object_type="table", object_name=tname,
                    object_guid=ctx.guid_for(model),
                    detail=f"Fact table '{tname}' has {attrs}/{len(table_cols)} ATTRIBUTE columns (>40%)",
                    metric=round(attrs / len(table_cols) * 100, 1),
                    threshold={"max_attribute_pct": 40},
                ))
    return findings


def check_d7(ctx: AuditContext) -> list[Finding]:
    findings = []
    if len(ctx.models) < 2:
        return findings
    for m1, m2 in combinations(ctx.models, 2):
        s1 = {t.get("fqn", t.get("name", "")) for t in (m1.get("model", {}).get("model_tables") or [])}
        s2 = {t.get("fqn", t.get("name", "")) for t in (m2.get("model", {}).get("model_tables") or [])}
        if not s1 or not s2:
            continue
        inter = s1 & s2
        union = s1 | s2
        if not inter:
            continue
        jaccard = len(inter) / len(union)
        n1 = m1.get("model", {}).get("name", "")
        n2 = m2.get("model", {}).get("name", "")
        if s1 == s2:
            findings.append(Finding(
                check_id="D7", angle=_ANGLE, severity="HIGH",
                object_type="model", object_name=f"{n1} / {n2}",
                object_guid=ctx.guid_for(m1),
                detail=f"Identical table sets ({len(s1)} tables) — likely duplicate models",
                metric=round(jaccard, 2),
            ))
        elif jaccard > 0.5:
            findings.append(Finding(
                check_id="D7", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=f"{n1} / {n2}",
                object_guid=ctx.guid_for(m1),
                detail=f"High overlap: {len(inter)}/{len(union)} tables shared (Jaccard {jaccard:.2f})",
                metric=round(jaccard, 2), threshold={"high_overlap": 0.5},
            ))
    return findings


def check_d8(ctx: AuditContext) -> list[Finding]:
    findings = []
    table_keys: dict[tuple, list[str]] = defaultdict(list)
    for entry in ctx.metadata:
        header = entry.get("metadata_header") or entry
        sub = header.get("type", "")
        if sub in ("ONE_TO_ONE_LOGICAL", "SQL_VIEW"):
            ds = header.get("dataSourceName", "")
            db = header.get("databaseStripe", "")
            schema = header.get("schemaStripe", "")
            tbl = header.get("name", "")
            key = (ds, db, schema, tbl)
            table_keys[key].append(header.get("id", ""))
    for key, guids in table_keys.items():
        if len(guids) > 1:
            findings.append(Finding(
                check_id="D8", angle=_ANGLE, severity="HIGH",
                object_type="table", object_name=f"{key[0]}.{key[1]}.{key[2]}.{key[3]}",
                object_guid=guids[0],
                detail=f"{len(guids)} ThoughtSpot objects point to the same physical table",
                metric=len(guids),
            ))
    return findings


def check_d9(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        formulas = m.get("formulas") or []
        if not formulas:
            continue
        sql_count = sum(1 for f in formulas if _SQL_PASSTHROUGH.search(f.get("expr", "")))
        ratio = sql_count / len(formulas) * 100
        if ratio > 20:
            findings.append(Finding(
                check_id="D9", angle=_ANGLE, severity="LOW",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{sql_count}/{len(formulas)} formulas use sql_*_aggregate_op ({ratio:.0f}%)",
                metric=round(ratio, 1), threshold={"max_pct": 20},
            ))
    return findings


def check_d10(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        mt = m.get("model_tables") or []
        tables_with_cols: set[str] = set()
        for c in cols:
            cid = c.get("column_id", "")
            if "::" in cid:
                tables_with_cols.add(cid.split("::")[0])
        joined: set[str] = set()
        for t in mt:
            for j in (t.get("joins") or []):
                joined.add(t.get("name", ""))
                joined.add(j.get("with", ""))
        for t in mt:
            tname = t.get("name", "")
            if tname not in tables_with_cols:
                role = "bridge" if tname in joined else "leaf"
                severity = "INFO" if role == "bridge" else "MEDIUM"
                findings.append(Finding(
                    check_id="D10", angle=_ANGLE, severity=severity,
                    object_type="table", object_name=tname,
                    object_guid=ctx.guid_for(model),
                    detail=f"Zero-column {role} table '{tname}'",
                ))
    return findings


def check_d11(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        for mt in (m.get("model_tables") or []):
            for j in (mt.get("joins") or []):
                cardinality = (j.get("cardinality") or "").upper()
                if "ONE_TO_MANY" in cardinality or "MANY_TO_MANY" in cardinality:
                    tname = j.get("with", "")
                    from_table = mt.get("name", "")
                    from_role = _table_role(cols, from_table)
                    to_role = _table_role(cols, tname)
                    if from_role == "fact" and to_role == "fact":
                        findings.append(Finding(
                            check_id="D11", angle=_ANGLE, severity="MEDIUM",
                            object_type="join", object_name=j.get("name", ""),
                            object_guid=ctx.guid_for(model),
                            detail=f"Fan-out risk: fact-to-fact join '{from_table}' -> '{tname}' with {cardinality}",
                        ))
                    else:
                        findings.append(Finding(
                            check_id="D11", angle=_ANGLE, severity="INFO",
                            object_type="join", object_name=j.get("name", ""),
                            object_guid=ctx.guid_for(model),
                            detail=f"ONE_TO_MANY join '{from_table}' -> '{tname}'",
                        ))
    return findings


def check_d12(ctx: AuditContext) -> list[Finding]:
    findings = []
    if len(ctx.models) < 2:
        return findings
    col_types: dict[str, dict[str, str]] = defaultdict(dict)
    for model in ctx.models:
        m = model.get("model", {})
        mname = m.get("name", "")
        for c in (m.get("columns") or []):
            db_name = c.get("db_column_name") or c.get("name", "")
            ctype = (c.get("properties") or {}).get("column_type", "")
            if ctype:
                col_types[db_name][mname] = ctype
    for db_name, model_map in col_types.items():
        types = set(model_map.values())
        if len(types) > 1:
            models_str = ", ".join(f"{mn}={ct}" for mn, ct in model_map.items())
            findings.append(Finding(
                check_id="D12", angle=_ANGLE, severity="MEDIUM",
                object_type="column", object_name=db_name,
                object_guid="",
                detail=f"Column '{db_name}' classified differently across models: {models_str}",
            ))
    return findings


ALL_CHECKS = [
    check_d1, check_d2, check_d3, check_d4, check_d5, check_d6,
    check_d7, check_d8, check_d9, check_d10, check_d11, check_d12,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_data.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/checks_data.py tools/ts-cli/tests/test_checks_data.py
git commit -m "feat(audit): add data modeling checks D1-D12"
```

---

### Task 5: Human Readiness Checks (H1–H10)

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/checks_human.py`
- Create: `tools/ts-cli/tests/test_checks_human.py`

**Interfaces:**
- Consumes: `Finding` from `ts_cli.audit.findings`. `AuditContext` and `make_context()` from `ts_cli.audit.context`. `ctx.models`, `ctx.dependents`, `ctx.answers`, `ctx.metadata`, `ctx.guid_for(tml)`.
- Produces: `ALL_CHECKS: list[callable]` — 10 check functions (H1–H10).

- [ ] **Step 1: Write the test file**

```python
# tools/ts-cli/tests/test_checks_human.py
from ts_cli.audit.checks_human import (
    check_h1, check_h2, check_h3, check_h4, check_h5, check_h6,
    check_h7, check_h8, check_h9, check_h10, ALL_CHECKS,
)
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", columns=None, formulas=None, model_tables=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": {},
        },
    }


def _col(name="Amount", description="", is_hidden=False, column_id=None):
    c = {"name": name, "description": description, "properties": {}}
    if is_hidden:
        c["properties"]["is_hidden"] = True
    if column_id:
        c["column_id"] = column_id
    return c


# --- H1: Column name quality ---

def test_h1_flags_generic_names():
    cols = [
        _col("col1"), _col("field_2"), _col("val"),
        _col("Amount"), _col("Revenue"), _col("Date"),
        _col("Customer"), _col("Product"), _col("Region"), _col("Sales"),
    ]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_h1(ctx)
    assert any(f.check_id == "H1" for f in findings)


def test_h1_passes_good_names():
    cols = [_col("Amount"), _col("Revenue"), _col("Order Date")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_h1(ctx) == []


# --- H3: Unnecessary hidden columns ---

def test_h3_flags_hidden_not_referenced():
    cols = [
        _col("Amount", is_hidden=True, column_id="T1::Amount"),
        _col("Revenue", column_id="T1::Revenue"),
    ]
    ctx = make_context(models=[_model(columns=cols, formulas=[])])
    findings = check_h3(ctx)
    assert any(f.check_id == "H3" and "Amount" in f.detail for f in findings)


def test_h3_passes_hidden_referenced_by_formula():
    cols = [
        _col("Amount", is_hidden=True, column_id="T1::Amount"),
        _col("Revenue", column_id="T1::Revenue"),
    ]
    formulas = [{"name": "Total", "expr": "sum([Amount])"}]
    ctx = make_context(models=[_model(columns=cols, formulas=formulas)])
    assert check_h3(ctx) == []


# --- H4: Orphan models ---

def test_h4_flags_zero_dependents():
    ctx = make_context(
        models=[_model(guid="m-1")],
        dependents={},
    )
    findings = check_h4(ctx)
    assert any(f.check_id == "H4" for f in findings)


def test_h4_passes_with_dependents():
    ctx = make_context(
        models=[_model(guid="m-1")],
        dependents={"m-1": [{"guid": "a-1", "type": "ANSWER"}]},
    )
    assert check_h4(ctx) == []


# --- H10: Stale objects ---

def test_h10_flags_stale_column():
    cols = [_col("DO NOT USE Amount"), _col("Revenue")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_h10(ctx)
    assert any(f.check_id == "H10" for f in findings)


def test_h10_passes_clean_names():
    cols = [_col("Amount"), _col("Revenue")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_h10(ctx) == []


# --- ALL_CHECKS ---

def test_all_checks_has_ten_entries():
    assert len(ALL_CHECKS) == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_human.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write the checks module**

```python
# tools/ts-cli/ts_cli/audit/checks_human.py
from __future__ import annotations

import re
from collections import defaultdict

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "human"

_NAME_ANTI = re.compile(
    r"^col\d+$|^field[-_]?\d+$|^val\d*$|^tmp[-_]|^\d|^[A-Z_]+$",
    re.IGNORECASE,
)
_NAME_ANTI_UPPER_ONLY = re.compile(r"^[A-Z][A-Z0-9_]+$")

_STALE_NAME = re.compile(
    r"\bdo[-_ ]?not[-_ ]?use\b|\bDEPRECATED\b|\bOBSOLETE\b"
    r"|\btest[-_ ]?\d*\b|\btmp[-_ ]|\btemp[-_ ]"
    r"|^copy[-_ ]of[-_ ]|[-_ ]copy\d*$|[-_ ]\(\d+\)$"
    r"|\bzDEL\b|\bDELETE\b|\bTO[-_ ]?DELETE\b|\bREMOVE\b"
    r"|\bbackup\b|\barchive\b|\bbak\b|[-_ ]old$|^old[-_ ]",
    re.IGNORECASE,
)
_STALE_NAME_SAFE = re.compile(
    r"test_results|test_automation|test_coverage|test_environment|test_suite",
    re.IGNORECASE,
)
_STALE_DESC = re.compile(
    r"do not use|deprecated|obsolete|will be removed|scheduled for deletion"
    r"|temporary|for testing|test only|copied from|clone of"
    r"|to be deleted|to be removed|pending deletion|backup of|archived|old version",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(r"^(This is a|Column for|Field for|The |A )", re.IGNORECASE)


def check_h1(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        if not cols:
            continue
        anti = [c.get("name", "") for c in cols
                if _NAME_ANTI.match(c.get("name", "")) or _NAME_ANTI_UPPER_ONLY.match(c.get("name", ""))]
        pct = len(anti) / len(cols) * 100
        if pct > 10:
            findings.append(Finding(
                check_id="H1", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{len(anti)}/{len(cols)} columns have anti-pattern names ({pct:.0f}%): {', '.join(anti[:5])}",
                metric=round(pct, 1), threshold={"max_pct": 10},
            ))
    return findings


def check_h2(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        issues = []
        for c in cols:
            desc = (c.get("description") or "").strip()
            if not desc:
                continue
            name = c.get("name", "")
            if len(desc) < 20:
                issues.append(f"'{name}' too short ({len(desc)} chars)")
            elif len(desc) > 400:
                issues.append(f"'{name}' too long ({len(desc)} chars)")
            elif _BOILERPLATE.match(desc):
                issues.append(f"'{name}' uses boilerplate pattern")
        if issues:
            findings.append(Finding(
                check_id="H2", angle=_ANGLE, severity="LOW",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{len(issues)} description quality issues: {'; '.join(issues[:3])}",
                metric=len(issues),
            ))
    return findings


def check_h3(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        formulas = m.get("formulas") or []
        formula_exprs = " ".join(f.get("expr", "") for f in formulas)
        mt = m.get("model_tables") or []
        joined: set[str] = set()
        for t in mt:
            for j in (t.get("joins") or []):
                joined.add(t.get("name", ""))
                joined.add(j.get("with", ""))
        for c in cols:
            props = c.get("properties") or {}
            if not props.get("is_hidden"):
                continue
            cname = c.get("name", "")
            cid = c.get("column_id", "")
            table_name = cid.split("::")[0] if "::" in cid else ""
            if table_name in joined and not any(
                cc.get("column_id", "").startswith(f"{table_name}::")
                for cc in cols if cc is not c and not (cc.get("properties") or {}).get("is_hidden")
            ):
                continue
            if f"[{cname}]" in formula_exprs:
                continue
            if c.get("formula_id") and any(
                f"[{fn.get('name', '')}]" in formula_exprs
                for fn in formulas if fn.get("id") == c.get("formula_id")
            ):
                continue
            findings.append(Finding(
                check_id="H3", angle=_ANGLE, severity="MEDIUM",
                object_type="column", object_name=cname,
                object_guid=ctx.guid_for(model),
                detail=f"Hidden column '{cname}' not referenced by any formula",
            ))
    return findings


def check_h4(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        guid = ctx.guid_for(model)
        deps = ctx.dependents.get(guid, [])
        if not deps:
            findings.append(Finding(
                check_id="H4", angle=_ANGLE, severity="MEDIUM",
                object_type="model",
                object_name=model.get("model", {}).get("name", ""),
                object_guid=guid,
                detail="Orphan model — zero dependents (no answers, liveboards, or sets)",
            ))
    return findings


def check_h5(ctx: AuditContext) -> list[Finding]:
    findings = []
    for deps in ctx.dependents.values():
        for d in deps:
            if d.get("type") == "SET":
                set_guid = d.get("guid", "")
                set_deps = ctx.dependents.get(set_guid, [])
                if not set_deps:
                    findings.append(Finding(
                        check_id="H5", angle=_ANGLE, severity="MEDIUM",
                        object_type="table", object_name=d.get("name", ""),
                        object_guid=set_guid,
                        detail=f"Orphan set '{d.get('name', '')}' — zero consuming answers or liveboards",
                    ))
    return findings


def check_h6(ctx: AuditContext) -> list[Finding]:
    # Placeholder: duplicate set detection requires set TML with filter definitions.
    # Sets are exported as LOGICAL_TABLE subtype COHORT — would need dedicated export.
    # Deferred to a follow-up once set TML export is available in context.
    return []


def check_h7(ctx: AuditContext) -> list[Finding]:
    findings = []
    model_guids = set(ctx.model_guids)
    table_guids: set[str] = set()
    for t in ctx.tables.values():
        tg = t.get("guid", "")
        if tg:
            table_guids.add(tg)
    for answer in ctx.answers:
        a = answer.get("answer", {})
        aname = a.get("name", "")
        for tref in (a.get("tables") or []):
            fqn = tref.get("fqn", "")
            # If the answer references a table directly (not via a model)
            if fqn and not any(fqn in str(m) for m in ctx.models):
                findings.append(Finding(
                    check_id="H7", angle=_ANGLE, severity="MEDIUM",
                    object_type="answer", object_name=aname,
                    object_guid=answer.get("guid", ""),
                    detail=f"Answer connects directly to table '{fqn}', bypassing the model layer",
                ))
    return findings


def _normalize_expr(expr: str) -> str:
    return re.sub(r"\s+", " ", expr.strip().lower())


def check_h8(ctx: AuditContext) -> list[Finding]:
    findings = []
    if not ctx.answers:
        return findings
    model_formulas: set[str] = set()
    for model in ctx.models:
        for f in (model.get("model", {}).get("formulas") or []):
            model_formulas.add(_normalize_expr(f.get("expr", "")))
    answer_formulas: dict[str, list[str]] = defaultdict(list)
    for answer in ctx.answers:
        a = answer.get("answer", {})
        for f in (a.get("formulas") or []):
            expr = _normalize_expr(f.get("expr", ""))
            if expr and expr not in model_formulas:
                answer_formulas[expr].append(a.get("name", ""))
    for expr, answers in answer_formulas.items():
        if len(answers) >= 2:
            findings.append(Finding(
                check_id="H8", angle=_ANGLE, severity="HIGH",
                object_type="formula", object_name=f"shared in {len(answers)} answers",
                object_guid="",
                detail=f"Formula duplicated in {len(answers)} answers but not in model: {', '.join(answers[:3])}",
                metric=len(answers),
            ))
    return findings


def check_h9(ctx: AuditContext) -> list[Finding]:
    findings = []
    if not ctx.answers:
        return findings
    model_formulas: dict[str, str] = {}
    for model in ctx.models:
        for f in (model.get("model", {}).get("formulas") or []):
            model_formulas[_normalize_expr(f.get("expr", ""))] = f.get("name", "")
    for answer in ctx.answers:
        a = answer.get("answer", {})
        for f in (a.get("formulas") or []):
            expr = _normalize_expr(f.get("expr", ""))
            if expr in model_formulas:
                findings.append(Finding(
                    check_id="H9", angle=_ANGLE, severity="LOW",
                    object_type="formula", object_name=f.get("name", ""),
                    object_guid=answer.get("guid", ""),
                    detail=f"Answer formula '{f.get('name', '')}' duplicates model formula '{model_formulas[expr]}'",
                ))
    return findings


def check_h10(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mname = m.get("name", "")
        guid = ctx.guid_for(model)
        if _stale_match(mname):
            findings.append(Finding(
                check_id="H10", angle=_ANGLE, severity="LOW",
                object_type="model", object_name=mname, object_guid=guid,
                detail=f"Model name matches stale pattern: '{mname}'",
            ))
        for c in (m.get("columns") or []):
            cname = c.get("name", "")
            if _stale_match(cname):
                findings.append(Finding(
                    check_id="H10", angle=_ANGLE, severity="LOW",
                    object_type="column", object_name=cname, object_guid=guid,
                    detail=f"Column name matches stale pattern: '{cname}'",
                ))
            cdesc = c.get("description") or ""
            if cdesc and _STALE_DESC.search(cdesc):
                findings.append(Finding(
                    check_id="H10", angle=_ANGLE, severity="LOW",
                    object_type="column", object_name=cname, object_guid=guid,
                    detail=f"Column description matches stale pattern: '{cdesc[:60]}'",
                ))
    return findings


def _stale_match(name: str) -> bool:
    if _STALE_NAME_SAFE.search(name):
        return False
    return bool(_STALE_NAME.search(name))


ALL_CHECKS = [
    check_h1, check_h2, check_h3, check_h4, check_h5,
    check_h6, check_h7, check_h8, check_h9, check_h10,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_human.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/checks_human.py tools/ts-cli/tests/test_checks_human.py
git commit -m "feat(audit): add human readiness checks H1-H10"
```

---

### Task 6: Performance Checks (P1–P18)

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/checks_perf.py`
- Create: `tools/ts-cli/tests/test_checks_perf.py`

**Interfaces:**
- Consumes: `Finding` from `ts_cli.audit.findings`. `AuditContext` and `make_context()` from `ts_cli.audit.context`. `ctx.models`, `ctx.tables`, `ctx.metadata`, `ctx.guid_for(tml)`.
- Produces: `ALL_CHECKS: list[callable]` — 16 check functions (P1–P9, P11, P13–P18).

- [ ] **Step 1: Write the test file**

```python
# tools/ts-cli/tests/test_checks_perf.py
from ts_cli.audit.checks_perf import (
    check_p1, check_p2, check_p3, check_p4, check_p5, check_p6, check_p7,
    check_p8, check_p9, check_p11, check_p13, check_p14, check_p15,
    check_p16, check_p17, check_p18, ALL_CHECKS,
)
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", columns=None, formulas=None,
           model_tables=None, properties=None, filters=None, constraints=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": model_tables or [{"name": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
            "filters": filters or [],
            "constraints": constraints or [],
        },
    }


def _col(name="Amount", column_type="MEASURE", aggregation=None,
         index_type=None, column_id=None, data_type="INT64"):
    c = {
        "name": name,
        "column_id": column_id or f"T1::{name}",
        "properties": {"column_type": column_type},
        "db_column_properties": {"data_type": data_type},
    }
    if aggregation:
        c["properties"]["aggregation"] = aggregation
    if index_type:
        c["properties"]["index_type"] = index_type
    return c


def _table_tml(name="ORDERS", guid="t-1", rls_rules=None):
    t = {"guid": guid, "table": {"name": name, "columns": []}}
    if rls_rules:
        t["table"]["rls_rules"] = rls_rules
    return t


# --- P1: SQL View detection ---

def test_p1_flags_sql_view():
    ctx = make_context(metadata=[
        {"metadata_header": {"type": "SQL_VIEW", "name": "V1", "id": "v-1"}},
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": "T1", "id": "t-1"}},
    ])
    findings = check_p1(ctx)
    assert len(findings) == 1
    assert findings[0].check_id == "P1"


def test_p1_passes_no_views():
    ctx = make_context(metadata=[
        {"metadata_header": {"type": "ONE_TO_ONE_LOGICAL", "name": "T1", "id": "t-1"}},
    ])
    assert check_p1(ctx) == []


# --- P4: Apply-all-joins ---

def test_p4_flags_non_progressive():
    tables = [{"name": f"T{i}"} for i in range(6)]
    ctx = make_context(models=[_model(model_tables=tables,
                                       properties={"join_progressive": False})])
    findings = check_p4(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


# --- P8: Column sprawl ---

def test_p8_flags_excess_columns():
    cols = [_col(f"C{i}") for i in range(80)]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_p8(ctx)
    assert any(f.check_id == "P8" for f in findings)


def test_p8_passes_under_threshold():
    cols = [_col(f"C{i}") for i in range(50)]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_p8(ctx) == []


# --- P13: RLS rule density ---

def test_p13_flags_high_rls_count():
    rls = {"rules": [{"expr": f"[col{i}]"} for i in range(7)]}
    ctx = make_context(tables={"db.s.T1": _table_tml(rls_rules=rls)})
    findings = check_p13(ctx)
    assert any(f.check_id == "P13" and f.severity == "HIGH" for f in findings)


# --- P16: Formula nesting depth ---

def test_p16_flags_deep_nesting():
    formulas = [{"name": "F1", "expr": "if(if(if(if(if(if([x]>0,1,0)>0,1,0)>0,1,0)>0,1,0)>0,1,0)>0,1,0)"}]
    ctx = make_context(models=[_model(formulas=formulas)])
    findings = check_p16(ctx)
    assert any(f.check_id == "P16" for f in findings)


# --- P18: COUNT_DISTINCT ---

def test_p18_flags_count_distinct():
    cols = [_col("Users", aggregation="COUNT_DISTINCT")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_p18(ctx)
    assert any(f.check_id == "P18" for f in findings)


# --- ALL_CHECKS ---

def test_all_checks_has_sixteen_entries():
    assert len(ALL_CHECKS) == 16
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_perf.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write the checks module**

```python
# tools/ts-cli/ts_cli/audit/checks_perf.py
from __future__ import annotations

import re
from collections import defaultdict

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "performance"
_SQL_PASSTHROUGH = re.compile(r"sql_(int|string|bool)_aggregate_op", re.IGNORECASE)
_ID_PATTERN = re.compile(r"(_id|_guid|_uuid|transaction_id|row_id|surrogate_key)$", re.IGNORECASE)
_FUNC_IN_EXPR = re.compile(r"\b(UPPER|LOWER|TRIM|CAST|CONCAT|CONTAINS|IF)\s*\(", re.IGNORECASE)
_IF_PATTERN = re.compile(r"\bif\s*\(", re.IGNORECASE)
_BRACKET_REF = re.compile(r"\[([^\]]+)\]")


def check_p1(ctx: AuditContext) -> list[Finding]:
    findings = []
    for entry in ctx.metadata:
        header = entry.get("metadata_header") or entry
        if header.get("type") == "SQL_VIEW":
            findings.append(Finding(
                check_id="P1", angle=_ANGLE, severity="MEDIUM",
                object_type="table", object_name=header.get("name", ""),
                object_guid=header.get("id", ""),
                detail="SQL_VIEW data source blocks filter pushdown",
            ))
    return findings


def check_p2(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        formulas = m.get("formulas") or []
        cols = m.get("columns") or []
        agg_formula_ids = {c.get("formula_id") for c in cols
                          if (c.get("properties") or {}).get("aggregation")}
        scalar = [f for f in formulas if f.get("id") not in agg_formula_ids]
        count = len(scalar)
        if count > 10:
            severity = "HIGH"
        elif count > 5:
            severity = "MEDIUM"
        else:
            continue
        findings.append(Finding(
            check_id="P2", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"{count} scalar formulas (run at query time in TS engine)",
            metric=count, threshold={"green": 5, "yellow": 10},
        ))
    return findings


def check_p3(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        filters = m.get("filters") or []
        if not filters:
            continue
        non_prog = [f for f in filters if not (f.get("apply_on_tables") or [])]
        if non_prog:
            findings.append(Finding(
                check_id="P3", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{len(non_prog)}/{len(filters)} filters lack apply_on_tables (run on every query)",
                metric=len(non_prog),
            ))
    return findings


def check_p4(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mt = m.get("model_tables") or []
        props = m.get("properties") or {}
        if len(mt) > 5 and not props.get("join_progressive", False):
            findings.append(Finding(
                check_id="P4", angle=_ANGLE, severity="HIGH",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"join_progressive: false on {len(mt)}-table model — every query joins ALL tables",
                metric=len(mt),
            ))
    return findings


def check_p5(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        constraints = m.get("constraints") or []
        has_date_constraint = any(
            "date_range_condition" in str(c) for c in constraints
        )
        if has_date_constraint:
            continue
        fact_tables = set()
        for mt in (m.get("model_tables") or []):
            tname = mt.get("name", "")
            table_cols = [c for c in cols
                          if (c.get("column_id") or "").split("::")[0] == tname]
            measures = sum(1 for c in table_cols
                           if (c.get("properties") or {}).get("column_type") == "MEASURE")
            if measures > 3:
                fact_tables.add(tname)
        if fact_tables:
            findings.append(Finding(
                check_id="P5", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"No date constraints on model with fact tables: {', '.join(sorted(fact_tables)[:3])}",
                metric=len(fact_tables),
            ))
    return findings


def check_p6(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        col_types = {}
        for c in (m.get("columns") or []):
            cid = c.get("column_id", "")
            dt = (c.get("db_column_properties") or {}).get("data_type", "")
            col_types[cid] = dt
        for mt in (m.get("model_tables") or []):
            for j in (mt.get("joins") or []):
                on_str = j.get("on", "")
                parts = [p.strip() for p in on_str.replace("=", ",").split(",") if p.strip()]
                varchar_keys = [p for p in parts if col_types.get(p, "").upper() in ("VARCHAR", "CHAR", "STRING", "TEXT")]
                if varchar_keys:
                    findings.append(Finding(
                        check_id="P6", angle=_ANGLE, severity="HIGH",
                        object_type="join", object_name=j.get("name", ""),
                        object_guid=ctx.guid_for(model),
                        detail=f"VARCHAR join key(s) — 2-5x slower than integer: {', '.join(varchar_keys)}",
                        metric=len(varchar_keys),
                    ))
    return findings


def check_p7(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        mt = m.get("model_tables") or []
        graph: dict[str, list[str]] = {}
        for t in mt:
            tn = t.get("name", "")
            for j in (t.get("joins") or []):
                graph.setdefault(tn, []).append(j.get("with", ""))
        if not graph:
            continue
        max_depth = 0
        for start in graph:
            visited: set[str] = set()
            stack = [(start, 0)]
            while stack:
                node, depth = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                max_depth = max(max_depth, depth)
                for nb in graph.get(node, []):
                    stack.append((nb, depth + 1))
        if max_depth > 5:
            severity = "HIGH"
        elif max_depth > 3:
            severity = "MEDIUM"
        else:
            continue
        findings.append(Finding(
            check_id="P7", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"Join depth {max_depth} (>5 HIGH, >3 MEDIUM) — complex query plans",
            metric=max_depth, threshold={"green": 3, "yellow": 5},
        ))
    return findings


def check_p8(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        if len(cols) > 75:
            findings.append(Finding(
                check_id="P8", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{len(cols)} columns — wider GROUP BY, more complex query plans",
                metric=len(cols), threshold={"max": 75},
            ))
    return findings


def check_p9(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        for c in (m.get("columns") or []):
            props = c.get("properties") or {}
            ctype = props.get("column_type", "")
            idx = props.get("index_type", "")
            name = c.get("name", "")
            if ctype == "ATTRIBUTE" and idx and _ID_PATTERN.search(name):
                findings.append(Finding(
                    check_id="P9", angle=_ANGLE, severity="MEDIUM",
                    object_type="column", object_name=name,
                    object_guid=ctx.guid_for(model),
                    detail=f"High-cardinality ID column '{name}' indexed as ATTRIBUTE — wastes storage, pollutes suggestions",
                ))
    return findings


def check_p11(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        props = m.get("properties") or {}
        spotter = (props.get("spotter_config") or {}).get("is_spotter_enabled", False)
        if not spotter:
            continue
        indexed = sum(1 for c in (m.get("columns") or [])
                      if (c.get("properties") or {}).get("index_type"))
        if indexed > 30:
            findings.append(Finding(
                check_id="P11", angle=_ANGLE, severity="INFO",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"{indexed} indexed columns on Spotter-enabled model — each adds a DB lookup for suggestions",
                metric=indexed, threshold={"info": 30},
            ))
    return findings


def check_p13(ctx: AuditContext) -> list[Finding]:
    findings = []
    for fqn, table in ctx.tables.items():
        t = table.get("table", {})
        rls = t.get("rls_rules") or {}
        rules = rls.get("rules") or []
        count = len(rules)
        if count > 6:
            severity = "HIGH"
        elif count > 3:
            severity = "MEDIUM"
        else:
            continue
        findings.append(Finding(
            check_id="P13", angle=_ANGLE, severity=severity,
            object_type="table", object_name=t.get("name", ""),
            object_guid=table.get("guid", ""),
            detail=f"{count} RLS rules — cost compounds linearly per query",
            metric=count, threshold={"medium": 3, "high": 6},
        ))
    return findings


def check_p14(ctx: AuditContext) -> list[Finding]:
    findings = []
    for fqn, table in ctx.tables.items():
        t = table.get("table", {})
        rls = t.get("rls_rules") or {}
        for rule in (rls.get("rules") or []):
            expr = rule.get("expr", "")
            if _FUNC_IN_EXPR.search(expr):
                findings.append(Finding(
                    check_id="P14", angle=_ANGLE, severity="MEDIUM",
                    object_type="table", object_name=t.get("name", ""),
                    object_guid=table.get("guid", ""),
                    detail=f"RLS expression uses functions — prevents index/partition pruning: {expr[:80]}",
                ))
    return findings


def check_p15(ctx: AuditContext) -> list[Finding]:
    findings = []
    for fqn, table in ctx.tables.items():
        t = table.get("table", {})
        rls = t.get("rls_rules") or {}
        cols = t.get("columns") or []
        col_props = {}
        for c in cols:
            cn = c.get("name", "")
            dt = (c.get("db_column_properties") or {}).get("data_type", "")
            vc = (c.get("properties") or {}).get("value_casing", "")
            col_props[cn] = (dt, vc)
        for rule in (rls.get("rules") or []):
            expr = rule.get("expr", "")
            refs = _BRACKET_REF.findall(expr)
            for ref in refs:
                col_name = ref.split("::")[-1] if "::" in ref else ref
                dt, vc = col_props.get(col_name, ("", ""))
                if dt.upper() in ("VARCHAR", "CHAR", "STRING", "TEXT") and not vc:
                    findings.append(Finding(
                        check_id="P15", angle=_ANGLE, severity="MEDIUM",
                        object_type="column", object_name=col_name,
                        object_guid=table.get("guid", ""),
                        detail=f"VARCHAR RLS column '{col_name}' without value_casing — indexes cannot be used efficiently",
                    ))
    return findings


def check_p16(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        for f in (m.get("formulas") or []):
            expr = f.get("expr", "")
            depth = len(_IF_PATTERN.findall(expr))
            if depth > 5:
                severity = "LOW"
            elif depth > 3:
                severity = "INFO"
            else:
                continue
            findings.append(Finding(
                check_id="P16", angle=_ANGLE, severity=severity,
                object_type="formula", object_name=f.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"Formula has {depth} nested if() levels — branching overhead in calculation engine",
                metric=depth, threshold={"info": 3, "low": 5},
            ))
    return findings


def check_p17(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        formulas = m.get("formulas") or []
        formula_names = {f.get("name", "") for f in formulas}
        graph: dict[str, list[str]] = {}
        for f in formulas:
            fname = f.get("name", "")
            expr = f.get("expr", "")
            refs = _BRACKET_REF.findall(expr)
            cross_refs = [r for r in refs if r in formula_names and r != fname]
            if cross_refs:
                graph[fname] = cross_refs
        for start in graph:
            depth = _bfs_depth(graph, start)
            if depth > 3:
                severity = "LOW"
            elif depth > 2:
                severity = "INFO"
            else:
                continue
            findings.append(Finding(
                check_id="P17", angle=_ANGLE, severity=severity,
                object_type="formula", object_name=start,
                object_guid=ctx.guid_for(model),
                detail=f"Formula reference chain depth {depth} — each link adds a calculation layer",
                metric=depth, threshold={"info": 2, "low": 3},
            ))
    return findings


def _bfs_depth(graph: dict[str, list[str]], start: str) -> int:
    visited: set[str] = set()
    queue = [(start, 0)]
    max_d = 0
    while queue:
        node, d = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        max_d = max(max_d, d)
        for nb in graph.get(node, []):
            queue.append((nb, d + 1))
    return max_d


def check_p18(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        for c in (m.get("columns") or []):
            agg = (c.get("properties") or {}).get("aggregation", "")
            if agg == "COUNT_DISTINCT":
                findings.append(Finding(
                    check_id="P18", angle=_ANGLE, severity="INFO",
                    object_type="column", object_name=c.get("name", ""),
                    object_guid=ctx.guid_for(model),
                    detail=f"COUNT_DISTINCT aggregation on '{c.get('name', '')}' — most expensive aggregation",
                ))
    return findings


ALL_CHECKS = [
    check_p1, check_p2, check_p3, check_p4, check_p5, check_p6,
    check_p7, check_p8, check_p9, check_p11, check_p13, check_p14,
    check_p15, check_p16, check_p17, check_p18,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_perf.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/checks_perf.py tools/ts-cli/tests/test_checks_perf.py
git commit -m "feat(audit): add performance checks P1-P18"
```

---

### Task 7: Security Checks (S1–S10)

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/checks_security.py`
- Create: `tools/ts-cli/tests/test_checks_security.py`

**Interfaces:**
- Consumes: `Finding` from `ts_cli.audit.findings`. `AuditContext` and `make_context()` from `ts_cli.audit.context`. `ctx.models`, `ctx.tables`, `ctx.guid_for(tml)`.
- Produces: `ALL_CHECKS: list[callable]` — 8 check functions (S1–S5, S8–S10).

- [ ] **Step 1: Write the test file**

```python
# tools/ts-cli/tests/test_checks_security.py
from ts_cli.audit.checks_security import (
    check_s1, check_s2, check_s3, check_s4, check_s5,
    check_s8, check_s9, check_s10, ALL_CHECKS,
)
from ts_cli.audit.context import make_context


def _model(name="Sales", guid="m-1", columns=None, formulas=None, properties=None):
    return {
        "guid": guid,
        "model": {
            "name": name,
            "model_tables": [{"name": "T1"}],
            "columns": columns or [],
            "formulas": formulas or [],
            "properties": properties or {},
        },
    }


def _col(name="Amount", column_id=None, index_type=None):
    c = {
        "name": name,
        "column_id": column_id or f"T1::{name}",
        "properties": {},
        "db_column_properties": {"data_type": "VARCHAR"},
    }
    if index_type:
        c["properties"]["index_type"] = index_type
    return c


def _table_tml(name="ORDERS", guid="t-1", rls_rules=None):
    t = {"guid": guid, "table": {"name": name, "columns": []}}
    if rls_rules:
        t["table"]["rls_rules"] = rls_rules
    return t


# --- S1: PII detection ---

def test_s1_flags_email():
    cols = [_col("customer_email"), _col("Amount")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_s1(ctx)
    assert any(f.check_id == "S1" and "email" in f.detail.lower() for f in findings)


def test_s1_passes_non_pii():
    cols = [_col("Amount"), _col("Revenue")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_s1(ctx) == []


# --- S5: Credentials in analytics ---

def test_s5_flags_password_column():
    cols = [_col("password"), _col("Amount")]
    ctx = make_context(models=[_model(columns=cols)])
    findings = check_s5(ctx)
    assert any(f.check_id == "S5" and f.severity == "CRITICAL" for f in findings)


def test_s5_passes_no_credentials():
    cols = [_col("Amount"), _col("Revenue")]
    ctx = make_context(models=[_model(columns=cols)])
    assert check_s5(ctx) == []


# --- S4: RLS bypass + PII ---

def test_s4_flags_bypass_with_pii():
    cols = [_col("customer_email")]
    ctx = make_context(models=[_model(columns=cols, properties={"is_bypass_rls": True})])
    findings = check_s4(ctx)
    assert any(f.check_id == "S4" and f.severity == "HIGH" for f in findings)


# --- S10: RLS bypass as exception ---

def test_s10_flags_bypass():
    ctx = make_context(models=[_model(properties={"is_bypass_rls": True})])
    findings = check_s10(ctx)
    assert any(f.check_id == "S10" for f in findings)


def test_s10_passes_no_bypass():
    ctx = make_context(models=[_model(properties={})])
    assert check_s10(ctx) == []


# --- ALL_CHECKS ---

def test_all_checks_has_eight_entries():
    assert len(ALL_CHECKS) == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_security.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write the checks module**

```python
# tools/ts-cli/ts_cli/audit/checks_security.py
from __future__ import annotations

import re

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "security"

_PII_PATTERNS = [
    (re.compile(r"e[-_]?mail|email[-_]?addr", re.I), "email", "HIGH"),
    (re.compile(r"phone|mobile|cell[-_]?phone|fax|tel(?:ephone)?", re.I), "phone", "HIGH"),
    (re.compile(r"ssn|social[-_]?sec|national[-_]?id|tax[-_]?id|nin\b|sin\b", re.I), "national_id", "HIGH"),
    (re.compile(r"dob|birth[-_]?date|date[-_]?of[-_]?birth|birthday", re.I), "dob", "HIGH"),
    (re.compile(r"credit[-_]?card|card[-_]?num|account[-_]?num|iban|routing[-_]?num", re.I), "financial", "HIGH"),
    (re.compile(r"first[-_]?name|last[-_]?name|surname|full[-_]?name|given[-_]?name", re.I), "person_name", "MEDIUM"),
    (re.compile(r"street[-_]?addr|postal[-_]?code|zip[-_]?code", re.I), "address", "MEDIUM"),
]

_CREDENTIAL_PATTERNS = re.compile(
    r"\bpassword\b|\bpasswd\b|\bsecret[-_]?key\b|\bapi[-_]?key\b|\btoken\b",
    re.IGNORECASE,
)

_FUNC_IN_EXPR = re.compile(r"\b(UPPER|LOWER|TRIM|CAST|CONCAT|CONTAINS|IF)\s*\(", re.IGNORECASE)
_BRACKET_REF = re.compile(r"\[([^\]]+)\]")


def _find_pii_columns(columns: list[dict]) -> list[tuple[dict, str, str]]:
    results = []
    for c in columns:
        name = c.get("name", "")
        for pattern, category, confidence in _PII_PATTERNS:
            if pattern.search(name):
                results.append((c, category, confidence))
                break
    return results


def check_s1(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        pii = _find_pii_columns(m.get("columns") or [])
        for col, category, confidence in pii:
            findings.append(Finding(
                check_id="S1", angle=_ANGLE, severity="INFO",
                object_type="column", object_name=col.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"PII detected ({category}, {confidence} confidence): '{col.get('name', '')}'",
            ))
    return findings


def check_s2(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        pii = _find_pii_columns(m.get("columns") or [])
        table_has_rls: dict[str, bool] = {}
        for fqn, table in ctx.tables.items():
            t = table.get("table", {})
            rls = t.get("rls_rules") or {}
            table_has_rls[t.get("name", "")] = bool(rls.get("rules"))
        for col, category, _ in pii:
            idx = (col.get("properties") or {}).get("index_type", "")
            if not idx:
                continue
            cid = col.get("column_id", "")
            table_name = cid.split("::")[0] if "::" in cid else ""
            has_rls = table_has_rls.get(table_name, False)
            severity = "INFO" if has_rls else "HIGH"
            findings.append(Finding(
                check_id="S2", angle=_ANGLE, severity=severity,
                object_type="column", object_name=col.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"PII column '{col.get('name', '')}' is indexed"
                       f"{' (table has RLS)' if has_rls else ' WITHOUT table RLS — values visible in autocomplete'}",
            ))
    return findings


def check_s3(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        pii = _find_pii_columns(m.get("columns") or [])
        formula_exprs = " ".join(f.get("expr", "") for f in (m.get("formulas") or []))
        has_masking = "is_group_member" in formula_exprs.lower()
        for col, category, _ in pii:
            cname = col.get("name", "")
            if has_masking and cname.lower() in formula_exprs.lower():
                continue
            findings.append(Finding(
                check_id="S3", angle=_ANGLE, severity="HIGH",
                object_type="column", object_name=cname,
                object_guid=ctx.guid_for(model),
                detail=f"PII column '{cname}' ({category}) has no CLS or masking formula",
            ))
    return findings


def check_s4(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        props = m.get("properties") or {}
        if not props.get("is_bypass_rls"):
            continue
        pii = _find_pii_columns(m.get("columns") or [])
        if pii:
            findings.append(Finding(
                check_id="S4", angle=_ANGLE, severity="HIGH",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail=f"RLS bypass enabled AND model contains {len(pii)} PII column(s) — all users see all rows",
                metric=len(pii),
            ))
    return findings


def check_s5(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        for c in (m.get("columns") or []):
            if _CREDENTIAL_PATTERNS.search(c.get("name", "")):
                findings.append(Finding(
                    check_id="S5", angle=_ANGLE, severity="CRITICAL",
                    object_type="column", object_name=c.get("name", ""),
                    object_guid=ctx.guid_for(model),
                    detail=f"Credential column '{c.get('name', '')}' in analytics model — should never be exposed",
                ))
    return findings


def check_s8(ctx: AuditContext) -> list[Finding]:
    findings = []
    for fqn, table in ctx.tables.items():
        t = table.get("table", {})
        rls = t.get("rls_rules") or {}
        cols = t.get("columns") or []
        col_types = {c.get("name", ""): (c.get("db_column_properties") or {}).get("data_type", "")
                     for c in cols}
        for rule in (rls.get("rules") or []):
            expr = rule.get("expr", "")
            refs = _BRACKET_REF.findall(expr)
            for ref in refs:
                col_name = ref.split("::")[-1] if "::" in ref else ref
                dt = col_types.get(col_name, "")
                if dt.upper() in ("VARCHAR", "CHAR", "STRING", "TEXT"):
                    findings.append(Finding(
                        check_id="S8", angle=_ANGLE, severity="MEDIUM",
                        object_type="column", object_name=col_name,
                        object_guid=table.get("guid", ""),
                        detail=f"VARCHAR RLS column '{col_name}' — 2-5x slower than integer for filtering",
                    ))
    return findings


def check_s9(ctx: AuditContext) -> list[Finding]:
    findings = []
    for fqn, table in ctx.tables.items():
        t = table.get("table", {})
        rls = t.get("rls_rules") or {}
        for rule in (rls.get("rules") or []):
            expr = rule.get("expr", "")
            if _FUNC_IN_EXPR.search(expr):
                findings.append(Finding(
                    check_id="S9", angle=_ANGLE, severity="HIGH",
                    object_type="table", object_name=t.get("name", ""),
                    object_guid=table.get("guid", ""),
                    detail=f"Function in RLS expression prevents filter pushdown: {expr[:80]}",
                ))
    return findings


def check_s10(ctx: AuditContext) -> list[Finding]:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        props = m.get("properties") or {}
        if props.get("is_bypass_rls"):
            findings.append(Finding(
                check_id="S10", angle=_ANGLE, severity="MEDIUM",
                object_type="model", object_name=m.get("name", ""),
                object_guid=ctx.guid_for(model),
                detail="is_bypass_rls: true — all users see all rows regardless of RLS rules",
            ))
    return findings


ALL_CHECKS = [check_s1, check_s2, check_s3, check_s4, check_s5, check_s8, check_s9, check_s10]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/ts-cli && python -m pytest tests/test_checks_security.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/checks_security.py tools/ts-cli/tests/test_checks_security.py
git commit -m "feat(audit): add security checks S1-S10"
```

---

### Task 8: Runner, CLI Command, and Integration

**Files:**
- Modify: `tools/ts-cli/ts_cli/audit/__init__.py` (add `run_audit()`)
- Create: `tools/ts-cli/ts_cli/commands/audit.py`
- Modify: `tools/ts-cli/ts_cli/cli.py` (register audit command group)
- Modify: `tools/ts-cli/ts_cli/__init__.py` (version bump 0.21.0 → 0.22.0)
- Modify: `tools/ts-cli/pyproject.toml` (version bump 0.21.0 → 0.22.0)

**Interfaces:**
- Consumes: All prior tasks. `run_audit()` calls `build_context()` from Task 2, then dispatches to `ALL_CHECKS` from Tasks 3–7. `Finding.to_dict()` and `build_summary()` from Task 1.
- Produces: `ts audit run` CLI command. `run_audit(client, model_guids, angles) -> dict` returning the full JSON report structure.

- [ ] **Step 1: Write the runner in `audit/__init__.py`**

```python
# tools/ts-cli/ts_cli/audit/__init__.py
from __future__ import annotations

from typing import Optional

from ts_cli.audit import checks_ai, checks_data, checks_human, checks_perf, checks_security
from ts_cli.audit.context import AuditContext, build_context
from ts_cli.audit.findings import Finding, build_summary

ANGLE_MODULES = {
    "A": checks_ai,
    "D": checks_data,
    "H": checks_human,
    "P": checks_perf,
    "S": checks_security,
}


def run_audit(
    client,
    model_guids: list[str],
    angles: Optional[list[str]] = None,
) -> dict:
    angles = angles or list(ANGLE_MODULES.keys())
    ctx = build_context(client, model_guids, angles)
    findings: list[Finding] = []
    checks_run = 0
    for angle_key in angles:
        module = ANGLE_MODULES.get(angle_key)
        if not module:
            continue
        for check_fn in module.ALL_CHECKS:
            findings.extend(check_fn(ctx))
            checks_run += 1
    return {
        "findings": [f.to_dict() for f in findings],
        "summary": build_summary(findings, checks_run, len(ctx.models), len(ctx.tables)),
    }
```

- [ ] **Step 2: Write the CLI command**

```python
# tools/ts-cli/ts_cli/commands/audit.py
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

import typer

from ts_cli.client import ThoughtSpotClient, resolve_profile

app = typer.Typer(help="Audit ThoughtSpot models for best practices.")

_profile_option = typer.Option(None, "--profile", "-p", envvar="TS_PROFILE",
                               help="Profile name (default: first profile or TS_PROFILE env var)")


@app.command("run")
def run(
    models: List[str] = typer.Option(..., "--models", "-m",
                                     help="One or more model GUIDs to audit"),
    profile: Optional[str] = _profile_option,
    angles: Optional[str] = typer.Option(None, "--angles", "-a",
                                          help="Comma-separated angle filter: A,D,H,P,S (default: all)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                           help="Write JSON report to file instead of stdout"),
) -> None:
    """Run audit checks against one or more ThoughtSpot models.

    Exports TML, runs all checks as pure functions, and outputs a structured
    JSON report with findings and summary statistics.

    Examples:

    \b
      ts audit run --models abc-123
      ts audit run --models abc-123 --models def-456 --angles D,P
      ts audit run --models abc-123 --output report.json
    """
    from ts_cli.audit import run_audit

    angle_list = [a.strip().upper() for a in angles.split(",")] if angles else None
    client = ThoughtSpotClient(resolve_profile(profile))
    result = run_audit(client, models, angle_list)
    json_str = json.dumps(result, indent=2)

    if output:
        output.write_text(json_str)
        typer.echo(f"Report written to {output}", err=True)
    else:
        print(json_str)

    summary = result.get("summary", {})
    total = sum(summary.get("by_severity", {}).values())
    typer.echo(f"Audit complete: {total} finding(s) across "
               f"{summary.get('checks_run', 0)} checks", err=True)
```

- [ ] **Step 3: Register the command group in cli.py**

In `tools/ts-cli/ts_cli/cli.py`, add the import and registration:

Add to the import line:
```python
from ts_cli.commands import auth, connections, load, metadata, orgs, profiles, spotql, tables, tableau, tml, users, variables, audit
```

Add after the last `app.add_typer(...)` line:
```python
app.add_typer(audit.app, name="audit")
```

- [ ] **Step 4: Bump version to 0.22.0**

In `tools/ts-cli/ts_cli/__init__.py`:
```python
__version__ = "0.22.0"
```

In `tools/ts-cli/pyproject.toml`, change:
```
version = "0.22.0"
```

- [ ] **Step 5: Run the full test suite**

Run: `cd tools/ts-cli && python -m pytest tests/ -v`
Expected: All tests pass (existing + new)

Run: `python tools/validate/check_version_sync.py`
Expected: Version sync check passes

- [ ] **Step 6: Verify the CLI command is registered**

Run: `cd tools/ts-cli && python -m ts_cli.cli audit run --help`
Expected: Help text showing --models, --profile, --angles, --output flags

- [ ] **Step 7: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/__init__.py tools/ts-cli/ts_cli/commands/audit.py tools/ts-cli/ts_cli/cli.py tools/ts-cli/ts_cli/__init__.py tools/ts-cli/pyproject.toml
git commit -m "feat(audit): add ts audit run CLI command and runner

Wires the audit engine: run_audit() dispatches to angle modules,
CLI command handles --models/--angles/--output flags.
Version bump to 0.22.0."
```
