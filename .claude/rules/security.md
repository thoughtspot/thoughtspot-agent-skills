# Credential and Secret Handling

## Platform support

This project supports **macOS, Windows, and Linux** for credential management.

| Platform | Credential store | Shell profile |
|---|---|---|
| macOS | Keychain (`security` CLI or `keyring`) | `~/.zshenv` |
| Windows | Windows Credential Manager (`keyring`) | PowerShell `$PROFILE` or permanent env var via `SetEnvironmentVariable` |
| Linux | Secret Service / KWallet (`keyring` + `secretstorage`) | `~/.zshenv` or `~/.bashrc` |

The `keyring` Python library (`pip install keyring`) is the cross-platform abstraction used by
`client.py`. On macOS it delegates to Keychain and is backward-compatible with credentials
stored via the `security` CLI. On Windows it delegates to Windows Credential Manager. On Linux
it delegates to the D-Bus Secret Service (install `pip install secretstorage` as a backend).

Skills still show the native `security` command for macOS users (more ergonomic), and `keyring`
Python one-liners for Windows and Linux users. Both work with `client.py`'s fallback logic.

## Where credentials go

| Credential type | Storage location | Never in |
|---|---|---|
| Tokens, passwords, secret keys | OS credential store: macOS Keychain (`security`), Windows Credential Manager (`keyring`), Linux Secret Service (`keyring`) | Files, env files, git, conversation |
| Env var for the credential | `~/.zshenv` (macOS/Linux) or permanent user env var via PowerShell (Windows — optional if `keyring` fallback suffices) | `.env`, `.bash_profile` (unless agreed), any tracked file |
| Profile metadata (URL, username, auth method name) | `~/.claude/thoughtspot-profiles.json` | Git — this file is gitignored |
| Snowflake key files (`.p8`, `.pem`) | Outside the repo; referenced by path | Git — `.gitignore` covers `*.p8`, `*.pem`, `*.key` |

## Rules for skill authors

**Never accept a credential in the Claude Code conversation.** Instructions to the user to
enter a token, password, or key must always direct them to run the command in their own
terminal. The credential must not appear in any message the user sends or Claude echoes.
See `agents/claude/ts-profile-thoughtspot/SKILL.md` (Add section) for the exact pattern.

**Never write credentials to files inside the repo.** Even to the OS temp directory — tokens
cached there must be cleaned up at skill end and must not be inside the working directory.

**Never `print()` or `echo` a credential value** for debugging. Use presence-check only:
```python
# Good — confirms entry exists, never reveals the value (macOS)
result = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", user], ...)
print("Found." if result.returncode == 0 else "Not found.")

# Good — cross-platform presence check
import keyring
stored = keyring.get_password(svc, user)
print("Found." if stored else "Not found.")

# Bad — reveals the credential
result = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", user, "-w"], ...)
print(result.stdout)  # never do this
```

**Use `ts auth` for ThoughtSpot API calls.** The CLI handles token caching and Keychain
access — skill code never needs to read, store, or pass credentials directly. If you find
yourself constructing an `Authorization: Bearer` header in skill code, stop and use the CLI.

## Env var naming convention

Derived from the profile slug (lowercase profile name, non-alphanumeric → hyphens):

```
THOUGHTSPOT_TOKEN_{SLUG}       ← token auth
THOUGHTSPOT_PASSWORD_{SLUG}    ← password auth
THOUGHTSPOT_SECRET_KEY_{SLUG}  ← secret key auth
```

Example: profile name `"My Staging"` → slug `my-staging` → env var `THOUGHTSPOT_TOKEN_MY_STAGING`.

Full pattern: `agents/claude/ts-profile-thoughtspot/SKILL.md` (Derive names section).

## Token cache

The `ts` CLI caches tokens in the OS temp directory (`tempfile.gettempdir()/ts_token_<slug>.txt`,
permissions 0600 on POSIX). Skills do not manage this file — the CLI handles expiry and
refresh. Do not reference or read this path from skill code. If a token needs to be
invalidated, use `ts auth logout --profile <name>`.

## Adding a new external service

If a new skill adds credentials for a service other than ThoughtSpot or Snowflake:
1. Follow the same OS credential store + env var pattern (see ts-profile-thoughtspot for reference)
2. Add a new `<service>-profiles.json` to `.gitignore` before writing any code
3. Use a distinct credential service name prefix to avoid collisions (e.g. `"databricks-{slug}"`)
4. Document the credential type, env var convention, and platform-specific commands in the skill's SKILL.md
