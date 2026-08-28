"""Domo internal-API client for capturing a bundle.

Authenticates to a Domo instance with a Developer Access Token (`X-DOMO-Developer-
Token`) and reads the objects the public Developer API does NOT expose — card
metadata and Beast Modes — alongside datasets and pages.

IMPORTANT: these are Domo's **internal, undocumented** endpoints (the ones the Domo
web app itself calls). They work today but are unsupported and may change; every
response is treated as best-effort and what cannot be read is flagged.

Credential handling — the rules this module has to hold, and why
---------------------------------------------------------------
The token is a bearer credential in a *custom* header, which changes what the stdlib
does for you. All four of these were live defects found in review:

- **HTTPS is mandatory.** `if not inst.startswith("http")` accepted `http://` (it
  starts with "http"), so the token went out in cleartext. The scheme is now
  allowlisted, not sniffed.
- **Redirects are not followed.** urllib's default redirect handler rebuilds every
  header except `content-length`/`content-type` onto the new request, and whatever
  stripping it does for `Authorization` does not apply to `X-DOMO-Developer-Token`.
  A 302 to another origin therefore handed the token to that origin. Verified
  against two local servers; now refused.
- **The host is validated, syntactically and by resolution.** `https://acme.domo.com@example.com`
  connects to example.com while every UI string shows acme.domo.com; a bare
  `169.254.169.254` reaches cloud metadata; `https://evil.com/?x=` turns each path
  into a query parameter. Userinfo, query, fragment and path are rejected.

  An earlier version classified only *canonical* IP literals, which closed four
  spellings of one address rather than the class — `localhost`, `2130706433`,
  `127.1`, `0177.1` and `0x7f.1` all reached loopback. And Python's IDNA codec treats
  U+3002 / U+FF0E / U+FF61 as label separators, so `acme.domo.com。evil.example`
  connected to `acme.domo.com.evil.example` while every UI string rendered the
  original — precisely what the userinfo check exists to prevent.

  Now: non-ASCII hosts are IDNA-encoded and alternative label separators refused;
  numeric IPv4 shorthands are canonicalised via `inet_aton` before classification;
  loopback hostname forms are refused by name; and the host is resolved and every
  returned address classified.

  **Limitation, stated plainly because a guardrail nobody can audit is worse than
  none:** resolution is a check at validation time, not a guarantee. DNS can change
  between this check and the request (rebinding), and a resolution failure is not
  treated as fatal so the CLI still works offline. This is defence in depth, not a
  proof.
- **Server text never reaches the terminal.** The response body was interpolated
  into the exception, which `ts domo signin` prints — so a host the operator was
  tricked into naming could echo the token back into their transcript. Only the
  status code and reason are surfaced now.

The token is resolved lazily (see `_resolve_token`) and is never held in a frame that
can raise before it is used, so it cannot be rendered into a traceback.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

# A Domo tenant is always reached over TLS. Anything else is refused rather than
# downgraded, because the credential travels in a header on every request.
_ALLOWED_SCHEMES = ("https",)

# Unicode characters Python's IDNA codec treats as label separators. A host carrying
# one connects somewhere other than what the UI renders.
_IDNA_SEPARATORS = ("\u3002", "\uff0e", "\uff61")

# Hostname forms that mean "this machine" without being IP literals.
_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain")


class DomoError(RuntimeError):
    pass


_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _safe(text: str, limit: int = 80) -> str:
    """Strip control bytes from server-controlled text before it can be printed.

    The HTTP reason phrase comes from the server. Raw ANSI/BEL/backspace bytes in an
    exception that reaches a terminal are a transcript-forgery primitive — a host can
    redraw what the operator appears to have seen. What saved this before was
    incidental (`json.dumps` at one call site escapes C0); eight sibling call sites
    use `typer.echo(str(e))` and would not have.
    """
    return _CONTROL.sub("", str(text or ""))[:limit]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect.

    The custom auth header would be replayed onto the redirect target, which the
    server chooses. There is no legitimate cross-origin redirect on these endpoints,
    so a redirect is an error rather than something to follow carefully.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise DomoError(
            f"refusing to follow an HTTP {code} redirect to {newurl!r}: the Domo "
            "developer token would be replayed onto that host. Check the instance URL.")


def _is_internal(ip) -> bool:
    return bool(ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified)


def _as_ip(host: str):
    """Parse `host` as an IP, accepting the shorthand forms `ip_address` rejects.

    `2130706433`, `127.1`, `0177.1` and `0x7f.1` are all loopback to the resolver but
    are not canonical literals, so classifying only canonical forms closed four
    spellings of one address instead of the class.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.inet_ntoa(socket.inet_aton(host)))
    except (OSError, ValueError):
        return None


