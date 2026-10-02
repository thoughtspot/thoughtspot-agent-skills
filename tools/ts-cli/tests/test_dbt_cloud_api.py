"""Tests for `ts_cli.dbt.cloud_api` — profile resolution, run lookup, artifact cache.

The cache is the point of the module: a round trip used to download the same
`manifest.json` three to five times because `list-models`, `inspect` and
`build-model` each resolved the run themselves. The tests below pin the two
properties that makes safe — a hit serves the SAME run's bytes without a
request, and a new run never hits.
"""
from __future__ import annotations

import json

import pytest

import ts_cli.dbt.cloud_api as cloud_api
from ts_cli.dbt.cloud_api import (
    DbtCloudCtx,
    fetch_artifact,
    latest_successful_run,
    resolve_dbt_profile,
)


# The stand-in credential for every test below. It must contain the whole word
# "fake" so `check_secrets.py` reads it as a placeholder: these tests exist to
# prove a token never reaches a cache file, a URL or a repr, and a sentinel that
# trips the secrets gate would make the suite unstageable.
FAKE_TOKEN = "fake-token-value"


class _Resp:
    def __init__(self, payload, ok=True, status_code=200, text=""):
        self.ok, self.status_code, self.text = ok, status_code, text
        self._payload = payload

    def json(self):
        return self._payload


def _fake_http(monkeypatch, handler, calls=None):
    calls = calls if calls is not None else []

    def get(url, **kwargs):
        calls.append(url)
        return handler(url, **kwargs)

    monkeypatch.setattr(cloud_api, "_requests", type("M", (), {"get": staticmethod(get)})())
    return calls


def _ctx(tmp_path, monkeypatch, slug="proj"):
    ctx = DbtCloudCtx(account_id="1", project_id="2", slug=slug, token="tok")
    monkeypatch.setattr(
        cloud_api, "artifact_cache_path",
        lambda c, run_id, name: tmp_path / f"{c.slug}_{run_id}_{name}")
    return ctx


class TestArtifactCache:
    _MANIFEST = {"nodes": {"model.p.a": {"resource_type": "model", "name": "a"}}}

    def test_three_fetches_of_one_run_make_one_request(self, monkeypatch, tmp_path):
        ctx = _ctx(tmp_path, monkeypatch)
        calls = _fake_http(monkeypatch, lambda url, **kw: _Resp(self._MANIFEST))

        first = fetch_artifact(ctx, 42, "manifest.json")
        second = fetch_artifact(ctx, 42, "manifest.json")
        third = fetch_artifact(ctx, 42, "manifest.json")

        assert first == second == third == self._MANIFEST
        assert len(calls) == 1, f"expected one download, got {calls}"

    def test_a_new_run_id_is_a_cache_miss(self, monkeypatch, tmp_path):
        """No TTL to tune: a finished run's artifacts are immutable, so the run
        id IS the invalidation key. A newer run must re-download."""
        ctx = _ctx(tmp_path, monkeypatch)
        payloads = {42: {"run": 42}, 43: {"run": 43}}
        current = {"id": 42}
        calls = _fake_http(monkeypatch, lambda url, **kw: _Resp(payloads[current["id"]]))

        assert fetch_artifact(ctx, 42, "manifest.json") == {"run": 42}
        current["id"] = 43
        assert fetch_artifact(ctx, 43, "manifest.json") == {"run": 43}
        assert len(calls) == 2

    def test_different_artifacts_of_one_run_do_not_collide(self, monkeypatch, tmp_path):
        ctx = _ctx(tmp_path, monkeypatch)
        _fake_http(monkeypatch, lambda url, **kw: _Resp(
            {"which": "catalog"} if "catalog" in url else {"which": "manifest"}))
        assert fetch_artifact(ctx, 7, "manifest.json") == {"which": "manifest"}
        assert fetch_artifact(ctx, 7, "catalog.json") == {"which": "catalog"}

    def test_no_cache_forces_a_redownload(self, monkeypatch, tmp_path):
        ctx = _ctx(tmp_path, monkeypatch)
        calls = _fake_http(monkeypatch, lambda url, **kw: _Resp(self._MANIFEST))
        fetch_artifact(ctx, 42, "manifest.json")
        fetch_artifact(ctx, 42, "manifest.json", use_cache=False)
        assert len(calls) == 2

    def test_corrupt_cache_file_refetches_instead_of_raising(self, monkeypatch, tmp_path):
        ctx = _ctx(tmp_path, monkeypatch)
        cloud_api.artifact_cache_path(ctx, 42, "manifest.json").write_text("{not json")
        calls = _fake_http(monkeypatch, lambda url, **kw: _Resp(self._MANIFEST))
        assert fetch_artifact(ctx, 42, "manifest.json") == self._MANIFEST
        assert len(calls) == 1

    def test_http_error_is_a_named_systemexit(self, monkeypatch, tmp_path):
        ctx = _ctx(tmp_path, monkeypatch)
        _fake_http(monkeypatch, lambda url, **kw: _Resp(None, ok=False, status_code=404,
                                                        text="not found"))
        with pytest.raises(SystemExit) as ei:
            fetch_artifact(ctx, 42, "manifest.json")
        assert "manifest.json" in str(ei.value) and "404" in str(ei.value)

    def test_cache_file_is_owner_only(self, monkeypatch, tmp_path):
        ctx = _ctx(tmp_path, monkeypatch)
        _fake_http(monkeypatch, lambda url, **kw: _Resp(self._MANIFEST))
        fetch_artifact(ctx, 42, "manifest.json")
        path = cloud_api.artifact_cache_path(ctx, 42, "manifest.json")
        assert path.stat().st_mode & 0o077 == 0, "cache must not be group/world readable"

    def test_artifact_name_cannot_escape_the_cache_dir(self):
        ctx = DbtCloudCtx(account_id="1", slug="p", token="t")
        path = cloud_api.artifact_cache_path(ctx, 1, "../../etc/passwd")
        assert ".." not in path.name and "/" not in path.name


