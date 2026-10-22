"""Capture and replay the data an audit reads.

A snapshot is a directory holding one JSON file per ``AuditContext`` field plus
``manifest.json``::

    {"format": 1, "ts_cli_version": "...", "created": "...",
     "angles": ["A", "D", ...], "needs": ["ai_instructions", ...],
     "files": ["answers.json", ...]}

``angles`` records what the capture was asked for, ``needs`` what it fetched: the
data always fetched (``context.ALWAYS_FETCHED``) and the conditional data (AI
instructions, Answer TML, Sets) a selected rule declares in ``requires`` or ``uses``
(``engine.run.needs_for``, under every profile). A replay refuses a selection whose rules read data the
snapshot did not capture, rather than report it clean. A manifest written before
``needs`` was recorded is read by what its angles fetched then
(``LEGACY_ANGLE_NEEDS``).

Replaying a snapshot runs the checks over exactly the data a live run saw.
That is what lets two audit engines be compared on identical input, so a
snapshot that does not reproduce its context exactly is worse than none:
``write_snapshot`` reads its own output back and refuses to leave a snapshot
that differs from what it was given.

Keys are written in insertion order, NOT sorted. The checks iterate the
context's dicts (H5 walks ``dependents``), so dict order decides finding
order; sorting keys reordered 45 of 5,091 findings on a real capture.

A snapshot holds real exported TML, so where it may go is checked before anything is
fetched (``prepare_snapshot_dir``): never inside a git work tree (this repo is
public, and history is permanent), and never into a non-empty directory that is not
an earlier snapshot (its generic file names would overwrite someone's files).

The manifest is written last. A capture interrupted part-way leaves no
manifest, which ``read_snapshot`` reports, never a half-written snapshot that
reads as complete.
"""
from __future__ import annotations

import dataclasses
import datetime
import json
from pathlib import Path

from ts_cli import __version__
from ts_cli.audit.context import ALWAYS_FETCHED, AuditContext

FORMAT = 1
MANIFEST = "manifest.json"
_FIELDS = [f.name for f in dataclasses.fields(AuditContext)]
_TAG = "__ts_snapshot_type__"
#: What a snapshot without `needs` in its manifest fetched for each angle: before the
#: catalog, AI instructions for A, Answer TML and Sets for H (and since, under the
#: shipped catalog, exactly the same — test_audit_context_needs.py).
LEGACY_ANGLE_NEEDS = {"A": frozenset({"ai_instructions"}),
                      "H": frozenset({"answers", "sets"})}


class SnapshotError(Exception):
    """A snapshot cannot be written faithfully, or cannot be read."""


def _file_for(field: str) -> str:
    return f"{field}.json"


# ── encoding ────────────────────────────────────────────────────────────────
# Exported TML is parsed with yaml.safe_load, which turns an unquoted
# 2024-01-31 into a date. JSON has no date type, so dates are tagged.

def _encode_extra(obj):
    if isinstance(obj, datetime.datetime):
        return {_TAG: "datetime", "value": obj.isoformat()}
    if isinstance(obj, datetime.date):
        return {_TAG: "date", "value": obj.isoformat()}
    raise TypeError(f"{type(obj).__name__} is not JSON serialisable")


def _decode_extra(obj: dict):
    kind = obj.get(_TAG)
    if kind == "datetime" and len(obj) == 2:
        return datetime.datetime.fromisoformat(obj["value"])
    if kind == "date" and len(obj) == 2:
        return datetime.date.fromisoformat(obj["value"])
    return obj


def _dumps(value, what: str) -> str:
    try:
        return json.dumps(value, indent=1, default=_encode_extra)
    except (TypeError, ValueError) as exc:
        raise SnapshotError(f"cannot write {what} to a snapshot: {exc}") from exc


# ── write ───────────────────────────────────────────────────────────────────

def _git_work_tree(path: Path):
    """The nearest ancestor of `path` (itself included) holding a `.git` entry — a
    directory, or the file a linked worktree or submodule has; None outside one."""
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _is_earlier_snapshot(out_dir: Path) -> bool:
    """`out_dir` holds a manifest that reads as one `write_snapshot` wrote — format,
    ts_cli_version, created, angles, files — not merely a file named manifest.json (a
    web app's, say)."""
    try:
        manifest = _read_manifest(out_dir)
    except SnapshotError:
        return False
    return all(isinstance(manifest.get(k), str) for k in ("ts_cli_version", "created"))


def prepare_snapshot_dir(out_dir: Path) -> Path:
    """Resolve and create `out_dir` for a snapshot, refusing — with ``SnapshotError``,
    before anything is fetched — a directory inside a git work tree, or a non-empty one
    that is not an earlier snapshot (``_is_earlier_snapshot``)."""
    out_dir = Path(out_dir).expanduser().resolve()
    tree = _git_work_tree(out_dir)
    if tree is not None:
        raise SnapshotError(
            f"{out_dir} is inside the git work tree {tree}. A snapshot holds real "
            "exported TML: write it outside any repository (e.g. ~/audit-snapshots/<name>)")
    if out_dir.exists() and not out_dir.is_dir():
        raise SnapshotError(f"{out_dir} exists and is not a directory")
    if out_dir.is_dir() and any(out_dir.iterdir()) and not _is_earlier_snapshot(out_dir):
        raise SnapshotError(
            f"{out_dir} is not empty and holds no earlier snapshot (a {MANIFEST} as "
            "--snapshot-out writes it); a snapshot overwrites files by generic names — "
            "choose an empty or new directory")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SnapshotError(f"cannot create {out_dir}: {exc}") from exc
    return out_dir


