#!/usr/bin/env python3
"""
ts-audit analysis engine.

Takes a TML corpus (exported model/table/answer TMLs + metadata) and runs
all audit checks, producing a list of findings. Called by the skill's Step 5.

Usage (from Claude Code or script):
    from analyzer import run_audit, AuditConfig

    config = AuditConfig(
        angles=["A", "D", "H", "P", "S"],
        profile="spotter-ready",
    )
    findings = run_audit(corpus, config)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# Config & data structures
# ---------------------------------------------------------------------------

SPOTTER_THRESHOLDS = {
    "description_coverage": 0.95,
    "synonym_coverage": 0.80,
    "ai_context_required": True,
    "model_description_required": True,
}

GENERAL_THRESHOLDS = {
    "description_coverage": 0.50,
    "synonym_coverage": 0.25,
    "ai_context_required": False,
    "model_description_required": False,
}

COMPLEXITY_THRESHOLDS = {
    "tables":    {"green": 10, "yellow": 15},
    "columns":   {"green": 50, "yellow": 75},
    "joins":     {"green": 8,  "yellow": 12},
    "depth":     {"green": 3,  "yellow": 5},
    "formulas":  {"green": 30, "yellow": 50},
}


@dataclass
class AuditConfig:
    angles: list[str] = field(default_factory=lambda: ["A", "D", "H", "P", "S"])
    profile: str = "spotter-ready"

    @property
    def thresholds(self) -> dict:
        return SPOTTER_THRESHOLDS if self.profile == "spotter-ready" else GENERAL_THRESHOLDS


@dataclass
class Finding:
    angle: str
    check_id: str
    check_name: str
    severity: str
    title: str
    detail: str
    recommendation: str
    score: float | None = None
    model_name: str | None = None
    model_guid: str | None = None
    objects: list[dict] | None = None
    accepted: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d = {k: v for k, v in d.items() if v is not None}
        return d


@dataclass
class Corpus:
    """Structured TML corpus built from exported data."""
    models: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    answers: list[dict] = field(default_factory=list)
    sets: list[dict] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)
    dependents: dict[str, list[dict]] = field(default_factory=dict)
    table_tmls_by_model: dict[str, list[dict]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _severity_from_threshold(value: float, green: float, yellow: float) -> str:
    if value <= green:
        return "GREEN"
    if value <= yellow:
        return "MEDIUM"
    return "HIGH"


def _severity_from_fraction(fraction: float, high_below: float, medium_below: float) -> str:
    if fraction < high_below:
        return "HIGH"
    if fraction < medium_below:
        return "MEDIUM"
    return "GREEN"


def _model_name(model_tml: dict) -> str:
    return model_tml.get("model", {}).get("name", "Unknown")


def _model_guid(model_tml: dict) -> str | None:
    return model_tml.get("guid")


def _get_columns(model: dict) -> list[dict]:
    return model.get("model", {}).get("columns", [])


def _get_formulas(model: dict) -> list[dict]:
    return model.get("model", {}).get("formulas", [])


def _get_model_tables(model: dict) -> list[dict]:
    return model.get("model", {}).get("model_tables", [])


def _get_properties(model: dict) -> dict:
    return model.get("model", {}).get("properties", {})


def _columns_by_table(model: dict) -> dict[str, list[dict]]:
    """Map table name → list of columns referencing it via column_id."""
    result: dict[str, list[dict]] = {}
    for col in _get_columns(model):
        cid = col.get("column_id", "")
        if "::" in cid:
            tname = cid.split("::")[0]
            result.setdefault(tname, []).append(col)
    return result


def _all_joins(model: dict) -> list[tuple[str, dict]]:
    """Return (source_table_name, join_dict) for all joins in the model."""
    joins = []
    for mt in _get_model_tables(model):
        for j in mt.get("joins", []):
            joins.append((mt.get("name", ""), j))
    return joins


def _join_targets(model: dict) -> set[str]:
    """Set of table names that appear as join targets."""
    return {j.get("with", "") for _, j in _all_joins(model)}


def _join_sources(model: dict) -> set[str]:
    """Set of table names that source at least one join."""
    return {src for src, _ in _all_joins(model)}


def _join_depth(model: dict) -> int:
    """Longest chain of joins from any table (BFS)."""
    adjacency: dict[str, list[str]] = {}
    for mt in _get_model_tables(model):
        src = mt.get("name", "")
        for j in mt.get("joins", []):
            adjacency.setdefault(src, []).append(j.get("with", ""))

    max_depth = 0
    for start in adjacency:
        visited = {start}
        queue = [(start, 0)]
        while queue:
            node, depth = queue.pop(0)
            max_depth = max(max_depth, depth)
            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
    return max_depth


PII_PATTERNS = [
    (re.compile(r"email|e[-_]?mail|email[-_]?addr", re.I), "Email", "HIGH"),
    (re.compile(r"phone|mobile|cell[-_]?phone|fax|tel(?:ephone)?", re.I), "Phone", "HIGH"),
    (re.compile(r"ssn|social[-_]?sec|national[-_]?id|tax[-_]?id|\bsin\b|\bnin\b", re.I), "National ID", "HIGH"),
    (re.compile(r"dob|birth[-_]?date|date[-_]?of[-_]?birth|birthday", re.I), "Date of birth", "HIGH"),
    (re.compile(r"credit[-_]?card|card[-_]?num|account[-_]?num|iban|routing[-_]?num", re.I), "Financial", "HIGH"),
    (re.compile(r"password|passwd|secret[-_]?key|api[-_]?key", re.I), "Credentials", "CRITICAL"),
    (re.compile(r"first[-_]?name|last[-_]?name|surname|full[-_]?name|given[-_]?name", re.I), "Name", "MEDIUM"),
    (re.compile(r"street[-_]?addr|postal[-_]?code|zip[-_]?code", re.I), "Address", "MEDIUM"),
]

STALE_PATTERNS = [
    (re.compile(r"\bdo[-_ ]?not[-_ ]?use\b", re.I), "Explicit exclusion", "HIGH"),
    (re.compile(r"\bDEPRECATED\b", re.I), "Explicit exclusion", "HIGH"),
    (re.compile(r"\bOBSOLETE\b", re.I), "Explicit exclusion", "HIGH"),
    (re.compile(r"\bzDEL\b", re.I), "Deletion candidate", "HIGH"),
    (re.compile(r"\bDELETE\b", re.I), "Deletion candidate", "HIGH"),
    (re.compile(r"\bTO[-_ ]?DELETE\b", re.I), "Deletion candidate", "HIGH"),
    (re.compile(r"^copy[-_ ]of[-_ ]", re.I), "Copy artifact", "MEDIUM"),
    (re.compile(r"[-_ ]copy\d*$", re.I), "Copy artifact", "MEDIUM"),
    (re.compile(r"[-_ ]\(\d+\)$", re.I), "Copy artifact", "MEDIUM"),
    (re.compile(r"\bbackup\b", re.I), "Backup/archive", "MEDIUM"),
    (re.compile(r"\barchive\b", re.I), "Backup/archive", "MEDIUM"),
    (re.compile(r"\bbak\b", re.I), "Backup/archive", "MEDIUM"),
    (re.compile(r"[-_ ]old$", re.I), "Backup/archive", "MEDIUM"),
    (re.compile(r"^old[-_ ]", re.I), "Backup/archive", "MEDIUM"),
    (re.compile(r"\btest[-_ ]?\d*\b", re.I), "Temporary", "MEDIUM"),
    (re.compile(r"\btmp[-_ ]", re.I), "Temporary", "MEDIUM"),
    (re.compile(r"\btemp[-_ ]", re.I), "Temporary", "MEDIUM"),
]

STALE_EXCLUDE = [
    re.compile(r"test[-_]results", re.I),
    re.compile(r"test[-_]automation", re.I),
    re.compile(r"test[-_]coverage", re.I),
    re.compile(r"test[-_]environment", re.I),
    re.compile(r"test[-_]suite", re.I),
]

COLUMN_NAME_ANTIPATTERNS = [
    (re.compile(r"^col\d+$", re.I), "Generic (col#)"),
    (re.compile(r"^field[-_]?\d+$", re.I), "Generic (field#)"),
    (re.compile(r"^val\d*$", re.I), "Ambiguous (val)"),
    (re.compile(r"^tmp[-_]?", re.I), "Temporary"),
    (re.compile(r"^\d", re.I), "Starts with digit"),
    (re.compile(r"^[A-Z][A-Z0-9_]+$"), "All uppercase+underscore"),
]

SQL_PASSTHROUGH_RE = re.compile(
    r"sql_(int|string|bool|date|double)_aggregate_op", re.I
)

FANOUT_NAME_RE = re.compile(
    r"(RATE|CURRENCY|EXCHANGE|FX|CONVERSION|XREF|CROSS_REF|BRIDGE|MAPPING)",
    re.I,
)


def _detect_pii(name: str) -> tuple[str, str] | None:
    lower = name.lower()
    for pattern, category, severity in PII_PATTERNS:
        if pattern.search(lower):
            return category, severity
    return None


def _detect_stale(name: str) -> tuple[str, str] | None:
    if any(ex.search(name) for ex in STALE_EXCLUDE):
        return None
    for pattern, category, severity in STALE_PATTERNS:
        if pattern.search(name):
            return category, severity
    return None


def _normalise_expr(expr: str) -> str:
    """Normalise a formula expression for comparison."""
    s = expr.strip().rstrip(";").strip()
    s = re.sub(r"\s+", " ", s)
    return s.lower()


# ---------------------------------------------------------------------------
# A — AI Readiness checks
# ---------------------------------------------------------------------------

def check_a1(model: dict, config: AuditConfig) -> list[Finding]:
    """A1: Column description coverage."""
    columns = _get_columns(model)
    if not columns:
        return []
    described = sum(1 for c in columns if c.get("description", "").strip())
    total = len(columns)
    fraction = described / total if total else 0
    threshold = config.thresholds["description_coverage"]
    severity = _severity_from_fraction(fraction, 0.50, 0.80)
    if fraction >= threshold:
        return []
    return [Finding(
        angle="A", check_id="A1", check_name="DESCRIPTION_COVERAGE",
        severity=severity,
        title=f"Description coverage {fraction:.0%} (target: {threshold:.0%})",
        detail=f"{described}/{total} columns have descriptions",
        score=fraction,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Run /ts-object-model-coach to generate descriptions",
    )]


def check_a2(model: dict, config: AuditConfig) -> list[Finding]:
    """A2: Synonym coverage."""
    columns = _get_columns(model)
    if not columns:
        return []
    with_synonyms = sum(1 for c in columns if c.get("synonyms"))
    total = len(columns)
    fraction = with_synonyms / total if total else 0
    threshold = config.thresholds["synonym_coverage"]
    severity = _severity_from_fraction(fraction, 0.25, 0.50)
    if fraction >= threshold:
        return []
    return [Finding(
        angle="A", check_id="A2", check_name="SYNONYM_COVERAGE",
        severity=severity,
        title=f"Synonym coverage {fraction:.0%} (target: {threshold:.0%})",
        detail=f"{with_synonyms}/{total} columns have synonyms",
        score=fraction,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Run /ts-object-model-coach to generate synonyms",
    )]


def check_a3(model: dict, _config: AuditConfig) -> list[Finding]:
    """A3: AI context presence (data_model_instructions)."""
    m = model.get("model", {})
    instructions = (m.get("model_instructions", {}) or {}).get(
        "data_model_instructions", ""
    )
    if instructions and instructions.strip():
        return []
    return [Finding(
        angle="A", check_id="A3", check_name="AI_CONTEXT_MISSING",
        severity="HIGH",
        title="No AI context (data model instructions)",
        detail="Model has no data_model_instructions — Spotter has no coaching context",
        score=0.0,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Run /ts-object-model-coach to add Spotter coaching instructions",
    )]


def check_a4(model: dict, _config: AuditConfig) -> list[Finding]:
    """A4: Model description."""
    desc = model.get("model", {}).get("description", "")
    if desc and desc.strip():
        return []
    return [Finding(
        angle="A", check_id="A4", check_name="MODEL_DESCRIPTION_MISSING",
        severity="MEDIUM",
        title="No model description",
        detail="Model-level description is empty or absent",
        score=0.0,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Add a description explaining what this model covers and who it serves",
    )]


def check_a5(model: dict, config: AuditConfig) -> list[Finding]:
    """A5: Spotter readiness composite score."""
    columns = _get_columns(model)
    total = len(columns) if columns else 1

    desc_count = sum(1 for c in columns if c.get("description", "").strip())
    syn_count = sum(1 for c in columns if c.get("synonyms"))
    desc_frac = desc_count / total
    syn_frac = syn_count / total

    m = model.get("model", {})
    has_ai = bool((m.get("model_instructions", {}) or {}).get(
        "data_model_instructions", ""
    ))
    has_desc = bool(m.get("description", "").strip())

    bad_names = sum(
        1 for c in columns
        if any(p.search(c.get("name", "")) for p, _ in COLUMN_NAME_ANTIPATTERNS)
    )
    name_quality = 1.0 - (bad_names / total if total else 0)

    score = (
        desc_frac * 0.30
        + (1.0 if has_ai else 0.0) * 0.25
        + syn_frac * 0.15
        + (1.0 if has_desc else 0.0) * 0.15
        + name_quality * 0.15
    )
    score_100 = round(score * 100)

    if score_100 >= 80:
        label = "READY"
        severity = "INFO"
    elif score_100 >= 50:
        label = "NEEDS WORK"
        severity = "MEDIUM"
    else:
        label = "NOT READY"
        severity = "HIGH"

    return [Finding(
        angle="A", check_id="A5", check_name="SPOTTER_READINESS",
        severity=severity,
        title=f"Spotter readiness: {score_100}/100 ({label})",
        detail=(
            f"Descriptions: {desc_frac:.0%}, Synonyms: {syn_frac:.0%}, "
            f"AI context: {'Yes' if has_ai else 'No'}, "
            f"Model description: {'Yes' if has_desc else 'No'}, "
            f"Name quality: {name_quality:.0%}"
        ),
        score=score,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Run /ts-object-model-coach" if score_100 < 80 else "",
    )]


# ---------------------------------------------------------------------------
# D — Data Modeling checks
# ---------------------------------------------------------------------------

def check_d1(model: dict, _config: AuditConfig) -> list[Finding]:
    """D1: Model complexity (tables, columns, joins, formulas, depth)."""
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    mt = _get_model_tables(model)
    cols = _get_columns(model)
    formulas = _get_formulas(model)
    join_count = sum(len(t.get("joins", [])) for t in mt)
    depth = _join_depth(model)

    metrics = [
        ("tables", len(mt)),
        ("columns", len(cols)),
        ("joins", join_count),
        ("depth", depth),
        ("formulas", len(formulas)),
    ]

    METRIC_DETAIL = {
        "tables": "Number of tables joined in the model. More tables means wider queries and more complex join plans.",
        "columns": "Total columns exposed by the model. Wide models increase GROUP BY clause size and memory usage.",
        "joins": "Total join relationships defined. Each join adds a table scan or hash-join step to the query plan.",
        "depth": "Longest chain of joins from any table to the furthest reachable table. "
                 "Deep chains force the query engine to process joins sequentially rather than in parallel.",
        "formulas": "Number of formulas in the model. Each formula is evaluated at query time; "
                    "high counts increase calculation overhead.",
    }

    METRIC_REC = {
        "tables": "Consider splitting into domain-specific models",
        "columns": "Hide or remove columns that are not used in answers or searches",
        "joins": "Review whether all joins are needed — remove unused table relationships",
        "depth": "Flatten the join graph by connecting tables to a central fact rather than chaining through intermediaries",
        "formulas": "Move reusable calculations to the warehouse as views or computed columns",
    }

    for metric_name, value in metrics:
        t = COMPLEXITY_THRESHOLDS[metric_name]
        sev = _severity_from_threshold(value, t["green"], t["yellow"])
        if sev != "GREEN":
            detail = METRIC_DETAIL[metric_name]
            detail += f" (≤{t['green']} pass, ≤{t['yellow']} review, >{t['yellow']} action needed)"
            findings.append(Finding(
                angle="D", check_id="D1", check_name=f"COMPLEXITY_{metric_name.upper()}",
                severity=sev,
                title=f"{metric_name.capitalize()}: {value}",
                detail=detail,
                score=value,
                model_name=name, model_guid=guid,
                recommendation=METRIC_REC[metric_name],
            ))
    return findings


def check_d2(model: dict, corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """D2: Join key quality — VARCHAR joins, multi-column joins."""
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    table_tmls = corpus.table_tmls_by_model.get(guid or "", [])

    col_types: dict[str, dict[str, str]] = {}
    for ttl in table_tmls:
        tbl = ttl.get("table", {})
        tbl_name = tbl.get("name", "")
        for c in tbl.get("columns", []):
            db_col = c.get("db_column_name", c.get("name", ""))
            dtype = (c.get("db_column_properties", {}) or {}).get("data_type", "")
            col_types.setdefault(tbl_name, {})[db_col] = dtype

    for src_table, join in _all_joins(model):
        on_clause = join.get("on", "")
        target = join.get("with", "")
        if "AND" in on_clause.upper():
            findings.append(Finding(
                angle="D", check_id="D2", check_name="MULTI_COLUMN_JOIN",
                severity="MEDIUM",
                title=f"Multi-column join: {src_table} → {target}",
                detail=f"Join ON: {on_clause}. Consider a surrogate key.",
                model_name=name, model_guid=guid,
                recommendation="Add a surrogate integer key to simplify the join",
            ))

    return findings


def check_d3(model: dict, _config: AuditConfig) -> list[Finding]:
    """D3: Join type analysis — FULL OUTER, LEFT/RIGHT OUTER."""
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    for src, join in _all_joins(model):
        jtype = join.get("type", "INNER").upper()
        target = join.get("with", "")
        if jtype == "OUTER":
            findings.append(Finding(
                angle="D", check_id="D3", check_name="FULL_OUTER_JOIN",
                severity="HIGH",
                title=f"FULL OUTER join: {src} → {target}",
                detail="FULL OUTER joins often cause performance issues and unexpected row multiplication",
                model_name=name, model_guid=guid,
                recommendation="Review whether INNER or LEFT OUTER would be correct",
            ))
        elif jtype in ("LEFT_OUTER", "RIGHT_OUTER"):
            findings.append(Finding(
                angle="D", check_id="D3", check_name="OUTER_JOIN",
                severity="INFO",
                title=f"{jtype} join: {src} → {target}",
                detail="May indicate data discrepancies between tables — review for correctness",
                model_name=name, model_guid=guid,
                recommendation="",
            ))
    return findings


def check_d4(model: dict, _config: AuditConfig) -> list[Finding]:
    """D4: Progressive joins."""
    props = _get_properties(model)
    progressive = props.get("join_progressive", False)
    table_count = len(_get_model_tables(model))
    if progressive or table_count <= 5:
        return []
    return [Finding(
        angle="D", check_id="D4", check_name="JOIN_NOT_PROGRESSIVE",
        severity="HIGH",
        title=f"join_progressive is false ({table_count} tables)",
        detail="Every query joins ALL tables regardless of which columns are searched",
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Enable progressive joins in model properties",
    )]


def _tables_referenced_in_formulas(model: dict) -> set[str]:
    """Return table names referenced via [Table::Column] in formula expressions."""
    refs: set[str] = set()
    for f in _get_formulas(model):
        expr = f.get("expr", "")
        for match in re.findall(r'\[([^]]+)::', expr):
            refs.add(match)
    for c in _get_columns(model):
        cid = c.get("column_id", "")
        if "::" in cid:
            refs.add(cid.split("::")[0])
    return refs


def check_d5(model: dict, _config: AuditConfig) -> list[Finding]:
    """D5: Orphan tables in model (no joins and no formula/column references)."""
    findings = []
    targets = _join_targets(model)
    sources = _join_sources(model)
    connected = targets | sources
    formula_refs = _tables_referenced_in_formulas(model)
    for mt in _get_model_tables(model):
        tname = mt.get("name", "")
        if tname in connected or tname in formula_refs:
            continue
        findings.append(Finding(
            angle="D", check_id="D5", check_name="ORPHAN_TABLE_IN_MODEL",
            severity="HIGH",
            title=f"Unjoined table: {tname}",
            detail="Table has no join in either direction and no column or formula references — Cartesian product risk",
            model_name=_model_name(model), model_guid=_model_guid(model),
            recommendation="Add a join or remove from the model",
        ))
    return findings


def check_d6(model: dict, _config: AuditConfig) -> list[Finding]:
    """D6: Grain consistency — fact tables with too many attributes."""
    findings = []
    cbt = _columns_by_table(model)
    for tname, cols in cbt.items():
        measures = sum(
            1 for c in cols
            if (c.get("properties", {}) or {}).get("column_type", "") == "MEASURE"
        )
        if measures < 3:
            continue
        attrs = sum(
            1 for c in cols
            if (c.get("properties", {}) or {}).get("column_type", "") == "ATTRIBUTE"
        )
        total = len(cols)
        if total > 0 and attrs / total > 0.40:
            findings.append(Finding(
                angle="D", check_id="D6", check_name="GRAIN_INCONSISTENCY",
                severity="LOW",
                title=f"Fact table '{tname}' has {attrs}/{total} attributes ({attrs/total:.0%})",
                detail="Fact tables should be mostly measures. High attribute ratio may indicate mixed grain.",
                score=attrs / total,
                model_name=_model_name(model), model_guid=_model_guid(model),
                recommendation="Review whether some attributes should be in a dimension table",
            ))
    return findings


def _display_name(name: str, guid: str | None) -> str:
    """Disambiguate models with the same display name by appending a short GUID."""
    return f"{name} [{guid[:8]}]" if guid else name


def check_d7(models: list[dict], _config: AuditConfig) -> list[Finding]:
    """D7: Model overlap & duplication (cross-model check)."""
    findings = []
    table_sets: list[tuple[str, str | None, set[str]]] = []

    for m in models:
        name = _model_name(m)
        guid = _model_guid(m)
        fqns = {mt.get("fqn", mt.get("name", "")) for mt in _get_model_tables(m)}
        table_sets.append((name, guid, fqns))

    seen_pairs: set[tuple[str, str]] = set()

    for i in range(len(table_sets)):
        for j in range(i + 1, len(table_sets)):
            n1, g1, s1 = table_sets[i]
            n2, g2, s2 = table_sets[j]
            if not s1 or not s2:
                continue
            pair_key = tuple(sorted([g1 or n1, g2 or n2]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            intersection = s1 & s2
            union = s1 | s2
            jaccard = len(intersection) / len(union) if union else 0

            dn1 = _display_name(n1, g1) if n1 == n2 else n1
            dn2 = _display_name(n2, g2) if n1 == n2 else n2

            if jaccard == 1.0:
                findings.append(Finding(
                    angle="D", check_id="D7", check_name="IDENTICAL_MODELS",
                    severity="HIGH",
                    title=f"Identical table sets: {dn1}, {dn2}",
                    detail=f"Both models reference the same {len(s1)} tables",
                    score=jaccard,
                    objects=[
                        {"name": dn1, "guid": g1},
                        {"name": dn2, "guid": g2},
                    ],
                    recommendation="Consolidate via /ts-dependency-manager (Repoint mode)",
                ))
            elif s1 < s2 or s2 < s1:
                subset_name = dn1 if s1 < s2 else dn2
                superset_name = dn2 if s1 < s2 else dn1
                findings.append(Finding(
                    angle="D", check_id="D7", check_name="MODEL_SUBSET",
                    severity="INFO",
                    title=f"'{subset_name}' is a strict subset of '{superset_name}'",
                    detail=f"Subset has {min(len(s1), len(s2))} tables, superset has {max(len(s1), len(s2))}",
                    score=jaccard,
                    objects=[
                        {"name": dn1, "guid": g1},
                        {"name": dn2, "guid": g2},
                    ],
                    recommendation="May be correctly scoped domain model — review whether the subset is needed",
                ))
            elif jaccard > 0.5:
                findings.append(Finding(
                    angle="D", check_id="D7", check_name="MODEL_OVERLAP",
                    severity="MEDIUM" if jaccard > 0.7 else "LOW",
                    title=f"High overlap ({jaccard:.0%}): {dn1}, {dn2}",
                    detail=f"Shared: {len(intersection)} tables, Union: {len(union)} tables",
                    score=jaccard,
                    objects=[
                        {"name": dn1, "guid": g1},
                        {"name": dn2, "guid": g2},
                    ],
                    recommendation="Review whether these serve different domains or should be consolidated",
                ))
    return findings


def check_d8(corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """D8: Duplicate tables — different TS objects pointing at same physical table."""
    findings = []
    # Deduplicate table TMLs by GUID first (associated exports repeat the same table)
    seen_guids: set[str] = set()
    unique_tables: list[dict] = []
    for ttl in corpus.tables:
        guid = ttl.get("guid", "")
        if guid and guid in seen_guids:
            continue
        if guid:
            seen_guids.add(guid)
        unique_tables.append(ttl)

    physical_map: dict[tuple, list[dict]] = {}
    for ttl in unique_tables:
        tbl = ttl.get("table", {})
        conn = tbl.get("connection", {})
        key = (
            conn.get("name", ""),
            tbl.get("db", ""),
            tbl.get("schema", ""),
            tbl.get("db_table", ""),
        )
        if any(key):
            physical_map.setdefault(key, []).append({
                "name": tbl.get("name", ""),
                "guid": ttl.get("guid"),
            })

    for key, tables in physical_map.items():
        if len(tables) > 1:
            names = [t["name"] for t in tables]
            fqn = f"{key[1]}.{key[2]}.{key[3]}"
            findings.append(Finding(
                angle="D", check_id="D8", check_name="DUPLICATE_TABLE",
                severity="HIGH",
                title=f"{len(tables)} TS objects → {key[3]}",
                detail=fqn,
                objects=tables,
                recommendation="Consolidate to one ThoughtSpot table object",
            ))
    return findings


def check_d9(model: dict, _config: AuditConfig) -> list[Finding]:
    """D9: SQL pass-through function usage."""
    formulas = _get_formulas(model)
    if not formulas:
        return []
    passthrough = [f for f in formulas if SQL_PASSTHROUGH_RE.search(f.get("expr", ""))]
    total = len(formulas)
    count = len(passthrough)
    if count == 0:
        return []
    fraction = count / total
    severity = "MEDIUM" if fraction > 0.20 else "LOW"
    return [Finding(
        angle="D", check_id="D9", check_name="SQL_PASSTHROUGH",
        severity=severity,
        title=f"{count}/{total} formulas use sql_*_aggregate_op ({fraction:.0%})",
        detail="SQL pass-through bypasses ThoughtSpot formula engine. Legitimate for timezone conversions; overuse indicates TS formula limitations being worked around.",
        score=fraction,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Check if native TS formulas exist (see ts-snowflake-formula-translation.md)" if fraction > 0.20 else "",
    )]


def check_d10(model: dict, _config: AuditConfig) -> list[Finding]:
    """D10: Zero-column tables."""
    findings = []
    cbt = _columns_by_table(model)
    targets = _join_targets(model)
    sources = _join_sources(model)
    connected = targets | sources

    for mt in _get_model_tables(model):
        tname = mt.get("name", "")
        if tname in cbt:
            continue
        is_bridge = tname in connected
        findings.append(Finding(
            angle="D", check_id="D10", check_name="ZERO_COLUMN_TABLE",
            severity="INFO" if is_bridge else "MEDIUM",
            title=f"Zero-column table: {tname} ({'bridge' if is_bridge else 'leaf'})",
            detail="Bridge table with no selected columns — may cause query generation issues" if is_bridge else "Leaf table with no selected columns and no join purpose — consider removing",
            model_name=_model_name(model), model_guid=_model_guid(model),
            recommendation="" if is_bridge else "Remove from model or select columns",
        ))
    return findings


def _classify_table_role(model: dict) -> dict[str, str]:
    """Classify tables using join topology (primary) and column composition (fallback).

    Topology signals:
    - "dimension": only receives joins (inbound > 0, outbound == 0) — lookup table
    - "fact": hub with many inbound joins and outbound joins (inbound >= 2, outbound > 0)
    - "detail": leaf that only joins outward (inbound == 0, outbound >= 1)

    When topology is ambiguous (inbound == 1, outbound > 0), fall back to
    column composition: > 3 measures → "fact", otherwise "dimension".

    Isolated tables (no joins) use column composition only.
    """
    inbound: dict[str, int] = {}
    outbound: dict[str, int] = {}
    for mt in _get_model_tables(model):
        src = mt.get("name", "")
        for j in mt.get("joins", []):
            tgt = j.get("with", "")
            inbound[tgt] = inbound.get(tgt, 0) + 1
            outbound[src] = outbound.get(src, 0) + 1

    cbt = _columns_by_table(model)

    def _measure_count(tname: str) -> int:
        return sum(
            1 for c in cbt.get(tname, [])
            if (c.get("properties", {}) or {}).get("column_type", "") == "MEASURE"
        )

    roles: dict[str, str] = {}
    for mt in _get_model_tables(model):
        tname = mt.get("name", "")
        i = inbound.get(tname, 0)
        o = outbound.get(tname, 0)

        if i > 0 and o == 0:
            roles[tname] = "dimension"
        elif i >= 2 and o > 0:
            roles[tname] = "fact"
        elif i == 0 and o >= 1:
            roles[tname] = "detail"
        elif i == 1 and o > 0:
            roles[tname] = "fact" if _measure_count(tname) > 3 else "dimension"
        else:
            roles[tname] = "fact" if _measure_count(tname) > 3 else "unknown"

    return roles


def _refs_table(column_ref, table_name: str) -> bool:
    """Return True if column_ref is a ThoughtSpot Table::Column reference for table_name."""
    if isinstance(column_ref, list):
        return any(isinstance(c, str) and c.startswith(f"{table_name}::") for c in column_ref)
    if not isinstance(column_ref, str):
        return False
    return column_ref.startswith(f"{table_name}::")


def _check_fanout_mitigations(model: dict, target_table: str) -> bool:
    """Check if the model has parameters/filters/formulas that constrain a target table."""
    m = model.get("model", {})
    params = m.get("parameters", [])
    filters = m.get("filters", [])
    formulas = m.get("formulas", [])

    # Use prefix-aware matching: ThoughtSpot column refs are "Table::Column"
    filter_refs_target = any(
        _refs_table(f.get("column", "") or "", target_table)
        for f in filters
    )
    if filter_refs_target:
        return True

    if params:
        # Formula expressions use [Table::Column] syntax — substring match is acceptable
        all_exprs = " ".join(f.get("expr", "") for f in formulas)
        # Filter column refs use prefix-aware check to avoid false positives
        all_filter_cols = " ".join(
            " ".join(c for c in col if isinstance(c, str)) if isinstance(col, list) else (col or "")
            for col in (f.get("column", "") for f in filters)
        )
        filter_col_refs_target = any(
            _refs_table(f.get("column", "") or "", target_table)
            for f in filters
        )
        if target_table in all_exprs or filter_col_refs_target:
            return True

    return False


def check_d11(model: dict, _config: AuditConfig) -> list[Finding]:
    """D11: Fan-out join risk — cardinality, hub-to-hub joins, naming + mitigation.

    Uses topology-based role classification so that normal patterns
    (detail→fact, fact→dimension) are not flagged.
    """
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    roles = _classify_table_role(model)

    for src_table, join in _all_joins(model):
        target = join.get("with", "")
        cardinality = join.get("cardinality", "")
        src_role = roles.get(src_table, "unknown")
        tgt_role = roles.get(target, "unknown")
        mitigated = _check_fanout_mitigations(model, target)

        if cardinality == "ONE_TO_MANY":
            severity = "INFO" if mitigated else "MEDIUM"
            detail = (f"ONE_TO_MANY join: {src_table} → {target}. "
                      f"Each source row produces multiple output rows.")
            if mitigated:
                detail += " Fan-out risk appears mitigated by parameter/filter — confirm."
            else:
                detail += " No visible constraint — confirm users select a single value."
            findings.append(Finding(
                angle="D", check_id="D11", check_name="FANOUT_CARDINALITY",
                severity=severity,
                title=f"ONE_TO_MANY join: {src_table} → {target}",
                detail=detail,
                model_name=name, model_guid=guid,
                recommendation="Add a parameter or filter to constrain the target table to a single value",
            ))

        if src_role == "fact" and tgt_role == "fact":
            severity = "INFO" if mitigated else "MEDIUM"
            findings.append(Finding(
                angle="D", check_id="D11", check_name="FANOUT_FACT_TO_FACT",
                severity=severity,
                title=f"Fact-to-fact join: {src_table} → {target}",
                detail=f"Two hub tables joined (both receive multiple inbound joins) "
                       f"— potential chasm trap or fan trap. "
                       f"{'Fan-out appears mitigated.' if mitigated else 'Verify join is many-to-one.'}",
                model_name=name, model_guid=guid,
                recommendation="Confirm the join is many-to-one, or add a bridge table to control cardinality",
            ))

        if FANOUT_NAME_RE.search(target):
            name_mitigated = _check_fanout_mitigations(model, target)
            already_flagged = any(
                f.check_id == "D11" and target in f.title
                for f in findings
            )
            if not already_flagged and not name_mitigated:
                findings.append(Finding(
                    angle="D", check_id="D11", check_name="FANOUT_NAME",
                    severity="INFO",
                    title=f"Potential conversion/rate table: {target}",
                    detail=f"Join to '{target}' — if this is a conversion/rate table, "
                           f"confirm a parameter or filter constrains it to a single target value",
                    model_name=name, model_guid=guid,
                    recommendation="Add a parameter for target value selection if not already present",
                ))

    return findings


# ---------------------------------------------------------------------------
# H — Human Readiness checks
# ---------------------------------------------------------------------------

def check_h1(model: dict, _config: AuditConfig) -> list[Finding]:
    """H1: Column name quality."""
    columns = _get_columns(model)
    if not columns:
        return []
    bad = []
    for c in columns:
        cname = c.get("name", "")
        for pattern, issue in COLUMN_NAME_ANTIPATTERNS:
            if pattern.search(cname):
                bad.append((cname, issue))
                break

    if not bad:
        return []
    fraction = len(bad) / len(columns)
    if fraction <= 0.10:
        return []
    return [Finding(
        angle="H", check_id="H1", check_name="COLUMN_NAME_QUALITY",
        severity="MEDIUM",
        title=f"{len(bad)}/{len(columns)} columns have name anti-patterns ({fraction:.0%})",
        detail="; ".join(f"{n} ({issue})" for n, issue in bad[:10])
            + (f" ... and {len(bad)-10} more" if len(bad) > 10 else ""),
        score=fraction,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Rename columns to be user-friendly and descriptive",
    )]


def check_h2(model: dict, _config: AuditConfig) -> list[Finding]:
    """H2: Description quality."""
    columns = _get_columns(model)
    issues = []
    for c in columns:
        desc = c.get("description", "")
        if not desc:
            continue
        name = c.get("name", "?")
        if len(desc) < 20:
            issues.append((name, "too short"))
        elif len(desc) > 400:
            issues.append((name, "too long (>400 chars, Spotter limit)"))
        elif re.match(r"^(This is a |This column |Column for )", desc, re.I):
            issues.append((name, "boilerplate"))

    if not issues:
        return []
    return [Finding(
        angle="H", check_id="H2", check_name="DESCRIPTION_QUALITY",
        severity="LOW",
        title=f"{len(issues)} description quality issues",
        detail="; ".join(f"{n}: {issue}" for n, issue in issues[:10])
            + (f" ... and {len(issues)-10} more" if len(issues) > 10 else ""),
        score=len(issues),
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Improve descriptions: 20-400 chars, avoid boilerplate openers",
    )]


def check_h3(model: dict, _config: AuditConfig) -> list[Finding]:
    """H3: Unnecessary hidden columns."""
    columns = _get_columns(model)
    formulas = _get_formulas(model)

    formula_exprs = " ".join(f.get("expr", "") for f in formulas)

    cbt = _columns_by_table(model)
    targets = _join_targets(model)
    sources = _join_sources(model)
    connected = targets | sources
    bridge_tables = {
        mt.get("name", "") for mt in _get_model_tables(model)
        if mt.get("name", "") in connected and mt.get("name", "") not in cbt
    }

    unnecessary = []
    for c in columns:
        props = c.get("properties", {}) or {}
        if not props.get("is_hidden"):
            continue
        cname = c.get("name", "")
        if f"[{cname}]" in formula_exprs:
            continue
        cid = c.get("column_id", "")
        if "::" in cid and cid.split("::")[0] in bridge_tables:
            continue
        unnecessary.append(cname)

    if not unnecessary:
        return []
    return [Finding(
        angle="H", check_id="H3", check_name="UNNECESSARY_HIDDEN",
        severity="MEDIUM",
        title=f"{len(unnecessary)} hidden columns not referenced by any formula",
        detail="Hidden columns cause locked visualizations. "
            + "; ".join(unnecessary[:15])
            + (f" ... and {len(unnecessary)-15} more" if len(unnecessary) > 15 else ""),
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Remove unused columns from the model rather than hiding them",
    )]


def check_h4(corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """H4: Orphan models (zero dependents)."""
    if not corpus.dependents:
        return []
    findings = []
    for m in corpus.models:
        guid = _model_guid(m)
        if not guid:
            continue
        if guid not in corpus.dependents:
            continue
        deps = corpus.dependents[guid]
        if not deps:
            findings.append(Finding(
                angle="H", check_id="H4", check_name="ORPHAN_MODEL",
                severity="MEDIUM",
                title=f"Orphan model: {_model_name(m)}",
                detail="Zero dependents — no answers, liveboards, or sets use this model",
                model_name=_model_name(m), model_guid=guid,
                recommendation="Review whether this model is needed or should be removed",
            ))
    return findings


def check_h7(corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """H7: Direct table connections — answers connected to tables, not models."""
    findings = []
    model_fqns = set()
    for m in corpus.models:
        for mt in _get_model_tables(m):
            fqn = mt.get("fqn", "")
            if fqn:
                model_fqns.add(fqn)

    for ans in corpus.answers:
        answer = ans.get("answer", {})
        aname = answer.get("name", "?")
        tables = answer.get("tables", [])
        for t in tables:
            fqn = t.get("fqn", "")
            if fqn and fqn not in model_fqns:
                findings.append(Finding(
                    angle="H", check_id="H7", check_name="DIRECT_TABLE_CONNECTION",
                    severity="MEDIUM",
                    title=f"Answer '{aname}' connects directly to table",
                    detail=f"FQN: {fqn} — bypasses the semantic layer (model)",
                    recommendation="Rebuild the answer against a model instead of a table",
                ))
    return findings


def check_h8(corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """H8: Formula promotion candidates — duplicated in answers but not in model."""
    findings = []
    model_formulas: dict[str, set[str]] = {}
    for m in corpus.models:
        guid = _model_guid(m)
        if not guid:
            continue
        exprs = {_normalise_expr(f.get("expr", "")) for f in _get_formulas(m)}
        model_formulas[guid] = exprs

    answer_formulas: dict[str, list[tuple[str, str]]] = {}
    for ans in corpus.answers:
        answer = ans.get("answer", {})
        data_source = answer.get("tables", [{}])[0].get("fqn", "") if answer.get("tables") else ""
        aname = answer.get("name", "?")
        for f in answer.get("formulas", []):
            expr = _normalise_expr(f.get("expr", ""))
            if expr:
                answer_formulas.setdefault(expr, []).append((aname, data_source))

    for expr, occurrences in answer_formulas.items():
        if len(occurrences) < 2:
            continue
        sources = {ds for _, ds in occurrences}
        for source in sources:
            in_model = any(
                expr in model_formulas.get(guid, set())
                for guid in model_formulas
            )
            if not in_model:
                answer_names = [n for n, ds in occurrences if ds == source]
                findings.append(Finding(
                    angle="H", check_id="H8", check_name="FORMULA_PROMOTION",
                    severity="HIGH",
                    title=f"Formula in {len(answer_names)} answers, not in model",
                    detail=f"Expression: {expr[:80]}... Answers: {', '.join(answer_names[:5])}",
                    recommendation="Run /ts-object-answer-promote to promote to the model",
                ))
    return findings


def check_h10_objects(corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """H10: Stale/temporary objects — object-level scan."""
    findings = []
    for m in corpus.metadata:
        name = m.get("metadata_name", "")
        desc = m.get("metadata_header", {}).get("description", "") or ""
        obj_type = m.get("metadata_type", "?")
        match = _detect_stale(name)
        if not match:
            for text in [desc]:
                match = _detect_stale(text)
                if match:
                    break
        if match:
            category, severity = match
            findings.append(Finding(
                angle="H", check_id="H10", check_name="STALE_OBJECT",
                severity="LOW",
                title=f"Stale {obj_type}: {name}",
                detail=f"Pattern: {category}",
                recommendation="Review for removal — cross-reference with usage data when available",
            ))
    return findings


def check_h10_columns(model: dict, _config: AuditConfig) -> list[Finding]:
    """H10: Stale/temporary objects — column-level scan within a model."""
    findings = []
    stale_cols = []
    for c in _get_columns(model):
        cname = c.get("name", "")
        match = _detect_stale(cname)
        if match:
            stale_cols.append((cname, match[0], match[1]))

    if not stale_cols:
        return []

    high_count = sum(1 for _, _, sev in stale_cols if sev == "HIGH")
    return [Finding(
        angle="H", check_id="H10", check_name="STALE_COLUMNS",
        severity="MEDIUM" if high_count > 5 else "LOW",
        title=f"{len(stale_cols)} stale-pattern columns ({high_count} high-confidence)",
        detail="; ".join(f"{n} ({cat})" for n, cat, _ in stale_cols[:10])
            + (f" ... and {len(stale_cols)-10} more" if len(stale_cols) > 10 else ""),
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Remove stale columns via /ts-dependency-manager or TML reimport",
    )]


def check_h11(model: dict, _config: AuditConfig) -> list[Finding]:
    """H11: Column group coverage — models with many columns but no data panel folders."""
    m = model.get("model", {})
    columns = _get_columns(model)
    col_count = len(columns)
    if col_count < 30:
        return []

    groups = m.get("column_groups", [])
    if groups:
        return []

    return [Finding(
        angle="H", check_id="H11", check_name="NO_COLUMN_GROUPS",
        severity="LOW" if col_count < 60 else "MEDIUM",
        title=f"{col_count} columns with no column groups defined",
        detail="Column groups organise the search bar into folders. "
               "Without them, users must scroll an unsorted list to find columns.",
        score=col_count,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Add column_groups to organise columns into logical folders (e.g. Measures, Dates, Customer)",
    )]


# ---------------------------------------------------------------------------
# P — Performance checks
# ---------------------------------------------------------------------------

def check_p2(model: dict, _config: AuditConfig) -> list[Finding]:
    """P2: Scalar formula density."""
    formulas = _get_formulas(model)
    columns = _get_columns(model)
    agg_formula_ids = {
        c.get("formula_id") for c in columns
        if c.get("formula_id") and c.get("properties", {}).get("aggregation")
    }
    scalars = [f for f in formulas if f.get("id") not in agg_formula_ids]
    count = len(scalars)
    if count <= 5:
        return []
    severity = "MEDIUM" if count > 10 else "LOW"
    return [Finding(
        angle="P", check_id="P2", check_name="SCALAR_FORMULA_DENSITY",
        severity=severity,
        title=f"{count} scalar formulas (no aggregation)",
        detail="Scalar formulas run at query time in the TS calculation engine, not pushed to warehouse",
        score=count,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Consider materializing as warehouse columns if performance is impacted",
    )]


def check_p3(model: dict, _config: AuditConfig) -> list[Finding]:
    """P3: Model filter progressiveness."""
    m = model.get("model", {})
    filters = m.get("filters", [])
    if not filters:
        return []
    non_progressive = [f for f in filters if not f.get("apply_on_tables")]
    if not non_progressive:
        return []
    return [Finding(
        angle="P", check_id="P3", check_name="NON_PROGRESSIVE_FILTER",
        severity="MEDIUM",
        title=f"{len(non_progressive)}/{len(filters)} filters lack apply_on_tables",
        detail="These filters run on every query regardless of which tables are involved",
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Add apply_on_tables to scope filters to relevant tables",
    )]


def check_p5(model: dict, _config: AuditConfig) -> list[Finding]:
    """P5: Date constraint coverage on fact tables."""
    m = model.get("model", {})
    constraints = m.get("constraints", [])
    has_date_constraint = any(
        c.get("constraint", [{}])[0].get("condition", [{}])[0].get("date_range_condition")
        for c in constraints
        if c.get("constraint")
    ) if constraints else False

    cbt = _columns_by_table(model)
    fact_tables = []
    for tname, cols in cbt.items():
        measures = sum(
            1 for c in cols
            if (c.get("properties", {}) or {}).get("column_type") == "MEASURE"
        )
        if measures >= 3:
            fact_tables.append(tname)

    if not fact_tables or has_date_constraint:
        return []
    return [Finding(
        angle="P", check_id="P5", check_name="NO_DATE_CONSTRAINT",
        severity="MEDIUM",
        title=f"No date constraints on model with {len(fact_tables)} fact table(s)",
        detail="Large fact tables without date constraints risk full table scans",
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Add date range constraints to ensure a date filter is applied",
    )]


def check_p8(model: dict, _config: AuditConfig) -> list[Finding]:
    """P8: Column sprawl (>75 columns)."""
    count = len(_get_columns(model))
    if count <= 75:
        return []
    return [Finding(
        angle="P", check_id="P8", check_name="COLUMN_SPRAWL",
        severity="MEDIUM",
        title=f"{count} columns (>75 threshold)",
        detail="Wide models produce wider GROUP BY and more complex query plans",
        score=count,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Split into domain-specific models or remove unused columns",
    )]


def check_p9(model: dict, _config: AuditConfig) -> list[Finding]:
    """P9: High-cardinality attribute indexing."""
    id_pattern = re.compile(r"(_id|_guid|_uuid|transaction_id|row_id|surrogate_key)$", re.I)
    columns = _get_columns(model)
    flagged = []
    for c in columns:
        cname = c.get("name", "")
        props = c.get("properties", {}) or {}
        if not id_pattern.search(cname):
            continue
        if props.get("column_type") != "ATTRIBUTE":
            continue
        idx = props.get("index_type", "DONT_INDEX")
        if idx != "DONT_INDEX":
            flagged.append((cname, idx))

    if not flagged:
        return []
    return [Finding(
        angle="P", check_id="P9", check_name="HIGH_CARDINALITY_INDEX",
        severity="MEDIUM",
        title=f"{len(flagged)} ID/GUID columns indexed as attributes",
        detail="Wastes storage, pollutes Spotter suggestions. "
            + "; ".join(f"{n} ({idx})" for n, idx in flagged[:10]),
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Set index_type to DONT_INDEX for ID columns",
    )]


def check_s10(model: dict, _config: AuditConfig) -> list[Finding]:
    """S10: RLS bypass as exception."""
    props = _get_properties(model)
    if not props.get("is_bypass_rls"):
        return []
    return [Finding(
        angle="S", check_id="S10", check_name="RLS_BYPASS",
        severity="MEDIUM",
        title="is_bypass_rls is true",
        detail="RLS bypass disables Row-Level Security — all users see all rows regardless of RLS rules. Legitimate for aggregate-only models but should be the exception.",
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Review whether RLS bypass is intentional",
    )]


def check_p11(model: dict, _config: AuditConfig) -> list[Finding]:
    """P11: Secure suggestions overhead."""
    props = _get_properties(model)
    spotter_cfg = props.get("spotter_config", {}) or {}
    if not spotter_cfg.get("is_spotter_enabled"):
        return []
    columns = _get_columns(model)
    indexed = sum(
        1 for c in columns
        if (c.get("properties", {}) or {}).get("index_type", "DONT_INDEX") != "DONT_INDEX"
    )
    if indexed <= 30:
        return []
    return [Finding(
        angle="P", check_id="P11", check_name="SECURE_SUGGESTIONS_OVERHEAD",
        severity="INFO",
        title=f"{indexed} indexed columns on Spotter-enabled model",
        detail="Each indexed column adds a DB lookup for suggestions. Informational — indexing is correct for searchable columns.",
        score=indexed,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Review whether all indexed columns need to be searchable",
    )]


def check_p13(model: dict, corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """P13: RLS rule density — many rules per table compound query cost."""
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    table_tmls = corpus.table_tmls_by_model.get(guid or "", [])

    for ttl in table_tmls:
        tbl_name = ttl.get("table", {}).get("name", "?")
        rls = ttl.get("table", {}).get("rls_rules", {})
        if not rls:
            continue
        rule_count = len(rls.get("rules", []))
        if rule_count <= 3:
            continue
        severity = "HIGH" if rule_count > 6 else "MEDIUM"
        findings.append(Finding(
            angle="P", check_id="P13", check_name="RLS_RULE_DENSITY",
            severity=severity,
            title=f"{rule_count} RLS rules on table {tbl_name}",
            detail="Each RLS rule evaluates independently on every query — cost compounds linearly",
            score=rule_count,
            model_name=name, model_guid=guid,
            recommendation="Review whether rules can be consolidated or simplified",
        ))
    return findings


def check_p14(model: dict, corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """P14: RLS formula complexity — functions prevent index/partition use."""
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    table_tmls = corpus.table_tmls_by_model.get(guid or "", [])

    for ttl in table_tmls:
        tbl_name = ttl.get("table", {}).get("name", "?")
        rls = ttl.get("table", {}).get("rls_rules", {})
        if not rls:
            continue
        for rule in rls.get("rules", []):
            expr = rule.get("expr", "")
            match = RLS_PERF_FUNCTION_RE.search(expr)
            if match:
                func_name = match.group(1).upper()
                findings.append(Finding(
                    angle="P", check_id="P14", check_name="RLS_FUNCTION_PERF",
                    severity="MEDIUM",
                    title=f"Function {func_name}() in RLS on {tbl_name}",
                    detail=f"Expression: {expr[:120]}. Functions in RLS prevent index/partition pruning.",
                    model_name=name, model_guid=guid,
                    recommendation="Materialise the function result as a warehouse column and filter on that",
                ))
    return findings


STRING_TYPES = {"VARCHAR", "CHAR", "TEXT", "STRING", "NVARCHAR", "NCHAR"}


def _get_table_col_casing(table_tml: dict) -> dict[str, str | None]:
    """Build {column_name: value_casing or None} for string columns."""
    tbl = table_tml.get("table", {})
    result = {}
    for c in tbl.get("columns", []):
        col_name = c.get("db_column_name", c.get("name", ""))
        dtype = (c.get("db_column_properties", {}) or {}).get("data_type", "")
        if dtype.upper() in STRING_TYPES:
            casing = (c.get("properties", {}) or {}).get("value_casing")
            result[col_name] = casing
    return result


def check_p15(model: dict, corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """P15: RLS column casing — VARCHAR RLS columns without UPPER/LOWER casing."""
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    table_tmls = corpus.table_tmls_by_model.get(guid or "", [])

    for ttl in table_tmls:
        tbl_name = ttl.get("table", {}).get("name", "?")
        rls_cols = _extract_rls_columns(ttl)
        if not rls_cols:
            continue
        col_casing = _get_table_col_casing(ttl)
        for col_name, _expr in rls_cols:
            if col_name not in col_casing:
                continue
            casing = col_casing[col_name]
            if casing in ("UPPER", "LOWER"):
                continue
            casing_display = casing if casing else "absent"
            findings.append(Finding(
                angle="P", check_id="P15", check_name="RLS_COLUMN_CASING",
                severity="MEDIUM",
                title=f"RLS on VARCHAR column {tbl_name}.{col_name} (value_casing={casing_display})",
                detail="Without UPPER or LOWER casing, the database cannot use indexes efficiently for RLS filtering",
                model_name=name, model_guid=guid,
                recommendation="Set value_casing to UPPER or LOWER on the underlying table column",
            ))
    return findings


IF_RE = re.compile(r"\bif\s*\(", re.I)


def _count_if_nesting(expr: str) -> int:
    """Count if() occurrences as a proxy for nesting depth."""
    return len(IF_RE.findall(expr))


def check_p16(model: dict, _config: AuditConfig) -> list[Finding]:
    """P16: Formula nesting depth — deeply nested if() conditionals."""
    findings = []
    formulas = _get_formulas(model)
    if not formulas:
        return findings
    for f in formulas:
        fname = f.get("name", "?")
        expr = f.get("expr", "")
        depth = _count_if_nesting(expr)
        if depth <= 3:
            continue
        severity = "LOW" if depth > 5 else "INFO"
        findings.append(Finding(
            angle="P", check_id="P16", check_name="FORMULA_NESTING_DEPTH",
            severity=severity,
            title=f"Formula '{fname}' has {depth} levels of if() nesting",
            detail="Each nesting level adds branching in the ThoughtSpot calculation engine at query time",
            score=depth,
            model_name=_model_name(model), model_guid=_model_guid(model),
            recommendation="Consider a CASE-style approach or materialising the logic in the warehouse",
        ))
    return findings


BRACKET_REF_RE = re.compile(r"\[([^\]]+)\]")


def _formula_chain_depth(formulas: list[dict]) -> tuple[int, list[str]]:
    """Find the longest formula-references-formula chain. Returns (depth, chain_names)."""
    formula_names = {f.get("name", "") for f in formulas}
    deps: dict[str, set[str]] = {}
    for f in formulas:
        fname = f.get("name", "")
        expr = f.get("expr", "")
        refs = set()
        for ref in BRACKET_REF_RE.findall(expr):
            if "::" not in ref and ref in formula_names and ref != fname:
                refs.add(ref)
        deps[fname] = refs

    max_depth = 0
    max_chain: list[str] = []
    for start in formula_names:
        visited: set[str] = set()
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        while stack:
            node, path = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            if len(path) > max_depth:
                max_depth = len(path)
                max_chain = path[:]
            for dep in deps.get(node, set()):
                if dep not in visited:
                    stack.append((dep, path + [dep]))

    return max_depth, max_chain


def check_p17(model: dict, _config: AuditConfig) -> list[Finding]:
    """P17: Formula reference chains — formulas referencing formulas."""
    formulas = _get_formulas(model)
    if not formulas:
        return []
    depth, chain = _formula_chain_depth(formulas)
    if depth <= 2:
        return []
    severity = "LOW" if depth > 3 else "INFO"
    chain_str = " → ".join(chain)
    return [Finding(
        angle="P", check_id="P17", check_name="FORMULA_CHAIN_DEPTH",
        severity=severity,
        title=f"Formula chain {depth} deep: {chain_str}",
        detail="Each link adds a computation layer at query time",
        score=depth,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Consider inlining or materialising intermediate steps in the warehouse",
    )]


def check_p18(model: dict, _config: AuditConfig) -> list[Finding]:
    """P18: COUNT_DISTINCT measures — most expensive aggregation type."""
    columns = _get_columns(model)
    cd_cols = [
        c.get("name", "?") for c in columns
        if (c.get("properties", {}) or {}).get("aggregation") == "COUNT_DISTINCT"
    ]
    if not cd_cols:
        return []
    col_list = ", ".join(cd_cols[:5])
    suffix = f" (+{len(cd_cols) - 5} more)" if len(cd_cols) > 5 else ""
    return [Finding(
        angle="P", check_id="P18", check_name="COUNT_DISTINCT_MEASURES",
        severity="INFO",
        title=f"{len(cd_cols)} column(s) use COUNT_DISTINCT",
        detail=f"Columns: {col_list}{suffix}. Most expensive aggregation on most warehouses.",
        score=len(cd_cols),
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Review whether approximate distinct (HLL) or pre-aggregation is viable",
    )]


def check_p19(model: dict, _config: AuditConfig) -> list[Finding]:
    """P19: Aggregate awareness — large models without pre-aggregated models configured."""
    m = model.get("model", {})
    mt = _get_model_tables(model)
    table_count = len(mt)
    if table_count < 5:
        return []

    agg_models = m.get("aggregated_models", [])
    if agg_models:
        return []

    join_count = sum(len(t.get("joins", [])) for t in mt)
    col_count = len(_get_columns(model))

    return [Finding(
        angle="P", check_id="P19", check_name="NO_AGGREGATE_AWARENESS",
        severity="INFO" if table_count < 10 else "LOW",
        title=f"No aggregate models configured ({table_count} tables, {join_count} joins)",
        detail="Aggregate awareness routes queries to pre-aggregated models when the "
               "query grain matches, reducing warehouse compute. Models with many tables "
               "and joins benefit most.",
        score=table_count,
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Consider creating aggregate models for common query patterns "
                       "(e.g. daily/weekly rollups) and associating them via aggregated_models",
    )]


# ---------------------------------------------------------------------------
# S — Security checks
# ---------------------------------------------------------------------------

def check_s1(model: dict, _config: AuditConfig) -> list[Finding]:
    """S1: PII column detection."""
    findings = []
    for c in _get_columns(model):
        cname = c.get("name", "")
        match = _detect_pii(cname)
        if match:
            category, severity = match
            findings.append(Finding(
                angle="S", check_id="S1", check_name="PII_DETECTED",
                severity=severity if severity == "CRITICAL" else "INFO",
                title=f"PII column: {cname} ({category})",
                detail=f"Heuristic match — verify this column contains {category} data",
                model_name=_model_name(model), model_guid=_model_guid(model),
                recommendation="Check S2–S4 for security posture on this column",
            ))
    return findings


def check_s2(model: dict, corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """S2: PII indexing without RLS."""
    findings = []
    guid = _model_guid(model)
    table_tmls = corpus.table_tmls_by_model.get(guid or "", [])

    tables_with_rls = set()
    for ttl in table_tmls:
        tbl = ttl.get("table", {})
        if tbl.get("rls_rules"):
            tables_with_rls.add(tbl.get("name", ""))

    for c in _get_columns(model):
        cname = c.get("name", "")
        if not _detect_pii(cname):
            continue
        props = c.get("properties", {}) or {}
        idx = props.get("index_type", "DONT_INDEX")
        if idx == "DONT_INDEX":
            continue
        cid = c.get("column_id", "")
        table_name = cid.split("::")[0] if "::" in cid else ""
        has_rls = table_name in tables_with_rls
        severity = "INFO" if has_rls else "HIGH"
        findings.append(Finding(
            angle="S", check_id="S2", check_name="PII_INDEXED_NO_RLS",
            severity=severity,
            title=f"PII indexed: {cname} ({idx})" + (" — table has RLS" if has_rls else " — NO RLS"),
            detail=f"Indexed PII exposes values in Spotter autocomplete. Table: {table_name}",
            model_name=_model_name(model), model_guid=_model_guid(model),
            recommendation="" if has_rls else "Add RLS to the backing table or set index_type to DONT_INDEX",
        ))
    return findings


def check_s4(model: dict, _config: AuditConfig) -> list[Finding]:
    """S4: RLS bypass + PII."""
    props = _get_properties(model)
    if not props.get("is_bypass_rls"):
        return []
    pii_cols = [
        c.get("name", "") for c in _get_columns(model) if _detect_pii(c.get("name", ""))
    ]
    if not pii_cols:
        return []
    return [Finding(
        angle="S", check_id="S4", check_name="RLS_BYPASS_WITH_PII",
        severity="HIGH",
        title=f"RLS bypass + {len(pii_cols)} PII columns",
        detail=f"is_bypass_rls=true AND model contains PII: {', '.join(pii_cols[:10])}",
        model_name=_model_name(model), model_guid=_model_guid(model),
        recommendation="Remove RLS bypass or remove PII columns from the model",
    )]


def check_s5(model: dict, _config: AuditConfig) -> list[Finding]:
    """S5: Credentials in analytics."""
    findings = []
    cred_re = re.compile(r"password|passwd|secret[-_]?key|api[-_]?key|private[-_]?key", re.I)
    for c in _get_columns(model):
        cname = c.get("name", "")
        if cred_re.search(cname):
            findings.append(Finding(
                angle="S", check_id="S5", check_name="CREDENTIAL_IN_MODEL",
                severity="CRITICAL",
                title=f"Credential column: {cname}",
                detail="Should never be in an analytics model",
                model_name=_model_name(model), model_guid=_model_guid(model),
                recommendation="Remove immediately from the model",
            ))
    return findings


def _extract_rls_columns(table_tml: dict) -> list[tuple[str, str]]:
    """Extract (column_name, expression) pairs from a table's rls_rules."""
    tbl = table_tml.get("table", {})
    rls = tbl.get("rls_rules", {})
    if not rls:
        return []
    col_ref_re = re.compile(r"\[([^]]+)::([^]]+)\]")
    results = []
    rules = rls.get("rules", [])
    for rule in rules:
        expr = rule.get("expr", "")
        for _path_id, col_name in col_ref_re.findall(expr):
            results.append((col_name, expr))
    return results


