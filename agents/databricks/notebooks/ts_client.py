"""
ts_client.py — ThoughtSpotClient for Databricks notebooks.

Consumed via ``%run ./ts_client`` in Databricks notebooks, or imported
directly in tests (add ``agents/databricks/notebooks/`` to sys.path first).

Design principles
-----------------
- **Single file** — no package install needed; %run resolves it at notebook time.
- **Databricks Secrets for credentials** — one scope per ThoughtSpot profile
  (scope name: ``thoughtspot-{profile}``).
- **In-memory token caching** — no filesystem; tokens live in the notebook session.
- **No dependency on ts CLI, keyring, or OS keychain.**
- **Three auth methods**: bearer_token (direct), password (exchange), secret_key (exchange).
- **401 retry**: on the first 401 the stale token is cleared and a fresh one obtained;
  if the retry also fails, ThoughtSpotAPIError is raised.
"""

from __future__ import annotations

import builtins
import json
import re
import time
from typing import Optional

import requests
import yaml

# ---------------------------------------------------------------------------
# Module-level helpers (used by TML methods added in later tasks)
# ---------------------------------------------------------------------------

_NONPRINTABLE_RE: re.Pattern = re.compile(
    r"[^\x09\x0a\x0d\x20-\x7e\x80-\xff]"
)

_TML_TYPE_KEYS: frozenset = frozenset(
    {
        "table",
        "view",
        "sql_view",
        "worksheet",
        "answer",
        "liveboard",
        "model",
        "connection",
    }
)


def _strip_nonprintable(text: str) -> str:
    """Remove non-printable characters from *text*."""
    return _NONPRINTABLE_RE.sub("", text)


def _detect_tml_type(parsed: dict) -> Optional[str]:
    """Return the TML object type from the top-level key of a parsed TML dict."""
    for key in _TML_TYPE_KEYS:
        if key in parsed:
            return key
    return None


def _parse_edoc(edoc: str, fmt: str = "YAML") -> dict:
    """Parse a TML edoc string in YAML or JSON format.

    Parameters
    ----------
    edoc:
        Raw TML string (YAML or JSON).
    fmt:
        ``"YAML"`` (default) or ``"JSON"``.

    Returns
    -------
    dict
        Parsed TML as a Python dict.
    """
    cleaned = _strip_nonprintable(edoc)
    if fmt.upper() == "JSON":
        return json.loads(cleaned)
    return yaml.safe_load(cleaned)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

_CONFIGURATION_RE: re.Pattern = re.compile(
    r'"configuration"\s*:\s*\{[^}]*\}'
)


class ThoughtSpotAPIError(Exception):
    """Raised when a ThoughtSpot REST API call returns a non-2xx status.

    Attributes
    ----------
    status_code : int
        HTTP status code returned by the API.
    endpoint : str
        The URL path that was called, for context in error messages.
    """

    def __init__(self, status_code: int, message: str, endpoint: str) -> None:
        self.status_code = status_code
        self.endpoint = endpoint
        # Scrub any connection credential details from the message body.
        scrubbed = _CONFIGURATION_RE.sub('"configuration": "[REDACTED]"', message)
        super().__init__(f"[{status_code}] {endpoint}: {scrubbed}")


# ---------------------------------------------------------------------------
# ThoughtSpotClient
# ---------------------------------------------------------------------------

# Number of seconds before expiry at which we proactively refresh the token.
_REFRESH_BUFFER_SECS: int = 60


