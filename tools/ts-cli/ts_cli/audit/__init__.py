from __future__ import annotations

from typing import Optional

from ts_cli.audit import checks_ai, checks_data, checks_human, checks_perf, checks_security
from ts_cli.audit.context import build_context
from ts_cli.audit.erd import build_erd_for_audit
from ts_cli.audit.findings import CHECK_META, Finding, build_summary

ANGLE_MODULES = {
    "A": checks_ai,
    "D": checks_data,
    "H": checks_human,
    "P": checks_perf,
    "S": checks_security,
}


_SEV_MAP = {"CRITICAL": "crit", "HIGH": "warn", "MEDIUM": "warn", "LOW": "info", "INFO": "info"}


def _inject_findings_into_erd(corpus: dict, findings: list) -> None:
    """Inject audit findings into ERD model data so the ERD renderer can display them."""
    models = corpus.get("models") or []
    guid_to_model = {m["guid"]: m for m in models}
    for f in findings:
        guid = f.object_guid
        model = guid_to_model.get(guid)
        if not model:
            continue
        erd = model.get("erd")
        if not erd:
            continue
        table_names = {t["id"] for t in erd.get("tables", [])}
        target = ""
        detail_lower = f.detail.lower()
        for tn in table_names:
            if tn.lower() in detail_lower:
                target = tn
                break
        erd_finding = {
            "sev": _SEV_MAP.get(f.severity, "info"),
            "check": f.check_id,
            "title": CHECK_META.get(f.check_id, {}).get("desc", f.check_id),
            "where": f.object_name,
            "target": target,
            "detail": f.detail,
            "rec": CHECK_META.get(f.check_id, {}).get("thresholds", ""),
        }
        erd["findings"].append(erd_finding)


_SOURCE_PREFIXES = {
    "SFDC": "Salesforce", "SF_": "Salesforce", "HUB_": "HubSpot",
    "GA_": "Google Analytics", "GADS": "Google Ads", "FB_": "Facebook",
    "STRIPE": "Stripe", "NETSUITE": "NetSuite",
    "JIRA": "Jira", "ZD_": "Zendesk", "ZENDESK": "Zendesk",
    "SHOPIFY": "Shopify", "SAP_": "SAP", "MARKETO": "Marketo",
    "HUBSPOT": "HubSpot", "INTERCOM": "Intercom",
    "SNOWPLOW": "Snowplow", "SEGMENT": "Segment",
    "WORKDAY": "Workday", "ADP_": "ADP",
}
_DOMAIN_SIGNALS: list[tuple[str, str, str, str]] = [
    # (keyword, domain_phrase, focus_phrase, persona)
    ("opportunity", "sales pipeline", "deal progression and revenue forecasting",
     "sales operations and leadership"),
    ("pipeline", "sales pipeline", "deal flow and conversion",
     "sales leadership"),
    ("revenue", "revenue analysis", "revenue tracking and growth",
     "finance and revenue operations"),
    ("partner", "partner/channel management",
     "partner-influenced deals and co-sell effectiveness",
     "partner and channel managers"),
    ("account", "account management", "account health and expansion",
     "account managers and customer success"),
    ("customer", "customer analytics", "customer behaviour and retention",
     "customer success teams"),
    ("order", "order management", "order fulfilment and processing",
     "operations teams"),
    ("invoice", "billing and invoicing", "billing accuracy and payment tracking",
     "finance teams"),
    ("product", "product analytics", "product usage and adoption",
     "product teams"),
    ("inventory", "inventory management", "stock levels and supply chain",
     "supply chain and operations"),
    ("employee", "workforce analytics", "headcount, tenure, and HR metrics",
     "HR and people operations"),
    ("ticket", "support operations", "ticket volume, resolution, and SLAs",
     "support and service teams"),
    ("campaign", "marketing performance", "campaign ROI and attribution",
     "marketing teams"),
    ("lead", "demand generation", "lead volume, conversion, and scoring",
     "demand gen and marketing"),
    ("subscription", "subscription analytics",
     "recurring revenue, churn, and renewal",
     "revenue operations"),
    ("churn", "retention analysis", "churn drivers and prevention",
     "retention and customer success"),
    ("usage", "usage analytics", "feature adoption and engagement",
     "product analytics"),
    ("transaction", "transactional analysis",
     "transaction volume and value trends",
     "operations and finance"),
    ("payment", "payment processing", "payment flow and reconciliation",
     "finance teams"),
    ("shipping", "logistics and fulfilment", "delivery performance and costs",
     "logistics and operations"),
    ("forecast", "forecasting", "predictive planning and accuracy",
     "FP&A and planning"),
    ("budget", "financial planning", "budget tracking and variance",
     "finance teams"),
    ("expense", "expense management", "spend tracking and compliance",
     "finance teams"),
    ("sales", "sales analytics", "sales performance and quota attainment",
     "sales operations"),
    ("funnel", "funnel analysis", "conversion rates across stages",
     "growth and marketing teams"),
]


