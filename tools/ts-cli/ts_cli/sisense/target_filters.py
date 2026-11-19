"""Which Sisense filters ``build-liveboard --target-model`` can carry, and how (pure, no I/O).

The rule is an allowlist: a filter is carried only when every part of it is something this
module reads and has verified. Anything else -- an unrecognised filter key, a relative date, a
date value whose day boundary is unknown, a value search quoting has not been verified for --
comes back as a reason, which the caller reports NEEDS REVIEW. A filter is never carried on a
guess, because a wrong filter still returns numbers and nothing downstream can tell.

Live-verified search behaviour this relies on (26.9): repeated ``[X] = v`` is ORed, repeated
``[X] != v`` ANDed; ``in (...)`` / ``not in (...)`` are ignored silently; ``'`` escaped as
``\\'`` matches; ``top N`` / ``bottom N`` rank by the answer's measure. A DATE value has no
verified search form: ``[D] = '2026-02-01'`` and ``'2026-02-01T00:00:00'`` are rejected ("Date value
token doesn't have a valid date filter"), bare dates are invalid tokens, and ``'02/01/2026'`` parses
but matched nothing for a day with rows -- so no date value is carried.
"""
from __future__ import annotations

import re
from typing import Optional

from ts_cli.sisense.answers import _range_generic_filter
from ts_cli.sisense.target_settings import VERIFIED_BOOLEAN_TERMS

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
    """Sisense `all`: no condition, at any kind or level -- unless the filter also carries settings
    this converter does not read, which may give it one."""
    return bool((sf.get("raw") or {}).get("all")) and not sf.get("unsupported")


def _is_date(sf: dict) -> bool:
    return sf.get("datatype") == "datetime" or bool(sf.get("level"))


def date_problem(sf: dict) -> Optional[str]:
    """Why a date filter's values are not carried, or None for a filter with no date values.
    No search form for a date value is verified (see the module docstring), and a coarser level's
    members are period starts (``2024-01-01`` for 2024) rather than days besides."""
    if not _is_date(sf) or sf.get("kind") not in _VALUE_KINDS:
        return None
    level = (sf.get("level") or "").lower()
    if level in _COARSE_LEVELS:
        return f"its values are {level} periods, and no search form for a date value is verified"
    return "a date filter's values are not carried: no search form for a date value is verified"


def value_problem(sf: dict, boolean_ok: bool = False) -> Optional[str]:
    """Why a filter's values cannot be carried as written, or None. ``boolean_ok``: the column is a
    boolean, where `= true` / `!= true` match exactly its true / false rows (live 26.11)."""
    vals = sf.get("values") or []
    if any(v is None for v in vals):
        return "a member is null, which has no verified search or chip form"
    if any("\\" in str(v) for v in vals):
        return "a value contains a backslash, which search quoting has not been verified for"
    if sf.get("kind") in ("member", "exclude") and any(_odd_member(v, boolean_ok) for v in vals):
        return "a member is a boolean (on a column not known to be one) or a decimal, whose written form is not verified"
    return _range_problem(sf) if sf.get("kind") == "range" else None


def _odd_member(v, boolean_ok: bool) -> bool:
    return isinstance(v, float) or (isinstance(v, bool) and not boolean_ok)


def _plain_number(v) -> bool:
    return (not isinstance(v, bool) and isinstance(v, (int, float)) and v == v
            and v not in (float("inf"), float("-inf")) and "e" not in str(v).lower())


def _range_problem(sf: dict) -> Optional[str]:
    raw = sf.get("raw") or {}
    bounds = [raw[k] for k in ("from", "to", "fromNotEqual", "toNotEqual", "equals") if raw.get(k) is not None]
    if not all(_plain_number(v) for v in bounds):
        return "a range bound is not a plain number, whose written form is not verified"
    if raw.get("equals") is not None and len(bounds) > 1:
        return "a range with both `equals` and a bound has no single meaning"
    return None


def common_problem(sf: dict, boolean_ok: bool = False) -> Optional[str]:
    """Reasons shared by widget filters and chips (unrecognised keys, values, dates)."""
    if sf.get("unsupported"):
        return "it carries filter settings this converter does not read: " + ", ".join(sf["unsupported"])
    if sf.get("agg"):
        return f"it filters an aggregate ({sf['agg']}), whose ThoughtSpot filter semantics are not verified"
    return date_problem(sf) or value_problem(sf, boolean_ok)


