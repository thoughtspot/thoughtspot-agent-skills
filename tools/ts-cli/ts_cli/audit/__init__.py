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


def build_corpus(ctx, cluster_url: str = "", profile_name: str = "",
                 angles: Optional[list] = None) -> dict:
    angles = angles or list(ANGLE_MODULES.keys())
    models_out = []
    for model in ctx.models:
        m = model.get("model", {})
        guid = model.get("guid", m.get("guid", ""))
        model_tables = m.get("model_tables") or []
        models_out.append({
            "guid": guid,
            "name": m.get("name", ""),
            "table_count": len(model_tables),
            "column_count": len(m.get("columns") or []),
            "formula_count": len(m.get("formulas") or []),
            "join_count": len(m.get("joins") or []),
            "join_depth": _calc_join_depth(m),
            "model_tables": [
                {"name": mt.get("name", ""), "fqn": mt.get("fqn", "")}
                for mt in model_tables
            ],
        })

    table_reuse = _build_table_reuse_from_ctx(models_out)
    model_overlaps = _build_overlaps_from_ctx(models_out)

    return {
        "cluster_url": cluster_url,
        "profile_name": profile_name,
        "audit_date": "",
        "angles_run": list(angles),
        "models": models_out,
        "table_reuse": table_reuse,
        "model_overlaps": model_overlaps,
        "dependents": dict(ctx.dependents),
    }


def _calc_join_depth(model_data: dict) -> int:
    joins = model_data.get("joins") or []
    if not joins:
        return 0
    tables = {mt.get("name", "") for mt in (model_data.get("model_tables") or [])}
    graph = {}
    for j in joins:
        src = j.get("source", j.get("name", ""))
        dest = j.get("destination", j.get("with", ""))
        if src and dest:
            graph.setdefault(src, []).append(dest)
            graph.setdefault(dest, []).append(src)
    if not graph:
        return len(joins)
    max_depth = 0
    for start in tables:
        if start not in graph:
            continue
        visited = {start}
        queue = [(start, 0)]
        while queue:
            node, depth = queue.pop(0)
            max_depth = max(max_depth, depth)
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
    return max_depth


def _build_table_reuse_from_ctx(models: list) -> list:
    fqn_to_models = {}
    for m in models:
        for mt in m["model_tables"]:
            fqn = mt["fqn"]
            if fqn:
                fqn_to_models.setdefault(fqn, []).append(
                    {"name": m["name"], "guid": m["guid"]}
                )
    return [
        {"fqn": fqn, "name": fqn.rsplit(".", 1)[-1] if "." in fqn else fqn,
         "models": mlist}
        for fqn, mlist in fqn_to_models.items()
        if len(mlist) > 1
    ]


def _build_overlaps_from_ctx(models: list) -> list:
    overlaps = []
    for i, a in enumerate(models):
        a_fqns = {mt["fqn"] for mt in a["model_tables"] if mt["fqn"]}
        for b in models[i + 1:]:
            b_fqns = {mt["fqn"] for mt in b["model_tables"] if mt["fqn"]}
            shared = a_fqns & b_fqns
            if len(shared) < 2:
                continue
            union = a_fqns | b_fqns
            jaccard = len(shared) / len(union) if union else 0
            if jaccard == 1.0:
                otype = "identical"
            elif shared == a_fqns or shared == b_fqns:
                otype = "subset"
            elif jaccard >= 0.5:
                otype = "high_overlap"
            else:
                otype = "conformed_reuse"
            overlaps.append({
                "model_a": {"name": a["name"], "guid": a["guid"]},
                "model_b": {"name": b["name"], "guid": b["guid"]},
                "jaccard": round(jaccard, 3),
                "shared_table_count": len(shared),
                "total_tables_a": len(a_fqns),
                "total_tables_b": len(b_fqns),
                "shared_tables": sorted(
                    fqn.rsplit(".", 1)[-1] if "." in fqn else fqn for fqn in shared
                ),
                "type": otype,
            })
    return overlaps


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

    corpus = build_corpus(
        ctx,
        cluster_url=client.base_url,
        profile_name=client._profile_name,
        angles=angles,
    )

    return {
        "findings": [f.to_dict() for f in findings],
        "summary": build_summary(findings, checks_run, len(ctx.models), len(ctx.tables)),
        "corpus": corpus,
    }
