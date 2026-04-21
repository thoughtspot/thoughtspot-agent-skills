# Credential and Secret Handling

## Platform requirement

This project's credential storage is **macOS only**. The `security` command (macOS Keychain)
and `~/.zshenv` are used throughout. Windows and Linux are not currently supported for
interactive credential management. If adding Windows support in future, use the `keyring`
Python library — it wraps macOS Keychain, Windows Credential Manager, and Linux secret-service
behind one API and is already a viable replacement for `security` calls in skill code.

## Where credentials go

| Credential type | Storage location | Never in |
|---|---|---|
| Tokens, passwords, secret keys | macOS Keychain via `security add-generic-password` | Files, env files, git, conversation |
| Env var for the credential | `~/.zshenv` export line only | `.env`, `.bash_profile` (unless agreed), any tracked file |
| Profile metadata (URL, username, auth method name) | `~/.claude/thoughtspot-profiles.json` | Git — this file is gitignored |
| Snowflake key files (`.p8`, `.pem`) | Outside the repo; referenced by path | Git — `.gitignore` covers `*.p8`, `*.pem`, `*.key` |

## Rules for skill authors

**Never accept a credential in the Claude Code conversation.** Instructions to the user to
enter a token, password, or key must always direct them to run the command in their own
terminal. The credential must not appear in any message the user sends or Claude echoes.
See `agents/claude/ts-setup-profile/SKILL.md` (Add section) for the exact pattern.

**Never write credentials to files inside the repo.** Even to `/tmp/` — tokens cached to
`/tmp/` must be cleaned up at skill end and must not be inside the working directory.

**Never `print()` or `echo` a credential value** for debugging. Use presence-check only:
```python
# Good — confirms entry exists, never reveals the value
result = subprocess.run(["security", "find-generic-password", "-s", svc, "-a", user], ...)
print("Found." if result.returncode == 0 else "Not found.")

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

Full pattern: `agents/claude/ts-setup-profile/SKILL.md` (Derive names section).

## Token cache

The `ts` CLI caches tokens at `/tmp/ts_token_<slug>.txt` (permissions 0600). Skills do not
manage this file — the CLI handles expiry and refresh. Do not reference or read this path
from skill code. If a token needs to be invalidated, use `ts auth logout --profile <name>`.

## Adding a new external service

If a new skill adds credentials for a service other than ThoughtSpot or Snowflake:
1. Follow the same Keychain + env var pattern (see ts-setup-profile for reference)
2. Add a new `<service>-profiles.json` to `.gitignore` before writing any code
3. Use a distinct Keychain service name prefix to avoid collisions
4. Document the credential type and env var convention in the skill's SKILL.md
