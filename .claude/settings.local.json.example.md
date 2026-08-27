# `settings.local.json` — how to use it

> Moved out of `.claude/settings.local.json.example` on 2026-08-26 (audit finding
> 18.2). That file is consumed by `cp` into a **strict-JSON** settings file, and the
> ~30 lines of `//` prose below made it fail `json.load` with
> `Extra data: line 12` — so a contributor following step 1 got a Settings Error on
> next launch and lost their local settings file until they hand-stripped the
> comments. The example is now valid JSON; the guidance lives here.

── How to use this file ──────────────────────────────────────────────────────

1. Copy this file: cp .claude/settings.local.json.example .claude/settings.local.json
2. Add your personal bash allowlists and WebFetch domains — the vendor
   docs hosts the audit sweep needs are already in the **committed**
   `.claude/settings.json` (finding 18.1), so put only instance-specific hosts here
3. NEVER commit settings.local.json — it is gitignored

── Model ─────────────────────────────────────────────────────────────────────

settings.json intentionally carries NO model pin — the session inherits your
account's default model, and .claude/rules/model-routing.md says it should stay
that way: planning and QA happen interactively, so the session default should be
the strong tier. Override here only to downgrade for simple authoring sessions,
and always use a tier alias, never a generation-specific model ID (those go
stale fast — see the model-routing.md angle-18 note on why a hardcoded ID is a
harness-currency risk):

"model": "sonnet"

── Common additions ──────────────────────────────────────────────────────────

ThoughtSpot instance domains (add yours to allow WebFetch calls):
"WebFetch(domain:yourorg.thoughtspot.cloud)"

Snowflake CLI and connector tools:
"Bash(snow:*)"

── Hook events ───────────────────────────────────────────────────────────────

Add personal hooks here (not in shared settings.json):

"hooks": {
"Notification": [{ "hooks": [{ "type": "command", "command": "..." }] }]
}
