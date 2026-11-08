"""Reference extraction and the post-translation qualification pass.

Some translators take a resolver callable (Snowflake, Databricks); others take a column
map (Tableau, DAX) or emit references unqualified (Qlik, Sisense). For the latter, the
adapter runs ``qualify_refs`` over the translator's OUTPUT, so every reference still goes
through the one recording resolver in ``context.ColumnContext``.

String literals (single- or double-quoted) are never rewritten.

The audit's catalog gate imports this module and `context` (A9's
`@parameter_formula_names` reads formulas through `split_literals`) under Python 3.9
with only PyYAML: keep both stdlib-only (`GATE_SHARED_MODULES` in
`tools/validate/tests/test_check_audit_catalog.py`).
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.formula_translate.context import ColumnContext

_QUOTED = re.compile(r"('(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\")")
# One `[field]` reference as a SCANNER must see it, so that no scan reads a function
# name, a keyword or a comment out of a column name. A name is free text: it may hold `(`,
# a quote or `[` (`[Revenue (net) [EUR]]]`), and a `]` inside it is doubled (Tableau, DAX
# and Qlik escape it that way). The scanners share it: split_literals below,
# traps._code, tableau/literals.py and the comment strippers (BL-460 review).
#
# The RESOLVERS do not: _BRACKET (bracket_refs, qualify_refs) and the converter's
# scope_columns read `[^[\]]+` / `[^\]]+`, a name with no bracket in it. A name that
# holds one is therefore never resolved: `bracketed_name` finds it first, and
# `ts formula translate` returns NEEDS_REVIEW / the converter skips the formula. How
# ThoughtSpot escapes a bracket inside `[T::col]` is unverified, so there is no safe
# output to resolve it to.
REF_GRAMMAR = r"\[(?:[^\]]|\]\])*\]"
_REF = re.compile(REF_GRAMMAR)
# A bracketed reference is code even when its name holds a quote ([Bob's Sales::x],
# BL-369): matched first at its own position so its apostrophe never opens a literal.
_QUOTED_OR_BRACKET = re.compile(rf"({REF_GRAMMAR})|" + _QUOTED.pattern)
_BRACKET = re.compile(r"\[([^\[\]]+)\]")

# Words that are never a field when they appear bare (Qlik output).
_KEYWORDS = {
    "if", "then", "else", "and", "or", "not", "true", "false", "null", "in", "is",
    "distinct", "total", "case", "when", "end",
}
# Not a call, and not the first word of the two-word function `unique count (`.
_BARE_IDENT = re.compile(
    r"(?<![\w\[.$#:'\"])([A-Za-z_][A-Za-z0-9_]*)(?![\w\]#])(?!\s*\()(?!\s+count\s*\()")


def split_literals(expr: str, brackets_are_code: bool = True) -> list[tuple[bool, str]]:
    """Split into (is_literal, text) segments.

    ``brackets_are_code`` (the default, for ThoughtSpot formula text): a ``[...]``
    reference is never a literal, even when the name inside it holds a quote (BL-369).
    Pass False for SOURCE text in a dialect where ``[`` is not a reference — SQL's
    ``v['a--b']`` holds a real literal inside the brackets (#583 review)."""
    out: list[tuple[bool, str]] = []
    pos = 0
    for m in (_QUOTED_OR_BRACKET if brackets_are_code else _QUOTED).finditer(expr):
        if brackets_are_code and m.group(1) is not None:
            continue                      # a bracketed ref: stays in the code segment
        if m.start() > pos:
            out.append((False, expr[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(expr):
        out.append((False, expr[pos:]))
    return out


def bracketed_name(expr: str) -> Optional[str]:
    """The first ``[field]`` reference outside string literals whose name holds ``[`` or
    ``]`` once a doubled ``]]`` is read as one ``]`` (``[Sales [USD]]]``,
    ``[Profit]] Margin]``), or None. No resolver here can read such a name (see
    REF_GRAMMAR), so a caller refuses the formula rather than resolve a piece of it."""
    for lit, seg in split_literals(expr):
        if lit:
            continue
        for m in _REF.finditer(seg):
            name = m.group(0)[1:-1].replace("]]", "]")
            if "[" in name or "]" in name:
                return m.group(0)
    return None


def _map_code(expr: str, fn) -> str:
    return "".join(seg if lit else fn(seg) for lit, seg in split_literals(expr))


def bracket_refs(expr: str) -> list[str]:
    """Every ``[name]`` in ``expr`` outside string literals, in order, deduplicated."""
    seen: dict[str, None] = {}
    for lit, seg in split_literals(expr):
        if not lit:
            for m in _BRACKET.finditer(seg):
                seen.setdefault(m.group(1).strip(), None)
    return list(seen)


def qualify_refs(expr: str, ctx: ColumnContext, *, bare_idents: bool = False,
                 parameters: Optional[set[str]] = None,
                 placeholder_tables: Optional[set[str]] = None) -> str:
    """Resolve every column reference in translated ``expr`` through ``ctx``.

    - ``[T::C]`` → ``ctx.resolve(C, table_hint=T)``; a ``T`` in ``placeholder_tables``
      is a sentinel the adapter itself injected, so it is not passed as a hint.
    - ``[C]`` → ``ctx.resolve(C)``, unless ``C`` is a parameter or a ``formula_`` id-ref.
    - with ``bare_idents`` (Qlik), a bare identifier that is not a keyword or a call.
    """
    parameters = parameters or set()
    placeholder_tables = placeholder_tables or set()

    def _bracket(m: re.Match) -> str:
        inner = m.group(1).strip()
        if inner.startswith("formula_"):
            return m.group(0)
        if "::" in inner:
            t, c = inner.split("::", 1)
            hint = None if t in placeholder_tables else t.strip()
            return ctx.resolve(c.strip(), table_hint=hint)
        if inner in parameters:
            return ctx.record_parameter(inner)
        return ctx.resolve(inner)

    def _seg(seg: str) -> str:
        # Protect bracketed refs from the bare-identifier pass by resolving them first
        # into tokens, then restoring.
        out: list[str] = []
        pos = 0
        for m in _BRACKET.finditer(seg):
            out.append(_bare(seg[pos:m.start()]) if bare_idents else seg[pos:m.start()])
            out.append(_bracket(m))
            pos = m.end()
        tail = seg[pos:]
        out.append(_bare(tail) if bare_idents else tail)
        return "".join(out)

    def _bare(text: str) -> str:
        def repl(m: re.Match) -> str:
            word = m.group(1)
            if word.lower() in _KEYWORDS:
                return word
            return ctx.resolve(word)
        return _BARE_IDENT.sub(repl, text)

    return _map_code(expr, _seg)
