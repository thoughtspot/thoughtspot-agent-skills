"""dbt Cloud Admin API access — profile resolution, run lookup, artifact cache.

The one I/O module in `ts_cli/dbt/` (every sibling is pure). Extracted from the
three near-identical blocks `commands/dbt.py` grew in `list-models`,
`build-model` and `trigger-job`, each of which resolved the same profile, found
the same latest run and re-downloaded the same `manifest.json`.

**Why the cache is keyed on `run_id`.** A round trip runs `list-models`, then
`inspect`, then `build-model`, and each wanted the manifest of the *same*
successful run — 3-5 downloads of a file that is immutable once the run
finishes. Keying the cache on the run id means a new dbt job invalidates it by
construction: there is no TTL to tune and no way to serve a stale artifact,
because a stale artifact belongs to a different run and therefore a different
file. `--no-cache` exists for the one case the key cannot see: a run whose
artifacts were re-uploaded in place.

Cache files live in a per-user 0700 directory under the OS temp dir
(`ts_dbt_cache_<uid>`, see `artifacts.private_cache_dir`), each written
atomically at mode 0600. They hold compiled dbt metadata, never
credentials — the token is held in memory for the life of the process and is
never written to disk, logged, or included in an error message.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests as _requests
# Imported by name, not through `_requests`: tests swap `_requests` for a stub
# that has only `.get`, and the except clause must still resolve.
from requests.exceptions import Timeout as _RequestsTimeout

from ts_cli.dbt.artifacts import is_private_file, private_cache_dir, write_private_file
from ts_cli.profile_ops import derive_env_var, load_platform_profiles, slugify

DEFAULT_DBT_URL = "https://cloud.getdbt.com"
_SUCCESS_STATUS = "10"  # dbt Cloud run status enum: 10 = Success

# (connect, read) seconds for every dbt Cloud Admin API call. 2026-10 (PR #506
# review): none of these calls had a timeout, so a stalled dbt Cloud endpoint
# hung `list-models` / `build-model` / `trigger-job` indefinitely. The read
# budget is generous because `manifest.json` for a large project runs to
# hundreds of MB.
DBT_CLOUD_TIMEOUT = (10, 120)


@dataclass
class DbtCloudCtx:
    """Everything an Admin API call needs, resolved once.

    `token` is deliberately excluded from `repr` — a dataclass that prints its
    own credential turns any stray `print(ctx)` or traceback into a leak.
    """

    account_id: str
    project_id: str = ""
    dbt_env_id: Optional[str] = None
    base: str = DEFAULT_DBT_URL
    slug: str = ""
    token: str = field(default="", repr=False)

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Token {self.token}"}


def token_from_keychain(slug: str, profile: Optional[dict] = None) -> Optional[str]:
    """dbt Cloud token for a profile slug: env var first, then Keychain.

    Env var `DBT_CLOUD_TOKEN_{SLUG}` (the profile's `token_env`, set from
    `~/.zshenv`); Keychain service `dbt-cloud-{slug}`, account `token` — the
    convention `ts profiles add --platform dbt-cloud` writes. Env is checked
    first because a Python-side Keychain read prompts for the keychain password
    on every call. Returns None when neither source has a value.

    When the profile dict is supplied its own recorded `token_env` /
    `keychain_service` / `keychain_account` win over the derived names: those
    are what `ts profiles add` actually wrote, and re-deriving them here is how
    a lookup silently misses. Callers previously passed the raw profile *name*
    as the slug, which resolves to nothing for any name that is not already
    slug-shaped ("My Project" -> service `dbt-cloud-My Project`, never written).
    """
    profile = profile or {}
    try:
        derived_env = derive_env_var("dbt-cloud", "token", slug)
    except ValueError:
        derived_env = None
    env_var = profile.get("token_env") or derived_env
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]

    service = profile.get("keychain_service") or f"dbt-cloud-{slug}"
    account = profile.get("keychain_account") or "token"
    try:
        import keyring

        return keyring.get_password(service, account) or None
    except Exception:
        return None


def _lookup_profile(profile_name: str) -> dict:
    """The stored dbt Cloud profile, or a `SystemExit` naming how to list them."""
    prof = next(
        (p for p in load_platform_profiles("dbt-cloud") if p.get("name") == profile_name),
        None)
    if not prof:
        raise SystemExit(
            f"dbt Cloud profile {profile_name!r} not found. "
            "Run `ts profiles list --dbt-cloud` to see available profiles.")
    return prof


def _token_or_exit(profile_name: Optional[str], prof: dict,
                   access_token_env: Optional[str]) -> str:
    """The API token, from the keychain or the named env var. Never returns
    empty — an unauthenticated call would 401 somewhere much less obvious."""
    if profile_name:
        token = token_from_keychain(slugify(profile_name), prof)
        if not token:
            raise SystemExit(
                f"No token found in keychain for profile {profile_name!r} "
                "(service: dbt-cloud-{slug}, account: token). "
                "Re-run `ts profiles add --platform dbt-cloud` to re-store the credential.")
        return token
    if access_token_env:
        token = os.environ.get(access_token_env)
        if not token:
            raise SystemExit(
                f"Environment variable {access_token_env!r} is not set. "
                "Export it in your own shell — never pass a token as a flag value.")
        return token
    raise SystemExit(
        "Provide either --dbt-cloud-profile <name> (reads the token from the "
        "keychain) or --access-token-env <VAR> (reads it from an env var).")


def resolve_dbt_profile(
    profile_name: Optional[str],
    *,
    account_id: Optional[str] = None,
    project_id: Optional[str] = None,
    dbt_env_id: Optional[str] = None,
    dbt_url: Optional[str] = None,
    access_token_env: Optional[str] = None,
    require_project: bool = True,
) -> DbtCloudCtx:
    """Resolve a dbt Cloud profile (plus per-flag overrides) into a `DbtCloudCtx`.

    Either `profile_name` (token from the OS keychain — preferred) or
    `access_token_env` (token from the named env var). Explicit ids override the
    profile's stored values. Raises `SystemExit` with an actionable message when
    anything required is missing.
    """
    prof = _lookup_profile(profile_name) if profile_name else {}
    token = _token_or_exit(profile_name, prof, access_token_env)

    account_id = account_id or prof.get("account_id")
    project_id = project_id or prof.get("project_id")
    dbt_env_id = dbt_env_id or prof.get("dbt_env_id")
    dbt_url = dbt_url or prof.get("dbt_url") or DEFAULT_DBT_URL

    if not account_id:
        raise SystemExit("--account-id is required (or use --dbt-cloud-profile).")
    if require_project and not project_id:
        raise SystemExit("--project-id is required (or use --dbt-cloud-profile).")

    return DbtCloudCtx(
        account_id=str(account_id),
        project_id=str(project_id or ""),
        dbt_env_id=str(dbt_env_id) if dbt_env_id else None,
        base=(dbt_url or DEFAULT_DBT_URL).rstrip("/"),
        slug=slugify(profile_name) if profile_name else "env",
        token=token,
    )


def dbt_cloud_call(method: str, url: str, *, what: str, **kwargs):
    """`requests.<method>(url, ...)` with `DBT_CLOUD_TIMEOUT`, timeouts as SystemExit.

    `what` names the call ("fetching runs", "polling run 7") so a timeout says
    which request stalled instead of surfacing a urllib3 traceback.
    """
    try:
        return getattr(_requests, method)(url, timeout=DBT_CLOUD_TIMEOUT, **kwargs)
    except _RequestsTimeout as exc:
        connect, read = DBT_CLOUD_TIMEOUT
        raise SystemExit(
            f"dbt Cloud API timed out {what} (connect {connect}s / read {read}s): "
            f"{type(exc).__name__}. Check dbt Cloud status and network access, "
            "then retry.") from None


def latest_successful_run(ctx: DbtCloudCtx) -> int:
    """Run id of the most recent SUCCESSFUL run for the ctx's project/environment."""
    params = {
        "project_id": ctx.project_id,
        "order_by": "-created_at",
        "limit": "1",
        "status": _SUCCESS_STATUS,
    }
    if ctx.dbt_env_id:
        params["environment_id"] = ctx.dbt_env_id

    resp = dbt_cloud_call(
        "get", f"{ctx.base}/api/v2/accounts/{ctx.account_id}/runs/",
        what="fetching runs", headers=ctx.headers, params=params)
    if not resp.ok:
        raise SystemExit(
            f"dbt Cloud API error fetching runs ({resp.status_code}): {resp.text}")
    runs = resp.json().get("data", [])
    if not runs:
        env_hint = f" in environment {ctx.dbt_env_id}" if ctx.dbt_env_id else ""
        raise SystemExit(
            f"No successful runs found for project {ctx.project_id}{env_hint}. "
            "Check the project ID, environment ID, and token permissions.")
    return runs[0]["id"]


