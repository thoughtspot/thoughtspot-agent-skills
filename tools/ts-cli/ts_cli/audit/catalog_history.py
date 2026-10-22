"""Rule-id history: an id, once in the catalog, is never removed and never reused.

A finding's `check_id` is how a reader of audit JSON — a past report, a tracker, a
diff between two runs — knows what it is about. So a rule is retired, never deleted
(`status: retired` keeps the id allocated), and a retired id never comes back as a
rule that runs again. `history_problems(base, head, ref)` compares two catalogs, each
`{rule id: entry}` as read from YAML (`rule_entries`):

  * an id at `ref` that is gone now -> "removed (retire it instead)";
  * an id retired at `ref` that is active now -> "a retired id reused".

`status` is overridable per profile, so "retired" and "active" are judged on the
EFFECTIVE status under each profile (a profile's non-null `status` override, else the
rule's own): retired at `ref` means retired under every profile — a rule active under
one profile never stopped running — and active now means active under any profile, so
a retired rule revived only through `profiles.<p>.status` is caught.

The gate (tools/validate/check_audit_catalog.py --base <ref>) reads `ref`'s catalog
with git and passes both here. Kept importable on Python 3.9 with only PyYAML.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from ts_cli.audit.catalog_model import RULES_DIR


def rule_entries(raw: Dict[str, Iterable[Any]]) -> Dict[str, Dict[str, Any]]:
    """`{id: entry}` over the rule files of a `load_raw`-shaped mapping (first wins, as
    the loader keeps it)."""
    out: Dict[str, Dict[str, Any]] = {}
    for file, entries in raw.items():
        if not file.startswith(f"{RULES_DIR}/"):
            continue
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("id"):
                out.setdefault(str(entry["id"]), entry)
    return out


def _status(entry: Dict[str, Any]) -> str:
    return str(entry.get("status") or "active")


def statuses(entry: Dict[str, Any], profiles: Iterable[str]) -> Dict[str, str]:
    """`{profile: effective status}` — the profile's non-null `status` override, else
    the rule's own. With no profiles, the rule's own status under the key ''."""
    own = _status(entry)
    overrides = entry.get("profiles") if isinstance(entry.get("profiles"), dict) else {}
    out = {}
    for pid in profiles:
        block = overrides.get(pid)
        value = block.get("status") if isinstance(block, dict) else None
        out[pid] = str(value) if value is not None else own
    return out or {"": own}


def profile_ids(*raws: Dict[str, Iterable[Any]]) -> List[str]:
    """Profile ids declared in any of the given `load_raw`-shaped catalogs."""
    ids: List[str] = []
    for raw in raws:
        for entry in raw.get("profiles.yaml") or []:
            if isinstance(entry, dict) and entry.get("id") and str(entry["id"]) not in ids:
                ids.append(str(entry["id"]))
    return ids


def history_problems(base: Dict[str, Dict[str, Any]], head: Dict[str, Dict[str, Any]],
                     ref: str, profiles: Iterable[str] = ()) -> List[str]:
    """Ids removed since `ref`, and ids retired (under every profile) at `ref` that are
    active (under any profile) again."""
    profiles = list(profiles)
    out: List[str] = []
    for rid, old in base.items():
        new = head.get(rid)
        if new is None:
            out.append(f"{rid}: removed since {ref} — a rule id is permanent: set "
                       "`status: retired` instead of deleting the entry")
            continue
        was_retired = set(statuses(old, profiles).values()) == {"retired"}
        active_under = [p or "the catalog" for p, s in statuses(new, profiles).items()
                        if s != "retired"]
        if was_retired and active_under:
            was, now = old.get("title", ""), new.get("title", "")
            what = f" (was '{was}', now '{now}')" if was != now else ""
            out.append(f"{rid}: retired at {ref} and active again under "
                       f"{', '.join(active_under)}{what} — a retired id is never reused: "
                       "give the rule a new id")
    return out
