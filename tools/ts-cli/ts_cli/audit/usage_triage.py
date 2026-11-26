"""The Usage view's reading of each audited Model (ts-audit 3.28.0): its status, its
dependents by type, its owner and when it was created, beside the usage itself.

Read from what the audit already fetches — the usage (audit/usage.py), each Model's
dependents (`ctx.dependents`, the rows H4 and the scorecard's Downstream consumers
read) and its metadata header (`ctx.metadata`) — never a call of its own. Added to
`corpus.models[].usage` (add_triage), so it is there only when usage was read.

The status reuses H17's reading (usage.idle_reading), so the view and H17 agree and no
threshold is written twice:

* "active": queried within the idle days;
* "idle": no query in the idle days or more (H17 reports it, by its days);
* "never": no query in a history that covers the idle days (H17 reports it);
* "too_new": never queried, and created less than the idle days before the read (the
  0.224.1 rule: H17 skips it);
* "not_judged": anything else — a history too short to say, or a row with no query time.

Standard library only at import, as usage.py is: H17's code rule imports this module.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Optional

from ts_cli.audit.usage import idle_days_of, idle_reading, model_usage, usage_readable

STATUSES = ("active", "idle", "never", "too_new", "not_judged")
#: `ctx.dependents` row types counted on their own; every other type counts as "other".
_KINDS = {"LIVEBOARD": "liveboards", "ANSWER": "answers", "SET": "sets"}


def headers_by_id(metadata: Any) -> Dict[str, dict]:
    """Each object's metadata header (`metadata/search` row's `metadata_header`, or the
    row itself) by its id."""
    out: Dict[str, dict] = {}
    for entry in metadata or []:
        header = (entry.get("metadata_header") or entry) if isinstance(entry, dict) else {}
        if isinstance(header, dict) and isinstance(header.get("id"), str):
            out[header["id"]] = header
    return out


def owner_of(header: Optional[dict]) -> Optional[str]:
    """The header's author, as a person reads it: `authorDisplayName`, else `authorName`;
    None when neither is a non-empty string (`owner` is a user id, never shown)."""
    for key in ("authorDisplayName", "authorName"):
        value = (header or {}).get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def created_date(created_ms: Any) -> Optional[str]:
    """A header's `created` (epoch milliseconds) as a UTC date, YYYY-MM-DD; None when it is
    not a number."""
    if not isinstance(created_ms, (int, float)) or isinstance(created_ms, bool):
        return None
    return datetime.datetime.fromtimestamp(created_ms / 1000,
                                           tz=datetime.timezone.utc).date().isoformat()


def model_status(usage: dict, guid: str, idle_days: float, created_ms: Any) -> str:
    """One of STATUSES for a Model, from readable usage (module docstring). "too_new" is
    the never-queried Model that H17 would report but for its creation time."""
    days, idle = idle_reading(usage, guid, idle_days, created_ms)
    if idle is not None:
        return "never" if days is None else "idle"
    reading = model_usage(usage, guid)
    if reading["never"]:
        if idle_reading(usage, guid, idle_days, None)[1] is not None:
            return "too_new"
        return "not_judged"
    return "not_judged" if reading["days"] is None else "active"


def dependent_counts(rows: Any, sets_read: Optional[bool]) -> Dict[str, Optional[int]]:
    """`{total, liveboards, answers, sets, other}` from a Model's `ctx.dependents` rows;
    `sets` is None when the run did not fetch Sets (`sets_read` False), and `total` then
    counts the rest. A Set counts toward the total: removing the Model removes it."""
    counts: Dict[str, Optional[int]] = {"liveboards": 0, "answers": 0, "sets": 0, "other": 0}
    for row in rows or []:
        if isinstance(row, dict):
            kind = _KINDS.get(row.get("type"), "other")
            counts[kind] += 1
    if sets_read is False:
        counts["sets"] = None
    counts = {"total": sum(v for v in counts.values() if v), **counts}
    return counts


def status_idle_days(ran: Optional[dict]) -> float:
    """The idle days the statuses use: H17's for this run (usage.idle_days_of), else the
    catalog's own `idle_days` for its usage rules (a replay whose rules did not include
    H17)."""
    days = idle_days_of(ran or {})
    if days is not None:
        return days
    from ts_cli.audit.catalog_model import load_catalog
    rules = load_catalog().rules.values()
    return min(r.parameters["idle_days"] for r in rules
               if "usage" in (r.requires or []) and "idle_days" in (r.parameters or {}))


def add_triage(models_out: list, ctx: Any, ran: Optional[dict],
               fetched_needs: Optional[set]) -> Optional[float]:
    """Add `status`, `dependents`, `owner` and `created` to each corpus Model's `usage`,
    and return the idle days the statuses used (status_idle_days); None, adding nothing,
    when usage was not read. `fetched_needs` (None: not known) says whether Sets were
    fetched, so a Model's Sets read None, not 0, when they were not."""
    if not usage_readable(ctx.usage):
        return None
    idle_days = status_idle_days(ran)
    sets_read = None if fetched_needs is None else "sets" in fetched_needs
    headers = headers_by_id(ctx.metadata)
    for m in models_out:
        usage = m.get("usage")
        if not isinstance(usage, dict):
            continue
        header = headers.get(m["guid"]) or {}
        usage.update({
            "status": model_status(ctx.usage, m["guid"], idle_days, header.get("created")),
            "dependents": dependent_counts(ctx.dependents.get(m["guid"]), sets_read),
            "owner": owner_of(header),
            "created": created_date(header.get("created")),
        })
    return idle_days


def with_status_days(usage: Optional[dict], idle_days: Optional[float]) -> Optional[dict]:
    """`corpus.usage` with `status_idle_days`, the idle days each Model's status used."""
    if usage is not None:
        usage["status_idle_days"] = idle_days
    return usage
