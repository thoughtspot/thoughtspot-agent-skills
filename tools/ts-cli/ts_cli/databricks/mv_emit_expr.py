"""TS-formula tokenizer + recursive-descent parser → dict-AST (reverse direction).

Pure: stdlib only. No I/O. Vendored into the Genie notebook.
"""
from __future__ import annotations

import re


class UntranslatableError(Exception):
    """A ThoughtSpot formula construct has no deterministic Databricks-SQL translation."""


_KW = {"if", "then", "else", "and", "or", "not", "in", "between",
       "null", "true", "false"}

# order matters: multi-char ops before single-char
_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<bracket>\[[^\]]*\])
  | (?P<string>'(?:[^']|'')*')
  | (?P<number>\d+\.\d+|\d+)
  | (?P<op>!=|<=|>=|[(),+\-*/=<>{}])
  | (?P<ident>[A-Za-z_][A-Za-z0-9_ ]*?(?=\s*\())
  | (?P<bareident>[A-Za-z_][A-Za-z0-9_]*)
""", re.VERBOSE)


def tokenize(expr: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    i = 0
    n = len(expr)
    while i < n:
        m = _TOKEN_RE.match(expr, i)
        if not m or m.end() == i:
            raise UntranslatableError(f"unrecognized character at {i!r}: {expr[i:i+8]!r}")
        i = m.end()
        kind = m.lastgroup
        text = m.group()
        if kind == "ws":
            continue
        if kind in ("ident", "bareident"):
            word = text.strip()
            if word.lower() in _KW:
                toks.append(("kw", word.lower()))
            else:
                toks.append(("ident", word))
        else:
            toks.append((kind, text))
    return toks
