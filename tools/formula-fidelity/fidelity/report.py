"""Markdown report for one run. Leads with silent wrong answers (design §7).

A *silent wrong answer* is a case the translator marked TRANSLATED or APPROXIMATED, whose
formula imported cleanly, and whose query returned a different value from the oracle.
It is split into *unexplained* (no known-divergence tag: a converter bug until shown
otherwise) and *explained* (a documented platform semantic or an already-filed bug).
A single match ratio is never the headline — the SV study's lesson is that it hides
exactly this class.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from fidelity.compare import (
    ERROR_EQUIV, IMPORT_FAILED, MATCH, MISMATCH, ORACLE_FAILED, RUN_FAILED,
    TRANSLATE_FAILED, VERDICTS, WRONG_OUTCOMES, counts,
)

_VERDICT_GLOSS = {
    MISMATCH: "ran, returned a different value (silent wrong)",
    RUN_FAILED: "imported, but the AgentQL query failed where the source returned a value",
    IMPORT_FAILED: "translated, but ThoughtSpot rejected the formula (VALIDATE_ONLY)",
    TRANSLATE_FAILED: "the translator declined (NEEDS_REVIEW)",
    ERROR_EQUIV: "the source errored and ThoughtSpot returned NULL / an error",
    ORACLE_FAILED: "the source formula failed in the warehouse on every key (authoring error)",
    MATCH: "every key equal under the comparison rules",
}


def _md(s: Any) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


_TABLE = {"name": None}


def _short(s: Optional[str]) -> Optional[str]:
    """Display form: the run's long scratch Table name shown as ``T``."""
    t = _TABLE["name"]
    return s.replace(f"[{t}::", "[T::") if s and t else s


def _code(s: Optional[str]) -> str:
    if s is None:
        return "—"
    s = _short(str(s)).replace("\n", " ")
    return "`" + s.replace("`", "'").replace("|", "\\|") + "`"


def fmt_value(c: Optional[dict]) -> str:
    if c is None:
        return "(absent)"
    t = c["t"]
    if t == "null":
        return "NULL"
    if t == "error":
        return f"ERROR: {c['v']}"
    if t == "str":
        return repr(c["v"])
    return str(c["v"]).lower() if t == "bool" else str(c["v"])


def referenced_columns(formula: str, fixture: dict) -> list[str]:
    """Fixture columns a source formula names (word match outside string literals)."""
    bare = re.sub(r"'(?:[^']|'')*'", "''", formula)
    return [c["name"] for c in fixture["columns"]
            if re.search(rf"\b{re.escape(c['name'])}\b", bare, re.I)]


def repro_rows(case: dict, fixture: dict, key: str) -> list[dict]:
    cols = referenced_columns(case["source_formula"], fixture)
    kcol = case["group_by"] if case["role"] == "aggregate" else fixture["key"]
    keep = [fixture["key"]] + ([kcol] if kcol != fixture["key"] else []) + \
        [c for c in cols if c not in (fixture["key"], kcol)]
    return [{c: r.get(c) for c in keep} for r in fixture["rows"] if str(r.get(kcol)) == key]


def _wrong_rows(result: dict) -> list[dict]:
    return [r for r in result.get("rows", []) if r["outcome"] in WRONG_OUTCOMES]


def _silent_section(title: str, items: list[dict], fixtures: dict, lines: list[str],
                    with_repro: bool) -> None:
    lines.append(f"### {title} ({len(items)})")
    lines.append("")
    if not items:
        lines.append("None.")
        lines.append("")
        return
    lines.append("| Case | Source | Emitted | Status | Wrong keys | Cause |")
    lines.append("|---|---|---|---|--:|---|")
    for it in items:
        res, tr = it["result"], it.get("translation") or {}
        cause = res.get("cause") or {}
        c = cause.get("tag", "unexplained")
        if cause.get("backlog"):
            c += f" ({cause['backlog']})"
        lines.append(f"| {it['id']} | {_code(it['source_formula'])} | {_code(tr.get('formula'))} "
                     f"| {tr.get('status')} | {len(_wrong_rows(res))}/{len(res.get('rows', []))} "
                     f"| {_md(c)} |")
    lines.append("")
    if not with_repro:
        return
    for it in items:
        res = it["result"]
        wrong = _wrong_rows(res)
        if not wrong:
            continue
        w = wrong[0]
        fx = fixtures[it["fixture"]]
        lines.append(f"**{it['id']}** — minimal repro (key {w['key']}):")
        lines.append("")
        lines.append(f"- source (Snowflake): `{it['source_formula']}`")
        lines.append(f"- emitted (ThoughtSpot): `{_short((it.get('translation') or {}).get('formula'))}`")
        sql = (it.get("actual") or {}).get("sql")
        if sql:
            lines.append(f"- compiled SQL (value expression): `{_value_sql(sql)}`")
        lines.append(f"- input: `{repro_rows(it, fx, w['key'])}`")
        lines.append(f"- expected {fmt_value(w['expected'])}, ThoughtSpot returned "
                     f"{fmt_value(w['actual'])} ({w['outcome']})")
        others = [f"{r['key']}: {fmt_value(r['expected'])} vs {fmt_value(r['actual'])}"
                  for r in wrong[1:]]
        if others:
            lines.append(f"- other wrong keys: {'; '.join(others)}")
        lines.append("")


