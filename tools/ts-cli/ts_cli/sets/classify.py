"""Set class — spec §4. First matching rule wins; uncertainty is resolved before any
CANDIDATE verdict, so a Set is never marked convertible on incomplete evidence."""
from __future__ import annotations


def _r(cls: str, reason: str, target=None) -> dict:
    return {"class": cls, "reason": reason, "target": target}


def classify(c: dict) -> dict:
    deps, lbs = c["dependents"], c["liveboards"]
    if any(u.get("filter") for u in lbs.values()):
        return _r("KEEP_FILTER", "used as a Liveboard filter")
    if c.get("error"):
        return _r("REVIEW_MANUAL", c["error"])
    if c["unreadable"]:
        return _r("REVIEW_MANUAL", "; ".join(f"{u['name']}: {u['reason']}" for u in c["unreadable"]))
    if c["other_types"]:
        return _r("REVIEW_MANUAL", "dependent type(s) not inspected: "
                  + ", ".join(sorted({o["type"] for o in c["other_types"]})))
    for d in deps:
        if d["type"] == "LIVEBOARD" and not lbs.get(d["guid"], {}).get("vizzes"):
            return _r("REVIEW_MANUAL", f"Liveboard '{d['name']}' depends on the Set but no "
                      "visualization or filter referencing it was found")
    if len(deps) >= 2:
        return _r("KEEP_SHARED", f"{len(deps)} dependent objects")
    if len(deps) == 1:
        d = deps[0]
        if d["type"] == "ANSWER":
            return _r("CANDIDATE_ANSWER", "one Answer",
                      {"type": "ANSWER", "guid": d["guid"], "name": d["name"]})
        vizzes = lbs[d["guid"]]["vizzes"]
        if len(vizzes) >= 2:
            return _r("KEEP_SHARED", f"{len(vizzes)} visualizations on '{d['name']}'")
        v = vizzes[0]
        return _r("CANDIDATE_VIZ", "one visualization",
                  {"type": "VIZ", "liveboard_guid": d["guid"], "liveboard_name": d["name"],
                   "viz_id": v["id"], "viz_title": v["title"]})
    return _r("REVIEW_DELETE", "no recorded dependents — check ad-hoc use before deleting")
