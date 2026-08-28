"""Tests for Domo profile + developer-token resolution (ts-profile-domo).

Covers the contract the skill documents: the token resolves from the env var first,
falls back to the OS credential store, and is never persisted to the profile file.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from ts_cli import profile_ops
from ts_cli.cli import app
from ts_cli.domo import client as domo_client

runner = CliRunner()


@pytest.fixture
def domo_profiles(tmp_path, monkeypatch):
    path = tmp_path / "domo-profiles.json"
    monkeypatch.setattr(
        profile_ops, "PROFILE_PATHS", {**profile_ops.PROFILE_PATHS, "domo": path}
    )
    return path


def _write(path, profiles):
    path.write_text(json.dumps(profiles))


class TestProfileResolution:
    def test_no_profiles_points_at_skill(self, domo_profiles):
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile()
        assert "ts-profile-domo" in str(e.value)

    def test_single_profile_resolves_without_name(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "auth": "developer-token",
                                "token_env": "DOMO_TOK_ACME"}])
        monkeypatch.setenv("DOMO_TOK_ACME", "tok-123")
        c = domo_client.client_from_profile()
        assert c.base == "https://acme.domo.com"
        assert c._headers()["X-DOMO-Developer-Token"] == "tok-123"

    def test_multiple_profiles_require_explicit_name(self, domo_profiles):
        _write(domo_profiles, [
            {"name": "A", "instance": "https://a.domo.com", "token_env": "T_A"},
            {"name": "B", "instance": "https://b.domo.com", "token_env": "T_B"},
        ])
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile()
        assert "--profile" in str(e.value)

    def test_named_profile_selected(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [
            {"name": "A", "instance": "https://a.domo.com", "token_env": "T_A"},
            {"name": "B", "instance": "https://b.domo.com", "token_env": "T_B"},
        ])
        monkeypatch.setenv("T_B", "tok-b")
        assert domo_client.client_from_profile("B").base == "https://b.domo.com"

    def test_unknown_profile_name_errors(self, domo_profiles):
        _write(domo_profiles, [{"name": "A", "instance": "https://a.domo.com"}])
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile("nope")
        assert "not found" in str(e.value)

    def test_missing_instance_field_errors(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "A", "token_env": "T_A"}])
        monkeypatch.setenv("T_A", "tok")
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile()
        assert "instance" in str(e.value)

    def test_scheme_added_when_missing(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "A", "instance": "acme.domo.com",
                                "token_env": "T_A"}])
        monkeypatch.setenv("T_A", "tok")
        assert domo_client.client_from_profile().base == "https://acme.domo.com"


class TestTokenResolution:
    def test_keychain_fallback_used_when_env_unset(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_UNSET"}])
        monkeypatch.delenv("DOMO_TOK_UNSET", raising=False)

        calls = {}

        class FakeKeyring:
            @staticmethod
            def get_password(service, account):
                calls["service"] = service
                calls["account"] = account
                return "tok-from-keychain"

        monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)
        c = domo_client.client_from_profile()
        assert c._headers()["X-DOMO-Developer-Token"] == "tok-from-keychain"
        assert calls == {"service": "domo-acme", "account": "developer-token"}

    def test_no_credential_anywhere_points_at_skill(self, domo_profiles, monkeypatch):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_NONE"}])
        monkeypatch.delenv("DOMO_TOK_NONE", raising=False)

        class FakeKeyring:
            @staticmethod
            def get_password(service, account):
                return None

        monkeypatch.setitem(__import__("sys").modules, "keyring", FakeKeyring)
        with pytest.raises(SystemExit) as e:
            domo_client.client_from_profile()
        assert "ts-profile-domo" in str(e.value)


class TestSigninCommand:
    def test_signin_reports_reachability_without_printing_token(
        self, domo_profiles, monkeypatch
    ):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_S"}])
        monkeypatch.setenv("DOMO_TOK_S", "super-secret-token")
        monkeypatch.setattr(domo_client.DomoClient, "list_datasets",
                            lambda self, limit=200: [{"id": "1"}, {"id": "2"}])
        monkeypatch.setattr(domo_client.DomoClient, "list_pages",
                            lambda self, limit=100: [{"id": "p1"}])

        result = runner.invoke(app, ["domo", "signin", "--profile", "Acme"])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["ok"] is True
        assert out["reachable"] == {"datasets": 2, "pages": 1}
        assert "super-secret-token" not in result.output

    def test_signin_exits_nonzero_when_nothing_reachable(
        self, domo_profiles, monkeypatch
    ):
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_F"}])
        monkeypatch.setenv("DOMO_TOK_F", "tok")

        def boom(self, **kwargs):
            raise domo_client.DomoError("HTTP 401: unauthorized")

        monkeypatch.setattr(domo_client.DomoClient, "list_datasets", boom)
        monkeypatch.setattr(domo_client.DomoClient, "list_pages", boom)

        result = runner.invoke(app, ["domo", "signin", "--profile", "Acme"])
        assert result.exit_code == 1
        assert "FAILED" in result.output


# ---------------------------------------------------------------------------
# Credential-path hardening (PR #440 third review)
#
# Each test here corresponds to a reproduced way the Domo developer token could
# leave the machine, or a way a mistyped/hostile instance URL became an SSRF or
# exfiltration primitive. The token travels in a CUSTOM header, so the stdlib's
# protections for `Authorization` do not apply to it.
# ---------------------------------------------------------------------------


class TestInstanceValidation:
    @pytest.mark.parametrize("instance,because", [
        ("http://acme.domo.com", "plain HTTP would send the token in cleartext"),
        ("https://acme.domo.com@example.com", "userinfo redirects the real host"),
        ("https://evil.com/?x=", "a query string turns every path into a parameter"),
        ("https://acme.domo.com/some/path", "a path prefix is not a bare origin"),
        ("169.254.169.254", "cloud metadata service"),
        ("127.0.0.1", "loopback"),
        ("10.1.2.3", "private range"),
        ("192.168.0.9", "private range"),
        ("[::1]", "IPv6 loopback"),
        ("", "empty"),
    ])
    def test_refused(self, instance, because):
        from ts_cli.domo.client import DomoError, normalise_instance
        with pytest.raises(DomoError):
            normalise_instance(instance)

    @pytest.mark.parametrize("instance,expected", [
        ("acme.domo.com", "https://acme.domo.com"),
        ("https://acme.domo.com", "https://acme.domo.com"),
        ("https://acme.domo.com/", "https://acme.domo.com"),
        ("  https://acme.domo.com  ", "https://acme.domo.com"),
    ])
    def test_accepted(self, instance, expected):
        from ts_cli.domo.client import normalise_instance
        assert normalise_instance(instance) == expected

    def test_no_bypass_flag_exists(self):
        """A security control with an override is not a control.

        Grepping for literals caught 1 of 8 realistic bypasses (and one of the five it
        looked for was a `requests` idiom this module doesn't use), so this asserts
        POSITIVE properties of the code instead: no TLS context is constructed, no
        env var can relax validation, and every request goes through the one opener.
        """
        import inspect

        from ts_cli.domo import client
        src = inspect.getsource(client)

        # No way to build or weaken an SSL context.
        for banned in ("ssl.", "_create_unverified", "SSLContext", "CERT_NONE",
                       "check_hostname", "verify=False", "verify = False"):
            assert banned not in src, f"TLS control surface present: {banned}"

        # Validation must not be reachable from the environment.
        env_reads = [ln for ln in src.splitlines()
                     if "os.environ" in ln or "getenv" in ln]
        for ln in env_reads:
            assert "token_env" in ln or "env_var" in ln, (
                f"environment read outside credential resolution: {ln.strip()}")

        # Exactly one request path, and it uses the redirect-refusing opener.
        assert src.count("urlopen(") == 0, "a bare urlopen bypasses the opener"
        assert src.count("self._opener.open(") == 1, "more than one request path"

        # The scheme allowlist is a constant, not a parameter.
        assert '_ALLOWED_SCHEMES = ("https",)' in src

    def test_control_bytes_are_stripped_from_server_text(self):
        from ts_cli.domo.client import _safe
        assert _safe("Forbidden\x1b[2J\x07\x08bad") == "Forbidden[2Jbad"
        assert "\x1b" not in _safe("\x1b]0;title\x07")

    def test_undecodable_body_is_an_error_not_a_traceback(self, monkeypatch):
        import io

        from ts_cli.domo.client import DomoClient, DomoError

        c = DomoClient("acme.domo.com", "tok")

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(c._opener, "open",
                            lambda *a, **k: Resp(b"\xff\xfe not utf-8"))
        with pytest.raises(DomoError) as e:
            c.list_datasets()
        assert "not" in str(e.value).lower()


class TestRedirectsAreRefused:
    def test_handler_raises_rather_than_following(self):
        """urllib rebuilds custom headers onto the redirect target."""
        from ts_cli.domo.client import DomoError, _NoRedirect
        with pytest.raises(DomoError) as e:
            _NoRedirect().redirect_request(
                None, None, 302, "Found", {}, "https://evil.example/steal")
        assert "refusing to follow" in str(e.value)

    def test_client_installs_the_handler(self):
        from ts_cli.domo.client import DomoClient, _NoRedirect
        c = DomoClient("acme.domo.com", "tok")
        assert any(isinstance(h, _NoRedirect) for h in c._opener.handlers)


class TestServerTextNeverReachesTheTerminal:
    def test_http_error_body_is_not_interpolated(self, monkeypatch):
        """`ts domo signin` prints DomoError text; the body is chosen by the host."""
        import urllib.error

        from ts_cli.domo.client import DomoClient, DomoError

        c = DomoClient("acme.domo.com", "tok")

        import io

        def _raise(*_a, **_k):
            raise urllib.error.HTTPError(
                "https://acme.domo.com/x", 403, "Forbidden", {},
                io.BytesIO(b"ECHOED-SECRET-TOKEN-abc123"))

        monkeypatch.setattr(c._opener, "open", _raise)
        with pytest.raises(DomoError) as e:
            c.list_datasets()
        assert "ECHOED-SECRET" not in str(e.value)
        assert "403" in str(e.value)


class TestTokenIsNotAConstructorLocal:
    def test_profile_path_defers_resolution(self, domo_profiles, monkeypatch):
        """A raw secret in a frame can be rendered into a traceback panel."""
        _write(domo_profiles, [{"name": "Acme", "instance": "https://acme.domo.com",
                                "token_env": "DOMO_TOK_LAZY"}])
        monkeypatch.setenv("DOMO_TOK_LAZY", "tok-lazy")
        c = domo_client.client_from_profile()
        assert c._token is None, "the resolved secret must not be stored on the client"
        assert c._token_provider is not None
        assert c._headers()["X-DOMO-Developer-Token"] == "tok-lazy"

    def test_typer_never_renders_locals(self):
        from ts_cli.cli import app
        assert app.pretty_exceptions_show_locals is False
