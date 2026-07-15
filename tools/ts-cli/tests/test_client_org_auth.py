"""
test_client_org_auth.py — unit tests for optional org-scoped auth (org_id) on
ThoughtSpotClient.

Covers Task 6 of Plan 1 (read-only `ts migrate audit`): the audit command needs
to authenticate to two Orgs (source + clean) on the same cluster. `org_id` is
an optional constructor param, added to the password/secret_key auth/token/full
body only (browser bearer tokens are pre-scoped to their issuing Org), and the
token cache key must be disambiguated by org so different-org sessions don't
share a cached token.

Note: env vars are set via `monkeypatch.setenv` (function-scoped, reverts at
test teardown) rather than `patch.dict` as a `with`-block inside the client
helper — a `with`-scoped patch reverts at the end of `_make_client`, before
`client._authenticate()` runs in the test body, which would make the credential
lookup fail regardless of the org_id change under test.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from ts_cli.client import ThoughtSpotClient

_PROFILE = {
    "base_url": "https://ts.example.com",
    "username": "u",
    "password_env": "TS_PW",
    "verify_ssl": True,
}


def _make_client(monkeypatch, org_id):
    monkeypatch.setenv("TS_PW", "secret")
    with patch("ts_cli.client.load_profiles", return_value={"p": _PROFILE}):
        return ThoughtSpotClient("p", org_id=org_id)


def _mock_ok_session():
    session = MagicMock()
    session.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"token": "tok", "expiration_time_in_millis": 0},
    )
    return session


def test_org_id_included_in_token_body(monkeypatch):
    client = _make_client(monkeypatch, org_id=3)
    session = _mock_ok_session()
    client._session = session
    client._authenticate()
    body = session.post.call_args.kwargs["json"]
    assert body["org_id"] == 3


def test_token_cache_key_disambiguates_by_org(monkeypatch):
    c0 = _make_client(monkeypatch, org_id=0)
    c1 = _make_client(monkeypatch, org_id=1)
    assert c0._token_path() != c1._token_path()


def test_org_id_defaults_to_none_and_omitted_from_body(monkeypatch):
    """Backward compatibility: no org_id passed -> no org_id key in the request body."""
    client = _make_client(monkeypatch, org_id=None)
    session = _mock_ok_session()
    client._session = session
    client._authenticate()
    body = session.post.call_args.kwargs["json"]
    assert "org_id" not in body


def test_org_id_defaults_to_none_and_cache_path_unchanged(monkeypatch):
    """Backward compatibility: omitting org_id entirely must match today's cache path."""
    monkeypatch.setenv("TS_PW", "secret")
    with patch("ts_cli.client.load_profiles", return_value={"p": _PROFILE}):
        client_no_kwarg = ThoughtSpotClient("p")
        client_explicit_none = ThoughtSpotClient("p", org_id=None)
    assert client_no_kwarg._token_path() == client_explicit_none._token_path()


def test_org_id_included_in_secret_key_token_body(monkeypatch):
    """org_id must also be included on the secret_key auth branch, not just password."""
    profile = {
        "base_url": "https://ts.example.com",
        "username": "u",
        "secret_key_env": "TS_SK",
        "verify_ssl": True,
    }
    monkeypatch.setenv("TS_SK", "secret-key")
    with patch("ts_cli.client.load_profiles", return_value={"p": profile}):
        client = ThoughtSpotClient("p", org_id=7)
    session = _mock_ok_session()
    client._session = session
    client._authenticate()
    body = session.post.call_args.kwargs["json"]
    assert body["org_id"] == 7


def test_org_id_not_included_for_token_env_branch(monkeypatch):
    """Browser bearer tokens are pre-scoped to their issuing Org — org_id must not apply."""
    profile = {
        "base_url": "https://ts.example.com",
        "username": "u",
        "token_env": "TS_TOKEN",
        "verify_ssl": True,
    }
    monkeypatch.setenv("TS_TOKEN", "bearer-tok")
    with patch("ts_cli.client.load_profiles", return_value={"p": profile}):
        client = ThoughtSpotClient("p", org_id=9)
    session = MagicMock()
    client._session = session
    token, expiry = client._authenticate()
    assert token == "bearer-tok"
    session.post.assert_not_called()
