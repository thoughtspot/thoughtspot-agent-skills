"""ts tableau — Tableau Server/Cloud REST API commands."""
from __future__ import annotations

import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests
import typer

TABLEAU_PROFILES_PATH = Path.home() / ".claude" / "tableau-profiles.json"


def _slugify_tableau(name: str) -> str:
    """Derive a URL-safe slug from a Tableau profile name.

    Lowercases, collapses non-alphanumeric runs to a single hyphen, strips
    leading/trailing hyphens. Matches the slug derivation pattern used for
    ThoughtSpot profiles.
    """
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def load_tableau_profiles() -> list:
    """Load Tableau profiles from ~/.claude/tableau-profiles.json.

    Returns a list of profile dicts, or an empty list if the file does not exist.
    """
    if not TABLEAU_PROFILES_PATH.exists():
        return []
    raw = json.loads(TABLEAU_PROFILES_PATH.read_text())
    if isinstance(raw, list):
        return raw
    return []


def _resolve_tableau_profile(profile_name: Optional[str]) -> dict:
    """Return a single profile dict by name, or the first profile if name is None."""
    profiles = load_tableau_profiles()
    if not profiles:
        raise SystemExit(
            f"No Tableau profiles found in {TABLEAU_PROFILES_PATH}.\n"
            "Run /ts-profile-tableau to add a profile."
        )
    if profile_name:
        for p in profiles:
            if p["name"] == profile_name:
                return p
        available = ", ".join(p["name"] for p in profiles)
        raise SystemExit(
            f"Tableau profile '{profile_name}' not found.\n"
            f"Available profiles: {available}"
        )
    return profiles[0]


_RETRYABLE_STATUSES = {429, 408, 502, 503, 504}


