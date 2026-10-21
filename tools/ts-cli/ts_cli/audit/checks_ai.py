from __future__ import annotations

import re

from ts_cli.audit import assessment
from ts_cli.audit.context import AuditContext, nl_instructions
from ts_cli.audit.findings import Finding

_ANGLE = "ai"

_NAME_ANTI = re.compile(
    r"^col\d+$|^field[-_]?\d+$|^val\d*$|^tmp[-_]|^\d",
    re.IGNORECASE,
)
_NAME_ANTI_UPPER = re.compile(r"^[A-Z][A-Z0-9]*_[A-Z0-9_]+$")


def _has_synonyms(col: dict) -> bool:
    """Model TML keeps `synonyms` under `properties:` — 13,375 of 24,263 columns
    across 599 exported Models on the SE demo cluster (2026-10-21), and 0 at the
    column root. A2 and A5 read the root only, so every Model scored 0% synonyms.
    The root is still read as a fallback for hand-built fixtures."""
    props = col.get("properties") or {}
    return bool((props.get("synonyms") if isinstance(props, dict) else None)
                or col.get("synonyms"))


def check_a1(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        if not cols:
            continue
        described = sum(1 for c in cols if (c.get("description") or "").strip())
        pct = (described / len(cols)) * 100
        severity = assessment.coverage_severity(ctx.assessment, "A1", pct)
        if severity is None:
            continue
        findings.append(Finding(
            check_id="A1", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"{described}/{len(cols)} columns have descriptions ({pct:.0f}%)",
            metric=round(pct, 1),
            threshold=assessment.threshold(ctx.assessment, "A1"),
        ))
    return findings


def check_a2(ctx: AuditContext) -> list:
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        cols = m.get("columns") or []
        if not cols:
            continue
        with_syn = sum(1 for c in cols if _has_synonyms(c))
        pct = (with_syn / len(cols)) * 100
        severity = assessment.coverage_severity(ctx.assessment, "A2", pct)
        if severity is None:
            continue
        findings.append(Finding(
            check_id="A2", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=f"{with_syn}/{len(cols)} columns have synonyms ({pct:.0f}%)",
            metric=round(pct, 1),
            threshold=assessment.threshold(ctx.assessment, "A2"),
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
            nl_instructions(instr)
            or (m.get("model_instructions", {}).get("data_model_instructions") or "").strip()
        )
        if not has_instructions:
            findings.append(Finding(
                check_id="A3", angle=_ANGLE,
                severity=assessment.presence_severity(ctx.assessment, "A3"),
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
                check_id="A4", angle=_ANGLE,
                severity=assessment.presence_severity(ctx.assessment, "A4"),
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
        syn_pct = (sum(1 for c in cols if _has_synonyms(c)) / total) * 100
        guid = ctx.guid_for(model)
        ai_instr = ctx.ai_instructions.get(guid, {}) if guid in ctx.ai_instructions else {}
        has_ai = bool(
            nl_instructions(ai_instr)
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


def _visible_measures(cols: list) -> list:
    out = []
    for c in cols:
        props = c.get("properties") or {}
        if not isinstance(props, dict) or props.get("is_hidden"):
            continue
        if str(props.get("column_type") or "").upper() == "MEASURE":
            out.append(c)
    return out


def check_a6(ctx: AuditContext) -> list:
    """Measure AI context coverage — `properties.ai_context` on visible MEASURE columns.

    The coach's ai_context schema makes it REQUIRED for every measure (`additivity`,
    `time_basis`, `grain_keys`: an external SQL agent cannot aggregate a semi-additive
    balance or a ratio correctly without them) and optional, or wrong, for most
    attributes (a surrogate key should carry none). So coverage is measured over
    measures only; a whole-model percentage would penalise the correct choice to leave
    an ID column bare. Hidden columns are not searched, so they are not counted.
    """
    findings = []
    for model in ctx.models:
        m = model.get("model", {})
        measures = _visible_measures(m.get("columns") or [])
        if not measures:
            continue
        missing = [c.get("name", "?") for c in measures
                   if not str((c.get("properties") or {}).get("ai_context") or "").strip()]
        covered = len(measures) - len(missing)
        pct = (covered / len(measures)) * 100
        severity = assessment.coverage_severity(ctx.assessment, "A6", pct)
        if severity is None:
            continue
        shown = ", ".join(missing[:5]) + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else "")
        findings.append(Finding(
            check_id="A6", angle=_ANGLE, severity=severity,
            object_type="model", object_name=m.get("name", ""),
            object_guid=ctx.guid_for(model),
            detail=(f"{covered}/{len(measures)} measures have AI context ({pct:.0f}%) — "
                    f"missing: {shown}"),
            metric=round(pct, 1),
            threshold=assessment.threshold(ctx.assessment, "A6"),
        ))
    return findings


ALL_CHECKS = [check_a1, check_a2, check_a3, check_a4, check_a5, check_a6]
