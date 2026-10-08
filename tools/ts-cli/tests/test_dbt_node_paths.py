"""Tests for `ts_cli.dbt.node_paths` — which directory a manifest node belongs to.

The regression these guard (open-items #18, found live 2026-09-10): a test node's
`original_file_path` is the schema.yml that DECLARES it, which need not be the
directory of the models it tests. Both manifest readers matched a test by that
path, so a project whose schema.yml sits above its models reported zero joins —
and zero joins silently downgrades a Path-Y project to Path N.

`ts dbt-export build` generates exactly that layout, so this repo could not
correctly inspect a project it had just produced.
"""
from __future__ import annotations

from ts_cli.dbt.inspect import inspect_manifest, model_nodes_in_path, ts_join_tests
from ts_cli.dbt.manifest import build_model_tml_from_manifest
from ts_cli.dbt.node_paths import model_in_path, join_test_in_path, owner_dir


def _model(name, path, project="p"):
    return f"model.{project}.{name}", {
        "resource_type": "model", "name": name, "original_file_path": path,
        "database": "DB", "schema": "SC",
    }


def _join_test(name, attached, from_name, to_name, path, project="p", column="CUSTOMER_ID"):
    node = {
        "resource_type": "test",
        "name": name,
        "original_file_path": path,
        "test_metadata": {
            "name": "relationships",
            "kwargs": {
                "column_name": column,
                "field": column,
                "model": "{{ get_where_subquery(ref('%s')) }}" % from_name,
                "to": "ref('%s')" % to_name,
            },
        },
        "config": {"meta": {"ts_join_name": name, "ts_join_type": "left_outer",
                            "ts_join_cardinality": "many_to_one"}},
    }
    if attached:
        node["attached_node"] = f"model.{project}.{attached}"
    return f"test.{project}.{name}", node


def _manifest(*pairs):
    return {"nodes": dict(pairs)}


# The layout `ts dbt-export build` emits: .sql under models/staging, schema.yml
# one level up at models/. This is the shape that returned zero joins.
PARENT_DIR = _manifest(
    _model("stg_appointments", "models/staging/stg_appointments.sql"),
    _model("stg_customers", "models/staging/stg_customers.sql"),
    _join_test("appointments_to_customers", "stg_appointments",
               "stg_appointments", "stg_customers", "models/schema.yml"),
)

# The hand-authored layout: schema.yml beside the models it documents.
CO_LOCATED = _manifest(
    _model("appointments", "models/staging/barbershop/appointments.sql"),
    _model("customers", "models/staging/barbershop/customers.sql"),
    _join_test("appointments_to_customers", "appointments",
               "appointments", "customers",
               "models/staging/barbershop/schema.yml"),
)


class TestModelInPath:
    def test_exact_dirname_matches(self):
        _, node = _model("a", "models/staging/a.sql")
        assert model_in_path(node, "models/staging")

    def test_sibling_sharing_a_prefix_is_excluded(self):
        """`models/staging` must not absorb `models/staging_archive` — the
        reason this is an exact dirname and not a substring."""
        _, node = _model("old", "models/staging_archive/old.sql")
        assert not model_in_path(node, "models/staging")

    def test_a_parent_directory_does_not_match(self):
        _, node = _model("a", "models/staging/a.sql")
        assert not model_in_path(node, "models")

    def test_a_test_node_is_never_a_model(self):
        _, node = _join_test("t", "a", "a", "b", "models/schema.yml")
        assert not model_in_path(node, "models")


class TestTestInPath:
    def test_attached_model_decides_not_the_declaring_file(self):
        """THE #18 regression: the test lives in models/schema.yml but is
        attached to a model in models/staging, so it belongs to models/staging."""
        node = PARENT_DIR["nodes"]["test.p.appointments_to_customers"]
        assert join_test_in_path(PARENT_DIR, node, "models/staging")

    def test_the_declaring_file_directory_does_not_match(self):
        """The corollary — before the fix this was the ONLY thing that matched,
        which is why neither --model-path value gave a correct answer."""
        node = PARENT_DIR["nodes"]["test.p.appointments_to_customers"]
        assert not join_test_in_path(PARENT_DIR, node, "models")

    def test_co_located_layout_still_matches(self):
        node = CO_LOCATED["nodes"]["test.p.appointments_to_customers"]
        assert join_test_in_path(CO_LOCATED, node, "models/staging/barbershop")

    def test_owner_dir_prefers_the_attached_model(self):
        node = PARENT_DIR["nodes"]["test.p.appointments_to_customers"]
        assert owner_dir(PARENT_DIR, node) == "models/staging"

    def test_falls_back_to_substring_when_attached_node_is_absent(self):
        """An older manifest carries no `attached_node`. Falling back to the
        previous behaviour keeps it working rather than reporting zero joins."""
        key, node = _join_test("t", None, "a", "b", "models/staging/schema.yml")
        m = _manifest(_model("a", "models/staging/a.sql"), (key, node))
        assert join_test_in_path(m, node, "models/staging")

    def test_a_dangling_attached_node_falls_back_too(self):
        key, node = _join_test("t", "gone", "a", "b", "models/staging/schema.yml")
        m = _manifest(_model("a", "models/staging/a.sql"), (key, node))
        assert join_test_in_path(m, node, "models/staging")

    def test_cross_directory_join_belongs_only_to_the_from_side(self):
        """A join from marts to staging is the marts directory's join. Reporting
        it under both would hand `build-model` a join whose other table is not
        in the Model it is assembling."""
        m = _manifest(
            _model("fct", "models/marts/fct.sql"),
            _model("dim", "models/staging/dim.sql"),
            _join_test("fct_to_dim", "fct", "fct", "dim", "models/schema.yml"),
        )
        node = m["nodes"]["test.p.fct_to_dim"]
        assert join_test_in_path(m, node, "models/marts")
        assert not join_test_in_path(m, node, "models/staging")


class TestReadersAgree:
    """`inspect` must never promise a join graph `build-model` will not find."""

    def test_inspect_finds_the_join_in_a_parent_dir_layout(self):
        assert len(ts_join_tests(PARENT_DIR, "models/staging")) == 1
        assert len(model_nodes_in_path(PARENT_DIR, "models/staging")) == 2

    def test_inspect_recommends_path_y_for_the_generated_layout(self):
        """Before the fix this produced no reasons at all and returned N —
        dropping ts_formula / ts_display_name / ts_column_exclude silently."""
        rep = inspect_manifest(PARENT_DIR, "models/staging")
        assert rep["recommended_path"] == "Y"
        assert any("ts_join_" in r for r in rep["reasons"])

    def test_build_model_finds_the_same_joins(self):
        tml = build_model_tml_from_manifest(PARENT_DIR, {}, "models/staging", "M")
        model = tml.get("model") or tml.get("worksheet") or {}
        built = sum(len(t.get("joins") or []) for t in model.get("model_tables", []))
        assert built == len(ts_join_tests(PARENT_DIR, "models/staging")) == 1

    def test_both_readers_agree_on_the_co_located_layout_too(self):
        path = "models/staging/barbershop"
        tml = build_model_tml_from_manifest(CO_LOCATED, {}, path, "M")
        model = tml.get("model") or tml.get("worksheet") or {}
        built = sum(len(t.get("joins") or []) for t in model.get("model_tables", []))
        assert built == len(ts_join_tests(CO_LOCATED, path)) == 1
