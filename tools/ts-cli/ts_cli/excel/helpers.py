"""Small helpers shared by the handler modules (kept apart to avoid import cycles)."""
from __future__ import annotations

import re

from ts_cli.excel import nodes as X
from ts_cli.excel import tsast as T
from ts_cli.formula_common import sql_int_digits

# A sql_*_op template: the double-quoted FIRST argument of a pass-through. Any other
# double-quoted string is a ThoughtSpot text literal (BL-365), which the parser reads; a
# single-quoted literal is skipped whole so a '"' inside it is never taken for a template.
_TEMPLATE = re.compile(r"""('(?:[^'\\]|\\.|'')*')|(\bsql_\w+_op\s*\(\s*)("[^"]*")""")


def need(tr, node: X.Call, lo: int, hi: int) -> None:
    n = len(node.args)
    if not lo <= n <= hi:
        tr.review(f"{node.name} with {n} argument(s) is outside its rule ({lo}–{hi} arguments)")


def is_range(node) -> bool:
    """True if the Excel subtree references a whole column (a range, ``Table[Col]``)."""
    return any(isinstance(n, X.Ref) and n.grain in ("column", "block") for n in X.walk(node))


def from_text(text: str) -> dict:
    """ThoughtSpot text (e.g. a ``formula_common`` helper's output) → AST, with the ONE
    ThoughtSpot parser (``mv_emit_expr.parse_formula``, BL-217). A ``sql_*_op`` template
    is swapped out first and restored as a ``template`` literal; the parser would read it
    as a text literal."""
    from ts_cli.databricks.mv_emit_expr import parse_formula

    templates: list[str] = []

    def stash(m: "re.Match") -> str:
        if m.group(1) is not None:
            return m.group(1)
        templates.append(m.group(3))
        return f"{m.group(2)}'__TPL{len(templates) - 1}__'"

    node = parse_formula(_TEMPLATE.sub(stash, text))
    for n in T.walk(node):
        if n.get("node") == "lit" and n["kind"] == "string":
            m = re.fullmatch(r"'__TPL(\d+)__'", n["value"])
            if m:
                n["kind"], n["value"] = "template", templates[int(m.group(1))]
    return node


def literal_int(node):
    """An Excel integer literal (``2``, ``-2``) as int, else None."""
    if isinstance(node, X.Num):
        return sql_int_digits(node.text)
    if isinstance(node, X.Unary) and node.op == "-" and isinstance(node.operand, X.Num):
        v = sql_int_digits(node.operand.text)
        return -v if v is not None else None
    return None


def fold(op: str, args: list) -> dict:
    out = args[0]
    for a in args[1:]:
        out = T.binop(op, out, a)
    return out


def template(sql: str) -> dict:
    """A ``sql_*_op`` template literal: printed verbatim, double-quoted."""
    return {"node": "lit", "kind": "template", "value": '"' + sql + '"'}


def graft(tree: dict, *parts: dict) -> dict:
    """``tree`` (re-parsed from text that embeds ``parts``) with each subtree that prints as a
    part replaced by the part itself, so tags on the part's nodes (``via: coerce``) survive a
    ``formula_common`` text helper."""
    texts = {T.to_text(p): p for p in parts}

    def sub(node):
        if not isinstance(node, dict):
            return node
        hit = texts.get(T.to_text(node)) if node.get("node") else None
        if hit is not None:
            return hit
        for key, value in list(node.items()):
            if isinstance(value, dict):
                node[key] = sub(value)
            elif isinstance(value, list):
                node[key] = [sub(v) if isinstance(v, dict) else
                             [sub(x) for x in v] if isinstance(v, list) else v for v in value]
        return node
    return sub(tree)