def _reject_separators(raw: str) -> None:
    """Alternative IDNA label separators change which host is contacted.

    Same threat as a userinfo '@': every UI string keeps rendering the original.
    """
    for sep in _IDNA_SEPARATORS:
        if sep in raw:
            raise DomoError(
                f"Domo instance contains the Unicode label separator {sep!r} "
                f"(U+{ord(sep):04X}), which Python's IDNA codec treats as a dot — "
                f"{raw!r} would connect to a different host than it appears to name.")


def _reject_url_shape(raw: str, parts) -> None:
    """Refuse anything that is not a bare origin."""
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise DomoError(
            f"Domo instance must use https:// (got {parts.scheme!r}). The developer "
            "token is sent as a request header, so plain HTTP would expose it.")
    if "@" in parts.netloc:
        raise DomoError(
            "Domo instance must not contain credentials or a userinfo '@' section — "
            f"{raw!r} would connect to {parts.hostname!r}, not to the host shown "
            "before the '@'.")
    if parts.query or parts.fragment:
        raise DomoError(
            "Domo instance must be a bare host, with no query string or fragment "
            f"(got {raw!r}) — otherwise every API path becomes a query parameter.")
    if (parts.path or "").strip("/"):
        raise DomoError(
            f"Domo instance must be a bare host, with no path (got {raw!r}).")
    if not parts.hostname:
        raise DomoError(f"Domo instance has no host: {raw!r}")


def _ascii_host(hostname: str) -> str:
    """IDNA-encode so what is validated is what urllib will send."""
    if hostname.isascii():
        return hostname
    try:
        return hostname.encode("idna").decode("ascii")
    except UnicodeError as e:
        raise DomoError(
            f"Domo instance host {hostname!r} is not a valid IDNA name: {e}") from None


def normalise_instance(instance: str) -> str:
    """Validate a Domo instance URL and return its bare origin.

    Raises DomoError with the reason, rather than silently accepting something that
    sends the token somewhere unintended.
    """
    raw = (instance or "").strip()
    if not raw:
        raise DomoError("Domo instance is empty")
    if "://" not in raw:
        raw = "https://" + raw

    _reject_separators(raw)
    parts = urllib.parse.urlsplit(raw)
    _reject_url_shape(raw, parts)

    host = _ascii_host(parts.hostname)
    _reject_internal_host(host)
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


def _reject_internal_host(host: str) -> None:
    """Refuse hosts that are not a public tenant, syntactically and by resolution.

    A Domo tenant is SaaS and never loopback/link-local/private; `169.254.169.254` is
    the cloud metadata service and the rest are the usual SSRF pivots. There is
    deliberately no override flag.

    See the module docstring for the limitation: resolution here is defence in depth,
    not a proof, because DNS can change between this check and the request.
    """
    low = host.strip().lower().rstrip(".")

    ip = _as_ip(low)
    if ip is not None:
        if _is_internal(ip):
            raise DomoError(
                f"Domo instance must be a public tenant host (got {host!r}, which "
                f"resolves to the {ip} loopback/link-local/private address). A Domo "
                "tenant looks like https://<tenant>.domo.com.")
        return

    if low in _LOCAL_NAMES or low.endswith(_LOCAL_SUFFIXES):
        raise DomoError(
            f"Domo instance must be a public tenant host (got {host!r}, which names "
            "the local machine or a private zone).")

    # Resolve and classify every address behind the name.
    try:
        infos = socket.getaddrinfo(low, None)
    except OSError:
        return          # offline / unresolvable — not treated as fatal, see docstring
    for info in infos:
        addr = info[4][0]
        try:
            resolved = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_internal(resolved):
            raise DomoError(
                f"Domo instance {host!r} resolves to {resolved}, which is a "
                "loopback/link-local/private address. Refusing to send the developer "
                "token there.")


