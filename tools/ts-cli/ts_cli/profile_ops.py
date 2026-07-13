"""Deterministic profile substrate — slug derivation, env-var naming, keychain
command generation, and zshenv management.

Pure functions only. No I/O, no network, no credential values.

Consolidates logic previously duplicated across the profile skills
(ts-profile-thoughtspot, ts-profile-snowflake, ts-profile-databricks,
ts-profile-tableau) and two Python client modules (`client.py::_slugify`,
`tableau/client.py::_slugify_tableau`). Those callers now delegate to
`slugify()` here — see BL-084.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Slug derivation
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Derive a profile slug: lowercase, non-alphanumeric → hyphens, collapsed and stripped."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def slug_to_upper(slug: str) -> str:
    """Convert a slug to UPPER_SNAKE for env var name segments."""
    return slug.upper().replace("-", "_")


# ---------------------------------------------------------------------------
# Env var + keychain service naming
# ---------------------------------------------------------------------------

_ENV_VAR_TEMPLATES: dict[tuple[str, str], str] = {
    ("thoughtspot", "token"): "THOUGHTSPOT_TOKEN_{SLUG}",
    ("thoughtspot", "password"): "THOUGHTSPOT_PASSWORD_{SLUG}",
    ("thoughtspot", "secret_key"): "THOUGHTSPOT_SECRET_KEY_{SLUG}",
    ("snowflake", "password"): "SNOWFLAKE_PASSWORD_{SLUG}",
    ("databricks", "oauth-m2m"): "DATABRICKS_SP_SECRET_{SLUG}",
    ("databricks", "pat"): "DATABRICKS_TOKEN_{SLUG}",
    ("tableau", "password"): "TABLEAU_PASSWORD_{SLUG}",
    ("tableau", "pat"): "TABLEAU_PAT_SECRET_{SLUG}",
}

# Public — for reference by skills/docs that need to enumerate known
# platform/auth_type combinations without reaching into the private template map.
PLATFORM_ENV_VAR_TEMPLATES = dict(_ENV_VAR_TEMPLATES)


def derive_env_var(platform: str, auth_type: str, slug: str) -> str:
    """Return the env var name for a given platform, auth type, and slug."""
    template = _ENV_VAR_TEMPLATES.get((platform, auth_type))
    if template is None:
        raise ValueError(
            f"Unknown platform/auth_type: ({platform!r}, {auth_type!r}). "
            f"Known: {sorted(_ENV_VAR_TEMPLATES)}"
        )
    return template.replace("{SLUG}", slug_to_upper(slug))


def derive_keychain_service(platform: str, slug: str) -> str:
    """Return the keychain service name: '{platform}-{slug}'."""
    return f"{platform}-{slug}"


# ---------------------------------------------------------------------------
# Keychain command generation
# ---------------------------------------------------------------------------


def keychain_store_commands(service: str, account: str) -> dict[str, str]:
    """Return per-platform commands for storing a credential in the OS credential store.

    The VALUE placeholder is literal — the skill fills it in via user interaction,
    never through the CLI.
    """
    return {
        "darwin": (
            f'security add-generic-password \\\n'
            f'    -s "{service}" \\\n'
            f'    -a "{account}" \\\n'
            f'    -w "VALUE" \\\n'
            f'    -U'
        ),
        "linux": (
            f'python3 -c "import keyring; '
            f"keyring.set_password('{service}', '{account}', 'VALUE')\""
        ),
        "windows": (
            f'python -c "import keyring; '
            f"keyring.set_password('{service}', '{account}', 'VALUE')\""
        ),
    }


def keychain_verify_commands(service: str, account: str) -> dict[str, str]:
    """Return per-platform commands for verifying a credential exists (never prints the value)."""
    return {
        "darwin": (
            f'result=$(security find-generic-password -s "{service}" -a "{account}" 2>&1)\n'
            f'echo "$([[ $? -eq 0 ]] && echo "Found." || echo "Not found.")"'
        ),
        "linux": (
            f'python3 -c "import keyring; '
            f"stored = keyring.get_password('{service}', '{account}'); "
            f"print('Stored.' if stored else 'Not found.')\""
        ),
        "windows": (
            f'python -c "import keyring; '
            f"stored = keyring.get_password('{service}', '{account}'); "
            f"print('Stored.' if stored else 'Not found.')\""
        ),
    }


# ---------------------------------------------------------------------------
# ~/.zshenv management
# ---------------------------------------------------------------------------


def zshenv_export_line(env_var: str, service: str, account: str, method: str) -> str:
    """Return the shell export line for ~/.zshenv.

    method is 'darwin' or 'linux' — determines the credential-read mechanism.
    """
    if method == "darwin":
        return (
            f'export {env_var}=$(security find-generic-password'
            f' -s "{service}" -a "{account}" -w 2>/dev/null)'
        )
    return (
        f'export {env_var}=$(python3 -c "import keyring; '
        f"v=keyring.get_password('{service}', '{account}'); "
        f'print(v or \'\', end=\'\')" 2>/dev/null)'
    )


def windows_env_commands(env_var: str, service: str, account: str) -> str:
    """Return the PowerShell snippet for persisting an env var on Windows."""
    return (
        f"$val = python -c \"import keyring; "
        f"v=keyring.get_password('{service}', '{account}'); "
        f"print(v or '', end='')\"\n"
        f"[System.Environment]::SetEnvironmentVariable('{env_var}', $val, 'User')"
    )


def upsert_zshenv(content: str, env_var: str, new_line: str) -> str:
    """Return updated ~/.zshenv content with the export line replaced or appended."""
    lines = content.splitlines(keepends=True)
    prefix = f"export {env_var}="
    replaced = False
    result = []
    for line in lines:
        if line.lstrip().startswith(prefix):
            result.append(new_line + "\n")
            replaced = True
        else:
            result.append(line)
    if not replaced:
        text = "".join(result)
        if text and not text.endswith("\n\n"):
            if not text.endswith("\n"):
                text += "\n"
            text += "\n"
        text += new_line + "\n"
        return text
    return "".join(result)


def remove_zshenv_line(content: str, env_var: str) -> str:
    """Return ~/.zshenv content with the export line for env_var removed."""
    prefix = f"export {env_var}="
    lines = content.splitlines(keepends=True)
    result = [line for line in lines if not line.lstrip().startswith(prefix)]
    text = "".join(result)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text
