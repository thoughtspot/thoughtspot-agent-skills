"""ts tableau — Tableau Server/Cloud REST API commands."""
from __future__ import annotations

import json
import os
import random
import re
import time
import zipfile
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

    def download_datasource(self, datasource_id: str, output_dir: Path) -> dict:
        """Download a published datasource's content from Tableau Server/Cloud.

        Downloads the datasource as a TDSX (zip) file, extracts it, and returns
        metadata about the extracted files. Validates CSV files for row integrity.

        Returns a dict with keys: tdsx_path, extracted_dir, files, data_files,
        and validation (per-file row counts + any corrupt lines found).
        """
        if not self._token:
            self.signin()

        output_dir.mkdir(parents=True, exist_ok=True)

        path = f"{self._base_path()}/datasources/{datasource_id}/content"
        # Accept: */* — the content endpoint returns binary (octet-stream);
        # Tableau Cloud returns 406 if Accept is application/json or application/octet-stream.
        resp = self.request("GET", path, headers={"Accept": "*/*"}, timeout=120)

        content_disp = resp.headers.get("Content-Disposition", "")
        if "filename=" in content_disp:
            fname = content_disp.split("filename=")[-1].strip(' "\'')
        else:
            fname = f"{datasource_id}.tdsx"
        tdsx_path = output_dir / fname

        tdsx_path.write_bytes(resp.content)
        typer.echo(f"Downloaded {len(resp.content)} bytes → {tdsx_path}", err=True)

        extracted_dir = output_dir / tdsx_path.stem
        data_files: list[dict] = []
        all_files: list[str] = []

        if zipfile.is_zipfile(tdsx_path):
            extracted_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(tdsx_path, "r") as zf:
                zf.extractall(extracted_dir)
                all_files = zf.namelist()

            for file_name in all_files:
                file_path = extracted_dir / file_name
                if not file_path.is_file():
                    continue
                ext = file_path.suffix.lower()
                if ext in (".csv", ".tsv", ".txt"):
                    validation = self._validate_csv(file_path)
                    data_files.append({
                        "name": file_name,
                        "path": str(file_path),
                        "type": "csv",
                        "validation": validation,
                    })
                elif ext == ".hyper":
                    data_files.append({
                        "name": file_name,
                        "path": str(file_path),
                        "type": "hyper",
                    })
        else:
            all_files = [fname]
            ext = tdsx_path.suffix.lower()
            if ext in (".csv", ".tsv", ".txt"):
                validation = self._validate_csv(tdsx_path)
                data_files.append({
                    "name": fname,
                    "path": str(tdsx_path),
                    "type": "csv",
                    "validation": validation,
                })

        return {
            "tdsx_path": str(tdsx_path),
            "extracted_dir": str(extracted_dir),
            "files": all_files,
            "data_files": data_files,
        }

    @staticmethod
    def _validate_csv(file_path: Path) -> dict:
        """Check a CSV file for row integrity — column count consistency and corrupt lines.

        Uses Python's csv module to handle quoted fields correctly (e.g.
        "First Aid Kit, Office Size" is one field, not two).
        """
        import csv as csv_mod

        corrupt_lines: list[dict] = []
        total_lines = 0
        header_col_count = 0
        raw_lines: list[str] = []

        with open(file_path, "r", errors="replace") as f:
            raw_lines = f.readlines()
            total_lines = len(raw_lines)

        if total_lines == 0:
            return {
                "total_lines": 0,
                "data_rows": 0,
                "header_columns": 0,
                "corrupt_lines": [],
                "is_valid": True,
            }

        with open(file_path, "r", errors="replace") as f:
            reader = csv_mod.reader(f)
            for row_num, row in enumerate(reader, 1):
                if row_num == 1:
                    header_col_count = len(row)
                    continue
                if len(row) != header_col_count:
                    raw_content = raw_lines[row_num - 1].strip() if row_num <= len(raw_lines) else ""
                    corrupt_lines.append({
                        "line": row_num,
                        "expected_columns": header_col_count,
                        "actual_columns": len(row),
                        "content": raw_content[:120],
                    })

        return {
            "total_lines": total_lines,
            "data_rows": total_lines - 1,
            "header_columns": header_col_count,
            "corrupt_lines": corrupt_lines,
            "is_valid": len(corrupt_lines) == 0,
        }

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


