"""What uses a reusable Set — dependents, and where inside a Liveboard.

A Liveboard visualization is a COPY of an Answer inside the Liveboard's TML (ThoughtSpot
does not pin by reference), so a Liveboard dependent means finding the visualization(s)
whose search references the Set. A Set named in `liveboard.filters[].column[]` is a
Liveboard filter and must stay reusable (spec §1, req 4).
"""
from __future__ import annotations

from typing import Dict

from ts_cli.sets.discover import export_doc as _export

SEARCH = "/api/rest/2.0/metadata/search"
_KNOWN = {"ANSWER", "LIVEBOARD"}


def _token(name: str) -> str:
    return f"[{name}]".casefold()


def _has_token(text: str, set_name: str) -> bool:
    """Literal, case-insensitive `[Set Name]` match. The token must not be followed by `]`,
    so "[Top 10 [Q1]s]" does not match "[Top 10 [Q1]]". No regex: names contain brackets."""
    text, tok = text.casefold(), _token(set_name)
    i = text.find(tok)
    while i != -1:
        end = i + len(tok)
        if end == len(text) or text[end] != "]":
            return True
        i = text.find(tok, i + 1)
    return False


def _viz_uses(viz: dict, set_name: str) -> bool:
    ans = viz.get("answer") or {}
    if _has_token(ans.get("search_query") or "", set_name):
        return True
    if any(_has_token(f.get("expr") or "", set_name) for f in ans.get("formulas") or []):
        return True  # Task 1: Sets are also referenced inside viz formulas
    target = set_name.casefold()
    return any((c.get("name") or "").casefold() == target for c in ans.get("answer_columns") or [])


def liveboard_usage(doc: dict, set_name: str) -> dict:
    lb = (doc or {}).get("liveboard") or {}
    vizzes = [{"id": v.get("id", ""), "title": (v.get("answer") or {}).get("name", "")}
              for v in lb.get("visualizations") or [] if _viz_uses(v, set_name)]
    target = set_name.casefold()
    in_filter = any(any((c or "").casefold() == target for c in f.get("column") or [])
                    for f in lb.get("filters") or [])
    return {"vizzes": vizzes, "filter": in_filter}


def _dependents_hidden(dep_objects: dict) -> bool:
    """True when some dependents are inaccessible AND were not returned (ruling R17)."""
    return bool(dep_objects.get("hasInaccessibleDependents")) and \
        dep_objects.get("areInaccessibleDependentsReturned") is not True


def _own_item(body: list, guid: str):
    """The response item for this Set — matched the way `_normalize_dependents_response`
    keys its `source_guid` (`metadata_id`, falling back to `identifier`) — and only when its
    `dependent_objects.dependents` carries a dict under that GUID. `None` otherwise."""
    for item in body:
        if not isinstance(item, dict):
            continue
        if (item.get("metadata_id") or item.get("identifier") or "") != guid:
            continue
        deps = (item.get("dependent_objects") or {}).get("dependents")
        if isinstance(deps, dict) and isinstance(deps.get(guid), dict):
            return item
    return None


def fetch_consumers(client, set_ref: dict) -> dict:
    from ts_cli.commands.metadata import _build_dependents_payload, _normalize_dependents_response
    out: Dict = {"dependents": [], "liveboards": {}, "unreadable": [], "other_types": [],
                 "error": None}
    try:
        resp = client.post(SEARCH, json=_build_dependents_payload([set_ref["guid"]],
                                                                  "LOGICAL_COLUMN"))
        body = resp.json()
        if not isinstance(body, list):
            # _normalize_dependents_response maps a non-list body to [] — which would read
            # as "no dependents". A failure must never become the more favourable result.
            raise ValueError(f"unexpected dependents response shape: {type(body).__name__}")
        # Two flags, read BEFORE normalising (which drops both):
        #   hasInaccessibleDependents         — dependents exist that the caller cannot see;
        #   areInaccessibleDependentsReturned — those dependents were nonetheless returned.
        # Only has=true WITHOUT returned=true means the list is incomplete; a missing
        # `returned` counts as not returned. Live 2026-10-02 (se-thoughtspot, ruling R17):
        # an admin gets BOTH true with the full list, and reading only the first flag
        # turned every used Set into REVIEW_MANUAL. Still list what IS visible.
        item = _own_item(body, set_ref["guid"])
        if item is None:
            # `[]`, an item with no dependents map, or an item for another GUID must not
            # read as "no dependents" (final review must-fix 1, spec §7). A present
            # `{"<guid>": {}}` IS a real zero (open item #5) and passes this check.
            out["error"] = "dependents response did not include this Set"
            return out
        hidden = _dependents_hidden(item.get("dependent_objects") or {})
        rows = _normalize_dependents_response([item])
    except (Exception, SystemExit) as exc:
        out["error"] = f"dependents lookup failed: {exc!r}"
        return out
    if hidden:
        out["error"] = "some dependents are not visible to this user (hasInaccessibleDependents)"
    for r in rows:
        dep = {"guid": r["guid"], "name": r["name"], "type": r["type"], "author_id": r["author_id"]}
        if r["type"] not in _KNOWN:
            out["other_types"].append({"guid": r["guid"], "name": r["name"], "type": r["type"]})
            continue
        out["dependents"].append(dep)
        if r["type"] == "LIVEBOARD":
            doc = _export(client, r["guid"])
            if doc is None:
                out["unreadable"].append({"guid": r["guid"], "name": r["name"],
                                          "reason": "Liveboard TML export failed or was refused"})
            elif not isinstance(doc, dict) or "liveboard" not in doc:
                # Never read a non-Liveboard export as "read, no usage".
                out["unreadable"].append({"guid": r["guid"], "name": r["name"],
                                          "reason": "export was not Liveboard TML"})
            else:
                out["liveboards"][r["guid"]] = liveboard_usage(doc, set_ref["name"])
    return out