class TestLatestSuccessfulRun:
    def test_returns_the_first_run_id(self, monkeypatch):
        _fake_http(monkeypatch, lambda url, **kw: _Resp({"data": [{"id": 501}]}))
        assert latest_successful_run(DbtCloudCtx(account_id="1", project_id="2",
                                                 token="t")) == 501

    def test_only_asks_for_successful_runs(self, monkeypatch):
        """status=10 is dbt Cloud's Success. Dropping the filter would happily
        return the most recent FAILED run's artifacts."""
        seen = {}

        def get(url, **kwargs):
            seen.update(kwargs.get("params") or {})
            return _Resp({"data": [{"id": 1}]})

        monkeypatch.setattr(cloud_api, "_requests",
                            type("M", (), {"get": staticmethod(get)})())
        latest_successful_run(DbtCloudCtx(account_id="1", project_id="2",
                                          dbt_env_id="9", token="t"))
        assert seen["status"] == "10"
        assert seen["order_by"] == "-created_at"
        assert seen["environment_id"] == "9"

    def test_no_runs_names_the_project_and_environment(self, monkeypatch):
        _fake_http(monkeypatch, lambda url, **kw: _Resp({"data": []}))
        with pytest.raises(SystemExit) as ei:
            latest_successful_run(DbtCloudCtx(account_id="1", project_id="777",
                                              dbt_env_id="88", token="t"))
        assert "777" in str(ei.value) and "88" in str(ei.value)


class TestResolveDbtProfile:
    _PROFILE = {
        "name": "My Project", "account_id": "43692", "project_id": "130012",
        "dbt_env_id": "218891", "dbt_url": "https://cloud.getdbt.com/",
        "auth_type": "token",
        "token_env": "DBT_CLOUD_TOKEN_MY_PROJECT",
        "keychain_service": "dbt-cloud-my-project", "keychain_account": "token",
    }

    def test_profile_fields_populate_the_context(self, monkeypatch):
        monkeypatch.setattr(cloud_api, "load_platform_profiles", lambda _p: [self._PROFILE])
        monkeypatch.setattr(cloud_api, "token_from_keychain", lambda s, p=None: "tok")
        ctx = resolve_dbt_profile("My Project")
        assert (ctx.account_id, ctx.project_id, ctx.dbt_env_id) == ("43692", "130012", "218891")
        assert ctx.base == "https://cloud.getdbt.com"       # trailing slash stripped
        assert ctx.slug == "my-project"

    def test_flags_override_profile_values(self, monkeypatch):
        monkeypatch.setattr(cloud_api, "load_platform_profiles", lambda _p: [self._PROFILE])
        monkeypatch.setattr(cloud_api, "token_from_keychain", lambda s, p=None: "tok")
        ctx = resolve_dbt_profile("My Project", project_id="999", dbt_url="https://eu.getdbt.com")
        assert ctx.project_id == "999" and ctx.base == "https://eu.getdbt.com"

    def test_slug_is_derived_not_the_raw_name(self, monkeypatch):
        """`ts profiles add` keys the keychain on slugify(name). Passing the raw
        name — which every caller used to do — misses for any name that is not
        already slug-shaped, and the miss reads as "no credential stored"."""
        seen = {}
        monkeypatch.setattr(cloud_api, "load_platform_profiles", lambda _p: [self._PROFILE])

        def fake_token(slug, profile=None):
            seen["slug"] = slug
            seen["profile"] = profile
            return "tok"

        monkeypatch.setattr(cloud_api, "token_from_keychain", fake_token)
        resolve_dbt_profile("My Project")
        assert seen["slug"] == "my-project"
        assert seen["profile"] is self._PROFILE

    def test_unknown_profile_names_the_fix(self, monkeypatch):
        monkeypatch.setattr(cloud_api, "load_platform_profiles", lambda _p: [])
        with pytest.raises(SystemExit) as ei:
            resolve_dbt_profile("ghost")
        assert "ghost" in str(ei.value) and "ts profiles list" in str(ei.value)

    def test_missing_token_refuses_rather_than_calling_unauthenticated(self, monkeypatch):
        monkeypatch.setattr(cloud_api, "load_platform_profiles", lambda _p: [self._PROFILE])
        monkeypatch.setattr(cloud_api, "token_from_keychain", lambda s, p=None: None)
        with pytest.raises(SystemExit) as ei:
            resolve_dbt_profile("My Project")
        assert "keychain" in str(ei.value).lower()

    def test_access_token_env_path(self, monkeypatch):
        monkeypatch.setenv("SOME_DBT_TOKEN", "env-tok")
        ctx = resolve_dbt_profile(None, account_id="1", project_id="2",
                                  access_token_env="SOME_DBT_TOKEN")
        assert ctx.token == "env-tok" and ctx.slug == "env"

    def test_unset_access_token_env_names_the_variable(self, monkeypatch):
        monkeypatch.delenv("NO_SUCH_DBT_TOKEN", raising=False)
        with pytest.raises(SystemExit) as ei:
            resolve_dbt_profile(None, account_id="1", project_id="2",
                                access_token_env="NO_SUCH_DBT_TOKEN")
        assert "NO_SUCH_DBT_TOKEN" in str(ei.value)

    def test_neither_source_refuses(self):
        with pytest.raises(SystemExit) as ei:
            resolve_dbt_profile(None, account_id="1", project_id="2")
        assert "--dbt-cloud-profile" in str(ei.value)


