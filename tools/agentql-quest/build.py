#!/usr/bin/env python3
"""Build AgentQL Quest, the browser game for the Learn AgentQL course.

Joins two sources into the game's data, `quest.json`, and one self-contained `index.html`:

  - `references/lesson-sql.md` of the ts-object-model-agentql-query skill: the AgentQL and
    the warehouse SQL ThoughtSpot generated for each lesson, captured live and committed.
    It is the only source of SQL; the game never carries a hand-written copy.
  - `encounters.yaml` (next to this script): which parts of that SQL the game asks about,
    who put each one there, and the text the player reads.

The data and the fonts are written into the page rather than shipped beside it, so the file
makes no outside requests and runs from GitHub Pages, any static host, or a double-click. The same
data is also written beside the page as `quest.json`, the contract `quest.schema.json` describes,
so another front end can play the same checked content without parsing the YAML or the capture.

    python3 tools/agentql-quest/build.py                   # write tools/agentql-quest/dist/
    python3 tools/agentql-quest/build.py --out _site/index.html   # quest.json and its schema land beside it
    python3 tools/agentql-quest/build.py --check           # validate only (tools/validate/check_agentql_quest.py)

Fails when an encounter no longer matches the capture or the course: a lesson or Module the
text names that the course no longer has, a missing or rejected case, AgentQL that differs by
more than layout, an `sql` line that is no longer in the SQL exactly, an `sql_count` that no
longer holds, or a capture header that names a different Model from the one the AgentQL queries;
or when the data no longer fits `quest.schema.json`. A recapture that changes what a lesson
teaches therefore breaks the build instead of quietly teaching something false.
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
SCHEMA = HERE / "quest.schema.json"
SCHEMA_VERSION = 1
BESIDE = ("quest.json", "quest.schema.json")  # written next to the page, so --out may not name them
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

WHO_ANSWERS = {"model": "forge", "thoughtspot": "forge", "agentql": "agentql"}
WHO_ORDER = ("forge", "agentql", "ai")
RULE_BY = ("model", "thoughtspot", "agentql", "determinism")
ALL = "*"
_STRING = re.compile(r"""('(?:[^']|'')*'|"(?:[^"]|"")*")""")    # string literals and quoted names


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


def parse_capture_model(text: str) -> str | None:
    """The Model the capture was taken on, from the header's "captured live on the sample Model **`…`**"."""
    m = re.search(r"captured\s+live\s+on\s+the\s+sample\s+Model\s+\*\*`([^`]+)`\*\*", text)
    return m.group(1).strip() if m else None


