#!/usr/bin/env python3
"""Build AgentQL Quest, the browser game for the Learn AgentQL course.

Joins two sources into one self-contained `index.html`:

  - `references/lesson-sql.md` of the ts-object-model-agentql-query skill: the AgentQL and
    the warehouse SQL ThoughtSpot generated for each lesson, captured live and committed.
    It is the only source of SQL; the game never carries a hand-written copy.
  - `encounters.yaml` (next to this script): which parts of that SQL the game asks about,
    who put each one there, and the text the player reads.

The data is written into the page rather than shipped beside it, so the file runs from
GitHub Pages, any static host, or a double-click with no server.

    python3 tools/agentql-quest/build.py                   # write tools/agentql-quest/dist/index.html
    python3 tools/agentql-quest/build.py --out _site/index.html
    python3 tools/agentql-quest/build.py --check           # validate only (pre-commit, CI)

Fails when an encounter no longer matches the capture: a missing or rejected case, AgentQL
that differs by more than layout, or a highlight that hits no line of the SQL. A recapture
that changes a lesson therefore breaks the build instead of quietly highlighting nothing.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LESSON_SQL = ROOT / "agents/cli/ts-object-model-agentql-query/references/lesson-sql.md"
ENCOUNTERS = HERE / "encounters.yaml"
TEMPLATE = HERE / "game.html"
DEFAULT_OUT = HERE / "dist" / "index.html"
PLACEHOLDER = "__QUEST_DATA__"

PATHS = ("dwarf", "elf", "human")
WHO_ANSWERS = {"model": "forge", "thoughtspot": "forge", "agentql": "agentql"}
WHO_ORDER = ("forge", "agentql", "ai")
ALL = "*"


def parse_lesson_sql(text: str) -> tuple[str | None, dict[str, dict]]:
    """Read the capture date and, per case id, its AgentQL and generated SQL (None if rejected).

    The layout is fixed by tools/agentql-retest/build_lesson_sql.py: a `## <case id>` heading,
    an AgentQL ```sql block, then a second ```sql block only when the status was SUCCESS.
    """
    m = re.search(r"captured live on .*? on\s+(\d{4}-\d{2}-\d{2})", text, re.S)
    date = m.group(1) if m else None
    cases: dict[str, dict] = {}
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        cid = block.split("\n", 1)[0].strip()
        blocks = re.findall(r"```sql\n(.*?)\n```", block, re.S)
        ok = "`status: SUCCESS`" in block and len(blocks) > 1
        cases[cid] = {"agentql": blocks[0] if blocks else "", "sql": blocks[1] if ok else None}
    return date, cases


def _norm(sql: str) -> str:
    """Collapse whitespace and drop it around brackets and commas: only layout may differ."""
    return re.sub(r"\s*([(),])\s*", r"\1", " ".join(sql.split()))


def _highlight(matches: list[str], lines: list[str], where: str, errors: list[str]) -> list[int] | str:
    if ALL in matches:
        return "all"
    hits: set[int] = set()
    for m in matches:
        found = [i for i, line in enumerate(lines) if m in line]
        if not found:
            errors.append(f"{where}: match {m!r} hits no line")
        hits.update(found)
    return sorted(hits)


def _point(p: dict, who: dict, sql: list[str], scroll: list[str], where: str, errors: list[str]) -> dict:
    out = {
        "ask": p.get("ask", ""), "hint": p.get("hint", ""), "lesson": p.get("lesson", ""),
        "sqlHl": _highlight(p.get("sql") or [], sql, f"{where} sql", errors),
        "scrollHl": _highlight(p.get("scroll") or [], scroll, f"{where} scroll", errors),
    }
    for field in ("ask", "hint", "lesson"):
        if not out[field]:
            errors.append(f"{where}: missing {field}")
    kind = p.get("kind")
    if kind == "who":
        target = WHO_ANSWERS.get(p.get("answer"))
        if target is None:
            errors.append(f"{where}: answer must be one of {sorted(WHO_ANSWERS)}, got {p.get('answer')!r}")
            target = "forge"
        out["options"] = [who[k] for k in WHO_ORDER]
        out["correct"] = WHO_ORDER.index(target)
    elif kind == "choice":
        opts = p.get("options") or []
        correct = [i for i, o in enumerate(opts) if o.get("correct")]
        if len(opts) < 2 or len(correct) != 1:
            errors.append(f"{where}: a choice needs 2+ options and exactly one correct")
        out["options"] = [o.get("text", "") for o in opts]
        out["correct"] = correct[0] if correct else 0
    else:
        errors.append(f"{where}: kind must be 'who' or 'choice', got {kind!r}")
    return out


def compile_quest(doc: dict, date: str | None, cases: dict[str, dict]) -> tuple[dict, list[str]]:
    """Turn encounters.yaml plus the capture into the game's data. Returns (data, errors)."""
    errors: list[str] = []
    who = doc.get("who_options") or {}
    missing = [k for k in WHO_ORDER if not who.get(k)]
    if missing:
        errors.append(f"who_options: missing {missing}")
    if not date:
        errors.append("lesson-sql.md: no capture date found in its header")

    encounters, paths = [], {p: [] for p in PATHS}
    for n, e in enumerate(doc.get("encounters") or [], 1):
        cid = e.get("case", f"#{n}")
        cap = cases.get(cid)
        if cap is None:
            errors.append(f"{cid}: not in lesson-sql.md")
            continue
        if cap["sql"] is None:
            errors.append(f"{cid}: captured status was not SUCCESS, so there is no SQL to fight")
            continue
        agentql = (e.get("agentql") or "").rstrip("\n")
        if _norm(agentql) != _norm(cap["agentql"]):
            errors.append(f"{cid}: agentql differs from the captured AgentQL (only layout may differ)")
        sql_lines, scroll_lines = cap["sql"].splitlines(), agentql.splitlines()
        points = [_point(p, who, sql_lines, scroll_lines, f"{cid} point {i}", errors)
                  for i, p in enumerate(e.get("points") or [], 1)]
        if not points:
            errors.append(f"{cid}: no points")
        for field in ("quest", "why_agentql", "loot", "takeaway"):
            if not e.get(field):
                errors.append(f"{cid}: missing {field}")
        for path in e.get("paths") or []:
            if path not in paths:
                errors.append(f"{cid}: unknown path {path!r} (known: {list(PATHS)})")
            else:
                paths[path].append(len(encounters))
        encounters.append({
            "case": cid, "quest": e.get("quest", ""), "whyAgentql": e.get("why_agentql", ""),
            "agentql": scroll_lines, "sql": sql_lines, "points": points,
            "loot": e.get("loot", ""), "takeaway": e.get("takeaway", ""),
        })

    court = []
    for i, c in enumerate(doc.get("court") or [], 1):
        if not c.get("claim") or not c.get("why") or not isinstance(c.get("truth"), bool):
            errors.append(f"court claim {i}: needs claim, why and a true/false truth")
        court.append({"claim": c.get("claim", ""), "truth": bool(c.get("truth")), "why": c.get("why", "")})
    if not court:
        errors.append("court: no claims")

    return {"captured": date, "encounters": encounters, "paths": paths, "court": court}, errors


def render(template: str, data: dict) -> str:
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"game.html must contain {PLACEHOLDER} exactly once")
    # Inside <script type="application/json">, "</" could close the tag; "<\/" is the same JSON.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return template.replace(PLACEHOLDER, payload)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output HTML (default: tools/agentql-quest/dist/index.html)")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    ap.add_argument("--root", help="accepted for parity with the other validators; paths resolve from this script")
    args = ap.parse_args(argv)

    date, cases = parse_lesson_sql(LESSON_SQL.read_text(encoding="utf-8"))
    doc = yaml.safe_load(ENCOUNTERS.read_text(encoding="utf-8")) or {}
    data, errors = compile_quest(doc, date, cases)
    if errors:
        print("agentql-quest: encounters.yaml no longer matches lesson-sql.md:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    html = render(TEMPLATE.read_text(encoding="utf-8"), data)
    n_points = sum(len(e["points"]) for e in data["encounters"])
    if args.check:
        print(f"agentql-quest: OK ({len(data['encounters'])} encounters, {n_points} points, {len(data['court'])} court claims)")
        return 0
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"agentql-quest: wrote {out} ({len(data['encounters'])} encounters, {n_points} points)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
