"""What an M1 run may commit, and the scanner that proves nothing third-party leaked.

The user's rule (2026-10-06): third-party formulas and values stay in the data dir. A
committed result carries, per case, only the id, where it came from (file + locator, via the
manifest), the function names, the translator status and the verdict class. Repros for
failures are written by hand, in our own words, in the review.

- ``redact_run``         full run JSON (data dir) -> committable results
- ``classify_m1``        M1's verdict classes (silent wrong first)
- ``build_report``       the generated part of the review (tables only, no formulas)
- ``scan_committed``     heuristic leak scan for committed files (CI test, no data dir)
- ``leaks_against_corpus`` exact scan against the corpus (run time, with the data dir)
"""
from __future__ import annotations

import collections
import json
import re
from typing import Any, Iterable, Optional

from fidelity.compare import (ERROR_EQUIV, IMPORT_FAILED, MATCH, MISMATCH, ORACLE_FAILED,
                              RUN_FAILED, TRANSLATE_FAILED)

# M1 classes, in report order.
SILENT_WRONG = "SILENT_WRONG"
WARNED_WRONG = "WARNED_WRONG"
DIVERGENCE_BLANK = "DIVERGENCE_BLANK"     # Excel blank vs warehouse NULL (documented)
DIVERGENCE_ERROR = "DIVERGENCE_ERROR"     # Excel errors, ThoughtSpot returns a value
ORACLE_DISPUTED = "ORACLE_DISPUTED"       # bronze cross-check disagreed: not run, not scored
CLASSES = (SILENT_WRONG, WARNED_WRONG, DIVERGENCE_BLANK, DIVERGENCE_ERROR, RUN_FAILED,
           IMPORT_FAILED, TRANSLATE_FAILED, ERROR_EQUIV, ORACLE_FAILED, MATCH, ORACLE_DISPUTED)
CLASS_MEANING = {
    SILENT_WRONG: "imported, ran, returned a different value, and the translator said "
                  "TRANSLATED (or APPROXIMATED with no trap)",
    WARNED_WRONG: "a different value, but the translator said APPROXIMATED and named a trap",
    DIVERGENCE_BLANK: "an input cell is blank: Excel reads 0 / '', the warehouse column is "
                      "NULL (documented divergence, not scored as a match)",
    DIVERGENCE_ERROR: "Excel returns an error value; ThoughtSpot returns a value "
                      "(documented divergence, not scored as a match)",
    RUN_FAILED: "imported, but the AgentQL query failed or returned no rows",
    IMPORT_FAILED: "ThoughtSpot rejected the translated formula (VALIDATE_ONLY)",
    TRANSLATE_FAILED: "the translator declined (NEEDS_REVIEW)",
    ERROR_EQUIV: "Excel returns an error; ThoughtSpot returns NULL or an error",
    ORACLE_FAILED: "the corpus has no usable expected value",
    MATCH: "equal under the comparison rules",
    ORACLE_DISPUTED: "the `formulas` cross-check disagrees with the corpus value: "
                     "quarantined, not run, not scored",
}

# "agentql" is not here: it is also a run phase name. The statement it would hold carries only
# the scratch formula name; the formula text is in "formula" / "sql", which are.
FORBIDDEN_KEYS = {"formula", "source_formula", "expected", "actual", "values", "sql",
                  "inputs", "tokens", "letters", "rows", "notes", "traps"}


def classify_m1(result: dict, case: dict) -> str:
    v = result["verdict"]
    if v != MISMATCH:
        return v
    if "blank-input" in (case.get("flags") or []):
        return DIVERGENCE_BLANK
    if set(result.get("mismatch_kinds") or []) == {"ERROR_VS_VALUE"}:
        return DIVERGENCE_ERROR
    return WARNED_WRONG if result.get("warned") else SILENT_WRONG


_CODE = re.compile(r"error_code[^0-9]*(\d+)|\((\d{4,6})\)")


def sanitize(msg: Optional[str]) -> Optional[str]:
    """An error message without anything that can carry the case's text: quoted strings,
    brackets, parentheses and formula names are dropped."""
    if not msg:
        return None
    m = _CODE.search(msg)
    s = re.sub(r"'[^']*'|\"[^\"]*\"|\[[^\]]*\]|\([^)]*\)|Formula: *\S+|f_[A-Za-z0-9_]+",
               "…", msg)
    s = re.sub(r"\s+", " ", s).strip()[:120]
    code = (m.group(1) or m.group(2)) if m else None
    return f"{s} [code {code}]" if code else s


