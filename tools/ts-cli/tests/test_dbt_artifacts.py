"""Tests for `ts_cli.dbt.artifacts` — locating and packing dbt Core artifacts.

The ZIP_FILE path used to list "ability to zip manifest.json + catalog.json
together" as a user prerequisite. These pin the behaviour that removed it:
point `--file` at `target/` and the archive is built, with the two failure
modes that actually bite (a `dbt compile` run that never wrote catalog.json,
and a path that is neither) refused by name rather than uploaded silently.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from ts_cli.dbt.artifacts import (
    find_artifacts,
    load_local_manifest,
    pack_artifacts,
    resolve_artifact_zip,
)

_MANIFEST = {"nodes": {"model.p.a": {"resource_type": "model", "name": "a",
                                     "original_file_path": "models/a.sql"}}}
_CATALOG = {"nodes": {"model.p.a": {"columns": {"ID": {"type": "NUMBER"}}}}}


def _project(tmp_path, *, catalog=True, nested=True):
    """A dbt project laid out the way `dbt docs generate` leaves it."""
    root = tmp_path / "my_dbt_project"
    target = (root / "target") if nested else root
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps(_MANIFEST))
    if catalog:
        (target / "catalog.json").write_text(json.dumps(_CATALOG))
    return root, target


class TestFindArtifacts:
    def test_finds_both_in_a_target_dir(self, tmp_path):
        _, target = _project(tmp_path)
        manifest, catalog = find_artifacts(target)
        assert manifest.name == "manifest.json" and catalog.name == "catalog.json"

    def test_finds_both_from_the_project_root(self, tmp_path):
        """dbt writes to `<project>/target/`, and the user should not have to
        remember which of the two levels this flag wanted."""
        root, _ = _project(tmp_path)
        manifest, catalog = find_artifacts(root)
        assert manifest.parent.name == "target"

    def test_accepts_a_path_to_either_artifact(self, tmp_path):
        _, target = _project(tmp_path)
        for named in ("manifest.json", "catalog.json"):
            manifest, catalog = find_artifacts(target / named)
            assert manifest.name == "manifest.json"
            assert catalog.name == "catalog.json"

    def test_missing_catalog_is_refused_and_names_dbt_docs_generate(self, tmp_path):
        """`dbt compile` writes only the manifest. ThoughtSpot types columns
        from catalog.json, so a manifest-only upload imports with no column
        types rather than failing — a silent degradation."""
        _, target = _project(tmp_path, catalog=False)
        with pytest.raises(SystemExit) as ei:
            find_artifacts(target)
        msg = str(ei.value)
        assert "catalog.json" in msg and "dbt docs generate" in msg

    def test_refusal_names_the_manual_escape_hatch(self, tmp_path):
        _, target = _project(tmp_path, catalog=False)
        with pytest.raises(SystemExit) as ei:
            find_artifacts(target)
        assert ".zip" in str(ei.value)

    def test_empty_directory_says_where_it_looked(self, tmp_path):
        empty = tmp_path / "nothing"
        empty.mkdir()
        with pytest.raises(SystemExit) as ei:
            find_artifacts(empty)
        assert "./target/" in str(ei.value)

    def test_an_unrelated_file_is_refused(self, tmp_path):
        stray = tmp_path / "notes.txt"
        stray.write_text("hi")
        with pytest.raises(SystemExit) as ei:
            find_artifacts(stray)
        assert "not a dbt artifact" in str(ei.value)


class TestPackArtifacts:
    def test_entries_are_flat_at_the_archive_root(self, tmp_path):
        """The layout ThoughtSpot's "a ZIP containing manifest.json and
        catalog.json" implies, and what a hand-rolled
        `cd target && zip a.zip manifest.json catalog.json` produces."""
        _, target = _project(tmp_path)
        dest = pack_artifacts(target / "manifest.json", target / "catalog.json",
                              tmp_path / "out.zip")
        with zipfile.ZipFile(dest) as zf:
            assert sorted(zf.namelist()) == ["catalog.json", "manifest.json"]

    def test_contents_round_trip_unchanged(self, tmp_path):
        _, target = _project(tmp_path)
        dest = pack_artifacts(target / "manifest.json", target / "catalog.json",
                              tmp_path / "out.zip")
        with zipfile.ZipFile(dest) as zf:
            assert json.loads(zf.read("manifest.json")) == _MANIFEST
            assert json.loads(zf.read("catalog.json")) == _CATALOG

    def test_default_destination_is_stable_per_source_dir(self, tmp_path):
        """`create`, `generate-tml` and `generate-sync-tml` each upload the same
        artifacts. A fresh temp name per call would leave three copies of a
        manifest that can run to hundreds of MB."""
        _, target = _project(tmp_path)
        a = pack_artifacts(target / "manifest.json", target / "catalog.json")
        b = pack_artifacts(target / "manifest.json", target / "catalog.json")
        assert a == b

    def test_different_projects_get_different_archives(self, tmp_path):
        _, t1 = _project(tmp_path / "one")
        _, t2 = _project(tmp_path / "two")
        assert pack_artifacts(t1 / "manifest.json", t1 / "catalog.json") != \
            pack_artifacts(t2 / "manifest.json", t2 / "catalog.json")

    def test_archive_is_owner_only(self, tmp_path):
        _, target = _project(tmp_path)
        dest = pack_artifacts(target / "manifest.json", target / "catalog.json")
        assert dest.stat().st_mode & 0o077 == 0


class TestResolveArtifactZip:
    def test_a_ready_made_zip_is_passed_through_untouched(self, tmp_path):
        """The escape hatch for any layout this module would guess wrong."""
        z = tmp_path / "mine.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("weird/nesting/manifest.json", json.dumps(_MANIFEST))
        assert resolve_artifact_zip(str(z)) == z

    def test_a_target_dir_is_packed(self, tmp_path):
        _, target = _project(tmp_path)
        out = resolve_artifact_zip(str(target))
        with zipfile.ZipFile(out) as zf:
            assert sorted(zf.namelist()) == ["catalog.json", "manifest.json"]

    def test_none_passes_through_for_dbt_cloud_callers(self):
        assert resolve_artifact_zip(None) is None
        assert resolve_artifact_zip("") is None

    def test_a_missing_path_is_refused_by_name(self, tmp_path):
        with pytest.raises(SystemExit) as ei:
            resolve_artifact_zip(str(tmp_path / "nope"))
        assert "--file not found" in str(ei.value)


class TestLoadLocalManifest:
    def test_reads_a_bare_file_a_dir_and_a_zip(self, tmp_path):
        root, target = _project(tmp_path)
        assert load_local_manifest(str(target / "manifest.json")) == _MANIFEST
        assert load_local_manifest(str(target)) == _MANIFEST
        assert load_local_manifest(str(root)) == _MANIFEST

        z = tmp_path / "a.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("target/manifest.json", json.dumps(_MANIFEST))
        assert load_local_manifest(str(z)) == _MANIFEST

    def test_shallowest_manifest_wins_in_a_zip(self, tmp_path):
        z = tmp_path / "a.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("deep/vendor/pkg/manifest.json", json.dumps({"nodes": {"wrong": {}}}))
            zf.writestr("manifest.json", json.dumps(_MANIFEST))
        assert load_local_manifest(str(z)) == _MANIFEST

    def test_invalid_json_names_the_file(self, tmp_path):
        bad = tmp_path / "manifest.json"
        bad.write_text("{not json")
        with pytest.raises(SystemExit) as ei:
            load_local_manifest(str(bad))
        assert "not valid JSON" in str(ei.value)

    def test_a_packed_archive_reads_back(self, tmp_path):
        """resolve_artifact_zip and load_local_manifest are the write and read
        halves of the same layout — an archive one produces the other must read."""
        _, target = _project(tmp_path)
        packed = resolve_artifact_zip(str(target))
        assert load_local_manifest(str(packed)) == _MANIFEST
