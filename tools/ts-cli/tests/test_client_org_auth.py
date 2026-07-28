"""Org-scoped auth on `ThoughtSpotClient`.

Targets the `org=` keyword that landed on main (PR #346), which superseded this branch's
earlier `org_id=` parameter. Main's is the live-verified version: `auth/token/full` takes
`org_id` as an INT and SILENTLY IGNORES a non-numeric `org_identifier`, so
`_org_auth_fields` resolves the distinction instead of passing a name straight through.

Kept rather than deleted at the merge, because three branch behaviours here are not
covered elsewhere: the unscoped cache path, the secret_key branch carrying the org, and
the bearer-token branch deliberately not carrying it.

`ts migrate audit` is why this matters — it authenticates to two Orgs (source + clean) on
the same cluster in one process, so the token cache must be disambiguated by org or the
second session silently reuses the first's token.

Note: env vars are set via `monkeypatch.setenv` (function-scoped, reverts at test
teardown) rather than a `with patch.dict` inside the client helper — a `with`-scoped patch
reverts at the end of the helper, before `client._authenticate()` runs in the test body,
which would make the credential lookup fail regardless of the behaviour under test.
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


def _make_client(monkeypatch, org):
    monkeypatch.setenv("TS_PW", "secret")
    with patch("ts_cli.client.load_profiles", return_value={"p": _PROFILE}):
        return ThoughtSpotClient("p", org=org)


def _mock_ok_session():
    session = MagicMock()
    session.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"token": "tok", "expiration_time_in_millis": 0},
    )
    return session


def test_org_id_included_in_token_body(monkeypatch):
    client = _make_client(monkeypatch, org=3)
    session = _mock_ok_session()
    client._session = session
    client._authenticate()
    body = session.post.call_args.kwargs["json"]
    assert body["org_id"] == 3


def test_token_cache_key_disambiguates_by_org(monkeypatch):
    c0 = _make_client(monkeypatch, org=0)
    c1 = _make_client(monkeypatch, org=1)
    assert c0._token_path() != c1._token_path()


def test_org_id_defaults_to_none_and_omitted_from_body(monkeypatch):
    """Backward compatibility: no org_id passed -> no org_id key in the request body."""
    client = _make_client(monkeypatch, org=None)
    session = _mock_ok_session()
    client._session = session
    client._authenticate()
    body = session.post.call_args.kwargs["json"]
    assert "org_id" not in body


def test_org_id_defaults_to_none_and_cache_path_unchanged(monkeypatch):
    """Backward compatibility: omitting the org entirely must match the unscoped cache path."""
    monkeypatch.setenv("TS_PW", "secret")
    with patch("ts_cli.client.load_profiles", return_value={"p": _PROFILE}):
        client_no_kwarg = ThoughtSpotClient("p")
        client_explicit_none = ThoughtSpotClient("p", org=None)
    assert client_no_kwarg._token_path() == client_explicit_none._token_path()


def test_org_id_included_in_secret_key_token_body(monkeypatch):
    """The org must reach the secret_key auth branch too, not just password.

    Easy to add to one branch and forget the other, and the failure is silent: the token
    is minted in the caller's DEFAULT Org and every later call quietly runs there."""
    profile = {
        "base_url": "https://ts.example.com",
        "username": "u",
        "secret_key_env": "TS_SK",
        "verify_ssl": True,
    }
    monkeypatch.setenv("TS_SK", "secret-key")
    with patch("ts_cli.client.load_profiles", return_value={"p": profile}):
        client = ThoughtSpotClient("p", org=7)
    session = _mock_ok_session()
    client._session = session
    client._authenticate()
    body = session.post.call_args.kwargs["json"]
    assert body["org_id"] == 7


def test_org_id_not_included_for_token_env_branch(monkeypatch):
    """Browser bearer tokens are pre-scoped to their issuing Org, so no org field applies.

    `_authenticate` returns the token before reaching any auth/token/full call, which is
    what this asserts via `post.assert_not_called()`."""
    profile = {
        "base_url": "https://ts.example.com",
        "username": "u",
        "token_env": "TS_TOKEN",
        "verify_ssl": True,
    }
    monkeypatch.setenv("TS_TOKEN", "bearer-tok")
    with patch("ts_cli.client.load_profiles", return_value={"p": profile}):
        client = ThoughtSpotClient("p", org=9)
    session = MagicMock()
    client._session = session
    token, expiry = client._authenticate()
    assert token == "bearer-tok"
    session.post.assert_not_called()
