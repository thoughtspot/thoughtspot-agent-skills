"""What the audit keeps of a `connection/search` entry: a few derived facts, never a
configuration value.

`POST /api/rest/2.0/connection/search` with `include_details: true` answers each
connection as `{id, name, data_warehouse_type, details: {type, configuration, ...}}`,
where `details.configuration` is a JSON string of the connection's settings (live probe,
the SE demo cluster, 2026-11-18; ts-audit open-items #17). The configuration holds
credentials. They were masked (`******`) in what the probe saw, but nothing here relies
on that: `connection_facts` parses it, derives four booleans and drops it, so no
configuration value reaches the audit context, a snapshot, the audit JSON, a warning
or a log line.

    oauth          a configuration key, at any depth, containing `oauth` (any case:
                   `OAuth2ClientId`, `OAuth2Secret`, `oauth_pvt_key` were seen), or both
                   `client_id` and `client_secret` (an OAuth M2M service principal).
                   Read from key names: the response has no auth-type field. A key
                   counts only when its value is set (_is_set): not null, false,
                   empty, or text reading "false" or "null".
    oauth_m2m      `oauth` rests only on a client ID and secret, whose kind of OAuth the
                   product owner's team is to confirm (open-items #18): the
                   `client_id` and `client_secret` pair on any connection, or, on a
                   Databricks connection or one whose type is not given, OAuth read
                   only from `OAuth2ClientId`, `OAuth2Secret` or both (no other setting
                   naming OAuth). On the SE demo cluster, 12 of its 14
                   Databricks connections use OAuth, and each holds just that pair
                   (2026-11-19), which per-user OAuth and a service principal (M2M)
                   both use, so the names cannot tell them apart.
    privatelink    a `host` or `accountName` value (any case of key) containing
                   `privatelink` (any case): a Snowflake PrivateLink URL carries
                   `.privatelink.`. No configuration key names PrivateLink; the team is
                   to confirm the host is a sound signal (open-items #18).
    parameterized  a configuration value that is wholly a `${var}` template token
                   (publish_plan.parse_variable_token, as connection parameterization
                   writes it). The search was seen returning a parameterized
                   connection's settings without its tokens (open-items #17), so this
                   rarely holds; `parameterized_connection` is the signal.
    parameterized_connection
                   the connection's metadata header says it is parameterized
                   (header_parameterized). The search does not carry the header, so
                   `connection_facts` leaves it None and the audit's fetch fills it from
                   a CONNECTION metadata search (audit/context.py).

A configuration that is absent, does not parse as a JSON object, parses to `{}` or holds
none of the keys the OAuth and PrivateLink readings read leaves those flags None:
unknown, never "no" (_flags). Pure; stdlib and publish_plan only.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, Optional, Tuple

from ts_cli.publish_plan import parse_variable_token

#: The version of how `connection_facts` derives its flags. A snapshot keeps only the
#: derived facts, never the settings, so a replay cannot derive them again: bump this
#: whenever any entry's facts change, and a snapshot recording an older version (or
#: none) is refused for the rules that read them (audit/snapshot.py). The golden table
#: in tests/test_audit_connections_data.py fails until it is bumped.
#: 1: ts-cli 0.219.0 to 0.220.0 (no `derived` recorded). 2: from 0.221.0, a Databricks OAuth2ClientId/OAuth2Secret pair alone
#: (either key or both, on Databricks or a connection with no type) reads as
#: `oauth_m2m` (to confirm); the Databricks comparison ignores an `RDBMS_` prefix.
FACTS_VERSION = 2

#: The keys `connection_facts` returns, and the only ones the audit stores.
CONNECTION_KEYS = ("id", "name", "type", "oauth", "oauth_m2m", "privatelink", "parameterized",
                   "parameterized_connection")
#: The metadata header keys that say a connection is parameterized (seen on every
#: CONNECTION header of the SE demo cluster, 2026-11-18).
HEADER_PARAMETERIZED_KEYS = ("parameterizedConnection", "isParameterized")
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


def _entries(value: Any, depth: int = 0,
             key: Optional[str] = None) -> Iterator[Tuple[Optional[str], Any]]:
    """Every (key, value) pair in a configuration, nested mappings and lists walked: a
    mapping's entry comes with its value (a nested mapping or list included), then what
    that value holds; a list's items come with the key of the list (`key`)."""
    if depth > _MAX_DEPTH:
        return
    if isinstance(value, dict):
        for name, inner in value.items():
            name = name if isinstance(name, str) else None
            yield name, inner
            if isinstance(inner, (dict, list)):
                yield from _entries(inner, depth + 1, name)
    elif isinstance(value, list):
        for inner in value:
            if isinstance(inner, (dict, list)):
                yield from _entries(inner, depth + 1, key)
            else:
                yield key, inner


#: Text that sets nothing, case and edge spaces aside.
_UNSET_TEXT = ("", "false", "null")


