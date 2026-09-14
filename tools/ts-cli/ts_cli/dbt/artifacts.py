"""Local dbt artifacts — find `manifest.json`/`catalog.json`, and pack them for upload.

The dbt Core (`ZIP_FILE`) side of the integration. ThoughtSpot's dbt connection
takes the two compiled artifacts as a single ZIP, so the skill used to list
"ability to zip manifest.json + catalog.json together" as a *user prerequisite*
and told the reader to go make one by hand before anything could proceed.

That is a mechanical step over two files whose location dbt already fixes
(`target/`), so it belongs here. Every `--file` flag now accepts the
`target/` directory — or the project root, or one of the artifacts — and the
archive is built for you. Passing a real `.zip` still works unchanged, which
is the escape hatch for any layout this module refuses to guess at.

Filesystem only: no network, no ThoughtSpot or dbt Cloud call.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

MANIFEST = "manifest.json"
CATALOG = "catalog.json"


def _candidate_dirs(path: Path) -> list:
    """Where to look for the artifacts, given a directory the user named.

    `target/` is dbt's own output directory, so accept either it or the project
    root that contains it — the user should not have to remember which one this
    flag wanted.
    """
    return [path, path / "target"]


def find_artifacts(path: Path) -> tuple:
    """Locate `(manifest.json, catalog.json)` from a directory or either file.

    Accepts the `target/` dir, a project root containing one, or a path to
    either artifact (the other is taken from the same directory). Returns the
    pair of paths; raises `SystemExit` naming what is missing and how to
    produce it.
    """
    if path.is_file():
        if path.name not in (MANIFEST, CATALOG):
            raise SystemExit(
                f"{path} is not a dbt artifact. Pass the target/ directory, "
                f"{MANIFEST}, {CATALOG}, or a ready-made .zip.")
        found = {path.name: path}
        sibling = path.parent / (CATALOG if path.name == MANIFEST else MANIFEST)
        if sibling.is_file():
            found[sibling.name] = sibling
        return _require_both(found, path.parent)

    for candidate in _candidate_dirs(path):
        found = {n: candidate / n for n in (MANIFEST, CATALOG)
                 if (candidate / n).is_file()}
        if found:
            return _require_both(found, candidate)

    raise SystemExit(
        f"No {MANIFEST} or {CATALOG} under {path} (looked in ./ and ./target/). "
        "Run `dbt docs generate` in the dbt project first — it writes both.")


def _require_both(found: dict, where: Path) -> tuple:
    """Both artifacts, or a refusal naming the missing one.

    ThoughtSpot types the generated Table columns from `catalog.json`, so a
    manifest-only archive imports with no column types rather than failing —
    a silent degradation, which is why this refuses instead of proceeding.
    `dbt docs generate` writes both; `dbt compile` writes only the manifest,
    which is the usual reason one is absent.
    """
    missing = [n for n in (MANIFEST, CATALOG) if n not in found]
    if missing:
        raise SystemExit(
            f"{', '.join(missing)} not found in {where}. `dbt compile` writes only "
            f"{MANIFEST} — run `dbt docs generate` to produce {CATALOG} too. "
            "(To upload an archive without it anyway, zip the files yourself and "
            "pass the .zip.)")
    return found[MANIFEST], found[CATALOG]


def pack_artifacts(manifest: Path, catalog: Path, dest: "Path | None" = None) -> Path:
    """Zip the two artifacts into an upload-ready archive, flat at the root.

    **Layout assumption:** both entries sit at the archive root, named exactly
    `manifest.json` and `catalog.json` — the literal reading of ThoughtSpot's
    "a ZIP containing manifest.json and catalog.json", and what a user doing
    this by hand (`cd target && zip a.zip manifest.json catalog.json`) would
    produce. Not verified against a live ZIP_FILE connection — see
    ts-convert-from-dbt coverage-matrix L6.

    `dest` defaults to a per-source-directory path in the OS temp dir, so the
    three uploads of one session (`create`, `generate-tml`,
    `generate-sync-tml`) rewrite one file instead of accumulating copies of a
    manifest that can run to hundreds of MB.
    """
    if dest is None:
        key = hashlib.sha256(str(manifest.resolve().parent).encode()).hexdigest()[:12]
        dest = Path(tempfile.gettempdir()) / f"ts_dbt_artifacts_{key}.zip"

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(manifest, MANIFEST)
        zf.write(catalog, CATALOG)
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    return dest


def resolve_artifact_zip(path_str: "str | None") -> "Path | None":
    """What every `--file` flag accepts: a `.zip`, a directory, or an artifact.

    A `.zip` is used verbatim. Anything else is located via
    :func:`find_artifacts` and packed by :func:`pack_artifacts`. Returns None
    for a falsy input so DBT_CLOUD callers can pass through unchanged.
    """
    if not path_str:
        return None
    path = Path(path_str)
    if not path.exists():
        raise SystemExit(f"--file not found: {path}")
    if path.is_file() and path.suffix.lower() == ".zip":
        return path
    manifest, catalog = find_artifacts(path)
    return pack_artifacts(manifest, catalog)


def load_local_manifest(path_str: str) -> dict:
    """Load `manifest.json` from a directory, a bare file, or a dbt project ZIP.

    The read-side counterpart to `resolve_artifact_zip`, behind
    `ts dbt list-models --manifest` and `ts dbt inspect --manifest`. Exists so
    the ZIP_FILE path — which has no dbt Cloud run to fetch from — uses the
    same code path as DBT_CLOUD instead of the hand-written
    `json.loads(Path("manifest.json").read_text())` loop the skill used to
    carry.
    """
    path = Path(path_str)
    if not path.exists():
        raise SystemExit(f"--manifest not found: {path_str}")

    if path.is_dir():
        for candidate in _candidate_dirs(path):
            if (candidate / MANIFEST).is_file():
                path = candidate / MANIFEST
                break
        else:
            raise SystemExit(
                f"No {MANIFEST} in {path_str} (looked in ./ and ./target/). "
                "Run `dbt compile` or `dbt docs generate` first.")

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == MANIFEST]
            if not names:
                raise SystemExit(f"No {MANIFEST} inside {path_str}.")
            # Shallowest wins: target/manifest.json over some vendored copy deeper in.
            with zf.open(sorted(names, key=lambda n: n.count("/"))[0]) as fh:
                return json.load(fh)

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}")
