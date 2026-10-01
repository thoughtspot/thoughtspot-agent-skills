"""Scope selectors → Models. Pure; the command supplies the per-Org Model list."""
from __future__ import annotations

from typing import List, Tuple


def _name(m: dict) -> str:
    """A Model's name, casefolded; a missing or None name matches as ""."""
    return (m.get("name") or "").casefold()


def select_models(models: List[dict], *, model: List[str],
                  contains: List[str]) -> Tuple[List[dict], List[str]]:
    if not model and not contains:
        return list(models), []
    keep: set = set()
    missed: List[str] = []
    for sel in model:
        hits = {m["guid"] for m in models
                if m["guid"] == sel or _name(m) == sel.casefold()}
        keep |= hits
        if not hits:
            missed.append(sel)
    for sub in contains:
        hits = {m["guid"] for m in models if sub.casefold() in _name(m)}
        keep |= hits
        if not hits:
            missed.append(sub)
    return [m for m in models if m["guid"] in keep], missed
