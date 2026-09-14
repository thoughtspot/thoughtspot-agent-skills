"""dbt <-> ThoughtSpot conversion internals.

Pure engine modules for the `ts-convert-from-dbt` / `ts-convert-to-dbt` skills,
split out of `ts_cli/dbt_build_export.py` when that module passed the 1000-line
`check_file_size` gate. Same package convention as `ts_cli/databricks/`,
`ts_cli/tableau/` and `ts_cli/report/`.

- `tags.py`                  ts_* metadata tags <-> TML column properties (both directions)
- `manifest.py`              compiled dbt manifest -> ThoughtSpot Model TML
- `model_from_schema_yml.py` raw schema.yml -> ThoughtSpot Model TML

`dbt_build_export.py` keeps the Case A project scaffolder and re-exports every
public name from these modules, so existing import sites are unchanged.
"""
