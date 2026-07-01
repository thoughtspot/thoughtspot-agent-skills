# ts-audit Unified HTML Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `ts audit report` CLI command that renders the JSON output from `ts audit run` into a single, self-contained, shareable HTML file with five interactive views — replacing the existing `efficiency_report.py`.

**Architecture:** Template-based rendering. `report_template.html` is a real HTML file with CSS, JS, and a `{{AUDIT_DATA}}` placeholder. `report.py` reads the audit JSON, compacts it (short keys, deduplicated lookups), injects it into the template, and writes the output HTML. All chart rendering (heatmap, Sankey, bar charts) happens client-side in JavaScript from the injected data. The `ts audit run` command is extended to include a `corpus` key with structural metadata (model stats, table reuse, overlaps, dependents, cluster URL).

**Tech Stack:** Python 3.9+ (Typer CLI), vanilla HTML/CSS/JS (no external deps), pytest

## Global Constraints

- Version bump: `0.22.0` → `0.23.0` in both `ts_cli/__init__.py` and `pyproject.toml`
- No external resources in HTML output — all CSS/JS inline, no CDN links, no web fonts
- System font stacks: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` (body), `ui-monospace, "SF Mono", Menlo, Consolas, monospace` (code)
- CSS custom properties must use the ERD mockup names: `--ground`, `--surface`, `--ink`, `--muted`, `--hair`, `--accent`, `--crit`, `--warn`, `--ok`, `--mono`, `--sans`
- Severity colours: CRITICAL `#C2382E`, HIGH `#f97316`, MEDIUM `#eab308`, LOW `#3b82f6`, INFO `#6B7480`, GREEN `#2E8B62`
- The `corpus` key in `ts audit run` output is optional for `ts audit report` — views that need it show a graceful fallback message
- Target: output HTML under 1MB for 100-model / 1000-finding audit
- ThoughtSpot deep-link patterns: Model/Table `{cluster_url}/#/data/tables/{guid}`, Answer `{cluster_url}/#/saved-answer/{guid}`, Liveboard `{cluster_url}/#/pinboard/{guid}`
- Object display: name as primary label, GUID as secondary muted text. No special disambiguation for name collisions — the always-visible GUID handles it
- Tests run from repo root: `pytest tools/ts-cli/tests/test_audit_report.py -v`
- The `artifact-design` skill must be loaded before writing any CSS for the template

---

### Task 1: Test fixtures + corpus building in `run_audit`

Extend `ts audit run` to emit a `corpus` key alongside `findings` and `summary`. Build a test fixture generator so all later tasks have realistic data.

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/test_fixtures.py`
- Modify: `tools/ts-cli/ts_cli/audit/__init__.py:18-37`
- Modify: `tools/ts-cli/ts_cli/audit/context.py:10-17`
- Create: `tools/ts-cli/tests/test_audit_corpus.py`

**Interfaces:**
- Consumes: `AuditContext` from `context.py`, `run_audit()` from `__init__.py`, `ThoughtSpotClient.base_url` property from `client.py:340`
- Produces:
  - `generate_test_data(model_count=5, findings_per_model=10, include_corpus=True, name_collisions=0, empty_angles=None, cluster_url="https://demo.thoughtspot.cloud") -> dict` — returns a dict with `findings`, `summary`, and `corpus` keys matching the schema in design spec §4.1
  - `build_corpus(ctx: AuditContext, client, profile_name: str, angles: list) -> dict` — returns the corpus dict
  - Updated `run_audit()` signature: `run_audit(client, model_guids, angles=None) -> dict` now includes `"corpus"` key

- [ ] **Step 1: Write the test for `generate_test_data`**

Create `tools/ts-cli/tests/test_audit_corpus.py`:

```python
from ts_cli.audit.test_fixtures import generate_test_data


def test_generate_test_data_default():
    data = generate_test_data()
    assert "findings" in data
    assert "summary" in data
    assert "corpus" in data
    corpus = data["corpus"]
    assert corpus["cluster_url"] == "https://demo.thoughtspot.cloud"
    assert len(corpus["models"]) == 5
    assert isinstance(corpus["table_reuse"], list)
    assert isinstance(corpus["model_overlaps"], list)
    assert isinstance(corpus["dependents"], dict)


def test_generate_test_data_name_collisions():
    data = generate_test_data(model_count=4, name_collisions=2)
    corpus = data["corpus"]
    names = [m["name"] for m in corpus["models"]]
    assert len(names) != len(set(names)), "Expected duplicate names"


def test_generate_test_data_no_corpus():
    data = generate_test_data(include_corpus=False)
    assert "corpus" not in data


def test_generate_test_data_empty_angles():
    data = generate_test_data(empty_angles=["S"])
    for f in data["findings"]:
        assert f["angle"] != "security"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_corpus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ts_cli.audit.test_fixtures'`

- [ ] **Step 3: Implement `test_fixtures.py`**

Create `tools/ts-cli/ts_cli/audit/test_fixtures.py`:

