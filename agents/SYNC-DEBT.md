# Mirror sync debt

Acknowledged gaps between canonical CLI/Claude skills and their runtime mirrors.
`check_mirror_sync.py` fails on any UNACKNOWLEDGED gap. Closing a row = syncing the
mirror and bumping its `synced-from` marker.

| Mirror | At (marker) | CLI now | Gap | Owner decision |
|---|---|---|---|---|
| agents/coco-snowsight/ts-convert-to-snowflake-sv/SKILL.md | v1.2.2 | v1.2.3 | SV-to v1.2.3 (minor checklist addition) | sync scheduled |
| agents/coco-snowsight/ts-convert-from-snowflake-sv/SKILL.md | v1.9.0 | v1.11.1 | CLI-only: connection-scoped table search (v1.10.0) + N/F/L connection-identification prompt (v1.11.0/v1.11.1) — all depend on `ts connections list` and a local shell | won't sync — CoCo runs in Snowsight (stored procs, no `ts` CLI); no CoCo equivalent applies |
