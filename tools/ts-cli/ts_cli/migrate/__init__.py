from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from ts_cli.commands.tml import detect_tml_type
from ts_cli.migrate import classify, discover
from ts_cli.migrate.match import compare_model
from ts_cli.migrate.mapping import write_mapping
from ts_cli.migrate.report import build_report, render_markdown


def run_audit(source_client, target_client, model_guids: List[str], out_dir: str,
              source_owner_org_id: Optional[int] = None) -> dict:
    """Compare each source Model against its published counterpart in the target Org.

    `source_owner_org_id` is what stops a **same-Org** run pairing a Model with ITSELF.
    Pass `None` only when the two clients are on different clusters, where an Org id from
    one cluster means nothing on the other (see `discover.select_target`).
    """
    comparisons = []
    for mg in model_guids:
        src_doc = discover.export_parsed(source_client, mg)
        section = src_doc.get(detect_tml_type(src_doc)) or {}
        model_name = section.get("name", mg)
        src_cols = discover.model_columns(source_client, mg, doc=src_doc)
        # Follow through Views: single-hop hides everything a View shields, which
        # is exactly what breaks if a View is missed.
        dependents = discover.dependents_through_views(source_client, mg)

        # ONE export, shared by the column scan and the dependent classification.
        dep_docs = discover.export_dependents(source_client, dependents)
        used = discover.used_column_names_in(dep_docs, {c.name for c in src_cols})

        # What each dependent SITS ON decides what it costs: content on a View is free,
        # because repointing the View preserves the names its dependents see.
        refs = [classify.source_refs(d) for d in dep_docs]
        kinds = {g: classify.kind_of(st) for g, st in discover.subtypes_by_guid(
            source_client, {r for rs in refs for r in rs}).items()}
        classified = [
            classify.classify_dependent(dep.get("guid", ""), dep.get("name", ""),
                                        dep.get("type", ""), ref, kinds)
            for dep, ref in zip(dependents, refs)]
        effort = classify.build_effort(classified)

        # Never the source object itself: in a same-Org run the tenant's own Model and the
        # published master share a name, and a bare name lookup returns whichever the
        # search happens to list first.
        target_guid = discover.find_target_model(
            target_client, model_name,
            exclude_owner_org_id=source_owner_org_id, exclude_guid=mg)
        target_cols = discover.model_columns(target_client, target_guid) if target_guid else []
        comparison = compare_model(model_name, mg, target_guid, src_cols, target_cols,
                                   used, dependents)
        comparison.effort = effort
        comparison.classified_dependents = classified
        comparisons.append(comparison)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_mapping(out / "column-mapping.csv", comparisons)
    report = build_report(comparisons)
    (out / "audit-report.json").write_text(json.dumps(report, indent=2))
    (out / "audit-report.md").write_text(render_markdown(report))
    return report
