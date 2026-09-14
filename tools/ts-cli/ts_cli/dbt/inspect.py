"""Read a compiled dbt manifest and answer the questions the skill used to ask by hand.

`ts-convert-from-dbt` Step 8-pre used to have the LLM download a manifest and
write a 31-line loop over `nodes` to decide Path N vs Path Y. That is a
mechanical transformation over a JSON file — `.claude/rules/repo-audit.md`
angle 11's definition of work that belongs in Python — and doing it in the
model made the decision unreproducible and the fetch un-cacheable.

Everything here is pure: a manifest dict in, a report dict out. The `ts_join_*`
scan deliberately uses the SAME predicates as
:func:`ts_cli.dbt.manifest.build_model_tml_from_manifest` (resource_type
`test`, `test_metadata.name == "relationships"`, at least one `ts_join_` key
under `config.meta`, and `node_paths.join_test_in_path` for the directory), so
`inspect` cannot recommend Path Y for a join graph `build-model` will not then
read. Both call into `node_paths` rather than carrying their own copy — they
drifted on exactly that point before (open-items #18).
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

from .node_paths import model_in_path, join_test_in_path

_REF_RE = re.compile(r"""ref\(['"]?([^'")]+)['"]?\)""")


def _ref_name(raw: str) -> str:
    """Model name out of a dbt `ref('x')` expression, possibly wrapped in a macro."""
    m = _REF_RE.search(raw or "")
    return m.group(1) if m else ""


def model_nodes_in_path(manifest: dict, model_path: str) -> list:
    """Model nodes whose directory is exactly `model_path`, sorted by name.

    Exact directory match, not a substring: `models/staging/barbershop` must not
    pull in `models/staging/barbershop_archive`. (The test scan resolves its
    directory differently — see `ts_join_tests`.)
    """
    out = [
        node for node in manifest.get("nodes", {}).values()
        if model_in_path(node, model_path)
    ]
    return sorted(out, key=lambda n: n.get("name", ""))


def group_manifest_models(manifest: dict, *, use_alias: bool = True) -> list:
    """Group every model node by parent directory, as `--model-tables` JSON.

    Returns `[{"model_name", "model_path", "tables": [<UPPERCASE>, …]}]`.

    `use_alias` (the default) emits `alias or name`, which is the name dbt
    actually materialises in the warehouse and therefore the only name
    ThoughtSpot's `generate-tml` matches. Emitting `name` for a project that
    sets `alias:` (or a project-level `+alias` / `generate_alias_name` macro)
    fails the whole call with a 400 naming tables that "do not exist" —
    open-items #15, live 2026-09-09. `--no-alias` restores the old behaviour
    for a project whose aliases are wrong in the manifest.
    """
    groups: dict = defaultdict(list)
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "model":
            continue
        dir_path = os.path.dirname(node.get("original_file_path", ""))
        name = (node.get("alias") or node["name"]) if use_alias else node["name"]
        groups[dir_path].append(name.upper())

    return [
        {
            "model_name": os.path.basename(dir_path),
            "model_path": dir_path,
            "tables": sorted(tables),
        }
        for dir_path, tables in sorted(groups.items())
    ]


def ts_join_tests(manifest: dict, model_path: str) -> list:
    """Every `relationships` test in `model_path` carrying `ts_join_*` meta.

    A test is placed by the model it is **attached to**, not by the schema.yml
    that declares it — see `node_paths.join_test_in_path`. The two can be different
    directories, and matching on the declaring file made this return zero joins
    for any project whose schema.yml sits above its models (open-items #18),
    including every project `ts dbt-export build` generates.

    `build_model_tml_from_manifest` calls the same predicate — the two must
    agree or `inspect` would promise a join graph `build-model` then fails to
    find.
    """
    out = []
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "test":
            continue
        if not join_test_in_path(manifest, node, model_path):
            continue
        tm = node.get("test_metadata") or {}
        if tm.get("name") != "relationships":
            continue
        meta = (node.get("config") or {}).get("meta") or {}
        if not any(k.startswith("ts_join_") for k in meta):
            continue
        kwargs = tm.get("kwargs") or {}
        column = kwargs.get("column_name", "")
        out.append({
            "from": _ref_name(kwargs.get("model", "")) or "(unknown)",
            "to": _ref_name(kwargs.get("to", "")) or "(unknown)",
            "column": column,
            "field": kwargs.get("field", column),
            "meta": {k: v for k, v in sorted(meta.items()) if k.startswith("ts_join_")},
        })
    return sorted(out, key=lambda t: (t["from"], t["to"], t["column"]))


def rls_models(manifest: dict, model_path: str) -> list:
    """Models in `model_path` carrying model-level `ts_rls_rules`.

    Their presence is on its own a Path Y signal: ThoughtSpot's server-side
    `generate-tml` does not read this tag, so a Path N import drops the rules
    silently.
    """
    return sorted(
        node["name"]
        for node in model_nodes_in_path(manifest, model_path)
        if ((node.get("config") or {}).get("meta") or {}).get("ts_rls_rules")
    )


def metricflow_metrics(manifest: dict, model_path: str) -> list:
    """MetricFlow metrics whose semantic models are all in `model_path`.

    Delegates the scoping to `dbt_metricflow.metrics_in_scope` rather than
    re-deriving it: that function already resolves the `metric.*` -> semantic
    model edges transitively, which dbt Cloud manifests need and a naive
    one-hop check gets wrong for every ratio and derived metric.
    """
    from ts_cli.dbt_metricflow import metrics_in_scope, semantic_models_in_scope

    sm_scope = semantic_models_in_scope(manifest, model_path)
    if not sm_scope:
        return []
    return sorted(
        (
            {
                "name": mt.get("name", ""),
                "type": mt.get("type", ""),
                "label": mt.get("label", ""),
            }
            for mt in metrics_in_scope(manifest, sm_scope)
        ),
        key=lambda m: m["name"],
    )


def path_n_model_count(joins: list) -> int:
    """How many Models Path N would emit: one per FK-SOURCE table.

    A table with outgoing `ts_join_*` edges roots a Model holding itself plus
    its DIRECT (one-hop) targets; shared dimensions are duplicated into every
    Model that references them.

    Directly observed 2026-09-10 and it corrects open-items #11: barbershop's 7
    models are a SINGLE FK-connected component (APPOINTMENTS and PRODUCT_SALES
    both reach BARBERS and CUSTOMERS) yet split into 3 Models, so the split is
    not by connected component. The fact-table rule also retro-explains the
    2026-09-04 observation the old theory was invented for -- `models/marts/core`
    has one FK source (`fct_orders`) and returned one Model.
    """
    return len({t["from"] for t in joins})


def _path_reasons(joins: list, rls: list, metrics: list) -> list:
    """One line per signal that forced the verdict, so it is auditable."""
    reasons = []
    if joins:
        n = path_n_model_count(joins)
        split = (f"split this directory into {n} Models (one per FK-source "
                 "table, each with its direct targets; shared dimensions "
                 "duplicated across them)") if n > 1 else (
                 "return a single Model (only one FK-source table here)")
        reasons.append(
            f"{len(joins)} ts_join_* relationship test(s) — the author declared an "
            f"explicit join graph. Path N would {split}, and drops ts_formula / "
            "ts_display_name / ts_column_exclude")
    if rls:
        reasons.append(
            f"{len(rls)} model(s) with ts_rls_rules ({', '.join(rls)}) — ThoughtSpot's "
            "server-side sync does not read this tag")
    if metrics:
        reasons.append(
            f"{len(metrics)} MetricFlow metric(s) — only build-model translates them "
            "into Model formulas")
    if not reasons:
        reasons.append(
            "no ts_join_* tests, ts_rls_rules or MetricFlow metrics in this directory — "
            "ThoughtSpot's own generate-tml can unify it")
    return reasons


def inspect_manifest(manifest: dict, model_path: str) -> dict:
    """Everything Step 8-pre needs to choose Path N or Path Y, as one dict.

    `recommended_path` is **Y** whenever anything in the directory can only
    survive the client-side assembly: a `ts_join_*` join graph, model-level
    `ts_rls_rules`, or MetricFlow metrics. Otherwise **N** — let ThoughtSpot's
    own generator do it. `reasons` names each signal that forced the verdict so
    the recommendation is auditable rather than a bare letter.
    """
    models = model_nodes_in_path(manifest, model_path)
    joins = ts_join_tests(manifest, model_path)
    rls = rls_models(manifest, model_path)
    metrics = metricflow_metrics(manifest, model_path)

    reasons = _path_reasons(joins, rls, metrics)

    return {
        "model_path": model_path,
        "models": [
            {
                "name": n.get("name", ""),
                "alias": n.get("alias") or n.get("name", ""),
                "table": (n.get("alias") or n.get("name", "")).upper(),
                "database": n.get("database") or "",
                "schema": n.get("schema") or "",
            }
            for n in models
        ],
        "ts_join_tests": joins,
        "rls_models": rls,
        "metricflow_metrics": metrics,
        "recommended_path": "Y" if (joins or rls or metrics) else "N",
        # Reported so the caller can say "Path N gives you 3 Models, Path Y
        # gives you 1" rather than leaving the user to find out after import.
        "path_n_model_count": path_n_model_count(joins) or (1 if models else 0),
        "reasons": reasons,
    }