def _get_table_col_types(table_tml: dict) -> dict[str, str]:
    """Build {column_name: data_type} from a table TML."""
    tbl = table_tml.get("table", {})
    result = {}
    for c in tbl.get("columns", []):
        name = c.get("db_column_name", c.get("name", ""))
        dtype = (c.get("db_column_properties", {}) or {}).get("data_type", "")
        if name and dtype:
            result[name] = dtype
    return result


RLS_FUNCTION_RE = re.compile(
    r"\b(UPPER|LOWER|TRIM|SUBSTR|SUBSTRING|CONCAT|REPLACE|CAST|CONVERT|COALESCE|"
    r"NVL|IFNULL|TO_CHAR|TO_VARCHAR|TO_NUMBER|TO_DATE|DATE_TRUNC|LEFT|RIGHT)\s*\(",
    re.I,
)

RLS_PERF_FUNCTION_RE = re.compile(
    r"\b(UPPER|LOWER|TRIM|SUBSTR|SUBSTRING|CONCAT|REPLACE|CAST|CONVERT|"
    r"COALESCE|NVL|IFNULL|TO_CHAR|TO_VARCHAR|TO_NUMBER|TO_DATE|DATE_TRUNC|"
    r"LEFT|RIGHT|CONTAINS|STARTS_WITH|ENDS_WITH|IF|IN)\s*\(",
    re.I,
)