class DomoClient:
    def __init__(self, instance: str, token: Optional[str] = None,
                 timeout: int = 30, *,
                 token_provider: Optional[Callable[[], str]] = None) -> None:
        """`instance` is validated up front; the token is resolved lazily.

        Pass `token_provider` to defer resolution entirely (the profile path does),
        so the raw secret is never a local in a frame that could raise.
        """
        self.base = normalise_instance(instance)
        self._token = token
        self._token_provider = token_provider
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    # -- low-level ---------------------------------------------------------
    def _headers(self) -> dict:
        token = self._token if self._token is not None else (
            self._token_provider() if self._token_provider else "")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-DOMO-Developer-Token": token,
        }

    def _url(self, path: str) -> str:
        """Join `path` onto the validated origin without letting it change host."""
        if not path.startswith("/"):
            path = "/" + path
        return self.base + path

    def _request(self, path: str, method: str = "GET",
                 body: Optional[Any] = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self._url(path), data=data, headers=self._headers(), method=method)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                # errors="replace": a non-UTF-8 body raised an uncaught
                # UnicodeDecodeError that replaced the reachability report with a
                # traceback.
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            # Status + reason only. The response BODY is attacker-controlled and
            # `ts domo signin` prints DomoError text to the operator's terminal.
            raise DomoError(
                f"{method} {path} -> HTTP {e.code} "
                f"{_safe(getattr(e, 'reason', ''))}".rstrip()) from None
        except DomoError:
            raise
        except urllib.error.URLError as e:
            raise DomoError(f"{method} {path} -> {type(e).__name__}") from None
        except (UnicodeDecodeError, UnicodeError):
            raise DomoError(f"{method} {path} -> response was not decodable") from None
        except json.JSONDecodeError:
            raise DomoError(f"{method} {path} -> response was not JSON") from None

    def _get(self, path: str) -> Any:
        return self._request(path, "GET")

    def _post(self, path: str, body: Any) -> Any:
        return self._request(path, "POST", body)

    # -- datasets ----------------------------------------------------------
    def list_datasets(self, limit: int = 200) -> list[dict]:
        d = self._get(f"/api/data/v3/datasources?limit={limit}")
        return (d or {}).get("dataSources", []) if isinstance(d, dict) else (d or [])

    def get_dataset_schema(self, dataset_id: str) -> dict:
        """Return {id, name, rows, columns:[{name,type}]} for a dataset.

        Tries the schema endpoint, then falls back to the datasource detail.
        Column type keys vary (type / dataType), normalised by the parser.
        """
        for path in (
            f"/api/data/v3/datasources/{dataset_id}/schemas/latest",
            f"/api/data/v3/datasources/{dataset_id}",
        ):
            try:
                return self._get(path)
            except DomoError:
                continue
        raise DomoError(f"no schema for dataset {dataset_id}")

    # -- pages / cards -----------------------------------------------------
    def list_pages(self, limit: int = 100) -> list[dict]:
        d = self._get(f"/api/content/v1/pages?limit={limit}")
        return d if isinstance(d, list) else (d or {}).get("pages", [])

    def get_page_stack(self, page_id: str) -> dict:
        """Page with its cards + collections (tabs) + title."""
        return self._get(f"/api/content/v3/stacks/{page_id}/cards?parts=metadata")

    def get_page_card_refs(self, page_id: str) -> list[dict]:
        """Lightweight list of a page's card refs (urn/id/type)."""
        d = self._get(f"/api/content/v1/pages/{page_id}/cards")
        return d if isinstance(d, list) else (d or {}).get("cards", [])

    def get_card_definitions(self, urns: list[str],
                             parts: str = "metadata,datasources,slicers,dateGrain") -> list[dict]:
        if not urns:
            return []
        d = self._get(f"/api/content/v1/cards?urns={','.join(urns)}&parts={parts}")
        return (d or {}).get("cards", []) if isinstance(d, dict) else (d or [])

    # -- beast modes -------------------------------------------------------
    def search_beast_modes(self, dataset_id: Optional[str] = None,
                           limit: int = 200) -> list[dict]:
        body: dict = {"limit": limit, "offset": 0}
        if dataset_id:
            body["dataSourceId"] = dataset_id
        try:
            d = self._post("/api/query/v1/functions/search", body)
        except DomoError:
            return []
        return (d or {}).get("results", []) if isinstance(d, dict) else []


