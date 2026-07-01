"""Generate realistic audit JSON fixtures for testing and artifact previews."""
from __future__ import annotations

import hashlib
from typing import Optional

ANGLE_NAMES = {"A": "ai", "D": "data_modeling", "H": "human", "P": "performance", "S": "security"}
ALL_ANGLES = list(ANGLE_NAMES.keys())
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

CHECK_CATALOG = [
    ("A1", "ai", "Description coverage below threshold"),
    ("A2", "ai", "Synonym coverage below threshold"),
    ("A3", "ai", "No AI instructions configured"),
    ("D1", "data_modeling", "Model complexity exceeds threshold"),
    ("D2", "data_modeling", "Chasm trap detected in join path"),
    ("D7", "data_modeling", "High model overlap detected"),
    ("D8", "data_modeling", "Duplicate table objects found"),
    ("H3", "human", "Unnecessary hidden columns"),
    ("H4", "human", "Orphan model with no dependents"),
    ("H7", "human", "Answer queries table directly"),
    ("H8", "human", "Formula promotion candidate"),
    ("P1", "performance", "SQL View used as model source"),
    ("P5", "performance", "Non-progressive join detected"),
    ("P16", "performance", "Deeply nested if() calls"),
    ("S1", "security", "PII column without RLS"),
    ("S3", "security", "Indexing enabled without RLS"),
]

MODEL_NAMES = [
    "Sales Model", "Revenue Model", "Customer Analytics", "Product Catalog",
    "Supply Chain", "HR Analytics", "Finance Model", "Marketing Insights",
    "Inventory Tracker", "Operations Dashboard",
]

TABLE_NAMES = [
    "DM_ORDERS", "DM_CUSTOMERS", "DM_PRODUCTS", "DM_LINE_ITEMS",
    "DM_EMPLOYEES", "DM_REGIONS", "DM_DATES", "DM_CHANNELS",
    "DM_SUPPLIERS", "DM_WAREHOUSES", "DM_RETURNS", "DM_PROMOTIONS",
]


def _guid(seed: str) -> str:
    return hashlib.md5(seed.encode()).hexdigest()[:8] + "-" + \
           hashlib.md5((seed + "x").encode()).hexdigest()[:4] + "-" + \
           hashlib.md5((seed + "y").encode()).hexdigest()[:4] + "-" + \
           hashlib.md5((seed + "z").encode()).hexdigest()[:4] + "-" + \
           hashlib.md5((seed + "w").encode()).hexdigest()[:12]