class TableauClient:
    """Authenticated HTTP client for the Tableau Server/Cloud REST API.

    Auth flow:
      1. Read the credential from the env var named in the profile, or fall back
         to the OS credential store via keyring (macOS Keychain, Windows Credential
         Manager, Linux Secret Service).
      2. POST to /api/{version}/auth/signin with either password or PAT credentials.
      3. Store the returned X-Tableau-Auth token for subsequent requests.
      4. On 401, re-authenticate once automatically (session expiry).
      5. On retryable status codes (429, 408, 502, 503, 504), exponential-backoff
         retry up to max_retries times.

    Supports two auth methods controlled by profile["auth"]:
      "password" — username + password credential
      "pat"      — Personal Access Token (pat_name + pat_secret)
    """

    def __init__(self, profile: dict):
        self.server_url = profile["server_url"].rstrip("/")
        self.site_content_url = profile.get("site_content_url", "")
        self.api_version = profile.get("api_version", "3.22")
        self._profile = profile
        self._slug = _slugify_tableau(profile["name"])
        self._token: Optional[str] = None
        self._site_id: Optional[str] = None

    def _get_credential(self) -> str:
        """Read a credential — env var first, OS credential store fallback."""
        profile = self._profile
        auth = profile.get("auth", "password")
        if auth == "pat":
            env_var = profile.get("pat_secret_env", "")
        else:
            env_var = profile.get("password_env", "")

        if env_var:
            val = os.environ.get(env_var, "")
            if val:
                return val

        # OS credential store fallback
        service = f"tableau-{self._slug}"
        if auth == "pat":
            account = profile.get("pat_name", "")
        else:
            account = profile.get("username", "")

        try:
            import keyring  # deferred import — graceful if not installed
            stored = keyring.get_password(service, account)
            if stored:
                return stored
        except Exception:
            pass

        raise SystemExit(
            f"No credential found for Tableau profile '{self._profile['name']}'.\n"
            "Run /ts-profile-tableau to configure credentials."
        )

    def signin(self) -> dict:
        """Sign in to Tableau Server/Cloud. Stores token and site_id internally.

        Returns a dict with site_id, api_version, and user_id.
        """
        from xml.sax.saxutils import quoteattr

        profile = self._profile
        auth = profile.get("auth", "password")
        credential = self._get_credential()

        if auth == "pat":
            pat_name = profile.get("pat_name", "")
            body = (
                f'<tsRequest>'
                f'<credentials personalAccessTokenName={quoteattr(pat_name)} '
                f'personalAccessTokenSecret={quoteattr(credential)}>'
                f'<site contentUrl={quoteattr(self.site_content_url)}/>'
                f'</credentials>'
                f'</tsRequest>'
            )
        else:
            username = profile.get("username", "")
            body = (
                f'<tsRequest>'
                f'<credentials name={quoteattr(username)} password={quoteattr(credential)}>'
                f'<site contentUrl={quoteattr(self.site_content_url)}/>'
                f'</credentials>'
                f'</tsRequest>'
            )

        url = f"{self.server_url}/api/{self.api_version}/auth/signin"
        resp = requests.post(
            url,
            data=body,
            headers={"Content-Type": "application/xml", "Accept": "application/json"},
            timeout=30,
        )

        if resp.status_code in (401, 403):
            raise SystemExit(
                f"Tableau authentication failed ({resp.status_code}).\n"
                "Check your credentials. Run /ts-profile-tableau to update."
            )
        resp.raise_for_status()

        data = resp.json()
        creds = data["credentials"]
        self._token = creds["token"]
        self._site_id = creds["site"]["id"]
        return {
            "site_id": self._site_id,
            "api_version": self.api_version,
            "user_id": creds.get("user", {}).get("id", ""),
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        max_retries: int = 4,
        **kwargs: Any,
    ) -> requests.Response:
        """Make an authenticated request. Handles 401 re-auth and retryable errors.

        JSON to stdout, diagnostics to stderr — consistent with ts-cli conventions.
        """
        if not self._token:
            self.signin()

        headers = kwargs.pop("headers", {})
        headers["X-Tableau-Auth"] = self._token
        headers.setdefault("Accept", "application/json")

        url = f"{self.server_url}{path}"
        timeout = kwargs.pop("timeout", 60)
        refreshed = False

        for attempt in range(1, max_retries + 1):
            resp = requests.request(
                method, url, headers=headers, timeout=timeout, **kwargs
            )

            if resp.status_code == 401 and not refreshed:
                typer.echo("Session expired, re-authenticating...", err=True)
                self.signin()
                headers["X-Tableau-Auth"] = self._token
                refreshed = True
                continue

            if resp.status_code in _RETRYABLE_STATUSES and attempt < max_retries:
                delay = 1.5 * (2 ** (attempt - 1)) + random.random() * 0.5
                typer.echo(
                    f"Retryable {resp.status_code}, attempt {attempt}/{max_retries}, "
                    f"waiting {delay:.1f}s...",
                    err=True,
                )
                time.sleep(delay)
                continue

            if not resp.ok:
                detail = ""
                try:
                    err = resp.json()
                    detail = str(
                        err.get("error", {}).get("summary", "")
                        or err.get("error", {}).get("detail", "")
                        or resp.text[:200]
                    )
                except Exception:
                    detail = resp.text[:200]
                typer.echo(
                    f"Tableau API {resp.status_code} on {method} {path} — {detail}",
                    err=True,
                )
                raise SystemExit(1)

            return resp

        typer.echo(f"Max retries exceeded for {method} {path}", err=True)
        raise SystemExit(1)

    def _base_path(self) -> str:
        return f"/api/{self.api_version}/sites/{self._site_id}"

    def datasources(self, name_filter: Optional[str] = None) -> list:
        """List all published datasources on the site, auto-paginating.

        When name_filter is given, uses the Tableau REST API filter parameter
        (exact match) instead of paging through all results.
        """
        if not self._token:
            self.signin()
        all_ds: list = []
        page = 1
        while True:
            if name_filter:
                path = (
                    f"{self._base_path()}/datasources"
                    f"?filter=name:eq:{quote(name_filter, safe='')}"
                )
            else:
                path = f"{self._base_path()}/datasources?pageSize=100&pageNumber={page}"

            resp = self.request("GET", path)
            data = resp.json()
            ds_list = data.get("datasources", {}).get("datasource", [])
            # Tableau returns a dict (not list) when there is exactly one result
            if not isinstance(ds_list, list):
                ds_list = [ds_list] if ds_list else []
            all_ds.extend(ds_list)

            if name_filter:
                break

            pagination = data.get("pagination", {})
            total = int(pagination.get("totalAvailable", 0))
            if len(all_ds) >= total:
                break
            page += 1

        return all_ds

    def datasource_fields(self, datasource_id: str) -> list:
        """Fetch field metadata for a datasource via the VizQL Data Service.

        Uses POST /api/v1/vizql-data-service/read-metadata (not versioned by
        the same api_version path as the REST API). Returns the list of field
        objects from the response.
        """
        if not self._token:
            self.signin()
        resp = self.request(
            "POST",
            "/api/v1/vizql-data-service/read-metadata",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json={"datasource": {"datasourceLuid": datasource_id}},
        )
        data = resp.json()
        return data.get("data", data) if isinstance(data, dict) else data


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------

app = typer.Typer(help="Tableau Server/Cloud REST API commands.")

_profile_option = typer.Option(
    None, "--profile", "-p",
    help="Tableau profile name (default: first profile in ~/.claude/tableau-profiles.json)",
)


@app.command()
def signin(
    profile: Optional[str] = _profile_option,
) -> None:
    """Sign in to Tableau Server/Cloud and verify credentials."""
    p = _resolve_tableau_profile(profile)
    client = TableauClient(p)
    result = client.signin()
    print(json.dumps(result))


@app.command()
def datasources(
    profile: Optional[str] = _profile_option,
    name: Optional[str] = typer.Option(None, "--name", "-n",
                                        help="Exact datasource name filter"),
) -> None:
    """List published datasources on the Tableau site."""
    p = _resolve_tableau_profile(profile)
    client = TableauClient(p)
    result = client.datasources(name_filter=name)
    print(json.dumps(result))


@app.command()
def datasource(
    datasource_id: str = typer.Argument(..., help="Datasource UUID"),
    profile: Optional[str] = _profile_option,
    fields: bool = typer.Option(False, "--fields", "-f",
                                 help="Include field metadata via VizQL read-metadata"),
) -> None:
    """Get datasource details, optionally with field metadata."""
    p = _resolve_tableau_profile(profile)
    client = TableauClient(p)
    client.signin()

    path = f"{client._base_path()}/datasources/{datasource_id}"
    resp = client.request("GET", path)
    ds_info = resp.json()

    if fields:
        field_list = client.datasource_fields(datasource_id)
        ds_info["fields"] = field_list

    print(json.dumps(ds_info))
