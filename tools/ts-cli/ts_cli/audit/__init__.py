"""`ts audit` — run the rule catalog over an AuditContext and assemble the audit JSON.

The rules are data (`catalog/`, run by `engine/`); `run_audit` selects them by category
(`--angles`) and profile (`--assessment`), fetches what those rules declare
(`data_needs`: requires ∪ uses — nothing more), and returns `{findings, summary, corpus,
check_meta}`. `corpus.fetched_needs` records what was fetched, so the report can tell a
section "not collected for this selection" from "collected, none".
"""
from __future__ import annotations

from typing import Any, Optional

from ts_cli.audit.context import ALWAYS_FETCHED, AuditContext, build_context
from ts_cli.audit.engine import scopes, tml
from ts_cli.audit.engine.code_rules import readiness_level, readiness_score
from ts_cli.audit.erd import build_erd_for_audit
from ts_cli.audit.findings import Finding, build_summary
from ts_cli.audit.formula_tree import formula_tree

#: The conditional data the report reads that no rule need declare: the AI
#: instructions behind each Model's "Business Questions" (`build_corpus`) and its ERD's
#: instruction list (`erd.build_erd_for_audit`), and the dependents — Set rows
#: included, which Set discovery writes — behind each Model's "Downstream Consumers"
#: panel (`corpus.dependents`). Same vocabulary as a rule's `uses`. NOT fetched for
#: the report's sake: `ts audit run` fetches only what the selected rules need, and
#: the report says "not collected for this selection" for a section whose data is
#: missing from `corpus.fetched_needs`.
REPORT_NEEDS = frozenset({"ai_instructions", "dependents", "sets"})

#: The category whose run computes each Model's Spotter readiness score (`build_corpus`).
READINESS_CATEGORY = "A"


_SEV_MAP = {"CRITICAL": "crit", "HIGH": "warn", "MEDIUM": "warn", "LOW": "info", "INFO": "info"}


def _inject_findings_into_erd(corpus: dict, findings: list, check_meta: dict) -> None:
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
        table_names = {str(t["id"]) for t in erd.get("tables", []) if t.get("id")}
        # The table named first in the detail (longest name on a tie, then by name), so
        # the target is the same on every run: set order is not (a detail naming several
        # tables, D3's roll-up, picked a different one per hash seed).
        detail_lower = f.detail.lower()
        named = [(detail_lower.find(tn.lower()), -len(tn), tn) for tn in table_names
                 if tn.lower() in detail_lower]
        target = min(named)[2] if named else ""
        erd_finding = {
            "sev": _SEV_MAP.get(f.severity, "info"),
            "check": f.check_id,
            "title": check_meta.get(f.check_id, {}).get("desc", f.check_id),
            "where": f.object_name,
            "target": target,
            "detail": f.detail,
            # What the ERD shows as "Fix.": the rule's remediation, else its grading.
            "rec": (check_meta.get(f.check_id, {}).get("remediation")
                    or check_meta.get(f.check_id, {}).get("thresholds", "")),
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


def _name(obj: Any) -> str:
    """An object's name as text: a null or YAML-typed one (`name: 2024`) must not crash
    the report."""
    return str(obj.get("name") or "") if isinstance(obj, dict) else ""


def _model_names(model_data: dict) -> tuple:
    """(table names, measure count, every name lower-cased as one text) of a Model."""
    tables = [_name(mt) for mt in (model_data.get("model_tables") or [])]
    cols = [c for c in (model_data.get("columns") or []) if isinstance(c, dict)]
    measures = sum(1 for c in cols
                   if tml.mapping(c, "properties").get("column_type") == "MEASURE")
    text = " ".join(tables + [_name(c) for c in cols] + [_name(model_data)])
    return tables, measures, text.lower().replace("_", " ")


def _build_ai_analysis(instructions: list, model_data: dict) -> dict:
    """Build a narrative domain summary from model structure."""
    tables, n_measures, all_text = _model_names(model_data)

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
            f" with {n_measures} metric{'s' if n_measures != 1 else ''}."
        )
    else:
        domain = (
            f"This model covers {domain_str}"
            f" across {len(tables)} table{'s' if len(tables) != 1 else ''}"
            f" with {n_measures} metric{'s' if n_measures != 1 else ''}."
        )

    objectives = matched_focus[:5]
    personas = list(dict.fromkeys(matched_personas))[:4]
    return {
        "domain": domain,
        "objectives": objectives,
        "personas": personas,
        "questions": instructions[:5],
    }


def _model_ai_analysis(ctx, guid: str, model: dict, ai_fetched: Optional[bool]) -> dict:
    """`_build_ai_analysis` over the Model's fetched instructions, plus — when the
    caller knows whether ai_instructions was fetched — `instructions_read`: whether this
    Model's `ai/instructions/get` lookup succeeded (a failure leaves no entry, so its
    questions are [] exactly as for a Model with none), or None when none was made."""
    instructions = []
    for info in (ctx.ai_instructions.get(guid, {}).get("nl_instructions_info") or []):
        instructions.extend(info.get("instructions") or [])
    analysis = _build_ai_analysis(instructions, model)
    if ai_fetched is not None:
        analysis["instructions_read"] = guid in ctx.ai_instructions if ai_fetched else None
    return analysis


