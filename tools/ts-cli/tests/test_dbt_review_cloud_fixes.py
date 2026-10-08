"""PR #506 review fixes for the dbt Cloud I/O path (2026-10).

1. Every dbt Cloud request carries a (connect, read) timeout; a timeout is a
   SystemExit naming the call, not a urllib3 traceback.
2. `ts dbt trigger-job --wait` gives up after `--timeout` seconds instead of
   polling forever.
3. The artifact cache key includes the account id and the dbt Cloud host, so
   two `--access-token-env` callers (slug "env") never share an entry.
4. Cache files and the packed upload ZIP live in a per-user 0700 directory, are
   written atomically at 0600, and a cached file that is a symlink is ignored.
5. A malformed hand-written `ts_rls_rules` tag is a SystemExit naming the model
   and the missing key — and `build-model` refuses it BEFORE importing the Model.

No network: every HTTP call is a fake.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import time
import zipfile

import pytest
import requests

import ts_cli.commands.dbt as dbt_mod
import ts_cli.dbt.cloud_api as cloud_api
from ts_cli.cli import app
from ts_cli.dbt.artifacts import pack_artifacts
from ts_cli.dbt.cloud_api import DbtCloudCtx, fetch_artifact, latest_successful_run
from ts_cli.dbt.manifest import extract_model_rls_from_manifest
from ts_cli.dbt.model_from_schema_yml import extract_table_rls_from_schema_yml

from runners import runner  # noqa: E402

_POSIX = hasattr(os, "getuid")


class _Resp:
    def __init__(self, payload, ok=True, status_code=200, text=""):
        self.ok, self.status_code, self.text = ok, status_code, text
        self._payload = payload

    def json(self):
        return self._payload


def _stub_cloud_get(monkeypatch, handler, calls):
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return handler(url, **kwargs)
    monkeypatch.setattr(cloud_api, "_requests", type("M", (), {"get": staticmethod(get)})())


def _patch_profile(monkeypatch):
    profile = {"name": "p", "account_id": "12345", "project_id": "67890",
               "dbt_url": "https://cloud.getdbt.com"}
    monkeypatch.setattr(cloud_api, "load_platform_profiles", lambda _p: [profile])
    monkeypatch.setattr(cloud_api, "token_from_keychain", lambda _s, profile=None: "tok")


def _real_cache_dir(monkeypatch, tmp_path):
    """Drop conftest's autouse `artifact_cache_path` stub and point the OS temp
    dir at `tmp_path`, so the real cache-path code runs without touching /tmp."""
    monkeypatch.undo()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# 1. Request timeouts
# ---------------------------------------------------------------------------

class TestDbtCloudTimeouts:
    def _ctx(self):
        return DbtCloudCtx(account_id="1", project_id="2", slug="p", token="t")

    def _assert_timeout(self, kwargs):
        t = kwargs.get("timeout")
        assert t is not None, "dbt Cloud request sent with no timeout"
        connect, read = t
        assert 0 < connect <= read

    def test_latest_successful_run_sends_a_timeout(self, monkeypatch):
        calls = []
        _stub_cloud_get(monkeypatch, lambda url, **kw: _Resp({"data": [{"id": 5}]}), calls)
        assert latest_successful_run(self._ctx()) == 5
        self._assert_timeout(calls[0][1])

    def test_fetch_artifact_sends_a_timeout(self, monkeypatch):
        calls = []
        _stub_cloud_get(monkeypatch, lambda url, **kw: _Resp({"nodes": {}}), calls)
        fetch_artifact(self._ctx(), 9, "manifest.json", use_cache=False)
        self._assert_timeout(calls[0][1])

    def test_timeout_is_a_systemexit_naming_the_call(self, monkeypatch):
        def stall(url, **kw):
            raise requests.exceptions.ReadTimeout("read timed out")
        _stub_cloud_get(monkeypatch, stall, [])
        with pytest.raises(SystemExit) as ei:
            fetch_artifact(self._ctx(), 9, "manifest.json", use_cache=False)
        msg = str(ei.value)
        assert "timed out" in msg and "manifest.json" in msg and "run 9" in msg

    def test_trigger_job_requests_all_send_a_timeout(self, monkeypatch):
        _patch_profile(monkeypatch)
        seen = []

        def get(url, **kw):
            seen.append(("GET", url, kw))
            return _Resp({"data": {"id": 999, "status": 10, "finished_at": "x"}})

        def post(url, **kw):
            seen.append(("POST", url, kw))
            return _Resp({"data": {"id": 999, "status": 1}})

        monkeypatch.setattr("ts_cli.commands.dbt._requests.get", get)
        monkeypatch.setattr("ts_cli.commands.dbt._requests.post", post)
        monkeypatch.setattr("time.sleep", lambda _s: None)
        result = runner.invoke(app, ["dbt", "trigger-job", "--dbt-cloud-profile", "p",
                                     "--job-id", "42", "--poll-interval", "1"])
        assert result.exit_code == 0, result.output
        assert {m for m, _, _ in seen} == {"GET", "POST"}
        for _m, _u, kw in seen:
            self._assert_timeout(kw)

    def test_trigger_job_poll_timeout_names_the_run(self, monkeypatch):
        _patch_profile(monkeypatch)

        def get(url, **kw):
            raise requests.exceptions.ConnectTimeout("connect timed out")

        monkeypatch.setattr("ts_cli.commands.dbt._requests.get", get)
        monkeypatch.setattr("ts_cli.commands.dbt._requests.post",
                            lambda url, **kw: _Resp({"data": {"id": 31, "status": 1}}))
        monkeypatch.setattr("time.sleep", lambda _s: None)
        result = runner.invoke(app, ["dbt", "trigger-job", "--dbt-cloud-profile", "p",
                                     "--job-id", "42", "--poll-interval", "1"])
        assert result.exit_code != 0
        assert isinstance(result.exception, SystemExit)
        assert "timed out" in str(result.exception) and "run 31" in str(result.exception)


# ---------------------------------------------------------------------------
# 2. trigger-job --wait deadline
# ---------------------------------------------------------------------------

class TestTriggerJobWaitTimeout:
    def test_wait_gives_up_after_timeout_with_run_id_and_last_status(self, monkeypatch):
        _patch_profile(monkeypatch)
        clock = {"t": 1000.0}
        polls = {"n": 0}

        def get(url, **kw):
            polls["n"] += 1
            if polls["n"] > 50:  # old code polled forever — fail instead of hanging
                raise RuntimeError("still polling after 50 calls")
            return _Resp({"data": {"id": 999, "status": 3}})

        monkeypatch.setattr("ts_cli.commands.dbt._requests.get", get)
        monkeypatch.setattr("ts_cli.commands.dbt._requests.post",
                            lambda url, **kw: _Resp({"data": {"id": 999, "status": 1}}))
        monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))

        result = runner.invoke(app, ["dbt", "trigger-job", "--dbt-cloud-profile", "p",
                                     "--job-id", "42", "--poll-interval", "15",
                                     "--timeout", "60"])
        assert result.exit_code != 0
        msg = str(result.exception)
        assert "999" in msg and "Running" in msg and "still be running" in msg
        assert polls["n"] == 4  # 15s x 4 = the 60s budget, no more
        assert clock["t"] == 1060.0


# ---------------------------------------------------------------------------
# 3. Cache key carries account + host
# ---------------------------------------------------------------------------

class TestArtifactCacheKey:
    def test_env_token_users_on_different_accounts_do_not_share_a_cache_entry(
            self, monkeypatch, tmp_path):
        _real_cache_dir(monkeypatch, tmp_path)
        a = DbtCloudCtx(account_id="1", slug="env", token="t")
        b = DbtCloudCtx(account_id="2", slug="env", token="t")
        assert cloud_api.artifact_cache_path(a, 7, "manifest.json") != \
            cloud_api.artifact_cache_path(b, 7, "manifest.json")

    def test_same_account_on_different_hosts_do_not_share_a_cache_entry(
            self, monkeypatch, tmp_path):
        _real_cache_dir(monkeypatch, tmp_path)
        a = DbtCloudCtx(account_id="1", slug="env", token="t", base="https://cloud.getdbt.com")
        b = DbtCloudCtx(account_id="1", slug="env", token="t", base="https://emea.dbt.com")
        assert cloud_api.artifact_cache_path(a, 7, "manifest.json") != \
            cloud_api.artifact_cache_path(b, 7, "manifest.json")


# ---------------------------------------------------------------------------
# 4. Private directory, atomic 0600 writes, symlink-safe reads
# ---------------------------------------------------------------------------

def _target(tmp_path):
    target = tmp_path / "proj" / "target"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text('{"nodes": {}}')
    (target / "catalog.json").write_text('{"nodes": {}}')
    return target


@pytest.mark.skipif(not _POSIX, reason="uid/mode semantics are POSIX-only")
class TestPrivateTempFiles:
    def _private_dir(self, tmp_path):
        return tmp_path / f"ts_dbt_cache_{os.getuid()}"

    def test_artifact_cache_lives_in_a_0700_per_user_dir(self, monkeypatch, tmp_path):
        _real_cache_dir(monkeypatch, tmp_path)
        ctx = DbtCloudCtx(account_id="1", slug="env", token="t")
        path = cloud_api.artifact_cache_path(ctx, 7, "manifest.json")
        assert path.parent == self._private_dir(tmp_path)
        assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700

    def test_packed_zip_lives_in_the_private_dir_at_0600(self, monkeypatch, tmp_path):
        _real_cache_dir(monkeypatch, tmp_path)
        target = _target(tmp_path)
        dest = pack_artifacts(target / "manifest.json", target / "catalog.json")
        assert dest.parent == self._private_dir(tmp_path)
        assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600
        assert sorted(zipfile.ZipFile(dest).namelist()) == ["catalog.json", "manifest.json"]

    def test_pack_does_not_write_through_a_planted_symlink(self, tmp_path):
        target = _target(tmp_path)
        victim = tmp_path / "victim.txt"
        victim.write_text("precious")
        dest = tmp_path / "out.zip"
        dest.symlink_to(victim)
        pack_artifacts(target / "manifest.json", target / "catalog.json", dest)
        assert victim.read_text() == "precious"
        assert not dest.is_symlink() and zipfile.is_zipfile(dest)
        assert stat.S_IMODE(os.stat(dest).st_mode) == 0o600

    def test_group_accessible_private_dir_is_refused(self, monkeypatch, tmp_path):
        _real_cache_dir(monkeypatch, tmp_path)
        d = self._private_dir(tmp_path)
        d.mkdir()
        os.chmod(d, 0o777)
        target = _target(tmp_path)
        with pytest.raises(SystemExit) as ei:
            pack_artifacts(target / "manifest.json", target / "catalog.json")
        assert "group/other-accessible" in str(ei.value)
        assert list(d.iterdir()) == []

    def test_symlinked_private_dir_is_refused(self, monkeypatch, tmp_path):
        _real_cache_dir(monkeypatch, tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        self._private_dir(tmp_path).symlink_to(elsewhere)
        target = _target(tmp_path)
        with pytest.raises(SystemExit):
            pack_artifacts(target / "manifest.json", target / "catalog.json")
        assert list(elsewhere.iterdir()) == []

    def test_unsafe_cache_dir_disables_the_cache_but_still_downloads(
            self, monkeypatch, tmp_path, capsys):
        _real_cache_dir(monkeypatch, tmp_path)
        d = self._private_dir(tmp_path)
        d.mkdir()
        os.chmod(d, 0o755)
        calls = []
        _stub_cloud_get(monkeypatch, lambda url, **kw: _Resp({"nodes": {"a": 1}}), calls)
        ctx = DbtCloudCtx(account_id="1", slug="env", token="t")
        assert fetch_artifact(ctx, 7, "manifest.json") == {"nodes": {"a": 1}}
        assert list(d.iterdir()) == []
        assert "artifact cache disabled" in capsys.readouterr().err

    def test_cached_symlink_is_ignored_and_refetched(self, monkeypatch, tmp_path):
        # conftest points artifact_cache_path at tmp_path; plant a symlink there.
        ctx = DbtCloudCtx(account_id="1", slug="env", token="t")
        planted = tmp_path / "planted.json"
        planted.write_text(json.dumps({"nodes": {"evil": 1}}))
        cache = cloud_api.artifact_cache_path(ctx, 7, "manifest.json")
        cache.symlink_to(planted)
        calls = []
        _stub_cloud_get(monkeypatch, lambda url, **kw: _Resp({"nodes": {"real": 1}}), calls)
        assert fetch_artifact(ctx, 7, "manifest.json") == {"nodes": {"real": 1}}
        assert len(calls) == 1
        assert json.loads(planted.read_text()) == {"nodes": {"evil": 1}}, \
            "the cache write must replace the symlink, not write through it"
        assert not cache.is_symlink()
        assert stat.S_IMODE(os.stat(cache).st_mode) == 0o600


# ---------------------------------------------------------------------------
# 5. Malformed ts_rls_rules
# ---------------------------------------------------------------------------

_PATH = "models/staging/barbershop"


def _manifest_with_rls(rules):
    return {"nodes": {
        "model.p.barbers": {
            "resource_type": "model", "name": "barbers",
            "database": "ANALYTICS_DB", "schema": "dbt", "alias": "barbers",
            "original_file_path": f"{_PATH}/barbers.sql",
            "config": {"meta": {"ts_rls_rules": rules}},
            "columns": {"HOURLY_RATE": {"config": {"meta": {"ts_column_type": "measure"}}}},
        }}}


class TestMalformedRlsRules:
    def test_manifest_rule_missing_expr_names_model_and_key(self):
        with pytest.raises(SystemExit) as ei:
            extract_model_rls_from_manifest(_manifest_with_rls([{"name": "r1"}]), _PATH)
        msg = str(ei.value)
        assert "'barbers'" in msg and "'expr'" in msg

    def test_manifest_table_path_missing_table_names_model_and_key(self):
        rules = [{"name": "r1", "expr": "x", "table_paths": [{"id": "T_1"}]}]
        with pytest.raises(SystemExit) as ei:
            extract_model_rls_from_manifest(_manifest_with_rls(rules), _PATH)
        assert "'barbers'" in str(ei.value) and "'table'" in str(ei.value)

    def test_schema_yml_rule_missing_name_names_model_and_key(self):
        yml = ("models:\n  - name: orders\n    config:\n      meta:\n"
               "        ts_rls_rules:\n          - expr: \"[x] = ts_username\"\n")
        with pytest.raises(SystemExit) as ei:
            extract_table_rls_from_schema_yml(yml)
        assert "'orders'" in str(ei.value) and "'name'" in str(ei.value)

    def test_schema_yml_table_path_missing_id_names_model_and_key(self):
        yml = ("models:\n  - name: orders\n    config:\n      meta:\n"
               "        ts_rls_rules:\n          - name: r\n            expr: x\n"
               "            table_paths:\n              - table: ORDERS\n")
        with pytest.raises(SystemExit) as ei:
            extract_table_rls_from_schema_yml(yml)
        assert "'orders'" in str(ei.value) and "'id'" in str(ei.value)

    def test_build_model_refuses_bad_tag_before_importing_the_model(self, monkeypatch, tmp_path):
        target = tmp_path / "proj" / "target"
        target.mkdir(parents=True)
        (target / "manifest.json").write_text(json.dumps(_manifest_with_rls([{"name": "r1"}])))
        (target / "catalog.json").write_text(json.dumps({"nodes": {}}))
        calls = []

        class C:
            def __init__(self, *_): pass

            def post(self, path, **kw):
                calls.append(path)
                if path.endswith("/metadata/search"):
                    return _Resp([{"metadata_id": "g-b", "metadata_header": {"name": "BARBERS"}}])
                return _Resp([{"response": {"status": {"status_code": "OK"}}}])

        monkeypatch.setattr(dbt_mod, "ThoughtSpotClient", C)
        monkeypatch.setattr(dbt_mod, "resolve_profile", lambda p: "tp")
        result = runner.invoke(app, ["dbt", "build-model", "--manifest", str(target),
                                     "--model-path", _PATH, "--model-name", "M"])
        assert result.exit_code != 0
        assert isinstance(result.exception, SystemExit)
        assert "'expr'" in str(result.exception)
        assert not any(p.endswith("/tml/import") for p in calls), \
            "the Model must not be imported when its ts_rls_rules tag is malformed"
