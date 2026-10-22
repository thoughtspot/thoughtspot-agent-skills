"""Message templates: a rule's `message` (and a group's `name`) rendered per finding.

Python `str.format` syntax. Each mode supplies its placeholder values (see
catalog_expr.MODE_PLACEHOLDERS); a name the mode does not supply is resolved as a
field path on the item (`{properties.column_type}`, `{@is_indexed}`), which is how an
`each` message reads any field. Indexing a supplied value works (`{key[0]}`).

Lists of names render through `NameList`'s format spec:

    {names}          first 5, then " (+N more)"     — the default
    {names:head3}    first 3, nothing about the rest
    {names:head3+}   first 3, then " (+N more)"
    {names:all}      every one
"""
from __future__ import annotations

import re
import string
from typing import Any, Dict, Optional

from ts_cli.audit.engine import fields

_HEAD = re.compile(r"^head(\d+)(\+?)$")
_FIRST = re.compile(r"[^.\[]*")  # a placeholder's leading name, before `.x` / `[i]`
DEFAULT_SHOWN = 5


class NameList(list):
    """A list of names whose format spec chooses how many to show."""

    def __format__(self, spec: str) -> str:
        if spec == "all":
            return ", ".join(map(str, self))
        if not spec:
            return self.head(DEFAULT_SHOWN, more=True)
        m = _HEAD.match(spec)
        if not m:
            raise ValueError(f"unknown name-list format '{spec}' (use headN, headN+ or all)")
        return self.head(int(m.group(1)), more=bool(m.group(2)))

    def head(self, n: int, more: bool) -> str:
        shown = ", ".join(map(str, self[:n]))
        rest = len(self) - n
        return shown + (f" (+{rest} more)" if more and rest > 0 else "")


class Key(tuple):
    """A composite group key: renders dot-joined (`SF.ORDERS`), indexes as a tuple."""

    def __format__(self, spec: str) -> str:
        return format(".".join(map(str, self)), spec)


class _Formatter(string.Formatter):
    def __init__(self, values: Dict[str, Any], item: Optional[dict], ctx: Any):
        super().__init__()
        self.values, self.item, self.ctx = values, item, ctx

    def get_field(self, field_name, args, kwargs):
        if _FIRST.match(field_name).group(0) in self.values:
            return super().get_field(field_name, args, kwargs)
        if self.item is None:
            raise KeyError(f"unknown placeholder '{field_name}'")
        return fields.get(self.item, field_name, self.ctx), field_name

    def get_value(self, key, args, kwargs):
        return self.values[key]


def render(template: str, values: Dict[str, Any], item: Optional[dict] = None,
           ctx: Any = None) -> str:
    """`template` with mode `values`, falling back to `item` field paths."""
    return _Formatter(values, item, ctx).format(template)
