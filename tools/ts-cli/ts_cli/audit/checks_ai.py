from __future__ import annotations

import re

from ts_cli.audit.context import AuditContext
from ts_cli.audit.findings import Finding

_ANGLE = "ai"

_NAME_ANTI = re.compile(
    r"^col\d+$|^field[-_]?\d+$|^val\d*$|^tmp[-_]|^\d",
    re.IGNORECASE,
)
_NAME_ANTI_UPPER = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$")


def check_a1(ctx: AuditContext) -> list:
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


def check_a2(ctx: AuditContext) -> list:
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


def check_a3(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        guid = ctx.guid_for(model)
        if guid not in ctx.ai_instructions:
            continue
        instr = ctx.ai_instructions[guid]
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


def check_a4(ctx: AuditContext) -> list:
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


def check_a5(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        total = len(cols) if cols else 1
        desc_pct = (sum(1 for c in cols if (c.get("description") or "").strip()) / total) * 100
        syn_pct = (sum(1 for c in cols if (c.get("synonyms") or [])) / total) * 100
        guid = ctx.guid_for(model)
        ai_instr = ctx.ai_instructions.get(guid, {}) if guid in ctx.ai_instructions else {}
        has_ai = bool(
            ai_instr.get("instructions")
            or (m.get("model_instructions", {}).get("data_model_instructions") or "").strip()
        )
        has_desc = bool((m.get("description") or "").strip())
        anti = sum(1 for c in cols if _NAME_ANTI.match(c.get("name", "")) or _NAME_ANTI_UPPER.match(c.get("name", "")))
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
