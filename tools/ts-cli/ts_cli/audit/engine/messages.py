"""Message templates: a rule's `message` (and a group's `name`) rendered per finding.

Python `str.format` syntax. Each mode supplies its placeholder values (see
catalog_expr.MODE_PLACEHOLDERS). Given an `item` (mode `each`), two more forms read
the item: `{obj.<path>}` — a field of the object itself (`{obj.properties.column_type}`,
`{obj.name}`) — and `{@name}`, a derived field. Any other name raises KeyError: a typo
must never render as "None". Indexing a supplied value works (`{key[0]}`).

A rule's `message` is one template, or one per severity (`{by_severity: {SEVERITY:
template}}`, catalog_forms.py): `template(rule, severity)` picks the one a finding
renders, and raises — naming the rule — when its severity has none.

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
        head = _FIRST.match(field_name).group(0)
        if head in self.values:
            return super().get_field(field_name, args, kwargs)
        if self.item is not None and head == "obj":
            rest = field_name[len("obj"):].lstrip(".")
            return fields.walk(self.item.get("obj"), rest), field_name
        if self.item is not None and head.startswith("@"):
            return fields.get(self.item, field_name, self.ctx), field_name
        raise KeyError(f"unknown placeholder '{field_name}'")

    def get_value(self, key, args, kwargs):
        return self.values[key]


def template(rule: Any, severity: str) -> str:
    """The message template for a finding of `severity` under `rule`'s (effective)
    message: the message itself, or its `by_severity` entry for that severity."""
    message = rule.message
    if not isinstance(message, dict):
        return message
    templates = message.get("by_severity") or {}
    if severity not in templates:
        raise ValueError(f"{rule.id}: no message for severity {severity} "
                         f"(by_severity has {', '.join(templates) or 'none'})")
    return templates[severity]


def render(template: str, values: Dict[str, Any], item: Optional[dict] = None,
           ctx: Any = None) -> str:
    """`template` with mode `values`, falling back to `item` field paths."""
    return _Formatter(values, item, ctx).format(template)
