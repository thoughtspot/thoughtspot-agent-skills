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
    """Stub — implemented in F2."""
    raise NotImplementedError


def render_md(report: Report) -> str:
    """Stub — implemented in F3."""
    raise NotImplementedError