def check_s8(model: dict, corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """S8: RLS column data type quality — VARCHAR filters are slower than integer."""
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    table_tmls = corpus.table_tmls_by_model.get(guid or "", [])

    for ttl in table_tmls:
        tbl_name = ttl.get("table", {}).get("name", "?")
        col_types = _get_table_col_types(ttl)
        rls_cols = _extract_rls_columns(ttl)

        for col_name, _expr in rls_cols:
            dtype = col_types.get(col_name, "")
            if not dtype:
                continue
            dtype_upper = dtype.upper()
            if dtype_upper in ("VARCHAR", "CHAR", "TEXT", "STRING", "NVARCHAR", "NCHAR"):
                findings.append(Finding(
                    angle="S", check_id="S8", check_name="RLS_VARCHAR_FILTER",
                    severity="MEDIUM",
                    title=f"RLS on VARCHAR column: {tbl_name}.{col_name}",
                    detail=f"data_type={dtype}. Integer RLS columns are 2-5x faster for filter evaluation.",
                    model_name=name, model_guid=guid,
                    recommendation="Consider an integer surrogate key for RLS filtering",
                ))

    return findings


def check_s9(model: dict, corpus: Corpus, _config: AuditConfig) -> list[Finding]:
    """S9: RLS expression complexity — functions prevent pushdown."""
    findings = []
    name = _model_name(model)
    guid = _model_guid(model)
    table_tmls = corpus.table_tmls_by_model.get(guid or "", [])

    for ttl in table_tmls:
        tbl_name = ttl.get("table", {}).get("name", "?")
        rls = ttl.get("table", {}).get("rls_rules", {})
        if not rls:
            continue
        for rule in rls.get("rules", []):
            expr = rule.get("expr", "")
            match = RLS_FUNCTION_RE.search(expr)
            if match:
                func_name = match.group(1).upper()
                findings.append(Finding(
                    angle="S", check_id="S9", check_name="RLS_FUNCTION_IN_EXPR",
                    severity="HIGH",
                    title=f"Function in RLS expression: {func_name}() on {tbl_name}",
                    detail=f"Expression: {expr[:120]}. Functions in RLS prevent filter pushdown to the database.",
                    model_name=name, model_guid=guid,
                    recommendation="Materialise the function result as a column and RLS on that instead",
                ))

    return findings


def check_d12(models: list[dict], _config: AuditConfig) -> list[Finding]:
    """D12: Conformed dimension divergence — same db column classified differently across models."""
    findings = []
    col_types: dict[str, dict[str, set[str]]] = {}

    for m in models:
        mname = _model_name(m)
        for c in _get_columns(m):
            db_col = c.get("db_column_name", c.get("name", ""))
            ctype = (c.get("properties", {}) or {}).get("column_type", "")
            if db_col and ctype:
                col_types.setdefault(db_col, {}).setdefault(ctype, set()).add(mname)

    for db_col, type_map in col_types.items():
        if len(type_map) > 1:
            detail_parts = []
            for ctype, model_names in type_map.items():
                detail_parts.append(f"{ctype} in {', '.join(sorted(model_names)[:3])}")
            findings.append(Finding(
                angle="D", check_id="D12", check_name="CONFORMED_DIM_DIVERGENCE",
                severity="MEDIUM",
                title=f"Divergent classification: {db_col}",
                detail="; ".join(detail_parts),
                recommendation="Standardise column_type across models so the same column behaves consistently",
            ))
    return findings


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_audit(corpus: Corpus, config: AuditConfig) -> list[Finding]:
    """Run all selected angle checks and return findings."""
    findings: list[Finding] = []
    angles = set(config.angles)

    for m in corpus.models:
        if "A" in angles:
            findings.extend(check_a1(m, config))
            findings.extend(check_a2(m, config))
            findings.extend(check_a3(m, config))
            findings.extend(check_a4(m, config))
            findings.extend(check_a5(m, config))

        if "D" in angles:
            findings.extend(check_d1(m, config))
            findings.extend(check_d2(m, corpus, config))
            findings.extend(check_d3(m, config))
            findings.extend(check_d4(m, config))
            findings.extend(check_d5(m, config))
            findings.extend(check_d6(m, config))
            findings.extend(check_d9(m, config))
            findings.extend(check_d10(m, config))
            findings.extend(check_d11(m, config))

        if "H" in angles:
            findings.extend(check_h1(m, config))
            findings.extend(check_h2(m, config))
            findings.extend(check_h3(m, config))
            findings.extend(check_h10_columns(m, config))
            findings.extend(check_h11(m, config))

        if "P" in angles:
            findings.extend(check_p2(m, config))
            findings.extend(check_p3(m, config))
            findings.extend(check_p5(m, config))
            findings.extend(check_p8(m, config))
            findings.extend(check_p9(m, config))
            findings.extend(check_p11(m, config))
            findings.extend(check_p13(m, corpus, config))
            findings.extend(check_p14(m, corpus, config))
            findings.extend(check_p15(m, corpus, config))
            findings.extend(check_p16(m, config))
            findings.extend(check_p17(m, config))
            findings.extend(check_p18(m, config))
            findings.extend(check_p19(m, config))

        if "S" in angles:
            findings.extend(check_s2(m, corpus, config))
            findings.extend(check_s4(m, config))
            findings.extend(check_s5(m, config))
            findings.extend(check_s8(m, corpus, config))
            findings.extend(check_s9(m, corpus, config))
            findings.extend(check_s10(m, config))

    if "D" in angles:
        findings.extend(check_d7(corpus.models, config))
        findings.extend(check_d8(corpus, config))
        findings.extend(check_d12(corpus.models, config))

    if "H" in angles:
        findings.extend(check_h4(corpus, config))
        findings.extend(check_h7(corpus, config))
        findings.extend(check_h8(corpus, config))
        findings.extend(check_h10_objects(corpus, config))

    return findings


def summarise(findings: list[Finding]) -> dict[str, Any]:
    """Produce a summary from findings."""
    by_severity: dict[str, int] = {}
    by_angle: dict[str, int] = {}
    by_model: dict[str, dict[str, str]] = {}

    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_angle[f.angle] = by_angle.get(f.angle, 0) + 1
        if f.model_name:
            model_angles = by_model.setdefault(f.model_name, {})
            current = model_angles.get(f.angle, "GREEN")
            rank = {"GREEN": 0, "INFO": 1, "LOW": 2, "MEDIUM": 3, "HIGH": 4, "CRITICAL": 5}
            if rank.get(f.severity, 0) > rank.get(current, 0):
                model_angles[f.angle] = f.severity

    return {
        "total": len(findings),
        "by_severity": by_severity,
        "by_angle": by_angle,
        "model_heatmap": by_model,
    }
