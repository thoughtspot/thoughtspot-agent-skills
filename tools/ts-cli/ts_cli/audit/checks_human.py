from __future__ import annotations

import re
from collections import defaultdict

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "human"

_NAME_ANTI = re.compile(
    r"^col\d+$|^field[-_]?\d+$|^val\d*$|^tmp[-_]|^\d",
    re.IGNORECASE,
)
_NAME_ANTI_UPPER_ONLY = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$")

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


def _stale_match(name):
    if _STALE_NAME_SAFE.search(name):
        return False
    return bool(_STALE_NAME.search(name))


def _normalize_expr(expr):
    return re.sub(r"\s+", " ", expr.strip().lower())


def check_h1(ctx: AuditContext) -> list:
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


def check_h2(ctx: AuditContext) -> list:
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


def check_h3(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        formulas = m.get("formulas") or []
        formula_exprs = " ".join(f.get("expr", "") for f in formulas)
        mt = m.get("model_tables") or []
        joined = set()
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


def check_h4(ctx: AuditContext) -> list:
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


def check_h5(ctx: AuditContext) -> list:
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


def check_h6(ctx: AuditContext) -> list:
    return []


def check_h7(ctx: AuditContext) -> list:
    findings = []
    for answer in ctx.answers:
        a = answer.get("answer", {})
        aname = a.get("name", "")
        for tref in (a.get("tables") or []):
            fqn = tref.get("fqn", "")
            if fqn and not any(fqn in str(m) for m in ctx.models):
                findings.append(Finding(
                    check_id="H7", angle=_ANGLE, severity="MEDIUM",
                    object_type="answer", object_name=aname,
                    object_guid=answer.get("guid", ""),
                    detail=f"Answer connects directly to table '{fqn}', bypassing the model layer",
                ))
    return findings


def check_h8(ctx: AuditContext) -> list:
    findings = []
    if not ctx.answers:
        return findings
    model_formulas = set()
    for model in ctx.models:
        for f in (model.get("model", {}).get("formulas") or []):
            model_formulas.add(_normalize_expr(f.get("expr", "")))
    answer_formulas = defaultdict(list)
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


def check_h9(ctx: AuditContext) -> list:
    findings = []
    if not ctx.answers:
        return findings
    model_formulas = {}
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


def check_h10(ctx: AuditContext) -> list:
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


ALL_CHECKS = [
    check_h1, check_h2, check_h3, check_h4, check_h5,
    check_h6, check_h7, check_h8, check_h9, check_h10,
]
