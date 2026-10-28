#!/usr/bin/env python3
"""pr_tree.py — write a commit's files to a directory as raw blobs, for reading only.

The `pr-ready` skill's "Someone else's branch" procedure gives the read-only reviewer
the PR head's files to read. `git archive | tar -x` was the first way, and it is the
wrong one: `git archive` applies the archived tree's OWN `.gitattributes` — `filter=`
and `working-tree-encoding=` rewrite content, `export-subst` expands placeholders,
`export-ignore` drops files — so the PR decides what the reviewer sees. This reads the
tree with `git ls-tree` and the bytes with `git cat-file --batch`, neither of which
applies attributes, and writes the files itself:

- **regular blobs only** (modes 100644 and 100755). Symbolic links (120000) are
  skipped, so nothing under the output can point outside it; submodules (160000) have
  no content here. Both are listed as skipped.
- **paths are checked** before anything is written: an absolute path, an empty
  segment, or a `.`/`..` segment is refused (git itself refuses these, so one means a
  hand-built tree).
- **nothing is executable**: every file is written 0644, whatever its mode.
- the output directory must be empty or absent.

    python3 tools/validate/pr_tree.py <commit> <out-dir>

Prints one line per skipped entry to stdout and a summary to stderr. Exit 0 written;
1 a refused path or a git failure (nothing is left half-trusted: the caller deletes
the directory); 2 usage.

Must import and run on Python 3.9 (the system interpreter).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REGULAR = ("100644", "100755")


class TreeError(RuntimeError):
    pass


def safe_path(path: str) -> bool:
    """True for a relative path with no empty, `.` or `..` segment."""
    if not path or path.startswith("/") or "\\" in path or "\0" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))


def _entries(repo: Path, commit: str) -> List[Tuple[str, str, str, str]]:
    """(mode, type, sha, path) for every entry under `commit`, recursively."""
    proc = subprocess.run(["git", "ls-tree", "-r", "-z", "--full-tree", commit], cwd=repo,
                          capture_output=True)
    if proc.returncode != 0:
        raise TreeError(f"git ls-tree failed: {proc.stderr.decode(errors='replace').strip()}")
    out = []
    for record in proc.stdout.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        mode, kind, sha = meta.decode().split()
        out.append((mode, kind, sha, path.decode("utf-8", errors="surrogateescape")))
    return out


def extract(repo: Path, commit: str, out: Path) -> Dict[str, List[str]]:
    """Write `commit`'s regular files under `out`. Returns {"written": [...],
    "skipped": ["<path> (<reason>)", ...]}. Raises TreeError on a refused path."""
    if out.exists() and any(out.iterdir()):
        raise TreeError(f"{out} is not empty")
    entries = _entries(repo, commit)
    bad = [p for _, _, _, p in entries if not safe_path(p)]
    if bad:
        raise TreeError(f"refused unsafe path(s): {bad[:5]}")
    blobs = [(sha, p) for mode, kind, sha, p in entries if kind == "blob" and mode in REGULAR]
    skipped = [f"{p} ({'symlink' if mode == '120000' else 'submodule' if kind == 'commit' else mode})"
               for mode, kind, _, p in entries if not (kind == "blob" and mode in REGULAR)]

    out.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=repo,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert proc.stdin is not None and proc.stdout is not None
    written = []
    try:
        for sha, rel in blobs:
            proc.stdin.write(sha.encode() + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().split()
            if len(header) != 3 or header[1] != b"blob":
                raise TreeError(f"unexpected cat-file reply for {rel}: {header!r}")
            data = proc.stdout.read(int(header[2]))
            proc.stdout.read(1)                       # the newline after the content
            target = out.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            written.append(rel)
    finally:
        proc.stdin.close()
        proc.wait()
    return {"written": written, "skipped": skipped}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: pr_tree.py <commit> <out-dir>", file=sys.stderr)
        return 2
    try:
        result = extract(Path.cwd(), args[0], Path(args[1]))
    except (TreeError, OSError) as exc:
        print(f"pr_tree: {exc}", file=sys.stderr)
        return 1
    for line in result["skipped"]:
        print(f"skipped: {line}")
    print(f"pr_tree: wrote {len(result['written'])} file(s), skipped "
          f"{len(result['skipped'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