class TestTokenNeverLeaks:
    def test_repr_omits_the_token(self):
        ctx = DbtCloudCtx(account_id="1", project_id="2", token=FAKE_TOKEN)
        assert FAKE_TOKEN not in repr(ctx)

    def test_token_is_not_written_to_the_cache(self, monkeypatch, tmp_path):
        ctx = _ctx(tmp_path, monkeypatch)
        ctx.token = FAKE_TOKEN
        _fake_http(monkeypatch, lambda url, **kw: _Resp({"ok": True}))
        fetch_artifact(ctx, 42, "manifest.json")
        for path in tmp_path.iterdir():
            assert FAKE_TOKEN not in path.read_text()
            assert FAKE_TOKEN not in path.name

    def test_token_travels_in_the_authorization_header_only(self, monkeypatch):
        seen = {}

        def get(url, **kwargs):
            seen["url"] = url
            seen["headers"] = kwargs.get("headers") or {}
            return _Resp({"data": [{"id": 1}]})

        monkeypatch.setattr(cloud_api, "_requests",
                            type("M", (), {"get": staticmethod(get)})())
        latest_successful_run(DbtCloudCtx(account_id="1", project_id="2", token=FAKE_TOKEN))
        assert seen["headers"]["Authorization"] == f"Token {FAKE_TOKEN}"
        assert FAKE_TOKEN not in seen["url"]


class TestErrorTextIsUsable:
    def test_run_fetch_error_carries_status_and_body(self, monkeypatch):
        _fake_http(monkeypatch, lambda url, **kw: _Resp(None, ok=False, status_code=401,
                                                        text="invalid token"))
        with pytest.raises(SystemExit) as ei:
            latest_successful_run(DbtCloudCtx(account_id="1", project_id="2", token="t"))
        assert "401" in str(ei.value) and "invalid token" in str(ei.value)

    def test_cache_write_failure_is_not_fatal(self, monkeypatch, tmp_path):
        """A read-only temp dir must degrade to "no cache", never break the command."""
        ctx = _ctx(tmp_path, monkeypatch)
        monkeypatch.setattr(
            cloud_api, "artifact_cache_path",
            lambda c, r, n: tmp_path / "does" / "not" / "exist" / "x.json")
        _fake_http(monkeypatch, lambda url, **kw: _Resp({"ok": True}))
        assert fetch_artifact(ctx, 1, "manifest.json") == {"ok": True}


def test_cache_path_is_scoped_per_profile(tmp_path):
    """Two profiles pointing at different dbt Cloud accounts can see the same
    run id. Without the slug in the key, one would serve the other's manifest."""
    a = DbtCloudCtx(account_id="1", slug="prod", token="t")
    b = DbtCloudCtx(account_id="2", slug="staging", token="t")
    assert cloud_api.artifact_cache_path(a, 7, "manifest.json") != \
        cloud_api.artifact_cache_path(b, 7, "manifest.json")


def test_cache_round_trips_a_realistic_manifest(monkeypatch, tmp_path):
    ctx = _ctx(tmp_path, monkeypatch)
    manifest = {"nodes": {f"model.p.m{i}": {"resource_type": "model", "name": f"m{i}",
                                            "original_file_path": f"models/x/m{i}.sql"}
                          for i in range(50)}}
    _fake_http(monkeypatch, lambda url, **kw: _Resp(manifest))
    assert fetch_artifact(ctx, 3, "manifest.json") == manifest
    cached = json.loads(cloud_api.artifact_cache_path(ctx, 3, "manifest.json").read_text())
    assert cached == manifest
