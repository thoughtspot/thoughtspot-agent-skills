# Mirror sync debt

Acknowledged gaps between canonical CLI/Claude skills and their runtime mirrors.
`check_mirror_sync.py` fails on any UNACKNOWLEDGED gap. Closing a row = syncing the
mirror and bumping its `synced-from` marker.

| Mirror | At (marker) | CLI now | Gap | Owner decision |
|---|---|---|---|---|
| agents/coco-snowsight/ts-convert-to-snowflake-sv/SKILL.md | v1.2.2 | v1.3.0 | SV-to v1.2.3 (minor checklist addition) + v1.2.4 (credential-refresh pointer) + v1.3.0 (Step 9.5C/Step 11 delegate to `ts snowflake diff`/`lint-ddl`, BL-063) | won't sync — v1.3.0 depends on the `ts` CLI (`ts snowflake diff`/`lint-ddl`), which CoCo cannot invoke; sync scheduled for the earlier checklist-only gap |
| agents/coco-snowsight/ts-convert-from-snowflake-sv/SKILL.md | v1.9.0 | v1.13.0 | CLI-only: connection-scoped table search (v1.10.0) + N/F/L connection-identification prompt (v1.11.0/v1.11.1) + Step C3 delegated to `ts snowflake diff` (v1.13.0, BL-063) — all depend on `ts connections list` / `ts snowflake diff` and a local shell | won't sync — CoCo runs in Snowsight (stored procs, no `ts` CLI); no CoCo equivalent applies |
