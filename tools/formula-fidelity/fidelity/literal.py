"""Literal-oracle cases: a third-party corpus read from a data dir OUTSIDE the repo.

The user's rule (2026-10-06): third-party test data is never committed. What the repo holds
is a **manifest** — case id, source file path relative to the data dir, the file's sha256,
and a locator (sheet + row or cell) — and the code that re-reads each case from the file.
No formula and no expected value is in the manifest.

At run time ``materialise`` re-extracts every manifest entry from the data dir (checking the
file's sha256 first), and builds, in memory only:

- the cases, in the shape ``run.live_run`` takes (``source_formula`` with inputs renamed to
  row-1 cells, ``expected`` keyed ``"1"``), and
- one single-row fixture holding every case's input cells as typed columns
  (``X<n>``, deduplicated by source cell), loaded run-stamped by M0's warehouse loader.

The oracle of record is the value stored in the source file (``literal_oracle``): silver
for LibreOffice (its certified ``Expected``), gold for POI (cached by Excel itself).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
from typing import Any, Optional

from fidelity import sources

DATA_DIR_ENV = "FORMULA_FIDELITY_DATA"
MANIFEST_FIELDS = ("id", "source", "path", "sha256", "locator")
SOURCES = {
    "libreoffice": {"licence": "MPL-2.0", "tier": "silver",
                    "by": "LibreOffice sc/qa/unit/data/functions Expected column"},
    "poi": {"licence": "Apache-2.0", "tier": "gold",
            "by": "Apache POI test-data, value cached by Microsoft Excel"},
}
CROSSCHECK = {"agree", "disputed", "unavailable"}
FIXTURE_NAME = "m1"
KEY = "ROW_ID"
BLANK_COLUMN = "X_BLANK"
BLANK_DIVERGENCE = {
    "tag": "excel-blank-vs-null", "kind": "platform-semantics", "keys": ["1"],
    "reason": "an Excel blank cell is 0 in arithmetic and '' in text; the same input as a "
              "warehouse column is NULL, which propagates through ThoughtSpot formulas"}


# Per-case divergences, by case id (ids are ours to commit; no corpus text). A tag explains a
# wrong value, it never hides one: the case still runs and is still classified by its values.
CASE_DIVERGENCES = {
    "poi-formulaevaltestdata_copy-everythingtests-f23": {
        "tag": "decimal-literal-exact", "kind": "platform-semantics", "backlog": "BL-351",
        "keys": ["1"],
        "reason": "literal-only arithmetic: the warehouse computes exact decimals, Excel IEEE "
                  "doubles; documented divergence, tolerance not widened"},
    # lo-mathematical-roundup-sheet2-r17 carried an "oracle-dispute" tag here until BL-356:
    # the cross-check now compares at the case's own tolerance, so the case is quarantined
    # as ORACLE_DISPUTED and never run, and a tag explaining its value would be dead.
}


class DataError(ValueError):
    """The data dir, a manifest entry, or a source file is unusable."""


def resolve_data_dir(arg: Optional[str], repo_root: Optional[pathlib.Path] = None) -> pathlib.Path:
    """``--data-dir`` or ``$FORMULA_FIDELITY_DATA``. Refuses a dir inside the repo: the
    corpus must never sit where a ``git add`` can reach it."""
    raw = arg or os.environ.get(DATA_DIR_ENV)
    if not raw:
        raise DataError(f"no data dir: pass --data-dir or set ${DATA_DIR_ENV}")
    p = pathlib.Path(raw).expanduser().resolve()
    if not p.is_dir():
        raise DataError(f"data dir {p} does not exist")
    if repo_root is not None and p.is_relative_to(repo_root.resolve()):
        raise DataError(f"data dir {p} is inside the repo; third-party data stays outside it")
    return p


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# -- manifest -------------------------------------------------------------------------

def check_entry(e: dict, where: str) -> dict:
    missing = [k for k in MANIFEST_FIELDS if not e.get(k)]
    if missing:
        raise DataError(f"{where}: missing {', '.join(missing)}")
    if e["source"] not in SOURCES:
        raise DataError(f"{where}: unknown source {e['source']!r}")
    p = pathlib.PurePosixPath(e["path"])
    if p.is_absolute() or ".." in p.parts:
        raise DataError(f"{where}: path must be relative to the data dir, without '..'")
    loc = e["locator"]
    if not isinstance(loc, dict) or not loc.get("sheet") or not (loc.get("row") or loc.get("cell")):
        raise DataError(f"{where}: locator needs sheet and row (or cell)")
    if e.get("crosscheck") is not None and e["crosscheck"] not in CROSSCHECK:
        raise DataError(f"{where}: crosscheck must be one of {sorted(CROSSCHECK)}")
    if len(e["sha256"]) != 64:
        raise DataError(f"{where}: sha256 must be 64 hex characters")
    return e


def parse_manifest(text: str, source: str = "<manifest>") -> list[dict]:
    out, seen = [], set()
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError as exc:
            raise DataError(f"{source}:{n}: not JSON: {exc}") from exc
        check_entry(e, f"{source}:{n}")
        if e["id"] in seen:
            raise DataError(f"{source}:{n}: duplicate id {e['id']!r}")
        seen.add(e["id"])
        out.append(e)
    if not out:
        raise DataError(f"{source}: empty manifest")
    return out


def manifest_line(e: dict) -> str:
    keep = ("id", "source", "path", "sha256", "locator", "category", "functions",
            "crosscheck", "crosscheck_stale", "flags")
    return json.dumps({k: e[k] for k in keep if k in e}, sort_keys=False)


# -- reading one case ---------------------------------------------------------------

class SourceCache:
    """Parsed source files, each sha-checked once."""

    def __init__(self, data_dir: pathlib.Path):
        self.data_dir = data_dir
        self._sheets: dict[str, Any] = {}

    def sheets(self, rel: str, want_sha: Optional[str]) -> dict:
        if rel not in self._sheets:
            path = (self.data_dir / rel).resolve()
            if not path.is_relative_to(self.data_dir):
                raise DataError(f"{rel}: escapes the data dir")
            if not path.is_file():
                raise DataError(f"{rel}: not found in {self.data_dir}")
            got = sha256(path)
            self._sheets[rel] = (got, sources.read_fods(path) if rel.endswith(".fods")
                                 else sources.read_xlsx(path))
        got, sheets = self._sheets[rel]
        if want_sha and got != want_sha:
            raise DataError(f"{rel}: sha256 {got[:12]}… does not match the manifest "
                            f"({want_sha[:12]}…) — the corpus changed; re-select")
        return sheets


def extract(entry: dict, cache: SourceCache) -> dict:
    sheets = cache.sheets(entry["path"], entry.get("sha256"))
    loc = entry["locator"]
    if entry["source"] == "libreoffice":
        return sources.lo_case(sheets, loc["sheet"], int(loc["row"]))
    return sources.xlsx_case(sheets, loc["sheet"], loc["cell"])


# -- materialise: manifest -> cases + fixture (in memory only) ----------------------------

_SF_TYPES = {"num": ("FLOAT", "DOUBLE"), "str": ("VARCHAR", "VARCHAR"),
             "date": ("DATE", "DATE"), "bool": ("BOOLEAN", "BOOL")}


def input_column_key(entry: dict, inp: dict) -> tuple:
    return (entry["path"], entry["locator"]["sheet"], inp["cell"], inp["kind"],
            json.dumps(inp["value"]))


def materialise(entries: list[dict], cache: SourceCache, licence_note: str = "") -> tuple[list[dict], dict, list[dict]]:
    """Cases, the one fixture, and the entries that no longer extract (loud, not dropped)."""
    columns: dict[tuple, str] = {}
    col_specs = [{"name": KEY, "sf_type": "NUMBER(38,0)", "ts_type": "INT64",
                  "column_type": "ATTRIBUTE"},
                 {"name": BLANK_COLUMN, "sf_type": "FLOAT", "ts_type": "DOUBLE",
                  "column_type": "ATTRIBUTE"}]
    row: dict[str, Any] = {KEY: 1, BLANK_COLUMN: None}
    cases, broken = [], []
    for e in entries:
        raw = extract(e, cache)
        if "skip" in raw:
            broken.append({"id": e["id"], "reason": raw["skip"]})
            continue
        letters: dict[str, str] = {}
        for inp in raw["inputs"]:
            if inp["kind"] == "blank":
                letters[inp["letter"]] = BLANK_COLUMN
                continue
            k = input_column_key(e, inp)
            if k not in columns:
                name = f"X{len(columns) + 1}"
                columns[k] = name
                sf, ts = _SF_TYPES[inp["kind"]]
                col_specs.append({"name": name, "sf_type": sf, "ts_type": ts,
                                  "column_type": "ATTRIBUTE"})
                row[name] = inp["value"]
            letters[inp["letter"]] = columns[k]
        src = SOURCES[e["source"]]
        case = {
            "id": e["id"], "dialect": "excel", "source_formula": raw["formula"],
            "role": "row", "fixture": FIXTURE_NAME, "group_by": None,
            "expected": {"key_column": KEY, "values": {"1": raw["expected"]}},
            "tolerance": raw["tolerance"], "inputs": letters,
            "input_kinds": {i["letter"]: i["kind"] for i in raw["inputs"]},
            "functions": raw["functions"], "flags": raw["flags"],
            "crosscheck": e.get("crosscheck"), "source": e["source"],
            "provenance": {"source": f"{e['source']}:{e['path']}", "licence": src["licence"],
                           "oracle_tier": src["tier"], "oracle_by": src["by"]},
        }
        if "blank-input" in raw["flags"]:
            case["known_divergence"] = dict(BLANK_DIVERGENCE)
        elif e["id"] in CASE_DIVERGENCES:
            case["known_divergence"] = dict(CASE_DIVERGENCES[e["id"]])
        cases.append(case)
    fixture = {"name": FIXTURE_NAME, "key": KEY, "columns": col_specs, "rows": [row],
               "session": {"TIMEZONE": "UTC"}}
    return cases, fixture, broken


def literal_oracle(case: dict) -> dict:
    """The oracle of record is the value stored in the source file — no query is run."""
    return {"sql": None, "oracle": "literal", "values": dict(case["expected"]["values"]),
            "error": None}


def column_context(case: dict, fixture: dict, ts_table: str) -> list[dict]:
    """``--columns`` for one case: its own input letters -> the fixture columns."""
    types = {c["name"]: c for c in fixture["columns"]}
    out = [{"source": KEY, "table": ts_table, "column": KEY, "data_type": "INT64",
            "column_type": "ATTRIBUTE", "key": True}]
    for letter, col in sorted(case.get("inputs", {}).items()):
        out.append({"source": letter, "table": ts_table, "column": col,
                    "data_type": types[col]["ts_type"], "column_type": "ATTRIBUTE",
                    "key": False})
    return out


def classify_error_expected(case: dict, item: dict) -> Optional[dict]:
    """A verdict for a case whose corpus value IS an error (``#DIV/0!``, ``#VALUE!``, …).

    M0's ``classify_case`` reads an all-error oracle as an authoring error (ORACLE_FAILED):
    right for a warehouse oracle, wrong for a literal one, where the error is the expected
    result. Returns None for any other case. The comparison is the same rule: NULL or an
    error from ThoughtSpot is ERROR_EQUIV, a value is ERROR_VS_VALUE (never a match).
    """
    from fidelity.compare import (ERROR_EQUIV, ERROR_VS_VALUE, IMPORT_FAILED, MISMATCH,
                                  RUN_FAILED, TRANSLATE_FAILED, compare_value)

    vals = (case.get("expected") or {}).get("values") or {}
    if not vals or not all(v["t"] == "error" for v in vals.values()):
        return None
    tr = item.get("translation") or {}
    out = {"id": case["id"], "translation_status": tr.get("status"), "rows": [],
           "mismatch_kinds": [], "silent_wrong": False, "warned": False,
           "stale_divergence": False, "detail": None, "error_expected": True}
    if tr.get("status") not in ("TRANSLATED", "APPROXIMATED"):
        return {**out, "verdict": TRANSLATE_FAILED}
    if item.get("import_error"):
        return {**out, "verdict": IMPORT_FAILED, "detail": item["import_error"]}
    actual = item.get("actual")
    if actual is None:
        return {**out, "verdict": RUN_FAILED, "detail": "not queried"}
    avals = actual.get("values") or {}
    if not avals:
        if actual.get("error") and not actual.get("zero_rows"):
            return {**out, "verdict": ERROR_EQUIV, "detail": actual["error"]}
        return {**out, "verdict": RUN_FAILED, "detail": actual.get("error")}
    kinds = {compare_value(vals[k], avals.get(k, {"t": "null"}), case["tolerance"]) for k in vals}
    if kinds == {ERROR_EQUIV}:
        return {**out, "verdict": ERROR_EQUIV}
    return {**out, "verdict": MISMATCH, "mismatch_kinds": [ERROR_VS_VALUE]}