def write_snapshot(ctx: AuditContext, out_dir: Path, angles: list[str],
                   needs=None) -> None:
    """Write ``ctx``, the angles it was captured for and — when given — the ``needs``
    ``build_context`` fetched it with to ``out_dir``. Without ``needs`` the manifest
    records none, and a replay reads it as a legacy, angle-keyed snapshot.

    Raises ``SnapshotError`` when ``out_dir`` is refused (``prepare_snapshot_dir``), or
    when the context holds data JSON cannot carry back unchanged (for example non-string mapping keys); the half-written snapshot
    is left without a manifest, so it cannot be replayed by mistake.
    """
    out_dir = prepare_snapshot_dir(out_dir)
    manifest_path = out_dir / MANIFEST
    if manifest_path.exists():
        manifest_path.unlink()

    files = []
    for field in _FIELDS:
        name = _file_for(field)
        (out_dir / name).write_text(_dumps(getattr(ctx, field), field), encoding="utf-8")
        files.append(name)
    _check_round_trip(ctx, out_dir)

    manifest = {
        "format": FORMAT,
        "ts_cli_version": __version__,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "angles": list(angles),
        "files": sorted(files),
    }
    if needs is not None:
        manifest["needs"] = sorted(set(needs) | ALWAYS_FETCHED)
    manifest_path.write_text(_dumps(manifest, MANIFEST), encoding="utf-8")


def _same(a, b) -> bool:
    """Equal, including dict key ORDER and exact types.

    ``==`` ignores dict order and calls 1 == 1.0 == True; a replay that differs
    in either can change what the checks emit, or the order they emit it in.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _check_round_trip(ctx: AuditContext, out_dir: Path) -> None:
    for field in _FIELDS:
        if not _same(_load(out_dir / _file_for(field)), getattr(ctx, field)):
            raise SnapshotError(
                f"snapshot of {field} does not read back unchanged; "
                "it holds data JSON cannot reproduce (e.g. non-string keys)")


# ── read ────────────────────────────────────────────────────────────────────

def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_hook=_decode_extra)
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"cannot read {path}: {exc}") from exc


def _read_manifest(in_dir: Path) -> dict:
    path = in_dir / MANIFEST
    if not path.is_file():
        raise SnapshotError(f"not a snapshot: {MANIFEST} not found in {in_dir}")
    manifest = _load(path)
    if not isinstance(manifest, dict):
        raise SnapshotError(f"{path} is not a snapshot manifest")
    found = manifest.get("format")
    if found != FORMAT:
        raise SnapshotError(
            f"snapshot format {found} is not supported: this ts-cli reads format {FORMAT}")
    angles, files = manifest.get("angles"), manifest.get("files")
    if not isinstance(angles, list) or not isinstance(files, list):
        raise SnapshotError(f"{path} must list 'angles' and 'files'")
    needs = manifest.get("needs")
    if needs is not None and not (isinstance(needs, list)
                                  and all(isinstance(n, str) for n in needs)):
        raise SnapshotError(f"{path}: 'needs' must be a list of names")
    return manifest


def captured_needs(manifest: dict) -> set:
    """What the snapshot fetched: its manifest's ``needs``, or for a legacy manifest
    without them, what its angles fetched (``LEGACY_ANGLE_NEEDS``)."""
    if manifest.get("needs") is not None:
        return set(manifest["needs"])
    out = set(ALWAYS_FETCHED)
    for angle in manifest["angles"]:
        out |= LEGACY_ANGLE_NEEDS.get(angle, frozenset())
    return out


def read_snapshot(in_dir: Path) -> tuple[AuditContext, list[str]]:
    """Return the ``AuditContext`` stored in ``in_dir`` and the angles it was captured for."""
    ctx, angles, _ = read_snapshot_needs(in_dir)
    return ctx, angles


def read_snapshot_needs(in_dir: Path) -> tuple[AuditContext, list[str], set]:
    """``read_snapshot`` plus what the snapshot fetched (``captured_needs``)."""
    in_dir = Path(in_dir)
    manifest = _read_manifest(in_dir)
    listed = set(manifest["files"])
    for name in manifest["files"]:
        if not (in_dir / name).is_file():
            raise SnapshotError(f"snapshot is incomplete: {name} is listed in "
                                f"{MANIFEST} but missing from {in_dir}")
    values = {}
    for field in _FIELDS:
        name = _file_for(field)
        if name not in listed:
            raise SnapshotError(f"snapshot has no {field} data: {MANIFEST} does not list {name}")
        values[field] = _load(in_dir / name)
    return AuditContext(**values), list(manifest["angles"]), captured_needs(manifest)