def redact_run(full: dict, entries: list[dict], disputed: Iterable[dict]) -> dict:
    by_entry = {e["id"]: e for e in entries}
    meta = full["run"]
    keep = ("date", "profile", "connection", "warehouse_table", "ts_table", "ts_model",
            "translator_version", "runtime_s", "phases", "aborted")
    run = {k: meta.get(k) for k in keep if meta.get(k) is not None}
    if run.get("aborted"):
        run["aborted"] = sanitize(run["aborted"])
    cl = meta.get("cleanup") or {}
    run["cleanup"] = {k: cl.get(k) for k in ("ts_confirmed_absent", "warehouse_confirmed_absent",
                                             "remaining", "not_owned", "errors")}
    run["startup_orphans"] = {"thoughtspot": len(meta.get("orphans") or []),
                              "warehouse": len(meta.get("warehouse_orphans") or [])}
    rows = []
    for it in full["cases"]:
        e = by_entry.get(it["id"], {})
        res = it["result"]
        tr = it.get("translation") or {}
        cause = res.get("cause") or {}
        rows.append({
            "id": it["id"], "source": e.get("source"), "category": e.get("category"),
            "functions": e.get("functions"), "flags": e.get("flags") or [],
            "crosscheck": e.get("crosscheck"), "translation_status": tr.get("status"),
            "trap_count": len(tr.get("traps") or []), "verdict": res["verdict"],
            "class": classify_m1(res, e), "mismatch_kinds": res.get("mismatch_kinds") or [],
            "cause_tag": cause.get("tag"), "backlog": cause.get("backlog"),
            "detail": sanitize(res.get("detail")) if res["verdict"] in
            (IMPORT_FAILED, RUN_FAILED) else None})
    for e in disputed:
        rows.append({"id": e["id"], "source": e["source"], "category": e.get("category"),
                     "functions": e.get("functions"), "flags": e.get("flags") or [],
                     "crosscheck": "disputed", "translation_status": None, "trap_count": 0,
                     "verdict": None, "class": ORACLE_DISPUTED, "mismatch_kinds": [],
                     "cause_tag": None, "backlog": None, "detail": None})
    run["summary"] = summarise(rows)
    return {"run": run, "cases": rows}


def summarise(rows: list[dict]) -> dict:
    by_class = {c: 0 for c in CLASSES}
    by_source: dict[str, dict[str, int]] = {}
    for r in rows:
        by_class[r["class"]] += 1
        s = by_source.setdefault(r["source"] or "?", {c: 0 for c in CLASSES})
        s[r["class"]] += 1
    scored = sum(v for k, v in by_class.items() if k != ORACLE_DISPUTED)
    return {"cases": len(rows), "scored": scored, "silent_wrong": by_class[SILENT_WRONG],
            "oracle_disputed": by_class[ORACLE_DISPUTED], "by_class": by_class,
            "by_source": by_source}


# =====================================================================================
# report (generated part)
# =====================================================================================

MARKER = "<!-- generated by tools/formula-fidelity/run_literal.py: edit above this line -->"


