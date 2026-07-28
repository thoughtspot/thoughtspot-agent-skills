from __future__ import annotations

from typing import List

from ts_cli.migrate.classify import render_effort_markdown
from ts_cli.migrate.schema import (
    ModelComparison, MATCHED, GAP, GAP_BLOCKER, BINDING_MISMATCH, READY,
)


def build_report(comparisons: List[ModelComparison]) -> dict:
    models = []
    overall_ready = True
    for c in comparisons:
        counts = {MATCHED: 0, GAP: 0, GAP_BLOCKER: 0, BINDING_MISMATCH: 0}
        for r in c.rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        blockers = [r.tenant_column for r in c.rows
                    if r.status == GAP_BLOCKER and not r.published_column]
        if c.readiness != READY:
            overall_ready = False
        models.append({
            "model": c.model_name,
            "source_guid": c.source_model_guid,
            "target_guid": c.target_model_guid,
            "readiness": c.readiness,
            "column_counts": counts,
            "blocker_columns": blockers,
            "dependent_count": len(c.dependents),
            "dependents": c.dependents,
            "effort": c.effort,
            "classified_dependents": c.classified_dependents,
        })
    return {"overall_ready": overall_ready, "models": models}


def render_markdown(report: dict) -> str:
    verdict = "READY" if report["overall_ready"] else "NEEDS MAPPING"
    lines = ["# Org Migration Audit", "", f"**Overall:** {verdict}", ""]
    for m in report["models"]:
        lines.append(f"## {m['model']} — {m['readiness']}")
        cc = m["column_counts"]
        lines.append(
            f"- Columns: {cc.get(MATCHED, 0)} matched, {cc.get(GAP, 0)} gap, "
            f"{cc.get(GAP_BLOCKER, 0)} gap-blocker, {cc.get(BINDING_MISMATCH, 0)} binding-mismatch"
        )
        # The rewrite count, NOT the object count, is what sizes the job -- content on a
        # View is free. Leading with the object count would make a cheap tenant look
        # expensive and hide which wave to schedule first.
        effort = m.get("effort") or {}
        if effort:
            lines.append(f"- Dependents: {effort.get('dependents', 0)}, of which "
                         f"**{effort.get('needs_rewrite', 0)} need rewriting**")
            if effort.get("shielded_by_views"):
                lines.append(
                    f"- {effort['shielded_by_views']} shielded by "
                    f"{len(effort.get('views_to_repoint') or [])} View(s) — free")
        else:
            lines.append(f"- Dependents to migrate: {m['dependent_count']}")
        if m["blocker_columns"]:
            lines.append(f"- **Blockers (need mapping):** {', '.join(m['blocker_columns'])}")
        lines.append("")
        if effort:
            lines.append(render_effort_markdown(effort))
    return "\n".join(lines)