def generate_test_data(
    model_count: int = 5,
    findings_per_model: int = 10,
    include_corpus: bool = True,
    name_collisions: int = 0,
    empty_angles: Optional[list] = None,
    cluster_url: str = "https://demo.thoughtspot.cloud",
) -> dict:
    empty_angles = empty_angles or []
    active_checks = [
        c for c in CHECK_CATALOG
        if c[0][0] not in empty_angles
    ]

    models_meta = []
    model_names_used = []
    for i in range(model_count):
        if i < name_collisions and i > 0:
            name = model_names_used[0]
        else:
            name = MODEL_NAMES[i % len(MODEL_NAMES)]
        model_names_used.append(name)

        guid = _guid(f"model-{i}")
        table_count = 5 + (i * 3) % 15
        model_tables = []
        for t in range(table_count):
            tidx = (i * 7 + t) % len(TABLE_NAMES)
            tname = TABLE_NAMES[tidx]
            model_tables.append({
                "name": tname,
                "fqn": f"ANALYTICS.PUBLIC.{tname}",
            })

        models_meta.append({
            "guid": guid,
            "name": name,
            "table_count": table_count,
            "column_count": table_count * 8 + i * 5,
            "formula_count": 3 + i * 2,
            "join_count": max(0, table_count - 1),
            "join_depth": min(table_count, 4 + i % 3),
            "model_tables": model_tables,
        })

    findings = []
    for i, m in enumerate(models_meta):
        count = findings_per_model
        if i == model_count - 1:
            count = max(1, findings_per_model // 3)
        for j in range(count):
            check = active_checks[j % len(active_checks)]
            sev_idx = j % len(SEVERITIES)
            if j == 0 and i == 0:
                sev_idx = 0
            findings.append({
                "check_id": check[0],
                "angle": check[1],
                "severity": SEVERITIES[sev_idx],
                "object_type": "model",
                "object_name": m["name"],
                "object_guid": m["guid"],
                "detail": f"{check[2]} — {m['name']}",
                "metric": round(20 + j * 5.5, 1),
                "threshold": {"green": 80, "yellow": 50} if "coverage" in check[2].lower() else None,
            })

    by_severity = {s: 0 for s in SEVERITIES}
    by_angle = {a: 0 for a in ANGLE_NAMES.values()}
    for f in findings:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
        by_angle[f["angle"]] = by_angle.get(f["angle"], 0) + 1

    result = {
        "findings": findings,
        "summary": {
            "by_severity": by_severity,
            "by_angle": by_angle,
            "objects_scanned": {"models": model_count, "tables": sum(m["table_count"] for m in models_meta)},
            "checks_run": len(active_checks),
        },
    }

    if include_corpus:
        table_reuse = _build_table_reuse(models_meta)
        model_overlaps = _build_model_overlaps(models_meta)
        dependents = _build_dependents(models_meta)

        result["corpus"] = {
            "cluster_url": cluster_url,
            "profile_name": "demo",
            "audit_date": "2026-07-01",
            "angles_run": [a for a in ALL_ANGLES if a not in empty_angles],
            "models": models_meta,
            "table_reuse": table_reuse,
            "model_overlaps": model_overlaps,
            "dependents": dependents,
        }

    return result


def _build_table_reuse(models: list) -> list:
    fqn_to_models = {}
    for m in models:
        for mt in m["model_tables"]:
            fqn = mt["fqn"]
            fqn_to_models.setdefault(fqn, []).append({"name": m["name"], "guid": m["guid"]})
    return [
        {"fqn": fqn, "name": fqn.rsplit(".", 1)[-1], "models": mlist}
        for fqn, mlist in fqn_to_models.items()
        if len(mlist) > 1
    ]


def _build_model_overlaps(models: list) -> list:
    overlaps = []
    for i, a in enumerate(models):
        a_fqns = {mt["fqn"] for mt in a["model_tables"]}
        for b in models[i + 1:]:
            b_fqns = {mt["fqn"] for mt in b["model_tables"]}
            shared = a_fqns & b_fqns
            if len(shared) < 2:
                continue
            union = a_fqns | b_fqns
            jaccard = len(shared) / len(union) if union else 0
            if jaccard >= 0.5:
                otype = "identical" if jaccard == 1.0 else (
                    "subset" if shared == a_fqns or shared == b_fqns else "high_overlap"
                )
            else:
                otype = "conformed_reuse"
            overlaps.append({
                "model_a": {"name": a["name"], "guid": a["guid"]},
                "model_b": {"name": b["name"], "guid": b["guid"]},
                "jaccard": round(jaccard, 3),
                "shared_table_count": len(shared),
                "total_tables_a": len(a_fqns),
                "total_tables_b": len(b_fqns),
                "shared_tables": sorted(fqn.rsplit(".", 1)[-1] for fqn in shared),
                "type": otype,
            })
    return overlaps


def _build_dependents(models: list) -> dict:
    dep_types = ["ANSWER", "LIVEBOARD", "ANSWER", "LIVEBOARD", "ANSWER"]
    dep_names = ["Q1 Dashboard", "Sales Summary", "Weekly Report", "KPI Board", "Trend Analysis"]
    result = {}
    for i, m in enumerate(models):
        deps = []
        for j in range(2 + i % 3):
            dtype = dep_types[j % len(dep_types)]
            dname = dep_names[(i + j) % len(dep_names)]
            deps.append({
                "name": dname,
                "guid": _guid(f"dep-{m['guid']}-{j}"),
                "type": dtype,
            })
        result[m["guid"]] = deps
    return result