def artifact_cache_path(ctx: DbtCloudCtx, run_id: int, name: str) -> Path:
    """Where `fetch_artifact` caches one artifact. `name` is sanitised into the
    filename so a caller cannot escape the cache dir with a path-shaped value.

    The key carries the account id and a short hash of the dbt Cloud base URL
    as well as the profile slug (PR #506 review): every `--access-token-env`
    caller has slug "env", so two accounts — or two dbt Cloud hosts — that
    happened to share a run id read each other's manifest. Raises `OSError`
    when the private cache dir is unusable; `fetch_artifact` then skips the cache.
    """
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    acct = "".join(c if c.isalnum() else "_" for c in str(ctx.account_id))
    host = hashlib.sha256(ctx.base.encode("utf-8")).hexdigest()[:8]
    return private_cache_dir() / f"ts_dbt_artifact_{ctx.slug}_{acct}_{host}_{run_id}_{safe}"


def _cache_location(ctx: DbtCloudCtx, run_id: int, name: str) -> Optional[Path]:
    """`artifact_cache_path`, or None (with a stderr note) when it is unusable."""
    try:
        return artifact_cache_path(ctx, run_id, name)
    except OSError as exc:
        print(f"Warning: dbt artifact cache disabled — {exc}", file=sys.stderr)
        return None