def build_corpus(ctx, cluster_url: str = "", profile_name: str = "",
                 angles: Optional[list] = None, ai_fetched: Optional[bool] = None) -> dict:
    """The report's corpus. ``ai_fetched`` says whether ai_instructions was fetched for
    this context: True records each Model's ``ai_analysis.instructions_read`` (whether
    its lookup succeeded), False records it as None (not looked up), and None — the
    caller does not know — leaves it out."""
    if not angles:
        from ts_cli.audit import catalog_model
        angles = list(catalog_model.load_catalog().categories)
    # The Spotter readiness score (A5 until 2026-10, now a report figure rather than a
    # finding) is computed when the AI Readiness category ran, which is when the AI
    # instructions it reads (coaching, 25% of the score) are fetched — and not when the
    # caller knows they were not, since every Model would then score as uncoached.
    scored = READINESS_CATEGORY in angles and ai_fetched is not False
    items = list(scopes.iterate(ctx, "model")) if scored else None
    models_out = []
    for i, model in enumerate(ctx.models):
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
            "join_count": tml.join_count(model_tables),
            "join_depth": tml.join_depth(model_tables),
            "model_tables": [
                {"name": mt.get("name", ""), "fqn": mt.get("fqn", "")}
                for mt in model_tables
            ],
        }
        entry["ai_analysis"] = _model_ai_analysis(ctx, guid, m, ai_fetched)
        entry["formula_tree"] = formula_tree(m)
        if items is not None:
            score = readiness_score(items[i], ctx)
            # graded on the raw score, as A5 was; rounded only for the report
            entry["spotter_readiness"] = {"score": round(score, 1),
                                          "level": readiness_level(score)}
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


def data_needs(angles: list, profiles: Optional[list] = None) -> set:
    """What `build_context` must fetch for `angles`: `requires ∪ uses` of the catalog
    rules those categories select that are active under any of `profiles` (default: every
    catalog profile — what a snapshot, replayable under either, captures). An angle the
    catalog does not know selects nothing, as it runs nothing."""
    from ts_cli.audit.catalog_model import load_catalog
    from ts_cli.audit.engine.run import needs_for
    catalog = load_catalog()
    known = [a for a in angles if a in catalog.categories]
    needs: set = set()
    for profile in (list(catalog.profiles) if profiles is None else profiles):
        needs |= needs_for(catalog, known, profile)
    return needs


def _unreadable(ctx: AuditContext) -> list:
    """Each Model, Table and Answer no rule judges, because its TML holds a list or
    scalar where a mapping belongs (tml.unreadable_documents): warned on stderr and
    returned for the run's JSON and the report's "Could not be read" (product owner's
    ruling, 2026-10-30: skip the whole Model, and show it)."""
    from ts_cli.audit.context import _log
    messages = tml.unreadable_documents(ctx)[3]
    for msg in messages:
        _log(f"Warning: {msg}")
        ctx.warnings.append(msg)
    return messages


def run_audit(
    client,
    model_guids: list,
    angles: Optional[list] = None,
    assessment_name: Optional[str] = None,
    ctx: Optional[AuditContext] = None,
    fetched_needs: Optional[set] = None,
) -> dict:
    """Run the catalog rules of the categories ``angles`` (default: all) and return
    findings, summary, corpus and check_meta. A category the catalog does not know
    selects nothing (the CLI rejects one before it gets here).

    ``ctx`` replays captured data (``audit/snapshot.py``) instead of fetching:
    ``client`` and ``model_guids`` are then unused for data and ``client`` may
    be None. A supplied ``ctx`` keeps the assessment it was captured with
    unless ``assessment_name`` is given — the profile decides rule ids, severities
    and thresholds, so falling back to the default would make a replay
    disagree with the live run it recorded. A fetched ``ctx`` gets
    ``assessment_name``, or the catalog's default profile when it is None.

    ``corpus.fetched_needs`` (sorted) records what the context holds: for a fetched
    ``ctx``, what was fetched; for a supplied one, ``fetched_needs`` when the caller
    knows it (a snapshot's manifest) — omitted when it does not.
    """
    from ts_cli.audit import catalog_model
    from ts_cli.audit.engine.run import resolve_profile, run_rules, selected_rules
    from ts_cli.audit.generate import report_meta
    catalog = catalog_model.load_catalog()
    angles = list(dict.fromkeys(angles or catalog.categories))  # each category once
    if ctx is None:
        profile = resolve_profile(catalog, assessment_name)
        needs = data_needs(angles, [profile])
        ctx = build_context(client, model_guids, needs)
        fetched_needs = set(needs) | ALWAYS_FETCHED
    else:
        profile = resolve_profile(catalog, assessment_name if assessment_name is not None
                                  else ctx.assessment)
    ctx.assessment = profile
    unreadable = _unreadable(ctx)
    from ts_cli.audit.engine.run import readable
    ctx = readable(ctx)  # what no rule judges is left out of the findings and corpus
    known = [a for a in angles if a in catalog.categories]
    findings: list[Finding] = run_rules(ctx, catalog, known, profile)
    run_ids = [rule.id for rule in selected_rules(catalog, known, profile)]
    check_meta = report_meta(catalog)["checks"]

    corpus = build_corpus(
        ctx,
        cluster_url=getattr(client, "base_url", ""),
        profile_name=getattr(client, "_profile_name", ""),
        angles=angles,
        ai_fetched=None if fetched_needs is None else "ai_instructions" in fetched_needs,
    )
    corpus["assessment"] = catalog.profiles[profile].label
    if unreadable:
        corpus["unreadable"] = unreadable
    if fetched_needs is not None:
        corpus["fetched_needs"] = sorted(fetched_needs)

    _inject_findings_into_erd(corpus, findings, check_meta)

    return {
        "findings": [f.to_dict() for f in findings],
        "summary": build_summary(findings, len(run_ids), len(ctx.models), len(ctx.tables),
                                 all_check_ids=run_ids, categories=list(catalog.categories)),
        "corpus": corpus,
        "check_meta": check_meta,
    }
