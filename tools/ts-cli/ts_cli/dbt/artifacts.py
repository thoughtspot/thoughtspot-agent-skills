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
import stat
import tempfile
import zipfile
from pathlib import Path
from typing import IO, Callable, Optional

MANIFEST = "manifest.json"
CATALOG = "catalog.json"


class UnsafeCacheDirError(OSError):
    """The per-user cache dir exists but is not safe to write into."""


def _current_uid() -> Optional[int]:
    """The real uid, or None where the platform has none (Windows)."""
    getuid = getattr(os, "getuid", None)
    return getuid() if getuid else None


def private_cache_dir() -> Path:
    """`<tempdir>/ts_dbt_cache_<uid>`, created 0700 — where every dbt temp file lives.

    2026-10 (PR #506 review): the artifact cache and the packed upload ZIP used
    fixed, guessable names directly in the shared temp dir, written with
    `write_text`/`ZipFile(dest, "w")` and only then chmod-ed. On a multi-user
    host another user could pre-create that name as a symlink (the write
    follows it) or read the file in the window before the chmod. A directory
    only this user can enter closes both: nothing inside it is reachable by
    anyone else, whatever the file names are.

    Refuses (`UnsafeCacheDirError`) a pre-existing path that is a symlink, not a
    directory, owned by someone else, or group/other-accessible — each is either
    an attack or a state this function cannot make safe without guessing. On
    Windows (no uid) the per-user `%TEMP%` already isolates users, so only the
    symlink/type check applies.
    """
    uid = _current_uid()
    path = Path(tempfile.gettempdir()) / (
        f"ts_dbt_cache_{uid}" if uid is not None else "ts_dbt_cache")
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise UnsafeCacheDirError(f"{path} is a symlink or not a directory")
    if uid is not None and st.st_uid != uid:
        raise UnsafeCacheDirError(f"{path} is owned by uid {st.st_uid}, not {uid}")
    if uid is not None and st.st_mode & 0o077:
        raise UnsafeCacheDirError(
            f"{path} is group/other-accessible (mode {stat.S_IMODE(st.st_mode):o}); "
            "remove it or `chmod 700` it")
    return path


def is_private_file(path: Path) -> bool:
    """True when `path` is a regular file (not a symlink) owned by this user.

    The read-side check (PR #506 review): a cache hit is trusted only when this
    process could have written it — anything else is re-downloaded.
    """
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    uid = _current_uid()
    return uid is None or st.st_uid == uid


def write_private_file(dest: Path, write: Callable[[IO[bytes]], None]) -> Path:
    """Write `dest` atomically at mode 0600: `mkstemp` beside it, then `os.replace`.

    `mkstemp` opens with O_EXCL at 0600, so the bytes are never readable by
    anyone else and a planted symlink is never followed; `os.replace` renames
    over `dest` (replacing a symlink rather than writing through it), so a
    reader sees the old file or the complete new one, never a partial write.
    """
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".ts_dbt_", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            write(fh)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return dest


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

    `dest` defaults to a per-source-directory path in the per-user
    :func:`private_cache_dir`, so the three uploads of one session (`create`,
    `generate-tml`, `generate-sync-tml`) rewrite one file instead of
    accumulating copies of a manifest that can run to hundreds of MB. The
    archive is written via :func:`write_private_file` — created 0600, never
    through a symlink (PR #506 review: it was `ZipFile(dest, "w")` on a
    guessable name in the shared temp dir, chmod-ed afterwards).
    """
    if dest is None:
        key = hashlib.sha256(str(manifest.resolve().parent).encode()).hexdigest()[:12]
        try:
            cache_dir = private_cache_dir()
        except OSError as exc:
            raise SystemExit(
                f"Cannot use the private temp dir for the artifact ZIP: {exc}. "
                "Zip manifest.json + catalog.json yourself and pass the .zip.")
        dest = cache_dir / f"ts_dbt_artifacts_{key}.zip"

    dest.parent.mkdir(parents=True, exist_ok=True)

    def _zip(fh: IO[bytes]) -> None:
        with zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(manifest, MANIFEST)
            zf.write(catalog, CATALOG)

    return write_private_file(dest, _zip)


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
    return _load_local_artifact(path_str, MANIFEST,
                                "Run `dbt compile` or `dbt docs generate` first.")


def load_local_catalog(path_str: str) -> dict:
    """Load `catalog.json` from the same places `load_local_manifest` accepts.

    `ts dbt build-model --manifest` needs both: the catalog types the columns
    that carry no `ts_*` meta. Only `dbt docs generate` writes it.
    """
    return _load_local_artifact(path_str, CATALOG,
                                "Run `dbt docs generate` — it writes the catalog.")


def _load_local_artifact(path_str: str, name: str, hint: str) -> dict:
    """One artifact by file name, from a directory, the file itself, or a ZIP."""
    path = Path(path_str)
    if not path.exists():
        raise SystemExit(f"--manifest not found: {path_str}")

    if path.is_dir():
        for candidate in _candidate_dirs(path):
            if (candidate / name).is_file():
                path = candidate / name
                break
        else:
            raise SystemExit(f"No {name} in {path_str} (looked in ./ and ./target/). {hint}")
    elif path.suffix.lower() != ".zip" and name != MANIFEST and path.name != name:
        # --manifest named a file: it IS the manifest, whatever it is called
        # (as before), and the catalog is read from beside it.
        path = path.parent / name
        if not path.is_file():
            raise SystemExit(f"No {name} next to {path_str}. {hint}")

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.rsplit("/", 1)[-1] == name]
            if not names:
                raise SystemExit(f"No {name} inside {path_str}. {hint}")
            # Shallowest wins: target/manifest.json over some vendored copy deeper in.
            with zf.open(sorted(names, key=lambda n: n.count("/"))[0]) as fh:
                return json.load(fh)

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}")
