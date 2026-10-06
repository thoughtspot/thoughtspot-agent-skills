"""Canonical values and the comparison rules (harness design §5).

Both sides are reduced to a canonical typed value before comparing:

    {"t": "null"} | {"t": "num", "v": "<decimal string>"} | {"t": "str", "v": ...}
    {"t": "bool", "v": true} | {"t": "date", "v": "YYYY-MM-DD"}
    {"t": "datetime", "v": "YYYY-MM-DDTHH:MM:SS"} | {"t": "error", "v": "<message>"}

Rules:
- numbers compare as Decimal within the case's declared tolerance (never widened after a
  failure); INT 3 equals DOUBLE 3.0.
- NULL equals NULL only; NULL against a value is a mismatch (``NULL_DIFF``).
- a boolean never equals a number; a numeric string equals the number it spells.
- a date equals a datetime only at midnight on the same day; an integer where a date is
  expected is read as epoch seconds (UTC) — AgentQL returns temporal formula results that
  way (``epoch_to_temporal``).
- strings are exact and case-sensitive (ThoughtSpot's case-insensitive *operators* are a
  separate matter — BL-333 — returned values are not changed).
- a source error against a ThoughtSpot NULL or error is ``ERROR_EQUIV`` — reported, never
  counted as a match.
"""
from __future__ import annotations

import datetime as _dt
import math
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

TRANSLATED, APPROXIMATED, NEEDS_REVIEW = "TRANSLATED", "APPROXIMATED", "NEEDS_REVIEW"

# Case verdicts, in report order (silent first).
MATCH = "MATCH"
MISMATCH = "MISMATCH"
ERROR_EQUIV = "ERROR_EQUIV"
TRANSLATE_FAILED = "TRANSLATE_FAILED"
IMPORT_FAILED = "IMPORT_FAILED"
RUN_FAILED = "RUN_FAILED"
ORACLE_FAILED = "ORACLE_FAILED"
VERDICTS = (MISMATCH, RUN_FAILED, IMPORT_FAILED, TRANSLATE_FAILED, ERROR_EQUIV,
            ORACLE_FAILED, MATCH)

# Per-key outcomes.
EQUAL = "EQUAL"
NUMERIC_DIFF = "NUMERIC_DIFF"
VALUE_DIFF = "VALUE_DIFF"
NULL_DIFF = "NULL_DIFF"
ERROR_VS_VALUE = "ERROR_VS_VALUE"   # source errored, ThoughtSpot returned a value
TS_ERROR = "TS_ERROR"               # ThoughtSpot errored, source returned a value
MISSING = "MISSING"                 # key in the oracle, absent from ThoughtSpot
EXTRA = "EXTRA"                     # key ThoughtSpot returned that the oracle did not
WRONG_OUTCOMES = {NUMERIC_DIFF, VALUE_DIFF, NULL_DIFF, ERROR_VS_VALUE, MISSING, EXTRA}

NULL = {"t": "null"}


def _num(v: Any) -> dict:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return {"t": "num", "v": repr(v)}
    return {"t": "num", "v": str(Decimal(str(v)) if isinstance(v, float) else v)}


def canon(v: Any) -> dict:
    """Canonical form of a value as a Python driver returns it (warehouse side)."""
    if v is None:
        return dict(NULL)
    if isinstance(v, bool):
        return {"t": "bool", "v": v}
    if isinstance(v, (int, float, Decimal)):
        return _num(v)
    if isinstance(v, _dt.datetime):
        return {"t": "datetime", "v": v.replace(tzinfo=None).isoformat(timespec="seconds")}
    if isinstance(v, _dt.date):
        return {"t": "date", "v": v.isoformat()}
    return {"t": "str", "v": str(v)}


def error(msg: str) -> dict:
    return {"t": "error", "v": (msg or "error").strip().splitlines()[0][:300]}


_TS_DATE_TYPES = {"DATE", "TYPE_DATE"}
_INT64_TYPES = {"INT64", "TYPE_INT64"}
_TS_DATETIME_TYPES = {"DATE_TIME", "DATETIME", "TIMESTAMP", "TYPE_DATE_TIME", "TIME"}


def _epoch(v: Any) -> Optional[_dt.datetime]:
    """Epoch seconds -> naive UTC datetime, or None for anything that is not one."""
    try:
        if isinstance(v, bool):
            return None
        d = Decimal(str(v))
        if not d.is_finite() or d != d.to_integral_value():
            return None
        return _dt.datetime.fromtimestamp(int(d), tz=_dt.timezone.utc).replace(tzinfo=None)
    except (InvalidOperation, ValueError, OverflowError, OSError, TypeError):
        return None