```python
"""Generate realistic audit JSON fixtures for testing and artifact previews."""
from __future__ import annotations

import hashlib
from typing import Optional

ANGLE_NAMES = {"A": "ai", "D": "data_modeling", "H": "human", "P": "performance", "S": "security"}
ALL_ANGLES = list(ANGLE_NAMES.keys())
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

CHECK_CATALOG = [
    ("A1", "ai", "Description coverage below threshold"),
    ("A2", "ai", "Synonym coverage below threshold"),
    ("A3", "ai", "No AI instructions configured"),
    ("D1", "data_modeling", "Model complexity exceeds threshold"),
    ("D2", "data_modeling", "Chasm trap detected in join path"),
    ("D7", "data_modeling", "High model overlap detected"),
    ("D8", "data_modeling", "Duplicate table objects found"),
    ("H3", "human", "Unnecessary hidden columns"),
    ("H4", "human", "Orphan model with no dependents"),
    ("H7", "human", "Answer queries table directly"),
    ("H8", "human", "Formula promotion candidate"),
    ("P1", "performance", "SQL View used as model source"),
    ("P5", "performance", "Non-progressive join detected"),
    ("P16", "performance", "Deeply nested if() calls"),
    ("S1", "security", "PII column without RLS"),
    ("S3", "security", "Indexing enabled without RLS"),
]

MODEL_NAMES = [
    "Sales Model", "Revenue Model", "Customer Analytics", "Product Catalog",
    "Supply Chain", "HR Analytics", "Finance Model", "Marketing Insights",
    "Inventory Tracker", "Operations Dashboard",
]

TABLE_NAMES = [
    "DM_ORDERS", "DM_CUSTOMERS", "DM_PRODUCTS", "DM_LINE_ITEMS",
    "DM_EMPLOYEES", "DM_REGIONS", "DM_DATES", "DM_CHANNELS",
    "DM_SUPPLIERS", "DM_WAREHOUSES", "DM_RETURNS", "DM_PROMOTIONS",
]


def _guid(seed: str) -> str:
    return hashlib.md5(seed.encode()).hexdigest()[:8] + "-" + \
           hashlib.md5((seed + "x").encode()).hexdigest()[:4] + "-" + \
           hashlib.md5((seed + "y").encode()).hexdigest()[:4] + "-" + \
           hashlib.md5((seed + "z").encode()).hexdigest()[:4] + "-" + \
           hashlib.md5((seed + "w").encode()).hexdigest()[:12]


def generate_test_data(
    model_count: int = 5,
    findings_per_model: int = 10,
    include_corpus: bool = True,
    name_collisions: int = 0,
    empty_angles: Optional[list] = None,
    cluster_url: str = "https://demo.thoughtspot.cloud",
) -> dict:
    empty_angles = empty_angles or []
    active_checks = [
        c for c in CHECK_CATALOG
        if c[0][0] not in empty_angles
    ]

    models_meta = []
    model_names_used = []
    for i in range(model_count):
        if i < name_collisions and i > 0:
            name = model_names_used[0]
        else:
            name = MODEL_NAMES[i % len(MODEL_NAMES)]
        model_names_used.append(name)

        guid = _guid(f"model-{i}")
        table_count = 5 + (i * 3) % 15
        model_tables = []
        for t in range(table_count):
            tidx = (i * 7 + t) % len(TABLE_NAMES)
            tname = TABLE_NAMES[tidx]
            model_tables.append({
                "name": tname,
                "fqn": f"ANALYTICS.PUBLIC.{tname}",
            })

        models_meta.append({
            "guid": guid,
            "name": name,
            "table_count": table_count,
            "column_count": table_count * 8 + i * 5,
            "formula_count": 3 + i * 2,
            "join_count": max(0, table_count - 1),
            "join_depth": min(table_count, 4 + i % 3),
            "model_tables": model_tables,
        })

    findings = []
    for i, m in enumerate(models_meta):
        count = findings_per_model
        if i == model_count - 1:
            count = max(1, findings_per_model // 3)
        for j in range(count):
            check = active_checks[j % len(active_checks)]
            sev_idx = j % len(SEVERITIES)
            if j == 0 and i == 0:
                sev_idx = 0
            findings.append({
                "check_id": check[0],
                "angle": check[1],
                "severity": SEVERITIES[sev_idx],
                "object_type": "model",
                "object_name": m["name"],
                "object_guid": m["guid"],
                "detail": f"{check[2]} — {m['name']}",
                "metric": round(20 + j * 5.5, 1),
                "threshold": {"green": 80, "yellow": 50} if "coverage" in check[2].lower() else None,
            })

    by_severity = {s: 0 for s in SEVERITIES}
    by_angle = {a: 0 for a in ANGLE_NAMES.values()}
    for f in findings:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
        by_angle[f["angle"]] = by_angle.get(f["angle"], 0) + 1

    result = {
        "findings": findings,
        "summary": {
            "by_severity": by_severity,
            "by_angle": by_angle,
            "objects_scanned": {"models": model_count, "tables": sum(m["table_count"] for m in models_meta)},
            "checks_run": len(active_checks),
        },
    }

    if include_corpus:
        table_reuse = _build_table_reuse(models_meta)
        model_overlaps = _build_model_overlaps(models_meta)
        dependents = _build_dependents(models_meta)

        result["corpus"] = {
            "cluster_url": cluster_url,
            "profile_name": "demo",
            "audit_date": "2026-07-01",
            "angles_run": [a for a in ALL_ANGLES if a not in empty_angles],
            "models": models_meta,
            "table_reuse": table_reuse,
            "model_overlaps": model_overlaps,
            "dependents": dependents,
        }

    return result


def _build_table_reuse(models: list[dict]) -> list[dict]:
    fqn_to_models = {}
    for m in models:
        for mt in m["model_tables"]:
            fqn = mt["fqn"]
            fqn_to_models.setdefault(fqn, []).append({"name": m["name"], "guid": m["guid"]})
    return [
        {"fqn": fqn, "name": fqn.rsplit(".", 1)[-1], "models": mlist}
        for fqn, mlist in fqn_to_models.items()
        if len(mlist) > 1
    ]


def _build_model_overlaps(models: list[dict]) -> list[dict]:
    overlaps = []
    for i, a in enumerate(models):
        a_fqns = {mt["fqn"] for mt in a["model_tables"]}
        for b in models[i + 1:]:
            b_fqns = {mt["fqn"] for mt in b["model_tables"]}
            shared = a_fqns & b_fqns
            if len(shared) < 2:
                continue
            union = a_fqns | b_fqns
            jaccard = len(shared) / len(union) if union else 0
            if jaccard >= 0.5:
                otype = "identical" if jaccard == 1.0 else (
                    "subset" if shared == a_fqns or shared == b_fqns else "high_overlap"
                )
            else:
                otype = "conformed_reuse"
            overlaps.append({
                "model_a": {"name": a["name"], "guid": a["guid"]},
                "model_b": {"name": b["name"], "guid": b["guid"]},
                "jaccard": round(jaccard, 3),
                "shared_table_count": len(shared),
                "total_tables_a": len(a_fqns),
                "total_tables_b": len(b_fqns),
                "shared_tables": sorted(fqn.rsplit(".", 1)[-1] for fqn in shared),
                "type": otype,
            })
    return overlaps


def _build_dependents(models: list[dict]) -> dict:
    dep_types = ["ANSWER", "LIVEBOARD", "ANSWER", "LIVEBOARD", "ANSWER"]
    dep_names = ["Q1 Dashboard", "Sales Summary", "Weekly Report", "KPI Board", "Trend Analysis"]
    result = {}
    for i, m in enumerate(models):
        deps = []
        for j in range(2 + i % 3):
            dtype = dep_types[j % len(dep_types)]
            dname = dep_names[(i + j) % len(dep_names)]
            deps.append({
                "name": dname,
                "guid": _guid(f"dep-{m['guid']}-{j}"),
                "type": dtype,
            })
        result[m["guid"]] = deps
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_corpus.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Write test for `build_corpus`**

Add to `tools/ts-cli/tests/test_audit_corpus.py`:

```python
from ts_cli.audit import build_corpus
from ts_cli.audit.context import make_context


