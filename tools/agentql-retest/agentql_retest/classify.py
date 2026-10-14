"""Case model and verdicts. Pure: no I/O, so every rule here is unit-tested offline.

A case encodes what `limitations.md` currently SAYS about one construct. The verdict is
whether the cluster still behaves that way:

- AS_DOCUMENTED  the documented behaviour reproduced (a known failure still fails, a fixed
                 construct still works, a silent-wrong construct is still wrong)
- CHANGED        the behaviour moved. Either direction is news: a ❌ row that now works is a
                 fix to confirm and document, a ✅ row that now fails is a regression
- ERROR          the run could not tell (CLI/auth failure, or a control it depends on broke)

A status is never trusted on its own. Constructs whose failure mode is a wrong number
carry a control case or a value check, because they return SUCCESS either way.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

AS_DOCUMENTED = "AS_DOCUMENTED"
CHANGED = "CHANGED"
ERROR = "ERROR"

# What the case expects of the two calls.
OK = "ok"                    # generate-sql and fetch-data both SUCCESS
SQL_OK = "sql_ok"            # generate-sql SUCCESS; fetch-data not run (SQL-shape checks)
GEN_ERROR = "gen_error"      # generate-sql returns a non-SUCCESS status
FETCH_ERROR = "fetch_error"  # generate-sql SUCCESS, fetch-data fails in the warehouse

CLI_ERROR = "CLI_ERROR"

Rows = list
Check = Callable[[Rows, dict], Optional[str]]


@dataclass(frozen=True)
class Case:
    id: str
    sql: str
    expect: str
    row: str                                  # the limitations.md row this case backs
    model: str = "single"                     # key into the --model-* arguments
    code: Optional[str] = None                # expected status for GEN_ERROR / FETCH_ERROR
    sql_has: tuple = ()                       # lower-case substrings the executable SQL must contain
    sql_lacks: tuple = ()                     # ... and must not contain
    same_as: Optional[str] = None             # control case id: rows must match
    differs_from: Optional[str] = None        # control case id: rows must NOT match (silent-wrong)
    values: tuple = ()                        # ((row, col, expected), ...) — floats compared with tolerance
    check: Optional[Check] = field(default=None, compare=False)  # bespoke rule: (rows, results) -> problem or None
    control: bool = False                     # a control only: reported, but backs no row on its own

    @property
    def suite(self) -> str:
        """`lessons` cases back learning-path.md on the sample Model; the rest back limitations.md."""
        return "lessons" if self.model == "apparel" else "limitations"

    @property
    def runs_fetch(self) -> bool:
        return self.expect in (OK, FETCH_ERROR)


def _norm(v):
    if isinstance(v, float):
        if math.isnan(v):
            return "nan"
        return round(v, 9)
    return v


def canonical_rows(rows) -> list:
    """Order-insensitive, float-tolerant form for comparing two result sets."""
    return sorted((tuple(_norm(v) for v in r) for r in rows or []), key=repr)


def value_matches(actual, expected, rel=1e-9) -> bool:
    if isinstance(expected, float) or isinstance(actual, float):
        try:
            return math.isclose(float(actual), float(expected), rel_tol=rel, abs_tol=1e-12)
        except (TypeError, ValueError):
            return False
    return actual == expected


def _status(res) -> Optional[str]:
    return None if res is None else res.get("status")


def _first_error(res) -> str:
    errs = (res or {}).get("errors") or []
    msg = errs[0].get("message", "") if errs and isinstance(errs[0], dict) else str(errs[:1])
    return " ".join(msg.split())[:240]


def _shape_problems(case: Case, gen: dict) -> list:
    sql = (gen.get("executable_sql") or "").lower()
    out = [f"SQL no longer contains {s!r}" for s in case.sql_has if s not in sql]
    out += [f"SQL now contains {s!r}" for s in case.sql_lacks if s in sql]
    return out


def _value_problems(case: Case, rows: list, results: dict) -> tuple:
    """Returns (problems, error). An unusable control is an ERROR, not a CHANGED."""
    out = []
    for r, c, exp in case.values:
        try:
            got = rows[r][c]
        except (IndexError, TypeError):
            out.append(f"no value at row {r} col {c} (expected {exp!r})")
            continue
        if not value_matches(got, exp):
            out.append(f"value at row {r} col {c} is {got!r}, documented {exp!r}")
    for ref, want_same in ((case.same_as, True), (case.differs_from, False)):
        if not ref:
            continue
        ctl = results.get(ref) or {}
        if _status(ctl.get("fetch")) != "SUCCESS":
            return out, f"control {ref} has no rows ({_status(ctl.get('fetch'))})"
        same = canonical_rows(rows) == canonical_rows(ctl["fetch"].get("rows"))
        if want_same and not same:
            out.append(f"rows differ from control {ref}")
        if not want_same and same:
            out.append(f"rows now MATCH control {ref} — the silent-wrong result looks fixed")
    if case.check:
        problem = case.check(rows, results)
        if problem:
            out.append(problem)
    return out, None


def classify(case: Case, gen: Optional[dict], fetch: Optional[dict], results: dict) -> tuple:
    """-> (verdict, [reasons]). `results` maps case id -> {"gen": ..., "fetch": ...}."""
    if _status(gen) in (None, CLI_ERROR):
        return ERROR, [f"generate-sql did not run: {_first_error(gen) or gen}"]
    g = _status(gen)

    if case.expect == GEN_ERROR:
        if g == "SUCCESS":
            return CHANGED, ["now compiles (generate-sql SUCCESS) — documented as rejected"]
        if case.code and g != case.code:
            return CHANGED, [f"still rejected, but status changed: {case.code} -> {g}: {_first_error(gen)}"]
        return AS_DOCUMENTED, [f"{g}"]

    if g != "SUCCESS":
        return CHANGED, [f"generate-sql now fails: {g}: {_first_error(gen)}"]
    shape = _shape_problems(case, gen)

    if case.expect == SQL_OK:
        return (CHANGED, shape) if shape else (AS_DOCUMENTED, ["compiles; SQL shape as documented"])

    if _status(fetch) in (None, CLI_ERROR):
        return ERROR, [f"fetch-data did not run: {_first_error(fetch) or fetch}"]
    f = _status(fetch)

    if case.expect == FETCH_ERROR:
        if f == "SUCCESS":
            return CHANGED, ["now executes (fetch-data SUCCESS) — documented as failing in the warehouse"] + shape
        if case.code and f != case.code:
            return CHANGED, [f"still fails, but status changed: {case.code} -> {f}: {_first_error(fetch)}"] + shape
        return (CHANGED, shape) if shape else (AS_DOCUMENTED, [f"{f}"])

    # OK
    if f != "SUCCESS":
        return CHANGED, [f"fetch-data now fails: {f}: {_first_error(fetch)}"]
    problems, err = _value_problems(case, fetch.get("rows") or [], results)
    if err:
        return ERROR, [err]
    problems = shape + problems
    return (CHANGED, problems) if problems else (AS_DOCUMENTED, ["works; values as documented" if (
        case.values or case.same_as or case.differs_from or case.check) else "works"])


def validate_cases(cases) -> list:
    """Structural problems in the case list itself — run before any live call."""
    ids = [c.id for c in cases]
    out = [f"duplicate id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    known = set(ids)
    by_id = {c.id: c for c in cases}
    for c in cases:
        if c.expect not in (OK, SQL_OK, GEN_ERROR, FETCH_ERROR):
            out.append(f"{c.id}: unknown expect {c.expect!r}")
        for ref in (c.same_as, c.differs_from):
            if ref and ref not in known:
                out.append(f"{c.id}: control {ref} is not a case")
            elif ref and by_id[ref].expect != OK:
                out.append(f"{c.id}: control {ref} must expect {OK}")
        if (c.values or c.same_as or c.differs_from or c.check) and c.expect != OK:
            out.append(f"{c.id}: value checks need expect={OK}")
        if not c.row.strip():
            out.append(f"{c.id}: no limitations.md row named")
    return out
