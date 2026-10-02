"""Tests for `ts dbt inspect` and its pure engine `ts_cli.dbt.inspect`.

The Path N / Path Y verdict is the whole point: choosing N when the directory
holds a `ts_join_*` graph, `ts_rls_rules` or MetricFlow metrics silently
produces several Models instead of one, or drops row-level security. So the
scan predicates are pinned here AND asserted to agree with the reader that
actually consumes them (`build_model_tml_from_manifest`) — if the two drift,
`inspect` promises a join graph `build-model` will not find.
"""
from __future__ import annotations

import json

import ts_cli.dbt.cloud_api as cloud_api_mod
from ts_cli.cli import app
from ts_cli.dbt.inspect import (
    group_manifest_models,
    inspect_manifest,
    model_nodes_in_path,
    ts_join_tests,
)

from runners import msg_runner, runner  # noqa: E402

PATH = "models/staging/barbershop"


def _model(name, path=PATH, alias=None, meta=None):
    node = {
        "resource_type": "model", "name": name,
        "original_file_path": f"{path}/{name}.sql",
        "database": "DL_TEST", "schema": "dbt",
    }
    if alias:
        node["alias"] = alias
    if meta:
        node["config"] = {"meta": meta}
    return node


def _rel_test(src, tgt, column, meta, path=PATH):
    return {
        "resource_type": "test",
        "original_file_path": f"{path}/schema.yml",
        "test_metadata": {
            "name": "relationships",
            "kwargs": {
                "model": "{{ get_where_subquery(ref('%s')) }}" % src,
                "to": "ref('%s')" % tgt,
                "column_name": column,
                "field": "ID",
            },
        },
        "config": {"meta": meta},
    }


class TestModelNodesInPath:
    def test_exact_directory_match_only(self):
        """A substring match would pull `barbershop_archive` into `barbershop`
        and generate a Model spanning two unrelated directories."""
        manifest = {"nodes": {
            "a": _model("barbers"),
            "b": _model("old", path=f"{PATH}_archive"),
            "c": _model("deep", path=f"{PATH}/nested"),
        }}
        assert [n["name"] for n in model_nodes_in_path(manifest, PATH)] == ["barbers"]

    def test_empty_manifest(self):
        assert model_nodes_in_path({}, PATH) == []


class TestGroupManifestModels:
    def test_alias_is_the_default_and_no_alias_restores_the_file_name(self):
        manifest = {"nodes": {"a": _model("stg_appointments", alias="appointments")}}
        assert group_manifest_models(manifest)[0]["tables"] == ["APPOINTMENTS"]
        assert group_manifest_models(manifest, use_alias=False)[0]["tables"] == \
            ["STG_APPOINTMENTS"]

    def test_models_without_an_alias_are_unaffected(self):
        manifest = {"nodes": {"a": _model("barbers")}}
        assert group_manifest_models(manifest)[0]["tables"] == ["BARBERS"]

    def test_grouped_by_directory_and_sorted(self):
        manifest = {"nodes": {
            "a": _model("zeta"), "b": _model("alpha"),
            "c": _model("other", path="models/marts/core"),
        }}
        groups = group_manifest_models(manifest)
        assert [g["model_path"] for g in groups] == ["models/marts/core", PATH]
        assert groups[1]["tables"] == ["ALPHA", "ZETA"]
        assert groups[1]["model_name"] == "barbershop"

    def test_non_model_nodes_are_skipped(self):
        manifest = {"nodes": {
            "a": _model("barbers"),
            "t": _rel_test("barbers", "shops", "SHOP_ID", {"ts_join_name": "x"}),
        }}
        assert group_manifest_models(manifest)[0]["tables"] == ["BARBERS"]


class TestTsJoinTests:
    _META = {"ts_join_name": "appt_to_barber", "ts_join_type": "left_outer",
             "ts_join_cardinality": "many_to_one"}

    def test_extracts_endpoints_and_meta(self):
        manifest = {"nodes": {
            "m": _model("appointments"),
            "t": _rel_test("appointments", "barbers", "BARBER_ID", self._META),
        }}
        [join] = ts_join_tests(manifest, PATH)
        assert (join["from"], join["to"], join["column"]) == \
            ("appointments", "barbers", "BARBER_ID")
        assert join["field"] == "ID"
        assert join["meta"] == self._META

    def test_a_relationships_test_without_ts_join_meta_is_ignored(self):
        """A plain dbt referential-integrity test is not a ThoughtSpot join
        declaration; treating it as one invents joins the author never asked for."""
        manifest = {"nodes": {
            "t": _rel_test("appointments", "barbers", "BARBER_ID", {"severity": "warn"})}}
        assert ts_join_tests(manifest, PATH) == []

    def test_a_non_relationships_test_is_ignored(self):
        node = _rel_test("appointments", "barbers", "BARBER_ID", {"ts_join_name": "x"})
        node["test_metadata"]["name"] = "not_null"
        assert ts_join_tests({"nodes": {"t": node}}, PATH) == []

    def test_tests_outside_the_path_are_ignored(self):
        node = _rel_test("a", "b", "C", {"ts_join_name": "x"}, path="models/other")
        assert ts_join_tests({"nodes": {"t": node}}, PATH) == []

    def test_agrees_with_the_reader_that_consumes_it(self):
        """inspect and build_model_tml_from_manifest must see the same joins.
        If inspect says Path Y and build-model finds nothing, the run produces
        a Model with no join graph and nothing reports why."""
        from ts_cli.dbt.manifest import build_model_tml_from_manifest

        manifest = {"nodes": {
            "m1": _model("appointments"),
            "m2": _model("barbers"),
            "t": _rel_test("appointments", "barbers", "BARBER_ID", self._META),
        }}
        assert len(ts_join_tests(manifest, PATH)) == 1
        tml = build_model_tml_from_manifest(manifest, {}, PATH, "M", metrics=False)
        joins = [j for mt in tml["model"]["model_tables"] for j in mt.get("joins") or []]
        assert len(joins) == 1 and joins[0]["name"] == "appt_to_barber"