class ThoughtSpotClient:
    """ThoughtSpot REST API client designed for Databricks notebooks.

    Credentials are read from Databricks Secrets under the scope
    ``thoughtspot-{profile}``.  The following keys are expected:

    ===============  ==========================================================
    Key              Value
    ===============  ==========================================================
    ``base_url``     Root URL of the ThoughtSpot instance, e.g.
                     ``https://company.thoughtspot.cloud``
    ``auth_method``  One of ``bearer_token``, ``password``, ``secret_key``
    ``username``     ThoughtSpot user name / e-mail
    ``token``        *bearer_token only* — the pre-issued bearer token
    ``password``     *password only* — the user's password
    ``secret_key``   *secret_key only* — the secret key for token exchange
    ===============  ==========================================================

    Token exchange is lazy — no network call is made during ``__init__``.
    The first call to :meth:`get_token` (or any API helper) triggers the
    exchange and caches the result.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        profile: str = "default",
        *,
        dbutils=None,
    ) -> None:
        """Initialise the client for the given *profile*.

        Parameters
        ----------
        profile:
            Name of the Databricks Secrets scope to read from.
            The scope name used is ``thoughtspot-{profile}``.
        dbutils:
            The Databricks ``dbutils`` object.  If ``None`` (the default) the
            constructor checks ``builtins.dbutils`` — the name Databricks
            automatically injects into notebook scope.  Pass an explicit value
            in tests (or any non-notebook context) to avoid the builtins lookup.

        Raises
        ------
        RuntimeError
            If *dbutils* is ``None`` and ``builtins.dbutils`` is not set.
        """
        if dbutils is None:
            dbutils = getattr(builtins, "dbutils", None)
        if dbutils is None:
            raise RuntimeError(
                "dbutils is not available. Either pass it explicitly as "
                "ThoughtSpotClient(profile, dbutils=dbutils) or run this "
                "code inside a Databricks notebook where dbutils is injected."
            )

        self._dbutils = dbutils
        self._profile = profile
        self._scope = f"thoughtspot-{profile}"

        # Read non-sensitive profile metadata from Secrets.
        self._base_url: str = self._secret("base_url").rstrip("/")
        self._auth_method: str = self._secret("auth_method")
        self._username: str = self._secret("username")

        # Token cache — populated lazily on first get_token() call.
        self._token: Optional[str] = None
        self._token_expiry: Optional[float] = None  # Unix timestamp; None = no expiry

    # ------------------------------------------------------------------
    # Secret helpers
    # ------------------------------------------------------------------

    def _secret(self, key: str) -> str:
        """Read a single secret from this profile's scope."""
        return self._dbutils.secrets.get(self._scope, key)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _authenticate(self) -> tuple[str, Optional[float]]:
        """Perform the auth flow for this profile's auth_method.

        Returns
        -------
        (token, expiry_timestamp)
            *expiry_timestamp* is a Unix float (time.time() + TTL) for
            exchanged tokens, or ``None`` for bearer tokens (no expiry tracked).

        Raises
        ------
        ThoughtSpotAPIError
            If the token exchange endpoint returns 401 or 403.
        """
        method = self._auth_method

        if method == "bearer_token":
            token = self._secret("token")
            return token, None

        # Both password and secret_key hit the same exchange endpoint.
        url = f"{self._base_url}/api/rest/2.0/auth/token/full"
        body: dict = {
            "username": self._username,
            "validity_time_in_sec": 3600,
        }

        if method == "password":
            body["password"] = self._secret("password")
        elif method == "secret_key":
            body["secret_key"] = self._secret("secret_key")
        else:
            raise ValueError(f"Unknown auth_method: {method!r}")

        resp = requests.request(
            "POST",
            url,
            json=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=30,
        )

        if resp.status_code in (401, 403):
            raise ThoughtSpotAPIError(resp.status_code, resp.text, url)

        if not resp.ok:
            raise ThoughtSpotAPIError(resp.status_code, resp.text[:500], url)

        data = resp.json()
        token = data["token"]
        # token_expiry_duration is in milliseconds.
        validity_ms: int = data.get("token_expiry_duration", 3_600_000)
        expiry = time.time() + (validity_ms / 1000.0)
        return token, expiry

    def get_token(self) -> str:
        """Return a valid bearer token, refreshing if necessary.

        For ``bearer_token`` profiles the stored token is returned as-is
        (no expiry tracking). For ``password`` and ``secret_key`` profiles
        the token is refreshed when it is within ``_REFRESH_BUFFER_SECS``
        seconds of expiry, or when the cache is empty.

        Returns
        -------
        str
            A valid bearer token for use in ``Authorization: Bearer`` headers.
        """
        now = time.time()
        if self._token is not None:
            # Check expiry: None means no expiry (bearer_token), so no refresh.
            if self._token_expiry is None:
                return self._token
            if self._token_expiry - now > _REFRESH_BUFFER_SECS:
                return self._token

        # Cache is empty or token is about to expire — (re-)authenticate.
        self._token, self._token_expiry = self._authenticate()
        return self._token

    def logout(self) -> None:
        """Clear the cached token, forcing re-authentication on the next request."""
        self._token = None
        self._token_expiry = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict:
        """Build authentication headers for a ThoughtSpot REST API request."""
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request_with_retry(
        self, method: str, path: str, **kwargs
    ) -> requests.Response:
        """Make an authenticated HTTP request, retrying once on 401.

        Parameters
        ----------
        method:
            HTTP method string (e.g. ``"GET"``, ``"POST"``).
        path:
            URL path relative to ``base_url`` (must start with ``/``).
        **kwargs:
            Passed directly to ``requests.request`` (e.g. ``json=``, ``params=``).

        Returns
        -------
        requests.Response
            The response object on success (2xx).

        Raises
        ------
        ThoughtSpotAPIError
            On any non-2xx status after a single 401 retry.
        """
        url = f"{self._base_url}{path}"
        headers = self._auth_headers()
        kwargs.setdefault("headers", {})
        caller_headers = dict(kwargs["headers"])
        kwargs["headers"] = {**headers, **caller_headers}
        kwargs.setdefault("timeout", 60)

        resp = requests.request(method, url, **kwargs)

        if resp.status_code == 401:
            # Stale token — clear cache, re-auth, and retry once.
            self.logout()
            headers = self._auth_headers()
            kwargs["headers"] = {**headers, **caller_headers}
            resp = requests.request(method, url, **kwargs)

        if not resp.ok:
            raise ThoughtSpotAPIError(resp.status_code, resp.text, path)

        return resp

    def get(self, path: str, **kwargs) -> requests.Response:
        """Make an authenticated GET request.

        Parameters
        ----------
        path:
            URL path relative to ``base_url``.
        **kwargs:
            Forwarded to ``requests.request``.
        """
        return self._request_with_retry("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        """Make an authenticated POST request.

        Parameters
        ----------
        path:
            URL path relative to ``base_url``.
        **kwargs:
            Forwarded to ``requests.request``.
        """
        return self._request_with_retry("POST", path, **kwargs)

    # ------------------------------------------------------------------
    # Metadata API
    # ------------------------------------------------------------------

    _BUCKET_TO_TYPE: dict = {
        "TABLE": "LOGICAL_TABLE",
        "MODEL": "LOGICAL_TABLE",
        "WORKSHEET": "LOGICAL_TABLE",
        "SQL_VIEW": "LOGICAL_TABLE",
        "VIEW": "LOGICAL_TABLE",
        "ONE_TO_ONE_LOGICAL": "LOGICAL_TABLE",
        "AGGR_WORKSHEET": "LOGICAL_TABLE",
        "LOGICAL_COLUMN": "LOGICAL_COLUMN",
        "ANSWER": "ANSWER",
        "LIVEBOARD": "LIVEBOARD",
        "PINBOARD": "LIVEBOARD",
        "SET": "SET",
        "COHORT": "SET",
        "FEEDBACK": "FEEDBACK",
    }

    def metadata_search(
        self,
        *,
        type: str,
        subtypes=None,
        name: Optional[str] = None,
        guid: Optional[str] = None,
        tags=None,
        include_hidden: bool = False,
        fetch_all: bool = False,
    ) -> list:
        """Search for metadata objects.

        POST /api/rest/2.0/metadata/search

        Parameters
        ----------
        type:
            Metadata type (required), e.g. ``"LOGICAL_TABLE"``, ``"ANSWER"``.
        subtypes:
            Optional list of subtypes to filter by.
        name:
            Optional name pattern (passed as ``name_pattern`` in the request).
        guid:
            Optional GUID to filter by (passed as ``identifier`` in the request).
        tags:
            Optional list of tag identifiers to filter by.
        include_hidden:
            Whether to include hidden objects.
        fetch_all:
            If True, auto-paginates until an empty page is returned.

        Returns
        -------
        list[dict]
            List of metadata objects matching the search criteria.
        """
        page_size = 500
        offset = 0
        results: list = []

        while True:
            metadata_filter: dict = {"type": type}
            if subtypes:
                metadata_filter["sub_types"] = subtypes
            if name is not None:
                metadata_filter["name_pattern"] = name
            if guid is not None:
                metadata_filter["identifier"] = guid
            if tags:
                metadata_filter["tag_identifiers"] = tags

            body: dict = {
                "metadata": [metadata_filter],
                "include_hidden_objects": include_hidden,
                "record_size": page_size,
                "record_offset": offset,
            }

            resp = self.post("/api/rest/2.0/metadata/search", json=body)
            page = resp.json()

            if not page:
                break

            results.extend(page)

            if not fetch_all or len(page) < page_size:
                break

            offset += page_size

        return results

    def metadata_get(self, guid: str, *, type: str) -> dict:
        """Retrieve a single metadata object by GUID.

        Parameters
        ----------
        guid:
            The GUID of the object to retrieve.
        type:
            Metadata type, e.g. ``"LOGICAL_TABLE"``.

        Returns
        -------
        dict
            The metadata object.

        Raises
        ------
        ThoughtSpotAPIError
            With status_code 404 if no object with the given GUID is found.
        """
        results = self.metadata_search(
            type=type,
            subtypes=None,
            name=None,
            guid=guid,
            tags=None,
            include_hidden=False,
            fetch_all=False,
        )
        if not results:
            raise ThoughtSpotAPIError(
                404,
                f"No metadata object found with guid={guid!r} and type={type!r}",
                "/api/rest/2.0/metadata/search",
            )
        return results[0]

    def metadata_dependents(self, guids: list, *, type: str) -> list:
        """Return objects that depend on the given GUIDs.

        POST /api/rest/2.0/metadata/search with ``dependent_object_version: "V2"``.

        Parameters
        ----------
        guids:
            List of source object GUIDs to find dependents for.
        type:
            Metadata type of the source objects.

        Returns
        -------
        list[dict]
            Flattened list of dependent objects, each with keys:
            ``source_guid``, ``type`` (normalized), ``id``, ``name``.
        """
        body: dict = {
            "metadata": [{"type": type, "identifier": g} for g in guids],
            "dependent_object_version": "V2",
        }
        resp = self.post("/api/rest/2.0/metadata/search", json=body)
        raw: dict = resp.json()

        flat: list = []
        for source_guid, buckets in raw.items():
            for bucket_name, items in buckets.items():
                normalized_type = self._BUCKET_TO_TYPE.get(bucket_name, bucket_name)
                for item in items:
                    flat.append(
                        {
                            "source_guid": source_guid,
                            "type": normalized_type,
                            "id": item.get("id"),
                            "name": item.get("name"),
                        }
                    )
        return flat

    def metadata_delete(self, guids: list, *, type: str) -> dict:
        """Delete metadata objects by GUID.

        POST /api/rest/2.0/metadata/delete

        Parameters
        ----------
        guids:
            List of GUIDs to delete.
        type:
            Metadata type of the objects to delete.

        Returns
        -------
        dict
            Response body as a dict, or empty dict if no JSON body returned.
        """
        body: dict = {
            "metadata": [{"identifier": g, "type": type} for g in guids],
        }
        resp = self.post("/api/rest/2.0/metadata/delete", json=body)
        try:
            return resp.json()
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Auth API
    # ------------------------------------------------------------------

    def whoami(self) -> dict:
        """Return the currently authenticated ThoughtSpot user.

        Calls ``GET /api/rest/2.0/auth/session/user`` and returns the
        parsed JSON response as a dict.
        """
        resp = self.get("/api/rest/2.0/auth/session/user")
        return resp.json()

    # ------------------------------------------------------------------
    # TML API
    # ------------------------------------------------------------------

    def tml_export(
        self,
        guids: list,
        *,
        fqn: bool = False,
        associated: bool = False,
        format: str = "YAML",
        parse: bool = False,
        type: Optional[str] = None,
        include_obj_id: bool = False,
        include_obj_id_ref: bool = False,
        include_guid: bool = True,
    ) -> list:
        """Export TML for one or more objects.

        POST /api/rest/2.0/metadata/tml/export

        Parameters
        ----------
        guids:
            List of object GUIDs to export.
        fqn:
            If True, export with fully-qualified names (``export_fqn=True``).
        associated:
            If True, also export associated objects (``export_associated=True``).
        format:
            TML format: ``"YAML"`` (default) or ``"JSON"``.
        parse:
            If False (default), return the raw API response (list of dicts with
            ``edoc`` and ``info`` keys).  If True, parse each edoc and return a
            list of dicts with keys ``type``, ``guid``, ``tml``, and ``info``.
        type:
            Optional metadata type filter.  Passing ``"FEEDBACK"`` (any case)
            raises ``ValueError`` — FEEDBACK objects cannot be exported as TML;
            use :meth:`metadata_dependents` to locate FEEDBACK GUIDs instead.
        include_obj_id:
            If True, include ``obj_id`` fields in the exported TML.
        include_obj_id_ref:
            If True, include ``obj_id_ref`` fields in the exported TML.
        include_guid:
            If False, omit ``guid`` fields from the exported TML (default True).

        Returns
        -------
        list[dict]
            Raw API response items when ``parse=False``, or parsed items when
            ``parse=True``.

        Raises
        ------
        ValueError
            If *type* is ``"FEEDBACK"`` (case-insensitive).
        ThoughtSpotAPIError
            On any non-2xx API response.
        """
        if type is not None and type.upper() == "FEEDBACK":
            raise ValueError(
                "FEEDBACK objects cannot be exported as TML. "
                "Use metadata_dependents() to find FEEDBACK GUIDs."
            )

        body: dict = {
            "metadata": [{"identifier": g} for g in guids],
            "export_fqn": fqn,
            "export_associated": associated,
            "formattype": format,
        }

        # Only include export_options when any option deviates from its default.
        if include_obj_id or include_obj_id_ref or not include_guid:
            export_options: dict = {}
            if include_obj_id:
                export_options["include_obj_id"] = True
            if include_obj_id_ref:
                export_options["include_obj_id_ref"] = True
            if not include_guid:
                export_options["include_guid"] = False
            body["export_options"] = export_options

        resp = self.post("/api/rest/2.0/metadata/tml/export", json=body)
        data: list = resp.json()

        if not parse:
            return data

        parsed_items: list = []
        for item in data:
            edoc: str = item.get("edoc", "")
            info: dict = item.get("info", {})
            tml: dict = _parse_edoc(edoc, fmt=format)
            tml_type: Optional[str] = _detect_tml_type(tml)
            guid: str = info.get("id", "")
            parsed_items.append(
                {
                    "type": tml_type,
                    "guid": guid,
                    "tml": tml,
                    "info": info,
                }
            )

        return parsed_items

    def tml_import(
        self,
        tmls: list,
        *,
        policy: str = "PARTIAL",
        create_new: bool = False,
    ) -> list:
        """Import TML objects into ThoughtSpot.

        POST /api/rest/2.0/metadata/tml/import

        Parameters
        ----------
        tmls:
            List of TML strings (YAML or JSON) to import.
        policy:
            Import policy: ``"PARTIAL"`` (default, imports what it can) or
            ``"ALL_OR_NONE"`` (fail the whole batch on any error).
        create_new:
            If True, always create new objects even if a matching GUID exists.
            Defaults to False — True silently creates duplicates if called
            repeatedly on the same TML.

        Returns
        -------
        list[dict]
            List of import response objects.  A dict response is wrapped in a
            list for consistent return type.

        Raises
        ------
        ThoughtSpotAPIError
            On any non-2xx API response.
        """
        body: dict = {
            "metadata_tmls": tmls,
            "import_policy": policy,
            "create_new": create_new,
        }
        resp = self.post("/api/rest/2.0/metadata/tml/import", json=body)
        data = resp.json()
        if isinstance(data, dict):
            return [data]
        return list(data)

    # ------------------------------------------------------------------
    # Connections API
    # ------------------------------------------------------------------

    def connections_list(self, *, type: str = "SNOWFLAKE") -> list:
        """List data connections.

        POST /api/rest/2.0/connection/search — auto-paginates until all pages
        are retrieved.

        Parameters
        ----------
        type:
            Connection type to filter by (default ``"SNOWFLAKE"``).

        Returns
        -------
        list[dict]
            All matching connection objects.
        """
        page_size = 500
        offset = 0
        results: list = []

        while True:
            body: dict = {
                "data_warehouse_types": [type],
                "record_size": page_size,
                "record_offset": offset,
            }
            resp = self.post("/api/rest/2.0/connection/search", json=body)
            page = resp.json()

            if not page:
                break

            results.extend(page)

            if len(page) < page_size:
                break

            offset += page_size

        return results

    def connections_get(self, connection_id: str) -> dict:
        """Fetch a single connection with full table/column metadata.

        POST /tspublic/v1/connection/fetchConnection (v1 endpoint).

        Parameters
        ----------
        connection_id:
            The GUID of the connection to fetch.

        Returns
        -------
        dict
            Full connection object including ``dataWarehouseInfo``.
        """
        body: dict = {
            "connection_id": connection_id,
            "includeColumns": True,
        }
        resp = self.post("/tspublic/v1/connection/fetchConnection", json=body)
        return resp.json()

    def connections_add_tables(self, connection_id: str, tables: list) -> dict:
        """Add tables (and their columns) to an existing connection.

        Fetches the current connection state, merges the new tables using
        :meth:`_merge_tables`, then POSTs the updated configuration.

        Parameters
        ----------
        connection_id:
            The GUID of the connection to update.
        tables:
            List of table spec dicts, each with keys:
            ``db``, ``schema``, ``name``, ``columns``
            (each column: ``name``, ``type``).

        Returns
        -------
        dict
            The API response body, or empty dict if no JSON body returned.
        """
        try:
            fetch_response = self.connections_get(connection_id)
        except Exception:
            fetch_response = {}

        merged = self._merge_tables(fetch_response, tables)

        body: dict = {
            "data_warehouse_config": {
                "externalDatabases": merged,
            },
            "validate": True,
        }
        resp = self.post(
            f"/api/rest/2.0/connections/{connection_id}/update", json=body
        )
        try:
            return resp.json()
        except Exception:
            return {}

    @staticmethod
    def _merge_tables(fetch_response: dict, new_tables: list) -> list:
        """Merge new tables into an existing connection hierarchy.

        Preserves existing tables and columns, appending only missing columns
        to existing tables and creating full hierarchy entries for new ones.

        Parameters
        ----------
        fetch_response:
            Raw response from ``connections_get`` (may be empty dict on failure).
        new_tables:
            List of table spec dicts, each with:
            - ``db`` (str): database name
            - ``schema`` (str): schema name
            - ``name`` (str): table name
            - ``columns`` (list[dict]): each with ``name`` and ``type``

        Returns
        -------
        list
            Updated ``externalDatabases`` hierarchy suitable for the
            ``data_warehouse_config`` payload.
        """
        # Extract existing hierarchy from either key name the API may use.
        dw_info = fetch_response.get("dataWarehouseInfo", {})
        existing_dbs: list = dw_info.get("databases", []) or dw_info.get(
            "externalDatabases", []
        )

        # Build a nested index: db → schema → table → table_dict
        db_index: dict = {}
        for db_entry in existing_dbs:
            db_name = db_entry.get("name", "")
            db_index[db_name] = {"_entry": db_entry, "schemas": {}}
            for schema_entry in db_entry.get("schemas", []):
                schema_name = schema_entry.get("name", "")
                db_index[db_name]["schemas"][schema_name] = {
                    "_entry": schema_entry,
                    "tables": {},
                }
                for table_entry in schema_entry.get("tables", []):
                    table_name = table_entry.get("name", "")
                    db_index[db_name]["schemas"][schema_name]["tables"][
                        table_name
                    ] = table_entry

        # Merge new tables into the index.
        for spec in new_tables:
            db_name = spec["db"]
            schema_name = spec["schema"]
            table_name = spec["name"]
            columns = spec.get("columns", [])

            # Ensure db exists.
            if db_name not in db_index:
                db_index[db_name] = {"_entry": {"name": db_name, "schemas": []}, "schemas": {}}

            # Ensure schema exists.
            if schema_name not in db_index[db_name]["schemas"]:
                db_index[db_name]["schemas"][schema_name] = {
                    "_entry": {"name": schema_name, "tables": []},
                    "tables": {},
                }

            schema_idx = db_index[db_name]["schemas"][schema_name]

            if table_name in schema_idx["tables"]:
                # Table already exists — append only missing columns.
                existing_table = schema_idx["tables"][table_name]
                existing_col_names = {
                    c.get("name") for c in existing_table.get("columns", [])
                }
                for col in columns:
                    if col["name"] not in existing_col_names:
                        new_col = {
                            "name": col["name"],
                            "type": col["type"],
                            "selected": True,
                            "isLinkedActive": True,
                        }
                        existing_table.setdefault("columns", []).append(new_col)
            else:
                # New table — build full entry.
                built_columns = [
                    {
                        "name": c["name"],
                        "type": c["type"],
                        "selected": True,
                        "isLinkedActive": True,
                    }
                    for c in columns
                ]
                table_entry = {
                    "name": table_name,
                    "type": "TABLE",
                    "selected": True,
                    "linked": True,
                    "columns": built_columns,
                }
                schema_idx["tables"][table_name] = table_entry

        # Reconstruct the externalDatabases list from the index.
        result_dbs: list = []
        for db_name, db_data in db_index.items():
            result_schemas: list = []
            for schema_name, schema_data in db_data["schemas"].items():
                result_tables = list(schema_data["tables"].values())
                schema_entry = dict(schema_data["_entry"])
                schema_entry["name"] = schema_name
                schema_entry["tables"] = result_tables
                result_schemas.append(schema_entry)
            db_entry = dict(db_data["_entry"])
            db_entry["name"] = db_name
            db_entry["schemas"] = result_schemas
            result_dbs.append(db_entry)

        return result_dbs

    # ------------------------------------------------------------------
    # Tables API
    # ------------------------------------------------------------------

    def tables_create(
        self, tables: list, *, retries: int = 3, retry_delay: float = 5.0
    ) -> dict:
        """Create ThoughtSpot table objects from a list of specs.

        For each spec, builds a table TML via :meth:`_build_table_tml`,
        imports it via :meth:`tml_import`, and resolves the resulting GUID.
        Retries on JDBC/connection-metadata errors.

        Parameters
        ----------
        tables:
            List of table spec dicts, each with:
            - ``name`` (str): table name (used as the TML display name)
            - ``db`` (str): database name
            - ``schema`` (str): schema name
            - ``db_table`` (str, optional): physical table name (defaults to ``name``)
            - ``connection_name`` (str): display name of the data connection
            - ``columns`` (list[dict]): column specs with ``name``, ``type``,
              ``kind`` (``"ATTRIBUTE"`` or ``"MEASURE"``), and optional
              ``db_column_name``
        retries:
            Maximum number of attempts per table on JDBC errors (default 3).
        retry_delay:
            Seconds to wait between retries (default 5.0).

        Returns
        -------
        dict
            Mapping of table name → GUID string, or ``None`` if the table
            failed to import after all retries.
        """
        result: dict = {}

        for spec in tables:
            table_name = spec["name"]
            tml_str = self._build_table_tml(spec)
            guid = None

            for attempt in range(retries):
                try:
                    import_result = self.tml_import([tml_str], create_new=True)
                    # Resolve GUID from import response.
                    # Response shape: list of items, each with response.header.id_guid
                    # or object_guids list, depending on the API version.
                    for item in import_result:
                        # V2 import response shape: {"response": {"header": {"id_guid": ...}}}
                        header = (
                            item.get("response", {})
                            .get("header", {})
                        )
                        candidate = header.get("id_guid") or header.get("id")
                        if candidate:
                            guid = candidate
                            break
                        # Alternative shape: {"object_guids": [...]}
                        guids_list = item.get("object_guids", [])
                        if guids_list:
                            guid = guids_list[0]
                            break
                    break  # Success — exit retry loop.

                except ThoughtSpotAPIError as exc:
                    error_text = str(exc)
                    is_jdbc = "JDBC" in error_text or "CONNECTION_METADATA" in error_text
                    if is_jdbc and attempt < retries - 1:
                        time.sleep(retry_delay)
                        continue
                    # Either not a retryable error, or out of retries.
                    guid = None
                    break

            result[table_name] = guid

        return result

    @staticmethod
    def _build_table_tml(spec: dict) -> str:
        """Build a YAML TML string for a single table.

        Parameters
        ----------
        spec:
            Table specification dict with keys:
            - ``name`` (str): TML display name
            - ``db`` (str): database name
            - ``schema`` (str): schema name
            - ``db_table`` (str, optional): physical table name
            - ``connection_name`` (str): data connection display name
            - ``columns`` (list[dict]): each with ``name``, ``type``,
              ``kind`` (``"ATTRIBUTE"`` or ``"MEASURE"``), and optional
              ``db_column_name``

        Returns
        -------
        str
            YAML-formatted TML string ready for import.
        """
        name = spec["name"]
        db = spec["db"]
        schema = spec["schema"]
        db_table = spec.get("db_table", name)
        connection_name = spec["connection_name"]
        columns = spec.get("columns", [])

        tml_columns = []
        for col in columns:
            col_name = col["name"]
            col_type = col["type"]
            col_kind = col.get("kind", "ATTRIBUTE")
            db_col_name = col.get("db_column_name", col_name)

            col_entry: dict = {
                "name": col_name,
                "db_column_name": db_col_name,
                "properties": {
                    "column_type": col_kind,
                },
                "db_column_properties": {
                    "data_type": col_type,
                },
            }
            if col_kind == "MEASURE":
                col_entry["properties"]["aggregation"] = "SUM"

            tml_columns.append(col_entry)

        tml_dict: dict = {
            "table": {
                "name": name,
                "db": db,
                "schema": schema,
                "db_table": db_table,
                "connection": {
                    "name": connection_name,
                },
                "columns": tml_columns,
            }
        }

        return yaml.dump(tml_dict, default_flow_style=False, allow_unicode=True)

    # ------------------------------------------------------------------
    # Users and Groups API
    # ------------------------------------------------------------------

    def users_search(
        self,
        *,
        name: Optional[str] = None,
        org: Optional[str] = None,
        limit: int = 20,
    ) -> list:
        """Search for ThoughtSpot users.

        POST /api/rest/2.0/users/search

        Parameters
        ----------
        name:
            Optional name pattern to filter users by.
        org:
            Optional org identifier to filter users by.
        limit:
            Maximum number of results to return (default 20).

        Returns
        -------
        list[dict]
            List of matching user objects.
        """
        body: dict = {"record_size": limit}
        if name is not None:
            body["name_pattern"] = name
        if org is not None:
            body["org_identifiers"] = [org]
        resp = self.post("/api/rest/2.0/users/search", json=body)
        return resp.json()

    def groups_search(
        self,
        *,
        name: Optional[str] = None,
        org: Optional[str] = None,
        include_users: bool = False,
        limit: int = 20,
    ) -> list:
        """Search for ThoughtSpot groups.

        POST /api/rest/2.0/groups/search

        Parameters
        ----------
        name:
            Optional name pattern to filter groups by.
        org:
            Optional org identifier to filter groups by.
        include_users:
            If True, include group members in the response.
        limit:
            Maximum number of results to return (default 20).

        Returns
        -------
        list[dict]
            List of matching group objects.
        """
        body: dict = {
            "record_size": limit,
            "include_user_count": include_users,
        }
        if name is not None:
            body["name_pattern"] = name
        if org is not None:
            body["org_identifiers"] = [org]
        resp = self.post("/api/rest/2.0/groups/search", json=body)
        return resp.json()

    # ------------------------------------------------------------------
    # Orgs API
    # ------------------------------------------------------------------

    def orgs_search(
        self,
        *,
        status: Optional[str] = None,
        name: Optional[str] = None,
        limit: int = 200,
    ) -> list:
        """Search for ThoughtSpot orgs.

        POST /api/rest/2.0/orgs/search

        Parameters
        ----------
        status:
            Optional org status filter (e.g. ``"ACTIVE"``).
        name:
            Optional name pattern to filter orgs by.
        limit:
            Maximum number of results to return (default 200).

        Returns
        -------
        list[dict]
            List of matching org objects.
        """
        body: dict = {"record_size": limit}
        if status is not None:
            body["status"] = status
        if name is not None:
            body["name_pattern"] = name
        resp = self.post("/api/rest/2.0/orgs/search", json=body)
        return resp.json()

    # ------------------------------------------------------------------
    # Variables (Template Variables) API
    # ------------------------------------------------------------------

    def variables_search(self, *, identifier: Optional[str] = None) -> list:
        """Search for template variables.

        POST /api/rest/2.0/template/variables/search

        Parameters
        ----------
        identifier:
            Optional identifier (name or GUID) to filter variables by.

        Returns
        -------
        list[dict]
            List of matching variable objects with metadata and current values.
        """
        body: dict = {"response_content": "METADATA_AND_VALUES"}
        if identifier is not None:
            body["variable_identifiers"] = [identifier]
        resp = self.post("/api/rest/2.0/template/variables/search", json=body)
        return resp.json()

    def variables_set(
        self,
        variable: str,
        value: str,
        *,
        orgs: list,
        users: Optional[list] = None,
    ) -> dict:
        """Set a template variable value for one or more orgs (and optionally users).

        POST /api/rest/2.0/template/variables/update-values with
        ``operation=REPLACE``.

        Parameters
        ----------
        variable:
            Identifier (name or GUID) of the variable to set.
        value:
            The value to assign.
        orgs:
            List of org identifiers to scope the assignment to.
        users:
            Optional list of user identifiers.  When provided, the value is
            set per-user within each org; when omitted the value is set at
            the org level.

        Returns
        -------
        dict
            API response body, or empty dict if no JSON body returned.
        """
        scopes = self._build_variable_scopes(orgs=orgs, users=users)
        body: dict = {
            "variable_identifier": variable,
            "operation": "REPLACE",
            "variable_values": [
                {"value": value, "scopes": scopes},
            ],
        }
        resp = self.post("/api/rest/2.0/template/variables/update-values", json=body)
        try:
            return resp.json()
        except Exception:
            return {}

    def variables_remove(
        self,
        variable: str,
        value: str,
        *,
        orgs: list,
        users: Optional[list] = None,
    ) -> dict:
        """Remove a template variable value for one or more orgs (and optionally users).

        POST /api/rest/2.0/template/variables/update-values with
        ``operation=REMOVE``.

        Parameters
        ----------
        variable:
            Identifier (name or GUID) of the variable to update.
        value:
            The value to remove.
        orgs:
            List of org identifiers to scope the removal to.
        users:
            Optional list of user identifiers.  When provided, the removal is
            scoped per-user within each org; when omitted it is org-level.

        Returns
        -------
        dict
            API response body, or empty dict if no JSON body returned.
        """
        scopes = self._build_variable_scopes(orgs=orgs, users=users)
        body: dict = {
            "variable_identifier": variable,
            "operation": "REMOVE",
            "variable_values": [
                {"value": value, "scopes": scopes},
            ],
        }
        resp = self.post("/api/rest/2.0/template/variables/update-values", json=body)
        try:
            return resp.json()
        except Exception:
            return {}

    @staticmethod
    def _build_variable_scopes(*, orgs: list, users: Optional[list]) -> list:
        """Build the scopes list for a variable update-values request.

        Parameters
        ----------
        orgs:
            List of org identifiers.
        users:
            Optional list of user identifiers.  When provided, one scope entry
            is created per (org, user) pair.  When omitted, one org-level entry
            is created per org.

        Returns
        -------
        list[dict]
            Scopes list for the ``variable_values[].scopes`` field.
        """
        scopes: list = []
        for org in orgs:
            if users:
                for user in users:
                    scopes.append({"org_identifier": org, "user_identifier": user})
            else:
                scopes.append({"org_identifier": org})
        return scopes

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """The base URL of the ThoughtSpot instance (trailing slash stripped)."""
        return self._base_url