def test_build_corpus_basic():
    models = [
        {
            "guid": "m-1",
            "model": {
                "name": "Test Model",
                "model_tables": [
                    {"name": "T1", "fqn": "DB.SCH.T1"},
                    {"name": "T2", "fqn": "DB.SCH.T2"},
                ],
                "joins": [{"name": "j1"}],
                "columns": [{"name": "c1"}, {"name": "c2"}],
                "formulas": [{"name": "f1"}],
            },
        }
    ]
    ctx = make_context(
        models=models,
        tables={"DB.SCH.T1": {"guid": "t-1"}, "DB.SCH.T2": {"guid": "t-2"}},
        dependents={"m-1": [{"guid": "a-1", "name": "My Answer", "type": "ANSWER"}]},
        model_guids=["m-1"],
    )
    corpus = build_corpus(ctx, cluster_url="https://test.thoughtspot.cloud",
                          profile_name="test", angles=["A", "D"])
    assert corpus["cluster_url"] == "https://test.thoughtspot.cloud"
    assert corpus["profile_name"] == "test"
    assert len(corpus["models"]) == 1
    m = corpus["models"][0]
    assert m["guid"] == "m-1"
    assert m["name"] == "Test Model"
    assert m["table_count"] == 2
    assert m["join_count"] == 1
    assert m["column_count"] == 2
    assert m["formula_count"] == 1
    assert corpus["angles_run"] == ["A", "D"]
    assert "m-1" in corpus["dependents"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_corpus.py::test_build_corpus_basic -v`
Expected: FAIL — `ImportError: cannot import name 'build_corpus' from 'ts_cli.audit'`

- [ ] **Step 7: Implement `build_corpus` and wire into `run_audit`**

Add `build_corpus` to `tools/ts-cli/ts_cli/audit/__init__.py`:

```python
from __future__ import annotations

from typing import Optional

from ts_cli.audit import checks_ai, checks_data, checks_human, checks_perf, checks_security
from ts_cli.audit.context import build_context
from ts_cli.audit.findings import Finding, build_summary

ANGLE_MODULES = {
    "A": checks_ai,
    "D": checks_data,
    "H": checks_human,
    "P": checks_perf,
    "S": checks_security,
}


def build_corpus(ctx, cluster_url: str = "", profile_name: str = "",
                 angles: Optional[list] = None) -> dict:
    angles = angles or list(ANGLE_MODULES.keys())
    models_out = []
    for model in ctx.models:
        m = model.get("model", {})
        guid = model.get("guid", m.get("guid", ""))
        model_tables = m.get("model_tables") or []
        models_out.append({
            "guid": guid,
            "name": m.get("name", ""),
            "table_count": len(model_tables),
            "column_count": len(m.get("columns") or []),
            "formula_count": len(m.get("formulas") or []),
            "join_count": len(m.get("joins") or []),
            "join_depth": _calc_join_depth(m),
            "model_tables": [
                {"name": mt.get("name", ""), "fqn": mt.get("fqn", "")}
                for mt in model_tables
            ],
        })

    table_reuse = _build_table_reuse_from_ctx(models_out)
    model_overlaps = _build_overlaps_from_ctx(models_out)

    return {
        "cluster_url": cluster_url,
        "profile_name": profile_name,
        "audit_date": "",
        "angles_run": list(angles),
        "models": models_out,
        "table_reuse": table_reuse,
        "model_overlaps": model_overlaps,
        "dependents": dict(ctx.dependents),
    }


def _calc_join_depth(model_data: dict) -> int:
    joins = model_data.get("joins") or []
    if not joins:
        return 0
    tables = {mt.get("name", "") for mt in (model_data.get("model_tables") or [])}
    graph = {}
    for j in joins:
        src = j.get("source", j.get("name", ""))
        dest = j.get("destination", j.get("with", ""))
        if src and dest:
            graph.setdefault(src, []).append(dest)
            graph.setdefault(dest, []).append(src)
    if not graph:
        return len(joins)
    max_depth = 0
    for start in tables:
        if start not in graph:
            continue
        visited = {start}
        queue = [(start, 0)]
        while queue:
            node, depth = queue.pop(0)
            max_depth = max(max_depth, depth)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
    return max_depth


def _build_table_reuse_from_ctx(models: list[dict]) -> list[dict]:
    fqn_to_models = {}
    for m in models:
        for mt in m["model_tables"]:
            fqn = mt["fqn"]
            if fqn:
                fqn_to_models.setdefault(fqn, []).append(
                    {"name": m["name"], "guid": m["guid"]}
                )
    return [
        {"fqn": fqn, "name": fqn.rsplit(".", 1)[-1] if "." in fqn else fqn,
         "models": mlist}
        for fqn, mlist in fqn_to_models.items()
        if len(mlist) > 1
    ]


def _build_overlaps_from_ctx(models: list[dict]) -> list[dict]:
    overlaps = []
    for i, a in enumerate(models):
        a_fqns = {mt["fqn"] for mt in a["model_tables"] if mt["fqn"]}
        for b in models[i + 1:]:
            b_fqns = {mt["fqn"] for mt in b["model_tables"] if mt["fqn"]}
            shared = a_fqns & b_fqns
            if len(shared) < 2:
                continue
            union = a_fqns | b_fqns
            jaccard = len(shared) / len(union) if union else 0
            if jaccard == 1.0:
                otype = "identical"
            elif shared == a_fqns or shared == b_fqns:
                otype = "subset"
            elif jaccard >= 0.5:
                otype = "high_overlap"
            else:
                otype = "conformed_reuse"
            overlaps.append({
                "model_a": {"name": a["name"], "guid": a["guid"]},
                "model_b": {"name": b["name"], "guid": b["guid"]},
                "jaccard": round(jaccard, 3),
                "shared_table_count": len(shared),
                "total_tables_a": len(a_fqns),
                "total_tables_b": len(b_fqns),
                "shared_tables": sorted(
                    fqn.rsplit(".", 1)[-1] if "." in fqn else fqn for fqn in shared
                ),
                "type": otype,
            })
    return overlaps


def run_audit(
    client,
    model_guids: list,
    angles: Optional[list] = None,
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

    corpus = build_corpus(
        ctx,
        cluster_url=client.base_url,
        profile_name=client._profile_name,
        angles=angles,
    )

    return {
        "findings": [f.to_dict() for f in findings],
        "summary": build_summary(findings, checks_run, len(ctx.models), len(ctx.tables)),
        "corpus": corpus,
    }
```

- [ ] **Step 8: Run all corpus tests**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_corpus.py -v`
Expected: All 5 tests PASS

- [ ] **Step 9: Run existing audit tests to confirm no regressions**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_*.py tools/ts-cli/tests/test_checks_*.py -v`
Expected: All existing tests PASS

- [ ] **Step 10: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/__init__.py tools/ts-cli/ts_cli/audit/test_fixtures.py tools/ts-cli/tests/test_audit_corpus.py
git commit -m "feat(audit): add corpus building + test fixture generator"
```

---

### Task 2: `report.py` — data compaction + template injection + CLI command

Build the Python renderer that compacts the audit JSON, injects it into the template, and writes the output HTML. Register the `report` subcommand under `ts audit`.

**Files:**
- Create: `tools/ts-cli/ts_cli/audit/report.py`
- Modify: `tools/ts-cli/ts_cli/commands/audit.py:1-45`
- Create: `tools/ts-cli/tests/test_audit_report.py`

**Interfaces:**
- Consumes: `generate_test_data()` from `ts_cli.audit.test_fixtures` (Task 1)
- Produces:
  - `compact_payload(data: dict) -> dict` — transforms verbose audit JSON to short-key payload with lookup arrays. Returns `{"L": [...], "F": [...], "S": {...}, "C": {...}}` where `L` = model lookup, `F` = findings, `S` = summary, `C` = corpus
  - `render_report(data: dict) -> str` — reads template, injects compacted payload, returns complete HTML string
  - `report` CLI command: `ts audit report <input> [--output/-o <path>]`

- [ ] **Step 1: Write structural tests for `compact_payload` and `render_report`**

Create `tools/ts-cli/tests/test_audit_report.py`:

```python
import json
import re

from ts_cli.audit.test_fixtures import generate_test_data
from ts_cli.audit.report import compact_payload, render_report


def test_compact_payload_has_required_keys():
    data = generate_test_data()
    payload = compact_payload(data)
    assert "L" in payload
    assert "F" in payload
    assert "S" in payload


def test_compact_payload_with_corpus():
    data = generate_test_data(include_corpus=True)
    payload = compact_payload(data)
    assert "C" in payload
    assert "u" in payload["C"]  # cluster_url
    assert "m" in payload["C"]  # models


def test_compact_payload_without_corpus():
    data = generate_test_data(include_corpus=False)
    payload = compact_payload(data)
    assert "C" not in payload or payload["C"] is None


def test_compact_payload_findings_use_short_keys():
    data = generate_test_data(model_count=2, findings_per_model=3)
    payload = compact_payload(data)
    first = payload["F"][0]
    assert "ci" in first  # check_id
    assert "s" in first   # severity
    assert "d" in first   # detail


def test_compact_payload_deduplicates_models():
    data = generate_test_data(model_count=3, findings_per_model=5)
    payload = compact_payload(data)
    for f in payload["F"]:
        assert isinstance(f["mi"], int)  # model index into L


def test_render_report_replaces_placeholder():
    data = generate_test_data(model_count=2, findings_per_model=3)
    html = render_report(data)
    assert "{{AUDIT_DATA}}" not in html


def test_render_report_no_external_resources():
    data = generate_test_data()
    html = render_report(data)
    external_refs = re.findall(
        r'(?:src|href)\s*=\s*["\']https?://(?!demo\.thoughtspot\.cloud)',
        html,
    )
    assert external_refs == [], f"Found external refs: {external_refs}"


def test_render_report_contains_valid_json_payload():
    data = generate_test_data()
    html = render_report(data)
    match = re.search(
        r'<script[^>]*id="audit-data"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "No <script id='audit-data'> found"
    parsed = json.loads(match.group(1))
    assert "F" in parsed


def test_render_report_size_under_1mb():
    data = generate_test_data(model_count=100, findings_per_model=10)
    html = render_report(data)
    size_bytes = len(html.encode("utf-8"))
    assert size_bytes < 1_048_576, f"Report is {size_bytes} bytes, exceeds 1MB"


def test_render_report_empty_findings():
    data = generate_test_data(model_count=1, findings_per_model=0)
    data["findings"] = []
    html = render_report(data)
    assert "{{AUDIT_DATA}}" not in html


def test_render_report_no_corpus_graceful():
    data = generate_test_data(include_corpus=False)
    html = render_report(data)
    assert "{{AUDIT_DATA}}" not in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ts_cli.audit.report'`

- [ ] **Step 3: Implement `report.py`**

Create `tools/ts-cli/ts_cli/audit/report.py`:

```python
"""Audit report renderer — compacts JSON, injects into HTML template."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


TEMPLATE_PATH = Path(__file__).parent / "report_template.html"


def compact_payload(data: dict) -> dict:
    findings = data.get("findings", [])
    summary = data.get("summary", {})
    corpus = data.get("corpus")

    model_lookup = []
    model_index = {}
    for f in findings:
        key = (f.get("object_name", ""), f.get("object_guid", ""))
        if key not in model_index:
            model_index[key] = len(model_lookup)
            model_lookup.append({"n": key[0], "g": key[1]})

    if corpus:
        for m in corpus.get("models", []):
            key = (m.get("name", ""), m.get("guid", ""))
            if key not in model_index:
                model_index[key] = len(model_lookup)
                model_lookup.append({"n": key[0], "g": key[1]})

    compact_findings = []
    for f in findings:
        key = (f.get("object_name", ""), f.get("object_guid", ""))
        cf = {
            "ci": f["check_id"],
            "a": f["angle"],
            "s": f["severity"],
            "ot": f.get("object_type", ""),
            "mi": model_index[key],
            "d": f["detail"],
        }
        if f.get("metric") is not None:
            cf["me"] = f["metric"]
        if f.get("threshold"):
            cf["th"] = f["threshold"]
        compact_findings.append(cf)

    compact_summary = {
        "bs": summary.get("by_severity", {}),
        "ba": summary.get("by_angle", {}),
        "os": summary.get("objects_scanned", {}),
        "cr": summary.get("checks_run", 0),
    }

    result = {
        "L": model_lookup,
        "F": compact_findings,
        "S": compact_summary,
    }

    if corpus:
        compact_models = []
        for m in corpus.get("models", []):
            key = (m.get("name", ""), m.get("guid", ""))
            cm = {
                "mi": model_index.get(key, -1),
                "tc": m.get("table_count", 0),
                "cc": m.get("column_count", 0),
                "fc": m.get("formula_count", 0),
                "jc": m.get("join_count", 0),
                "jd": m.get("join_depth", 0),
                "mt": [{"n": t["name"], "f": t["fqn"]} for t in m.get("model_tables", [])],
            }
            compact_models.append(cm)

        compact_reuse = [
            {"f": t["fqn"], "n": t["name"],
             "ms": [{"n": mm["name"], "g": mm["guid"]} for mm in t["models"]]}
            for t in corpus.get("table_reuse", [])
        ]

        compact_overlaps = [
            {
                "a": {"n": o["model_a"]["name"], "g": o["model_a"]["guid"]},
                "b": {"n": o["model_b"]["name"], "g": o["model_b"]["guid"]},
                "j": o["jaccard"],
                "sc": o["shared_table_count"],
                "ta": o.get("total_tables_a", 0),
                "tb": o.get("total_tables_b", 0),
                "st": o.get("shared_tables", []),
                "t": o["type"],
            }
            for o in corpus.get("model_overlaps", [])
        ]

        compact_deps = {}
        for guid, deps in corpus.get("dependents", {}).items():
            compact_deps[guid] = [
                {"n": d["name"], "g": d["guid"], "t": d["type"]}
                for d in deps
            ]

        result["C"] = {
            "u": corpus.get("cluster_url", ""),
            "p": corpus.get("profile_name", ""),
            "dt": corpus.get("audit_date", ""),
            "ar": corpus.get("angles_run", []),
            "m": compact_models,
            "tr": compact_reuse,
            "mo": compact_overlaps,
            "dp": compact_deps,
        }
    else:
        result["C"] = None

    return result


def render_report(data: dict) -> str:
    payload = compact_payload(data)
    json_str = json.dumps(payload, separators=(",", ":"))

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("{{AUDIT_DATA}}", json_str)
```

- [ ] **Step 4: Create a minimal template placeholder**

Create `tools/ts-cli/ts_cli/audit/report_template.html` with minimal content so the tests pass. This template will be fully built in Tasks 3-6.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ThoughtSpot Audit Report</title>
<style>
:root {
  --ground:#F6F7F9; --surface:#FFFFFF; --surface-2:#FBFCFD;
  --ink:#161B26; --muted:#6B7480; --hair:#E2E6EC; --hair-2:#EDF0F4;
  --accent:#1E6FA8; --accent-soft:#EAF2F8;
  --warn:#B5730A; --warn-soft:#FBF1DF;
  --crit:#C2382E; --crit-soft:#FBE9E7;
  --ok:#2E8B62; --ok-soft:#E6F3EC;
  --sev-critical:#C2382E; --sev-high:#f97316; --sev-medium:#eab308;
  --sev-low:#3b82f6; --sev-info:#6B7480; --sev-green:#2E8B62;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
}
body { margin:0; font-family:var(--sans); color:var(--ink); background:var(--ground); }
</style>
</head>
<body>
<div id="app"></div>
<script id="audit-data" type="application/json">{{AUDIT_DATA}}</script>
<script>
(function(){
  var raw = document.getElementById('audit-data').textContent;
  var D = JSON.parse(raw);
  var app = document.getElementById('app');
  app.textContent = 'Report loaded: ' + D.F.length + ' findings';
})();
</script>
</body>
</html>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_report.py -v`
Expected: All 11 tests PASS

- [ ] **Step 6: Wire the `report` CLI command**

Edit `tools/ts-cli/ts_cli/commands/audit.py` — add the `report` command after the existing `run` command:

```python
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
    """Run audit checks against one or more ThoughtSpot models."""
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


@app.command("report")
def report(
    input_file: Optional[Path] = typer.Argument(
        None, help="Path to audit JSON file (omit to read from stdin)"),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write HTML report to file instead of stdout"),
) -> None:
    """Render audit JSON as a self-contained HTML report."""
    from ts_cli.audit.report import render_report

    if input_file:
        if not input_file.exists():
            typer.echo(f"File not found: {input_file}", err=True)
            raise typer.Exit(1)
        raw = input_file.read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            typer.echo("No input file provided and stdin is a terminal. "
                       "Pipe audit JSON or pass a file path.", err=True)
            raise typer.Exit(1)
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        typer.echo(f"Invalid JSON: {e}", err=True)
        raise typer.Exit(1)

    if "findings" not in data or "summary" not in data:
        typer.echo("Input JSON must contain 'findings' and 'summary' keys.", err=True)
        raise typer.Exit(1)

    html = render_report(data)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html, encoding="utf-8")
        size_kb = len(html.encode("utf-8")) / 1024
        typer.echo(f"Report written to {output} ({size_kb:.0f} KB)", err=True)
    else:
        print(html)
```

- [ ] **Step 7: Write CLI test**

Add to `tools/ts-cli/tests/test_audit_report.py`:

```python
import subprocess
import tempfile
import os


def test_report_cli_from_file():
    data = generate_test_data(model_count=2, findings_per_model=3)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        f.flush()
        input_path = f.name
    try:
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as out:
            output_path = out.name
        result = subprocess.run(
            ["python", "-m", "ts_cli.cli", "audit", "report", input_path,
             "-o", output_path],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        html = Path(output_path).read_text()
        assert "{{AUDIT_DATA}}" not in html
        assert len(html) > 100
    finally:
        os.unlink(input_path)
        if os.path.exists(output_path):
            os.unlink(output_path)
```

- [ ] **Step 8: Run all report tests**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_report.py -v`
Expected: All 12 tests PASS

- [ ] **Step 9: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/report.py tools/ts-cli/ts_cli/audit/report_template.html tools/ts-cli/ts_cli/commands/audit.py tools/ts-cli/tests/test_audit_report.py
git commit -m "feat(audit): add report command — compacts JSON, injects into template"
```

---

### Task 3: HTML template — Dashboard view + navigation shell

Build the full report template with sidebar navigation, severity filter bar, breadcrumb bar, and the Dashboard view (header, severity cards, cluster heatmap, stats strip). Load the `artifact-design` skill before writing any CSS.

**Files:**
- Modify: `tools/ts-cli/ts_cli/audit/report_template.html` (complete rewrite of the placeholder from Task 2)

**Interfaces:**
- Consumes: compact payload structure from `compact_payload()` (Task 2) — specifically `D.L` (model lookup), `D.F` (findings), `D.S` (summary), `D.C` (corpus with `.u` cluster_url, `.m` models, `.ar` angles_run)
- Produces: complete HTML template with the Dashboard view functional. Other views render placeholder content ("View coming soon") to be filled in Tasks 4-6.

**Implementation notes for the subagent:**
- You MUST invoke the `artifact-design` skill before writing any CSS for this template. Follow the design plan it produces.
- The template is a single HTML file. All CSS goes in a `<style>` tag. All JS goes in `<script>` tags. No external resources.
- The `{{AUDIT_DATA}}` placeholder sits inside `<script id="audit-data" type="application/json">{{AUDIT_DATA}}</script>`. JavaScript reads it via `document.getElementById('audit-data').textContent` and calls `JSON.parse()`.
- CSS custom properties MUST use the names from Global Constraints (--ground, --surface, --ink, --muted, --hair, --accent, --crit, --warn, --ok, --sev-critical, --sev-high, --sev-medium, --sev-low, --sev-info, --sev-green, --mono, --sans).
- Responsive: sidebar collapses to hamburger below 768px. Heatmap gets `overflow-x: auto`. No body-level horizontal scroll.
- Hash routing: `#dashboard` is the default. Clicking changes the hash. `hashchange` event drives view switching.
- After building, use the Artifact tool to preview the template in a browser with test fixture data injected (generate via `generate_test_data()` from `ts_cli.audit.test_fixtures`, inject manually into the template for the preview). Verify: sidebar highlights, heatmap cells are colour-coded, severity cards show counts, breadcrumb updates.

- [ ] **Step 1: Load the artifact-design skill**

Before writing any CSS, invoke the `artifact-design` skill. Follow the design plan it produces — it will define the palette, typography, layout approach. The design constraints are:
- This is a UI/dashboard, not a document — information density, scan-and-operate, severity at a glance
- System font stacks only (no web fonts)
- CSS custom property names from the ERD mockup (see Global Constraints)
- Severity colours are semantic, separate from the accent palette
- Print stylesheet: hide sidebar, expand collapsed sections, black-and-white severity labels

- [ ] **Step 2: Build the complete HTML template**

Rewrite `tools/ts-cli/ts_cli/audit/report_template.html` with:

**HTML structure:**
```
<div id="app">
  <nav class="sidebar">          — persistent left nav
  <main class="main">
    <div class="topbar">         — breadcrumb + severity filter pills
    <div class="view" id="v-dashboard">      — Dashboard view
    <div class="view" id="v-scorecard">      — placeholder
    <div class="view" id="v-crossmodel">     — placeholder
    <div class="view" id="v-objectmap">      — placeholder
    <div class="view" id="v-cleanup">        — placeholder
  </main>
</div>
```

**Sidebar content:**
- "Dashboard" link (with CRITICAL+HIGH badge count)
- "Cross-Model" link
- "Object Map" link
- "Cleanup" link
- Divider
- "Models" section header
- Collapsible list of all models from `D.C.m` (or `D.L` if no corpus), each linking to `#model/{guid}`

**Dashboard view content:**
- Header bar: cluster URL as a link (from `D.C.u`), profile name (`D.C.p`), audit date (`D.C.dt`), angles run (`D.C.ar`)
- Severity summary cards row: one card per severity showing count from `D.S.bs`. Clickable → `#crossmodel?severity={sev}`
- Cluster heatmap: build from `D.F` by grouping findings by model (use `D.L[f.mi]` for name/guid) and angle. Each cell = worst severity for that model×angle. Sort models by worst severity descending. Cell click → `#model/{guid}/{angle}`. Model name click → `#model/{guid}`. Column header click → `#crossmodel?angle={a}`
- Stats strip: total models (`D.S.os.models`), total tables (`D.S.os.tables`), checks run (`D.S.cr`), total findings (`D.F.length`)

**JS core:**
- Parse payload from `#audit-data`
- Hash router: listen to `hashchange`, parse route, show/hide `.view` divs
- `navigate(hash)` — set `location.hash`, update sidebar active state, update breadcrumb
- Severity filter state: array of active severities, `toggleSeverity(sev)` function
- `buildDashboard(D)` — constructs the Dashboard DOM on first visit
- Deferred construction: each `buildXxx(D)` is called only once, on first navigation to that view

**Heatmap rendering (SVG or table):**
- Use an HTML `<table>` for the heatmap (simpler than SVG for a grid, accessible). Each `<td>` gets a `data-severity` attribute and a CSS background from `var(--sev-{severity})`. Cell text is empty (colour only) or a Unicode dot.

- [ ] **Step 3: Preview in browser with test data**

Use the Artifact tool to render the template with test fixture data injected. The preview file should:
1. Import `generate_test_data` from the test_fixtures module
2. Call `generate_test_data(model_count=8, findings_per_model=12)` to get realistic data
3. Run `compact_payload(data)` to get the compacted payload
4. Inject the JSON into the template by replacing `{{AUDIT_DATA}}`
5. Render via Artifact

Verify in the browser:
- Sidebar shows all 5 navigation items + 8 models
- Dashboard header shows cluster URL, profile, date
- 5 severity cards with correct counts
- Heatmap shows 8 rows × 5 columns with colour-coded cells
- Clicking a heatmap cell updates the hash to `#model/{guid}/{angle}`
- Clicking a sidebar item switches views (placeholders shown for non-Dashboard views)
- Severity filter pills toggle (visual feedback on click)
- Breadcrumb shows "Dashboard" on the landing page
- No horizontal body scroll

- [ ] **Step 4: Run the structural tests from Task 2**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_report.py -v`
Expected: All 12 tests still PASS (the template replacement and structural assertions)

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/report_template.html
git commit -m "feat(audit): dashboard view + navigation shell in report template"
```

---

### Task 4: HTML template — Model Scorecard view

Add the Model Scorecard view to the template. This is the per-model drill-down showing model stats, findings grouped by angle, recommendation mapping, dependents panel, and ERD placeholder hook.

**Files:**
- Modify: `tools/ts-cli/ts_cli/audit/report_template.html` (add JS function `buildScorecard` and its CSS)

**Interfaces:**
- Consumes: compact payload `D.L` (model lookup), `D.F` (findings), `D.C.m` (corpus models), `D.C.dp` (dependents). Navigation via hash `#model/{guid}` and `#model/{guid}/{angle}`
- Produces: `buildScorecard(D, guid, filterAngle)` JS function that renders the scorecard into `#v-scorecard`

**Implementation notes:**
- The scorecard is built fresh each time a model is navigated to (different model = different content). Clear `#v-scorecard` and rebuild.
- **Model header:** name (large, primary), GUID (small, muted, monospace), table/column/formula/join stats from corpus `D.C.m[i]`. ThoughtSpot link icon if `D.C.u` is set — URL pattern: `{D.C.u}/#/data/tables/{guid}`. ERD button with `data-erd-ready="false"`.
- **Angle sections:** for each angle in `D.C.ar` (or ["A","D","H","P","S"] if no corpus), filter `D.F` for this model's findings in this angle. Build a collapsible `<details>` element. Summary line: angle full name, worst severity badge, finding count. CRITICAL/HIGH sections `open` by default; MEDIUM/LOW/INFO closed.
- **Finding cards** inside each angle section: check ID badge, severity pill, detail text, metric bar if `.me` exists (width = metric% of threshold.green, capped at 100%), threshold display ("25% — threshold: 80%"), recommendation text.
- **Recommendation mapping** (hardcoded in JS):
  ```
  A1-A5 → "Run /ts-object-model-coach to improve descriptions, synonyms, AI context"
  D7    → "Run /ts-dependency-manager (Repoint mode) to consolidate overlapping models"
  D8    → "Run /ts-dependency-manager (Remove mode) to remove duplicate table objects"
  H3    → "Remove unnecessary hidden columns via TML reimport"
  H4    → "Run /ts-dependency-manager (Remove mode) if confirmed unused"
  H8    → "Run /ts-object-answer-promote to promote formula to model"
  S1-S5 → "Review security settings via ThoughtSpot UI or TML reimport"
  ```
  Default for unmatched check IDs: no recommendation shown.
- **Dependents panel:** collapsible `<details>` at the bottom. For each dependent in `D.C.dp[guid]`: name, type badge (ANSWER/LIVEBOARD), GUID (muted), TS deep-link. If no dependents, show "No downstream consumers found."
- **ERD placeholder:** `<div id="erd-{guid}" class="erd-container">` inside the scorecard. Button click shows: "ERD diagram — coming soon. Use /ts-object-model-erd for standalone ERD rendering." Styled with `--accent-soft` background.
- **Severity filter integration:** finding cards whose severity is toggled off in the global filter should be hidden via CSS class.
- If `filterAngle` is provided (from `#model/{guid}/{angle}` hash), only that angle section is expanded.
- Breadcrumb: "Dashboard > {model name}" or "Dashboard > {model name} > {angle}"

- [ ] **Step 1: Add `buildScorecard` function and CSS**

Add to the `<script>` section of `report_template.html`:
- `buildScorecard(D, guid, filterAngle)` — clears `#v-scorecard`, builds the full scorecard DOM, appends to the view container
- `ANGLE_FULL_NAMES` lookup: `{A:"AI Readiness", D:"Data Modeling", H:"Human Readiness", P:"Performance", S:"Security"}`
- `RECOMMENDATIONS` lookup: maps check ID prefixes to recommendation strings
- `tsLink(clusterUrl, guid, type)` helper — returns `<a>` tag or empty string
- `severityPill(sev)` helper — returns `<span class="sev-pill sev-{sev.toLowerCase()}">{sev}</span>`

Add CSS for:
- `.scorecard-header` — model name large, GUID muted, stats row
- `.angle-section` — `<details>` with severity-coloured left border
- `.finding-card` — card with check ID badge, severity pill, detail, metric bar
- `.metric-bar` — thin horizontal bar showing metric vs threshold
- `.dependents-panel` — collapsible bottom section
- `.erd-container` — placeholder with border-dashed and message
- `.erd-btn` — button styled with `--accent`

- [ ] **Step 2: Update hash router to handle `#model/{guid}` and `#model/{guid}/{angle}`**

In the existing hash router function, add cases:
- `#model/{guid}` → call `buildScorecard(D, guid, null)`, show `#v-scorecard`, update breadcrumb
- `#model/{guid}/{angle}` → call `buildScorecard(D, guid, angle)`, show `#v-scorecard`, update breadcrumb

Extract the guid and angle from the hash using string split:
```javascript
if (hash.startsWith('#model/')) {
  var parts = hash.substring(7).split('/');
  var guid = parts[0];
  var angle = parts[1] || null;
  buildScorecard(D, guid, angle);
  showView('scorecard');
  updateBreadcrumb([{label:'Dashboard',hash:'#dashboard'}, {label:modelName(D,guid),hash:'#model/'+guid}]);
}
```

- [ ] **Step 3: Preview in browser**

Use the Artifact tool to preview the template. Navigate to a model scorecard by clicking a model name in the sidebar or a heatmap cell. Verify:
- Model header shows name, GUID, stats
- ThoughtSpot link icon opens correct URL pattern
- Angle sections are collapsible, CRITICAL/HIGH expanded by default
- Finding cards show check ID, severity, detail, metric bar, recommendation
- ERD button shows placeholder message on click
- Dependents panel lists downstream objects with type badges
- Severity filter hides/shows finding cards
- Breadcrumb updates correctly
- Back button returns to Dashboard

- [ ] **Step 4: Run structural tests**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_report.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/report_template.html
git commit -m "feat(audit): model scorecard view with findings, recommendations, ERD hook"
```

---

### Task 5: HTML template — Cross-Model view

Add the Cross-Model view: a filterable, sortable table showing all findings across all models.

**Files:**
- Modify: `tools/ts-cli/ts_cli/audit/report_template.html` (add `buildCrossModel` JS function and CSS)

**Interfaces:**
- Consumes: `D.F` (findings), `D.L` (model lookup), `D.C.u` (cluster URL). Navigation via `#crossmodel`, optional query params `?severity={sev}` or `?angle={a}`
- Produces: `buildCrossModel(D, initialFilters)` JS function

- [ ] **Step 1: Implement `buildCrossModel`**

Add to the `<script>` section of `report_template.html`:

`buildCrossModel(D, initialFilters)`:
- Builds a `<table>` with columns: severity (pill), check ID, angle, model name (linked to `#model/{guid}`), object name, object type, detail
- Each `<tr>` gets `data-severity`, `data-angle`, `data-model` attributes for filtering
- Sort: clicking a `<th>` sorts the table rows. Toggle ascending/descending on repeated click. Use a `data-sort-dir` attribute on the `<th>`. Sort is alpha for text columns, severity-rank for severity column.
- Text filter: an `<input type="search">` above the table. Filters rows where model name, object name, or detail contains the search term (case-insensitive).
- Group-by toggle: a checkbox "Group by check ID". When checked, insert group header rows (`<tr class="group-header">`) before each check ID group showing the check ID and count. When unchecked, remove group headers.
- Severity filter: rows whose severity is toggled off in the global filter bar get `display:none`.
- `initialFilters`: if provided from the hash (`?severity=HIGH` or `?angle=D`), pre-filter the table.
- Model names are clickable → `#model/{guid}`. ThoughtSpot link icon beside model name if `D.C.u` is set.

CSS:
- `.crossmodel-table` — full-width, striped rows, header sticky
- `.crossmodel-filter` — search input + group-by toggle row
- `.sort-asc::after { content: " ▲" }` / `.sort-desc::after { content: " ▼" }`
- `.group-header` — bold, `--surface-2` background, spans all columns

- [ ] **Step 2: Update hash router**

Add `#crossmodel` route. Parse optional query parameters from the hash:
```javascript
if (hash.startsWith('#crossmodel')) {
  var params = parseHashParams(hash);  // {severity: "HIGH"} or {angle: "D"}
  buildCrossModel(D, params);
  showView('crossmodel');
  updateBreadcrumb([{label:'Dashboard',hash:'#dashboard'}, {label:'Cross-Model'}]);
}
```

Also update the Dashboard severity cards to navigate to `#crossmodel?severity=HIGH` on click, and heatmap column headers to `#crossmodel?angle=A`.

- [ ] **Step 3: Preview in browser**

Preview via Artifact. Verify:
- Table shows all findings with correct columns
- Click column header → rows sort. Click again → reverse sort
- Type in search box → rows filter in real time
- "Group by check ID" checkbox → group headers appear/disappear
- Click model name → navigates to scorecard
- Severity filter pills hide/show rows across the table
- Clicking a Dashboard severity card → Cross-Model filtered to that severity
- Clicking a heatmap column header → Cross-Model filtered to that angle
- No horizontal scroll on the body (table scrolls within its container on narrow viewports)

- [ ] **Step 4: Run structural tests**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_report.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/report_template.html
git commit -m "feat(audit): cross-model view with sort, filter, group-by"
```

---

### Task 6: HTML template — Object Map + Cleanup views

Add the final two views: Object Map (4 sub-tabs: Overlaps, Duplicates, Table Reuse with Sankey, Dependencies with bar charts) and Cleanup (orphans, stale objects, checkbox selection).

**Files:**
- Modify: `tools/ts-cli/ts_cli/audit/report_template.html` (add `buildObjectMap` and `buildCleanup` JS functions and CSS)

**Interfaces:**
- Consumes: `D.C` (corpus — `D.C.mo` overlaps, `D.C.tr` table reuse, `D.C.dp` dependents, `D.C.m` models), `D.F` (findings for H4, H5, H10 cleanup data), `D.C.u` (cluster URL)
- Produces:
  - `buildObjectMap(D, subTab)` — renders into `#v-objectmap`
  - `buildCleanup(D)` — renders into `#v-cleanup`

- [ ] **Step 1: Implement `buildObjectMap`**

Add to `<script>` section:

`buildObjectMap(D, subTab)`:
- Show a graceful fallback if `D.C` is null: "Run with the latest ts-cli to enable cross-model analysis."
- Sub-tab navigation: 4 buttons (Overlaps, Duplicates, Table Reuse, Dependencies). Active sub-tab highlighted. Hash updates to `#object-map/{sub-tab}`.
- **Overlaps sub-tab:** table with columns: Model A (name + guid), Model B (name + guid), Jaccard score (formatted as percentage), shared tables count, classification badge (identical/subset/high_overlap/conformed_reuse coloured). Each row has a `<details>` "Compare" that expands to show the list of shared table names. Data from `D.C.mo`.
- **Duplicates sub-tab:** group findings with check_id "D8" from `D.F`. For each group, show the physical FQN and the duplicate TS table objects. If no D8 findings, show "No duplicate table objects found."
- **Table Reuse sub-tab:** 
  - Sankey diagram (SVG): left column = physical table names, right column = model names. Lines connect tables to models they belong to. Line width proportional to 1 (all equal — it's presence, not volume). SVG built client-side from `D.C.tr` data.
  - Below the Sankey: sortable table with FQN, table name, model count, model names (each linked to `#model/{guid}`).
  - Sankey rendering: place left nodes evenly spaced vertically, right nodes evenly spaced, draw cubic bezier paths between connected pairs. Use `--accent` for path fill with low opacity. Label each node.
- **Dependencies sub-tab:**
  - Two horizontal bar charts (SVG):
    - Tables-per-model: one bar per model from `D.C.m`, width = `tc` (table count). Use `--accent` fill.
    - Models-per-table: one bar per shared table (from `D.C.tr` where models.length > 1), width = number of models. Use `--rls` fill (purple, per spec "purple").
  - Below each chart: sortable detail table. Model/table names link to TS.
  - Bar chart rendering: horizontal bars with labels on the left, value on the right. Scale bar width to the max value in the dataset. SVG viewBox scales to data.

CSS:
- `.object-map-tabs` — sub-tab button row
- `.sankey-container` — SVG container with `overflow-x: auto`
- `.bar-chart` — SVG container
- `.overlap-badge` — colour-coded classification pill
- Sub-tab content sections that show/hide

- [ ] **Step 2: Implement `buildCleanup`**

`buildCleanup(D)`:
- Show graceful fallback if no cleanup findings exist and `D.C` is null.
- **Orphan models (H4):** filter `D.F` for `check_id == "H4"`. Table with: checkbox, name (from `D.L[f.mi].n`), GUID (`D.L[f.mi].g`), TS link, detail. If zero, show "No orphan models found."
- **Orphan sets (H5):** filter `D.F` for `check_id == "H5"`. Same table format. If zero, show "No orphan sets found."
- **Stale objects (H10):** filter `D.F` for `check_id == "H10"`. Split into model-level and column-level by checking if detail contains "column" (case-insensitive). Table with: checkbox, pattern matched, object name, model, GUID. If zero, show "No stale objects found."
- **"Copy selected" button:** when clicked, collect all checked rows' name + GUID pairs, format as text, copy to clipboard via `navigator.clipboard.writeText()`. Show a brief "Copied!" toast.
- Checkboxes are client-side only, not persisted. A "Select all" / "Deselect all" toggle at the top of each section.

CSS:
- `.cleanup-section` — section with heading and table
- `.cleanup-table` — table with checkbox column
- `.copy-btn` — button styled with `--accent`
- `.toast` — brief notification that fades after 2s

- [ ] **Step 3: Update hash router**

Add routes:
- `#object-map` → `buildObjectMap(D, 'overlaps')` (default sub-tab)
- `#object-map/{sub-tab}` → `buildObjectMap(D, subTab)`
- `#cleanup` → `buildCleanup(D)`

- [ ] **Step 4: Add print stylesheet**

Add `@media print` CSS block:
```css
@media print {
  .sidebar { display: none; }
  .topbar .filter-bar { display: none; }
  details { display: block; }
  details[open] summary ~ * { display: block; }
  details:not([open]) > *:not(summary) { display: block !important; }
  .sev-pill { border: 1px solid #000; color: #000 !important; background: #fff !important; }
  .sev-pill::before { content: attr(data-severity) " "; }
  .main { margin-left: 0; }
}
```

- [ ] **Step 5: Preview in browser**

Preview via Artifact with `generate_test_data(model_count=8, findings_per_model=12)`. Verify:

**Object Map:**
- Overlaps sub-tab: model pairs shown with Jaccard %, classification badges, "Compare" expand shows shared tables
- Duplicates sub-tab: D8 findings grouped correctly (or "No duplicates" message)
- Table Reuse: Sankey diagram renders with correct connections, sortable table below
- Dependencies: two bar charts scale correctly, model/table names link to TS
- Sub-tab navigation works, hash updates

**Cleanup:**
- Orphan models section shows H4 findings (or empty message)
- Stale objects split into model-level and column-level
- Checkboxes toggle independently
- "Select all" toggles all checkboxes in its section
- "Copy selected" copies name+GUID to clipboard, shows toast
- Severity filter hides cleanup rows when their severity is toggled off

**Print:**
- Open browser print preview
- Sidebar is hidden
- Filter bar is hidden
- All `<details>` sections are expanded
- Severity pills use black text on white background

- [ ] **Step 6: Run all tests**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/test_audit_report.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add tools/ts-cli/ts_cli/audit/report_template.html
git commit -m "feat(audit): object map (Sankey, bar charts, overlaps) + cleanup views"
```

---

### Task 7: Version bump, SKILL.md update, delete superseded file, CHANGELOG

Final integration: bump version, update the ts-audit SKILL.md to include the `ts audit report` step, delete `efficiency_report.py`, update CHANGELOG.md and ts-cli CLAUDE.md.

**Files:**
- Modify: `tools/ts-cli/ts_cli/__init__.py:1` — `__version__ = "0.23.0"`
- Modify: `tools/ts-cli/pyproject.toml:4` — `version = "0.23.0"`
- Delete: `agents/cli/ts-audit/efficiency_report.py`
- Modify: `agents/cli/ts-audit/SKILL.md` — add Step 3b for report generation, update changelog
- Modify: `CHANGELOG.md` — add entry for `ts audit report` and version bump
- Modify: `tools/ts-cli/CLAUDE.md` — add `report.py` and `report_template.html` to architecture section, update version to 0.23.0

**Interfaces:**
- Consumes: all prior tasks (the report command and template are complete)
- Produces: shipped, versioned feature ready for PR

- [ ] **Step 1: Bump version**

Edit `tools/ts-cli/ts_cli/__init__.py`:
```python
__version__ = "0.23.0"
```

Edit `tools/ts-cli/pyproject.toml`:
```toml
version = "0.23.0"
```

- [ ] **Step 2: Run version sync check**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && python tools/validate/check_version_sync.py`
Expected: PASS

- [ ] **Step 3: Delete `efficiency_report.py`**

```bash
git rm agents/cli/ts-audit/efficiency_report.py
```

- [ ] **Step 4: Update SKILL.md**

Edit `agents/cli/ts-audit/SKILL.md`. After the existing Step 3 (Run Audit Engine), add Step 3b:

After the line `If \`--output\` is provided, the JSON is written to that file instead of stdout.` and before `**Error handling:**`, add nothing — the Step 3 content stays as-is.

After Step 3's closing `---`, add a new step:

```markdown
## Step 3b — Generate HTML Report

After Step 3 produces the JSON output, generate the unified HTML report:

```bash
ts audit report {json_file_or_stdin} --output ~/Dev/audit-runs/{profile}-{date}/report.html
```

Or piped directly from Step 3:

```bash
ts audit run \
  --models "{guid1}" --models "{guid2}" \
  --angles "{A,D,H,P,S}" \
  --profile "{profile_name}" \
  | ts audit report -o ~/Dev/audit-runs/{profile_name}-{date}/report.html
```

The report is a single self-contained HTML file with five interactive views:
- **Dashboard** — severity heatmap across all models and angles
- **Model Scorecard** — per-model findings with recommendations
- **Cross-Model** — sortable table of all findings
- **Object Map** — table reuse, model overlaps, dependencies (Sankey + bar charts)
- **Cleanup** — orphan models, stale objects with checkbox selection

Open the HTML file in the user's default browser after generation. The file is
self-contained (no external dependencies) and can be shared directly via email or Slack.

---
```

Update the Changelog table — add a new row at the top:

```markdown
| 2.1.0 | 2026-07-01 | Add `ts audit report` command: unified HTML report with Dashboard, Scorecard, Cross-Model, Object Map, Cleanup views. Delete superseded `efficiency_report.py`. |
```

- [ ] **Step 5: Update CHANGELOG.md**

Add a new date section at the top of `CHANGELOG.md` (or add to today's section if it exists):

```markdown
## 2026-07-01
- feat: add `ts audit report` command — unified HTML report
- chore: bump ts-cli to v0.23.0
- chore: delete superseded `efficiency_report.py`
```

- [ ] **Step 6: Update ts-cli CLAUDE.md**

Edit `tools/ts-cli/CLAUDE.md`. In the architecture section, add to the `audit/` block:

```
    report.py         — HTML report renderer (compact payload + template injection)
    report_template.html — Self-contained HTML template with CSS/JS
    test_fixtures.py  — Realistic test data generator
```

Update the version line: `Current version: **0.23.0**`

Add to the `commands/` block:
```
    audit.py      — ts audit run / report
```

- [ ] **Step 7: Run all tests + validators**

Run: `cd /Users/damianwaldron/Dev/thoughtspot-agent-skills && pytest tools/ts-cli/tests/ -v && python tools/validate/check_version_sync.py && python tools/validate/check_skill_versions.py --root .`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add tools/ts-cli/ts_cli/__init__.py tools/ts-cli/pyproject.toml agents/cli/ts-audit/SKILL.md CHANGELOG.md tools/ts-cli/CLAUDE.md
git rm agents/cli/ts-audit/efficiency_report.py
git commit -m "feat: ts audit report v0.23.0 — unified HTML report, delete efficiency_report.py"
```