class TestRecommendedPath:
    def test_plain_directory_recommends_n(self):
        manifest = {"nodes": {"a": _model("barbers"), "b": _model("shops")}}
        report = inspect_manifest(manifest, PATH)
        assert report["recommended_path"] == "N"
        assert "generate-tml can unify it" in " ".join(report["reasons"])

    def test_ts_join_tests_force_y(self):
        manifest = {"nodes": {
            "a": _model("appointments"), "b": _model("barbers"),
            "t": _rel_test("appointments", "barbers", "BARBER_ID", {"ts_join_name": "j"}),
        }}
        report = inspect_manifest(manifest, PATH)
        assert report["recommended_path"] == "Y"
        assert "ts_join_*" in " ".join(report["reasons"])

    def test_ts_rls_rules_alone_force_y(self):
        """generate-tml does not read ts_rls_rules, so Path N drops row-level
        security with no error — the reason Path Y is not optional here."""
        manifest = {"nodes": {"a": _model(
            "appointments", meta={"ts_rls_rules": [{"name": "r", "expr": "1=1"}]})}}
        report = inspect_manifest(manifest, PATH)
        assert report["recommended_path"] == "Y"
        assert report["rls_models"] == ["appointments"]
        assert "ts_rls_rules" in " ".join(report["reasons"])

    def test_reasons_name_every_signal(self):
        manifest = {"nodes": {
            "a": _model("appointments", meta={"ts_rls_rules": [{"name": "r", "expr": "x"}]}),
            "b": _model("barbers"),
            "t": _rel_test("appointments", "barbers", "BARBER_ID", {"ts_join_name": "j"}),
        }}
        reasons = " ".join(inspect_manifest(manifest, PATH)["reasons"])
        assert "ts_join_*" in reasons and "ts_rls_rules" in reasons


class TestReportShape:
    def test_models_carry_the_thoughtspot_table_name(self):
        manifest = {"nodes": {"a": _model("stg_appointments", alias="appointments")}}
        [m] = inspect_manifest(manifest, PATH)["models"]
        assert m["name"] == "stg_appointments"
        assert m["alias"] == "appointments"
        assert m["table"] == "APPOINTMENTS"
        assert (m["database"], m["schema"]) == ("DL_TEST", "dbt")

    def test_empty_directory_reports_nothing_rather_than_raising(self):
        report = inspect_manifest({"nodes": {}}, PATH)
        assert report["models"] == [] and report["recommended_path"] == "N"