def _read_cache(cache: Optional[Path]) -> Optional[dict]:
    """The cached artifact, or None. A symlink or a file this user does not own
    is ignored (PR #506 review) — it was not written by this process."""
    if cache is None or not is_private_file(cache):
        return None
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def fetch_artifact(
    ctx: DbtCloudCtx, run_id: int, name: str, *, use_cache: bool = True
) -> dict:
    """Download one run artifact (`manifest.json`, `catalog.json`, …), cached by run.

    A finished run's artifacts are immutable, so the `(slug, account, host,
    run_id, name)` key
    is exact: a cache hit cannot be stale for that run, and a newer run has a
    different key. Pass `use_cache=False` to force a re-download.

    A corrupt or unreadable cache file is ignored rather than fatal — the
    artifact is simply re-fetched, and a failure to *write* the cache is
    likewise non-fatal (a read-only temp dir must not break the command).
    """
    cache = _cache_location(ctx, run_id, name)
    cached = _read_cache(cache) if use_cache else None
    if cached is not None:
        return cached

    resp = dbt_cloud_call(
        "get",
        f"{ctx.base}/api/v2/accounts/{ctx.account_id}/runs/{run_id}/artifacts/{name}",
        what=f"downloading {name} for run {run_id}", headers=ctx.headers)
    if not resp.ok:
        raise SystemExit(
            f"Failed to download {name} for run {run_id} "
            f"({resp.status_code}): {resp.text}")
    data = resp.json()

    if cache is not None:
        try:
            write_private_file(cache, lambda fh: fh.write(json.dumps(data).encode("utf-8")))
        except OSError:
            pass
    return data


# ---------------------------------------------------------------------------
# trigger-job calls — moved here from commands/dbt.py `trigger_job` (2026-10,
# PR #506 review) so every dbt Cloud request goes through `dbt_cloud_call` and
# its timeout, and so the command's own complexity went down, not up.
# ---------------------------------------------------------------------------

def list_jobs_with_last_success(ctx: DbtCloudCtx) -> list:
    """The project's jobs, each with the finish time of its latest successful run.

    The runs lookup is best-effort (a non-OK response leaves every
    `last_successful_run` None) — it only decorates the job list.
    """
    acct = f"{ctx.base}/api/v2/accounts/{ctx.account_id}"
    jobs_resp = dbt_cloud_call("get", f"{acct}/jobs/", what="listing jobs",
                               headers=ctx.headers, params={"project_id": ctx.project_id})
    if not jobs_resp.ok:
        raise SystemExit(
            f"dbt Cloud API error listing jobs ({jobs_resp.status_code}): {jobs_resp.text}")
    jobs = jobs_resp.json().get("data", [])
    if not jobs:
        raise SystemExit(f"No jobs found for project {ctx.project_id}.")

    runs_resp = dbt_cloud_call(
        "get", f"{acct}/runs/", what="fetching recent runs", headers=ctx.headers,
        params={"project_id": ctx.project_id, "order_by": "-created_at", "limit": "100"})
    last_success: dict = {}
    if runs_resp.ok:
        for run in runs_resp.json().get("data", []):
            jid = run.get("job_definition_id")
            if run.get("status") == 10 and jid and jid not in last_success:
                last_success[jid] = run.get("finished_at") or run.get("created_at") or ""
    return [{"id": j["id"], "name": j.get("name", ""),
             "description": j.get("description", ""),
             "last_successful_run": last_success.get(j["id"], None)}
            for j in jobs]


def trigger_run(ctx: DbtCloudCtx, job_id: int, cause: str):
    """POST a run of `job_id`; returns the new run id."""
    resp = dbt_cloud_call(
        "post", f"{ctx.base}/api/v2/accounts/{ctx.account_id}/jobs/{job_id}/run/",
        what=f"triggering job {job_id}", headers=ctx.headers, json={"cause": cause})
    if not resp.ok:
        raise SystemExit(f"Failed to trigger job {job_id} ({resp.status_code}): {resp.text}")
    return resp.json().get("data", {}).get("id")


def get_run(ctx: DbtCloudCtx, run_id, *, with_steps: bool = False) -> Optional[dict]:
    """One run's `data` block. With `with_steps`, includes `run_steps` and is
    best-effort (None on a non-OK response) — it only enriches a failure report."""
    kwargs = {"params": {"include_related": '["run_steps"]'}} if with_steps else {}
    resp = dbt_cloud_call(
        "get", f"{ctx.base}/api/v2/accounts/{ctx.account_id}/runs/{run_id}/",
        what=f"polling run {run_id}", headers=ctx.headers, **kwargs)
    if not resp.ok:
        if with_steps:
            return None
        raise SystemExit(f"Error polling run {run_id} ({resp.status_code}): {resp.text}")
    return resp.json().get("data") or {}
