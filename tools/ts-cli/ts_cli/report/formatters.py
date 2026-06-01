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


def render_md(report: Report) -> str:
    """Stub — implemented in F3."""
    raise NotImplementedError
