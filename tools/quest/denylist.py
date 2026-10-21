#!/usr/bin/env python3
"""The published-name denylist: words and two-word names from published fantasy works that a
quest must not use. Names stay generic fantasy ("White Peaks"), never a published work's.

The list is stored as hashes (denylist.txt), so the names themselves are never committed. To add
names, pipe them in, one per line; nothing is echoed back:

    python3 tools/quest/denylist.py add < names.txt

Keep names.txt outside the repo (or delete it after). Each line is one name of one or two words;
longer lines are refused, not silently dropped. A build fails on a hit and reports the word from
our own content, never the list.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
DENYLIST = HERE / "denylist.txt"
BINARY = {".png", ".gif", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".webm",
          ".mp3", ".ogg", ".wav", ".pdf", ".zip"}  # everything else is read as text
_SALT = b"quest-denylist\0"


APOSTROPHES = re.compile("['\u2019\u02bc]")


def words(text: str, apostrophe: str = "") -> list[str]:
    """Lowercased, accents stripped, letters and digits only. Apostrophes are removed ("Zqxvorn's"
    is one word, as add() stores a name) or, with apostrophe=" ", split ("Zqxvorn" and "s"); hits()
    reads text both ways, so a listed name is caught in possessives and contractions too."""
    folded = unicodedata.normalize("NFKD", text)
    plain = APOSTROPHES.sub(apostrophe, folded).encode("ascii", "ignore").decode("ascii").lower()
    return re.findall(r"[a-z0-9]+", plain)


def digest(phrase: str) -> str:
    return hashlib.sha256(_SALT + " ".join(words(phrase)).encode("ascii")).hexdigest()[:20]


HASH = re.compile(r"[0-9a-f]{20}")


def load(path: pathlib.Path = DENYLIST) -> set[str]:
    """The hashes. Fails closed: a missing file, or a line that isn't a hash (a name typed in by
    hand would never match anything, and would itself be committed), raises."""
    if not path.is_file():
        raise FileNotFoundError(f"{path.name} is missing; the published-name check can't run without it")
    entries = [(n, line.strip()) for n, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
               if line.strip() and not line.strip().startswith("#")]
    bad = [n for n, line in entries if not HASH.fullmatch(line)]
    if bad:
        raise ValueError(f"{path.name}: lines {bad} are not hashes; add names with denylist.py add, never by hand")
    if not entries:
        raise ValueError(f"{path.name} holds no hashes; the published-name check can't run without them")
    return {line for _, line in entries}


def hits(text: str, hashes: set[str]) -> list[str]:
    """The words, and two-word names, in `text` that are on the list."""
    found = []
    for ws in (words(text), words(text, " ")):
        found += [w for w in ws if digest(w) in hashes]
        found += [f"{a} {b}" for a, b in zip(ws, ws[1:]) if digest(f"{a} {b}") in hashes]
    return sorted(set(found))


def scan(folder: pathlib.Path, hashes: set[str] | None = None) -> list[str]:
    """Errors for every listed word in every file of the folder except known binaries (content,
    strings, maps, art with or without a suffix, the page, promo scripts)."""
    hashes = load() if hashes is None else hashes
    errors = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() not in BINARY and "__pycache__" not in path.parts:
            for word in hits(path.read_text(encoding="utf-8", errors="ignore"), hashes):
                errors.append(f"{path.relative_to(folder)}: {word!r} is a name from a published work "
                              f"(denylist.txt); use a generic fantasy name")
    return errors


def add(lines: list[str], path: pathlib.Path = DENYLIST) -> int:
    long = [n for n, line in enumerate(lines, 1) if len(words(line)) > 2]
    if long:
        raise ValueError(f"lines {long} have more than two words; add one or two words per line")
    hashes = load(path) if path.is_file() and any(
        x.strip() and not x.strip().startswith("#") for x in path.read_text(encoding="utf-8-sig").splitlines()) else set()
    new = {digest(line) for line in lines if words(line)} - hashes
    header = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("#")] if path.is_file() else []
    path.write_text("\n".join(header + sorted(hashes | new)) + "\n", encoding="utf-8")
    return len(new)


if __name__ == "__main__":
    if sys.argv[1:] != ["add"]:
        sys.exit("usage: python3 tools/quest/denylist.py add < names.txt   (one name per line)")
    print(f"added {add(sys.stdin.read().splitlines())} hash(es) to {DENYLIST.name}")
