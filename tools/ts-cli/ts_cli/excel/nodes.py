"""Excel formula AST node types.

A reference node says WHAT it names and at which GRAIN:

- ``row``    — one row's value of a column: ``[@Col]``, ``Table[@Col]``, ``[#This Row]``, an
               A1 cell (``B2``) — the Excel map's E5 "a cell is a row's value";
- ``column`` — the whole column: ``Table[Col]``, ``[Col]``, ``B:B``, ``B2:B100``, Sheets'
               ``B2:B`` — E5 "a range is a column", aggregated when a reducer consumes it;
- ``block``  — a range over several columns (``A1:C9``, ``A:C``): parsed, so a structural
               function (QUERY) can be reported for what it is, and refused when translated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union


@dataclass
class Num:
    text: str


@dataclass
class Str:
    value: str


@dataclass
class Bool:
    value: bool


@dataclass
class Err:
    text: str  # #DIV/0!, #N/A, ...


@dataclass
class Missing:
    """An omitted argument: ``IF(a,,b)``."""


@dataclass
class Ref:
    column: str
    grain: str                      # "row" | "column"
    table: Optional[str] = None     # Excel Table name, when the reference names one
    kind: str = "structured"        # "structured" | "a1" | "name"
    raw: str = ""
    sheet: Optional[str] = None
    absolute: bool = False


@dataclass
class Unary:
    op: str            # "-" | "+"
    operand: "Node"


@dataclass
class Percent:
    operand: "Node"


@dataclass
class Binary:
    op: str            # + - * / ^ & = <> < <= > >=
    left: "Node"
    right: "Node"


@dataclass
class Call:
    name: str          # upper case, ``_xlfn.`` stripped: "SUM", "STDEV.S"
    args: list = field(default_factory=list)


@dataclass
class Array:
    rows: list         # list[list[Node]]


Node = Union[Num, Str, Bool, Err, Missing, Ref, Unary, Percent, Binary, Call, Array]


def walk(node):
    """Every node in ``node``'s subtree, pre-order."""
    yield node
    if isinstance(node, (Unary, Percent)):
        yield from walk(node.operand)
    elif isinstance(node, Binary):
        yield from walk(node.left)
        yield from walk(node.right)
    elif isinstance(node, Call):
        for a in node.args:
            yield from walk(a)
    elif isinstance(node, Array):
        for row in node.rows:
            for a in row:
                yield from walk(a)