@app.command()
def download(
    datasource_id: str = typer.Argument(..., help="Datasource UUID"),
    profile: Optional[str] = _profile_option,
    output_dir: str = typer.Option(".", "--output-dir", "-o",
                                    help="Directory to save downloaded content"),
) -> None:
    """Download a published datasource's content (TDSX) and extract data files.

    Downloads the datasource, extracts the TDSX archive, and validates any CSV
    files for row integrity (column count consistency, corrupt lines).
    """
    p = _resolve_tableau_profile(profile)
    client = TableauClient(p)
    result = client.download_datasource(datasource_id, Path(output_dir))
    print(json.dumps(result, indent=2))


@app.command("translate-formulas")
def translate_formulas_cmd(
    input_file: str = typer.Option(..., "--input", "-i",
                                    help="classification.json from TWB parse"),
    output_file: str = typer.Option(..., "--output", "-o",
                                     help="Output translated formulas JSON"),
    tables: Optional[str] = typer.Option(None, "--tables", "-t",
                                          help="Comma-separated table names for this model"),
    table_columns: Optional[str] = typer.Option(None, "--table-columns",
                                                 help="JSON file mapping column→table"),
    parameters_file: Optional[str] = typer.Option(None, "--parameters",
                                                   help="JSON file with parameter definitions"),
    param_map_file: Optional[str] = typer.Option(None, "--param-map",
                                                  help="JSON file mapping internal param names→captions"),
    calc_map_file: Optional[str] = typer.Option(None, "--calc-map",
                                                 help="JSON file mapping [Calculation_NNN]→caption"),
    datasource: Optional[str] = typer.Option(None, "--datasource", "-d",
                                              help="Filter to a single datasource name"),
    csq_map_file: Optional[str] = typer.Option(None, "--csq-map",
                                                help="JSON file mapping Custom SQL Query aliases→table names"),
    date_columns_opt: Optional[str] = typer.Option(None, "--date-columns",
                                                    help="Comma-separated date column names for arithmetic rewrite"),
) -> None:
    """Translate Tableau calculated fields to ThoughtSpot formula syntax.

    Reads classification.json (from the TWB parse), applies the ordered translation
    pipeline, resolves cross-references via dependency DAG, and outputs a JSON file
    with translated formulas ready for TML generation.
    """
    from ts_cli.tableau_translate import translate_formulas

    input_path = Path(input_file)
    if not input_path.exists():
        typer.echo(f"Input file not found: {input_file}", err=True)
        raise SystemExit(1)

    classification = json.loads(input_path.read_text())

    # Filter to datasource if specified
    if datasource:
        classification = [f for f in classification if f.get("datasource") == datasource]
        typer.echo(f"Filtered to datasource '{datasource}': {len(classification)} formulas", err=True)

    # Load scoped columns map
    scoped_columns: dict[str, str] = {}
    if table_columns:
        tc_path = Path(table_columns)
        if tc_path.exists():
            scoped_columns = json.loads(tc_path.read_text())
    elif tables:
        typer.echo("Warning: --tables without --table-columns; column scoping disabled", err=True)

    # Load parameters
    parameters: list[dict] = []
    if parameters_file:
        p_path = Path(parameters_file)
        if p_path.exists():
            parameters = json.loads(p_path.read_text())

    # Load param name map (internal name → caption)
    param_map: dict[str, str] = {}
    if param_map_file:
        pm_path = Path(param_map_file)
        if pm_path.exists():
            param_map = json.loads(pm_path.read_text())

    # Load calc ID map ([Calculation_NNN] → caption)
    calc_id_map: dict[str, str] | None = None
    if calc_map_file:
        cm_path = Path(calc_map_file)
        if cm_path.exists():
            calc_id_map = json.loads(cm_path.read_text())

    # Load Custom SQL Query alias map
    csq_to_table: dict[str, str] | None = None
    if csq_map_file:
        csq_path = Path(csq_map_file)
        if csq_path.exists():
            csq_to_table = json.loads(csq_path.read_text())

    # Parse date columns
    date_columns: set[str] | None = None
    if date_columns_opt:
        date_columns = {c.strip() for c in date_columns_opt.split(",") if c.strip()}

    result = translate_formulas(
        formulas=classification,
        scoped_columns=scoped_columns,
        param_map=param_map,
        parameters=parameters,
        calc_id_map=calc_id_map,
        csq_to_table=csq_to_table,
        date_columns=date_columns,
    )

    output_path = Path(output_file)
    output_path.write_text(json.dumps(result, indent=2))

    typer.echo(
        f"Translated: {result['stats']['translated']}/{result['stats']['total']} formulas\n"
        f"Skipped: {result['stats']['skipped']} "
        f"(levels: {json.dumps(result['stats']['levels'])})",
        err=True,
    )

    print(json.dumps(result["stats"]))
