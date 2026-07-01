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


def _find_pii_columns(columns):
    results = []
    for c in columns:
        name = c.get("name", "")
        for pattern, category, confidence in _PII_PATTERNS:
            if pattern.search(name):
                results.append((c, category, confidence))
                break
    return results


def check_s1(ctx: AuditContext) -> list:
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


def check_s2(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        pii = _find_pii_columns(m.get("columns") or [])
        table_has_rls = {}
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
                       f"{' (table has RLS)' if has_rls else ' WITHOUT table RLS'}",
            ))
    return findings


def check_s3(ctx: AuditContext) -> list:
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


def check_s4(ctx: AuditContext) -> list:
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
                detail=f"RLS bypass enabled AND model contains {len(pii)} PII column(s)",
                metric=len(pii),
            ))
    return findings


def check_s5(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        for c in (m.get("columns") or []):
            name = c.get("name", "")
            match = _CREDENTIAL_PATTERNS.search(name)
            if match:
                severity = "CRITICAL" if match.group().lower() != "token" else "HIGH"
                findings.append(Finding(
                    check_id="S5", angle=_ANGLE, severity=severity,
                    object_type="column", object_name=c.get("name", ""),
                    object_guid=ctx.guid_for(model),
                    detail=f"Credential column '{c.get('name', '')}' in analytics model",
                ))
    return findings


def check_s8(ctx: AuditContext) -> list:
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
                        detail=f"VARCHAR RLS column '{col_name}'",
                    ))
    return findings


def check_s9(ctx: AuditContext) -> list:
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


def check_s10(ctx: AuditContext) -> list:
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
