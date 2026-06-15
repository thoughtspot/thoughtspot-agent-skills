"""
token_refresh.py — Scheduled token refresh for ThoughtSpot profiles in Databricks Secrets.

Designed to run as a scheduled Databricks Job on a ~12-hour interval.
Only password and secret_key profiles are refreshed — bearer_token profiles are
static credentials that cannot be rotated via the auth/token/full endpoint.

Typical Databricks Job configuration:
  - Schedule: every 12 hours
  - Task type: Notebook (or Python script via wheel)
  - Entry point: call refresh_all_profiles(dbutils) from a notebook cell

Usage from a notebook:
    from token_refresh import refresh_all_profiles
    results = refresh_all_profiles(dbutils)
    for profile, status in results.items():
        print(f"{profile}: {status}")
"""

import requests


def refresh_all_profiles(dbutils) -> dict:
    """Refresh ThoughtSpot tokens for all password and secret_key profiles.

    Scans all Databricks Secrets scopes whose names start with "thoughtspot-",
    attempts a fresh token exchange for password/secret_key auth profiles, and
    stores the new token back in the same scope.  Bearer-token profiles are
    skipped — they are static credentials that must be rotated out-of-band.

    Args:
        dbutils: The Databricks dbutils object (passed in from the notebook context).

    Returns:
        dict[str, str] mapping profile name → one of:
            "OK"            — token refreshed and stored successfully
            "SKIPPED"       — bearer_token profile; no refresh needed
            "ERROR: <msg>"  — refresh failed; original token unchanged
    """
    results: dict = {}

    scopes = dbutils.secrets.listScopes()
    thoughtspot_scopes = [s for s in scopes if s.startswith("thoughtspot-")]

    for scope in thoughtspot_scopes:
        profile = scope[len("thoughtspot-"):]

        try:
            auth_method = dbutils.secrets.get(scope, "auth_method")
        except KeyError:
            results[profile] = "ERROR: missing auth_method"
            continue

        if auth_method == "bearer_token":
            results[profile] = "SKIPPED"
            continue

        try:
            base_url = dbutils.secrets.get(scope, "base_url").rstrip("/")
            username = dbutils.secrets.get(scope, "username")

            if auth_method == "password":
                credential = dbutils.secrets.get(scope, "password")
                body = {
                    "username": username,
                    "password": credential,
                    "validity_time_in_sec": 3600,
                }
            elif auth_method == "secret_key":
                credential = dbutils.secrets.get(scope, "secret_key")
                body = {
                    "username": username,
                    "secret_key": credential,
                    "validity_time_in_sec": 3600,
                }
            else:
                results[profile] = f"ERROR: unknown auth_method '{auth_method}'"
                continue

            resp = requests.post(
                f"{base_url}/api/rest/2.0/auth/token/full",
                json=body,
                timeout=30,
            )

            if not resp.ok:
                results[profile] = f"ERROR: HTTP {resp.status_code} from token endpoint"
                continue

            token = resp.json().get("token")
            if not token:
                results[profile] = "ERROR: no token in response"
                continue

            dbutils.secrets.put(scope, "token", token)
            results[profile] = "OK"

        except Exception as e:
            results[profile] = f"ERROR: {e}"

    return results
