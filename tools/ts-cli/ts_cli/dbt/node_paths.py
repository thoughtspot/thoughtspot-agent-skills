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