def canon_ts(v: Any, col_type: str = "") -> dict:
    """Canonical form of one AgentQL fetch-data cell.

    Temporal cells under a DATE / DATE_TIME column type are converted from epoch seconds.
    A cell under an INT64 column keeps ``ts_type: INT64``: that is the only shape in which
    the comparator may read an integer as an epoch date (AgentQL types DATE *formula*
    results as INT64 — observed 2026-10-06).
    """
    t = (col_type or "").upper()
    if v is None:
        return dict(NULL)
    if t in _TS_DATE_TYPES | _TS_DATETIME_TYPES and isinstance(v, (int, float)) \
            and not isinstance(v, bool):
        ts = _epoch(v)
        if ts is None:
            return {"t": "num", "v": str(v), "ts_type": t}
        return {"t": "date", "v": ts.date().isoformat()} if t in _TS_DATE_TYPES \
            else {"t": "datetime", "v": ts.isoformat(timespec="seconds")}
    if isinstance(v, str) and t in {"BOOL", "BOOLEAN", "TYPE_BOOL"}:
        if v.lower() in ("true", "false"):
            return {"t": "bool", "v": v.lower() == "true"}
    c = canon(v)
    if t in _INT64_TYPES and c["t"] == "num":
        c["ts_type"] = "INT64"
    return c


def _as_decimal(c: dict) -> Optional[Decimal]:
    if c["t"] == "num":
        try:
            return Decimal(c["v"])
        except InvalidOperation:
            return None
    if c["t"] == "str":
        v = c["v"]
        if not isinstance(v, str) or v != v.strip():  # Decimal() would accept ' 7'
            return None
        try:
            d = Decimal(v)
            return d if d.is_finite() else None
        except (InvalidOperation, TypeError):
            return None
    return None


def _temporal(c: dict) -> Optional[str]:
    """ISO datetime string for date/datetime (and ISO-looking strings), else None."""
    if c["t"] == "date":
        return c["v"] + "T00:00:00"
    if c["t"] == "datetime":
        return c["v"]
    if c["t"] == "str":
        s = c["v"].replace(" ", "T")
        try:
            if len(s) == 10:
                return _dt.date.fromisoformat(s).isoformat() + "T00:00:00"
            return _dt.datetime.fromisoformat(s).replace(tzinfo=None).isoformat(timespec="seconds")
        except ValueError:
            return None
    return None


def epoch_to_temporal(c: dict) -> Optional[dict]:
    """An INT64 epoch-seconds cell read as a datetime (UTC); None if it is not one.

    AgentQL fetch-data returns DATE formula results as INT64 epoch seconds with the
    column typed INT64 (observed 2026-10-06, se-thoughtspot), so the type is lost and
    only the expected side says the value is temporal. Applied only to cells tagged
    ``ts_type: INT64``; a date then compares equal only at midnight on the same day.
    """
    if c.get("t") != "num" or c.get("ts_type") != "INT64":
        return None
    ts = _epoch(c.get("v"))
    return None if ts is None else {"t": "datetime", "v": ts.isoformat(timespec="seconds")}


def numbers_close(a: Decimal, b: Decimal, tol: dict) -> bool:
    if not (a.is_finite() and b.is_finite()):
        return a == b or (a.is_nan() and b.is_nan())
    diff = abs(a - b)
    bound = max(Decimal(str(tol.get("abs", 0))),
                Decimal(str(tol.get("rel", 0))) * max(abs(a), abs(b)))
    return diff <= bound


def compare_value(exp: dict, act: dict, tol: dict) -> str:
    et, at = exp["t"], act["t"]
    if et == "error":
        return ERROR_EQUIV if at in ("null", "error") else ERROR_VS_VALUE
    if at == "error":
        return TS_ERROR
    if et == "null" or at == "null":
        return EQUAL if et == at else NULL_DIFF
    if et == "bool" or at == "bool":
        return EQUAL if et == at and exp["v"] == act["v"] else VALUE_DIFF
    if et in ("date", "datetime") and at == "num":
        conv = epoch_to_temporal(act)
        if conv is None:
            return VALUE_DIFF
        act, at = conv, conv["t"]
    if et == "num":
        # cross-type numeric equality only when the ORACLE is numeric: a numeric string
        # from ThoughtSpot may equal a number, never the other way round
        a, b = _as_decimal(exp), _as_decimal(act) if at in ("num", "str") else None
        if a is None or b is None:
            return VALUE_DIFF
        return EQUAL if numbers_close(a, b, tol) else NUMERIC_DIFF
    if at == "num":
        return VALUE_DIFF  # a string / date oracle never equals a number ("007" != 7)
    if et in ("date", "datetime") or at in ("date", "datetime"):
        a, b = _temporal(exp), _temporal(act)
        return EQUAL if a is not None and a == b else VALUE_DIFF
    return EQUAL if et == at and exp.get("v") == act.get("v") else VALUE_DIFF


def compare_rows(expected: dict[str, dict], actual: dict[str, dict], tol: dict) -> list[dict]:
    rows = []
    for k in sorted(set(expected) | set(actual), key=_key_order):
        e, a = expected.get(k), actual.get(k)
        if a is None:
            outcome = MISSING
        elif e is None:
            outcome = EXTRA
        else:
            outcome = compare_value(e, a, tol)
        rows.append({"key": k, "expected": e, "actual": a, "outcome": outcome})
    return rows


def _key_order(k: str):
    try:
        return (0, float(k), k)
    except ValueError:
        return (1, 0.0, k)