def _norm(sql: str) -> str:
    """Normalise layout only: line breaks and indentation may differ, nothing else.

    Outside string literals, runs of whitespace collapse to one space, and whitespace is
    dropped just inside brackets and before commas — the places a reader adds line breaks.
    `(Sample) Retail` and `(Sample)Retail`, or `a, b` and `a,b`, stay different. String
    literals and double-quoted names are kept byte for byte.
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


def _point(p: dict, who: dict, sql: list[str], scroll: list[str], cases: dict[str, dict],
           where: str, errors: list[str]) -> dict:
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
    stripped = [line.strip() for line in sql if line.strip()]
    last = p.get("sql_last_line")
    if last and (not stripped or stripped[-1] != last.strip()):
        errors.append(f"{where}: expected the statement to end with {last!r}, it ends with {stripped[-1] if stripped else None!r}")
    for before, after in p.get("sql_before") or []:
        ia = next((i for i, l in enumerate(stripped) if l == before.strip()), None)
        ib = next((i for i, l in enumerate(stripped) if l == after.strip()), None)
        if ia is None or ib is None or ia >= ib:
            errors.append(f"{where}: expected {before!r} before {after!r} in the SQL")
    # "Could the AI write X?" — only true while the capture still shows X being rejected.
    rejected = p.get("rejected_case")
    if rejected:
        cap = cases.get(rejected)
        if cap is None:
            errors.append(f"{where}: rejected_case {rejected!r} is not in lesson-sql.md")
        elif cap["sql"] is not None:
            errors.append(f"{where}: rejected_case {rejected!r} now compiles (SUCCESS), so the answer is wrong")
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


def _path(path: dict, engines: dict, where: str, errors: list[str]) -> dict:
    """The quest's first question: which engine fits the merchant's intent?

    The dragon is the AgentQL path, so AgentQL must be the answer. Every other engine either
    explains why it doesn't fit (`why`) or is closed in this realm (`blocked`), which costs no
    gold: the player simply chooses again.
    """
    order = list(engines)
    answer, blocked, why = path.get("answer"), path.get("blocked") or {}, path.get("why") or {}
    if answer != "agentql":
        errors.append(f"{where}: the dragon is the AgentQL path, so path.answer must be 'agentql', got {answer!r}")
    if answer in blocked:
        errors.append(f"{where}: the right path can't be blocked")
    outcomes = []
    for k in order:
        text = blocked.get(k) if k in blocked else why.get(k)
        if not text:
            errors.append(f"{where}: path needs a why (or blocked) text for {k}")
        outcomes.append({"kind": "blocked" if k in blocked else "win" if k == answer else "loss", "why": text or ""})
    for k in list(blocked) + list(why):
        if k not in engines:
            errors.append(f"{where}: unknown engine {k!r} in path")
    return {"options": [f"Send it to {engines[k]}" for k in order], "outcomes": outcomes,
            "correct": order.index(answer) if answer in order else 0}


def _encounter(e: dict, n: int, who: dict, engines: dict, cases: dict[str, dict], errors: list[str]) -> dict | None:
    cid = e.get("case", f"#{n}")
    cap = cases.get(cid)
    if cap is None:
        errors.append(f"{cid}: not in lesson-sql.md")
        return None
    if cap["sql"] is None:
        errors.append(f"{cid}: captured status was not SUCCESS, so there is no SQL to fight")
        return None
    agentql = (e.get("agentql") or "").rstrip("\n")
    if _norm(agentql) != _norm(cap["agentql"]):
        errors.append(f"{cid}: agentql differs from the captured AgentQL (only layout may differ)")
    sql_lines, scroll_lines = cap["sql"].splitlines(), agentql.splitlines()
    points = [_point(p, who, sql_lines, scroll_lines, cases, f"{cid} point {i}", errors)
              for i, p in enumerate(e.get("points") or [], 1)]
    if not points:
        errors.append(f"{cid}: no points")
    for field in ("quest", "path", "takeaway"):
        if not e.get(field):
            errors.append(f"{cid}: missing {field}")
    for i, (raw, pt) in enumerate(zip(e.get("points") or [], points), 1):
        if raw.get("kind") == "who" and not raw.get("rule"):
            errors.append(f"{cid} point {i}: a who point needs a rule (the hoard lists it)")
        # The hoard tags each rule with who adds it; a who point's answer already says so.
        by = raw.get("rule_by") or (raw.get("answer") if raw.get("kind") == "who" else None)
        if raw.get("rule") and by not in RULE_BY:
            errors.append(f"{cid} point {i}: rule_by must be one of {list(RULE_BY)}, got {by!r}")
        pt["rule"], pt["ruleBy"] = raw.get("rule", ""), by or ""
    return {"case": cid, "lesson": str(e.get("lesson") or ""), "quest": e.get("quest", ""),
            "path": _path(e.get("path") or {}, engines, f"{cid} path", errors),
            "agentql": scroll_lines, "sql": sql_lines, "points": points, "takeaway": e.get("takeaway", "")}


def _trial(t: dict, engines: dict, where: str, errors: list[str]) -> dict:
    kind = t.get("kind")
    if kind == "claim":
        if not t.get("claim") or not t.get("why") or not isinstance(t.get("truth"), bool):
            errors.append(f"{where}: a claim needs claim, why and a true/false truth")
        return {"kind": "claim", "text": t.get("claim", ""), "why": t.get("why", ""),
                "options": ["Heed them. It is true.", "Banish them. It is false."],
                "correct": 0 if t.get("truth") is True else 1}
    if kind == "route":
        order = list(engines)
        if t.get("answer") not in engines:
            errors.append(f"{where}: answer must be one of {order}, got {t.get('answer')!r}")
        if not t.get("petition") or not t.get("why"):
            errors.append(f"{where}: a route needs petition and why")
        return {"kind": "route", "text": t.get("petition", ""), "why": t.get("why", ""),
                "options": [f"Send it to {engines[k]}" for k in order],
                "correct": order.index(t["answer"]) if t.get("answer") in engines else 0}
    errors.append(f"{where}: kind must be 'claim' or 'route', got {kind!r}")
    return {"kind": kind, "text": "", "why": "", "options": [], "correct": 0}


def _halls(r: dict, engines: dict, rid: str, errors: list[str]) -> list[dict]:
    """Law teaches one idea per hall, with just the slice of the comparison table it needs,
    then tests it straight away. The full table (`scroll`) is the recap at the end."""
    scroll = r.get("scroll") or {}
    columns = scroll.get("columns") or []
    rows = {row.get("label"): row.get("cells") or [] for row in scroll.get("rows") or []}
    for label, cells in rows.items():
        if len(cells) != len(columns):
            errors.append(f"realm {rid}: scroll row {label!r} has {len(cells)} cells for {len(columns)} "
                          f"columns (an unquoted comma in YAML splits a cell)")
    halls, taught = [], set()
    for n, h in enumerate(r.get("halls") or [], 1):
        where = f"realm {rid} hall {n}"
        cols = h.get("columns") or []
        bad_cols = [c for c in cols if c not in columns]
        bad_rows = [x for x in h.get("rows") or [] if x not in rows]
        if bad_cols or bad_rows:
            errors.append(f"{where}: unknown scroll columns {bad_cols} or rows {bad_rows}")
        if not h.get("title") or not h.get("teach"):
            errors.append(f"{where}: needs a title and something to teach")
        trials = [_trial(t, engines, f"{where} trial {i}", errors) for i, t in enumerate(h.get("trials") or [], 1)]
        if not trials:
            errors.append(f"{where}: needs at least one question")
        idx = [columns.index(c) for c in cols if c in columns]
        table = [{"label": x, "cells": [rows[x][i] for i in idx if i < len(rows[x])]} for x in h.get("rows") or [] if x in rows]
        taught.update(x for x in h.get("rows") or [])
        halls.append({"title": h.get("title", ""), "teach": h.get("teach") or [], "columns": cols,
                      "rows": table, "trials": trials})
    for label in rows:
        if halls and label not in taught:
            errors.append(f"realm {rid}: scroll row {label!r} is in the recap but no hall teaches it")
    return halls


def compile_quest(doc: dict, date: str | None, cases: dict[str, dict],
                  model: str | None) -> tuple[dict, list[str]]:
    """Turn encounters.yaml plus the capture into the game's data. Returns (data, errors).

    `model` is the Model the capture's header names (see parse_capture_model)."""
    errors: list[str] = []
    model = (model or "").strip()
    if not model:
        errors.append("lesson-sql.md: no Model named in its header")
    who = doc.get("who_options") or {}
    missing = [k for k in WHO_ORDER if not who.get(k)]
    if missing:
        errors.append(f"who_options: missing {missing}")
    engines = doc.get("engines") or {}
    if len(engines) < 2:
        errors.append("engines: need at least two engines for petitions")
    if not date:
        errors.append("lesson-sql.md: no capture date found in its header")

    by_case: dict[str, dict] = {}
    for n, e in enumerate(doc.get("encounters") or [], 1):
        built = _encounter(e, n, who, engines, cases, errors)
        if built:
            by_case[built["case"]] = built
            # The dragon's caption names the header's Model: it must be the one this AgentQL queries.
            if model and not re.search(rf'\bFROM\s+"{re.escape(model)}"', cases[built["case"]]["agentql"], re.I):
                errors.append(f"{built['case']}: the capture header names Model {model!r}, "
                              f"but this AgentQL does not query FROM \"{model}\"")

    realms, used, ids = [], set(), set()
    for r in doc.get("realms") or []:
        rid = r.get("id") or "?"
        if rid in ids:
            errors.append(f"realm {rid}: duplicate id")
        ids.add(rid)
        for field in ("name", "covers", "depth", "minutes"):
            if not r.get(field):
                errors.append(f"realm {rid}: missing {field}")
        for field in ("module", "minutes"):  # whole numbers, never 4.0: strict decoders reject a float
            if not isinstance(r.get(field), int) or isinstance(r.get(field), bool):
                errors.append(f"realm {rid}: {field} must be a whole number")
        halls = _halls(r, engines, rid, errors)
        trials = [t for h in halls for t in h["trials"]]
        enc_ids = list(r.get("encounters") or [])
        for cid in enc_ids:
            if cid not in by_case and not any(e.get("case") == cid for e in doc.get("encounters") or []):
                errors.append(f"realm {rid}: encounter {cid!r} is not defined under encounters")
            elif cid in used:
                errors.append(f"realm {rid}: encounter {cid!r} is already in another realm")
            used.add(cid)
        sealed = bool(r.get("sealed"))
        if sealed and (trials or enc_ids):
            errors.append(f"realm {rid}: a sealed realm has no trials or encounters")
        if not sealed and not (trials or enc_ids):
            errors.append(f"realm {rid}: an open realm needs trials or encounters (or sealed: true)")
        if halls and not r.get("decree"):
            errors.append(f"realm {rid}: a realm of halls needs a decree")
        realms.append({
            "id": rid, "name": r.get("name", ""), "module": r.get("module"), "depth": r.get("depth", ""),
            "minutes": r.get("minutes", 0), "covers": r.get("covers", ""), "sealed": sealed,
            "scroll": r.get("scroll"), "halls": halls, "decree": r.get("decree") or [],
            "encounters": [by_case[c] for c in enc_ids if c in by_case],
        })
    if not realms:
        errors.append("realms: none defined")
    elif realms[0]["sealed"] or not realms[0]["halls"]:
        errors.append("realms: the first realm is where every player starts; it must be open with halls")
    for cid in by_case:
        if cid not in used:
            errors.append(f"{cid}: defined under encounters but in no realm")

    routes = []
    for rt in doc.get("routes") or []:
        bad = [x for x in rt.get("path") or [] if x not in ids]
        if bad or not rt.get("who") or not rt.get("path"):
            errors.append(f"route {rt.get('who')!r}: needs who and a path of realm ids (unknown: {bad})")
        routes.append({"who": rt.get("who", ""), "path": rt.get("path") or []})

    return {"schema_version": SCHEMA_VERSION, "captured": date, "model": model,
            "realms": realms, "routes": routes}, errors


