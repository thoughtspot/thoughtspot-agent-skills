---
name: ts-profile-domo
description: Set up and manage Domo connection profiles for the Domo → ThoughtSpot converter. Use when configuring a new Domo instance for dashboard migration, updating credentials, or testing whether an existing profile works. Uses a Domo developer access token, stored in the OS keychain — never in a file or this conversation.
---

# Domo Profile Setup

Manage Domo connection profiles via the `ts profiles` CLI. The token is stored in the OS
credential store (macOS Keychain / Windows Credential Manager / Linux Secret Service) and read at
runtime from an env var with a keychain fallback — never written to a profile file and never
echoed in this conversation.

Ask one question at a time for **dependent** decisions; batch **independent** questions — profile
name and instance URL can be collected together.

**What the profile is for.** `ts_cli/domo/client.py` reads Domo's **internal** endpoints — the
ones the Domo web app itself calls — to enumerate datasets, pages, card metadata and Beast Modes.
That is genuinely useful for *capturing* a bundle, but note the boundary: a card's **analyzer
query** is not exposed by any Domo endpoint a token can reach, so `/ts-convert-from-domo` still
converts from an **offline bundle on disk**, not live. See
[../ts-convert-from-domo/references/open-items.md](../ts-convert-from-domo/references/open-items.md).

---

## Prerequisites

- `ts` CLI installed: `pip install -e tools/ts-cli`
- A Domo **developer access token** for the instance (Domo → Admin → Authentication → Access
  Tokens). This is the credential `client.py` sends as `X-DOMO-Developer-Token`.
- Admin rights on the Domo instance to mint that token.

---

## On Invocation

Ask: **Add, List, Test, or Remove a Domo profile?**

## Add

### Step 1 — Collect profile details (batch)

1. **Profile name** — e.g. `acme-domo`
2. **Instance URL** — e.g. `https://acme.domo.com`

Auth method is always `developer-token`; there is no second option to ask about.

### Step 2 — Save profile and derive credential locations

```bash
ts profiles add \
  --platform domo \
  --name "{PROFILE_NAME}" \
  --auth-type developer-token \
  --field instance={INSTANCE_URL}
```

Parse the JSON output. It contains `env_var` (`DOMO_DEVELOPER_TOKEN_{SLUG}`),
`keychain_service` (`domo-{slug}`), `keychain_account` (`developer-token`),
`keychain_store_commands`, `keychain_verify_commands`, `zshenv_line`, and
`windows_env_commands`.

### Step 3 — Store the token

**Never accept the token in this conversation.**

Show the user the keychain store command for their platform from the `keychain_store_commands`
in the Step 2 output, replacing `VALUE` with `PASTE_TOKEN_HERE`. Tell them to run it in their own
terminal. Then have them add the `zshenv_line` (macOS/Linux) or run the `windows_env_commands`
so the token resolves from the env var without a keychain prompt on every call.

### Step 4 — Verify

```bash
ts domo signin --profile "{PROFILE_NAME}"
```

Makes two authenticated calls — one per endpoint family — and reports which the token
actually reaches (`datasets`, `pages`) — never printing the token. A `FAILED:` entry for both means the token or
instance URL is wrong; a partial result means the token is valid but scoped narrowly, which is
worth telling the user before they rely on it.

## Test

```bash
ts domo signin --profile "{PROFILE_NAME}"
```

## List

```bash
ts profiles list --domo
```

Shows profile names, auth method and instance URLs only — never secrets.

## Remove

```bash
ts profiles remove --platform domo --name "{PROFILE_NAME}"
```

Removes the profile entry. Tell the user the keychain item and env var persist — deleting those
is theirs to do (`security delete-generic-password -s "domo-{slug}" -a developer-token` on
macOS), and removing the `~/.zshenv` export line.

---

## Guardrails

- Never enter the developer token in this conversation — always via the keychain command in the
  user's own terminal.
- The token is resolved lazily at call time and held in memory only.
- **Never pass a secret through `--field`.** `--field` is for non-secret metadata
  (`instance`) only; the token belongs in the OS keychain via Step 3, with only the env-var
  *name* in the profile.

  As of **ts-cli 0.134.0** the CLI refuses a `--field` whose key is a **known**
  credential name (`token`, `password`, `secret`, `pat_secret`, `api_key`,
  `developer_token`, … and anything ending `_token`/`_password`/`_secret`/`_passphrase`),
  all-or-nothing across the whole `--field` set. `list`/`add`/`update` strip those same
  names from their output. See `.claude/rules/security.md`.

  **This is a key-name denylist, not a guarantee about values.** An unlisted key —
  `bearer`, `credential`, `passphrase`, `pw`, `notes`, `t0ken` — still writes cleartext to
  `~/.claude/domo-profiles.json` at mode `0644` and is echoed back by
  `ts profiles list --domo --json`. So the rule remains "never put a secret in
  `--field`", and the refusal is a safety net for the common spellings rather than a
  reason to stop caring which key you use.

  This paragraph previously described the *opposite* — that a `--field token=…` would
  persist in cleartext and be echoed back by `ts profiles list --domo --json`, and that the
  substrate could not guard it. That was true when written and was fixed in #480/#483. It is
  recorded here because a guardrail described as **absent when it exists** misleads in the
  same way as one described as present when it does not: it tells the reader not to rely on a
  protection they have.
- The client requires `https://` and refuses redirects — a redirect target would otherwise be
  handed the token, because urllib replays custom headers onto the new host. Server response
  bodies are never printed (only the status code and a control-character-stripped reason),
  because the body is chosen by whatever host the URL actually reached.
- Instance-URL validation rejects a userinfo `@`, a query, a fragment, a path, and the Unicode
  label separators (U+3002/U+FF0E/U+FF61) that would connect somewhere other than the string
  shown. Hosts are then classified: IP literals including the shorthand forms (`2130706433`,
  `127.1`, `0177.1`), `localhost`/`.local`/`.internal` names, and — best-effort — every address
  the name resolves to. Anything loopback/link-local/private is refused.

  **What that is not:** a guarantee. It is a check at validation time, so DNS can change between
  the check and the request, and an unresolvable host is allowed through so the CLI works
  offline. Treat it as defence in depth. The reason this is spelled out rather than summarised
  as "refuses internal hosts" is that an earlier version of this bullet claimed exactly that
  while classifying only canonical IP literals — `localhost` and four spellings of loopback went
  straight through. A guardrail described more strongly than it behaves stops the next reader
  looking.

---

## Changelog

| Version | Date | Summary |
|---|---|---|
| 1.0.0 | 2026-08-26 | Initial release. `domo` added as a platform to `ts profiles add/list/update/remove/sync-env` (developer-token auth, `DOMO_DEVELOPER_TOKEN_{SLUG}` env var, `domo-{slug}` keychain service); `ts domo signin` verifies a profile without printing the token. |
