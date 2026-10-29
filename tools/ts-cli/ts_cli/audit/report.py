"""Audit report renderer — compacts JSON, injects into HTML template.

What the report says about categories and rules — the category tabs, labels and order,
each rule's title, grading text and recommendation, and which rules feed the
duplicates and cleanup views — comes from the rule catalog (generate.report_meta), not
from the template. JSON written before the catalog cut-over (findings with `angle` and
the legacy `threshold` dict only) still renders: a finding's categories are derived
from its angle, and the metric bar falls back to the legacy pass mark.
"""
from __future__ import annotations

import importlib.util
import json
import operator
from pathlib import Path
from typing import Any, Dict, List, Optional


TEMPLATE_PATH = Path(__file__).parent / "report_template.html"
_ERD_DIR = Path(__file__).resolve().parents[4] / "agents" / "shared" / "erd"


def _read_erd_assets() -> dict | None:
    """Read ERD renderer assets from the shared directory."""
    if not _ERD_DIR.is_dir():
        return None
    try:
        css = (_ERD_DIR / "renderer.css").read_text(encoding="utf-8")
        js = (_ERD_DIR / "renderer.js").read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "_erd_render", str(_ERD_DIR / "render.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        body = mod._BODY
        return {"css": css, "js": js, "body": body}
    except Exception:
        return None


_OPS = {"lt": operator.lt, "lte": operator.le, "gt": operator.gt, "gte": operator.ge,
        "eq": operator.eq}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bar(value: float, mark: float, ok: bool, unit: str, direction: str) -> Dict[str, Any]:
    if mark:
        width = min(100, round(value / mark * 100))
    else:
        width = 100 if value else 0
    return {"v": value, "mark": mark, "ok": ok, "unit": unit, "dir": direction,
            "w": max(0, width)}


def metric_bar(finding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The metric bar for one finding, or None when there is none to draw.

    From the uniform `bands` payload when present: the mark is the least severe level's
    value (the pass mark for a higher-is-better metric, the limit for a lower-is-better
    one) and the metric is a breach when any level matches it — so P8's 90 columns
    against `gt 75` is a breach, not "ok". Without bands — JSON from before the
    cut-over, or a code rule that grades in code (D1) — the legacy `threshold` dict is
    read: `green` is the mark, and the direction is lower-is-better when its `yellow`
    (where HIGH starts) lies above `green` (D1, P2, P7), else higher-is-better (the
    coverage checks, in percent). No `green`, no bar — the old fallback to 80 drew
    lower-is-better metrics as passing."""
    value = finding.get("metric")
    if not _number(value):
        return None
    bands = finding.get("bands") or {}
    levels = [lv for lv in bands.get("levels") or []
              if _number(lv.get("value")) and lv.get("op") in _OPS]
    if levels:
        breach = any(_OPS[lv["op"]](value, lv["value"]) for lv in levels)
        unit = "%" if bands.get("unit") == "percent" else ""
        return _bar(value, levels[-1]["value"], not breach, unit,
                    bands.get("direction", "higher_is_better"))
    threshold = finding.get("threshold") or {}
    green, yellow = threshold.get("green"), threshold.get("yellow")
    if not _number(green):
        return None
    if _number(yellow) and yellow > green:
        return _bar(value, green, value <= green, "", "lower_is_better")
    return _bar(value, green, value >= green, "%", "higher_is_better")


def _catalog_meta() -> Dict[str, Any]:
    from ts_cli.audit.catalog_model import load_catalog
    from ts_cli.audit.generate import report_meta
    return report_meta(load_catalog())


def _categories_of(finding: Dict[str, Any], by_angle: Dict[str, str]) -> List[str]:
    """A finding's category ids; for pre-cut-over JSON, its angle's category."""
    cats = finding.get("categories")
    if cats:
        return list(cats)
    angle = finding.get("angle", "")
    return [by_angle.get(angle, angle)]


def _check_text(meta: Dict[str, Any], run_meta: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Per rule `{d: title, t: grading, r: recommendation}`: the catalog's, with the
    audit run's own `check_meta` text winning where it has any (it describes that run)."""
    out: Dict[str, Dict[str, str]] = {}
    for cid in list(meta["checks"]) + [c for c in run_meta if c not in meta["checks"]]:
        cat = meta["checks"].get(cid, {})
        run = run_meta.get(cid) or {}
        out[cid] = {"d": run.get("desc", cat.get("desc", "")),
                    "t": run.get("thresholds", cat.get("thresholds", "")),
                    "r": run.get("remediation", cat.get("remediation", ""))}
    return out


def _model_lookup(findings: list, corpus: Optional[dict]) -> tuple:
    """`(lookup, index)`: one `{n, g}` per distinct (name, guid) — the corpus's Models
    first, then each finding's object — and the position of each key."""
    model_lookup: list = []
    model_index: dict = {}
    keys = [(m.get("name", ""), m.get("guid", "")) for m in (corpus or {}).get("models", [])]
    keys += [(f.get("object_name", ""), f.get("object_guid", "")) for f in findings]
    for key in keys:
        if key not in model_index:
            model_index[key] = len(model_lookup)
            model_lookup.append({"n": key[0], "g": key[1]})
    return model_lookup, model_index


def _compact_finding(f: dict, model_index: dict, by_angle: Dict[str, str]) -> dict:
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
    cf["c"] = _categories_of(f, by_angle)
    bar = metric_bar(f)
    if bar:
        cf["mb"] = bar
    return cf


def _compact_ai(ai: dict) -> dict:
    """A Model's `ai_analysis`, compacted. `rd` (instructions_read) is passed through
    only when the run recorded it: true/false when ai_instructions was fetched, null
    when it was not; absent in JSON from before the rule catalog."""
    out = {
        "do": ai.get("domain", ""),
        "ob": ai.get("objectives", []),
        "pe": ai.get("personas", []),
        "qu": ai.get("questions", []),
    }
    if "instructions_read" in ai:
        out["rd"] = ai["instructions_read"]
    return out


def _compact_model(m: dict, model_index: dict) -> dict:
    """One corpus Model, compacted: its stats, tables, and — when present — its AI
    analysis, Spotter readiness score (`rs`: score and level) and ERD."""
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
    if m.get("ai_analysis"):
        cm["ai"] = _compact_ai(m["ai_analysis"])
    if m.get("spotter_readiness"):
        cm["rs"] = {"s": m["spotter_readiness"]["score"],
                    "l": m["spotter_readiness"]["level"]}
    if m.get("erd"):
        cm["ed"] = m["erd"]
    return cm


def compact_payload(data: dict) -> dict:
    findings = data.get("findings", [])
    summary = data.get("summary", {})
    corpus = data.get("corpus")

    model_lookup, model_index = _model_lookup(findings, corpus)
    meta = _catalog_meta()
    by_angle = {c["angle_key"]: c["id"] for c in meta["categories"]}
    compact_findings = [_compact_finding(f, model_index, by_angle) for f in findings]

    compact_summary = {
        "bs": summary.get("by_severity", {}),
        "ba": summary.get("by_angle", {}),
        "bc": summary.get("by_category", {}),
        "os": summary.get("objects_scanned", {}),
        "cr": summary.get("checks_run", 0),
        "ac": summary.get("all_check_ids", []),
    }

    result: dict = {
        "L": model_lookup,
        "F": compact_findings,
        "S": compact_summary,
        "K": _check_text(meta, data.get("check_meta") or {}),
        "G": {"categories": meta["categories"], "views": meta["views"],
              "profiles": meta["profiles"]},
    }

    if corpus:
        compact_models = [_compact_model(m, model_index) for m in corpus.get("models", [])]

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
            "as": corpus.get("assessment", ""),
            "m": compact_models,
            "tr": compact_reuse,
            "mo": compact_overlaps,
            "dp": compact_deps,
        }
        # What the run fetched (absent in JSON written before it was recorded, which
        # then renders as before): a section whose data is not in it says
        # "not collected for this selection".
        if isinstance(corpus.get("fetched_needs"), list):
            result["C"]["fn"] = corpus["fetched_needs"]
    else:
        result["C"] = None

    return result


def render_report(data: dict) -> str:
    payload = compact_payload(data)
    erd_assets = _read_erd_assets()
    if erd_assets:
        payload["E"] = erd_assets
    json_str = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("{{AUDIT_DATA}}", json_str)
