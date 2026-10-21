#!/usr/bin/env python3
"""The published-name denylist: words and two-word names from published fantasy works that a
quest must not use. Names stay generic fantasy ("White Peaks"), never a published work's.

The list is stored as hashes (denylist.txt), so the names themselves are never committed. To add
names, pipe them in, one per line; nothing is echoed back:

    python3 tools/quest/denylist.py add < names.txt

A build fails on a hit and reports the word from our own content, never the list.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
DENYLIST = HERE / "denylist.txt"
SCANNED = (".yaml", ".yml", ".md", ".txt", ".py", ".json", ".tmj")
_SALT = b"quest-denylist\0"


def words(text: str) -> list[str]:
    """Lowercased, accents stripped, letters and digits only."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.findall(r"[a-z0-9]+", plain)


def digest(phrase: str) -> str:
    return hashlib.sha256(_SALT + " ".join(words(phrase)).encode("ascii")).hexdigest()[:20]


def load(path: pathlib.Path = DENYLIST) -> set[str]:
    if not path.is_file():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}


def hits(text: str, hashes: set[str]) -> list[str]:
    """The words, and two-word names, in `text` that are on the list."""
    ws = words(text)
    found = [w for w in ws if digest(w) in hashes]
    found += [f"{a} {b}" for a, b in zip(ws, ws[1:]) if digest(f"{a} {b}") in hashes]
    return sorted(set(found))


def scan(folder: pathlib.Path, hashes: set[str] | None = None) -> list[str]:
    """Errors for every listed word in the folder's text files (content, strings, maps, art, promo)."""
    hashes = load() if hashes is None else hashes
    errors = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and (path.suffix in SCANNED or "art" in path.relative_to(folder).parts):
            for word in hits(path.read_text(encoding="utf-8", errors="ignore"), hashes):
                errors.append(f"{path.relative_to(folder)}: {word!r} is a name from a published work "
                              f"(denylist.txt); use a generic fantasy name")
    return errors


def add(lines: list[str], path: pathlib.Path = DENYLIST) -> int:
    hashes = load(path)
    new = {digest(line) for line in lines if words(line) and len(words(line)) <= 2} - hashes
    header = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#")] if path.is_file() else []
    path.write_text("\n".join(header + sorted(hashes | new)) + "\n", encoding="utf-8")
    return len(new)


if __name__ == "__main__":
    if sys.argv[1:] != ["add"]:
        sys.exit("usage: python3 tools/quest/denylist.py add < names.txt   (one name per line)")
    print(f"added {add(sys.stdin.read().splitlines())} hash(es) to {DENYLIST.name}")
