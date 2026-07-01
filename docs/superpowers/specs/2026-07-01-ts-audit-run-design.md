# `ts audit run` — Deterministic Audit Engine Design

**Date:** 2026-07-01
**Backlog:** BL-065
**Status:** Design approved, pending implementation plan

---

## Goal

Codify all 51 ts-audit checks (A1-A5, D1-D12, H1-H10, P1-P18, S1-S10) as
deterministic Python in a `ts audit run` CLI command. The command exports TML,
runs every check as a pure function, and outputs a structured JSON report. The
LLM's role shifts from re-deriving threshold logic to interpreting and
prioritising the findings.

## Architecture

Module-per-angle with a thin runner. Each angle gets its own focused module
(200-500 lines). A runner orchestrates data fetching, dispatches to angle
modules, and merges results.

```
ts audit run --profile prod --models <guid1> <guid2> --angles A,D,H,P,S
                                  |
                 +----------------+----------------+
                 v                v                v
         TML export          Metadata API      AI instructions
    (models + tables)     (dependents, search)   (A3 only)
                 |                |                |
                 +----------------+----------------+
                                  v
                          AuditContext object
                    (all data, shared across checks)
                                  |
            +--------+--------+--------+--------+
            v        v        v        v        v
        checks_ai checks_data checks_human checks_perf checks_security
            |        |        |        |        |
            +--------+--------+--------+--------+
                                  v
                          Merged findings[]
                                  |
                                  v
                          JSON to stdout
```

## File Layout

```
tools/ts-cli/ts_cli/
+-- audit/
|   +-- __init__.py          # run_audit() entry point (~150 lines)
|   +-- context.py           # AuditContext dataclass + data fetching (~200 lines)
|   +-- checks_ai.py         # A1-A5 (~150 lines)
|   +-- checks_data.py       # D1-D12 (~400 lines)
|   +-- checks_human.py      # H1-H10 (~350 lines)
|   +-- checks_perf.py       # P1-P18 (~350 lines)
|   +-- checks_security.py   # S1-S10 (~250 lines)
|   +-- findings.py          # Finding dataclass + severity enum + stats (~100 lines)
+-- commands/
|   +-- audit.py             # CLI: ts audit run (Typer wiring, ~80 lines)
```

Total: ~1600 lines across 8 files, no file exceeding 400 lines.

## CLI Interface

```
ts audit run --profile <name> --models <guid> [<guid> ...] [--angles A,D,H,P,S] [--output <path>]
```

| Flag | Required | Default | Description |
|---|---|---|---|
| `--profile` / `-p` | No | `TS_PROFILE` env var or first profile | ThoughtSpot profile for auth |
| `--models` / `-m` | Yes | -- | One or more model GUIDs to audit |
| `--angles` / `-a` | No | `A,D,H,P,S` (all) | Comma-separated angle filter |
| `--output` / `-o` | No | stdout | Write JSON to file instead of stdout |

- JSON report to stdout (or `--output` file)
- Diagnostics and progress to stderr
- `--models` takes GUIDs, not names (unambiguous; SKILL.md already has users discover GUIDs via `ts metadata search`)
- No `--tables` flag; tables are auto-discovered from each model's `model_tables[].fqn`

## Data Collection Strategy

The `AuditContext` builder in `context.py` fetches everything once before any
checks run. All HTTP calls use the existing `ThoughtSpotClient` from `client.py`.

| Step | API call | Purpose | Conditional |
|---|---|---|---|
| 1 | `metadata/tml/export` per model (with `--fqn --associated`) | Model + table TMLs | Always |
| 2 | `metadata/search` (type: `LOGICAL_TABLE`) | Object inventory for orphan detection, SQL_VIEW, cross-model comparison | Always |
| 3 | `metadata/search` with `dependent_object_version: V2` per GUID | Dependents for H4, H5, H7, H8, H9 | Always |
| 4 | `ai/instructions/get` per model GUID | AI instructions for A3 | Only if angle A requested |
| 5 | `metadata/tml/export` for dependent answers | Answer TMLs for H8, H9 formula promotion/redundancy | Only if angle H requested and dependents exist |

All data cached in memory (no disk I/O). Typical audit (1-5 models, 10-30
tables) is well under 50MB.

### AuditContext Dataclass

