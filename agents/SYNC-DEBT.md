# Mirror sync debt

Acknowledged gaps between canonical CLI/Claude skills and their runtime mirrors.
`check_mirror_sync.py` fails on any UNACKNOWLEDGED gap. Closing a row = syncing the
mirror and bumping its `synced-from` marker.

| Mirror | At (marker) | CLI now | Gap | Owner decision |
|---|---|---|---|---|
| agents/cursor/rules/ts-convert-from-databricks-mv.mdc | v1.0.1 | v1.3.0 | MV v1.1–v1.3 (sql_view path, semi-additive, PT1, pre-import gate) | sync scheduled — BL-017 |
| agents/cursor/rules/ts-convert-from-snowflake-sv.mdc | v1.3.1 | v1.8.0 | SV v1.4–v1.8 (N1, I7, pre-import gate, PT1, name-normalisation, fail-loud parsing) | sync scheduled — BL-017 |
| agents/cursor/rules/ts-convert-from-tableau.mdc | v1.1.2 | v1.9.1 | Tableau v1.2–v1.9 (sets pipeline, function mappings, audit hotfixes) | sync scheduled — BL-017 |
| agents/cursor/rules/ts-convert-to-snowflake-sv.mdc | v1.2.0 | v1.2.3 | SV-to v1.2.1–v1.2.3 (error-010256, checklist additions) | sync scheduled — BL-017 |
| agents/cursor/rules/ts-object-answer-promote.mdc | v1.1.0 | v1.2.0 | answer-promote v1.2 (minor update) | sync scheduled — BL-017 |
| agents/cursor/rules/ts-object-model-coach.mdc | v1.2.0 | v2.3.0 | model-coach v1.3–v2.3 (major behind — full rewrite) | decide: sync or retire cursor mirror — BL-017 |
| agents/cursor/rules/ts-profile-snowflake.mdc | v1.0.0 | v1.0.1 | profile-snowflake v1.0.1 (context line addition) | sync scheduled — BL-017 |
| agents/coco-snowsight/ts-convert-to-snowflake-sv/SKILL.md | v1.2.2 | v1.2.3 | SV-to v1.2.3 (minor checklist addition) | sync scheduled — BL-017 |
