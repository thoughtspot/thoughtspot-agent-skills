"""Which model directory a manifest node belongs to — the one answer both readers use.

`ts dbt inspect` (inspect.py) and `ts dbt build-model` (manifest.py) each scope a
manifest to one `--model-path`. They MUST agree: `inspect` recommending Path Y
for a join graph `build-model` then fails to find is the failure this module
exists to prevent. Before it, the two carried near-identical predicates inline
and drifted anyway — not on the model scan, but on the *test* scan.

The bug that motivated it (`ts-convert-from-dbt` open-items #18, found live
2026-09-10). A model node is located by its own `.sql` file, but a test node's
`original_file_path` is **the schema.yml that declares it**, which need not sit
in the same directory as the models it tests. Both readers matched a test with
`model_path in original_file_path`, so a project whose schema.yml sits ABOVE its
models satisfied neither value of `--model-path`:

    models/staging  ->  7 models, 0 join tests   (schema.yml is not under it)
    models          ->  0 models, 7 join tests   (no .sql files are directly in it)

`ts dbt-export build` generates exactly that layout, so a project this repo
produces could not be inspected correctly. Joins force Path Y, so the miss
silently downgraded such a project to Path N — which drops ts_formula /
ts_display_name / ts_column_exclude. Valid output, wrong result, no diagnostic.

The fix is to stop inferring a test's directory from where it was *written* and
read where it was *attached*: `attached_node` names the model the test is
declared on — the join's `from` side — and dbt populates it regardless of which
file the test lives in. Attributing by the `from` side (rather than by every
entry in `depends_on.nodes`, which also holds the `to` model) keeps a
cross-directory join from being reported under both directories.
"""
from __future__ import annotations

import os
import re


def table_name(node: dict) -> str:
    """The ThoughtSpot Table name for a manifest model node: `alias or name`,
    upper-cased.

    `alias` is the relation dbt materialises, and ThoughtSpot registers the
    Table under that name. Every reader must use this, not `name`: the manifest
    reader used `name` while the schema.yml reader used the alias, so an aliased
    project produced Model TML naming tables that do not exist and RLS keyed to
    the wrong table (PR #506 review, blocker 2). It must agree with
    `model_from_schema_yml._table_name_of`.
    """
    return str(node.get("alias") or node.get("name") or "").upper()


def ref_tables(manifest: dict) -> dict:
    """`{dbt model name: ThoughtSpot Table name}` for every model node, so a
    `ref('name')` can be resolved to the Table it materialises — including a
    join target outside the scoped directory."""
    return {n["name"]: table_name(n) for n in manifest.get("nodes", {}).values()
            if n.get("resource_type") == "model" and n.get("name")}


_REF_ARGS_RE = re.compile(r"""\bref\(\s*(['"][^'"]+['"](?:\s*,\s*['"][^'"]+['"])?)\s*\)""")
_SOURCE_RE = re.compile(r"""\bsource\(\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*\)""")


def join_endpoint(expr: str, ref_to_table: dict) -> "tuple[str | None, str | None, str]":
    """Resolve one end of a `relationships` test: `(dbt model, Table, reason)`.

    The one resolver `build-model` and `inspect` share, so `inspect` can never
    count a join `build-model` then drops (PR #506 review). Accepts `ref('m')`
    and the cross-package `ref('pkg', 'm')`, possibly wrapped in a macro such as
    `get_where_subquery(...)`. On failure Table is None and `reason` says why:

    - `source('raw', 't')` — a dbt source, not a model; ThoughtSpot's dbt
      integration imports models only (ts-convert-from-dbt open-items #3), so
      there is no Table to join to;
    - a `ref()` to a model not in this manifest;
    - anything else.
    """
    expr = expr or ""
    m = _REF_ARGS_RE.search(expr)
    if m:
        model = re.findall(r"""['"]([^'"]+)['"]""", m.group(1))[-1]
        table = ref_to_table.get(model)
        if table:
            return model, table, ""
        return model, None, f"ref('{model}') is not a model in this manifest"
    sm = _SOURCE_RE.search(expr)
    if sm:
        return None, None, (f"source('{sm.group(1)}', '{sm.group(2)}') is a dbt source, not a "
                            "model — ThoughtSpot imports dbt models only, so there is no Table "
                            "to join to")
    return None, None, f"unrecognised relationships target {expr.strip()!r}"


