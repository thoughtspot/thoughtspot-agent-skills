"""Case model and verdicts. Pure: no I/O, so every rule here is unit-tested offline.

A case encodes what `limitations.md` currently SAYS about one construct. The verdict is
whether the cluster still behaves that way:

- AS_DOCUMENTED  the documented behaviour reproduced (a known failure still fails, a fixed
                 construct still works, a silent-wrong construct is still wrong)
- CHANGED        the behaviour moved. Either direction is news: a ❌ row that now works is a
                 fix to confirm and document, a ✅ row that now fails is a regression
- ERROR          the run could not tell (CLI/auth failure, or a control it depends on broke)
- BREACH         a `guard` case (a write, DDL or injection attempt) compiled to something
                 other than one read-only SELECT. Not news to document: a safety regression
                 to raise immediately. Guards never call fetch-data, so nothing reaches the
                 warehouse even then

A status is never trusted on its own. Constructs whose failure mode is a wrong number
carry a control case or a value check, because they return SUCCESS either way.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

AS_DOCUMENTED = "AS_DOCUMENTED"
CHANGED = "CHANGED"
ERROR = "ERROR"
BREACH = "BREACH"

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
    guard: bool = False                       # must stay rejected / read-only forever; never fetched

    @property
    def suite(self) -> str:
        """`guards` must never change; `lessons` back learning-path.md; the rest back limitations.md."""
        if self.guard:
            return "guards"
        return "lessons" if self.model == "apparel" else "limitations"

    @property
    def runs_fetch(self) -> bool:
        return self.expect in (OK, FETCH_ERROR) and not self.guard


_WRITE_WORDS = re.compile(
    r"(?<![\w$])("
    r"insert|update|delete|merge|truncate|drop|create|alter|grant|revoke|call|copy|put|get|list|"
    r"remove|undrop|describe|desc|show|execute|exec|begin|commit|rollback|use|into|set|nextval"
    r"|system\$\w*)"
    r"(?![\w$])")


def strip_literals(sql: str) -> str:
    """Blank out every quoted string and identifier so a keyword inside a value is never read
    as SQL. Handles ANSI doubled quotes (''), backslash escapes (\'), `$$ dollar quoting $$`
    and `backtick identifiers` — so neither a backslash dialect nor dollar quoting can smuggle
    a statement terminator or keyword past the scan. An unterminated quote blanks to end."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "$" and sql.startswith("$$", i):            # $$ ... $$
            end = sql.find("$$", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c in ("'", '"', "`"):                            # quoted string / identifier
            i += 1
            while i < n:
                d = sql[i]
                if d == "\\" and i + 1 < n:                 # backslash escape
                    i += 2
                    continue
                if d == c:
                    if i + 1 < n and sql[i + 1] == c:        # doubled = escaped quote
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def read_only_problem(sql) -> Optional[str]:
    """None when `sql` is one read-only SELECT (optionally led by WITH); else what is wrong."""
    if not isinstance(sql, str):
        return f"executable_sql is not a string: {type(sql).__name__}"
    body = strip_literals(sql).strip().lower()
    if not body:
        return "no SQL"
    if not re.match(r"(select|with)\b", body):
        return f"does not start with SELECT/WITH: {body[:40]!r}"
    if ";" in body.rstrip(";"):
        return "contains more than one statement"
    if "--" in body or "/*" in body or "#" in body:
        return "carries a comment through to the warehouse"
    hit = _WRITE_WORDS.search(body)
    return f"contains {hit.group(1).upper()!r} outside a literal" if hit else None


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

    if case.guard:
        return _classify_guard(case, gen, g)

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


def _classify_guard(case: Case, gen: dict, g: str) -> tuple:
    # A guard CONTROL is a plain valid SELECT: it must compile. If it does not, the endpoint
    # is unusable (auth/wrong-model/down) and every "rejected" guard below would pass for the
    # wrong reason — so a failed control is ERROR, which makes the whole run untrustworthy.
    if case.control:
        if g != "SUCCESS":
            return ERROR, [f"guard control did not compile ({g}: {_first_error(gen)}) — "
                           "endpoint unusable, so guard rejections prove nothing"]
        problem = read_only_problem(gen.get("executable_sql"))
        return (ERROR, [f"guard control is not read-only: {problem}"]) if problem else (AS_DOCUMENTED, ["control compiles"])

    carried = read_only_problem(gen.get("executable_sql")) if gen.get("executable_sql") else None

    if case.expect == GEN_ERROR:
        if g == "SUCCESS":
            return BREACH, [f"now compiles: {carried or 'to a SELECT, but it must be rejected'}"]
        # Rejected — but a non-SUCCESS response that still carries unsafe SQL is a breach.
        if carried:
            return BREACH, [f"rejected ({g}) but response carries unsafe SQL: {carried}"]
        return AS_DOCUMENTED, [f"rejected: {g}"]

    # SQL_OK guard: compiling is expected; the output must be one read-only SELECT.
    if g != "SUCCESS":
        return CHANGED, [f"now rejected outright ({g}) — still safe; update the note"]
    if carried:
        return BREACH, [carried]
    shape = _shape_problems(case, gen)   # a shape change is news, not a safety breach
    return (CHANGED, shape) if shape else (AS_DOCUMENTED, ["compiles to one read-only SELECT"])


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
        if c.guard and c.expect not in (GEN_ERROR, SQL_OK):
            out.append(f"{c.id}: a guard may only expect {GEN_ERROR} or {SQL_OK} (it is never fetched)")
    return out