```python
@dataclass
class AuditContext:
    models: list[dict]                    # parsed model TMLs
    tables: dict[str, dict]               # table TMLs keyed by FQN
    dependents: dict[str, list]           # GUID -> dependent objects
    metadata: list[dict]                  # metadata search results (all objects in scope)
    ai_instructions: dict[str, dict]      # model GUID -> AI instructions
    answers: list[dict]                   # answer TMLs (for H8, H9)
    model_guids: list[str]               # input GUIDs (for cross-reference)

    def guid_for(self, tml: dict) -> str:
        """Extract GUID from a TML dict."""
        ...

    def tables_for_model(self, model: dict) -> list[dict]:
        """Return table TMLs referenced by a model's model_tables."""
        ...
```

## Finding Schema

Each check returns a list of `Finding` objects:

```python
@dataclass
class Finding:
    check_id: str           # "D1", "A3", "S5"
    angle: str              # "ai", "data_modeling", "human", "performance", "security"
    severity: str           # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO"
    object_type: str        # "model" | "table" | "column" | "formula" | "join"
    object_name: str        # human-readable name
    object_guid: str        # ThoughtSpot GUID
    detail: str             # what triggered the finding
    metric: float | int | None   # raw numeric value (None for boolean checks)
    threshold: dict | None  # {"green": N, "yellow": M} or None for boolean
```

## Output Format

Full JSON output to stdout:

```json
{
    "findings": [
        {
            "check_id": "D1",
            "angle": "data_modeling",
            "severity": "HIGH",
            "object_type": "model",
            "object_name": "Sales Model",
            "object_guid": "abc-123",
            "detail": "15 joins exceed threshold (max 12 for GREEN)",
            "metric": 15,
            "threshold": {"green": 12, "yellow": 8}
        }
    ],
    "summary": {
        "by_severity": {"CRITICAL": 0, "HIGH": 3, "MEDIUM": 7, "LOW": 2, "INFO": 5},
        "by_angle": {"ai": 2, "data": 4, "human": 5, "perf": 4, "security": 2},
        "objects_scanned": {"models": 3, "tables": 12},
        "checks_run": 49,
        "checks_skipped": 2
    }
}
```

## Check Implementation Pattern

Every check function follows the same contract:

```python
def check_d1(ctx: AuditContext) -> list[Finding]:
    """Model complexity -- tables, columns, joins, formulas, join depth."""
    findings = []
    for model in ctx.models:
        tables = model["model"]["model_tables"]
        table_count = len(tables)
        severity = (
            "HIGH" if table_count > 15
            else "MEDIUM" if table_count > 10
            else None
        )
        if severity:
            findings.append(Finding(
                check_id="D1",
                angle="data_modeling",
                severity=severity,
                object_type="model",
                object_name=model["model"]["name"],
                object_guid=ctx.guid_for(model),
                detail=f"{table_count} tables (threshold: >15 HIGH, >10 MEDIUM)",
                metric=table_count,
                threshold={"green": 10, "yellow": 15},
            ))
        # ... same pattern for columns, joins, join_depth, formulas
    return findings
```

Conventions:
- Returns `[]` when nothing triggers -- no findings means passing
- D1 emits up to 5 sub-findings (one per metric) for the same model
- Checks never call APIs -- they only read from `AuditContext`
- Thresholds are literals in the check function (from modeling-best-practices reference)
- Cross-model checks (D7, D8, D12) iterate model pairs via `itertools.combinations`
- `Finding` is a flat dataclass with `.to_dict()` for JSON serialization

## Runner Logic

```python
# audit/__init__.py

ANGLE_MODULES = {
    "A": checks_ai,
    "D": checks_data,
    "H": checks_human,
    "P": checks_perf,
    "S": checks_security,
}

def run_audit(
    client: ThoughtSpotClient,
    model_guids: list[str],
    angles: list[str] | None = None,
) -> dict:
    angles = angles or list(ANGLE_MODULES.keys())

    # Phase 1: collect data
    ctx = build_context(client, model_guids, angles)

    # Phase 2: run checks
    findings = []
    checks_run = 0
    for angle_key in angles:
        module = ANGLE_MODULES[angle_key]
        for check_fn in module.ALL_CHECKS:
            findings.extend(check_fn(ctx))
            checks_run += 1

    # Phase 3: build output
    return {
        "findings": [f.to_dict() for f in findings],
        "summary": build_summary(findings, checks_run, ctx),
    }
```

## Checks by Angle

### A -- AI Readiness (5 checks)

