"""Per-run memo for lookups the derived fields would otherwise recompute per item.

A derived field is a function of one item, so a lookup over the whole context (every
Model formula, for H8/H9) or over one Model (its formula graph, for P17) was rebuilt for
every item it answered — quadratic in the size of the context: H8+H9 took ~9.5s on
8,000 Model formulas x 6,000 Answer formulas, where the legacy checks, building each
lookup once, took ~5ms.

`cached(key, owner, compute, *args)` returns `compute(*args)`, computed once per
`(key, owner)` for the length of a run (`engine.run.run_rules` / `run_rule` open one with
`run_scope()`). `owner` is the object the lookup is about — the AuditContext for a
context-wide lookup, a Model body for a per-Model one — and is kept referenced by the
memo, so its `id` cannot be reused within the run. Nothing outlives a run, so a context
changed between two runs is read afresh. Outside a run (a field called directly) and
under `disabled()`, every call computes.

A cached value is shared by every caller in the run: callers must not mutate it.

Kept importable on Python 3.9 with only the standard library (the catalog gate imports
the derived-field modules that use it).
"""
from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

_RUN: "contextvars.ContextVar[Optional[Dict[Tuple[str, int], Tuple[Any, Any]]]]" = \
    contextvars.ContextVar("ts_audit_run_memo", default=None)
_OFF: "contextvars.ContextVar[bool]" = contextvars.ContextVar("ts_audit_memo_off",
                                                               default=False)


@contextlib.contextmanager
def run_scope() -> Iterator[None]:
    """One run's memo. Nested scopes share the outermost one."""
    if _RUN.get() is not None:
        yield
        return
    token = _RUN.set({})
    try:
        yield
    finally:
        _RUN.reset(token)


@contextlib.contextmanager
def disabled() -> Iterator[None]:
    """Compute every lookup afresh, even inside a run (tests compare both ways)."""
    token = _OFF.set(True)
    try:
        yield
    finally:
        _OFF.reset(token)


def cached(key: str, owner: Any, compute: Callable[..., Any], *args: Any) -> Any:
    """`compute(*args)`, once per `(key, owner)` within the current run."""
    memo = _RUN.get()
    if memo is None or _OFF.get():
        return compute(*args)
    slot = (key, id(owner))
    if slot not in memo:
        memo[slot] = (owner, compute(*args))
    return memo[slot][1]