def _build_ai_analysis(instructions: list, model_data: dict) -> dict:
    """Build a narrative domain summary from model structure."""
    model_name = model_data.get("name", "")
    tables = [mt.get("name", "") for mt in (model_data.get("model_tables") or [])]
    cols = model_data.get("columns") or []
    measures = [c.get("name", "") for c in cols
                if (c.get("properties") or {}).get("column_type") == "MEASURE"]

    all_text = " ".join(
        tables + [c.get("name", "") for c in cols] + [model_name]
    ).lower().replace("_", " ")

    source = ""
    for prefix, label in _SOURCE_PREFIXES.items():
        if any(t.upper().startswith(prefix) for t in tables):
            source = label
            break

    matched_domains = []
    matched_focus = []
    matched_personas = []
    seen_domains = set()
    for kw, domain, focus, persona in _DOMAIN_SIGNALS:
        if kw in all_text and domain not in seen_domains:
            seen_domains.add(domain)
            matched_domains.append(domain)
            matched_focus.append(focus)
            matched_personas.append(persona)

    domain_str = " and ".join(matched_domains[:3]) if matched_domains else "data"
    if source:
        domain = (
            f"This model analyses {source} {domain_str} data"
            f" across {len(tables)} table{'s' if len(tables) != 1 else ''}"
            f" with {len(measures)} metric{'s' if len(measures) != 1 else ''}."
        )
    else:
        domain = (
            f"This model covers {domain_str}"
            f" across {len(tables)} table{'s' if len(tables) != 1 else ''}"
            f" with {len(measures)} metric{'s' if len(measures) != 1 else ''}."
        )

    objectives = matched_focus[:5]
    personas = list(dict.fromkeys(matched_personas))[:4]
    return {
        "domain": domain,
        "objectives": objectives,
        "personas": personas,
        "questions": instructions[:5],
    }


def build_corpus(ctx, cluster_url: str = "", profile_name: str = "",
                 angles: Optional[list] = None) -> dict:
    angles = angles or list(ANGLE_MODULES.keys())
    models_out = []
    for model in ctx.models:
        m = model.get("model", {})
        guid = model.get("guid", m.get("guid", ""))
        model_tables = m.get("model_tables") or []
        entry: dict = {
            "guid": guid,
            "name": m.get("name", ""),
            "description": m.get("description", ""),
            "table_count": len(model_tables),
            "column_count": len(m.get("columns") or []),
            "formula_count": len(m.get("formulas") or []),
            "join_count": len(m.get("joins") or []),
            "join_depth": _calc_join_depth(m),
            "model_tables": [
                {"name": mt.get("name", ""), "fqn": mt.get("fqn", "")}
                for mt in model_tables
            ],
        }
        ai_data = ctx.ai_instructions.get(guid, {})
        instructions = []
        for info in (ai_data.get("nl_instructions_info") or []):
            instructions.extend(info.get("instructions") or [])
        entry["ai_analysis"] = _build_ai_analysis(instructions, m)
        models_out.append(entry)

    table_reuse = _build_table_reuse_from_ctx(models_out)
    model_overlaps = _build_overlaps_from_ctx(models_out)

    erd_models = build_erd_for_audit(ctx)
    erd_by_guid = {m["model"]["guid"]: m for m in erd_models}
    for m in models_out:
        erd = erd_by_guid.get(m["guid"])
        if erd and m.get("ai_analysis"):
            erd["model"]["ai_analysis"] = m["ai_analysis"]
        m["erd"] = erd

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
    fqn_to_info: dict = {}
    for m in models:
        for mt in m["model_tables"]:
            fqn = mt["fqn"]
            if fqn:
                if fqn not in fqn_to_info:
                    fqn_to_info[fqn] = {"name": mt.get("name", fqn), "models": []}
                fqn_to_info[fqn]["models"].append(
                    {"name": m["name"], "guid": m["guid"]}
                )
    return [
        {"fqn": fqn, "name": info["name"], "models": info["models"]}
        for fqn, info in fqn_to_info.items()
        if len(info["models"]) > 1
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
    all_check_ids: list[str] = []
    for angle_key in angles:
        module = ANGLE_MODULES.get(angle_key)
        if not module:
            continue
        for check_fn in module.ALL_CHECKS:
            pre_len = len(findings)
            findings.extend(check_fn(ctx))
            checks_run += 1
            fn_name = check_fn.__name__
            check_id = fn_name.replace("check_", "").upper()
            all_check_ids.append(check_id)

    corpus = build_corpus(
        ctx,
        cluster_url=client.base_url,
        profile_name=client._profile_name,
        angles=angles,
    )

    _inject_findings_into_erd(corpus, findings)

    return {
        "findings": [f.to_dict() for f in findings],
        "summary": build_summary(findings, checks_run, len(ctx.models), len(ctx.tables),
                                 all_check_ids=all_check_ids),
        "corpus": corpus,
        "check_meta": CHECK_META,
    }