| Check | What it measures | Key fields | Severity thresholds |
|---|---|---|---|
| A1 | Column description coverage (%) | `columns[].description` | RED < 50%, YELLOW 50-79%, GREEN >= 80% |
| A2 | Synonym coverage (%) | `columns[].synonyms[]` | RED < 25%, YELLOW 25-49%, GREEN >= 50% |
| A3 | AI context presence | `ai/instructions/get` response | HIGH if absent |
| A4 | Model description | `model.description` | MEDIUM if absent |
| A5 | Spotter readiness composite | Weighted A1-A4 + H1 | Ready >= 80, Needs work 50-79, Not ready < 50 |

### D -- Data Modeling (12 checks)

| Check | What it measures | Key fields | Severity thresholds |
|---|---|---|---|
| D1 | Model complexity (tables, columns, joins, formulas, depth) | `model_tables[]`, `columns[]`, `joins[]`, `formulas[]` | Per-metric: tables >15 HIGH, >10 MEDIUM; columns >75 HIGH, >50 MEDIUM; joins >12 HIGH, >8 MEDIUM; depth >5 HIGH, >3 MEDIUM; formulas >50 HIGH, >30 MEDIUM |
| D2 | Join key quality (VARCHAR, multi-column) | `joins[].on` + column data types | VARCHAR = HIGH, multi-column = MEDIUM |
| D3 | Join type analysis | `joins[].type` | FULL OUTER = HIGH, LEFT/RIGHT OUTER = INFO |
| D4 | Progressive joins | `model.properties.join_progressive` | HIGH if false on models > 5 tables |
| D5 | Orphan tables in model | `model_tables[].name` vs `joins[].with` | HIGH per orphan |
| D6 | Grain consistency | `columns[].properties.column_type` per table | LOW if fact > 40% ATTRIBUTEs |
| D7 | Model overlap and duplication | `model_tables[].fqn` cross-model | Identical sets = HIGH, shared facts = MEDIUM |
| D8 | Duplicate tables | `(connection, db, schema, db_table)` grouping | HIGH per duplicate |
| D9 | SQL pass-through usage | `formulas[].expr` regex for `sql_*_aggregate_op` | LOW (flag if > 20%) |
| D10 | Zero-column tables | Column-to-table mapping vs model_tables | Bridge = INFO, leaf = MEDIUM |
| D11 | Fan-out join risk | Join cardinality + table role + mitigation | MEDIUM unmitigated, INFO mitigated |
| D12 | Conformed dimension divergence | Same `db_column_name` classified differently across models | MEDIUM per divergent column |

### H -- Human Readiness (10 checks)

| Check | What it measures | Key fields | Severity thresholds |
|---|---|---|---|
| H1 | Column name quality | `columns[].name` regex | MEDIUM if > 10% anti-pattern |
| H2 | Description quality | `columns[].description` length + boilerplate | LOW per issue |
| H3 | Unnecessary hidden columns | `is_hidden` not referenced by any formula (bridge-table exception) | MEDIUM per column |
| H4 | Orphan models | Zero dependents from metadata API | MEDIUM |
| H5 | Orphan sets | Zero consuming answers/liveboards | MEDIUM |
| H6 | Duplicate sets | Equivalent filter definitions across models | LOW |
| H7 | Direct table connections | Answers connected to tables bypassing model layer | MEDIUM per answer |
| H8 | Formula promotion candidates | Duplicate formulas in 2+ answers not in model | HIGH per group |
| H9 | Redundant answer formulas | Answer formulas duplicating model formulas | LOW per formula |
| H10 | Stale/temporary objects | Name/description regex for stale patterns (Phase 1 only; Phase 2 BI Server deferred) | Object-level = LOW (MEDIUM if orphan), column-level = LOW |

### P -- Performance (16 checks)

