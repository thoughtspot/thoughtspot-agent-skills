"""Load and validate fidelity cases (JSONL) and their fixture tables (JSON).

A case is one source formula evaluated over a fixture table, either per row (``role:
row``, keyed by the fixture's key column) or per group (``role: aggregate``, keyed by
``group_by``). Its ``expected`` block is filled by the oracle — for a SQL dialect the
warehouse itself — so a case file may carry ``expected: null`` until the first run.

Validation is strict on purpose: a malformed case is an authoring error, and silently
skipping it would shrink the denominator without anyone noticing.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Optional

DIALECTS = {"snowflake", "databricks", "excel", "sheets", "tableau", "dax", "qlik",
            "sisense", "thoughtspot"}
ROLES = {"row", "aggregate"}
DIVERGENCE_KINDS = {"platform-semantics", "translator-bug"}
REQUIRED = ("id", "dialect", "source_formula", "role", "fixture", "tolerance", "provenance")


class CaseError(ValueError):
    """A case or fixture file is malformed."""


def _check_case(case: dict, where: str) -> None:
    missing = [k for k in REQUIRED if k not in case]
    if missing:
        raise CaseError(f"{where}: missing field(s) {', '.join(missing)}")
    if case["dialect"] not in DIALECTS:
        raise CaseError(f"{where}: unknown dialect {case['dialect']!r}")
    if case["role"] not in ROLES:
        raise CaseError(f"{where}: role must be one of {sorted(ROLES)}, got {case['role']!r}")
    if case["role"] == "aggregate" and not case.get("group_by"):
        raise CaseError(f"{where}: an aggregate case needs group_by")
    if not str(case["source_formula"]).strip():
        raise CaseError(f"{where}: empty source_formula")
    tol = case["tolerance"]
    if not isinstance(tol, dict) or not set(tol) <= {"rel", "abs"} or \
            any(not isinstance(v, (int, float)) or v < 0 for v in tol.values()):
        raise CaseError(f"{where}: tolerance must be {{'rel': >=0, 'abs': >=0}}")
    prov = case["provenance"]
    if not isinstance(prov, dict) or not prov.get("source") or not prov.get("licence"):
        raise CaseError(f"{where}: provenance needs source and licence")
    kd = case.get("known_divergence")
    if kd is not None:
        if not isinstance(kd, dict) or not kd.get("tag") or not kd.get("reason"):
            raise CaseError(f"{where}: known_divergence needs tag and reason")
        if kd.get("kind") not in DIVERGENCE_KINDS:
            raise CaseError(f"{where}: known_divergence.kind must be one of "
                            f"{sorted(DIVERGENCE_KINDS)}")
        if kd["kind"] == "translator-bug" and not kd.get("backlog"):
            raise CaseError(f"{where}: a translator-bug divergence must cite a BL id")
        keys = kd.get("keys")
        if not isinstance(keys, list) or not keys or \
                not all(isinstance(k, str) and k for k in keys):
            raise CaseError(f"{where}: known_divergence.keys must list the keys expected to "
                            'diverge (strings), or ["*"] for a case-level tag')


def parse_cases(text: str, source: str = "<cases>") -> list[dict]:
    cases: list[dict] = []
    seen: set[str] = set()
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        where = f"{source}:{n}"
        try:
            case = json.loads(line)
        except ValueError as exc:
            raise CaseError(f"{where}: not valid JSON: {exc}") from exc
        if not isinstance(case, dict):
            raise CaseError(f"{where}: a case must be a JSON object")
        _check_case(case, where)
        if case["id"] in seen:
            raise CaseError(f"{where}: duplicate case id {case['id']!r}")
        seen.add(case["id"])
        cases.append(case)
    if not cases:
        raise CaseError(f"{source}: no cases")
    return cases


def load_cases(path: pathlib.Path) -> list[dict]:
    return parse_cases(path.read_text(encoding="utf-8"), str(path))


def file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_fixture(fx: dict, source: str = "<fixture>") -> dict:
    for k in ("name", "key", "columns", "rows"):
        if k not in fx:
            raise CaseError(f"{source}: missing {k}")
    names = [c["name"] for c in fx["columns"]]
    if fx["key"] not in names:
        raise CaseError(f"{source}: key {fx['key']!r} is not a column")
    if fx.get("group") and fx["group"] not in names:
        raise CaseError(f"{source}: group {fx['group']!r} is not a column")
    for c in fx["columns"]:
        if not {"name", "sf_type", "ts_type", "column_type"} <= set(c):
            raise CaseError(f"{source}: column {c.get('name')!r} needs name/sf_type/ts_type/column_type")
    keys = [r.get(fx["key"]) for r in fx["rows"]]
    if None in keys or len(set(keys)) != len(keys):
        raise CaseError(f"{source}: key values must be present and unique")
    for r in fx["rows"]:
        extra = set(r) - set(names)
        if extra:
            raise CaseError(f"{source}: row {r.get(fx['key'])} has unknown column(s) {sorted(extra)}")
    return fx


def load_fixture(path: pathlib.Path) -> dict:
    return check_fixture(json.loads(path.read_text(encoding="utf-8")), str(path))


def fixtures_for(cases: list[dict], case_dir: pathlib.Path) -> dict[str, dict]:
    """Every fixture the cases reference, loaded once."""
    return {name: load_fixture(case_dir / name)
            for name in sorted({c["fixture"] for c in cases})}


def write_expected(cases: list[dict], expected: dict[str, Optional[dict]]) -> str:
    """The case file text with ``expected`` replaced by the oracle's values (JSONL)."""
    lines = []
    for c in cases:
        c = dict(c)
        if c["id"] in expected:
            c["expected"] = expected[c["id"]]
        lines.append(json.dumps(c, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def key_column(case: dict, fixture: dict) -> str:
    return case["group_by"] if case["role"] == "aggregate" else fixture["key"]


def summarise(cases: list[dict]) -> dict[str, Any]:
    by_role: dict[str, int] = {}
    for c in cases:
        by_role[c["role"]] = by_role.get(c["role"], 0) + 1
    return {"cases": len(cases), "by_role": by_role,
            "with_known_divergence": sum(1 for c in cases if c.get("known_divergence"))}
