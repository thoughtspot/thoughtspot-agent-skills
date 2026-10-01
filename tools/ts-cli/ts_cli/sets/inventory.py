"""Assemble the per-Set inventory. Composition only — each rule lives in its own module.

Spec §7: a failure makes the report less certain, never more favourable. No step here
catches an exception and substitutes a class or a provenance; an unexpected error for a
Set propagates rather than being read as a lighter verdict.
"""
from __future__ import annotations

from collections import Counter
from typing import List

from ts_cli.sets.classify import classify
from ts_cli.sets.consumers import fetch_consumers
from ts_cli.sets.discover import discover_sets
from ts_cli.sets.grants import UNKNOWN_GRANTS, fetch_grants, provenance

# Labels that depend on knowing EVERY consumer and its owner. When that is uncertain
# they are downgraded to UNKNOWN; DIRECT and REQUIRED rest on positive evidence and stay.
_NEEDS_COMPLETE_CONSUMERS = {"EXPLAINED", "UNEXPLAINED"}


def _consumers_uncertain(consumers: dict) -> bool:
    """Hidden dependents (or a failed lookup) or a dependent with no owner: an owner we
    cannot see would read UNEXPLAINED and land on the review list (spec §6.1 says that
    list never holds a REQUIRED grant). An `other_types` consumer carries no owner in the
    record, so its owner is equally invisible (R12)."""
    return (bool(consumers.get("error")) or bool(consumers.get("other_types"))
            or any(not d.get("author_id") for d in consumers["dependents"]))


def build_set_record(set_ref: dict, consumers: dict, cls: dict, grants) -> dict:
    if grants is None:
        labelled = [dict(g) for g in UNKNOWN_GRANTS]
    else:
        owners = {d["author_id"] for d in consumers["dependents"] if d.get("author_id")}
        consumer_grants = {d["guid"]: grants.get(d["guid"], []) for d in consumers["dependents"]}
        labelled = provenance(grants.get(set_ref["guid"], []), consumer_grants, owners)
        if _consumers_uncertain(consumers):
            labelled = [dict(g, provenance="UNKNOWN")
                        if g["provenance"] in _NEEDS_COMPLETE_CONSUMERS else g
                        for g in labelled]
    return dict(set_ref, **{"class": cls["class"], "reason": cls["reason"],
                            "target": cls["target"], "dependents": consumers["dependents"],
                            # False when the dependents list may be short: a failed or
                            # partial lookup, an uninspected type, or an unreadable export.
                            # The renderer must then never show the count as a total.
                            "dependents_complete": not (consumers.get("error")
                                                        or consumers.get("other_types")
                                                        or consumers.get("unreadable")),
                            "liveboards": consumers["liveboards"], "grants": labelled})


def inventory_org(client, label: str, models: List[dict]) -> dict:
    found = discover_sets(client, models)
    notes = list(found["notes"])
    out_models = []
    for m in models:
        if m["guid"] in found["incomplete"]:
            out_models.append({"guid": m["guid"], "name": m["name"], "discovery": "INCOMPLETE",
                               "set_count": None, "sets": []})
            continue
        records = []
        for s in found["sets"].get(m["guid"], []):
            obj = f"{m['name']} / {s['name']}"
            cons = fetch_consumers(client, s)
            grants = fetch_grants(client, s["guid"], cons)
            records.append(build_set_record(s, cons, classify(cons), grants))
            if cons.get("error"):
                notes.append({"kind": "dependents_failed", "object": obj,
                              "detail": cons["error"]})
            for u in cons.get("unreadable") or []:
                notes.append({"kind": "export_unreadable",
                              "object": f"{obj} / {u['name']} ({u['guid']})",
                              "detail": u["reason"]})
            for o in cons.get("other_types") or []:
                notes.append({"kind": "unrecognised_dependent",
                              "object": f"{obj} / {o['name']} ({o['guid']})",
                              "detail": f"type {o['type']} not inspected"})
            if grants is None:
                notes.append({"kind": "grants_unreadable", "object": obj,
                              "detail": "fetch-permissions failed or returned an unusable "
                                        "body; grant provenance is UNKNOWN (reason on stderr)"})
        out_models.append({"guid": m["guid"], "name": m["name"], "discovery": "COMPLETE",
                           "set_count": len(records), "sets": records})
    return {"org": label, "models": out_models, "notes": notes}


def _grants_with(sets: List[dict], prov: str) -> int:
    return sum(1 for s in sets for g in s["grants"] if g["provenance"] == prov)


def summarise(orgs: List[dict]) -> dict:
    models = [m for o in orgs for m in o["models"]]
    sets = [s for m in models for s in m["sets"]]
    return {"models": len(models),
            "models_incomplete": sum(1 for m in models if m["discovery"] == "INCOMPLETE"),
            "sets": len(sets),
            "by_class": dict(Counter(s["class"] for s in sets)),
            "unexplained_grants": _grants_with(sets, "UNEXPLAINED"),
            "unknown_grants": _grants_with(sets, "UNKNOWN")}
