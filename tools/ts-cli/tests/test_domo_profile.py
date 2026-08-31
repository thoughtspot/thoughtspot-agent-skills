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

    # --- one test per mechanism, because six of them were asserted by NOTHING ----
    #
    # Round 5 deleted each mechanism in turn and the whole file stayed green for six
    # of nine. Every round-3 host bypass could therefore regress silently. Each test
    # below was confirmed to go RED when its mechanism is neutered.

    @pytest.mark.parametrize("sep,name", [
        ("\u3002", "U+3002 IDEOGRAPHIC FULL STOP"),
        ("\uff0e", "U+FF0E FULLWIDTH FULL STOP"),
        ("\uff61", "U+FF61 HALFWIDTH IDEOGRAPHIC FULL STOP"),
        ("\u2024", "U+2024 ONE DOT LEADER"),
        ("\ufe52", "U+FE52 SMALL FULL STOP"),
    ])
    def test_unicode_label_separators_are_refused(self, sep, name):
        """`acme.domo.com<sep>evil.example` connects to evil.example, displays as Domo.

        Two mechanisms produce a separator — the codec's own `dots` regex and
        nameprep's NFKC mapping — and the first fix for this held only one set.
        """
        from ts_cli.domo.client import DomoError, normalise_instance
        with pytest.raises(DomoError):
            normalise_instance(f"https://acme.domo.com{sep}evil.example")

    @pytest.mark.parametrize("shorthand", [
        "2130706433", "127.1", "0177.1", "0x7f.1", "0x7f000001", "017700000001",
        "127.0.1", "0",
    ])
    def test_ipv4_shorthand_is_canonicalised_before_classification(self, shorthand):
        """Loopback to the resolver, but not canonical literals.

        `getaddrinfo` is stubbed to FAIL, deliberately. Without that the shorthand is
        also caught by the resolution guard, so deleting the `inet_aton`
        canonicalisation left this test green — it was asserting the outcome, which two
        mechanisms can produce, rather than the mechanism. The two are not redundant:
        canonicalisation works offline, resolution does not. Verified to go red when
        the `inet_aton` path is removed.
        """
        import socket
        from unittest import mock

        from ts_cli.domo.client import DomoError, normalise_instance

        def no_dns(*a, **k):
            raise socket.gaierror("offline")

        with mock.patch.object(socket, "getaddrinfo", no_dns):
            with pytest.raises(DomoError):
                normalise_instance(f"https://{shorthand}")

    @pytest.mark.parametrize("host", [
        "localhost", "LOCALHOST", "localhost.", "localhost.localdomain",
        "ip6-localhost", "box.localhost", "svc.local", "api.internal",
        "metadata.google.internal",
    ])
    def test_local_hostname_forms_are_refused_by_name(self, host):
        """Refused without resolving, so an offline machine cannot be tricked either."""
        from ts_cli.domo.client import DomoError, normalise_instance
        with pytest.raises(DomoError):
            normalise_instance(f"https://{host}")

    def test_a_public_name_resolving_to_an_internal_address_is_refused(self):
        """The resolution guard — the headline of round 4, tested by nothing.

        `getaddrinfo` is stubbed rather than relying on the ambient resolver: the real
        one made these tests network-dependent, and in isolated CI the
        `except OSError: return` path meant this classifier never ran at all.
        """
        import socket
        from unittest import mock

        from ts_cli.domo import client as c

        def fake(host, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("93.184.216.34", 443)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

        with mock.patch.object(socket, "getaddrinfo", fake):
            with pytest.raises(c.DomoError):
                c.normalise_instance("https://looks-public.example")

    def test_every_resolved_address_is_classified_not_just_the_first(self):
        """A hostile resolver can put a public address first."""
        import socket
        from unittest import mock

        from ts_cli.domo import client as c

        for internal in ("169.254.169.254", "10.0.0.5", "100.64.0.1"):
            def fake(host, *a, _ip=internal, **k):
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (_ip, 443))]
            with mock.patch.object(socket, "getaddrinfo", fake):
                with pytest.raises(c.DomoError):
                    c.normalise_instance("https://looks-public.example")

    def test_an_unresolvable_host_is_not_fatal(self):
        """The CLI must work offline; resolution is a best-effort guard, not a gate."""
        import socket
        from unittest import mock

        from ts_cli.domo import client as c

        def boom(*a, **k):
            raise socket.gaierror("no DNS")

        with mock.patch.object(socket, "getaddrinfo", boom):
            assert c.normalise_instance("https://acme.domo.com") == \
                "https://acme.domo.com"

    def test_non_ascii_host_is_idna_encoded_before_validation(self):
        """What is validated must be what urllib sends.

        `①②⑦.0.0.1` NFKC/IDNA-expands to `127.0.0.1`, so classifying the raw string
        would check a host nothing ever connects to. (Getting the circled digit wrong
        by one gives `128.0.0.1`, which is public and correctly ACCEPTED — the first
        draft of this test did exactly that and read as a gap in the code.)
        """
        from ts_cli.domo.client import DomoError, normalise_instance
        with pytest.raises(DomoError):
            normalise_instance("https://\u2460\u2461\u2466.0.0.1")

    @pytest.mark.parametrize("instance", [
        "https://acme.domo.com#frag",
        "https://acme.domo.com?q=1",
        "https://acme.domo.com/some/path",
    ])
    def test_fragment_path_and_query_are_refused(self, instance):
        """An EMPTY fragment or query is deliberately allowed — nothing to smuggle."""
        from ts_cli.domo.client import DomoError, normalise_instance
        with pytest.raises(DomoError):
            normalise_instance(instance)

    @pytest.mark.parametrize("host", [
        "100.64.0.1", "100.127.255.254",
    ])
    def test_cgnat_is_refused_independently_of_interpreter_version(self, host):
        """CPython 3.13 dropped 100.64/10 from `_private_networks`.

        The old flag union delegated "internal" to the interpreter, so the same source
        accepted this on 3.13+ and refused it on <=3.12 — both inside
        `requires-python = ">=3.10,<3.15"`. 100.64/10 is the EKS/Fargate and GKE
        pod CIDR. `not is_global` is version-stable.
        """
        import ipaddress

        from ts_cli.domo.client import DomoError, normalise_instance
        assert ipaddress.ip_address(host).is_global is False
        with pytest.raises(DomoError):
            normalise_instance(f"https://{host}")

    def test_tls_verification_is_actually_on(self):
        """Inspect the LIVE SSL context, not the source text.

        The previous version grepped six substrings for a TLS control surface and
        called that a positive property. It is a denylist, and a three-line split
        walks through it while the whole file stays green (PR #440 review, round 5):

            _m = _il.import_module("s" + "sl")
            _U = _m.__dict__["_create" + "_unverified" + "_context"]()
            self._opener = urllib.request.build_opener(_NoRedirect,
                            urllib.request.HTTPSHandler(context=_U))

        That handed a token to a self-signed MITM server with all 33 tests passing.
        A property cannot be evaded by spelling, so this asks the constructed opener
        what its context actually does.
        """
        import ssl
        import urllib.request

        from ts_cli.domo.client import DomoClient

        c = DomoClient("acme.domo.com", "tok")
        https = [h for h in c._opener.handlers
                 if isinstance(h, urllib.request.HTTPSHandler)]
        assert https, "no HTTPSHandler on the opener"
        contexts = [getattr(h, "_context", None) for h in https]
        for ctx in contexts:
            if ctx is None:
                continue  # handler defers to ssl.create_default_context()
            assert ctx.verify_mode == ssl.CERT_REQUIRED, (
                f"TLS verification is off: verify_mode={ctx.verify_mode!r}")
            assert ctx.check_hostname is True, "hostname checking is off"

    def test_redirects_are_refused_by_the_installed_opener(self):
        """The no-redirect handler is present and is the one that runs.

        Asserted on the opener rather than by grepping for `build_opener`, because
        replacing the opener with a plain `build_opener()` was one of the bypasses the
        old text-based check missed.
        """
        import urllib.request

        from ts_cli.domo.client import DomoClient, _NoRedirect

        c = DomoClient("acme.domo.com", "tok")
        assert any(isinstance(h, _NoRedirect) for h in c._opener.handlers), \
            "the redirect-refusing handler is not installed"
        assert not any(
            type(h) is urllib.request.HTTPRedirectHandler
            for h in c._opener.handlers), "the default redirect handler is installed"

    def test_no_environment_variable_can_relax_validation(self):
        """Behavioural, not a grep: set every plausible kill-switch and re-probe.

        The old check scanned source lines for `os.environ`/`getenv`, which
        `from os import environ` defeats — and that missed a working
        `DOMO_ALLOW_INTERNAL=1` switch over the whole host classifier.
        """
        import os
        from unittest import mock

        from ts_cli.domo.client import DomoError, normalise_instance

        names = [
            "DOMO_ALLOW_INTERNAL", "DOMO_ALLOW_HTTP", "DOMO_INSECURE",
            "DOMO_SKIP_VERIFY", "DOMO_ALLOW_PRIVATE", "DOMO_DISABLE_VALIDATION",
            "PYTHONHTTPSVERIFY", "SSLKEYLOGFILE", "DOMO_NO_VERIFY",
        ]
        for name in names:
            with mock.patch.dict(os.environ, {name: "1"}, clear=False):
                for host in ("127.0.0.1", "169.254.169.254", "100.64.0.1"):
                    with pytest.raises(DomoError):
                        normalise_instance(f"https://{host}")
                with pytest.raises(DomoError):
                    normalise_instance("http://acme.domo.com")

    def test_validation_cannot_be_opted_out_of(self):
        """No constructor argument or attribute skips `normalise_instance`.

        `DomoClient(validate=False)` is the literal "security control with an
        override" the old docstring named, and nothing caught it.
        """
        import inspect

        from ts_cli.domo.client import DomoClient, DomoError

        params = inspect.signature(DomoClient.__init__).parameters
        for name in params:
            assert not any(tok in name.lower() for tok in
                           ("validate", "verify", "insecure", "skip", "unsafe")), \
                f"DomoClient.__init__ exposes an opt-out parameter: {name}"
        with pytest.raises(DomoError):
            DomoClient("127.0.0.1", "tok")

    def test_the_cli_layer_adds_no_insecure_flag(self):
        """The old check read only client.py, so `--insecure` on the command was free."""
        import inspect

        from ts_cli.commands import domo as domo_cmd
        src = inspect.getsource(domo_cmd)
        for banned in ("insecure", "no-verify", "skip-verify", "allow-http",
                       "allow_internal"):
            assert banned not in src.lower(), f"CLI exposes a bypass: {banned}"

    def test_exactly_one_request_path(self):
        import inspect

        from ts_cli.domo import client

        src = inspect.getsource(client)
        assert src.count("urlopen(") == 0, "a bare urlopen bypasses the opener"
        assert src.count("self._opener.open(") == 1, "more than one request path"
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
