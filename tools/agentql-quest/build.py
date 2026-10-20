#!/usr/bin/env python3
"""Build AgentQL Quest, the browser game for the Learn AgentQL course.

Joins two sources into one self-contained `index.html`:

  - `references/lesson-sql.md` of the ts-object-model-agentql-query skill: the AgentQL and
    the warehouse SQL ThoughtSpot generated for each lesson, captured live and committed.
    It is the only source of SQL; the game never carries a hand-written copy.
  - `encounters.yaml` (next to this script): which parts of that SQL the game asks about,
    who put each one there, and the text the player reads.

The data and the fonts are written into the page rather than shipped beside it, so the file
makes no outside requests and runs from GitHub Pages, any static host, or a double-click.

    python3 tools/agentql-quest/build.py                   # write tools/agentql-quest/dist/index.html
    python3 tools/agentql-quest/build.py --out _site/index.html
    python3 tools/agentql-quest/build.py --check           # validate only (tools/validate/check_agentql_quest.py)

Fails when an encounter no longer matches the capture or the course: a lesson or Module the
text names that the course no longer has, a missing or rejected case, AgentQL
that differs by more than layout, an `sql` line that is no longer in the SQL exactly, or an
`sql_count` that no longer holds. A recapture that changes what a lesson teaches therefore
breaks the build instead of quietly teaching something false.
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LESSON_SQL = ROOT / "agents/cli/ts-object-model-agentql-query/references/lesson-sql.md"
LEARNING_PATH = ROOT / "agents/cli/ts-object-model-agentql-query/references/learning-path.md"
ENCOUNTERS = HERE / "encounters.yaml"
TEMPLATE = HERE / "game.html"
FONT_DIR = HERE / "fonts"
DEFAULT_OUT = HERE / "dist" / "index.html"
PLACEHOLDER = "__QUEST_DATA__"
FONT_PLACEHOLDER = "/*__FONT_FACES__*/"

# (family, weight, file in fonts/) — Latin subsets from Fontsource 5.3.0, SIL OFL 1.1.
FONTS = (
    ("VT323", 400, "vt323-latin-400-normal.woff2"),
    ("IBM Plex Mono", 400, "ibm-plex-mono-latin-400-normal.woff2"),
    ("IBM Plex Mono", 600, "ibm-plex-mono-latin-600-normal.woff2"),
)

PATHS = ("dwarf", "elf", "human")
WHO_ANSWERS = {"model": "forge", "thoughtspot": "forge", "agentql": "agentql"}
WHO_ORDER = ("forge", "agentql", "ai")
ALL = "*"
_STRING = re.compile(r"('(?:[^']|'')*')")


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
    """Normalise layout only: line breaks and indentation may differ, nothing else.

    Outside string literals, runs of whitespace collapse to one space, and whitespace is
    dropped just inside brackets and before commas — the places a reader adds line breaks.
    `(Sample) Retail` and `(Sample)Retail`, or `a, b` and `a,b`, stay different. String
    literals are kept byte for byte.
    """
    parts = _STRING.split(sql)
    for i in range(0, len(parts), 2):
        s = re.sub(r"\s+", " ", parts[i])  # not " ".join(split()): that trims the edges next to a literal
        s = re.sub(r"\(\s+", "(", s)
        s = re.sub(r"\s+([),])", r"\1", s)
        parts[i] = s
    return "".join(parts).strip()


def _scroll_hl(matches: list[str], lines: list[str], where: str, errors: list[str]) -> list[int] | str:
    """AgentQL highlights: substring match (the display copy is already pinned to the capture)."""
    if ALL in matches:
        return "all"
    hits: set[int] = set()
    for m in matches:
        found = [i for i, line in enumerate(lines) if m in line]
        if not found:
            errors.append(f"{where}: match {m!r} hits no line")
        hits.update(found)
    return sorted(hits)


def _sql_hl(matches: list[str], lines: list[str], where: str, errors: list[str]) -> list[int] | str:
    """SQL highlights: each match must equal a whole line (ignoring indentation), so a
    recapture that edits that line — LIMIT 100000 → 1000000, JOIN → LEFT OUTER JOIN — fails."""
    if ALL in matches:
        return "all"
    hits: set[int] = set()
    for m in matches:
        found = [i for i, line in enumerate(lines) if line.strip() == m.strip()]
        if not found:
            errors.append(f"{where}: no SQL line is exactly {m!r}")
        hits.update(found)
    return sorted(hits)


def _point(p: dict, who: dict, sql: list[str], scroll: list[str], where: str, errors: list[str]) -> dict:
    kind = p.get("kind")
    out = {
        "ask": p.get("ask", ""), "hint": p.get("hint", ""), "lesson": p.get("lesson", ""),
        "sqlHl": _sql_hl(p.get("sql") or [], sql, f"{where} sql", errors),
        "scrollHl": _scroll_hl(p.get("scroll") or [], scroll, f"{where} scroll", errors),
    }
    for field in ("ask", "hint", "lesson"):
        if not out[field]:
            errors.append(f"{where}: missing {field}")
    # Facts about the whole statement that a single highlighted line can't pin down,
    # e.g. the fact table appears once (pruning held) or only one join is outer.
    whole = "\n".join(sql)
    for needle, want in (p.get("sql_count") or {}).items():
        got = whole.count(needle)
        if got != want:
            errors.append(f"{where}: expected {needle!r} {want} time(s) in the SQL, found {got}")
    if kind == "who":
        if not p.get("sql"):
            errors.append(f"{where}: a who point must highlight the SQL it asks about")
        target = WHO_ANSWERS.get(p.get("answer"))
        if target is None:
            errors.append(f"{where}: answer must be one of {sorted(WHO_ANSWERS)}, got {p.get('answer')!r}")
            target = "forge"
        out["options"] = [who.get(k, "") for k in WHO_ORDER]
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


def parse_learning_path(text: str) -> tuple[set[str], dict[str, set[str]]]:
    """Module numbers, and per lesson number ("3.4") the case ids its **Guarded by** line names."""
    modules = set(re.findall(r"^## Module (\d+)\b", text, re.M))
    lessons: dict[str, set[str]] = {}
    for m in re.finditer(r"^### (\d+\.\d+)\b(.*?)(?=^##)", text + "\n##", re.S | re.M):
        guarded = re.findall(r"\*\*Guarded by:?\*\*:?([^\n]*)", m.group(2))
        lessons[m.group(1)] = {cid for line in guarded for cid in re.findall(r"`([^`]+)`", line)}
    return modules, lessons


def check_course_refs(encounters_text: str, doc: dict, modules: set[str], lessons: dict[str, set[str]]) -> list[str]:
    """The game's text names lessons and modules by number; the course renumbers them.

    Every "lesson X.Y" / "Module N" (or "Modules N and M") in encounters.yaml must still exist,
    and each encounter's `lesson` must be one whose Guarded by line lists the encounter's case,
    so "In lesson 3.4's live run" points at the lesson that actually teaches this SQL.
    """
    errors = []
    for ref in sorted(set(re.findall(r"\blessons? (\d+\.\d+)\b", encounters_text, re.I))):
        if ref not in lessons:
            errors.append(f"encounters.yaml names lesson {ref}, which learning-path.md no longer has")
    for a, b in re.findall(r"\bModules? (\d+)(?: and (\d+))?\b", encounters_text):
        for ref in filter(None, (a, b)):
            if ref not in modules:
                errors.append(f"encounters.yaml names Module {ref}, which learning-path.md no longer has")
    for e in doc.get("encounters") or []:
        cid, lesson = e.get("case"), str(e.get("lesson") or "")
        if not lesson:
            errors.append(f"{cid}: missing lesson (the learning-path.md lesson it comes from)")
        elif lesson not in lessons:
            errors.append(f"{cid}: lesson {lesson} is not in learning-path.md")
        elif cid not in lessons[lesson]:
            errors.append(f"{cid}: lesson {lesson}'s Guarded by line does not list {cid}")
    return errors


def font_faces(font_dir: pathlib.Path = FONT_DIR) -> str:
    """@font-face rules with each font inlined as a data: URI, so the page loads nothing."""
    rules = []
    for family, weight, name in FONTS:
        b64 = base64.b64encode((font_dir / name).read_bytes()).decode("ascii")
        rules.append(f'@font-face {{ font-family: "{family}"; font-style: normal; font-weight: {weight}; '
                     f'font-display: swap; src: url(data:font/woff2;base64,{b64}) format("woff2"); }}')
    return "\n".join(rules)


def render(template: str, data: dict, fonts_css: str = "") -> str:
    if template.count(PLACEHOLDER) != 1:
        raise ValueError(f"game.html must contain {PLACEHOLDER} exactly once")
    if template.count(FONT_PLACEHOLDER) != 1:
        raise ValueError(f"game.html must contain {FONT_PLACEHOLDER} exactly once")
    # The JSON sits in a <script type="application/json">. Escaping every <, > and & keeps any
    # string from closing the element or opening a "<!--<script" state in the HTML parser.
    payload = (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
               .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))
    return template.replace(PLACEHOLDER, payload).replace(FONT_PLACEHOLDER, fonts_css)


def build(check: bool = False) -> tuple[str | None, dict, list[str]]:
    """Validate, and unless `check`, render. Returns (html or None, data, errors)."""
    date, cases = parse_lesson_sql(LESSON_SQL.read_text(encoding="utf-8"))
    raw = ENCOUNTERS.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw) or {}
    data, errors = compile_quest(doc, date, cases)
    errors += check_course_refs(raw, doc, *parse_learning_path(LEARNING_PATH.read_text(encoding="utf-8")))
    if errors:
        return None, data, errors
    fonts = font_faces()  # read even under --check, so a missing font file fails pre-commit too
    html = None if check else render(TEMPLATE.read_text(encoding="utf-8"), data, fonts)
    return html, data, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output HTML (default: tools/agentql-quest/dist/index.html)")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    ap.add_argument("--root", help="accepted for parity with the other validators; paths resolve from this script")
    args = ap.parse_args(argv)

    html, data, errors = build(check=args.check)
    if errors:
        print("agentql-quest: encounters.yaml no longer matches lesson-sql.md:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    n_points = sum(len(e["points"]) for e in data["encounters"])
    summary = f"{len(data['encounters'])} encounters, {n_points} points, {len(data['court'])} court claims"
    if args.check:
        print(f"agentql-quest: OK ({summary})")
        return 0
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"agentql-quest: wrote {out} ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
