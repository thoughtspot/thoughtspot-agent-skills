"""Unit tests for ts_cli.commands.share — payload builders and pure helpers."""
from __future__ import annotations

import pytest

from ts_cli.commands.share import build_share_payload


def _perm(group="Analyst", mode="READ_ONLY"):
    return [{"principal": {"type": "USER_GROUP", "identifier": group}, "share_mode": mode}]


def test_build_share_payload_puts_message_at_the_top_level():
    """The single fact that blocks every share call if it is wrong.

    Every published example nests `message` inside `notification`; the API rejects that
    with `Variable "$message" of required type "String!" was not provided`. The
    shareMetadata request schema agrees with the live behaviour: message and
    notify_on_share are top-level, and message is required.
    """
    payload = build_share_payload(["guid-1"], "LOGICAL_TABLE", _perm(),
                                  message="granting tenant access")
    assert payload["message"] == "granting tenant access"
    assert "notification" not in payload
    assert payload["notify_on_share"] is False


def test_build_share_payload_shape():
    payload = build_share_payload(["g1", "g2"], "LOGICAL_COLUMN", _perm(),
                                  message="m", notify_on_share=True)
    assert payload == {
        "metadata_type": "LOGICAL_COLUMN",
        "metadata_identifiers": ["g1", "g2"],
        "permissions": _perm(),
        "message": "m",
        "notify_on_share": True,
    }


def test_build_share_payload_accepts_logical_column():
    """LOGICAL_COLUMN is absent from the docs' supported-object list but works."""
    payload = build_share_payload(["c1"], "LOGICAL_COLUMN", _perm(), message="m")
    assert payload["metadata_type"] == "LOGICAL_COLUMN"


def test_build_share_payload_dedupes_identifiers_preserving_order():
    payload = build_share_payload(["g2", "g1", "g2"], "LOGICAL_TABLE", _perm(), message="m")
    assert payload["metadata_identifiers"] == ["g2", "g1"]


def test_build_share_payload_rejects_unsupported_type():
    with pytest.raises(ValueError, match="CONNECTION"):
        build_share_payload(["g1"], "CONNECTION", _perm(), message="m")


def test_build_share_payload_rejects_empty_identifiers():
    with pytest.raises(ValueError, match="at least one object"):
        build_share_payload([], "LOGICAL_TABLE", _perm(), message="m")


def test_build_share_payload_rejects_empty_permissions():
    with pytest.raises(ValueError, match="at least one principal"):
        build_share_payload(["g1"], "LOGICAL_TABLE", [], message="m")


def test_build_share_payload_rejects_blank_message():
    """`message` is required by the schema, so an empty one fails server-side."""
    with pytest.raises(ValueError, match="message"):
        build_share_payload(["g1"], "LOGICAL_TABLE", _perm(), message="   ")


def test_client_accepts_an_explicit_org_overriding_the_env(monkeypatch):
    """Per-Org grants need a per-Org token without mutating process state."""
    from ts_cli import client as client_module

    profiles = {"p": {"base_url": "https://example.thoughtspot.cloud",
                      "token_env": "THOUGHTSPOT_TOKEN_P"}}
    monkeypatch.setattr(client_module, "load_profiles", lambda: profiles)
    monkeypatch.setenv("TS_ORG", "Primary")

    scoped = client_module.ThoughtSpotClient("p", org="ORG1")
    assert scoped._org == "ORG1"
    assert "org1" in scoped._cache_key()

    default = client_module.ThoughtSpotClient("p")
    assert default._org == "Primary"