| Check | What it measures | Key fields | Severity thresholds |
|---|---|---|---|
| P1 | SQL View detection | metadata search subtype `SQL_VIEW` | MEDIUM per view |
| P2 | Scalar formula density | Formulas without aggregation | MEDIUM if > 10 |
| P3 | Model filter progressiveness | `filters[].apply_on_tables` presence | MEDIUM per non-progressive |
| P4 | Apply-all-joins anti-pattern | `join_progressive: false` | HIGH on models > 5 tables |
| P5 | Date constraint coverage | `constraints[].date_range_condition` on fact tables | MEDIUM per uncovered fact |
| P6 | VARCHAR join keys | Same data as D2, framed as performance | HIGH per VARCHAR join |
| P7 | Join depth | Same data as D1 depth, framed as query plan | HIGH if > 5 |
| P8 | Column sprawl | Column count > 75 | MEDIUM |
| P9 | High-cardinality attribute indexing | `index_type` + ID name regex | MEDIUM per column |
| P11 | Secure suggestions overhead | Indexed columns on Spotter-enabled model | INFO if > 30 |
| P13 | RLS rule density | `rls_rules.rules[]` count per table | MEDIUM > 3, HIGH > 6 |
| P14 | RLS formula complexity | Functions in RLS expressions | MEDIUM per expression |
| P15 | RLS column casing | VARCHAR RLS columns without `value_casing` | MEDIUM per column |
| P16 | Formula nesting depth | `if()` count in formula expressions | INFO > 3, LOW > 5 |
| P17 | Formula reference chains | Cross-formula bracket refs, BFS depth | INFO > 2, LOW > 3 |
| P18 | COUNT_DISTINCT measures | `aggregation: COUNT_DISTINCT` columns | INFO per column |

### S -- Security (8 checks)

| Check | What it measures | Key fields | Severity thresholds |
|---|---|---|---|
| S1 | PII column detection | `columns[].name` regex (email, phone, SSN, DOB, financial, person name, address) | Flag for review |
| S2 | PII indexing without RLS | PII columns indexed + no table RLS | HIGH unsecured, INFO with RLS |
| S3 | Column Level Security gaps | PII without CLS/masking formulas | HIGH per unprotected |
| S4 | RLS bypass + PII | `is_bypass_rls: true` with PII columns | HIGH |
| S5 | Credentials in analytics | Credential name patterns in columns | CRITICAL |
| S8 | RLS column data type quality | VARCHAR columns in RLS expressions | MEDIUM per column |
| S9 | RLS expression complexity | Functions wrapping columns in RLS | HIGH per expression |
| S10 | RLS bypass as exception | `is_bypass_rls: true` | MEDIUM |

## Deferred Scope

| Item | Reason | When |
|---|---|---|
| H10 Phase 2 (BI Server usage overlay) | Needs BI Server query infrastructure not yet in ts-cli | Future BL item when BI Server access is built |
| Tunable thresholds (`--config`) | YAGNI -- thresholds come from modeling-best-practices and change rarely | If user demand materialises |
| HTML report output | v1 is JSON; LLM generates the narrative. A `--format html` could generate a standalone report | Future enhancement |

## Testing Strategy

Each angle module gets its own test file with fixture-based TML:

```
tools/ts-cli/tests/
+-- audit/
|   +-- test_checks_ai.py
|   +-- test_checks_data.py
|   +-- test_checks_human.py
|   +-- test_checks_perf.py
|   +-- test_checks_security.py
|   +-- test_context.py
|   +-- fixtures/
|       +-- model_healthy.json      # passes all checks
|       +-- model_unhealthy.json    # triggers every check
|       +-- tables/                 # associated table TMLs
```

Test pattern: build an `AuditContext` from fixture JSON, call a check function,
assert the findings list.

```python
def test_d1_flags_high_table_count():
    ctx = make_context(model={"model_tables": [{}] * 16})
    findings = check_d1(ctx)
    assert any(f.check_id == "D1" and f.severity == "HIGH" for f in findings)

def test_d1_passes_under_threshold():
    ctx = make_context(model={"model_tables": [{}] * 8})
    assert check_d1(ctx) == []
```

A `make_context()` helper builds minimal `AuditContext` objects from partial
dicts -- tests only specify the fields their check reads, everything else
defaults to empty.

Smoke test (`tools/smoke-tests/smoke_ts_audit.py`) covers the CLI entry point
against a live instance. The 51 check functions are all unit-tested with fixtures.

## SKILL.md Impact

After `ts audit run` ships, the ts-audit SKILL.md simplifies to:

1. User identifies model GUIDs (via `ts metadata search`)
2. `ts audit run --profile <name> --models <guid1> <guid2>`
3. LLM reads the JSON output
4. LLM interprets findings: prioritises by severity and business context,
   groups related issues, recommends remediation order, explains impact
5. LLM writes the narrative report

Steps 3-5 are where the LLM adds genuine value -- judgment, prioritisation,
business-context interpretation. The threshold logic, TML parsing, and
finding classification are gone from the prompt.
