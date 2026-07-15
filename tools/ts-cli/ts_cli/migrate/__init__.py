from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ts_cli.commands.tml import detect_tml_type
from ts_cli.migrate import discover
from ts_cli.migrate.match import compare_model
from ts_cli.migrate.mapping import write_mapping
from ts_cli.migrate.report import build_report, render_markdown


def run_audit(source_client, target_client, model_guids: List[str], out_dir: str) -> dict:
    comparisons = []
    for mg in model_guids:
        src_doc = discover.export_parsed(source_client, mg)
        section = src_doc.get(detect_tml_type(src_doc)) or {}
        model_name = section.get("name", mg)
        src_cols = discover.model_columns(source_client, mg, doc=src_doc)
        dependents = discover.list_dependents(source_client, mg)
        used = discover.used_column_names(source_client, dependents, {c.name for c in src_cols})
        target_guid = discover.find_model_by_name(target_client, model_name)
        target_cols = discover.model_columns(target_client, target_guid) if target_guid else []
        comparisons.append(
            compare_model(model_name, mg, target_guid, src_cols, target_cols, used, dependents)
        )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_mapping(out / "column-mapping.csv", comparisons)
    report = build_report(comparisons)
    (out / "audit-report.json").write_text(json.dumps(report, indent=2))
    (out / "audit-report.md").write_text(render_markdown(report))
    return report