def widget_filter(sf: dict, name: str, boolean_ok: bool = False) -> tuple:
    """A widget filter on resolved ``name`` -> (search fragment | None, problem | None)."""
    problem = common_problem(sf, boolean_ok)
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


def chip_condition(sf: dict, chip: dict) -> Optional[str]:
    """Set a dashboard filter's condition on its chip; -> why it is not carried exactly, or None.
    A chip with no condition is unfiltered, so a reason always goes to the report."""
    if is_all(sf):
        return None
    problem = common_problem(sf)
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
        return ("a range chip (generic_filter) has not been verified to filter on a live Liveboard "
                "(open-item #5); check it after import")
    return f"its {kind} condition is not carried, so the chip is unfiltered"


def top_n(widget: dict, measures: list, dimensions: list) -> tuple:
    """A widget's top/bottom-N -> (top N | None, extra search fragment | None, problems).

    ThoughtSpot ranks the ANSWER'S ROWS by its measure, so it is carried only when N is a whole
    number above 0, the ranked dimension is the widget's only dimension (one row per member) and
    the ranking measure (``by``) is its only measure. ``bottom N`` is carried as is."""
    ranks = [sf for sf in widget.get("filters", []) if sf.get("kind") == "top_n"]
    if not ranks:
        return None, None, []
    if len(ranks) > 1:
        return None, None, ["more than one top/bottom ranking on the widget is not carried"]
    sf = ranks[0]
    op = sf.get("operator")
    try:
        n = int(str((sf.get("values") or [""])[0]))
    except ValueError:
        return None, None, [f"{op} {sf.get('values')} is not a whole number, so the ranking is not carried"]
    problem = _rank_problem(sf, n, measures, dimensions)
    if problem:
        return None, None, [problem]
    return (n, None, []) if op == "top" else (None, f"bottom {n}", [])


def _rank_problem(sf: dict, n: int, measures: list, dimensions: list) -> Optional[str]:
    op, by = sf.get("operator"), (sf.get("raw") or {}).get("by") or {}
    if sf.get("unsupported"):
        return "the ranking carries settings this converter does not read: " + ", ".join(sf["unsupported"])
    if n <= 0:
        return f"{op} {n} is not a positive rank, so the ranking is not carried"
    if len(dimensions) != 1 or dimensions[0].get("dim") != sf.get("dim") or \
            (dimensions[0].get("level") or "").lower() != (sf.get("level") or "").lower():
        return (f"{op} {n} ranks {sf.get('dim')} (level {sf.get('level') or 'none'}), which is not the widget's "
                "only dimension at the same level, so ThoughtSpot would rank different rows; not carried")
    if len(measures) != 1 or not _same_measure(by, measures[0]):
        return (f"{op} {n} ranks by {by.get('dim') or by.get('formula') or 'an unknown measure'}, "
                "which is not the widget's only measure, so the ranking is not carried")
    return None


def _same_measure(by: dict, f: dict) -> bool:
    if by.get("formula") or f.get("formula"):
        return False
    return by.get("dim") == f.get("dim") and (by.get("agg") or "").lower() == (f.get("agg") or "").lower()


# --------------------------------------------------------------------------- filter_map and value rules
# filter_map fragments: `in (...)` / `not in (...)` are ignored by search silently (live-verified),
# and no search form for a date value is verified (target_filters), so neither is accepted
_IN_LIST = re.compile(r"\b(not\s+)?in\s*\(", re.I)
_DATE_VALUE = re.compile(r"'\s*(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4})|\]\s*\.\s*['\w]")
# a filter_map fragment is read only as `[column] op value` terms: the forms whose search behaviour
# is verified (repeated `=` ORed, `!=` ANDed, ranges). Anything else (a bare column, which would
# change the query's grain, a ranking, `contains`, `or`, a date keyword) is refused
_TERM = r"\[[^\]]+\]\s*(?:!=|>=|<=|=|>|<)\s*(?:'(?:[^'\\]|\\.)*'|-?\d+(?:\.\d+)?|true|false)"
_FILTER_TERMS = re.compile(rf"\s*{_TERM}(?:\s+{_TERM})*\s*", re.I)


_TERM_PARTS = re.compile(r"\[([^\]]+)\]\s*(!=|>=|<=|=|>|<)\s*('(?:[^'\\]|\\.)*'|\S+)")
_RANGE_TERM_OPS = {">=", "<=", ">", "<"}