def _value_sql(sql: str) -> str:
    """The SELECT's second expression (the formula), from AgentQL's generated SQL."""
    m = re.search(r'"ca_1",\s*(.*?)\s+"ca_2"', sql, re.S)
    return re.sub(r"\s+", " ", m.group(1)) if m else re.sub(r"\s+", " ", sql)[:200]


def build_report(run: dict, fixtures: dict[str, dict], title: str) -> str:
    items = run["cases"]
    _TABLE["name"] = run["run"].get("ts_table")
    results = [it["result"] for it in items]
    cnt = counts(results)
    silent = [it for it in items if it["result"].get("silent_wrong")]
    def kind(it):
        return (it["result"].get("cause") or {}).get("kind")

    unexplained = [it for it in silent if kind(it) is None]
    bugs = [it for it in silent if kind(it) == "translator-bug"]
    semantics = [it for it in silent if kind(it) == "platform-semantics"]
    meta = run["run"]

    lines = [f"# {title}", ""]
    lines.append(
        f"**{len(silent)} silent wrong answer(s)** in {len(items)} cases: "
        f"{len(bugs)} translator bug(s) with an open BL item, {len(unexplained)} unexplained, "
        f"{len(semantics)} documented platform semantics the translator already warns about. "
        f"{cnt[MATCH]} of {len(items)} matched.")
    lines.append("")
    lines.append(
        "A silent wrong answer is a case the translator marked TRANSLATED or APPROXIMATED, "
        "that imported cleanly, and that returned a different value from the oracle. "
        "The oracle is the warehouse itself: each source formula is run as a Snowflake "
        "SELECT over the same fixture rows ThoughtSpot queries.")
    lines.append("")
    if meta.get("ts_table"):
        lines.append(f"In emitted formulas `[T::col]` is the run's scratch Table, "
                     f"`{meta['ts_table']}`.")
        lines.append("")
    lines.append("## Silent wrong answers")
    lines.append("")
    _silent_section("Unexplained", unexplained, fixtures, lines, with_repro=True)
    _silent_section("Translator bugs (open BL item)", bugs, fixtures, lines, with_repro=True)
    _silent_section("Documented platform semantics (translator warns)", semantics, fixtures,
                    lines, with_repro=True)

    lines.append("## Counts by class")
    lines.append("")
    lines.append("| Class | Cases | Meaning |")
    lines.append("|---|--:|---|")
    for v in VERDICTS:
        lines.append(f"| {v} | {cnt[v]} | {_VERDICT_GLOSS[v]} |")
    lines.append(f"| **Total** | **{len(items)}** | |")
    lines.append("")

    loud = [it for it in items if it["result"]["verdict"] in
            (RUN_FAILED, IMPORT_FAILED, TRANSLATE_FAILED, ORACLE_FAILED, ERROR_EQUIV)]
    lines.append("## Loud failures and error-equivalents")
    lines.append("")
    if loud:
        lines.append("| Case | Class | Source | Detail / cause |")
        lines.append("|---|---|---|---|")
        for it in loud:
            r = it["result"]
            d = r.get("detail")
            kd = it.get("known_divergence") or {}
            if kd.get("backlog") and r["verdict"] != ERROR_EQUIV:
                d = f"{kd['backlog']}: {d}"
            if r["verdict"] == ERROR_EQUIV:
                cause = r.get("cause") or {}
                d = cause.get("tag", "unexplained") + (f" ({cause['backlog']})"
                                                       if cause.get("backlog") else "")
            lines.append(f"| {it['id']} | {r['verdict']} | {_code(it['source_formula'])} "
                         f"| {_md(d)[:240]} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Per-case results")
    lines.append("")
    lines.append("| Case | Role | Source | Emitted | Status | Verdict | Keys equal |")
    lines.append("|---|---|---|---|---|---|--:|")
    for it in items:
        r, tr = it["result"], it.get("translation") or {}
        rows = r.get("rows", [])
        eq = sum(1 for x in rows if x["outcome"] == "EQUAL")
        lines.append(f"| {it['id']} | {it['role']} | {_code(it['source_formula'])} "
                     f"| {_code(tr.get('formula'))} | {tr.get('status')} | {r['verdict']} "
                     f"| {eq}/{len(rows) if rows else '—'} |")
    lines.append("")

    lines.append("## Run")
    lines.append("")
    for k in ("date", "profile", "connection", "warehouse_table", "sf_profile",
              "cases_file", "cases_sha256", "translator_version", "runtime_s"):
        if k in meta:
            lines.append(f"- {k}: `{meta[k]}`")
    phases = meta.get("phases") or {}
    if phases:
        lines.append("- phases (s): " + ", ".join(f"{k} {v}" for k, v in phases.items()))
    cl = meta.get("cleanup") or {}
    lines.append(f"- cleanup: ThoughtSpot objects confirmed absent = "
                 f"`{cl.get('ts_confirmed_absent')}`, warehouse table dropped and confirmed = "
                 f"`{cl.get('warehouse_confirmed_absent')}`")
    if cl.get("remaining"):
        lines.append(f"- **objects left behind:** `{cl['remaining']}`")
    if meta.get("orphans"):
        lines.append(f"- pre-existing orphans found by the startup sweep (not touched): "
                     f"`{meta['orphans']}`")
    lines.append("")
    return "\n".join(lines)