class TestInspectCommand:
    _MANIFEST = {"nodes": {
        "a": _model("appointments"), "b": _model("barbers"),
        "t": _rel_test("appointments", "barbers", "BARBER_ID",
                       {"ts_join_name": "appt_to_barber"}),
    }}

    def test_manifest_flag_needs_no_profile_token_or_network(self, monkeypatch, tmp_path):
        def _boom(*_a, **_k):
            raise AssertionError("--manifest must not touch the dbt Cloud API")
        monkeypatch.setattr(cloud_api_mod, "_requests",
                            type("M", (), {"get": staticmethod(_boom)})())
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(self._MANIFEST))

        result = runner.invoke(app, ["dbt", "inspect", "--manifest", str(mf),
                                     "--model-path", PATH])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["recommended_path"] == "Y"
        assert payload["manifest"] == str(mf)
        assert len(payload["ts_join_tests"]) == 1

    def test_downloads_and_reports_the_run_id(self, monkeypatch, tmp_path):
        class _R:
            def __init__(self, p): self.ok, self._p, self.status_code = True, p, 200
            def json(self): return self._p

        def get(url, **kw):
            return _R({"data": [{"id": 77}]}) if "artifacts" not in url \
                else _R(self._MANIFEST)

        monkeypatch.setattr(cloud_api_mod, "load_platform_profiles", lambda _p: [
            {"name": "p", "account_id": "1", "project_id": "2", "auth_type": "token"}])
        monkeypatch.setattr(cloud_api_mod, "token_from_keychain",
                            lambda s, profile=None: "tok")
        monkeypatch.setattr(cloud_api_mod, "_requests",
                            type("M", (), {"get": staticmethod(get)})())

        result = runner.invoke(app, ["dbt", "inspect", "--dbt-cloud-profile", "p",
                                     "--model-path", PATH])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["run_id"] == 77

    def test_unknown_path_still_emits_json(self, tmp_path):
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(self._MANIFEST))
        result = runner.invoke(app, ["dbt", "inspect", "--manifest", str(mf),
                                     "--model-path", "models/typo"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["models"] == []

    def test_unknown_path_says_so_on_stderr(self, tmp_path):
        """A silent empty report reads as "this directory has nothing special",
        which is the same answer a typo'd path gives."""
        mf = tmp_path / "manifest.json"
        mf.write_text(json.dumps(self._MANIFEST))
        result = msg_runner.invoke(app, ["dbt", "inspect", "--manifest", str(mf),
                                         "--model-path", "models/typo"])
        assert "No model nodes found" in result.output
        assert "ts dbt list-models" in result.output


class TestPathNModelCount:
    """How many Models Path N produces — one per FK-SOURCE table.

    Directly observed 2026-09-10 on `models/staging/barbershop`: 7 models that
    form a SINGLE FK-connected component (APPOINTMENTS and PRODUCT_SALES both
    reach BARBERS and CUSTOMERS) still split into 3 Models. So the split is not
    by connected component — the earlier reading in open-items #11 — but by
    fact table, each Model holding its source plus that source's DIRECT targets,
    with shared dimensions duplicated. The same rule retro-explains the
    2026-09-04 observation that `models/marts/core` returned one Model.
    """

    @staticmethod
    def _manifest(edges, project="p"):
        """edges: [(from_model, to_model, column)] -> a manifest with those joins."""
        nodes = {}
        for name in {n for e in edges for n in e[:2]}:
            nodes[f"model.{project}.{name}"] = {
                "resource_type": "model", "name": name,
                "original_file_path": f"models/d/{name}.sql",
            }
        for i, (src, tgt, col) in enumerate(edges):
            nodes[f"test.{project}.j{i}"] = {
                "resource_type": "test", "name": f"j{i}",
                "original_file_path": "models/d/schema.yml",
                "attached_node": f"model.{project}.{src}",
                "test_metadata": {"name": "relationships", "kwargs": {
                    "column_name": col, "field": col,
                    "model": "{{ get_where_subquery(ref('%s')) }}" % src,
                    "to": "ref('%s')" % tgt}},
                "config": {"meta": {"ts_join_name": f"{src}_to_{tgt}"}},
            }
        return {"nodes": nodes}

    def test_one_fact_table_gives_one_model(self):
        m = self._manifest([("fct_orders", "dim_customers", "CUSTOMER_ID")])
        assert inspect_manifest(m, "models/d")["path_n_model_count"] == 1

    def test_the_barbershop_shape_gives_three(self):
        """A single connected component that nonetheless splits into 3 — the
        exact case that disproved the connected-component reading."""
        m = self._manifest([
            ("appointments", "barbers", "BARBER_ID"),
            ("appointments", "customers", "CUSTOMER_ID"),
            ("appointments", "services", "SERVICE_ID"),
            ("product_sales", "barbers", "BARBER_ID"),
            ("product_sales", "customers", "CUSTOMER_ID"),
            ("product_sales", "products", "PRODUCT_ID"),
            ("transactions", "appointments", "APPOINTMENT_ID"),
        ])
        assert inspect_manifest(m, "models/d")["path_n_model_count"] == 3

    def test_shared_dimensions_do_not_merge_the_models(self):
        """Two facts sharing a dimension stay two Models — the dimension is
        duplicated into both rather than joining them into one."""
        m = self._manifest([
            ("fct_a", "dim_shared", "K"),
            ("fct_b", "dim_shared", "K"),
        ])
        assert inspect_manifest(m, "models/d")["path_n_model_count"] == 2

    def test_the_count_is_reflected_in_the_reason_text(self):
        m = self._manifest([
            ("fct_a", "dim_shared", "K"),
            ("fct_b", "dim_shared", "K"),
        ])
        joined = " ".join(inspect_manifest(m, "models/d")["reasons"])
        assert "2 Models" in joined

    def test_a_single_fact_says_so_rather_than_claiming_a_split(self):
        m = self._manifest([("fct_orders", "dim_customers", "CUSTOMER_ID")])
        joined = " ".join(inspect_manifest(m, "models/d")["reasons"])
        assert "single Model" in joined and "split" not in joined

    def test_no_joins_still_reports_one_model_when_models_exist(self):
        m = {"nodes": {"model.p.a": {
            "resource_type": "model", "name": "a",
            "original_file_path": "models/d/a.sql"}}}
        assert inspect_manifest(m, "models/d")["path_n_model_count"] == 1

    def test_an_empty_directory_reports_zero(self):
        assert inspect_manifest({"nodes": {}}, "models/d")["path_n_model_count"] == 0
