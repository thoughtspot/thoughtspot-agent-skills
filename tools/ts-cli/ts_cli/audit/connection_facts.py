"""What the audit keeps of a `connection/search` entry: a few derived facts, never a
configuration value.

`POST /api/rest/2.0/connection/search` with `include_details: true` answers each
connection as `{id, name, data_warehouse_type, details: {type, configuration, ...}}`,
where `details.configuration` is a JSON string of the connection's settings (live probe,
the SE demo cluster, 2026-11-18; ts-audit open-items #17). The configuration holds
credentials. They were masked (`******`) in what the probe saw, but nothing here relies
on that: `connection_facts` parses it, derives three booleans and drops it, so no
configuration value reaches the audit context, a snapshot, the audit JSON, a warning
or a log line.

    oauth          a configuration key, at any depth, containing `oauth` (any case:
                   `OAuth2ClientId`, `OAuth2Secret`, `oauth_pvt_key` were seen), or both
                   `client_id` and `client_secret` (a Databricks OAuth M2M service
                   principal). Read from key names: the response has no auth-type field.
    privatelink    a `host` or `accountName` value (any case of key) containing
                   `privatelink` (any case): a Snowflake PrivateLink URL carries
                   `.privatelink.`. No configuration key names PrivateLink.
    parameterized  a configuration value that is wholly a `${var}` template token
                   (publish_plan.parse_variable_token, as connection parameterization
                   writes it).

A configuration that is absent or does not parse as a JSON object leaves all three
None: unknown, never "no". Pure; stdlib and publish_plan only.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, Optional, Tuple

from ts_cli.publish_plan import parse_variable_token

#: The keys `connection_facts` returns, and the only ones the audit stores.
CONNECTION_KEYS = ("id", "name", "type", "oauth", "privatelink", "parameterized")
#: How deep a configuration is walked: far beyond any seen (they are flat).
_MAX_DEPTH = 8
_HOST_KEYS = ("host", "accountname")


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _configuration(raw: Any) -> Optional[dict]:
    """The configuration as a mapping: a JSON string parsed, a mapping as it is; None
    for anything else (the parse error is dropped, never reported: its message can
    quote the text)."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _entries(value: Any, depth: int = 0) -> Iterator[Tuple[Optional[str], Any]]:
    """Every (key, value) pair in a configuration, nested mappings and lists walked;
    a list's items come with the key of the list."""
    if depth > _MAX_DEPTH:
        return
    if isinstance(value, dict):
        for key, inner in value.items():
            name = key if isinstance(key, str) else None
            if isinstance(inner, (dict, list)):
                yield name, None
                yield from _entries(inner, depth + 1)
            else:
                yield name, inner
    elif isinstance(value, list):
        for inner in value:
            if isinstance(inner, (dict, list)):
                yield from _entries(inner, depth + 1)
            else:
                yield None, inner


def _flags(config: dict) -> Dict[str, bool]:
    keys = set()
    privatelink = parameterized = False
    for key, value in _entries(config):
        folded = (key or "").casefold()
        keys.add(folded)
        if folded in _HOST_KEYS and isinstance(value, str) \
                and "privatelink" in value.casefold():
            privatelink = True
        if parse_variable_token(value) is not None:
            parameterized = True
    oauth = any("oauth" in k for k in keys) or {"client_id", "client_secret"} <= keys
    return {"oauth": oauth, "privatelink": privatelink, "parameterized": parameterized}


def connection_facts(entry: Any) -> Optional[Dict[str, Any]]:
    """`{id, name, type, oauth, privatelink, parameterized}` for one `connection/search`
    entry (see the module docstring), or None for an entry that is not a mapping. `type`
    is `data_warehouse_type`, else `details.type`; each text field None when absent."""
    if not isinstance(entry, dict):
        return None
    details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
    config = _configuration(details.get("configuration"))
    flags = _flags(config) if config is not None else \
        {"oauth": None, "privatelink": None, "parameterized": None}
    return {"id": _text(entry.get("id")), "name": _text(entry.get("name")),
            "type": _text(entry.get("data_warehouse_type")) or _text(details.get("type")),
            **flags}