# The JSON Schema keywords quest.schema.json may use. Pre-commit needs no extra package for this;
# CI also validates the published pair with the real jsonschema (see the README). lint_schema
# checks the schema first, whole, and accepts only a strict form of 2020-12 that _check enforces
# exactly; the README lists what it refuses.
_SCHEMA_NOTES = {"$schema", "$id", "title", "description", "$defs"}
_SCHEMA_RULES = {"type", "enum", "required", "properties", "additionalProperties", "items",
                 "minItems", "anyOf", "$ref"}
_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_DEF_NAME = re.compile(r"[A-Za-z0-9_]+")  # nothing JSON Pointer (~ /) or a URI (%) would decode
_JSON_TYPES = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool,
               "null": type(None)}


def lint_schema(node, root: dict, where: str = "#") -> list[str]:
    """Problems with the schema itself: anything check_schema could not enforce exactly."""
    def bad(msg: str) -> list[str]:
        return [f"quest.schema.json {where}: {msg}"]
    if not isinstance(node, dict):
        return bad("every schema must be an object (boolean schemas are not supported)")
    unknown = set(node) - _SCHEMA_NOTES - _SCHEMA_RULES
    if unknown:
        return bad(f"uses {sorted(unknown)}, which check_schema does not support")
    errors: list[str] = []
    for k in ("title", "description"):  # the metaschema types these too
        if k in node and not isinstance(node[k], str):
            errors += bad(f"{k} must be a string")
    if node is root and node.get("$schema", _DIALECT) != _DIALECT:
        errors += bad(f"$schema must be {_DIALECT!r}, the dialect check_schema follows")
    if node is root and "$id" in node and not (isinstance(node["$id"], str) and re.fullmatch(r"[^#]*#?", node["$id"])):
        errors += bad("$id must be a URI without a fragment")
    if node is not root and {"$id", "$schema", "$defs"} & node.keys():
        # $ref always resolves against the root's $defs, so nothing below may start a new scope.
        errors += bad("$id, $schema and $defs are supported only at the root")
    t = node.get("type")
    if "type" in node and (not isinstance(t, str) or t not in _JSON_TYPES):
        errors += bad(f"type {t!r} is not supported (one of {sorted(_JSON_TYPES)})")
    if "additionalProperties" in node and node["additionalProperties"] is not False:
        errors += bad("only additionalProperties: false is supported")
    if t == "object" or {"properties", "required", "additionalProperties"} & node.keys():
        # A front end relies on the shape: every field present, nothing unlisted. _check applies
        # required and additionalProperties only beside properties, so none may appear alone.
        if t != "object" or "properties" not in node or node.get("additionalProperties") is not False:
            errors += bad("an object needs type: object, properties and additionalProperties: false")
        if not isinstance(node.get("properties", {}), dict) or not isinstance(node.get("required", []), list) \
                or not all(isinstance(k, str) for k in node.get("required", [])):
            return errors + bad("properties must be an object and required a list of names")
        if set(node.get("required", [])) != set(node.get("properties", {})):
            errors += bad("every property must be required")
        if len(set(node.get("required", []))) != len(node.get("required", [])):
            errors += bad("required lists a name twice")
    if "enum" in node and not isinstance(node["enum"], list):
        errors += bad("enum must be a list")
    if "minItems" in node and (not isinstance(node["minItems"], int) or isinstance(node["minItems"], bool)
                               or node["minItems"] < 0):
        errors += bad("minItems must be an integer, 0 or more")
    if "$ref" in node:
        ref, seen = node["$ref"], set()
        defs = root.get("$defs") if isinstance(root.get("$defs"), dict) else {}
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref[8:] not in defs:
            errors += bad(f"unknown $ref {ref!r}")
        else:
            # A chain of $refs that comes back to itself never reaches a rule (and never ends).
            while isinstance(ref, str) and ref.startswith("#/$defs/") and ref[8:] in defs and ref not in seen:
                seen.add(ref)
                ref = defs[ref[8:]].get("$ref") if isinstance(defs[ref[8:]], dict) else None
            if ref in seen:
                errors += bad(f"$ref {node['$ref']!r} refers back to itself")
    for k, sub in (node.get("properties") or {}).items():
        errors += lint_schema(sub, root, f"{where}/properties/{k}")
    if "items" in node:
        errors += lint_schema(node["items"], root, f"{where}/items")
    if "anyOf" in node and not (isinstance(node["anyOf"], list) and node["anyOf"]):
        return errors + bad("anyOf must be a non-empty list")
    for i, sub in enumerate(node.get("anyOf") or []):
        errors += lint_schema(sub, root, f"{where}/anyOf/{i}")
    if node is root:
        if not isinstance(node.get("$defs", {}), dict):
            return errors + bad("$defs must be an object")
        for k, sub in (node.get("$defs") or {}).items():
            if not _DEF_NAME.fullmatch(k):
                errors += bad(f"definition name {k!r}: use letters, digits and _ only")
            errors += lint_schema(sub, root, f"#/$defs/{k}")
            if _rechecks_itself(sub, node["$defs"], (f"#/$defs/{k}",)):
                errors += bad(f"#/$defs/{k} reaches itself through $ref/anyOf without reading any deeper")
    return errors