# ---------------------------------------------------------------------------
# Profile resolution — mirrors ts_cli/tableau/client.py
# ---------------------------------------------------------------------------

def load_domo_profiles() -> list[dict]:
    """Load Domo profiles from ~/.claude/domo-profiles.json.

    Delegates to profile_ops.load_platform_profiles.
    """
    from ts_cli.profile_ops import load_platform_profiles
    return load_platform_profiles("domo")


def _resolve_domo_profile(profile_name: Optional[str]) -> dict:
    """Return a single profile dict by name, or the only profile if name is None."""
    from ts_cli.profile_ops import PROFILE_PATHS
    profiles = load_domo_profiles()
    if not profiles:
        raise SystemExit(
            f"No Domo profiles found in {PROFILE_PATHS['domo']}.\n"
            "Run /ts-profile-domo to add a profile."
        )
    if profile_name:
        for p in profiles:
            if p.get("name") == profile_name:
                return p
        raise SystemExit(
            f"Domo profile {profile_name!r} not found. "
            f"Known: {[p.get('name') for p in profiles]}"
        )
    if len(profiles) > 1:
        raise SystemExit(
            "Multiple Domo profiles configured — pass --profile. "
            f"Known: {[p.get('name') for p in profiles]}"
        )
    return profiles[0]


def _resolve_token(profile: dict) -> str:
    """Read the developer token — env var first, OS credential store fallback.

    The token is never written to disk or logged; it is held in memory only.
    """
    from ts_cli.profile_ops import derive_keychain_service, slugify

    env_var = profile.get("token_env", "")
    if env_var:
        val = os.environ.get(env_var, "")
        if val:
            return val

    service = derive_keychain_service("domo", slugify(profile["name"]))
    try:
        import keyring  # deferred import — graceful if not installed
        stored = keyring.get_password(service, "developer-token")
        if stored:
            return stored
    except Exception:  # noqa: BLE001 — keyring is optional and may fail on any backend
        pass

    raise SystemExit(
        f"No credential found for Domo profile {profile['name']!r}.\n"
        "Run /ts-profile-domo to configure credentials."
    )


def _credential_present(profile: dict) -> bool:
    """Is a token obtainable for this profile? Returns a bool, never the value.

    Lets `client_from_profile` fail fast on a missing credential without binding the
    secret to a name, so the lazy-resolution guarantee still holds.
    """
    env_var = profile.get("token_env", "")
    if env_var and os.environ.get(env_var):
        return True
    from ts_cli.profile_ops import derive_keychain_service, slugify
    service = derive_keychain_service("domo", slugify(profile["name"]))
    try:
        import keyring
        return keyring.get_password(service, "developer-token") is not None
    except Exception:  # noqa: BLE001 — keyring is optional and may fail on any backend
        return False


def client_from_profile(profile_name: Optional[str] = None,
                        timeout: int = 30) -> DomoClient:
    """Build a DomoClient from a configured profile (see /ts-profile-domo)."""
    profile = _resolve_domo_profile(profile_name)
    instance = profile.get("instance") or profile.get("instance_url") or ""
    if not instance:
        raise SystemExit(
            f"Domo profile {profile['name']!r} has no 'instance' field.\n"
            "Re-add it with: ts profiles add --platform domo --field instance=https://<tenant>.domo.com ..."
        )
    # Fail fast on a missing credential, but WITHOUT binding it: _credential_present
    # returns a bool. Resolution itself stays deferred, because passing the secret
    # positionally would make it a local in a frame that raises if `instance` is bad,
    # and typer<1 permits versions whose traceback panels render locals.
    if not _credential_present(profile):
        raise SystemExit(
            f"No credential found for Domo profile {profile['name']!r}.\n"
            "Run /ts-profile-domo to configure credentials.")
    return DomoClient(instance, token_provider=lambda: _resolve_token(profile),
                      timeout=timeout)