def build_report(red: dict, title: str = "") -> str:
    s = red["run"]["summary"]
    rows = red["cases"]
    out = [MARKER, "", "## Counts by class", "",
           "| Class | LibreOffice | POI | Total | Meaning |", "|---|--:|--:|--:|---|"]
    for c in CLASSES:
        lo = s["by_source"].get("libreoffice", {}).get(c, 0)
        poi = s["by_source"].get("poi", {}).get(c, 0)
        out.append(f"| {c} | {lo} | {poi} | {s['by_class'][c]} | {CLASS_MEANING[c]} |")
    out += [f"| **Total** | {sum(s['by_source'].get('libreoffice', {}).values())} | "
            f"{sum(s['by_source'].get('poi', {}).values())} | **{s['cases']}** | |", ""]
    out += ["## By function", "",
            "| Function | Cases | Match | Silent wrong | Warned | Divergence | Loud | "
            "Error-equiv | Disputed |",
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    fn: dict[str, collections.Counter] = {}
    for r in rows:
        lead = (r["functions"] or ["(operators)"])[0]
        fn.setdefault(lead, collections.Counter())[r["class"]] += 1
    for lead in sorted(fn):
        c = fn[lead]
        out.append(f"| {lead} | {sum(c.values())} | {c[MATCH]} | {c[SILENT_WRONG]} | "
                   f"{c[WARNED_WRONG]} | {c[DIVERGENCE_BLANK] + c[DIVERGENCE_ERROR]} | "
                   f"{c[RUN_FAILED] + c[IMPORT_FAILED] + c[TRANSLATE_FAILED]} | "
                   f"{c[ERROR_EQUIV]} | {c[ORACLE_DISPUTED]} |")
    out += ["", "## Per-case results", "",
            "Case ids name the source file and its row or cell; the formula and values are in "
            "the corpus (data dir), not here.", "",
            "| Case | Functions | Translator | Class | Mismatch | Cause / detail |",
            "|---|---|---|---|---|---|"]
    order = {c: i for i, c in enumerate(CLASSES)}
    for r in sorted(rows, key=lambda r: (order[r["class"]], r["id"])):
        cause = r.get("backlog") or r.get("cause_tag") or r.get("detail") or ""
        if cause == "unexplained":
            cause = ""
        out.append(f"| {r['id']} | {', '.join(r['functions'] or []) or '(operators)'} | "
                   f"{r['translation_status'] or '—'} | {r['class']} | "
                   f"{', '.join(r['mismatch_kinds']) or ''} | {cause} |")
    run = red["run"]
    cl = run["cleanup"]
    out += ["", "## Run", "",
            f"- date {run.get('date')}, profile `{run.get('profile')}`, connection "
            f"`{run.get('connection')}`, {run.get('translator_version')}",
            f"- scratch objects: warehouse `{run.get('warehouse_table')}`, Table "
            f"`{run.get('ts_table')}`, Model `{run.get('ts_model')}`",
            f"- cleanup: ThoughtSpot confirmed absent **{cl.get('ts_confirmed_absent')}**, "
            f"warehouse confirmed absent **{cl.get('warehouse_confirmed_absent')}**, remaining "
            f"{len(cl.get('remaining') or [])}, not owned {len(cl.get('not_owned') or [])}",
            f"- startup sweep: {run['startup_orphans']['thoughtspot']} ThoughtSpot and "
            f"{run['startup_orphans']['warehouse']} warehouse `ZZ_FIDELITY_*` objects from "
            "earlier runs (reported, not touched)",
            f"- runtime {run.get('runtime_s')} s; phases {json.dumps(run.get('phases'))}"]
    if run.get("aborted"):
        out.append(f"- **ABORTED:** {run['aborted']}")
    return "\n".join(out) + "\n"


def merge_report(prior: str, generated: str) -> str:
    """Keep the hand-written part of an existing report; replace the generated part."""
    if MARKER in prior:
        head = prior.split(MARKER)[0].rstrip() + "\n\n"
    else:
        head = prior.rstrip() + "\n\n" if prior.strip() else ""
    return head + generated


# =====================================================================================
# leak scanning
# =====================================================================================

# A call as a spreadsheet writes it (``NAME(``) or as ThoughtSpot does (``name ( ``) — not a
# prose aside (``word (aside)``).
_CALL = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]*(?:\(| \( )(?:[^()]|\([^()]*\))*\)")
_A1 = re.compile(r"\b[A-Z]{1,2}[0-9]{1,5}\b")
_LITERAL = re.compile(r"\"[^\"]*\"|'[^']*'|\d+\.\d+|\d{3,}")


_PROSE = re.compile(r"\b[A-Za-z]{2,} [a-z]{2,} [a-z]{2,}\b")
_TS_REF = re.compile(r"\[[^\]]*::[^\]]*\]")


def suspicious_calls(text: str) -> list[str]:
    """Formula-shaped text with case-specific content: a call (not a prose aside) carrying a
    quoted string, a decimal or 3+ digit number, an A1 cell, a ``[TABLE::col]`` reference, a
    nested call, or 40+ characters. Generic shapes in our own words (``round ( x , 10 )``,
    ``MID(text, start, n)``) pass."""
    hits = []
    for m in _CALL.finditer(text):
        call = m.group(0)
        inner = call[call.index("(") + 1:-1]
        if _PROSE.search(re.sub(r"\"[^\"]*\"|'[^']*'", "", inner)):
            continue  # an English aside in parentheses, not a formula
        if (len(call) >= 40 or _LITERAL.search(inner) or _A1.search(inner)
                or _TS_REF.search(inner) or "(" in inner):
            hits.append(call[:80])
    return hits


def scan_committed(text: str, is_json: bool = False) -> list[str]:
    findings = [f"formula-like text: {h}" for h in suspicious_calls(text)]
    if is_json:
        def walk(o: Any) -> None:
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in FORBIDDEN_KEYS:
                        findings.append(f"forbidden key: {k}")
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        stripped = text.strip()
        try:
            walk(json.loads(stripped))
        except ValueError:  # JSONL
            walk([json.loads(line) for line in text.splitlines() if line.strip()])
    return findings


def leaks_against_corpus(text: str, cases: list[dict], min_len: int = 10) -> list[str]:
    """Exact substrings of the corpus (formulas, string values) found in ``text``."""
    hits = []
    for c in cases:
        f = (c.get("source_formula") or "").lstrip("=")
        if len(f) >= min_len and f in text:
            hits.append(f"{c['id']}: formula")
        for v in (c.get("expected") or {}).get("values", {}).values():
            if v.get("t") == "str" and len(v.get("v") or "") >= min_len and v["v"] in text:
                hits.append(f"{c['id']}: expected string")
    return hits