def _is_set(value: Any) -> bool:
    """A setting holds something: not null, false, zero or empty, and not text reading
    "", "false" or "null"."""
    if isinstance(value, str):
        return value.strip().casefold() not in _UNSET_TEXT
    return bool(value)


#: Keys whose presence lets the OAuth and PrivateLink readings judge a configuration:
#: one naming OAuth, an M2M client pair, or a host. A configuration with none of them
#: (`{}`, or only a user and password) says nothing either way.
_M2M_KEYS = ("client_id", "client_secret")
#: The client ID and secret a Databricks OAuth connection holds (case folded), used by
#: per-user OAuth and by a service principal alike (oauth_m2m in the module docstring).
_DATABRICKS_OAUTH_PAIR = frozenset(("oauth2clientid", "oauth2secret"))


def _read_entries(config: dict) -> Tuple[set, set, list, bool]:
    """What _flags reads of a configuration: every key (case folded), the keys whose
    value is set (_is_set), the text of each host or account name, and whether any value
    is wholly a template token. A blank host or account name holds no text, so it is
    not a host."""
    present, keys, hosts = set(), set(), []
    parameterized = False
    for key, value in _entries(config):
        folded = (key or "").casefold()
        present.add(folded)
        if _is_set(value):
            keys.add(folded)
        if not isinstance(value, str):
            continue
        if folded in _HOST_KEYS and value.strip():
            hosts.append(value)
        if parse_variable_token(value) is not None:
            parameterized = True
    return present, keys, hosts, parameterized


def warehouse_type(kind: Any) -> Optional[str]:
    """A warehouse type as compared: upper case, edge spaces and an `RDBMS_` prefix
    dropped (a connection's `data_warehouse_type` was seen bare, a Table header's
    `dataSourceType` prefixed); None for anything blank or not text. P23 and P24 both
    compare types through it."""
    if not isinstance(kind, str) or not kind.strip():
        return None
    text = kind.strip().upper()
    return text[len("RDBMS_"):] if text.startswith("RDBMS_") else text


def _flags(config: dict, warehouse: Optional[str] = None) -> Dict[str, Optional[bool]]:
    """The four flags of a parsed configuration (module docstring). OAuth and PrivateLink
    are None, unknown, when no key they read is present (_M2M_KEYS, a key naming OAuth,
    _HOST_KEYS); PrivateLink is None too when no host or account name holds text. A
    template variable is True when a value is one, else False for a configuration the
    readings can judge and None for one they cannot. `warehouse` is the connection's
    type: on DATABRICKS, or with no type given, OAuth resting only on keys of
    _DATABRICKS_OAUTH_PAIR is oauth_m2m."""
    present, keys, hosts, parameterized = _read_entries(config)
    readable = any("oauth" in k for k in present) or bool(
        present & (set(_M2M_KEYS) | set(_HOST_KEYS)))
    if not readable:
        return {"oauth": None, "oauth_m2m": None, "privatelink": None,
                "parameterized": True if parameterized else None}
    oauth_keys = {k for k in keys if "oauth" in k}
    named = bool(oauth_keys)
    m2m = (not named and set(_M2M_KEYS) <= keys) or (
        warehouse_type(warehouse) in ("DATABRICKS", None)
        and named and oauth_keys <= _DATABRICKS_OAUTH_PAIR)
    privatelink = any("privatelink" in h.casefold() for h in hosts) if hosts else None
    return {"oauth": named or m2m, "oauth_m2m": m2m, "privatelink": privatelink,
            "parameterized": parameterized}


def connection_facts(entry: Any) -> Optional[Dict[str, Any]]:
    """`{id, name, type, oauth, oauth_m2m, privatelink, parameterized,
    parameterized_connection}` for one `connection/search` entry (see the module
    docstring; `parameterized_connection` None, for the fetch to fill), or None for an
    entry that is not a mapping. `type`
    is `data_warehouse_type`, else `details.type`; each text field None when absent."""
    if not isinstance(entry, dict):
        return None
    details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
    config = _configuration(details.get("configuration"))
    kind = _text(entry.get("data_warehouse_type")) or _text(details.get("type"))
    flags = _flags(config, kind) if config is not None else \
        {"oauth": None, "oauth_m2m": None, "privatelink": None, "parameterized": None}
    return {"id": _text(entry.get("id")), "name": _text(entry.get("name")),
            "type": kind, **flags, "parameterized_connection": None}


def header_parameterized(header: Any) -> Optional[bool]:
    """Whether a CONNECTION metadata header says the connection is parameterized: True
    when either HEADER_PARAMETERIZED_KEYS value is the boolean true, False when one is
    the boolean false and neither is true, None when neither is a boolean (unknown,
    never "no"). Reads nothing else of the header."""
    values = [header.get(k) for k in HEADER_PARAMETERIZED_KEYS] if isinstance(header, dict) else []
    flags = [v for v in values if isinstance(v, bool)]
    if any(flags):
        return True
    return False if flags else None
