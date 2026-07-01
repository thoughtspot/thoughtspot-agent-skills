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
    return {
        "findings": [f.to_dict() for f in findings],
        "summary": build_summary(findings, checks_run, len(ctx.models), len(ctx.tables)),
    }
