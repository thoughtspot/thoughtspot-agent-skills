"""Metric View YAML doc -> CREATE VIEW WITH METRICS DDL + summary (Task 11).

Pure: stdlib + PyYAML only (Genie-vendorable, no HTTP/auth/typer deps). The
MV YAML body is NOT ThoughtSpot TML, so `ts_cli.tml_common.dump_tml_yaml` is
NOT reused here -- this module is the one place a Metric View body is dumped,
via `yaml.safe_dump` directly (databricks-metric-view.md "DDL Syntax").
`sort_keys=False` is required to preserve the key order `mv_emit.build_metric_view`
establishes (version, comment, source, joins, dimensions, measures, filter).
"""
from __future__ import annotations

import yaml

from ts_cli.databricks.mv_emit import to_snake


def build_view_ddl(yaml_doc: dict, *, catalog: str, schema: str, view_name: str) -> str:
    """Wrap an MV YAML doc in the `CREATE OR REPLACE VIEW ... WITH METRICS
    LANGUAGE YAML AS $$ ... $$` DDL (databricks-metric-view.md "DDL Syntax" /
    "Create"). Raises `ValueError` if the dumped YAML body contains a literal
    `$$` -- that substring would terminate the dollar-quoted string early and
    silently truncate/corrupt the DDL, so this is a fail-loud guard rather
    than a best-effort escape.
    """
    body = yaml.safe_dump(yaml_doc, sort_keys=False, default_flow_style=False,
                          width=100000, allow_unicode=True)
    if "$$" in body:
        raise ValueError(
            "MV YAML body contains a literal '$$', which would terminate "
            "the dollar-quoted DDL early -- rewrite the offending "
            "dimension/measure expr to avoid a '$$' substring")
    return (f"CREATE OR REPLACE VIEW {catalog}.{schema}.{view_name}\n"
           f"WITH METRICS LANGUAGE YAML AS $$\n{body}$$")


def default_view_name(model_name: str, source_table: str) -> str:
    """Default snake_case view name: `{model}_{fact}_mv` (matches the
    `dunder_mifflin_sales_mv`-style worked-example naming when model + fact
    combine). Callers (the `build-mv` command, the Genie skill) may override
    this per-invocation.
    """
    return f"{to_snake(model_name)}_{to_snake(source_table)}_mv"


def build_summary(model_name: str, mvs: list[dict]) -> dict:
    """Aggregate per-MV results into the single stdout JSON contract / the
    Unmapped Report source.

    Each `mvs[]` entry is `mv_emit.build_metric_view`'s own return shape
    (`{"yaml_doc", "skipped", "warnings"}`) plus the two fields the caller
    adds once the view is named and written (`view_name`, `file`) --
    `skipped`/`warnings` default to `[]` when absent. `dimensions`,
    `measures`, `filter_applied`, and `source` are all derived from
    `yaml_doc` so callers never have to recompute counts the emitter already
    produced.
    """
    metric_views: list[dict] = []
    skipped: list = []
    warnings: list = []
    for mv in mvs:
        yaml_doc = mv.get("yaml_doc") or {}
        metric_views.append({
            "view_name": mv["view_name"],
            "source": yaml_doc.get("source"),
            "dimensions": len(yaml_doc.get("dimensions") or []),
            "measures": len(yaml_doc.get("measures") or []),
            "filter_applied": "filter" in yaml_doc,
            "file": mv["file"],
        })
        skipped.extend(mv.get("skipped") or [])
        warnings.extend(mv.get("warnings") or [])
    return {"model_name": model_name, "metric_views": metric_views,
            "skipped": skipped, "warnings": warnings}
