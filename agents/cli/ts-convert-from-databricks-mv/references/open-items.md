# Open Items — ts-convert-from-databricks-mv

Tracker for unverified assumptions, API behaviour questions, and deferred work.

---

## #1 — Merge multiple MVs into single ThoughtSpot model — DEFERRED 2026-07-10

When multiple Metric Views represent what was originally one multi-table ThoughtSpot
model (split during to-direction conversion due to MV single-source limitation),
the from-direction skill should support merging them back into a single model.

This requires:
- Detecting related MVs (naming convention, shared dimension tables, user selection)
- Generating one Table TML per unique source table across all MVs
- Generating joins between tables in the model TML
- Deduplicating shared dimension columns

Mirrors the Snowflake SV from-direction merge capability.

**Status:** Deferred — explicitly parked as a Non-Goal in
`docs/superpowers/specs/2026-07-08-dbx-conversion-substrate-design.md` §Goals & Non-Goals:
"Resolving the MV-on-MV merge case (open-items #1) — stays fail-loud, not a supported
transform." No committed target version or BL-NNN filed as of 2026-07-10; revisit if a
merge-back requirement is prioritized in a future phase.
