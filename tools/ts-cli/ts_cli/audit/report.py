"""Audit report renderer — compacts JSON, injects into HTML template."""
from __future__ import annotations

import json
from pathlib import Path


TEMPLATE_PATH = Path(__file__).parent / "report_template.html"


def compact_payload(data: dict) -> dict:
    findings = data.get("findings", [])
    summary = data.get("summary", {})
    corpus = data.get("corpus")

    model_lookup: list = []
    model_index: dict = {}
    for f in findings:
        key = (f.get("object_name", ""), f.get("object_guid", ""))
        if key not in model_index:
            model_index[key] = len(model_lookup)
            model_lookup.append({"n": key[0], "g": key[1]})

    if corpus:
        for m in corpus.get("models", []):
            key = (m.get("name", ""), m.get("guid", ""))
            if key not in model_index:
                model_index[key] = len(model_lookup)
                model_lookup.append({"n": key[0], "g": key[1]})

    compact_findings = []
    for f in findings:
        key = (f.get("object_name", ""), f.get("object_guid", ""))
        cf: dict = {
            "ci": f["check_id"],
            "a": f["angle"],
            "s": f["severity"],
            "ot": f.get("object_type", ""),
            "mi": model_index[key],
            "d": f["detail"],
        }
        if f.get("metric") is not None:
            cf["me"] = f["metric"]
        if f.get("threshold"):
            cf["th"] = f["threshold"]
        compact_findings.append(cf)

    compact_summary = {
        "bs": summary.get("by_severity", {}),
        "ba": summary.get("by_angle", {}),
        "os": summary.get("objects_scanned", {}),
        "cr": summary.get("checks_run", 0),
        "ac": summary.get("all_check_ids", []),
    }

    check_meta = data.get("check_meta", {})
    compact_check_meta = {}
    for cid, meta in check_meta.items():
        compact_check_meta[cid] = {
            "d": meta.get("desc", ""),
            "t": meta.get("thresholds", ""),
        }

    result: dict = {
        "L": model_lookup,
        "F": compact_findings,
        "S": compact_summary,
        "K": compact_check_meta,
    }

    if corpus:
        compact_models = []
        for m in corpus.get("models", []):
            key = (m.get("name", ""), m.get("guid", ""))
            cm = {
                "mi": model_index.get(key, -1),
                "tc": m.get("table_count", 0),
                "cc": m.get("column_count", 0),
                "fc": m.get("formula_count", 0),
                "jc": m.get("join_count", 0),
                "jd": m.get("join_depth", 0),
                "ds": m.get("description", ""),
                "mt": [{"n": t["name"], "f": t["fqn"]} for t in m.get("model_tables", [])],
            }
            ai = m.get("ai_analysis")
            if ai:
                cm["ai"] = {
                    "pe": ai.get("personas", []),
                    "qu": ai.get("questions", []),
                    "st": ai.get("structure", ""),
                }
            compact_models.append(cm)

        compact_reuse = [
            {
                "f": t["fqn"],
                "n": t["name"],
                "ms": [{"n": mm["name"], "g": mm["guid"]} for mm in t["models"]],
            }
            for t in corpus.get("table_reuse", [])
        ]

        # Sort by jaccard descending and cap at 200 — beyond that the UI
        # can't usefully display pairwise overlaps and the payload would blow up.
        raw_overlaps = sorted(
            corpus.get("model_overlaps", []),
            key=lambda o: o["jaccard"],
            reverse=True,
        )[:200]
        compact_overlaps = [
            {
                "a": {"n": o["model_a"]["name"], "g": o["model_a"]["guid"]},
                "b": {"n": o["model_b"]["name"], "g": o["model_b"]["guid"]},
                "j": o["jaccard"],
                "sc": o["shared_table_count"],
                "ta": o.get("total_tables_a", 0),
                "tb": o.get("total_tables_b", 0),
                "st": o.get("shared_tables", [])[:10],
                "t": o["type"],
            }
            for o in raw_overlaps
        ]

        compact_deps: dict = {}
        for guid, deps in corpus.get("dependents", {}).items():
            compact_deps[guid] = [
                {"n": d["name"], "g": d["guid"], "t": d["type"]}
                for d in deps
            ]

        result["C"] = {
            "u": corpus.get("cluster_url", ""),
            "p": corpus.get("profile_name", ""),
            "dt": corpus.get("audit_date", ""),
            "ar": corpus.get("angles_run", []),
            "m": compact_models,
            "tr": compact_reuse,
            "mo": compact_overlaps,
            "dp": compact_deps,
        }
    else:
        result["C"] = None

    return result


def render_report(data: dict) -> str:
    payload = compact_payload(data)
    json_str = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("{{AUDIT_DATA}}", json_str)