def _ts_join_test_parts(manifest: dict, node: dict, model_path: str) -> "tuple[dict, dict] | None":
    """`(kwargs, meta)` when `node` is a relationships test in `model_path` that
    carries `ts_join_*` meta — the author's declaration of a ThoughtSpot join."""
    if node.get("resource_type") != "test" or not join_test_in_path(manifest, node, model_path):
        return None
    tm = node.get("test_metadata") or {}
    meta = (node.get("config") or {}).get("meta") or {}
    if tm.get("name") != "relationships" or not any(k.startswith("ts_join_") for k in meta):
        return None
    return tm.get("kwargs") or {}, meta


def parse_ts_join_test(manifest: dict, node: dict, model_path: str,
                       ref_to_table: dict) -> "dict | None":
    """One `ts_join_*` relationships test in `model_path`, parsed — or None for
    any other node. The ONE parser `inspect` and `build-model` both call, so they
    cannot disagree about which tests become joins (PR #506 review).

    Returns ``{from, to, from_table, to_table, column, field, meta, test,
    reason}``; ``reason`` is empty when both ends resolve to a model Table.
    """
    found = _ts_join_test_parts(manifest, node, model_path)
    if found is None:
        return None
    kwargs, meta = found
    column = kwargs.get("column_name", "")
    src, src_table, src_why = join_endpoint(kwargs.get("model", ""), ref_to_table)
    tgt, tgt_table, tgt_why = join_endpoint(kwargs.get("to", ""), ref_to_table)
    return {
        "from": src or "(unknown)", "to": tgt or kwargs.get("to", "") or "(unknown)",
        "from_table": src_table, "to_table": tgt_table,
        "column": column, "field": kwargs.get("field", column),
        "meta": {k: v for k, v in sorted(meta.items()) if k.startswith("ts_join_")},
        "test": node.get("name") or node.get("unique_id", ""),
        "reason": "" if src_table and tgt_table else (src_why or tgt_why),
    }


def node_dir(node: dict) -> str:
    """Directory of a node's own source file."""
    return os.path.dirname(node.get("original_file_path", ""))


def model_in_path(node: dict, model_path: str) -> bool:
    """True if `node` is a model whose directory is EXACTLY `model_path`.

    Exact, not a substring: `models/staging/barbershop` must not pull in the
    sibling `models/staging/barbershop_archive`.
    """
    return (node.get("resource_type") == "model"
            and node_dir(node) == model_path)


def models_by_key(manifest: dict) -> dict:
    """Every model node keyed by its manifest node id (`model.<project>.<name>`)."""
    return {
        key: node
        for key, node in (manifest.get("nodes") or {}).items()
        if node.get("resource_type") == "model"
    }


def owner_dir(manifest: dict, test_node: dict) -> str:
    """Directory of the model a test is attached to, else the test's own file.

    `attached_node` is the model the test is declared on. The fallback to the
    test's own path matters for older manifests (and any node dbt did not
    populate it for), and reproduces the previous behaviour for the co-located
    layout, where the two answers are the same directory anyway.
    """
    attached = test_node.get("attached_node")
    if attached:
        owner = (manifest.get("nodes") or {}).get(attached)
        if owner:
            return node_dir(owner)
    return node_dir(test_node)


def join_test_in_path(manifest: dict, test_node: dict, model_path: str) -> bool:
    """True if `test_node` belongs to `model_path`, by the model it is attached to.

    Falls back to the pre-#18 substring match on the test's own file when
    `attached_node` is absent AND that path is not itself an exact match — so a
    manifest too old to carry `attached_node` keeps working rather than silently
    reporting zero joins.
    """
    attached_dir = owner_dir(manifest, test_node)
    if attached_dir == model_path:
        return True
    if test_node.get("attached_node"):
        return False
    return model_path in test_node.get("original_file_path", "")