ALL_KEYS = "*"


def _cause(case: dict, divergent: Optional[set[str]] = None,
           equal: Optional[set[str]] = None) -> dict:
    """Attribute ``divergent`` keys to the case's ``known_divergence``, key by key.

    A tag explains only the keys it lists. Any other divergent key is unexplained, and a
    listed key that came back equal makes the tag stale. ``keys: ["*"]`` is a case-level
    tag (an import failure, a decline): it explains no per-key value at all.
    """
    divergent, equal = divergent or set(), equal or set()
    kd = case.get("known_divergence")
    if not kd:
        return {"explained": not divergent, "tag": "unexplained", "kind": None,
                "backlog": None, "reason": None, "unexplained_keys": sorted(divergent, key=_key_order),
                "stale_keys": []}
    listed = {str(k) for k in kd.get("keys") or []}
    per_key = listed - {ALL_KEYS}
    unexplained = divergent - per_key
    return {"explained": not unexplained, "tag": kd["tag"], "kind": kd["kind"],
            "backlog": kd.get("backlog"), "reason": kd["reason"],
            "unexplained_keys": sorted(unexplained, key=_key_order),
            "stale_keys": sorted(per_key & equal, key=_key_order)}


def classify_case(case: dict, oracle: dict, translation: Optional[dict],
                  import_error: Optional[str], actual: Optional[dict]) -> dict:
    """One case's verdict.

    ``oracle`` / ``actual``: ``{"values": {key: canonical}, "error": str|None}``;
    ``translation``: the ``ts formula translate`` result (``status``, ``formula``, ``traps``).

    A MISMATCH is ``silent_wrong`` when the translator said TRANSLATED (or APPROXIMATED
    with no trap), and ``warned`` when it said APPROXIMATED and named a trap.
    """
    status = (translation or {}).get("status")
    out: dict[str, Any] = {"id": case["id"], "translation_status": status, "rows": [],
                           "mismatch_kinds": [], "silent_wrong": False, "warned": False,
                           "stale_divergence": False, "detail": None}
    kd = case.get("known_divergence")
    ovals = oracle.get("values") or {}
    if not ovals or all(v["t"] == "error" for v in ovals.values()):
        out.update(verdict=ORACLE_FAILED,
                   detail=oracle.get("error") or next(iter(ovals.values()), {}).get("v"))
        return out
    if status not in (TRANSLATED, APPROXIMATED):
        notes = (translation or {}).get("notes") or []
        out.update(verdict=TRANSLATE_FAILED, detail="; ".join(notes) or status)
        return _with_case_tag(out, case)
    if import_error:
        out.update(verdict=IMPORT_FAILED, detail=import_error)
        return _with_case_tag(out, case)
    if actual is None:  # never queried (the run aborted) — loud, never "missing rows"
        out.update(verdict=RUN_FAILED, detail="not queried (run aborted before this case)")
        return out
    avals = actual.get("values") or {}
    if not avals:
        if actual.get("zero_rows") or not actual.get("error"):
            out.update(verdict=RUN_FAILED, detail=actual.get("error") or
                       "AgentQL returned SUCCESS with 0 rows")
            return out
        all_err = all(v["t"] == "error" for v in ovals.values())
        out.update(verdict=ERROR_EQUIV if all_err else RUN_FAILED, detail=actual["error"])
        if all_err:
            out["cause"] = _cause(case, set(ovals))
        return out

    rows = compare_rows(ovals, avals, case["tolerance"])
    out["rows"] = rows
    outcomes = {r["outcome"] for r in rows}
    equal = {r["key"] for r in rows if r["outcome"] == EQUAL}
    wrong = sorted(outcomes & WRONG_OUTCOMES)
    if wrong:
        bad = {r["key"] for r in rows if r["outcome"] in WRONG_OUTCOMES}
        warned = status == APPROXIMATED and bool((translation or {}).get("traps"))
        out.update(verdict=MISMATCH, mismatch_kinds=wrong, cause=_cause(case, bad, equal),
                   silent_wrong=not warned, warned=warned)
    elif TS_ERROR in outcomes:
        errs = [r["actual"]["v"] for r in rows if r["outcome"] == TS_ERROR]
        out.update(verdict=RUN_FAILED, detail=errs[0])
    elif ERROR_EQUIV in outcomes:
        eq = {r["key"] for r in rows if r["outcome"] == ERROR_EQUIV}
        out.update(verdict=ERROR_EQUIV, cause=_cause(case, eq, equal))
    else:
        out["verdict"] = MATCH
        if kd:
            out["stale_divergence"] = True
            out["cause"] = _cause(case, set(), equal)
    if out.get("cause", {}).get("stale_keys"):
        out["stale_divergence"] = True
    return out


def _with_case_tag(out: dict, case: dict) -> dict:
    if case.get("known_divergence"):
        out["cause"] = _cause(case)
    return out


def counts(results: list[dict]) -> dict[str, int]:
    c = {v: 0 for v in VERDICTS}
    for r in results:
        c[r["verdict"]] += 1
    return c