def _rechecks_itself(node, defs: dict, stack: tuple) -> bool:
    """True if checking `node` leads back to a definition on `stack` while still checking the same
    value: through $ref and anyOf only (properties and items always move to a smaller value)."""
    if not isinstance(node, dict):
        return False
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/") and ref[8:] in defs:
        if ref in stack or _rechecks_itself(defs[ref[8:]], defs, stack + (ref,)):
            return True
    return any(_rechecks_itself(b, defs, stack) for b in node.get("anyOf") or [] if isinstance(node.get("anyOf"), list))


def _same(a, b) -> bool:
    """JSON equality: true and false are not 1 and 0, as they are to Python's ==."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    return a == b


def _is_type(value, name: str) -> bool:
    if isinstance(value, bool):
        return name == "boolean"
    if name == "integer":  # 2020-12: 1.0 is an integer
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    return isinstance(value, _JSON_TYPES[name])


def check_schema(value, schema: dict) -> list[str]:
    """Check `value` against quest.schema.json's subset of JSON Schema 2020-12."""
    problems = lint_schema(schema, schema)
    return problems or _check(value, schema, schema, "quest")


def _check(value, schema: dict, root: dict, where: str) -> list[str]:
    errors: list[str] = []
    if "$ref" in schema:  # 2020-12: $ref applies alongside its siblings, it doesn't replace them
        errors += _check(value, root["$defs"][schema["$ref"][8:]], root, where)
    if "anyOf" in schema:
        branches = [_check(value, s, root, where) for s in schema["anyOf"]]
        if all(branches):
            errors.append(f"{where}: matches none of its allowed shapes ({'; or '.join(b[0] for b in branches)})")
    if "type" in schema and not _is_type(value, schema["type"]):
        return errors + [f"{where}: expected {schema['type']}, got {type(value).__name__}"]
    if "enum" in schema and not any(_same(value, e) for e in schema["enum"]):
        errors.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, dict) and "properties" in schema:
        props = schema["properties"]
        errors += [f"{where}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        errors += [f"{where}: {k!r} is not in quest.schema.json" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                errors += _check(v, props[k], root, f"{where}.{k}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{where}: needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for i, v in enumerate(value):
                errors += _check(v, schema["items"], root, f"{where}[{i}]")
    return errors


def parse_learning_path(text: str) -> tuple[set[str], dict[str, set[str]], dict[str, str]]:
    """Module numbers; per lesson number ("3.4") the case ids its **Guarded by** line names; and
    per lesson number its heading title."""
    modules = set(re.findall(r"^## Module (\d+)\b", text, re.M))
    lessons: dict[str, set[str]] = {}
    titles: dict[str, str] = {}
    for m in re.finditer(r"^### (\d+\.\d+)\b([^\n]*)(.*?)(?=^##)", text + "\n##", re.S | re.M):
        guarded = re.findall(r"\*\*Guarded by:?\*\*:?([^\n]*)", m.group(3))
        lessons[m.group(1)] = {cid for line in guarded for cid in re.findall(r"`([^`]+)`", line)}
        titles[m.group(1)] = m.group(2).strip()
    return modules, lessons, titles


def check_course_refs(encounters_text: str, doc: dict, modules: set[str], lessons: dict[str, set[str]],
                      titles: dict[str, str] | None = None) -> list[str]:
    """The game's text names lessons and modules by number; the course renumbers them.

    Every "lesson X.Y" / "Module N" (or "Modules N and M") in encounters.yaml must still exist,
    and each encounter's `lesson` must be one whose Guarded by line lists the encounter's case,
    so "In lesson 3.4's live run" points at the lesson that actually teaches this SQL.
    """
    errors = []
    expect = doc.get("lesson_titles") or {}
    named = set(re.findall(r"\blessons? (\d+\.\d+)\b", encounters_text, re.I))
    named |= {str(e.get("lesson")) for e in doc.get("encounters") or [] if e.get("lesson")}
    for ref in sorted(named):
        if ref not in lessons:
            errors.append(f"encounters.yaml names lesson {ref}, which learning-path.md no longer has")
        elif titles is not None:
            # A renumbered or retitled course can leave a number pointing at a different lesson.
            want = expect.get(ref)
            if not want:
                errors.append(f"lesson {ref} is named but has no entry in lesson_titles")
            elif want.lower() not in titles.get(ref, "").lower():
                errors.append(f"lesson {ref} is now {titles.get(ref)!r}, not the lesson about {want!r}")
    for a, b in re.findall(r"\bModules? (\d+)(?: and (\d+))?\b", encounters_text):
        for ref in filter(None, (a, b)):
            if ref not in modules:
                errors.append(f"encounters.yaml names Module {ref}, which learning-path.md no longer has")
    realm_of = {cid: r for r in doc.get("realms") or [] for cid in r.get("encounters") or []}
    for r in doc.get("realms") or []:
        if str(r.get("module")) not in modules:
            errors.append(f"realm {r.get('id')}: Module {r.get('module')} is not in learning-path.md")
    for e in doc.get("encounters") or []:
        cid, lesson = e.get("case"), str(e.get("lesson") or "")
        realm = realm_of.get(cid)
        if realm and lesson and lesson.split(".")[0] != str(realm.get("module")):
            errors.append(f"{cid}: lesson {lesson} is not in Module {realm.get('module')}, its realm's module")
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


def _not_json(name: str):
    raise ValueError(f"quest.schema.json: {name} is not JSON (JSON.parse and strict parsers reject it)")


def build(check: bool = False) -> tuple[str | None, dict, list[str]]:
    """Validate, and unless `check`, render. Returns (html or None, data, errors)."""
    capture = LESSON_SQL.read_text(encoding="utf-8")
    date, cases = parse_lesson_sql(capture)
    model = parse_capture_model(capture)
    raw = ENCOUNTERS.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw) or {}
    data, errors = compile_quest(doc, date, cases, model)
    errors += check_course_refs(raw, doc, *parse_learning_path(LEARNING_PATH.read_text(encoding="utf-8")))  # modules, lessons, titles
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"), parse_constant=_not_json)
    except ValueError as e:  # includes JSONDecodeError
        errors.append(str(e) if str(e).startswith("quest.schema.json") else f"quest.schema.json: not valid JSON ({e})")
    else:
        errors += check_schema(data, schema)
    if errors:
        return None, data, errors
    fonts = font_faces()  # read even under --check, so a missing font file fails pre-commit too
    html = None if check else render(TEMPLATE.read_text(encoding="utf-8"), data, fonts)
    return html, data, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output HTML (default: tools/agentql-quest/dist/index.html); "
                         "quest.json and quest.schema.json are written beside it")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    ap.add_argument("--root", help="accepted for parity with the other validators; paths resolve from this script")
    args = ap.parse_args(argv)

    if pathlib.Path(args.out).name.casefold() in BESIDE:  # case-insensitive filesystems
        print(f"agentql-quest: --out names the page; {pathlib.Path(args.out).name} is written beside it", file=sys.stderr)
        return 2
    html, data, errors = build(check=args.check)
    if errors:
        print("agentql-quest: encounters.yaml no longer matches lesson-sql.md, the course or quest.schema.json:",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    open_realms = [r for r in data["realms"] if not r["sealed"]]
    encs = [e for r in data["realms"] for e in r["encounters"]]
    summary = (f"{len(open_realms)}/{len(data['realms'])} realms open, {len(encs)} dragons, "
               f"{sum(len(e['points']) for e in encs)} scales, "
               f"{sum(len(h['trials']) for r in data['realms'] for h in r['halls'])} hall questions")
    if args.check:
        print(f"agentql-quest: OK ({summary})")
        return 0
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    out.with_name("quest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.with_name("quest.schema.json").write_text(SCHEMA.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"agentql-quest: wrote {out}, quest.json and quest.schema.json ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
