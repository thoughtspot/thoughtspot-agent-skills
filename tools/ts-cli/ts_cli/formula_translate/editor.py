"""The formula-EDITOR form of a translated formula (user's domain guidance, 2026-10-06).

Two forms of every formula are emitted:

- **TML form** (``formula``): bracketed references — ``[TABLE::col]`` for a column,
  ``[formula_<id>]`` for another formula. Brackets are REQUIRED in TML: on se-thoughtspot
  (VALIDATE_ONLY import, 2026-10-06) ``[formula_Total_Days] * 2`` and
  ``day_number_of_week ( [EFFECTIVE_DATE] )`` were accepted, while the bare
  ``Total_Days * 2``, the display-name ``[Total_Days] * 2`` and the bare
  ``day_number_of_week ( EFFECTIVE_DATE )`` were rejected.
- **Editor form** (``formula_editor``): for pasting into the ThoughtSpot formula editor.
  References go by display name and WITHOUT brackets (``Total_Days - floor ( Total_Days / 7 )``),
  because brackets make names hard to double-click-select in the editor. A name that is not
  a bare identifier (it has a space, say) keeps its brackets — ``[Order Date]`` — since it
  cannot be referenced bare. This follows the user's ThoughtSpot domain guidance: the
  editor's parser is not reachable through the API, so ``--validate`` does not cover it.

Names this tool coins use ``_`` instead of spaces (default ``Translated_Formula``), so the
editor and TML forms share one name.
"""
from __future__ import annotations

import re

from ts_cli.formula_translate.context import PRIMARY_KEY_PLACEHOLDER, ColumnContext
from ts_cli.formula_translate.refs import split_literals

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BRACKET = re.compile(r"\[([^\[\]]+)\]")

EDITOR_SOURCE = ("editor form: references by name without brackets, per ThoughtSpot "
                 "domain guidance — the formula editor is not reachable through the API, "
                 "so --validate checks only the TML form")
SPACES_NOTE = ("names with spaces or other characters stay in brackets in the editor form "
               "({names}); renaming them with underscores in the Model would allow bare "
               "references")


def coined(name: str) -> str:
    """A name this tool coins: spaces → ``_``."""
    return re.sub(r"\s+", "_", name.strip())


def _editor_name(inner: str, ctx: ColumnContext) -> str:
    target = f"[{inner}]"
    spec = ctx.spec_for_target(target)
    if spec is not None and spec.display_name:
        return spec.display_name
    for ref in ctx.references:
        if ref.target == target:
            if ref.kind == "primary_key":
                return PRIMARY_KEY_PLACEHOLDER
            src = ref.source.strip("[]")
            return src.split(".", 1)[1] if (ref.placeholder and "." in src
                                            and ctx.level == 0) else src
    if inner.startswith("formula_"):
        return inner[len("formula_"):]
    return inner.split("::", 1)[-1]


def editor_form(expr: str, ctx: ColumnContext) -> tuple[str, list[str]]:
    """(editor-form formula, notes)."""
    bracketed: list[str] = []

    def repl(m: re.Match) -> str:
        name = _editor_name(m.group(1).strip(), ctx)
        if _IDENT.match(name):
            return name
        if name not in bracketed and name != PRIMARY_KEY_PLACEHOLDER:
            bracketed.append(name)
        return f"[{name}]"

    out = "".join(seg if lit else _BRACKET.sub(repl, seg) for lit, seg in split_literals(expr))
    notes = [EDITOR_SOURCE]
    if bracketed:
        notes.append(SPACES_NOTE.format(names=", ".join(f"'{n}'" for n in bracketed)))
    return out, notes
