"""TS-formula tokenizer + recursive-descent parser → dict-AST (reverse direction).

Pure: stdlib only. No I/O. Vendored into the Genie notebook.
"""
from __future__ import annotations

import re

# UntranslatableError's canonical home is ts_cli/formula_common.py (BL-063
# PR 14) — mv_sql.py (the forward direction) raises the same exception for
# the same concept, and vendoring both into one Genie-notebook namespace
# would otherwise define the class twice under one name. Re-exported here so
# existing `from ts_cli.databricks.mv_emit_expr import UntranslatableError`
# call sites are unaffected.
from ts_cli.formula_common import UntranslatableError


_KW = {"if", "then", "else", "and", "or", "not", "in", "between",
       "null", "true", "false"}

# order matters: multi-char ops before single-char. Named _FORMULA_TOKEN_RE
# (not _TOKEN_RE) to avoid an accidental top-level name clash with
# mv_sql.py's own (differently-shaped, SQL-grammar) _TOKEN_RE when both
# modules are vendored into one Genie-notebook namespace (BL-063 PR 14) —
# these tokenize two different grammars and are not the same concept, unlike
# UntranslatableError above, so they are renamed rather than unified.
_FORMULA_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<bracket>\[[^\]]*\])
  | (?P<string>'(?:[^']|'')*')
  | (?P<number>\d+\.\d+|\d+)
  | (?P<op>!=|<=|>=|[(),+\-*/=<>{}])
  | (?P<ident>[A-Za-z_][A-Za-z0-9_ ]*?(?=\s*\())
  | (?P<bareident>[A-Za-z_][A-Za-z0-9_]*)
""", re.VERBOSE)


def tokenize_formula(expr: str) -> list[tuple[str, str]]:
    """Tokenize ThoughtSpot formula text. Named `tokenize_formula` (not
    `tokenize`) to avoid an accidental top-level name clash with mv_sql.py's
    own `tokenize` (SQL grammar) when both modules are vendored into one
    Genie-notebook namespace (BL-063 PR 14) — see `_FORMULA_TOKEN_RE`."""
    toks: list[tuple[str, str]] = []
    i = 0
    n = len(expr)
    while i < n:
        m = _FORMULA_TOKEN_RE.match(expr, i)
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


class _P:
    def __init__(self, toks: list[tuple[str, str]]):
        self.toks = toks
        self.i = 0

    def peek(self) -> tuple[str | None, str | None]:
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def next(self) -> tuple[str, str]:
        if self.i >= len(self.toks):
            raise UntranslatableError("unexpected end of formula")
        t = self.toks[self.i]
        self.i += 1
        return t

    def eat(self, kind: str, text: str | None = None) -> tuple[str, str]:
        k, t = self.next()
        if k != kind or (text is not None and t != text):
            raise UntranslatableError(f"expected {kind} {text!r}, got {k} {t!r}")
        return k, t


def parse_formula(expr: str) -> dict:
    p = _P(tokenize_formula(expr))
    node = _parse_or(p)
    if p.i != len(p.toks):
        raise UntranslatableError(f"trailing tokens: {p.toks[p.i:]!r}")
    return node


_CMP = {"=", "!=", "<", "<=", ">", ">="}


def _parse_or(p):
    left = _parse_and(p)
    while p.peek() == ("kw", "or"):
        p.next(); left = {"node": "binop", "op": "or", "left": left, "right": _parse_and(p)}
    return left


def _parse_and(p):
    left = _parse_cmp(p)
    while p.peek() == ("kw", "and"):
        p.next(); left = {"node": "binop", "op": "and", "left": left, "right": _parse_cmp(p)}
    return left


def _parse_cmp(p):
    left = _parse_add(p)
    k, t = p.peek()
    if k == "op" and t in _CMP:
        p.next(); return {"node": "binop", "op": t, "left": left, "right": _parse_add(p)}
    if (k, t) == ("kw", "in"):
        return _parse_in(p, left)
    if (k, t) == ("kw", "between"):
        return _parse_between(p, left)
    return left


def _parse_in(p, left):
    p.eat("kw", "in")
    p.eat("op", "(")
    args = [left, _parse_or(p)]
    while p.peek() == ("op", ","):
        p.next(); args.append(_parse_or(p))
    p.eat("op", ")")
    return {"node": "call", "fn": "in", "args": args}


def _parse_between(p, left):
    p.eat("kw", "between")
    lo = _parse_add(p)
    p.eat("kw", "and")
    hi = _parse_add(p)
    return {"node": "call", "fn": "between", "args": [left, lo, hi]}


def _parse_add(p):
    left = _parse_mul(p)
    while p.peek()[0] == "op" and p.peek()[1] in ("+", "-"):
        op = p.next()[1]; left = {"node": "binop", "op": op, "left": left, "right": _parse_mul(p)}
    return left


def _parse_mul(p):
    left = _parse_unary(p)
    while p.peek()[0] == "op" and p.peek()[1] in ("*", "/"):
        op = p.next()[1]; left = {"node": "binop", "op": op, "left": left, "right": _parse_unary(p)}
    return left


def _parse_unary(p):
    k, t = p.peek()
    if (k, t) == ("kw", "not"):
        p.next(); return {"node": "unop", "op": "not", "operand": _parse_unary(p)}
    if (k, t) == ("op", "-"):
        p.next(); return {"node": "unop", "op": "-", "operand": _parse_unary(p)}
    return _parse_primary(p)


def _parse_primary(p):
    k, t = p.peek()
    if (k, t) == ("kw", "if"):
        return _parse_ifelse(p)
    if k == "op" and t == "(":
        p.next(); node = _parse_or(p); p.eat("op", ")"); return node
    if k == "op" and t == "{":
        return _parse_lodset(p)
    if k == "bracket":
        p.next(); return _bracket_node(t)
    if k == "string":
        p.next(); return {"node": "lit", "kind": "string", "value": t}
    if k == "number":
        p.next(); return {"node": "lit", "kind": "number", "value": t}
    if (k, t) == ("kw", "null"):
        p.next(); return {"node": "lit", "kind": "null", "value": "null"}
    if (k, t) in (("kw", "true"), ("kw", "false")):
        p.next(); return {"node": "lit", "kind": "bool", "value": t}
    if k == "ident":
        return _parse_call(p)
    raise UntranslatableError(f"unexpected token {k} {t!r}")


def _parse_call(p):
    name = p.next()[1].lower()
    p.eat("op", "(")
    args = []
    if p.peek() != ("op", ")"):
        args.append(_parse_or(p))
        while p.peek() == ("op", ","):
            p.next(); args.append(_parse_or(p))
    p.eat("op", ")")
    return {"node": "call", "fn": name, "args": args}


def _parse_ifelse(p):
    branches = []
    p.eat("kw", "if")
    cond = _parse_or(p); p.eat("kw", "then"); val = _parse_or(p)
    branches.append([cond, val])
    els = None
    if p.peek() == ("kw", "else"):
        p.next(); els = _parse_or(p)
    return {"node": "ifelse", "branches": branches, "else": els}


def _parse_lodset(p):
    p.eat("op", "{")
    cols = [_parse_or(p)]
    while p.peek() == ("op", ","):
        p.next(); cols.append(_parse_or(p))
    p.eat("op", "}")
    return {"node": "lodset", "cols": cols}


def _bracket_node(text: str) -> dict:
    inner = text[1:-1]
    if "::" in inner:
        table, col = inner.split("::", 1)
        return {"node": "col", "table": table.strip(), "column": col.strip()}
    return {"node": "ref", "name": inner.strip()}