# keys that only shape the filter UI; everything else in a filter is part of its condition
_PRESENTATION_FILTER_KEYS = ("explicit", "multiSelection")


def condition_key(raw, level=None) -> tuple:
    """A Sisense filter's condition, comparable: every key and value of the filter except the
    UI-only ones (members as a sorted list of strings, nested objects in full), plus the date
    level it filters at, which lives beside the filter on the JAQL item."""
    raw = raw if isinstance(raw, dict) else {}

    def norm(v):
        if isinstance(v, dict):
            return tuple(sorted((k, norm(x)) for k, x in v.items()))
        if isinstance(v, list):
            return tuple(sorted(str(norm(x)) for x in v))
        return str(v)
    body = tuple(sorted((k, norm(v)) for k, v in raw.items() if k not in _PRESENTATION_FILTER_KEYS and k != "level"))
    return body + ((("level", str(level or raw.get("level") or "").lower()),) if (level or raw.get("level")) else ())


def _show(sf: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in condition_key(sf.get("raw"), sf.get("level"))) or "no condition"


def _text_value_problem(sf: dict, numeric: bool) -> str:
    """Member / exclude text whose matching is not verified: empty, space-padded, or text on a number."""
    if sf.get("kind") not in ("member", "exclude"):
        return ""
    texts = [v for v in sf.get("values") or [] if isinstance(v, str)]
    if any(v == "" or v != v.strip() for v in texts):
        return "a member is empty or space-padded, whose matching is not verified"
    if numeric and texts:
        return "a member is text on a number column, whose matching is not verified"
    return ""


def _boolean_filter_problem(sf: dict) -> str:
    """A native filter on a boolean column: only members true / false and an exclude of true
    (`= true`, `= false`, `!= true`) are verified."""
    vals = sf.get("values") or []
    if sf.get("kind") == "member" and vals and all(isinstance(v, bool) for v in vals):
        return ""
    if sf.get("kind") == "exclude" and vals == [True]:
        return ""
    if sf.get("kind") in ("member", "exclude", "range"):
        return "on a boolean column only = true, = false and != true are verified"
    return ""


def _value_rule(col: str, op: str, value: str) -> str:
    if "\\" in value.replace("\\'", ""):     # `\'` is the verified escape for a quote
        return "a value contains a backslash, which search quoting has not been verified for"
    if value.startswith("'") and (value == "''" or value[1:-1] != value[1:-1].strip()):
        return "an empty or space-padded text value, whose matching is not verified"
    if op in ("=", "!=") and re.fullmatch(r"-?\d+\.\d+", value):
        return "a decimal under = / != has no verified written form"
    return ""


def _typed_rule(col: str, op: str, value: str, booleans: set, numerics: set) -> str:
    if value.startswith("'") and col in numerics:
        return f"[{col}] is a number, compared here with text {value}"
    if value.lower() in ("true", "false") and col not in booleans:
        return f"[{col}] is compared with {value}, and it is not known to be a boolean column"
    if col in booleans and (op, value) not in VERIFIED_BOOLEAN_TERMS:      # as verified: lower case
        return f"[{col}] is a boolean column, where only = true, = false and != true are verified (not {op} {value})"
    return ""


def _term_problem(frag: str, booleans: set = frozenset(), numerics: set = frozenset()) -> str:
    """The value and operator rules a native filter follows, applied to a filter_map fragment:
    no backslash in a value, no empty or padded text, no decimal under `=` / `!=` (its written form is not verified), `true`
    / `false` only on a boolean column (verified there, live 26.11), and one kind of operator per column -- repeated `=` (ORed), repeated `!=` (ANDed)
    or a range -- since how search combines them on one column is not verified."""
    ops: dict = {}
    for col, op, value in _TERM_PARTS.findall(frag):
        problem = _value_rule(col, op, value) or _typed_rule(col, op, value, booleans, numerics)
        if problem:
            return problem
        ops.setdefault(col, set()).add("range" if op in _RANGE_TERM_OPS else op)
    mixed = sorted(c for c, kinds in ops.items() if len(kinds) > 1)
    return (f"[{mixed[0]}] is filtered with more than one kind of operator, which search is not verified to "
            "combine as Sisense does") if mixed else ""
