"""Which Sisense filters ``build-liveboard --target-model`` can carry, and how (pure, no I/O).

The rule is an allowlist: a filter is carried only when every part of it is something this
module reads and has verified. Anything else -- an unrecognised filter key, a relative date, a
date value whose day boundary is unknown, a value search quoting has not been verified for --
comes back as a reason, which the caller reports NEEDS REVIEW. A filter is never carried on a
guess, because a wrong filter still returns numbers and nothing downstream can tell.

Live-verified search behaviour this relies on (26.9): repeated ``[X] = v`` is ORed, repeated
``[X] != v`` ANDed; ``in (...)`` / ``not in (...)`` are ignored silently; ``'`` escaped as
``\\'`` matches; ``top N`` / ``bottom N`` rank by the answer's measure.
"""
from __future__ import annotations

from typing import Optional

from ts_cli.sisense.answers import _range_generic_filter

_RANGE_OPS = (("from", ">="), ("fromNotEqual", ">"), ("to", "<="), ("toNotEqual", "<"), ("equals", "="))
_COARSE_LEVELS = ("years", "quarters", "months", "weeks")
_VALUE_KINDS = ("member", "exclude", "range")


def literal(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "\\'") + "'"


def search_filter(kind: str, name: str, raw: dict, vals: list):
    """One carried Sisense filter on a resolved column -> search fragment, or None."""
    if kind == "member" and vals:
        return " ".join(f"[{name}] = {literal(v)}" for v in vals)
    if kind == "exclude" and vals:
        return " ".join(f"[{name}] != {literal(v)}" for v in vals)
    if kind == "range":
        parts = [f"[{name}] {op} {literal(raw[k])}" for k, op in _RANGE_OPS if raw.get(k) is not None]
        return " ".join(parts) or None
    return None


def is_all(sf: dict) -> bool:
    """Sisense `all`: no condition, at any kind or level."""
    return bool((sf.get("raw") or {}).get("all"))


def _is_date(sf: dict) -> bool:
    return sf.get("datatype") == "datetime" or bool(sf.get("level"))


def date_problem(sf: dict, name: str, target) -> Optional[str]:
    """Why a date filter's values cannot be compared with ``[name]``, or None.

    Only a days-level value on a DATE column is carried: a coarser level's members are period
    starts (``2024-01-01`` for 2024), a finer level is not a day, no level leaves the grain
    unknown, and on a DATE_TIME column a day value matches midnight only."""
    if not _is_date(sf) or sf.get("kind") not in _VALUE_KINDS:
        return None
    level = (sf.get("level") or "").lower()
    if not level:
        return "a date filter with no level: its values could be days, months or years"
    if level in _COARSE_LEVELS:
        return f"its values are {level} periods, which a comparison on the date would read as single days"
    if level != "days":
        return f"it is at the {level} level, finer than the days a date comparison reads"
    dtype = target.data_type(name)
    if dtype == "DATE":
        return None
    if dtype is None:
        return (f"[{name}] could not be confirmed as a DATE column (export the Model with "
                "--associated so the Table types are known)")
    return f"[{name}] is a {dtype} column: a day value matches midnight only, and a range end drops the rest of that day"


def value_problem(sf: dict) -> Optional[str]:
    """Why a filter's values cannot be written into a search, or None."""
    if any("\\" in str(v) for v in sf.get("values") or []):
        return "a value contains a backslash, which search quoting has not been verified for"
    return None


def common_problem(sf: dict, name: str, target) -> Optional[str]:
    """Reasons shared by widget filters and chips (unrecognised keys, dates)."""
    if sf.get("unsupported"):
        return "it carries filter settings this converter does not read: " + ", ".join(sf["unsupported"])
    return date_problem(sf, name, target)


def widget_filter(sf: dict, name: str, target) -> tuple:
    """A widget filter on resolved ``name`` -> (search fragment | None, problem | None)."""
    problem = common_problem(sf, name, target) or value_problem(sf)
    if problem:
        return None, problem
    frag = search_filter(sf.get("kind"), name, sf.get("raw") or {}, sf.get("values") or [])
    if frag:
        return frag, None
    return None, f"its {sf.get('kind')} condition has no deterministic search form"


def _mixed_range(raw: dict) -> bool:
    lo_in, lo_ex = raw.get("from") is not None, raw.get("fromNotEqual") is not None
    hi_in, hi_ex = raw.get("to") is not None, raw.get("toNotEqual") is not None
    return (lo_in or lo_ex) and (hi_in or hi_ex) and (lo_in != hi_in)


def chip_condition(sf: dict, chip: dict, name: str, target) -> Optional[str]:
    """Set a dashboard filter's condition on its chip; -> why it is not carried exactly, or None.
    A chip with no condition is unfiltered, so a reason always goes to the report."""
    if is_all(sf):
        return None
    problem = common_problem(sf, name, target)
    if problem:
        return problem
    kind, vals = sf.get("kind"), [str(v) for v in sf.get("values") or []]
    if kind in ("member", "exclude") and vals:
        chip.update(oper="in" if kind == "member" else "not in", values=vals)
        return None
    gf = _range_generic_filter(sf.get("raw")) if kind == "range" else None
    if gf:
        chip["generic_filter"] = gf
        if _mixed_range(sf.get("raw") or {}):
            return "one bound is inclusive and the other exclusive; the chip includes both ends"
        return None
    return f"its {kind} condition is not carried, so the chip is unfiltered"


def top_n(widget: dict, measures: list) -> tuple:
    """A widget's top/bottom-N -> (top N | None, extra search fragment | None, problems).

    Carried only when N is a whole number and the ranking measure (``by``) is the widget's only
    measure, since ThoughtSpot ranks by the answer's measure. ``bottom N`` is carried as is."""
    ranks = [sf for sf in widget.get("filters", []) if sf.get("kind") == "top_n"]
    if not ranks:
        return None, None, []
    if len(ranks) > 1:
        return None, None, ["more than one top/bottom ranking on the widget is not carried"]
    sf = ranks[0]
    op, raw = sf.get("operator"), sf.get("raw") or {}
    try:
        n = int(str((sf.get("values") or [""])[0]))
    except ValueError:
        return None, None, [f"{op} {sf.get('values')} is not a whole number, so the ranking is not carried"]
    if sf.get("unsupported"):
        return None, None, ["the ranking carries settings this converter does not read: " + ", ".join(sf["unsupported"])]
    by = raw.get("by") or {}
    if len(measures) != 1 or not _same_measure(by, measures[0]):
        return None, None, [f"{op} {n} ranks by {by.get('dim') or by.get('formula') or 'an unknown measure'}, "
                            "which is not the widget's only measure, so the ranking is not carried"]
    return (n, None, []) if op == "top" else (None, f"bottom {n}", [])


def _same_measure(by: dict, f: dict) -> bool:
    if by.get("formula") or f.get("formula"):
        return False
    return by.get("dim") == f.get("dim") and (by.get("agg") or "").lower() == (f.get("agg") or "").lower()
